# ADS-B Wi-Fi Manager

**JLBMaritime - Integrated ADS-B Data Management System**

A comprehensive solution for Raspberry Pi 4B that combines ADS-B aircraft tracking with a powerful web-based WiFi management interface.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [System Requirements](#system-requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Web Interface](#web-interface)
- [Command Line Tools](#command-line-tools)
- [Troubleshooting](#troubleshooting)
- [Architecture](#architecture)
- [License](#license)

---

## 🎯 Overview

This system provides a complete ADS-B (Automatic Dependent Surveillance-Broadcast) data reception, filtering, and forwarding solution with an integrated WiFi management interface. Perfect for maritime or aviation tracking applications where you need reliable data forwarding and easy network configuration.

### What it Does

1. **Receives ADS-B Data**: Captures aircraft tracking data via FlightAware SDR USB dongle
2. **Filters Aircraft**: Optionally filters by specific ICAO aircraft IDs
3. **Forwards Data**: Sends filtered data to configured TCP endpoints
4. **Manages WiFi**: Provides hotspot and web interface for network management
5. **Centralized Control**: All configuration via responsive web interface

---

## ✨ Features

### ADS-B Server
- ✅ Receives SBS1 format data from dump1090-fa
- ✅ Configurable ICAO aircraft filter (specific IDs or all aircraft)
- ✅ Multiple TCP endpoint forwarding
- ✅ Automatic reconnection on connection loss
- ✅ 72-hour automatic log rotation
- ✅ Runs as systemd service (auto-start on boot)

### WiFi Manager
- ✅ Built-in hotspot (wlan1) for configuration access
- ✅ Scan and connect to WiFi networks (wlan0)
- ✅ Save and manage network profiles
- ✅ Network diagnostics and ping tests
- ✅ mDNS support (ADS-B.local domain)

### Web Interface
- ✅ **Dashboard**: System status overview
- ✅ **WiFi Manager**: Network configuration
- ✅ **ADS-B Configuration**: Endpoints and filters
- ✅ **Logs & Troubleshooting**: Live log viewer
- ✅ **Settings**: Password, backup/restore
- ✅ Responsive design (desktop and mobile)
- ✅ Secure authentication

---

## 🖥️ System Requirements

### Hardware
- **Raspberry Pi 4B** (2GB RAM minimum)
- **Two WiFi interfaces**: wlan0 and wlan1
- **FlightAware SDR USB stick** with antenna
- **MicroSD card** (16GB minimum)

### Software
- **OS**: Raspberry Pi OS 64-bit (Bookworm) - Lite or Desktop
- **Python**: 3.9 or higher (included in OS)
- **Internet connection**: For initial setup and dump1090-fa installation

---

## 📦 Installation

### Quick Install

1. **Download the repository** to your Raspberry Pi:
   ```bash
   cd /home/JLBMaritime
   git clone <repository-url> adsb-wifi-manager
   cd adsb-wifi-manager
   ```

2. **Make installation script executable**:
   ```bash
   chmod +x install.sh
   ```

3. **Run installation** (requires sudo):
   ```bash
   sudo ./install.sh
   ```

4. **Reboot the system**:
   ```bash
   sudo reboot
   ```

### What Gets Installed

The installation script will:
- Update system packages
- Install Python3 and required libraries (Flask)
- Install and configure dump1090-fa for ADS-B reception
- Install hostapd and dnsmasq for WiFi hotspot
- Configure Avahi for mDNS (ADS-B.local)
- Set up systemd services for auto-start
- Configure wlan1 as hotspot (192.168.4.1)
- Configure wlan0 for internet connectivity
- Set hostname to "ADS-B"

### Installation Time
Approximately **15-30 minutes** depending on internet speed.

---

## ⚙️ Configuration

### Default Credentials

**Hotspot WiFi**:
- **SSID**: `JLBMaritime-ADSB`
- **Password**: `Admin123`

**Web Interface**:
- **URL**: `http://ADS-B.local:5000` or `http://192.168.4.1:5000`
- **Username**: `JLBMaritime`
- **Password**: `Admin`

### Initial Setup Steps

1. **Connect to Hotspot**:
   - Look for WiFi network "JLBMaritime-ADSB"
   - Enter password: `Admin123`

2. **Access Web Interface**:
   - Open browser to `http://ADS-B.local`
   - Login with JLBMaritime / Admin

3. **Configure Internet WiFi**:
   - Go to "WiFi Manager" tab
   - Click "Scan Networks"
   - Connect to your internet WiFi

4. **Configure ADS-B**:
   - Go to "ADS-B Configuration" tab
   - Set filter mode (All or Specific ICAOs)
   - Add TCP endpoints (IP:Port)
   - Click "Save Configuration"

5. **Add Logo** (Optional):
   - Place `logo.png` in `/home/JLBMaritime/adsb-wifi-manager/web_interface/static/`

---

## 🌐 Web Interface

### Dashboard Tab
Monitor system status in real-time:
- ADS-B server status (Running/Stopped, uptime)
- WiFi connection info (SSID, IP, signal strength)
- System hostname

### WiFi Manager Tab
Manage network connections:
- View current WiFi connection
- Scan for available networks
- Connect to new networks
- Manage saved networks (connect/forget)
- Run network diagnostics
- Ping test to verify connectivity

### ADS-B Configuration Tab
Configure ADS-B data forwarding:
- **Service Control**: Start/Stop/Restart ADS-B server
- **Aircraft Filter**: 
  - All aircraft mode
  - Specific ICAO IDs (comma-separated)
  - Default ICAOs: A92F2D, A932E4, A9369B, A93A52
- **TCP Endpoints**:
  - Add multiple IP:Port destinations
  - Test connection to each endpoint
  - Remove endpoints

### Logs & Troubleshooting Tab
Monitor and diagnose issues:
- View logs with filtering (All, Errors, Warnings, Info)
- Manual refresh
- Download logs
- Clear logs
- Run system diagnostics

### Settings Tab
System configuration:
- Change web interface password
- View system information
- Backup/restore configuration files

---

## 🔧 Command Line Tools

### ADS-B Server CLI

Located at: `/home/JLBMaritime/adsb-wifi-manager/adsb_server/adsb_cli.py`

**Commands**:
```bash
# Start the ADS-B server
sudo python3 adsb_cli.py start

# Stop the ADS-B server
sudo python3 adsb_cli.py stop

# Restart the ADS-B server
sudo python3 adsb_cli.py restart

# View service status
python3 adsb_cli.py status

# View current configuration
python3 adsb_cli.py config

# View recent logs
python3 adsb_cli.py logs

# Show help
python3 adsb_cli.py help
```

### Systemd Service Management

```bash
# Check ADS-B server status
sudo systemctl status adsb-server

# Check Web manager status
sudo systemctl status web-manager

# View logs
sudo journalctl -u adsb-server -f
sudo journalctl -u web-manager -f

# Restart services
sudo systemctl restart adsb-server
sudo systemctl restart web-manager
```

---

## 🔍 Troubleshooting

### WiFi Hotspot Not Starting

**Problem**: Unable to connect to JLBMaritime-ADSB hotspot

**Solutions**:
```bash
# Check if wlan1 is available
iwconfig

# Restart hotspot services
sudo systemctl restart hostapd
sudo systemctl restart dnsmasq

# Check service status
sudo systemctl status hostapd
sudo systemctl status dnsmasq

# Verify wlan1 IP
ip addr show wlan1
```

### Cannot Access Web Interface

**Problem**: Browser cannot reach ADS-B.local

**Solutions**:
1. Try direct IP: `http://192.168.4.1`
2. Ensure connected to JLBMaritime-ADSB hotspot
3. Clear browser cache
4. Check web service:
   ```bash
   sudo systemctl status web-manager
   sudo systemctl restart web-manager
   ```

### ADS-B Server Not Receiving Data

**Problem**: No aircraft data being received

**Solutions**:
```bash
# Check dump1090-fa is running
sudo systemctl status dump1090-fa
sudo systemctl restart dump1090-fa

# Verify SDR dongle is connected
lsusb | grep -i rtl

# Check ADS-B server logs
python3 /home/JLBMaritime/adsb-wifi-manager/adsb_server/adsb_cli.py logs

# Test connection to dump1090-fa
telnet 127.0.0.1 30005
```

### WiFi Connection Issues (wlan0)

**Problem**: Cannot connect to internet WiFi

**Solutions**:
```bash
# Check wlan0 status
iwconfig wlan0

# Scan for networks
sudo iwlist wlan0 scan

# Check WPA supplicant
wpa_cli -i wlan0 status

# Reconnect via CLI
sudo wpa_cli -i wlan0 reconfigure
```

### Performance Issues

**Problem**: System running slowly

**Solutions**:
```bash
# Check CPU/Memory usage
htop

# Check disk space
df -h

# Reduce log size
sudo truncate -s 0 /home/JLBMaritime/adsb-wifi-manager/logs/adsb_server.log

# Restart services
sudo systemctl restart adsb-server web-manager
```

### Port 80 Conflict (Lighttpd)

**Problem**: Web interface shows "Port 80 is in use" or 403 Forbidden

**Cause**: dump1090-fa installs lighttpd which uses ports 80 and 8080

**Solution**: The web interface runs on port 5000 by default to avoid this conflict.
- Access at: `http://192.168.4.1:5000`
- dump1090 SkyAware available at: `http://192.168.4.1:8080`

### NetworkManager Managing wlan1 (MOST COMMON ISSUE)

**Problem**: Hotspot appears briefly then disappears, or wlan1 shows as "disconnected" in NetworkManager

**Cause**: NetworkManager is managing wlan1 and preventing hostapd from using it as an access point

**Solution**:
```bash
# Create NetworkManager unmanage rule
sudo mkdir -p /etc/NetworkManager/conf.d
sudo tee /etc/NetworkManager/conf.d/unmanage-wlan1.conf > /dev/null <<EOF
[keyfile]
unmanaged-devices=interface-name:wlan1
EOF

# Restart NetworkManager
sudo systemctl restart NetworkManager

# Reconfigure wlan1
sudo ip link set wlan1 down
sudo ip link set wlan1 up
sudo ip addr add 192.168.4.1/24 dev wlan1

# Restart hostapd
sudo systemctl restart hostapd

# Verify wlan1 is in AP mode
iw dev wlan1 info  # Should show "type AP"
```

### wlan1 Keeps Connecting as Client

**Problem**: Hotspot not visible, wlan1 connects to saved WiFi network

**Cause**: wpa_supplicant auto-connects wlan1 to saved networks

**Solution**:
```bash
# Disconnect wlan1 from client networks
sudo wpa_cli -i wlan1 disconnect
sudo ip addr flush dev wlan1

# Configure wlan1 as hotspot
sudo ip link set wlan1 down
sudo ip link set wlan1 up
sudo ip addr add 192.168.4.1/24 dev wlan1

# Restart hostapd
sudo systemctl restart hostapd
```

---

## 🏗️ Architecture

### System Components

```
┌─────────────────────────────────────────────┐
│          Raspberry Pi 4B (ADS-B)            │
├─────────────────────────────────────────────┤
│                                             │
│  ┌─────────────┐         ┌──────────────┐  │
│  │ FlightAware │ USB     │  dump1090-fa │  │
│  │  SDR Stick  ├────────▶│  (Decoder)   │  │
│  └─────────────┘         └──────┬───────┘  │
│                                 │ SBS1      │
│                                 ▼           │
│                        ┌────────────────┐   │
│                        │  ADS-B Server  │   │
│                        │   (Python)     │   │
│                        │  - Filter ICAO │   │
│                        │  - Forward TCP │   │
│                        └───────┬────────┘   │
│                                │            │
│                                ▼            │
│                        TCP Endpoints        │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │       Web Interface (Flask)         │   │
│  │  - Dashboard                        │   │
│  │  - WiFi Manager                     │   │
│  │  - ADS-B Config                     │   │
│  │  - Logs                             │   │
│  │  - Settings                         │   │
│  └──────────┬──────────────────────────┘   │
│             │                               │
│  ┌──────────▼──────────┐                   │
│  │   WiFi Hotspot      │  wlan1            │
│  │   (hostapd/dnsmasq) │  192.168.4.1      │
│  │   JLBMaritime-ADSB  │  ADS-B.local      │
│  └─────────────────────┘                   │
│                                             │
│  ┌─────────────────────┐                   │
│  │  Internet WiFi      │  wlan0            │
│  │  (wpa_supplicant)   │  DHCP             │
│  └─────────────────────┘                   │
│                                             │
└─────────────────────────────────────────────┘
```

### File Structure

```
/home/JLBMaritime/adsb-wifi-manager/
├── adsb_server/
│   ├── adsb_server.py          # Main ADS-B server application
│   └── adsb_cli.py              # Command-line interface
├── wifi_manager/
│   └── wifi_controller.py       # WiFi management backend
├── web_interface/
│   ├── app.py                   # Flask web application
│   ├── templates/
│   │   ├── index.html           # Main dashboard
│   │   └── login.html           # Login page
│   └── static/
│       ├── css/style.css        # Stylesheet
│       ├── js/main.js           # Frontend JavaScript
│       └── logo.png             # JLBMaritime logo
├── config/
│   ├── adsb_server_config.conf  # ADS-B configuration
│   └── web_config.conf          # Web interface config
├── services/
│   ├── adsb-server.service      # ADS-B systemd service
│   └── web-manager.service      # Web interface service
├── logs/
│   └── adsb_server.log          # Application logs
├── install.sh                   # Installation script
└── README.md                    # This file
```

---

## 📝 Configuration Files

### ADS-B Server Config
**Location**: `/home/JLBMaritime/adsb-wifi-manager/config/adsb_server_config.conf`

```ini
[Dump1090]
host = 127.0.0.1
port = 30005

[Filter]
mode = specific
icao_list = A92F2D,A932E4,A9369B,A93A52

[Endpoints]
count = 2
endpoint_0_ip = 192.168.1.100
endpoint_0_port = 30003
endpoint_1_ip = 10.0.0.50
endpoint_1_port = 30003
```

### Web Interface Config
**Location**: `/home/JLBMaritime/adsb-wifi-manager/config/web_config.conf`

```ini
[Auth]
username = JLBMaritime
password = Admin
```

---

## 🔒 Security Considerations

1. **Change Default Passwords**: Update both hotspot and web interface passwords after installation
2. **Network Isolation**: The hotspot (wlan1) is isolated from internet WiFi (wlan0) by default
3. **Firewall**: Consider adding iptables rules for additional security
4. **HTTPS**: For production use, consider adding SSL/TLS certificates
5. **Access Control**: Limit physical access to the Raspberry Pi

---

## 🤝 Support & Contributing

### Getting Help
- Check the Troubleshooting section above
- Review application logs
- Check systemd service status

### Reporting Issues
When reporting issues, include:
- Raspberry Pi model and OS version
- Output of `systemctl status adsb-server web-manager`
- Relevant log entries
- Steps to reproduce the problem

---

## 📄 License

This project is developed for JLBMaritime. All rights reserved.

---

## 🙏 Acknowledgments

- FlightAware for dump1090-fa ADS-B decoder
- Raspberry Pi Foundation
- Flask web framework
- Open source community

---

**Version**: 1.0.0  
**Last Updated**: December 2025  
**Author**: JLBMaritime Development Team
