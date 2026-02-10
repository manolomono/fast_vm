"""Backup and restore endpoints."""
from fastapi import APIRouter, HTTPException, Depends, Request, UploadFile, File
from fastapi.responses import FileResponse
from typing import Optional
import os
import logging

from ..models import VMResponse
from ..auth import get_current_user, UserInfo as AuthUserInfo
from ..audit import log_action
from ..deps import vm_manager

logger = logging.getLogger("fast_vm.routers.backups")

router = APIRouter(prefix="/api", tags=["backups"])


@router.post("/vms/{vm_id}/backup")
async def backup_vm(
    request: Request,
    vm_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Create a backup of a VM (must be stopped)"""
    try:
        result = vm_manager.backup_vm(vm_id)
        log_action(current_user.username, "backup_vm", "vm", vm_id, {"backup": result["backup_name"]}, request.client.host if request.client else None)
        return {"success": True, "message": f"Backup created: {result['backup_name']}", **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/vms/{vm_id}/backup/download")
async def download_backup(
    vm_id: str,
    backup_name: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Download a VM backup file"""
    backup_path = vm_manager.backups_dir / backup_name
    if not backup_path.exists() or not backup_path.is_file():
        raise HTTPException(status_code=404, detail="Backup not found")
    # Security: ensure file is within backups dir
    if not str(backup_path.resolve()).startswith(str(vm_manager.backups_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid backup path")
    return FileResponse(str(backup_path), filename=backup_name, media_type="application/gzip")


@router.post("/vms/restore")
async def restore_vm_from_backup(
    request: Request,
    file: UploadFile = File(...),
    new_name: Optional[str] = None,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Restore a VM from an uploaded backup file"""
    import tempfile

    if not file.filename.endswith('.tar.gz'):
        raise HTTPException(status_code=400, detail="File must be a .tar.gz backup")
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar.gz') as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        vm = vm_manager.restore_vm(tmp_path, new_name)
        log_action(current_user.username, "restore_vm", "vm", vm.id, {"name": vm.name, "from": file.filename}, request.client.host if request.client else None)
        return VMResponse(success=True, message=f"VM '{vm.name}' restored successfully", vm=vm)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.get("/backups")
async def list_backups(current_user: AuthUserInfo = Depends(get_current_user)):
    """List available backups"""
    return vm_manager.list_backups()
