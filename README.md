# AIS-WiFi Manager

Browser- and CLI-driven Wi-Fi + AIS configuration tool for a Raspberry Pi
running a dAISy HAT (or any AIS receiver on a serial port).

> **You probably want to read this section first if you're upgrading.** The
> install layout, default login flow, port (80, not 5000), and recovery
> commands are all new.

---

## What changed in this version

This drop is largely a stability + security pass driven by the AIS Server
brief.  The headline items:

| # | Area | What changed | Why it matters |
|---|------|--------------|----------------|
| 1 | **Auth** | Real session-based login (Flask-Login + bcrypt) replacing HTTP-Basic. Default `JLBMaritime / Admin` is **force-changed on first login**. | Old basic-auth was checked against a plaintext on-disk password and the credentials prompt re-appeared on every refresh. |
| 2 | **Sessions** | Persistent random `SECRET_KEY` at `/opt/ais-wifi-manager/secret_key` (mode 600). | Service restarts no longer kick everyone out. |
| 3 | **Web server** | `waitress` instead of Werkzeug debug server. | Werkzeug is not safe for unattended long-running use; that was the most likely cause of the "UI hangs after a few hours" bug. |
| 4 | **Watchdog** | systemd `WatchdogSec=60` + `sdnotify` ping. | If the request loop ever wedges, systemd restarts us. |
| 5 | **AIS forwarding** | Persistent TCP per endpoint, exponential backoff, NMEA checksum filter, optional `\s:NODE_ID*HH\` tag-block, configurable baud rate. | The original opened/closed a socket *per sentence* — fine on LAN, terrible across Tailscale. |
| 6 | **Endpoint reload** | `reload_endpoints()` diffs config in place. | Adding/removing endpoints used to restart the service and drop a few seconds of data. |
| 7 | **Wi-Fi shell-injection** | All `nmcli` calls go through a `shell=False` helper. | SSIDs / passwords with `;` `$` `` ` `` could previously inject commands. |
| 8 | **Wi-Fi freeze** | Power-save permanently disabled (NM drop-in *and* oneshot fallback). | Mitigates the well-known brcmfmac freeze after several hours on the Pi 4B. |
| 9 | **DB** | SQLite WAL + bcrypt `users` table + atomic config writes + capped backups. | Power-loss-during-write no longer truncates `ais_config.conf` to zero bytes. |
| 10 | **Logs** | Bounded `deque(maxlen=200)`, single `logging.basicConfig`, `journald` `Storage=persistent`. | No more list-slice memory churn; logs survive reboots. |
| 11 | **Recovery** | `sudo ais-wifi-cli reset-password` resets to default and forces re-change. | If you forget your password, you no longer have to reflash the SD card. |
| 12 | **Hotspot password** | Randomised at install time, stored mode 600 at `/opt/ais-wifi-manager/HOTSPOT_PASSWORD.txt`, retrievable via `sudo ais-wifi-cli show-hotspot`. | Old install hard-coded `JLBMaritime` for the AP — visible in the repo. |
| 13 | **Health** | `GET /healthz` (unauthenticated) returns 200 only when forwarder + serial are alive. | Useful for external monitors / Tailscale Serve probes. |

---

## Repository layout

```
.
├── app/                         # Flask application package
│   ├── __init__.py              # App factory, persistent SECRET_KEY, login mgr
│   ├── auth.py                  # /login, /logout, /change-password
│   ├── routes.py                # Pages + JSON APIs (all @login_required)
│   ├── ais_manager.py           # Persistent-TCP forwarder, NMEA checksum filter
│   ├── ais_config_manager.py    # Atomic-write config, validated endpoints
│   ├── wifi_manager.py          # nmcli wrapper (shell=False)
│   ├── network_diagnostics.py   # ping / iface status / DNS / gateway
│   ├── database.py              # SQLite (WAL) — saved networks + users
│   ├── _shellutil.py            # Shared shell=False subprocess helper
│   ├── static/                  # CSS / JS / images
│   └── templates/               # Jinja2 templates
├── cli/
│   └── ais_wifi_cli.py          # Interactive + non-interactive CLI
├── service/
│   ├── ais-wifi-manager.service          # Main unit (Type=notify, watchdog)
│   ├── ais-wifi-powersave-off.service    # Oneshot powersave-off fallback
│   └── wifi-powersave-off.conf           # NM drop-in (wifi.powersave=2)
├── run.py                       # Entry point — waitress + sdnotify
├── requirements.txt
├── install.sh                   # Idempotent installer (venv, capset, etc.)
├── uninstall.sh
└── README.md                    # This file
```

---

## Installation

Tested on **Raspberry Pi OS Bookworm (64-bit)**, fresh image.

```bash
# 1. Get the code
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/JLBMaritime/AIS-WiFi-Manager.git
cd AIS-WiFi-Manager

# 2. Run the installer (add --with-tailscale if you want it; see below)
sudo ./install.sh
# or:
# sudo ./install.sh --with-tailscale
```

The installer will:

1. `apt install` Python, NetworkManager, hostapd, dnsmasq, iw, wireless-tools,
   git, libcap2-bin (for `setcap`).
2. Turn on persistent journald (`/var/log/journal`).
3. Copy the project to `/opt/ais-wifi-manager`.
4. Create a venv at `/opt/ais-wifi-manager/.venv` and install Python deps.
5. `setcap cap_net_bind_service=+ep` on the venv `python3` so the service
   can bind port 80 without being root.
6. Install the `ais-wifi-cli` shim in `/usr/local/bin`.
7. Drop a NetworkManager config that **permanently disables Wi-Fi
   power-save** (the brcmfmac freeze mitigation).
8. Generate a random hotspot password (saved mode 600 in
   `/opt/ais-wifi-manager/HOTSPOT_PASSWORD.txt`).
9. Install + enable both systemd units.

When it finishes:

```
Web UI:   http://AIS.local/   (or http://192.168.4.1 in hotspot mode)
Login:    JLBMaritime / Admin    ← will be forced to change on first sign-in
```

---

## Tailscale (recommended)

The AIS Server brief calls for a secure tail-net between every node and the
central server.  Tailscale is the easiest way to do that.

```bash
sudo ./install.sh --with-tailscale     # if you didn't choose it earlier
sudo tailscale up --ssh                # bring up + opt into Tailscale SSH
```

### Suggested ACLs / tags

Define the following tags in your tail-net policy and you can restrict the
nodes to *only* talking to the server:

```jsonc
{
  "tagOwners": {
    "tag:ais-node":   ["autogroup:admin"],
    "tag:ais-server": ["autogroup:admin"],
  },
  "acls": [
    // Nodes may only push NMEA to the server.
    { "action": "accept",
      "src":    ["tag:ais-node"],
      "dst":    ["tag:ais-server:80,5000-5100"] },
    // The server may not initiate connections back to nodes.
    { "action": "accept",
      "src":    ["autogroup:admin"],
      "dst":    ["*:*"] },
  ],
}
```

The server then publishes its web UI over the tailnet alone:

```bash
sudo tailscale serve --bg --https=443 http://localhost:80
```

---

## Recovery

* **Forgot the web password.**

  ```bash
  ssh pi@AIS.local
  sudo ais-wifi-cli reset-password
  ```

  This restores `JLBMaritime / Admin` and forces a change on next login.
  To set an explicit password instead:
  `sudo ais-wifi-cli reset-password --to MyNewPassword`.

* **Forgot the hotspot password.**

  ```bash
  sudo ais-wifi-cli show-hotspot
  ```

* **Service is broken.**

  ```bash
  sudo journalctl -u ais-wifi-manager -n 200 --no-pager
  ais-wifi-cli health
  sudo systemctl restart ais-wifi-manager
  ```

---

## Operational notes

* **The web UI runs on port 80**, not 5000.  If port 80 is unavailable
  (because something else has bound it), the service falls back to 5000.
* **Default credentials change on first login** — there is no way to
  bypass the change-password screen short of `reset-password` over SSH.
* **NMEA checksums are enforced.**  Sentences with bad `*HH` checksums are
  dropped and counted (visible on the AIS dashboard) but never forwarded.
* **Endpoint config edits don't restart the forwarder.**  Persistent TCP
  connections are diffed and adjusted in place.
* **Per-endpoint stats** (sent / failed / connected / last error) are
  surfaced via `/api/ais/endpoints` and the AIS Configuration page.

---

## Uninstall

```bash
sudo ./uninstall.sh
```

This stops both services, removes the unit files, deletes the CLI shim,
optionally deletes `/opt/ais-wifi-manager` (config + saved networks),
and optionally tears down the hotspot.
