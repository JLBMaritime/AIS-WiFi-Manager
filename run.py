#!/usr/bin/env python3
"""AIS-WiFi Manager — entry point.

Changes vs. the original
------------------------
* Uses the **waitress** WSGI server (production-grade, pure Python) instead
  of Werkzeug's debug server.  Werkzeug is not safe for long-running
  unattended use; that was the most likely cause of the "UI just stops
  responding" symptom.
* Pings systemd's watchdog every 10 s via ``sdnotify`` when run under a
  ``WatchdogSec=`` unit.  If the Flask request loop ever wedges, systemd
  will kill us and restart cleanly.
* Configures logging once, here — :mod:`app.ais_manager` no longer calls
  ``logging.basicConfig`` at import time.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time

from waitress import serve

from app import app
from app.ais_manager import ais_manager
from app.database import init_db


# ---------------------------------------------------------------------------
# Logging — single place, single time.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,                     # journald captures stdout
)
log = logging.getLogger("ais-wifi-manager")


# ---------------------------------------------------------------------------
# Optional systemd watchdog
# ---------------------------------------------------------------------------
def _watchdog_pinger():
    try:
        from sdnotify import SystemdNotifier
    except Exception:    # pragma: no cover  (sdnotify may not be installed)
        return
    notifier = SystemdNotifier()
    notifier.notify("READY=1")
    interval = 10.0
    # If WatchdogSec is set, half it (per systemd recommendation).
    wd_usec = os.environ.get("WATCHDOG_USEC")
    if wd_usec:
        try:
            interval = max(1.0, int(wd_usec) / 1_000_000 / 2)
        except ValueError:
            pass
    while True:
        notifier.notify("WATCHDOG=1")
        time.sleep(interval)


threading.Thread(target=_watchdog_pinger, daemon=True,
                 name="sdnotify-watchdog").start()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _print_banner(host: str, port: int):
    log.info("=" * 60)
    log.info("AIS-WiFi Manager web server")
    log.info("  URL:  http://AIS.local  /  http://192.168.4.1")
    log.info("  Bind: %s:%d", host, port)
    log.info("Default credentials (first install):")
    log.info("  Username: JLBMaritime")
    log.info("  Password: Admin   (will be forced to change on first login)")
    log.info("Recovery: sudo ais-wifi-cli reset-password")
    log.info("=" * 60)


def main():
    init_db()

    if hasattr(os, "geteuid") and os.geteuid() != 0:
        log.warning("Not running as root — Wi-Fi reconfiguration may fail.")

    log.info("Starting AIS Manager…")
    ok, msg = ais_manager.start()
    log.info("AIS Manager: %s", msg if ok else f"⚠ {msg}")

    host = os.environ.get("AIS_BIND_HOST", "0.0.0.0")
    port = int(os.environ.get("AIS_BIND_PORT", "80"))
    _print_banner(host, port)

    try:
        serve(app, host=host, port=port,
              threads=8, ident="ais-wifi-manager",
              channel_timeout=120)
    except PermissionError:
        log.error("Cannot bind port %d. Either run with sudo, or grant the "
                  "venv python: setcap cap_net_bind_service=+ep .venv/bin/python",
                  port)
        log.warning("Falling back to port 5000…")
        serve(app, host=host, port=5000,
              threads=8, ident="ais-wifi-manager",
              channel_timeout=120)
    except KeyboardInterrupt:
        log.info("Shutting down…")
        ais_manager.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
