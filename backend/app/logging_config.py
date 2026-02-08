"""
Logging configuration for Fast VM
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging():
    """Configure application logging with rotating file handler"""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "fast_vm.log"

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Rotating file handler: 10MB max, 5 backups
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5
    )
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Configure root logger for app
    root_logger = logging.getLogger("fast_vm")
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return root_logger
