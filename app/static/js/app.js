// WiFi Manager JavaScript
let currentSSID = null;
let savedNetworkSSIDs = [];
let updateInterval = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

function initializeApp() {
    // Initial data load
    loadCurrentConnection();
    loadAvailableNetworks();
    loadSavedNetworks();
    
    // Start auto-update polling (every 5 seconds)
    updateInterval = setInterval(updateStatus, 5000);
    
    // Setup event listeners
    document.getElementById('scan-btn').addEventListener('click', rescanNetworks);
    document.getElementById('ping-btn').addEventListener('click', runPingTest);
    document.getElementById('modal-connect').addEventListener('click', connectFromModal);
    document.getElementById('modal-cancel').addEventListener('click', closeModal);
    
    // Close modal when clicking outside
    document.getElementById('password-modal').addEventListener('click', function(e) {
        if (e.target === this) {
            closeModal();
        }
    });
    
    // Allow Enter key in password field
    document.getElementById('modal-password').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            connectFromModal();
        }
    });
}

// Update status periodically
function updateStatus() {
    loadCurrentConnection();
    loadSavedNetworks();
}

// Load current connection
function loadCurrentConnection() {
    fetch('/api/current')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const ssidElement = document.getElementById('current-ssid');
                const ipElement = document.getElementById('current-ip');
                
                if (data.current && data.current.ssid) {
                    currentSSID = data.current.ssid;
                    ssidElement.textContent = data.current.ssid;
                    ipElement.textContent = data.ip;
                } else {
                    currentSSID = null;
                    ssidElement.textContent = 'Not connected';
                    ipElement.textContent = '-';
                }
            }
        })
        .catch(error => {
            console.error('Error loading current connection:', error);
        });
}

// Load available networks
function loadAvailableNetworks() {
    const container = document.getElementById('available-networks');
    container.innerHTML = '<div class="loading">Scanning for networks...</div>';
    
    fetch('/api/scan')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.networks.length > 0) {
                container.innerHTML = '';
                data.networks.forEach(network => {
                    // Skip if this is a saved network
                    if (savedNetworkSSIDs.includes(network.ssid)) return;
                    
                    const networkElement = createNetworkElement(network, false);
                    container.appendChild(networkElement);
                });
                
                // Check if any networks were added
                if (container.children.length === 0) {
                    container.innerHTML = '<div class="loading">No other networks found</div>';
                }
            } else {
                container.innerHTML = '<div class="loading">No networks found</div>';
            }
        })
        .catch(error => {
            console.error('Error loading networks:', error);
            container.innerHTML = '<div class="loading">Error loading networks</div>';
        });
}

// Rescan networks
function rescanNetworks() {
    const btn = document.getElementById('scan-btn');
    btn.disabled = true;
    btn.textContent = 'Scanning...';
    
    const container = document.getElementById('available-networks');
    container.innerHTML = '<div class="loading">Scanning for networks...</div>';
    
    fetch('/api/rescan', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success && data.networks.length > 0) {
                container.innerHTML = '';
                data.networks.forEach(network => {
                    // Skip if this is a saved network
                    if (savedNetworkSSIDs.includes(network.ssid)) return;
                    
                    const networkElement = createNetworkElement(network, false);
                    container.appendChild(networkElement);
                });
                
                // Check if any networks were added
                if (container.children.length === 0) {
                    container.innerHTML = '<div class="loading">No other networks found</div>';
                }
                showToast('Scan complete', 'success');
            } else {
                container.innerHTML = '<div class="loading">No networks found</div>';
            }
        })
        .catch(error => {
            console.error('Error rescanning networks:', error);
            container.innerHTML = '<div class="loading">Error scanning networks</div>';
            showToast('Scan failed', 'error');
        })
        .finally(() => {
            btn.disabled = false;
            btn.textContent = 'Scan';
        });
}

// Load saved networks
function loadSavedNetworks() {
    const container = document.getElementById('saved-networks');
    
    fetch('/api/saved')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.networks.length > 0) {
                // Update saved networks list for filtering
                savedNetworkSSIDs = data.networks.map(n => n.ssid);
                
                container.innerHTML = '';
                data.networks.forEach(network => {
                    const networkElement = createNetworkElement(network, true);
                    container.appendChild(networkElement);
                });
            } else {
                savedNetworkSSIDs = [];
                container.innerHTML = '<div class="loading">No saved networks</div>';
            }
        })
        .catch(error => {
            console.error('Error loading saved networks:', error);
            container.innerHTML = '<div class="loading">Error loading saved networks</div>';
        });
}

// Create network element
function createNetworkElement(network, isSaved) {
    const div = document.createElement('div');
    div.className = 'network-item';
    
    const infoDiv = document.createElement('div');
    infoDiv.className = 'network-info';
    
    const ssidSpan = document.createElement('div');
    ssidSpan.className = 'network-ssid';
    ssidSpan.textContent = network.ssid;
    
    const detailsDiv = document.createElement('div');
    detailsDiv.className = 'network-details';
    
    if (!isSaved && network.signal) {
        const signalSpan = document.createElement('span');
        signalSpan.className = 'network-signal';
        
        const signal = parseInt(network.signal);
        if (signal >= 70) {
            signalSpan.className += ' signal-strong';
        } else if (signal >= 40) {
            signalSpan.className += ' signal-medium';
        } else {
            signalSpan.className += ' signal-weak';
        }
        
        signalSpan.textContent = `📶 ${network.signal}%`;
        detailsDiv.appendChild(signalSpan);
        
        if (network.security) {
            const securitySpan = document.createElement('span');
            securitySpan.textContent = network.security;
            detailsDiv.appendChild(securitySpan);
        }
    }
    
    infoDiv.appendChild(ssidSpan);
    infoDiv.appendChild(detailsDiv);
    
    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'network-actions';
    
    // Connect button (hide for currently connected network in saved networks)
    if (!isSaved || network.ssid !== currentSSID) {
        const connectBtn = document.createElement('button');
        connectBtn.className = 'btn btn-secondary';
        connectBtn.textContent = 'Connect';
        
        // Different behavior for saved networks vs available networks
        if (isSaved) {
            // Saved networks: direct connect with confirmation (no password needed)
            connectBtn.addEventListener('click', () => connectToSavedNetwork(network.ssid));
        } else {
            // Available networks: show password modal
            connectBtn.addEventListener('click', () => showPasswordModal(network.ssid));
        }
        
        actionsDiv.appendChild(connectBtn);
    }
    
    // Forget button (only for saved networks, not current connection)
    if (isSaved && network.ssid !== currentSSID) {
        const forgetBtn = document.createElement('button');
        forgetBtn.className = 'btn btn-danger';
        forgetBtn.textContent = 'Forget';
        forgetBtn.addEventListener('click', () => forgetNetwork(network.ssid));
        actionsDiv.appendChild(forgetBtn);
    }
    
    div.appendChild(infoDiv);
    div.appendChild(actionsDiv);
    
    return div;
}

// Show password modal
function showPasswordModal(ssid) {
    document.getElementById('modal-ssid').textContent = `Network: ${ssid}`;
    document.getElementById('modal-password').value = '';
    document.getElementById('modal-message').classList.remove('show');
    
    const modal = document.getElementById('password-modal');
    modal.classList.add('show');
    
    // Store SSID in modal for later use
    modal.dataset.ssid = ssid;
    
    // Focus password field
    setTimeout(() => {
        document.getElementById('modal-password').focus();
    }, 100);
}

// Close modal
function closeModal() {
    const modal = document.getElementById('password-modal');
    modal.classList.remove('show');
}

// Connect to saved network (without password prompt)
function connectToSavedNetwork(ssid) {
    if (!confirm(`Connect to "${ssid}"?`)) {
        return;
    }
    
    showToast('Connecting...', 'info');
    
    fetch('/api/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssid: ssid, password: '' })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Connected successfully', 'success');
            setTimeout(() => {
                loadCurrentConnection();
                loadSavedNetworks();
            }, 1000);
        } else {
            showToast(data.message || 'Connection failed', 'error');
        }
    })
    .catch(error => {
        console.error('Error connecting:', error);
        showToast('Connection error', 'error');
    });
}

// Connect from modal
function connectFromModal() {
    const modal = document.getElementById('password-modal');
    const ssid = modal.dataset.ssid;
    const password = document.getElementById('modal-password').value;
    const messageDiv = document.getElementById('modal-message');
    const connectBtn = document.getElementById('modal-connect');
    
    connectBtn.disabled = true;
    connectBtn.textContent = 'Connecting...';
    
    fetch('/api/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssid: ssid, password: password })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            messageDiv.textContent = data.message;
            messageDiv.className = 'message success show';
            showToast('Connected successfully', 'success');
            
            setTimeout(() => {
                closeModal();
                loadCurrentConnection();
                loadSavedNetworks();
            }, 1500);
        } else {
            messageDiv.textContent = data.message;
            messageDiv.className = 'message error show';
            showToast('Connection failed', 'error');
        }
    })
    .catch(error => {
        console.error('Error connecting:', error);
        messageDiv.textContent = 'Connection error';
        messageDiv.className = 'message error show';
        showToast('Connection error', 'error');
    })
    .finally(() => {
        connectBtn.disabled = false;
        connectBtn.textContent = 'Connect';
    });
}

// Forget network
function forgetNetwork(ssid) {
    if (!confirm(`Forget network "${ssid}"?`)) {
        return;
    }
    
    fetch('/api/forget', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssid: ssid })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Network forgotten', 'success');
            loadSavedNetworks();
        } else {
            showToast(data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error forgetting network:', error);
        showToast('Error forgetting network', 'error');
    });
}

// Run ping test
function runPingTest() {
    const btn = document.getElementById('ping-btn');
    const output = document.getElementById('diagnostics-output');
    const hostInput = document.getElementById('ping-host');
    
    const host = hostInput.value.trim() || '8.8.8.8';
    
    btn.disabled = true;
    btn.textContent = 'Running...';
    output.textContent = 'Running ping test...';
    
    fetch('/api/ping', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ host: host, count: 4 })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            let result = `Ping test to ${data.host}:\n\n`;
            
            if (data.packet_loss) {
                result += `Packet Loss: ${data.packet_loss}\n`;
            }
            if (data.min_time) {
                result += `Min: ${data.min_time}\n`;
                result += `Avg: ${data.avg_time}\n`;
                result += `Max: ${data.max_time}\n`;
            }
            
            result += `\n${data.output}`;
            output.textContent = result;
            showToast('Ping test complete', 'success');
        } else {
            output.textContent = `Ping test failed:\n\n${data.output}`;
            showToast('Ping test failed', 'error');
        }
    })
    .catch(error => {
        console.error('Error running ping test:', error);
        output.textContent = 'Error running ping test';
        showToast('Ping test error', 'error');
    })
    .finally(() => {
        btn.disabled = false;
        btn.textContent = 'Run Ping Test';
    });
}

// Show toast notification
function showToast(message, type) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type} show`;
    
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// Cleanup on page unload
window.addEventListener('beforeunload', function() {
    if (updateInterval) {
        clearInterval(updateInterval);
    }
});
