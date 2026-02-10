// API helper con autenticacion JWT
window.FastVM = window.FastVM || {};
window.FastVM.api = async function api(endpoint, options = {}) {
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
        if (response.status === 422 && Array.isArray(data.detail)) {
            const msgs = data.detail.map(e => e.msg || e.message || JSON.stringify(e)).join('; ');
            throw new Error(msgs);
        }
        throw new Error(data.detail || `Error ${response.status}`);
    }

    return response.json();
};
