# AIS-WiFi Manager

A unified management system for Raspberry Pi that combines AIS data forwarding with WiFi network management through a web-based interface.

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%204B-red)

## Overview

AIS-WiFi Manager merges two essential functionalities into a single, efficient application:
- **AIS Data Forwarding**: Reads AIS data from a dAISy HAT and forwards it to multiple configurable endpoints
- **WiFi Management**: Web-based interface for managing WiFi connections and network settings

## Key Features

### AIS Management
- **Multiple Endpoints**: Forward AIS data to unlimited destinations simultaneously
- **Web Configuration**: Add, edit, enable/disable, and delete endpoints through the web interface
- **Individual Control**: Enable/disable endpoints without deleting configuration
- **Real-Time Status**: Monitor connection status for each endpoint
- **Automatic Retry**: 3 retry attempts per endpoint with independent failure handling
- **Service Control**: Start, stop, and restart AIS forwarding from the web interface
- **Live Logging**: View AIS service logs in real-time

### WiFi Management
- **Network Scanning**: Discover and display available WiFi networks with signal strength
- **Connection Management**: Connect to networks with password support
- **Saved Networks**: Remember and manage previously connected networks
- **Network Diagnostics**: Built-in ping tests and network status monitoring
- **Real-Time Updates**: Live status updates via AJAX polling

### System Features
- **Hotspot Mode**: wlan1 configured as access point (JLBMaritime-AIS), wlan0 for internet
- **Web Interface**: Intuitive, mobile-responsive interface accessible via hotspot
- **HTTP Authentication**: Secure access with username/password (JLBMaritime/Admin)
- **Auto-Start**: Systemd service for automatic startup on boot
- **Configuration Backup**: Automatic backup before any config changes

## Hardware Requirements

- Raspberry Pi 4B (2GB RAM or higher)
- dAISy HAT or compatible AIS receiver
- Two WiFi interfaces (wlan0 and wlan1)
  - wlan0: Connect to internet
  - wlan1: Hotspot for web interface access
- Micro SD card (16GB or larger recommended)
- Power supply for Raspberry Pi
- Antenna suitable for AIS reception

## Software Requirements

- Raspberry Pi OS (64-bit Bookworm)
- Python 3.9 or higher
- NetworkManager (nmcli)
- hostapd
- dnsmasq
- avahi-daemon

## Quick Installation

1. Clone the repository:
```bash
git clone https://github.com/JLBMaritime/AIS-WiFi-Manager.git
cd AIS-WiFi-Manager
```

2. Run the installation script:
```bash
sudo bash install.sh
```

3. Reboot your Raspberry Pi:
```bash
sudo reboot
```

4. After reboot:
   - Connect to WiFi hotspot: `JLBMaritime-AIS` (password: `Admin123`)
   - Open browser to: `http://AIS.local` or `http://192.168.4.1`
   - Login with username: `JLBMaritime`, password: `Admin`

## Usage

### WiFi Manager

1. **Scan Networks**: Click "Scan" to discover available WiFi networks
2. **Connect**: Click "Connect" on a network, enter password if required
3. **Saved Networks**: View and manage previously connected networks
4. **Diagnostics**: Run ping tests and view network statistics

### AIS Configuration

1. Navigate to "AIS Configuration" in the main menu
2. **View Status**: Check if AIS service is running
3. **Add Endpoint**:
   - Click "+ Add Endpoint"
   - Enter name (e.g., "Chart Plotter")
   - Enter IP address and port
   - Choose if endpoint should be enabled
   - Click "Save"
4. **Manage Endpoints**:
   - Toggle: Enable/disable without deleting
   - Edit: Modify endpoint details
   - Delete: Remove endpoint completely
5. **Control Service**: Start, stop, or restart AIS forwarding

### AIS Logs

1. Navigate to "AIS Logs" to view real-time service logs
2. Monitor connection status for all endpoints
3. Logs auto-refresh every 5 seconds

## Configuration

### Default Hotspot Settings

- **SSID**: JLBMaritime-AIS
- **Password**: Admin123
- **IP Address**: 192.168.4.1
- **DHCP Range**: 192.168.4.2 - 192.168.4.20

### Default Login Credentials

- **Username**: JLBMaritime
- **Password**: Admin

### AIS Configuration

The serial port is fixed at `/dev/serial0` and cannot be edited via the web interface for security.

Endpoints are configured through the web interface with:
- **Name**: User-friendly identifier
- **IP Address**: Target device IP
- **Port**: Target port number
- **Enabled**: Whether endpoint is active

## Project Structure

```
AIS-WiFi-Manager/
├── README.md                      # This file
├── LICENSE                        # MIT License
├── .gitignore                     # Git ignore patterns
├── requirements.txt               # Python dependencies
├── install.sh                     # Installation script
├── uninstall.sh                   # Uninstallation script
├── run.py                         # Application entry point
├── ais_config.conf                # AIS configuration
├── logo.png                       # JLBMaritime logo
├── app/
│   ├── __init__.py               # Flask initialization
│   ├── routes.py                 # All API routes
│   ├── wifi_manager.py           # WiFi operations (wlan0)
│   ├── ais_manager.py            # AIS multi-endpoint manager
│   ├── ais_config_manager.py     # Config backup & management
│   ├── network_diagnostics.py    # Network diagnostics
│   ├── database.py               # SQLite database
│   ├── templates/
│   │   ├── base.html             # Base template
│   │   ├── index.html            # WiFi Manager page
│   │   ├── ais_config.html       # AIS Configuration page
│   │   └── ais_logs.html         # AIS Logs viewer
│   └── static/
│       ├── css/style.css         # Unified styling
│       ├── js/app.js             # WiFi functionality
│       ├── js/ais.js             # AIS functionality
│       └── logo.png              # Logo
├── service/
│   └── ais-wifi-manager.service  # Systemd service
├── examples/
│   └── ais_config.conf.example   # Example configuration
└── docs/
    └── (documentation files)
```

## API Documentation

### WiFi Endpoints

- `GET /api/scan` - Scan for networks
- `POST /api/rescan` - Trigger new scan
- `GET /api/current` - Get current connection
- `GET /api/saved` - Get saved networks
- `POST /api/connect` - Connect to network
- `POST /api/forget` - Forget network
- `POST /api/ping` - Run ping test
- `GET /api/diagnostics` - Get network diagnostics

### AIS Endpoints

- `GET /api/ais/status` - Get service status
- `POST /api/ais/start` - Start service
- `POST /api/ais/stop` - Stop service
- `POST /api/ais/restart` - Restart service
- `GET /api/ais/logs` - Get service logs
- `GET /api/ais/endpoints` - List all endpoints
- `POST /api/ais/endpoints` - Add endpoint
- `PUT /api/ais/endpoints/<id>` - Update endpoint
- `DELETE /api/ais/endpoints/<id>` - Delete endpoint
- `POST /api/ais/endpoints/<id>/toggle` - Toggle endpoint

## Service Management

### Check Status
```bash
sudo systemctl status ais-wifi-manager
```

### Start/Stop/Restart
```bash
sudo systemctl start ais-wifi-manager
sudo systemctl stop ais-wifi-manager
sudo systemctl restart ais-wifi-manager
```

### View Logs
```bash
sudo journalctl -u ais-wifi-manager -f
```

### Enable/Disable Auto-Start
```bash
sudo systemctl enable ais-wifi-manager
sudo systemctl disable ais-wifi-manager
```

## Troubleshooting

### Hotspot Not Appearing

1. Check hostapd status:
```bash
sudo systemctl status hostapd
```

2. Verify wlan1 interface:
```bash
ip addr show wlan1
```

3. Restart services:
```bash
sudo systemctl restart hostapd
sudo systemctl restart dnsmasq
```

### Cannot Access Web Interface

1. Ensure connected to hotspot (JLBMaritime-AIS)
2. Try IP address: `http://192.168.4.1`
3. Check if service is running:
```bash
sudo systemctl status ais-wifi-manager
```

### AIS Not Forwarding Data

1. Check serial port connection
2. Verify endpoints are enabled
3. View logs for errors:
```bash
sudo journalctl -u ais-wifi-manager -n 50
```

## Security Considerations

- Change default credentials before deployment
- Use HTTPS for production (requires SSL certificate)
- Limit hotspot access to trusted devices
- Consider MAC address filtering
- Keep system packages updated
- Review and restrict API access if needed

## Uninstallation

To remove AIS-WiFi Manager:

```bash
cd AIS-WiFi-Manager
sudo bash uninstall.sh
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For issues, questions, or contributions, please open an issue on GitHub.

## Acknowledgments

- Original AIS Server project for AIS data forwarding concept
- Original Hotspot WiFi Manager for network management interface
- dAISy HAT project for affordable AIS reception
- Raspberry Pi Foundation for excellent single-board computers

## Changelog

### Version 1.0.0 (Initial Release)
- Unified AIS forwarding and WiFi management
- Multi-endpoint AIS data forwarding
- Web-based endpoint configuration
- Real-time status monitoring
- Configuration backup system
- Auto-start systemd service
- Mobile-responsive design
- Comprehensive documentation

---

**Developed for JLBMaritime AIS ADS-B Project**

**Raspberry Pi 4B | 64-bit Raspberry Pi OS (Bookworm) | Python 3 | Flask**
