"""Network diagnostics: ping + interface status + signal/DNS/gateway.

Same hardening as :mod:`app.wifi_manager` — no ``shell=True`` anywhere.
"""
from __future__ import annotations

import logging
import re

from app._shellutil import run_args

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------
def ping_test(host: str = "8.8.8.8", count: int = 4) -> dict:
    if not host or any(c.isspace() for c in host):
        return {"success": False, "host": host, "output": "invalid host"}
    try:
        count = max(1, min(int(count), 20))
    except (TypeError, ValueError):
        count = 4

    out, err, rc = run_args(
        ["ping", "-c", str(count), "-W", "2", host],
        timeout=count * 3 + 5,
    )
    result = {
        "success": rc == 0,
        "host": host,
        "output": out if rc == 0 else (err or out),
    }
    if rc == 0:
        m = re.search(r"(\d+)% packet loss", out)
        if m:
            result["packet_loss"] = m.group(1) + "%"
        m = re.search(r"min/avg/max/(?:mdev|stddev) = "
                      r"([\d.]+)/([\d.]+)/([\d.]+)/[\d.]+ ms", out)
        if m:
            result["min_time"] = m.group(1) + " ms"
            result["avg_time"] = m.group(2) + " ms"
            result["max_time"] = m.group(3) + " ms"
    return result


# ---------------------------------------------------------------------------
# Interfaces
# ---------------------------------------------------------------------------
def _iface_status(name: str) -> dict:
    out, _err, rc = run_args(["ip", "link", "show", name])
    if rc != 0:
        return {"status": "Not found", "exists": False}
    return {
        "status": "UP" if "state UP" in out else "DOWN",
        "exists": True,
    }


def get_interface_status() -> dict:
    return {iface: _iface_status(iface) for iface in ("wlan0", "wlan1")}


# ---------------------------------------------------------------------------
# Connection stats / DNS / gateway
# ---------------------------------------------------------------------------
def get_connection_stats() -> dict:
    stats: dict = {}
    out, _err, rc = run_args([
        "nmcli", "-t", "-f",
        "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS,SIGNAL",
        "device", "show", "wlan0",
    ])
    if rc == 0:
        for line in out.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            value = value.strip()
            if "STATE" in key:
                stats["state"] = value
            elif "CONNECTION" in key:
                stats["connection"] = value
            elif "IP4.ADDRESS" in key:
                stats["ip_address"] = value
    out, _err, rc = run_args(["iwconfig", "wlan0"])
    if rc == 0:
        m = re.search(r"Signal level[=:](-?\d+)", out)
        if m:
            stats["signal_strength"] = m.group(1) + " dBm"
    return stats


def get_gateway() -> str:
    out, _err, rc = run_args(["ip", "route", "show", "default"])
    if rc == 0 and out.strip():
        for line in out.splitlines():
            tok = line.split()
            if "via" in tok:
                return tok[tok.index("via") + 1]
    return "Unknown"


def get_dns_servers() -> list:
    out, _err, rc = run_args([
        "nmcli", "-t", "-f", "IP4.DNS", "device", "show", "wlan0",
    ])
    servers = []
    if rc == 0:
        for line in out.splitlines():
            if "IP4.DNS" in line:
                v = line.partition(":")[2].strip()
                if v:
                    servers.append(v)
    return servers or ["None configured"]


def get_full_diagnostics() -> dict:
    return {
        "interfaces": get_interface_status(),
        "connection_stats": get_connection_stats(),
        "gateway": get_gateway(),
        "dns_servers": get_dns_servers(),
    }
