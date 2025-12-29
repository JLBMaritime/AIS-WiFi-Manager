#!/bin/bash
################################################################################
# ADS-B Wi-Fi Manager Installation Script
# JLBMaritime - Raspberry Pi 4B Installation
################################################################################

set -e  # Exit on error

echo "=========================================="
echo "ADS-B Wi-Fi Manager Installation"
echo "JLBMaritime - Raspberry Pi Setup"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "ERROR: Please run as root (sudo ./install.sh)"
    exit 1
fi

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-$USER}
if [ "$ACTUAL_USER" = "root" ]; then
    echo "ERROR: Please run with sudo, not as root user"
    exit 1
fi

INSTALL_DIR="/home/$ACTUAL_USER/AIS-WiFi-Manager"

echo "Installing for user: $ACTUAL_USER"
echo "Installation directory: $INSTALL_DIR"
echo ""

# Update system
echo "[1/10] Updating system packages..."
apt-get update
apt-get upgrade -y

# Install required packages
echo "[2/10] Installing required packages..."
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    hostapd \
    dnsmasq \
    avahi-daemon \
    wireless-tools \
    wpasupplicant \
    git \
    curl

# Install FlightAware dump1090-fa
echo "[3/10] Installing dump1090-fa..."
if ! command -v dump1090-fa &> /dev/null; then
    wget -O - https://www.flightaware.com/adsb/piaware/files/packages/pool/piaware/f/flightaware-apt-repository/flightaware-apt-repository_1.2_all.deb > /tmp/piaware-repo.deb || true
    if [ -f /tmp/piaware-repo.deb ]; then
        dpkg -i /tmp/piaware-repo.deb || true
        apt-get update
        apt-get install -y dump1090-fa
    else
        echo "WARNING: Could not install dump1090-fa automatically. Please install manually."
    fi
else
    echo "dump1090-fa already installed"
fi

# Install Python packages
echo "[4/10] Installing Python packages..."
pip3 install flask --break-system-packages || pip3 install flask

# Copy application files
echo "[5/10] Copying application files..."
if [ -d "$INSTALL_DIR" ]; then
    echo "Backing up existing installation..."
    mv "$INSTALL_DIR" "${INSTALL_DIR}.backup.$(date +%Y%m%d_%H%M%S)"
fi

mkdir -p "$INSTALL_DIR"
cp -r "$(dirname "$0")"/* "$INSTALL_DIR/"
chown -R $ACTUAL_USER:$ACTUAL_USER "$INSTALL_DIR"

# Create config directory if it doesn't exist
mkdir -p "$INSTALL_DIR/config"
mkdir -p "$INSTALL_DIR/logs"
chown -R $ACTUAL_USER:$ACTUAL_USER "$INSTALL_DIR/config"
chown -R $ACTUAL_USER:$ACTUAL_USER "$INSTALL_DIR/logs"

# Configure Wi-Fi Hotspot on wlan1
echo "[6/10] Configuring Wi-Fi hotspot on wlan1..."

# Ensure network interfaces directory exists
mkdir -p /etc/network/interfaces.d/

# Configure hostapd
cat > /etc/hostapd/hostapd.conf << EOF
# JLBMaritime ADS-B Hotspot Configuration
interface=wlan1
driver=nl80211
ssid=JLBMaritime-ADSB
hw_mode=g
channel=1
ieee80211d=1
country_code=GB
ieee80211n=1
wmm_enabled=1
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=3
wpa_passphrase=Admin123
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP TKIP
rsn_pairwise=CCMP
beacon_int=100
dtim_period=2
EOF

# Point hostapd to config file
sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd || echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' >> /etc/default/hostapd

# Configure dnsmasq
mv /etc/dnsmasq.conf /etc/dnsmasq.conf.backup || true
cat > /etc/dnsmasq.conf << EOF
# JLBMaritime ADS-B DNS/DHCP Configuration
interface=wlan1
dhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,24h
domain=local
address=/ADS-B.local/192.168.4.1
EOF

# Configure wlan1 static IP
cat > /etc/network/interfaces.d/wlan1 << EOF
auto wlan1
iface wlan1 inet static
    address 192.168.4.1
    netmask 255.255.255.0
EOF

# Ensure wlan0 is managed by wpa_supplicant
cat > /etc/network/interfaces.d/wlan0 << EOF
allow-hotplug wlan0
iface wlan0 inet dhcp
    wpa-conf /etc/wpa_supplicant/wpa_supplicant.conf
EOF

# Prevent wpa_supplicant from managing wlan1 (hotspot interface)
echo "Preventing wpa_supplicant from managing wlan1..."

# Remove any saved networks for wlan1 from wpa_supplicant
if [ -f /etc/wpa_supplicant/wpa_supplicant-wlan1.conf ]; then
    rm -f /etc/wpa_supplicant/wpa_supplicant-wlan1.conf
fi

# Create wpa_supplicant config that excludes wlan1
cat > /etc/wpa_supplicant/wpa_supplicant.conf << EOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=GB

# Only manage wlan0, not wlan1
EOF

# Stop wpa_supplicant from auto-starting for wlan1
systemctl disable wpa_supplicant@wlan1 2>/dev/null || true

# Prevent NetworkManager from managing wlan1
echo "[7/10] Configuring NetworkManager to ignore wlan1..."
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/unmanage-wlan1.conf << EOF
[keyfile]
unmanaged-devices=interface-name:wlan1
EOF

# Restart NetworkManager if it's running
if systemctl is-active NetworkManager &>/dev/null; then
    echo "Restarting NetworkManager..."
    systemctl restart NetworkManager
fi

# Configure mDNS (Avahi)
echo "[8/10] Configuring mDNS for ADS-B.local resolution..."
systemctl enable avahi-daemon
systemctl start avahi-daemon

# Set hostname
hostnamectl set-hostname ADS-B

# Update hosts file
cat > /etc/hosts << EOF
127.0.0.1       localhost
127.0.1.1       ADS-B
192.168.4.1     ADS-B.local

::1             localhost ip6-localhost ip6-loopback
ff02::1         ip6-allnodes
ff02::2         ip6-allrouters
EOF

# Enable IP forwarding (optional - for internet sharing)
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p

# Install systemd services
echo "[9/10] Installing systemd services..."

# Install wlan1 configuration service (runs before hostapd)
cp "$INSTALL_DIR/services/wlan1-config.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable wlan1-config.service

# Install ADS-B Server service
cp "$INSTALL_DIR/services/adsb-server.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable adsb-server.service

# Install Web Manager service
cp "$INSTALL_DIR/services/web-manager.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable web-manager.service

# Configure sudo permissions for web interface
echo "[10/10] Configuring sudo permissions..."
cat > /etc/sudoers.d/adsb-wifi-manager << EOF
# Allow web interface to control services and Wi-Fi
www-data ALL=(ALL) NOPASSWD: /usr/bin/systemctl start adsb-server
www-data ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop adsb-server
www-data ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart adsb-server
www-data ALL=(ALL) NOPASSWD: /usr/bin/systemctl is-active adsb-server
www-data ALL=(ALL) NOPASSWD: /usr/bin/systemctl show adsb-server
www-data ALL=(ALL) NOPASSWD: /usr/sbin/iwlist
www-data ALL=(ALL) NOPASSWD: /usr/sbin/iwconfig
www-data ALL=(ALL) NOPASSWD: /usr/sbin/wpa_cli
www-data ALL=(ALL) NOPASSWD: /usr/sbin/dhclient
www-data ALL=(ALL) NOPASSWD: /usr/bin/ip
root ALL=(ALL) NOPASSWD: /usr/bin/systemctl start adsb-server
root ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop adsb-server
root ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart adsb-server
root ALL=(ALL) NOPASSWD: /usr/bin/systemctl is-active adsb-server
root ALL=(ALL) NOPASSWD: /usr/bin/systemctl show adsb-server
EOF
chmod 0440 /etc/sudoers.d/adsb-wifi-manager

# Start services
echo "[11/11] Starting services..."

# Enable and start hotspot
systemctl unmask hostapd
systemctl enable hostapd
systemctl enable dnsmasq

# Bring up wlan1 interface and disable power management
echo "Configuring wlan1 interface..."
ip link set wlan1 down || true
sleep 2
ip link set wlan1 up || true
sleep 1
ip addr add 192.168.4.1/24 dev wlan1 2>/dev/null || true

# Disable power management on wlan1 for stability
iw dev wlan1 set power_save off 2>/dev/null || true
iwconfig wlan1 power off 2>/dev/null || true

# Give wlan1 time to stabilize before starting hostapd
echo "Waiting for wlan1 to stabilize..."
sleep 3

# Start hostapd and dnsmasq with delay
systemctl start hostapd
sleep 2
systemctl start dnsmasq

# Wait for dump1090-fa to be ready (if installed)
if systemctl is-enabled dump1090-fa &>/dev/null; then
    echo "Waiting for dump1090-fa to start..."
    sleep 5
fi

# Start application services with delays
systemctl start adsb-server.service
sleep 2
systemctl start web-manager.service

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "Setup Summary:"
echo "  - Hostname: ADS-B"
echo "  - Hotspot SSID: JLBMaritime-ADSB"
echo "  - Hotspot Password: Admin123"
echo "  - Hotspot IP: 192.168.4.1"
echo "  - Web Interface: http://ADS-B.local or http://192.168.4.1"
echo "  - Web Login: JLBMaritime / Admin"
echo ""
echo "Services Status:"
systemctl is-active hostapd && echo "  ✓ Hotspot: Running" || echo "  ✗ Hotspot: Not Running"
systemctl is-active dnsmasq && echo "  ✓ DNS/DHCP: Running" || echo "  ✗ DNS/DHCP: Not Running"
systemctl is-active adsb-server && echo "  ✓ ADS-B Server: Running" || echo "  ✗ ADS-B Server: Not Running"
systemctl is-active web-manager && echo "  ✓ Web Manager: Running" || echo "  ✗ Web Manager: Not Running"
systemctl is-active dump1090-fa && echo "  ✓ dump1090-fa: Running" || echo "  ✗ dump1090-fa: Not Running (install manually if needed)"
echo ""
echo "Next Steps:"
echo "  1. Connect to Wi-Fi hotspot 'JLBMaritime-ADSB' (password: Admin123)"
echo "  2. Open browser to http://ADS-B.local"
echo "  3. Login with JLBMaritime / Admin"
echo "  4. Configure your internet Wi-Fi in the Wi-Fi Manager tab"
echo "  5. Configure ADS-B endpoints in the ADS-B Configuration tab"
echo "  6. Place logo.png file in: $INSTALL_DIR/web_interface/static/"
echo ""
echo "Reboot recommended: sudo reboot"
echo "=========================================="
