from __future__ import annotations

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BotCategoryDefault(Base):
    __tablename__ = "bot_category_defaults"
    __table_args__ = (
        UniqueConstraint("business_category", "alias", name="uq_bot_category_default_alias"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_category: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    service_term: Mapped[str] = mapped_column(String(80), nullable=False)
    alias: Mapped[str] = mapped_column(String(80), nullable=False)
