"""
Flask routes for WiFi Manager and AIS Configuration web interface and API
"""
from flask import render_template, jsonify, request
from app import app, auth
from app.wifi_manager import (
    scan_networks, get_current_connection, get_connection_ip,
    connect_to_network, forget_network, rescan_networks
)
from app.network_diagnostics import ping_test, get_full_diagnostics
from app.database import get_saved_networks, init_db
from app.ais_manager import ais_manager
from app.ais_config_manager import (
    get_all_endpoints, add_endpoint, update_endpoint, 
    delete_endpoint, toggle_endpoint, load_ais_config
)

# Initialize database on startup
init_db()

# ===== WiFi Manager Routes =====

@app.route('/')
@auth.login_required
def index():
    """Serve the main WiFi management interface"""
    return render_template('index.html')

@app.route('/api/scan', methods=['GET'])
@auth.login_required
def api_scan():
    """API endpoint to scan for available networks"""
    networks = scan_networks()
    return jsonify({'success': True, 'networks': networks})

@app.route('/api/rescan', methods=['POST'])
@auth.login_required
def api_rescan():
    """API endpoint to trigger a new scan"""
    networks = rescan_networks()
    return jsonify({'success': True, 'networks': networks})

@app.route('/api/current', methods=['GET'])
@auth.login_required
def api_current():
    """API endpoint to get current connection"""
    current = get_current_connection()
    ip = get_connection_ip()
    return jsonify({
        'success': True,
        'current': current,
        'ip': ip
    })

@app.route('/api/saved', methods=['GET'])
@auth.login_required
def api_saved():
    """API endpoint to get saved networks"""
    saved = get_saved_networks()
    return jsonify({'success': True, 'networks': saved})

@app.route('/api/connect', methods=['POST'])
@auth.login_required
def api_connect():
    """API endpoint to connect to a network"""
    data = request.json
    ssid = data.get('ssid')
    password = data.get('password')
    
    if not ssid:
        return jsonify({'success': False, 'message': 'SSID is required'}), 400
    
    success, message = connect_to_network(ssid, password)
    return jsonify({'success': success, 'message': message})

@app.route('/api/forget', methods=['POST'])
@auth.login_required
def api_forget():
    """API endpoint to forget a network"""
    data = request.json
    ssid = data.get('ssid')
    
    if not ssid:
        return jsonify({'success': False, 'message': 'SSID is required'}), 400
    
    success, message = forget_network(ssid)
    return jsonify({'success': success, 'message': message})

@app.route('/api/ping', methods=['POST'])
@auth.login_required
def api_ping():
    """API endpoint to run a ping test"""
    data = request.json
    host = data.get('host', '8.8.8.8')
    count = data.get('count', 4)
    
    result = ping_test(host, count)
    return jsonify(result)

@app.route('/api/diagnostics', methods=['GET'])
@auth.login_required
def api_diagnostics():
    """API endpoint to get network diagnostics"""
    diagnostics = get_full_diagnostics()
    return jsonify({'success': True, 'diagnostics': diagnostics})

@app.route('/api/status', methods=['GET'])
@auth.login_required
def api_status():
    """API endpoint to get complete system status"""
    current = get_current_connection()
    ip = get_connection_ip()
    saved = get_saved_networks()
    
    return jsonify({
        'success': True,
        'current': current,
        'ip': ip,
        'saved_count': len(saved)
    })

# ===== AIS Configuration Routes =====

@app.route('/ais')
@auth.login_required
def ais_config():
    """Serve the AIS configuration interface"""
    return render_template('ais_config.html')

@app.route('/ais/logs')
@auth.login_required
def ais_logs():
    """Serve the AIS logs viewer interface"""
    return render_template('ais_logs.html')

@app.route('/api/ais/status', methods=['GET'])
@auth.login_required
def api_ais_status():
    """API endpoint to get AIS service status"""
    status = ais_manager.get_status()
    return jsonify({'success': True, 'status': status})

@app.route('/api/ais/start', methods=['POST'])
@auth.login_required
def api_ais_start():
    """API endpoint to start AIS service"""
    success, message = ais_manager.start()
    return jsonify({'success': success, 'message': message})

@app.route('/api/ais/stop', methods=['POST'])
@auth.login_required
def api_ais_stop():
    """API endpoint to stop AIS service"""
    success, message = ais_manager.stop()
    return jsonify({'success': success, 'message': message})

@app.route('/api/ais/restart', methods=['POST'])
@auth.login_required
def api_ais_restart():
    """API endpoint to restart AIS service"""
    success, message = ais_manager.restart()
    return jsonify({'success': success, 'message': message})

@app.route('/api/ais/logs', methods=['GET'])
@auth.login_required
def api_ais_logs():
    """API endpoint to get AIS logs"""
    count = request.args.get('count', 100, type=int)
    logs = ais_manager.get_logs(count)
    return jsonify({'success': True, 'logs': logs})

@app.route('/api/ais/endpoints', methods=['GET'])
@auth.login_required
def api_ais_endpoints():
    """API endpoint to get all AIS endpoints"""
    endpoints = get_all_endpoints()
    status = ais_manager.get_status()
    
    # Merge endpoint configuration with connection status
    for endpoint in endpoints:
        endpoint_id = endpoint['id']
        if endpoint_id in status['endpoint_status']:
            endpoint['status'] = status['endpoint_status'][endpoint_id]
        else:
            endpoint['status'] = {'connected': False, 'last_attempt': None, 'error': None}
    
    return jsonify({'success': True, 'endpoints': endpoints})

@app.route('/api/ais/endpoints', methods=['POST'])
@auth.login_required
def api_ais_add_endpoint():
    """API endpoint to add a new AIS endpoint"""
    data = request.json
    name = data.get('name')
    ip = data.get('ip')
    port = data.get('port')
    enabled = data.get('enabled', True)
    
    if not name or not ip or not port:
        return jsonify({'success': False, 'message': 'Name, IP, and port are required'}), 400
    
    try:
        port = int(port)
        if port < 1 or port > 65535:
            return jsonify({'success': False, 'message': 'Port must be between 1 and 65535'}), 400
    except ValueError:
        return jsonify({'success': False, 'message': 'Port must be a valid number'}), 400
    
    success, endpoint_id, message = add_endpoint(name, ip, port, enabled)
    
    if success and ais_manager.is_running():
        # Restart AIS service to apply changes
        ais_manager.restart()
    
    return jsonify({'success': success, 'message': message, 'endpoint_id': endpoint_id})

@app.route('/api/ais/endpoints/<endpoint_id>', methods=['PUT'])
@auth.login_required
def api_ais_update_endpoint(endpoint_id):
    """API endpoint to update an existing AIS endpoint"""
    data = request.json
    name = data.get('name')
    ip = data.get('ip')
    port = data.get('port')
    enabled = data.get('enabled', True)
    
    if not name or not ip or not port:
        return jsonify({'success': False, 'message': 'Name, IP, and port are required'}), 400
    
    try:
        port = int(port)
        if port < 1 or port > 65535:
            return jsonify({'success': False, 'message': 'Port must be between 1 and 65535'}), 400
    except ValueError:
        return jsonify({'success': False, 'message': 'Port must be a valid number'}), 400
    
    success, message = update_endpoint(endpoint_id, name, ip, port, enabled)
    
    if success and ais_manager.is_running():
        # Restart AIS service to apply changes
        ais_manager.restart()
    
    return jsonify({'success': success, 'message': message})

@app.route('/api/ais/endpoints/<endpoint_id>', methods=['DELETE'])
@auth.login_required
def api_ais_delete_endpoint(endpoint_id):
    """API endpoint to delete an AIS endpoint"""
    success, message = delete_endpoint(endpoint_id)
    
    if success and ais_manager.is_running():
        # Restart AIS service to apply changes
        ais_manager.restart()
    
    return jsonify({'success': success, 'message': message})

@app.route('/api/ais/endpoints/<endpoint_id>/toggle', methods=['POST'])
@auth.login_required
def api_ais_toggle_endpoint(endpoint_id):
    """API endpoint to toggle an AIS endpoint enabled status"""
    success, message = toggle_endpoint(endpoint_id)
    
    if success and ais_manager.is_running():
        # Restart AIS service to apply changes
        ais_manager.restart()
    
    return jsonify({'success': success, 'message': message})
