"""Tests for VNC and SPICE console connection endpoints"""
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

pytestmark = pytest.mark.asyncio


def _create_running_vm(vm_manager, vm_id="test-vm-123"):
    """Helper: insert a fake running VM with VNC and SPICE ports"""
    vm_manager.vms[vm_id] = {
        "id": vm_id,
        "name": "TestVM",
        "status": "running",
        "memory": 2048,
        "cpus": 2,
        "disk_size": 20,
        "disk_path": "/tmp/fake.qcow2",
        "vnc_port": 5900,
        "spice_port": 5930,
        "pid": 99999,
        "ws_port": None,
        "ws_proxy_pid": None,
        "spice_ws_port": None,
        "spice_proxy_pid": None,
        "networks": [],
        "boot_order": ["disk"],
    }
    return vm_id


# ==================== SPICE Console Tests ====================


async def test_spice_connect_vm_not_found(app_client, auth_headers):
    """SPICE connection should 400 if VM doesn't exist"""
    response = await app_client.get("/api/vms/nonexistent/spice", headers=auth_headers)
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


async def test_spice_connect_vm_stopped(app_client, auth_headers):
    """SPICE connection should 400 if VM is stopped"""
    from app.main import vm_manager

    vm_id = _create_running_vm(vm_manager)
    vm_manager.vms[vm_id]["status"] = "stopped"

    response = await app_client.get(f"/api/vms/{vm_id}/spice", headers=auth_headers)
    assert response.status_code == 400
    assert "not running" in response.json()["detail"].lower()

    # Cleanup
    del vm_manager.vms[vm_id]


async def test_spice_connect_success(app_client, auth_headers):
    """SPICE connection should return connection info via built-in proxy"""
    from app.main import vm_manager

    vm_id = _create_running_vm(vm_manager)

    # Mock _update_vm_status to not change the status
    # Mock _is_port_in_use to simulate SPICE port is listening
    with patch.object(vm_manager, '_update_vm_status'):
        with patch.object(vm_manager, '_is_port_in_use', return_value=True):
            response = await app_client.get(f"/api/vms/{vm_id}/spice", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["spice_port"] == 5930
    assert data["status"] == "ready"
    assert "ws_url" in data
    assert f"/ws/spice/{vm_id}" in data["ws_url"]

    # Cleanup
    del vm_manager.vms[vm_id]


async def test_spice_connect_port_not_ready(app_client, auth_headers):
    """SPICE connection should 400 if SPICE port is not listening"""
    from app.main import vm_manager

    vm_id = _create_running_vm(vm_manager)

    with patch.object(vm_manager, '_update_vm_status'):
        with patch.object(vm_manager, '_is_port_in_use', return_value=False):
            response = await app_client.get(f"/api/vms/{vm_id}/spice", headers=auth_headers)

    assert response.status_code == 400
    assert "not responding" in response.json()["detail"].lower()

    del vm_manager.vms[vm_id]


async def test_spice_connect_no_spice_port(app_client, auth_headers):
    """SPICE connection should 400 if VM has no SPICE port"""
    from app.main import vm_manager

    vm_id = _create_running_vm(vm_manager)
    vm_manager.vms[vm_id]["spice_port"] = None

    with patch.object(vm_manager, '_update_vm_status'):
        response = await app_client.get(f"/api/vms/{vm_id}/spice", headers=auth_headers)

    assert response.status_code == 400
    assert "spice" in response.json()["detail"].lower()

    del vm_manager.vms[vm_id]


async def test_spice_disconnect(app_client, auth_headers):
    """SPICE disconnect should stop the proxy"""
    from app.main import vm_manager

    vm_id = _create_running_vm(vm_manager)
    vm_manager.vms[vm_id]["spice_ws_port"] = 6800
    vm_manager.vms[vm_id]["spice_proxy_pid"] = 12345

    with patch.object(vm_manager.spice_proxy_manager, 'stop_proxy') as mock_stop:
        with patch.object(vm_manager, '_save_vms'):
            response = await app_client.post(f"/api/vms/{vm_id}/spice/disconnect", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["success"] is True
    mock_stop.assert_called_once_with(vm_id)

    del vm_manager.vms[vm_id]


# ==================== VNC Console Tests ====================


async def test_vnc_connect_vm_not_found(app_client, auth_headers):
    """VNC connection should 400 if VM doesn't exist"""
    response = await app_client.get("/api/vms/nonexistent/vnc", headers=auth_headers)
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


async def test_vnc_connect_vm_stopped(app_client, auth_headers):
    """VNC connection should 400 if VM is stopped"""
    from app.main import vm_manager

    vm_id = _create_running_vm(vm_manager)
    vm_manager.vms[vm_id]["status"] = "stopped"

    response = await app_client.get(f"/api/vms/{vm_id}/vnc", headers=auth_headers)
    assert response.status_code == 400
    assert "not running" in response.json()["detail"].lower()

    del vm_manager.vms[vm_id]


async def test_vnc_connect_success(app_client, auth_headers):
    """VNC connection should return ws_port when proxy starts successfully"""
    from app.main import vm_manager

    vm_id = _create_running_vm(vm_manager)

    with patch.object(vm_manager, '_update_vm_status'):
        with patch.object(vm_manager.vnc_proxy_manager, 'get_proxy_status', return_value={'status': 'stopped'}):
            with patch.object(vm_manager.vnc_proxy_manager, 'start_proxy', return_value={'ws_port': 6900, 'ws_proxy_pid': 54321}):
                response = await app_client.get(f"/api/vms/{vm_id}/vnc", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["ws_port"] == 6900
    assert data["vnc_port"] == 5900
    assert data["status"] == "ready"
    assert "ws_url" in data

    del vm_manager.vms[vm_id]


async def test_vnc_connect_proxy_already_running(app_client, auth_headers):
    """VNC connection should reuse existing proxy"""
    from app.main import vm_manager

    vm_id = _create_running_vm(vm_manager)

    with patch.object(vm_manager, '_update_vm_status'):
        with patch.object(vm_manager.vnc_proxy_manager, 'get_proxy_status',
                          return_value={'status': 'running', 'ws_port': 6901, 'pid': 22222}):
            response = await app_client.get(f"/api/vms/{vm_id}/vnc", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["ws_port"] == 6901
    assert data["status"] == "ready"

    del vm_manager.vms[vm_id]


async def test_vnc_connect_no_vnc_port(app_client, auth_headers):
    """VNC connection should 400 if VM has no VNC port"""
    from app.main import vm_manager

    vm_id = _create_running_vm(vm_manager)
    vm_manager.vms[vm_id]["vnc_port"] = None

    with patch.object(vm_manager, '_update_vm_status'):
        response = await app_client.get(f"/api/vms/{vm_id}/vnc", headers=auth_headers)

    assert response.status_code == 400
    assert "vnc" in response.json()["detail"].lower()

    del vm_manager.vms[vm_id]


async def test_vnc_disconnect(app_client, auth_headers):
    """VNC disconnect should stop the proxy"""
    from app.main import vm_manager

    vm_id = _create_running_vm(vm_manager)
    vm_manager.vms[vm_id]["ws_port"] = 6900
    vm_manager.vms[vm_id]["ws_proxy_pid"] = 54321

    with patch.object(vm_manager.vnc_proxy_manager, 'stop_proxy') as mock_stop:
        with patch.object(vm_manager, '_save_vms'):
            response = await app_client.post(f"/api/vms/{vm_id}/vnc/disconnect", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["success"] is True
    mock_stop.assert_called_once_with(vm_id)

    del vm_manager.vms[vm_id]


# ==================== Console without Auth ====================


async def test_spice_connect_no_auth(app_client):
    """SPICE endpoints should require authentication"""
    response = await app_client.get("/api/vms/some-id/spice")
    assert response.status_code == 403


async def test_vnc_connect_no_auth(app_client):
    """VNC endpoints should require authentication"""
    response = await app_client.get("/api/vms/some-id/vnc")
    assert response.status_code == 403


async def test_spice_disconnect_no_auth(app_client):
    """SPICE disconnect should require authentication"""
    response = await app_client.post("/api/vms/some-id/spice/disconnect")
    assert response.status_code == 403


async def test_vnc_disconnect_no_auth(app_client):
    """VNC disconnect should require authentication"""
    response = await app_client.post("/api/vms/some-id/vnc/disconnect")
    assert response.status_code == 403


# ==================== Spice Tools ====================


async def test_spice_tools_status(app_client, auth_headers):
    """Spice tools endpoint should return availability status"""
    response = await app_client.get("/api/spice-tools", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "available" in data
    assert isinstance(data["available"], bool)
