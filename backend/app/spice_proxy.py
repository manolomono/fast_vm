import subprocess
import psutil
from pathlib import Path
from typing import Optional, Dict


class SpiceProxyManager:
    """Manager for SPICE websocket proxies using websockify"""

    def __init__(self, proxies_dir: Optional[Path] = None, spice_html5_path: Optional[Path] = None):
        """Initialize SPICE proxy manager

        Args:
            proxies_dir: Directory to store proxy state files
            spice_html5_path: Path to spice-html5 directory for web content
        """
        if proxies_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            proxies_dir = base_dir / "vms" / "proxies"

        if spice_html5_path is None:
            base_dir = Path(__file__).parent.parent.parent
            spice_html5_path = base_dir / "frontend" / "spice"

        self.proxies_dir = Path(proxies_dir)
        self.proxies_dir.mkdir(parents=True, exist_ok=True)

        self.spice_html5_path = Path(spice_html5_path)
        self.proxy_state: Dict[str, Dict] = {}

    def _get_free_ws_port(self, used_ports: set) -> int:
        """Get a free WebSocket port starting from 6800

        Args:
            used_ports: Set of already used ports

        Returns:
            Free port number between 6800-6899
        """
        for port in range(6800, 6899):
            if port not in used_ports and not self._is_port_in_use(port):
                return port
        raise RuntimeError("No free WebSocket ports available for SPICE")

    def _is_port_in_use(self, port: int) -> bool:
        """Check if a port is in use"""
        for conn in psutil.net_connections():
            if conn.laddr.port == port:
                return True
        return False

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is running"""
        try:
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def start_proxy(self, vm_id: str, spice_port: int, used_ws_ports: set) -> Dict:
        """Start websockify proxy for SPICE

        Args:
            vm_id: VM identifier
            spice_port: SPICE port number
            used_ws_ports: Set of WebSocket ports already in use

        Returns:
            Dict with ws_port and proxy_pid
        """
        # Check if proxy already running
        if vm_id in self.proxy_state:
            state = self.proxy_state[vm_id]
            if self._is_process_running(state.get('pid')):
                return {
                    'ws_port': state['ws_port'],
                    'proxy_pid': state['pid']
                }

        # Get free WebSocket port
        ws_port = self._get_free_ws_port(used_ws_ports)

        # Prepare websockify command
        pid_file = self.proxies_dir / f"spice_{vm_id}.pid"
        log_file = self.proxies_dir / f"spice_{vm_id}.log"

        # Use websockify from venv
        venv_websockify = Path(__file__).parent.parent / "venv" / "bin" / "websockify"
        websockify_cmd = str(venv_websockify) if venv_websockify.exists() else "websockify"

        cmd = [
            websockify_cmd,
            "--web", str(self.spice_html5_path),
            "--timeout", "0",
            "--idle-timeout", "0",
            str(ws_port),
            f"localhost:{spice_port}"
        ]

        try:
            # Start websockify process in background
            log_f = open(log_file, 'w')
            process = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True
            )

            pid = process.pid

            # Wait and verify process is running
            import time
            time.sleep(0.5)

            if not self._is_process_running(pid):
                log_f.close()
                with open(log_file, 'r') as f:
                    log_content = f.read()
                raise RuntimeError(f"websockify process died immediately. Log: {log_content}")

            # Save PID to file
            with open(pid_file, 'w') as f:
                f.write(str(pid))

            # Store state
            self.proxy_state[vm_id] = {
                'ws_port': ws_port,
                'pid': pid,
                'spice_port': spice_port
            }

            return {
                'ws_port': ws_port,
                'proxy_pid': pid
            }

        except Exception as e:
            if pid_file.exists():
                pid_file.unlink()
            if log_file.exists():
                with open(log_file, 'r') as f:
                    log_content = f.read()
                raise RuntimeError(f"Failed to start websockify: {str(e)}. Log: {log_content}")
            raise RuntimeError(f"Failed to start websockify: {str(e)}")

    def stop_proxy(self, vm_id: str) -> bool:
        """Stop websockify proxy for a VM"""
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
        pid_file = self.proxies_dir / f"spice_{vm_id}.pid"
        if pid_file.exists():
            pid_file.unlink()

        return True

    def get_proxy_status(self, vm_id: str) -> Dict:
        """Get proxy status for a VM"""
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
            del self.proxy_state[vm_id]
            return {'status': 'stopped'}

    def cleanup_all(self):
        """Stop all proxies and cleanup"""
        vm_ids = list(self.proxy_state.keys())
        for vm_id in vm_ids:
            self.stop_proxy(vm_id)
