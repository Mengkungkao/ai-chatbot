"""Rotating file logging.

SD cards wear out, so this module is deliberately conservative:
rotation is on by default and display redraws are never logged.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False

_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _try_file_handler(path: Path, max_bytes: int, backup_count: int):
    """Return a handler for ``path``, or None when it is not writable."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
        return handler
    except (OSError, PermissionError):
        return None


def setup_logging(settings) -> logging.Logger:
    """Configure root logging once. Safe to call repeatedly."""
    global _CONFIGURED

    root = logging.getLogger()
    if _CONFIGURED:
        return logging.getLogger("whisplay-crypto")

    root.setLevel(getattr(logging, settings.log_level, logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    # Preferred path first (usually /var/log/whisplay-crypto), then a
    # per-user fallback so the app never dies over a permissions problem.
    handler = _try_file_handler(
        settings.log_path, settings.log_max_bytes, settings.log_backup_count
    )
    resolved_path = settings.log_path
    if handler is None:
        resolved_path = Path("~/.whisplay-crypto/app.log").expanduser()
        handler = _try_file_handler(
            resolved_path, settings.log_max_bytes, settings.log_backup_count
        )
    if handler is not None:
        root.addHandler(handler)

    # stdout goes to the daemon log when use_daemon_default_log is enabled.
    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    root.addHandler(stream)

    # Third-party libraries are far too chatty at INFO.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    _CONFIGURED = True
    log = logging.getLogger("whisplay-crypto")
    log.info("logging initialised (file=%s pid=%s)", resolved_path, os.getpid())
    return log


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"whisplay-crypto.{name}")
