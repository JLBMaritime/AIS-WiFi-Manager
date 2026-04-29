"""AIS configuration file manager.

* **Atomic writes** — write to ``<file>.tmp`` then ``os.replace``; a power
  loss mid-write can no longer truncate ``ais_config.conf`` to zero bytes
  and lose every endpoint.
* **Backup pruning** — keep the last :data:`MAX_BACKUPS` only.
* **IP / hostname validation** — :func:`add_endpoint` / :func:`update_endpoint`
  reject obvious garbage (``;rm -rf /``) before it ever lands on disk.
"""
from __future__ import annotations

import configparser
import ipaddress
import logging
import os
import re
import shutil
import socket
from datetime import datetime
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

MAX_BACKUPS = 30


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
def get_config_path() -> str:
    installed = '/opt/ais-wifi-manager/ais_config.conf'
    if os.path.exists(installed) or os.path.isdir('/opt/ais-wifi-manager'):
        return installed
    return os.path.abspath('ais_config.conf')


CONFIG_FILE = get_config_path()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}"
                          r"(\.(?!-)[A-Za-z0-9-]{1,63})*$")


def _valid_host(host: str) -> bool:
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if not _HOSTNAME_RE.match(host):
        return False
    # Best-effort DNS resolution; tolerate failures (offline at config time).
    try:
        socket.gethostbyname(host)
        return True
    except OSError:
        return True   # syntactically valid is enough


def _valid_port(port) -> Optional[int]:
    try:
        p = int(port)
    except (TypeError, ValueError):
        return None
    return p if 1 <= p <= 65535 else None


# ---------------------------------------------------------------------------
# Atomic load / save
# ---------------------------------------------------------------------------
def load_ais_config() -> dict | None:
    if not os.path.exists(CONFIG_FILE):
        create_default_config()

    parser = configparser.ConfigParser()
    try:
        parser.read(CONFIG_FILE)
        return {section: dict(parser.items(section))
                for section in parser.sections()}
    except (configparser.Error, OSError) as exc:
        log.error("Failed to load %s: %s", CONFIG_FILE, exc)
        return None


def create_default_config() -> bool:
    parser = configparser.ConfigParser()
    parser['AIS'] = {
        'serial_port': '/dev/serial0',
        'baud_rate':   '38400',
    }
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE) or '.', exist_ok=True)
        return _atomic_write(parser)
    except OSError as exc:
        log.error("Could not create default config: %s", exc)
        return False


def _atomic_write(parser: configparser.ConfigParser) -> bool:
    tmp = CONFIG_FILE + '.tmp'
    try:
        with open(tmp, 'w') as f:
            parser.write(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_FILE)
        return True
    except OSError as exc:
        log.error("Atomic write of %s failed: %s", CONFIG_FILE, exc)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def backup_config() -> Optional[str]:
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = os.path.join(os.path.dirname(CONFIG_FILE), 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = os.path.join(backup_dir, f'ais_config_{ts}.conf')
        shutil.copy2(CONFIG_FILE, backup_file)
        _prune_backups(backup_dir)
        return backup_file
    except OSError as exc:
        log.warning("Backup failed: %s", exc)
        return None


def _prune_backups(backup_dir: str) -> None:
    try:
        files = sorted(
            (os.path.join(backup_dir, f)
             for f in os.listdir(backup_dir)
             if f.startswith('ais_config_') and f.endswith('.conf')),
            key=os.path.getmtime,
            reverse=True,
        )
        for old in files[MAX_BACKUPS:]:
            try:
                os.remove(old)
            except OSError:
                pass
    except OSError:
        pass


def save_ais_config(config_dict: dict) -> Tuple[bool, str]:
    backup_file = backup_config()
    parser = configparser.ConfigParser()
    for section, values in config_dict.items():
        parser[section] = {k: str(v) for k, v in values.items()}
    if not _atomic_write(parser):
        return False, "Error saving config"
    return True, ("Configuration saved (backup: "
                  f"{os.path.basename(backup_file) if backup_file else 'none'})")


# ---------------------------------------------------------------------------
# Endpoints API (signatures unchanged for backwards-compat)
# ---------------------------------------------------------------------------
def get_all_endpoints() -> List[dict]:
    config = load_ais_config()
    if not config:
        return []
    out = []
    for section, values in config.items():
        if section.startswith('ENDPOINT_'):
            ep = dict(values)
            ep['id'] = section
            out.append(ep)
    return out


def _next_endpoint_id(config: dict) -> str:
    nums = []
    for section in config:
        if section.startswith('ENDPOINT_'):
            try:
                nums.append(int(section.split('_', 1)[1]))
            except (IndexError, ValueError):
                pass
    return f"ENDPOINT_{(max(nums) + 1) if nums else 1}"


def add_endpoint(name: str, ip: str, port, enabled: bool = True):
    if not name:
        return False, None, "Name is required"
    p = _valid_port(port)
    if p is None:
        return False, None, "Port must be 1–65535"
    if not _valid_host(ip):
        return False, None, "Invalid IP address or hostname"

    config = load_ais_config() or {'AIS': {'serial_port': '/dev/serial0',
                                           'baud_rate': '38400'}}
    eid = _next_endpoint_id(config)
    config[eid] = {
        'name':    name.strip(),
        'ip':      ip.strip(),
        'port':    str(p),
        'enabled': str(bool(enabled)).lower(),
    }
    ok, msg = save_ais_config(config)
    return (ok, eid if ok else None, msg)


def update_endpoint(endpoint_id: str, name: str, ip: str, port, enabled):
    config = load_ais_config()
    if not config or endpoint_id not in config:
        return False, "Endpoint not found"
    p = _valid_port(port)
    if p is None:
        return False, "Port must be 1–65535"
    if not _valid_host(ip):
        return False, "Invalid IP address or hostname"

    config[endpoint_id] = {
        'name':    (name or '').strip(),
        'ip':      ip.strip(),
        'port':    str(p),
        'enabled': str(bool(enabled)).lower(),
    }
    return save_ais_config(config)


def delete_endpoint(endpoint_id: str):
    config = load_ais_config()
    if not config or endpoint_id not in config:
        return False, "Endpoint not found"
    del config[endpoint_id]
    return save_ais_config(config)


def toggle_endpoint(endpoint_id: str):
    config = load_ais_config()
    if not config or endpoint_id not in config:
        return False, "Endpoint not found"
    cur = config[endpoint_id].get('enabled', 'false').lower() == 'true'
    config[endpoint_id]['enabled'] = str(not cur).lower()
    return save_ais_config(config)
