from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Appointment, AppointmentStatus, BarberShop, BotSettings
from app.models.bot_settings import DEFAULT_GREETING_MESSAGE, DEFAULT_MENU_MESSAGE, DEFAULT_REMINDER_TEMPLATE
from app.services.appointments import ACTIVE_ACCESS_STATUS, SchedulingError


def _as_naive_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


@dataclass(frozen=True)
class ReminderPreview:
    appointment_id: int
    barber_shop_id: int
    customer_name: str
    customer_phone: str
    starts_at: datetime
    message: str


def get_or_create_bot_settings(session: Session, barber_shop_id: int) -> BotSettings:
    shop = session.get(BarberShop, barber_shop_id)
    if shop is None:
        raise SchedulingError("Negocio no encontrado.", 404)

    settings = session.scalars(
        select(BotSettings).where(BotSettings.barber_shop_id == barber_shop_id)
    ).first()
    if settings is not None:
        return settings

    settings = BotSettings(barber_shop_id=barber_shop_id)
    session.add(settings)
    session.commit()
    session.refresh(settings)
    return settings


def get_or_create_bot_settings_map(
    session: Session,
    barber_shop_ids: list[int],
) -> dict[int, BotSettings]:
    """Load settings for several shops without issuing one query per shop."""
    unique_shop_ids = sorted(set(barber_shop_ids))
    if not unique_shop_ids:
        return {}

    settings_by_shop = {
        item.barber_shop_id: item
        for item in session.scalars(
            select(BotSettings).where(BotSettings.barber_shop_id.in_(unique_shop_ids))
        ).all()
    }
    missing_shop_ids = [shop_id for shop_id in unique_shop_ids if shop_id not in settings_by_shop]
    if missing_shop_ids:
        session.add_all(BotSettings(barber_shop_id=shop_id) for shop_id in missing_shop_ids)
        session.commit()
        settings_by_shop = {
            item.barber_shop_id: item
            for item in session.scalars(
                select(BotSettings).where(BotSettings.barber_shop_id.in_(unique_shop_ids))
            ).all()
        }
    return settings_by_shop


def update_bot_settings(
    session: Session,
    *,
    barber_shop_id: int,
    bot_enabled: bool,
    reminders_enabled: bool,
    reminder_hours_before: int,
    greeting_message: str,
    reminder_template: str,
    menu_message: str = DEFAULT_MENU_MESSAGE,
) -> BotSettings:
    settings = get_or_create_bot_settings(session, barber_shop_id)
    settings.bot_enabled = bot_enabled
    settings.reminders_enabled = reminders_enabled
    settings.reminder_hours_before = reminder_hours_before
    settings.greeting_message = greeting_message.strip() or DEFAULT_GREETING_MESSAGE
    settings.menu_message = menu_message.strip() or DEFAULT_MENU_MESSAGE
    settings.reminder_template = reminder_template.strip() or DEFAULT_REMINDER_TEMPLATE
    session.commit()
    session.refresh(settings)
    return settings


def render_reminder_message(appointment: Appointment, template: str) -> str:
    return template.format(
        customer_name=appointment.customer.full_name,
        customer_phone=appointment.customer.phone,
        shop_name=appointment.barber_shop.name,
        barber_name=appointment.barber.name,
        service_name=appointment.service.name,
        starts_at=appointment.starts_at.strftime("%Y-%m-%d %H:%M"),
    )


def list_pending_reminders(
    session: Session,
    *,
    now: datetime | None = None,
) -> list[ReminderPreview]:
    current_time_utc = now or datetime.now(UTC)
    current_time = _as_naive_datetime(current_time_utc)

    appointments = session.scalars(
        select(Appointment)
        .options(
            joinedload(Appointment.customer),
            joinedload(Appointment.barber_shop),
            joinedload(Appointment.barber),
            joinedload(Appointment.service),
        )
        .join(Appointment.barber_shop)
        .where(
            BarberShop.access_status == ACTIVE_ACCESS_STATUS,
            or_(BarberShop.trial_ends_at.is_(None), BarberShop.trial_ends_at >= current_time_utc),
            Appointment.status.in_(
                (
                    AppointmentStatus.PENDING.value,
                    AppointmentStatus.CONFIRMED.value,
                )
            ),
            Appointment.starts_at >= current_time,
        )
        .order_by(Appointment.starts_at)
    ).all()

    settings_by_shop = get_or_create_bot_settings_map(
        session,
        [appointment.barber_shop_id for appointment in appointments],
    )

    previews: list[ReminderPreview] = []
    for appointment in appointments:
        settings = settings_by_shop[appointment.barber_shop_id]
        reminder_window_end = current_time + timedelta(hours=settings.reminder_hours_before)
        if not settings.bot_enabled or not settings.reminders_enabled:
            continue
        appointment_starts_at = _as_naive_datetime(appointment.starts_at)
        if appointment_starts_at > reminder_window_end:
            continue

        previews.append(
            ReminderPreview(
                appointment_id=appointment.id,
                barber_shop_id=appointment.barber_shop_id,
                customer_name=appointment.customer.full_name,
                customer_phone=appointment.customer.phone,
                starts_at=appointment.starts_at,
                message=render_reminder_message(appointment, settings.reminder_template),
            )
        )

    return previews
