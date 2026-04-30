#!/usr/bin/env python3
"""
AIS-WiFi Manager CLI
Unified command-line interface for WiFi and AIS management
"""
import sys
import os
import subprocess

# Add parent directory to path to import app modules
# Use realpath to properly resolve symlinks
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from app.wifi_manager import (
    scan_networks, get_current_connection, get_connection_ip,
    connect_to_network, forget_network as wifi_forget_network,
    hotspot_status, hotspot_psk, hotspot_up, hotspot_down,
    hotspot_set_psk, AP_CON_NAME, AP_DEFAULT_SSID,
)

from app.network_diagnostics import ping_test, get_full_diagnostics
from app.database import (
    get_saved_networks, init_db, set_password, reset_user_to_default,
    DEFAULT_USER, DEFAULT_PASSWORD,
)
from app.ais_config_manager import (
    get_all_endpoints, add_endpoint, update_endpoint,
    delete_endpoint, toggle_endpoint
)

HOTSPOT_PASSWORD_FILE = '/opt/ais-wifi-manager/HOTSPOT_PASSWORD.txt'

# Service name for systemctl commands
SERVICE_NAME = 'ais-wifi-manager'

# Helper functions for service control
def is_service_running():
    """Check if the AIS service is running via systemctl"""
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', SERVICE_NAME],
            capture_output=True,
            text=True
        )
        return result.stdout.strip() == 'active'
    except Exception:
        return False

def get_service_logs(lines=50):
    """Get service logs from journalctl"""
    try:
        result = subprocess.run(
            ['journalctl', '-u', SERVICE_NAME, '-n', str(lines), '--no-pager'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception:
        return None

def control_service(action):
    """Control the service via systemctl (start/stop/restart)"""
    try:
        result = subprocess.run(
            ['systemctl', action, SERVICE_NAME],
            capture_output=True,
            text=True
        )
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)

# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

def color_text(text, color):
    """Apply color to text"""
    return f"{color}{text}{Colors.END}"

def print_header():
    """Print CLI header"""
    print("\n" + "="*80)
    print(color_text("                    AIS-WiFi Manager CLI v1.0", Colors.BOLD))
    print("="*80)

def print_menu():
    """Print main menu"""
    print("\n" + color_text("Main Menu:", Colors.BOLD))
    print("\n" + color_text(" WiFi Management:", Colors.CYAN))
    print("   1. Scan for networks")
    print("   2. Connect to network")
    print("   3. Show current connection")
    print("   4. List saved networks")
    print("   5. Forget network")
    print("   6. Run network diagnostics")
    print("   7. Run ping test")
    
    print("\n" + color_text(" AIS Management:", Colors.CYAN))
    print("   8. AIS service status")
    print("   9. Start AIS service")
    print("  10. Stop AIS service")
    print("  11. Restart AIS service")
    print("  12. View AIS logs")
    print("  13. List endpoints")
    print("  14. Add endpoint")
    print("  15. Edit endpoint")
    print("  16. Delete endpoint")
    print("  17. Enable/disable endpoint")
    
    print("\n" + color_text(" System:", Colors.CYAN))
    print("  18. Show complete system status")
    print("  19. Exit")
    print("-"*80)

# ============================================================================
# WiFi Management Functions
# ============================================================================

def scan_and_display():
    """Scan and display available networks"""
    print("\n" + color_text("Scanning for networks...", Colors.YELLOW))
    networks = scan_networks()
    
    if not networks:
        print(color_text("No networks found.", Colors.RED))
        return
    
    print(f"\n{color_text('Found', Colors.GREEN)} {len(networks)} {color_text('networks:', Colors.GREEN)}")
    print("-"*80)
    print(f"{'#':<4} {'SSID':<35} {'Signal':<10} {'Security':<15}")
    print("-"*80)
    
    for idx, network in enumerate(networks, 1):
        ssid = network['ssid'][:33]
        signal = network['signal']
        
        # Color code signal strength
        if int(signal) >= 70:
            signal_str = color_text(f"{signal}%", Colors.GREEN)
        elif int(signal) >= 40:
            signal_str = color_text(f"{signal}%", Colors.YELLOW)
        else:
            signal_str = color_text(f"{signal}%", Colors.RED)
        
        security = network['security']
        print(f"{idx:<4} {ssid:<35} {signal_str:<20} {security:<15}")
    
    print("-"*80)

def connect_to_network_cli():
    """Connect to a network via CLI"""
    print("\n" + color_text("--- Connect to Network ---", Colors.BOLD))
    
    # First scan networks
    scan_and_display()
    
    ssid = input("\nEnter network SSID (or 'c' to cancel): ").strip()
    if ssid.lower() == 'c':
        return
    
    if not ssid:
        print(color_text("Error: SSID cannot be empty", Colors.RED))
        return
    
    password = input("Enter password (leave empty for open networks): ").strip()
    
    print(f"\n{color_text('Connecting to', Colors.YELLOW)} '{ssid}'...")
    success, message = connect_to_network(ssid, password if password else None)
    
    if success:
        print(color_text(f"✓ {message}", Colors.GREEN))
    else:
        print(color_text(f"✗ {message}", Colors.RED))

def show_current_connection():
    """Display current connection information"""
    print("\n" + color_text("--- Current Connection ---", Colors.BOLD))
    
    current = get_current_connection()
    ip = get_connection_ip()
    
    if current and current['ssid']:
        print(f"Network:    {color_text(current['ssid'], Colors.GREEN)}")
        print(f"IP Address: {color_text(ip, Colors.CYAN)}")
    else:
        print(color_text("Not connected to any network", Colors.YELLOW))

def list_saved_networks_cli():
    """List saved networks"""
    print("\n" + color_text("--- Saved Networks ---", Colors.BOLD))
    
    saved = get_saved_networks()
    current = get_current_connection()
    current_ssid = current['ssid'] if current else None
    
    if not saved:
        print(color_text("No saved networks", Colors.YELLOW))
        return
    
    print("-"*80)
    print(f"{'#':<4} {'SSID':<50} {'Status':<20}")
    print("-"*80)
    
    for idx, network in enumerate(saved, 1):
        ssid = network['ssid'][:48]
        status = color_text("(Connected)", Colors.GREEN) if network['ssid'] == current_ssid else ""
        print(f"{idx:<4} {ssid:<50} {status:<30}")
    
    print("-"*80)

def forget_network_cli():
    """Forget a saved network"""
    print("\n" + color_text("--- Forget Network ---", Colors.BOLD))
    
    saved = get_saved_networks()
    current = get_current_connection()
    current_ssid = current['ssid'] if current else None
    
    if not saved:
        print(color_text("No saved networks", Colors.YELLOW))
        return
    
    print("-"*80)
    print(f"{'#':<4} {'SSID':<50} {'Status':<20}")
    print("-"*80)
    
    for idx, network in enumerate(saved, 1):
        ssid = network['ssid'][:48]
        status = color_text("(Connected)", Colors.GREEN) if network['ssid'] == current_ssid else ""
        print(f"{idx:<4} {ssid:<50} {status:<30}")
    
    print("-"*80)
    
    choice = input("\nEnter network number to forget (or 'c' to cancel): ").strip()
    
    if choice.lower() == 'c':
        return
    
    try:
        idx = int(choice)
        if 1 <= idx <= len(saved):
            ssid = saved[idx - 1]['ssid']
            
            confirm = input(f"Forget '{ssid}'? (y/n): ").strip().lower()
            if confirm != 'y':
                print(color_text("Cancelled", Colors.YELLOW))
                return
            
            success, message = wifi_forget_network(ssid)
            if success:
                print(color_text(f"✓ {message}", Colors.GREEN))
            else:
                print(color_text(f"✗ {message}", Colors.RED))
        else:
            print(color_text("Invalid network number", Colors.RED))
    except ValueError:
        print(color_text("Invalid input", Colors.RED))

def run_diagnostics():
    """Run and display network diagnostics"""
    print("\n" + color_text("--- Network Diagnostics ---", Colors.BOLD))
    
    diagnostics = get_full_diagnostics()
    
    # Interface status
    print("\n" + color_text("Interface Status:", Colors.CYAN))
    for iface, info in diagnostics['interfaces'].items():
        status = info['status']
        if status == 'UP':
            status_str = color_text(status, Colors.GREEN)
        else:
            status_str = color_text(status, Colors.RED)
        print(f"  {iface}: {status_str}")
    
    # Connection stats
    if diagnostics['connection_stats']:
        print("\n" + color_text("Connection Statistics:", Colors.CYAN))
        for key, value in diagnostics['connection_stats'].items():
            print(f"  {key}: {value}")
    
    # Gateway and DNS
    print(f"\n{color_text('Gateway:', Colors.CYAN)} {diagnostics['gateway']}")
    print(f"{color_text('DNS Servers:', Colors.CYAN)} {', '.join(diagnostics['dns_servers'])}")

def run_ping_test_cli():
    """Run ping test via CLI"""
    print("\n" + color_text("--- Ping Test ---", Colors.BOLD))
    
    host = input("Enter host to ping (default: 8.8.8.8): ").strip()
    if not host:
        host = "8.8.8.8"
    
    count = input("Enter number of pings (default: 4): ").strip()
    try:
        count = int(count) if count else 4
    except ValueError:
        count = 4
    
    print(f"\n{color_text('Pinging', Colors.YELLOW)} {host}...")
    result = ping_test(host, count)
    
    if result['success']:
        print(color_text("\n✓ Ping successful", Colors.GREEN))
        if 'packet_loss' in result:
            print(f"Packet Loss: {result['packet_loss']}")
        if 'min_time' in result:
            print(f"Min: {result['min_time']}")
            print(f"Avg: {result['avg_time']}")
            print(f"Max: {result['max_time']}")
        print(f"\nFull output:\n{result['output']}")
    else:
        print(color_text("\n✗ Ping failed", Colors.RED))
        print(f"Error: {result['output']}")

# ============================================================================
# AIS Management Functions
# ============================================================================

def show_ais_status():
    """Display AIS service status"""
    print("\n" + color_text("--- AIS Service Status ---", Colors.BOLD))
    
    # Check service status via systemctl
    running = is_service_running()
    
    # Service status
    if running:
        status_str = color_text("RUNNING", Colors.GREEN)
    else:
        status_str = color_text("STOPPED", Colors.RED)
    
    print(f"Service:     {status_str}")
    print(f"Serial Port: {color_text('/dev/serial0', Colors.CYAN)}")
    
    # Endpoints from config file
    endpoints = get_all_endpoints()
    if endpoints:
        print(f"\n{color_text('Endpoints:', Colors.CYAN)} {len(endpoints)} configured")
        print("-"*80)
        print(f"{'Name':<25} {'Address':<25} {'Enabled':<10}")
        print("-"*80)
        
        for endpoint in endpoints:
            name = endpoint['name'][:23]
            address = f"{endpoint['ip']}:{endpoint['port']}"
            enabled = endpoint.get('enabled', 'true') == 'true'
            enabled_str = color_text("Yes", Colors.GREEN) if enabled else color_text("No", Colors.YELLOW)
            
            print(f"{name:<25} {address:<25} {enabled_str:<20}")
        
        print("-"*80)
    else:
        print(color_text("\nNo endpoints configured", Colors.YELLOW))

def start_ais_service():
    """Start AIS service"""
    print("\n" + color_text("Starting AIS service...", Colors.YELLOW))
    success, message = control_service('start')
    
    if success:
        print(color_text("✓ Service started", Colors.GREEN))
    else:
        print(color_text(f"✗ Failed to start service: {message}", Colors.RED))

def stop_ais_service():
    """Stop AIS service"""
    confirm = input(f"\n{color_text('Stop AIS service?', Colors.YELLOW)} (y/n): ").strip().lower()
    if confirm != 'y':
        print(color_text("Cancelled", Colors.YELLOW))
        return
    
    print(color_text("Stopping AIS service...", Colors.YELLOW))
    success, message = control_service('stop')
    
    if success:
        print(color_text("✓ Service stopped", Colors.GREEN))
    else:
        print(color_text(f"✗ Failed to stop service: {message}", Colors.RED))

def restart_ais_service():
    """Restart AIS service"""
    print("\n" + color_text("Restarting AIS service...", Colors.YELLOW))
    success, message = control_service('restart')
    
    if success:
        print(color_text("✓ Service restarted", Colors.GREEN))
    else:
        print(color_text(f"✗ Failed to restart service: {message}", Colors.RED))

def view_ais_logs():
    """View AIS service logs"""
    print("\n" + color_text("--- AIS Service Logs ---", Colors.BOLD))
    
    count = input("Enter number of log lines to display (default: 50): ").strip()
    try:
        count = int(count) if count else 50
    except ValueError:
        count = 50
    
    logs = get_service_logs(count)
    
    if logs:
        print(f"\n{color_text('Last', Colors.CYAN)} {count} {color_text('log entries:', Colors.CYAN)}")
        print("-"*80)
        print(logs)
        print("-"*80)
    else:
        print(color_text("No logs available or unable to access journalctl", Colors.YELLOW))

def list_endpoints():
    """List all AIS endpoints"""
    print("\n" + color_text("--- AIS Endpoints ---", Colors.BOLD))
    
    endpoints = get_all_endpoints()
    
    if not endpoints:
        print(color_text("No endpoints configured", Colors.YELLOW))
        return
    
    print("-"*80)
    print(f"{'ID':<5} {'Name':<20} {'IP Address':<18} {'Port':<8} {'Enabled':<10}")
    print("-"*80)
    
    for endpoint in endpoints:
        ep_id = endpoint['id']
        name = endpoint['name'][:18]
        ip = endpoint['ip']
        port = endpoint['port']
        enabled = endpoint.get('enabled', 'true') == 'true'
        enabled_str = color_text("Yes", Colors.GREEN) if enabled else color_text("No", Colors.YELLOW)
        
        print(f"{ep_id:<5} {name:<20} {ip:<18} {port:<8} {enabled_str:<20}")
    
    print("-"*80)

def add_endpoint_cli():
    """Add a new AIS endpoint"""
    print("\n" + color_text("--- Add New Endpoint ---", Colors.BOLD))
    
    name = input("Enter endpoint name (e.g., Chart Plotter): ").strip()
    if not name:
        print(color_text("Error: Name cannot be empty", Colors.RED))
        return
    
    ip = input("Enter IP address: ").strip()
    if not ip:
        print(color_text("Error: IP address cannot be empty", Colors.RED))
        return
    
    port_str = input("Enter port number: ").strip()
    try:
        port = int(port_str)
        if port < 1 or port > 65535:
            print(color_text("Error: Port must be between 1 and 65535", Colors.RED))
            return
    except ValueError:
        print(color_text("Error: Port must be a valid number", Colors.RED))
        return
    
    enabled = input("Enable endpoint? (Y/n): ").strip().lower()
    enabled = enabled != 'n'
    
    print(f"\n{color_text('Adding endpoint...', Colors.YELLOW)}")
    success, endpoint_id, message = add_endpoint(name, ip, port, enabled)
    
    if success:
        print(color_text(f"✓ {message}", Colors.GREEN))
        print(f"Endpoint ID: {endpoint_id}")
        
        # Restart service if running
        if is_service_running():
            print(color_text("Restarting AIS service to apply changes...", Colors.YELLOW))
            control_service('restart')
    else:
        print(color_text(f"✗ {message}", Colors.RED))

def edit_endpoint_cli():
    """Edit an existing AIS endpoint"""
    print("\n" + color_text("--- Edit Endpoint ---", Colors.BOLD))
    
    # List endpoints first
    endpoints = get_all_endpoints()
    
    if not endpoints:
        print(color_text("No endpoints configured", Colors.YELLOW))
        return
    
    print("-"*80)
    print(f"{'ID':<5} {'Name':<20} {'IP Address':<18} {'Port':<8}")
    print("-"*80)
    
    for endpoint in endpoints:
        print(f"{endpoint['id']:<5} {endpoint['name']:<20} {endpoint['ip']:<18} {endpoint['port']:<8}")
    
    print("-"*80)
    
    ep_id = input("\nEnter endpoint ID to edit (or 'c' to cancel): ").strip()
    
    if ep_id.lower() == 'c':
        return
    
    # Find endpoint
    endpoint = next((e for e in endpoints if e['id'] == ep_id), None)
    if not endpoint:
        print(color_text("Endpoint not found", Colors.RED))
        return
    
    print(f"\nCurrent values:")
    print(f"  Name: {endpoint['name']}")
    print(f"  IP: {endpoint['ip']}")
    print(f"  Port: {endpoint['port']}")
    print(f"  Enabled: {'Yes' if endpoint.get('enabled', 'true') == 'true' else 'No'}")
    
    # Get new values
    name = input(f"\nNew name (or Enter to keep '{endpoint['name']}'): ").strip()
    if not name:
        name = endpoint['name']
    
    ip = input(f"New IP (or Enter to keep '{endpoint['ip']}'): ").strip()
    if not ip:
        ip = endpoint['ip']
    
    port_str = input(f"New port (or Enter to keep '{endpoint['port']}'): ").strip()
    if port_str:
        try:
            port = int(port_str)
            if port < 1 or port > 65535:
                print(color_text("Error: Port must be between 1 and 65535", Colors.RED))
                return
        except ValueError:
            print(color_text("Error: Port must be a valid number", Colors.RED))
            return
    else:
        port = int(endpoint['port'])
    
    current_enabled = endpoint.get('enabled', 'true') == 'true'
    enabled_input = input(f"Enabled (Y/n, current: {'Yes' if current_enabled else 'No'}): ").strip().lower()
    if enabled_input:
        enabled = enabled_input != 'n'
    else:
        enabled = current_enabled
    
    print(f"\n{color_text('Updating endpoint...', Colors.YELLOW)}")
    success, message = update_endpoint(ep_id, name, ip, port, enabled)
    
    if success:
        print(color_text(f"✓ {message}", Colors.GREEN))
        
        # Restart service if running
        if is_service_running():
            print(color_text("Restarting AIS service to apply changes...", Colors.YELLOW))
            control_service('restart')
    else:
        print(color_text(f"✗ {message}", Colors.RED))

def delete_endpoint_cli():
    """Delete an AIS endpoint"""
    print("\n" + color_text("--- Delete Endpoint ---", Colors.BOLD))
    
    # List endpoints first
    endpoints = get_all_endpoints()
    
    if not endpoints:
        print(color_text("No endpoints configured", Colors.YELLOW))
        return
    
    print("-"*80)
    print(f"{'ID':<5} {'Name':<20} {'IP Address':<18} {'Port':<8}")
    print("-"*80)
    
    for endpoint in endpoints:
        print(f"{endpoint['id']:<5} {endpoint['name']:<20} {endpoint['ip']:<18} {endpoint['port']:<8}")
    
    print("-"*80)
    
    ep_id = input("\nEnter endpoint ID to delete (or 'c' to cancel): ").strip()
    
    if ep_id.lower() == 'c':
        return
    
    # Find endpoint
    endpoint = next((e for e in endpoints if e['id'] == ep_id), None)
    if not endpoint:
        print(color_text("Endpoint not found", Colors.RED))
        return
    
    confirm = input(f"\n{color_text('Delete', Colors.RED)} endpoint '{endpoint['name']}'? (y/n): ").strip().lower()
    if confirm != 'y':
        print(color_text("Cancelled", Colors.YELLOW))
        return
    
    print(f"\n{color_text('Deleting endpoint...', Colors.YELLOW)}")
    success, message = delete_endpoint(ep_id)
    
    if success:
        print(color_text(f"✓ {message}", Colors.GREEN))
        
        # Restart service if running
        if is_service_running():
            print(color_text("Restarting AIS service to apply changes...", Colors.YELLOW))
            control_service('restart')
    else:
        print(color_text(f"✗ {message}", Colors.RED))

def toggle_endpoint_cli():
    """Enable/disable an AIS endpoint"""
    print("\n" + color_text("--- Enable/Disable Endpoint ---", Colors.BOLD))
    
    # List endpoints first
    endpoints = get_all_endpoints()
    
    if not endpoints:
        print(color_text("No endpoints configured", Colors.YELLOW))
        return
    
    print("-"*80)
    print(f"{'ID':<5} {'Name':<20} {'IP Address':<18} {'Port':<8} {'Enabled':<10}")
    print("-"*80)
    
    for endpoint in endpoints:
        enabled = endpoint.get('enabled', 'true') == 'true'
        enabled_str = color_text("Yes", Colors.GREEN) if enabled else color_text("No", Colors.YELLOW)
        print(f"{endpoint['id']:<5} {endpoint['name']:<20} {endpoint['ip']:<18} {endpoint['port']:<8} {enabled_str:<20}")
    
    print("-"*80)
    
    ep_id = input("\nEnter endpoint ID to toggle (or 'c' to cancel): ").strip()
    
    if ep_id.lower() == 'c':
        return
    
    # Find endpoint
    endpoint = next((e for e in endpoints if e['id'] == ep_id), None)
    if not endpoint:
        print(color_text("Endpoint not found", Colors.RED))
        return
    
    current_enabled = endpoint.get('enabled', 'true') == 'true'
    action = "disable" if current_enabled else "enable"
    
    print(f"\n{color_text(f'{action.capitalize()} endpoint...', Colors.YELLOW)}")
    success, message = toggle_endpoint(ep_id)
    
    if success:
        print(color_text(f"✓ {message}", Colors.GREEN))
        
        # Restart service if running
        if is_service_running():
            print(color_text("Restarting AIS service to apply changes...", Colors.YELLOW))
            control_service('restart')
    else:
        print(color_text(f"✗ {message}", Colors.RED))

# ============================================================================
# System Functions
# ============================================================================

def show_complete_status():
    """Show complete system status"""
    print("\n" + color_text("="*80, Colors.BOLD))
    print(color_text("                Complete System Status", Colors.BOLD))
    print(color_text("="*80, Colors.BOLD))
    
    # WiFi Status
    print("\n" + color_text("WiFi Connection:", Colors.CYAN))
    current = get_current_connection()
    ip = get_connection_ip()
    
    if current and current['ssid']:
        print(f"  Network:    {color_text(current['ssid'], Colors.GREEN)}")
        print(f"  IP Address: {color_text(ip, Colors.CYAN)}")
    else:
        print(f"  {color_text('Not connected', Colors.RED)}")
    
    # AIS Status
    print("\n" + color_text("AIS Service:", Colors.CYAN))
    running = is_service_running()
    
    if running:
        print(f"  Status: {color_text('RUNNING', Colors.GREEN)}")
    else:
        print(f"  Status: {color_text('STOPPED', Colors.RED)}")
    
    print(f"  Serial Port: /dev/serial0")
    
    # Endpoints
    endpoints = get_all_endpoints()
    if endpoints:
        print(f"\n  {color_text('Endpoints:', Colors.CYAN)} {len(endpoints)} configured")
        enabled_count = sum(1 for e in endpoints if e.get('enabled', 'true') == 'true')
        print(f"    Enabled:   {enabled_count}/{len(endpoints)}")
    else:
        print(f"  {color_text('No endpoints configured', Colors.YELLOW)}")
    
    # Network Interfaces
    print("\n" + color_text("Network Interfaces:", Colors.CYAN))
    diagnostics = get_full_diagnostics()
    for iface, info in diagnostics['interfaces'].items():
        status_str = color_text(info['status'], Colors.GREEN if info['status'] == 'UP' else Colors.RED)
        print(f"  {iface}: {status_str}")
    
    print("\n" + color_text("="*80, Colors.BOLD))

# ============================================================================
# Main Function
# ============================================================================

# ============================================================================
# Non-interactive subcommands
# ============================================================================

def cmd_reset_password(argv):
    """`ais-wifi-cli reset-password [--to PASSWORD] [--user NAME]`

    With no flags: restore the install default (JLBMaritime / Admin)
    and force a change on next login.  This is the SSH-based recovery
    path documented on the login page.

    With `--to`: set an explicit password (must be ≥ 8 chars).
    """
    import argparse
    parser = argparse.ArgumentParser(prog='ais-wifi-cli reset-password',
                                     add_help=True)
    parser.add_argument('--user', default=DEFAULT_USER,
                        help='Username to reset (default: %(default)s)')
    parser.add_argument('--to', default=None,
                        help='Set this exact password '
                             '(default: restore install default and force change)')
    args = parser.parse_args(argv)

    if os.geteuid() != 0:
        print(color_text("This command must be run with sudo "
                         "(it edits /opt/ais-wifi-manager/wifi_manager.db).",
                         Colors.RED))
        return 2

    init_db()
    if args.to is None:
        reset_user_to_default(args.user)
        print(color_text(
            f"User '{args.user}' reset to default password "
            f"('{DEFAULT_PASSWORD}'). The user will be forced to "
            "change it on next login.", Colors.GREEN))
        return 0

    if len(args.to) < 8:
        print(color_text("Password must be at least 8 characters.",
                         Colors.RED))
        return 1
    if set_password(args.user, args.to, must_change=False):
        print(color_text(f"Password for '{args.user}' updated.",
                         Colors.GREEN))
        return 0
    print(color_text("Failed to update password.", Colors.RED))
    return 1


def cmd_show_hotspot(_argv):
    """`ais-wifi-cli show-hotspot` — print the live AP credentials.

    Reads from NetworkManager (the source of truth) so this is always
    accurate even after the user rotates the PSK; the static
    HOTSPOT_PASSWORD.txt file is only consulted as a last-ditch fallback
    if NM doesn't yet know about the AP profile (e.g. installer was
    interrupted before step 7b).
    """
    if os.geteuid() != 0:
        print(color_text(
            "This command needs sudo (PSKs are NM secrets, "
            "and the seed file is mode 600 root).",
            Colors.RED))
        return 2

    status = hotspot_status()
    psk    = hotspot_psk()

    if status['ssid'] or psk:
        print(f"SSID:     {status['ssid'] or AP_DEFAULT_SSID}")
        if psk:
            print(f"Password: {psk}")
        print(f"Iface:    {status['iface']}")
        print(f"IP:       {status['ip'] or '(not up)'}")
        print(f"State:    "
              f"{'activated' if status['active'] else 'inactive'}")
        print(f"Clients:  {status['clients']}")
        return 0

    # Fallback: NM doesn't know about the connection (probably because the
    # installer was interrupted before step 7b).  Read the seed file.
    if not os.path.exists(HOTSPOT_PASSWORD_FILE):
        print(color_text(
            f"NetworkManager has no '{AP_CON_NAME}' profile and there is "
            f"no seed at {HOTSPOT_PASSWORD_FILE}. Run the installer.",
            Colors.RED))
        return 1
    try:
        with open(HOTSPOT_PASSWORD_FILE, 'r') as f:
            print(color_text(
                "(NM profile not present; falling back to install-time "
                "seed file. Re-run the installer to materialise the AP.)",
                Colors.YELLOW))
            print(f.read().rstrip())
        return 0
    except OSError as exc:
        print(color_text(f"Cannot read {HOTSPOT_PASSWORD_FILE}: {exc}",
                         Colors.RED))
        return 1


# ----- hotspot subcommand --------------------------------------------------
def _hotspot_status_print():
    s = hotspot_status()
    psk = hotspot_psk() if os.geteuid() == 0 else None
    print(color_text("Hotspot:", Colors.BOLD))
    print(f"  SSID:    {s['ssid'] or '(unknown)'}")
    if psk:
        print(f"  PSK:     {psk}")
    elif os.geteuid() != 0:
        print(f"  PSK:     (run with sudo to reveal)")
    print(f"  Iface:   {s['iface']}")
    print(f"  IP:      {s['ip'] or '(not up)'}")
    state_col = Colors.GREEN if s['active'] else Colors.RED
    print(f"  State:   {color_text('activated' if s['active'] else 'inactive', state_col)}")
    print(f"  Clients: {s['clients']}")


def cmd_hotspot(argv):
    """`ais-wifi-cli hotspot {status|up|down|rotate-pw|diagnose}`"""
    sub = argv[0] if argv else 'status'

    if sub == 'status':
        _hotspot_status_print()
        return 0

    if sub == 'up':
        if os.geteuid() != 0:
            print(color_text("Needs sudo.", Colors.RED)); return 2
        ok, msg = hotspot_up()
        print(color_text(("✓ " if ok else "✗ ") + msg,
                         Colors.GREEN if ok else Colors.RED))
        return 0 if ok else 1

    if sub == 'down':
        if os.geteuid() != 0:
            print(color_text("Needs sudo.", Colors.RED)); return 2
        ok, msg = hotspot_down()
        print(color_text(("✓ " if ok else "✗ ") + msg,
                         Colors.GREEN if ok else Colors.RED))
        return 0 if ok else 1

    if sub == 'rotate-pw':
        if os.geteuid() != 0:
            print(color_text("Needs sudo.", Colors.RED)); return 2
        import secrets, string
        alphabet = string.ascii_letters + string.digits
        new_psk = ''.join(secrets.choice(alphabet) for _ in range(16))
        ok, msg = hotspot_set_psk(new_psk)
        if not ok:
            print(color_text(f"✗ {msg}", Colors.RED))
            return 1
        # Sync the seed file so future show-hotspot fallback also reads
        # the current value (and so HOTSPOT_PASSWORD.txt isn't a stale
        # artefact).
        try:
            ssid = hotspot_status()['ssid'] or AP_DEFAULT_SSID
            with open(HOTSPOT_PASSWORD_FILE, 'w') as f:
                f.write(f"SSID:     {ssid}\nPassword: {new_psk}\n")
            os.chmod(HOTSPOT_PASSWORD_FILE, 0o600)
        except OSError as exc:
            print(color_text(f"  (warning: could not update {HOTSPOT_PASSWORD_FILE}: {exc})",
                             Colors.YELLOW))
        print(color_text(f"✓ {msg}", Colors.GREEN))
        print(f"  New PSK: {new_psk}")
        return 0

    if sub == 'diagnose':
        # Best-effort, read-only.  Captures the same probes a human would run.
        print(color_text("Hotspot diagnostics:", Colors.BOLD))
        print("\n[A] NetworkManager device view")
        subprocess.run(["nmcli", "-t", "-f",
                        "DEVICE,TYPE,STATE,CONNECTION", "device"])
        print("\n[B] Active connections")
        subprocess.run(["nmcli", "-t", "-f",
                        "NAME,DEVICE,STATE", "connection", "show", "--active"])
        print("\n[C] System dnsmasq.service status (must be inactive — see README)")
        subprocess.run(["systemctl", "is-active", "dnsmasq"])
        print("\n[D] Listeners on :53 / :67")
        subprocess.run(["ss", "-lntup", "( sport = :53 or sport = :67 )"])
        print("\n[E] AP radio capability")
        subprocess.run(["bash", "-c",
                        "iw list 2>/dev/null | "
                        "awk '/Wiphy/{p=$0} "
                        "/Supported interface modes/,/Supported commands/' "
                        "| head -n 40"])
        print("\n[F] Live AP info on iface")
        from app.wifi_manager import AP_IFACE as _IFACE
        subprocess.run(["iw", "dev", _IFACE, "info"])
        print()
        _hotspot_status_print()
        return 0

    print(color_text(
        "Usage: ais-wifi-cli hotspot {status|up|down|rotate-pw|diagnose}",
        Colors.RED))
    return 2



def cmd_health(_argv):
    """`ais-wifi-cli health` — quick liveness check."""
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen('http://127.0.0.1/healthz', timeout=3) as r:
            print(r.read().decode('utf-8', errors='replace'))
            return 0 if r.status == 200 else 1
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}")
        return 1
    except OSError as e:
        print(color_text(f"Cannot reach local server: {e}", Colors.RED))
        return 1


def _dispatch_subcommand():
    """If argv[1] is a known subcommand, run it and exit; else fall through
    to the interactive menu."""
    if len(sys.argv) < 2:
        return None
    sub = sys.argv[1]
    handlers = {
        'reset-password': cmd_reset_password,
        'show-hotspot':   cmd_show_hotspot,
        'hotspot':        cmd_hotspot,
        'health':         cmd_health,
    }
    if sub in handlers:
        sys.exit(handlers[sub](sys.argv[2:]) or 0)
    if sub in ('-h', '--help', 'help'):
        print("AIS-WiFi Manager CLI")
        print("Usage:")
        print("  ais-wifi-cli                     Interactive menu")
        print("  sudo ais-wifi-cli reset-password [--to NEWPASS] [--user NAME]")
        print("  sudo ais-wifi-cli show-hotspot")
        print("       ais-wifi-cli hotspot status")
        print("  sudo ais-wifi-cli hotspot {up|down|rotate-pw|diagnose}")
        print("  ais-wifi-cli health")
        sys.exit(0)
    return None



def main():
    """Main CLI loop"""
    _dispatch_subcommand()

    # Initialize database
    init_db()
    
    # Check if running as root
    if os.geteuid() != 0:
        print(color_text("Warning: This tool should be run with sudo for full functionality", Colors.YELLOW))
        print("Example: sudo ais-wifi-cli")
        response = input("\nContinue anyway? (y/n): ").strip().lower()
        if response != 'y':
            sys.exit(0)
    
    print_header()
    
    while True:
        print_menu()
        choice = input(f"\n{color_text('Enter your choice (1-19):', Colors.BOLD)} ").strip()
        
        try:
            if choice == '1':
                scan_and_display()
            elif choice == '2':
                connect_to_network_cli()
            elif choice == '3':
                show_current_connection()
            elif choice == '4':
                list_saved_networks_cli()
            elif choice == '5':
                forget_network_cli()
            elif choice == '6':
                run_diagnostics()
            elif choice == '7':
                run_ping_test_cli()
            elif choice == '8':
                show_ais_status()
            elif choice == '9':
                start_ais_service()
            elif choice == '10':
                stop_ais_service()
            elif choice == '11':
                restart_ais_service()
            elif choice == '12':
                view_ais_logs()
            elif choice == '13':
                list_endpoints()
            elif choice == '14':
                add_endpoint_cli()
            elif choice == '15':
                edit_endpoint_cli()
            elif choice == '16':
                delete_endpoint_cli()
            elif choice == '17':
                toggle_endpoint_cli()
            elif choice == '18':
                show_complete_status()
            elif choice == '19':
                print(f"\n{color_text('Exiting AIS-WiFi Manager CLI...', Colors.CYAN)}")
                sys.exit(0)
            else:
                print(color_text("\nInvalid choice. Please enter a number between 1 and 19.", Colors.RED))
        except KeyboardInterrupt:
            print(f"\n\n{color_text('Exiting AIS-WiFi Manager CLI...', Colors.CYAN)}")
            sys.exit(0)
        except Exception as e:
            print(color_text(f"\nError: {e}", Colors.RED))
            import traceback
            traceback.print_exc()
        
        input(f"\n{color_text('Press Enter to continue...', Colors.YELLOW)}")

if __name__ == '__main__':
    main()
