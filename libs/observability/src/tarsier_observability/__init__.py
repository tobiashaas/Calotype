"""Lightweight logging façade for services and workers."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from tarsier_observability.heartbeat import start_heartbeat_thread
from tarsier_observability.json_formatter import JsonFormatter
from tarsier_observability.request_id import (
    RequestIdFilter,
    get_request_id,
    new_request_id,
    set_request_id,
)

__all__ = [
    "get_logger",
    "log_kv",
    "configure_logging",
    "start_heartbeat_thread",
    "get_request_id",
    "set_request_id",
    "new_request_id",
]

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Set up root logger with JSON output.

    Call once at service/worker startup. Safe to call multiple times.
    Controlled by env var LOG_FORMAT=json (default) or LOG_FORMAT=text.
    """
    global _configured
    if _configured:
        return
    _configured = True

    log_format = os.environ.get("LOG_FORMAT", "json").lower()
    handler = logging.StreamHandler(sys.stdout)

    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))

    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger.  configure_logging() is called lazily if not done yet."""
    configure_logging()
    return logging.getLogger(name)


def log_kv(logger: logging.Logger, level: int, msg: str, **fields: Any) -> None:
    extra = " ".join(f"{k}={v!r}" for k, v in sorted(fields.items()))
    logger.log(level, "%s | %s", msg, extra)
