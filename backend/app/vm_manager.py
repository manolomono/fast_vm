import os
import json
import subprocess
import psutil
import uuid
import random
import re
import threading
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
import shutil
import tempfile
from .models import (
    VMStatus, VMInfo, VMCreate, NetworkConfig, PortForward,
    Volume, VolumeCreate, Snapshot, SnapshotCreate, CloudInitConfig
)
from .vnc_proxy import VNCProxyManager
from .spice_proxy import SpiceProxyManager
import logging

logger = logging.getLogger("fast_vm.vm_manager")


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
        self.backups_dir = self.vms_dir.parent / "backups"
        self.backups_dir.mkdir(parents=True, exist_ok=True)

        # Lock to protect concurrent JSON config read/write
        self._config_lock = threading.Lock()

        self.vms = self._load_vms()
        self.volumes = self._load_volumes()

        # Initialize VNC proxy manager (legacy)
        self.vnc_proxy_manager = VNCProxyManager()

        # Initialize SPICE proxy manager
        self.spice_proxy_manager = SpiceProxyManager()

        # Path to spice-guest-tools ISO
        self.spice_tools_iso = self.vms_dir.parent / "images" / "spice-guest-tools.iso"

        # Persistent Process objects + I/O baselines for accurate metrics
        self._metric_procs: dict = {}    # vm_id -> psutil.Process
        self._metric_prev_io: dict = {}  # vm_id -> (read_bytes, write_bytes)

    def _start_swtpm(self, vm_id: str, vm_dir: Path) -> Optional[str]:
        """Start swtpm (software TPM) for a VM"""
        tpm_dir = vm_dir / "tpm"
        tpm_dir.mkdir(parents=True, exist_ok=True)
        tpm_socket = vm_dir / "swtpm-sock"

        # Check if swtpm is installed
        try:
            subprocess.run(["which", "swtpm"], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            logger.warning("swtpm not installed, TPM will not be available")
            return None

        # Kill any existing swtpm for this VM
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"swtpm.*{vm_id}"],
                capture_output=True, text=True
            )
            if result.stdout.strip():
                for pid in result.stdout.strip().split('\n'):
                    subprocess.run(["kill", pid], capture_output=True)
        except Exception:
            pass

        # Start swtpm
        try:
            swtpm_cmd = [
                "swtpm", "socket",
                "--tpmstate", f"dir={tpm_dir}",
                "--ctrl", f"type=unixio,path={tpm_socket}",
                "--tpm2",
                "--log", f"file={vm_dir}/swtpm.log,level=20",
                "-d"  # daemonize
            ]
            subprocess.run(swtpm_cmd, check=True, capture_output=True)
            return str(tpm_socket)
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to start swtpm: {e}")
            return None

    def _stop_swtpm(self, vm_id: str, vm_dir: Path):
        """Stop swtpm for a VM"""
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"swtpm.*{vm_dir}"],
                capture_output=True, text=True
            )
            if result.stdout.strip():
                for pid in result.stdout.strip().split('\n'):
                    subprocess.run(["kill", pid], capture_output=True)
        except Exception:
            pass

    @staticmethod
    def _validate_iface_name(name: str) -> str:
        """Validate a network interface name to prevent injection"""
        if not re.match(r'^[a-zA-Z0-9_.-]{1,15}$', name):
            raise ValueError(f"Invalid interface name: {name}")
        return name

    @staticmethod
    def _validate_mac_address(mac: str) -> str:
        """Validate a MAC address format"""
        if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac):
            raise ValueError(f"Invalid MAC address: {mac}")
        return mac

    def _create_macvtap(self, name: str, parent_iface: str, mac: str) -> Optional[int]:
        """Create a macvtap interface and return its tap device index"""
        try:
            # Validate inputs before passing to subprocess
            name = self._validate_iface_name(name)
            parent_iface = self._validate_iface_name(parent_iface)
            mac = self._validate_mac_address(mac)

            # Delete existing interface if any
            subprocess.run(
                ["sudo", "-n", "/usr/sbin/ip", "link", "delete", name],
                capture_output=True, timeout=10
            )

            # Create macvtap interface in bridge mode
            logger.info(f"Creating macvtap {name} on {parent_iface}")
            result = subprocess.run(
                ["sudo", "-n", "/usr/sbin/ip", "link", "add", "link", parent_iface,
                 "name", name, "type", "macvtap", "mode", "bridge"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                logger.error(f"Error creating macvtap {name}: {result.stderr}")
                return None

            # Set MAC address
            subprocess.run(
                ["sudo", "-n", "/usr/sbin/ip", "link", "set", name, "address", mac],
                capture_output=True, timeout=10
            )

            # Bring interface up
            subprocess.run(
                ["sudo", "-n", "/usr/sbin/ip", "link", "set", name, "up"],
                capture_output=True, timeout=10
            )

            # Get the tap device index from /sys
            tap_index_path = Path(f"/sys/class/net/{name}/ifindex")
            if tap_index_path.exists():
                tap_index = int(tap_index_path.read_text().strip())

                # Set permissions on /dev/tapN so QEMU can access it
                tap_dev = f"/dev/tap{tap_index}"
                subprocess.run(
                    ["sudo", "-n", "/bin/chmod", "666", tap_dev],
                    capture_output=True, timeout=10
                )

                return tap_index

            return None
        except Exception as e:
            logger.error(f"Error creating macvtap {name}: {e}")
            return None

    def _delete_macvtap(self, name: str):
        """Delete a macvtap interface"""
        try:
            name = self._validate_iface_name(name)
        except ValueError:
            logger.warning(f"Skipping delete of invalid interface name: {name}")
            return
        subprocess.run(
            ["sudo", "-n", "/usr/sbin/ip", "link", "delete", name],
            capture_output=True, timeout=10
        )

    def _cleanup_vm_macvtaps(self, vm_id: str):
        """Clean up all macvtap interfaces for a VM"""
        prefix = f"mvt{vm_id[:6]}"
        try:
            result = subprocess.run(
                ["ip", "-o", "link", "show", "type", "macvtap"],
                capture_output=True, text=True
            )
            for line in result.stdout.strip().split('\n'):
                if prefix in line:
                    # Extract interface name
                    parts = line.split(':')
                    if len(parts) >= 2:
                        iface_name = parts[1].strip().split('@')[0]
                        self._delete_macvtap(iface_name)
        except Exception:
            pass

    def _load_vms(self) -> Dict:
        """Load VMs configuration from disk"""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                vms = json.load(f)
                # Migrate old VMs to include new fields
                needs_save = False
                for vm_id, vm in vms.items():
                    vm.setdefault('networks', [{'id': str(uuid.uuid4()), 'type': 'nat', 'port_forwards': []}])
                    vm.setdefault('volumes', [])
                    vm.setdefault('boot_order', ['disk', 'cdrom'])
                    vm.setdefault('cpu_model', 'host')
                    # Migrate to SPICE
                    if 'spice_port' not in vm:
                        vm['spice_port'] = None  # Will be assigned on start
                        needs_save = True
                    if vm.get('display_type') == 'std':
                        vm['display_type'] = 'qxl'  # Better for SPICE
                        needs_save = True
                if needs_save:
                    with open(self.config_file, 'w') as f:
                        json.dump(vms, f, indent=2)
                return vms
        return {}

    def _save_vms(self):
        """Save VMs configuration to disk (thread-safe)"""
        with self._config_lock:
            with open(self.config_file, 'w') as f:
                json.dump(self.vms, f, indent=2)

    def _load_volumes(self) -> Dict:
        """Load volumes configuration from disk"""
        if self.volumes_file.exists():
            with open(self.volumes_file, 'r') as f:
                return json.load(f)
        return {}

    def _save_volumes(self):
        """Save volumes configuration to disk (thread-safe)"""
        with self._config_lock:
            with open(self.volumes_file, 'w') as f:
                json.dump(self.volumes, f, indent=2)

    def _get_free_vnc_port(self) -> int:
        """Get a free VNC port starting from 5900"""
        used_ports = {vm.get('vnc_port') for vm in self.vms.values() if vm.get('vnc_port')}
        for port in range(5900, 5999):
            if port not in used_ports:
                return port
        return 5900

    def _get_free_spice_port(self) -> int:
        """Get a free SPICE port starting from 5800, checking actual availability"""
        used_ports = {vm.get('spice_port') for vm in self.vms.values() if vm.get('spice_port')}
        for port in range(5800, 5899):
            if port not in used_ports and not self._is_port_in_use(port):
                return port
        raise RuntimeError("No free SPICE ports available (5800-5899)")

    def _generate_mac_address(self) -> str:
        """Generate a random MAC address for QEMU"""
        # QEMU uses 52:54:00 as the OUI
        mac = [0x52, 0x54, 0x00,
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff)]
        return ':'.join(map(lambda x: "%02x" % x, mac))

    def _is_port_in_use(self, port: int) -> bool:
        """Check if a port is currently in use on the system"""
        try:
            for conn in psutil.net_connections():
                if conn.laddr.port == port:
                    return True
        except (psutil.AccessDenied, OSError):
            pass
        return False

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

        # Map model names to QEMU device names
        nic_model_map = {
            'virtio': 'virtio-net-pci',
            'e1000': 'e1000',
            'rtl8139': 'rtl8139'
        }

        if not networks:
            # Default NAT network
            networks = [{'id': str(uuid.uuid4()), 'type': 'nat', 'model': 'virtio', 'port_forwards': []}]

        for idx, net in enumerate(networks):
            net_type = net.get('type', 'nat')
            nic_model = nic_model_map.get(net.get('model', 'virtio'), 'virtio-net-pci')
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
                args.extend(["-device", f"{nic_model},netdev=net{idx},mac={mac}"])

            elif net_type == 'bridge':
                # Bridge networking - requires qemu-bridge-helper to be configured
                bridge_name = net.get('bridge_name', 'br0')
                # Verify bridge helper configuration
                bridge_conf = Path("/etc/qemu/bridge.conf")
                helper_path = Path("/usr/lib/qemu/qemu-bridge-helper")
                if not bridge_conf.exists():
                    raise ValueError(
                        f"Bridge networking requires /etc/qemu/bridge.conf. "
                        f"Create it with: sudo mkdir -p /etc/qemu && "
                        f"sudo sh -c 'echo \"allow {bridge_name}\" > /etc/qemu/bridge.conf'"
                    )
                if helper_path.exists():
                    # Check if helper has setuid bit
                    mode = helper_path.stat().st_mode
                    if not (mode & 0o4000):  # Check setuid bit
                        raise ValueError(
                            f"qemu-bridge-helper needs setuid permission. "
                            f"Run: sudo chmod u+s /usr/lib/qemu/qemu-bridge-helper"
                        )
                args.extend(["-netdev", f"bridge,id=net{idx},br={bridge_name}"])
                args.extend(["-device", f"{nic_model},netdev=net{idx},mac={mac}"])

            elif net_type == 'macvtap':
                # macvtap networking - direct connection to physical interface
                # VM gets IP from same DHCP as host, no bridge required
                # This is handled specially in start_vm - just add placeholder
                parent_iface = net.get('parent_interface', 'eno1')
                # Include model in placeholder for device creation
                args.append(f"__MACVTAP_{idx}_{parent_iface}_{nic_model}_{mac}__")

            elif net_type == 'isolated':
                # Isolated network (no external access)
                args.extend(["-netdev", f"user,id=net{idx},restrict=yes"])
                args.extend(["-device", f"{nic_model},netdev=net{idx},mac={mac}"])

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
        spice_port = self._get_free_spice_port()

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
            'secondary_iso_path': vm_data.secondary_iso_path,
            'vnc_port': vnc_port,
            'spice_port': spice_port,
            'status': VMStatus.STOPPED.value,
            'pid': None,
            'networks': networks,
            'volumes': [],
            'boot_order': vm_data.boot_order,
            'cpu_model': vm_data.cpu_model,
            'display_type': vm_data.display_type,
            'os_type': vm_data.os_type
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

        # UEFI firmware paths - prefer Secure Boot variants for Windows 11
        ovmf_code = None
        ovmf_vars_template = None

        # Try Secure Boot variants first (required for Windows 11)
        # Note: secboot CODE + ms VARS is the correct combination for Microsoft Secure Boot
        secboot_paths = [
            ("/usr/share/OVMF/OVMF_CODE_4M.secboot.fd", "/usr/share/OVMF/OVMF_VARS_4M.ms.fd"),
            ("/usr/share/OVMF/OVMF_CODE_4M.ms.fd", "/usr/share/OVMF/OVMF_VARS_4M.ms.fd"),
            ("/usr/share/OVMF/OVMF_CODE_4M.secboot.fd", "/usr/share/OVMF/OVMF_VARS_4M.secboot.fd"),
            ("/usr/share/OVMF/OVMF_CODE.secboot.fd", "/usr/share/OVMF/OVMF_VARS.secboot.fd"),
            ("/usr/share/qemu/OVMF_CODE_4M.secboot.fd", "/usr/share/qemu/OVMF_VARS_4M.ms.fd"),
        ]

        for code_path, vars_path in secboot_paths:
            if Path(code_path).exists() and Path(vars_path).exists():
                ovmf_code = Path(code_path)
                ovmf_vars_template = Path(vars_path)
                break

        # Fallback to non-secure boot variants
        if not ovmf_code:
            fallback_paths = [
                ("/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_VARS_4M.fd"),
                ("/usr/share/OVMF/OVMF_CODE.fd", "/usr/share/OVMF/OVMF_VARS.fd"),
                ("/usr/share/qemu/OVMF_CODE.fd", "/usr/share/qemu/OVMF_VARS.fd"),
            ]
            for code_path, vars_path in fallback_paths:
                if Path(code_path).exists() and Path(vars_path).exists():
                    ovmf_code = Path(code_path)
                    ovmf_vars_template = Path(vars_path)
                    break

        ovmf_vars_vm = vm_dir / "OVMF_VARS.fd"

        # Copy OVMF_VARS to VM directory if not exists
        if not ovmf_vars_vm.exists() and ovmf_vars_template and ovmf_vars_template.exists():
            import shutil
            shutil.copy(ovmf_vars_template, ovmf_vars_vm)

        # Start TPM emulator
        tpm_socket = self._start_swtpm(vm_id, vm_dir)

        # Get SPICE port (assign if not exists for legacy VMs)
        spice_port = vm.get('spice_port')
        if not spice_port:
            spice_port = self._get_free_spice_port()
            vm['spice_port'] = spice_port
            self._save_vms()

        # Build base QEMU command with SPICE
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
            # SPICE configuration - bind to localhost only (proxied via FastAPI WebSocket)
            "-spice", f"port={spice_port},addr=127.0.0.1,disable-ticketing=on,streaming-video=off,agent-mouse=on",
            # QXL display for best SPICE experience
            "-device", "qxl-vga,vgamem_mb=64",
            # SPICE agent channel for clipboard, mouse, and display resize
            "-device", "virtio-serial-pci",
            "-chardev", "spicevmc,id=vdagent,name=vdagent",
            "-device", "virtserialport,chardev=vdagent,name=com.redhat.spice.0",
            # USB redirection support
            "-device", "ich9-usb-ehci1,id=usb",
            "-device", "ich9-usb-uhci1,masterbus=usb.0,firstport=0,multifunction=on",
            "-device", "ich9-usb-uhci2,masterbus=usb.0,firstport=2",
            "-device", "ich9-usb-uhci3,masterbus=usb.0,firstport=4",
            "-chardev", "spicevmc,id=usbredirchardev1,name=usbredir",
            "-device", "usb-redir,chardev=usbredirchardev1,id=usbredirdev1",
            "-chardev", "spicevmc,id=usbredirchardev2,name=usbredir",
            "-device", "usb-redir,chardev=usbredirchardev2,id=usbredirdev2",
            # Input devices
            "-device", "usb-tablet",
            "-monitor", f"unix:{monitor_file},server,nowait",
            "-serial", "file:" + str(vm_dir / "serial.log"),
            "-daemonize"
        ]

        # Add network arguments
        networks = vm.get('networks', [])
        qemu_cmd.extend(self._build_network_args(networks, vm_id))

        # Add volume arguments
        volumes = vm.get('volumes', [])
        qemu_cmd.extend(self._build_volume_args(volumes))

        # Add UEFI firmware if available
        if ovmf_code and ovmf_code.exists() and ovmf_vars_vm.exists():
            qemu_cmd.extend([
                "-drive", f"if=pflash,format=raw,readonly=on,file={ovmf_code}",
                "-drive", f"if=pflash,format=raw,file={ovmf_vars_vm}"
            ])

        # Add TPM 2.0 if swtpm is running
        if tpm_socket:
            qemu_cmd.extend([
                "-chardev", f"socket,id=chrtpm,path={tpm_socket}",
                "-tpmdev", "emulator,id=tpm0,chardev=chrtpm",
                "-device", "tpm-tis,tpmdev=tpm0"
            ])

        # Add ISOs - main installation ISO and secondary ISO (drivers, tools, etc.)
        has_iso = vm.get('iso_path') and os.path.exists(vm['iso_path'])
        has_secondary_iso = vm.get('secondary_iso_path') and os.path.exists(vm['secondary_iso_path'])

        is_windows = vm.get('os_type') == 'windows'
        has_spice_tools = self.spice_tools_iso.exists()

        cd_index = 0
        if has_iso:
            qemu_cmd.extend([
                "-drive", f"file={vm['iso_path']},media=cdrom,index={cd_index}"
            ])
            cd_index += 1
        if has_secondary_iso:
            qemu_cmd.extend([
                "-drive", f"file={vm['secondary_iso_path']},media=cdrom,index={cd_index}"
            ])
            cd_index += 1
        # Auto-mount spice-guest-tools for Windows VMs on every boot
        if is_windows and has_spice_tools:
            qemu_cmd.extend([
                "-drive", f"file={self.spice_tools_iso},media=cdrom,index={cd_index},readonly=on"
            ])

        # Add boot order
        boot_order = vm.get('boot_order', ['disk', 'cdrom'])
        qemu_cmd.extend(self._build_boot_order_args(boot_order, has_iso))

        qemu_cmd.extend(["-pidfile", str(pid_file)])

        # Process macvtap placeholders and create interfaces
        macvtap_fds = []
        final_cmd = []
        for arg in qemu_cmd:
            if arg.startswith("__MACVTAP_"):
                # Parse: __MACVTAP_{idx}_{parent}_{model}_{mac}__
                parts = arg.strip("_").split("_")
                if len(parts) >= 5:
                    idx = parts[1]
                    parent_iface = parts[2]
                    nic_model = parts[3]
                    mac = parts[4]
                    if len(parts) > 5:  # MAC has colons which were split
                        mac = ":".join(parts[4:])
                        mac = mac.rstrip("_")

                    macvtap_name = f"mvt{vm_id[:6]}{idx}"
                    tap_index = self._create_macvtap(macvtap_name, parent_iface, mac)

                    if tap_index:
                        tap_dev = f"/dev/tap{tap_index}"
                        # Open the tap device and keep fd
                        fd = os.open(tap_dev, os.O_RDWR)
                        macvtap_fds.append(fd)
                        final_cmd.extend(["-netdev", f"tap,id=net{idx},fd={fd}"])
                        final_cmd.extend(["-device", f"{nic_model},netdev=net{idx},mac={mac}"])
                    else:
                        raise Exception(f"Failed to create macvtap interface for {parent_iface}")
            else:
                final_cmd.append(arg)

        qemu_cmd = final_cmd

        try:
            # Run QEMU and capture any immediate errors
            # Pass macvtap fds if any were created
            run_kwargs = {
                'check': True,
                'capture_output': True,
                'text': True
            }
            if macvtap_fds:
                run_kwargs['pass_fds'] = tuple(macvtap_fds)

            result = subprocess.run(qemu_cmd, **run_kwargs)

            # Close macvtap fds after QEMU has inherited them
            for fd in macvtap_fds:
                try:
                    os.close(fd)
                except OSError:
                    pass

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

        # Stop SPICE proxy if running
        self.spice_proxy_manager.stop_proxy(vm_id)
        vm['spice_ws_port'] = None
        vm['spice_proxy_pid'] = None

        # Stop VNC proxy if running (legacy)
        self.vnc_proxy_manager.stop_proxy(vm_id)
        vm['ws_port'] = None
        vm['ws_proxy_pid'] = None

        # Stop TPM emulator
        vm_dir = self.vms_dir / vm_id
        self._stop_swtpm(vm_id, vm_dir)

        # Clean up macvtap interfaces
        self._cleanup_vm_macvtaps(vm_id)

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

        # Stop VM if running (this also stops the proxy and TPM)
        self.stop_vm(vm_id)

        # Cleanup VNC proxy
        self.vnc_proxy_manager.stop_proxy(vm_id)

        # Cleanup TPM
        vm_dir = self.vms_dir / vm_id
        self._stop_swtpm(vm_id, vm_dir)

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
            logger.warning(f"Error getting bridges: {e}")
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

    def get_available_interfaces(self) -> List[Dict]:
        """Get list of physical network interfaces for macvtap"""
        interfaces = []
        try:
            result = subprocess.run(
                ["ip", "-j", "link", "show"],
                capture_output=True, text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                import json as json_module
                iface_data = json_module.loads(result.stdout)
                for iface in iface_data:
                    name = iface.get('ifname', '')
                    # Skip loopback, virtual, and docker interfaces
                    if name in ('lo',) or name.startswith(('veth', 'docker', 'br-', 'virbr', 'macvtap')):
                        continue
                    # Skip bridges (handled separately)
                    link_type = iface.get('link_type', '')
                    if link_type == 'bridge':
                        continue
                    state = iface.get('operstate', 'unknown').lower()
                    # Only show interfaces that are up or could be used
                    if state in ('up', 'down', 'unknown'):
                        interfaces.append({
                            'name': name,
                            'state': state,
                            'active': state == 'up'
                        })
        except Exception as e:
            logger.warning(f"Error getting interfaces: {e}")

        return sorted(interfaces, key=lambda x: (not x['active'], x['name']))

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
        if 'secondary_iso_path' in updates:
            # Validate secondary ISO exists if provided
            if updates['secondary_iso_path'] and not os.path.exists(updates['secondary_iso_path']):
                raise ValueError(f"Secondary ISO file not found: {updates['secondary_iso_path']}")
            vm['secondary_iso_path'] = updates['secondary_iso_path']

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
        if 'os_type' in updates and updates['os_type'] is not None:
            vm['os_type'] = updates['os_type']

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

    def get_spice_connection(self, vm_id: str) -> Dict:
        """Get SPICE connection info for a VM.
        Console access is now proxied through the main FastAPI server
        via /ws/spice/{vm_id}, so external websockify ports are no longer needed.
        """
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        vm = self.vms[vm_id]
        self._update_vm_status(vm_id)

        if vm['status'] != VMStatus.RUNNING.value:
            raise ValueError(f"VM is not running (status: {vm['status']})")

        spice_port = vm.get('spice_port')
        if not spice_port:
            raise ValueError("VM does not have SPICE port configured")

        # Verify the SPICE port is actually listening
        if not self._is_port_in_use(spice_port):
            raise ValueError(f"SPICE port {spice_port} is not responding. The VM display may not be ready yet.")

        return {
            'spice_port': spice_port,
            'ws_url': f"/ws/spice/{vm_id}",
            'status': 'ready'
        }

    def get_spice_tools_status(self) -> Dict:
        """Check if spice-guest-tools ISO is available"""
        exists = self.spice_tools_iso.exists()
        return {
            'available': exists,
            'path': str(self.spice_tools_iso) if exists else None,
            'download_url': 'https://www.spice-space.org/download/windows/spice-guest-tools/spice-guest-tools-latest.exe'
        }

    def download_spice_guest_tools(self) -> Dict:
        """Download spice-guest-tools ISO for Windows VMs"""
        if self.spice_tools_iso.exists():
            return {'status': 'already_exists', 'path': str(self.spice_tools_iso)}

        self.spice_tools_iso.parent.mkdir(parents=True, exist_ok=True)
        url = 'https://www.spice-space.org/download/windows/spice-guest-tools/spice-guest-tools-latest.exe'
        tmp_path = self.spice_tools_iso.parent / "spice-guest-tools-latest.exe"

        try:
            import urllib.request
            logger.info(f"Downloading spice-guest-tools from {url}")
            urllib.request.urlretrieve(url, str(tmp_path))

            # Create an ISO containing the exe for easy mounting in Windows VMs
            for tool in ["genisoimage", "mkisofs", "xorriso"]:
                try:
                    if tool == "xorriso":
                        cmd = [tool, "-as", "genisoimage"]
                    else:
                        cmd = [tool]
                    cmd.extend([
                        "-o", str(self.spice_tools_iso),
                        "-volid", "SPICE_TOOLS",
                        "-joliet", "-rock",
                        str(tmp_path)
                    ])
                    subprocess.run(cmd, check=True, capture_output=True, text=True)
                    tmp_path.unlink(missing_ok=True)
                    return {'status': 'downloaded', 'path': str(self.spice_tools_iso)}
                except (subprocess.CalledProcessError, FileNotFoundError):
                    continue

            # No ISO tool available - keep the exe as-is renamed to .iso
            # QEMU can still mount it, but Windows won't auto-see it as a CDROM
            tmp_path.unlink(missing_ok=True)
            raise ValueError("No ISO generation tool found (genisoimage/mkisofs/xorriso)")

        except Exception as e:
            tmp_path.unlink(missing_ok=True)
            raise ValueError(f"Failed to download spice-guest-tools: {e}")

    # ==================== Clone ====================

    def clone_vm(self, vm_id: str, name: str, memory: Optional[int] = None, cpus: Optional[int] = None) -> VMInfo:
        """Clone a VM (must be stopped)"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        source_vm = self.vms[vm_id]
        self._update_vm_status(vm_id)

        if source_vm['status'] == VMStatus.RUNNING.value:
            raise ValueError("Cannot clone a running VM. Stop it first.")

        # Create new VM directory
        new_vm_id = str(uuid.uuid4())
        new_vm_dir = self.vms_dir / new_vm_id
        new_vm_dir.mkdir(parents=True, exist_ok=True)

        new_disk_path = new_vm_dir / "disk.qcow2"

        # Clone the disk (full copy)
        source_disk = source_vm.get('disk_path')
        if not source_disk or not os.path.exists(source_disk):
            raise ValueError("Source VM disk not found")

        subprocess.run([
            "qemu-img", "create", "-f", "qcow2",
            "-b", source_disk, "-F", "qcow2",
            str(new_disk_path)
        ], check=True, capture_output=True, text=True)

        # Copy OVMF_VARS if exists
        source_dir = self.vms_dir / vm_id
        source_ovmf = source_dir / "OVMF_VARS.fd"
        if source_ovmf.exists():
            shutil.copy(source_ovmf, new_vm_dir / "OVMF_VARS.fd")

        vnc_port = self._get_free_vnc_port()
        spice_port = self._get_free_spice_port()

        # Build new networks with fresh MACs
        new_networks = []
        for net in source_vm.get('networks', []):
            new_net = dict(net)
            new_net['id'] = str(uuid.uuid4())
            new_net['mac_address'] = self._generate_mac_address()
            new_networks.append(new_net)

        new_vm_config = {
            'id': new_vm_id,
            'name': name,
            'memory': memory or source_vm['memory'],
            'cpus': cpus or source_vm['cpus'],
            'disk_size': source_vm['disk_size'],
            'disk_path': str(new_disk_path),
            'iso_path': source_vm.get('iso_path'),
            'secondary_iso_path': source_vm.get('secondary_iso_path'),
            'vnc_port': vnc_port,
            'spice_port': spice_port,
            'status': VMStatus.STOPPED.value,
            'pid': None,
            'networks': new_networks,
            'volumes': [],
            'boot_order': source_vm.get('boot_order', ['disk', 'cdrom']),
            'cpu_model': source_vm.get('cpu_model', 'host'),
            'display_type': source_vm.get('display_type', 'qxl'),
            'os_type': source_vm.get('os_type', 'linux')
        }

        self.vms[new_vm_id] = new_vm_config
        self._save_vms()

        return VMInfo(**new_vm_config)

    # ==================== Cloud-init ====================

    def create_cloudinit_iso(self, config: CloudInitConfig) -> str:
        """Create a cloud-init ISO with user-data and meta-data"""
        # Create temp directory for cloud-init files
        ci_dir = tempfile.mkdtemp(prefix="cloudinit_")

        try:
            # meta-data
            meta_data = f"instance-id: {uuid.uuid4()}\nlocal-hostname: {config.hostname}\n"
            with open(os.path.join(ci_dir, "meta-data"), 'w') as f:
                f.write(meta_data)

            # user-data
            user_data_lines = ["#cloud-config"]
            user_data_lines.append(f"hostname: {config.hostname}")
            user_data_lines.append(f"manage_etc_hosts: true")

            # User config
            user_data_lines.append("users:")
            user_data_lines.append(f"  - name: {config.username}")
            user_data_lines.append(f"    sudo: ALL=(ALL) NOPASSWD:ALL")
            user_data_lines.append(f"    shell: /bin/bash")
            user_data_lines.append(f"    lock_passwd: false")
            if config.password:
                user_data_lines.append(f"    plain_text_passwd: '{config.password}'")
            if config.ssh_authorized_keys:
                user_data_lines.append(f"    ssh_authorized_keys:")
                for key in config.ssh_authorized_keys:
                    user_data_lines.append(f"      - {key}")

            # Packages
            if config.packages:
                user_data_lines.append("packages:")
                for pkg in config.packages:
                    user_data_lines.append(f"  - {pkg}")

            # Run commands
            user_data_lines.append("runcmd:")
            user_data_lines.append("  - apt-get install -y spice-vdagent qemu-guest-agent 2>/dev/null || yum install -y spice-vdagent qemu-guest-agent 2>/dev/null || true")
            user_data_lines.append("  - systemctl enable --now spice-vdagent 2>/dev/null || true")
            user_data_lines.append("  - systemctl enable --now qemu-guest-agent 2>/dev/null || true")
            for cmd in config.runcmd:
                user_data_lines.append(f"  - {cmd}")

            user_data_lines.append("power_state:")
            user_data_lines.append("  mode: reboot")
            user_data_lines.append("  condition: true")

            with open(os.path.join(ci_dir, "user-data"), 'w') as f:
                f.write('\n'.join(user_data_lines) + '\n')

            # network-config (if static IP specified)
            if config.static_ip:
                net_config_lines = [
                    "version: 2",
                    "ethernets:",
                    "  id0:",
                    "    match:",
                    "      name: 'en*'",
                    f"    addresses: [{config.static_ip}]",
                ]
                if config.gateway:
                    net_config_lines.append(f"    gateway4: {config.gateway}")
                if config.dns:
                    net_config_lines.append("    nameservers:")
                    net_config_lines.append(f"      addresses: [{', '.join(config.dns)}]")

                with open(os.path.join(ci_dir, "network-config"), 'w') as f:
                    f.write('\n'.join(net_config_lines) + '\n')

            # Generate ISO
            iso_path = self.vms_dir.parent / "images" / f"cloudinit-{config.hostname}.iso"
            iso_path.parent.mkdir(parents=True, exist_ok=True)

            # Try genisoimage first, fall back to mkisofs
            for tool in ["genisoimage", "mkisofs"]:
                try:
                    cmd = [
                        tool,
                        "-output", str(iso_path),
                        "-volid", "cidata",
                        "-joliet",
                        "-rock",
                        os.path.join(ci_dir, "meta-data"),
                        os.path.join(ci_dir, "user-data"),
                    ]
                    # Add network-config if exists
                    nc_path = os.path.join(ci_dir, "network-config")
                    if os.path.exists(nc_path):
                        cmd.append(nc_path)

                    subprocess.run(cmd, check=True, capture_output=True, text=True)
                    return str(iso_path)
                except (subprocess.CalledProcessError, FileNotFoundError):
                    continue

            # Fallback: try xorriso
            try:
                cmd = [
                    "xorriso", "-as", "genisoimage",
                    "-output", str(iso_path),
                    "-volid", "cidata",
                    "-joliet",
                    "-rock",
                    os.path.join(ci_dir, "meta-data"),
                    os.path.join(ci_dir, "user-data"),
                ]
                nc_path = os.path.join(ci_dir, "network-config")
                if os.path.exists(nc_path):
                    cmd.append(nc_path)
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                return str(iso_path)
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

            raise ValueError(
                "No ISO generation tool found. Install genisoimage: "
                "sudo apt install genisoimage"
            )

        finally:
            # Cleanup temp dir
            shutil.rmtree(ci_dir, ignore_errors=True)

    # ==================== Metrics ====================

    def get_vm_metrics(self, vm_id: str) -> Dict:
        """Get real-time metrics for a running VM"""
        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        vm = self.vms[vm_id]
        self._update_vm_status(vm_id)

        if vm['status'] != VMStatus.RUNNING.value:
            raise ValueError("VM is not running")

        pid = vm.get('pid')
        if not pid:
            raise ValueError("VM process not found")

        try:
            # Reuse Process object for accurate cpu_percent across calls
            if vm_id not in self._metric_procs or self._metric_procs[vm_id].pid != pid:
                proc = psutil.Process(pid)
                self._metric_procs[vm_id] = proc
                proc.cpu_percent(interval=0)  # prime baseline
                # Prime I/O baseline
                try:
                    io = proc.io_counters()
                    self._metric_prev_io[vm_id] = (io.read_bytes, io.write_bytes)
                except (psutil.AccessDenied, AttributeError):
                    self._metric_prev_io[vm_id] = (0, 0)

            proc = self._metric_procs[vm_id]

            # CPU usage (sum parent + children for full QEMU)
            cpu_percent = proc.cpu_percent(interval=0)
            try:
                for child in proc.children(recursive=True):
                    cpu_percent += child.cpu_percent(interval=0)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            # Memory info
            mem_info = proc.memory_info()
            mem_rss_mb = mem_info.rss / (1024 * 1024)

            # I/O delta since last call
            io_read_mb = 0.0
            io_write_mb = 0.0
            try:
                io = proc.io_counters()
                prev_r, prev_w = self._metric_prev_io.get(vm_id, (io.read_bytes, io.write_bytes))
                io_read_mb = max(io.read_bytes - prev_r, 0) / (1024 * 1024)
                io_write_mb = max(io.write_bytes - prev_w, 0) / (1024 * 1024)
                self._metric_prev_io[vm_id] = (io.read_bytes, io.write_bytes)
            except (psutil.AccessDenied, AttributeError):
                pass

            # Configured resources
            configured_mem_mb = vm.get('memory', 0)

            return {
                "vm_id": vm_id,
                "status": "running",
                "cpu_percent": round(cpu_percent, 1),
                "cpu_count": vm.get('cpus', 1),
                "memory_used_mb": round(mem_rss_mb, 1),
                "memory_configured_mb": configured_mem_mb,
                "memory_percent": round((mem_rss_mb / configured_mem_mb * 100), 1) if configured_mem_mb > 0 else 0,
                "io_read_mb": round(io_read_mb, 2),
                "io_write_mb": round(io_write_mb, 2),
            }
        except psutil.NoSuchProcess:
            self._metric_procs.pop(vm_id, None)
            self._metric_prev_io.pop(vm_id, None)
            raise ValueError("VM process no longer running")

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

    # ==================== Backup & Restore ====================

    def backup_vm(self, vm_id: str) -> Dict:
        """Backup a VM (must be stopped). Creates a tar.gz with config + disk."""
        import tarfile

        if vm_id not in self.vms:
            raise ValueError(f"VM {vm_id} not found")

        vm = self.vms[vm_id]
        self._update_vm_status(vm_id)

        if vm['status'] == VMStatus.RUNNING.value:
            raise ValueError("Cannot backup a running VM. Stop it first.")

        disk_path = vm.get('disk_path')
        if not disk_path or not os.path.exists(disk_path):
            raise ValueError("VM disk not found")

        vm_dir = self.vms_dir / vm_id
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[^\w\-.]', '_', vm['name'])
        backup_name = f"{safe_name}_{timestamp}.tar.gz"
        backup_path = self.backups_dir / backup_name

        # Write VM config to a temp file
        config_path = vm_dir / "vm_config.json"
        with open(config_path, 'w') as f:
            json.dump(vm, f, indent=2)

        try:
            with tarfile.open(backup_path, "w:gz") as tar:
                # Add config
                tar.add(str(config_path), arcname="vm_config.json")
                # Add disk
                tar.add(disk_path, arcname="disk.qcow2")
                # Add OVMF_VARS if exists
                ovmf_vars = vm_dir / "OVMF_VARS.fd"
                if ovmf_vars.exists():
                    tar.add(str(ovmf_vars), arcname="OVMF_VARS.fd")
        finally:
            # Clean up temp config
            if config_path.exists():
                config_path.unlink()

        size_mb = round(backup_path.stat().st_size / (1024 * 1024), 1)
        logger.info(f"Backup created: {backup_name} ({size_mb} MB)")

        return {
            "backup_name": backup_name,
            "backup_path": str(backup_path),
            "size_mb": size_mb,
            "vm_name": vm['name']
        }

    def restore_vm(self, backup_path: str, new_name: str = None) -> VMInfo:
        """Restore a VM from a backup tar.gz"""
        import tarfile

        if not os.path.exists(backup_path):
            raise ValueError(f"Backup file not found: {backup_path}")

        new_vm_id = str(uuid.uuid4())
        new_vm_dir = self.vms_dir / new_vm_id
        new_vm_dir.mkdir(parents=True, exist_ok=True)

        try:
            with tarfile.open(backup_path, "r:gz") as tar:
                # Security: validate no path traversal
                for member in tar.getmembers():
                    if member.name.startswith('/') or '..' in member.name:
                        raise ValueError("Invalid backup: contains unsafe paths")

                tar.extractall(path=str(new_vm_dir))

            # Read config
            config_path = new_vm_dir / "vm_config.json"
            if not config_path.exists():
                raise ValueError("Invalid backup: missing vm_config.json")

            with open(config_path, 'r') as f:
                vm_config = json.load(f)

            # Update with new identity
            new_disk_path = new_vm_dir / "disk.qcow2"
            vm_config['id'] = new_vm_id
            vm_config['name'] = new_name or (vm_config.get('name', 'Restored') + ' (restored)')
            vm_config['disk_path'] = str(new_disk_path)
            vm_config['status'] = VMStatus.STOPPED.value
            vm_config['pid'] = None
            vm_config['vnc_port'] = self._get_free_vnc_port()
            vm_config['spice_port'] = self._get_free_spice_port()
            vm_config['ws_port'] = None
            vm_config['ws_proxy_pid'] = None
            vm_config['spice_ws_port'] = None
            vm_config['spice_proxy_pid'] = None

            # Generate new MAC addresses
            for net in vm_config.get('networks', []):
                net['id'] = str(uuid.uuid4())
                net['mac_address'] = self._generate_mac_address()

            # Clean up volumes reference (don't carry over)
            vm_config['volumes'] = []

            # Clean up temp config
            config_path.unlink()

            self.vms[new_vm_id] = vm_config
            self._save_vms()

            logger.info(f"VM restored from backup: {vm_config['name']} ({new_vm_id})")
            return VMInfo(**vm_config)

        except Exception as e:
            # Clean up on failure
            if new_vm_dir.exists():
                shutil.rmtree(new_vm_dir)
            raise

    def list_backups(self) -> list:
        """List available backup files"""
        backups = []
        for f in sorted(self.backups_dir.glob("*.tar.gz"), reverse=True):
            try:
                stat = f.stat()
                backups.append({
                    "name": f.name,
                    "path": str(f),
                    "size_mb": round(stat.st_size / (1024 * 1024), 1),
                    "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
            except Exception:
                continue
        return backups
