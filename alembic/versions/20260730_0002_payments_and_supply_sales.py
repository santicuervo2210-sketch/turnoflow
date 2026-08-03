"""payments and supply sales

Revision ID: 20260730_0002
Revises: 20260730_0001
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260730_0002"
down_revision: str | None = "20260730_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("is_paid", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("appointments", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("appointments", sa.Column("payment_method", sa.String(length=50), nullable=True))

    op.create_table(
        "supply_sales",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("barber_shop_id", sa.Integer(), nullable=False),
        sa.Column("appointment_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_supply_sales_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_supply_sales_unit_price_non_negative"),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"]),
        sa.ForeignKeyConstraint(["barber_shop_id"], ["barber_shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_supply_sales_appointment_id"), "supply_sales", ["appointment_id"])
    op.create_index(op.f("ix_supply_sales_barber_shop_id"), "supply_sales", ["barber_shop_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_supply_sales_barber_shop_id"), table_name="supply_sales")
    op.drop_index(op.f("ix_supply_sales_appointment_id"), table_name="supply_sales")
    op.drop_table("supply_sales")
    op.drop_column("appointments", "payment_method")
    op.drop_column("appointments", "paid_at")
    op.drop_column("appointments", "is_paid")

