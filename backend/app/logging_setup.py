"""Dedicated app logger + rotating log file under backend/logs/."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging() -> logging.Logger:
    """
    Idempotent: safe to call on uvicorn reload. Logs go to stderr and
    backend/logs/spellbinder.log (rotates at ~1MB, 3 backups).
    """
    name = "spellbinder"
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    backend_dir = Path(__file__).resolve().parent.parent
    log_dir = backend_dir / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "spellbinder.log"

    fh = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def get_logger(suffix: str = "") -> logging.Logger:
    configure_logging()
    return logging.getLogger(f"spellbinder{suffix}" if suffix else "spellbinder")
