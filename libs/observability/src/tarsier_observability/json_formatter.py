"""JSON log formatter — emits one JSON object per log record."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects.

    Output fields:
        ts       ISO-8601 UTC timestamp
        level    DEBUG / INFO / WARNING / ERROR / CRITICAL
        logger   Logger name
        msg      Log message
        request_id  (optional) from record if injected by RequestIdFilter
        exc      (optional) exception traceback string
        <extra>  any extra fields passed via logger.xxx(..., extra={...})
    """

    _SKIP = frozenset({
        "args", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "message", "module", "msecs", "msg",
        "name", "pathname", "process", "processName", "relativeCreated",
        "request_id", "stack_info", "taskName", "thread", "threadName",
    })

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        doc: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.message,
        }

        # request_id injected by RequestIdFilter
        if rid := getattr(record, "request_id", None):
            doc["request_id"] = rid

        # extra fields
        for key, val in record.__dict__.items():
            if key not in self._SKIP and not key.startswith("_"):
                doc[key] = val

        if record.exc_info:
            doc["exc"] = self.formatException(record.exc_info)
        elif record.exc_text:
            doc["exc"] = record.exc_text

        return json.dumps(doc, default=str)
