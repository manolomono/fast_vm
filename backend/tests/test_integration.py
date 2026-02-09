"""Integration tests - Complete user flows"""
import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.asyncio


class TestFullVMLifecycle:
    """Test complete VM lifecycle: create -> update -> clone -> delete"""

    async def test_vm_lifecycle(self, app_client, auth_headers):
        with patch("subprocess.run") as mock_run, patch("os.path.exists", return_value=True):
            mock_run.return_value = MagicMock(returncode=0)

            # 1. Create VM
            resp = await app_client.post(
                "/api/vms",
                headers=auth_headers,
                json={
                    "name": "Lifecycle VM",
                    "memory": 2048,
                    "cpus": 2,
                    "disk_size": 20,
                    "networks": [{"type": "nat", "model": "virtio"}],
                },
            )
            assert resp.status_code == 200
            vm_id = resp.json()["vm"]["id"]
            assert resp.json()["vm"]["status"] == "stopped"

            # 2. List VMs - should have 1
            resp = await app_client.get("/api/vms", headers=auth_headers)
            assert len(resp.json()) == 1

            # 3. Update VM
            resp = await app_client.put(
                f"/api/vms/{vm_id}",
                headers=auth_headers,
                json={"memory": 4096, "cpus": 4},
            )
            assert resp.status_code == 200
            assert resp.json()["vm"]["memory"] == 4096

            # 4. Clone VM
            resp = await app_client.post(
                f"/api/vms/{vm_id}/clone",
                headers=auth_headers,
                json={"name": "Cloned Lifecycle"},
            )
            assert resp.status_code == 200
            clone_id = resp.json()["vm"]["id"]
            assert clone_id != vm_id

            # 5. List VMs - should have 2
            resp = await app_client.get("/api/vms", headers=auth_headers)
            assert len(resp.json()) == 2

            # 6. Delete clone
            resp = await app_client.delete(f"/api/vms/{clone_id}", headers=auth_headers)
            assert resp.status_code == 200

            # 7. Delete original
            resp = await app_client.delete(f"/api/vms/{vm_id}", headers=auth_headers)
            assert resp.status_code == 200

            # 8. List VMs - should be empty
            resp = await app_client.get("/api/vms", headers=auth_headers)
            assert len(resp.json()) == 0


class TestVolumeLifecycle:
    """Test volume: create -> attach to VM -> detach -> delete"""

    async def test_volume_attach_detach(self, app_client, auth_headers):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            # 1. Create VM
            resp = await app_client.post(
                "/api/vms",
                headers=auth_headers,
                json={"name": "Vol Test VM", "memory": 512, "cpus": 1, "disk_size": 5},
            )
            vm_id = resp.json()["vm"]["id"]

            # 2. Create Volume
            resp = await app_client.post(
                "/api/volumes",
                headers=auth_headers,
                json={"name": "data-disk", "size_gb": 50, "format": "qcow2"},
            )
            assert resp.status_code == 200
            vol_id = resp.json()["volume"]["id"]

            # 3. Attach volume to VM
            resp = await app_client.post(
                f"/api/vms/{vm_id}/volumes/{vol_id}", headers=auth_headers,
            )
            assert resp.status_code == 200

            # 4. Verify volume is attached
            resp = await app_client.get(f"/api/volumes/{vol_id}", headers=auth_headers)
            assert resp.json()["attached_to"] == vm_id

            # 5. Detach volume
            resp = await app_client.delete(
                f"/api/vms/{vm_id}/volumes/{vol_id}", headers=auth_headers,
            )
            assert resp.status_code == 200

            # 6. Verify detached
            resp = await app_client.get(f"/api/volumes/{vol_id}", headers=auth_headers)
            assert resp.json()["attached_to"] is None

            # 7. Delete volume
            with patch("os.path.exists", return_value=True), patch("os.remove"):
                resp = await app_client.delete(
                    f"/api/volumes/{vol_id}", headers=auth_headers
                )
            assert resp.status_code == 200


class TestUserManagementFlow:
    """Test user management: create -> login -> change password -> delete"""

    async def test_user_management_flow(self, app_client, auth_headers):
        # 1. Admin creates a new user
        resp = await app_client.post(
            "/api/auth/users",
            headers=auth_headers,
            json={"username": "developer", "password": "DevPass1x", "is_admin": False},
        )
        assert resp.status_code == 200

        # 2. New user logs in
        resp = await app_client.post(
            "/api/auth/login",
            json={"username": "developer", "password": "DevPass1x"},
        )
        assert resp.status_code == 200
        dev_token = resp.json()["access_token"]
        dev_headers = {"Authorization": f"Bearer {dev_token}"}

        # 3. New user gets their info
        resp = await app_client.get("/api/auth/me", headers=dev_headers)
        assert resp.status_code == 200
        assert resp.json()["username"] == "developer"
        assert resp.json()["is_admin"] is False

        # 4. Non-admin cannot list users
        resp = await app_client.get("/api/auth/users", headers=dev_headers)
        assert resp.status_code == 403

        # 5. Non-admin cannot create users
        resp = await app_client.post(
            "/api/auth/users",
            headers=dev_headers,
            json={"username": "hacker", "password": "HackPass1", "is_admin": True},
        )
        assert resp.status_code == 403

        # 6. User changes their own password
        resp = await app_client.post(
            "/api/auth/change-password",
            headers=dev_headers,
            json={"current_password": "DevPass1x", "new_password": "NewDevPass2"},
        )
        assert resp.status_code == 200

        # 7. Login with new password works
        resp = await app_client.post(
            "/api/auth/login",
            json={"username": "developer", "password": "NewDevPass2"},
        )
        assert resp.status_code == 200

        # 8. Old password no longer works
        resp = await app_client.post(
            "/api/auth/login",
            json={"username": "developer", "password": "DevPass1x"},
        )
        assert resp.status_code == 401

        # 9. Admin deletes user
        resp = await app_client.delete(
            "/api/auth/users/developer", headers=auth_headers
        )
        assert resp.status_code == 200

        # 10. Deleted user can no longer login
        resp = await app_client.post(
            "/api/auth/login",
            json={"username": "developer", "password": "NewDevPass2"},
        )
        assert resp.status_code == 401


class TestMultipleVMs:
    """Test creating multiple VMs with different configs"""

    async def test_multiple_vms(self, app_client, auth_headers):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            # Create VM with NAT
            resp = await app_client.post(
                "/api/vms",
                headers=auth_headers,
                json={
                    "name": "NAT VM",
                    "memory": 1024,
                    "cpus": 1,
                    "disk_size": 10,
                    "networks": [{"type": "nat", "model": "virtio"}],
                    "cpu_model": "host",
                    "display_type": "qxl",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["vm"]["networks"][0]["type"] == "nat"

            # Create VM with different config
            resp = await app_client.post(
                "/api/vms",
                headers=auth_headers,
                json={
                    "name": "Bridge VM",
                    "memory": 4096,
                    "cpus": 4,
                    "disk_size": 50,
                    "networks": [{"type": "bridge", "model": "e1000", "bridge_name": "br0"}],
                    "boot_order": ["cdrom", "disk"],
                },
            )
            assert resp.status_code == 200
            assert resp.json()["vm"]["networks"][0]["type"] == "bridge"
            assert resp.json()["vm"]["boot_order"] == ["cdrom", "disk"]

            # List - should have 2
            resp = await app_client.get("/api/vms", headers=auth_headers)
            assert len(resp.json()) == 2
