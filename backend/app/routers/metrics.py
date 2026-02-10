"""Metrics endpoints and WebSocket real-time metrics push."""
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect
from typing import Optional
from collections import deque
from datetime import datetime, timezone
import asyncio
import psutil
import logging

from ..auth import get_current_user, UserInfo as AuthUserInfo
from ..deps import vm_manager, ws_clients, metrics_history, METRICS_HISTORY_SIZE
from ..database import save_host_metrics, save_vm_metrics, get_extended_metrics

logger = logging.getLogger("fast_vm.routers.metrics")

router = APIRouter(prefix="/api", tags=["metrics"])


@router.get("/vms/{vm_id}/metrics")
async def get_vm_metrics(
    vm_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Get real-time metrics for a running VM (CPU%, RAM, I/O)"""
    try:
        return vm_manager.get_vm_metrics(vm_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/system/metrics")
async def get_system_metrics(
    current_user: AuthUserInfo = Depends(get_current_user),
):
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
            "disk_percent": round(disk.percent, 1),
        }
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/metrics/history")
async def get_metrics_history(
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Get metrics history for charts (host + all VMs)"""
    return {
        "host": list(metrics_history["host"]),
        "vms": {vm_id: list(points) for vm_id, points in metrics_history["vms"].items()},
    }


@router.get("/vms/{vm_id}/metrics/history")
async def get_vm_metrics_history(
    vm_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Get metrics history for a specific VM"""
    if vm_id not in metrics_history["vms"]:
        return {"points": []}
    return {"points": list(metrics_history["vms"][vm_id])}


@router.get("/metrics/history/extended")
async def get_extended_metrics_history(
    hours: int = 24,
    vm_id: Optional[str] = None,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Get extended metrics history from SQLite (up to 24h)"""
    hours = min(hours, 24)
    return get_extended_metrics(hours, vm_id)


# ==================== Background Tasks ====================


async def collect_metrics_task():
    """Background task to collect metrics every 10 seconds"""
    vm_procs: dict[str, psutil.Process] = {}
    vm_prev_io: dict[str, tuple] = {}

    while True:
        try:
            cpu_percent = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            timestamp = datetime.now(timezone.utc).isoformat()

            host_cpu = round(cpu_percent, 1)
            host_mem = round(mem.percent, 1)

            metrics_history["host"].append({"t": timestamp, "cpu": host_cpu, "mem": host_mem})
            save_host_metrics(timestamp, host_cpu, host_mem)

            # VM metrics
            active_ids = set()
            for vm_id, vm in vm_manager.vms.items():
                if vm.get('status') != 'running' or not vm.get('pid'):
                    continue
                active_ids.add(vm_id)
                try:
                    pid = vm['pid']
                    if vm_id not in vm_procs or vm_procs[vm_id].pid != pid:
                        proc = psutil.Process(pid)
                        vm_procs[vm_id] = proc
                        proc.cpu_percent(interval=0)
                        try:
                            io = proc.io_counters()
                            vm_prev_io[vm_id] = (io.read_bytes, io.write_bytes)
                        except (psutil.AccessDenied, AttributeError):
                            vm_prev_io[vm_id] = (0, 0)
                        continue

                    proc = vm_procs[vm_id]
                    cpu = proc.cpu_percent(interval=0)
                    try:
                        for child in proc.children(recursive=True):
                            cpu += child.cpu_percent(interval=0)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                    mem_info = proc.memory_info()
                    mem_mb = mem_info.rss / (1024 * 1024)
                    configured_mb = vm.get('memory', 1)

                    io_read = 0.0
                    io_write = 0.0
                    try:
                        io = proc.io_counters()
                        prev_r, prev_w = vm_prev_io.get(vm_id, (io.read_bytes, io.write_bytes))
                        io_read = round(max(io.read_bytes - prev_r, 0) / (1024 * 1024), 2)
                        io_write = round(max(io.write_bytes - prev_w, 0) / (1024 * 1024), 2)
                        vm_prev_io[vm_id] = (io.read_bytes, io.write_bytes)
                    except (psutil.AccessDenied, AttributeError):
                        pass

                    if vm_id not in metrics_history["vms"]:
                        metrics_history["vms"][vm_id] = deque(maxlen=METRICS_HISTORY_SIZE)

                    vm_cpu = round(cpu, 1)
                    vm_mem_mb = round(mem_mb, 1)
                    vm_mem_pct = round(mem_mb / configured_mb * 100, 1) if configured_mb > 0 else 0

                    metrics_history["vms"][vm_id].append({
                        "t": timestamp, "cpu": vm_cpu, "mem_mb": vm_mem_mb,
                        "mem_pct": vm_mem_pct, "io_r": io_read, "io_w": io_write,
                    })
                    save_vm_metrics(timestamp, vm_id, vm_cpu, vm_mem_mb, vm_mem_pct, io_read, io_write)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    vm_procs.pop(vm_id, None)
                    vm_prev_io.pop(vm_id, None)
                    continue

            # Cleanup VMs that are no longer running
            for vm_id in list(metrics_history["vms"].keys()):
                if vm_id not in active_ids:
                    del metrics_history["vms"][vm_id]
            for vm_id in list(vm_procs):
                if vm_id not in active_ids:
                    del vm_procs[vm_id]
                    vm_prev_io.pop(vm_id, None)

        except Exception as e:
            logger.error(f"Error collecting metrics: {e}")

        await asyncio.sleep(10)


# ==================== WebSocket Metrics ====================


def create_metrics_ws_route(app):
    """Register the WebSocket metrics route on the app."""

    @app.websocket("/ws/metrics")
    async def websocket_metrics(websocket: WebSocket):
        """WebSocket endpoint for real-time metrics push (every 0.5s).
        Requires authentication via ?token=JWT query parameter.
        """
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=4401, reason="Missing authentication token")
            return

        from ..auth import verify_token, get_user
        payload = verify_token(token)
        if not payload or not payload.get("sub"):
            await websocket.close(code=4401, reason="Invalid or expired token")
            return
        if not get_user(payload["sub"]):
            await websocket.close(code=4401, reason="User not found")
            return

        await websocket.accept()
        ws_clients.add(websocket)
        logger.info(f"WebSocket client connected ({len(ws_clients)} total)")

        async def _receive_loop():
            try:
                while True:
                    await websocket.receive_text()
            except (WebSocketDisconnect, Exception):
                pass

        receive_task = asyncio.create_task(_receive_loop())

        vm_procs: dict[str, psutil.Process] = {}
        vm_prev_io: dict[str, tuple] = {}

        try:
            while not receive_task.done():
                try:
                    cpu_percent = psutil.cpu_percent(interval=0)
                    mem = psutil.virtual_memory()
                    timestamp = datetime.now(timezone.utc).isoformat()

                    payload_data = {
                        "type": "metrics",
                        "host": {"t": timestamp, "cpu": round(cpu_percent, 1), "mem": round(mem.percent, 1)},
                        "vms": {},
                    }

                    active_vids = set()
                    for vid, vm in vm_manager.vms.items():
                        if vm.get('status') != 'running' or not vm.get('pid'):
                            continue
                        active_vids.add(vid)
                        try:
                            pid = vm['pid']
                            if vid not in vm_procs or vm_procs[vid].pid != pid:
                                proc = psutil.Process(pid)
                                vm_procs[vid] = proc
                                proc.cpu_percent(interval=0)
                                try:
                                    io = proc.io_counters()
                                    vm_prev_io[vid] = (io.read_bytes, io.write_bytes)
                                except (psutil.AccessDenied, AttributeError):
                                    vm_prev_io[vid] = (0, 0)
                                continue

                            proc = vm_procs[vid]
                            cpu = proc.cpu_percent(interval=0)
                            try:
                                for child in proc.children(recursive=True):
                                    cpu += child.cpu_percent(interval=0)
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass

                            mem_info = proc.memory_info()
                            mem_mb = mem_info.rss / (1024 * 1024)
                            configured_mb = vm.get('memory', 1)

                            io_r = 0.0
                            io_w = 0.0
                            try:
                                io = proc.io_counters()
                                prev_r, prev_w = vm_prev_io.get(vid, (io.read_bytes, io.write_bytes))
                                io_r = round(max(io.read_bytes - prev_r, 0) / (1024 * 1024), 2)
                                io_w = round(max(io.write_bytes - prev_w, 0) / (1024 * 1024), 2)
                                vm_prev_io[vid] = (io.read_bytes, io.write_bytes)
                            except (psutil.AccessDenied, AttributeError):
                                pass

                            payload_data["vms"][vid] = {
                                "t": timestamp, "cpu": round(cpu, 1),
                                "mem_mb": round(mem_mb, 1),
                                "mem_pct": round(mem_mb / configured_mb * 100, 1) if configured_mb > 0 else 0,
                                "io_r": io_r, "io_w": io_w,
                            }
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            vm_procs.pop(vid, None)
                            vm_prev_io.pop(vid, None)
                            continue

                    for vid in list(vm_procs):
                        if vid not in active_vids:
                            del vm_procs[vid]
                            vm_prev_io.pop(vid, None)

                    await websocket.send_json(payload_data)
                except (WebSocketDisconnect, ConnectionError):
                    break
                except Exception as e:
                    logger.error(f"Error building WS metrics: {e}")

                await asyncio.sleep(0.5)
        finally:
            receive_task.cancel()
            ws_clients.discard(websocket)
            logger.info(f"WebSocket client disconnected ({len(ws_clients)} remaining)")
