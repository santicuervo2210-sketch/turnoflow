from datetime import date, datetime, time, timedelta
from decimal import Decimal
from http import HTTPStatus
import hashlib
import hmac

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import log_unhandled_error
from app.core.rate_limit import is_rate_limited
from app.db.session import get_db
from app.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    BarberShop,
    BarberTimeBlock,
    Customer,
    Service,
    SupplySale,
    User,
    UserRole,
    WorkingSchedule,
)
from app.services.appointments import (
    ALL_WEEKDAYS,
    BUSINESS_WEEKDAYS,
    DEFAULT_CLOSING_TIME,
    DEFAULT_OPENING_TIME,
    SchedulingError,
    activate_barber_shop,
    barber_can_perform_service,
    business_hours_for_shop,
    business_working_days_for_shop,
    cancel_appointment,
    create_appointment,
    get_available_slots,
    mark_appointment_paid,
    mark_appointment_unpaid,
    reschedule_appointment,
    suspend_barber_shop,
    update_appointment_status,
)
from app.services.bot_flow import BotConversationContext, process_bot_message
from app.services.bot_settings import get_or_create_bot_settings, list_pending_reminders, update_bot_settings
from app.services.supply_sales import create_supply_sale
from app.services.users import authenticate_user, create_password_reset_token, create_user, reset_password_with_token
from app.schemas.business import BotWebhookRequest, BotWebhookResponse
from app.web.auth import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    csrf_token_for_request,
    parse_session_subject,
    session_subject_for_env_owner,
    session_subject_for_user,
    set_csrf_cookie,
    set_session_cookie,
    validate_admin_credentials,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
BOT_SIMULATOR_CONTEXTS: dict[tuple[int, str], BotConversationContext] = {}
BOT_SIMULATOR_FROM_PHONE = "+5491100000000"
WEEKDAY_SHORT_LABELS = ("Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom")
ADMIN_MODULES = {"agenda", "clientes", "servicios", "equipo", "configuracion", "rendimiento"}
OWNER_MANAGED_SHOP_COOKIE = "turnoflow_owner_shop"


def _redirect_to(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=HTTPStatus.SEE_OTHER)


def _panel_template_response(
    request: Request,
    template_name: str,
    context: dict,
    status_code: int = HTTPStatus.OK,
):
    csrf_token = csrf_token_for_request(request)
    context = {"csrf_token": csrf_token, **context}
    response = templates.TemplateResponse(request, template_name, context, status_code=status_code)
    set_csrf_cookie(response, csrf_token)
    return response


def _safe_next_path(next_path: str | None) -> str:
    if not next_path or not next_path.startswith("/") or next_path.startswith("//"):
        return "/admin"
    return next_path


def _client_host(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _current_user(request: Request, session: Session) -> User | None:
    subject = parse_session_subject(request.cookies.get(SESSION_COOKIE_NAME))
    if subject is None or not subject.startswith("user:"):
        return None

    parts = subject.split(":")
    if len(parts) != 3:
        return None

    try:
        user_id = int(parts[1])
    except ValueError:
        return None

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


def _managed_shop_cookie_value(barber_shop_id: int) -> str:
    payload = str(barber_shop_id)
    signature = hmac.new(
        settings.session_secret.encode("utf-8"),
        f"owner-shop:{payload}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{signature}"


def _managed_shop_id(request: Request, session: Session) -> int | None:
    value = request.cookies.get(OWNER_MANAGED_SHOP_COOKIE)
    if not value or ":" not in value:
        return None
    shop_id_text, signature = value.rsplit(":", 1)
    expected_signature = hmac.new(
        settings.session_secret.encode("utf-8"),
        f"owner-shop:{shop_id_text}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None
    try:
        shop_id = int(shop_id_text)
    except ValueError:
        return None
    return shop_id if session.get(BarberShop, shop_id) is not None else None


def _current_shop_id(request: Request, session: Session) -> int | None:
    user = _current_user(request, session)
    if user is not None and user.role == UserRole.BUSINESS_ADMIN.value:
        return user.barber_shop_id
    if _is_owner_request(request, session):
        return _managed_shop_id(request, session)
    return None


def _is_owner_request(request: Request, session: Session) -> bool:
    if not settings.auth_enabled:
        return True
    subject = parse_session_subject(request.cookies.get(SESSION_COOKIE_NAME))
    if subject is not None and subject.endswith(f":{UserRole.OWNER.value}"):
        return True
    user = _current_user(request, session)
    return user is not None and user.role == UserRole.OWNER.value


def _redirect_if_not_owner(request: Request, session: Session) -> RedirectResponse | None:
    if _is_owner_request(request, session):
        return None
    return _redirect_to("/admin")


def _shop_allowed(request: Request, session: Session, barber_shop_id: int) -> bool:
    if _is_owner_request(request, session):
        return True
    return _current_shop_id(request, session) == barber_shop_id


def _redirect_if_shop_not_allowed(request: Request, session: Session, barber_shop_id: int) -> RedirectResponse | None:
    if session.get(BarberShop, barber_shop_id) is None:
        return _redirect_to("/admin")
    if _shop_allowed(request, session, barber_shop_id):
        return None
    return _redirect_to("/admin")


def _redirect_if_appointment_not_allowed(
    request: Request,
    session: Session,
    appointment_id: int,
) -> RedirectResponse | None:
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        return _redirect_to("/admin")
    return _redirect_if_shop_not_allowed(request, session, appointment.barber_shop_id)


def _shop_filter(query, shop_id: int | None, model):
    if shop_id is None:
        return query
    return query.where(model.barber_shop_id == shop_id)


def _date_query_param(request: Request, name: str) -> date | None:
    raw_value = request.query_params.get(name)
    if not raw_value:
        return None
    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        return None


def _int_query_param(request: Request, name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = request.query_params.get(name)
    try:
        value = int(raw_value) if raw_value is not None else default
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _admin_module_param(request: Request) -> str:
    module = request.query_params.get("module", "agenda")
    return module if module in ADMIN_MODULES else "agenda"


def _as_naive_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _dashboard_context(request: Request, session: Session, shop_id: int | None = None, **extra):
    shops_query = select(BarberShop).order_by(BarberShop.id)
    if shop_id is not None:
        shops_query = shops_query.where(BarberShop.id == shop_id)
    shops = list(session.scalars(shops_query).all())

    start_date = _date_query_param(request, "start_date")
    end_date = _date_query_param(request, "end_date")
    page = _int_query_param(request, "page", default=1, minimum=1, maximum=10_000)
    per_page = _int_query_param(request, "per_page", default=50, minimum=1, maximum=200)

    appointments_query = _shop_filter(select(Appointment), shop_id, Appointment)
    if start_date is not None:
        appointments_query = appointments_query.where(Appointment.starts_at >= datetime.combine(start_date, time.min))
    if end_date is not None:
        appointments_query = appointments_query.where(Appointment.starts_at <= datetime.combine(end_date, time.max))
    total_filtered_appointments = session.scalar(
        select(func.count()).select_from(appointments_query.order_by(None).subquery())
    ) or 0
    appointments = list(
        session.scalars(
            appointments_query.order_by(Appointment.starts_at).offset((page - 1) * per_page).limit(per_page)
        ).all()
    )
    agenda_appointments = list(
        session.scalars(
            _shop_filter(select(Appointment).order_by(Appointment.starts_at), shop_id, Appointment)
        ).all()
    )
    supply_sales = list(
        session.scalars(_shop_filter(select(SupplySale).order_by(SupplySale.id), shop_id, SupplySale)).all()
    )
    now = datetime.now()
    today = now.date()
    tomorrow = today + timedelta(days=1)
    agenda_source_appointments = appointments if start_date is not None or end_date is not None else agenda_appointments
    active_appointments = [
        appointment
        for appointment in agenda_source_appointments
        if appointment.status in (AppointmentStatus.PENDING.value, AppointmentStatus.CONFIRMED.value)
        and _as_naive_datetime(appointment.starts_at) >= now
    ]
    active_appointment_ids = {appointment.id for appointment in active_appointments}
    agenda_today_appointments = [appointment for appointment in active_appointments if appointment.starts_at.date() == today]
    agenda_tomorrow_appointments = [
        appointment for appointment in active_appointments if appointment.starts_at.date() == tomorrow
    ]
    agenda_upcoming_appointments = [
        appointment for appointment in active_appointments if appointment.starts_at.date() > tomorrow
    ]
    appointment_history = [
        appointment for appointment in agenda_source_appointments if appointment.id not in active_appointment_ids
    ]
    today_start = datetime.combine(today, time.min)
    today_end = datetime.combine(today, time.max)
    today_supply_sales = [
        sale
        for sale in supply_sales
        if sale.created_at is not None and today_start <= sale.created_at.replace(tzinfo=None) <= today_end
    ]
    paid_appointments = [appointment for appointment in agenda_appointments if appointment.is_paid]
    paid_today_appointments = [
        appointment
        for appointment in paid_appointments
        if appointment.paid_at is not None and today_start <= appointment.paid_at.replace(tzinfo=None) <= today_end
    ]
    completed_paid_appointments = [
        appointment
        for appointment in agenda_appointments
        if appointment.status == AppointmentStatus.COMPLETED.value and appointment.is_paid
    ]
    cancelled_appointments = [
        appointment for appointment in agenda_appointments if appointment.status == AppointmentStatus.CANCELLED.value
    ]
    appointment_revenue = sum(
        appointment.service.price
        for appointment in paid_appointments
        if appointment.service is not None
    )
    completed_appointment_revenue = sum(
        appointment.service.price
        for appointment in completed_paid_appointments
        if appointment.service is not None
    )
    active_expected_revenue = sum(
        appointment.service.price
        for appointment in active_appointments
        if appointment.service is not None
    )
    cancelled_value = sum(
        appointment.service.price
        for appointment in cancelled_appointments
        if appointment.service is not None
    )
    supply_revenue = sum(sale.total_price for sale in supply_sales)
    today_appointment_revenue = sum(
        appointment.service.price
        for appointment in paid_today_appointments
        if appointment.service is not None
    )
    today_supply_revenue = sum(sale.total_price for sale in today_supply_sales)
    services = list(session.scalars(_shop_filter(select(Service).order_by(Service.id), shop_id, Service)).all())
    barbers = list(session.scalars(_shop_filter(select(Barber).order_by(Barber.id), shop_id, Barber)).all())
    customers = list(session.scalars(_shop_filter(select(Customer).order_by(Customer.id), shop_id, Customer)).all())
    context = {
        "request": request,
        "now": now,
        "as_naive_datetime": _as_naive_datetime,
        "shops": shops,
        "services": services,
        "barbers": barbers,
        "customers": customers,
        "general_hours_by_shop": {
            shop.id: business_hours_for_shop(session, shop.id) for shop in shops
        },
        "general_working_days_by_shop": {
            shop.id: business_working_days_for_shop(session, shop.id) for shop in shops
        },
        "working_days_by_barber": {
            barber.id: sorted(
                schedule.day_of_week
                for schedule in barber.working_schedules
                if schedule.is_active
            )
            or list(BUSINESS_WEEKDAYS)
            for barber in barbers
        },
        "working_hours_by_barber": {
            barber.id: next(
                (
                    (schedule.start_time, schedule.end_time)
                    for schedule in barber.working_schedules
                    if schedule.is_active
                ),
                business_hours_for_shop(session, barber.barber_shop_id),
            )
            for barber in barbers
        },
        "weekday_labels": ("Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"),
        "schedules": list(
            session.scalars(
                select(WorkingSchedule)
                .join(WorkingSchedule.barber)
                .where(Barber.barber_shop_id == shop_id, WorkingSchedule.is_active.is_(True))
                .order_by(WorkingSchedule.id)
                if shop_id is not None
                else select(WorkingSchedule).where(WorkingSchedule.is_active.is_(True)).order_by(WorkingSchedule.id)
            ).all()
        ),
        "time_blocks": list(
            session.scalars(
                select(BarberTimeBlock)
                .join(BarberTimeBlock.barber)
                .where(BarberTimeBlock.is_active.is_(True), Barber.barber_shop_id == shop_id)
                .order_by(BarberTimeBlock.starts_at.desc())
                if shop_id is not None
                else select(BarberTimeBlock)
                .where(BarberTimeBlock.is_active.is_(True))
                .order_by(BarberTimeBlock.starts_at.desc())
            ).all()
        ),
        "appointments": appointments,
        "active_appointments": active_appointments,
        "agenda_today_appointments": agenda_today_appointments,
        "agenda_tomorrow_appointments": agenda_tomorrow_appointments,
        "agenda_upcoming_appointments": agenda_upcoming_appointments,
        "appointment_history": appointment_history,
        "supply_sales": supply_sales,
        "today_supply_sales": today_supply_sales,
        "bot_settings_by_shop": {shop.id: get_or_create_bot_settings(session, shop.id) for shop in shops},
        "pending_reminders": [
            reminder
            for reminder in list_pending_reminders(session)
            if shop_id is None or reminder.barber_shop_id == shop_id
        ],
        "bot_ai_provider": settings.bot_ai_provider,
        "ollama_model": settings.ollama_model,
        "dashboard_filters": {
            "start_date": start_date.isoformat() if start_date is not None else "",
            "end_date": end_date.isoformat() if end_date is not None else "",
            "page": page,
            "per_page": per_page,
            "total": total_filtered_appointments,
            "has_previous": page > 1,
            "has_next": page * per_page < total_filtered_appointments,
        },
        "selected_module": _admin_module_param(request),
        "current_user": _current_user(request, session),
        "is_owner_view": _is_owner_request(request, session) or not settings.auth_enabled,
        "managed_shop": shops[0] if shop_id is not None and shops and _is_owner_request(request, session) else None,
        "stats": {
            "shops": len(shops),
            "active_shops": len([shop for shop in shops if shop.access_status == "active"]),
            "appointments": len(appointments),
            "active_appointments": len(active_appointments),
            "history_appointments": len(appointment_history),
            "paid_appointments": len(paid_appointments),
            "revenue": appointment_revenue + supply_revenue,
            "completed_revenue": completed_appointment_revenue,
            "active_expected_revenue": active_expected_revenue,
            "cancelled_value": cancelled_value,
            "supply_revenue": supply_revenue,
            "today_appointment_revenue": today_appointment_revenue,
            "today_supply_revenue": today_supply_revenue,
            "today_total_revenue": today_appointment_revenue + today_supply_revenue,
        },
    }
    context.update(extra)
    return context


def _customer_appointments_context(
    request: Request,
    session: Session,
    customer_id: int | None = None,
    shop_id: int | None = None,
    **extra,
):
    customers_query = select(Customer).order_by(Customer.id)
    if shop_id is not None:
        customers_query = customers_query.where(Customer.barber_shop_id == shop_id)
    customers = list(session.scalars(customers_query).all())
    selected_customer = session.get(Customer, customer_id) if customer_id is not None else (customers[0] if customers else None)
    if selected_customer is not None and shop_id is not None and selected_customer.barber_shop_id != shop_id:
        selected_customer = None
    confirmed_appointments = []

    if selected_customer is not None:
        confirmed_appointments = list(
            session.scalars(
                select(Appointment).where(
                    Appointment.customer_id == selected_customer.id,
                    Appointment.status == AppointmentStatus.CONFIRMED.value,
                ).order_by(Appointment.starts_at)
            ).all()
        )

    context = {
        "request": request,
        "customers": customers,
        "selected_customer": selected_customer,
        "confirmed_appointments": confirmed_appointments,
    }
    context.update(extra)
    return context


def _first_barber_for_service(session: Session, service: Service) -> Barber | None:
    barbers = session.scalars(
        select(Barber).where(
            Barber.barber_shop_id == service.barber_shop_id,
            Barber.is_active.is_(True),
        ).order_by(Barber.id)
    ).all()
    return next((barber for barber in barbers if barber_can_perform_service(session, barber, service)), None)


def _bot_simulator_shop_id(request: Request, session: Session) -> int | None:
    shop_id = _current_shop_id(request, session)
    if shop_id is not None:
        return shop_id

    shop = session.scalars(
        select(BarberShop).where(BarberShop.access_status == "active").order_by(BarberShop.id)
    ).first()
    return shop.id if shop is not None else None


def _bot_context_for(barber_shop_id: int, from_phone: str) -> BotConversationContext:
    key = (barber_shop_id, from_phone.strip())
    if key not in BOT_SIMULATOR_CONTEXTS:
        BOT_SIMULATOR_CONTEXTS[key] = BotConversationContext(barber_shop_id=barber_shop_id)
    return BOT_SIMULATOR_CONTEXTS[key]


def _bot_quick_actions(
    session: Session,
    barber_shop_id: int | None,
    context: BotConversationContext | None,
) -> list[dict[str, str]]:
    service = None
    if context is not None and context.service_id and barber_shop_id is not None:
        service = session.scalars(
            select(Service).where(
                Service.id == context.service_id,
                Service.barber_shop_id == barber_shop_id,
                Service.is_active.is_(True),
            )
        ).first()
    if service is None:
        actions = [
            {"label": "Sacar turno", "message": "2"},
            {"label": "Servicios y precios", "message": "1"},
            {"label": "Mi turno", "message": "3"},
            {"label": "Cancelar o mover", "message": "4"},
        ]
        return actions[:8]

    barber = _first_barber_for_service(session, service)
    if barber is None:
        return [{"label": "Servicios", "message": "servicios"}]

    if context is not None and context.last_target_date is not None:
        try:
            slots = get_available_slots(
                session,
                barber_id=barber.id,
                service_id=service.id,
                target_date=context.last_target_date,
            )
        except SchedulingError:
            slots = []
        if slots:
            actions = [
                {
                    "label": slot["starts_at"].strftime("%H:%M"),
                    "message": slot["starts_at"].strftime("%H:%M"),
                }
                for slot in slots[:8]
            ]
            actions.append({"label": "Otro dia", "message": "que dias tenes disponibles"})
            actions.append({"label": "Volver", "message": "0"})
            return actions

    actions: list[dict[str, str]] = [
        {"label": f"Precio {service.name}", "message": f"cuanto sale {service.name}"},
    ]
    for offset in range(7):
        target_date = date.today() + timedelta(days=offset)
        try:
            slots = get_available_slots(
                session,
                barber_id=barber.id,
                service_id=service.id,
                target_date=target_date,
            )
        except SchedulingError:
            slots = []
        if slots:
            actions.append(
                {
                    "label": f"{WEEKDAY_SHORT_LABELS[target_date.weekday()]} {target_date:%d/%m}",
                    "message": target_date.isoformat(),
                }
            )
        if len(actions) >= 6:
            break

    actions.append({"label": "Cambiar servicio", "message": "2"})
    actions.append({"label": "Volver", "message": "0"})
    return actions


def _bot_context_extra(
    session: Session,
    barber_shop_id: int | None,
    context: BotConversationContext | None,
) -> dict:
    selected_service = (
        session.scalars(
            select(Service).where(
                Service.id == context.service_id,
                Service.barber_shop_id == barber_shop_id,
                Service.is_active.is_(True),
            )
        ).first()
        if context is not None and context.service_id is not None and barber_shop_id is not None
        else None
    )
    return {
        "bot_quick_actions": _bot_quick_actions(session, barber_shop_id, context),
        "bot_selected_service": selected_service,
        "bot_selected_date": context.last_target_date if context is not None else None,
        "bot_barber_shop_id": barber_shop_id,
    }


def _bot_simulator_resource_error(
    request: Request,
    session: Session,
    barber_id: int,
    service_id: int,
) -> str | None:
    barber = session.get(Barber, barber_id)
    service = session.get(Service, service_id)
    if barber is None or service is None:
        return "El profesional o servicio no existe."
    if not _shop_allowed(request, session, barber.barber_shop_id):
        return "Ese recurso no pertenece a tu negocio."
    if service.barber_shop_id != barber.barber_shop_id:
        return "El servicio no pertenece a ese negocio."
    return None


def _save(session: Session, item):
    try:
        session.add(item)
        session.commit()
        session.refresh(item)
    except IntegrityError:
        session.rollback()
        raise
    return item


def _admin_error_response(
    request: Request,
    session: Session,
    message: str,
    status_code: int = HTTPStatus.BAD_REQUEST,
    selected_module: str | None = None,
):
    context = _dashboard_context(
        request,
        session,
        shop_id=_current_shop_id(request, session),
        error=message,
    )
    if selected_module is not None:
        context["selected_module"] = selected_module
    return _panel_template_response(request, "admin/index.html", context, status_code=status_code)


@router.get("/")
def home() -> RedirectResponse:
    return _redirect_to("/admin")


@router.get("/login")
def login_page(request: Request, next: str | None = None):
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"request": request, "next_path": _safe_next_path(next)},
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next_path: str | None = Form(default="/admin"),
    session: Session = Depends(get_db),
):
    if is_rate_limited(
        f"login:{_client_host(request)}",
        settings.login_rate_limit_per_minute,
    ):
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail="Demasiados intentos de inicio de sesion.")

    if validate_admin_credentials(username, password):
        response = _redirect_to(_safe_next_path(next_path))
        set_session_cookie(response, session_subject_for_env_owner(username))
        return response

    user = authenticate_user(session, username, password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {
                "request": request,
                "next_path": _safe_next_path(next_path),
                "error": "Usuario o clave incorrectos.",
            },
            status_code=HTTPStatus.UNAUTHORIZED,
        )

    response = _redirect_to(_safe_next_path(next_path))
    set_session_cookie(response, session_subject_for_user(user))
    return response


@router.get("/password-reset")
def password_reset_page(request: Request, token: str):
    return templates.TemplateResponse(
        request,
        "auth/password_reset.html",
        {"request": request, "token": token},
    )


@router.post("/password-reset")
def password_reset_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_db),
):
    user = reset_password_with_token(session, token, password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "auth/password_reset.html",
            {"request": request, "token": token, "error": "El link no es valido o ya vencio."},
            status_code=HTTPStatus.BAD_REQUEST,
        )
    return _redirect_to("/login")


@router.get("/logout")
def logout() -> RedirectResponse:
    response = _redirect_to("/login")
    clear_session_cookie(response)
    return response


@router.get("/admin")
def admin_dashboard(request: Request, session: Session = Depends(get_db)):
    shop_id = _current_shop_id(request, session)
    return _panel_template_response(
        request,
        "admin/index.html",
        _dashboard_context(request, session, shop_id=shop_id),
    )


@router.get("/owner")
def owner_dashboard(request: Request, session: Session = Depends(get_db)):
    redirect = _redirect_if_not_owner(request, session)
    if redirect is not None:
        return redirect

    notice_messages = {
        "user_deactivated": "Acceso desactivado. La sesion del usuario deja de ser valida inmediatamente.",
        "user_activated": "Acceso reactivado.",
        "user_deleted": "Cuenta de acceso eliminada. Los datos del negocio se conservaron.",
        "user_must_be_inactive": "Primero desactiva la cuenta antes de eliminarla.",
    }
    return _panel_template_response(
        request,
        "owner/index.html",
        {
            "request": request,
            "shops": list(session.scalars(select(BarberShop).order_by(BarberShop.id)).all()),
            "users": list(session.scalars(select(User).order_by(User.id)).all()),
            "current_user": _current_user(request, session),
            "is_owner_view": True,
            "notice": notice_messages.get(request.query_params.get("notice", "")),
        },
    )


@router.post("/owner/users")
def owner_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    barber_shop_id: str = Form(default=""),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    redirect = _redirect_if_not_owner(request, session)
    if redirect is not None:
        return redirect

    try:
        selected_role = UserRole(role)
        parsed_shop_id = int(barber_shop_id) if barber_shop_id.strip() else None
    except ValueError:
        return _redirect_to("/owner")
    if not username.strip() or len(password) < 8:
        return _redirect_to("/owner")
    if selected_role == UserRole.BUSINESS_ADMIN and parsed_shop_id is None:
        return _redirect_to("/owner")
    if parsed_shop_id is not None and session.get(BarberShop, parsed_shop_id) is None:
        return _redirect_to("/owner")

    try:
        create_user(
            session,
            username=username,
            password=password,
            role=selected_role,
            barber_shop_id=parsed_shop_id,
        )
    except IntegrityError:
        session.rollback()
    return _redirect_to("/owner")


@router.post("/owner/users/{user_id}/password-reset-link")
def owner_create_password_reset_link(
    request: Request,
    user_id: int,
    session: Session = Depends(get_db),
) -> dict:
    redirect = _redirect_if_not_owner(request, session)
    if redirect is not None:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Se requiere acceso de superadministrador.")

    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Usuario no encontrado.")

    token = create_password_reset_token(user)
    return {"reset_url": f"/password-reset?token={token}"}


@router.get("/owner/users/{user_id}/password-reset")
def owner_password_reset_page(
    request: Request,
    user_id: int,
    session: Session = Depends(get_db),
):
    redirect = _redirect_if_not_owner(request, session)
    if redirect is not None:
        return redirect
    user = session.get(User, user_id)
    if user is None:
        return _redirect_to("/owner")
    token = create_password_reset_token(user)
    reset_path = f"/password-reset?token={token}"
    return _panel_template_response(
        request,
        "owner/password_reset_link.html",
        {
            "request": request,
            "user": user,
            "reset_url": f"{str(request.base_url).rstrip('/')}{reset_path}",
        },
    )


@router.post("/owner/users/{user_id}/deactivate")
def owner_deactivate_user(request: Request, user_id: int, session: Session = Depends(get_db)) -> RedirectResponse:
    redirect = _redirect_if_not_owner(request, session)
    if redirect is not None:
        return redirect
    user = session.get(User, user_id)
    if user is not None and user.role == UserRole.BUSINESS_ADMIN.value:
        user.is_active = False
        session.commit()
    return _redirect_to("/owner?notice=user_deactivated")


@router.post("/owner/users/{user_id}/activate")
def owner_activate_user(request: Request, user_id: int, session: Session = Depends(get_db)) -> RedirectResponse:
    redirect = _redirect_if_not_owner(request, session)
    if redirect is not None:
        return redirect
    user = session.get(User, user_id)
    if user is not None and user.role == UserRole.BUSINESS_ADMIN.value:
        user.is_active = True
        session.commit()
    return _redirect_to("/owner?notice=user_activated")


@router.post("/owner/users/{user_id}/delete")
def owner_delete_user(request: Request, user_id: int, session: Session = Depends(get_db)) -> RedirectResponse:
    redirect = _redirect_if_not_owner(request, session)
    if redirect is not None:
        return redirect
    user = session.get(User, user_id)
    if user is None or user.role != UserRole.BUSINESS_ADMIN.value:
        return _redirect_to("/owner")
    if user.is_active:
        return _redirect_to("/owner?notice=user_must_be_inactive")
    session.delete(user)
    session.commit()
    return _redirect_to("/owner?notice=user_deleted")


@router.get("/owner/shops/{barber_shop_id}/manage")
def owner_manage_shop(
    request: Request,
    barber_shop_id: int,
    session: Session = Depends(get_db),
) -> RedirectResponse:
    redirect = _redirect_if_not_owner(request, session)
    if redirect is not None:
        return redirect
    if session.get(BarberShop, barber_shop_id) is None:
        return _redirect_to("/owner")
    response = _redirect_to("/admin")
    response.set_cookie(
        OWNER_MANAGED_SHOP_COOKIE,
        _managed_shop_cookie_value(barber_shop_id),
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        max_age=60 * 60 * 4,
    )
    return response


@router.get("/owner/shops/manage/clear")
def owner_clear_managed_shop(request: Request, session: Session = Depends(get_db)) -> RedirectResponse:
    redirect = _redirect_if_not_owner(request, session)
    if redirect is not None:
        return redirect
    response = _redirect_to("/admin")
    response.delete_cookie(OWNER_MANAGED_SHOP_COOKIE)
    return response


@router.post("/admin/barber-shops")
def admin_create_barber_shop(
    request: Request,
    name: str = Form(...),
    phone: str | None = Form(default=None),
    address: str | None = Form(default=None),
    main_barber_name: str | None = Form(default=None),
    main_barber_phone: str | None = Form(default=None),
    main_barber_email: str | None = Form(default=None),
    next_path: str | None = Form(default="/admin"),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    redirect = _redirect_if_not_owner(request, session)
    if redirect is not None:
        return redirect
    if not name.strip():
        return _redirect_to(_safe_next_path(next_path))

    clean_main_barber_name = main_barber_name.strip() if main_barber_name else ""
    shop = BarberShop(
        name=name.strip(),
        phone=phone.strip() if phone else None,
        address=address.strip() if address else None,
    )
    if clean_main_barber_name:
        main_barber = Barber(
            name=clean_main_barber_name,
            phone=main_barber_phone.strip() if main_barber_phone else None,
            email=main_barber_email.strip() if main_barber_email else None,
        )
        main_barber.working_schedules = [
            WorkingSchedule(
                day_of_week=day_of_week,
                start_time=DEFAULT_OPENING_TIME,
                end_time=DEFAULT_CLOSING_TIME,
            )
            for day_of_week in ALL_WEEKDAYS
        ]
        shop.barbers.append(main_barber)
    _save(session, shop)
    return _redirect_to(_safe_next_path(next_path))


@router.post("/admin/barber-shops/{barber_shop_id}/suspend")
def admin_suspend_barber_shop(
    request: Request,
    barber_shop_id: int,
    reason: str | None = Form(default=None),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    redirect = _redirect_if_not_owner(request, session)
    if redirect is not None:
        return redirect
    suspend_barber_shop(session, barber_shop_id, reason or None)
    return _redirect_to("/admin")


@router.post("/admin/barber-shops/{barber_shop_id}/activate")
def admin_activate_barber_shop(request: Request, barber_shop_id: int, session: Session = Depends(get_db)) -> RedirectResponse:
    redirect = _redirect_if_not_owner(request, session)
    if redirect is not None:
        return redirect
    activate_barber_shop(session, barber_shop_id)
    return _redirect_to("/admin")


@router.post("/admin/barber-shops/{barber_shop_id}/hours")
def admin_update_business_hours(
    request: Request,
    barber_shop_id: int,
    opening_time: time = Form(...),
    closing_time: time = Form(...),
    working_days: list[int] = Form(default=[]),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    redirect = _redirect_if_shop_not_allowed(request, session, barber_shop_id)
    if redirect is not None:
        return redirect
    if opening_time >= closing_time:
        return _admin_error_response(
            request,
            session,
            "La hora de apertura debe ser anterior a la de cierre.",
            selected_module="configuracion",
        )
    selected_days = sorted(set(working_days))
    if not selected_days or any(day not in ALL_WEEKDAYS for day in selected_days):
        return _admin_error_response(
            request,
            session,
            "Selecciona al menos un dia de trabajo valido.",
            selected_module="configuracion",
        )

    barbers = list(
        session.scalars(
            select(Barber).where(
                Barber.barber_shop_id == barber_shop_id,
                Barber.is_active.is_(True),
            )
        ).all()
    )
    for barber in barbers:
        schedules = list(
            session.scalars(
                select(WorkingSchedule).where(WorkingSchedule.barber_id == barber.id)
            ).all()
        )
        for schedule in schedules:
            schedule.is_active = False
        for day_of_week in selected_days:
            matching_schedule = next(
                (
                    schedule
                    for schedule in schedules
                    if schedule.day_of_week == day_of_week
                    and schedule.start_time == opening_time
                    and schedule.end_time == closing_time
                ),
                None,
            )
            if matching_schedule is None:
                session.add(
                    WorkingSchedule(
                        barber_id=barber.id,
                        day_of_week=day_of_week,
                        start_time=opening_time,
                        end_time=closing_time,
                    )
                )
            else:
                matching_schedule.is_active = True
    session.commit()
    return _redirect_to("/admin?module=configuracion")


@router.post("/admin/services")
def admin_create_service(
    request: Request,
    barber_shop_id: int = Form(...),
    name: str = Form(...),
    duration_minutes: int = Form(...),
    price: Decimal = Form(...),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    redirect = _redirect_if_shop_not_allowed(request, session, barber_shop_id)
    if redirect is not None:
        return redirect
    if not name.strip():
        return _admin_error_response(request, session, "El servicio necesita un nombre.", selected_module="servicios")
    if duration_minutes < 1 or duration_minutes > 480:
        return _admin_error_response(request, session, "La duracion debe estar entre 1 y 480 minutos.", selected_module="servicios")
    if price < 0:
        return _admin_error_response(request, session, "El precio no puede ser negativo.", selected_module="servicios")

    _save(
        session,
        Service(
            barber_shop_id=barber_shop_id,
            name=name,
            duration_minutes=duration_minutes,
            price=price,
        ),
    )
    return _redirect_to("/admin")


@router.post("/admin/services/{service_id}/edit")
def admin_edit_service(
    request: Request,
    service_id: int,
    name: str = Form(...),
    duration_minutes: int = Form(...),
    price: Decimal = Form(...),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    service = session.get(Service, service_id)
    if service is None:
        return _redirect_to("/admin")
    redirect = _redirect_if_shop_not_allowed(request, session, service.barber_shop_id)
    if redirect is not None:
        return redirect
    if not name.strip():
        return _admin_error_response(request, session, "El servicio necesita un nombre.", selected_module="servicios")
    if duration_minutes < 1 or duration_minutes > 480:
        return _admin_error_response(request, session, "La duracion debe estar entre 1 y 480 minutos.", selected_module="servicios")
    if price < 0:
        return _admin_error_response(request, session, "El precio no puede ser negativo.", selected_module="servicios")

    service.name = name
    service.duration_minutes = duration_minutes
    service.price = price
    session.commit()
    return _redirect_to("/admin")


@router.post("/admin/barbers")
def admin_create_barber(
    request: Request,
    barber_shop_id: int = Form(...),
    name: str = Form(...),
    phone: str | None = Form(default=None),
    email: str | None = Form(default=None),
    service_ids: list[int] = Form(default=[]),
    working_days: list[int] = Form(default=[]),
    opening_time: time = Form(default=DEFAULT_OPENING_TIME),
    closing_time: time = Form(default=DEFAULT_CLOSING_TIME),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    redirect = _redirect_if_shop_not_allowed(request, session, barber_shop_id)
    if redirect is not None:
        return redirect
    if not name.strip():
        return _admin_error_response(request, session, "El profesional necesita un nombre.", selected_module="equipo")
    selected_days = sorted(set(working_days)) if working_days else list(ALL_WEEKDAYS)
    if any(day not in ALL_WEEKDAYS for day in selected_days) or opening_time >= closing_time:
        return _admin_error_response(
            request,
            session,
            "Revisa los dias y el horario del profesional.",
            selected_module="equipo",
        )

    barber = Barber(
        barber_shop_id=barber_shop_id,
        name=name,
        phone=phone or None,
        email=email or None,
    )
    barber.working_schedules = [
        WorkingSchedule(
            day_of_week=day_of_week,
            start_time=opening_time,
            end_time=closing_time,
        )
        for day_of_week in selected_days
    ]
    if service_ids:
        services = list(session.scalars(select(Service).where(Service.id.in_(set(service_ids)))).all())
        if len(services) != len(set(service_ids)) or any(
            service.barber_shop_id != barber_shop_id for service in services
        ):
            return _admin_error_response(
                request,
                session,
                "Una de las especialidades seleccionadas no pertenece al negocio.",
                selected_module="equipo",
            )
        barber.services = services
    _save(session, barber)
    return _redirect_to("/admin?module=equipo")


@router.post("/admin/barbers/{barber_id}/edit")
def admin_edit_barber(
    request: Request,
    barber_id: int,
    name: str = Form(...),
    phone: str | None = Form(default=None),
    email: str | None = Form(default=None),
    service_ids: list[int] = Form(default=[]),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    barber = session.get(Barber, barber_id)
    if barber is None:
        return _redirect_to("/admin")
    redirect = _redirect_if_shop_not_allowed(request, session, barber.barber_shop_id)
    if redirect is not None:
        return redirect
    if not name.strip():
        return _admin_error_response(request, session, "El profesional necesita un nombre.", selected_module="equipo")

    barber.name = name
    barber.phone = phone or None
    barber.email = email or None
    services = list(session.scalars(select(Service).where(Service.id.in_(set(service_ids)))).all()) if service_ids else []
    if len(services) != len(set(service_ids)) or any(
        service.barber_shop_id != barber.barber_shop_id for service in services
    ):
        return _admin_error_response(
            request,
            session,
            "Una de las especialidades seleccionadas no pertenece al negocio.",
            selected_module="equipo",
        )
    barber.services = services
    session.commit()
    return _redirect_to("/admin")


@router.post("/admin/customers")
def admin_create_customer(
    request: Request,
    barber_shop_id: int = Form(...),
    full_name: str = Form(...),
    phone: str | None = Form(default=None),
    email: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    redirect = _redirect_if_shop_not_allowed(request, session, barber_shop_id)
    if redirect is not None:
        return redirect
    if not full_name.strip():
        return _admin_error_response(request, session, "El cliente necesita un nombre.", selected_module="clientes")

    normalized_phone = phone.strip() if phone and phone.strip() else None
    existing_customer = None
    if normalized_phone:
        existing_customer = session.scalars(
            select(Customer).where(
                Customer.barber_shop_id == barber_shop_id,
                Customer.phone == normalized_phone,
            )
        ).first()
    if existing_customer is None:
        _save(
            session,
            Customer(
                barber_shop_id=barber_shop_id,
                full_name=full_name.strip(),
                phone=normalized_phone,
                email=email or None,
                notes=notes or None,
            ),
        )
    return _redirect_to("/admin?module=clientes")


@router.get("/admin/customers/{customer_id}")
def admin_customer_detail(
    request: Request,
    customer_id: int,
    session: Session = Depends(get_db),
):
    customer = session.get(Customer, customer_id)
    if customer is None or not _shop_allowed(request, session, customer.barber_shop_id):
        return _redirect_to("/admin?module=clientes")

    customer_appointments = list(
        session.scalars(
            select(Appointment)
            .where(Appointment.customer_id == customer.id)
            .order_by(Appointment.starts_at.desc())
        ).all()
    )
    return _panel_template_response(
        request,
        "admin/index.html",
        _dashboard_context(
            request,
            session,
            shop_id=_current_shop_id(request, session),
            selected_module="clientes",
            customer_detail=customer,
            customer_appointments=customer_appointments,
        ),
    )


@router.post("/admin/customers/{customer_id}/edit")
def admin_edit_customer(
    request: Request,
    customer_id: int,
    full_name: str = Form(...),
    phone: str | None = Form(default=None),
    email: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    customer = session.get(Customer, customer_id)
    if customer is None:
        return _redirect_to("/admin")
    redirect = _redirect_if_shop_not_allowed(request, session, customer.barber_shop_id)
    if redirect is not None:
        return redirect
    if not full_name.strip():
        return _admin_error_response(request, session, "El cliente necesita un nombre.", selected_module="clientes")

    customer.full_name = full_name.strip()
    customer.phone = phone.strip() if phone and phone.strip() else None
    customer.email = email or None
    customer.notes = notes or None
    session.commit()
    return _redirect_to(f"/admin/customers/{customer.id}")


@router.post("/admin/customers/{customer_id}/delete")
def admin_delete_customer(
    request: Request,
    customer_id: int,
    session: Session = Depends(get_db),
):
    customer = session.get(Customer, customer_id)
    if customer is None:
        return _redirect_to("/admin?module=clientes")
    redirect = _redirect_if_shop_not_allowed(request, session, customer.barber_shop_id)
    if redirect is not None:
        return redirect

    appointment_ids = list(
        session.scalars(select(Appointment.id).where(Appointment.customer_id == customer.id)).all()
    )
    if appointment_ids:
        customer_appointments = list(
            session.scalars(
                select(Appointment)
                .where(Appointment.customer_id == customer.id)
                .order_by(Appointment.starts_at.desc())
            ).all()
        )
        return _panel_template_response(
            request,
            "admin/index.html",
            _dashboard_context(
                request,
                session,
                shop_id=_current_shop_id(request, session),
                selected_module="clientes",
                customer_detail=customer,
                customer_appointments=customer_appointments,
                error="No se puede eliminar este cliente porque tiene turnos asociados. El historial debe conservarse.",
            ),
            status_code=HTTPStatus.CONFLICT,
        )

    session.delete(customer)
    session.commit()
    return _redirect_to("/admin?module=clientes")


@router.post("/admin/working-schedules")
def admin_create_working_schedule(
    request: Request,
    barber_id: int = Form(...),
    day_of_week: int | None = Form(default=None),
    days_of_week: list[int] = Form(default=[]),
    replace_week: bool = Form(default=False),
    start_time: time = Form(...),
    end_time: time = Form(...),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    barber = session.get(Barber, barber_id)
    if barber is None:
        return _redirect_to("/admin")
    redirect = _redirect_if_shop_not_allowed(request, session, barber.barber_shop_id)
    if redirect is not None:
        return redirect

    selected_days = sorted(set(days_of_week or ([] if day_of_week is None else [day_of_week])))
    if not selected_days or any(day not in ALL_WEEKDAYS for day in selected_days) or start_time >= end_time:
        return _panel_template_response(
            request,
            "admin/index.html",
            _dashboard_context(
                request,
                session,
                shop_id=_current_shop_id(request, session),
                error="Selecciona al menos un dia valido y verifica que el inicio sea anterior al fin.",
                selected_module="equipo",
            ),
            status_code=HTTPStatus.BAD_REQUEST,
        )

    if replace_week:
        schedules = list(
            session.scalars(
                select(WorkingSchedule).where(WorkingSchedule.barber_id == barber_id)
            ).all()
        )
        for schedule in schedules:
            schedule.is_active = False
        for selected_day in selected_days:
            matching_schedule = next(
                (
                    schedule
                    for schedule in schedules
                    if schedule.day_of_week == selected_day
                    and schedule.start_time == start_time
                    and schedule.end_time == end_time
                ),
                None,
            )
            if matching_schedule is None:
                session.add(
                    WorkingSchedule(
                        barber_id=barber_id,
                        day_of_week=selected_day,
                        start_time=start_time,
                        end_time=end_time,
                    )
                )
            else:
                matching_schedule.is_active = True
        session.commit()
        return _redirect_to("/admin?module=equipo")

    selected_day = selected_days[0]
    duplicate_schedule = session.scalars(
        select(WorkingSchedule).where(
            WorkingSchedule.barber_id == barber_id,
            WorkingSchedule.day_of_week == selected_day,
            WorkingSchedule.start_time < end_time,
            WorkingSchedule.end_time > start_time,
        )
    ).first()
    if duplicate_schedule is not None:
        return _panel_template_response(
            request,
            "admin/index.html",
            _dashboard_context(
                request,
                session,
                shop_id=_current_shop_id(request, session),
                error="Ese horario ya esta cargado para el profesional.",
            ),
            status_code=HTTPStatus.BAD_REQUEST,
        )

    _save(
        session,
        WorkingSchedule(
            barber_id=barber_id,
            day_of_week=selected_day,
            start_time=start_time,
            end_time=end_time,
        ),
    )
    return _redirect_to("/admin")


@router.post("/admin/working-schedules/{schedule_id}/edit")
def admin_edit_working_schedule(
    request: Request,
    schedule_id: int,
    day_of_week: int = Form(...),
    start_time: time = Form(...),
    end_time: time = Form(...),
    session: Session = Depends(get_db),
):
    schedule = session.get(WorkingSchedule, schedule_id)
    if schedule is None:
        return _redirect_to("/admin")
    redirect = _redirect_if_shop_not_allowed(request, session, schedule.barber.barber_shop_id)
    if redirect is not None:
        return redirect

    if day_of_week not in ALL_WEEKDAYS or start_time >= end_time:
        return _admin_error_response(
            request,
            session,
            "El horario debe tener un dia valido y el inicio debe ser anterior al fin.",
            selected_module="configuracion",
        )

    duplicate_schedule = session.scalars(
        select(WorkingSchedule).where(
            WorkingSchedule.barber_id == schedule.barber_id,
            WorkingSchedule.day_of_week == day_of_week,
            WorkingSchedule.start_time < end_time,
            WorkingSchedule.end_time > start_time,
            WorkingSchedule.id != schedule_id,
        )
    ).first()
    if duplicate_schedule is not None:
        return _admin_error_response(
            request,
            session,
            "Ese horario ya esta cargado para el profesional.",
            selected_module="configuracion",
        )

    schedule.day_of_week = day_of_week
    schedule.start_time = start_time
    schedule.end_time = end_time
    session.commit()
    return _redirect_to("/admin")


@router.post("/admin/time-blocks")
def admin_create_time_block(
    request: Request,
    barber_id: int = Form(...),
    starts_at: datetime = Form(...),
    ends_at: datetime = Form(...),
    reason: str | None = Form(default=None),
    session: Session = Depends(get_db),
):
    barber = session.get(Barber, barber_id)
    if barber is None:
        return _redirect_to("/admin")
    redirect = _redirect_if_shop_not_allowed(request, session, barber.barber_shop_id)
    if redirect is not None:
        return redirect

    if starts_at >= ends_at:
        return _panel_template_response(
            request,
            "admin/index.html",
            _dashboard_context(
                request,
                session,
                shop_id=_current_shop_id(request, session),
                error="El inicio del bloqueo debe ser anterior al fin.",
            ),
            status_code=HTTPStatus.BAD_REQUEST,
        )

    _save(
        session,
        BarberTimeBlock(
            barber_id=barber_id,
            starts_at=starts_at,
            ends_at=ends_at,
            reason=reason or None,
        ),
    )
    return _redirect_to("/admin")


@router.post("/admin/time-blocks/{time_block_id}/deactivate")
def admin_deactivate_time_block(
    request: Request,
    time_block_id: int,
    session: Session = Depends(get_db),
) -> RedirectResponse:
    time_block = session.get(BarberTimeBlock, time_block_id)
    if time_block is not None:
        redirect = _redirect_if_shop_not_allowed(request, session, time_block.barber.barber_shop_id)
        if redirect is not None:
            return redirect
    if time_block is not None:
        time_block.is_active = False
        session.commit()
    return _redirect_to("/admin")


@router.post("/admin/appointments")
def admin_create_appointment(
    request: Request,
    barber_id: int = Form(...),
    customer_id: str = Form(default=""),
    new_customer_name: str | None = Form(default=None),
    new_customer_phone: str | None = Form(default=None),
    service_id: int = Form(...),
    starts_at: datetime = Form(...),
    duration_minutes: int | None = Form(default=None),
    notes: str | None = Form(default=None),
    session: Session = Depends(get_db),
):
    try:
        barber = session.get(Barber, barber_id)
        service = session.get(Service, service_id)
        if barber is None or service is None:
            raise SchedulingError("No se encontro el profesional o el servicio.", HTTPStatus.NOT_FOUND)
        redirect = _redirect_if_shop_not_allowed(request, session, barber.barber_shop_id)
        if redirect is not None:
            return redirect
        if service.barber_shop_id != barber.barber_shop_id:
            raise SchedulingError("El servicio no pertenece a ese negocio.")

        if customer_id.strip():
            try:
                parsed_customer_id = int(customer_id)
            except ValueError as exc:
                raise SchedulingError("Cliente invalido.") from exc
            customer = session.get(Customer, parsed_customer_id)
            if customer is None or customer.barber_shop_id != barber.barber_shop_id:
                raise SchedulingError("Cliente invalido.")
        else:
            normalized_name = (new_customer_name or "").strip()
            normalized_phone = (new_customer_phone or "").strip()
            if not normalized_name:
                raise SchedulingError("Carga un cliente existente o el nombre del cliente nuevo.")
            customer = None
            if normalized_phone:
                customer = session.scalars(
                    select(Customer).where(
                        Customer.barber_shop_id == barber.barber_shop_id,
                        Customer.phone == normalized_phone,
                    )
                ).first()
            if customer is None:
                customer = Customer(
                    barber_shop_id=barber.barber_shop_id,
                    full_name=normalized_name,
                    phone=normalized_phone or None,
                )
                session.add(customer)
                session.flush()
            parsed_customer_id = customer.id

        appointment = create_appointment(
            session,
            barber_id=barber_id,
            customer_id=parsed_customer_id,
            service_id=service_id,
            starts_at=starts_at,
            duration_minutes=duration_minutes,
            notes=notes or None,
            status=AppointmentStatus.CONFIRMED,
        )
    except SchedulingError as exc:
        session.rollback()
        return _panel_template_response(
            request,
            "admin/index.html",
            _dashboard_context(
                request,
                session,
                shop_id=_current_shop_id(request, session),
                error=exc.detail,
            ),
            status_code=exc.status_code,
        )
    except IntegrityError:
        session.rollback()
        return _admin_error_response(
            request,
            session,
            "No se pudo crear el turno porque el cliente o el horario ya fue registrado. Actualiza la agenda e intenta de nuevo.",
            status_code=HTTPStatus.CONFLICT,
            selected_module="agenda",
        )
    except Exception as exc:
        session.rollback()
        log_unhandled_error(request.method, request.url.path, exc)
        return _admin_error_response(
            request,
            session,
            "No se pudo confirmar el turno. Actualiza la agenda e intenta nuevamente.",
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            selected_module="agenda",
        )
    return _redirect_to("/admin?module=agenda")


@router.post("/admin/appointments/{appointment_id}/cancel")
def admin_cancel_appointment(
    request: Request,
    appointment_id: int,
    session: Session = Depends(get_db),
):
    redirect = _redirect_if_appointment_not_allowed(request, session, appointment_id)
    if redirect is not None:
        return redirect
    appointment = session.get(Appointment, appointment_id)
    cancel_appointment(session, appointment_id)

    notice = "Turno cancelado."
    if appointment is not None:
        notice = (
            f"Se libero el turno del {appointment.starts_at:%Y-%m-%d} a las {appointment.starts_at:%H:%M}. "
            "Mensaje simulado: hay un horario disponible para reservar."
        )

    return _panel_template_response(
        request,
        "admin/index.html",
        _dashboard_context(
            request,
            session,
            shop_id=_current_shop_id(request, session),
            notice=notice,
            selected_module="rendimiento",
        ),
    )


@router.post("/admin/appointments/{appointment_id}/confirm")
def admin_confirm_appointment(
    request: Request,
    appointment_id: int,
    session: Session = Depends(get_db),
) -> RedirectResponse:
    redirect = _redirect_if_appointment_not_allowed(request, session, appointment_id)
    if redirect is not None:
        return redirect
    update_appointment_status(session, appointment_id, AppointmentStatus.CONFIRMED)
    return _redirect_to("/admin")


@router.post("/admin/appointments/{appointment_id}/complete")
def admin_complete_appointment(
    request: Request,
    appointment_id: int,
    session: Session = Depends(get_db),
) -> RedirectResponse:
    redirect = _redirect_if_appointment_not_allowed(request, session, appointment_id)
    if redirect is not None:
        return redirect
    update_appointment_status(session, appointment_id, AppointmentStatus.COMPLETED)
    return _redirect_to("/admin")


@router.post("/admin/appointments/{appointment_id}/no-show")
def admin_no_show_appointment(
    request: Request,
    appointment_id: int,
    session: Session = Depends(get_db),
) -> RedirectResponse:
    redirect = _redirect_if_appointment_not_allowed(request, session, appointment_id)
    if redirect is not None:
        return redirect
    update_appointment_status(session, appointment_id, AppointmentStatus.NO_SHOW)
    return _redirect_to("/admin")


@router.post("/admin/appointments/{appointment_id}/paid")
def admin_mark_appointment_paid(
    request: Request,
    appointment_id: int,
    payment_method: str | None = Form(default=None),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    redirect = _redirect_if_appointment_not_allowed(request, session, appointment_id)
    if redirect is not None:
        return redirect
    mark_appointment_paid(session, appointment_id, payment_method or None)
    return _redirect_to("/admin")


@router.post("/admin/appointments/{appointment_id}/unpaid")
def admin_mark_appointment_unpaid(
    request: Request,
    appointment_id: int,
    session: Session = Depends(get_db),
) -> RedirectResponse:
    redirect = _redirect_if_appointment_not_allowed(request, session, appointment_id)
    if redirect is not None:
        return redirect
    mark_appointment_unpaid(session, appointment_id)
    return _redirect_to("/admin")


@router.post("/admin/appointments/{appointment_id}/reschedule")
def admin_reschedule_appointment(
    request: Request,
    appointment_id: int,
    starts_at: datetime = Form(...),
    session: Session = Depends(get_db),
):
    redirect = _redirect_if_appointment_not_allowed(request, session, appointment_id)
    if redirect is not None:
        return redirect
    try:
        reschedule_appointment(session, appointment_id, starts_at)
    except SchedulingError as exc:
        return _panel_template_response(
            request,
            "admin/index.html",
            _dashboard_context(
                request,
                session,
                shop_id=_current_shop_id(request, session),
                error=exc.detail,
            ),
            status_code=exc.status_code,
        )
    return _redirect_to("/admin")


@router.post("/admin/supply-sales")
def admin_create_supply_sale(
    request: Request,
    barber_shop_id: int = Form(...),
    appointment_id: str = Form(default=""),
    name: str = Form(...),
    quantity: int = Form(...),
    unit_price: Decimal = Form(...),
    session: Session = Depends(get_db),
):
    redirect = _redirect_if_shop_not_allowed(request, session, barber_shop_id)
    if redirect is not None:
        return redirect
    normalized_name = name.strip()
    if not normalized_name or len(normalized_name) > 120:
        return _admin_error_response(
            request,
            session,
            "El ingreso necesita un nombre de hasta 120 caracteres.",
            selected_module="agenda",
        )
    if quantity < 1 or quantity > 999:
        return _admin_error_response(
            request,
            session,
            "La cantidad debe estar entre 1 y 999.",
            selected_module="agenda",
        )
    if unit_price < 0 or unit_price > Decimal("99999999.99"):
        return _admin_error_response(
            request,
            session,
            "El importe debe estar entre 0 y 99.999.999,99.",
            selected_module="agenda",
        )
    try:
        parsed_appointment_id = int(appointment_id) if appointment_id.strip() else None
    except ValueError:
        return _admin_error_response(request, session, "Turno invalido.", selected_module="agenda")
    if parsed_appointment_id is not None:
        appointment = session.get(Appointment, parsed_appointment_id)
        if appointment is None or appointment.barber_shop_id != barber_shop_id:
            return _redirect_to("/admin")
    try:
        create_supply_sale(
            session,
            barber_shop_id=barber_shop_id,
            appointment_id=parsed_appointment_id,
            name=normalized_name,
            quantity=quantity,
            unit_price=unit_price,
        )
    except SchedulingError as exc:
        return _panel_template_response(
            request,
            "admin/index.html",
            _dashboard_context(
                request,
                session,
                shop_id=_current_shop_id(request, session),
                error=exc.detail,
            ),
            status_code=exc.status_code,
        )
    return _redirect_to("/admin")


@router.post("/admin/bot-settings/{barber_shop_id}")
def admin_update_bot_settings(
    request: Request,
    barber_shop_id: int,
    bot_enabled: str = Form(...),
    reminders_enabled: str = Form(...),
    reminder_hours_before: int = Form(...),
    greeting_message: str = Form(...),
    reminder_template: str = Form(...),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    redirect = _redirect_if_shop_not_allowed(request, session, barber_shop_id)
    if redirect is not None:
        return redirect
    if reminder_hours_before < 1 or reminder_hours_before > 168:
        return _admin_error_response(
            request,
            session,
            "El recordatorio debe configurarse entre 1 y 168 horas.",
            selected_module="configuracion",
        )
    update_bot_settings(
        session,
        barber_shop_id=barber_shop_id,
        bot_enabled=bot_enabled == "true",
        reminders_enabled=reminders_enabled == "true",
        reminder_hours_before=reminder_hours_before,
        greeting_message=greeting_message,
        reminder_template=reminder_template,
    )
    return _redirect_to("/admin")


@router.post("/admin/reminders/{appointment_id}/simulate")
def admin_simulate_reminder(
    request: Request,
    appointment_id: int,
    session: Session = Depends(get_db),
):
    redirect = _redirect_if_appointment_not_allowed(request, session, appointment_id)
    if redirect is not None:
        return redirect
    reminder = next(
        (item for item in list_pending_reminders(session) if item.appointment_id == appointment_id),
        None,
    )
    if reminder is None:
        return _panel_template_response(
            request,
            "admin/index.html",
            _dashboard_context(
                request,
                session,
                shop_id=_current_shop_id(request, session),
                error="No hay recordatorio pendiente para ese turno.",
            ),
            status_code=HTTPStatus.BAD_REQUEST,
        )

    return _panel_template_response(
        request,
        "admin/index.html",
        _dashboard_context(
            request,
            session,
            notice=f"Recordatorio simulado para {reminder.customer_phone}: {reminder.message}",
        ),
    )


@router.get("/bot-simulator")
def bot_simulator(request: Request, session: Session = Depends(get_db)):
    bot_shop_id = _bot_simulator_shop_id(request, session)
    bot_context = _bot_context_for(bot_shop_id, BOT_SIMULATOR_FROM_PHONE) if bot_shop_id is not None else None
    return _panel_template_response(
        request,
        "bot/simulator.html",
        _dashboard_context(request, session, messages=[], **_bot_context_extra(session, bot_shop_id, bot_context)),
    )


@router.get("/customer")
def customer_portal(request: Request, session: Session = Depends(get_db)):
    shop_id = _current_shop_id(request, session)
    return templates.TemplateResponse(
        request,
        "customer/appointments.html",
        _customer_appointments_context(request, session, shop_id=shop_id),
    )


@router.get("/customer/{customer_id}/appointments")
def customer_appointments(customer_id: int, request: Request, session: Session = Depends(get_db)):
    customer = session.get(Customer, customer_id)
    status_code = HTTPStatus.OK
    extra = {}
    if customer is None:
        status_code = HTTPStatus.NOT_FOUND
        extra["error"] = "Cliente no encontrado."
    elif not _shop_allowed(request, session, customer.barber_shop_id):
        status_code = HTTPStatus.NOT_FOUND
        customer_id = None
        extra["error"] = "Cliente no encontrado."

    return templates.TemplateResponse(
        request,
        "customer/appointments.html",
        _customer_appointments_context(request, session, customer_id, shop_id=_current_shop_id(request, session), **extra),
        status_code=status_code,
    )


@router.post("/bot-simulator/reset")
def bot_simulator_reset(
    request: Request,
    from_phone: str = Form(default=BOT_SIMULATOR_FROM_PHONE),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    bot_shop_id = _bot_simulator_shop_id(request, session)
    if bot_shop_id is not None:
        BOT_SIMULATOR_CONTEXTS.pop((bot_shop_id, from_phone.strip()), None)
    return _redirect_to("/bot-simulator")


@router.post("/bot-simulator/availability")
def bot_simulator_availability(
    request: Request,
    barber_id: int = Form(...),
    service_id: int = Form(...),
    target_date: date = Form(...),
    session: Session = Depends(get_db),
):
    bot_shop_id = _bot_simulator_shop_id(request, session)
    bot_context = _bot_context_for(bot_shop_id, BOT_SIMULATOR_FROM_PHONE) if bot_shop_id is not None else None
    try:
        resource_error = _bot_simulator_resource_error(request, session, barber_id, service_id)
        if resource_error is not None:
            raise SchedulingError(resource_error)
        slots = get_available_slots(
            session,
            barber_id=barber_id,
            service_id=service_id,
            target_date=target_date,
        )
        messages = [
            ("client", f"Quiero un turno el {target_date.isoformat()}"),
            ("bot", "Tengo estos horarios disponibles."),
        ]
        if bot_context is not None:
            bot_context.service_id = service_id
            bot_context.last_target_date = target_date
    except SchedulingError as exc:
        slots = []
        messages = [("client", f"Quiero un turno el {target_date.isoformat()}"), ("bot", exc.detail)]

    return _panel_template_response(
        request,
        "bot/simulator.html",
        _dashboard_context(
            request,
            session,
            messages=messages,
            slots=slots,
            selected_barber_id=barber_id,
            selected_service_id=service_id,
            selected_date=target_date,
            **_bot_context_extra(session, bot_shop_id, bot_context),
        ),
    )


@router.post("/bot-simulator/book")
def bot_simulator_book(
    request: Request,
    barber_id: int = Form(...),
    customer_id: int = Form(...),
    service_id: int = Form(...),
    starts_at: datetime = Form(...),
    session: Session = Depends(get_db),
):
    bot_shop_id = _bot_simulator_shop_id(request, session)
    bot_context = _bot_context_for(bot_shop_id, BOT_SIMULATOR_FROM_PHONE) if bot_shop_id is not None else None
    messages = [("client", f"Reservar {starts_at:%Y-%m-%d %H:%M}")]
    try:
        resource_error = _bot_simulator_resource_error(request, session, barber_id, service_id)
        if resource_error is not None:
            raise SchedulingError(resource_error)
        appointment = create_appointment(
            session,
            barber_id=barber_id,
            customer_id=customer_id,
            service_id=service_id,
            starts_at=starts_at,
        )
        update_appointment_status(session, appointment.id, AppointmentStatus.CONFIRMED)
        if bot_context is not None:
            bot_context.last_target_date = appointment.starts_at.date()
        messages.append(("bot", f"Listo, turno #{appointment.id} confirmado y reflejado en Gestion."))
    except SchedulingError as exc:
        messages.append(("bot", exc.detail))

    return _panel_template_response(
        request,
        "bot/simulator.html",
        _dashboard_context(request, session, messages=messages, **_bot_context_extra(session, bot_shop_id, bot_context)),
    )


@router.post("/bot-simulator/message")
def bot_simulator_message(
    request: Request,
    message: str = Form(...),
    from_phone: str = Form(default=BOT_SIMULATOR_FROM_PHONE),
    session: Session = Depends(get_db),
):
    bot_shop_id = _bot_simulator_shop_id(request, session)
    bot_context = _bot_context_for(bot_shop_id, from_phone) if bot_shop_id is not None else None
    if bot_shop_id is None:
        messages = [("client", message), ("bot", "Crea un negocio activo antes de usar el simulador.")]
    else:
        messages = [
            ("client", message),
            *process_bot_message(
                session,
                message,
                bot_shop_id,
                from_phone,
                bot_context,
            ),
        ]

    return _panel_template_response(
        request,
        "bot/simulator.html",
        _dashboard_context(request, session, messages=messages, **_bot_context_extra(session, bot_shop_id, bot_context)),
    )


@router.post("/bot/webhook", response_model=BotWebhookResponse)
def bot_webhook(
    request: Request,
    payload: BotWebhookRequest,
    session: Session = Depends(get_db),
) -> dict:
    configured_secret = str(settings.bot_webhook_secret or "")
    if not configured_secret:
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail="El webhook no esta configurado.")
    provided_secret = request.headers.get("X-TurnoFlow-Webhook-Secret") or ""
    if not hmac.compare_digest(provided_secret.encode("utf-8"), configured_secret.encode("utf-8")):
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="La clave del webhook no es valida.")
    business_number = payload.to_business_number.strip()
    if is_rate_limited(
        f"bot-webhook:{_client_host(request)}",
        settings.bot_webhook_rate_limit_per_minute,
    ):
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail="Demasiados mensajes enviados al bot.")

    shop = session.scalars(
        select(BarberShop).where(
            BarberShop.phone == business_number,
            BarberShop.access_status == "active",
        )
    ).first()
    if shop is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="El numero del negocio no esta configurado.")

    context = _bot_context_for(shop.id, payload.from_phone)
    messages = process_bot_message(
        session,
        payload.message,
        shop.id,
        payload.from_phone,
        context,
    )
    return {
        "barber_shop_id": shop.id,
        "messages": [{"sender": sender, "text": text} for sender, text in messages],
    }
