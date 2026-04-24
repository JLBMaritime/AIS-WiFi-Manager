"""
AIS Manager Module
------------------
Reads NMEA sentences from the AIS receiver on a serial port and forwards
every sentence to each configured endpoint.

Design
~~~~~~
* **One persistent TCP connection per endpoint**, not one connect-per-line.
  The old behaviour (opening a new socket for every sentence) made the
  AIS-Server think every sentence was a brand-new node and wasted a full
  3-way handshake per line.  We now keep a single long-lived TCP session
  per endpoint with :class:`EndpointConnection`, reconnecting with
  exponential back-off on error.
* An optional ``node_id`` (``[AIS] node_id = MYBOAT``) is prepended to
  every line as a NMEA 4.10 tag-block ``\\s:MYBOAT*HH\\`` so the server
  can identify a node stably across IP changes / Wi-Fi reconnects.
* ``SO_KEEPALIVE`` + ``TCP_NODELAY`` are enabled so dead peers are
  detected within ~2 minutes and every sentence flushes immediately.
"""
import logging
import socket
import threading
import time
from datetime import datetime
from typing import Optional

import serial

from app.ais_config_manager import load_ais_config

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")


# ---------------------------------------------------------------------------
# NMEA tag-block helper
# ---------------------------------------------------------------------------
def _nmea_checksum(text: str) -> str:
    """Return the 2-hex-digit XOR checksum of *text* (no leading '*')."""
    cs = 0
    for ch in text:
        cs ^= ord(ch)
    return f"{cs:02X}"


def _tag_block(source_id: str) -> bytes:
    """Build ``\\s:<id>*HH\\`` tag-block bytes, or b'' if *source_id* is empty."""
    if not source_id:
        return b""
    body = f"s:{source_id}"
    return f"\\{body}*{_nmea_checksum(body)}\\".encode("ascii")


# ---------------------------------------------------------------------------
# Endpoint connection (persistent TCP socket with auto-reconnect)
# ---------------------------------------------------------------------------
class EndpointConnection:
    """Long-lived TCP sender for a single endpoint.

    Thread-safe: any number of producer threads may call :meth:`send`
    concurrently.  Reconnects are performed lazily on the caller thread.
    """
    def __init__(self, name: str, host: str, port: int,
                 logger_cb=None, connect_timeout: float = 5.0,
                 send_timeout: float = 5.0) -> None:
        self.name = name
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.send_timeout = send_timeout
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._backoff = 1.0                # seconds
        self._backoff_max = 30.0
        self._next_retry_at = 0.0
        self._last_state: Optional[bool] = None  # for edge-triggered logging
        self.logger_cb = logger_cb         # fn(level, msg) or None
        # Stats
        self.last_attempt: Optional[str] = None
        self.last_error: Optional[str] = None
        self.connected = False
        self.sent_count = 0
        self.failed_count = 0

    # ------------------------------------------------------------------
    def _log(self, level: str, msg: str) -> None:
        if self.logger_cb:
            try:
                self.logger_cb(level, msg)
            except Exception:  # noqa: BLE001
                pass
        if level == "ERROR":
            logging.error(msg)
        elif level == "WARNING":
            logging.warning(msg)
        else:
            logging.info(msg)

    def _set_state(self, up: bool, err: Optional[str] = None) -> None:
        self.connected = up
        self.last_error = None if up else err
        self.last_attempt = datetime.now().isoformat()
        # Only emit a log when the state *changes* so we don't spam for
        # every single line.
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

    def _close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _connect(self) -> bool:
        """Attempt one connect.  Returns True on success."""
        self._close()
        try:
            s = socket.create_connection((self.host, self.port),
                                         timeout=self.connect_timeout)
        except (OSError, socket.gaierror) as e:
            self.failed_count += 1
            self._set_state(False, str(e))
            # Exponential back-off.
            self._next_retry_at = time.time() + self._backoff
            self._backoff = min(self._backoff * 2, self._backoff_max)
            return False
        # Tune keepalive / nagle.
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

    # ------------------------------------------------------------------
    def send(self, data: bytes) -> bool:
        """Send *data* (raw bytes, already CR/LF-terminated) on the
        persistent socket, reconnecting if necessary.
        Returns True on success, False on failure (will retry on next call).
        """
        with self._lock:
            # Respect back-off window.
            if self._sock is None:
                if time.time() < self._next_retry_at:
                    return False
                if not self._connect():
                    return False
            try:
                self._sock.sendall(data)
                self.sent_count += 1
                # Keep state "up" even though we don't re-log.
                self.connected = True
                return True
            except OSError as e:
                self.failed_count += 1
                self._set_state(False, str(e))
                self._close()
                self._next_retry_at = time.time() + self._backoff
                self._backoff = min(self._backoff * 2, self._backoff_max)
                return False

    def close(self) -> None:
        with self._lock:
            self._close()
            self._set_state(False, "closed")


# ---------------------------------------------------------------------------
# AIS Manager
# ---------------------------------------------------------------------------
class AISManager:
    def __init__(self):
        self.running = False
        self.thread = None
        self.serial_port = "/dev/serial0"
        self.node_id = ""
        self.endpoints = []
        self.connections: dict[str, EndpointConnection] = {}
        self.endpoint_status = {}
        self.logs = []
        self.max_logs = 200
        self.lock = threading.Lock()

    # ------------------------------------------------------------------
    def load_endpoints(self):
        """Load endpoints from configuration"""
        config = load_ais_config()
        if not config:
            return []

        endpoints = []
        ais_section = config.get('AIS', {}) or {}
        self.serial_port = ais_section.get('serial_port', '/dev/serial0')
        self.node_id = (ais_section.get('node_id') or '').strip()

        for section in config:
            if section.startswith('ENDPOINT_'):
                ec = config[section]
                if ec.get('enabled', 'false').lower() == 'true':
                    endpoints.append({
                        'id': section,
                        'name': ec.get('name', section),
                        'ip': ec.get('ip', ''),
                        'port': int(ec.get('port', 0)),
                        'enabled': True,
                    })
        return endpoints

    # ------------------------------------------------------------------
    def _ensure_connections(self):
        """Create/refresh EndpointConnection objects to match self.endpoints.
        Safe to call whenever config reloads."""
        wanted = {e['id']: e for e in self.endpoints}
        # Remove stale.
        for eid in list(self.connections):
            if eid not in wanted:
                self.connections[eid].close()
                del self.connections[eid]
        # Create new / update existing.
        for eid, ep in wanted.items():
            existing = self.connections.get(eid)
            if existing and (existing.host != ep['ip']
                             or existing.port != ep['port']):
                existing.close()
                existing = None
            if existing is None:
                self.connections[eid] = EndpointConnection(
                    name=ep['name'], host=ep['ip'], port=int(ep['port']),
                    logger_cb=self.add_log,
                )
        # Keep a simple status mirror (keeps the old /status UI happy).
        self.endpoint_status = {
            eid: {
                'connected': self.connections[eid].connected,
                'last_attempt': self.connections[eid].last_attempt,
                'error': self.connections[eid].last_error,
                'sent': self.connections[eid].sent_count,
                'failed': self.connections[eid].failed_count,
            }
            for eid in self.connections
        }

    # ------------------------------------------------------------------
    def start(self):
        """Start AIS forwarding service"""
        if self.running:
            self.add_log("INFO", "AIS service is already running")
            return False, "Service already running"

        self.running = True
        self.endpoints = self.load_endpoints()
        self._ensure_connections()

        self.thread = threading.Thread(target=self._run_ais_forwarding, daemon=True)
        self.thread.start()
        self.add_log("INFO",
                     f"AIS service started with {len(self.endpoints)} endpoint(s)"
                     + (f", node_id='{self.node_id}'" if self.node_id else ""))
        return True, "Service started"

    def stop(self):
        """Stop AIS forwarding service"""
        if not self.running:
            return False, "Service not running"

        self.running = False
        for conn in self.connections.values():
            conn.close()
        if self.thread:
            self.thread.join(timeout=5)
        self.add_log("INFO", "AIS service stopped")
        return True, "Service stopped"

    def restart(self):
        """Restart AIS forwarding service"""
        self.stop()
        time.sleep(2)
        return self.start()

    def is_running(self):
        return self.running

    # ------------------------------------------------------------------
    def get_status(self):
        # Refresh the mirror so the UI reflects live state.
        self.endpoint_status = {
            eid: {
                'connected': c.connected,
                'last_attempt': c.last_attempt,
                'error': c.last_error,
                'sent': c.sent_count,
                'failed': c.failed_count,
            }
            for eid, c in self.connections.items()
        }
        return {
            'running': self.running,
            'serial_port': self.serial_port,
            'node_id': self.node_id,
            'endpoints': self.endpoints,
            'endpoint_status': self.endpoint_status,
        }

    # ------------------------------------------------------------------
    def add_log(self, level, message):
        """Add log entry (thread-safe)."""
        with self.lock:
            self.logs.append({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'level': level,
                'message': message,
            })
            if len(self.logs) > self.max_logs:
                self.logs = self.logs[-self.max_logs:]

    def get_logs(self, count=100):
        with self.lock:
            return self.logs[-count:]

    # ------------------------------------------------------------------
    def _build_payload(self, line: bytes) -> bytes:
        """Add CR/LF if needed + optional tag-block."""
        # Normalise line ending.
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
        """Send one sentence to every enabled endpoint."""
        payload = self._build_payload(line)
        for conn in self.connections.values():
            conn.send(payload)

    # ------------------------------------------------------------------
    def _run_ais_forwarding(self):
        """Main AIS forwarding loop."""
        self.add_log("INFO", f"Opening serial port {self.serial_port}")

        while self.running:
            try:
                with serial.Serial(
                    self.serial_port,
                    baudrate=38400,
                    timeout=1,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    xonxoff=False, rtscts=False, dsrdtr=False,
                ) as ser:
                    self.add_log("INFO",
                                 f"Connected to AIS serial port: {self.serial_port}")
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()

                    lines_read = 0
                    while self.running:
                        try:
                            line = ser.readline()
                        except serial.SerialException as e:
                            self.add_log("ERROR", f"Serial read error: {e}")
                            break
                        except UnicodeDecodeError:
                            continue

                        if not line:
                            # Timeout – just keep looping; keepalive handles TCP.
                            continue

                        lines_read += 1
                        if lines_read == 1:
                            preview = line.decode('ascii', errors='ignore').strip()[:50]
                            self.add_log("INFO",
                                         f"Receiving AIS data (first sentence: {preview}...)")
                        try:
                            self._broadcast(line)
                        except Exception as e:  # noqa: BLE001
                            self.add_log("ERROR", f"Broadcast error: {e}")

            except serial.SerialException as e:
                self.add_log("ERROR",
                             f"Failed to open serial port {self.serial_port}: {e}")
                time.sleep(10)
            except Exception as e:  # noqa: BLE001
                import traceback
                self.add_log("ERROR",
                             f"Unexpected error in AIS forwarding: {e}")
                self.add_log("ERROR", f"Traceback: {traceback.format_exc()}")
                time.sleep(10)

        self.add_log("INFO", "AIS forwarding loop ended")


# Global AIS manager instance
ais_manager = AISManager()
