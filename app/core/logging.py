from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from app.core.config import settings

error_logger = logging.getLogger("turnoflow.errors")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        structured_payload = getattr(record, "structured_payload", None)
        if isinstance(structured_payload, dict):
            payload.update(structured_payload)
        return json.dumps(payload, ensure_ascii=True, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def build_error_log_payload(method: str, path: str, exc: Exception) -> dict[str, Any]:
    return {
        "event": "unhandled_error",
        "environment": settings.environment,
        "method": method,
        "path": path,
        "exception_type": type(exc).__name__,
    }


def send_error_alert(payload: dict[str, Any]) -> None:
    if not settings.error_alert_webhook_url:
        return

    request = urllib.request.Request(
        settings.error_alert_webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=2).close()
    except OSError:
        error_logger.warning("error_alert_delivery_failed")


def log_unhandled_error(method: str, path: str, exc: Exception) -> None:
    payload = build_error_log_payload(method, path, exc)
    error_logger.exception(
        "unhandled_error",
        extra={"structured_payload": payload},
    )
    send_error_alert(payload)
