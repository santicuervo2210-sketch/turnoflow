"""bot settings

Revision ID: 20260730_0004
Revises: 20260730_0003
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260730_0004"
down_revision: str | None = "20260730_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_GREETING_MESSAGE = "Hola, soy el asistente de TurnoFlow. Te ayudo a reservar tu turno."
DEFAULT_REMINDER_TEMPLATE = (
    "Hola {customer_name}, te recordamos tu turno en {shop_name} "
    "el {starts_at}. Servicio: {service_name}."
)


def upgrade() -> None:
    op.create_table(
        "bot_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("barber_shop_id", sa.Integer(), nullable=False),
        sa.Column("bot_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("reminders_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("reminder_hours_before", sa.Integer(), server_default="24", nullable=False),
        sa.Column("greeting_message", sa.Text(), server_default=DEFAULT_GREETING_MESSAGE, nullable=False),
        sa.Column("reminder_template", sa.Text(), server_default=DEFAULT_REMINDER_TEMPLATE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("reminder_hours_before >= 1", name="ck_bot_settings_reminder_hours_min"),
        sa.CheckConstraint("reminder_hours_before <= 168", name="ck_bot_settings_reminder_hours_max"),
        sa.ForeignKeyConstraint(["barber_shop_id"], ["barber_shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("barber_shop_id"),
    )
    op.create_index(op.f("ix_bot_settings_barber_shop_id"), "bot_settings", ["barber_shop_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_bot_settings_barber_shop_id"), table_name="bot_settings")
    op.drop_table("bot_settings")
