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

# -- Colours --------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

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
    git ca-certificates libcap2-bin
systemctl disable --now dnsmasq 2>/dev/null || true
systemctl disable --now hostapd 2>/dev/null || true


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

# -- 6. Wi-Fi power-save off ---------------------------------------------
echo -e "${GREEN}[6/9] Disabling Wi-Fi power-save on wlan0…${NC}"
install -m 0644 "$SCRIPT_DIR/service/wifi-powersave-off.conf" \
    /etc/NetworkManager/conf.d/wifi-powersave-off.conf
install -m 0644 "$SCRIPT_DIR/service/ais-wifi-powersave-off.service" \
    /etc/systemd/system/${PS_SERVICE_NAME}.service

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
        >/dev/null

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
    echo -e "${YELLOW}      Run 'sudo tailscale up' afterwards to join your tail-net.${NC}"
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
