from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from app.core.config import settings

error_logger = logging.getLogger("turnoflow.errors")
request_logger = logging.getLogger("turnoflow.requests")


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


def build_error_log_payload(
    method: str,
    path: str,
    exc: Exception,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "event": "unhandled_error",
        "environment": settings.environment,
        "method": method,
        "path": path,
        "exception_type": type(exc).__name__,
        "request_id": request_id,
    }


def send_error_alert(payload: dict[str, Any]) -> None:
    webhook_url = settings.error_alert_webhook_url
    if not webhook_url or not webhook_url.startswith("https://"):
        return

    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        # The URL is restricted to HTTPS above; Bandit cannot infer that guard.
        urllib.request.urlopen(request, timeout=2).close()  # nosec B310
    except OSError:
        error_logger.warning("error_alert_delivery_failed")


def log_unhandled_error(method: str, path: str, exc: Exception, request_id: str | None = None) -> None:
    payload = build_error_log_payload(method, path, exc, request_id)
    error_logger.exception(
        "unhandled_error",
        extra={"structured_payload": payload},
    )
    send_error_alert(payload)


def log_request_completed(
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    request_id: str,
) -> None:
    request_logger.info(
        "request_completed",
        extra={
            "structured_payload": {
                "event": "request_completed",
                "environment": settings.environment,
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": round(duration_ms, 2),
                "request_id": request_id,
            }
        },
    )
