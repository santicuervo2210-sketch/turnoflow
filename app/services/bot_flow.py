from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Appointment, AppointmentStatus, Barber, BarberShop, BotSettings, Customer, Service
from app.services.ai_bot import BotIntent, classify_with_ai
from app.services.appointments import (
    SchedulingError,
    cancel_appointment,
    create_appointment,
    get_available_slots,
    reschedule_appointment,
)

BotMessages = list[tuple[str, str]]
PRICE_WORDS = (
    "precio",
    "vale",
    "valor",
    "sale",
    "cuesta",
    "cobran",
    "cobras",
    "tarifa",
)
SERVICE_ALIASES = {
    "corte": ("corte", "cortar", "cortarme", "pelo", "cabello"),
    "barba": ("barba", "afeitado", "afeitarme"),
    "unas": ("unas", "manicura", "manos", "nails"),
    "pestanas": ("pestanas", "pestana", "lashes"),
    "claritos": ("claritos", "mechas", "reflejos"),
}
GREETING_WORDS = ("hola", "buenas", "buen dia", "buenas tardes", "buenas noches")
AVAILABILITY_WORDS = (
    "dia",
    "dias",
    "horario",
    "horarios",
    "turno",
    "turnos",
    "lugar",
    "disponible",
    "disponibilidad",
    "agenda",
    "atienden",
)
BOOKING_WORDS = ("reservar", "reservame", "reserva", "agendar", "agendame", "sacar turno", "sacame")
CANCEL_WORDS = ("cancelar", "cancela", "cancelame", "dar de baja", "anular")
RESCHEDULE_WORDS = ("reprogramar", "reprogramame", "mover", "cambiar", "pasar")
APPOINTMENT_LOOKUP_WORDS = (
    "a que hora",
    "cuando",
    "que dia",
    "tenia",
    "tengo",
    "mis turnos",
    "mi turno",
    "recordame",
    "recordar",
    "confirmado",
)
WEEKDAY_NAMES = {
    0: "lunes",
    1: "martes",
    2: "miercoles",
    3: "jueves",
    4: "viernes",
    5: "sabado",
    6: "domingo",
}
WEEKDAY_NUMBERS = {name: number for number, name in WEEKDAY_NAMES.items()}
RECENT_ACTIVE_BOOKING_HOURS = 2


@dataclass
class BotConversationContext:
    barber_shop_id: int | None = None
    service_id: int | None = None
    customer_id: int | None = None
    last_target_date: date | None = None

    def reset(self) -> None:
        self.barber_shop_id = None
        self.service_id = None
        self.customer_id = None
        self.last_target_date = None


def _format_money(value) -> str:
    return f"${value}"


def _normalize_text(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return ascii_text.strip().lower()


def _active_services(session: Session, barber_shop_id: int) -> list[Service]:
    return list(
        session.scalars(
            select(Service)
            .where(Service.barber_shop_id == barber_shop_id, Service.is_active.is_(True))
            .order_by(Service.id)
        ).all()
    )


def _has_enabled_bot(session: Session, barber_shop_id: int) -> bool:
    shop = session.get(BarberShop, barber_shop_id)
    if shop is None or shop.access_status != "active":
        return False

    settings = session.scalars(select(BotSettings).where(BotSettings.barber_shop_id == barber_shop_id)).first()
    return settings is None or settings.bot_enabled


def _service_for_shop(session: Session, service_id: int, barber_shop_id: int) -> Service | None:
    return session.scalars(
        select(Service).where(
            Service.id == service_id,
            Service.barber_shop_id == barber_shop_id,
            Service.is_active.is_(True),
        )
    ).first()


def _list_services(session: Session, barber_shop_id: int) -> BotMessages:
    services = _active_services(session, barber_shop_id)
    if not services:
        return [("bot", "Todavia no hay servicios cargados.")]

    lines = [
        f"#{service.id} {service.name} - {service.duration_minutes} min - {_format_money(service.price)}"
        for service in services
    ]
    return [("bot", "Servicios disponibles: " + " | ".join(lines))]


def _looks_like_price_question(message: str) -> bool:
    return any(word in message for word in PRICE_WORDS)


def _service_matches_message(service: Service, message: str) -> bool:
    service_name = _normalize_text(service.name)
    service_words = [word for word in re.findall(r"\w+", service_name) if len(word) >= 3]

    if service_name and service_name in message:
        return True

    if any(word in message for word in service_words):
        return True

    for alias_key, aliases in SERVICE_ALIASES.items():
        if alias_key in service_name and any(alias in message for alias in aliases):
            return True

    return False


def _message_mentions_alias(message: str, alias_key: str) -> bool:
    return any(alias in message for alias in SERVICE_ALIASES[alias_key])


def _format_service_line(service: Service) -> str:
    return f"#{service.id} {service.name} - {service.duration_minutes} min - {_format_money(service.price)}"


def _choose_preferred_service(services: list[Service], message: str) -> Service | None:
    service_by_name = {_normalize_text(service.name): service for service in services}
    mentions_cut = _message_mentions_alias(message, "corte")
    mentions_claritos = _message_mentions_alias(message, "claritos")

    if mentions_cut and mentions_claritos and "corte + claritos" in service_by_name:
        return service_by_name["corte + claritos"]

    if mentions_claritos and not mentions_cut and "claritos" in service_by_name:
        return service_by_name["claritos"]

    if mentions_cut and not mentions_claritos and "corte" in service_by_name:
        return service_by_name["corte"]

    return None


def _find_service_from_message(session: Session, message: str, barber_shop_id: int) -> Service | None:
    services = _active_services(session, barber_shop_id)
    matching_services = [service for service in services if _service_matches_message(service, message)]

    if len(matching_services) == 1:
        return matching_services[0]

    if len(matching_services) > 1:
        preferred_service = _choose_preferred_service(matching_services, message)
        if preferred_service is not None:
            return preferred_service

    if not matching_services and len(services) == 1:
        return services[0]

    return None


def _find_service_for_conversation(
    session: Session,
    message: str,
    barber_shop_id: int,
    context: BotConversationContext | None = None,
) -> Service | None:
    service = _find_service_from_message(session, message, barber_shop_id)
    if service is not None:
        if context is not None:
            context.barber_shop_id = barber_shop_id
            context.service_id = service.id
        return service

    if context is None or context.service_id is None:
        return None

    return _service_for_shop(session, context.service_id, barber_shop_id)


def _handle_price_question(
    session: Session,
    message: str,
    barber_shop_id: int,
    context: BotConversationContext | None = None,
) -> BotMessages | None:
    if not _looks_like_price_question(message):
        return None

    services = _active_services(session, barber_shop_id)
    if not services:
        return [("bot", "Todavia no hay servicios cargados para consultar precios.")]

    matching_services = [service for service in services if _service_matches_message(service, message)]

    if len(matching_services) > 1:
        preferred_service = _choose_preferred_service(matching_services, message)
        if preferred_service is not None:
            matching_services = [preferred_service]

    if not matching_services and context is not None and context.service_id is not None:
        service = _service_for_shop(session, context.service_id, barber_shop_id)
        if service is not None:
            matching_services = [service]

    if len(matching_services) == 1:
        service = matching_services[0]
        if context is not None:
            context.barber_shop_id = barber_shop_id
            context.service_id = service.id
        return [
            (
                "bot",
                f"{service.name} cuesta {_format_money(service.price)} y dura {service.duration_minutes} minutos.",
            )
        ]

    if len(matching_services) > 1:
        lines = " | ".join(_format_service_line(service) for service in matching_services)
        return [("bot", f"Encontre varios servicios posibles: {lines}. Decime cual queres consultar.")]

    if len(services) == 1:
        service = services[0]
        return [
            (
                "bot",
                f"{service.name} cuesta {_format_money(service.price)} y dura {service.duration_minutes} minutos.",
            )
        ]

    lines = " | ".join(_format_service_line(service) for service in services)
    return [("bot", f"Estos son los servicios con precio: {lines}")]


def _looks_like_service_interest(message: str) -> bool:
    interest_words = ("quiero", "queria", "necesito", "busco", "me hago", "hacerme", "hacer", "consultar")
    return any(word in message for word in interest_words)


def _find_barber_for_service(session: Session, service: Service, message: str) -> Barber | None:
    barbers = session.scalars(
        select(Barber).where(
            Barber.barber_shop_id == service.barber_shop_id,
            Barber.is_active.is_(True),
        ).order_by(Barber.id)
    ).all()

    for barber in barbers:
        if _normalize_text(barber.name) in message:
            return barber

    for barber in barbers:
        if any(barber_service.id == service.id for barber_service in barber.services):
            return barber

    return None


def _customer_for_sender_phone(session: Session, barber_shop_id: int, from_phone: str) -> Customer:
    phone = from_phone.strip()
    customer = session.scalars(
        select(Customer).where(Customer.barber_shop_id == barber_shop_id, Customer.phone == phone)
    ).first()
    if customer is not None:
        return customer

    customer = Customer(
        barber_shop_id=barber_shop_id,
        full_name=f"Cliente {phone}",
        phone=phone,
    )
    session.add(customer)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        customer = session.scalars(
            select(Customer).where(Customer.barber_shop_id == barber_shop_id, Customer.phone == phone)
        ).first()
        if customer is None:
            raise
        return customer

    session.refresh(customer)
    return customer


def _existing_customer_for_sender_phone(session: Session, barber_shop_id: int, from_phone: str) -> Customer | None:
    phone = from_phone.strip()
    return session.scalars(
        select(Customer).where(Customer.barber_shop_id == barber_shop_id, Customer.phone == phone)
    ).first()


def _parse_target_date(message: str, today: date | None = None) -> date | None:
    today = today or date.today()

    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", message)
    if iso_match:
        return date.fromisoformat(iso_match.group(1))

    if "pasado manana" in message:
        return today + timedelta(days=2)

    if "manana" in message:
        return today + timedelta(days=1)

    if "hoy" in message:
        return today

    for weekday_name, weekday_number in WEEKDAY_NUMBERS.items():
        if weekday_name in message:
            days_ahead = (weekday_number - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return today + timedelta(days=days_ahead)

    return None


def _parse_target_time(message: str) -> str | None:
    if re.fullmatch(r"\d{1,2}", message.strip()):
        return f"{int(message):02d}:00"

    match = re.search(r"\b(\d{1,2})(?::|\.)(\d{2})\b", message)
    if match:
        hour, minute = match.groups()
        return f"{int(hour):02d}:{minute}"

    match = re.search(r"\b(?:a las|las)?\s*(\d{1,2})\s*(?:hs|h)\b", message)
    if match:
        return f"{int(match.group(1)):02d}:00"

    match = re.search(r"\b(?:a las|las)\s+(\d{1,2})\b", message)
    if match:
        return f"{int(match.group(1)):02d}:00"

    return None


def _format_date(value: date) -> str:
    return f"{WEEKDAY_NAMES[value.weekday()]} {value.strftime('%d/%m')}"


def _format_slot_times(slots: list[dict[str, datetime]], limit: int = 8) -> str:
    return ", ".join(slot["starts_at"].strftime("%H:%M") for slot in slots[:limit])


def _available_days_for_service(
    session: Session,
    barber: Barber,
    service: Service,
    *,
    start_date: date | None = None,
    days_to_check: int = 7,
) -> list[tuple[date, list[dict[str, datetime]]]]:
    start_date = start_date or date.today()
    days: list[tuple[date, list[dict[str, datetime]]]] = []

    for offset in range(days_to_check):
        target_date = start_date + timedelta(days=offset)
        slots = get_available_slots(
            session,
            barber_id=barber.id,
            service_id=service.id,
            target_date=target_date,
        )
        if slots:
            days.append((target_date, slots))

    return days


def _suggest_nearby_available_day(
    session: Session,
    barber: Barber,
    service: Service,
    target_date: date,
) -> str | None:
    previous_days = _available_days_for_service(
        session,
        barber,
        service,
        start_date=target_date - timedelta(days=3),
        days_to_check=3,
    )
    next_days = _available_days_for_service(
        session,
        barber,
        service,
        start_date=target_date + timedelta(days=1),
        days_to_check=7,
    )

    suggestions = [item for item in previous_days if item[0] < target_date] + next_days
    if not suggestions:
        return None

    suggested_date, slots = suggestions[0]
    return f"Tengo lugar el {_format_date(suggested_date)} a las {_format_slot_times(slots, 3)}."


def _looks_like_availability_question(message: str) -> bool:
    return (
        any(word in message for word in AVAILABILITY_WORDS)
        or "puedo cortarme" in message
        or _parse_target_date(message) is not None
    )


def _looks_like_booking_request(message: str) -> bool:
    return any(word in message for word in BOOKING_WORDS)


def _handle_availability_question(
    session: Session,
    message: str,
    barber_shop_id: int,
    context: BotConversationContext | None = None,
) -> BotMessages | None:
    if not _looks_like_availability_question(message):
        return None

    service = _find_service_for_conversation(session, message, barber_shop_id, context)
    if service is None:
        return [("bot", "Decime que servicio queres: corte, claritos o corte + claritos.")]

    barber = _find_barber_for_service(session, service, message)
    if barber is None:
        return [("bot", f"Todavia no hay profesionales activos para {service.name}.")]

    target_date = _parse_target_date(message)
    if target_date is None:
        available_days = _available_days_for_service(session, barber, service, days_to_check=7)
        if not available_days:
            return [("bot", f"No encontre horarios libres para {service.name} en los proximos 7 dias.")]

        lines = [
            f"{_format_date(day)}: {_format_slot_times(slots, 4)}"
            for day, slots in available_days[:4]
        ]
        return [
            (
                "bot",
                f"Para {service.name} tengo estos dias libres: "
                + " | ".join(lines)
                + ". Decime dia y hora y te lo reservo.",
            )
        ]

    if context is not None:
        context.barber_shop_id = barber_shop_id
        context.last_target_date = target_date

    slots = get_available_slots(
        session,
        barber_id=barber.id,
        service_id=service.id,
        target_date=target_date,
    )
    if not slots:
        suggestion = _suggest_nearby_available_day(session, barber, service, target_date)
        if suggestion is None:
            return [("bot", f"El {_format_date(target_date)} esta todo ocupado para {service.name}.")]
        return [("bot", f"El {_format_date(target_date)} esta todo ocupado para {service.name}. {suggestion}")]

    return [
        (
            "bot",
            f"Para {service.name} el {_format_date(target_date)} tengo libre: "
            + _format_slot_times(slots)
            + ".",
        )
    ]


def _handle_service_interest(
    session: Session,
    message: str,
    barber_shop_id: int,
    context: BotConversationContext | None = None,
) -> BotMessages | None:
    service = _find_service_for_conversation(session, message, barber_shop_id, context)
    if service is None:
        return None

    if not _looks_like_service_interest(message) and _find_service_from_message(session, message, barber_shop_id) is None:
        return None

    barber = _find_barber_for_service(session, service, message)
    if barber is None:
        return [("bot", f"{service.name} cuesta {_format_money(service.price)}, pero no hay profesionales activos.")]

    available_days = _available_days_for_service(session, barber, service, days_to_check=7)
    if not available_days:
        return [
            (
                "bot",
                f"{service.name} cuesta {_format_money(service.price)} y dura {service.duration_minutes} minutos. "
                "No encontre horarios libres en los proximos 7 dias.",
            )
        ]

    lines = [
        f"{_format_date(day)}: {_format_slot_times(slots, 3)}"
        for day, slots in available_days[:3]
    ]
    return [
        (
            "bot",
            f"Perfecto. {service.name} cuesta {_format_money(service.price)} y dura "
            f"{service.duration_minutes} minutos. Tengo lugar: "
            + " | ".join(lines)
            + ". Decime dia y hora y te lo confirmo.",
        )
    ]


def _customer_has_recent_active_booking(session: Session, customer: Customer, barber_shop_id: int) -> Appointment | None:
    threshold = datetime.now() - timedelta(hours=RECENT_ACTIVE_BOOKING_HOURS)
    return session.scalars(
        select(Appointment).where(
            Appointment.barber_shop_id == barber_shop_id,
            Appointment.customer_id == customer.id,
            Appointment.status.in_((AppointmentStatus.PENDING.value, AppointmentStatus.CONFIRMED.value)),
            Appointment.created_at >= threshold,
        ).order_by(Appointment.created_at.desc())
    ).first()


def _latest_active_appointment_for_customer(session: Session, customer: Customer, barber_shop_id: int) -> Appointment | None:
    return session.scalars(
        select(Appointment).where(
            Appointment.barber_shop_id == barber_shop_id,
            Appointment.customer_id == customer.id,
            Appointment.status.in_((AppointmentStatus.PENDING.value, AppointmentStatus.CONFIRMED.value)),
        ).order_by(Appointment.starts_at.desc())
    ).first()


def _looks_like_cancel_request(message: str) -> bool:
    return any(word in message for word in CANCEL_WORDS)


def _looks_like_reschedule_request(message: str) -> bool:
    return any(word in message for word in RESCHEDULE_WORDS)


def _looks_like_appointment_lookup(message: str) -> bool:
    return ("turno" in message or "reserva" in message) and any(word in message for word in APPOINTMENT_LOOKUP_WORDS)


def _next_active_appointment_for_customer(session: Session, customer: Customer, barber_shop_id: int) -> Appointment | None:
    upcoming_appointment = session.scalars(
        select(Appointment).where(
            Appointment.barber_shop_id == barber_shop_id,
            Appointment.customer_id == customer.id,
            Appointment.status.in_((AppointmentStatus.PENDING.value, AppointmentStatus.CONFIRMED.value)),
            Appointment.starts_at >= datetime.now(),
        ).order_by(Appointment.starts_at)
    ).first()
    if upcoming_appointment is not None:
        return upcoming_appointment

    return _latest_active_appointment_for_customer(session, customer, barber_shop_id)


def _handle_appointment_lookup(
    session: Session,
    message: str,
    barber_shop_id: int,
    from_phone: str,
    context: BotConversationContext | None = None,
) -> BotMessages | None:
    if not _looks_like_appointment_lookup(message):
        return None

    customer = _existing_customer_for_sender_phone(session, barber_shop_id, from_phone)
    if customer is None:
        return [("bot", "No encontre turnos activos asociados a este telefono.")]

    appointment = _next_active_appointment_for_customer(session, customer, barber_shop_id)
    if appointment is None:
        return [("bot", "No encontre turnos activos asociados a este telefono.")]

    if context is not None:
        context.barber_shop_id = barber_shop_id
        context.customer_id = customer.id
        context.service_id = appointment.service_id
        context.last_target_date = appointment.starts_at.date()

    return [
        (
            "bot",
            f"Tenes un turno #{appointment.id} el {_format_date(appointment.starts_at.date())} "
            f"a las {appointment.starts_at:%H:%M} para {appointment.service.name} "
            f"con {appointment.barber.name}.",
        )
    ]


def _handle_cancel_request(
    session: Session,
    message: str,
    barber_shop_id: int,
    from_phone: str,
    context: BotConversationContext | None = None,
) -> BotMessages | None:
    if not _looks_like_cancel_request(message):
        return None

    _find_service_for_conversation(session, message, barber_shop_id, context)
    customer = _customer_for_sender_phone(session, barber_shop_id, from_phone)
    if context is not None:
        context.customer_id = customer.id

    appointment = _latest_active_appointment_for_customer(session, customer, barber_shop_id)
    if appointment is None:
        return [("bot", "No encontre turnos activos para cancelar.")]

    cancel_appointment(session, appointment.id)
    if context is not None:
        context.reset()

    return [
        (
            "bot",
            f"Listo, cancele el turno #{appointment.id} del "
            f"{_format_date(appointment.starts_at.date())} a las {appointment.starts_at:%H:%M}.",
        )
    ]


def _handle_reschedule_request(
    session: Session,
    message: str,
    barber_shop_id: int,
    from_phone: str,
    context: BotConversationContext | None = None,
) -> BotMessages | None:
    if not _looks_like_reschedule_request(message):
        return None

    _find_service_for_conversation(session, message, barber_shop_id, context)
    customer = _customer_for_sender_phone(session, barber_shop_id, from_phone)
    if context is not None:
        context.customer_id = customer.id

    appointment = _latest_active_appointment_for_customer(session, customer, barber_shop_id)
    if appointment is None:
        return [("bot", "No encontre turnos activos para reprogramar.")]

    target_date = _parse_target_date(message)
    target_time = _parse_target_time(message)
    if target_date is None and context is not None:
        target_date = context.last_target_date
    if target_date is None or target_time is None:
        return [("bot", "Decime nuevo dia y hora. Por ejemplo: reprogramar sabado a las 10:00.")]

    try:
        starts_at = datetime.fromisoformat(f"{target_date.isoformat()}T{target_time}:00")
        updated_appointment = reschedule_appointment(session, appointment.id, starts_at)
        updated_appointment.status = AppointmentStatus.CONFIRMED.value
        session.commit()
        session.refresh(updated_appointment)
        if context is not None:
            context.barber_shop_id = barber_shop_id
            context.service_id = updated_appointment.service_id
            context.last_target_date = updated_appointment.starts_at.date()
    except SchedulingError as exc:
        return [("bot", exc.detail)]
    except ValueError:
        return [("bot", "No pude entender la nueva fecha u hora.")]

    return [
        (
            "bot",
            f"Listo, reprograme el turno #{updated_appointment.id} para "
            f"{_format_date(updated_appointment.starts_at.date())} a las {updated_appointment.starts_at:%H:%M}.",
        )
    ]


def _handle_booking_request(
    session: Session,
    message: str,
    barber_shop_id: int,
    from_phone: str,
    context: BotConversationContext | None = None,
) -> BotMessages | None:
    target_date = _parse_target_date(message)
    target_time = _parse_target_time(message)
    service_from_message = _find_service_from_message(session, message, barber_shop_id)
    can_complete_from_context = (
        context is not None
        and context.service_id is not None
        and target_time is not None
        and (target_date is not None or context.last_target_date is not None)
    )
    can_complete_from_message = service_from_message is not None and target_date is not None and target_time is not None
    if not _looks_like_booking_request(message) and not can_complete_from_context and not can_complete_from_message:
        return None

    service = service_from_message or _find_service_for_conversation(session, message, barber_shop_id, context)
    if service is None:
        return [("bot", "Que servicio queres reservar: corte, claritos o corte + claritos?")]

    barber = _find_barber_for_service(session, service, message)
    if barber is None:
        return [("bot", f"Todavia no hay profesionales activos para {service.name}.")]

    customer = _customer_for_sender_phone(session, barber_shop_id, from_phone)
    if context is not None:
        context.customer_id = customer.id

    recent_booking = _customer_has_recent_active_booking(session, customer, barber_shop_id)
    if recent_booking is not None:
        return [
            (
                "bot",
                f"Ya tenes un turno activo reciente: #{recent_booking.id} el "
                f"{_format_date(recent_booking.starts_at.date())} a las {recent_booking.starts_at:%H:%M}. "
                "Para este demo no te dejo reservar otro enseguida.",
            )
        ]

    if target_date is None and context is not None:
        target_date = context.last_target_date
    if target_date is None or target_time is None:
        return [("bot", "Decime dia y hora. Por ejemplo: reservame corte manana a las 10:00.")]

    try:
        starts_at = datetime.fromisoformat(f"{target_date.isoformat()}T{target_time}:00")
        appointment = create_appointment(
            session,
            barber_id=barber.id,
            customer_id=customer.id,
            service_id=service.id,
            starts_at=starts_at,
        )
        appointment.status = AppointmentStatus.CONFIRMED.value
        session.commit()
        session.refresh(appointment)
        if context is not None:
            context.barber_shop_id = barber_shop_id
            context.last_target_date = appointment.starts_at.date()
    except SchedulingError as exc:
        if "overlaps" in exc.detail:
            slots = get_available_slots(
                session,
                barber_id=barber.id,
                service_id=service.id,
                target_date=target_date,
            )
            if slots:
                return [
                    (
                        "bot",
                        "Ese horario ya esta ocupado. Te puedo ofrecer: " + _format_slot_times(slots, 6) + ".",
                    )
                ]
        return [("bot", exc.detail)]
    except ValueError:
        return [("bot", "No pude entender la fecha u hora. Proba con: manana a las 10:00.")]

    return [
        (
            "bot",
            f"Listo, te confirme el turno #{appointment.id} para {service.name} "
            f"el {_format_date(appointment.starts_at.date())} a las {appointment.starts_at:%H:%M}.",
        )
    ]


def _list_barbers(session: Session, barber_shop_id: int) -> BotMessages:
    barbers = session.scalars(
        select(Barber)
        .where(Barber.barber_shop_id == barber_shop_id, Barber.is_active.is_(True))
        .order_by(Barber.id)
    ).all()
    if not barbers:
        return [("bot", "Todavia no hay profesionales cargados.")]

    lines = [f"#{barber.id} {barber.name}" for barber in barbers]
    return [("bot", "Profesionales disponibles: " + " | ".join(lines))]


def _list_customers(session: Session, barber_shop_id: int) -> BotMessages:
    customers = session.scalars(
        select(Customer).where(Customer.barber_shop_id == barber_shop_id).order_by(Customer.id)
    ).all()
    if not customers:
        return [("bot", "Todavia no hay clientes cargados.")]

    lines = [f"#{customer.id} {customer.full_name} ({customer.phone})" for customer in customers]
    return [("bot", "Clientes registrados: " + " | ".join(lines))]


def _parse_availability(message: str) -> tuple[int, int, date] | None:
    patterns = (
        r"(?:horarios|disponibilidad)\s+barbero\s*(\d+)\s+servicio\s*(\d+)\s+fecha\s*(\d{4}-\d{2}-\d{2})",
        r"(?:horarios|disponibilidad)\s+(\d+)\s+(\d+)\s+(\d{4}-\d{2}-\d{2})",
    )
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            barber_id, service_id, target_date = match.groups()
            return int(barber_id), int(service_id), date.fromisoformat(target_date)
    return None


def _parse_booking(message: str) -> tuple[int, int, int, datetime] | None:
    patterns = (
        r"reservar\s+barbero\s*(\d+)\s+cliente\s*(\d+)\s+servicio\s*(\d+)\s+fecha\s*(\d{4}-\d{2}-\d{2})\s+hora\s*(\d{2}:\d{2})",
        r"reservar\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})",
    )
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            barber_id, customer_id, service_id, target_date, target_time = match.groups()
            return (
                int(barber_id),
                int(customer_id),
                int(service_id),
                datetime.fromisoformat(f"{target_date}T{target_time}:00"),
            )
    return None


def _barber_belongs_to_shop(session: Session, barber_id: int, barber_shop_id: int) -> bool:
    return (
        session.scalars(
            select(Barber.id).where(
                Barber.id == barber_id,
                Barber.barber_shop_id == barber_shop_id,
                Barber.is_active.is_(True),
            )
        ).first()
        is not None
    )


def _service_belongs_to_shop(session: Session, service_id: int, barber_shop_id: int) -> bool:
    return _service_for_shop(session, service_id, barber_shop_id) is not None


def _customer_belongs_to_shop(session: Session, customer_id: int, barber_shop_id: int) -> bool:
    return (
        session.scalars(
            select(Customer.id).where(Customer.id == customer_id, Customer.barber_shop_id == barber_shop_id)
        ).first()
        is not None
    )


def _handle_ai_intent(session: Session, intent: BotIntent, barber_shop_id: int, from_phone: str) -> BotMessages | None:
    if intent.intent == "list_services":
        return _list_services(session, barber_shop_id)

    if intent.intent == "list_barbers":
        return _list_barbers(session, barber_shop_id)

    if intent.intent == "list_customers":
        return _list_customers(session, barber_shop_id)

    if intent.intent == "check_availability":
        if intent.barber_id is None or intent.service_id is None or intent.target_date is None:
            return [("bot", intent.reply or "Necesito profesional, servicio y fecha para buscar horarios.")]
        if not _barber_belongs_to_shop(session, intent.barber_id, barber_shop_id) or not _service_belongs_to_shop(
            session,
            intent.service_id,
            barber_shop_id,
        ):
            return [("bot", "No encontre ese profesional o servicio para este negocio.")]

        try:
            target_date = date.fromisoformat(intent.target_date)
            slots = get_available_slots(
                session,
                barber_id=intent.barber_id,
                service_id=intent.service_id,
                target_date=target_date,
            )
        except (SchedulingError, ValueError) as exc:
            return [("bot", str(exc))]

        if not slots:
            return [("bot", "No encontre horarios disponibles para esa fecha.")]

        lines = [slot["starts_at"].strftime("%H:%M") for slot in slots[:6]]
        return [("bot", f"Horarios disponibles para {target_date.isoformat()}: " + ", ".join(lines))]

    if intent.intent == "create_appointment":
        required_values = (
            intent.barber_id,
            intent.service_id,
            intent.target_date,
            intent.target_time,
        )
        if any(value is None for value in required_values):
            return [("bot", intent.reply or "Necesito profesional, servicio, fecha y hora para reservar.")]
        if (
            not _barber_belongs_to_shop(session, intent.barber_id, barber_shop_id)
            or not _service_belongs_to_shop(session, intent.service_id, barber_shop_id)
        ):
            return [("bot", "No encontre profesional o servicio para este negocio.")]

        try:
            customer = _customer_for_sender_phone(session, barber_shop_id, from_phone)
            recent_booking = _customer_has_recent_active_booking(session, customer, barber_shop_id)
            if recent_booking is not None:
                return [
                    (
                        "bot",
                        f"Ya tenes un turno activo reciente: #{recent_booking.id} el "
                        f"{_format_date(recent_booking.starts_at.date())} a las {recent_booking.starts_at:%H:%M}.",
                    )
                ]

            starts_at = datetime.fromisoformat(f"{intent.target_date}T{intent.target_time}:00")
            appointment = create_appointment(
                session,
                barber_id=intent.barber_id,
                customer_id=customer.id,
                service_id=intent.service_id,
                starts_at=starts_at,
            )
            appointment.status = AppointmentStatus.CONFIRMED.value
            session.commit()
            session.refresh(appointment)
        except (SchedulingError, ValueError) as exc:
            return [("bot", str(exc))]

        return [("bot", f"Listo, turno #{appointment.id} confirmado y reflejado en Gestion.")]

    if intent.reply:
        return [("bot", intent.reply)]

    return None


def process_bot_message(
    session: Session,
    message: str,
    barber_shop_id: int,
    from_phone: str,
    context: BotConversationContext | None = None,
) -> BotMessages:
    normalized = _normalize_text(message)
    if not normalized:
        return [("bot", "Necesito un mensaje para poder ayudarte.")]
    if not from_phone.strip():
        return [("bot", "Necesito el telefono del remitente para poder ayudarte.")]

    if context is not None:
        context.barber_shop_id = barber_shop_id

    if not _has_enabled_bot(session, barber_shop_id):
        return [("bot", "El bot esta desactivado para este negocio.")]

    ai_intent = classify_with_ai(session, message, barber_shop_id)
    if ai_intent is not None:
        ai_response = _handle_ai_intent(session, ai_intent, barber_shop_id, from_phone)
        if ai_response is not None:
            return ai_response

    availability = _parse_availability(normalized)
    if availability is not None:
        barber_id, service_id, target_date = availability
        if not _barber_belongs_to_shop(session, barber_id, barber_shop_id) or not _service_belongs_to_shop(
            session,
            service_id,
            barber_shop_id,
        ):
            return [("bot", "No encontre ese profesional o servicio para este negocio.")]
        try:
            slots = get_available_slots(
                session,
                barber_id=barber_id,
                service_id=service_id,
                target_date=target_date,
            )
        except SchedulingError as exc:
            return [("bot", exc.detail)]

        if not slots:
            return [("bot", "No encontre horarios disponibles para esa fecha.")]

        lines = [slot["starts_at"].strftime("%H:%M") for slot in slots[:6]]
        return [("bot", f"Horarios disponibles para {target_date.isoformat()}: " + ", ".join(lines))]

    booking = _parse_booking(normalized)
    if booking is not None:
        barber_id, customer_id, service_id, starts_at = booking
        if (
            not _barber_belongs_to_shop(session, barber_id, barber_shop_id)
            or not _service_belongs_to_shop(session, service_id, barber_shop_id)
            or not _customer_belongs_to_shop(session, customer_id, barber_shop_id)
        ):
            return [("bot", "No encontre profesional, cliente o servicio para este negocio.")]
        try:
            appointment = create_appointment(
                session,
                barber_id=barber_id,
                customer_id=customer_id,
                service_id=service_id,
                starts_at=starts_at,
            )
        except SchedulingError as exc:
            return [("bot", exc.detail)]

        appointment.status = AppointmentStatus.CONFIRMED.value
        session.commit()
        session.refresh(appointment)
        return [("bot", f"Listo, turno #{appointment.id} confirmado y reflejado en Gestion.")]

    price_answer = _handle_price_question(session, normalized, barber_shop_id, context)
    if price_answer is not None:
        return price_answer

    cancel_answer = _handle_cancel_request(session, normalized, barber_shop_id, from_phone, context)
    if cancel_answer is not None:
        return cancel_answer

    reschedule_answer = _handle_reschedule_request(session, normalized, barber_shop_id, from_phone, context)
    if reschedule_answer is not None:
        return reschedule_answer

    appointment_lookup_answer = _handle_appointment_lookup(session, normalized, barber_shop_id, from_phone, context)
    if appointment_lookup_answer is not None:
        return appointment_lookup_answer

    booking_answer = _handle_booking_request(session, normalized, barber_shop_id, from_phone, context)
    if booking_answer is not None:
        return booking_answer

    availability_answer = _handle_availability_question(session, normalized, barber_shop_id, context)
    if availability_answer is not None:
        return availability_answer

    service_interest_answer = _handle_service_interest(session, normalized, barber_shop_id, context)
    if service_interest_answer is not None:
        return service_interest_answer

    if any(word in normalized for word in GREETING_WORDS):
        return [
            (
                "bot",
                "Hola! Soy el asistente de TurnoFlow. Te puedo contar precios, mostrar horarios libres "
                "o reservarte un turno confirmado.",
            )
        ]

    if "servicio" in normalized:
        return _list_services(session, barber_shop_id)

    if "barbero" in normalized or "profesional" in normalized:
        return _list_barbers(session, barber_shop_id)

    if "cliente" in normalized:
        return _list_customers(session, barber_shop_id)

    return [
        (
            "bot",
            "Puedo mostrar servicios, profesionales, clientes, horarios o registrar una reserva con datos concretos.",
        )
    ]
