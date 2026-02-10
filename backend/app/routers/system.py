"""System, health, audit, and resource listing endpoints."""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
import os
import subprocess
import psutil
import logging

from ..models import AuditLogResponse
from ..auth import get_current_user, UserInfo as AuthUserInfo
from ..audit import get_audit_logs
from ..deps import vm_manager

logger = logging.getLogger("fast_vm.routers.system")

router = APIRouter(prefix="/api", tags=["system"])


def _check_system_health() -> dict:
    """Check system dependencies and return health status"""
    checks = {}
    try:
        result = subprocess.run(["qemu-system-x86_64", "--version"], capture_output=True, text=True, timeout=5)
        checks["qemu"] = {"ok": result.returncode == 0, "version": result.stdout.split('\n')[0] if result.returncode == 0 else None}
    except Exception:
        checks["qemu"] = {"ok": False, "version": None}

    checks["kvm"] = {"ok": os.path.exists("/dev/kvm")}

    try:
        disk = psutil.disk_usage(str(vm_manager.vms_dir))
        free_gb = round(disk.free / (1024 ** 3), 1)
        checks["disk"] = {"ok": free_gb > 5, "free_gb": free_gb}
    except Exception:
        checks["disk"] = {"ok": False, "free_gb": 0}

    try:
        from ..database import get_connection
        with get_connection() as conn:
            conn.execute("SELECT 1")
        checks["database"] = {"ok": True}
    except Exception:
        checks["database"] = {"ok": False}

    return checks


@router.get("/health")
async def health_check():
    """Health check endpoint with system status"""
    checks = _check_system_health()
    all_ok = all(c["ok"] for c in checks.values())
    return {"status": "healthy" if all_ok else "degraded", "service": "Fast VM", "checks": checks}


@router.get("/audit-logs", response_model=AuditLogResponse)
async def get_audit_log(
    limit: int = 100,
    offset: int = 0,
    username: Optional[str] = None,
    action: Optional[str] = None,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Get audit logs (admin only)"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return get_audit_logs(limit=min(limit, 500), offset=offset, username=username, action=action)


@router.get("/isos")
async def list_isos(current_user: AuthUserInfo = Depends(get_current_user)):
    """List available ISO files"""
    try:
        return vm_manager.get_available_isos()
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/bridges")
async def list_bridges(current_user: AuthUserInfo = Depends(get_current_user)):
    """List available network bridges on the system"""
    try:
        return vm_manager.get_available_bridges()
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/interfaces")
async def list_interfaces(current_user: AuthUserInfo = Depends(get_current_user)):
    """List available physical network interfaces for macvtap"""
    try:
        return vm_manager.get_available_interfaces()
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/system/user")
async def get_system_user(current_user: AuthUserInfo = Depends(get_current_user)):
    """Get the current system user running the backend"""
    import getpass
    return {"username": getpass.getuser()}
