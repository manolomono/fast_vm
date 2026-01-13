import os
import json
import subprocess
import psutil
import uuid
from pathlib import Path
from typing import List, Optional, Dict
from .models import VMStatus, VMInfo, VMCreate


class VMManager:
    def __init__(self, vms_dir: Optional[str] = None):
        if vms_dir is None:
            # Use relative path from project root
            base_dir = Path(__file__).parent.parent.parent
            vms_dir = base_dir / "vms"
        self.vms_dir = Path(vms_dir)
        self.vms_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.vms_dir / "vms.json"
        self.vms = self._load_vms()

    def _load_vms(self) -> Dict:
        """Load VMs configuration from disk"""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {}

    def _save_vms(self):
        """Save VMs configuration to disk"""
        with open(self.config_file, 'w') as f:
            json.dump(self.vms, f, indent=2)

    def _get_free_vnc_port(self) -> int:
        """Get a free VNC port starting from 5900"""
        used_ports = {vm.get('vnc_port') for vm in self.vms.values() if vm.get('vnc_port')}
        for port in range(5900, 5999):
            if port not in used_ports:
                return port
        return 5900

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is running"""
        try:
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def _update_vm_status(self, vm_id: str):
        """Update VM status based on process state"""
        vm = self.vms.get(vm_id)
        if not vm:
            return

        pid = vm.get('pid')
        if pid and self._is_process_running(pid):
            vm['status'] = VMStatus.RUNNING.value
        else:
            vm['status'] = VMStatus.STOPPED.value
            vm['pid'] = None

        self._save_vms()

    def create_vm(self, vm_data: VMCreate) -> VMInfo:
        """Create a new VM"""
        vm_id = str(uuid.uuid4())
        vm_dir = self.vms_dir / vm_id
        vm_dir.mkdir(parents=True, exist_ok=True)

        disk_path = vm_dir / "disk.qcow2"

        # Create disk image
        subprocess.run([
            "qemu-img", "create", "-f", "qcow2",
            str(disk_path), f"{vm_data.disk_size}G"
        ], check=True)

        vnc_port = self._get_free_vnc_port()

        vm_config = {
            'id': vm_id,
            'name': vm_data.name,
            'memory': vm_data.memory,
            'cpus': vm_data.cpus,
            'disk_size': vm_data.disk_size,
            'disk_path': str(disk_path),
            'iso_path': vm_data.iso_path,
            'vnc_port': vnc_port,
            'status': VMStatus.STOPPED.value,
            'pid': None
        }

        self.vms[vm_id] = vm_config
        self._save_vms()

        return VMInfo(**vm_config)

    def start_vm(self, vm_id: str) -> VMInfo:
        """Start a VM"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        vm = self.vms[vm_id]
        self._update_vm_status(vm_id)

        if vm['status'] == VMStatus.RUNNING.value:
            raise ValueError(f"VM {vm['name']} is already running")

        qemu_cmd = [
            "qemu-system-x86_64",
            "-name", vm['name'],
            "-m", str(vm['memory']),
            "-smp", str(vm['cpus']),
            "-drive", f"file={vm['disk_path']},format=qcow2",
            "-vnc", f":{vm['vnc_port'] - 5900}",
            "-daemonize",
            "-enable-kvm"
        ]

        if vm.get('iso_path') and os.path.exists(vm['iso_path']):
            qemu_cmd.extend(["-cdrom", vm['iso_path']])

        pid_file = self.vms_dir / vm_id / "qemu.pid"
        qemu_cmd.extend(["-pidfile", str(pid_file)])

        try:
            subprocess.run(qemu_cmd, check=True)

            # Read PID from pid file
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())

            vm['pid'] = pid
            vm['status'] = VMStatus.RUNNING.value
            self._save_vms()

            return VMInfo(**vm)
        except Exception as e:
            vm['status'] = VMStatus.ERROR.value
            self._save_vms()
            raise Exception(f"Failed to start VM: {str(e)}")

    def stop_vm(self, vm_id: str) -> VMInfo:
        """Stop a VM"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        vm = self.vms[vm_id]
        self._update_vm_status(vm_id)

        if vm['status'] == VMStatus.STOPPED.value:
            return VMInfo(**vm)

        pid = vm.get('pid')
        if pid and self._is_process_running(pid):
            try:
                process = psutil.Process(pid)
                process.terminate()
                process.wait(timeout=10)
            except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                try:
                    process.kill()
                except psutil.NoSuchProcess:
                    pass

        vm['status'] = VMStatus.STOPPED.value
        vm['pid'] = None
        self._save_vms()

        return VMInfo(**vm)

    def delete_vm(self, vm_id: str) -> bool:
        """Delete a VM"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        # Stop VM if running
        self.stop_vm(vm_id)

        # Delete VM directory
        vm_dir = self.vms_dir / vm_id
        if vm_dir.exists():
            import shutil
            shutil.rmtree(vm_dir)

        del self.vms[vm_id]
        self._save_vms()

        return True

    def get_vm(self, vm_id: str) -> Optional[VMInfo]:
        """Get VM information"""
        if vm_id not in self.vms:
            return None

        self._update_vm_status(vm_id)
        return VMInfo(**self.vms[vm_id])

    def list_vms(self) -> List[VMInfo]:
        """List all VMs"""
        for vm_id in list(self.vms.keys()):
            self._update_vm_status(vm_id)

        return [VMInfo(**vm) for vm in self.vms.values()]
