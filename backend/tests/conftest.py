"""Shared fixtures for tests"""
import pytest
import os
import sys

# Add backend dir to path so 'app' package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test environment before importing app
os.environ["JWT_SECRET_KEY"] = "test-secret-key"

import app.database as db_module
import app.auth as auth_module
from app.auth import hash_password, create_access_token
from app.database import init_db, db_create_user
from app.main import app as fastapi_app, vm_manager, limiter
from pathlib import Path

# Disable rate limiting during tests
limiter.enabled = False


@pytest.fixture(autouse=True)
def temp_dirs(tmp_path):
    """Create temporary directories for VMs and users (SQLite-backed)"""
    vms_dir = tmp_path / "vms"
    vms_dir.mkdir()
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    volumes_dir = vms_dir / "volumes"
    volumes_dir.mkdir()

    (vms_dir / "vms.json").write_text("{}")
    (vms_dir / "volumes.json").write_text("{}")

    # Point database to temp directory
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    original_db_dir = db_module.DB_DIR
    original_db_path = db_module.DB_PATH
    db_module.DB_DIR = data_dir
    db_module.DB_PATH = data_dir / "fast_vm.db"

    # Initialize DB and create default admin user
    init_db()
    hashed = hash_password("admin")
    db_create_user("admin", hashed, is_admin=True)

    yield {
        "vms_dir": str(vms_dir),
        "images_dir": str(images_dir),
        "tmp_path": tmp_path,
    }

    # Restore originals
    db_module.DB_DIR = original_db_dir
    db_module.DB_PATH = original_db_path


@pytest.fixture
def app_client(temp_dirs):
    """Create a test client pointing to temp directories"""
    from httpx import ASGITransport, AsyncClient

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
    vm_manager.vms_dir = orig_vms_dir
    vm_manager.config_file = orig_config_file
    vm_manager.volumes_file = orig_volumes_file
    vm_manager.volumes_dir = orig_volumes_dir
    vm_manager.vms = orig_vms
    vm_manager.volumes = orig_volumes


@pytest.fixture
def auth_headers(temp_dirs):
    """Get auth headers with a valid admin token"""
    token = create_access_token({"sub": "admin"})
    return {"Authorization": f"Bearer {token}"}
