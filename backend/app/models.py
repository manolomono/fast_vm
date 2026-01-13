from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class VMStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


class VMCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    memory: int = Field(default=2048, ge=512, le=32768)
    cpus: int = Field(default=2, ge=1, le=16)
    disk_size: int = Field(default=20, ge=5, le=500)
    iso_path: Optional[str] = None


class VMInfo(BaseModel):
    id: str
    name: str
    status: VMStatus
    memory: int
    cpus: int
    disk_size: int
    pid: Optional[int] = None
    vnc_port: Optional[int] = None


class VMResponse(BaseModel):
    success: bool
    message: str
    vm: Optional[VMInfo] = None
