"""Fast VM - QEMU Virtual Machine Manager API

Punto de entrada: creacion de app, middleware, archivos estaticos y routers.
Toda la logica de endpoints vive en app/routers/*.
"""
from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
import os
import time
import logging
import asyncio
import subprocess
import psutil

from .logging_config import setup_logging
setup_logging()
logger = logging.getLogger("fast_vm.main")

# Estado compartido (importar desde deps para que los routers usen las mismas instancias)
from .deps import vm_manager, ws_clients
from .database import init_db, cleanup_old_metrics, cleanup_old_audit_logs
from .auth import create_default_user

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)


# ==================== Verificaciones previas y tareas de fondo ====================


def _preflight_checks():
    """Verificaciones previas al arranque"""
    try:
        result = subprocess.run(["qemu-system-x86_64", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            logger.info(f"QEMU: {result.stdout.split(chr(10))[0]}")
        else:
            logger.warning("QEMU not found or not working. VM operations will fail.")
    except Exception:
        logger.warning("qemu-system-x86_64 not found. Install QEMU to create VMs.")

    if not os.path.exists("/dev/kvm"):
        logger.warning("KVM not available (/dev/kvm not found). VMs will run without hardware acceleration.")

    try:
        disk = psutil.disk_usage(str(vm_manager.vms_dir))
        free_gb = round(disk.free / (1024 ** 3), 1)
        if free_gb < 10:
            logger.warning(f"Low disk space: {free_gb} GB free. Consider freeing up space.")
        else:
            logger.info(f"Disk space: {free_gb} GB free")
    except Exception:
        pass


def _sync_vm_states():
    """Sync VM states on startup: mark VMs with dead/zombie PIDs as stopped"""
    updated = 0
    for vm_id in list(vm_manager.vms.keys()):
        vm_manager._update_vm_status(vm_id)
        if vm_manager.vms[vm_id].get('status') == 'stopped' and vm_manager.vms[vm_id].get('pid') is None:
            updated += 1
    if updated:
        logger.info(f"Startup sync: marked {updated} VM(s) as stopped (stale PIDs)")
    else:
        logger.info("Startup sync: all VM states consistent")


async def periodic_cleanup():
    """Limpieza periodica: proxies huerfanos, metricas antiguas, logs de auditoria"""
    while True:
        await asyncio.sleep(300)
        try:
            vm_manager.vnc_proxy_manager.cleanup_orphaned_proxies()
            for vm_id in list(vm_manager.vms.keys()):
                vm_manager._update_vm_status(vm_id)
            cleanup_old_metrics(24)
            cleanup_old_audit_logs(90)
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {e}")


# ==================== Lifespan ====================


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Lifespan handler: logica de arranque y cierre"""
    init_db()
    create_default_user()
    _preflight_checks()
    _sync_vm_states()

    from .routers.metrics import collect_metrics_task
    asyncio.create_task(collect_metrics_task())
    asyncio.create_task(periodic_cleanup())
    yield
    vm_manager.vnc_proxy_manager.cleanup_all()
    vm_manager.spice_proxy_manager.cleanup_all()
    for ws in list(ws_clients):
        try:
            await ws.close()
        except Exception:
            pass


# ==================== Creacion de la App ====================


app = FastAPI(title="Fast VM", description="QEMU VM Manager API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ==================== Middleware ====================


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        duration = round((time.time() - start_time) * 1000, 1)
        logger.info(f"{request.method} {request.url.path} {response.status_code} {duration}ms")
        return response


app.add_middleware(RequestLoggingMiddleware)

# CORS
_cors_origins = os.environ.get("CORS_ORIGINS", "*")
_allowed_origins = [o.strip() for o in _cors_origins.split(",")] if _cors_origins != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if os.environ.get("FASTVM_PRODUCTION"):
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdn.tailwindcss.com; "
                "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data:; "
                "frame-src 'self'; "
                "connect-src 'self' ws: wss:;"
            )
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ==================== Montaje de Routers ====================

from .routers import auth, vms, console, volumes, snapshots, backups, metrics, system

app.include_router(auth.router)
app.include_router(vms.router)
app.include_router(console.router)
app.include_router(volumes.router)
app.include_router(snapshots.router)
app.include_router(backups.router)
app.include_router(metrics.router)
app.include_router(system.router)

# Registrar rutas WebSocket (no pueden vivir en APIRouter con el mismo esquema)
console.create_spice_ws_route(app)
metrics.create_metrics_ws_route(app)


# ==================== Archivos Estaticos y Rutas Raiz ====================

frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

vnc_path = os.path.join(frontend_path, "vnc")
if os.path.exists(vnc_path):
    app.mount("/vnc", StaticFiles(directory=vnc_path, html=True), name="vnc")

spice_path = os.path.join(frontend_path, "spice")
if os.path.exists(spice_path):
    app.mount("/spice", StaticFiles(directory=spice_path, html=True), name="spice")


@app.get("/")
async def root():
    """Servir frontend"""
    index_path = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Fast VM API is running"}


@app.get("/login.html")
async def login_page():
    """Servir pagina de login"""
    login_path = os.path.join(frontend_path, "login.html")
    if os.path.exists(login_path):
        return FileResponse(login_path)
    return {"message": "Login page not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
