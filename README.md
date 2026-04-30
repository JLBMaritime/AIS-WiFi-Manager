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
| 12 | **Hotspot model** | Always-on AP `JLBMaritime-AIS` on **wlan1** (USB dongle), 192.168.4.1, no fallback gymnastics. PSK randomised at install and visible only via `sudo ais-wifi-cli show-hotspot` (queries NetworkManager directly — the source of truth). | wlan0 stays free for the station connection (your home/boat/shoreside Wi-Fi). The AP can never be knocked offline by a wlan0 mis-config. |
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
sudo chmod +x install.sh

# 2. Run the installer (add --with-tailscale if you want it; see below)
sudo ./install.sh
# or:
# sudo ./install.sh --with-tailscale
```

The installer will:

1. `apt install` Python, NetworkManager, **dnsmasq-base** (binary only — see
   note below), iw, wireless-tools, git, libcap2-bin (for `setcap`).  It
   also `systemctl disable --now`s `dnsmasq` and `hostapd` if a previous
   install pulled them in.
2. Turn on persistent journald (`/var/log/journal`).
3. Copy the project to `/opt/ais-wifi-manager`.
4. Create a venv at `/opt/ais-wifi-manager/.venv` and install Python deps.
5. `setcap cap_net_bind_service=+ep` on the venv `python3` so the service
   can bind port 80 without being root.
6. Install the `ais-wifi-cli` shim in `/usr/local/bin`, drop a
   NetworkManager config that **permanently disables Wi-Fi power-save**
   (the brcmfmac freeze mitigation).
7. **Materialise the always-on AP** on `wlan1` (USB Wi-Fi dongle):
   create / re-create the NetworkManager connection profile
   `ais-hotspot` (SSID `JLBMaritime-AIS`, 192.168.4.1/24, WPA2-PSK with
   a randomly generated 16-char alnum PSK), bring it up, and *verify*
   activation by polling `nmcli` for up to 15 s.  On failure, the NM
   journal tail is printed and the installer exits non-zero.
8. The PSK is written mode 600 to
   `/opt/ais-wifi-manager/HOTSPOT_PASSWORD.txt` (seed file — see Hotspot
   section below for the source-of-truth model).
9. Install + enable both systemd units, run a post-flight `is-active`
   check, and dump the journal tail if the unit failed to start.

When it finishes:

```
Web UI (over hotspot):     http://192.168.4.1/
Web UI (over your LAN):    http://<pi-ip>/   or   http://AIS.local/
Login:    JLBMaritime / Admin    ← will be forced to change on first sign-in
```

> **Why a USB dongle?**  The Pi 4B's onboard Wi-Fi (`wlan0`) carries the
> client connection to your home / boat / shoreside network so the unit
> has internet.  A USB dongle (`wlan1`) carries the always-on AP.  Both
> stay active simultaneously, which means the management AP can never be
> knocked offline by a wlan0 mis-config or out-of-range condition — you
> can always reach `http://192.168.4.1/` to fix things.
>
> Any modern dongle whose chipset reports `* AP` in `iw list` will work
> (RTL8188EUS / 8192EU / 8812AU, MT76xx, RT5370, etc.). The installer
> will warn if no AP-capable interface mode is reported.

---

## Hotspot

| Item       | Value                                                       |
|------------|-------------------------------------------------------------|
| SSID       | `JLBMaritime-AIS`                                           |
| Interface  | `wlan1` (USB Wi-Fi adapter)                                 |
| IPv4       | `192.168.4.1/24` (NM `ipv4.method shared`)                  |
| Security   | WPA2-PSK, randomised at install                             |
| Profile    | NM connection name `ais-hotspot`, autoconnect, MAC-pinned   |
| Source of truth | NetworkManager — **not** `HOTSPOT_PASSWORD.txt`        |

```bash
sudo ais-wifi-cli show-hotspot       # SSID + PSK + state + clients
sudo ais-wifi-cli hotspot status     # same, plus formatting
sudo ais-wifi-cli hotspot up         # bring up
sudo ais-wifi-cli hotspot down       # bring down
sudo ais-wifi-cli hotspot rotate-pw  # generate new PSK & bounce AP
sudo ais-wifi-cli hotspot diagnose   # full A–E probe report
```

### dnsmasq-base, not dnsmasq (if you're packaging this yourself)

NM's `ipv4.method shared` spawns its own private dnsmasq for the AP
subnet on 192.168.4.1.  The full `dnsmasq` Debian package ships a
systemd unit that auto-starts and binds port 53/67 on `0.0.0.0` —
that steals the port and makes the AP fail to come up with the famously
vague:

```
device (wlan1): state change: ip-config -> failed
                              (reason 'ip-config-unavailable')
dnsmasq: failed to create listening socket for 192.168.4.1: Address already in use
```

The fix is to install `dnsmasq-base` (binary only, no unit) — which is
what `install.sh` does.  If you upgraded from an older install where
the full `dnsmasq` package is already present, the installer also runs
`systemctl disable --now dnsmasq` belt-and-braces.


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

* **Pi won't come back up after installing Tailscale (no Wi-Fi, DNS broken).**

  This is a known Tailscale-on-RPi-OS-Lite trap.  Tailscale's installer
  drops `/etc/NetworkManager/conf.d/tailscale.conf` containing
  `dns=systemd-resolved`, but RPi OS Lite **doesn't ship
  systemd-resolved enabled**.  On reboot NetworkManager fails to start,
  no Wi-Fi, no AP, `ping google.com` says *Temporary failure in name
  resolution*.

  Plug in a monitor + keyboard and run:
  ```bash
  sudo rm -f /etc/NetworkManager/conf.d/tailscale.conf
  sudo tee /etc/NetworkManager/conf.d/00-dns.conf >/dev/null <<'EOF'
  [main]
  dns=default
  rc-manager=file
  EOF
  if [ -L /etc/resolv.conf ] && [ ! -e /etc/resolv.conf ]; then
      sudo rm -f /etc/resolv.conf
      printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' \
          | sudo tee /etc/resolv.conf >/dev/null
  fi
  sudo systemctl restart NetworkManager
  sudo reboot
  ```

  > Fresh installs from this version of `install.sh` are immune — step 6
  > pre-declares `dns=default` *before* invoking Tailscale, step 9
  > scrubs `tailscale.conf` belt-and-braces, and a post-flight
  > `systemctl is-active NetworkManager` aborts the installer (rather
  > than leaving the box unbootable) if anything's gone wrong.


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

## Troubleshooting

### `ais-wifi-cli doctor`

The fastest way to find out why a Pi is misbehaving is:

```bash
sudo ais-wifi-cli doctor
```

It validates every file under `/etc/NetworkManager/conf.d/`, checks
NetworkManager and the web service are active, sanity-checks
`/etc/resolv.conf`, confirms the AP is up, and pings the local
`/healthz` endpoint. Each check prints `✓` (pass), `!` (warning) or
`✗` (fail) and the command exits non-zero if any check fails — handy
in CI / Ansible / Watchtower.

### Pi boots but Wi-Fi, AP and SSH are all dead (the `;`-comment trap)

**Symptom**: after a fresh install or `apt full-upgrade`, the Pi powers
up but is unreachable: no SSH on the LAN, no `JLBMaritime-AIS` SSID, no
DNS resolution from the console (`Temporary failure in name
resolution`).  `systemctl status NetworkManager` shows
`activating (auto-restart)` cycling through `Result: exit-code` and
finally `failed`.

**Cause**: glib's keyfile parser (used by NetworkManager 1.52 on
Debian 13 *trixie*) **rejects `;` as a comment character** in
`/etc/NetworkManager/conf.d/*.conf`. Older glib silently accepted it.
A single `;`-prefixed line is enough to make NM exit 1, hit
systemd's restart-limit (5 starts in 10 s), and stay in `failed`. With
NM gone, every interface goes with it: wlan0 (uplink), wlan1 (AP),
even `dns=default` writes to `/etc/resolv.conf` stop happening.

**One-line recovery** (plug the Pi into a monitor + USB keyboard, or
use the serial console on the GPIO header):

```bash
sudo sed -i 's/^[[:space:]]*;/#/' /etc/NetworkManager/conf.d/*.conf \
  && sudo nmcli general reload \
  && sudo systemctl is-active NetworkManager
```

If you can't get a console at all, pull the SD card, mount the
`rootfs` partition on another Linux box, and run the same `sed` on
`<mount>/etc/NetworkManager/conf.d/*.conf`.

**Prevention**: `install.sh` v2 ships a `validate_nm_conf()` guard
that rejects `;`-comments at install time, plus the `doctor`
subcommand that catches the same bug post-install.  Both are tested
in CI; please don't remove them.

### Tailscale broke my DNS (`dns=systemd-resolved`)

**Symptom**: shortly after `tailscale up` (or after any
`apt upgrade tailscale`), name resolution dies and a reboot makes
NetworkManager fail to start.

**Cause**: the upstream Tailscale installer drops
`/etc/NetworkManager/conf.d/tailscale.conf` containing
`dns=systemd-resolved`. RPi OS *Lite* doesn't enable
`systemd-resolved`, so NM tries to load a plugin that isn't there and
exits.

**Fix**:

```bash
sudo rm -f /etc/NetworkManager/conf.d/tailscale.conf
sudo nmcli general reload
```

The installer pre-empts this by writing `00-dns.conf` with
`dns=default` *before* installing Tailscale, and by scrubbing
`tailscale.conf` afterwards. `ais-wifi-cli doctor` flags it if it
ever returns.

### Hotspot fails to come up: *"IP configuration could not be reserved"*

**Cause**: the full `dnsmasq` package is installed (instead of
`dnsmasq-base`) and has bound `:53`/`:67` on `0.0.0.0`, stealing the
ports NetworkManager's own dnsmasq needs for the AP's `ipv4.method
shared` to work.

**Fix**:

```bash
sudo systemctl disable --now dnsmasq
sudo apt-get install --reinstall -y dnsmasq-base
sudo apt-get remove -y dnsmasq          # NB: removes the FULL package only
sudo nmcli c up ais-hotspot
```

`sudo ais-wifi-cli hotspot diagnose` lists who is bound to those
ports.

### SSH disconnects mid-install

This is expected — step 1 installs `network-manager`, which on some
images briefly bounces wlan0. The installer detects you're on SSH and
prints a 5-second countdown so you can move into `tmux`/`screen` or
connect over the management AP at `192.168.4.1` instead. Whatever
you do, the full install transcript is captured to
`/var/log/ais-wifi-install.log` — after reconnecting, run:

```bash
sudo tail -n 200 /var/log/ais-wifi-install.log
```

to see exactly where it got to (or whether it crashed).


