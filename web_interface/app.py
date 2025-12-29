#!/usr/bin/env python3
"""
Web Application - Flask-based management interface
Part of JLBMaritime ADS-B & Wi-Fi Management System
"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sys
import os
import configparser
import subprocess
import json
from functools import wraps
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from wifi_manager.wifi_controller import WiFiController

app = Flask(__name__)
app.secret_key = 'jlbmaritime-adsb-secret-key-change-in-production'

# Configuration paths
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
ADSB_CONFIG_PATH = os.path.join(BASE_DIR, 'config', 'adsb_server_config.conf')
WEB_CONFIG_PATH = os.path.join(BASE_DIR, 'config', 'web_config.conf')
LOG_PATH = os.path.join(BASE_DIR, 'logs', 'adsb_server.log')

# Initialize WiFi controller
wifi = WiFiController('wlan0')

# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Load credentials from config
        config = configparser.ConfigParser()
        if os.path.exists(WEB_CONFIG_PATH):
            config.read(WEB_CONFIG_PATH)
            stored_username = config.get('Auth', 'username', fallback='JLBMaritime')
            stored_password = config.get('Auth', 'password', fallback='Admin')
        else:
            stored_username = 'JLBMaritime'
            stored_password = 'Admin'
            
        if username == stored_username and password == stored_password:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid credentials')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Logout"""
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    """Main dashboard page"""
    return render_template('index.html')

# ============= API ENDPOINTS =============

# Dashboard APIs
@app.route('/api/dashboard/status')
@login_required
def get_dashboard_status():
    """Get system status for dashboard"""
    try:
        # ADS-B Server status
        adsb_status = subprocess.run(['systemctl', 'is-active', 'adsb-server'],
                                    capture_output=True, text=True)
        adsb_running = adsb_status.stdout.strip() == 'active'
        
        # Get uptime
        if adsb_running:
            uptime_result = subprocess.run(['systemctl', 'show', 'adsb-server', 
                                          '--property=ActiveEnterTimestamp'],
                                         capture_output=True, text=True)
            uptime = uptime_result.stdout.strip().split('=')[1] if '=' in uptime_result.stdout else 'Unknown'
        else:
            uptime = 'N/A'
            
        # WiFi status
        current_wifi = wifi.get_current_network()
        
        # System info
        hostname_result = subprocess.run(['hostname'], capture_output=True, text=True)
        hostname = hostname_result.stdout.strip()
        
        return jsonify({
            'success': True,
            'adsb_server': {
                'running': adsb_running,
                'uptime': uptime
            },
            'wifi': current_wifi,
            'hostname': hostname
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# WiFi Manager APIs
@app.route('/api/wifi/scan')
@login_required
def wifi_scan():
    """Scan for available networks"""
    try:
        networks = wifi.scan_networks()
        return jsonify({'success': True, 'networks': networks})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/wifi/saved')
@login_required
def wifi_saved():
    """Get saved networks"""
    try:
        saved = wifi.get_saved_networks()
        current = wifi.get_current_network()
        current_ssid = current['ssid'] if current else None
        
        return jsonify({
            'success': True,
            'networks': saved,
            'current': current_ssid
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/wifi/current')
@login_required
def wifi_current():
    """Get current connection info"""
    try:
        current = wifi.get_current_network()
        return jsonify({'success': True, 'network': current})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/wifi/connect', methods=['POST'])
@login_required
def wifi_connect():
    """Connect to a network"""
    try:
        data = request.get_json()
        ssid = data.get('ssid')
        password = data.get('password')
        
        success = wifi.connect_to_network(ssid, password)
        return jsonify({'success': success})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/wifi/forget', methods=['POST'])
@login_required
def wifi_forget():
    """Forget a network"""
    try:
        data = request.get_json()
        ssid = data.get('ssid')
        
        success = wifi.forget_network(ssid)
        return jsonify({'success': success})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/wifi/ping', methods=['POST'])
@login_required
def wifi_ping():
    """Run ping test"""
    try:
        data = request.get_json()
        host = data.get('host', '8.8.8.8')
        
        result = wifi.ping_test(host)
        return jsonify({
            'success': True,
            'ping_success': result['success'],
            'output': result['output']
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/wifi/diagnostics')
@login_required
def wifi_diagnostics():
    """Get network diagnostics"""
    try:
        diag = wifi.get_diagnostics()
        return jsonify({'success': True, 'diagnostics': diag})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ADS-B Configuration APIs
@app.route('/api/adsb/config')
@login_required
def get_adsb_config():
    """Get ADS-B configuration"""
    try:
        config = configparser.ConfigParser()
        config.read(ADSB_CONFIG_PATH)
        
        filter_mode = config.get('Filter', 'mode', fallback='all')
        icao_list = config.get('Filter', 'icao_list', fallback='').split(',')
        icao_list = [icao.strip() for icao in icao_list if icao.strip()]
        
        endpoints = []
        endpoint_count = config.getint('Endpoints', 'count', fallback=0)
        for i in range(endpoint_count):
            ip = config.get('Endpoints', f'endpoint_{i}_ip', fallback='')
            port = config.get('Endpoints', f'endpoint_{i}_port', fallback='')
            if ip and port:
                endpoints.append({'ip': ip, 'port': port})
                
        return jsonify({
            'success': True,
            'filter_mode': filter_mode,
            'icao_list': icao_list,
            'endpoints': endpoints
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/adsb/config', methods=['POST'])
@login_required
def update_adsb_config():
    """Update ADS-B configuration"""
    try:
        data = request.get_json()
        
        config = configparser.ConfigParser()
        config.read(ADSB_CONFIG_PATH)
        
        # Update filter
        if 'filter_mode' in data:
            config.set('Filter', 'mode', data['filter_mode'])
            
        if 'icao_list' in data:
            icao_string = ','.join(data['icao_list'])
            config.set('Filter', 'icao_list', icao_string)
            
        # Update endpoints
        if 'endpoints' in data:
            config.set('Endpoints', 'count', str(len(data['endpoints'])))
            for i, endpoint in enumerate(data['endpoints']):
                config.set('Endpoints', f'endpoint_{i}_ip', endpoint['ip'])
                config.set('Endpoints', f'endpoint_{i}_port', str(endpoint['port']))
                
        # Save configuration
        with open(ADSB_CONFIG_PATH, 'w') as f:
            config.write(f)
            
        # Restart ADS-B service
        subprocess.run(['sudo', 'systemctl', 'restart', 'adsb-server'])
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/adsb/service/<action>', methods=['POST'])
@login_required
def adsb_service_control(action):
    """Control ADS-B service"""
    try:
        if action in ['start', 'stop', 'restart']:
            subprocess.run(['sudo', 'systemctl', action, 'adsb-server'], check=True)
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Invalid action'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/adsb/test-endpoint', methods=['POST'])
@login_required
def test_endpoint():
    """Test connection to an endpoint"""
    try:
        data = request.get_json()
        import socket
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((data['ip'], int(data['port'])))
        sock.close()
        
        return jsonify({'success': result == 0})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Logs & Troubleshooting APIs
@app.route('/api/logs/view')
@login_required
def view_logs():
    """View log file contents"""
    try:
        filter_level = request.args.get('level', 'all')
        
        if not os.path.exists(LOG_PATH):
            return jsonify({'success': True, 'logs': []})
            
        with open(LOG_PATH, 'r') as f:
            lines = f.readlines()
            
        # Filter by level if specified
        if filter_level != 'all':
            lines = [line for line in lines if filter_level.upper() in line]
            
        # Return last 500 lines
        logs = lines[-500:]
        
        return jsonify({'success': True, 'logs': logs})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/logs/download')
@login_required
def download_logs():
    """Download log file"""
    try:
        from flask import send_file
        return send_file(LOG_PATH, as_attachment=True, download_name='adsb_server.log')
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/logs/clear', methods=['POST'])
@login_required
def clear_logs():
    """Clear log file"""
    try:
        with open(LOG_PATH, 'w') as f:
            f.write('')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Settings APIs
@app.route('/api/settings/password', methods=['POST'])
@login_required
def change_password():
    """Change web interface password"""
    try:
        data = request.get_json()
        new_password = data.get('password')
        
        config = configparser.ConfigParser()
        if os.path.exists(WEB_CONFIG_PATH):
            config.read(WEB_CONFIG_PATH)
        else:
            config['Auth'] = {}
            config['Auth']['username'] = 'JLBMaritime'
            
        config.set('Auth', 'password', new_password)
        
        with open(WEB_CONFIG_PATH, 'w') as f:
            config.write(f)
            
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/settings/system-info')
@login_required
def get_system_info():
    """Get system information"""
    try:
        # Hostname
        hostname = subprocess.run(['hostname'], capture_output=True, text=True).stdout.strip()
        
        # OS version
        with open('/etc/os-release', 'r') as f:
            os_info = f.read()
        
        # Uptime
        uptime = subprocess.run(['uptime', '-p'], capture_output=True, text=True).stdout.strip()
        
        return jsonify({
            'success': True,
            'hostname': hostname,
            'os_info': os_info,
            'uptime': uptime
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/settings/backup')
@login_required
def backup_config():
    """Backup configuration"""
    try:
        from flask import send_file
        import zipfile
        import tempfile
        
        # Create temporary zip file
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        
        with zipfile.ZipFile(temp_zip.name, 'w') as zf:
            zf.write(ADSB_CONFIG_PATH, 'adsb_server_config.conf')
            if os.path.exists(WEB_CONFIG_PATH):
                zf.write(WEB_CONFIG_PATH, 'web_config.conf')
                
        return send_file(temp_zip.name, as_attachment=True, 
                        download_name=f'adsb_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip')
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    # Ensure config directory exists
    os.makedirs(os.path.join(BASE_DIR, 'config'), exist_ok=True)
    
    # Create default config if it doesn't exist
    if not os.path.exists(ADSB_CONFIG_PATH):
        config = configparser.ConfigParser()
        config['Dump1090'] = {'host': '127.0.0.1', 'port': '30005'}
        config['Filter'] = {'mode': 'specific', 'icao_list': 'A92F2D,A932E4,A9369B,A93A52'}
        config['Endpoints'] = {'count': '0'}
        with open(ADSB_CONFIG_PATH, 'w') as f:
            config.write(f)
            
    if not os.path.exists(WEB_CONFIG_PATH):
        config = configparser.ConfigParser()
        config['Auth'] = {'username': 'JLBMaritime', 'password': 'Admin'}
        with open(WEB_CONFIG_PATH, 'w') as f:
            config.write(f)
    
    # Run server
    app.run(host='0.0.0.0', port=5000, debug=False)
