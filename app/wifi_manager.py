"""
WiFi Manager Module
Handles WiFi scanning, connecting, and network management using NetworkManager (nmcli)
"""
import subprocess
import re
from app.database import add_saved_network, forget_network as db_forget_network

def run_command(command):
    """Execute a shell command and return output"""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", 1
    except Exception as e:
        return "", str(e), 1

def run_command_with_args(args):
    """Execute a command with argument list (no shell, safer for passwords)"""
    try:
        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", 1
    except Exception as e:
        return "", str(e), 1

def scan_networks():
    """Scan for available WiFi networks using nmcli"""
    command = "nmcli -t -f SSID,SIGNAL,SECURITY device wifi list ifname wlan0"
    stdout, stderr, returncode = run_command(command)
    
    if returncode != 0:
        return []
    
    networks = []
    seen_ssids = set()
    
    for line in stdout.split('\n'):
        if line.strip():
            parts = line.split(':')
            if len(parts) >= 2:
                ssid = parts[0].strip()
                signal = parts[1].strip() if len(parts) > 1 else "0"
                security = parts[2].strip() if len(parts) > 2 else ""
                
                # Skip empty SSIDs and duplicates
                if ssid and ssid not in seen_ssids:
                    seen_ssids.add(ssid)
                    networks.append({
                        'ssid': ssid,
                        'signal': signal,
                        'security': 'Secured' if security else 'Open'
                    })
    
    # Sort by signal strength
    networks.sort(key=lambda x: int(x['signal']), reverse=True)
    return networks

def get_current_connection():
    """Get currently connected WiFi network on wlan0"""
    command = "nmcli -t -f NAME,TYPE,DEVICE connection show --active"
    stdout, stderr, returncode = run_command(command)
    
    if returncode != 0:
        return None
    
    for line in stdout.split('\n'):
        if 'wlan0' in line:
            parts = line.split(':')
            if len(parts) >= 1:
                connection_name = parts[0].strip()
                
                # Get more details about the connection
                detail_cmd = f"nmcli -t -f 802-11-wireless.ssid connection show '{connection_name}'"
                detail_out, _, detail_code = run_command(detail_cmd)
                
                if detail_code == 0 and detail_out:
                    ssid = detail_out.split(':')[-1].strip()
                    return {'ssid': ssid, 'connection_name': connection_name}
                else:
                    return {'ssid': connection_name, 'connection_name': connection_name}
    
    return None

def get_connection_ip():
    """Get IP address of wlan0 interface"""
    command = "ip -4 addr show wlan0 | grep -oP '(?<=inet\\s)\\d+(\\.\\d+){3}'"
    stdout, stderr, returncode = run_command(command)
    
    if returncode == 0 and stdout:
        return stdout.split('\n')[0]
    return "Not connected"

def connect_to_network(ssid, password=None):
    """Connect to a WiFi network"""
    # If password is provided, delete any existing connection first
    # This ensures the new password is used
    if password:
        check_cmd = f"nmcli connection show '{ssid}'"
        _, _, check_code = run_command(check_cmd)
        
        if check_code == 0:
            # Delete existing connection using args (safer for special chars in SSID)
            delete_args = ['nmcli', 'connection', 'delete', ssid]
            run_command_with_args(delete_args)
        
        # Create new connection with password using args (safer for special chars)
        connect_args = ['nmcli', 'device', 'wifi', 'connect', ssid, 
                       'password', password, 'ifname', 'wlan0']
        stdout, stderr, returncode = run_command_with_args(connect_args)
    else:
        # For open networks, try to reuse existing connection
        check_cmd = f"nmcli connection show '{ssid}'"
        _, _, check_code = run_command(check_cmd)
        
        if check_code == 0:
            # Connection exists, activate it using args
            connect_args = ['nmcli', 'connection', 'up', ssid, 'ifname', 'wlan0']
            stdout, stderr, returncode = run_command_with_args(connect_args)
        else:
            # Create new connection for open network using args
            connect_args = ['nmcli', 'device', 'wifi', 'connect', ssid, 'ifname', 'wlan0']
            stdout, stderr, returncode = run_command_with_args(connect_args)
    
    if returncode == 0:
        # Add to saved networks database
        add_saved_network(ssid)
        return True, "Connected successfully"
    else:
        error_msg = stderr if stderr else "Failed to connect"
        return False, error_msg

def forget_network(ssid):
    """Forget a saved network"""
    # Get current connection to prevent forgetting active network
    current = get_current_connection()
    if current and current['ssid'] == ssid:
        return False, "Cannot forget currently active network"
    
    # Delete from NetworkManager
    command = f"nmcli connection delete '{ssid}'"
    stdout, stderr, returncode = run_command(command)
    
    # Always try to remove from database even if nmcli fails
    db_forget_network(ssid)
    
    if returncode == 0:
        return True, "Network forgotten"
    else:
        # If the connection doesn't exist in NetworkManager, still return success
        # since it's removed from our database
        return True, "Network forgotten"

def rescan_networks():
    """Trigger a new WiFi scan"""
    command = "nmcli device wifi rescan ifname wlan0"
    run_command(command)
    # Wait a moment for scan to complete
    import time
    time.sleep(2)
    return scan_networks()
