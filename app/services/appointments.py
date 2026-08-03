from datetime import UTC, date, datetime, time, timedelta
from http import HTTPStatus

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Appointment, AppointmentStatus, Barber, BarberShop, BarberTimeBlock, Customer, Service, WorkingSchedule


ACTIVE_BOOKING_STATUSES = (
    AppointmentStatus.PENDING.value,
    AppointmentStatus.CONFIRMED.value,
)
ACTIVE_ACCESS_STATUS = "active"
SUSPENDED_ACCESS_STATUS = "suspended"
SLOT_STEP_MINUTES = 15
BUSINESS_WEEKDAYS = tuple(range(6))
ALL_WEEKDAYS = tuple(range(7))
DEFAULT_OPENING_TIME = time(9, 0)
DEFAULT_CLOSING_TIME = time(19, 0)


class SchedulingError(Exception):
    def __init__(self, detail: str, status_code: int = HTTPStatus.BAD_REQUEST) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def _as_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.replace(tzinfo=None)


def _overlaps(first_start: datetime, first_end: datetime, second_start: datetime, second_end: datetime) -> bool:
    return first_start < second_end and first_end > second_start


def _get_required(session: Session, model: type, object_id: int, label: str):
    item = session.get(model, object_id)
    if item is None:
        labels = {
            "Appointment": "Turno",
            "Barber": "Profesional",
            "Barber shop": "Negocio",
            "Customer": "Cliente",
            "Service": "Servicio",
        }
        raise SchedulingError(f"{labels.get(label, label)} no encontrado.", HTTPStatus.NOT_FOUND)
    return item


def _service_ids_for_barber(barber: Barber) -> set[int]:
    return {service.id for service in barber.services}


def _validate_same_shop(barber: Barber, customer: Customer, service: Service) -> None:
    shop_ids = {barber.barber_shop_id, customer.barber_shop_id, service.barber_shop_id}
    if len(shop_ids) != 1:
        raise SchedulingError("El profesional, el cliente y el servicio deben pertenecer al mismo negocio.")


def barber_can_perform_service(session: Session, barber: Barber, service: Service) -> bool:
    if barber.barber_shop_id != service.barber_shop_id or not barber.is_active or not service.is_active:
        return False
    assigned_service_ids = _service_ids_for_barber(barber)
    return not assigned_service_ids or service.id in assigned_service_ids


def _validate_barber_can_perform_service(session: Session, barber: Barber, service: Service) -> None:
    if not barber_can_perform_service(session, barber, service):
        raise SchedulingError(
            "El profesional seleccionado no realiza ese servicio. Elegi otro profesional o asignale el servicio desde Equipo."
        )


def ensure_barber_shop_can_operate(session: Session, barber_shop_id: int) -> BarberShop:
    shop = _get_required(session, BarberShop, barber_shop_id, "Barber shop")
    if shop.access_status != ACTIVE_ACCESS_STATUS:
        raise SchedulingError("El acceso del negocio esta suspendido.", HTTPStatus.FORBIDDEN)
    return shop


def suspend_barber_shop(session: Session, barber_shop_id: int, reason: str | None = None) -> BarberShop:
    shop = _get_required(session, BarberShop, barber_shop_id, "Barber shop")
    shop.access_status = SUSPENDED_ACCESS_STATUS
    shop.suspended_at = datetime.now(UTC)
    shop.suspension_reason = reason
    session.commit()
    session.refresh(shop)
    return shop


def activate_barber_shop(session: Session, barber_shop_id: int) -> BarberShop:
    shop = _get_required(session, BarberShop, barber_shop_id, "Barber shop")
    shop.access_status = ACTIVE_ACCESS_STATUS
    shop.suspended_at = None
    shop.suspension_reason = None
    session.commit()
    session.refresh(shop)
    return shop


def business_hours_for_shop(session: Session, barber_shop_id: int) -> tuple[time, time]:
    schedule = session.scalars(
        select(WorkingSchedule)
        .join(WorkingSchedule.barber)
        .where(
            Barber.barber_shop_id == barber_shop_id,
            WorkingSchedule.day_of_week.in_(ALL_WEEKDAYS),
            WorkingSchedule.is_active.is_(True),
        )
        .order_by(WorkingSchedule.day_of_week, WorkingSchedule.id)
    ).first()
    if schedule is None:
        return DEFAULT_OPENING_TIME, DEFAULT_CLOSING_TIME
    return schedule.start_time, schedule.end_time


def business_working_days_for_shop(session: Session, barber_shop_id: int) -> tuple[int, ...]:
    working_days = session.scalars(
        select(WorkingSchedule.day_of_week)
        .join(WorkingSchedule.barber)
        .where(
            Barber.barber_shop_id == barber_shop_id,
            WorkingSchedule.is_active.is_(True),
        )
        .distinct()
        .order_by(WorkingSchedule.day_of_week)
    ).all()
    return tuple(working_days) if working_days else BUSINESS_WEEKDAYS


def _working_windows(
    session: Session,
    barber: Barber,
    target_date: date,
) -> list[tuple[time, time]]:
    schedules = session.scalars(
        select(WorkingSchedule).where(
            WorkingSchedule.barber_id == barber.id,
            WorkingSchedule.day_of_week == target_date.weekday(),
            WorkingSchedule.is_active.is_(True),
        )
    ).all()
    if schedules:
        return [(schedule.start_time, schedule.end_time) for schedule in schedules]

    has_configured_week = session.scalars(
        select(WorkingSchedule.id).where(WorkingSchedule.barber_id == barber.id).limit(1)
    ).first()
    if has_configured_week is not None or target_date.weekday() not in BUSINESS_WEEKDAYS:
        return []

    return [business_hours_for_shop(session, barber.barber_shop_id)]


def _active_appointments_query(
    barber_id: int,
    starts_at: datetime,
    ends_at: datetime,
    ignore_appointment_id: int | None = None,
) -> Select[tuple[Appointment]]:
    query = select(Appointment).where(
        Appointment.barber_id == barber_id,
        Appointment.status.in_(ACTIVE_BOOKING_STATUSES),
        Appointment.starts_at < ends_at,
        Appointment.ends_at > starts_at,
    )
    if ignore_appointment_id is not None:
        query = query.where(Appointment.id != ignore_appointment_id)
    return query


def _active_time_blocks_query(
    barber_id: int,
    starts_at: datetime,
    ends_at: datetime,
) -> Select[tuple[BarberTimeBlock]]:
    return select(BarberTimeBlock).where(
        BarberTimeBlock.barber_id == barber_id,
        BarberTimeBlock.is_active.is_(True),
        BarberTimeBlock.starts_at < ends_at,
        BarberTimeBlock.ends_at > starts_at,
    )


def ensure_slot_is_available(
    session: Session,
    barber: Barber,
    starts_at: datetime,
    ends_at: datetime,
    ignore_appointment_id: int | None = None,
) -> None:
    starts_at = _as_naive(starts_at)
    ends_at = _as_naive(ends_at)
    working_windows = _working_windows(session, barber, starts_at.date())

    is_inside_schedule = any(
        datetime.combine(starts_at.date(), opening_time) <= starts_at
        and datetime.combine(starts_at.date(), closing_time) >= ends_at
        for opening_time, closing_time in working_windows
    )
    if not is_inside_schedule:
        raise SchedulingError("El profesional no trabaja en el dia y horario elegidos.")

    overlapping_appointment = session.scalars(
        _active_appointments_query(
            barber.id,
            starts_at,
            ends_at,
            ignore_appointment_id=ignore_appointment_id,
        )
    ).first()
    if overlapping_appointment is not None:
        raise SchedulingError("Ese horario se superpone con otro turno activo.", HTTPStatus.CONFLICT)

    overlapping_block = session.scalars(_active_time_blocks_query(barber.id, starts_at, ends_at)).first()
    if overlapping_block is not None:
        raise SchedulingError("Ese horario fue bloqueado por el profesional.", HTTPStatus.CONFLICT)


def create_appointment(
    session: Session,
    *,
    barber_id: int,
    customer_id: int,
    service_id: int,
    starts_at: datetime,
    duration_minutes: int | None = None,
    notes: str | None = None,
    status: AppointmentStatus = AppointmentStatus.PENDING,
) -> Appointment:
    barber = _get_required(session, Barber, barber_id, "Barber")
    customer = _get_required(session, Customer, customer_id, "Customer")
    service = _get_required(session, Service, service_id, "Service")

    _validate_same_shop(barber, customer, service)
    ensure_barber_shop_can_operate(session, barber.barber_shop_id)
    _validate_barber_can_perform_service(session, barber, service)

    selected_duration = duration_minutes if duration_minutes is not None else service.duration_minutes
    if selected_duration < 1 or selected_duration > 480:
        raise SchedulingError("La duracion del turno debe estar entre 1 y 480 minutos.")

    starts_at = _as_naive(starts_at)
    ends_at = starts_at + timedelta(minutes=selected_duration)
    ensure_slot_is_available(session, barber, starts_at, ends_at)

    appointment = Appointment(
        barber_shop_id=barber.barber_shop_id,
        barber_id=barber.id,
        customer_id=customer.id,
        service_id=service.id,
        starts_at=starts_at,
        ends_at=ends_at,
        status=status.value,
        notes=notes,
    )
    session.add(appointment)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise SchedulingError(
            "Ese horario acaba de ser reservado. Elegi otro horario disponible.",
            HTTPStatus.CONFLICT,
        ) from exc
    session.refresh(appointment)
    return appointment


def cancel_appointment(session: Session, appointment_id: int) -> Appointment:
    return update_appointment_status(session, appointment_id, AppointmentStatus.CANCELLED)


def update_appointment_status(
    session: Session,
    appointment_id: int,
    status: AppointmentStatus,
) -> Appointment:
    appointment = _get_required(session, Appointment, appointment_id, "Appointment")
    appointment.status = status.value
    session.commit()
    session.refresh(appointment)
    return appointment


def mark_appointment_paid(
    session: Session,
    appointment_id: int,
    payment_method: str | None = None,
) -> Appointment:
    appointment = _get_required(session, Appointment, appointment_id, "Appointment")
    appointment.is_paid = True
    appointment.paid_at = datetime.now(UTC)
    appointment.payment_method = payment_method
    session.commit()
    session.refresh(appointment)
    return appointment


def mark_appointment_unpaid(session: Session, appointment_id: int) -> Appointment:
    appointment = _get_required(session, Appointment, appointment_id, "Appointment")
    appointment.is_paid = False
    appointment.paid_at = None
    appointment.payment_method = None
    session.commit()
    session.refresh(appointment)
    return appointment


def reschedule_appointment(session: Session, appointment_id: int, starts_at: datetime) -> Appointment:
    appointment = _get_required(session, Appointment, appointment_id, "Appointment")
    if appointment.status == AppointmentStatus.CANCELLED.value:
        raise SchedulingError("Un turno cancelado no se puede reprogramar.")

    barber = _get_required(session, Barber, appointment.barber_id, "Barber")
    starts_at = _as_naive(starts_at)
    current_duration = _as_naive(appointment.ends_at) - _as_naive(appointment.starts_at)
    ends_at = starts_at + current_duration

    ensure_slot_is_available(
        session,
        barber,
        starts_at,
        ends_at,
        ignore_appointment_id=appointment.id,
    )

    appointment.starts_at = starts_at
    appointment.ends_at = ends_at
    appointment.status = AppointmentStatus.PENDING.value
    session.commit()
    session.refresh(appointment)
    return appointment


def get_available_slots(
    session: Session,
    *,
    barber_id: int,
    service_id: int,
    target_date: date,
) -> list[dict[str, datetime]]:
    barber = _get_required(session, Barber, barber_id, "Barber")
    service = _get_required(session, Service, service_id, "Service")
    ensure_barber_shop_can_operate(session, barber.barber_shop_id)
    _validate_barber_can_perform_service(session, barber, service)

    working_windows = _working_windows(session, barber, target_date)
    if not working_windows:
        return []

    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)
    appointments = session.scalars(
        select(Appointment).where(
            Appointment.barber_id == barber.id,
            Appointment.status.in_(ACTIVE_BOOKING_STATUSES),
            Appointment.starts_at < day_end,
            Appointment.ends_at > day_start,
        )
    ).all()
    time_blocks = session.scalars(
        select(BarberTimeBlock).where(
            BarberTimeBlock.barber_id == barber.id,
            BarberTimeBlock.is_active.is_(True),
            BarberTimeBlock.starts_at < day_end,
            BarberTimeBlock.ends_at > day_start,
        )
    ).all()

    slots: list[dict[str, datetime]] = []
    service_delta = timedelta(minutes=service.duration_minutes)
    step_delta = timedelta(minutes=SLOT_STEP_MINUTES)

    for opening_time, closing_time in working_windows:
        cursor = datetime.combine(target_date, opening_time)
        schedule_end = datetime.combine(target_date, closing_time)

        while cursor + service_delta <= schedule_end:
            slot_start = cursor
            slot_end = cursor + service_delta
            is_free = all(
                not _overlaps(
                    slot_start,
                    slot_end,
                    _as_naive(appointment.starts_at),
                    _as_naive(appointment.ends_at),
                )
                for appointment in appointments
            ) and all(
                not _overlaps(
                    slot_start,
                    slot_end,
                    _as_naive(time_block.starts_at),
                    _as_naive(time_block.ends_at),
                )
                for time_block in time_blocks
            )
            if is_free:
                slots.append({"starts_at": slot_start, "ends_at": slot_end})

            cursor += step_delta

    return slots
