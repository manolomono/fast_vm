"""Volume management endpoints."""
from fastapi import APIRouter, HTTPException, Depends
from typing import List
import logging

from ..models import Volume, VolumeCreate, VolumeResponse, VMResponse
from ..auth import get_current_user, UserInfo as AuthUserInfo
from ..audit import log_action
from ..deps import vm_manager

logger = logging.getLogger("fast_vm.routers.volumes")

router = APIRouter(prefix="/api", tags=["volumes"])


@router.get("/volumes", response_model=List[Volume])
async def list_volumes(current_user: AuthUserInfo = Depends(get_current_user)):
    """List all volumes"""
    try:
        return vm_manager.list_volumes()
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/volumes/{vol_id}", response_model=Volume)
async def get_volume(vol_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Get volume details"""
    vol = vm_manager.get_volume(vol_id)
    if not vol:
        raise HTTPException(status_code=404, detail="Volume not found")
    return vol


@router.post("/volumes", response_model=VolumeResponse)
async def create_volume(
    vol_data: VolumeCreate,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Create a new volume"""
    try:
        vol = vm_manager.create_volume(vol_data)
        log_action(current_user.username, "create_volume", "volume", vol.id, {"name": vol.name})
        return VolumeResponse(success=True, message=f"Volume '{vol.name}' created successfully", volume=vol)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/volumes/{vol_id}", response_model=VolumeResponse)
async def delete_volume(
    vol_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Delete a volume"""
    try:
        vol = vm_manager.get_volume(vol_id)
        vol_name = vol.name if vol else "Unknown"
        vm_manager.delete_volume(vol_id)
        log_action(current_user.username, "delete_volume", "volume", vol_id, {"name": vol_name})
        return VolumeResponse(success=True, message=f"Volume '{vol_name}' deleted successfully")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/vms/{vm_id}/volumes/{vol_id}", response_model=VMResponse)
async def attach_volume(
    vm_id: str,
    vol_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Attach a volume to a VM"""
    try:
        vm = vm_manager.attach_volume(vm_id, vol_id)
        return VMResponse(success=True, message=f"Volume attached to VM '{vm.name}' successfully", vm=vm)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/vms/{vm_id}/volumes/{vol_id}/promote", response_model=VMResponse)
async def promote_volume(
    vm_id: str,
    vol_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Promote an attached volume to be the VM's primary disk.

    Replaces the current (empty) disk with the volume file.
    Useful when the OS was installed on a volume instead of the main disk.
    """
    try:
        vm = vm_manager.promote_volume(vm_id, vol_id)
        log_action(current_user.username, "promote_volume", "vm", vm_id, {"volume_id": vol_id})
        return VMResponse(success=True, message=f"Volume promoted to primary disk of VM '{vm.name}'", vm=vm)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/vms/{vm_id}/volumes/{vol_id}", response_model=VMResponse)
async def detach_volume(
    vm_id: str,
    vol_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Detach a volume from a VM"""
    try:
        vm = vm_manager.detach_volume(vm_id, vol_id)
        return VMResponse(success=True, message=f"Volume detached from VM '{vm.name}' successfully", vm=vm)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
