from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)

    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    return database_url


class Settings(BaseSettings):
    app_name: str = "TurnoFlow"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/turnoflow"
    auto_create_tables: bool = False
    bot_ai_provider: str = "rules"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_timeout_seconds: float = 8.0
    auth_enabled: bool = True
    admin_username: str = "admin"
    admin_password: str = "changeme"
    session_secret: str = "change-this-secret-before-deploy"
    bot_webhook_secret: str = ""
    error_alert_webhook_url: str | None = None
    login_rate_limit_per_minute: int = 30
    bot_webhook_rate_limit_per_minute: int = 120
    database_pool_mode: str = "serverless"
    cron_secret: str = ""
    bot_conversation_ttl_days: int = 30
    webhook_receipt_ttl_days: int = 30

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def sqlalchemy_database_url(self) -> str:
        return normalize_database_url(self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
