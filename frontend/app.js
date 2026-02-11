/**
 * Fast VM - Frontend principal
 *
 * Componente Alpine.js (funcion global dashboard()).
 * Los metodos se importan de modulos js/*.js via window.FastVM namespace.
 */

// Los modulos js/*.js se cargan antes via <script> tags.
// Accedemos a ellos via window.FastVM.

function dashboard() {
    const { api, vmMethods, volumeMethods, monitoringMethods,
            consoleMethods, backupMethods, userMethods, injectModals } = window.FastVM;

    return {
        // ==================== Estado ====================
        ready: false,
        user: null,
        vms: [],
        volumes: [],
        isos: [],
        bridges: [],
        interfaces: [],

        // UI - restaurar desde URL hash
        currentView: (['dashboard','volumes','users','monitoring','audit'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'dashboard'),
        selectedVm: null,
        showConsole: false,
        consoleVm: null,
        consoleUrl: '',

        // Busqueda y filtro de VMs
        vmSearchQuery: '',
        vmStatusFilter: 'all',

        // Audit Logs
        auditLogs: [],
        auditTotal: 0,
        auditPage: 0,

        // Backups
        backups: [],
        showRestoreModal: false,

        // Metricas
        vmMetrics: {},
        hostMetrics: { cpu_percent: 0, cpu_count: 0, memory_used_gb: 0, memory_total_gb: 0, memory_percent: 0, disk_used_gb: 0, disk_total_gb: 0, disk_percent: 0 },

        // Usuarios
        users: [],
        passwordForm: { current_password: '', new_password: '', confirm_password: '' },
        createUserForm: { username: '', password: '', is_admin: false },

        // Clone & Cloud-init
        cloneForm: { name: '', memory: null, cpus: null },
        cloneSource: null,
        cloudInitForm: {
            hostname: '', username: 'user', password: '',
            ssh_authorized_keys: '', packages: 'spice-vdagent qemu-guest-agent',
            static_ip: '', gateway: '', dns: '8.8.8.8, 8.8.4.4'
        },

        // Loading
        actionLoading: false,

        // Modales
        showCreateModal: false,
        showEditModal: false,
        showVolumeModal: false,
        showDeleteModal: false,
        showCreateUserModal: false,
        showCloneModal: false,
        showCloudInitModal: false,
        deleteTarget: null,
        editTarget: { memory: 0, cpus: 0, iso_path: '', secondary_iso_path: '', networks: [], volumes: [], boot_order: ['disk', 'cdrom'] },
        selectedVolumeToAttach: '',

        // Formulario de creacion
        createForm: {
            name: '', memory: 2048, cpus: 2, disk_size: 20,
            iso_path: '', secondary_iso_path: '',
            cpu_model: 'host', display_type: 'qxl', os_type: 'linux',
            networks: [{ type: 'nat', model: 'virtio', port_forwards: [] }],
            boot_order: ['disk', 'cdrom']
        },

        volumeForm: { name: '', size_gb: 10, format: 'qcow2' },

        // Monitorizacion
        monitoringInterval: null,
        monitoringVmId: null,
        metricsWs: null,
        metricsWsConnected: false,
        wsHostHistory: [],
        wsVmHistory: {},
        WS_MAX_POINTS: 120,
        _wsReconnectTimer: null,
        _wsReconnectAttempts: 0,

        // Snapshots
        vmSnapshots: {},
        snapshotForm: { name: '', description: '' },

        // ==================== Computed ====================
        get runningVMs() { return this.vms.filter(v => v.status === 'running').length; },
        get stoppedVMs() { return this.vms.filter(v => v.status !== 'running').length; },
        get filteredVMs() {
            return this.vms.filter(vm => {
                const matchesSearch = !this.vmSearchQuery || vm.name.toLowerCase().includes(this.vmSearchQuery.toLowerCase());
                const matchesStatus = this.vmStatusFilter === 'all' || vm.status === this.vmStatusFilter;
                return matchesSearch && matchesStatus;
            });
        },
        get availableVolumes() {
            if (!this.editTarget) return [];
            const attachedToThisVm = this.editTarget.volumes || [];
            return this.volumes.filter(v => !v.attached_to && !attachedToThisVm.includes(v.id));
        },

        // ==================== Inicializacion ====================
        async init() {
            const token = localStorage.getItem('token');
            if (!token) { window.location.href = '/login.html'; return; }

            try {
                this.user = await api('/auth/me');
                await this.loadData();
                this.ready = true;
                injectModals();

                // Auto-refresh cada 10s
                setInterval(() => { this.loadVMs(); this.loadMetrics(); }, 10000);
                this.loadMetrics();
                if (this.user?.is_admin) this.loadUsers();

                // Sincronizar currentView <-> URL hash
                this.$watch('currentView', (val) => {
                    const hash = val === 'dashboard' ? '' : '#' + val;
                    if (location.hash !== '#' + val) history.replaceState(null, '', hash || location.pathname);
                });
                window.addEventListener('hashchange', () => {
                    const view = location.hash.slice(1);
                    if (['dashboard','volumes','users','monitoring','audit'].includes(view)) {
                        this.currentView = view;
                    } else if (!location.hash) {
                        this.currentView = 'dashboard';
                    }
                });

                if (this.currentView === 'monitoring') {
                    this.$nextTick(() => this.loadMonitoringCharts());
                }
                if (this.currentView === 'audit' && this.user?.is_admin) {
                    this.loadAuditLogs();
                }
            } catch (err) {
                console.error('Init error:', err);
                localStorage.removeItem('token');
                window.location.href = '/login.html';
            }
        },

        // ==================== Carga de datos ====================
        async loadData() {
            await Promise.all([
                this.loadVMs(), this.loadVolumes(), this.loadIsos(),
                this.loadBridges(), this.loadBackups()
            ]);
        },

        async loadIsos() {
            try { this.isos = await api('/isos'); }
            catch (err) { console.error('Error loading ISOs:', err); }
        },

        async loadBridges() {
            try {
                const [bridgeData, ifaceData] = await Promise.all([
                    api('/bridges'), api('/interfaces')
                ]);
                this.bridges = bridgeData.map(b => b.name);
                this.interfaces = ifaceData.map(i => i.name);
            } catch (err) { console.error('Error loading network config:', err); }
        },

        async loadMetrics() {
            if (this.metricsWsConnected) return;
            try { this.hostMetrics = await api('/system/metrics'); }
            catch (err) { console.error('Error loading host metrics:', err); }

            const running = this.vms.filter(v => v.status === 'running');
            for (const vm of running) {
                try { this.vmMetrics[vm.id] = await api(`/vms/${vm.id}/metrics`); }
                catch (err) { /* VM may have just stopped */ }
            }
        },

        async loadAuditLogs(page = 0) {
            try {
                this.auditPage = page;
                const offset = page * 50;
                const data = await api(`/audit-logs?limit=50&offset=${offset}`);
                this.auditLogs = data.logs;
                this.auditTotal = data.total;
            } catch (err) { console.error('Error loading audit logs:', err); }
        },

        // ==================== Snapshots ====================
        async loadSnapshots(vmId) {
            try { this.vmSnapshots[vmId] = await api(`/vms/${vmId}/snapshots`); }
            catch (err) { console.error('Error loading snapshots:', err); this.vmSnapshots[vmId] = []; }
        },

        async createSnapshot(vmId) {
            if (!this.snapshotForm.name) return;
            try {
                await api(`/vms/${vmId}/snapshots`, { method: 'POST', body: JSON.stringify(this.snapshotForm) });
                this.showToast('Snapshot created', 'success');
                this.snapshotForm = { name: '', description: '' };
                await this.loadSnapshots(vmId);
            } catch (err) { this.showToast(err.message, 'error'); }
        },

        async restoreSnapshot(vmId, snapId) {
            if (!confirm('Restore this snapshot? The VM must be stopped.')) return;
            try {
                await api(`/vms/${vmId}/snapshots/${snapId}/restore`, { method: 'POST' });
                this.showToast('Snapshot restored', 'success');
            } catch (err) { this.showToast(err.message, 'error'); }
        },

        async deleteSnapshot(vmId, snapId) {
            if (!confirm('Delete this snapshot?')) return;
            try {
                await api(`/vms/${vmId}/snapshots/${snapId}`, { method: 'DELETE' });
                this.showToast('Snapshot deleted', 'success');
                await this.loadSnapshots(vmId);
            } catch (err) { this.showToast(err.message, 'error'); }
        },

        // ==================== Logs ====================
        async getVmLogs(vmId) {
            try {
                const logs = await api(`/vms/${vmId}/logs`);
                alert(`QEMU Log:\n${logs.qemu_log || '(empty)'}\n\nSerial Log:\n${logs.serial_log || '(empty)'}`);
            } catch (err) { this.showToast(err.message, 'error'); }
        },

        // ==================== Toast ====================
        showToast(message, type = 'info') {
            const toast = document.getElementById('toast');
            if (!toast) return;
            toast.textContent = message;
            toast.className = `fixed bottom-4 right-4 px-6 py-3 rounded-lg shadow-lg z-50 toast ${type} show`;
            setTimeout(() => {
                toast.className = 'fixed bottom-4 right-4 px-6 py-3 rounded-lg shadow-lg z-50 toast translate-y-20 opacity-0 transition-all duration-300';
            }, 4000);
        },

        // ==================== Formateo ====================
        formatMemory(mb) {
            return mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb + ' MB';
        },

        // ==================== Metodos importados de modulos ====================
        ...vmMethods,
        ...volumeMethods,
        ...monitoringMethods,
        ...consoleMethods,
        ...backupMethods,
        ...userMethods,
    };
}
