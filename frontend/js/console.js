// Metodos de consola VM (SPICE)
import { api } from './api.js';

export const consoleMethods = {
    async openConsole(vm) {
        try {
            await api(`/vms/${vm.id}/spice`);
            const token = localStorage.getItem('token');
            this.consoleUrl = `/spice/spice_auto.html?vm_id=${vm.id}&token=${encodeURIComponent(token)}`;
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
        if (frame.requestFullscreen) frame.requestFullscreen();
    },
};
