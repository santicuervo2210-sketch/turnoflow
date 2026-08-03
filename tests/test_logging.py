import json
import logging

from app.core.logging import JsonFormatter, build_error_log_payload


def test_error_log_payload_is_structured_without_sensitive_request_data() -> None:
    payload = build_error_log_payload("POST", "/login", ValueError("password=secret"))

    assert payload["event"] == "unhandled_error"
    assert payload["method"] == "POST"
    assert payload["path"] == "/login"
    assert payload["exception_type"] == "ValueError"
    assert "password" not in json.dumps(payload).lower()
    assert "secret" not in json.dumps(payload).lower()


def test_json_formatter_outputs_valid_json() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="turnoflow.errors",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="unhandled_error",
        args=(),
        exc_info=None,
    )
    record.structured_payload = {"event": "unhandled_error", "path": "/admin"}

    formatted = json.loads(formatter.format(record))

    assert formatted["level"] == "ERROR"
    assert formatted["event"] == "unhandled_error"
    assert formatted["path"] == "/admin"
