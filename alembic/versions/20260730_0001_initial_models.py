"""initial models

Revision ID: 20260730_0001
Revises:
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260730_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "barber_shops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "barbers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("barber_shop_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["barber_shop_id"], ["barber_shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_barbers_barber_shop_id"), "barbers", ["barber_shop_id"])

    op.create_table(
        "services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("barber_shop_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("duration_minutes > 0", name="ck_services_duration_positive"),
        sa.CheckConstraint("price >= 0", name="ck_services_price_non_negative"),
        sa.ForeignKeyConstraint(["barber_shop_id"], ["barber_shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_services_barber_shop_id"), "services", ["barber_shop_id"])

    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("barber_shop_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["barber_shop_id"], ["barber_shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("barber_shop_id", "phone", name="uq_customers_shop_phone"),
    )
    op.create_index(op.f("ix_customers_barber_shop_id"), "customers", ["barber_shop_id"])

    op.create_table(
        "barber_services",
        sa.Column("barber_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["barber_id"], ["barbers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("barber_id", "service_id"),
    )

    op.create_table(
        "working_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("barber_id", sa.Integer(), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="ck_working_schedules_day"),
        sa.CheckConstraint("start_time < end_time", name="ck_working_schedules_time_range"),
        sa.ForeignKeyConstraint(["barber_id"], ["barbers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "barber_id",
            "day_of_week",
            "start_time",
            "end_time",
            name="uq_working_schedules_barber_time",
        ),
    )
    op.create_index(op.f("ix_working_schedules_barber_id"), "working_schedules", ["barber_id"])

    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("barber_shop_id", sa.Integer(), nullable=False),
        sa.Column("barber_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("starts_at < ends_at", name="ck_appointments_time_range"),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'cancelled', 'completed', 'no_show')",
            name="ck_appointments_status",
        ),
        sa.ForeignKeyConstraint(["barber_id"], ["barbers.id"]),
        sa.ForeignKeyConstraint(["barber_shop_id"], ["barber_shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_appointments_barber_id"), "appointments", ["barber_id"])
    op.create_index("ix_appointments_barber_starts_at", "appointments", ["barber_id", "starts_at"])
    op.create_index(op.f("ix_appointments_barber_shop_id"), "appointments", ["barber_shop_id"])
    op.create_index("ix_appointments_shop_starts_at", "appointments", ["barber_shop_id", "starts_at"])
    op.create_index(op.f("ix_appointments_customer_id"), "appointments", ["customer_id"])
    op.create_index(op.f("ix_appointments_service_id"), "appointments", ["service_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_appointments_service_id"), table_name="appointments")
    op.drop_index(op.f("ix_appointments_customer_id"), table_name="appointments")
    op.drop_index("ix_appointments_shop_starts_at", table_name="appointments")
    op.drop_index(op.f("ix_appointments_barber_shop_id"), table_name="appointments")
    op.drop_index("ix_appointments_barber_starts_at", table_name="appointments")
    op.drop_index(op.f("ix_appointments_barber_id"), table_name="appointments")
    op.drop_table("appointments")
    op.drop_index(op.f("ix_working_schedules_barber_id"), table_name="working_schedules")
    op.drop_table("working_schedules")
    op.drop_table("barber_services")
    op.drop_index(op.f("ix_customers_barber_shop_id"), table_name="customers")
    op.drop_table("customers")
    op.drop_index(op.f("ix_services_barber_shop_id"), table_name="services")
    op.drop_table("services")
    op.drop_index(op.f("ix_barbers_barber_shop_id"), table_name="barbers")
    op.drop_table("barbers")
    op.drop_table("barber_shops")

