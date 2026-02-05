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

        // Modals
        showCreateModal: false,
        showEditModal: false,
        showVolumeModal: false,
        showDeleteModal: false,
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
                setInterval(() => this.loadVMs(), 10000);
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
            `;
        }
    };
}
