"""VNC and SPICE console connection endpoints + WebSocket proxy."""
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect
import asyncio
import logging

from ..models import VNCConnectionInfo, SpiceConnectionInfo, VMResponse
from ..auth import get_current_user, UserInfo as AuthUserInfo
from ..deps import vm_manager

logger = logging.getLogger("fast_vm.routers.console")

router = APIRouter(prefix="/api", tags=["console"])


# ==================== SPICE Endpoints ====================


@router.get("/vms/{vm_id}/spice", response_model=SpiceConnectionInfo)
async def get_spice_info(
    vm_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Get SPICE connection info"""
    try:
        spice_info = vm_manager.get_spice_connection(vm_id)
        return SpiceConnectionInfo(**spice_info)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/vms/{vm_id}/spice/disconnect", response_model=VMResponse)
async def disconnect_spice(
    vm_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Disconnect SPICE proxy for a VM"""
    try:
        vm_manager.spice_proxy_manager.stop_proxy(vm_id)
        if vm_id in vm_manager.vms:
            vm_manager.vms[vm_id]['spice_ws_port'] = None
            vm_manager.vms[vm_id]['spice_proxy_pid'] = None
            vm_manager._save_vms()
        return VMResponse(success=True, message="SPICE proxy disconnected successfully")
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/spice-tools")
async def get_spice_tools_status(
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Check if spice-guest-tools ISO is available"""
    try:
        return vm_manager.get_spice_tools_status()
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================== VNC Endpoints ====================


@router.get("/vms/{vm_id}/vnc", response_model=VNCConnectionInfo)
async def get_vnc_info(
    vm_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Get VNC connection info, starting proxy if needed"""
    try:
        vnc_info = vm_manager.get_vnc_connection(vm_id)
        return VNCConnectionInfo(**vnc_info)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/vms/{vm_id}/vnc/disconnect", response_model=VMResponse)
async def disconnect_vnc(
    vm_id: str,
    current_user: AuthUserInfo = Depends(get_current_user),
):
    """Disconnect VNC proxy for a VM"""
    try:
        vm_manager.vnc_proxy_manager.stop_proxy(vm_id)
        if vm_id in vm_manager.vms:
            vm_manager.vms[vm_id]['ws_port'] = None
            vm_manager.vms[vm_id]['ws_proxy_pid'] = None
            vm_manager._save_vms()
        return VMResponse(success=True, message="VNC proxy disconnected successfully")
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================== WebSocket SPICE Proxy ====================


def create_spice_ws_route(app):
    """Register the WebSocket SPICE proxy route on the app.

    WebSocket routes can't live on an APIRouter (no @router.websocket with prefix
    that matches the existing /ws/spice/{vm_id} path), so we register directly.
    """

    @app.websocket("/ws/spice/{vm_id}")
    async def websocket_spice_proxy(websocket: WebSocket, vm_id: str):
        """WebSocket-to-TCP proxy for SPICE console access.
        Eliminates the need for external websockify ports.
        Requires authentication via ?token=JWT query parameter.
        """
        # Authenticate via query parameter
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=4401, reason="Missing authentication token")
            return

        from ..auth import verify_token, get_user as auth_get_user
        payload_data = verify_token(token)
        if not payload_data or not payload_data.get("sub"):
            await websocket.close(code=4401, reason="Invalid or expired token")
            return
        if not auth_get_user(payload_data["sub"]):
            await websocket.close(code=4401, reason="User not found")
            return

        # Validate VM exists and is running
        if vm_id not in vm_manager.vms:
            await websocket.close(code=4404, reason="VM not found")
            return

        vm = vm_manager.vms[vm_id]
        vm_manager._update_vm_status(vm_id)

        if vm.get('status') != 'running':
            await websocket.close(code=4400, reason="VM is not running")
            return

        spice_port = vm.get('spice_port')
        if not spice_port:
            await websocket.close(code=4400, reason="SPICE port not configured")
            return

        # Accept the WebSocket connection
        await websocket.accept(subprotocol='binary')

        # Create TCP connection to the SPICE port with retry
        reader = writer = None
        for attempt in range(3):
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection('127.0.0.1', spice_port),
                    timeout=5.0,
                )
                break
            except asyncio.TimeoutError:
                logger.warning(f"SPICE connect timeout (attempt {attempt+1}/3) VM {vm_id} port {spice_port}")
            except ConnectionRefusedError:
                logger.warning(f"SPICE port {spice_port} refused (attempt {attempt+1}/3) VM {vm_id} - display may not be ready")
            except OSError as e:
                logger.warning(f"SPICE connect OS error (attempt {attempt+1}/3) VM {vm_id}: {e}")
            if attempt < 2:
                await asyncio.sleep(1)

        if reader is None or writer is None:
            logger.error(f"Failed to connect to SPICE port {spice_port} for VM {vm_id} after 3 attempts")
            await websocket.close(code=4500, reason=f"Cannot reach VM display on port {spice_port}. The VM may still be booting - try again in a few seconds.")
            return

        logger.info(f"SPICE proxy connected: VM {vm_id}, SPICE port {spice_port}")

        async def ws_to_tcp():
            """Forward WebSocket binary data to TCP"""
            try:
                while True:
                    data = await websocket.receive_bytes()
                    writer.write(data)
                    await writer.drain()
            except (WebSocketDisconnect, Exception):
                pass

        async def tcp_to_ws():
            """Forward TCP data to WebSocket"""
            try:
                while True:
                    data = await reader.read(65536)
                    if not data:
                        break
                    await websocket.send_bytes(data)
            except Exception:
                pass

        # Run both directions concurrently
        ws_task = asyncio.create_task(ws_to_tcp())
        tcp_task = asyncio.create_task(tcp_to_ws())

        try:
            done, pending = await asyncio.wait(
                [ws_task, tcp_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            try:
                await websocket.close()
            except Exception:
                pass
            logger.info(f"SPICE proxy disconnected: VM {vm_id}")
