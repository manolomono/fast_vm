// Metodos de gestion de VMs
window.FastVM = window.FastVM || {};
window.FastVM.vmMethods = {
    async loadVMs() {
        try { this.vms = await FastVM.api('/vms'); }
        catch (err) { console.error('Error loading VMs:', err); }
    },

    async startVM(id) {
        if (this.actionLoading) return;
        this.actionLoading = true;
        try {
            await FastVM.api(`/vms/${id}/start`, { method: 'POST' });
            this.showToast('VM started successfully', 'success');
            await this.loadVMs();
        } catch (err) {
            this.showToast(err.message, 'error');
        } finally { this.actionLoading = false; }
    },

    async stopVM(id) {
        if (this.actionLoading) return;
        this.actionLoading = true;
        try {
            await FastVM.api(`/vms/${id}/stop`, { method: 'POST' });
            this.showToast('VM stopped successfully', 'success');
            await this.loadVMs();
            if (this.consoleVm?.id === id) this.closeConsole();
        } catch (err) {
            this.showToast(err.message, 'error');
        } finally { this.actionLoading = false; }
    },

    async createVM() {
        if (this.actionLoading) return;
        this.actionLoading = true;
        try {
            const data = { ...this.createForm };
            if (!data.iso_path) delete data.iso_path;
            if (!data.secondary_iso_path) delete data.secondary_iso_path;
            await FastVM.api('/vms', { method: 'POST', body: JSON.stringify(data) });
            this.showToast('VM created successfully', 'success');
            this.showCreateModal = false;
            this.resetCreateForm();
            await this.loadVMs();
        } catch (err) {
            this.showToast(err.message, 'error');
        } finally { this.actionLoading = false; }
    },

    async updateVM() {
        if (!this.editTarget || this.actionLoading) return;
        this.actionLoading = true;
        try {
            const data = {
                memory: this.editTarget.memory,
                cpus: this.editTarget.cpus,
                iso_path: this.editTarget.iso_path || null,
                secondary_iso_path: this.editTarget.secondary_iso_path || null,
                cpu_model: this.editTarget.cpu_model,
                display_type: this.editTarget.display_type,
                os_type: this.editTarget.os_type || 'linux',
                networks: this.editTarget.networks,
                boot_order: this.editTarget.boot_order
            };
            await FastVM.api(`/vms/${this.editTarget.id}`, { method: 'PUT', body: JSON.stringify(data) });
            this.showToast('VM updated successfully', 'success');
            this.showEditModal = false;
            this.editTarget = null;
            await this.loadVMs();
        } catch (err) {
            this.showToast(err.message, 'error');
        } finally { this.actionLoading = false; }
    },

    async deleteVM() {
        if (!this.deleteTarget || this.actionLoading) return;
        this.actionLoading = true;
        try {
            await FastVM.api(`/vms/${this.deleteTarget.id}`, { method: 'DELETE' });
            this.showToast('VM deleted successfully', 'success');
            this.showDeleteModal = false;
            this.deleteTarget = null;
            await this.loadVMs();
        } catch (err) {
            this.showToast(err.message, 'error');
        } finally { this.actionLoading = false; }
    },

    // Clone
    openCloneModal(vm) {
        this.cloneSource = vm;
        this.cloneForm = { name: vm.name + ' (clone)', memory: vm.memory, cpus: vm.cpus };
        this.showCloneModal = true;
    },

    async cloneVM() {
        if (!this.cloneSource || this.actionLoading) return;
        this.actionLoading = true;
        try {
            const data = { name: this.cloneForm.name };
            if (this.cloneForm.memory) data.memory = this.cloneForm.memory;
            if (this.cloneForm.cpus) data.cpus = this.cloneForm.cpus;
            await FastVM.api(`/vms/${this.cloneSource.id}/clone`, { method: 'POST', body: JSON.stringify(data) });
            this.showToast('VM cloned successfully', 'success');
            this.showCloneModal = false;
            this.cloneSource = null;
            await this.loadVMs();
        } catch (err) {
            this.showToast(err.message, 'error');
        } finally { this.actionLoading = false; }
    },

    // Cloud-init
    async createCloudInit() {
        try {
            const data = {
                hostname: this.cloudInitForm.hostname,
                username: this.cloudInitForm.username,
                packages: this.cloudInitForm.packages ? this.cloudInitForm.packages.split(/[\s,]+/).filter(Boolean) : [],
                dns: this.cloudInitForm.dns ? this.cloudInitForm.dns.split(/[\s,]+/).filter(Boolean) : ['8.8.8.8'],
            };
            if (this.cloudInitForm.password) data.password = this.cloudInitForm.password;
            if (this.cloudInitForm.ssh_authorized_keys) {
                data.ssh_authorized_keys = this.cloudInitForm.ssh_authorized_keys.split('\n').filter(Boolean);
            }
            if (this.cloudInitForm.static_ip) data.static_ip = this.cloudInitForm.static_ip;
            if (this.cloudInitForm.gateway) data.gateway = this.cloudInitForm.gateway;

            await FastVM.api('/cloudinit', { method: 'POST', body: JSON.stringify(data) });
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

    // UI helpers para VMs
    selectVm(vm) {
        this.selectedVm = vm;
        this.currentView = 'dashboard';
        this.$nextTick(() => {
            const card = document.getElementById('vm-card-' + vm.id);
            if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
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
            name: '', memory: 2048, cpus: 2, disk_size: 20,
            iso_path: '', secondary_iso_path: '',
            cpu_model: 'host', display_type: 'qxl', os_type: 'linux',
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
};
