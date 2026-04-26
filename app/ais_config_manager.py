"""
AIS Configuration Manager
Handles reading, writing, and backing up AIS configuration file
"""
import configparser
import os
import shutil
from datetime import datetime

# Determine config file location
# Priority: 1) Installed location, 2) Current directory
def get_config_path():
    """Get the correct config file path based on installation"""
    installed_path = '/opt/ais-wifi-manager/ais_config.conf'
    
    # Check if running from installed location
    if os.path.exists(installed_path):
        return installed_path
    
    # Fallback to current directory for development
    return 'ais_config.conf'

CONFIG_FILE = get_config_path()

def load_ais_config():
    """Load AIS configuration from file"""
    if not os.path.exists(CONFIG_FILE):
        # Create default config if it doesn't exist
        create_default_config()
    
    config = configparser.ConfigParser()
    try:
        config.read(CONFIG_FILE)
        
        # Convert to dictionary format
        config_dict = {}
        for section in config.sections():
            config_dict[section] = dict(config.items(section))
        
        return config_dict
    except Exception as e:
        print(f"Error loading config: {e}")
        return None

def create_default_config():
    """Create default configuration file"""
    config = configparser.ConfigParser()
    
    # AIS section with fixed serial port
    config['AIS'] = {
        'serial_port': '/dev/serial0'
    }
    
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            config.write(f)
        return True
    except Exception as e:
        print(f"Error creating default config: {e}")
        return False

def backup_config():
    """Create backup of current configuration"""
    if not os.path.exists(CONFIG_FILE):
        return None
    
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = os.path.join(os.path.dirname(CONFIG_FILE), 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        backup_file = os.path.join(backup_dir, f'ais_config_{timestamp}.conf')
        shutil.copy2(CONFIG_FILE, backup_file)
        
        return backup_file
    except Exception as e:
        print(f"Error creating backup: {e}")
        return None

def save_ais_config(config_dict):
    """Save configuration to file (creates backup first)"""
    try:
        # Create backup before saving
        backup_file = backup_config()
        
        config = configparser.ConfigParser()
        
        # Add all sections from dictionary
        for section, values in config_dict.items():
            config[section] = values
        
        with open(CONFIG_FILE, 'w') as f:
            config.write(f)
        
        return True, f"Configuration saved (backup: {os.path.basename(backup_file) if backup_file else 'none'})"
    except Exception as e:
        return False, f"Error saving config: {e}"

def get_all_endpoints():
    """Get list of all configured endpoints"""
    config = load_ais_config()
    if not config:
        return []
    
    endpoints = []
    for section in config:
        if section.startswith('ENDPOINT_'):
            endpoint = config[section].copy()
            endpoint['id'] = section
            endpoints.append(endpoint)
    
    return endpoints

def add_endpoint(name, ip, port, enabled=True):
    """Add new endpoint to configuration"""
    config = load_ais_config()
    if not config:
        config = {'AIS': {'serial_port': '/dev/serial0'}}
    
    # Find next available endpoint number
    endpoint_nums = []
    for section in config:
        if section.startswith('ENDPOINT_'):
            try:
                num = int(section.split('_')[1])
                endpoint_nums.append(num)
            except:
                pass
    
    next_num = max(endpoint_nums) + 1 if endpoint_nums else 1
    endpoint_id = f'ENDPOINT_{next_num}'
    
    config[endpoint_id] = {
        'name': name,
        'ip': ip,
        'port': str(port),
        'enabled': str(enabled).lower()
    }
    
    success, message = save_ais_config(config)
    if success:
        return True, endpoint_id, message
    return False, None, message

def update_endpoint(endpoint_id, name, ip, port, enabled):
    """Update existing endpoint"""
    config = load_ais_config()
    if not config or endpoint_id not in config:
        return False, "Endpoint not found"
    
    config[endpoint_id] = {
        'name': name,
        'ip': ip,
        'port': str(port),
        'enabled': str(enabled).lower()
    }
    
    return save_ais_config(config)

def delete_endpoint(endpoint_id):
    """Delete endpoint from configuration"""
    config = load_ais_config()
    if not config or endpoint_id not in config:
        return False, "Endpoint not found"
    
    del config[endpoint_id]
    return save_ais_config(config)

def toggle_endpoint(endpoint_id):
    """Toggle endpoint enabled status"""
    config = load_ais_config()
    if not config or endpoint_id not in config:
        return False, "Endpoint not found"
    
    current_enabled = config[endpoint_id].get('enabled', 'false').lower() == 'true'
    config[endpoint_id]['enabled'] = str(not current_enabled).lower()
    
    return save_ais_config(config)
