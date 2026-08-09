from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class BotServiceAlias(TimestampMixin, Base):
    __tablename__ = "bot_service_aliases"
    __table_args__ = (
        UniqueConstraint("barber_shop_id", "alias", name="uq_bot_service_alias_shop_alias"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_shop_id: Mapped[int] = mapped_column(
        ForeignKey("barber_shops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
