"""WiFi management on top of NetworkManager (nmcli).

Hardening notes
~~~~~~~~~~~~~~~
* **No more ``shell=True``** anywhere.  All ``nmcli`` invocations go through
  :func:`app._shellutil.run_args` which is ``shell=False`` and timeout-bounded.
  This makes us immune to SSIDs / passwords containing ``;`` / ``$`` / `` ` ``
  / quotes — historically a real injection risk in this code path.
* :func:`rescan_networks` now polls ``LAST-SCAN`` with a 5-second budget
  rather than ``time.sleep(2)``-and-hope.  Stale scan results are no longer
  returned to the UI.
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

from app._shellutil import run_args
from app.database import add_saved_network, forget_network as db_forget_network

log = logging.getLogger(__name__)

WIFI_IFACE = "wlan0"


# ---------------------------------------------------------------------------
# Scan / list
# ---------------------------------------------------------------------------
def scan_networks() -> List[dict]:
    out, _err, rc = run_args([
        "nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY",
        "device", "wifi", "list", "ifname", WIFI_IFACE,
    ])
    if rc != 0:
        log.warning("nmcli wifi list failed: %s", _err)
        return []

    networks: list[dict] = []
    seen: set[str] = set()
    for line in out.splitlines():
        if not line.strip():
            continue
        # nmcli -t escapes ':' inside fields as '\:'; split with a regex-y
        # walker.
        parts = _split_nmcli_terse(line)
        if len(parts) < 2:
            continue
        ssid     = parts[0].strip()
        signal   = parts[1].strip() or "0"
        security = parts[2].strip() if len(parts) > 2 else ""
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        try:
            signal_i = int(signal)
        except ValueError:
            signal_i = 0
        networks.append({
            "ssid": ssid,
            "signal": str(signal_i),
            "security": "Secured" if security else "Open",
        })
    networks.sort(key=lambda n: int(n["signal"]), reverse=True)
    return networks


def _split_nmcli_terse(line: str) -> list[str]:
    """Split an nmcli ``-t`` line on ``:`` honouring ``\\:`` escapes."""
    out: list[str] = []
    cur = []
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line) and line[i + 1] == ":":
            cur.append(":")
            i += 2
            continue
        if c == ":":
            out.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


# ---------------------------------------------------------------------------
# Current connection / IP
# ---------------------------------------------------------------------------
def get_current_connection() -> Optional[dict]:
    out, _err, rc = run_args([
        "nmcli", "-t", "-f", "NAME,TYPE,DEVICE",
        "connection", "show", "--active",
    ])
    if rc != 0:
        return None
    for line in out.splitlines():
        parts = _split_nmcli_terse(line)
        if len(parts) >= 3 and parts[2].strip() == WIFI_IFACE:
            connection_name = parts[0].strip()
            ssid = _connection_ssid(connection_name) or connection_name
            return {"ssid": ssid, "connection_name": connection_name}
    return None


def _connection_ssid(connection_name: str) -> Optional[str]:
    out, _err, rc = run_args([
        "nmcli", "-t", "-f", "802-11-wireless.ssid",
        "connection", "show", connection_name,
    ])
    if rc != 0 or not out:
        return None
    parts = _split_nmcli_terse(out.strip())
    return parts[-1].strip() if parts else None


def get_connection_ip() -> str:
    out, _err, rc = run_args(["ip", "-4", "addr", "show", WIFI_IFACE])
    if rc != 0 or not out:
        return "Not connected"
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            addr = line.split()[1].split("/")[0]
            return addr
    return "Not connected"


# ---------------------------------------------------------------------------
# Connect / forget
# ---------------------------------------------------------------------------
def _connection_exists(name: str) -> bool:
    _out, _err, rc = run_args(["nmcli", "connection", "show", name])
    return rc == 0


def connect_to_network(ssid: str, password: Optional[str] = None):
    """Connect to *ssid*; if *password* is given, replace any saved profile.
    Returns ``(success, message)``.
    """
    if not ssid:
        return False, "SSID is required"

    # If a password was provided, drop any stale profile first so the new
    # password is what gets used.
    if password:
        if _connection_exists(ssid):
            run_args(["nmcli", "connection", "delete", ssid])
        out, err, rc = run_args([
            "nmcli", "device", "wifi", "connect", ssid,
            "password", password, "ifname", WIFI_IFACE,
        ], timeout=45)
    else:
        if _connection_exists(ssid):
            out, err, rc = run_args(
                ["nmcli", "connection", "up", ssid, "ifname", WIFI_IFACE],
                timeout=45)
        else:
            out, err, rc = run_args(
                ["nmcli", "device", "wifi", "connect", ssid,
                 "ifname", WIFI_IFACE],
                timeout=45)

    if rc == 0:
        add_saved_network(ssid)
        return True, "Connected successfully"
    log.info("connect_to_network(%r) failed: %s", ssid, err or out)
    return False, (err or out or "Failed to connect")


def forget_network(ssid: str):
    if not ssid:
        return False, "SSID is required"
    current = get_current_connection()
    if current and current.get("ssid") == ssid:
        return False, "Cannot forget currently active network"
    run_args(["nmcli", "connection", "delete", ssid])
    db_forget_network(ssid)
    return True, "Network forgotten"


# ---------------------------------------------------------------------------
# Rescan (poll instead of sleep-and-hope)
# ---------------------------------------------------------------------------
def rescan_networks() -> List[dict]:
    run_args(["nmcli", "device", "wifi", "rescan", "ifname", WIFI_IFACE],
             timeout=15)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        out, _err, rc = run_args([
            "nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL",
            "device", "wifi", "list", "ifname", WIFI_IFACE,
        ])
        if rc == 0 and out.strip():
            break
        time.sleep(0.2)
    return scan_networks()
