"""barber shop plan

Revision ID: 20260801_0008
Revises: 20260801_0007
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260801_0008"
down_revision: str | None = "20260801_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "barber_shops",
        sa.Column("plan", sa.String(length=20), server_default="basic", nullable=False),
    )
    op.create_check_constraint(
        "ck_barber_shops_plan",
        "barber_shops",
        "plan IN ('basic', 'premium')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_barber_shops_plan", "barber_shops", type_="check")
    op.drop_column("barber_shops", "plan")
