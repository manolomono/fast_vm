/**
 * Fast VM - Frontend principal
 *
 * Componente Alpine.js que importa modulos de:
 *   js/api.js        - Helper de llamadas API
 *   js/vms.js        - Gestion de VMs (CRUD, clone, cloud-init)
 *   js/volumes.js    - Gestion de volumenes
 *   js/monitoring.js - Monitorizacion y graficos en tiempo real
 *   js/console.js    - Consola SPICE
 *   js/backups.js    - Backup y restauracion
 *   js/users.js      - Gestion de usuarios y autenticacion
 *   js/modals.js     - HTML de modales
 */
import { api } from './js/api.js';
import { vmMethods } from './js/vms.js';
import { volumeMethods } from './js/volumes.js';
import { monitoringMethods } from './js/monitoring.js';
import { consoleMethods } from './js/console.js';
import { backupMethods } from './js/backups.js';
import { userMethods } from './js/users.js';
import { injectModals } from './js/modals.js';

document.addEventListener('alpine:init', () => {
    Alpine.data('vmManager', () => ({
        // ==================== Estado ====================
        currentView: 'vms',
        vms: [],
        volumes: [],
        isos: [],
        bridges: [],
        interfaces: [],
        backups: [],
        users: [],
        currentUser: null,

        // Estado de modales
        showCreateModal: false,
        showEditModal: false,
        showDeleteModal: false,
        showVolumeModal: false,
        showCloneModal: false,
        showRestoreModal: false,
        showCloudInitModal: false,
        showCreateUserModal: false,
        showConsole: false,

        // Formularios
        createForm: {
            name: '', memory: 2048, cpus: 2, disk_size: 20,
            iso_path: '', secondary_iso_path: '',
            cpu_model: 'host', display_type: 'qxl',
            networks: [{ type: 'nat', model: 'virtio', port_forwards: [] }],
            boot_order: ['disk', 'cdrom']
        },
        editTarget: null,
        deleteTarget: null,
        selectedVm: null,
        cloneSource: null,
        cloneForm: { name: '', memory: 2048, cpus: 2 },
        volumeForm: { name: '', size_gb: 10, format: 'qcow2' },
        selectedVolumeToAttach: '',
        createUserForm: { username: '', password: '', is_admin: false },
        passwordForm: { current_password: '', new_password: '', confirm_password: '' },
        cloudInitForm: {
            hostname: '', username: 'user', password: '',
            ssh_authorized_keys: '', packages: 'spice-vdagent qemu-guest-agent',
            static_ip: '', gateway: '', dns: '8.8.8.8, 8.8.4.4'
        },

        // Estado de consola
        consoleUrl: '',
        consoleVm: null,

        // Estado de monitorizacion
        monitoringVmId: null,
        monitoringInterval: null,
        metricsWs: null,
        metricsWsConnected: false,
        vmMetrics: {},
        wsHostHistory: [],
        wsVmHistory: {},
        WS_MAX_POINTS: 60,
        _wsReconnectTimer: null,
        _wsReconnectAttempts: 0,

        // Estado de snapshots
        vmSnapshots: {},
        snapshotForm: { name: '', description: '' },

        // UI
        actionLoading: false,

        // ==================== Computed ====================
        get runningVms() { return this.vms.filter(v => v.status === 'running'); },
        get stoppedVms() { return this.vms.filter(v => v.status !== 'running'); },
        get availableVolumes() { return this.volumes.filter(v => !v.attached_to); },

        // ==================== Inicializacion ====================
        async init() {
            // Inyectar HTML de modales
            const modalsEl = document.getElementById('modals');
            if (modalsEl) injectModals();

            // Cargar datos iniciales
            await Promise.all([
                this.loadVMs(),
                this.loadVolumes(),
                this.loadIsos(),
                this.loadBridges(),
                this.loadBackups(),
                this.loadCurrentUser(),
            ]);

            // Auto-refresh cada 5s
            setInterval(() => this.loadVMs(), 5000);
        },

        // ==================== Carga de datos ====================
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

        async loadCurrentUser() {
            try { this.currentUser = await api('/auth/me'); }
            catch (err) { console.error('Error loading user info:', err); }
        },

        // ==================== Snapshots ====================
        async loadSnapshots(vmId) {
            try {
                this.vmSnapshots[vmId] = await api(`/vms/${vmId}/snapshots`);
            } catch (err) {
                console.error('Error loading snapshots:', err);
                this.vmSnapshots[vmId] = [];
            }
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

        // ==================== Metodos importados ====================
        ...vmMethods,
        ...volumeMethods,
        ...monitoringMethods,
        ...consoleMethods,
        ...backupMethods,
        ...userMethods,
    }));
});
