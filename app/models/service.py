from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.associations import barber_services
from app.models.common import TimestampMixin

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.barber import Barber
    from app.models.barber_shop import BarberShop


class Service(TimestampMixin, Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="ck_services_duration_positive"),
        CheckConstraint("price >= 0", name="ck_services_price_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_shop_id: Mapped[int] = mapped_column(
        ForeignKey("barber_shops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    barber_shop: Mapped[BarberShop] = relationship(back_populates="services")
    barbers: Mapped[list[Barber]] = relationship(
        secondary=barber_services,
        back_populates="services",
    )
    appointments: Mapped[list[Appointment]] = relationship(back_populates="service")

