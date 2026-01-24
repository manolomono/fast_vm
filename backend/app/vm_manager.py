import os
import json
import subprocess
import psutil
import uuid
import random
import re
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
from .models import (
    VMStatus, VMInfo, VMCreate, NetworkConfig, PortForward,
    Volume, VolumeCreate, Snapshot, SnapshotCreate
)
from .vnc_proxy import VNCProxyManager


class VMManager:
    def __init__(self, vms_dir: Optional[str] = None):
        if vms_dir is None:
            # Use relative path from project root
            base_dir = Path(__file__).parent.parent.parent
            vms_dir = base_dir / "vms"
        self.vms_dir = Path(vms_dir)
        self.vms_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.vms_dir / "vms.json"
        self.volumes_file = self.vms_dir / "volumes.json"
        self.volumes_dir = self.vms_dir / "volumes"
        self.volumes_dir.mkdir(parents=True, exist_ok=True)

        self.vms = self._load_vms()
        self.volumes = self._load_volumes()

        # Initialize VNC proxy manager
        self.vnc_proxy_manager = VNCProxyManager()

    def _load_vms(self) -> Dict:
        """Load VMs configuration from disk"""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                vms = json.load(f)
                # Migrate old VMs to include new fields
                for vm_id, vm in vms.items():
                    vm.setdefault('networks', [{'id': str(uuid.uuid4()), 'type': 'nat', 'port_forwards': []}])
                    vm.setdefault('volumes', [])
                    vm.setdefault('boot_order', ['disk', 'cdrom'])
                    vm.setdefault('cpu_model', 'host')
                    vm.setdefault('display_type', 'std')
                return vms
        return {}

    def _save_vms(self):
        """Save VMs configuration to disk"""
        with open(self.config_file, 'w') as f:
            json.dump(self.vms, f, indent=2)

    def _load_volumes(self) -> Dict:
        """Load volumes configuration from disk"""
        if self.volumes_file.exists():
            with open(self.volumes_file, 'r') as f:
                return json.load(f)
        return {}

    def _save_volumes(self):
        """Save volumes configuration to disk"""
        with open(self.volumes_file, 'w') as f:
            json.dump(self.volumes, f, indent=2)

    def _get_free_vnc_port(self) -> int:
        """Get a free VNC port starting from 5900"""
        used_ports = {vm.get('vnc_port') for vm in self.vms.values() if vm.get('vnc_port')}
        for port in range(5900, 5999):
            if port not in used_ports:
                return port
        return 5900

    def _generate_mac_address(self) -> str:
        """Generate a random MAC address for QEMU"""
        # QEMU uses 52:54:00 as the OUI
        mac = [0x52, 0x54, 0x00,
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff)]
        return ':'.join(map(lambda x: "%02x" % x, mac))

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

    def _build_network_args(self, networks: List[Dict], vm_id: str) -> List[str]:
        """Build QEMU network arguments from network config"""
        args = []

        if not networks:
            # Default NAT network
            networks = [{'id': str(uuid.uuid4()), 'type': 'nat', 'port_forwards': []}]

        for idx, net in enumerate(networks):
            net_type = net.get('type', 'nat')
            mac = net.get('mac_address') or self._generate_mac_address()

            if net_type == 'nat':
                # User networking with optional port forwards
                netdev_opts = f"user,id=net{idx}"

                port_forwards = net.get('port_forwards', [])
                for pf in port_forwards:
                    proto = pf.get('protocol', 'tcp')
                    host_port = pf.get('host_port')
                    guest_port = pf.get('guest_port')
                    if host_port and guest_port:
                        netdev_opts += f",hostfwd={proto}::{host_port}-:{guest_port}"

                args.extend(["-netdev", netdev_opts])
                args.extend(["-device", f"virtio-net-pci,netdev=net{idx},mac={mac}"])

            elif net_type == 'bridge':
                # Bridge networking
                bridge_name = net.get('bridge_name', 'br0')
                args.extend(["-netdev", f"bridge,id=net{idx},br={bridge_name}"])
                args.extend(["-device", f"virtio-net-pci,netdev=net{idx},mac={mac}"])

            elif net_type == 'isolated':
                # Isolated network (no external access)
                args.extend(["-netdev", f"user,id=net{idx},restrict=yes"])
                args.extend(["-device", f"virtio-net-pci,netdev=net{idx},mac={mac}"])

        return args

    def _build_boot_order_args(self, boot_order: List[str], has_iso: bool) -> List[str]:
        """Build QEMU boot order arguments"""
        # Map boot devices to QEMU codes
        device_map = {
            'disk': 'c',
            'cdrom': 'd',
            'network': 'n'
        }

        order = ''.join(device_map.get(d, '') for d in boot_order if d in device_map)

        if not order:
            order = 'cd' if has_iso else 'c'

        return ["-boot", f"order={order},menu=on"]

    def _build_volume_args(self, volumes: List[str], start_index: int = 1) -> List[str]:
        """Build QEMU arguments for attached volumes"""
        args = []

        for idx, vol_id in enumerate(volumes):
            vol = self.volumes.get(vol_id)
            if vol and vol.get('path') and os.path.exists(vol['path']):
                drive_idx = start_index + idx
                vol_format = vol.get('format', 'qcow2')
                args.extend([
                    "-drive", f"file={vol['path']},format={vol_format},if=none,id=disk{drive_idx}",
                    "-device", f"ide-hd,drive=disk{drive_idx},bus=ahci.{drive_idx}"
                ])

        return args

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

        # Process networks - ensure MAC addresses are set
        networks = []
        for net in vm_data.networks:
            net_dict = net.model_dump() if hasattr(net, 'model_dump') else dict(net)
            if not net_dict.get('mac_address'):
                net_dict['mac_address'] = self._generate_mac_address()
            networks.append(net_dict)

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
            'pid': None,
            'networks': networks,
            'volumes': [],
            'boot_order': vm_data.boot_order,
            'cpu_model': vm_data.cpu_model,
            'display_type': vm_data.display_type
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

        vm_dir = self.vms_dir / vm_id
        log_file = vm_dir / "qemu.log"
        pid_file = vm_dir / "qemu.pid"
        monitor_file = vm_dir / "monitor.sock"

        # UEFI firmware paths
        ovmf_code = Path("/usr/share/OVMF/OVMF_CODE_4M.fd")
        ovmf_vars_template = Path("/usr/share/OVMF/OVMF_VARS_4M.fd")
        ovmf_vars_vm = vm_dir / "OVMF_VARS.fd"

        # Copy OVMF_VARS to VM directory if not exists
        if not ovmf_vars_vm.exists() and ovmf_vars_template.exists():
            import shutil
            shutil.copy(ovmf_vars_template, ovmf_vars_vm)

        # Build base QEMU command
        qemu_cmd = [
            "qemu-system-x86_64",
            "-name", vm['name'],
            "-machine", "q35,accel=kvm",
            "-cpu", vm.get('cpu_model', 'host'),
            "-m", str(vm['memory']),
            "-smp", str(vm['cpus']),
            "-drive", f"file={vm['disk_path']},format=qcow2,if=none,id=disk0",
            "-device", "ahci,id=ahci",
            "-device", "ide-hd,drive=disk0,bus=ahci.0",
            "-vnc", f":{vm['vnc_port'] - 5900}",
            "-monitor", f"unix:{monitor_file},server,nowait",
            "-serial", "file:" + str(vm_dir / "serial.log"),
            "-daemonize",
            "-vga", vm.get('display_type', 'std'),
            "-usb",
            "-device", "usb-tablet",
            "-device", "usb-kbd"
        ]

        # Add network arguments
        networks = vm.get('networks', [])
        qemu_cmd.extend(self._build_network_args(networks, vm_id))

        # Add volume arguments
        volumes = vm.get('volumes', [])
        qemu_cmd.extend(self._build_volume_args(volumes))

        # Add UEFI firmware if available
        if ovmf_code.exists() and ovmf_vars_vm.exists():
            qemu_cmd.extend([
                "-drive", f"if=pflash,format=raw,readonly=on,file={ovmf_code}",
                "-drive", f"if=pflash,format=raw,file={ovmf_vars_vm}"
            ])

        # Add ISO if specified
        has_iso = vm.get('iso_path') and os.path.exists(vm['iso_path'])
        if has_iso:
            qemu_cmd.extend(["-cdrom", vm['iso_path']])

        # Add boot order
        boot_order = vm.get('boot_order', ['disk', 'cdrom'])
        qemu_cmd.extend(self._build_boot_order_args(boot_order, has_iso))

        qemu_cmd.extend(["-pidfile", str(pid_file)])

        try:
            # Run QEMU and capture any immediate errors
            result = subprocess.run(
                qemu_cmd,
                check=True,
                capture_output=True,
                text=True
            )

            # Write startup info to log
            with open(log_file, 'w') as f:
                f.write(f"QEMU started at: {subprocess.check_output(['date']).decode().strip()}\n")
                f.write(f"Command: {' '.join(qemu_cmd)}\n")
                f.write(f"Stdout: {result.stdout}\n")
                f.write(f"Stderr: {result.stderr}\n")
                f.write("-" * 80 + "\n")

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

        # Stop VNC proxy if running
        self.vnc_proxy_manager.stop_proxy(vm_id)
        vm['ws_port'] = None
        vm['ws_proxy_pid'] = None

        self._save_vms()

        return VMInfo(**vm)

    def restart_vm(self, vm_id: str) -> VMInfo:
        """Restart a VM"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        # Stop the VM first
        self.stop_vm(vm_id)

        # Wait a bit for clean shutdown
        import time
        time.sleep(1)

        # Start the VM again
        return self.start_vm(vm_id)

    def delete_vm(self, vm_id: str) -> bool:
        """Delete a VM"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        # Stop VM if running (this also stops the proxy)
        self.stop_vm(vm_id)

        # Cleanup VNC proxy
        self.vnc_proxy_manager.stop_proxy(vm_id)

        # Detach all volumes
        vm = self.vms[vm_id]
        for vol_id in vm.get('volumes', []):
            if vol_id in self.volumes:
                self.volumes[vol_id]['attached_to'] = None
        self._save_volumes()

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

    def get_vm_logs(self, vm_id: str) -> Dict:
        """Get logs for a VM"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        vm_dir = self.vms_dir / vm_id
        logs = {
            'qemu_log': '',
            'serial_log': ''
        }

        # Read QEMU log
        qemu_log_file = vm_dir / "qemu.log"
        if qemu_log_file.exists():
            try:
                with open(qemu_log_file, 'r') as f:
                    logs['qemu_log'] = f.read()
            except Exception as e:
                logs['qemu_log'] = f"Error reading log: {str(e)}"

        # Read serial log
        serial_log_file = vm_dir / "serial.log"
        if serial_log_file.exists():
            try:
                with open(serial_log_file, 'r') as f:
                    logs['serial_log'] = f.read()
            except Exception as e:
                logs['serial_log'] = f"Error reading log: {str(e)}"

        return logs

    def get_available_bridges(self) -> List[Dict]:
        """Get list of available network bridges on the system"""
        bridges = []
        try:
            # Get bridges using ip command
            result = subprocess.run(
                ["ip", "-j", "link", "show", "type", "bridge"],
                capture_output=True, text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                import json as json_module
                bridge_data = json_module.loads(result.stdout)
                for br in bridge_data:
                    name = br.get('ifname', '')
                    state = br.get('operstate', 'unknown').lower()
                    bridges.append({
                        'name': name,
                        'state': state,
                        'active': state == 'up'
                    })
        except Exception as e:
            print(f"Error getting bridges: {e}")
            # Fallback: try reading from /sys/class/net
            try:
                import os
                net_path = Path("/sys/class/net")
                if net_path.exists():
                    for iface in net_path.iterdir():
                        bridge_path = iface / "bridge"
                        if bridge_path.exists():
                            operstate_file = iface / "operstate"
                            state = "unknown"
                            if operstate_file.exists():
                                state = operstate_file.read_text().strip()
                            bridges.append({
                                'name': iface.name,
                                'state': state,
                                'active': state == 'up'
                            })
            except Exception:
                pass

        return sorted(bridges, key=lambda x: x['name'])

    def get_available_isos(self) -> List[Dict]:
        """Get list of available ISO files"""
        images_dir = self.vms_dir.parent / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        isos = []
        for iso_file in images_dir.glob("*.iso"):
            try:
                size_bytes = iso_file.stat().st_size
                size_mb = size_bytes / (1024 * 1024)
                isos.append({
                    'name': iso_file.name,
                    'path': str(iso_file),
                    'size_mb': round(size_mb, 2)
                })
            except Exception:
                continue

        return sorted(isos, key=lambda x: x['name'])

    def update_vm(self, vm_id: str, updates: Dict) -> VMInfo:
        """Update VM configuration"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        vm = self.vms[vm_id]
        self._update_vm_status(vm_id)

        # Don't allow updates while running
        if vm['status'] == VMStatus.RUNNING.value:
            raise ValueError("Cannot update VM while it is running. Stop it first.")

        # Update allowed fields
        if 'memory' in updates and updates['memory'] is not None:
            vm['memory'] = updates['memory']
        if 'cpus' in updates and updates['cpus'] is not None:
            vm['cpus'] = updates['cpus']
        if 'iso_path' in updates:
            # Validate ISO exists if provided
            if updates['iso_path'] and not os.path.exists(updates['iso_path']):
                raise ValueError(f"ISO file not found: {updates['iso_path']}")
            vm['iso_path'] = updates['iso_path']

        # Update network config
        if 'networks' in updates and updates['networks'] is not None:
            networks = []
            for net in updates['networks']:
                net_dict = net if isinstance(net, dict) else (net.model_dump() if hasattr(net, 'model_dump') else dict(net))
                if not net_dict.get('mac_address'):
                    net_dict['mac_address'] = self._generate_mac_address()
                networks.append(net_dict)
            vm['networks'] = networks

        # Update hardware options
        if 'boot_order' in updates and updates['boot_order'] is not None:
            vm['boot_order'] = updates['boot_order']
        if 'cpu_model' in updates and updates['cpu_model'] is not None:
            vm['cpu_model'] = updates['cpu_model']
        if 'display_type' in updates and updates['display_type'] is not None:
            vm['display_type'] = updates['display_type']

        self._save_vms()
        return VMInfo(**vm)

    def get_vnc_connection(self, vm_id: str) -> Dict:
        """Get VNC connection info, starting proxy if needed"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        vm = self.vms[vm_id]
        self._update_vm_status(vm_id)

        if vm['status'] != VMStatus.RUNNING.value:
            raise ValueError(f"VM is not running (status: {vm['status']})")

        vnc_port = vm.get('vnc_port')
        if not vnc_port:
            raise ValueError("VM does not have VNC port configured")

        # Check if proxy already running
        proxy_status = self.vnc_proxy_manager.get_proxy_status(vm_id)

        if proxy_status['status'] == 'running':
            ws_port = proxy_status['ws_port']
        else:
            # Start new proxy
            used_ws_ports = {
                v.get('ws_port') for v in self.vms.values()
                if v.get('ws_port')
            }

            proxy_info = self.vnc_proxy_manager.start_proxy(
                vm_id, vnc_port, used_ws_ports
            )

            ws_port = proxy_info['ws_port']
            vm['ws_port'] = ws_port
            vm['ws_proxy_pid'] = proxy_info['ws_proxy_pid']
            self._save_vms()

        return {
            'ws_port': ws_port,
            'ws_url': f"ws://localhost:{ws_port}",
            'vnc_port': vnc_port,
            'status': 'ready'
        }

    # ==================== Volume Management ====================

    def create_volume(self, vol_data: VolumeCreate) -> Volume:
        """Create a new standalone volume"""
        vol_id = str(uuid.uuid4())
        vol_path = self.volumes_dir / f"{vol_id}.{vol_data.format}"

        # Create disk image
        subprocess.run([
            "qemu-img", "create", "-f", vol_data.format,
            str(vol_path), f"{vol_data.size_gb}G"
        ], check=True)

        vol_config = {
            'id': vol_id,
            'name': vol_data.name,
            'size_gb': vol_data.size_gb,
            'format': vol_data.format,
            'path': str(vol_path),
            'attached_to': None
        }

        self.volumes[vol_id] = vol_config
        self._save_volumes()

        return Volume(**vol_config)

    def list_volumes(self) -> List[Volume]:
        """List all volumes"""
        return [Volume(**vol) for vol in self.volumes.values()]

    def get_volume(self, vol_id: str) -> Optional[Volume]:
        """Get volume by ID"""
        if vol_id not in self.volumes:
            return None
        return Volume(**self.volumes[vol_id])

    def delete_volume(self, vol_id: str) -> bool:
        """Delete a volume"""
        if vol_id not in self.volumes:
            raise ValueError(f"Volume {vol_id} not found")

        vol = self.volumes[vol_id]

        # Check if attached
        if vol.get('attached_to'):
            raise ValueError(f"Volume is attached to VM {vol['attached_to']}. Detach it first.")

        # Delete file
        vol_path = Path(vol['path'])
        if vol_path.exists():
            vol_path.unlink()

        del self.volumes[vol_id]
        self._save_volumes()

        return True

    def attach_volume(self, vm_id: str, vol_id: str) -> VMInfo:
        """Attach a volume to a VM"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")
        if vol_id not in self.volumes:
            raise ValueError(f"Volume {vol_id} not found")

        vm = self.vms[vm_id]
        vol = self.volumes[vol_id]

        # Check if VM is running
        self._update_vm_status(vm_id)
        if vm['status'] == VMStatus.RUNNING.value:
            raise ValueError("Cannot attach volume while VM is running. Stop it first.")

        # Check if volume already attached
        if vol.get('attached_to'):
            if vol['attached_to'] == vm_id:
                raise ValueError("Volume is already attached to this VM")
            raise ValueError(f"Volume is attached to another VM")

        # Attach
        if vol_id not in vm.get('volumes', []):
            vm.setdefault('volumes', []).append(vol_id)
        vol['attached_to'] = vm_id

        self._save_vms()
        self._save_volumes()

        return VMInfo(**vm)

    def detach_volume(self, vm_id: str, vol_id: str) -> VMInfo:
        """Detach a volume from a VM"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")
        if vol_id not in self.volumes:
            raise ValueError(f"Volume {vol_id} not found")

        vm = self.vms[vm_id]
        vol = self.volumes[vol_id]

        # Check if VM is running
        self._update_vm_status(vm_id)
        if vm['status'] == VMStatus.RUNNING.value:
            raise ValueError("Cannot detach volume while VM is running. Stop it first.")

        # Check if volume is attached to this VM
        if vol.get('attached_to') != vm_id:
            raise ValueError("Volume is not attached to this VM")

        # Detach
        if vol_id in vm.get('volumes', []):
            vm['volumes'].remove(vol_id)
        vol['attached_to'] = None

        self._save_vms()
        self._save_volumes()

        return VMInfo(**vm)

    # ==================== Snapshot Management ====================

    def create_snapshot(self, vm_id: str, snap_data: SnapshotCreate) -> Snapshot:
        """Create a snapshot of a VM's disk"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        vm = self.vms[vm_id]
        disk_path = vm.get('disk_path')

        if not disk_path or not os.path.exists(disk_path):
            raise ValueError("VM disk not found")

        # Generate snapshot ID
        snap_id = str(uuid.uuid4())[:8]

        # Create snapshot using qemu-img
        try:
            subprocess.run([
                "qemu-img", "snapshot",
                "-c", snap_id,
                disk_path
            ], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise ValueError(f"Failed to create snapshot: {e.stderr}")

        # Store snapshot metadata in VM config
        snapshots = vm.setdefault('snapshots', {})
        snapshots[snap_id] = {
            'id': snap_id,
            'name': snap_data.name,
            'created_at': datetime.now().isoformat(),
            'description': snap_data.description
        }
        self._save_vms()

        return Snapshot(
            id=snap_id,
            name=snap_data.name,
            created_at=datetime.now(),
            description=snap_data.description
        )

    def list_snapshots(self, vm_id: str) -> List[Snapshot]:
        """List snapshots for a VM"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        vm = self.vms[vm_id]
        disk_path = vm.get('disk_path')

        if not disk_path or not os.path.exists(disk_path):
            return []

        # Get snapshots from qemu-img
        try:
            result = subprocess.run([
                "qemu-img", "snapshot", "-l", disk_path
            ], capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError:
            return []

        # Parse output
        snapshots = []
        snap_metadata = vm.get('snapshots', {})

        # Parse qemu-img snapshot -l output
        # Format: ID   TAG   VM_SIZE   DATE   VM_CLOCK
        lines = result.stdout.strip().split('\n')
        for line in lines[2:]:  # Skip header lines
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2:
                snap_id = parts[1]  # TAG column
                metadata = snap_metadata.get(snap_id, {})

                # Parse date from qemu-img output if available
                created_at = datetime.now()
                if metadata.get('created_at'):
                    try:
                        created_at = datetime.fromisoformat(metadata['created_at'])
                    except:
                        pass

                vm_size = parts[2] if len(parts) > 2 else None

                snapshots.append(Snapshot(
                    id=snap_id,
                    name=metadata.get('name', snap_id),
                    created_at=created_at,
                    description=metadata.get('description'),
                    vm_size=vm_size
                ))

        return snapshots

    def restore_snapshot(self, vm_id: str, snap_id: str) -> VMInfo:
        """Restore a VM to a snapshot"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        vm = self.vms[vm_id]

        # Check if VM is running
        self._update_vm_status(vm_id)
        if vm['status'] == VMStatus.RUNNING.value:
            raise ValueError("Cannot restore snapshot while VM is running. Stop it first.")

        disk_path = vm.get('disk_path')
        if not disk_path or not os.path.exists(disk_path):
            raise ValueError("VM disk not found")

        # Restore snapshot using qemu-img
        try:
            subprocess.run([
                "qemu-img", "snapshot",
                "-a", snap_id,
                disk_path
            ], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise ValueError(f"Failed to restore snapshot: {e.stderr}")

        return VMInfo(**vm)

    def delete_snapshot(self, vm_id: str, snap_id: str) -> bool:
        """Delete a snapshot"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        vm = self.vms[vm_id]

        # Check if VM is running
        self._update_vm_status(vm_id)
        if vm['status'] == VMStatus.RUNNING.value:
            raise ValueError("Cannot delete snapshot while VM is running. Stop it first.")

        disk_path = vm.get('disk_path')
        if not disk_path or not os.path.exists(disk_path):
            raise ValueError("VM disk not found")

        # Delete snapshot using qemu-img
        try:
            subprocess.run([
                "qemu-img", "snapshot",
                "-d", snap_id,
                disk_path
            ], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise ValueError(f"Failed to delete snapshot: {e.stderr}")

        # Remove from metadata
        snapshots = vm.get('snapshots', {})
        if snap_id in snapshots:
            del snapshots[snap_id]
            self._save_vms()

        return True
