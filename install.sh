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

# -- 7. Hotspot fallback (192.168.4.1 SSID=AIS-WiFi-Manager) -------------
# IMPORTANT (fresh-install gotcha):
#   The original generator was
#       tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16
#   which crashed every fresh install on Bookworm because:
#       head -c 16 closes the pipe early
#       → tr is killed by SIGPIPE (exit 141)
#       → `set -o pipefail` (top of file) propagates that 141
#       → `set -e` aborts the entire installer silently between [7/9] and [8/9]
#   We use `head -c 64 …` (a fixed *upstream* read that exits 0) and
#   `cut -c1-16` for the trim, so no command in the pipeline ever sees a
#   broken pipe.  We also wrap it in a subshell with `+pipefail` belt-and-
#   braces in case anyone adds another head/cut/awk-piped block here later.
echo -e "${GREEN}[7/9] Configuring fallback hotspot…${NC}"
if [ ! -f "$HOTSPOT_PW_FILE" ]; then
    HOTSPOT_PW="$(
        set +o pipefail
        head -c 64 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9' | cut -c1-16
    )"
    if [ -z "$HOTSPOT_PW" ] || [ "${#HOTSPOT_PW}" -lt 16 ]; then
        # Extremely unlikely fallback (e.g. /dev/urandom missing in chroot).
        HOTSPOT_PW="$(date +%s%N | sha256sum | cut -c1-16)"
    fi
    printf 'SSID:     AIS-WiFi-Manager\nPassword: %s\n' "$HOTSPOT_PW" \
        > "$HOTSPOT_PW_FILE"
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
