// Metodos de gestion de volumenes
import { api } from './api.js';

export const volumeMethods = {
    async loadVolumes() {
        try { this.volumes = await api('/volumes'); }
        catch (err) { console.error('Error loading volumes:', err); }
    },

    async createVolume() {
        try {
            await api('/volumes', { method: 'POST', body: JSON.stringify(this.volumeForm) });
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

    getVolumeName(volId) {
        const vol = this.volumes.find(v => v.id === volId);
        return vol ? `${vol.name} (${vol.size_gb}GB)` : volId;
    },

    async attachVolume() {
        if (!this.selectedVolumeToAttach || !this.editTarget) return;
        try {
            await api(`/vms/${this.editTarget.id}/volumes/${this.selectedVolumeToAttach}`, { method: 'POST' });
            this.showToast('Volume attached', 'success');
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
            this.editTarget.volumes = this.editTarget.volumes.filter(v => v !== volId);
            await this.loadVolumes();
            await this.loadVMs();
        } catch (err) {
            this.showToast(err.message, 'error');
        }
    },
};
