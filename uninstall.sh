#!/bin/bash
# AIS-WiFi Manager — uninstall script.
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

INSTALL_DIR="/opt/ais-wifi-manager"
SERVICE_NAME="ais-wifi-manager"
PS_SERVICE_NAME="ais-wifi-powersave-off"

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Run with sudo.${NC}"; exit 1
fi

echo "========================================="
echo " AIS-WiFi Manager — uninstallation"
echo "========================================="

read -p "Continue with uninstallation? (y/n) " -n 1 -r REPLY
echo
[[ "$REPLY" =~ ^[Yy]$ ]] || exit 1

echo -e "${GREEN}[1/4] Stopping services…${NC}"
systemctl stop    ${SERVICE_NAME}    2>/dev/null || true
systemctl disable ${SERVICE_NAME}    2>/dev/null || true
systemctl stop    ${PS_SERVICE_NAME} 2>/dev/null || true
systemctl disable ${PS_SERVICE_NAME} 2>/dev/null || true
rm -f /etc/systemd/system/${SERVICE_NAME}.service
rm -f /etc/systemd/system/${PS_SERVICE_NAME}.service
systemctl daemon-reload

echo -e "${GREEN}[2/4] Removing power-save drop-in…${NC}"
rm -f /etc/NetworkManager/conf.d/wifi-powersave-off.conf

echo -e "${GREEN}[3/4] Removing CLI shim and install dir…${NC}"
rm -f /usr/local/bin/ais-wifi-cli
read -p "Also delete $INSTALL_DIR (config + saved networks)? (y/n) " -n 1 -r
echo
if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    rm -rf "$INSTALL_DIR"
fi

echo -e "${GREEN}[4/4] Hotspot cleanup (optional)…${NC}"
read -p "Remove hotspot configuration (NM connection 'ais-hotspot')? (y/n) " -n 1 -r
echo
if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    # Tear down and delete the NM AP profile we created in install.sh step 7.
    nmcli connection down   ais-hotspot 2>/dev/null || true
    nmcli connection delete ais-hotspot 2>/dev/null || true
    # Older installs may have left these legacy units around — clean them
    # too, since we no longer use hostapd or the system dnsmasq.service.
    systemctl stop    hostapd dnsmasq 2>/dev/null || true
    systemctl disable hostapd dnsmasq 2>/dev/null || true
    rm -f /etc/hostapd/hostapd.conf /etc/dnsmasq.conf
    # Legacy connection name from a previous AP design.
    nmcli connection delete Hotspot 2>/dev/null || true
fi


echo -e "${GREEN}Done.${NC}"
