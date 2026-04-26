"""
Network Diagnostics Module
Handles ping tests and network status information
"""
import subprocess
import re

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

def ping_test(host='8.8.8.8', count=4):
    """Run a ping test to specified host"""
    command = f"ping -c {count} {host}"
    stdout, stderr, returncode = run_command(command)
    
    result = {
        'success': returncode == 0,
        'host': host,
        'output': stdout if returncode == 0 else stderr
    }
    
    # Parse ping statistics if successful
    if returncode == 0:
        # Extract packet loss
        loss_match = re.search(r'(\d+)% packet loss', stdout)
        if loss_match:
            result['packet_loss'] = loss_match.group(1) + '%'
        
        # Extract min/avg/max/mdev times
        time_match = re.search(r'min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms', stdout)
        if time_match:
            result['min_time'] = time_match.group(1) + ' ms'
            result['avg_time'] = time_match.group(2) + ' ms'
            result['max_time'] = time_match.group(3) + ' ms'
    
    return result

def get_interface_status():
    """Get status of network interfaces"""
    interfaces = {}
    
    # Get wlan0 status
    wlan0_cmd = "ip link show wlan0"
    stdout, _, returncode = run_command(wlan0_cmd)
    if returncode == 0:
        interfaces['wlan0'] = {
            'status': 'UP' if 'state UP' in stdout else 'DOWN',
            'exists': True
        }
    else:
        interfaces['wlan0'] = {'status': 'Not found', 'exists': False}
    
    # Get wlan1 status (hotspot interface)
    wlan1_cmd = "ip link show wlan1"
    stdout, _, returncode = run_command(wlan1_cmd)
    if returncode == 0:
        interfaces['wlan1'] = {
            'status': 'UP' if 'state UP' in stdout else 'DOWN',
            'exists': True
        }
    else:
        interfaces['wlan1'] = {'status': 'Not found', 'exists': False}
    
    return interfaces

def get_connection_stats():
    """Get WiFi connection statistics for wlan0"""
    stats = {}
    
    # Get signal strength and other stats
    command = "nmcli -t -f GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS,SIGNAL device show wlan0"
    stdout, stderr, returncode = run_command(command)
    
    if returncode == 0:
        for line in stdout.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                if 'STATE' in key:
                    stats['state'] = value.strip()
                elif 'CONNECTION' in key:
                    stats['connection'] = value.strip()
                elif 'IP4.ADDRESS' in key:
                    stats['ip_address'] = value.strip()
    
    # Get signal strength from iwconfig
    signal_cmd = "iwconfig wlan0 2>/dev/null | grep -i 'Signal level'"
    stdout, _, returncode = run_command(signal_cmd)
    if returncode == 0 and stdout:
        signal_match = re.search(r'Signal level[=:](-?\d+)', stdout)
        if signal_match:
            stats['signal_strength'] = signal_match.group(1) + ' dBm'
    
    return stats

def get_gateway():
    """Get default gateway"""
    command = "ip route | grep default | awk '{print $3}'"
    stdout, stderr, returncode = run_command(command)
    
    if returncode == 0 and stdout:
        return stdout.split('\n')[0]
    return "Unknown"

def get_dns_servers():
    """Get DNS servers"""
    command = "nmcli -t -f IP4.DNS device show wlan0"
    stdout, stderr, returncode = run_command(command)
    
    dns_servers = []
    if returncode == 0:
        for line in stdout.split('\n'):
            if 'IP4.DNS' in line:
                dns = line.split(':')[-1].strip()
                if dns:
                    dns_servers.append(dns)
    
    return dns_servers if dns_servers else ["None configured"]

def get_full_diagnostics():
    """Get comprehensive network diagnostics"""
    return {
        'interfaces': get_interface_status(),
        'connection_stats': get_connection_stats(),
        'gateway': get_gateway(),
        'dns_servers': get_dns_servers()
    }
