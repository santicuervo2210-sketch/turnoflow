"""add barber time blocks

Revision ID: 20260731_0005
Revises: 20260730_0004
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0005"
down_revision: str | None = "20260730_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "barber_time_blocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("barber_id", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=160), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("starts_at < ends_at", name="ck_barber_time_blocks_time_range"),
        sa.ForeignKeyConstraint(["barber_id"], ["barbers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_barber_time_blocks_barber_id"), "barber_time_blocks", ["barber_id"], unique=False)
    op.create_index(
        "ix_barber_time_blocks_barber_starts_at",
        "barber_time_blocks",
        ["barber_id", "starts_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_barber_time_blocks_barber_starts_at", table_name="barber_time_blocks")
    op.drop_index(op.f("ix_barber_time_blocks_barber_id"), table_name="barber_time_blocks")
    op.drop_table("barber_time_blocks")
