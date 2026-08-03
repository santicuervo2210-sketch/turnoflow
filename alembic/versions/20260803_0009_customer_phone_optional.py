"""allow customers without a phone number

Revision ID: 20260803_0009
Revises: 20260801_0008
Create Date: 2026-08-03
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260803_0009"
down_revision: str | None = "20260801_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "customers",
        "phone",
        existing_type=sa.String(length=30),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("UPDATE customers SET phone = 'sin-telefono-' || id WHERE phone IS NULL")
    op.alter_column(
        "customers",
        "phone",
        existing_type=sa.String(length=30),
        nullable=False,
    )
