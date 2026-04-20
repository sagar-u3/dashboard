// Dashboard JavaScript Application

// Global variables
let currentMode = 'single';
let websocket = null;
let currentCwd = '~';  // Start with home directory
let dockerComposeData = null;
let containerStatuses = {};

// Utility functions
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Navigation functions
function showSection(sectionId) {
    // Hide all sections
    const sections = document.querySelectorAll('.content-section');
    sections.forEach(section => section.classList.remove('active'));
    
    // Remove active class from all nav items
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => item.classList.remove('active'));
    
    // Show selected section
    const targetSection = document.getElementById(sectionId);
    if (targetSection) {
        targetSection.classList.add('active');
    }
    
    // Set active nav item
    const targetNav = document.querySelector(`[onclick="showSection('${sectionId}')"]`);
    if (targetNav) {
        targetNav.classList.add('active');
    }
}

// Terminal mode switching
function switchMode(mode) {
    currentMode = mode;
    
    // Update tab buttons
    const tabButtons = document.querySelectorAll('.tab-btn');
    tabButtons.forEach(btn => btn.classList.remove('active'));
    
    // Update tab content
    const tabContents = document.querySelectorAll('.tab-content');
    tabContents.forEach(content => content.classList.remove('active'));
    
    if (mode === 'single') {
        document.querySelector('[onclick="switchMode(\'single\')"]').classList.add('active');
        document.getElementById('single-mode').classList.add('active');
    } else if (mode === 'session') {
        document.querySelector('[onclick="switchMode(\'session\')"]').classList.add('active');
        document.getElementById('session-mode').classList.add('active');
    }
}

// Command execution
async function executeCommand() {
    const command = document.getElementById('command').value;
    const timeout = parseInt(document.getElementById('timeout').value) || 30;
    const output = document.getElementById('output');
    const executeBtn = document.getElementById('executeBtn');
    
    if (!command.trim()) {
        alert('Please enter a command');
        return;
    }
    
    executeBtn.disabled = true;
    executeBtn.textContent = 'Executing...';
    
    try {
        const response = await fetch('/execute', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                command: command,
                timeout: timeout
            })
        });
        
        const result = await response.json();
        
        let outputHtml = `<div class="command-info">$ ${result.command}</div>`;
        outputHtml += `<div class="command-info">Return code: ${result.return_code}</div>`;
        
        if (result.output) {
            outputHtml += `<div class="success">${escapeHtml(result.output)}</div>`;
        }
        
        if (result.error) {
            outputHtml += `<div class="error">${escapeHtml(result.error)}</div>`;
        }
        
        output.innerHTML = outputHtml;
        output.scrollTop = output.scrollHeight;
        
    } catch (error) {
        output.innerHTML = `<div class="error">Error: ${escapeHtml(error.message)}</div>`;
    } finally {
        executeBtn.disabled = false;
        executeBtn.textContent = 'Execute';
    }
}

function clearOutput() {
    document.getElementById('output').innerHTML = '';
}

// Terminal session functions
async function startTerminalSession() {
    const sessionId = 'session_' + Date.now();
    const wsUrl = `ws://localhost:8000/ws/terminal/${sessionId}`;
    
    websocket = new WebSocket(wsUrl);
    
    websocket.onopen = function() {
        document.getElementById('session-status').textContent = 'Connected';
        document.getElementById('session-status').style.color = '#3fb950';
        addTerminalLine('Terminal session started', 'system');
    };
    
    websocket.onmessage = function(event) {
        console.log('WebSocket received:', event.data);
        
        try {
            const data = JSON.parse(event.data);
            
            if (data.type === 'output') {
                // Only show result, command was already echoed when typed
                addTerminalLine(data.result, 'result');
                currentCwd = data.cwd;
                updatePrompt();
            } else if (data.type === 'error') {
                addTerminalLine(data.message, 'error');
            } else if (data.type === 'system') {
                addTerminalLine(data.message, 'system');
                if (data.message.includes('ended')) {
                    endTerminalSession();
                }
            }
        } catch (e) {
            console.error('Error parsing WebSocket message:', e);
            addTerminalLine('Error: Invalid message format', 'error');
        }
    };
    
    websocket.onclose = function() {
        document.getElementById('session-status').textContent = 'Disconnected';
        document.getElementById('session-status').style.color = '#f85149';
        addTerminalLine('Terminal session ended', 'system');
        websocket = null;
    };
    
    websocket.onerror = function(error) {
        console.error('WebSocket error:', error);
        addTerminalLine('WebSocket connection error', 'error');
    };
}

function endTerminalSession() {
    if (websocket) {
        websocket.close();
        websocket = null;
    }
    
    document.getElementById('session-status').textContent = 'Not connected';
    document.getElementById('session-status').style.color = '#8b949e';
}

function addTerminalLine(text, type = 'result') {
    const output = document.getElementById('terminal-output');
    const line = document.createElement('div');
    line.className = `terminal-output-line terminal-${type}`;
    line.textContent = text;
    output.appendChild(line);
    // Auto-scroll to bottom on new output
    setTimeout(() => {
        output.scrollTop = output.scrollHeight;
    }, 100);
}

function updatePrompt() {
    const prompt = document.querySelector('.prompt');
    if (prompt) {
        const path = currentCwd === os.path.expanduser("~") ? '~' : currentCwd.replace(os.path.expanduser("~"), '~');
        prompt.textContent = `user@host:${path}$ `;
    }
}

function handleTerminalInput(event) {
    if (event.key === 'Enter') {
        const input = event.target;
        const command = input.value.trim();
        
        if (command && websocket) {
            // Echo command with current prompt (like real terminal)
            const prompt = document.getElementById('current-prompt').textContent;
            addTerminalLine(prompt + command, 'command');
            
            // Debug: log what we're sending
            console.log('Sending command:', command);
            console.log('WebSocket ready state:', websocket.readyState);
            
            const message = JSON.stringify({ command: command });
            console.log('Message being sent:', message);
            
            websocket.send(message);
            input.value = '';
            
            // Auto-scroll to bottom after command execution
            setTimeout(() => {
                const output = document.getElementById('terminal-output');
                output.scrollTop = output.scrollHeight;
            }, 50);
        }
        
        event.preventDefault();
    }
}

// Docker Control Panel Functions
async function loadDockerCompose() {
    try {
        const response = await fetch('/api/docker/compose');
        const data = await response.json();
        
        if (data.error) {
            console.error('Error loading Docker Compose:', data.error);
            document.getElementById('compose-path').textContent = 'Error: ' + data.error;
            renderDockerTree();
            return;
        }
        
        // Update path display
        document.getElementById('compose-path').textContent = data.path;
        
        // Parse and render the compose file
        dockerComposeData = parseDockerCompose(data.content);
        renderDockerTree();
        await refreshDockerStatus();
        
    } catch (error) {
        console.error('Error loading Docker Compose:', error);
        document.getElementById('compose-path').textContent = 'Error: ' + error.message;
        renderDockerTree();
    }
}

function parseDockerCompose(yamlContent) {
    // Simple YAML parser for docker-compose
    const lines = yamlContent.split('\n');
    const services = {};
    let currentService = null;
    let inServices = false;
    
    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) continue;
        
        const indent = line.search(/\S/);
        
        if (trimmed === 'services:') {
            inServices = true;
            continue;
        }
        
        if (inServices && indent <= 0) {
            // We've moved out of services section
            inServices = false;
            continue;
        }
        
        if (inServices && indent === 2 && trimmed.endsWith(':')) {
            // Service level
            currentService = trimmed.replace(':', '');
            services[currentService] = {
                name: currentService,
                status: 'unknown',
                containers: []
            };
        } else if (currentService && inServices && indent >= 4) {
            // Service properties
            const [key, value] = trimmed.split(':').map(s => s.trim());
            if (key === 'image') {
                services[currentService].image = value;
            }
            if (key === 'build') {
                services[currentService].build = value;
            }
        }
    }
    
    return services;
}

function renderDockerTree() {
    const treeContainer = document.getElementById('docker-tree');
    
    if (!dockerComposeData) {
        treeContainer.innerHTML = `
            <div class="docker-services-empty">
                <div class="empty-icon">?</div>
                <div class="empty-text">No Docker Compose loaded</div>
            </div>
        `;
        return;
    }
    
    let html = '';
    for (const [serviceName, service] of Object.entries(dockerComposeData)) {
        html += `
            <div class="service-node" data-service="${serviceName}">
                <div class="service-header">
                    <span class="service-name">${serviceName}</span>
                    <span class="service-status status-unknown" id="status-${serviceName}">Unknown</span>
                </div>
                <div class="service-info">
                    <div><strong>Image:</strong> ${service.image || (service.build ? 'Build: ' + service.build : 'N/A')}</div>
                    <div><strong>Containers:</strong> <span id="container-count-${serviceName}">0</span></div>
                </div>
                <div class="service-controls">
                    <button onclick="editService('${serviceName}')" class="btn btn-primary btn-sm">Edit</button>
                    <button onclick="deleteService('${serviceName}')" class="btn btn-danger btn-sm">Delete</button>
                    <button onclick="startService('${serviceName}')" class="btn btn-success btn-sm">Start</button>
                    <button onclick="stopService('${serviceName}')" class="btn btn-danger btn-sm">Stop</button>
                    <button onclick="restartService('${serviceName}')" class="btn btn-warning btn-sm">Restart</button>
                    <button onclick="viewLogs('${serviceName}')" class="btn btn-info btn-sm">Logs</button>
                </div>
            </div>
        `;
    }
    
    treeContainer.innerHTML = html;
}

function toggleTreeNode(header) {
    const toggle = header.querySelector('.tree-toggle');
    const children = header.nextElementSibling;
    
    if (children.classList.contains('expended')) {
        children.classList.remove('expended');
        toggle.classList.remove('expended');
        toggle.textContent = '📁';
    } else {
        children.classList.add('expended');
        toggle.classList.add('expended');
        toggle.textContent = '📂';
    }
}

async function refreshDockerStatus() {
    try {
        const response = await fetch('/api/docker/status');
        const data = await response.json();
        
        if (data.containers) {
            for (const [serviceName, service] of Object.entries(dockerComposeData || {})) {
                const serviceContainers = data.containers.filter(c => 
                    c.service_name === serviceName
                );
                
                const statusElement = document.getElementById(`status-${serviceName}`);
                const countElement = document.getElementById(`container-count-${serviceName}`);
                
                if (statusElement) {
                    const runningCount = serviceContainers.filter(c => c.State === 'running').length;
                    
                    if (runningCount > 0) {
                        statusElement.textContent = `Running (${runningCount})`;
                        statusElement.className = 'service-status status-running';
                    } else if (serviceContainers.length > 0) {
                        statusElement.textContent = `Stopped`;
                        statusElement.className = 'service-status status-stopped';
                    } else {
                        statusElement.textContent = 'Not Created';
                        statusElement.className = 'service-status status-pending';
                    }
                }
                
                if (countElement) {
                    countElement.textContent = serviceContainers.length;
                }
            }
        }
    } catch (error) {
        console.error('Error refreshing Docker status:', error);
    }
}

async function startService(serviceName) {
    try {
        const response = await fetch(`/api/docker/start/${serviceName}`, { method: 'POST' });
        const result = await response.json();
        if (result.success) {
            await refreshDockerStatus();
        } else {
            alert('Error starting service: ' + result.error);
        }
    } catch (error) {
        console.error('Error starting service:', error);
        alert('Error starting service');
    }
}

async function stopService(serviceName) {
    try {
        const response = await fetch(`/api/docker/stop/${serviceName}`, { method: 'POST' });
        const result = await response.json();
        if (result.success) {
            await refreshDockerStatus();
        } else {
            alert('Error stopping service: ' + result.error);
        }
    } catch (error) {
        console.error('Error stopping service:', error);
        alert('Error stopping service');
    }
}

async function restartService(serviceName) {
    try {
        const response = await fetch(`/api/docker/restart/${serviceName}`, { method: 'POST' });
        const result = await response.json();
        if (result.success) {
            await refreshDockerStatus();
        } else {
            alert('Error restarting service: ' + result.error);
        }
    } catch (error) {
        console.error('Error restarting service:', error);
        alert('Error restarting service');
    }
}

async function viewLogs(serviceName) {
    try {
        const response = await fetch(`/api/docker/logs/${serviceName}`);
        const data = await response.json();
        
        if (data.logs) {
            const logWindow = window.open('', '_blank', 'width=800,height=600');
            logWindow.document.write(`
                <html>
                <head><title>Logs for ${serviceName}</title></head>
                <body style="font-family: monospace; background: #000; color: #fff; padding: 10px;">
                <pre>${data.logs}</pre>
                </body>
                </html>
            `);
        } else {
            alert('No logs available for this service');
        }
    } catch (error) {
        console.error('Error viewing logs:', error);
        alert('Error viewing logs');
    }
}

// Service Management Functions
let currentEditingService = null;

// Port and Environment Management Functions
function addPortEntry() {
    const container = document.getElementById('ports-container');
    const entry = document.createElement('div');
    entry.className = 'port-entry';
    entry.innerHTML = `
        <input type="number" class="port-published" placeholder="Host (e.g., 8080)" />
        <input type="number" class="port-target" placeholder="Container (e.g., 80)" />
        <select class="port-protocol">
            <option value="tcp">TCP</option>
            <option value="udp">UDP</option>
        </select>
        <button type="button" onclick="removePortEntry(this)" class="btn btn-danger btn-sm">×</button>
    `;
    container.appendChild(entry);
}

function removePortEntry(button) {
    const entry = button.parentElement;
    entry.remove();
}

function addEnvEntry() {
    const container = document.getElementById('env-container');
    const entry = document.createElement('div');
    entry.className = 'env-entry';
    entry.innerHTML = `
        <input type="text" class="env-key" placeholder="Key (e.g., NODE_ENV)" />
        <input type="text" class="env-value" placeholder="Value (e.g., production)" />
        <button type="button" onclick="removeEnvEntry(this)" class="btn btn-danger btn-sm">×</button>
    `;
    container.appendChild(entry);
}

function removeEnvEntry(button) {
    const entry = button.parentElement;
    entry.remove();
}

function getBuildFromForm() {
    const context = document.getElementById('build-context').value.trim();
    const dockerfile = document.getElementById('build-dockerfile').value.trim();
    const target = document.getElementById('build-target').value.trim();
    const argsValue = document.getElementById('build-args').value.trim();
    const build = {};

    if (context) {
        build.context = context;
    }
    if (dockerfile) {
        build.dockerfile = dockerfile;
    }
    if (target) {
        build.target = target;
    }
    if (argsValue) {
        try {
            const args = JSON.parse(argsValue);
            if (typeof args === 'object' && args !== null) {
                build.args = args;
            }
        } catch (err) {
            throw new Error('Build args must be valid JSON');
        }
    }

    return Object.keys(build).length > 0 ? build : null;
}

function getPortsFromForm() {
    const portEntries = document.querySelectorAll('.port-entry');
    const ports = [];
    
    portEntries.forEach(entry => {
        const published = entry.querySelector('.port-published').value;
        const target = entry.querySelector('.port-target').value;
        const protocol = entry.querySelector('.port-protocol').value;
        
        if (published && target) {
            ports.push({
                published: parseInt(published),
                target: parseInt(target),
                protocol: protocol
            });
        }
    });
    
    return ports;
}

function getEnvFromForm() {
    const envEntries = document.querySelectorAll('.env-entry');
    const env = {};
    
    envEntries.forEach(entry => {
        const key = entry.querySelector('.env-key').value.trim();
        const value = entry.querySelector('.env-value').value.trim();
        
        if (key) {
            env[key] = value;
        }
    });
    
    return env;
}

function setPortsInForm(ports) {
    const container = document.getElementById('ports-container');
    container.innerHTML = '';
    
    if (ports && ports.length > 0) {
        ports.forEach(port => {
            const entry = document.createElement('div');
            entry.className = 'port-entry';
            entry.innerHTML = `
                <input type="number" class="port-published" placeholder="Host (e.g., 8080)" value="${port.published || ''}" />
                <input type="number" class="port-target" placeholder="Container (e.g., 80)" value="${port.target || ''}" />
                <select class="port-protocol">
                    <option value="tcp" ${port.protocol === 'tcp' ? 'selected' : ''}>TCP</option>
                    <option value="udp" ${port.protocol === 'udp' ? 'selected' : ''}>UDP</option>
                </select>
                <button type="button" onclick="removePortEntry(this)" class="btn btn-danger btn-sm">×</button>
            `;
            container.appendChild(entry);
        });
    } else {
        // Add one empty entry
        addPortEntry();
    }
}

function setBuildInForm(build) {
    document.getElementById('build-context').value = '';
    document.getElementById('build-dockerfile').value = '';
    document.getElementById('build-target').value = '';
    document.getElementById('build-args').value = '';

    if (!build) {
        return;
    }

    if (typeof build === 'string') {
        document.getElementById('build-context').value = build;
        return;
    }

    document.getElementById('build-context').value = build.context || '';
    document.getElementById('build-dockerfile').value = build.dockerfile || '';
    document.getElementById('build-target').value = build.target || '';
    if (build.args && typeof build.args === 'object') {
        document.getElementById('build-args').value = JSON.stringify(build.args);
    }
}

function setEnvInForm(env) {
    const container = document.getElementById('env-container');
    container.innerHTML = '';
    
    if (env && Object.keys(env).length > 0) {
        Object.entries(env).forEach(([key, value]) => {
            const entry = document.createElement('div');
            entry.className = 'env-entry';
            entry.innerHTML = `
                <input type="text" class="env-key" placeholder="Key (e.g., NODE_ENV)" value="${key || ''}" />
                <input type="text" class="env-value" placeholder="Value (e.g., production)" value="${value || ''}" />
                <button type="button" onclick="removeEnvEntry(this)" class="btn btn-danger btn-sm">×</button>
            `;
            container.appendChild(entry);
        });
    } else {
        // Add one empty entry
        addEnvEntry();
    }
}

function toggleAddServiceForm() {
    const form = document.getElementById('add-service-form');
    if (form.style.display === 'none') {
        form.style.display = 'block';
        currentEditingService = null;
        resetFormToAddMode();
    } else {
        form.style.display = 'none';
        clearServiceForm();
    }
}

function resetFormToAddMode() {
    document.getElementById('form-title').textContent = 'Add New Service';
    document.getElementById('save-button').textContent = 'Add Service';
    document.getElementById('service-name').disabled = false;
    currentEditingService = null;
    // Initialize with empty entries
    setPortsInForm([]);
    setEnvInForm({});
    setBuildInForm(null);
}

function clearServiceForm() {
    document.getElementById('service-name').value = '';
    document.getElementById('service-image').value = '';
    setPortsInForm([]);
    setEnvInForm({});
    setBuildInForm(null);
}

async function editService(serviceName) {
    try {
        const response = await fetch('/api/docker/get-service/' + serviceName);
        const data = await response.json();
        
        if (data.error) {
            alert('Error getting service details: ' + data.error);
            return;
        }
        
        // Populate form with existing service data
        document.getElementById('form-title').textContent = 'Edit Service';
        document.getElementById('save-button').textContent = 'Update Service';
        document.getElementById('service-name').value = serviceName;
        document.getElementById('service-name').disabled = true;
        document.getElementById('service-image').value = data.image || '';
        setBuildInForm(data.build || null);
        
        // Set ports and environment using the new helper functions
        setPortsInForm(data.ports || []);
        setEnvInForm(data.environment || {});
        
        currentEditingService = serviceName;
        
        // Show the form
        document.getElementById('add-service-form').style.display = 'block';
        
    } catch (error) {
        console.error('Error editing service:', error);
        alert('Error editing service');
    }
}

async function deleteService(serviceName) {
    if (!confirm(`Are you sure you want to delete the service "${serviceName}"? This will remove it from the Docker Compose file.`)) {
        return;
    }
    
    try {
        const response = await fetch('/api/docker/delete-service/' + serviceName, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (result.success) {
            alert('Service deleted successfully!');
            await loadDockerCompose();
        } else {
            alert('Error deleting service: ' + result.error);
        }
    } catch (error) {
        console.error('Error deleting service:', error);
        alert('Error deleting service');
    }
}

async function saveService() {
    const serviceName = document.getElementById('service-name').value.trim();
    const serviceImage = document.getElementById('service-image').value.trim();
    const serviceBuild = getBuildFromForm();
    const servicePorts = getPortsFromForm();
    const serviceEnv = getEnvFromForm();
    
    if (!serviceName || (!serviceImage && !serviceBuild)) {
        alert('Service name and either image or build context are required');
        return;
    }
    
    try {
        let url, method;
        
        if (currentEditingService) {
            // Update existing service
            url = '/api/docker/update-service/' + currentEditingService;
            method = 'PUT';
        } else {
            // Add new service
            url = '/api/docker/add-service';
            method = 'POST';
        }
        
        const payload = {
            name: serviceName,
            ports: servicePorts,
            environment: serviceEnv
        };
        if (serviceImage) {
            payload.image = serviceImage;
        }
        if (serviceBuild) {
            payload.build = serviceBuild;
        }

        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload)
        });
        
        const result = await response.json();
        
        if (result.success) {
            const action = currentEditingService ? 'updated' : 'added';
            alert(`Service ${action} successfully!`);
            toggleAddServiceForm();
            await loadDockerCompose();
        } else {
            alert('Error saving service: ' + result.error);
        }
    } catch (error) {
        console.error('Error saving service:', error);
        alert('Error saving service');
    }
}

// Initialize application
document.addEventListener('DOMContentLoaded', function() {
    // Auto-focus on terminal input
    const terminalInput = document.getElementById('terminal-input');
    if (terminalInput) {
        terminalInput.focus();
    }
    
    // Show default section
    showSection('command-section');
    
    // Set default terminal mode
    switchMode('single');
    
    // Auto-load Docker Compose from environment
    loadDockerCompose();
});
