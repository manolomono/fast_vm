"""Shared fixtures for tests"""
import pytest
import os
import sys
import json

# Add backend dir to path so 'app' package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test environment before importing app
os.environ["JWT_SECRET_KEY"] = "test-secret-key"

import app.auth as auth_module
from app.auth import hash_password, create_access_token
from app.main import app as fastapi_app, vm_manager
from pathlib import Path


@pytest.fixture(autouse=True)
def temp_dirs(tmp_path):
    """Create temporary directories for VMs and users"""
    vms_dir = tmp_path / "vms"
    vms_dir.mkdir()
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    volumes_dir = vms_dir / "volumes"
    volumes_dir.mkdir()

    (vms_dir / "vms.json").write_text("{}")
    (vms_dir / "volumes.json").write_text("{}")

    # Create users file with default admin
    users_file = tmp_path / "users.json"
    users = {
        "admin": {
            "username": "admin",
            "hashed_password": hash_password("admin"),
            "is_admin": True,
        }
    }
    users_file.write_text(json.dumps(users))

    return {
        "vms_dir": str(vms_dir),
        "images_dir": str(images_dir),
        "users_file": str(users_file),
        "tmp_path": tmp_path,
    }


@pytest.fixture
def app_client(temp_dirs):
    """Create a test client pointing to temp directories"""
    from httpx import ASGITransport, AsyncClient

    # Point auth to temp users file
    original_users_file = auth_module.USERS_FILE
    auth_module.USERS_FILE = temp_dirs["users_file"]

    # Point vm_manager to temp dirs
    orig_vms_dir = vm_manager.vms_dir
    orig_config_file = vm_manager.config_file
    orig_volumes_file = vm_manager.volumes_file
    orig_volumes_dir = vm_manager.volumes_dir
    orig_vms = vm_manager.vms
    orig_volumes = getattr(vm_manager, 'volumes', {})

    vm_manager.vms_dir = Path(temp_dirs["vms_dir"])
    vm_manager.config_file = vm_manager.vms_dir / "vms.json"
    vm_manager.volumes_file = vm_manager.vms_dir / "volumes.json"
    vm_manager.volumes_dir = Path(temp_dirs["vms_dir"]) / "volumes"
    vm_manager.vms = {}
    vm_manager.volumes = {}

    transport = ASGITransport(app=fastapi_app)
    client = AsyncClient(transport=transport, base_url="http://test")

    yield client

    # Restore originals
    auth_module.USERS_FILE = original_users_file
    vm_manager.vms_dir = orig_vms_dir
    vm_manager.config_file = orig_config_file
    vm_manager.volumes_file = orig_volumes_file
    vm_manager.volumes_dir = orig_volumes_dir
    vm_manager.vms = orig_vms
    vm_manager.volumes = orig_volumes


@pytest.fixture
def auth_headers(temp_dirs):
    """Get auth headers with a valid admin token"""
    original = auth_module.USERS_FILE
    auth_module.USERS_FILE = temp_dirs["users_file"]
    token = create_access_token({"sub": "admin"})
    auth_module.USERS_FILE = original
    return {"Authorization": f"Bearer {token}"}
