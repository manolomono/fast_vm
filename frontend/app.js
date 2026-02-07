// Fast VM Dashboard - Alpine.js Application

// API Helper with auth
async function api(endpoint, options = {}) {
    const token = localStorage.getItem('token');
    const headers = {
        'Content-Type': 'application/json',
        ...(token && { 'Authorization': `Bearer ${token}` }),
        ...options.headers
    };

    const response = await fetch(`/api${endpoint}`, { ...options, headers });

    if (response.status === 401) {
        localStorage.removeItem('token');
        window.location.href = '/login.html';
        throw new Error('Unauthorized');
    }

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || 'API Error');
    }

    return response.json();
}

// Main Dashboard Component
function dashboard() {
    return {
        // State
        ready: false,
        user: null,
        vms: [],
        volumes: [],
        isos: [],
        bridges: [],
        interfaces: [],

        // UI State
        currentView: 'dashboard',
        selectedVm: null,
        showConsole: false,
        consoleVm: null,
        consoleUrl: '',

        // Metrics
        vmMetrics: {},
        hostMetrics: null,

        // Users
        users: [],
        passwordForm: { current_password: '', new_password: '', confirm_password: '' },
        createUserForm: { username: '', password: '', is_admin: false },

        // Clone & Cloud-init
        cloneForm: { name: '', memory: null, cpus: null },
        cloneSource: null,
        cloudInitForm: {
            hostname: '',
            username: 'user',
            password: '',
            ssh_authorized_keys: '',
            packages: 'spice-vdagent qemu-guest-agent',
            static_ip: '',
            gateway: '',
            dns: '8.8.8.8, 8.8.4.4'
        },

        // Modals
        showCreateModal: false,
        showEditModal: false,
        showVolumeModal: false,
        showDeleteModal: false,
        showCreateUserModal: false,
        showCloneModal: false,
        showCloudInitModal: false,
        deleteTarget: null,
        editTarget: null,
        selectedVolumeToAttach: '',

        // Form data
        createForm: {
            name: '',
            memory: 2048,
            cpus: 2,
            disk_size: 20,
            iso_path: '',
            secondary_iso_path: '',
            cpu_model: 'host',
            display_type: 'qxl',
            networks: [{ type: 'nat', model: 'virtio', port_forwards: [] }],
            boot_order: ['disk', 'cdrom']
        },

        volumeForm: {
            name: '',
            size_gb: 10,
            format: 'qcow2'
        },

        // Computed
        get runningVMs() {
            return this.vms.filter(v => v.status === 'running').length;
        },
        get stoppedVMs() {
            return this.vms.filter(v => v.status !== 'running').length;
        },
        get availableVolumes() {
            if (!this.editTarget) return [];
            // Show volumes that are not attached to any VM, excluding those already attached to the current VM
            const attachedToThisVm = this.editTarget.volumes || [];
            return this.volumes.filter(v => !v.attached_to && !attachedToThisVm.includes(v.id));
        },

        // Initialize
        async init() {
            const token = localStorage.getItem('token');
            if (!token) {
                window.location.href = '/login.html';
                return;
            }

            try {
                this.user = await api('/auth/me');
                await this.loadData();
                this.ready = true;
                this.injectModals();

                // Auto-refresh every 10 seconds
                setInterval(() => {
                    this.loadVMs();
                    this.loadMetrics();
                }, 10000);

                // Load metrics immediately
                this.loadMetrics();
                if (this.user?.is_admin) this.loadUsers();
            } catch (err) {
                console.error('Init error:', err);
                localStorage.removeItem('token');
                window.location.href = '/login.html';
            }
        },

        async loadData() {
            await Promise.all([
                this.loadVMs(),
                this.loadVolumes(),
                this.loadIsos(),
                this.loadBridges(),
                this.loadInterfaces()
            ]);
        },

        async loadVMs() {
            try {
                this.vms = await api('/vms');
            } catch (err) {
                console.error('Error loading VMs:', err);
            }
        },

        async loadVolumes() {
            try {
                this.volumes = await api('/volumes');
            } catch (err) {
                console.error('Error loading volumes:', err);
            }
        },

        async loadIsos() {
            try {
                this.isos = await api('/isos');
            } catch (err) {
                console.error('Error loading ISOs:', err);
            }
        },

        async loadBridges() {
            try {
                this.bridges = await api('/bridges');
            } catch (err) {
                console.error('Error loading bridges:', err);
            }
        },

        async loadInterfaces() {
            try {
                this.interfaces = await api('/interfaces');
            } catch (err) {
                console.error('Error loading interfaces:', err);
            }
        },

        // Metrics
        async loadMetrics() {
            // Host metrics
            try {
                this.hostMetrics = await api('/system/metrics');
            } catch (err) {
                console.error('Error loading host metrics:', err);
            }

            // VM metrics (only for running VMs)
            const running = this.vms.filter(v => v.status === 'running');
            for (const vm of running) {
                try {
                    this.vmMetrics[vm.id] = await api(`/vms/${vm.id}/metrics`);
                } catch (err) {
                    // Silently ignore - VM may have just stopped
                }
            }
        },

        // User Management
        async loadUsers() {
            try {
                this.users = await api('/auth/users');
            } catch (err) {
                console.error('Error loading users:', err);
            }
        },

        async createUser() {
            try {
                await api('/auth/users', {
                    method: 'POST',
                    body: JSON.stringify(this.createUserForm)
                });
                this.showToast('User created successfully', 'success');
                this.showCreateUserModal = false;
                this.createUserForm = { username: '', password: '', is_admin: false };
                await this.loadUsers();
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        deleteUserConfirm(u) {
            if (!confirm(`Delete user "${u.username}"?`)) return;
            this.deleteUser(u.username);
        },

        async deleteUser(username) {
            try {
                await api(`/auth/users/${username}`, { method: 'DELETE' });
                this.showToast('User deleted', 'success');
                await this.loadUsers();
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        async changePassword() {
            if (this.passwordForm.new_password !== this.passwordForm.confirm_password) {
                this.showToast('Passwords do not match', 'error');
                return;
            }
            try {
                await api('/auth/change-password', {
                    method: 'POST',
                    body: JSON.stringify({
                        current_password: this.passwordForm.current_password,
                        new_password: this.passwordForm.new_password
                    })
                });
                this.showToast('Password changed successfully', 'success');
                this.passwordForm = { current_password: '', new_password: '', confirm_password: '' };
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        // Monitoring charts
        charts: {},
        monitoringInterval: null,

        async loadMonitoringCharts() {
            // Small delay to ensure DOM is ready
            await new Promise(r => setTimeout(r, 100));

            try {
                const data = await api('/metrics/history');
                this.renderHostCharts(data.host);
                this.renderVmCharts(data.vms);
            } catch (err) {
                console.error('Error loading monitoring data:', err);
            }

            // Auto-refresh charts every 10s
            if (this.monitoringInterval) clearInterval(this.monitoringInterval);
            this.monitoringInterval = setInterval(async () => {
                if (this.currentView !== 'monitoring') {
                    clearInterval(this.monitoringInterval);
                    this.monitoringInterval = null;
                    return;
                }
                try {
                    const data = await api('/metrics/history');
                    this.renderHostCharts(data.host);
                    this.renderVmCharts(data.vms);
                } catch (err) { /* ignore */ }
            }, 10000);
        },

        chartDefaults() {
            return {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 300 },
                scales: {
                    x: { display: true, ticks: { maxTicksLimit: 8, color: '#64748b', font: { size: 10 } }, grid: { color: '#334155' } },
                    y: { display: true, beginAtZero: true, ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: '#334155' } }
                },
                plugins: { legend: { display: false } }
            };
        },

        renderChart(canvasId, labels, datasets, opts = {}) {
            const canvas = document.getElementById(canvasId);
            if (!canvas) return;

            // Destroy existing chart
            if (this.charts[canvasId]) {
                this.charts[canvasId].destroy();
            }

            const defaults = this.chartDefaults();
            if (opts.yMax) defaults.scales.y.max = opts.yMax;
            if (opts.legend) defaults.plugins.legend = { display: true, labels: { color: '#94a3b8', boxWidth: 12, font: { size: 11 } } };

            this.charts[canvasId] = new Chart(canvas, {
                type: 'line',
                data: { labels, datasets },
                options: defaults
            });
        },

        formatTime(iso) {
            if (!iso) return '';
            const d = new Date(iso + 'Z');
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        },

        renderHostCharts(hostData) {
            if (!hostData || hostData.length === 0) return;
            const labels = hostData.map(p => this.formatTime(p.t));

            this.renderChart('chartHostCpu', labels, [{
                data: hostData.map(p => p.cpu),
                borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.1)',
                fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2
            }], { yMax: 100 });

            this.renderChart('chartHostMem', labels, [{
                data: hostData.map(p => p.mem),
                borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)',
                fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2
            }], { yMax: 100 });
        },

        renderVmCharts(vmsData) {
            if (!vmsData) return;
            for (const [vmId, points] of Object.entries(vmsData)) {
                if (!points || points.length === 0) continue;
                const labels = points.map(p => this.formatTime(p.t));

                this.renderChart('chartVmCpu_' + vmId, labels, [{
                    data: points.map(p => p.cpu),
                    borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.1)',
                    fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2
                }]);

                this.renderChart('chartVmMem_' + vmId, labels, [{
                    data: points.map(p => p.mem_mb),
                    borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)',
                    fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2
                }]);

                this.renderChart('chartVmIo_' + vmId, labels, [
                    {
                        label: 'Read',
                        data: points.map(p => p.io_r),
                        borderColor: '#06b6d4', backgroundColor: 'rgba(6,182,212,0.1)',
                        fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2
                    },
                    {
                        label: 'Write',
                        data: points.map(p => p.io_w),
                        borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.1)',
                        fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2
                    }
                ], { legend: true });
            }
        },

        // Clone
        openCloneModal(vm) {
            this.cloneSource = vm;
            this.cloneForm = { name: vm.name + ' (clone)', memory: vm.memory, cpus: vm.cpus };
            this.showCloneModal = true;
        },

        async cloneVM() {
            if (!this.cloneSource) return;
            try {
                const data = { name: this.cloneForm.name };
                if (this.cloneForm.memory) data.memory = this.cloneForm.memory;
                if (this.cloneForm.cpus) data.cpus = this.cloneForm.cpus;

                await api(`/vms/${this.cloneSource.id}/clone`, {
                    method: 'POST',
                    body: JSON.stringify(data)
                });
                this.showToast('VM cloned successfully', 'success');
                this.showCloneModal = false;
                this.cloneSource = null;
                await this.loadVMs();
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        // Cloud-init
        async createCloudInit() {
            try {
                const data = {
                    hostname: this.cloudInitForm.hostname,
                    username: this.cloudInitForm.username,
                    packages: this.cloudInitForm.packages
                        ? this.cloudInitForm.packages.split(/[\s,]+/).filter(Boolean) : [],
                    dns: this.cloudInitForm.dns
                        ? this.cloudInitForm.dns.split(/[\s,]+/).filter(Boolean) : ['8.8.8.8'],
                };
                if (this.cloudInitForm.password) data.password = this.cloudInitForm.password;
                if (this.cloudInitForm.ssh_authorized_keys) {
                    data.ssh_authorized_keys = this.cloudInitForm.ssh_authorized_keys
                        .split('\n').filter(Boolean);
                }
                if (this.cloudInitForm.static_ip) data.static_ip = this.cloudInitForm.static_ip;
                if (this.cloudInitForm.gateway) data.gateway = this.cloudInitForm.gateway;

                await api('/cloudinit', {
                    method: 'POST',
                    body: JSON.stringify(data)
                });
                this.showToast(`Cloud-init ISO created for '${data.hostname}'. Use it as secondary ISO when creating a VM.`, 'success');
                this.showCloudInitModal = false;
                this.cloudInitForm = {
                    hostname: '', username: 'user', password: '',
                    ssh_authorized_keys: '', packages: 'spice-vdagent qemu-guest-agent',
                    static_ip: '', gateway: '', dns: '8.8.8.8, 8.8.4.4'
                };
                await this.loadIsos();
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        // VM Actions
        async startVM(id) {
            try {
                await api(`/vms/${id}/start`, { method: 'POST' });
                this.showToast('VM started successfully', 'success');
                await this.loadVMs();
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        async stopVM(id) {
            try {
                await api(`/vms/${id}/stop`, { method: 'POST' });
                this.showToast('VM stopped successfully', 'success');
                await this.loadVMs();
                if (this.consoleVm?.id === id) {
                    this.closeConsole();
                }
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        async createVM() {
            try {
                const data = { ...this.createForm };
                if (!data.iso_path) delete data.iso_path;
                if (!data.secondary_iso_path) delete data.secondary_iso_path;

                await api('/vms', {
                    method: 'POST',
                    body: JSON.stringify(data)
                });
                this.showToast('VM created successfully', 'success');
                this.showCreateModal = false;
                this.resetCreateForm();
                await this.loadVMs();
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        async updateVM() {
            if (!this.editTarget) return;
            try {
                const data = {
                    memory: this.editTarget.memory,
                    cpus: this.editTarget.cpus,
                    iso_path: this.editTarget.iso_path || null,
                    secondary_iso_path: this.editTarget.secondary_iso_path || null,
                    cpu_model: this.editTarget.cpu_model,
                    display_type: this.editTarget.display_type,
                    networks: this.editTarget.networks,
                    boot_order: this.editTarget.boot_order
                };

                await api(`/vms/${this.editTarget.id}`, {
                    method: 'PUT',
                    body: JSON.stringify(data)
                });
                this.showToast('VM updated successfully', 'success');
                this.showEditModal = false;
                this.editTarget = null;
                await this.loadVMs();
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        async deleteVM() {
            if (!this.deleteTarget) return;
            try {
                await api(`/vms/${this.deleteTarget.id}`, { method: 'DELETE' });
                this.showToast('VM deleted successfully', 'success');
                this.showDeleteModal = false;
                this.deleteTarget = null;
                await this.loadVMs();
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        // Volume Actions
        async createVolume() {
            try {
                await api('/volumes', {
                    method: 'POST',
                    body: JSON.stringify(this.volumeForm)
                });
                this.showToast('Volume created successfully', 'success');
                this.showVolumeModal = false;
                this.volumeForm = { name: '', size_gb: 10, format: 'qcow2' };
                await this.loadVolumes();
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        async deleteVolume(vol) {
            if (!confirm(`Delete volume "${vol.name}"?`)) return;
            try {
                await api(`/volumes/${vol.id}`, { method: 'DELETE' });
                this.showToast('Volume deleted', 'success');
                await this.loadVolumes();
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        // Volume attach/detach for edit modal
        getVolumeName(volId) {
            const vol = this.volumes.find(v => v.id === volId);
            return vol ? `${vol.name} (${vol.size_gb}GB)` : volId;
        },

        async attachVolume() {
            if (!this.selectedVolumeToAttach || !this.editTarget) return;
            try {
                await api(`/vms/${this.editTarget.id}/volumes/${this.selectedVolumeToAttach}`, { method: 'POST' });
                this.showToast('Volume attached', 'success');
                // Update local state
                if (!this.editTarget.volumes) this.editTarget.volumes = [];
                this.editTarget.volumes.push(this.selectedVolumeToAttach);
                this.selectedVolumeToAttach = '';
                await this.loadVolumes();
                await this.loadVMs();
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        async detachVolume(volId) {
            if (!this.editTarget) return;
            try {
                await api(`/vms/${this.editTarget.id}/volumes/${volId}`, { method: 'DELETE' });
                this.showToast('Volume detached', 'success');
                // Update local state
                this.editTarget.volumes = this.editTarget.volumes.filter(v => v !== volId);
                await this.loadVolumes();
                await this.loadVMs();
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        // Console
        async openConsole(vm) {
            try {
                const info = await api(`/vms/${vm.id}/spice`);
                const token = localStorage.getItem('token');
                // Build the SPICE HTML5 client URL with proper parameters including vm_id and token for reconnection
                this.consoleUrl = `/spice/spice_auto.html?host=localhost&port=${info.ws_port}&vm_id=${vm.id}&token=${encodeURIComponent(token)}`;
                this.consoleVm = vm;
                this.showConsole = true;
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        },

        closeConsole() {
            this.showConsole = false;
            this.consoleVm = null;
            this.consoleUrl = '';
        },

        toggleFullscreen() {
            const frame = document.getElementById('consoleFrame');
            if (frame.requestFullscreen) {
                frame.requestFullscreen();
            }
        },

        // UI Helpers
        selectVm(vm) {
            this.selectedVm = vm;
            this.currentView = 'dashboard';
        },

        editVm(vm) {
            this.editTarget = JSON.parse(JSON.stringify(vm));
            this.showEditModal = true;
        },

        confirmDelete(vm) {
            this.deleteTarget = vm;
            this.showDeleteModal = true;
        },

        resetCreateForm() {
            this.createForm = {
                name: '',
                memory: 2048,
                cpus: 2,
                disk_size: 20,
                iso_path: '',
                secondary_iso_path: '',
                cpu_model: 'host',
                display_type: 'qxl',
                networks: [{ type: 'nat', model: 'virtio', port_forwards: [] }],
                boot_order: ['disk', 'cdrom']
            };
        },

        addNetwork(form) {
            const target = form === 'edit' ? this.editTarget : this.createForm;
            target.networks.push({ type: 'nat', model: 'virtio', port_forwards: [] });
        },

        removeNetwork(form, index) {
            const target = form === 'edit' ? this.editTarget : this.createForm;
            target.networks.splice(index, 1);
        },

        logout() {
            localStorage.removeItem('token');
            window.location.href = '/login.html';
        },

        showToast(message, type = 'info') {
            const toast = document.getElementById('toast');
            if (!toast) return;
            toast.textContent = message;
            toast.className = `toast show ${type}`;
            setTimeout(() => toast.className = 'toast', 3000);
        },

        // Inject modals HTML
        injectModals() {
            document.getElementById('modals').innerHTML = `
                <!-- Toast -->
                <div id="toast" class="fixed bottom-4 right-4 px-6 py-3 rounded-lg shadow-lg transform translate-y-20 opacity-0 transition-all duration-300 z-50 bg-slate-700 text-white">
                    Message
                </div>
                <style>
                    .toast.show { transform: translateY(0); opacity: 1; }
                    .toast.success { background: #059669; }
                    .toast.error { background: #dc2626; }
                </style>

                <!-- Create VM Modal -->
                <div x-show="showCreateModal" x-transition.opacity class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="showCreateModal = false">
                    <div class="bg-slate-800 rounded-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto" @click.stop>
                        <div class="p-6 border-b border-slate-700 flex items-center justify-between">
                            <h2 class="text-xl font-semibold">Create New VM</h2>
                            <button @click="showCreateModal = false" class="text-slate-400 hover:text-white"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg></button>
                        </div>
                        <form @submit.prevent="createVM()" class="p-6 space-y-4">
                            <div class="grid grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">Name</label>
                                    <input x-model="createForm.name" type="text" required class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                </div>
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">Memory (MB)</label>
                                    <input x-model.number="createForm.memory" type="number" min="512" max="32768" step="256" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                </div>
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">CPUs</label>
                                    <input x-model.number="createForm.cpus" type="number" min="1" max="16" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                </div>
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">Disk Size (GB)</label>
                                    <input x-model.number="createForm.disk_size" type="number" min="5" max="500" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                </div>
                            </div>
                            <div class="grid grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">ISO</label>
                                    <select x-model="createForm.iso_path" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                        <option value="">No ISO</option>
                                        <template x-for="iso in isos" :key="iso.path"><option :value="iso.path" x-text="iso.name"></option></template>
                                    </select>
                                </div>
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">Secondary ISO</label>
                                    <select x-model="createForm.secondary_iso_path" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                        <option value="">No ISO</option>
                                        <template x-for="iso in isos" :key="iso.path"><option :value="iso.path" x-text="iso.name"></option></template>
                                    </select>
                                </div>
                            </div>
                            <div class="grid grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">CPU Model</label>
                                    <select x-model="createForm.cpu_model" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                        <option value="host">host (Best performance)</option>
                                        <option value="qemu64">qemu64 (Max compatibility)</option>
                                        <option value="max">max</option>
                                    </select>
                                </div>
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">Display</label>
                                    <select x-model="createForm.display_type" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                        <option value="qxl">QXL (SPICE optimized)</option>
                                        <option value="virtio">Virtio</option>
                                        <option value="std">Standard VGA</option>
                                    </select>
                                </div>
                            </div>
                            <!-- Networks -->
                            <div>
                                <div class="flex items-center justify-between mb-2">
                                    <label class="text-sm text-slate-400">Networks</label>
                                    <button type="button" @click="addNetwork('create')" class="text-xs text-primary-400 hover:text-primary-300">+ Add</button>
                                </div>
                                <template x-for="(net, idx) in createForm.networks" :key="idx">
                                    <div class="flex items-center space-x-2 mb-2 bg-slate-700/50 p-2 rounded-lg">
                                        <select x-model="net.type" class="flex-1 bg-slate-700 border border-slate-600 rounded px-2 py-1 text-sm">
                                            <option value="nat">NAT</option>
                                            <option value="bridge">Bridge</option>
                                            <option value="macvtap">Macvtap</option>
                                        </select>
                                        <select x-model="net.model" class="bg-slate-700 border border-slate-600 rounded px-2 py-1 text-sm">
                                            <option value="virtio">Virtio</option>
                                            <option value="e1000">e1000</option>
                                            <option value="rtl8139">RTL8139</option>
                                        </select>
                                        <template x-if="net.type === 'bridge'">
                                            <select x-model="net.bridge_name" class="bg-slate-700 border border-slate-600 rounded px-2 py-1 text-sm">
                                                <template x-for="br in bridges"><option :value="br" x-text="br"></option></template>
                                            </select>
                                        </template>
                                        <template x-if="net.type === 'macvtap'">
                                            <select x-model="net.parent_interface" class="bg-slate-700 border border-slate-600 rounded px-2 py-1 text-sm">
                                                <template x-for="iface in interfaces"><option :value="iface" x-text="iface"></option></template>
                                            </select>
                                        </template>
                                        <button type="button" @click="removeNetwork('create', idx)" x-show="createForm.networks.length > 1" class="text-red-400 hover:text-red-300 p-1">
                                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                                        </button>
                                    </div>
                                </template>
                            </div>
                            <div class="flex justify-end space-x-3 pt-4 border-t border-slate-700">
                                <button type="button" @click="showCreateModal = false" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg">Cancel</button>
                                <button type="submit" class="px-4 py-2 bg-primary-600 hover:bg-primary-700 rounded-lg">Create VM</button>
                            </div>
                        </form>
                    </div>
                </div>

                <!-- Edit VM Modal -->
                <div x-show="showEditModal" x-transition.opacity class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="showEditModal = false">
                    <div class="bg-slate-800 rounded-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto" @click.stop>
                        <div class="p-6 border-b border-slate-700 flex items-center justify-between">
                            <h2 class="text-xl font-semibold">Edit VM - <span x-text="editTarget?.name"></span></h2>
                            <button @click="showEditModal = false" class="text-slate-400 hover:text-white"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg></button>
                        </div>
                        <form @submit.prevent="updateVM()" class="p-6 space-y-4" x-show="editTarget">
                            <div class="grid grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">Memory (MB)</label>
                                    <input x-model.number="editTarget.memory" type="number" min="512" max="32768" step="256" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                </div>
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">CPUs</label>
                                    <input x-model.number="editTarget.cpus" type="number" min="1" max="16" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                </div>
                            </div>
                            <div class="grid grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">ISO</label>
                                    <select x-model="editTarget.iso_path" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                        <option value="">No ISO</option>
                                        <template x-for="iso in isos" :key="iso.path"><option :value="iso.path" x-text="iso.name"></option></template>
                                    </select>
                                </div>
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">Secondary ISO</label>
                                    <select x-model="editTarget.secondary_iso_path" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                        <option value="">No ISO</option>
                                        <template x-for="iso in isos" :key="iso.path"><option :value="iso.path" x-text="iso.name"></option></template>
                                    </select>
                                </div>
                            </div>
                            <!-- Networks -->
                            <div>
                                <div class="flex items-center justify-between mb-2">
                                    <label class="text-sm text-slate-400">Networks</label>
                                    <button type="button" @click="addNetwork('edit')" class="text-xs text-primary-400 hover:text-primary-300">+ Add</button>
                                </div>
                                <template x-for="(net, idx) in editTarget.networks" :key="idx">
                                    <div class="flex items-center space-x-2 mb-2 bg-slate-700/50 p-2 rounded-lg">
                                        <select x-model="net.type" class="flex-1 bg-slate-700 border border-slate-600 rounded px-2 py-1 text-sm">
                                            <option value="nat">NAT</option>
                                            <option value="bridge">Bridge</option>
                                            <option value="macvtap">Macvtap</option>
                                        </select>
                                        <select x-model="net.model" class="bg-slate-700 border border-slate-600 rounded px-2 py-1 text-sm">
                                            <option value="virtio">Virtio</option>
                                            <option value="e1000">e1000</option>
                                            <option value="rtl8139">RTL8139</option>
                                        </select>
                                        <button type="button" @click="removeNetwork('edit', idx)" x-show="editTarget.networks.length > 1" class="text-red-400 hover:text-red-300 p-1">
                                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                                        </button>
                                    </div>
                                </template>
                            </div>
                            <!-- Volumes -->
                            <div>
                                <div class="flex items-center justify-between mb-2">
                                    <label class="text-sm text-slate-400">Attached Volumes</label>
                                </div>
                                <div class="space-y-2 mb-2">
                                    <template x-for="volId in editTarget.volumes" :key="volId">
                                        <div class="flex items-center justify-between bg-slate-700/50 p-2 rounded-lg">
                                            <span class="text-sm" x-text="getVolumeName(volId)"></span>
                                            <button type="button" @click="detachVolume(volId)" class="text-red-400 hover:text-red-300 p-1" title="Detach">
                                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                                            </button>
                                        </div>
                                    </template>
                                    <p x-show="!editTarget.volumes || editTarget.volumes.length === 0" class="text-slate-500 text-sm">No volumes attached</p>
                                </div>
                                <div class="flex items-center space-x-2">
                                    <select x-model="selectedVolumeToAttach" class="flex-1 bg-slate-700 border border-slate-600 rounded px-2 py-1 text-sm">
                                        <option value="">Select volume...</option>
                                        <template x-for="vol in availableVolumes" :key="vol.id">
                                            <option :value="vol.id" x-text="vol.name + ' (' + vol.size_gb + 'GB)'"></option>
                                        </template>
                                    </select>
                                    <button type="button" @click="attachVolume()" :disabled="!selectedVolumeToAttach" class="px-3 py-1 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-600 disabled:cursor-not-allowed rounded text-sm">Attach</button>
                                </div>
                            </div>
                            <div class="flex justify-end space-x-3 pt-4 border-t border-slate-700">
                                <button type="button" @click="showEditModal = false" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg">Cancel</button>
                                <button type="submit" class="px-4 py-2 bg-primary-600 hover:bg-primary-700 rounded-lg">Save Changes</button>
                            </div>
                        </form>
                    </div>
                </div>

                <!-- Delete Confirmation Modal -->
                <div x-show="showDeleteModal" x-transition.opacity class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="showDeleteModal = false">
                    <div class="bg-slate-800 rounded-xl w-full max-w-md" @click.stop>
                        <div class="p-6">
                            <div class="w-12 h-12 bg-red-600/20 rounded-full flex items-center justify-center mx-auto mb-4">
                                <svg class="w-6 h-6 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                            </div>
                            <h3 class="text-lg font-semibold text-center mb-2">Delete VM</h3>
                            <p class="text-slate-400 text-center mb-6">Are you sure you want to delete "<span x-text="deleteTarget?.name"></span>"? This action cannot be undone.</p>
                            <div class="flex space-x-3">
                                <button @click="showDeleteModal = false" class="flex-1 px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg">Cancel</button>
                                <button @click="deleteVM()" class="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg">Delete</button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Create Volume Modal -->
                <div x-show="showVolumeModal" x-transition.opacity class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="showVolumeModal = false">
                    <div class="bg-slate-800 rounded-xl w-full max-w-md" @click.stop>
                        <div class="p-6 border-b border-slate-700 flex items-center justify-between">
                            <h2 class="text-xl font-semibold">Create Volume</h2>
                            <button @click="showVolumeModal = false" class="text-slate-400 hover:text-white"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg></button>
                        </div>
                        <form @submit.prevent="createVolume()" class="p-6 space-y-4">
                            <div>
                                <label class="block text-sm text-slate-400 mb-1">Name</label>
                                <input x-model="volumeForm.name" type="text" required class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                            </div>
                            <div class="grid grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">Size (GB)</label>
                                    <input x-model.number="volumeForm.size_gb" type="number" min="1" max="1000" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                </div>
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">Format</label>
                                    <select x-model="volumeForm.format" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                        <option value="qcow2">qcow2</option>
                                        <option value="raw">raw</option>
                                    </select>
                                </div>
                            </div>
                            <div class="flex justify-end space-x-3 pt-4 border-t border-slate-700">
                                <button type="button" @click="showVolumeModal = false" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg">Cancel</button>
                                <button type="submit" class="px-4 py-2 bg-primary-600 hover:bg-primary-700 rounded-lg">Create</button>
                            </div>
                        </form>
                    </div>
                </div>

                <!-- Create User Modal -->
                <div x-show="showCreateUserModal" x-transition.opacity class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="showCreateUserModal = false">
                    <div class="bg-slate-800 rounded-xl w-full max-w-md" @click.stop>
                        <div class="p-6 border-b border-slate-700 flex items-center justify-between">
                            <h2 class="text-xl font-semibold">Create User</h2>
                            <button @click="showCreateUserModal = false" class="text-slate-400 hover:text-white"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg></button>
                        </div>
                        <form @submit.prevent="createUser()" class="p-6 space-y-4">
                            <div>
                                <label class="block text-sm text-slate-400 mb-1">Username</label>
                                <input x-model="createUserForm.username" type="text" required minlength="3" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                            </div>
                            <div>
                                <label class="block text-sm text-slate-400 mb-1">Password</label>
                                <input x-model="createUserForm.password" type="password" required minlength="4" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                            </div>
                            <div class="flex items-center space-x-2">
                                <input x-model="createUserForm.is_admin" type="checkbox" id="newUserAdmin" class="w-4 h-4 rounded bg-slate-700 border-slate-600 text-primary-600 focus:ring-primary-500">
                                <label for="newUserAdmin" class="text-sm text-slate-300">Admin privileges</label>
                            </div>
                            <div class="flex justify-end space-x-3 pt-4 border-t border-slate-700">
                                <button type="button" @click="showCreateUserModal = false" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg">Cancel</button>
                                <button type="submit" class="px-4 py-2 bg-primary-600 hover:bg-primary-700 rounded-lg">Create User</button>
                            </div>
                        </form>
                    </div>
                </div>

                <!-- Clone VM Modal -->
                <div x-show="showCloneModal" x-transition.opacity class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="showCloneModal = false">
                    <div class="bg-slate-800 rounded-xl w-full max-w-md" @click.stop>
                        <div class="p-6 border-b border-slate-700 flex items-center justify-between">
                            <h2 class="text-xl font-semibold">Clone VM</h2>
                            <button @click="showCloneModal = false" class="text-slate-400 hover:text-white"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg></button>
                        </div>
                        <form @submit.prevent="cloneVM()" class="p-6 space-y-4">
                            <p class="text-sm text-slate-400">Cloning from: <span class="text-white" x-text="cloneSource?.name"></span></p>
                            <div>
                                <label class="block text-sm text-slate-400 mb-1">Clone Name</label>
                                <input x-model="cloneForm.name" type="text" required class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                            </div>
                            <div class="grid grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">Memory (MB)</label>
                                    <input x-model.number="cloneForm.memory" type="number" min="512" max="32768" step="256" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                </div>
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">CPUs</label>
                                    <input x-model.number="cloneForm.cpus" type="number" min="1" max="16" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                </div>
                            </div>
                            <p class="text-xs text-slate-500">The clone uses a copy-on-write disk backed by the original. New MAC addresses are generated for all NICs.</p>
                            <div class="flex justify-end space-x-3 pt-4 border-t border-slate-700">
                                <button type="button" @click="showCloneModal = false" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg">Cancel</button>
                                <button type="submit" class="px-4 py-2 bg-cyan-600 hover:bg-cyan-700 rounded-lg">Clone</button>
                            </div>
                        </form>
                    </div>
                </div>

                <!-- Cloud-init Modal -->
                <div x-show="showCloudInitModal" x-transition.opacity class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="showCloudInitModal = false">
                    <div class="bg-slate-800 rounded-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto" @click.stop>
                        <div class="p-6 border-b border-slate-700 flex items-center justify-between">
                            <h2 class="text-xl font-semibold">Create Cloud-init ISO</h2>
                            <button @click="showCloudInitModal = false" class="text-slate-400 hover:text-white"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg></button>
                        </div>
                        <form @submit.prevent="createCloudInit()" class="p-6 space-y-4">
                            <p class="text-sm text-slate-400">Generate an ISO with cloud-init config for automatic Linux VM provisioning. Use it as secondary ISO when creating or editing a VM.</p>
                            <div class="grid grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">Hostname *</label>
                                    <input x-model="cloudInitForm.hostname" type="text" required placeholder="my-server" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                </div>
                                <div>
                                    <label class="block text-sm text-slate-400 mb-1">Username</label>
                                    <input x-model="cloudInitForm.username" type="text" placeholder="user" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                                </div>
                            </div>
                            <div>
                                <label class="block text-sm text-slate-400 mb-1">Password</label>
                                <input x-model="cloudInitForm.password" type="text" placeholder="Leave empty for SSH-only" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                            </div>
                            <div>
                                <label class="block text-sm text-slate-400 mb-1">SSH Authorized Keys (one per line)</label>
                                <textarea x-model="cloudInitForm.ssh_authorized_keys" rows="3" placeholder="ssh-ed25519 AAAA..." class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm font-mono"></textarea>
                            </div>
                            <div>
                                <label class="block text-sm text-slate-400 mb-1">Packages (space or comma separated)</label>
                                <input x-model="cloudInitForm.packages" type="text" placeholder="spice-vdagent qemu-guest-agent" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-primary-500">
                            </div>
                            <div class="border-t border-slate-700 pt-4">
                                <p class="text-sm text-slate-400 mb-3">Network (optional - leave empty for DHCP)</p>
                                <div class="grid grid-cols-3 gap-4">
                                    <div>
                                        <label class="block text-sm text-slate-500 mb-1">Static IP</label>
                                        <input x-model="cloudInitForm.static_ip" type="text" placeholder="192.168.1.100/24" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-primary-500">
                                    </div>
                                    <div>
                                        <label class="block text-sm text-slate-500 mb-1">Gateway</label>
                                        <input x-model="cloudInitForm.gateway" type="text" placeholder="192.168.1.1" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-primary-500">
                                    </div>
                                    <div>
                                        <label class="block text-sm text-slate-500 mb-1">DNS</label>
                                        <input x-model="cloudInitForm.dns" type="text" placeholder="8.8.8.8, 8.8.4.4" class="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-primary-500">
                                    </div>
                                </div>
                            </div>
                            <div class="flex justify-end space-x-3 pt-4 border-t border-slate-700">
                                <button type="button" @click="showCloudInitModal = false" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg">Cancel</button>
                                <button type="submit" class="px-4 py-2 bg-cyan-600 hover:bg-cyan-700 rounded-lg">Create ISO</button>
                            </div>
                        </form>
                    </div>
                </div>
            `;
        }
    };
}
