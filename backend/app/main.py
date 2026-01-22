from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List
import os

from .models import VMCreate, VMInfo, VMResponse
from .vm_manager import VMManager

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
