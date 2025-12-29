#!/usr/bin/env python3
"""
WiFi Controller - Manages WiFi connections on wlan0
Part of JLBMaritime ADS-B & Wi-Fi Management System
"""

import subprocess
import re
import os
import time

class WiFiController:
    def __init__(self, interface='wlan0'):
        self.interface = interface
        
    def scan_networks(self):
        """Scan for available WiFi networks"""
        try:
            # Trigger scan
            subprocess.run(['sudo', 'iwlist', self.interface, 'scan'], 
                         capture_output=True, timeout=10)
            time.sleep(1)
            
            # Get scan results
            result = subprocess.run(['sudo', 'iwlist', self.interface, 'scan'], 
                                  capture_output=True, text=True, timeout=10)
            
            networks = []
            current_network = {}
            
            for line in result.stdout.split('\n'):
                line = line.strip()
                
                # New cell
                if 'Cell' in line and 'Address:' in line:
                    if current_network:
                        networks.append(current_network)
                    current_network = {}
                    
                # ESSID
                if 'ESSID:' in line:
                    match = re.search(r'ESSID:"([^"]*)"', line)
                    if match:
                        current_network['ssid'] = match.group(1)
                        
                # Signal quality
                if 'Quality=' in line:
                    match = re.search(r'Quality=(\d+)/(\d+)', line)
                    if match:
                        quality = int(match.group(1))
                        max_quality = int(match.group(2))
                        current_network['signal'] = int((quality / max_quality) * 100)
                        
                # Encryption
                if 'Encryption key:' in line:
                    current_network['encrypted'] = 'on' in line.lower()
                    
            if current_network:
                networks.append(current_network)
                
            # Remove duplicates and empty SSIDs
            seen = set()
            unique_networks = []
            for net in networks:
                if 'ssid' in net and net['ssid'] and net['ssid'] not in seen:
                    seen.add(net['ssid'])
                    if 'signal' not in net:
                        net['signal'] = 0
                    if 'encrypted' not in net:
                        net['encrypted'] = True
                    unique_networks.append(net)
                    
            return sorted(unique_networks, key=lambda x: x['signal'], reverse=True)
            
        except Exception as e:
            print(f"Error scanning networks: {e}")
            return []
            
    def get_saved_networks(self):
        """Get list of saved networks from wpa_supplicant"""
        try:
            result = subprocess.run(['sudo', 'wpa_cli', '-i', self.interface, 'list_networks'],
                                  capture_output=True, text=True)
            
            networks = []
            lines = result.stdout.split('\n')[1:]  # Skip header
            
            for line in lines:
                if line.strip():
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        networks.append({
                            'id': parts[0].strip(),
                            'ssid': parts[1].strip()
                        })
                        
            return networks
            
        except Exception as e:
            print(f"Error getting saved networks: {e}")
            return []
            
    def get_current_network(self):
        """Get currently connected network info"""
        try:
            result = subprocess.run(['iwgetid', self.interface, '-r'],
                                  capture_output=True, text=True)
            ssid = result.stdout.strip()
            
            if not ssid:
                return None
                
            # Get IP address
            result = subprocess.run(['ip', 'addr', 'show', self.interface],
                                  capture_output=True, text=True)
            
            ip_match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
            ip_address = ip_match.group(1) if ip_match else 'Unknown'
            
            # Get signal strength
            result = subprocess.run(['iwconfig', self.interface],
                                  capture_output=True, text=True)
            
            signal = 0
            quality_match = re.search(r'Quality=(\d+)/(\d+)', result.stdout)
            if quality_match:
                signal = int((int(quality_match.group(1)) / int(quality_match.group(2))) * 100)
                
            return {
                'ssid': ssid,
                'ip': ip_address,
                'signal': signal
            }
            
        except Exception as e:
            print(f"Error getting current network: {e}")
            return None
            
    def connect_to_network(self, ssid, password=None):
        """Connect to a WiFi network"""
        try:
            # Check if network already exists in saved networks
            saved = self.get_saved_networks()
            network_id = None
            
            for net in saved:
                if net['ssid'] == ssid:
                    network_id = net['id']
                    break
                    
            if network_id is None:
                # Add new network
                result = subprocess.run(['sudo', 'wpa_cli', '-i', self.interface, 'add_network'],
                                      capture_output=True, text=True)
                network_id = result.stdout.strip()
                
                # Set SSID
                subprocess.run(['sudo', 'wpa_cli', '-i', self.interface, 'set_network', 
                              network_id, 'ssid', f'"{ssid}"'], check=True)
                
                if password:
                    # Set PSK (password)
                    subprocess.run(['sudo', 'wpa_cli', '-i', self.interface, 'set_network', 
                                  network_id, 'psk', f'"{password}"'], check=True)
                else:
                    # Open network
                    subprocess.run(['sudo', 'wpa_cli', '-i', self.interface, 'set_network', 
                                  network_id, 'key_mgmt', 'NONE'], check=True)
                    
            # Enable and select network
            subprocess.run(['sudo', 'wpa_cli', '-i', self.interface, 'enable_network', network_id], 
                         check=True)
            subprocess.run(['sudo', 'wpa_cli', '-i', self.interface, 'select_network', network_id], 
                         check=True)
            
            # Save configuration
            subprocess.run(['sudo', 'wpa_cli', '-i', self.interface, 'save_config'], check=True)
            
            # Request DHCP
            subprocess.run(['sudo', 'dhclient', self.interface], check=False)
            
            return True
            
        except Exception as e:
            print(f"Error connecting to network: {e}")
            return False
            
    def forget_network(self, ssid):
        """Remove a saved network"""
        try:
            saved = self.get_saved_networks()
            network_id = None
            
            for net in saved:
                if net['ssid'] == ssid:
                    network_id = net['id']
                    break
                    
            if network_id:
                subprocess.run(['sudo', 'wpa_cli', '-i', self.interface, 'remove_network', 
                              network_id], check=True)
                subprocess.run(['sudo', 'wpa_cli', '-i', self.interface, 'save_config'], 
                             check=True)
                return True
                
            return False
            
        except Exception as e:
            print(f"Error forgetting network: {e}")
            return False
            
    def get_ip_address(self):
        """Get IP address of the interface"""
        try:
            result = subprocess.run(['ip', 'addr', 'show', self.interface],
                                  capture_output=True, text=True)
            
            ip_match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
            return ip_match.group(1) if ip_match else None
            
        except Exception as e:
            print(f"Error getting IP: {e}")
            return None
            
    def ping_test(self, host='8.8.8.8', count=4):
        """Run ping test"""
        try:
            result = subprocess.run(['ping', '-c', str(count), '-W', '2', host],
                                  capture_output=True, text=True)
            
            return {
                'success': result.returncode == 0,
                'output': result.stdout
            }
            
        except Exception as e:
            return {
                'success': False,
                'output': f"Error: {str(e)}"
            }
            
    def get_diagnostics(self):
        """Get network diagnostics information"""
        try:
            diagnostics = {}
            
            # Interface status
            result = subprocess.run(['ip', 'link', 'show', self.interface],
                                  capture_output=True, text=True)
            diagnostics['interface_up'] = 'UP' in result.stdout
            
            # IP configuration
            result = subprocess.run(['ip', 'addr', 'show', self.interface],
                                  capture_output=True, text=True)
            diagnostics['ip_config'] = result.stdout
            
            # Gateway
            result = subprocess.run(['ip', 'route', 'show', 'default'],
                                  capture_output=True, text=True)
            gateway_match = re.search(r'default via (\d+\.\d+\.\d+\.\d+)', result.stdout)
            diagnostics['gateway'] = gateway_match.group(1) if gateway_match else 'None'
            
            # DNS
            if os.path.exists('/etc/resolv.conf'):
                with open('/etc/resolv.conf', 'r') as f:
                    dns_servers = []
                    for line in f:
                        if line.startswith('nameserver'):
                            dns_servers.append(line.split()[1])
                    diagnostics['dns'] = dns_servers
            else:
                diagnostics['dns'] = []
                
            return diagnostics
            
        except Exception as e:
            return {'error': str(e)}
