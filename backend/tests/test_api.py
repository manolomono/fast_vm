"""Tests for VM, Volume, and System API endpoints"""
import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.asyncio


async def test_health_check(app_client):
    """Test health endpoint"""
    response = await app_client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


async def test_list_vms_empty(app_client, auth_headers):
    """Test listing VMs when none exist"""
    response = await app_client.get("/api/vms", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_create_vm(app_client, auth_headers):
    """Test creating a VM"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        response = await app_client.post(
            "/api/vms",
            headers=auth_headers,
            json={"name": "Test VM", "memory": 1024, "cpus": 1, "disk_size": 10},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["vm"]["name"] == "Test VM"
    assert data["vm"]["status"] == "stopped"


async def test_get_vm(app_client, auth_headers):
    """Test getting a specific VM"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        create_resp = await app_client.post(
            "/api/vms",
            headers=auth_headers,
            json={"name": "GetMe", "memory": 512, "cpus": 1, "disk_size": 5},
        )
        vm_id = create_resp.json()["vm"]["id"]
        response = await app_client.get(f"/api/vms/{vm_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["name"] == "GetMe"


async def test_get_vm_not_found(app_client, auth_headers):
    """Test getting a nonexistent VM"""
    response = await app_client.get("/api/vms/nonexistent-id", headers=auth_headers)
    assert response.status_code == 404


async def test_update_vm(app_client, auth_headers):
    """Test updating VM configuration"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        create_resp = await app_client.post(
            "/api/vms",
            headers=auth_headers,
            json={"name": "UpdateMe", "memory": 1024, "cpus": 1, "disk_size": 10},
        )
        vm_id = create_resp.json()["vm"]["id"]
        response = await app_client.put(
            f"/api/vms/{vm_id}",
            headers=auth_headers,
            json={"memory": 2048, "cpus": 2},
        )
    assert response.status_code == 200
    assert response.json()["vm"]["memory"] == 2048
    assert response.json()["vm"]["cpus"] == 2


async def test_delete_vm(app_client, auth_headers):
    """Test deleting a VM"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        create_resp = await app_client.post(
            "/api/vms",
            headers=auth_headers,
            json={"name": "DeleteMe", "memory": 512, "cpus": 1, "disk_size": 5},
        )
        vm_id = create_resp.json()["vm"]["id"]
        response = await app_client.delete(f"/api/vms/{vm_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["success"] is True


async def test_clone_vm(app_client, auth_headers):
    """Test cloning a VM"""
    with patch("subprocess.run") as mock_run, patch("os.path.exists", return_value=True):
        mock_run.return_value = MagicMock(returncode=0)
        create_resp = await app_client.post(
            "/api/vms",
            headers=auth_headers,
            json={"name": "Original", "memory": 1024, "cpus": 2, "disk_size": 20},
        )
        vm_id = create_resp.json()["vm"]["id"]
        response = await app_client.post(
            f"/api/vms/{vm_id}/clone",
            headers=auth_headers,
            json={"name": "Cloned VM", "memory": 2048},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["vm"]["name"] == "Cloned VM"
    assert data["vm"]["memory"] == 2048
    assert data["vm"]["cpus"] == 2


# ==================== Volume Tests ====================


async def test_list_volumes_empty(app_client, auth_headers):
    """Test listing volumes when none exist"""
    response = await app_client.get("/api/volumes", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_create_volume(app_client, auth_headers):
    """Test creating a volume"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        response = await app_client.post(
            "/api/volumes",
            headers=auth_headers,
            json={"name": "test-vol", "size_gb": 10, "format": "qcow2"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["volume"]["name"] == "test-vol"


async def test_delete_volume(app_client, auth_headers):
    """Test deleting a volume"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        create_resp = await app_client.post(
            "/api/volumes",
            headers=auth_headers,
            json={"name": "del-vol", "size_gb": 5, "format": "qcow2"},
        )
        vol_id = create_resp.json()["volume"]["id"]
        with patch("os.path.exists", return_value=True), patch("os.remove"):
            response = await app_client.delete(
                f"/api/volumes/{vol_id}", headers=auth_headers
            )
    assert response.status_code == 200
    assert response.json()["success"] is True


# ==================== System Tests ====================


async def test_system_metrics(app_client, auth_headers):
    """Test system metrics endpoint"""
    response = await app_client.get("/api/system/metrics", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "cpu_percent" in data
    assert "memory_total_gb" in data
    assert "disk_total_gb" in data


async def test_metrics_history(app_client, auth_headers):
    """Test metrics history endpoint"""
    response = await app_client.get("/api/metrics/history", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "host" in data
    assert "vms" in data


async def test_list_isos(app_client, auth_headers):
    """Test listing ISOs"""
    response = await app_client.get("/api/isos", headers=auth_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


async def test_create_cloudinit(app_client, auth_headers):
    """Test creating a cloud-init ISO"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        response = await app_client.post(
            "/api/cloudinit",
            headers=auth_headers,
            json={
                "hostname": "test-server",
                "username": "testuser",
                "password": "testpass",
                "packages": ["vim", "htop"],
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
