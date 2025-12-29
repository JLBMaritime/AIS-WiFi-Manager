#!/usr/bin/env python3
"""
ADS-B Server - Receives ADS-B data from dump1090-fa and forwards to configured endpoints
Part of JLBMaritime ADS-B & Wi-Fi Management System
"""

import socket
import threading
import time
import logging
import configparser
import os
import sys
from datetime import datetime, timedelta

class ADSBServer:
    def __init__(self, config_file):
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        self.running = False
        self.dump1090_socket = None
        self.endpoint_sockets = []
        self.filter_icao_list = []
        self.filter_all = True
        self.endpoints = []
        
        # Setup logging
        self.setup_logging()
        self.load_config()
        
    def setup_logging(self):
        """Configure logging with 72-hour rotation"""
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(log_dir, 'adsb_server.log')
        
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Start log rotation thread
        threading.Thread(target=self.log_rotation_worker, daemon=True).start()
        
    def log_rotation_worker(self):
        """Purge logs every 72 hours"""
        while True:
            time.sleep(3600)  # Check every hour
            try:
                log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'adsb_server.log')
                if os.path.exists(log_file):
                    file_time = datetime.fromtimestamp(os.path.getmtime(log_file))
                    if datetime.now() - file_time > timedelta(hours=72):
                        self.logger.info("Rotating log file (72 hours)")
                        open(log_file, 'w').close()
            except Exception as e:
                self.logger.error(f"Log rotation error: {e}")
                
    def load_config(self):
        """Load configuration from file"""
        try:
            if not os.path.exists(self.config_file):
                self.create_default_config()
                
            self.config.read(self.config_file)
            
            # Load filter settings
            filter_mode = self.config.get('Filter', 'mode', fallback='all')
            self.filter_all = (filter_mode.lower() == 'all')
            
            if not self.filter_all:
                icao_string = self.config.get('Filter', 'icao_list', fallback='')
                self.filter_icao_list = [icao.strip().upper() for icao in icao_string.split(',') if icao.strip()]
                
            # Load endpoints
            self.endpoints = []
            endpoint_count = self.config.getint('Endpoints', 'count', fallback=0)
            for i in range(endpoint_count):
                ip = self.config.get('Endpoints', f'endpoint_{i}_ip', fallback=None)
                port = self.config.getint('Endpoints', f'endpoint_{i}_port', fallback=None)
                if ip and port:
                    self.endpoints.append({'ip': ip, 'port': port, 'socket': None})
                    
            self.logger.info(f"Configuration loaded: Filter={'ALL' if self.filter_all else self.filter_icao_list}, Endpoints={len(self.endpoints)}")
            
        except Exception as e:
            self.logger.error(f"Error loading config: {e}")
            
    def create_default_config(self):
        """Create default configuration file"""
        self.config['Dump1090'] = {
            'host': '127.0.0.1',
            'port': '30005'
        }
        self.config['Filter'] = {
            'mode': 'specific',
            'icao_list': 'A92F2D,A932E4,A9369B,A93A52'
        }
        self.config['Endpoints'] = {
            'count': '0'
        }
        
        with open(self.config_file, 'w') as f:
            self.config.write(f)
            
    def connect_to_dump1090(self):
        """Connect to dump1090-fa"""
        host = self.config.get('Dump1090', 'host', fallback='127.0.0.1')
        port = self.config.getint('Dump1090', 'port', fallback=30005)
        
        try:
            self.dump1090_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.dump1090_socket.settimeout(10)
            self.dump1090_socket.connect((host, port))
            self.logger.info(f"Connected to dump1090-fa at {host}:{port}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to connect to dump1090-fa: {e}")
            self.dump1090_socket = None
            return False
            
    def connect_to_endpoints(self):
        """Connect to all configured endpoints"""
        for endpoint in self.endpoints:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((endpoint['ip'], endpoint['port']))
                endpoint['socket'] = sock
                self.logger.info(f"Connected to endpoint {endpoint['ip']}:{endpoint['port']}")
            except Exception as e:
                self.logger.warning(f"Failed to connect to {endpoint['ip']}:{endpoint['port']}: {e}")
                endpoint['socket'] = None
                
    def reconnect_endpoint(self, endpoint):
        """Attempt to reconnect to a failed endpoint"""
        try:
            if endpoint['socket']:
                try:
                    endpoint['socket'].close()
                except:
                    pass
                    
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((endpoint['ip'], endpoint['port']))
            endpoint['socket'] = sock
            self.logger.info(f"Reconnected to endpoint {endpoint['ip']}:{endpoint['port']}")
            return True
        except Exception as e:
            self.logger.debug(f"Reconnect failed for {endpoint['ip']}:{endpoint['port']}: {e}")
            endpoint['socket'] = None
            return False
            
    def filter_message(self, message):
        """Check if message should be forwarded based on filter"""
        if self.filter_all:
            return True
            
        # SBS1 format: MSG,3,1,1,ICAO,1,2023/01/01,12:00:00.000,2023/01/01,12:00:00.000,...
        try:
            parts = message.split(',')
            if len(parts) > 4:
                icao = parts[4].strip().upper()
                return icao in self.filter_icao_list
        except:
            pass
            
        return False
        
    def forward_message(self, message):
        """Forward message to all connected endpoints"""
        message_bytes = message.encode('utf-8')
        
        for endpoint in self.endpoints:
            if endpoint['socket']:
                try:
                    endpoint['socket'].sendall(message_bytes)
                except Exception as e:
                    self.logger.warning(f"Failed to send to {endpoint['ip']}:{endpoint['port']}: {e}")
                    endpoint['socket'] = None
                    # Attempt reconnection in background
                    threading.Thread(target=self.reconnect_endpoint, args=(endpoint,), daemon=True).start()
                    
    def run(self):
        """Main server loop"""
        self.running = True
        self.logger.info("ADS-B Server starting...")
        
        while self.running:
            # Connect to dump1090
            if not self.dump1090_socket:
                if not self.connect_to_dump1090():
                    self.logger.info("Waiting for dump1090-fa connection... (retry in 10s)")
                    time.sleep(10)
                    continue
                    
            # Connect to endpoints
            self.connect_to_endpoints()
            
            # Main data processing loop
            buffer = ""
            reconnect_time = time.time()
            
            try:
                while self.running:
                    # Reload config periodically (for updates)
                    if time.time() - reconnect_time > 30:
                        old_config = self.config_file
                        self.load_config()
                        reconnect_time = time.time()
                        
                    try:
                        data = self.dump1090_socket.recv(4096)
                        if not data:
                            self.logger.warning("dump1090-fa connection lost")
                            break
                            
                        buffer += data.decode('utf-8', errors='ignore')
                        
                        # Process complete messages (lines)
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()
                            
                            if line and self.filter_message(line):
                                self.forward_message(line + '\n')
                                
                    except socket.timeout:
                        continue
                    except Exception as e:
                        self.logger.error(f"Error receiving data: {e}")
                        break
                        
            except Exception as e:
                self.logger.error(f"Server error: {e}")
                
            # Clean up connection
            if self.dump1090_socket:
                try:
                    self.dump1090_socket.close()
                except:
                    pass
                self.dump1090_socket = None
                
            # Wait before reconnecting
            if self.running:
                time.sleep(5)
                
        self.logger.info("ADS-B Server stopped")
        
    def stop(self):
        """Stop the server"""
        self.logger.info("Stopping ADS-B Server...")
        self.running = False
        
        # Close all connections
        if self.dump1090_socket:
            try:
                self.dump1090_socket.close()
            except:
                pass
                
        for endpoint in self.endpoints:
            if endpoint['socket']:
                try:
                    endpoint['socket'].close()
                except:
                    pass

def main():
    """Main entry point"""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'adsb_server_config.conf')
    
    server = ADSBServer(config_path)
    
    # Handle graceful shutdown
    import signal
    def signal_handler(sig, frame):
        server.stop()
        sys.exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        server.run()
    except KeyboardInterrupt:
        server.stop()

if __name__ == "__main__":
    main()
