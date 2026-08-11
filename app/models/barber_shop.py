from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.barber import Barber
    from app.models.bot_settings import BotSettings
    from app.models.customer import Customer
    from app.models.service import Service
    from app.models.supply_sale import SupplySale
    from app.models.user import User


class BarberShop(TimestampMixin, Base):
    __tablename__ = "barber_shops"
    __table_args__ = (
        CheckConstraint("plan IN ('basic', 'premium')", name="ck_barber_shops_plan"),
        CheckConstraint(
            "visual_theme IN ('flow', 'marble', 'wood', 'brick', 'blush')",
            name="ck_barber_shops_visual_theme",
        ),
        CheckConstraint(
            "business_category IN ('barberia', 'unas', 'pestanas', 'masajes', 'tatuajes', 'general')",
            name="ck_barber_shops_business_category",
        ),
        Index(
            "uq_barber_shops_phone_not_null",
            "phone",
            unique=True,
            postgresql_where=text("phone IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(255))
    access_status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        server_default="active",
        nullable=False,
    )
    plan: Mapped[str] = mapped_column(
        String(20),
        default="basic",
        server_default="basic",
        nullable=False,
    )
    business_category: Mapped[str] = mapped_column(
        String(20),
        default="general",
        server_default="general",
        nullable=False,
    )
    visual_theme: Mapped[str] = mapped_column(
        String(20),
        default="flow",
        server_default="flow",
        nullable=False,
    )
    logo_url: Mapped[str | None] = mapped_column(Text)
    logo_key: Mapped[str | None] = mapped_column(String(512))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[str | None] = mapped_column(Text)
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC) + timedelta(days=15),
    )

    barbers: Mapped[list[Barber]] = relationship(
        back_populates="barber_shop",
        cascade="all, delete-orphan",
    )
    services: Mapped[list[Service]] = relationship(
        back_populates="barber_shop",
        cascade="all, delete-orphan",
    )
    customers: Mapped[list[Customer]] = relationship(
        back_populates="barber_shop",
        cascade="all, delete-orphan",
    )
    appointments: Mapped[list[Appointment]] = relationship(back_populates="barber_shop")
    supply_sales: Mapped[list[SupplySale]] = relationship(
        back_populates="barber_shop",
        cascade="all, delete-orphan",
    )
    bot_settings: Mapped[BotSettings | None] = relationship(
        back_populates="barber_shop",
        cascade="all, delete-orphan",
        uselist=False,
    )
    users: Mapped[list[User]] = relationship(
        back_populates="barber_shop",
        cascade="all, delete-orphan",
    )
