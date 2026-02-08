"""
SQLite database for metrics persistence and audit logging
"""
import sqlite3
import os
import json
import logging
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger("fast_vm.database")

DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DB_DIR / "fast_vm.db"


def init_db():
    """Initialize the SQLite database and create tables"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS metrics_host (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                cpu_percent REAL,
                memory_percent REAL
            );

            CREATE TABLE IF NOT EXISTS metrics_vm (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                vm_id TEXT NOT NULL,
                cpu_percent REAL,
                memory_mb REAL,
                memory_percent REAL,
                io_read_mb REAL,
                io_write_mb REAL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                details TEXT,
                ip_address TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_metrics_host_ts ON metrics_host(timestamp);
            CREATE INDEX IF NOT EXISTS idx_metrics_vm_ts ON metrics_vm(timestamp);
            CREATE INDEX IF NOT EXISTS idx_metrics_vm_id ON metrics_vm(vm_id);
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(username);
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
        """)
    logger.info(f"Database initialized at {DB_PATH}")


@contextmanager
def get_connection():
    """Context manager for SQLite connections"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save_host_metrics(timestamp: str, cpu_percent: float, memory_percent: float):
    """Save host metrics to database"""
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO metrics_host (timestamp, cpu_percent, memory_percent) VALUES (?, ?, ?)",
                (timestamp, cpu_percent, memory_percent)
            )
    except Exception as e:
        logger.error(f"Error saving host metrics: {e}")


def save_vm_metrics(timestamp: str, vm_id: str, cpu: float, mem_mb: float, mem_pct: float, io_r: float, io_w: float):
    """Save VM metrics to database"""
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO metrics_vm (timestamp, vm_id, cpu_percent, memory_mb, memory_percent, io_read_mb, io_write_mb) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (timestamp, vm_id, cpu, mem_mb, mem_pct, io_r, io_w)
            )
    except Exception as e:
        logger.error(f"Error saving VM metrics: {e}")


def get_extended_metrics(hours: int = 24, vm_id: str = None):
    """Get metrics history from SQLite for extended time range"""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    result = {"host": [], "vms": {}}

    try:
        with get_connection() as conn:
            # Host metrics
            rows = conn.execute(
                "SELECT timestamp, cpu_percent, memory_percent FROM metrics_host WHERE timestamp > ? ORDER BY timestamp",
                (cutoff,)
            ).fetchall()
            result["host"] = [{"t": r["timestamp"], "cpu": r["cpu_percent"], "mem": r["memory_percent"]} for r in rows]

            # VM metrics
            if vm_id:
                vm_rows = conn.execute(
                    "SELECT timestamp, vm_id, cpu_percent, memory_mb, memory_percent, io_read_mb, io_write_mb FROM metrics_vm WHERE timestamp > ? AND vm_id = ? ORDER BY timestamp",
                    (cutoff, vm_id)
                ).fetchall()
            else:
                vm_rows = conn.execute(
                    "SELECT timestamp, vm_id, cpu_percent, memory_mb, memory_percent, io_read_mb, io_write_mb FROM metrics_vm WHERE timestamp > ? ORDER BY timestamp",
                    (cutoff,)
                ).fetchall()

            for r in vm_rows:
                vid = r["vm_id"]
                if vid not in result["vms"]:
                    result["vms"][vid] = []
                result["vms"][vid].append({
                    "t": r["timestamp"],
                    "cpu": r["cpu_percent"],
                    "mem_mb": r["memory_mb"],
                    "mem_pct": r["memory_percent"],
                    "io_r": r["io_read_mb"],
                    "io_w": r["io_write_mb"]
                })
    except Exception as e:
        logger.error(f"Error getting extended metrics: {e}")

    return result


def cleanup_old_metrics(hours: int = 24):
    """Delete metrics older than specified hours"""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM metrics_host WHERE timestamp < ?", (cutoff,))
            conn.execute("DELETE FROM metrics_vm WHERE timestamp < ?", (cutoff,))
    except Exception as e:
        logger.error(f"Error cleaning up old metrics: {e}")
