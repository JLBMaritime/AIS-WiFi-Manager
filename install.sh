#!/bin/bash
# AIS-WiFi Manager Installation Script
# For Raspberry Pi 4B with Raspberry Pi OS (64-bit Bookworm)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration Variables
INSTALL_DIR="/opt/ais-wifi-manager"
SERVICE_NAME="ais-wifi-manager"
HOTSPOT_SSID="JLBMaritime-AIS"
HOTSPOT_PASSWORD="Admin123"
HOTSPOT_IP="192.168.4.1"
HOSTNAME="AIS"

echo "========================================="
echo "AIS-WiFi Manager Installation"
echo "========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Error: This script must be run as root (use sudo)${NC}"
    exit 1
fi

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo; then
    echo -e "${YELLOW}Warning: This does not appear to be a Raspberry Pi${NC}"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo -e "${GREEN}Step 1: Updating system packages...${NC}"
apt-get update
apt-get upgrade -y

echo -e "${GREEN}Step 2: Installing system dependencies...${NC}"
apt-get install -y python3 python3-pip python3-venv
apt-get install -y network-manager
apt-get install -y avahi-daemon
apt-get install -y git

echo -e "${GREEN}Step 3: Setting hostname to ${HOSTNAME}...${NC}"
hostnamectl set-hostname "$HOSTNAME"
sed -i "s/127.0.1.1.*/127.0.1.1\t$HOSTNAME/" /etc/hosts

echo -e "${GREEN}Step 4: Configuring hotspot on wlan1 with NetworkManager...${NC}"

# Stop and disable any conflicting services
systemctl stop hostapd 2>/dev/null || true
systemctl disable hostapd 2>/dev/null || true
systemctl stop dnsmasq 2>/dev/null || true
systemctl disable dnsmasq 2>/dev/null || true

# Configure NetworkManager hotspot with built-in DHCP
nmcli connection delete Hotspot 2>/dev/null || true
nmcli connection add type wifi ifname wlan1 con-name Hotspot autoconnect yes ssid "$HOTSPOT_SSID" mode ap \
    802-11-wireless.band bg \
    802-11-wireless.channel 7 \
    802-11-wireless-security.key-mgmt wpa-psk \
    802-11-wireless-security.psk "$HOTSPOT_PASSWORD" \
    ipv4.method shared \
    ipv4.address $HOTSPOT_IP/24

# Activate the hotspot connection
nmcli connection up Hotspot

echo -e "${GREEN}Step 5: Creating installation directory...${NC}"
mkdir -p $INSTALL_DIR
cp -r ./* $INSTALL_DIR/
cd $INSTALL_DIR

# Fix line endings (convert CRLF to LF for Unix compatibility)
sed -i 's/\r$//' $INSTALL_DIR/cli/ais_wifi_cli.py

# Make CLI executable
chmod +x $INSTALL_DIR/cli/ais_wifi_cli.py

# Create symlink for easy CLI access
ln -sf $INSTALL_DIR/cli/ais_wifi_cli.py /usr/local/bin/ais-wifi-cli

echo -e "${GREEN}Step 6: Installing Python dependencies...${NC}"
pip3 install --break-system-packages -r requirements.txt || pip3 install -r requirements.txt

echo -e "${GREEN}Step 7: Creating systemd service...${NC}"
cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=AIS-WiFi Manager Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/run.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}Step 8: Enabling and starting services...${NC}"
systemctl daemon-reload
systemctl enable avahi-daemon
systemctl enable ${SERVICE_NAME}
systemctl start avahi-daemon

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo "The system needs to reboot to apply all changes."
echo ""
echo "After reboot:"
echo "  1. Connect to WiFi hotspot: $HOTSPOT_SSID"
echo "  2. Password: $HOTSPOT_PASSWORD"
echo "  3. Open browser to: http://${HOSTNAME}.local or http://$HOTSPOT_IP"
echo "  4. Login with:"
echo "     Username: JLBMaritime"
echo "     Password: Admin"
echo ""
echo "The service will start automatically on boot."
echo ""
read -p "Reboot now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    reboot
fi
