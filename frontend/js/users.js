// Metodos de gestion de usuarios
import { api } from './api.js';

export const userMethods = {
    async loadUsers() {
        try { this.users = await api('/auth/users'); }
        catch (err) { console.error('Error loading users:', err); }
    },

    async createUser() {
        try {
            await api('/auth/users', { method: 'POST', body: JSON.stringify(this.createUserForm) });
            this.showToast('User created successfully', 'success');
            this.showCreateUserModal = false;
            this.createUserForm = { username: '', password: '', is_admin: false };
            await this.loadUsers();
        } catch (err) {
            this.showToast(err.message, 'error');
        }
    },

    deleteUserConfirm(u) {
        if (!confirm(`Delete user "${u.username}"?`)) return;
        this.deleteUser(u.username);
    },

    async deleteUser(username) {
        try {
            await api(`/auth/users/${username}`, { method: 'DELETE' });
            this.showToast('User deleted', 'success');
            await this.loadUsers();
        } catch (err) {
            this.showToast(err.message, 'error');
        }
    },

    async changePassword() {
        if (this.passwordForm.new_password !== this.passwordForm.confirm_password) {
            this.showToast('Passwords do not match', 'error');
            return;
        }
        try {
            await api('/auth/change-password', {
                method: 'POST',
                body: JSON.stringify({
                    current_password: this.passwordForm.current_password,
                    new_password: this.passwordForm.new_password
                })
            });
            this.showToast('Password changed successfully', 'success');
            this.passwordForm = { current_password: '', new_password: '', confirm_password: '' };
        } catch (err) {
            this.showToast(err.message, 'error');
        }
    },

    logout() {
        localStorage.removeItem('token');
        window.location.href = '/login.html';
    },
};
