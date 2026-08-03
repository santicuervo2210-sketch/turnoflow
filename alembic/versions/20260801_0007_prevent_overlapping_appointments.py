"""prevent overlapping active appointments in postgres

Revision ID: 20260801_0007
Revises: 20260731_0006
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260801_0007"
down_revision: str | None = "20260731_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT_NAME = "ex_appointments_no_active_overlap"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        f"""
        ALTER TABLE appointments
        ADD CONSTRAINT {CONSTRAINT_NAME}
        EXCLUDE USING gist (
            barber_id WITH =,
            tstzrange(starts_at, ends_at, '[)') WITH &&
        )
        WHERE (status IN ('pending', 'confirmed'))
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(f"ALTER TABLE appointments DROP CONSTRAINT IF EXISTS {CONSTRAINT_NAME}")
