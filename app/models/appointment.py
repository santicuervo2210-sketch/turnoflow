from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.appointment_status import AppointmentStatus
from app.models.common import TimestampMixin

if TYPE_CHECKING:
    from app.models.barber import Barber
    from app.models.barber_shop import BarberShop
    from app.models.customer import Customer
    from app.models.service import Service
    from app.models.supply_sale import SupplySale


class Appointment(TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("starts_at < ends_at", name="ck_appointments_time_range"),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'cancelled', 'completed', 'no_show')",
            name="ck_appointments_status",
        ),
        Index("ix_appointments_barber_starts_at", "barber_id", "starts_at"),
        Index("ix_appointments_shop_starts_at", "barber_shop_id", "starts_at"),
        Index("ix_appointments_shop_status_starts_at", "barber_shop_id", "status", "starts_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_shop_id: Mapped[int] = mapped_column(
        ForeignKey("barber_shops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    barber_id: Mapped[int] = mapped_column(ForeignKey("barbers.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default=AppointmentStatus.PENDING.value,
        server_default=AppointmentStatus.PENDING.value,
        nullable=False,
    )
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_method: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)

    barber_shop: Mapped[BarberShop] = relationship(back_populates="appointments")
    barber: Mapped[Barber] = relationship(back_populates="appointments")
    customer: Mapped[Customer] = relationship(back_populates="appointments")
    service: Mapped[Service] = relationship(back_populates="appointments")
    supply_sales: Mapped[list[SupplySale]] = relationship(back_populates="appointment")
