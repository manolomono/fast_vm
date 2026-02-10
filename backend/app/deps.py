"""Shared dependencies for Fast VM routers.

This module holds singleton instances and shared state that multiple
routers need to access, avoiding circular imports.
"""
from collections import deque
from .vm_manager import VMManager

# Singleton VM Manager
vm_manager = VMManager()

# WebSocket clients for real-time metrics
ws_clients: set = set()

# Metrics history buffer (keeps last 60 data points = 10 minutes at 10s intervals)
METRICS_HISTORY_SIZE = 60
metrics_history = {
    "host": deque(maxlen=METRICS_HISTORY_SIZE),
    "vms": {}  # vm_id -> deque of metrics
}
