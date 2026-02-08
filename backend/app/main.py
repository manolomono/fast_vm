from fastapi import FastAPI, HTTPException, Depends, Request, UploadFile, File, WebSocket, WebSocketDisconnect
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import List, Optional
import os
import time
import logging

from .logging_config import setup_logging
setup_logging()
logger = logging.getLogger("fast_vm.main")

from .models import (
    VMCreate, VMInfo, VMResponse, VNCConnectionInfo, SpiceConnectionInfo, VMUpdate,
    Volume, VolumeCreate, VolumeResponse,
    Snapshot, SnapshotCreate, SnapshotResponse,
    LoginRequest, Token, UserInfo,
    ChangePasswordRequest, CreateUserRequest,
    VMClone, CloudInitConfig,
    AuditLogEntry, AuditLogResponse
)
from .vm_manager import VMManager
from .auth import (
    authenticate_user, create_access_token, get_current_user,
    create_default_user, UserInfo as AuthUserInfo,
    verify_password, get_user, change_password,
    create_user, delete_user, list_users
)
from .database import init_db, save_host_metrics, save_vm_metrics, get_extended_metrics, cleanup_old_metrics
from .audit import log_action, get_audit_logs
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import asyncio
import psutil
from datetime import timedelta, datetime
from collections import deque

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Fast VM", description="QEMU VM Manager API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Request Logging Middleware
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        duration = round((time.time() - start_time) * 1000, 1)
        logger.info(f"{request.method} {request.url.path} {response.status_code} {duration}ms")
        return response


app.add_middleware(RequestLoggingMiddleware)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan handler: startup and shutdown logic"""
    # Startup
    asyncio.create_task(collect_metrics_task())
    asyncio.create_task(periodic_cleanup())
    yield
    # Shutdown
    vm_manager.vnc_proxy_manager.cleanup_all()
    vm_manager.spice_proxy_manager.cleanup_all()


app = FastAPI(title="Fast VM", description="QEMU VM Manager API", version="1.0.0", lifespan=lifespan)

# Metrics history buffer (keeps last 60 data points = 10 minutes at 10s intervals)
METRICS_HISTORY_SIZE = 60
metrics_history = {
    "host": deque(maxlen=METRICS_HISTORY_SIZE),
    "vms": {}  # vm_id -> deque of metrics
}

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


@app.get("/login.html")
async def login_page():
    """Serve login page"""
    login_path = os.path.join(frontend_path, "login.html")
    if os.path.exists(login_path):
        return FileResponse(login_path)
    return {"message": "Login page not found"}


# ==================== Auth Endpoints ====================

@app.post("/api/auth/login", response_model=Token)
@limiter.limit("5/minute")
async def login(request: Request, login_data: LoginRequest):
    """Authenticate user and return JWT token"""
    client_ip = request.client.host if request.client else None
    user = authenticate_user(login_data.username, login_data.password)
    if not user:
        log_action(login_data.username, "login_failed", ip=client_ip)
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )
    access_token = create_access_token(
        data={"sub": user.username, "is_admin": user.is_admin}
    )
    log_action(user.username, "login", ip=client_ip)
    return Token(access_token=access_token)


@app.post("/api/auth/logout")
async def logout():
    """Logout endpoint (client should discard token)"""
    return {"success": True, "message": "Logged out successfully"}


@app.get("/api/auth/me", response_model=UserInfo)
async def get_me(current_user: AuthUserInfo = Depends(get_current_user)):
    """Get current authenticated user info"""
    return UserInfo(username=current_user.username, is_admin=current_user.is_admin)


@app.post("/api/auth/change-password")
async def change_user_password(data: ChangePasswordRequest, current_user: AuthUserInfo = Depends(get_current_user)):
    """Change current user's password"""
    user = get_user(current_user.username)
    if not user or not verify_password(data.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    try:
        change_password(current_user.username, data.new_password)
        return {"success": True, "message": "Password changed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/auth/users")
async def get_users(current_user: AuthUserInfo = Depends(get_current_user)):
    """List all users (admin only)"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return list_users()


@app.post("/api/auth/users")
async def create_new_user(data: CreateUserRequest, current_user: AuthUserInfo = Depends(get_current_user)):
    """Create a new user (admin only)"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        create_user(data.username, data.password, data.is_admin)
        log_action(current_user.username, "create_user", "user", data.username, {"is_admin": data.is_admin})
        return {"success": True, "message": f"User '{data.username}' created successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/auth/users/{username}")
async def remove_user(username: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Delete a user (admin only, cannot delete self)"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    if username == current_user.username:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    try:
        delete_user(username)
        log_action(current_user.username, "delete_user", "user", username)
        return {"success": True, "message": f"User '{username}' deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "Fast VM"}


# ==================== Audit Log Endpoints ====================

@app.get("/api/audit-logs", response_model=AuditLogResponse)
async def get_audit_log(
    limit: int = 100, offset: int = 0,
    username: Optional[str] = None, action: Optional[str] = None,
    current_user: AuthUserInfo = Depends(get_current_user)
):
    """Get audit logs (admin only)"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return get_audit_logs(limit=min(limit, 500), offset=offset, username=username, action=action)


# ==================== VM Endpoints ====================

@app.get("/api/vms", response_model=List[VMInfo])
async def list_vms(current_user: AuthUserInfo = Depends(get_current_user)):
    """List all VMs"""
    try:
        return vm_manager.list_vms()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/vms/{vm_id}", response_model=VMInfo)
async def get_vm(vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Get VM details"""
    vm = vm_manager.get_vm(vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    return vm


@app.post("/api/vms", response_model=VMResponse)
@limiter.limit("10/minute")
async def create_vm(request: Request, vm_data: VMCreate, current_user: AuthUserInfo = Depends(get_current_user)):
    """Create a new VM"""
    try:
        vm = vm_manager.create_vm(vm_data)
        log_action(current_user.username, "create_vm", "vm", vm.id, {"name": vm.name}, request.client.host if request.client else None)
        return VMResponse(
            success=True,
            message=f"VM '{vm.name}' created successfully",
            vm=vm
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/vms/{vm_id}/start", response_model=VMResponse)
@limiter.limit("10/minute")
async def start_vm(request: Request, vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Start a VM"""
    try:
        vm = vm_manager.start_vm(vm_id)
        log_action(current_user.username, "start_vm", "vm", vm_id, {"name": vm.name}, request.client.host if request.client else None)
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
@limiter.limit("10/minute")
async def stop_vm(request: Request, vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Stop a VM"""
    try:
        vm = vm_manager.stop_vm(vm_id)
        log_action(current_user.username, "stop_vm", "vm", vm_id, {"name": vm.name}, request.client.host if request.client else None)
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
async def restart_vm(vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
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


@app.post("/api/vms/{vm_id}/clone", response_model=VMResponse)
@limiter.limit("10/minute")
async def clone_vm(request: Request, vm_id: str, clone_data: VMClone, current_user: AuthUserInfo = Depends(get_current_user)):
    """Clone a VM (must be stopped)"""
    try:
        vm = vm_manager.clone_vm(
            vm_id,
            name=clone_data.name,
            memory=clone_data.memory,
            cpus=clone_data.cpus
        )
        log_action(current_user.username, "clone_vm", "vm", vm.id, {"source_id": vm_id, "name": vm.name}, request.client.host if request.client else None)
        return VMResponse(
            success=True,
            message=f"VM '{vm.name}' cloned successfully",
            vm=vm
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cloudinit")
async def create_cloudinit(config: CloudInitConfig, current_user: AuthUserInfo = Depends(get_current_user)):
    """Create a cloud-init ISO for automatic VM provisioning"""
    try:
        iso_path = vm_manager.create_cloudinit_iso(config)
        return {
            "success": True,
            "message": f"Cloud-init ISO created for '{config.hostname}'",
            "iso_path": iso_path
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/vms/{vm_id}", response_model=VMResponse)
@limiter.limit("10/minute")
async def delete_vm(request: Request, vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Delete a VM"""
    try:
        vm = vm_manager.get_vm(vm_id)
        vm_name = vm.name if vm else "Unknown"
        vm_manager.delete_vm(vm_id)
        log_action(current_user.username, "delete_vm", "vm", vm_id, {"name": vm_name}, request.client.host if request.client else None)
        return VMResponse(
            success=True,
            message=f"VM '{vm_name}' deleted successfully"
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Backup & Restore Endpoints ====================

@app.post("/api/vms/{vm_id}/backup")
@limiter.limit("10/minute")
async def backup_vm(request: Request, vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Create a backup of a VM (must be stopped)"""
    try:
        result = vm_manager.backup_vm(vm_id)
        log_action(current_user.username, "backup_vm", "vm", vm_id, {"backup": result["backup_name"]}, request.client.host if request.client else None)
        return {"success": True, "message": f"Backup created: {result['backup_name']}", **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/vms/{vm_id}/backup/download")
async def download_backup(vm_id: str, backup_name: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Download a VM backup file"""
    backup_path = vm_manager.backups_dir / backup_name
    if not backup_path.exists() or not backup_path.is_file():
        raise HTTPException(status_code=404, detail="Backup not found")
    # Security: ensure file is within backups dir
    if not str(backup_path.resolve()).startswith(str(vm_manager.backups_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid backup path")
    return FileResponse(str(backup_path), filename=backup_name, media_type="application/gzip")


@app.post("/api/vms/restore")
@limiter.limit("10/minute")
async def restore_vm_from_backup(request: Request, file: UploadFile = File(...), new_name: Optional[str] = None, current_user: AuthUserInfo = Depends(get_current_user)):
    """Restore a VM from an uploaded backup file"""
    import tempfile
    if not file.filename.endswith('.tar.gz'):
        raise HTTPException(status_code=400, detail="File must be a .tar.gz backup")
    try:
        # Save uploaded file temporarily
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
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.get("/api/backups")
async def list_backups(current_user: AuthUserInfo = Depends(get_current_user)):
    """List available backups"""
    return vm_manager.list_backups()


@app.get("/api/vms/{vm_id}/vnc", response_model=VNCConnectionInfo)
async def get_vnc_info(vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Get VNC connection info, starting proxy if needed"""
    try:
        vnc_info = vm_manager.get_vnc_connection(vm_id)
        return VNCConnectionInfo(**vnc_info)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vms/{vm_id}/vnc/disconnect", response_model=VMResponse)
async def disconnect_vnc(vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
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
async def get_spice_info(vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Get SPICE connection info, starting proxy if needed"""
    try:
        spice_info = vm_manager.get_spice_connection(vm_id)
        return SpiceConnectionInfo(**spice_info)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vms/{vm_id}/spice/disconnect", response_model=VMResponse)
async def disconnect_spice(vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
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
async def get_spice_tools_status(current_user: AuthUserInfo = Depends(get_current_user)):
    """Check if spice-guest-tools ISO is available"""
    try:
        return vm_manager.get_spice_tools_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/vms/{vm_id}/logs")
async def get_vm_logs(vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Get logs for a VM"""
    try:
        logs = vm_manager.get_vm_logs(vm_id)
        return logs
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/isos")
async def list_isos(current_user: AuthUserInfo = Depends(get_current_user)):
    """List available ISO files"""
    try:
        isos = vm_manager.get_available_isos()
        return isos
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bridges")
async def list_bridges(current_user: AuthUserInfo = Depends(get_current_user)):
    """List available network bridges on the system"""
    try:
        bridges = vm_manager.get_available_bridges()
        return bridges
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/interfaces")
async def list_interfaces(current_user: AuthUserInfo = Depends(get_current_user)):
    """List available physical network interfaces for macvtap"""
    try:
        interfaces = vm_manager.get_available_interfaces()
        return interfaces
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/system/user")
async def get_system_user(current_user: AuthUserInfo = Depends(get_current_user)):
    """Get the current system user running the backend"""
    import getpass
    return {"username": getpass.getuser()}


@app.get("/api/vms/{vm_id}/metrics")
async def get_vm_metrics(vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Get real-time metrics for a running VM (CPU%, RAM, I/O)"""
    try:
        metrics = vm_manager.get_vm_metrics(vm_id)
        return metrics
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/system/metrics")
async def get_system_metrics(current_user: AuthUserInfo = Depends(get_current_user)):
    """Get host system metrics (CPU, RAM, disk)"""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        return {
            "cpu_percent": cpu_percent,
            "cpu_count": psutil.cpu_count(),
            "memory_total_gb": round(mem.total / (1024**3), 1),
            "memory_used_gb": round(mem.used / (1024**3), 1),
            "memory_percent": mem.percent,
            "disk_total_gb": round(disk.total / (1024**3), 1),
            "disk_used_gb": round(disk.used / (1024**3), 1),
            "disk_percent": round(disk.percent, 1)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/metrics/history")
async def get_metrics_history(current_user: AuthUserInfo = Depends(get_current_user)):
    """Get metrics history for charts (host + all VMs)"""
    return {
        "host": list(metrics_history["host"]),
        "vms": {vm_id: list(points) for vm_id, points in metrics_history["vms"].items()}
    }


@app.get("/api/vms/{vm_id}/metrics/history")
async def get_vm_metrics_history(vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Get metrics history for a specific VM"""
    if vm_id not in metrics_history["vms"]:
        return {"points": []}
    return {"points": list(metrics_history["vms"][vm_id])}


@app.get("/api/metrics/history/extended")
async def get_extended_metrics_history(hours: int = 24, vm_id: Optional[str] = None, current_user: AuthUserInfo = Depends(get_current_user)):
    """Get extended metrics history from SQLite (up to 24h)"""
    hours = min(hours, 24)
    return get_extended_metrics(hours, vm_id)


async def collect_metrics_task():
    """Background task to collect metrics every 10 seconds"""
    while True:
        try:
            # Host metrics
            cpu_percent = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            timestamp = datetime.utcnow().isoformat()

            host_cpu = round(cpu_percent, 1)
            host_mem = round(mem.percent, 1)

            metrics_history["host"].append({
                "t": timestamp,
                "cpu": host_cpu,
                "mem": host_mem,
            })

            # Persist host metrics to SQLite
            save_host_metrics(timestamp, host_cpu, host_mem)

            # VM metrics
            for vm_id, vm in vm_manager.vms.items():
                if vm.get('status') != 'running' or not vm.get('pid'):
                    continue
                try:
                    proc = psutil.Process(vm['pid'])
                    cpu = proc.cpu_percent(interval=0.1)
                    mem_info = proc.memory_info()
                    mem_mb = mem_info.rss / (1024 * 1024)
                    configured_mb = vm.get('memory', 1)

                    try:
                        io = proc.io_counters()
                        io_read = round(io.read_bytes / (1024 * 1024), 1)
                        io_write = round(io.write_bytes / (1024 * 1024), 1)
                    except (psutil.AccessDenied, AttributeError):
                        io_read = 0
                        io_write = 0

                    if vm_id not in metrics_history["vms"]:
                        metrics_history["vms"][vm_id] = deque(maxlen=METRICS_HISTORY_SIZE)

                    vm_cpu = round(cpu, 1)
                    vm_mem_mb = round(mem_mb, 1)
                    vm_mem_pct = round(mem_mb / configured_mb * 100, 1) if configured_mb > 0 else 0

                    metrics_history["vms"][vm_id].append({
                        "t": timestamp,
                        "cpu": vm_cpu,
                        "mem_mb": vm_mem_mb,
                        "mem_pct": vm_mem_pct,
                        "io_r": io_read,
                        "io_w": io_write,
                    })

                    # Persist VM metrics to SQLite
                    save_vm_metrics(timestamp, vm_id, vm_cpu, vm_mem_mb, vm_mem_pct, io_read, io_write)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            # Cleanup VMs that are no longer running
            active_ids = {vm_id for vm_id, vm in vm_manager.vms.items() if vm.get('status') == 'running'}
            for vm_id in list(metrics_history["vms"].keys()):
                if vm_id not in active_ids:
                    del metrics_history["vms"][vm_id]

            # Periodic cleanup of old metrics from SQLite (every collection cycle)
            cleanup_old_metrics(24)

        except Exception as e:
            logger.error(f"Error collecting metrics: {e}")

        await asyncio.sleep(10)


@app.on_event("startup")
async def start_metrics_collector():
    """Start metrics collection background task"""
    init_db()
    asyncio.create_task(collect_metrics_task())

@app.put("/api/vms/{vm_id}", response_model=VMResponse)
async def update_vm(vm_id: str, updates: VMUpdate, current_user: AuthUserInfo = Depends(get_current_user)):
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
async def list_volumes(current_user: AuthUserInfo = Depends(get_current_user)):
    """List all volumes"""
    try:
        return vm_manager.list_volumes()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/volumes/{vol_id}", response_model=Volume)
async def get_volume(vol_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Get volume details"""
    vol = vm_manager.get_volume(vol_id)
    if not vol:
        raise HTTPException(status_code=404, detail="Volume not found")
    return vol


@app.post("/api/volumes", response_model=VolumeResponse)
async def create_volume(vol_data: VolumeCreate, current_user: AuthUserInfo = Depends(get_current_user)):
    """Create a new volume"""
    try:
        vol = vm_manager.create_volume(vol_data)
        log_action(current_user.username, "create_volume", "volume", vol.id, {"name": vol.name})
        return VolumeResponse(
            success=True,
            message=f"Volume '{vol.name}' created successfully",
            volume=vol
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/volumes/{vol_id}", response_model=VolumeResponse)
async def delete_volume(vol_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """Delete a volume"""
    try:
        vol = vm_manager.get_volume(vol_id)
        vol_name = vol.name if vol else "Unknown"
        vm_manager.delete_volume(vol_id)
        log_action(current_user.username, "delete_volume", "volume", vol_id, {"name": vol_name})
        return VolumeResponse(
            success=True,
            message=f"Volume '{vol_name}' deleted successfully"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vms/{vm_id}/volumes/{vol_id}", response_model=VMResponse)
async def attach_volume(vm_id: str, vol_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
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
async def detach_volume(vm_id: str, vol_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
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
async def list_snapshots(vm_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
    """List snapshots for a VM"""
    try:
        return vm_manager.list_snapshots(vm_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vms/{vm_id}/snapshots", response_model=SnapshotResponse)
async def create_snapshot(vm_id: str, snap_data: SnapshotCreate, current_user: AuthUserInfo = Depends(get_current_user)):
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
async def restore_snapshot(vm_id: str, snap_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
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
async def delete_snapshot(vm_id: str, snap_id: str, current_user: AuthUserInfo = Depends(get_current_user)):
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
            logger.error(f"Error in periodic cleanup: {e}")


@app.on_event("startup")
async def startup_event():
    """Start background tasks on application startup"""
    asyncio.create_task(periodic_cleanup())


# ==================== WebSocket Metrics ====================

# Connected WebSocket clients
ws_clients: set = set()


@app.websocket("/ws/metrics")
async def websocket_metrics(websocket: WebSocket):
    """WebSocket endpoint for real-time metrics push (every 2s)"""
    # Accept without auth check for simplicity (metrics are not sensitive)
    # In production you could validate a token query param
    await websocket.accept()
    ws_clients.add(websocket)
    logger.info(f"WebSocket client connected ({len(ws_clients)} total)")
    try:
        while True:
            # Keep connection alive, listen for client messages (ping/filter)
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                break

            # Build metrics payload
            try:
                cpu_percent = psutil.cpu_percent(interval=0)
                mem = psutil.virtual_memory()
                timestamp = datetime.utcnow().isoformat()

                payload = {
                    "type": "metrics",
                    "host": {
                        "t": timestamp,
                        "cpu": round(cpu_percent, 1),
                        "mem": round(mem.percent, 1),
                    },
                    "vms": {}
                }

                for vid, vm in vm_manager.vms.items():
                    if vm.get('status') != 'running' or not vm.get('pid'):
                        continue
                    try:
                        proc = psutil.Process(vm['pid'])
                        cpu = proc.cpu_percent(interval=0)
                        mem_info = proc.memory_info()
                        mem_mb = mem_info.rss / (1024 * 1024)
                        configured_mb = vm.get('memory', 1)
                        try:
                            io = proc.io_counters()
                            io_r = round(io.read_bytes / (1024 * 1024), 1)
                            io_w = round(io.write_bytes / (1024 * 1024), 1)
                        except (psutil.AccessDenied, AttributeError):
                            io_r = io_w = 0

                        payload["vms"][vid] = {
                            "t": timestamp,
                            "cpu": round(cpu, 1),
                            "mem_mb": round(mem_mb, 1),
                            "mem_pct": round(mem_mb / configured_mb * 100, 1) if configured_mb > 0 else 0,
                            "io_r": io_r,
                            "io_w": io_w,
                        }
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                await websocket.send_json(payload)
            except Exception as e:
                logger.error(f"Error building WS metrics: {e}")

    except (WebSocketDisconnect, Exception):
        pass
    finally:
        ws_clients.discard(websocket)
        logger.info(f"WebSocket client disconnected ({len(ws_clients)} remaining)")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown"""
    vm_manager.vnc_proxy_manager.cleanup_all()
    vm_manager.spice_proxy_manager.cleanup_all()
    # Close all WebSocket connections
    for ws in list(ws_clients):
        try:
            await ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
