// AIS Configuration JavaScript
let statusUpdateInterval = null;
let currentEditingEndpoint = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    initializeAISConfig();
});

function initializeAISConfig() {
    // Load initial data
    loadAISStatus();
    loadEndpoints();
    
    // Start auto-update polling (every 3 seconds)
    statusUpdateInterval = setInterval(() => {
        loadAISStatus();
        loadEndpoints();
    }, 3000);
    
    // Setup event listeners
    document.getElementById('start-btn').addEventListener('click', startAISService);
    document.getElementById('stop-btn').addEventListener('click', stopAISService);
    document.getElementById('restart-btn').addEventListener('click', restartAISService);
    document.getElementById('add-endpoint-btn').addEventListener('click', showAddEndpointModal);
    document.getElementById('endpoint-form').addEventListener('submit', handleEndpointFormSubmit);
    document.getElementById('modal-cancel').addEventListener('click', closeEndpointModal);
    document.getElementById('cancel-delete').addEventListener('click', closeDeleteModal);
    document.getElementById('confirm-delete').addEventListener('click', confirmDeleteEndpoint);
    
    // Close modals when clicking outside
    document.getElementById('endpoint-modal').addEventListener('click', function(e) {
        if (e.target === this) {
            closeEndpointModal();
        }
    });
    
    document.getElementById('delete-modal').addEventListener('click', function(e) {
        if (e.target === this) {
            closeDeleteModal();
        }
    });
}

// Load AIS service status
function loadAISStatus() {
    fetch('/api/ais/status')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.status) {
                displayAISStatus(data.status);
            }
        })
        .catch(error => {
            console.error('Error loading AIS status:', error);
        });
}

// Display AIS status
function displayAISStatus(status) {
    const statusBadge = document.getElementById('service-status');
    const serialPort = document.getElementById('serial-port');
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    const restartBtn = document.getElementById('restart-btn');
    
    // Update status badge
    if (status.running) {
        statusBadge.textContent = 'Running';
        statusBadge.className = 'status-badge running';
        startBtn.disabled = true;
        stopBtn.disabled = false;
        restartBtn.disabled = false;
    } else {
        statusBadge.textContent = 'Stopped';
        statusBadge.className = 'status-badge stopped';
        startBtn.disabled = false;
        stopBtn.disabled = true;
        restartBtn.disabled = true;
    }
    
    // Update serial port
    serialPort.textContent = status.serial_port;
}

// Start AIS service
function startAISService() {
    const btn = document.getElementById('start-btn');
    btn.disabled = true;
    btn.textContent = 'Starting...';
    
    fetch('/api/ais/start', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('AIS service started', 'success');
                loadAISStatus();
            } else {
                showToast(data.message || 'Failed to start service', 'error');
                btn.disabled = false;
                btn.textContent = 'Start';
            }
        })
        .catch(error => {
            console.error('Error starting service:', error);
            showToast('Error starting service', 'error');
            btn.disabled = false;
            btn.textContent = 'Start';
        });
}

// Stop AIS service
function stopAISService() {
    if (!confirm('Stop AIS forwarding service?')) {
        return;
    }
    
    const btn = document.getElementById('stop-btn');
    btn.disabled = true;
    btn.textContent = 'Stopping...';
    
    fetch('/api/ais/stop', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('AIS service stopped', 'success');
                loadAISStatus();
            } else {
                showToast(data.message || 'Failed to stop service', 'error');
                btn.disabled = false;
                btn.textContent = 'Stop';
            }
        })
        .catch(error => {
            console.error('Error stopping service:', error);
            showToast('Error stopping service', 'error');
            btn.disabled = false;
            btn.textContent = 'Stop';
        });
}

// Restart AIS service
function restartAISService() {
    const btn = document.getElementById('restart-btn');
    btn.disabled = true;
    btn.textContent = 'Restarting...';
    
    fetch('/api/ais/restart', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('AIS service restarted', 'success');
                setTimeout(() => {
                    loadAISStatus();
                    loadEndpoints();
                }, 1500);
            } else {
                showToast(data.message || 'Failed to restart service', 'error');
                btn.disabled = false;
                btn.textContent = 'Restart';
            }
        })
        .catch(error => {
            console.error('Error restarting service:', error);
            showToast('Error restarting service', 'error');
            btn.disabled = false;
            btn.textContent = 'Restart';
        });
}

// Load endpoints
function loadEndpoints() {
    const container = document.getElementById('endpoints-list');
    
    fetch('/api/ais/endpoints')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (data.endpoints && data.endpoints.length > 0) {
                    container.innerHTML = '';
                    data.endpoints.forEach(endpoint => {
                        const endpointElement = createEndpointElement(endpoint);
                        container.appendChild(endpointElement);
                    });
                } else {
                    container.innerHTML = '<div class="no-data">No endpoints configured. Click "Add Endpoint" to create one.</div>';
                }
            }
        })
        .catch(error => {
            console.error('Error loading endpoints:', error);
            container.innerHTML = '<div class="loading">Error loading endpoints</div>';
        });
}

// Create endpoint element
function createEndpointElement(endpoint) {
    const div = document.createElement('div');
    div.className = 'endpoint-item';
    div.dataset.endpointId = endpoint.id;
    
    const infoDiv = document.createElement('div');
    infoDiv.className = 'endpoint-info';
    
    const nameSpan = document.createElement('span');
    nameSpan.className = 'endpoint-name';
    nameSpan.textContent = endpoint.name;
    
    const addressSpan = document.createElement('span');
    addressSpan.className = 'endpoint-address';
    addressSpan.textContent = `${endpoint.ip}:${endpoint.port}`;
    
    const statusIndicator = document.createElement('div');
    statusIndicator.className = 'endpoint-status-indicator';
    
    const statusDot = document.createElement('span');
    statusDot.className = 'status-dot';
    
    const statusText = document.createElement('span');
    statusText.className = 'endpoint-status-text';
    
    const enabled = endpoint.enabled === 'true' || endpoint.enabled === true;
    
    if (!enabled) {
        statusDot.className += ' disabled';
        statusText.textContent = 'Disabled';
    } else if (endpoint.status && endpoint.status.connected) {
        statusDot.className += ' connected';
        statusText.textContent = 'Connected';
    } else {
        statusDot.className += ' disconnected';
        const errorMsg = endpoint.status && endpoint.status.error ? ` (${endpoint.status.error})` : '';
        statusText.textContent = 'Disconnected' + errorMsg;
    }
    
    statusIndicator.appendChild(statusDot);
    statusIndicator.appendChild(statusText);
    
    infoDiv.appendChild(nameSpan);
    infoDiv.appendChild(addressSpan);
    infoDiv.appendChild(statusIndicator);
    
    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'endpoint-actions';
    
    // Toggle button
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'btn btn-icon btn-secondary';
    toggleBtn.textContent = enabled ? '⏸' : '▶';
    toggleBtn.title = enabled ? 'Disable' : 'Enable';
    toggleBtn.addEventListener('click', () => toggleEndpoint(endpoint.id));
    actionsDiv.appendChild(toggleBtn);
    
    // Edit button
    const editBtn = document.createElement('button');
    editBtn.className = 'btn btn-icon btn-secondary';
    editBtn.textContent = '✏';
    editBtn.title = 'Edit';
    editBtn.addEventListener('click', () => showEditEndpointModal(endpoint));
    actionsDiv.appendChild(editBtn);
    
    // Delete button
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'btn btn-icon btn-danger';
    deleteBtn.textContent = '🗑';
    deleteBtn.title = 'Delete';
    deleteBtn.addEventListener('click', () => showDeleteModal(endpoint));
    actionsDiv.appendChild(deleteBtn);
    
    div.appendChild(infoDiv);
    div.appendChild(actionsDiv);
    
    return div;
}

// Show add endpoint modal
function showAddEndpointModal() {
    currentEditingEndpoint = null;
    document.getElementById('modal-title').textContent = 'Add Endpoint';
    document.getElementById('endpoint-name').value = '';
    document.getElementById('endpoint-ip').value = '';
    document.getElementById('endpoint-port').value = '';
    document.getElementById('endpoint-enabled').checked = true;
    document.getElementById('modal-message').classList.remove('show');
    document.getElementById('endpoint-modal').classList.add('show');
    
    setTimeout(() => {
        document.getElementById('endpoint-name').focus();
    }, 100);
}

// Show edit endpoint modal
function showEditEndpointModal(endpoint) {
    currentEditingEndpoint = endpoint;
    document.getElementById('modal-title').textContent = 'Edit Endpoint';
    document.getElementById('endpoint-name').value = endpoint.name;
    document.getElementById('endpoint-ip').value = endpoint.ip;
    document.getElementById('endpoint-port').value = endpoint.port;
    document.getElementById('endpoint-enabled').checked = endpoint.enabled === 'true' || endpoint.enabled === true;
    document.getElementById('modal-message').classList.remove('show');
    document.getElementById('endpoint-modal').classList.add('show');
    
    setTimeout(() => {
        document.getElementById('endpoint-name').focus();
    }, 100);
}

// Close endpoint modal
function closeEndpointModal() {
    document.getElementById('endpoint-modal').classList.remove('show');
}

// Handle endpoint form submit
function handleEndpointFormSubmit(e) {
    e.preventDefault();
    
    const name = document.getElementById('endpoint-name').value.trim();
    const ip = document.getElementById('endpoint-ip').value.trim();
    const port = document.getElementById('endpoint-port').value.trim();
    const enabled = document.getElementById('endpoint-enabled').checked;
    
    if (!name || !ip || !port) {
        showModalMessage('All fields are required', 'error');
        return;
    }
    
    const submitBtn = document.querySelector('#endpoint-form button[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Saving...';
    
    if (currentEditingEndpoint) {
        // Update existing endpoint
        updateEndpoint(currentEditingEndpoint.id, name, ip, port, enabled, submitBtn);
    } else {
        // Add new endpoint
        addEndpoint(name, ip, port, enabled, submitBtn);
    }
}

// Add endpoint
function addEndpoint(name, ip, port, enabled, submitBtn) {
    fetch('/api/ais/endpoints', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, ip, port, enabled })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Endpoint added successfully', 'success');
            closeEndpointModal();
            loadEndpoints();
        } else {
            showModalMessage(data.message || 'Failed to add endpoint', 'error');
        }
    })
    .catch(error => {
        console.error('Error adding endpoint:', error);
        showModalMessage('Error adding endpoint', 'error');
    })
    .finally(() => {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Save';
    });
}

// Update endpoint
function updateEndpoint(endpointId, name, ip, port, enabled, submitBtn) {
    fetch(`/api/ais/endpoints/${endpointId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, ip, port, enabled })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Endpoint updated successfully', 'success');
            closeEndpointModal();
            loadEndpoints();
        } else {
            showModalMessage(data.message || 'Failed to update endpoint', 'error');
        }
    })
    .catch(error => {
        console.error('Error updating endpoint:', error);
        showModalMessage('Error updating endpoint', 'error');
    })
    .finally(() => {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Save';
    });
}

// Toggle endpoint
function toggleEndpoint(endpointId) {
    fetch(`/api/ais/endpoints/${endpointId}/toggle`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('Endpoint toggled', 'success');
                loadEndpoints();
            } else {
                showToast(data.message || 'Failed to toggle endpoint', 'error');
            }
        })
        .catch(error => {
            console.error('Error toggling endpoint:', error);
            showToast('Error toggling endpoint', 'error');
        });
}

// Show delete modal
function showDeleteModal(endpoint) {
    currentEditingEndpoint = endpoint;
    document.getElementById('delete-endpoint-name').textContent = endpoint.name;
    document.getElementById('delete-modal').classList.add('show');
}

// Close delete modal
function closeDeleteModal() {
    document.getElementById('delete-modal').classList.remove('show');
    currentEditingEndpoint = null;
}

// Confirm delete endpoint
function confirmDeleteEndpoint() {
    if (!currentEditingEndpoint) return;
    
    const endpointId = currentEditingEndpoint.id;
    const btn = document.getElementById('confirm-delete');
    
    btn.disabled = true;
    btn.textContent = 'Deleting...';
    
    fetch(`/api/ais/endpoints/${endpointId}`, { method: 'DELETE' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('Endpoint deleted', 'success');
                closeDeleteModal();
                loadEndpoints();
            } else {
                showToast(data.message || 'Failed to delete endpoint', 'error');
            }
        })
        .catch(error => {
            console.error('Error deleting endpoint:', error);
            showToast('Error deleting endpoint', 'error');
        })
        .finally(() => {
            btn.disabled = false;
            btn.textContent = 'Delete';
        });
}

// Show modal message
function showModalMessage(message, type) {
    const messageDiv = document.getElementById('modal-message');
    messageDiv.textContent = message;
    messageDiv.className = `message ${type} show`;
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
    if (statusUpdateInterval) {
        clearInterval(statusUpdateInterval);
    }
});
