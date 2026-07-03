# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AIS-WiFi-Manager is a headless Raspberry Pi appliance (JLBMaritime): a browser + CLI Wi-Fi and AIS configuration tool for a Pi with a **dAISy HAT** (serial AIS receiver). It reads AIS off the serial port and forwards NMEA-0183 over persistent TCP to endpoints — typically the sibling `AIS-Server` repo in `C:\dev` (the central concentrator), using the shared `\s:NODE_ID*HH\` tag-block convention and Tailscale tag `tag:ais-node`. The `ADSB-WiFi-Manager` repo is its near-identical aviation sibling.

## Running

Entry point is `run.py`: waitress WSGI serving the Flask app on port 80 (falls back to :5000), plus an sdnotify watchdog thread, `init_db()`, and the AIS forwarder. No test suite exists. Deployed via `install.sh` with three systemd units in `service/`: the manager (`Type=notify` + watchdog), powersave-off, and hotspot-watchdog. CLI: `cli/ais_wifi_cli.py`, installed as `ais-wifi-cli` (includes `reset-password`, `show-hotspot`).

## Architecture

`app/` is the Flask package: `__init__.py` (app factory), `auth.py` + `routes.py` (all routes `@login_required`, plus `/healthz`), `ais_manager.py` (persistent-TCP forwarder + NMEA checksum filter), `ais_config_manager.py` (atomic config writes), `wifi_manager.py` (nmcli wrappers, `shell=False`), `network_diagnostics.py`, `database.py` (SQLite WAL: users + saved networks), `_hotspot_watchdog.py`. `cli/` and `service/` sit outside the app package.

Key tech: Flask, Flask-Login, Flask-Limiter, waitress, bcrypt, pyserial, sdnotify. No SocketIO. Auth defaults `JLBMaritime`/`Admin`, forced change on first login. Always-on AP `JLBMaritime-AIS` on wlan1 (192.168.4.1) so the operator can always reach the box; Wi-Fi power-save is disabled (brcmfmac freeze workaround).

This runs on remote Pi hardware — serial/nmcli/systemd behavior can't be tested locally on Windows. The hotspot/watchdog/powersave patterns are copy-pasted (not shared) across the sibling repos; a fix here may need porting to `ADSB-WiFi-Manager` and vice versa.
