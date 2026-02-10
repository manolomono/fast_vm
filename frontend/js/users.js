// Metodos de gestion de usuarios
window.FastVM = window.FastVM || {};
window.FastVM.userMethods = {
    async loadUsers() {
        try { this.users = await FastVM.api('/auth/users'); }
        catch (err) { console.error('Error loading users:', err); }
    },

    async createUser() {
        try {
            await FastVM.api('/auth/users', { method: 'POST', body: JSON.stringify(this.createUserForm) });
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
            await FastVM.api(`/auth/users/${username}`, { method: 'DELETE' });
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
            await FastVM.api('/auth/change-password', {
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
