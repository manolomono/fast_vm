const API_BASE = '/api';

// DOM Elements
const vmsList = document.getElementById('vmsList');
const createVmBtn = document.getElementById('createVmBtn');
const refreshBtn = document.getElementById('refreshBtn');
const volumesBtn = document.getElementById('volumesBtn');
const createVmModal = document.getElementById('createVmModal');
const createVmForm = document.getElementById('createVmForm');
const closeModal = document.querySelector('.close');
const cancelCreateBtn = document.getElementById('cancelCreateBtn');
const toast = document.getElementById('toast');

// VNC Panel Elements
const rightPanel = document.getElementById('rightPanel');
const leftPanel = document.getElementById('leftPanel');
const vncFramePanel = document.getElementById('vncFramePanel');
const closePanelBtn = document.getElementById('closePanelBtn');
const vncVmNamePanel = document.getElementById('vncVmNamePanel');

// Logs Modal Elements
const logsModal = document.getElementById('logsModal');
const logsClose = document.getElementById('logsClose');
const closeLogsBtn = document.getElementById('closeLogsBtn');
const refreshLogsBtn = document.getElementById('refreshLogsBtn');
const logsVmName = document.getElementById('logsVmName');
const qemuLog = document.getElementById('qemuLog');
const serialLog = document.getElementById('serialLog');
let currentLogsVmId = null;

// Edit VM Modal Elements
const editVmModal = document.getElementById('editVmModal');
const editVmClose = document.getElementById('editVmClose');
const cancelEditBtn = document.getElementById('cancelEditBtn');
const editVmForm = document.getElementById('editVmForm');
const editVmNameDisplay = document.getElementById('editVmNameDisplay');
const editVmMemory = document.getElementById('editVmMemory');
const editVmCpus = document.getElementById('editVmCpus');
const editVmIso = document.getElementById('editVmIso');
let currentEditVmId = null;

// Volumes Modal Elements
const volumesModal = document.getElementById('volumesModal');
const volumesClose = document.getElementById('volumesClose');
const volumesList = document.getElementById('volumesList');

// Snapshots Modal Elements
const snapshotsModal = document.getElementById('snapshotsModal');
const snapshotsClose = document.getElementById('snapshotsClose');
const snapshotsVmName = document.getElementById('snapshotsVmName');
const snapshotsList = document.getElementById('snapshotsList');
const closeSnapshotsBtn = document.getElementById('closeSnapshotsBtn');
let currentSnapshotsVmId = null;

// Network interface counter
let networkInterfaceCounter = 0;
let editNetworkInterfaceCounter = 0;

// Available bridges cache
let availableBridges = [];

// Event Listeners
createVmBtn.addEventListener('click', () => openModal());
refreshBtn.addEventListener('click', () => loadVMs());
volumesBtn.addEventListener('click', () => openVolumesModal());
closeModal.addEventListener('click', () => closeCreateModal());
cancelCreateBtn.addEventListener('click', () => closeCreateModal());
createVmForm.addEventListener('submit', handleCreateVM);

window.addEventListener('click', (e) => {
    if (e.target === createVmModal) closeCreateModal();
    if (e.target === logsModal) closeLogsModal();
    if (e.target === editVmModal) closeEditVmModal();
    if (e.target === volumesModal) closeVolumesModal();
    if (e.target === snapshotsModal) closeSnapshotsModal();
});

// VNC Panel Event Listeners
closePanelBtn.addEventListener('click', () => closeVNCPanel());

// Logs Modal Event Listeners
logsClose.addEventListener('click', () => closeLogsModal());
closeLogsBtn.addEventListener('click', () => closeLogsModal());
refreshLogsBtn.addEventListener('click', () => {
    if (currentLogsVmId) loadVMLogs(currentLogsVmId);
});

// Edit VM Modal Event Listeners
editVmClose.addEventListener('click', () => closeEditVmModal());
cancelEditBtn.addEventListener('click', () => closeEditVmModal());
editVmForm.addEventListener('submit', handleEditVM);

// Volumes Modal Event Listeners
volumesClose.addEventListener('click', () => closeVolumesModal());

// Snapshots Modal Event Listeners
snapshotsClose.addEventListener('click', () => closeSnapshotsModal());
closeSnapshotsBtn.addEventListener('click', () => closeSnapshotsModal());

// Listen for messages from VNC iframe
window.addEventListener('message', (event) => {
    if (event.data && event.data.action === 'close') closeVNCPanel();
});

// Initialize
loadVMs();
loadIsos();
loadBridges();

// API Functions
async function apiRequest(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Request failed');
        }

        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

async function loadIsos() {
    try {
        const isos = await apiRequest('/isos');
        const vmIsoPath = document.getElementById('vmIsoPath');
        vmIsoPath.innerHTML = '<option value="">Sin ISO</option>';
        isos.forEach(iso => {
            const option = document.createElement('option');
            option.value = iso.path;
            option.textContent = `${iso.name} (${iso.size_mb} MB)`;
            vmIsoPath.appendChild(option);
        });
    } catch (error) {
        console.error('Error loading ISOs:', error);
    }
}

async function loadBridges() {
    try {
        availableBridges = await apiRequest('/bridges');
    } catch (error) {
        console.error('Error loading bridges:', error);
        availableBridges = [];
    }
}

function getBridgeOptionsHTML(selectedBridge = '') {
    if (availableBridges.length === 0) {
        return '<option value="">No hay bridges disponibles</option>';
    }
    let html = '<option value="">Seleccionar bridge...</option>';
    availableBridges.forEach(br => {
        const selected = br.name === selectedBridge ? 'selected' : '';
        const status = br.active ? '(activo)' : '(inactivo)';
        html += `<option value="${br.name}" ${selected}>${br.name} ${status}</option>`;
    });
    return html;
}

async function loadVMs() {
    try {
        refreshBtn.disabled = true;
        vmsList.innerHTML = '<div class="loading">Cargando máquinas virtuales...</div>';

        const vms = await apiRequest('/vms');

        if (vms.length === 0) {
            vmsList.innerHTML = `
                <div class="empty-state">
                    <h2>No hay máquinas virtuales</h2>
                    <p>Crea tu primera VM para comenzar</p>
                </div>
            `;
            return;
        }

        vmsList.innerHTML = '';
        vms.forEach(vm => {
            vmsList.appendChild(createVMCard(vm));
        });
    } catch (error) {
        showToast('Error al cargar las VMs: ' + error.message, 'error');
        vmsList.innerHTML = '<div class="loading">Error al cargar las máquinas virtuales</div>';
    } finally {
        refreshBtn.disabled = false;
    }
}

function createVMCard(vm) {
    const card = document.createElement('div');
    card.className = 'vm-card';

    const networkInfo = vm.networks && vm.networks.length > 0
        ? vm.networks.map(n => n.type).join(', ')
        : 'NAT';

    card.innerHTML = `
        <div class="vm-card-header">
            <div class="vm-name">${escapeHtml(vm.name)}</div>
            <span class="vm-status ${vm.status}">${vm.status}</span>
        </div>
        <div class="vm-details">
            <div class="vm-detail-item">
                <span class="vm-detail-label">Memoria:</span>
                <span class="vm-detail-value">${vm.memory} MB</span>
            </div>
            <div class="vm-detail-item">
                <span class="vm-detail-label">CPUs:</span>
                <span class="vm-detail-value">${vm.cpus}</span>
            </div>
            <div class="vm-detail-item">
                <span class="vm-detail-label">Disco:</span>
                <span class="vm-detail-value">${vm.disk_size} GB</span>
            </div>
            <div class="vm-detail-item">
                <span class="vm-detail-label">Red:</span>
                <span class="vm-detail-value">${networkInfo}</span>
            </div>
            <div class="vm-detail-item">
                <span class="vm-detail-label">CPU Model:</span>
                <span class="vm-detail-value">${vm.cpu_model || 'host'}</span>
            </div>
            ${vm.volumes && vm.volumes.length > 0 ? `
            <div class="vm-detail-item">
                <span class="vm-detail-label">Volúmenes:</span>
                <span class="vm-detail-value">${vm.volumes.length}</span>
            </div>
            ` : ''}
            ${vm.vnc_port ? `
            <div class="vm-detail-item">
                <span class="vm-detail-label">VNC Port:</span>
                <span class="vm-detail-value">${vm.vnc_port}</span>
            </div>
            ` : ''}
        </div>
        <div class="vm-actions">
            ${vm.status === 'stopped' ?
                `<button class="btn btn-success" onclick="startVM('${vm.id}')">▶ Iniciar</button>
                <button class="btn btn-secondary" onclick="openEditVMModal('${vm.id}')">✏️ Editar</button>` :
                `<button class="btn btn-warning" onclick="stopVM('${vm.id}')">⏸ Detener</button>`
            }
            ${vm.status === 'running' ?
                `<button class="btn btn-info" onclick="openVNCConsole('${vm.id}', '${escapeHtml(vm.name)}')">🖥 Consola</button>
                <button class="btn btn-secondary" onclick="restartVM('${vm.id}')">🔄 Reiniciar</button>` :
                ''
            }
            <button class="btn btn-secondary" onclick="openSnapshotsModal('${vm.id}', '${escapeHtml(vm.name)}')">📸 Snapshots</button>
            <button class="btn btn-secondary" onclick="showVMLogs('${vm.id}', '${escapeHtml(vm.name)}')">📋 Logs</button>
            <button class="btn btn-danger" onclick="deleteVM('${vm.id}', '${escapeHtml(vm.name)}')">🗑 Eliminar</button>
        </div>
    `;
    return card;
}

// ==================== Network Interface Functions ====================

function createNetworkInterfaceHTML(prefix, index, config = null) {
    const id = `${prefix}Net${index}`;
    const netType = config?.type || 'nat';
    const bridgeName = config?.bridge_name || '';
    const portForwards = config?.port_forwards || [];

    let portForwardsHTML = '';
    if (portForwards.length > 0) {
        portForwardsHTML = portForwards.map((pf, pfIdx) => `
            <div class="port-forward-item" data-pf-index="${pfIdx}">
                <input type="number" placeholder="Host" value="${pf.host_port}" class="pf-host" min="1" max="65535">
                <span>→</span>
                <input type="number" placeholder="Guest" value="${pf.guest_port}" class="pf-guest" min="1" max="65535">
                <select class="pf-protocol">
                    <option value="tcp" ${pf.protocol === 'tcp' ? 'selected' : ''}>TCP</option>
                    <option value="udp" ${pf.protocol === 'udp' ? 'selected' : ''}>UDP</option>
                </select>
                <button type="button" class="btn btn-danger btn-small" onclick="removePortForward(this)">✕</button>
            </div>
        `).join('');
    }

    const noBridgesWarning = availableBridges.length === 0
        ? '<small class="help-text warning">No hay bridges en el sistema. Usa NAT o crea un bridge primero.</small>'
        : '';

    return `
        <div class="network-interface" data-net-index="${index}">
            <div class="network-interface-header">
                <span>Interface ${index + 1}</span>
                <button type="button" class="btn btn-danger btn-small" onclick="removeNetworkInterface(this)">✕</button>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Tipo de Red:</label>
                    <select id="${id}Type" onchange="onNetworkTypeChange(this, '${id}')">
                        <option value="nat" ${netType === 'nat' ? 'selected' : ''}>NAT (User networking)</option>
                        <option value="bridge" ${netType === 'bridge' ? 'selected' : ''} ${availableBridges.length === 0 ? 'disabled' : ''}>Bridge ${availableBridges.length === 0 ? '(no disponible)' : ''}</option>
                        <option value="isolated" ${netType === 'isolated' ? 'selected' : ''}>Isolated</option>
                    </select>
                </div>
                <div class="form-group bridge-config" id="${id}BridgeConfig" style="display: ${netType === 'bridge' ? 'block' : 'none'};">
                    <label>Bridge:</label>
                    <select id="${id}Bridge">
                        ${getBridgeOptionsHTML(bridgeName)}
                    </select>
                    ${noBridgesWarning}
                </div>
            </div>
            <div class="port-forwards-section" id="${id}PortForwards" style="display: ${netType === 'nat' ? 'block' : 'none'};">
                <label>Port Forwards:</label>
                <div class="port-forwards-list" id="${id}PortForwardsList">
                    ${portForwardsHTML}
                </div>
                <button type="button" class="btn btn-secondary btn-small" onclick="addPortForward('${id}')">+ Añadir Port Forward</button>
            </div>
        </div>
    `;
}

function addNetworkInterface(mode = 'create') {
    const container = mode === 'edit'
        ? document.getElementById('editNetworkInterfaces')
        : document.getElementById('networkInterfaces');
    const prefix = mode === 'edit' ? 'edit' : 'create';
    const counter = mode === 'edit' ? editNetworkInterfaceCounter++ : networkInterfaceCounter++;

    container.insertAdjacentHTML('beforeend', createNetworkInterfaceHTML(prefix, counter));
}

function removeNetworkInterface(btn) {
    const netInterface = btn.closest('.network-interface');
    netInterface.remove();
}

function onNetworkTypeChange(select, id) {
    const bridgeConfig = document.getElementById(`${id}BridgeConfig`);
    const portForwards = document.getElementById(`${id}PortForwards`);

    if (select.value === 'bridge') {
        bridgeConfig.style.display = 'block';
        portForwards.style.display = 'none';
    } else if (select.value === 'nat') {
        bridgeConfig.style.display = 'none';
        portForwards.style.display = 'block';
    } else {
        bridgeConfig.style.display = 'none';
        portForwards.style.display = 'none';
    }
}

function addPortForward(netId) {
    const list = document.getElementById(`${netId}PortForwardsList`);
    const html = `
        <div class="port-forward-item">
            <input type="number" placeholder="Host" class="pf-host" min="1" max="65535">
            <span>→</span>
            <input type="number" placeholder="Guest" class="pf-guest" min="1" max="65535">
            <select class="pf-protocol">
                <option value="tcp">TCP</option>
                <option value="udp">UDP</option>
            </select>
            <button type="button" class="btn btn-danger btn-small" onclick="removePortForward(this)">✕</button>
        </div>
    `;
    list.insertAdjacentHTML('beforeend', html);
}

function removePortForward(btn) {
    btn.closest('.port-forward-item').remove();
}

function getNetworkConfigs(containerId) {
    const container = document.getElementById(containerId);
    const interfaces = container.querySelectorAll('.network-interface');
    const networks = [];

    interfaces.forEach((iface, idx) => {
        const typeSelect = iface.querySelector('select[id$="Type"]');
        const bridgeSelect = iface.querySelector('select[id$="Bridge"]');
        const portForwardItems = iface.querySelectorAll('.port-forward-item');

        const network = {
            type: typeSelect.value,
            bridge_name: typeSelect.value === 'bridge' && bridgeSelect ? bridgeSelect.value : null,
            port_forwards: []
        };

        if (typeSelect.value === 'nat') {
            portForwardItems.forEach(pf => {
                const hostPort = parseInt(pf.querySelector('.pf-host').value);
                const guestPort = parseInt(pf.querySelector('.pf-guest').value);
                const protocol = pf.querySelector('.pf-protocol').value;

                if (hostPort && guestPort) {
                    network.port_forwards.push({
                        host_port: hostPort,
                        guest_port: guestPort,
                        protocol: protocol
                    });
                }
            });
        }

        networks.push(network);
    });

    return networks.length > 0 ? networks : [{ type: 'nat', port_forwards: [] }];
}

// ==================== Boot Order Functions ====================

function getBootOrder(containerId) {
    const container = document.getElementById(containerId);
    const items = container.querySelectorAll('.boot-order-item');
    const order = [];

    items.forEach(item => {
        const checkbox = item.querySelector('input[type="checkbox"]');
        if (checkbox.checked) {
            order.push(item.dataset.device);
        }
    });

    return order.length > 0 ? order : ['disk', 'cdrom'];
}

function setBootOrder(containerId, bootOrder) {
    const container = document.getElementById(containerId);
    const items = container.querySelectorAll('.boot-order-item');

    items.forEach(item => {
        const checkbox = item.querySelector('input[type="checkbox"]');
        checkbox.checked = bootOrder.includes(item.dataset.device);
    });
}

// ==================== Section Toggle ====================

function toggleSection(sectionId) {
    const section = document.getElementById(sectionId);
    const title = section.previousElementSibling;
    const icon = title.querySelector('.collapse-icon');

    if (section.style.display === 'none') {
        section.style.display = 'block';
        icon.textContent = '▼';
    } else {
        section.style.display = 'none';
        icon.textContent = '▶';
    }
}

// ==================== VM CRUD Functions ====================

async function handleCreateVM(e) {
    e.preventDefault();

    const formData = new FormData(createVmForm);
    const vmData = {
        name: formData.get('name'),
        memory: parseInt(formData.get('memory')),
        cpus: parseInt(formData.get('cpus')),
        disk_size: parseInt(formData.get('disk_size')),
        iso_path: formData.get('iso_path') || null,
        networks: getNetworkConfigs('networkInterfaces'),
        boot_order: getBootOrder('bootOrderContainer'),
        cpu_model: document.getElementById('vmCpuModel').value,
        display_type: document.getElementById('vmDisplayType').value
    };

    try {
        const submitBtn = createVmForm.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Creando...';

        const response = await apiRequest('/vms', {
            method: 'POST',
            body: JSON.stringify(vmData)
        });

        showToast(response.message, 'success');
        closeCreateModal();
        createVmForm.reset();
        await loadVMs();
    } catch (error) {
        showToast('Error al crear VM: ' + error.message, 'error');
    } finally {
        const submitBtn = createVmForm.querySelector('button[type="submit"]');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Crear VM';
    }
}

async function startVM(vmId) {
    try {
        showToast('Iniciando VM...', 'info');
        const response = await apiRequest(`/vms/${vmId}/start`, { method: 'POST' });
        showToast(response.message, 'success');
        await loadVMs();
    } catch (error) {
        showToast('Error al iniciar VM: ' + error.message, 'error');
    }
}

async function stopVM(vmId) {
    try {
        showToast('Deteniendo VM...', 'info');
        const response = await apiRequest(`/vms/${vmId}/stop`, { method: 'POST' });
        showToast(response.message, 'success');
        await loadVMs();
    } catch (error) {
        showToast('Error al detener VM: ' + error.message, 'error');
    }
}

async function restartVM(vmId) {
    try {
        showToast('Reiniciando VM...', 'info');
        const response = await apiRequest(`/vms/${vmId}/restart`, { method: 'POST' });
        showToast(response.message, 'success');
        await loadVMs();
    } catch (error) {
        showToast('Error al reiniciar VM: ' + error.message, 'error');
    }
}

async function deleteVM(vmId, vmName) {
    if (!confirm(`¿Eliminar la VM "${vmName}"?\n\nEsta acción no se puede deshacer.`)) {
        return;
    }

    try {
        showToast('Eliminando VM...', 'info');
        const response = await apiRequest(`/vms/${vmId}`, { method: 'DELETE' });
        showToast(response.message, 'success');
        await loadVMs();
    } catch (error) {
        showToast('Error al eliminar VM: ' + error.message, 'error');
    }
}

// ==================== Edit VM Functions ====================

async function openEditVMModal(vmId) {
    try {
        currentEditVmId = vmId;
        editNetworkInterfaceCounter = 0;

        const vm = await apiRequest(`/vms/${vmId}`);
        const isos = await apiRequest('/isos');
        const volumes = await apiRequest('/volumes');

        // Basic settings
        editVmNameDisplay.textContent = vm.name;
        editVmMemory.value = vm.memory;
        editVmCpus.value = vm.cpus;

        // ISO dropdown
        editVmIso.innerHTML = '<option value="">Sin ISO</option>';
        isos.forEach(iso => {
            const option = document.createElement('option');
            option.value = iso.path;
            option.textContent = `${iso.name} (${iso.size_mb} MB)`;
            if (vm.iso_path === iso.path) option.selected = true;
            editVmIso.appendChild(option);
        });

        // Network interfaces
        const editNetworkInterfaces = document.getElementById('editNetworkInterfaces');
        editNetworkInterfaces.innerHTML = '';
        const networks = vm.networks || [{ type: 'nat', port_forwards: [] }];
        networks.forEach((net, idx) => {
            editNetworkInterfaces.insertAdjacentHTML('beforeend',
                createNetworkInterfaceHTML('edit', idx, net));
            editNetworkInterfaceCounter++;
        });

        // Hardware options
        document.getElementById('editVmCpuModel').value = vm.cpu_model || 'host';
        document.getElementById('editVmDisplayType').value = vm.display_type || 'std';
        setBootOrder('editBootOrderContainer', vm.boot_order || ['disk', 'cdrom']);

        // Attached volumes
        await loadAttachedVolumes(vmId, vm.volumes || [], volumes);

        editVmModal.style.display = 'block';
    } catch (error) {
        showToast('Error al abrir editor: ' + error.message, 'error');
        console.error('Error al abrir editor:', error);
    }
}

async function loadAttachedVolumes(vmId, attachedVolIds, allVolumes) {
    const attachedContainer = document.getElementById('attachedVolumes');
    const availableSelect = document.getElementById('availableVolumes');

    // Show attached volumes
    if (attachedVolIds.length === 0) {
        attachedContainer.innerHTML = '<p class="empty-text">No hay volúmenes adjuntos</p>';
    } else {
        attachedContainer.innerHTML = attachedVolIds.map(volId => {
            const vol = allVolumes.find(v => v.id === volId);
            if (!vol) return '';
            return `
                <div class="attached-volume-item">
                    <span>${escapeHtml(vol.name)} (${vol.size_gb} GB, ${vol.format})</span>
                    <button type="button" class="btn btn-danger btn-small"
                            onclick="detachVolumeFromVm('${volId}')">Desadjuntar</button>
                </div>
            `;
        }).join('');
    }

    // Populate available volumes (not attached to any VM)
    const available = allVolumes.filter(v => !v.attached_to);
    availableSelect.innerHTML = '<option value="">Seleccionar volumen...</option>';
    available.forEach(vol => {
        const option = document.createElement('option');
        option.value = vol.id;
        option.textContent = `${vol.name} (${vol.size_gb} GB, ${vol.format})`;
        availableSelect.appendChild(option);
    });
}

async function attachVolumeToVm() {
    const volId = document.getElementById('availableVolumes').value;
    if (!volId || !currentEditVmId) return;

    try {
        await apiRequest(`/vms/${currentEditVmId}/volumes/${volId}`, { method: 'POST' });
        showToast('Volumen adjuntado', 'success');

        // Reload volumes
        const vm = await apiRequest(`/vms/${currentEditVmId}`);
        const volumes = await apiRequest('/volumes');
        await loadAttachedVolumes(currentEditVmId, vm.volumes || [], volumes);
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    }
}

async function detachVolumeFromVm(volId) {
    if (!currentEditVmId) return;

    try {
        await apiRequest(`/vms/${currentEditVmId}/volumes/${volId}`, { method: 'DELETE' });
        showToast('Volumen desadjuntado', 'success');

        // Reload volumes
        const vm = await apiRequest(`/vms/${currentEditVmId}`);
        const volumes = await apiRequest('/volumes');
        await loadAttachedVolumes(currentEditVmId, vm.volumes || [], volumes);
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    }
}

async function handleEditVM(e) {
    e.preventDefault();
    if (!currentEditVmId) return;

    const updates = {
        memory: parseInt(editVmMemory.value),
        cpus: parseInt(editVmCpus.value),
        iso_path: editVmIso.value || null,
        networks: getNetworkConfigs('editNetworkInterfaces'),
        boot_order: getBootOrder('editBootOrderContainer'),
        cpu_model: document.getElementById('editVmCpuModel').value,
        display_type: document.getElementById('editVmDisplayType').value
    };

    try {
        const submitBtn = editVmForm.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Guardando...';

        const response = await apiRequest(`/vms/${currentEditVmId}`, {
            method: 'PUT',
            body: JSON.stringify(updates)
        });

        showToast(response.message, 'success');
        closeEditVmModal();
        await loadVMs();
    } catch (error) {
        showToast('Error al actualizar VM: ' + error.message, 'error');
    } finally {
        const submitBtn = editVmForm.querySelector('button[type="submit"]');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Guardar Cambios';
    }
}

function closeEditVmModal() {
    editVmModal.style.display = 'none';
    currentEditVmId = null;
    editVmForm.reset();
}

// ==================== Volumes Functions ====================

function openVolumesModal() {
    volumesModal.style.display = 'block';
    loadVolumes();
}

function closeVolumesModal() {
    volumesModal.style.display = 'none';
    hideCreateVolumeForm();
}

async function loadVolumes() {
    try {
        volumesList.innerHTML = '<div class="loading">Cargando volúmenes...</div>';
        const volumes = await apiRequest('/volumes');

        if (volumes.length === 0) {
            volumesList.innerHTML = '<div class="empty-state"><p>No hay volúmenes creados</p></div>';
            return;
        }

        volumesList.innerHTML = volumes.map(vol => `
            <div class="volume-card">
                <div class="volume-header">
                    <span class="volume-name">${escapeHtml(vol.name)}</span>
                    <span class="volume-status ${vol.attached_to ? 'attached' : 'available'}">
                        ${vol.attached_to ? 'Adjunto' : 'Disponible'}
                    </span>
                </div>
                <div class="volume-details">
                    <span>${vol.size_gb} GB</span>
                    <span>${vol.format}</span>
                </div>
                <div class="volume-actions">
                    ${!vol.attached_to ? `
                        <button class="btn btn-danger btn-small" onclick="deleteVolume('${vol.id}', '${escapeHtml(vol.name)}')">
                            🗑 Eliminar
                        </button>
                    ` : '<span class="help-text">Desadjuntar primero</span>'}
                </div>
            </div>
        `).join('');
    } catch (error) {
        volumesList.innerHTML = '<div class="error">Error al cargar volúmenes</div>';
        showToast('Error: ' + error.message, 'error');
    }
}

function showCreateVolumeForm() {
    document.getElementById('createVolumeForm').style.display = 'block';
}

function hideCreateVolumeForm() {
    document.getElementById('createVolumeForm').style.display = 'none';
    document.getElementById('volName').value = '';
    document.getElementById('volSize').value = '10';
    document.getElementById('volFormat').value = 'qcow2';
}

async function createVolume() {
    const name = document.getElementById('volName').value.trim();
    const size = parseInt(document.getElementById('volSize').value);
    const format = document.getElementById('volFormat').value;

    if (!name) {
        showToast('El nombre es requerido', 'error');
        return;
    }

    try {
        showToast('Creando volumen...', 'info');
        await apiRequest('/volumes', {
            method: 'POST',
            body: JSON.stringify({ name, size_gb: size, format })
        });
        showToast('Volumen creado', 'success');
        hideCreateVolumeForm();
        loadVolumes();
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    }
}

async function deleteVolume(volId, volName) {
    if (!confirm(`¿Eliminar el volumen "${volName}"?`)) return;

    try {
        await apiRequest(`/volumes/${volId}`, { method: 'DELETE' });
        showToast('Volumen eliminado', 'success');
        loadVolumes();
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    }
}

// ==================== Snapshots Functions ====================

function openSnapshotsModal(vmId, vmName) {
    currentSnapshotsVmId = vmId;
    snapshotsVmName.textContent = vmName;
    snapshotsModal.style.display = 'block';
    loadSnapshots(vmId);
}

function closeSnapshotsModal() {
    snapshotsModal.style.display = 'none';
    currentSnapshotsVmId = null;
    hideCreateSnapshotForm();
}

async function loadSnapshots(vmId) {
    try {
        snapshotsList.innerHTML = '<div class="loading">Cargando snapshots...</div>';
        const snapshots = await apiRequest(`/vms/${vmId}/snapshots`);

        if (snapshots.length === 0) {
            snapshotsList.innerHTML = '<div class="empty-state"><p>No hay snapshots</p></div>';
            return;
        }

        snapshotsList.innerHTML = snapshots.map(snap => `
            <div class="snapshot-item">
                <div class="snapshot-info">
                    <span class="snapshot-name">${escapeHtml(snap.name)}</span>
                    <span class="snapshot-date">${new Date(snap.created_at).toLocaleString()}</span>
                    ${snap.description ? `<span class="snapshot-desc">${escapeHtml(snap.description)}</span>` : ''}
                    ${snap.vm_size ? `<span class="snapshot-size">${snap.vm_size}</span>` : ''}
                </div>
                <div class="snapshot-actions">
                    <button class="btn btn-success btn-small" onclick="restoreSnapshot('${snap.id}')">
                        ↩ Restaurar
                    </button>
                    <button class="btn btn-danger btn-small" onclick="deleteSnapshot('${snap.id}', '${escapeHtml(snap.name)}')">
                        🗑 Eliminar
                    </button>
                </div>
            </div>
        `).join('');
    } catch (error) {
        snapshotsList.innerHTML = '<div class="error">Error al cargar snapshots</div>';
        showToast('Error: ' + error.message, 'error');
    }
}

function showCreateSnapshotForm() {
    document.getElementById('createSnapshotForm').style.display = 'block';
}

function hideCreateSnapshotForm() {
    document.getElementById('createSnapshotForm').style.display = 'none';
    document.getElementById('snapName').value = '';
    document.getElementById('snapDescription').value = '';
}

async function createSnapshot() {
    if (!currentSnapshotsVmId) return;

    const name = document.getElementById('snapName').value.trim();
    const description = document.getElementById('snapDescription').value.trim();

    if (!name) {
        showToast('El nombre es requerido', 'error');
        return;
    }

    try {
        showToast('Creando snapshot...', 'info');
        await apiRequest(`/vms/${currentSnapshotsVmId}/snapshots`, {
            method: 'POST',
            body: JSON.stringify({ name, description: description || null })
        });
        showToast('Snapshot creado', 'success');
        hideCreateSnapshotForm();
        loadSnapshots(currentSnapshotsVmId);
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    }
}

async function restoreSnapshot(snapId) {
    if (!currentSnapshotsVmId) return;

    if (!confirm('¿Restaurar este snapshot? Se perderán los cambios actuales.')) return;

    try {
        showToast('Restaurando snapshot...', 'info');
        await apiRequest(`/vms/${currentSnapshotsVmId}/snapshots/${snapId}/restore`, {
            method: 'POST'
        });
        showToast('Snapshot restaurado', 'success');
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    }
}

async function deleteSnapshot(snapId, snapName) {
    if (!currentSnapshotsVmId) return;

    if (!confirm(`¿Eliminar el snapshot "${snapName}"?`)) return;

    try {
        await apiRequest(`/vms/${currentSnapshotsVmId}/snapshots/${snapId}`, {
            method: 'DELETE'
        });
        showToast('Snapshot eliminado', 'success');
        loadSnapshots(currentSnapshotsVmId);
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    }
}

// ==================== UI Helper Functions ====================

function openModal() {
    // Reset network interfaces
    networkInterfaceCounter = 0;
    const networkInterfaces = document.getElementById('networkInterfaces');
    networkInterfaces.innerHTML = '';
    addNetworkInterface('create');

    // Load ISOs
    loadIsos();

    createVmModal.style.display = 'block';
    document.getElementById('vmName').focus();
}

function closeCreateModal() {
    createVmModal.style.display = 'none';
    createVmForm.reset();
}

function showToast(message, type = 'info') {
    toast.textContent = message;
    toast.className = `toast ${type}`;
    toast.style.display = 'block';

    setTimeout(() => {
        toast.style.display = 'none';
    }, 3000);
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return String(text).replace(/[&<>"']/g, m => map[m]);
}

// ==================== VNC Console Functions ====================

async function openVNCConsole(vmId, vmName) {
    try {
        showToast('Iniciando consola VNC...', 'info');

        const vncInfo = await apiRequest(`/vms/${vmId}/vnc`);

        if (vncInfo.status !== 'ready') {
            throw new Error('VNC no disponible. Asegúrate de que la VM esté iniciada.');
        }

        const wsHost = window.location.hostname || 'localhost';
        const vncUrl = `http://${wsHost}:${vncInfo.ws_port}/vnc.html?autoconnect=true&resize=scale`;
        vncFramePanel.src = vncUrl;
        vncVmNamePanel.textContent = vmName;

        rightPanel.classList.add('active');
        leftPanel.classList.add('compressed');

        showToast('Consola VNC iniciada', 'success');
    } catch (error) {
        showToast('Error al abrir consola VNC: ' + error.message, 'error');
        console.error('Error al abrir consola VNC:', error);
    }
}

function closeVNCPanel() {
    rightPanel.classList.remove('active');
    leftPanel.classList.remove('compressed');
    vncFramePanel.src = '';
}

// ==================== Logs Functions ====================

async function showVMLogs(vmId, vmName) {
    currentLogsVmId = vmId;
    logsVmName.textContent = vmName;
    logsModal.style.display = 'block';
    await loadVMLogs(vmId);
}

async function loadVMLogs(vmId) {
    try {
        qemuLog.textContent = 'Cargando...';
        serialLog.textContent = 'Cargando...';

        const logs = await apiRequest(`/vms/${vmId}/logs`);

        qemuLog.textContent = logs.qemu_log || 'No hay logs disponibles';
        serialLog.textContent = logs.serial_log || 'No hay logs disponibles';
    } catch (error) {
        qemuLog.textContent = `Error al cargar logs: ${error.message}`;
        serialLog.textContent = `Error al cargar logs: ${error.message}`;
        showToast('Error al cargar logs: ' + error.message, 'error');
    }
}

function closeLogsModal() {
    logsModal.style.display = 'none';
    currentLogsVmId = null;
}
