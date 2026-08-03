"""barber shop access status

Revision ID: 20260730_0003
Revises: 20260730_0002
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260730_0003"
down_revision: str | None = "20260730_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "barber_shops",
        sa.Column("access_status", sa.String(length=20), server_default="active", nullable=False),
    )
    op.add_column("barber_shops", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("barber_shops", sa.Column("suspension_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("barber_shops", "suspension_reason")
    op.drop_column("barber_shops", "suspended_at")
    op.drop_column("barber_shops", "access_status")
