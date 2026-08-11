import app.models  # noqa: F401
from sqlalchemy import inspect, text

from app.db.base import Base
from app.db.session import engine


def _ensure_sqlite_demo_columns() -> None:
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    statements: list[str] = []
    if "appointments" in table_names:
        existing_columns = {column["name"] for column in inspector.get_columns("appointments")}
        if "is_paid" not in existing_columns:
            statements.append("ALTER TABLE appointments ADD COLUMN is_paid BOOLEAN NOT NULL DEFAULT 0")
        if "paid_at" not in existing_columns:
            statements.append("ALTER TABLE appointments ADD COLUMN paid_at DATETIME")
        if "payment_method" not in existing_columns:
            statements.append("ALTER TABLE appointments ADD COLUMN payment_method VARCHAR(50)")

    if "barber_shops" in table_names:
        existing_columns = {column["name"] for column in inspector.get_columns("barber_shops")}
        if "access_status" not in existing_columns:
            statements.append("ALTER TABLE barber_shops ADD COLUMN access_status VARCHAR(20) NOT NULL DEFAULT 'active'")
        if "suspended_at" not in existing_columns:
            statements.append("ALTER TABLE barber_shops ADD COLUMN suspended_at DATETIME")
        if "suspension_reason" not in existing_columns:
            statements.append("ALTER TABLE barber_shops ADD COLUMN suspension_reason TEXT")
        if "trial_ends_at" not in existing_columns:
            statements.append("ALTER TABLE barber_shops ADD COLUMN trial_ends_at DATETIME")
        if "business_category" not in existing_columns:
            statements.append("ALTER TABLE barber_shops ADD COLUMN business_category VARCHAR(20) NOT NULL DEFAULT 'general'")
        if "visual_theme" not in existing_columns:
            statements.append("ALTER TABLE barber_shops ADD COLUMN visual_theme VARCHAR(20) NOT NULL DEFAULT 'flow'")
        if "logo_url" not in existing_columns:
            statements.append("ALTER TABLE barber_shops ADD COLUMN logo_url TEXT")
        if "logo_key" not in existing_columns:
            statements.append("ALTER TABLE barber_shops ADD COLUMN logo_key VARCHAR(512)")

    if "bot_settings" in table_names:
        existing_columns = {column["name"] for column in inspector.get_columns("bot_settings")}
        if "menu_message" not in existing_columns:
            statements.append(
                "ALTER TABLE bot_settings ADD COLUMN menu_message TEXT NOT NULL DEFAULT "
                "'Que queres hacer? 1. Ver servicios y precios | 2. Sacar un turno | "
                "3. Consultar mi turno | 4. Cancelar o reprogramar'"
            )

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def create_db_tables() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_demo_columns()
