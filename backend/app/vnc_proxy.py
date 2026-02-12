import os
import subprocess
import psutil
from pathlib import Path
from typing import Optional, Dict


class VNCProxyManager:
    def __init__(self, proxies_dir: Optional[Path] = None, novnc_path: Optional[Path] = None):
        """Initialize VNC proxy manager

        Args:
            proxies_dir: Directory to store proxy state files
            novnc_path: Path to noVNC directory for web content
        """
        if proxies_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            proxies_dir = base_dir / "vms" / "proxies"

        if novnc_path is None:
            base_dir = Path(__file__).parent.parent.parent
            novnc_path = base_dir / "frontend" / "vnc"

        self.proxies_dir = Path(proxies_dir)
        self.proxies_dir.mkdir(parents=True, exist_ok=True)

        self.novnc_path = Path(novnc_path)
        self.proxy_state: Dict[str, Dict] = {}

    def _get_free_ws_port(self, used_ports: set) -> int:
        """Get a free WebSocket port starting from 6900

        Args:
            used_ports: Set of already used ports

        Returns:
            Free port number between 6900-6999
        """
        for port in range(6900, 6999):
            if port not in used_ports and not self._is_port_in_use(port):
                return port
        raise RuntimeError("No free WebSocket ports available")

    def _is_port_in_use(self, port: int) -> bool:
        """Check if a port is in use via socket connect (avoids psutil AccessDenied)

        Args:
            port: Port number to check

        Returns:
            True if port is in use
        """
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                return s.connect_ex(('127.0.0.1', port)) == 0
        except Exception:
            try:
                for conn in psutil.net_connections():
                    if conn.laddr.port == port:
                        return True
            except (psutil.AccessDenied, OSError):
                pass
            return False

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is running

        Args:
            pid: Process ID to check

        Returns:
            True if process is running
        """
        try:
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def start_proxy(self, vm_id: str, vnc_port: int, used_ws_ports: set) -> Dict:
        """Start websockify proxy for a VM

        Args:
            vm_id: VM identifier
            vnc_port: VNC port number (5900-5999)
            used_ws_ports: Set of WebSocket ports already in use

        Returns:
            Dict with ws_port and ws_proxy_pid

        Raises:
            RuntimeError: If proxy fails to start
        """
        # Check if proxy already running
        if vm_id in self.proxy_state:
            state = self.proxy_state[vm_id]
            if self._is_process_running(state.get('pid')):
                return {
                    'ws_port': state['ws_port'],
                    'ws_proxy_pid': state['pid']
                }

        # Get free WebSocket port
        ws_port = self._get_free_ws_port(used_ws_ports)

        # Prepare websockify command
        # Run in foreground but detached from terminal with stdout/stderr redirected
        pid_file = self.proxies_dir / f"{vm_id}.pid"
        log_file = self.proxies_dir / f"{vm_id}.log"

        # Use websockify from venv
        venv_websockify = Path(__file__).parent.parent / "venv" / "bin" / "websockify"
        websockify_cmd = str(venv_websockify) if venv_websockify.exists() else "websockify"

        cmd = [
            websockify_cmd,
            "--web", str(self.novnc_path),
            "--timeout", "0",
            "--idle-timeout", "0",
            str(ws_port),
            f"localhost:{vnc_port}"
        ]

        try:
            # Start websockify process in background
            log_f = open(log_file, 'w')
            process = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True  # Detach from parent session
            )

            # Get PID immediately
            pid = process.pid

            # Wait a bit and verify process is still running
            import time
            time.sleep(0.5)

            if not self._is_process_running(pid):
                # Process died, read log
                log_f.close()
                with open(log_file, 'r') as f:
                    log_content = f.read()
                raise RuntimeError(f"websockify process died immediately. Log: {log_content}")

            # Save PID to file for future reference
            with open(pid_file, 'w') as f:
                f.write(str(pid))

            # Store state
            self.proxy_state[vm_id] = {
                'ws_port': ws_port,
                'pid': pid,
                'vnc_port': vnc_port
            }

            return {
                'ws_port': ws_port,
                'ws_proxy_pid': pid
            }

        except Exception as e:
            # Cleanup on failure
            if pid_file.exists():
                pid_file.unlink()
            if log_file.exists():
                # Read log for debugging
                with open(log_file, 'r') as f:
                    log_content = f.read()
                raise RuntimeError(f"Failed to start websockify: {str(e)}. Log: {log_content}")
            raise RuntimeError(f"Failed to start websockify: {str(e)}")

    def stop_proxy(self, vm_id: str) -> bool:
        """Stop websockify proxy for a VM

        Args:
            vm_id: VM identifier

        Returns:
            True if proxy was stopped or wasn't running
        """
        # Check in-memory state
        if vm_id in self.proxy_state:
            pid = self.proxy_state[vm_id].get('pid')
            if pid and self._is_process_running(pid):
                try:
                    process = psutil.Process(pid)
                    process.terminate()
                    process.wait(timeout=5)
                except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                    try:
                        if self._is_process_running(pid):
                            process.kill()
                    except psutil.NoSuchProcess:
                        pass

            del self.proxy_state[vm_id]

        # Cleanup PID file
        pid_file = self.proxies_dir / f"{vm_id}.pid"
        if pid_file.exists():
            pid_file.unlink()

        return True

    def get_proxy_status(self, vm_id: str) -> Dict:
        """Get proxy status for a VM

        Args:
            vm_id: VM identifier

        Returns:
            Dict with status, ws_port if running
        """
        if vm_id not in self.proxy_state:
            return {'status': 'stopped'}

        state = self.proxy_state[vm_id]
        pid = state.get('pid')

        if pid and self._is_process_running(pid):
            return {
                'status': 'running',
                'ws_port': state['ws_port'],
                'pid': pid
            }
        else:
            # Process died, cleanup
            del self.proxy_state[vm_id]
            return {'status': 'stopped'}

    def cleanup_orphaned_proxies(self):
        """Cleanup orphaned websockify processes

        Removes processes that are no longer needed
        """
        # Check all PID files
        for pid_file in self.proxies_dir.glob("*.pid"):
            vm_id = pid_file.stem

            try:
                with open(pid_file, 'r') as f:
                    pid = int(f.read().strip())

                # If process is running but not in our state, it's orphaned
                if self._is_process_running(pid) and vm_id not in self.proxy_state:
                    try:
                        process = psutil.Process(pid)
                        process.terminate()
                        process.wait(timeout=5)
                    except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                        pass

                # Remove PID file
                pid_file.unlink()

            except (ValueError, FileNotFoundError):
                # Invalid or missing PID file, just remove it
                if pid_file.exists():
                    pid_file.unlink()

    def cleanup_all(self):
        """Stop all proxies and cleanup

        Called on application shutdown
        """
        vm_ids = list(self.proxy_state.keys())
        for vm_id in vm_ids:
            self.stop_proxy(vm_id)

        self.cleanup_orphaned_proxies()
