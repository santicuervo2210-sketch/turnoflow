from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin

if TYPE_CHECKING:
    from app.models.barber_shop import BarberShop


class UserRole(StrEnum):
    OWNER = "owner"
    BUSINESS_ADMIN = "business_admin"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default=UserRole.BUSINESS_ADMIN.value, nullable=False)
    barber_shop_id: Mapped[int | None] = mapped_column(
        ForeignKey("barber_shops.id", ondelete="CASCADE"),
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true", nullable=False)

    barber_shop: Mapped[BarberShop | None] = relationship(back_populates="users")
