"""Flask routes for the WiFi Manager + AIS Configuration web interface.

Public endpoints: ``/login``, ``/logout``, ``/static/*`` (handled by Flask).
Everything else requires a logged-in session via ``@login_required``.

API endpoint changes vs. the original
-------------------------------------
* No more ``ais_manager.restart()`` after every config edit — we call
  ``ais_manager.reload_endpoints()`` instead.  Forwarding never pauses,
  the serial port stays open.
* ``GET /healthz`` (unauthenticated) returns 200 only when the forwarder
  thread is alive *and* the serial port still exists.  Useful for
  external watchdogs / Tailscale serve health-checks.
* JSON API endpoints return 401 ``{"success":false,"message":"login required"}``
  when unauthenticated, so the existing JS continues to work without an
  auth-aware redirect.
"""
from __future__ import annotations

import logging

from flask import jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import app
from app.ais_config_manager import (
    add_endpoint, delete_endpoint, get_all_endpoints, toggle_endpoint,
    update_endpoint,
)
from app.ais_manager import ais_manager
from app.database import get_saved_networks, init_db
from app.network_diagnostics import get_full_diagnostics, ping_test
from app.wifi_manager import (
    connect_to_network, forget_network, get_connection_ip,
    get_current_connection, rescan_networks, scan_networks,
)

log = logging.getLogger(__name__)

# Initialise database on first import.
init_db()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def _api_auth_required(view):
    """Decorator that returns JSON 401 instead of redirecting to /login."""
    from functools import wraps

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'success': False,
                            'message': 'login required'}), 401
        return view(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route('/healthz')
def healthz():
    ok = ais_manager.healthy()
    return (jsonify({'ok': ok,
                     'running': ais_manager.running,
                     'serial_port': ais_manager.serial_port}),
            200 if ok else 503)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.route('/')
@login_required
def index():
    return render_template('index.html')


@app.route('/ais')
@login_required
def ais_config():
    return render_template('ais_config.html')


@app.route('/ais/logs')
@login_required
def ais_logs():
    return render_template('ais_logs.html')


# ---------------------------------------------------------------------------
# WiFi APIs
# ---------------------------------------------------------------------------
@app.route('/api/scan', methods=['GET'])
@_api_auth_required
def api_scan():
    return jsonify({'success': True, 'networks': scan_networks()})


@app.route('/api/rescan', methods=['POST'])
@_api_auth_required
def api_rescan():
    return jsonify({'success': True, 'networks': rescan_networks()})


@app.route('/api/current', methods=['GET'])
@_api_auth_required
def api_current():
    return jsonify({
        'success': True,
        'current': get_current_connection(),
        'ip':      get_connection_ip(),
    })


@app.route('/api/saved', methods=['GET'])
@_api_auth_required
def api_saved():
    return jsonify({'success': True, 'networks': get_saved_networks()})


@app.route('/api/connect', methods=['POST'])
@_api_auth_required
def api_connect():
    data = request.get_json(silent=True) or {}
    ssid = data.get('ssid')
    password = data.get('password')
    if not ssid:
        return jsonify({'success': False, 'message': 'SSID is required'}), 400
    success, message = connect_to_network(ssid, password)
    return jsonify({'success': success, 'message': message})


@app.route('/api/forget', methods=['POST'])
@_api_auth_required
def api_forget():
    data = request.get_json(silent=True) or {}
    ssid = data.get('ssid')
    if not ssid:
        return jsonify({'success': False, 'message': 'SSID is required'}), 400
    success, message = forget_network(ssid)
    return jsonify({'success': success, 'message': message})


@app.route('/api/ping', methods=['POST'])
@_api_auth_required
def api_ping():
    data = request.get_json(silent=True) or {}
    return jsonify(ping_test(data.get('host', '8.8.8.8'),
                             data.get('count', 4)))


@app.route('/api/diagnostics', methods=['GET'])
@_api_auth_required
def api_diagnostics():
    return jsonify({'success': True, 'diagnostics': get_full_diagnostics()})


@app.route('/api/status', methods=['GET'])
@_api_auth_required
def api_status():
    return jsonify({
        'success': True,
        'current': get_current_connection(),
        'ip':      get_connection_ip(),
        'saved_count': len(get_saved_networks()),
    })


# ---------------------------------------------------------------------------
# AIS APIs
# ---------------------------------------------------------------------------
@app.route('/api/ais/status', methods=['GET'])
@_api_auth_required
def api_ais_status():
    return jsonify({'success': True, 'status': ais_manager.get_status()})


@app.route('/api/ais/start', methods=['POST'])
@_api_auth_required
def api_ais_start():
    success, message = ais_manager.start()
    return jsonify({'success': success, 'message': message})


@app.route('/api/ais/stop', methods=['POST'])
@_api_auth_required
def api_ais_stop():
    success, message = ais_manager.stop()
    return jsonify({'success': success, 'message': message})


@app.route('/api/ais/restart', methods=['POST'])
@_api_auth_required
def api_ais_restart():
    success, message = ais_manager.restart()
    return jsonify({'success': success, 'message': message})


@app.route('/api/ais/logs', methods=['GET'])
@_api_auth_required
def api_ais_logs():
    count = request.args.get('count', 100, type=int)
    return jsonify({'success': True, 'logs': ais_manager.get_logs(count)})


@app.route('/api/ais/endpoints', methods=['GET'])
@_api_auth_required
def api_ais_endpoints():
    endpoints = get_all_endpoints()
    status = ais_manager.get_status()
    for ep in endpoints:
        ep['status'] = status['endpoint_status'].get(
            ep['id'],
            {'connected': False, 'last_attempt': None, 'error': None},
        )
    return jsonify({'success': True, 'endpoints': endpoints})


@app.route('/api/ais/endpoints', methods=['POST'])
@_api_auth_required
def api_ais_add_endpoint():
    data = request.get_json(silent=True) or {}
    success, endpoint_id, message = add_endpoint(
        data.get('name'), data.get('ip'), data.get('port'),
        bool(data.get('enabled', True)),
    )
    if success and ais_manager.is_running():
        ais_manager.reload_endpoints()
    return jsonify({'success': success, 'message': message,
                    'endpoint_id': endpoint_id})


@app.route('/api/ais/endpoints/<endpoint_id>', methods=['PUT'])
@_api_auth_required
def api_ais_update_endpoint(endpoint_id):
    data = request.get_json(silent=True) or {}
    success, message = update_endpoint(
        endpoint_id, data.get('name'), data.get('ip'),
        data.get('port'), bool(data.get('enabled', True)),
    )
    if success and ais_manager.is_running():
        ais_manager.reload_endpoints()
    return jsonify({'success': success, 'message': message})


@app.route('/api/ais/endpoints/<endpoint_id>', methods=['DELETE'])
@_api_auth_required
def api_ais_delete_endpoint(endpoint_id):
    success, message = delete_endpoint(endpoint_id)
    if success and ais_manager.is_running():
        ais_manager.reload_endpoints()
    return jsonify({'success': success, 'message': message})


@app.route('/api/ais/endpoints/<endpoint_id>/toggle', methods=['POST'])
@_api_auth_required
def api_ais_toggle_endpoint(endpoint_id):
    success, message = toggle_endpoint(endpoint_id)
    if success and ais_manager.is_running():
        ais_manager.reload_endpoints()
    return jsonify({'success': success, 'message': message})
