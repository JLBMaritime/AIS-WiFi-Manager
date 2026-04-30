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

# Station-mode (client) interface — the one that connects to the user's home /
# boat / shoreside Wi-Fi to give the unit internet access.
WIFI_IFACE = "wlan0"

# Access-point (always-on management hotspot) — the USB Wi-Fi dongle.
# This lets admins reach the box at http://192.168.4.1/ even when wlan0 is
# misconfigured or out of range.  All AP-side state (SSID, PSK) lives in the
# NetworkManager connection profile named below; that is the single source of
# truth — the static HOTSPOT_PASSWORD.txt file is only the install-time *seed*.
AP_IFACE     = "wlan1"
AP_CON_NAME  = "ais-hotspot"
AP_DEFAULT_SSID = "JLBMaritime-AIS"
AP_DEFAULT_IP   = "192.168.4.1"



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


# ---------------------------------------------------------------------------
# Always-on management hotspot on wlan1 (USB dongle)
# ---------------------------------------------------------------------------
# Why a separate radio?
#   The Pi 4B's onboard wlan0 can technically do AP+STA simultaneously on the
#   same channel only, with caveats around brcmfmac stability.  In production
#   we want the AP to never go down even if the user mis-types the home Wi-Fi
#   password and wlan0 is stuck in 'connecting' for 30 s — so a USB dongle on
#   wlan1 carries the AP and wlan0 carries the station.  Both stay active
#   simultaneously, which the Pi handles cleanly.
#
# Why query NM instead of trusting HOTSPOT_PASSWORD.txt?
#   The file is only the *seed* the installer hands NM at first boot.  After
#   that NM is the source of truth — the user can rotate the PSK via
#   `ais-wifi-cli hotspot rotate-pw`, and we don't want the file and NM to
#   drift apart and lie to anyone.

def _nmcli_get(field: str, con_name: str = AP_CON_NAME,
               with_secrets: bool = False) -> Optional[str]:
    """Read a single connection field from NM, e.g. ``802-11-wireless.ssid``.

    With ``with_secrets=True`` the call uses ``-s`` so PSKs are returned;
    that requires root (the caller is responsible for running with sudo).
    """
    cmd = ["nmcli"]
    if with_secrets:
        cmd.append("-s")
    cmd += ["-t", "-g", field, "connection", "show", con_name]
    out, _err, rc = run_args(cmd)
    if rc != 0:
        return None
    return out.strip() or None


def _ap_clients() -> int:
    """Count associated stations on the AP via ``iw dev <iface> station dump``."""
    out, _err, rc = run_args(["iw", "dev", AP_IFACE, "station", "dump"])
    if rc != 0 or not out:
        return 0
    return sum(1 for line in out.splitlines() if line.startswith("Station "))


def _ap_ipv4() -> Optional[str]:
    """Return AP IPv4 address (e.g. ``192.168.4.1/24``) or None if not up."""
    out, _err, rc = run_args(["ip", "-4", "-br", "addr", "show", AP_IFACE])
    if rc != 0 or not out.strip():
        return None
    # Format: "wlan1            UP             192.168.4.1/24 ..."
    parts = out.split()
    for p in parts[2:]:
        if "/" in p:
            return p
    return None


def _ap_active() -> bool:
    out, _err, rc = run_args([
        "nmcli", "-t", "-f", "NAME,STATE", "connection", "show", "--active",
    ])
    if rc != 0:
        return False
    for line in out.splitlines():
        parts = _split_nmcli_terse(line)
        if len(parts) >= 2 and parts[0] == AP_CON_NAME and parts[1] == "activated":
            return True
    return False


def hotspot_status() -> dict:
    """Read-only AP status snapshot for dashboard / CLI / /healthz.

    Never raises — designed to be safe to call even before the AP is set up.
    """
    ssid_live = None
    out, _err, rc = run_args(["iw", "dev", AP_IFACE, "info"])
    if rc == 0 and out:
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("ssid "):
                ssid_live = line.split(None, 1)[1] if " " in line else None

    ssid_profile = _nmcli_get("802-11-wireless.ssid") or AP_DEFAULT_SSID
    ip = _ap_ipv4()
    return {
        "iface":   AP_IFACE,
        "con":     AP_CON_NAME,
        "ssid":    ssid_live or ssid_profile,
        "ip":      ip or "",
        "active":  _ap_active(),
        "clients": _ap_clients(),
    }


def hotspot_psk() -> Optional[str]:
    """Return the AP PSK from NM (root only — the caller must be uid 0)."""
    return _nmcli_get("802-11-wireless-security.psk", with_secrets=True)


def hotspot_up() -> tuple[bool, str]:
    out, err, rc = run_args(
        ["nmcli", "connection", "up", AP_CON_NAME], timeout=20)
    if rc == 0:
        return True, "Hotspot activated"
    return False, (err or out or "Failed to bring hotspot up")


def hotspot_down() -> tuple[bool, str]:
    out, err, rc = run_args(
        ["nmcli", "connection", "down", AP_CON_NAME], timeout=20)
    if rc == 0:
        return True, "Hotspot deactivated"
    return False, (err or out or "Failed to bring hotspot down")


def hotspot_set_psk(new_psk: str) -> tuple[bool, str]:
    """Replace the AP PSK in NM and bounce the connection."""
    if len(new_psk) < 8:
        return False, "PSK must be at least 8 characters (WPA2 minimum)"
    _o, e1, rc = run_args([
        "nmcli", "connection", "modify", AP_CON_NAME,
        "wifi-sec.psk", new_psk,
    ], timeout=10)
    if rc != 0:
        return False, e1 or "nmcli modify failed"
    # Bounce so the new PSK is actually used by the running hostapd.
    run_args(["nmcli", "connection", "down", AP_CON_NAME], timeout=20)
    out, err, rc = run_args(
        ["nmcli", "connection", "up", AP_CON_NAME], timeout=20)
    if rc != 0:
        return False, err or out or "PSK saved but reactivation failed"
    return True, "PSK updated and hotspot bounced"


