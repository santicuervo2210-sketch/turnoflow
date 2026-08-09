"""configurable bot categories and aliases

Revision ID: 20260809_0012
Revises: 20260809_0011
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0012"
down_revision: str | None = "20260809_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_MENU = (
    "Que queres hacer? 1. Ver servicios y precios | 2. Sacar un turno | "
    "3. Consultar mi turno | 4. Cancelar o reprogramar"
)
CATEGORY_DEFAULTS = {
    "general": {
        "corte": ("corte", "cortar", "cortarme", "pelo", "cabello"),
        "barba": ("barba", "afeitado", "afeitarme"),
        "unas": ("unas", "manicura", "manos", "nails"),
        "pestanas": ("pestanas", "pestana", "lashes"),
        "claritos": ("claritos", "mechas", "reflejos"),
    },
    "barberia": {
        "corte": ("corte", "cortar", "cortarme", "pelo", "cabello"),
        "barba": ("barba", "afeitado", "afeitarme"),
        "claritos": ("claritos", "mechas", "reflejos"),
    },
    "unas": {
        "manicura": ("manicura", "unas", "manos"),
        "semipermanente": ("semipermanente", "semi"),
        "esculpidas": ("esculpidas", "acrilicas"),
        "soft gel": ("soft gel", "softgel"),
    },
    "pestanas": {
        "lifting": ("lifting", "levantamiento"),
        "extensiones": ("extensiones", "pestanas", "lashes"),
        "volumen ruso": ("volumen ruso", "volumen"),
    },
    "masajes": {
        "descontracturante": ("descontracturante", "contractura"),
        "relajante": ("relajante", "relajacion"),
        "deportivo": ("deportivo", "deporte"),
    },
    "tatuajes": {
        "sesion": ("sesion", "tatuaje", "tatuarme"),
        "retoque": ("retoque", "retocar"),
        "cover up": ("cover up", "coverup", "cubrir"),
    },
}


def upgrade() -> None:
    op.add_column(
        "barber_shops",
        sa.Column("business_category", sa.String(length=20), server_default="general", nullable=False),
    )
    op.create_check_constraint(
        "ck_barber_shops_business_category",
        "barber_shops",
        "business_category IN ('barberia', 'unas', 'pestanas', 'masajes', 'tatuajes', 'general')",
    )
    op.add_column(
        "bot_settings",
        sa.Column("menu_message", sa.Text(), server_default=DEFAULT_MENU, nullable=False),
    )
    defaults_table = op.create_table(
        "bot_category_defaults",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_category", sa.String(length=20), nullable=False),
        sa.Column("service_term", sa.String(length=80), nullable=False),
        sa.Column("alias", sa.String(length=80), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_category", "alias", name="uq_bot_category_default_alias"),
    )
    op.create_index(
        op.f("ix_bot_category_defaults_business_category"),
        "bot_category_defaults",
        ["business_category"],
    )
    op.create_table(
        "bot_service_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("barber_shop_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=True),
        sa.Column("alias", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["barber_shop_id"], ["barber_shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("barber_shop_id", "alias", name="uq_bot_service_alias_shop_alias"),
    )
    op.create_index(
        op.f("ix_bot_service_aliases_barber_shop_id"),
        "bot_service_aliases",
        ["barber_shop_id"],
    )
    rows = [
        {"business_category": category, "service_term": term, "alias": alias}
        for category, terms in CATEGORY_DEFAULTS.items()
        for term, aliases in terms.items()
        for alias in aliases
    ]
    op.bulk_insert(defaults_table, rows)


def downgrade() -> None:
    op.drop_index(op.f("ix_bot_service_aliases_barber_shop_id"), table_name="bot_service_aliases")
    op.drop_table("bot_service_aliases")
    op.drop_index(op.f("ix_bot_category_defaults_business_category"), table_name="bot_category_defaults")
    op.drop_table("bot_category_defaults")
    op.drop_column("bot_settings", "menu_message")
    op.drop_constraint("ck_barber_shops_business_category", "barber_shops", type_="check")
    op.drop_column("barber_shops", "business_category")
