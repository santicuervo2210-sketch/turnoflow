"""make bot webhooks idempotent and routable

Revision ID: 20260809_0014
Revises: 20260809_0013
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0014"
down_revision: str | None = "20260809_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_webhook_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("barber_shop_id", sa.Integer(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["barber_shop_id"], ["barber_shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "barber_shop_id",
            "provider_message_id",
            name="uq_bot_webhook_receipt_shop_message",
        ),
    )
    op.create_index(
        op.f("ix_bot_webhook_receipts_barber_shop_id"),
        "bot_webhook_receipts",
        ["barber_shop_id"],
    )
    op.create_index(
        "ix_bot_webhook_receipts_created_at",
        "bot_webhook_receipts",
        ["created_at"],
    )
    op.create_index(
        "ix_bot_conversation_states_updated_at",
        "bot_conversation_states",
        ["updated_at"],
    )
    op.create_index(
        "ix_supply_sales_shop_created_at",
        "supply_sales",
        ["barber_shop_id", "created_at"],
    )
    op.create_index(
        "uq_barber_shops_phone_not_null",
        "barber_shops",
        ["phone"],
        unique=True,
        postgresql_where=sa.text("phone IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_barber_shops_phone_not_null", table_name="barber_shops")
    op.drop_index("ix_supply_sales_shop_created_at", table_name="supply_sales")
    op.drop_index("ix_bot_conversation_states_updated_at", table_name="bot_conversation_states")
    op.drop_index("ix_bot_webhook_receipts_created_at", table_name="bot_webhook_receipts")
    op.drop_index(op.f("ix_bot_webhook_receipts_barber_shop_id"), table_name="bot_webhook_receipts")
    op.drop_table("bot_webhook_receipts")
