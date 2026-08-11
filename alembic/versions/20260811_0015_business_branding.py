"""add business visual branding

Revision ID: 20260811_0015
Revises: 20260809_0014
Create Date: 2026-08-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260811_0015"
down_revision: str | None = "20260809_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "barber_shops",
        sa.Column("visual_theme", sa.String(length=20), server_default="flow", nullable=False),
    )
    op.add_column("barber_shops", sa.Column("logo_url", sa.Text(), nullable=True))
    op.add_column("barber_shops", sa.Column("logo_key", sa.String(length=512), nullable=True))
    op.create_check_constraint(
        "ck_barber_shops_visual_theme",
        "barber_shops",
        "visual_theme IN ('flow', 'marble', 'wood', 'brick', 'blush')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_barber_shops_visual_theme", "barber_shops", type_="check")
    op.drop_column("barber_shops", "logo_key")
    op.drop_column("barber_shops", "logo_url")
    op.drop_column("barber_shops", "visual_theme")
