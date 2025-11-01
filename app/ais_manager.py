"""
AIS Manager Module
Handles AIS data forwarding to multiple endpoints with independent connection management
"""
import serial
import socket
import threading
import time
import logging
from datetime import datetime
from app.ais_config_manager import load_ais_config

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class AISManager:
    def __init__(self):
        self.running = False
        self.thread = None
        self.serial_port = "/dev/serial0"
        self.endpoints = []
        self.endpoint_status = {}
        self.logs = []
        self.max_logs = 200
        self.lock = threading.Lock()
        
    def load_endpoints(self):
        """Load endpoints from configuration"""
        config = load_ais_config()
        if not config:
            return []
        
        endpoints = []
        self.serial_port = config.get('AIS', {}).get('serial_port', '/dev/serial0')
        
        # Load all endpoint sections
        for section in config:
            if section.startswith('ENDPOINT_'):
                endpoint_config = config[section]
                if endpoint_config.get('enabled', 'false').lower() == 'true':
                    endpoints.append({
                        'id': section,
                        'name': endpoint_config.get('name', section),
                        'ip': endpoint_config.get('ip', ''),
                        'port': int(endpoint_config.get('port', 0)),
                        'enabled': True
                    })
        
        return endpoints
    
    def start(self):
        """Start AIS forwarding service"""
        if self.running:
            self.add_log("INFO", "AIS service is already running")
            return False, "Service already running"
        
        self.running = True
        self.endpoints = self.load_endpoints()
        
        # Initialize status for all endpoints
        for endpoint in self.endpoints:
            self.endpoint_status[endpoint['id']] = {
                'connected': False,
                'last_attempt': None,
                'error': None
            }
        
        self.thread = threading.Thread(target=self._run_ais_forwarding, daemon=True)
        self.thread.start()
        self.add_log("INFO", f"AIS service started with {len(self.endpoints)} endpoint(s)")
        return True, "Service started"
    
    def stop(self):
        """Stop AIS forwarding service"""
        if not self.running:
            return False, "Service not running"
        
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        self.add_log("INFO", "AIS service stopped")
        return True, "Service stopped"
    
    def restart(self):
        """Restart AIS forwarding service"""
        self.stop()
        time.sleep(2)
        return self.start()
    
    def is_running(self):
        """Check if service is running"""
        return self.running
    
    def get_status(self):
        """Get current status of service and all endpoints"""
        return {
            'running': self.running,
            'serial_port': self.serial_port,
            'endpoints': self.endpoints,
            'endpoint_status': self.endpoint_status
        }
    
    def add_log(self, level, message):
        """Add log entry"""
        with self.lock:
            log_entry = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'level': level,
                'message': message
            }
            self.logs.append(log_entry)
            
            # Keep only last max_logs entries
            if len(self.logs) > self.max_logs:
                self.logs = self.logs[-self.max_logs:]
            
            # Also log to standard logging
            if level == 'ERROR':
                logging.error(message)
            elif level == 'WARNING':
                logging.warning(message)
            else:
                logging.info(message)
    
    def get_logs(self, count=100):
        """Get recent logs"""
        with self.lock:
            return self.logs[-count:]
    
    def _send_to_endpoint(self, endpoint, data, max_retries=3):
        """Send data to a specific endpoint with retry logic"""
        endpoint_id = endpoint['id']
        
        for attempt in range(max_retries):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(5)
                    s.connect((endpoint['ip'], endpoint['port']))
                    s.sendall(data)
                    
                    # Update status on success
                    self.endpoint_status[endpoint_id]['connected'] = True
                    self.endpoint_status[endpoint_id]['error'] = None
                    self.endpoint_status[endpoint_id]['last_attempt'] = datetime.now().isoformat()
                    
                    if attempt > 0:
                        self.add_log("INFO", f"Reconnected to {endpoint['name']} ({endpoint['ip']}:{endpoint['port']})")
                    
                    return True
                    
            except socket.error as e:
                self.endpoint_status[endpoint_id]['connected'] = False
                self.endpoint_status[endpoint_id]['error'] = str(e)
                self.endpoint_status[endpoint_id]['last_attempt'] = datetime.now().isoformat()
                
                if attempt == max_retries - 1:
                    self.add_log("ERROR", f"Failed to send to {endpoint['name']} after {max_retries} attempts: {e}")
                else:
                    time.sleep(2)
        
        return False
    
    def _run_ais_forwarding(self):
        """Main AIS forwarding loop"""
        self.add_log("INFO", f"Connecting to serial port {self.serial_port}")
        
        while self.running:
            try:
                # Open serial connection
                with serial.Serial(self.serial_port, baudrate=38400, timeout=2) as ser:
                    self.add_log("INFO", f"Connected to AIS serial port: {self.serial_port}")
                    
                    while self.running:
                        try:
                            # Read line from serial
                            line = ser.readline()
                            
                            if line:
                                # Forward to all enabled endpoints
                                for endpoint in self.endpoints:
                                    if endpoint['enabled']:
                                        self._send_to_endpoint(endpoint, line)
                                        
                        except serial.SerialException as e:
                            self.add_log("ERROR", f"Serial read error: {e}")
                            time.sleep(5)
                            break
                            
            except serial.SerialException as e:
                self.add_log("ERROR", f"Failed to connect to serial port {self.serial_port}: {e}")
                time.sleep(10)
                
            except Exception as e:
                self.add_log("ERROR", f"Unexpected error in AIS forwarding: {e}")
                time.sleep(10)
        
        self.add_log("INFO", "AIS forwarding loop ended")

# Global AIS manager instance
ais_manager = AISManager()
