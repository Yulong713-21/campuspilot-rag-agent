from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import sys
from typing import Any

from .runtime_context import current_request_id


RUNTIME_LOGGER_NAME = "campuspilot.runtime"


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = dict(getattr(record, "runtime_fields", {}))
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": fields.pop("event", "runtime_log"),
            "request_id": fields.pop("request_id", None) or current_request_id(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(fields)
        if record.exc_info:
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_runtime_logging(level: str | int | None = None) -> logging.Logger:
    logger = logging.getLogger(RUNTIME_LOGGER_NAME)
    configured = any(
        getattr(handler, "campuspilot_json_handler", False)
        for handler in logger.handlers
    )
    if not configured:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonLineFormatter())
        handler.campuspilot_json_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    configured_level = level or "INFO"
    logger.setLevel(configured_level)
    logger.propagate = False
    return logger


def runtime_logger(name: str) -> logging.Logger:
    configure_runtime_logging()
    return logging.getLogger(f"{RUNTIME_LOGGER_NAME}.{name}")


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    message: str | None = None,
    **fields: Any,
) -> None:
    logger.log(
        level,
        message or event,
        extra={"runtime_fields": {"event": event, **fields}},
    )
