from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.associations import barber_services
from app.models.common import TimestampMixin

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.barber_shop import BarberShop
    from app.models.barber_time_block import BarberTimeBlock
    from app.models.service import Service
    from app.models.working_schedule import WorkingSchedule


class Barber(TimestampMixin, Base):
    __tablename__ = "barbers"

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_shop_id: Mapped[int] = mapped_column(
        ForeignKey("barber_shops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    barber_shop: Mapped[BarberShop] = relationship(back_populates="barbers")
    services: Mapped[list[Service]] = relationship(
        secondary=barber_services,
        back_populates="barbers",
    )
    working_schedules: Mapped[list[WorkingSchedule]] = relationship(
        back_populates="barber",
        cascade="all, delete-orphan",
    )
    time_blocks: Mapped[list[BarberTimeBlock]] = relationship(
        back_populates="barber",
        cascade="all, delete-orphan",
    )
    appointments: Mapped[list[Appointment]] = relationship(back_populates="barber")
