from __future__ import annotations

from datetime import time
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin

if TYPE_CHECKING:
    from app.models.barber import Barber


class WorkingSchedule(TimestampMixin, Base):
    __tablename__ = "working_schedules"
    __table_args__ = (
        CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="ck_working_schedules_day"),
        CheckConstraint("start_time < end_time", name="ck_working_schedules_time_range"),
        UniqueConstraint(
            "barber_id",
            "day_of_week",
            "start_time",
            "end_time",
            name="uq_working_schedules_barber_time",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_id: Mapped[int] = mapped_column(
        ForeignKey("barbers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    barber: Mapped[Barber] = relationship(back_populates="working_schedules")

