from __future__ import annotations

from sqlalchemy import ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class BotWebhookReceipt(TimestampMixin, Base):
    __tablename__ = "bot_webhook_receipts"
    __table_args__ = (
        UniqueConstraint(
            "barber_shop_id",
            "provider_message_id",
            name="uq_bot_webhook_receipt_shop_message",
        ),
        Index("ix_bot_webhook_receipts_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_shop_id: Mapped[int] = mapped_column(
        ForeignKey("barber_shops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")
    response_payload: Mapped[dict | None] = mapped_column(JSON)
