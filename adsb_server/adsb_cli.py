#!/usr/bin/env python3
"""
ADS-B CLI - Command line interface for managing ADS-B Server
Part of JLBMaritime ADS-B & Wi-Fi Management System
"""

import os
import sys
import subprocess
import configparser

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'adsb_server_config.conf')

def get_service_status():
    """Get the current status of the ADS-B service"""
    try:
        result = subprocess.run(['systemctl', 'is-active', 'adsb-server'], 
                              capture_output=True, text=True)
        return result.stdout.strip()
    except:
        return "unknown"

def start_service():
    """Start the ADS-B service"""
    try:
        subprocess.run(['sudo', 'systemctl', 'start', 'adsb-server'], check=True)
        print("✓ ADS-B Server started")
    except subprocess.CalledProcessError:
        print("✗ Failed to start ADS-B Server")
        
def stop_service():
    """Stop the ADS-B service"""
    try:
        subprocess.run(['sudo', 'systemctl', 'stop', 'adsb-server'], check=True)
        print("✓ ADS-B Server stopped")
    except subprocess.CalledProcessError:
        print("✗ Failed to stop ADS-B Server")
        
def restart_service():
    """Restart the ADS-B service"""
    try:
        subprocess.run(['sudo', 'systemctl', 'restart', 'adsb-server'], check=True)
        print("✓ ADS-B Server restarted")
    except subprocess.CalledProcessError:
        print("✗ Failed to restart ADS-B Server")

def show_status():
    """Show detailed service status"""
    status = get_service_status()
    print(f"\n{'='*50}")
    print(f"ADS-B Server Status: {status.upper()}")
    print(f"{'='*50}")
    
    try:
        result = subprocess.run(['systemctl', 'status', 'adsb-server', '--no-pager'], 
                              capture_output=True, text=True)
        print(result.stdout)
    except:
        print("Unable to retrieve detailed status")

def show_config():
    """Display current configuration"""
    if not os.path.exists(CONFIG_PATH):
        print("Configuration file not found")
        return
        
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    
    print(f"\n{'='*50}")
    print("ADS-B Server Configuration")
    print(f"{'='*50}\n")
    
    # Filter settings
    filter_mode = config.get('Filter', 'mode', fallback='all')
    print(f"Filter Mode: {filter_mode.upper()}")
    
    if filter_mode.lower() != 'all':
        icao_list = config.get('Filter', 'icao_list', fallback='')
        print(f"ICAO Filter: {icao_list}")
    
    # Endpoints
    endpoint_count = config.getint('Endpoints', 'count', fallback=0)
    print(f"\nConfigured Endpoints: {endpoint_count}")
    
    for i in range(endpoint_count):
        ip = config.get('Endpoints', f'endpoint_{i}_ip', fallback='')
        port = config.get('Endpoints', f'endpoint_{i}_port', fallback='')
        print(f"  {i+1}. {ip}:{port}")
    
    print()

def show_logs():
    """Display recent logs"""
    log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'adsb_server.log')
    
    if not os.path.exists(log_file):
        print("No log file found")
        return
    
    print(f"\n{'='*50}")
    print("Recent ADS-B Server Logs (last 50 lines)")
    print(f"{'='*50}\n")
    
    try:
        subprocess.run(['tail', '-n', '50', log_file])
    except:
        # Fallback for systems without tail
        with open(log_file, 'r') as f:
            lines = f.readlines()
            for line in lines[-50:]:
                print(line, end='')

def show_help():
    """Display help information"""
    print("""
ADS-B Server CLI - Management Tool

Usage: adsb_cli.py [command]

Commands:
  start       Start the ADS-B server service
  stop        Stop the ADS-B server service
  restart     Restart the ADS-B server service
  status      Show service status
  config      Display current configuration
  logs        Show recent log entries
  help        Display this help message

Examples:
  sudo python3 adsb_cli.py start
  python3 adsb_cli.py status
  python3 adsb_cli.py logs
""")

def main():
    if len(sys.argv) < 2:
        show_help()
        return
    
    command = sys.argv[1].lower()
    
    if command == 'start':
        start_service()
    elif command == 'stop':
        stop_service()
    elif command == 'restart':
        restart_service()
    elif command == 'status':
        show_status()
    elif command == 'config':
        show_config()
    elif command == 'logs':
        show_logs()
    elif command == 'help':
        show_help()
    else:
        print(f"Unknown command: {command}")
        show_help()

if __name__ == "__main__":
    main()
