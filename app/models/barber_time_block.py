from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin

if TYPE_CHECKING:
    from app.models.barber import Barber


class BarberTimeBlock(TimestampMixin, Base):
    __tablename__ = "barber_time_blocks"
    __table_args__ = (
        CheckConstraint("starts_at < ends_at", name="ck_barber_time_blocks_time_range"),
        Index("ix_barber_time_blocks_barber_starts_at", "barber_id", "starts_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_id: Mapped[int] = mapped_column(
        ForeignKey("barbers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    barber: Mapped[Barber] = relationship(back_populates="time_blocks")
