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
apt-get install -y -qq --no-install-recommends \
    python3 python3-venv python3-pip python3-dev \
    network-manager hostapd dnsmasq iw wireless-tools iputils-ping \
    git ca-certificates libcap2-bin

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
echo -e "${GREEN}      Granting cap_net_bind_service to venv python…${NC}"
setcap 'cap_net_bind_service=+ep' "$INSTALL_DIR/.venv/bin/python3" || true

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

# -- 7. Hotspot fallback (192.168.4.1 SSID=AIS-WiFi-Manager) -------------
echo -e "${GREEN}[7/9] Configuring fallback hotspot…${NC}"
if [ ! -f "$HOTSPOT_PW_FILE" ]; then
    HOTSPOT_PW="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)"
    cat > "$HOTSPOT_PW_FILE" <<EOF
SSID:     AIS-WiFi-Manager
Password: $HOTSPOT_PW
EOF
    chmod 600 "$HOTSPOT_PW_FILE"
    echo -e "${YELLOW}      Generated hotspot password: $HOTSPOT_PW${NC}"
    echo -e "${YELLOW}      (saved to $HOTSPOT_PW_FILE; retrieve with"
    echo -e "${YELLOW}       sudo ais-wifi-cli show-hotspot)${NC}"
else
    echo -e "${YELLOW}      Existing hotspot config preserved.${NC}"
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
