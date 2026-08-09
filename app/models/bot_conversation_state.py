from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class BotConversationState(TimestampMixin, Base):
    __tablename__ = "bot_conversation_states"
    __table_args__ = (
        UniqueConstraint("barber_shop_id", "phone", name="uq_bot_conversation_shop_phone"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_shop_id: Mapped[int] = mapped_column(
        ForeignKey("barber_shops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id", ondelete="SET NULL"))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    last_target_date: Mapped[date | None] = mapped_column(Date)
    flow: Mapped[str | None] = mapped_column(String(40))
