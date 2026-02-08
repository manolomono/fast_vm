from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from enum import Enum
from datetime import datetime
import uuid


# ==================== Auth Models ====================

class User(BaseModel):
    username: str
    hashed_password: str
    is_admin: bool = True


class LoginRequest(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    username: str
    is_admin: bool


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=4, max_length=128)


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=4, max_length=128)
    is_admin: bool = False


# ==================== VM Models ====================

class VMStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


# Network Models
class PortForward(BaseModel):
    host_port: int = Field(..., ge=1, le=65535)
    guest_port: int = Field(..., ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"


class NetworkConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: Literal["nat", "bridge", "macvtap", "isolated"] = "nat"
    model: Literal["virtio", "e1000", "rtl8139"] = "virtio"  # NIC model
    bridge_name: Optional[str] = None  # For bridge mode (e.g., br0, virbr0)
    parent_interface: Optional[str] = None  # For macvtap mode (e.g., eno1, eth0)
    mac_address: Optional[str] = None  # Auto-generated if not specified
    port_forwards: List[PortForward] = []  # For NAT mode


# Volume Models
class Volume(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., min_length=1, max_length=50)
    size_gb: int = Field(..., ge=1, le=1000)
    format: Literal["qcow2", "raw"] = "qcow2"
    path: Optional[str] = None  # Generated automatically
    attached_to: Optional[str] = None  # VM ID if attached


class VolumeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    size_gb: int = Field(..., ge=1, le=1000)
    format: Literal["qcow2", "raw"] = "qcow2"


# Snapshot Models
class Snapshot(BaseModel):
    id: str
    name: str = Field(..., min_length=1, max_length=50)
    created_at: datetime
    description: Optional[str] = None
    vm_size: Optional[str] = None  # Size of snapshot


class SnapshotCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = None


# VM Models
class VMCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    memory: int = Field(default=2048, ge=512, le=32768)
    cpus: int = Field(default=2, ge=1, le=16)
    disk_size: int = Field(default=20, ge=5, le=500)
    iso_path: Optional[str] = None
    secondary_iso_path: Optional[str] = None  # Secondary CD-ROM (e.g., drivers ISO)

    # Network configuration
    networks: List[NetworkConfig] = Field(default_factory=lambda: [NetworkConfig()])

    # Hardware options
    boot_order: List[Literal["disk", "cdrom", "network"]] = Field(
        default=["disk", "cdrom"]
    )
    cpu_model: Literal["host", "qemu64", "max", "Skylake-Client", "EPYC"] = "host"
    display_type: Literal["std", "virtio", "qxl", "cirrus"] = "qxl"  # QXL for SPICE


class VMInfo(BaseModel):
    id: str
    name: str
    status: VMStatus
    memory: int
    cpus: int
    disk_size: int
    disk_path: Optional[str] = None
    iso_path: Optional[str] = None
    secondary_iso_path: Optional[str] = None  # Secondary CD-ROM (e.g., drivers ISO)
    pid: Optional[int] = None

    # SPICE connection info
    spice_port: Optional[int] = None
    spice_ws_port: Optional[int] = None
    spice_proxy_pid: Optional[int] = None

    # Legacy VNC (deprecated, kept for migration)
    vnc_port: Optional[int] = None
    ws_port: Optional[int] = None
    ws_proxy_pid: Optional[int] = None

    # Network configuration
    networks: List[NetworkConfig] = []

    # Attached volumes (list of volume IDs)
    volumes: List[str] = []

    # Hardware options
    boot_order: List[str] = ["disk", "cdrom"]
    cpu_model: str = "host"
    display_type: str = "qxl"  # Default to QXL for SPICE


class VMResponse(BaseModel):
    success: bool
    message: str
    vm: Optional[VMInfo] = None


class VNCConnectionInfo(BaseModel):
    ws_port: int
    ws_url: str
    vnc_port: int
    status: str


class SpiceConnectionInfo(BaseModel):
    spice_port: int
    ws_port: int
    ws_url: str
    status: str


class VMUpdate(BaseModel):
    memory: Optional[int] = Field(None, ge=512, le=32768)
    cpus: Optional[int] = Field(None, ge=1, le=16)
    iso_path: Optional[str] = None
    secondary_iso_path: Optional[str] = None  # Secondary CD-ROM (e.g., drivers ISO)

    # Network configuration
    networks: Optional[List[NetworkConfig]] = None

    # Hardware options
    boot_order: Optional[List[Literal["disk", "cdrom", "network"]]] = None
    cpu_model: Optional[Literal["host", "qemu64", "max", "Skylake-Client", "EPYC"]] = None
    display_type: Optional[Literal["std", "virtio", "qxl", "cirrus"]] = None


# Response models for volumes and snapshots
class VolumeResponse(BaseModel):
    success: bool
    message: str
    volume: Optional[Volume] = None


class SnapshotResponse(BaseModel):
    success: bool
    message: str
    snapshot: Optional[Snapshot] = None


# ==================== Clone Models ====================

class VMClone(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    memory: Optional[int] = Field(None, ge=512, le=32768)
    cpus: Optional[int] = Field(None, ge=1, le=16)


# ==================== Cloud-init Models ====================

class CloudInitConfig(BaseModel):
    hostname: str = Field(..., min_length=1, max_length=63)
    username: str = Field(default="user", min_length=1, max_length=32)
    password: Optional[str] = Field(None, min_length=1, max_length=128)
    ssh_authorized_keys: List[str] = []
    packages: List[str] = []
    runcmd: List[str] = []
    static_ip: Optional[str] = None  # e.g. "192.168.1.100/24"
    gateway: Optional[str] = None
    dns: List[str] = ["8.8.8.8", "8.8.4.4"]


# ==================== Audit Models ====================

class AuditLogEntry(BaseModel):
    id: int
    timestamp: str
    username: str
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[dict] = None
    ip_address: Optional[str] = None


class AuditLogResponse(BaseModel):
    total: int
    logs: List[AuditLogEntry]
