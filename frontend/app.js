const API_BASE = '/api';

// DOM Elements
const vmsList = document.getElementById('vmsList');
const createVmBtn = document.getElementById('createVmBtn');
const refreshBtn = document.getElementById('refreshBtn');
const createVmModal = document.getElementById('createVmModal');
const createVmForm = document.getElementById('createVmForm');
const closeModal = document.querySelector('.close');
const cancelCreateBtn = document.getElementById('cancelCreateBtn');
const toast = document.getElementById('toast');

// Event Listeners
createVmBtn.addEventListener('click', () => openModal());
refreshBtn.addEventListener('click', () => loadVMs());
closeModal.addEventListener('click', () => closeCreateModal());
cancelCreateBtn.addEventListener('click', () => closeCreateModal());
createVmForm.addEventListener('submit', handleCreateVM);

window.addEventListener('click', (e) => {
    if (e.target === createVmModal) {
        closeCreateModal();
    }
});

// Initialize
loadVMs();

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
            ${vm.vnc_port ? `
            <div class="vm-detail-item">
                <span class="vm-detail-label">VNC Port:</span>
                <span class="vm-detail-value">${vm.vnc_port}</span>
            </div>
            ` : ''}
            ${vm.pid ? `
            <div class="vm-detail-item">
                <span class="vm-detail-label">PID:</span>
                <span class="vm-detail-value">${vm.pid}</span>
            </div>
            ` : ''}
        </div>
        <div class="vm-actions">
            ${vm.status === 'stopped' ?
                `<button class="btn btn-success" onclick="startVM('${vm.id}')">▶ Iniciar</button>` :
                `<button class="btn btn-warning" onclick="stopVM('${vm.id}')">⏸ Detener</button>`
            }
            <button class="btn btn-danger" onclick="deleteVM('${vm.id}', '${escapeHtml(vm.name)}')">🗑 Eliminar</button>
        </div>
    `;
    return card;
}

async function handleCreateVM(e) {
    e.preventDefault();

    const formData = new FormData(createVmForm);
    const vmData = {
        name: formData.get('name'),
        memory: parseInt(formData.get('memory')),
        cpus: parseInt(formData.get('cpus')),
        disk_size: parseInt(formData.get('disk_size')),
        iso_path: formData.get('iso_path') || null
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
        const response = await apiRequest(`/vms/${vmId}/start`, {
            method: 'POST'
        });
        showToast(response.message, 'success');
        await loadVMs();
    } catch (error) {
        showToast('Error al iniciar VM: ' + error.message, 'error');
    }
}

async function stopVM(vmId) {
    try {
        showToast('Deteniendo VM...', 'info');
        const response = await apiRequest(`/vms/${vmId}/stop`, {
            method: 'POST'
        });
        showToast(response.message, 'success');
        await loadVMs();
    } catch (error) {
        showToast('Error al detener VM: ' + error.message, 'error');
    }
}

async function deleteVM(vmId, vmName) {
    if (!confirm(`¿Estás seguro de eliminar la VM "${vmName}"?\n\nEsta acción no se puede deshacer.`)) {
        return;
    }

    try {
        showToast('Eliminando VM...', 'info');
        const response = await apiRequest(`/vms/${vmId}`, {
            method: 'DELETE'
        });
        showToast(response.message, 'success');
        await loadVMs();
    } catch (error) {
        showToast('Error al eliminar VM: ' + error.message, 'error');
    }
}

// UI Helper Functions
function openModal() {
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
    return text.replace(/[&<>"']/g, m => map[m]);
}
