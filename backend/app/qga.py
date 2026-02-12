"""QEMU Guest Agent (QGA) helper for executing commands inside VMs."""
import json
import socket
import base64
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("fast_vm.qga")


class QGAError(Exception):
    """Error communicating with QEMU Guest Agent."""
    pass


class QGAClient:
    """Client for QEMU Guest Agent protocol over Unix socket."""

    def __init__(self, socket_path: str, timeout: float = 5.0):
        self.socket_path = socket_path
        self.timeout = timeout

    def _send_recv(self, command: dict) -> dict:
        """Send a QGA command and receive the response."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self.socket_path)
            # Sync first to clear any pending data
            sock.sendall(b'\xff')
            time.sleep(0.1)
            # Drain any buffered data
            sock.setblocking(False)
            try:
                while sock.recv(4096):
                    pass
            except (BlockingIOError, socket.error):
                pass
            sock.setblocking(True)
            sock.settimeout(self.timeout)

            # Send the actual command
            msg = json.dumps(command).encode() + b'\n'
            sock.sendall(msg)

            # Read response
            data = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                # QGA responses are single-line JSON
                if b'\n' in data:
                    break
            return json.loads(data.strip())
        finally:
            sock.close()

    def ping(self) -> bool:
        """Check if guest agent is responding."""
        try:
            resp = self._send_recv({"execute": "guest-ping"})
            return "return" in resp
        except Exception:
            return False

    def exec_command(self, command: str, timeout: int = 10) -> Optional[str]:
        """Execute a shell command in the guest and return stdout.

        Args:
            command: Shell command to execute
            timeout: Max seconds to wait for command completion

        Returns:
            stdout output as string, or None if failed
        """
        # Start the process
        cmd_b64 = base64.b64encode(command.encode()).decode()
        try:
            resp = self._send_recv({
                "execute": "guest-exec",
                "arguments": {
                    "path": "/bin/sh",
                    "arg": ["-c", command],
                    "capture-output": True
                }
            })
        except Exception as e:
            raise QGAError(f"Failed to exec command: {e}")

        if "error" in resp:
            raise QGAError(f"guest-exec error: {resp['error']}")

        pid = resp.get("return", {}).get("pid")
        if pid is None:
            raise QGAError("No PID returned from guest-exec")

        # Poll for completion
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                status_resp = self._send_recv({
                    "execute": "guest-exec-status",
                    "arguments": {"pid": pid}
                })
            except Exception as e:
                raise QGAError(f"Failed to get exec status: {e}")

            if "error" in status_resp:
                raise QGAError(f"guest-exec-status error: {status_resp['error']}")

            result = status_resp.get("return", {})
            if result.get("exited", False):
                stdout = ""
                if result.get("out-data"):
                    stdout = base64.b64decode(result["out-data"]).decode(errors="replace")
                stderr = ""
                if result.get("err-data"):
                    stderr = base64.b64decode(result["err-data"]).decode(errors="replace")

                exitcode = result.get("exitcode", -1)
                if exitcode != 0:
                    logger.warning(f"QGA command exited {exitcode}: stderr={stderr}")

                return stdout

            time.sleep(0.3)

        raise QGAError(f"Command timed out after {timeout}s")


def get_qga_client(vm_dir: Path) -> QGAClient:
    """Get a QGA client for a VM directory."""
    sock_path = vm_dir / "qga.sock"
    if not sock_path.exists():
        raise QGAError(f"QGA socket not found: {sock_path}")
    return QGAClient(str(sock_path))


def guest_resize_display(vm_dir: Path, width: int, height: int) -> bool:
    """Resize the guest display via QGA by running xrandr.

    Args:
        vm_dir: Path to the VM directory (contains qga.sock)
        width: Desired width in pixels
        height: Desired height in pixels

    Returns:
        True if resize command was sent successfully
    """
    client = get_qga_client(vm_dir)

    if not client.ping():
        raise QGAError("Guest agent not responding")

    # Script that finds the connected output and applies preferred resolution
    # or creates a new mode if needed. Works with both X11 and different output names.
    resize_script = f"""
export DISPLAY=:0 DISPLAY=:0.0
# Find active X display
for d in :0.0 :0 :1; do
    if DISPLAY=$d xrandr >/dev/null 2>&1; then
        export DISPLAY=$d
        break
    fi
done
# Find XAUTHORITY
for xa in /home/*/.Xauthority /root/.Xauthority; do
    if [ -f "$xa" ]; then
        export XAUTHORITY="$xa"
        break
    fi
done
# Get connected output name
OUTPUT=$(xrandr 2>/dev/null | grep ' connected' | head -1 | awk '{{print $1}}')
if [ -z "$OUTPUT" ]; then
    echo "ERROR: no connected output found"
    exit 1
fi
# Try setting preferred mode first (QEMU may have already added it via QXL)
xrandr --output "$OUTPUT" --preferred 2>/dev/null
# If the preferred mode doesn't match requested size, try explicit mode
CURRENT=$(xrandr 2>/dev/null | grep '\\*' | head -1 | awk '{{print $1}}')
if [ "$CURRENT" != "{width}x{height}" ]; then
    # Check if mode exists
    if xrandr 2>/dev/null | grep -q '{width}x{height}'; then
        xrandr --output "$OUTPUT" --mode {width}x{height} 2>/dev/null
    else
        # Create new mode via cvt and add it
        MODELINE=$(cvt {width} {height} 60 2>/dev/null | grep Modeline | sed 's/Modeline //')
        MODENAME=$(echo "$MODELINE" | awk '{{print $1}}' | tr -d '"')
        if [ -n "$MODENAME" ]; then
            xrandr --newmode $MODELINE 2>/dev/null
            xrandr --addmode "$OUTPUT" "$MODENAME" 2>/dev/null
            xrandr --output "$OUTPUT" --mode "$MODENAME" 2>/dev/null
        fi
    fi
fi
xrandr 2>/dev/null | grep '\\*' | head -1 | awk '{{print $1}}'
"""
    try:
        result = client.exec_command(resize_script, timeout=10)
        logger.info(f"QGA resize result: {result.strip() if result else 'empty'}")
        return True
    except QGAError as e:
        logger.warning(f"QGA resize failed: {e}")
        raise
