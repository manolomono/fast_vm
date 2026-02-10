from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal
from enum import Enum
from datetime import datetime
import uuid
import re


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


def _validate_password_strength(password: str) -> str:
    """Enforce password policy: min 8 chars, at least 1 upper, 1 lower, 1 digit"""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not re.search(r'[A-Z]', password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r'[a-z]', password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r'[0-9]', password):
        raise ValueError("Password must contain at least one digit")
    return password


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v):
        return _validate_password_strength(v)


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$')
    password: str = Field(..., min_length=8, max_length=128)
    is_admin: bool = False

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        return _validate_password_strength(v)


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
    bridge_name: Optional[str] = Field(None, pattern=r'^[a-zA-Z0-9_.-]{1,15}$')
    parent_interface: Optional[str] = Field(None, pattern=r'^[a-zA-Z0-9_.-]{1,15}$')
    mac_address: Optional[str] = Field(None, pattern=r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$')
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


def _validate_vm_name(name: str) -> str:
    """Validate VM name: alphanumeric, spaces, hyphens, underscores, dots only"""
    if not re.match(r'^[a-zA-Z0-9 _.\-]+$', name):
        raise ValueError("VM name can only contain letters, numbers, spaces, hyphens, underscores, and dots")
    return name


def _validate_path_safe(path: Optional[str]) -> Optional[str]:
    """Validate that a path doesn't contain traversal sequences"""
    if path is None:
        return None
    # Block path traversal
    if '..' in path or '\x00' in path:
        raise ValueError("Path contains invalid characters")
    # Must be an absolute path
    if not path.startswith('/'):
        raise ValueError("Path must be absolute")
    return path


# VM Models
class VMCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    memory: int = Field(default=2048, ge=512, le=32768)
    cpus: int = Field(default=2, ge=1, le=16)
    disk_size: int = Field(default=20, ge=5, le=500)
    iso_path: Optional[str] = None
    secondary_iso_path: Optional[str] = None  # Secondary CD-ROM (e.g., drivers ISO)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        return _validate_vm_name(v)

    @field_validator('iso_path', 'secondary_iso_path')
    @classmethod
    def validate_paths(cls, v):
        return _validate_path_safe(v)

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
    ws_port: Optional[int] = None  # Legacy: no longer needed with built-in proxy
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

    @field_validator('iso_path', 'secondary_iso_path')
    @classmethod
    def validate_paths(cls, v):
        return _validate_path_safe(v)


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

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        return _validate_vm_name(v)


# ==================== Cloud-init Models ====================

class CloudInitConfig(BaseModel):
    hostname: str = Field(..., min_length=1, max_length=63, pattern=r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?$')
    username: str = Field(default="user", min_length=1, max_length=32, pattern=r'^[a-z_][a-z0-9_-]*$')
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
