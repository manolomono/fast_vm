// Metodos de backup y restauracion
window.FastVM = window.FastVM || {};
window.FastVM.backupMethods = {
    async backupVM(vm) {
        if (vm.status === 'running') {
            this.showToast('Stop the VM first to create a backup', 'error');
            return;
        }
        try {
            const result = await FastVM.api(`/vms/${vm.id}/backup`, { method: 'POST' });
            this.showToast(`Backup created: ${result.backup_name}`, 'success');
            await this.loadBackups();
        } catch (err) {
            this.showToast(err.message, 'error');
        }
    },

    async downloadBackup(backup) {
        const token = localStorage.getItem('token');
        try {
            const response = await fetch(`/api/vms/_/backup/download?backup_name=${encodeURIComponent(backup.name)}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!response.ok) throw new Error('Download failed');
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = backup.name;
            a.click();
            window.URL.revokeObjectURL(url);
        } catch (err) {
            this.showToast(err.message, 'error');
        }
    },

    async loadBackups() {
        try { this.backups = await FastVM.api('/backups'); }
        catch (err) { console.error('Error loading backups:', err); }
    },

    async restoreFromFile() {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.tar.gz';
        input.onchange = async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            try {
                const formData = new FormData();
                formData.append('file', file);
                const token = localStorage.getItem('token');
                const response = await fetch('/api/vms/restore', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}` },
                    body: formData
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Restore failed');
                }
                this.showToast('VM restored successfully', 'success');
                this.showRestoreModal = false;
                await this.loadVMs();
            } catch (err) {
                this.showToast(err.message, 'error');
            }
        };
        input.click();
    },

    async restoreFromBackup(backup) {
        try {
            const token = localStorage.getItem('token');
            const response = await fetch(`/api/vms/_/backup/download?backup_name=${encodeURIComponent(backup.name)}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!response.ok) throw new Error('Failed to fetch backup');
            const blob = await response.blob();
            const formData = new FormData();
            formData.append('file', new File([blob], backup.name, { type: 'application/gzip' }));

            const restoreResponse = await fetch('/api/vms/restore', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
                body: formData
            });
            if (!restoreResponse.ok) {
                const data = await restoreResponse.json().catch(() => ({}));
                throw new Error(data.detail || 'Restore failed');
            }
            this.showToast('VM restored successfully', 'success');
            this.showRestoreModal = false;
            await this.loadVMs();
        } catch (err) {
            this.showToast(err.message, 'error');
        }
    },
};
