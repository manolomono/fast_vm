// Metodos de monitorizacion y graficos
import { api } from './api.js';

// Instancias de Chart.js fuera de Alpine para evitar wrapping de Proxy
export const _chartInstances = {};

export const monitoringMethods = {
    openVmMonitoring(vm) {
        this.monitoringVmId = vm.id;
        this.destroyAllCharts();
        this.currentView = 'monitoring';
        this.loadMonitoringCharts();
    },

    openAllMonitoring() {
        this.monitoringVmId = null;
        this.destroyAllCharts();
        this.currentView = 'monitoring';
        this.loadMonitoringCharts();
    },

    destroyAllCharts() {
        for (const [id, chart] of Object.entries(_chartInstances)) {
            try { chart.destroy(); } catch(e) {}
            delete _chartInstances[id];
        }
    },

    stopMonitoring() {
        if (this._wsReconnectTimer) {
            clearTimeout(this._wsReconnectTimer);
            this._wsReconnectTimer = null;
        }
        this._wsReconnectAttempts = 0;
        if (this.monitoringInterval) {
            clearInterval(this.monitoringInterval);
            this.monitoringInterval = null;
        }
        if (this.metricsWs) {
            this.metricsWs.close();
            this.metricsWs = null;
            this.metricsWsConnected = false;
        }
        this.destroyAllCharts();
    },

    async loadMonitoringCharts() {
        await this.$nextTick();
        await new Promise(r => setTimeout(r, 250));
        await this._fetchAndRenderCharts();
        this._connectMetricsWs();
    },

    _connectMetricsWs() {
        if (this.metricsWs) { this.metricsWs.close(); this.metricsWs = null; }
        if (this.monitoringInterval) { clearInterval(this.monitoringInterval); this.monitoringInterval = null; }

        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const token = localStorage.getItem('token');
        const wsUrl = `${proto}//${location.host}/ws/metrics${token ? '?token=' + encodeURIComponent(token) : ''}`;

        try {
            this.metricsWs = new WebSocket(wsUrl);

            this.metricsWs.onopen = () => {
                console.log('Metrics WebSocket connected');
                this.metricsWsConnected = true;
                this._wsReconnectAttempts = 0;
            };

            this.metricsWs.onmessage = (event) => {
                if (this.currentView !== 'monitoring') { this.stopMonitoring(); return; }
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === 'metrics') this._handleWsMetrics(data);
                } catch (err) { console.error('WS parse error:', err); }
            };

            this.metricsWs.onclose = (ev) => {
                this.metricsWsConnected = false;
                if (ev.code === 4401) {
                    localStorage.removeItem('token');
                    window.location.href = '/login.html';
                    return;
                }
                if (this.currentView === 'monitoring') {
                    this._wsReconnectAttempts = (this._wsReconnectAttempts || 0) + 1;
                    if (this._wsReconnectAttempts <= 3) {
                        const delay = Math.min(1000 * Math.pow(2, this._wsReconnectAttempts - 1), 8000);
                        this._wsReconnectTimer = setTimeout(() => this._connectMetricsWs(), delay);
                    } else {
                        this._wsReconnectAttempts = 0;
                        this._startPollingFallback();
                    }
                }
            };

            this.metricsWs.onerror = () => { this.metricsWsConnected = false; };
        } catch (err) {
            console.error('WebSocket error:', err);
            this._startPollingFallback();
        }
    },

    _startPollingFallback() {
        if (this.monitoringInterval) return;
        this.monitoringInterval = setInterval(async () => {
            if (this.currentView !== 'monitoring') { this.stopMonitoring(); return; }
            await this._fetchAndRenderCharts();
        }, 5000);
    },

    _handleWsMetrics(data) {
        if (data.host) {
            this.wsHostHistory.push(data.host);
            if (this.wsHostHistory.length > this.WS_MAX_POINTS) this.wsHostHistory.shift();
        }
        for (const [vmId, point] of Object.entries(data.vms || {})) {
            if (!this.wsVmHistory[vmId]) this.wsVmHistory[vmId] = [];
            this.wsVmHistory[vmId].push(point);
            if (this.wsVmHistory[vmId].length > this.WS_MAX_POINTS) this.wsVmHistory[vmId].shift();
        }
        for (const vmId of Object.keys(this.wsVmHistory)) {
            if (!data.vms || !(vmId in data.vms)) delete this.wsVmHistory[vmId];
        }
        for (const [vmId, point] of Object.entries(data.vms || {})) {
            this.vmMetrics[vmId] = {
                cpu_percent: point.cpu, memory_used_mb: point.mem_mb,
                memory_percent: point.mem_pct, io_read_mb: point.io_r, io_write_mb: point.io_w,
            };
        }

        if (!this.monitoringVmId) {
            this.renderHostCharts(this.wsHostHistory);
            this.renderVmCharts(this.wsVmHistory);
        } else {
            const vmData = {};
            if (this.wsVmHistory[this.monitoringVmId]) vmData[this.monitoringVmId] = this.wsVmHistory[this.monitoringVmId];
            this.renderVmCharts(vmData);
        }
    },

    async _fetchAndRenderCharts() {
        if (this.currentView !== 'monitoring') return;
        try {
            const data = await api('/metrics/history');
            if (data.host) this.wsHostHistory = [...data.host];
            if (data.vms) {
                this.wsVmHistory = {};
                for (const [vmId, points] of Object.entries(data.vms)) this.wsVmHistory[vmId] = [...points];
            }
            if (!this.monitoringVmId) {
                this.renderHostCharts(data.host);
                this.renderVmCharts(data.vms);
            } else {
                const vmData = {};
                if (data.vms[this.monitoringVmId]) vmData[this.monitoringVmId] = data.vms[this.monitoringVmId];
                this.renderVmCharts(vmData);
            }
        } catch (err) { console.error('Error loading monitoring data:', err); }
    },

    chartDefaults() {
        return {
            responsive: true, maintainAspectRatio: false,
            animation: { duration: 300 },
            scales: {
                x: { display: true, ticks: { maxTicksLimit: 8, color: '#64748b', font: { size: 10 } }, grid: { color: '#334155' } },
                y: { display: true, beginAtZero: true, ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: '#334155' } }
            },
            plugins: { legend: { display: false }, title: { display: false }, subtitle: { display: false }, tooltip: { enabled: true } }
        };
    },

    _rawCopy(obj) {
        try { return JSON.parse(JSON.stringify(obj)); } catch { return obj; }
    },

    renderChart(canvasId, labels, datasets, opts = {}) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !canvas.getContext) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        if (!canvas.offsetParent && !_chartInstances[canvasId]) {
            setTimeout(() => this.renderChart(canvasId, labels, datasets, opts), 200);
            return;
        }

        const rawLabels = this._rawCopy(labels);
        const rawDatasets = this._rawCopy(datasets);

        if (_chartInstances[canvasId]) {
            const chart = _chartInstances[canvasId];
            if (!chart.canvas || !chart.canvas.isConnected) {
                chart.destroy();
                delete _chartInstances[canvasId];
            } else {
                chart.data.labels = rawLabels;
                rawDatasets.forEach((ds, i) => {
                    if (chart.data.datasets[i]) chart.data.datasets[i].data = ds.data;
                    else chart.data.datasets[i] = ds;
                });
                chart.data.datasets.length = rawDatasets.length;
                chart.update('none');
                return;
            }
        }

        const defaults = this.chartDefaults();
        if (opts.yMax) defaults.scales.y.max = opts.yMax;
        if (opts.legend) defaults.plugins.legend = { display: true, labels: { color: '#94a3b8', boxWidth: 12, font: { size: 11 } } };

        try {
            _chartInstances[canvasId] = new Chart(ctx, {
                type: 'line',
                data: { labels: rawLabels, datasets: rawDatasets },
                options: defaults
            });
        } catch (err) { console.warn('Chart creation failed for', canvasId, err); }
    },

    formatTime(iso) {
        if (!iso) return '';
        const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    },

    renderHostCharts(hostData) {
        if (!hostData || hostData.length === 0) return;
        const labels = hostData.map(p => this.formatTime(p.t));
        this.renderChart('chartHostCpu', labels, [{
            data: hostData.map(p => p.cpu), borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.1)',
            fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2
        }], { yMax: 100 });
        this.renderChart('chartHostMem', labels, [{
            data: hostData.map(p => p.mem), borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)',
            fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2
        }], { yMax: 100 });
    },

    renderVmCharts(vmsData) {
        if (!vmsData) return;
        for (const [vmId, points] of Object.entries(vmsData)) {
            if (!points || points.length === 0) continue;
            const labels = points.map(p => this.formatTime(p.t));
            this.renderChart('chartVmCpu_' + vmId, labels, [{
                data: points.map(p => p.cpu), borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.1)',
                fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2
            }]);
            this.renderChart('chartVmMem_' + vmId, labels, [{
                data: points.map(p => p.mem_mb), borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)',
                fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2
            }]);
            this.renderChart('chartVmIo_' + vmId, labels, [
                { label: 'Read', data: points.map(p => p.io_r), borderColor: '#06b6d4', backgroundColor: 'rgba(6,182,212,0.1)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
                { label: 'Write', data: points.map(p => p.io_w), borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.1)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 }
            ], { legend: true });
        }
    },
};
