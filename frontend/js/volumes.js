// Metodos de gestion de volumenes
window.FastVM = window.FastVM || {};
window.FastVM.volumeMethods = {
    async loadVolumes() {
        try { this.volumes = await FastVM.api('/volumes'); }
        catch (err) { console.error('Error loading volumes:', err); }
    },

    async createVolume() {
        if (this.actionLoading) return;
        this.actionLoading = true;
        try {
            await FastVM.api('/volumes', { method: 'POST', body: JSON.stringify(this.volumeForm) });
            this.showToast('Volume created successfully', 'success');
            this.showVolumeModal = false;
            this.volumeForm = { name: '', size_gb: 10, format: 'qcow2' };
            await this.loadVolumes();
        } catch (err) {
            this.showToast(err.message, 'error');
        } finally { this.actionLoading = false; }
    },

    async deleteVolume(vol) {
        if (!confirm(`Delete volume "${vol.name}"?`)) return;
        if (this.actionLoading) return;
        this.actionLoading = true;
        try {
            await FastVM.api(`/volumes/${vol.id}`, { method: 'DELETE' });
            this.showToast('Volume deleted', 'success');
            await this.loadVolumes();
        } catch (err) {
            this.showToast(err.message, 'error');
        } finally { this.actionLoading = false; }
    },

    getVolumeName(volId) {
        const vol = this.volumes.find(v => v.id === volId);
        return vol ? `${vol.name} (${vol.size_gb}GB)` : volId;
    },

    async attachVolume() {
        if (!this.selectedVolumeToAttach || !this.editTarget) return;
        if (this.actionLoading) return;
        this.actionLoading = true;
        try {
            await FastVM.api(`/vms/${this.editTarget.id}/volumes/${this.selectedVolumeToAttach}`, { method: 'POST' });
            this.showToast('Volume attached', 'success');
            if (!this.editTarget.volumes) this.editTarget.volumes = [];
            this.editTarget.volumes.push(this.selectedVolumeToAttach);
            this.selectedVolumeToAttach = '';
            await this.loadVolumes();
            await this.loadVMs();
        } catch (err) {
            this.showToast(err.message, 'error');
        } finally { this.actionLoading = false; }
    },

    async promoteVolume(volId) {
        if (!this.editTarget) return;
        const volName = this.getVolumeName(volId);
        if (!confirm(`Promote "${volName}" to primary disk? This will replace the current disk.qcow2.`)) return;
        if (this.actionLoading) return;
        this.actionLoading = true;
        try {
            const res = await FastVM.api(`/vms/${this.editTarget.id}/volumes/${volId}/promote`, { method: 'POST' });
            this.showToast('Volume promoted to primary disk', 'success');
            this.editTarget.volumes = this.editTarget.volumes.filter(v => v !== volId);
            if (res.vm && res.vm.disk_size) this.editTarget.disk_size = res.vm.disk_size;
            await this.loadVolumes();
            await this.loadVMs();
        } catch (err) {
            this.showToast(err.message, 'error');
        } finally { this.actionLoading = false; }
    },

    async detachVolume(volId) {
        if (!this.editTarget) return;
        if (this.actionLoading) return;
        this.actionLoading = true;
        try {
            await FastVM.api(`/vms/${this.editTarget.id}/volumes/${volId}`, { method: 'DELETE' });
            this.showToast('Volume detached', 'success');
            this.editTarget.volumes = this.editTarget.volumes.filter(v => v !== volId);
            await this.loadVolumes();
            await this.loadVMs();
        } catch (err) {
            this.showToast(err.message, 'error');
        } finally { this.actionLoading = false; }
    },
};
