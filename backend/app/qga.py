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

    def __init__(self, socket_path: str, timeout: float = 3.0):
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

    def exec_command(self, command: str, timeout: int = 10,
                     shell: str = "sh") -> Optional[str]:
        """Execute a shell command in the guest and return stdout.

        Args:
            command: Shell command to execute
            timeout: Max seconds to wait for command completion
            shell: Shell to use - "sh" (Linux), "cmd" (Windows), "powershell" (Windows)

        Returns:
            stdout output as string, or None if failed
        """
        if shell == "cmd":
            path = "cmd.exe"
            args = ["/c", command]
        elif shell == "powershell":
            path = "powershell.exe"
            args = ["-NoProfile", "-NonInteractive", "-Command", command]
        else:
            path = "/bin/sh"
            args = ["-c", command]

        try:
            resp = self._send_recv({
                "execute": "guest-exec",
                "arguments": {
                    "path": path,
                    "arg": args,
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


    def query(self, command: str) -> dict:
        """Execute a QGA query command (no arguments) and return the result.

        Args:
            command: QGA command name (e.g. 'guest-get-osinfo')

        Returns:
            The 'return' value from the QGA response
        """
        try:
            resp = self._send_recv({"execute": command})
        except Exception as e:
            raise QGAError(f"Failed to execute {command}: {e}")
        if "error" in resp:
            raise QGAError(f"{command} error: {resp['error']}")
        return resp.get("return", {})

    def get_guest_info(self, os_type: str = "linux") -> dict:
        """Collect comprehensive guest information via native QGA commands.

        Args:
            os_type: "linux", "windows", or "other"

        Returns a dict with: hostname, os, interfaces, users, filesystems, uptime.
        Each field is None if the corresponding QGA command fails.
        Raises QGAError if the guest agent is not responding at all.
        """
        # Fail fast: ping first to avoid slow sequential timeouts
        if not self.ping():
            raise QGAError("Guest agent not responding (is qemu-guest-agent installed and running?)")

        is_windows = os_type == "windows"
        info = {}

        # Hostname - native QGA, works on both Linux and Windows
        try:
            info["hostname"] = self.query("guest-get-host-name")
        except QGAError:
            info["hostname"] = None

        # OS info - native QGA (may not be available on older Windows QGA)
        try:
            info["os"] = self.query("guest-get-osinfo")
        except QGAError:
            info["os"] = None
        # Windows fallback: wmic is instant (systeminfo is 15-30s, too slow)
        if info["os"] is None and is_windows:
            try:
                out = self.exec_command(
                    "wmic os get caption,version /value",
                    timeout=5, shell="cmd"
                )
                if out and out.strip():
                    name = ""
                    version = ""
                    for line in out.strip().splitlines():
                        line = line.strip()
                        if line.startswith("Caption="):
                            name = line.split("=", 1)[1].strip()
                        elif line.startswith("Version="):
                            version = line.split("=", 1)[1].strip()
                    if name:
                        info["os"] = {
                            "pretty-name": name,
                            "version": version,
                            "id": "mswindows",
                        }
            except QGAError:
                pass

        # Network interfaces (IPs, MACs) - native QGA, works on both
        try:
            info["interfaces"] = self.query("guest-network-get-interfaces")
        except QGAError:
            info["interfaces"] = None

        # Logged-in users - native QGA
        try:
            info["users"] = self.query("guest-get-users")
        except QGAError:
            info["users"] = None

        # Filesystems - native QGA
        try:
            info["filesystems"] = self.query("guest-get-fsinfo")
        except QGAError:
            info["filesystems"] = None

        # Windows: guest-get-fsinfo often lacks total-bytes/used-bytes.
        # Enrich with wmic data.
        if is_windows and info["filesystems"] is not None:
            has_bytes = any(
                fs.get("total-bytes") for fs in info["filesystems"]
            )
            if not has_bytes:
                try:
                    out = self.exec_command(
                        "wmic logicaldisk get caption,size,freespace /format:csv",
                        timeout=5, shell="cmd"
                    )
                    if out:
                        disk_map = {}
                        for line in out.strip().splitlines():
                            parts = line.strip().split(",")
                            if len(parts) >= 4 and parts[1] and parts[1] != "Caption":
                                caption = parts[1].rstrip("\\")
                                try:
                                    free = int(parts[2]) if parts[2] else 0
                                    total = int(parts[3]) if parts[3] else 0
                                    disk_map[caption] = {"total": total, "free": free}
                                except ValueError:
                                    pass
                        for fs in info["filesystems"]:
                            mp = fs.get("mountpoint", "").rstrip("\\")
                            if mp in disk_map:
                                fs["total-bytes"] = disk_map[mp]["total"]
                                fs["used-bytes"] = disk_map[mp]["total"] - disk_map[mp]["free"]
                except QGAError:
                    pass
        # Linux: if guest-get-fsinfo lacks bytes, try df
        elif not is_windows and info["filesystems"] is not None:
            has_bytes = any(
                fs.get("total-bytes") for fs in info["filesystems"]
            )
            if not has_bytes:
                try:
                    out = self.exec_command("df -B1 --output=target,size,used 2>/dev/null", timeout=5)
                    if out:
                        df_map = {}
                        for line in out.strip().splitlines()[1:]:
                            parts = line.split()
                            if len(parts) >= 3:
                                try:
                                    df_map[parts[0]] = {"total": int(parts[1]), "used": int(parts[2])}
                                except ValueError:
                                    pass
                        for fs in info["filesystems"]:
                            mp = fs.get("mountpoint", "")
                            if mp in df_map:
                                fs["total-bytes"] = df_map[mp]["total"]
                                fs["used-bytes"] = df_map[mp]["used"]
                except QGAError:
                    pass

        # Uptime
        if is_windows:
            try:
                # wmic is instant; output: LastBootUpTime=20250213143022.500000+060
                out = self.exec_command(
                    "wmic os get lastbootuptime /value",
                    timeout=5, shell="cmd"
                )
                if out:
                    for line in out.strip().splitlines():
                        line = line.strip()
                        if line.startswith("LastBootUpTime="):
                            ts = line.split("=", 1)[1].strip()
                            # Parse WMI datetime: YYYYMMDDHHmmss.ffffff+ZZZ
                            if len(ts) >= 14:
                                from datetime import datetime
                                boot_str = ts[:14]  # YYYYMMDDHHmmss
                                boot = datetime.strptime(boot_str, "%Y%m%d%H%M%S")
                                delta = datetime.now() - boot
                                # Rough correction for timezone (ignore for simplicity)
                                secs = max(int(delta.total_seconds()), 0)
                                info["uptime"] = self._format_uptime(secs)
                                break
                    else:
                        info["uptime"] = None
                else:
                    info["uptime"] = None
            except (QGAError, ValueError):
                info["uptime"] = None
        else:
            try:
                out = self.exec_command("cat /proc/uptime 2>/dev/null", timeout=5)
                if out and out.strip():
                    secs = int(float(out.strip().split()[0]))
                    info["uptime"] = self._format_uptime(secs)
                else:
                    info["uptime"] = None
            except QGAError:
                info["uptime"] = None

        return info

    @staticmethod
    def _format_uptime(secs: int) -> str:
        """Format seconds into human-readable uptime string."""
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        mins, _ = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        parts.append(f"{mins}m")
        return " ".join(parts)


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
