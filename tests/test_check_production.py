from app.check_production import configuration_errors
from app.core.config import settings


def test_configuration_errors_include_unsafe_production_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_enabled", False)
    monkeypatch.setattr(settings, "auto_create_tables", True)
    monkeypatch.setattr(settings, "admin_password", "changeme")
    monkeypatch.setattr(settings, "session_secret", "short")
    monkeypatch.setattr(settings, "bot_webhook_secret", "")
    monkeypatch.setattr(settings, "database_url", "sqlite+pysqlite:///./turnoflow.db")
    monkeypatch.setattr(settings, "login_rate_limit_per_minute", 0)
    monkeypatch.setattr(settings, "bot_webhook_rate_limit_per_minute", 0)
    monkeypatch.setattr(settings, "error_alert_webhook_url", "http://example.com/hook")

    errors = configuration_errors()

    assert any("AUTH_ENABLED" in error for error in errors)
    assert any("AUTO_CREATE_TABLES" in error for error in errors)
    assert any("ADMIN_PASSWORD" in error for error in errors)
    assert any("SESSION_SECRET" in error for error in errors)
    assert any("BOT_WEBHOOK_SECRET" in error for error in errors)
    assert any("PostgreSQL" in error for error in errors)
    assert any("LOGIN_RATE_LIMIT_PER_MINUTE" in error for error in errors)
    assert any("BOT_WEBHOOK_RATE_LIMIT_PER_MINUTE" in error for error in errors)
    assert any("ERROR_ALERT_WEBHOOK_URL" in error for error in errors)
