from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List
import os

from .models import (
    VMCreate, VMInfo, VMResponse, VNCConnectionInfo, SpiceConnectionInfo, VMUpdate,
    Volume, VolumeCreate, VolumeResponse,
    Snapshot, SnapshotCreate, SnapshotResponse
)
from .vm_manager import VMManager
import asyncio

app = FastAPI(title="Fast VM", description="QEMU VM Manager API", version="1.0.0")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize VM Manager
vm_manager = VMManager()

# Mount static files for frontend
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

# Mount noVNC directory (legacy)
vnc_path = os.path.join(frontend_path, "vnc")
if os.path.exists(vnc_path):
    app.mount("/vnc", StaticFiles(directory=vnc_path, html=True), name="vnc")

# Mount spice-html5 directory
spice_path = os.path.join(frontend_path, "spice")
if os.path.exists(spice_path):
    app.mount("/spice", StaticFiles(directory=spice_path, html=True), name="spice")


@app.get("/")
async def root():
    """Serve frontend"""
    index_path = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Fast VM API is running"}


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "Fast VM"}


# ==================== VM Endpoints ====================

@app.get("/api/vms", response_model=List[VMInfo])
async def list_vms():
    """List all VMs"""
    try:
        return vm_manager.list_vms()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/vms/{vm_id}", response_model=VMInfo)
async def get_vm(vm_id: str):
    """Get VM details"""
    vm = vm_manager.get_vm(vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    return vm


@app.post("/api/vms", response_model=VMResponse)
async def create_vm(vm_data: VMCreate):
    """Create a new VM"""
    try:
        vm = vm_manager.create_vm(vm_data)
        return VMResponse(
            success=True,
            message=f"VM '{vm.name}' created successfully",
            vm=vm
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/vms/{vm_id}/start", response_model=VMResponse)
async def start_vm(vm_id: str):
    """Start a VM"""
    try:
        vm = vm_manager.start_vm(vm_id)
        return VMResponse(
            success=True,
            message=f"VM '{vm.name}' started successfully",
            vm=vm
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vms/{vm_id}/stop", response_model=VMResponse)
async def stop_vm(vm_id: str):
    """Stop a VM"""
    try:
        vm = vm_manager.stop_vm(vm_id)
        return VMResponse(
            success=True,
            message=f"VM '{vm.name}' stopped successfully",
            vm=vm
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vms/{vm_id}/restart", response_model=VMResponse)
async def restart_vm(vm_id: str):
    """Restart a VM"""
    try:
        vm = vm_manager.restart_vm(vm_id)
        return VMResponse(
            success=True,
            message=f"VM '{vm.name}' restarted successfully",
            vm=vm
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/vms/{vm_id}", response_model=VMResponse)
async def delete_vm(vm_id: str):
    """Delete a VM"""
    try:
        vm = vm_manager.get_vm(vm_id)
        vm_name = vm.name if vm else "Unknown"
        vm_manager.delete_vm(vm_id)
        return VMResponse(
            success=True,
            message=f"VM '{vm_name}' deleted successfully"
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/vms/{vm_id}/vnc", response_model=VNCConnectionInfo)
async def get_vnc_info(vm_id: str):
    """Get VNC connection info, starting proxy if needed"""
    try:
        vnc_info = vm_manager.get_vnc_connection(vm_id)
        return VNCConnectionInfo(**vnc_info)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vms/{vm_id}/vnc/disconnect", response_model=VMResponse)
async def disconnect_vnc(vm_id: str):
    """Disconnect VNC proxy for a VM"""
    try:
        vm_manager.vnc_proxy_manager.stop_proxy(vm_id)

        # Update VM state
        if vm_id in vm_manager.vms:
            vm_manager.vms[vm_id]['ws_port'] = None
            vm_manager.vms[vm_id]['ws_proxy_pid'] = None
            vm_manager._save_vms()

        return VMResponse(
            success=True,
            message="VNC proxy disconnected successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== SPICE Endpoints ====================

@app.get("/api/vms/{vm_id}/spice", response_model=SpiceConnectionInfo)
async def get_spice_info(vm_id: str):
    """Get SPICE connection info, starting proxy if needed"""
    try:
        spice_info = vm_manager.get_spice_connection(vm_id)
        return SpiceConnectionInfo(**spice_info)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vms/{vm_id}/spice/disconnect", response_model=VMResponse)
async def disconnect_spice(vm_id: str):
    """Disconnect SPICE proxy for a VM"""
    try:
        vm_manager.spice_proxy_manager.stop_proxy(vm_id)

        # Update VM state
        if vm_id in vm_manager.vms:
            vm_manager.vms[vm_id]['spice_ws_port'] = None
            vm_manager.vms[vm_id]['spice_proxy_pid'] = None
            vm_manager._save_vms()

        return VMResponse(
            success=True,
            message="SPICE proxy disconnected successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/spice-tools")
async def get_spice_tools_status():
    """Check if spice-guest-tools ISO is available"""
    try:
        return vm_manager.get_spice_tools_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/vms/{vm_id}/logs")
async def get_vm_logs(vm_id: str):
    """Get logs for a VM"""
    try:
        logs = vm_manager.get_vm_logs(vm_id)
        return logs
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/isos")
async def list_isos():
    """List available ISO files"""
    try:
        isos = vm_manager.get_available_isos()
        return isos
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bridges")
async def list_bridges():
    """List available network bridges on the system"""
    try:
        bridges = vm_manager.get_available_bridges()
        return bridges
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/vms/{vm_id}", response_model=VMResponse)
async def update_vm(vm_id: str, updates: VMUpdate):
    """Update VM configuration"""
    try:
        vm = vm_manager.update_vm(vm_id, updates.model_dump(exclude_unset=True))
        return VMResponse(
            success=True,
            message=f"VM '{vm.name}' updated successfully",
            vm=vm
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Volume Endpoints ====================

@app.get("/api/volumes", response_model=List[Volume])
async def list_volumes():
    """List all volumes"""
    try:
        return vm_manager.list_volumes()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/volumes/{vol_id}", response_model=Volume)
async def get_volume(vol_id: str):
    """Get volume details"""
    vol = vm_manager.get_volume(vol_id)
    if not vol:
        raise HTTPException(status_code=404, detail="Volume not found")
    return vol


@app.post("/api/volumes", response_model=VolumeResponse)
async def create_volume(vol_data: VolumeCreate):
    """Create a new volume"""
    try:
        vol = vm_manager.create_volume(vol_data)
        return VolumeResponse(
            success=True,
            message=f"Volume '{vol.name}' created successfully",
            volume=vol
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/volumes/{vol_id}", response_model=VolumeResponse)
async def delete_volume(vol_id: str):
    """Delete a volume"""
    try:
        vol = vm_manager.get_volume(vol_id)
        vol_name = vol.name if vol else "Unknown"
        vm_manager.delete_volume(vol_id)
        return VolumeResponse(
            success=True,
            message=f"Volume '{vol_name}' deleted successfully"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vms/{vm_id}/volumes/{vol_id}", response_model=VMResponse)
async def attach_volume(vm_id: str, vol_id: str):
    """Attach a volume to a VM"""
    try:
        vm = vm_manager.attach_volume(vm_id, vol_id)
        return VMResponse(
            success=True,
            message=f"Volume attached to VM '{vm.name}' successfully",
            vm=vm
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/vms/{vm_id}/volumes/{vol_id}", response_model=VMResponse)
async def detach_volume(vm_id: str, vol_id: str):
    """Detach a volume from a VM"""
    try:
        vm = vm_manager.detach_volume(vm_id, vol_id)
        return VMResponse(
            success=True,
            message=f"Volume detached from VM '{vm.name}' successfully",
            vm=vm
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Snapshot Endpoints ====================

@app.get("/api/vms/{vm_id}/snapshots", response_model=List[Snapshot])
async def list_snapshots(vm_id: str):
    """List snapshots for a VM"""
    try:
        return vm_manager.list_snapshots(vm_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vms/{vm_id}/snapshots", response_model=SnapshotResponse)
async def create_snapshot(vm_id: str, snap_data: SnapshotCreate):
    """Create a snapshot of a VM"""
    try:
        snap = vm_manager.create_snapshot(vm_id, snap_data)
        return SnapshotResponse(
            success=True,
            message=f"Snapshot '{snap.name}' created successfully",
            snapshot=snap
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vms/{vm_id}/snapshots/{snap_id}/restore", response_model=VMResponse)
async def restore_snapshot(vm_id: str, snap_id: str):
    """Restore a VM to a snapshot"""
    try:
        vm = vm_manager.restore_snapshot(vm_id, snap_id)
        return VMResponse(
            success=True,
            message=f"VM '{vm.name}' restored to snapshot successfully",
            vm=vm
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/vms/{vm_id}/snapshots/{snap_id}", response_model=SnapshotResponse)
async def delete_snapshot(vm_id: str, snap_id: str):
    """Delete a snapshot"""
    try:
        vm_manager.delete_snapshot(vm_id, snap_id)
        return SnapshotResponse(
            success=True,
            message=f"Snapshot deleted successfully"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Background Tasks ====================

async def periodic_cleanup():
    """Periodic cleanup of orphaned VNC proxies"""
    while True:
        await asyncio.sleep(300)  # 5 minutes
        try:
            vm_manager.vnc_proxy_manager.cleanup_orphaned_proxies()
        except Exception as e:
            print(f"Error in periodic cleanup: {e}")


@app.on_event("startup")
async def startup_event():
    """Start background tasks on application startup"""
    asyncio.create_task(periodic_cleanup())


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown"""
    vm_manager.vnc_proxy_manager.cleanup_all()
    vm_manager.spice_proxy_manager.cleanup_all()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
