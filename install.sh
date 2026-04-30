#!/bin/bash
# =============================================================================
# AIS-WiFi Manager — installer
# =============================================================================
# Optimisations vs. the original installer:
#
# 1. **Virtualenv** at /opt/ais-wifi-manager/.venv  — no more sudo pip install
#    polluting the system Python or fighting Debian's externally-managed env.
# 2. **Capability bind on port 80** — `setcap cap_net_bind_service=+ep
#    .venv/bin/python`, so the service no longer has to be root just to bind.
#    (We still run as root for nmcli / hostapd, but losing that one
#    requirement is a stepping-stone to dropping privileges later.)
# 3. **Wi-Fi power-save permanently off** — both a NetworkManager drop-in
#    (`/etc/NetworkManager/conf.d/wifi-powersave-off.conf`) and a oneshot
#    fall-back unit (`ais-wifi-powersave-off.service`).  This is the
#    documented mitigation for the brcmfmac freeze on the Pi 4B.
# 4. **systemd-journald persistence** — `/var/log/journal` is created with
#    `Storage=persistent`, so logs survive reboot for post-mortem.
# 5. **Hotspot password is randomised** at install time (was hard-coded to
#    `JLBMaritime`).  The generated value is written to
#    `/opt/ais-wifi-manager/HOTSPOT_PASSWORD.txt` (mode 600 root) and can
#    be retrieved later with `sudo ais-wifi-cli show-hotspot`.
# 6. **No more `pip install --break-system-packages`** anywhere — the venv
#    is what makes that flag unnecessary.
# 7. **Idempotent**: re-running upgrades the install in place; existing
#    config / DB / saved networks are preserved.
# 8. **Tailscale install is opt-in** via `--with-tailscale` (recommended by
#    the AIS Server brief for the secure tail-net between nodes / server).
#
# =============================================================================

set -euo pipefail

# -- Tee everything to a log file ----------------------------------------
# So that an SSH disconnect (we touch NetworkManager — wlan0 may briefly
# bounce, killing your SSH session) never destroys post-mortem visibility.
# After reconnecting:  sudo tail -n 200 /var/log/ais-wifi-install.log
INSTALL_LOG="/var/log/ais-wifi-install.log"
if [ "$EUID" -eq 0 ]; then
    : > "$INSTALL_LOG" 2>/dev/null || true
    exec > >(tee -a "$INSTALL_LOG") 2>&1
fi

# -- Colours --------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

# -- Helpers --------------------------------------------------------------
# validate_nm_conf <file>
#   Reject any line that isn't blank, a [group], a key=value, or a `#…`
#   comment.  This is the exact rule glib's keyfile parser enforces from
#   2.78 onwards (Debian 13 trixie / NM 1.52); a single `;`-comment is
#   enough to make NM crash-loop on boot and take wlan0/wlan1 down with
#   it.  Calling this BEFORE we trigger a reload is the single most
#   important guard in this installer — please don't remove.
validate_nm_conf() {
    local f="$1"
    local n=0 bad=0
    while IFS= read -r line; do
        n=$((n+1))
        # strip CR (in case of CRLF) and leading whitespace
        local stripped="${line%$'\r'}"
        stripped="${stripped#"${stripped%%[![:space:]]*}"}"
        case "$stripped" in
            ''|'#'*|'['*) ;;                      # ok: blank / comment / group
            *=*) ;;                                # ok: key = value
            *)
                echo -e "${RED}      INVALID line $n in $f:${NC} $line"
                bad=$((bad+1))
                ;;
        esac
    done < "$f"
    if [ "$bad" -gt 0 ]; then
        echo -e "${RED}      $f has $bad invalid line(s) — refusing to install it.${NC}"
        echo -e "${RED}      (NM 1.52 on trixie rejects ';' comments.  Use '#'.)${NC}"
        return 1
    fi
}

# nm_reload
#   Re-read /etc/NetworkManager/conf.d/* WITHOUT tearing down active
#   radio links.  Falls back to a hard restart only if reload fails.
#   Crucially: it asserts NM is `is-active` afterwards and dumps the
#   journal + aborts if not — which is what would have caught the
#   original `;`-comment bug at install time instead of next reboot.
nm_reload() {
    if nmcli general reload >/dev/null 2>&1; then
        :
    else
        systemctl restart NetworkManager
    fi
    sleep 2
    if ! systemctl is-active --quiet NetworkManager; then
        echo -e "${RED}      NetworkManager is not active after reload!${NC}"
        echo "      Last 30 NM journal lines:"
        journalctl -u NetworkManager -n 30 --no-pager | tail -n 30 || true
        echo -e "${RED}      Refusing to continue — would leave Pi unbootable.${NC}"
        return 1
    fi
}


# -- Config ---------------------------------------------------------------
INSTALL_DIR="/opt/ais-wifi-manager"
SERVICE_NAME="ais-wifi-manager"
PS_SERVICE_NAME="ais-wifi-powersave-off"
HOTSPOT_PW_FILE="${INSTALL_DIR}/HOTSPOT_PASSWORD.txt"
WITH_TAILSCALE=0

for arg in "$@"; do
    case "$arg" in
        --with-tailscale) WITH_TAILSCALE=1 ;;
        -h|--help)
            cat <<EOF
AIS-WiFi Manager installer.

Options:
  --with-tailscale   Also install Tailscale (recommended; see README §Tailscale).
  -h, --help         This help.
EOF
            exit 0 ;;
    esac
done

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Run with sudo.${NC}"; exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================="
echo " AIS-WiFi Manager — installation"
echo "========================================="

# -- SSH detection / warning ---------------------------------------------
# We'll be touching NetworkManager (writing conf.d files, reloading, and
# bringing up the AP).  An `nmcli general reload` is non-disruptive, but
# step 1 also installs network-manager itself which on some images can
# briefly bounce wlan0 — and if you're SSH'd in over wlan0 your session
# will die mid-install.  The installer carries on regardless (everything
# is logged to $INSTALL_LOG), but the user has no way to know.  Print a
# clear warning and offer them 5 s to abort and switch to tmux/screen
# or to run from the AP at 192.168.4.1.
if [ -n "${SSH_CONNECTION:-}" ]; then
    echo
    echo -e "${YELLOW}NOTICE: you are running this installer over SSH (${SSH_CONNECTION}).${NC}"
    echo -e "${YELLOW}        Wi-Fi may briefly bounce; if your session drops, reconnect"
    echo -e "${YELLOW}        after ~30 s and follow progress with:${NC}"
    echo -e "${YELLOW}            sudo tail -f $INSTALL_LOG${NC}"
    echo -e "${YELLOW}        (For zero-risk: run inside ${GREEN}tmux${YELLOW} or ${GREEN}screen${YELLOW},"
    echo -e "${YELLOW}        or connect over the management AP at ${GREEN}192.168.4.1${YELLOW}.)${NC}"
    echo -e "${YELLOW}        Continuing in 5 s — Ctrl-C to abort.${NC}"
    sleep 5
fi


# -- 1. APT packages ------------------------------------------------------
echo -e "${GREEN}[1/9] Installing system packages…${NC}"
apt-get update -qq
# IMPORTANT: dnsmasq-base, NOT dnsmasq.
#   The full `dnsmasq` package ships a systemd unit that auto-starts and binds
#   :53 / :67 on 0.0.0.0.  NetworkManager's `ipv4.method shared` (used by our
#   AP profile on wlan1) needs to spawn its OWN private dnsmasq on
#   192.168.4.1 — and the system one being there steals the port and makes
#   the AP fail to come up with the famously vague:
#       "IP configuration could not be reserved (no available address, timeout, etc.)"
#   `dnsmasq-base` provides the same /usr/sbin/dnsmasq binary that NM invokes,
#   but with no systemd unit.  This single change is what fixes hotspot
#   activation on a fresh install.
# We also explicitly disable+stop the full `dnsmasq` service in case someone
# is upgrading from an older install where the full package was pulled in.
apt-get install -y -qq --no-install-recommends \
    python3 python3-venv python3-pip python3-dev \
    network-manager dnsmasq-base iw wireless-tools iputils-ping \
    git ca-certificates libcap2-bin dnsutils
# dnsutils is for `dig`, used by `ais-wifi-cli doctor` to send a real
# DNS query to 192.168.4.1 and verify the AP-side resolver is healthy.
# It's a tiny package (<200 KB) and well worth carrying for the
# diagnostic value when an iPhone refuses to join.

systemctl disable --now dnsmasq 2>/dev/null || true
systemctl disable --now hostapd 2>/dev/null || true

# Pin the FULL `dnsmasq` package to "do not install" so a future
# `apt full-upgrade` (or somebody manually `apt install`-ing pi-hole etc.)
# can't drag it back in and steal :53/:67 from NM's per-AP dnsmasq.
# `apt-mark hold` is the standard Debian way and is reversible with
# `apt-mark unhold dnsmasq`.  Errors are tolerated — on some images the
# package isn't even known to apt yet (clean install).
apt-mark hold dnsmasq 2>/dev/null || true



# -- 2. Persistent journald ----------------------------------------------
echo -e "${GREEN}[2/9] Enabling persistent journald…${NC}"
mkdir -p /var/log/journal
if ! grep -q '^Storage=persistent' /etc/systemd/journald.conf 2>/dev/null; then
    sed -i 's/^#\?Storage=.*/Storage=persistent/' /etc/systemd/journald.conf || true
    grep -q '^Storage=' /etc/systemd/journald.conf || \
        echo 'Storage=persistent' >> /etc/systemd/journald.conf
fi
systemctl restart systemd-journald || true

# -- 3. Project layout ----------------------------------------------------
echo -e "${GREEN}[3/9] Copying project to ${INSTALL_DIR}…${NC}"
mkdir -p "$INSTALL_DIR"
# rsync would be nicer, but cp is universally available.
cp -r "$SCRIPT_DIR/app"      "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/cli"      "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/service"  "$INSTALL_DIR/"
cp    "$SCRIPT_DIR/run.py"            "$INSTALL_DIR/"
cp    "$SCRIPT_DIR/requirements.txt"  "$INSTALL_DIR/"
chown -R root:root "$INSTALL_DIR"
chmod -R u+rwX,go+rX "$INSTALL_DIR"

# -- 4. Python venv -------------------------------------------------------
echo -e "${GREEN}[4/9] Creating Python virtualenv…${NC}"
if [ ! -d "$INSTALL_DIR/.venv" ]; then
    python3 -m venv "$INSTALL_DIR/.venv"
fi
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip wheel >/dev/null
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# Allow the venv python to bind port 80 without root.
# Notes for fresh installs:
#   * `python -m venv` on Debian creates `.venv/bin/python3` as a *symlink*
#     to /usr/bin/python3.X  → setcap refuses to operate on symlinks and
#     prints "Invalid file '<path>' for capability operation".
#   * We therefore resolve the symlink with readlink -f and apply the
#     capability to the real binary.  This is best-effort: the unit runs
#     as root anyway (it has to, for nmcli/hostapd), so a failure here is
#     not fatal — we just warn and keep going.
echo -e "${GREEN}      Granting cap_net_bind_service to venv python…${NC}"
REAL_PY="$(readlink -f "$INSTALL_DIR/.venv/bin/python3" 2>/dev/null || true)"
if [ -n "$REAL_PY" ] && [ -f "$REAL_PY" ]; then
    if setcap 'cap_net_bind_service=+ep' "$REAL_PY" 2>/dev/null; then
        echo -e "${GREEN}      → applied to $REAL_PY${NC}"
    else
        echo -e "${YELLOW}      → setcap not available / refused; skipping (we run as root anyway).${NC}"
    fi
else
    echo -e "${YELLOW}      → could not resolve venv python; skipping setcap.${NC}"
fi

# -- 5. CLI symlink -------------------------------------------------------
echo -e "${GREEN}[5/9] Installing CLI shim…${NC}"
cat > /usr/local/bin/ais-wifi-cli <<EOF
#!/bin/sh
exec "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/cli/ais_wifi_cli.py" "\$@"
EOF
chmod +x /usr/local/bin/ais-wifi-cli

# -- 6. Wi-Fi power-save off + NM DNS hardening --------------------------
echo -e "${GREEN}[6/9] Disabling Wi-Fi power-save on wlan0…${NC}"

# Validate the conf.d files we ship BEFORE installing them.  glib's
# keyfile parser (used by NM 1.52 on Debian 13 trixie) rejects `;` as a
# comment character — a single bad line is enough to make NM crash-loop
# on boot and take wlan0/wlan1/SSH down with it.  We caught this with a
# fresh-install field report; validate_nm_conf is the regression guard.
echo -e "${GREEN}      Validating shipped NetworkManager drop-ins…${NC}"
validate_nm_conf "$SCRIPT_DIR/service/wifi-powersave-off.conf" || exit 1

install -m 0644 "$SCRIPT_DIR/service/wifi-powersave-off.conf" \
    /etc/NetworkManager/conf.d/wifi-powersave-off.conf
install -m 0644 "$SCRIPT_DIR/service/ais-wifi-powersave-off.service" \
    /etc/systemd/system/${PS_SERVICE_NAME}.service

# Pin the per-AP dnsmasq's upstream resolvers.
#
# Why: NM's `ipv4.method shared` spawns a private dnsmasq for the AP
# subnet (192.168.4.0/24).  That dnsmasq forwards client DNS queries
# upstream by reading /etc/resolv.conf.  When Tailscale is also
# installed, /etc/resolv.conf flaps between NM's wlan0 server and
# Tailscale's MagicDNS (100.100.100.100) every 30-90 s — and
# dnsmasq re-reads it on every change.  An iPhone joining the AP runs
# its captive-portal probe (`GET captive.apple.com/hotspot-detect.html`)
# during one of those flap windows, the DNS lookup times out, and iOS
# either refuses to join with "Unable to join this network" OR joins
# but won't pass any traffic — so http://192.168.4.1/ never loads.
#
# Fix: ship a `dnsmasq-shared.d` drop-in that says `no-resolv` plus
# explicit `server=1.1.1.1` etc.  This decouples the AP-side resolver
# from /etc/resolv.conf entirely.  Tailscale's MagicDNS keeps working
# for the host (Pi itself) — only the AP-spawned dnsmasq is affected.
#
# The same file also adds `address=/captive.apple.com/192.168.4.1`
# entries that hijack OS captive-portal probes to our own Flask app
# (which serves the magic "Success" / 204 / NCSI strings each OS
# expects).  Belt-and-braces — once upstream is pinned this is rarely
# hit, but it makes the join experience instant.
echo -e "${GREEN}      Pinning AP-side dnsmasq upstream (resolv.conf-independent)…${NC}"
mkdir -p /etc/NetworkManager/dnsmasq-shared.d
install -m 0644 "$SCRIPT_DIR/service/dnsmasq-shared-ais.conf" \
    /etc/NetworkManager/dnsmasq-shared.d/00-ais-upstream.conf



# Lock NetworkManager's DNS plugin to the simple built-in writer BEFORE
# anything (Tailscale, in particular) gets a chance to re-write it.
#
# Why this matters:
#   Tailscale's installer sniffs NM and, if no `dns=` is declared in
#   /etc/NetworkManager/conf.d/, drops a file there with
#       dns=systemd-resolved
#   to make MagicDNS work via systemd-resolved.  RPi OS *Lite* doesn't
#   ship systemd-resolved enabled (it's a Desktop-image default), so on
#   the next reboot NM tries to load the resolved plugin, fails, and
#   NetworkManager.service exits [FAILED].  No NM = no wlan0 = no wlan1
#   = no AP, and `ping google.com` returns "Temporary failure in name
#   resolution".  Looks like a dead Pi; isn't.
#
#   By pre-declaring dns=default + rc-manager=file BEFORE Tailscale
#   installs, Tailscale's installer sees an existing dns= setting and
#   leaves it alone.  We also scrub the file post-Tailscale-install in
#   step 9 belt-and-braces.
#
echo -e "${GREEN}      Hardening NetworkManager DNS plugin (dns=default)…${NC}"
install -m 0644 /dev/stdin /etc/NetworkManager/conf.d/00-dns.conf <<'EOF'
# Managed by AIS-WiFi-Manager installer.
# Force NM to write /etc/resolv.conf itself (no systemd-resolved required).
# Do NOT replace this with dns=systemd-resolved on RPi OS Lite — that image
# does not have systemd-resolved enabled and NetworkManager will refuse to
# start.  See install.sh step 6/9 for the long story.
[main]
dns=default
rc-manager=file
EOF

# If a previous Tailscale install on this image already dropped the bad
# file, remove it now so the upcoming `systemctl restart NetworkManager`
# (implicit in step 7) can succeed.
rm -f /etc/NetworkManager/conf.d/tailscale.conf

# Repair /etc/resolv.conf if it's a dangling symlink to
# /run/systemd/resolve/stub-resolv.conf (which doesn't exist on Lite).
if [ -L /etc/resolv.conf ] && [ ! -e /etc/resolv.conf ]; then
    echo -e "${YELLOW}      /etc/resolv.conf is a dangling symlink — replacing with a real file.${NC}"
    rm -f /etc/resolv.conf
    printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > /etc/resolv.conf
    chmod 644 /etc/resolv.conf
fi

# Don't let *-wait-online services hold up boot for minutes if any
# interface (tailscale0 in particular) is slow to come up.  Our app
# supervises its own networking — the boot path doesn't need to block.
systemctl disable NetworkManager-wait-online.service 2>/dev/null || true
systemctl mask    systemd-networkd-wait-online.service 2>/dev/null || true

# Reload NM so it picks up dns=default before we proceed.
# nm_reload uses `nmcli general reload` which DOESN'T tear down active
# radio links — your SSH session over wlan0 stays alive.  It also
# asserts NM is is-active afterwards and aborts the install if not,
# which is the regression guard for the trixie `;`-comment bug we hit.
nm_reload || exit 1



# -- 7. Always-on management hotspot on wlan1 -----------------------------
#
# Design (final):
#   wlan0 = station (the user's home / boat / shoreside Wi-Fi for internet).
#   wlan1 = AP, always up, no fallback gymnastics.  Both stay active.
#
# Hard-won lessons baked into this block:
#   * The radio for the AP is a USB Wi-Fi dongle that enumerates as wlan1.
#     If it isn't plugged in the user gets a clear yellow warning, the
#     installer continues, and re-running the installer once it's plugged
#     in will materialise the AP cleanly.
#   * We bind the NM connection profile to the dongle's *MAC*
#     (802-11-wireless.mac-address), not the interface name.  Cheap dongles
#     can re-enumerate as wlan2/wlan3 across USB-port changes; the MAC is
#     the only stable identifier.
#   * `nmcli c delete ais-hotspot 2>/dev/null || true` first, then re-create.
#     This is what makes re-running the installer always converge to the
#     credentials in HOTSPOT_PASSWORD.txt.
#   * `connection.autoconnect yes` (no negative priority) — the AP comes up
#     unconditionally on every boot.  Two radios, one AP, one STA, life is
#     simple.
#   * The dnsmasq-base / disable-dnsmasq.service work in step 1 is what
#     lets `ipv4.method shared` actually succeed on activation.  Without
#     that, NM's spawned dnsmasq fails to bind 192.168.4.1:53 and the AP
#     dies with the famously vague "IP configuration could not be reserved".
#
HOTSPOT_SSID="JLBMaritime-AIS"
echo -e "${GREEN}[7/9] Configuring always-on AP hotspot on wlan1…${NC}"

# 7a. Generate (or preserve) a 16-char alnum PSK.
#     SIGPIPE-proof generator: head -c 64 reads a fixed amount and exits 0;
#     tr never sees a closed pipe.  Wrapped in a subshell that disables
#     pipefail belt-and-braces.
if [ ! -f "$HOTSPOT_PW_FILE" ]; then
    HOTSPOT_PW="$(
        set +o pipefail
        head -c 64 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9' | cut -c1-16
    )"
    if [ -z "$HOTSPOT_PW" ] || [ "${#HOTSPOT_PW}" -lt 16 ]; then
        HOTSPOT_PW="$(date +%s%N | sha256sum | cut -c1-16)"
    fi
    printf 'SSID:     %s\nPassword: %s\n' "$HOTSPOT_SSID" "$HOTSPOT_PW" \
        > "$HOTSPOT_PW_FILE"
    chmod 600 "$HOTSPOT_PW_FILE"
    echo -e "${YELLOW}      Generated PSK: $HOTSPOT_PW${NC}"
    echo -e "${YELLOW}      (saved to $HOTSPOT_PW_FILE; retrieve with"
    echo -e "${YELLOW}       sudo ais-wifi-cli show-hotspot)${NC}"
else
    # Preserve the existing PSK — we never want to invalidate working
    # client devices on re-install.  But normalise the SSID line in case
    # the file was written by an older installer (which shipped
    # SSID: AIS-WiFi-Manager).
    sed -i "s/^SSID:.*/SSID:     ${HOTSPOT_SSID}/" "$HOTSPOT_PW_FILE" || true
    HOTSPOT_PW="$(awk '/^Password:/ {print $2}' "$HOTSPOT_PW_FILE")"
    echo -e "${YELLOW}      Preserving existing PSK from $HOTSPOT_PW_FILE${NC}"
fi

# 7b. Materialise the NetworkManager AP profile.
if ! ip link show wlan1 >/dev/null 2>&1; then
    echo -e "${YELLOW}      wlan1 not present — skipping AP profile creation."
    echo -e "      Plug the USB Wi-Fi adapter in and re-run this installer"
    echo -e "      to enable the AP (or run: sudo ais-wifi-cli hotspot diagnose).${NC}"
else
    WLAN1_MAC="$(cat /sys/class/net/wlan1/address)"
    echo -e "${GREEN}      wlan1 detected (MAC $WLAN1_MAC) — creating AP profile.${NC}"

    # Heads-up only: not all USB chipsets support AP mode.  Most modern ones
    # do (RTL8188, MT7601/76xx, RT5370, etc.); if `iw list` shows no AP
    # interface mode anywhere we warn but still try — `nmcli c up` will
    # tell the truth either way.
    if ! iw list 2>/dev/null | grep -q '\* AP'; then
        echo -e "${YELLOW}      Warning: no radio reports AP-mode support."
        echo -e "      Activation may fail; check your dongle's chipset.${NC}"
    fi

    # Idempotent recreate.  This is what makes re-running the installer
    # always converge: previous profile is wiped, new one written with
    # the current PSK and SSID.
    nmcli c delete ais-hotspot 2>/dev/null || true
    nmcli c add type wifi con-name ais-hotspot \
        connection.interface-name wlan1 \
        802-11-wireless.mac-address "$WLAN1_MAC" \
        802-11-wireless.mode ap \
        802-11-wireless.band bg \
        802-11-wireless.channel 6 \
        ssid "$HOTSPOT_SSID" \
        ipv4.method shared \
        ipv4.addresses 192.168.4.1/24 \
        ipv6.method ignore \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.psk "$HOTSPOT_PW" \
        connection.autoconnect yes \
        connection.autoconnect-retries 0 \
        connection.autoconnect-priority 100 \
        ipv4.dhcp-leasetime 3600 \
        >/dev/null
    # Notes on the hardening flags:
    #   * autoconnect-retries 0  → never give up.  Default is 4, after
    #     which NM gives up on autoconnect for the boot session and
    #     leaves wlan1 idle.  We want the AP to come back forever.
    #   * autoconnect-priority 100 → win every autoconnect race.  If a
    #     future user accidentally creates a second profile bound to
    #     wlan1 (e.g. a STA test profile), this one still wins.
    #   * ipv4.dhcp-leasetime 3600 → 1-hour leases instead of NM's
    #     default 1-hour-but-clients-renew-every-30-min.  Stops phones
    #     from re-running their captive-portal probe every renewal,
    #     which is what surfaces the "Unable to join" error if our
    #     AP-side dnsmasq has a bad moment.

    # If the connection was already up (e.g. on a re-install), the new
    # dnsmasq-shared.d snippet won't take effect until the per-AP
    # dnsmasq is re-spawned.  Bouncing the connection is the cleanest
    # way: down + up = NM kills its dnsmasq child and respawns it,
    # picking up our /etc/NetworkManager/dnsmasq-shared.d/00-ais-upstream.conf
    nmcli c down ais-hotspot >/dev/null 2>&1 || true


    # 7c. Bring it up and verify.  We poll the active-state for up to 15 s
    #     because nmcli can return before NM finishes IP-config.  On
    #     failure we dump the NM journal so the user (or future-you) can
    #     see the real reason without having to run journalctl manually.
    echo -e "${GREEN}      Activating ais-hotspot…${NC}"
    nmcli c up ais-hotspot >/dev/null 2>&1 || true

    AP_OK=0
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        if nmcli -t -f NAME,STATE c show --active 2>/dev/null \
                | grep -qx 'ais-hotspot:activated'; then
            AP_OK=1; break
        fi
        sleep 1
    done

    if [ "$AP_OK" = 1 ]; then
        echo -e "${GREEN}      → AP is up. SSID '$HOTSPOT_SSID' on 192.168.4.1${NC}"
    else
        echo -e "${RED}      → AP failed to activate. NetworkManager journal tail:${NC}"
        journalctl -u NetworkManager -n 30 --no-pager | tail -n 30 || true
        echo -e "${RED}      Common causes:${NC}"
        echo -e "${RED}        • dnsmasq.service running (we disable it but check)."
        echo -e "        • USB dongle does not support AP mode."
        echo -e "        • wlan1 unmanaged in NetworkManager.${NC}"
        echo -e "${YELLOW}      Run 'sudo ais-wifi-cli hotspot diagnose' for a full report.${NC}"
        exit 1
    fi
fi


# -- 8. systemd unit ------------------------------------------------------
echo -e "${GREEN}[8/9] Installing systemd unit…${NC}"
install -m 0644 "$SCRIPT_DIR/service/ais-wifi-manager.service" \
    /etc/systemd/system/${SERVICE_NAME}.service
systemctl daemon-reload
systemctl enable --now ${PS_SERVICE_NAME}.service
systemctl enable --now ${SERVICE_NAME}.service

# -- 9. Optional Tailscale ------------------------------------------------
if [ "$WITH_TAILSCALE" = 1 ]; then
    echo -e "${GREEN}[9/9] Installing Tailscale…${NC}"
    if ! command -v tailscale >/dev/null 2>&1; then
        curl -fsSL https://tailscale.com/install.sh | sh
    fi

    # Tailscale's installer is allowed to drop a NetworkManager conf.d
    # snippet that says `dns=systemd-resolved`.  On RPi OS *Lite*,
    # systemd-resolved isn't enabled — so on the next reboot NM fails
    # to start, no Wi-Fi, no AP, the box is unreachable until you bring
    # a monitor over.  Defended against in three places:
    #
    #   * Step 6 wrote 00-dns.conf with `dns=default` (newer Tailscale
    #     installers respect an existing dns= setting and skip writing
    #     their own snippet).
    #   * Belt: scrub /etc/NetworkManager/conf.d/tailscale.conf if it
    #     was written anyway (older Tailscale, or our 00-dns.conf was
    #     missing for some reason).
    #   * Braces: post-flight `systemctl is-active NetworkManager` below.
    if [ -f /etc/NetworkManager/conf.d/tailscale.conf ]; then
        echo -e "${YELLOW}      Removing /etc/NetworkManager/conf.d/tailscale.conf"
        echo -e "      (Tailscale set dns=systemd-resolved which breaks NM on"
        echo -e "      RPi OS Lite — see install.sh step 6 for details).${NC}"
        rm -f /etc/NetworkManager/conf.d/tailscale.conf
        nm_reload || exit 1
    fi

    # Belt-and-braces: validate every conf.d file present (including any
    # written by Tailscale) so we'd catch a future regression of the same
    # `;`-comment / unknown-key class of bug *before* it hits the next
    # reboot.  Don't auto-delete — refuse to continue and let a human
    # decide.
    for f in /etc/NetworkManager/conf.d/*.conf; do
        [ -f "$f" ] || continue
        validate_nm_conf "$f" || {
            echo -e "${RED}      Refusing to leave you with an unbootable system.${NC}"
            exit 1
        }
    done

    # Confirm NM is still healthy after the Tailscale install.
    if ! systemctl is-active --quiet NetworkManager; then
        echo -e "${RED}      NetworkManager is not active after Tailscale install!${NC}"
        echo "      Last 30 NM journal lines:"
        journalctl -u NetworkManager -n 30 --no-pager | tail -n 30 || true
        echo -e "${RED}      Refusing to leave you with an unbootable system.${NC}"
        exit 1
    fi


    echo -e "${YELLOW}      Run 'sudo tailscale up --ssh' afterwards to join your tail-net.${NC}"
else
    echo -e "${GREEN}[9/9] Skipping Tailscale (use --with-tailscale to install).${NC}"
fi


# -- Post-flight check ----------------------------------------------------
# Loud failure beats silent failure.  If the unit didn't come up, dump the
# last 30 journal lines and exit non-zero so packaging tools / CI / humans
# notice immediately.
echo -e "${GREEN}      Verifying ${SERVICE_NAME}…${NC}"
sleep 2
if systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo -e "${GREEN}      → ${SERVICE_NAME} is active.${NC}"
else
    echo -e "${RED}=========================================${NC}"
    echo -e "${RED} ${SERVICE_NAME} is NOT running after install.${NC}"
    echo -e "${RED}=========================================${NC}"
    echo "Last 30 lines from the unit's journal:"
    journalctl -xeu "${SERVICE_NAME}" -n 30 --no-pager || true
    echo
    echo "Once the cause is fixed, re-run: sudo ./install.sh"
    exit 1
fi

# -- Done -----------------------------------------------------------------
IP="$(hostname -I | awk '{print $1}')"
cat <<EOF

${GREEN}=========================================${NC}
${GREEN} Installation complete${NC}
${GREEN}=========================================${NC}

  Web UI:   http://${IP:-AIS.local}/    (or http://192.168.4.1 in hotspot mode)
  CLI:      sudo ais-wifi-cli           (interactive menu)
            sudo ais-wifi-cli reset-password
            sudo ais-wifi-cli show-hotspot
            ais-wifi-cli health

  Default login (FORCED CHANGE on first sign-in):
    User:     JLBMaritime
    Password: Admin

  Hotspot password: see $HOTSPOT_PW_FILE
                    or run: sudo ais-wifi-cli show-hotspot

  Service control:
    systemctl status  ${SERVICE_NAME}
    journalctl -u     ${SERVICE_NAME} -f

EOF
