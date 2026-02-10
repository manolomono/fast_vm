"""Snapshot management endpoints."""
from fastapi import APIRouter, HTTPException, Depends
from typing import List
import logging

from ..models import Snapshot, SnapshotCreate, SnapshotResponse, VMResponse
from ..auth import get_current_user, UserInfo as AuthUserInfo
from ..deps import vm_manager

logger = logging.getLogger("fast_vm.routers.snapshots")

router = APIRouter(prefix="/api", tags=["snapshots"])


@router.get("/vms/{vm_id}/snapshots", response_model=List[Snapshot])
async def list_snapshots(
    vm_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """List snapshots for a VM"""
    try:
        return vm_manager.list_snapshots(vm_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/vms/{vm_id}/snapshots", response_model=SnapshotResponse)
async def create_snapshot(
    vm_id: str,
    snap_data: SnapshotCreate,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Create a snapshot of a VM"""
    try:
        snap = vm_manager.create_snapshot(vm_id, snap_data)
        return SnapshotResponse(success=True, message=f"Snapshot '{snap.name}' created successfully", snapshot=snap)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/vms/{vm_id}/snapshots/{snap_id}/restore", response_model=VMResponse)
async def restore_snapshot(
    vm_id: str,
    snap_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Restore a VM to a snapshot"""
    try:
        vm = vm_manager.restore_snapshot(vm_id, snap_id)
        return VMResponse(success=True, message=f"VM '{vm.name}' restored to snapshot successfully", vm=vm)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/vms/{vm_id}/snapshots/{snap_id}", response_model=SnapshotResponse)
async def delete_snapshot(
    vm_id: str,
    snap_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Delete a snapshot"""
    try:
        vm_manager.delete_snapshot(vm_id, snap_id)
        return SnapshotResponse(success=True, message="Snapshot deleted successfully")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
