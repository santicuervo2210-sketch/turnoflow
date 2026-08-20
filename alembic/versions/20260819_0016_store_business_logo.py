"""store business logo in postgres

Revision ID: 20260819_0016
Revises: 20260811_0015
Create Date: 2026-08-19
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260819_0016"
down_revision: str | None = "20260811_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("barber_shops", sa.Column("logo_data", sa.LargeBinary(), nullable=True))
    op.add_column("barber_shops", sa.Column("logo_content_type", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("barber_shops", "logo_content_type")
    op.drop_column("barber_shops", "logo_data")
