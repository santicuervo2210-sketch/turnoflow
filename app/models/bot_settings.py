from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin

if TYPE_CHECKING:
    from app.models.barber_shop import BarberShop


DEFAULT_GREETING_MESSAGE = "Hola, soy el asistente de TurnoFlow. Te ayudo a reservar tu turno."
DEFAULT_REMINDER_TEMPLATE = (
    "Hola {customer_name}, te recordamos tu turno en {shop_name} "
    "el {starts_at}. Servicio: {service_name}."
)


class BotSettings(TimestampMixin, Base):
    __tablename__ = "bot_settings"
    __table_args__ = (
        CheckConstraint("reminder_hours_before >= 1", name="ck_bot_settings_reminder_hours_min"),
        CheckConstraint("reminder_hours_before <= 168", name="ck_bot_settings_reminder_hours_max"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_shop_id: Mapped[int] = mapped_column(
        ForeignKey("barber_shops.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    bot_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    reminder_hours_before: Mapped[int] = mapped_column(Integer, default=24, server_default="24", nullable=False)
    greeting_message: Mapped[str] = mapped_column(
        Text,
        default=DEFAULT_GREETING_MESSAGE,
        server_default=DEFAULT_GREETING_MESSAGE,
        nullable=False,
    )
    reminder_template: Mapped[str] = mapped_column(
        Text,
        default=DEFAULT_REMINDER_TEMPLATE,
        server_default=DEFAULT_REMINDER_TEMPLATE,
        nullable=False,
    )

    barber_shop: Mapped[BarberShop] = relationship(back_populates="bot_settings")

