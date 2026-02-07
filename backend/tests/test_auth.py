"""Tests for authentication endpoints"""
import pytest

pytestmark = pytest.mark.asyncio


async def test_login_success(app_client):
    """Test successful login returns JWT token"""
    response = await app_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(app_client):
    """Test login with wrong password fails"""
    response = await app_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert response.status_code == 401


async def test_login_nonexistent_user(app_client):
    """Test login with nonexistent user fails"""
    response = await app_client.post(
        "/api/auth/login",
        json={"username": "nonexistent", "password": "pass"},
    )
    assert response.status_code == 401


async def test_get_me(app_client, auth_headers):
    """Test getting current user info"""
    response = await app_client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "admin"
    assert data["is_admin"] is True


async def test_get_me_no_auth(app_client):
    """Test getting user info without auth fails"""
    response = await app_client.get("/api/auth/me")
    assert response.status_code == 403


async def test_change_password(app_client, auth_headers):
    """Test changing password"""
    response = await app_client.post(
        "/api/auth/change-password",
        headers=auth_headers,
        json={"current_password": "admin", "new_password": "newpass123"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


async def test_change_password_wrong_current(app_client, auth_headers):
    """Test changing password with wrong current password"""
    response = await app_client.post(
        "/api/auth/change-password",
        headers=auth_headers,
        json={"current_password": "wrong", "new_password": "newpass123"},
    )
    assert response.status_code == 400


async def test_list_users(app_client, auth_headers):
    """Test listing users (admin only)"""
    response = await app_client.get("/api/auth/users", headers=auth_headers)
    assert response.status_code == 200
    users = response.json()
    assert len(users) >= 1
    assert any(u["username"] == "admin" for u in users)


async def test_create_user(app_client, auth_headers):
    """Test creating a new user"""
    response = await app_client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": "testuser", "password": "testpass", "is_admin": False},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


async def test_create_duplicate_user(app_client, auth_headers):
    """Test creating a duplicate user fails"""
    response = await app_client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": "admin", "password": "pass", "is_admin": False},
    )
    assert response.status_code == 400


async def test_delete_user(app_client, auth_headers):
    """Test deleting a user"""
    await app_client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": "todelete", "password": "pass", "is_admin": False},
    )
    response = await app_client.delete(
        "/api/auth/users/todelete", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


async def test_delete_self_fails(app_client, auth_headers):
    """Test that admin cannot delete themselves"""
    response = await app_client.delete(
        "/api/auth/users/admin", headers=auth_headers
    )
    assert response.status_code == 400
