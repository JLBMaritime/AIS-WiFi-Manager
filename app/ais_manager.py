"""AIS Manager.

Reads NMEA sentences from the AIS receiver on a serial port and forwards
each sentence to every enabled endpoint over a persistent TCP connection.

Improvements vs. the original
-----------------------------
* **`reload_endpoints()`** — formerly the API restarted the entire service
  (and therefore re-opened the serial port and dropped two seconds of data)
  every time someone toggled an endpoint.  Now it just *diffs* the wanted
  vs. running connection set and adjusts in place.
* **NMEA checksum filter** — sentences with a bad ``*HH`` checksum are
  dropped and counted, never forwarded.
* **Bounded log buffer** — ``collections.deque(maxlen=N)`` instead of a
  list slice.
* **Configurable baud-rate** — ``[AIS] baud_rate`` (default 38400) so
  receivers other than dAISy work.
* **No module-level `logging.basicConfig`** — only the entry point should
  configure logging, otherwise systemd ends up with two handlers.
* **Distinguishes "device gone" from transient errors** — if
  ``/dev/serial0`` doesn't exist we wait *and* log clearly, instead of
  spinning silently forever.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from collections import deque
from datetime import datetime
from typing import Optional

import serial

from app.ais_config_manager import load_ais_config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NMEA helpers
# ---------------------------------------------------------------------------
def _nmea_checksum(text: str) -> str:
    cs = 0
    for ch in text:
        cs ^= ord(ch)
    return f"{cs:02X}"


def _tag_block(source_id: str) -> bytes:
    if not source_id:
        return b""
    body = f"s:{source_id}"
    return f"\\{body}*{_nmea_checksum(body)}\\".encode("ascii")


def _looks_like_valid_nmea(line: bytes) -> bool:
    """True if *line* parses as ``!AIVDM…*HH`` or ``$AIVDO…*HH`` and the
    checksum matches.  Tolerant of CR/LF and tag-blocks."""
    try:
        text = line.decode("ascii", errors="strict").rstrip("\r\n")
    except UnicodeDecodeError:
        return False
    # Strip optional tag-block.
    if text.startswith("\\"):
        end = text.find("\\", 1)
        if end == -1:
            return False
        text = text[end + 1:]
    if not text or text[0] not in "!$":
        return False
    star = text.rfind("*")
    if star < 0 or star + 3 != len(text):
        return False
    body = text[1:star]
    given = text[star + 1:].upper()
    return _nmea_checksum(body) == given


# ---------------------------------------------------------------------------
# Persistent TCP endpoint
# ---------------------------------------------------------------------------
class EndpointConnection:
    """Long-lived TCP sender for a single endpoint.  Thread-safe."""

    def __init__(self, name, host, port,
                 logger_cb=None,
                 connect_timeout=5.0, send_timeout=5.0):
        self.name = name
        self.host = host
        self.port = int(port)
        self.connect_timeout = connect_timeout
        self.send_timeout = send_timeout
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._backoff = 1.0
        self._backoff_max = 30.0
        self._next_retry_at = 0.0
        self._last_state: Optional[bool] = None
        self.logger_cb = logger_cb
        self.last_attempt: Optional[str] = None
        self.last_error: Optional[str] = None
        self.connected = False
        self.sent_count = 0
        self.failed_count = 0

    # -- helpers ---------------------------------------------------------
    def _log(self, level, msg):
        if self.logger_cb:
            try:
                self.logger_cb(level, msg)
            except Exception:  # noqa: BLE001
                pass
        getattr(log, level.lower(), log.info)(msg)

    def _set_state(self, up, err=None):
        self.connected = up
        self.last_error = None if up else err
        self.last_attempt = datetime.now().isoformat()
        if self._last_state != up:
            if up:
                self._log("INFO",
                          f"Endpoint '{self.name}' connected "
                          f"({self.host}:{self.port})")
            else:
                self._log("WARNING",
                          f"Endpoint '{self.name}' down "
                          f"({self.host}:{self.port}): {err or '—'}")
            self._last_state = up

    def _close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _connect(self) -> bool:
        self._close()
        try:
            s = socket.create_connection((self.host, self.port),
                                         timeout=self.connect_timeout)
        except (OSError, socket.gaierror) as exc:
            self.failed_count += 1
            self._set_state(False, str(exc))
            self._next_retry_at = time.time() + self._backoff
            self._backoff = min(self._backoff * 2, self._backoff_max)
            return False
        # Tune socket.
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            for name, val in (("TCP_KEEPIDLE", 60),
                              ("TCP_KEEPINTVL", 20),
                              ("TCP_KEEPCNT", 5)):
                opt = getattr(socket, name, None)
                if opt is not None:
                    try:
                        s.setsockopt(socket.IPPROTO_TCP, opt, val)
                    except OSError:
                        pass
        except OSError:
            pass
        s.settimeout(self.send_timeout)
        self._sock = s
        self._backoff = 1.0
        self._next_retry_at = 0.0
        self._set_state(True)
        return True

    # -- API -------------------------------------------------------------
    def send(self, data: bytes) -> bool:
        with self._lock:
            if self._sock is None:
                if time.time() < self._next_retry_at:
                    return False
                if not self._connect():
                    return False
            try:
                self._sock.sendall(data)
                self.sent_count += 1
                self.connected = True
                return True
            except OSError as exc:
                self.failed_count += 1
                self._set_state(False, str(exc))
                self._close()
                self._next_retry_at = time.time() + self._backoff
                self._backoff = min(self._backoff * 2, self._backoff_max)
                return False

    def close(self):
        with self._lock:
            self._close()
            self._set_state(False, "closed")


# ---------------------------------------------------------------------------
# AIS Manager
# ---------------------------------------------------------------------------
class AISManager:
    def __init__(self):
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.serial_port = "/dev/serial0"
        self.baud_rate = 38400
        self.node_id = ""
        self.endpoints: list[dict] = []
        self.connections: dict[str, EndpointConnection] = {}
        self.endpoint_status: dict[str, dict] = {}
        self.logs: deque[dict] = deque(maxlen=200)
        self.lock = threading.Lock()
        # Stats.
        self.lines_seen = 0
        self.lines_invalid = 0
        self.lines_forwarded = 0

    # ------------------------------------------------------------------
    def load_endpoints(self):
        config = load_ais_config()
        if not config:
            return []
        ais = config.get('AIS', {}) or {}
        self.serial_port = ais.get('serial_port', '/dev/serial0')
        try:
            self.baud_rate = int(ais.get('baud_rate', 38400))
        except (TypeError, ValueError):
            self.baud_rate = 38400
        self.node_id = (ais.get('node_id') or '').strip()

        endpoints = []
        for section, vals in config.items():
            if section.startswith('ENDPOINT_') and vals.get('enabled', 'false').lower() == 'true':
                endpoints.append({
                    'id':      section,
                    'name':    vals.get('name', section),
                    'ip':      vals.get('ip', ''),
                    'port':    int(vals.get('port', 0) or 0),
                    'enabled': True,
                })
        return endpoints

    # ------------------------------------------------------------------
    def _ensure_connections(self):
        wanted = {e['id']: e for e in self.endpoints}
        # Remove stale.
        for eid in list(self.connections):
            if eid not in wanted:
                self.connections[eid].close()
                del self.connections[eid]
        # Create / update.
        for eid, ep in wanted.items():
            existing = self.connections.get(eid)
            if existing and (existing.host != ep['ip']
                             or existing.port != int(ep['port'])):
                existing.close()
                existing = None
            if existing is None:
                self.connections[eid] = EndpointConnection(
                    name=ep['name'],
                    host=ep['ip'],
                    port=int(ep['port']),
                    logger_cb=self.add_log,
                )
        self._refresh_status_mirror()

    def _refresh_status_mirror(self):
        self.endpoint_status = {
            eid: {
                'connected':    c.connected,
                'last_attempt': c.last_attempt,
                'error':        c.last_error,
                'sent':         c.sent_count,
                'failed':       c.failed_count,
            }
            for eid, c in self.connections.items()
        }

    # ------------------------------------------------------------------
    def reload_endpoints(self):
        """Re-read config and adjust live connections in place — no
        forwarding pause, no serial-port reopen."""
        with self.lock:
            self.endpoints = self.load_endpoints()
            self._ensure_connections()
        self.add_log("INFO",
                     f"Endpoint config reloaded ({len(self.endpoints)} active)")
        return True, "Endpoints reloaded"

    # ------------------------------------------------------------------
    def start(self):
        if self.running:
            self.add_log("INFO", "AIS service is already running")
            return False, "Service already running"
        self.running = True
        self.endpoints = self.load_endpoints()
        self._ensure_connections()
        self.thread = threading.Thread(target=self._run_ais_forwarding,
                                       daemon=True, name="ais-forwarder")
        self.thread.start()
        self.add_log("INFO",
                     f"AIS service started with {len(self.endpoints)} endpoint(s)"
                     + (f", node_id='{self.node_id}'" if self.node_id else ""))
        return True, "Service started"

    def stop(self):
        if not self.running:
            return False, "Service not running"
        self.running = False
        for c in self.connections.values():
            c.close()
        if self.thread:
            self.thread.join(timeout=5)
        self.add_log("INFO", "AIS service stopped")
        return True, "Service stopped"

    def restart(self):
        self.stop()
        time.sleep(2)
        return self.start()

    def is_running(self):
        return self.running

    # ------------------------------------------------------------------
    def get_status(self):
        self._refresh_status_mirror()
        return {
            'running':         self.running,
            'serial_port':     self.serial_port,
            'baud_rate':       self.baud_rate,
            'node_id':         self.node_id,
            'endpoints':       self.endpoints,
            'endpoint_status': self.endpoint_status,
            'lines_seen':      self.lines_seen,
            'lines_invalid':   self.lines_invalid,
            'lines_forwarded': self.lines_forwarded,
        }

    def healthy(self) -> bool:
        """For ``/healthz`` — running + thread alive + serial path exists."""
        if not self.running:
            return False
        if not self.thread or not self.thread.is_alive():
            return False
        return os.path.exists(self.serial_port)

    # ------------------------------------------------------------------
    def add_log(self, level, message):
        with self.lock:
            self.logs.append({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'level':     level,
                'message':   message,
            })
        # Also send to stdlib logger so journald gets a copy.
        getattr(log, str(level).lower(), log.info)(message)

    def get_logs(self, count=100):
        with self.lock:
            if count >= len(self.logs):
                return list(self.logs)
            return list(self.logs)[-count:]

    # ------------------------------------------------------------------
    def _build_payload(self, line: bytes) -> bytes:
        if line.endswith(b"\r\n"):
            body = line
        elif line.endswith(b"\n"):
            body = line[:-1] + b"\r\n"
        elif line.endswith(b"\r"):
            body = line + b"\n"
        else:
            body = line + b"\r\n"
        if self.node_id:
            return _tag_block(self.node_id) + body
        return body

    def _broadcast(self, line: bytes) -> None:
        payload = self._build_payload(line)
        for c in self.connections.values():
            c.send(payload)

    # ------------------------------------------------------------------
    def _run_ais_forwarding(self):
        backoff = 5
        while self.running:
            # Distinguish "device totally absent" from "device exists but
            # had a transient error".
            if not os.path.exists(self.serial_port):
                self.add_log("WARNING",
                             f"Serial port {self.serial_port} missing; "
                             f"waiting {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            backoff = 5
            try:
                with serial.Serial(
                    self.serial_port,
                    baudrate=self.baud_rate,
                    timeout=1,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    xonxoff=False, rtscts=False, dsrdtr=False,
                ) as ser:
                    self.add_log("INFO",
                                 f"Connected to AIS serial port "
                                 f"{self.serial_port} @ {self.baud_rate} baud")
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()

                    first_seen = False
                    while self.running:
                        try:
                            line = ser.readline()
                        except serial.SerialException as exc:
                            self.add_log("ERROR", f"Serial read error: {exc}")
                            break
                        except UnicodeDecodeError:
                            continue

                        if not line:
                            continue

                        self.lines_seen += 1
                        # NMEA checksum filter: bad → drop, count, never forward.
                        if not _looks_like_valid_nmea(line):
                            self.lines_invalid += 1
                            continue
                        if not first_seen:
                            preview = line.decode('ascii', errors='ignore').strip()[:60]
                            self.add_log("INFO",
                                         f"Receiving valid AIS data (first: {preview})")
                            first_seen = True

                        try:
                            self._broadcast(line)
                            self.lines_forwarded += 1
                        except Exception as exc:  # noqa: BLE001
                            self.add_log("ERROR", f"Broadcast error: {exc}")

            except serial.SerialException as exc:
                self.add_log("ERROR",
                             f"Failed to open serial port "
                             f"{self.serial_port}: {exc}")
                time.sleep(10)
            except Exception as exc:  # noqa: BLE001
                import traceback
                self.add_log("ERROR", f"Unexpected error in AIS forwarding: {exc}")
                self.add_log("ERROR", f"Traceback: {traceback.format_exc()}")
                time.sleep(10)

        self.add_log("INFO", "AIS forwarding loop ended")


# Global instance (kept for import compatibility).
ais_manager = AISManager()
