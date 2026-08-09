from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.barber_shop import BarberShop


class SupplySale(TimestampMixin, Base):
    __tablename__ = "supply_sales"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_supply_sales_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_supply_sales_unit_price_non_negative"),
        Index("ix_supply_sales_shop_created_at", "barber_shop_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_shop_id: Mapped[int] = mapped_column(
        ForeignKey("barber_shops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    barber_shop: Mapped[BarberShop] = relationship(back_populates="supply_sales")
    appointment: Mapped[Appointment | None] = relationship(back_populates="supply_sales")

    @property
    def total_price(self) -> Decimal:
        return self.unit_price * self.quantity
