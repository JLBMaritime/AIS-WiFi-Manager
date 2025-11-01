#!/bin/bash
# AIS-WiFi Manager Uninstallation Script

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration Variables
INSTALL_DIR="/opt/ais-wifi-manager"
SERVICE_NAME="ais-wifi-manager"

echo "========================================="
echo "AIS-WiFi Manager Uninstallation"
echo "========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Error: This script must be run as root (use sudo)${NC}"
    exit 1
fi

echo -e "${YELLOW}This will remove AIS-WiFi Manager from your system.${NC}"
read -p "Continue with un installation? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

echo -e "${GREEN}Step 1: Stopping and disabling service...${NC}"
systemctl stop ${SERVICE_NAME} 2>/dev/null || true
systemctl disable ${SERVICE_NAME} 2>/dev/null || true

echo -e "${GREEN}Step 2: Removing service file...${NC}"
rm -f /etc/systemd/system/${SERVICE_NAME}.service
systemctl daemon-reload

echo -e "${GREEN}Step 3: Removing installation directory...${NC}"
rm -rf $INSTALL_DIR

echo -e "${GREEN}Step 4: Cleaning up hotspot configuration...${NC}"
read -p "Remove hotspot configuration? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    systemctl stop hostapd 2>/dev/null || true
    systemctl stop dnsmasq 2>/dev/null || true
    systemctl disable hostapd 2>/dev/null || true
    systemctl disable dnsmasq 2>/dev/null || true
    
    rm -f /etc/hostapd/hostapd.conf
    rm -f /etc/dnsmasq.conf
    
    nmcli connection delete Hotspot 2>/dev/null || true
    
    echo -e "${GREEN}Hotspot configuration removed${NC}"
fi

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Uninstallation Complete!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo "AIS-WiFi Manager has been removed from your system."
echo ""
