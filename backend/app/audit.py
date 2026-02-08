"""
Audit logging for Fast VM
"""
import json
import logging
from datetime import datetime
from .database import get_connection

logger = logging.getLogger("fast_vm.audit")


def log_action(username: str, action: str, resource_type: str = None,
               resource_id: str = None, details: dict = None, ip: str = None):
    """Log an audit action to the database"""
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO audit_log (timestamp, username, action, resource_type, resource_id, details, ip_address) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.utcnow().isoformat(),
                    username,
                    action,
                    resource_type,
                    resource_id,
                    json.dumps(details) if details else None,
                    ip
                )
            )
        logger.info(f"AUDIT: {username} {action} {resource_type or ''} {resource_id or ''}")
    except Exception as e:
        logger.error(f"Error logging audit action: {e}")


def get_audit_logs(limit: int = 100, offset: int = 0,
                   username: str = None, action: str = None):
    """Query audit logs with optional filters"""
    try:
        with get_connection() as conn:
            query = "SELECT * FROM audit_log WHERE 1=1"
            params = []

            if username:
                query += " AND username = ?"
                params.append(username)
            if action:
                query += " AND action = ?"
                params.append(action)

            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()

            # Get total count
            count_query = "SELECT COUNT(*) as cnt FROM audit_log WHERE 1=1"
            count_params = []
            if username:
                count_query += " AND username = ?"
                count_params.append(username)
            if action:
                count_query += " AND action = ?"
                count_params.append(action)

            total = conn.execute(count_query, count_params).fetchone()["cnt"]

            return {
                "total": total,
                "logs": [
                    {
                        "id": r["id"],
                        "timestamp": r["timestamp"],
                        "username": r["username"],
                        "action": r["action"],
                        "resource_type": r["resource_type"],
                        "resource_id": r["resource_id"],
                        "details": json.loads(r["details"]) if r["details"] else None,
                        "ip_address": r["ip_address"]
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        logger.error(f"Error querying audit logs: {e}")
        return {"total": 0, "logs": []}
