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
apt-get install -y hostapd dnsmasq network-manager
apt-get install -y avahi-daemon
apt-get install -y git

echo -e "${GREEN}Step 3: Setting hostname to ${HOSTNAME}...${NC}"
hostnamectl set-hostname "$HOSTNAME"
sed -i "s/127.0.1.1.*/127.0.1.1\t$HOSTNAME/" /etc/hosts

echo -e "${GREEN}Step 4: Configuring

 hotspot on wlan1...${NC}"

# Stop services
systemctl stop hostapd 2>/dev/null || true
systemctl stop dnsmasq 2>/dev/null || true

# Configure hostapd
cat > /etc/hostapd/hostapd.conf << EOF
interface=wlan1
driver=nl80211
ssid=$HOTSPOT_SSID
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=$HOTSPOT_PASSWORD
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF

# Point hostapd to config
sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

# Configure dnsmasq
cat > /etc/dnsmasq.conf << EOF
interface=wlan1
dhcp-range=$HOTSPOT_IP,192.168.4.20,255.255.255.0,24h
domain=local
address=/AIS.local/$HOTSPOT_IP
EOF

# Configure wlan1 static IP
nmcli connection delete Hotspot 2>/dev/null || true
nmcli connection add type wifi ifname wlan1 con-name Hotspot autoconnect yes ssid "$HOTSPOT_SSID" mode ap
nmcli connection modify Hotspot 802-11-wireless.band bg
nmcli connection modify Hotspot 802-11-wireless.channel 7
nmcli connection modify Hotspot 802-11-wireless-security.key-mgmt wpa-psk
nmcli connection modify Hotspot 802-11-wireless-security.psk "$HOTSPOT_PASSWORD"
nmcli connection modify Hotspot ipv4.method manual
nmcli connection modify Hotspot ipv4.address $HOTSPOT_IP/24
nmcli connection modify Hotspot connection.autoconnect yes

echo -e "${GREEN}Step 5: Creating installation directory...${NC}"
mkdir -p $INSTALL_DIR
cp -r ./* $INSTALL_DIR/
cd $INSTALL_DIR

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
systemctl unmask hostapd
systemctl enable hostapd
systemctl enable dnsmasq
systemctl enable avahi-daemon
systemctl enable ${SERVICE_NAME}

# Start hotspot services
systemctl start hostapd
systemctl start dnsmasq
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
