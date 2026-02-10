"""VM CRUD and lifecycle endpoints."""
from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List
import logging

from ..models import (
    VMCreate, VMInfo, VMResponse, VMUpdate, VMClone, CloudInitConfig,
)
from ..auth import get_current_user, UserInfo as AuthUserInfo
from ..audit import log_action
from ..deps import vm_manager

logger = logging.getLogger("fast_vm.routers.vms")

router = APIRouter(prefix="/api", tags=["vms"])


@router.get("/vms", response_model=List[VMInfo])
async def list_vms(current_user: AuthUserInfo = Depends(get_current_user)):
    """List all VMs"""
    try:
        return vm_manager.list_vms()
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/vms/{vm_id}", response_model=VMInfo)
async def get_vm(vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Get VM details"""
    vm = vm_manager.get_vm(vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    return vm


@router.post("/vms", response_model=VMResponse)
async def create_vm(
    request: Request,
    vm_data: VMCreate,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Create a new VM"""
    try:
        vm = vm_manager.create_vm(vm_data)
        log_action(current_user.username, "create_vm", "vm", vm.id, {"name": vm.name}, request.client.host if request.client else None)
        return VMResponse(success=True, message=f"VM '{vm.name}' created successfully", vm=vm)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/vms/{vm_id}/start", response_model=VMResponse)
async def start_vm(
    request: Request,
    vm_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Start a VM"""
    try:
        vm = vm_manager.start_vm(vm_id)
        log_action(current_user.username, "start_vm", "vm", vm_id, {"name": vm.name}, request.client.host if request.client else None)
        return VMResponse(success=True, message=f"VM '{vm.name}' started successfully", vm=vm)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/vms/{vm_id}/stop", response_model=VMResponse)
async def stop_vm(
    request: Request,
    vm_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Stop a VM"""
    try:
        vm = vm_manager.stop_vm(vm_id)
        log_action(current_user.username, "stop_vm", "vm", vm_id, {"name": vm.name}, request.client.host if request.client else None)
        return VMResponse(success=True, message=f"VM '{vm.name}' stopped successfully", vm=vm)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/vms/{vm_id}/restart", response_model=VMResponse)
async def restart_vm(
    vm_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Restart a VM"""
    try:
        vm = vm_manager.restart_vm(vm_id)
        return VMResponse(success=True, message=f"VM '{vm.name}' restarted successfully", vm=vm)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/vms/{vm_id}/clone", response_model=VMResponse)
async def clone_vm(
    request: Request,
    vm_id: str,
    clone_data: VMClone,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Clone a VM (must be stopped)"""
    try:
        vm = vm_manager.clone_vm(vm_id, name=clone_data.name, memory=clone_data.memory, cpus=clone_data.cpus)
        log_action(current_user.username, "clone_vm", "vm", vm.id, {"source_id": vm_id, "name": vm.name}, request.client.host if request.client else None)
        return VMResponse(success=True, message=f"VM '{vm.name}' cloned successfully", vm=vm)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/vms/{vm_id}", response_model=VMResponse)
async def update_vm(
    vm_id: str,
    updates: VMUpdate,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Update VM configuration"""
    try:
        vm = vm_manager.update_vm(vm_id, updates.model_dump(exclude_unset=True))
        return VMResponse(success=True, message=f"VM '{vm.name}' updated successfully", vm=vm)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/vms/{vm_id}", response_model=VMResponse)
async def delete_vm(
    request: Request,
    vm_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Delete a VM"""
    try:
        vm = vm_manager.get_vm(vm_id)
        vm_name = vm.name if vm else "Unknown"
        vm_manager.delete_vm(vm_id)
        log_action(current_user.username, "delete_vm", "vm", vm_id, {"name": vm_name}, request.client.host if request.client else None)
        return VMResponse(success=True, message=f"VM '{vm_name}' deleted successfully")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/vms/{vm_id}/logs")
async def get_vm_logs(
    vm_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Get logs for a VM"""
    try:
        return vm_manager.get_vm_logs(vm_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/cloudinit")
async def create_cloudinit(
    config: CloudInitConfig,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Create a cloud-init ISO for automatic VM provisioning"""
    try:
        iso_path = vm_manager.create_cloudinit_iso(config)
        return {"success": True, "message": f"Cloud-init ISO created for '{config.hostname}'", "iso_path": iso_path}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
