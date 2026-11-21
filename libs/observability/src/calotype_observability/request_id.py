"""request_id propagation via contextvars.

API middleware sets request_id per HTTP request.
Workers set it from envelope.trace_context["request_id"].
A logging.Filter injects it into every log record automatically.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    return _request_id_var.get()


def set_request_id(value: str) -> None:
    _request_id_var.set(value)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


class RequestIdFilter(logging.Filter):
    """Injects the current request_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.request_id = get_request_id()  # type: ignore[attr-defined]
        return True
