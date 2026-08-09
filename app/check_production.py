from __future__ import annotations

from sqlalchemy import text

from app.core.config import settings
from app.db.session import build_engine
from app.models import User, UserRole
from app.db.session import SessionLocal

LATEST_ALEMBIC_REVISION = "20260809_0012"


def _fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def configuration_errors() -> list[str]:
    errors: list[str] = []

    if not settings.auth_enabled:
        errors.append("AUTH_ENABLED debe estar en true antes de exponer la demo.")

    if settings.auto_create_tables:
        errors.append("AUTO_CREATE_TABLES debe estar en false en produccion; usa Alembic.")

    if settings.admin_password in {"changeme", "change-me-before-deploy"}:
        errors.append("ADMIN_PASSWORD sigue usando un valor de ejemplo.")

    if len(settings.session_secret) < 32 or settings.session_secret == "change-this-secret-before-deploy":  # nosec B105
        errors.append("SESSION_SECRET debe ser largo, aleatorio y distinto al ejemplo.")

    if not settings.bot_webhook_secret or len(settings.bot_webhook_secret) < 32:
        errors.append("BOT_WEBHOOK_SECRET debe existir y tener al menos 32 caracteres.")

    if settings.sqlalchemy_database_url.startswith("sqlite"):
        errors.append("Para deploy usa PostgreSQL, no SQLite.")

    if settings.login_rate_limit_per_minute <= 0:
        errors.append("LOGIN_RATE_LIMIT_PER_MINUTE debe ser mayor a 0.")

    if settings.bot_webhook_rate_limit_per_minute <= 0:
        errors.append("BOT_WEBHOOK_RATE_LIMIT_PER_MINUTE debe ser mayor a 0.")

    if settings.error_alert_webhook_url and not settings.error_alert_webhook_url.startswith("https://"):
        errors.append("ERROR_ALERT_WEBHOOK_URL debe ser HTTPS si se configura.")

    return errors


def main() -> None:
    if settings.environment != "production":
        print("WARN: ENVIRONMENT no esta en production.")

    errors = configuration_errors()
    if errors:
        _fail(errors[0])

    engine = build_engine(settings.sqlalchemy_database_url)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        alembic_revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        if alembic_revision != LATEST_ALEMBIC_REVISION:
            _fail(f"Alembic no esta en head ({LATEST_ALEMBIC_REVISION}). Revision actual: {alembic_revision}.")
        overlap_constraint_exists = connection.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'ex_appointments_no_active_overlap'
                )
                """
            )
        ).scalar()
        if not overlap_constraint_exists:
            _fail("Falta el constraint ex_appointments_no_active_overlap. Ejecuta alembic upgrade head.")

    with SessionLocal() as session:
        owner_user = session.query(User).filter(User.username == settings.admin_username).first()
        if owner_user is None or owner_user.role != UserRole.OWNER.value:
            _fail("No existe el usuario owner. Ejecuta python -m app.create_owner despues de migrar.")

    print("OK: configuracion de produccion y conexion a base verificadas.")


if __name__ == "__main__":
    main()
