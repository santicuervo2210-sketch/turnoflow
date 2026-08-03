from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.barber_shop import BarberShop


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("barber_shop_id", "phone", name="uq_customers_shop_phone"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_shop_id: Mapped[int] = mapped_column(
        ForeignKey("barber_shops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)

    barber_shop: Mapped[BarberShop] = relationship(back_populates="customers")
    appointments: Mapped[list[Appointment]] = relationship(back_populates="customer")

