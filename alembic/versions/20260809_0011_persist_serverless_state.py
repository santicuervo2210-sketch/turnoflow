"""persist bot context and rate limits

Revision ID: 20260809_0011
Revises: 20260809_0010
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0011"
down_revision: str | None = "20260809_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_conversation_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("barber_shop_id", sa.Integer(), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("last_target_date", sa.Date(), nullable=True),
        sa.Column("flow", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["barber_shop_id"], ["barber_shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("barber_shop_id", "phone", name="uq_bot_conversation_shop_phone"),
    )
    op.create_index(
        op.f("ix_bot_conversation_states_barber_shop_id"),
        "bot_conversation_states",
        ["barber_shop_id"],
    )
    op.create_table(
        "rate_limit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rate_limit_events_key_created", "rate_limit_events", ["key", "created_at"])
    op.create_index(
        "ix_appointments_shop_status_starts_at",
        "appointments",
        ["barber_shop_id", "status", "starts_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_appointments_shop_status_starts_at", table_name="appointments")
    op.drop_index("ix_rate_limit_events_key_created", table_name="rate_limit_events")
    op.drop_table("rate_limit_events")
    op.drop_index(op.f("ix_bot_conversation_states_barber_shop_id"), table_name="bot_conversation_states")
    op.drop_table("bot_conversation_states")
