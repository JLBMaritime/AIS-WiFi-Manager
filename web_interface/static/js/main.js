// JLBMaritime ADS-B & Wi-Fi Manager - Frontend JavaScript

// Global variables
let currentSSID = null;
let currentEndpoints = [];
let currentICAOList = [];

// Tab Navigation
function openTab(tabName) {
    // Hide all tabs
    const tabs = document.getElementsByClassName('tab-content');
    for (let tab of tabs) {
        tab.classList.remove('active');
    }
    
    // Remove active class from buttons
    const buttons = document.getElementsByClassName('tab-button');
    for (let button of buttons) {
        button.classList.remove('active');
    }
    
    // Show selected tab
    document.getElementById(tabName).classList.add('active');
    event.target.classList.add('active');
    
    // Load tab-specific data
    switch(tabName) {
        case 'dashboard':
            refreshDashboard();
            break;
        case 'wifi':
            loadCurrentNetwork();
            loadSavedNetworks();
            break;
        case 'adsb':
            loadADSBConfig();
            break;
        case 'settings':
            loadSystemInfo();
            break;
    }
}

// Dashboard Functions
async function refreshDashboard() {
    try {
        const response = await fetch('/api/dashboard/status');
        const data = await response.json();
        
        if (data.success) {
            // ADS-B Status
            const statusBadge = document.getElementById('adsb-status');
            statusBadge.textContent = data.adsb_server.running ? 'RUNNING' : 'STOPPED';
            statusBadge.className = data.adsb_server.running ? 'badge running' : 'badge stopped';
            
            document.getElementById('adsb-uptime').textContent = data.adsb_server.uptime || 'N/A';
            
            // WiFi Status
            if (data.wifi) {
                document.getElementById('wifi-ssid').textContent = data.wifi.ssid;
                document.getElementById('wifi-ip').textContent = data.wifi.ip;
                document.getElementById('wifi-signal').textContent = data.wifi.signal + '%';
            } else {
                document.getElementById('wifi-ssid').textContent = 'Not Connected';
                document.getElementById('wifi-ip').textContent = 'N/A';
                document.getElementById('wifi-signal').textContent = 'N/A';
            }
            
            // System Info
            document.getElementById('system-hostname').textContent = data.hostname;
        }
    } catch (error) {
        console.error('Error refreshing dashboard:', error);
    }
}

// WiFi Manager Functions
async function loadCurrentNetwork() {
    try {
        const response = await fetch('/api/wifi/current');
        const data = await response.json();
        
        const container = document.getElementById('current-network-info');
        if (data.success && data.network) {
            container.innerHTML = `
                <div class="status-grid">
                    <div class="status-item">
                        <span class="label">Network:</span>
                        <span>${data.network.ssid}</span>
                    </div>
                    <div class="status-item">
                        <span class="label">IP Address:</span>
                        <span>${data.network.ip}</span>
                    </div>
                    <div class="status-item">
                        <span class="label">Signal:</span>
                        <span>${data.network.signal}%</span>
                    </div>
                </div>
            `;
        } else {
            container.innerHTML = '<p>Not connected to any network</p>';
        }
    } catch (error) {
        console.error('Error loading current network:', error);
    }
}

async function scanNetworks() {
    const container = document.getElementById('available-networks');
    container.innerHTML = '<p>Scanning for networks...</p>';
    
    try {
        const response = await fetch('/api/wifi/scan');
        const data = await response.json();
        
        if (data.success && data.networks.length > 0) {
            container.innerHTML = '';
            data.networks.forEach(network => {
                const networkDiv = document.createElement('div');
                networkDiv.className = 'network-item';
                networkDiv.innerHTML = `
                    <div class="network-info">
                        <div class="network-name">${network.ssid}</div>
                        <div class="network-details">
                            Signal: ${network.signal}% ${network.encrypted ? '🔒' : ''}
                        </div>
                    </div>
                    <button class="btn btn-primary" onclick="showConnectModal('${network.ssid}', ${network.encrypted})">Connect</button>
                `;
                container.appendChild(networkDiv);
            });
        } else {
            container.innerHTML = '<p>No networks found</p>';
        }
    } catch (error) {
        console.error('Error scanning networks:', error);
        container.innerHTML = '<p>Error scanning for networks</p>';
    }
}

async function loadSavedNetworks() {
    try {
        const response = await fetch('/api/wifi/saved');
        const data = await response.json();
        
        const container = document.getElementById('saved-networks');
        if (data.success && data.networks.length > 0) {
            container.innerHTML = '';
            data.networks.forEach(network => {
                const isCurrent = network.ssid === data.current;
                const networkDiv = document.createElement('div');
                networkDiv.className = isCurrent ? 'network-item current' : 'network-item';
                networkDiv.innerHTML = `
                    <div class="network-info">
                        <div class="network-name">${network.ssid} ${isCurrent ? '(Connected)' : ''}</div>
                    </div>
                    <div class="button-group">
                        ${!isCurrent ? `<button class="btn btn-primary" onclick="connectToSaved('${network.ssid}')">Connect</button>` : ''}
                        ${!isCurrent ? `<button class="btn btn-danger" onclick="forgetNetwork('${network.ssid}')">Forget</button>` : ''}
                    </div>
                `;
                container.appendChild(networkDiv);
            });
        } else {
            container.innerHTML = '<p>No saved networks</p>';
        }
    } catch (error) {
        console.error('Error loading saved networks:', error);
    }
}

function showConnectModal(ssid, encrypted) {
    currentSSID = ssid;
    document.getElementById('connect-ssid').textContent = `Network: ${ssid}`;
    document.getElementById('network-password').value = '';
    
    if (!encrypted) {
        document.getElementById('network-password').placeholder = 'Open network (no password required)';
    } else {
        document.getElementById('network-password').placeholder = 'Enter password';
    }
    
    document.getElementById('connect-modal').classList.add('active');
}

function closeModal() {
    document.getElementById('connect-modal').classList.remove('active');
    currentSSID = null;
}

async function connectToNetwork() {
    const password = document.getElementById('network-password').value;
    
    try {
        const response = await fetch('/api/wifi/connect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                ssid: currentSSID,
                password: password || null
            })
        });
        
        const data = await response.json();
        if (data.success) {
            alert('Connecting to network... Please wait.');
            closeModal();
            setTimeout(() => {
                loadCurrentNetwork();
                loadSavedNetworks();
            }, 5000);
        } else {
            alert('Failed to connect to network');
        }
    } catch (error) {
        console.error('Error connecting to network:', error);
        alert('Error connecting to network');
    }
}

async function connectToSaved(ssid) {
    try {
        const response = await fetch('/api/wifi/connect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ssid: ssid})
        });
        
        const data = await response.json();
        if (data.success) {
            alert('Connecting to network...');
            setTimeout(() => {
                loadCurrentNetwork();
                loadSavedNetworks();
            }, 3000);
        } else {
            alert('Failed to connect to network');
        }
    } catch (error) {
        console.error('Error connecting to network:', error);
    }
}

async function forgetNetwork(ssid) {
    if (!confirm(`Forget network "${ssid}"?`)) return;
    
    try {
        const response = await fetch('/api/wifi/forget', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ssid: ssid})
        });
        
        const data = await response.json();
        if (data.success) {
            loadSavedNetworks();
        } else {
            alert('Failed to forget network');
        }
    } catch (error) {
        console.error('Error forgetting network:', error);
    }
}

async function runPing() {
    const host = document.getElementById('ping-host').value;
    const results = document.getElementById('ping-results');
    results.innerHTML = '<p>Running ping test...</p>';
    
    try {
        const response = await fetch('/api/wifi/ping', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({host: host})
        });
        
        const data = await response.json();
        if (data.success) {
            results.innerHTML = `<pre>${data.output}</pre>`;
        } else {
            results.innerHTML = '<p>Ping test failed</p>';
        }
    } catch (error) {
        console.error('Error running ping:', error);
        results.innerHTML = '<p>Error running ping test</p>';
    }
}

async function runDiagnostics() {
    const output = document.getElementById('diagnostics-output');
    output.innerHTML = '<p>Running diagnostics...</p>';
    
    try {
        const response = await fetch('/api/wifi/diagnostics');
        const data = await response.json();
        
        if (data.success) {
            const diag = data.diagnostics;
            output.innerHTML = `
                <div class="status-grid">
                    <div class="status-item">
                        <span class="label">Interface Up:</span>
                        <span>${diag.interface_up ? 'Yes' : 'No'}</span>
                    </div>
                    <div class="status-item">
                        <span class="label">Gateway:</span>
                        <span>${diag.gateway}</span>
                    </div>
                    <div class="status-item">
                        <span class="label">DNS Servers:</span>
                        <span>${diag.dns ? diag.dns.join(', ') : 'None'}</span>
                    </div>
                </div>
                <pre>${diag.ip_config}</pre>
            `;
        }
    } catch (error) {
        console.error('Error running diagnostics:', error);
        output.innerHTML = '<p>Error running diagnostics</p>';
    }
}

// ADS-B Configuration Functions
async function loadADSBConfig() {
    try {
        const response = await fetch('/api/adsb/config');
        const data = await response.json();
        
        if (data.success) {
            // Set filter mode
            document.querySelector(`input[name="filter-mode"][value="${data.filter_mode}"]`).checked = true;
            toggleFilterMode();
            
            // Set ICAO list
            if (data.filter_mode === 'specific') {
                document.getElementById('icao-input').value = data.icao_list.join(',');
            }
            currentICAOList = data.icao_list;
            
            // Set endpoints
            currentEndpoints = data.endpoints;
            displayEndpoints();
        }
    } catch (error) {
        console.error('Error loading ADS-B config:', error);
    }
}

function toggleFilterMode() {
    const mode = document.querySelector('input[name="filter-mode"]:checked').value;
    const icaoSection = document.getElementById('icao-filter-section');
    icaoSection.style.display = mode === 'specific' ? 'block' : 'none';
}

function displayEndpoints() {
    const container = document.getElementById('endpoints-list');
    container.innerHTML = '';
    
    if (currentEndpoints.length === 0) {
        container.innerHTML = '<p>No endpoints configured</p>';
        return;
    }
    
    currentEndpoints.forEach((endpoint, index) => {
        const div = document.createElement('div');
        div.className = 'endpoint-item';
        div.innerHTML = `
            <div>
                <strong>${endpoint.ip}:${endpoint.port}</strong>
            </div>
            <div class="button-group">
                <button class="btn btn-secondary" onclick="testEndpoint('${endpoint.ip}', ${endpoint.port})">Test</button>
                <button class="btn btn-danger" onclick="removeEndpoint(${index})">Remove</button>
            </div>
        `;
        container.appendChild(div);
    });
}

function addEndpoint() {
    const ip = document.getElementById('endpoint-ip').value.trim();
    const port = parseInt(document.getElementById('endpoint-port').value);
    
    if (!ip || !port) {
        alert('Please enter both IP and port');
        return;
    }
    
    currentEndpoints.push({ip, port});
    displayEndpoints();
    
    document.getElementById('endpoint-ip').value = '';
    document.getElementById('endpoint-port').value = '';
}

function removeEndpoint(index) {
    currentEndpoints.splice(index, 1);
    displayEndpoints();
}

async function testEndpoint(ip, port) {
    try {
        const response = await fetch('/api/adsb/test-endpoint', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ip, port})
        });
        
        const data = await response.json();
        alert(data.success ? 'Connection successful!' : 'Connection failed');
    } catch (error) {
        alert('Error testing endpoint');
    }
}

async function saveADSBConfig() {
    const filterMode = document.querySelector('input[name="filter-mode"]:checked').value;
    let icaoList = [];
    
    if (filterMode === 'specific') {
        const input = document.getElementById('icao-input').value;
        icaoList = input.split(',').map(s => s.trim().toUpperCase()).filter(s => s);
    }
    
    try {
        const response = await fetch('/api/adsb/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                filter_mode: filterMode,
                icao_list: icaoList,
                endpoints: currentEndpoints
            })
        });
        
        const data = await response.json();
        if (data.success) {
            alert('Configuration saved and ADS-B server restarted');
        } else {
            alert('Failed to save configuration');
        }
    } catch (error) {
        console.error('Error saving config:', error);
        alert('Error saving configuration');
    }
}

async function controlADSBService(action) {
    try {
        const response = await fetch(`/api/adsb/service/${action}`, {method: 'POST'});
        const data = await response.json();
        
        if (data.success) {
            alert(`ADS-B server ${action}ed successfully`);
            setTimeout(refreshDashboard, 2000);
        } else {
            alert(`Failed to ${action} ADS-B server`);
        }
    } catch (error) {
        console.error('Error controlling service:', error);
        alert('Error controlling service');
    }
}

// Logs & Troubleshooting Functions
async function refreshLogs() {
    const level = document.getElementById('log-filter').value;
    const viewer = document.getElementById('log-viewer');
    viewer.innerHTML = '<p>Loading logs...</p>';
    
    try {
        const response = await fetch(`/api/logs/view?level=${level}`);
        const data = await response.json();
        
        if (data.success) {
            if (data.logs.length > 0) {
                viewer.innerHTML = `<pre>${data.logs.join('')}</pre>`;
            } else {
                viewer.innerHTML = '<p>No logs available</p>';
            }
        } else {
            viewer.innerHTML = '<p>Error loading logs</p>';
        }
    } catch (error) {
        console.error('Error loading logs:', error);
        viewer.innerHTML = '<p>Error loading logs</p>';
    }
}

function downloadLogs() {
    window.location.href = '/api/logs/download';
}

async function clearLogs() {
    if (!confirm('Clear all logs?')) return;
    
    try {
        const response = await fetch('/api/logs/clear', {method: 'POST'});
        const data = await response.json();
        
        if (data.success) {
            alert('Logs cleared');
            refreshLogs();
        }
    } catch (error) {
        console.error('Error clearing logs:', error);
    }
}

// Settings Functions
async function changePassword() {
    const newPass = document.getElementById('new-password').value;
    const confirmPass = document.getElementById('confirm-password').value;
    
    if (!newPass || !confirmPass) {
        alert('Please enter and confirm the new password');
        return;
    }
    
    if (newPass !== confirmPass) {
        alert('Passwords do not match');
        return;
    }
    
    try {
        const response = await fetch('/api/settings/password', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({password: newPass})
        });
        
        const data = await response.json();
        if (data.success) {
            alert('Password updated successfully. You will be logged out.');
            setTimeout(() => {window.location.href = '/logout';}, 1000);
        }
    } catch (error) {
        console.error('Error changing password:', error);
        alert('Error changing password');
    }
}

async function loadSystemInfo() {
    try {
        const response = await fetch('/api/settings/system-info');
        const data = await response.json();
        
        if (data.success) {
            document.getElementById('system-info').innerHTML = `
                <div class="status-grid">
                    <div class="status-item">
                        <span class="label">Hostname:</span>
                        <span>${data.hostname}</span>
                    </div>
                    <div class="status-item">
                        <span class="label">Uptime:</span>
                        <span>${data.uptime}</span>
                    </div>
                </div>
                <pre>${data.os_info}</pre>
            `;
        }
    } catch (error) {
        console.error('Error loading system info:', error);
    }
}

function backupConfig() {
    window.location.href = '/api/settings/backup';
}

// Logout
function logout() {
    window.location.href = '/logout';
}

// Initialize on page load
window.addEventListener('DOMContentLoaded', () => {
    refreshDashboard();
});
