from datetime import date
from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AppointmentStatus, Barber, BarberShop, Customer, Service, SupplySale, WorkingSchedule
from app.schemas.business import (
    AppointmentCreate,
    AppointmentPaymentUpdate,
    AppointmentRead,
    AppointmentReschedule,
    AvailabilitySlot,
    BarberCreate,
    BarberRead,
    BarberShopCreate,
    BarberShopRead,
    BarberShopSuspend,
    BotSettingsUpdate,
    CustomerCreate,
    CustomerRead,
    ServiceCreate,
    ServiceRead,
    SupplySaleCreate,
    SupplySaleRead,
    WorkingScheduleCreate,
    WorkingScheduleRead,
)
from app.services.appointments import (
    SchedulingError,
    activate_barber_shop,
    cancel_appointment,
    create_appointment,
    get_available_slots,
    mark_appointment_paid,
    mark_appointment_unpaid,
    reschedule_appointment,
    suspend_barber_shop,
    update_appointment_status,
)
from app.services.supply_sales import create_supply_sale, list_supply_sales
from app.services.bot_settings import get_or_create_bot_settings, list_pending_reminders, update_bot_settings

router = APIRouter(prefix="/api")


def _get_or_404(session: Session, model: type, object_id: int, label: str):
    item = session.get(model, object_id)
    if item is None:
        labels = {
            "Barber shop": "Negocio",
            "Barber": "Profesional",
            "Service": "Servicio",
            "Customer": "Cliente",
        }
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"{labels.get(label, label)} no encontrado.")
    return item


def _save(session: Session, item):
    try:
        session.add(item)
        session.commit()
        session.refresh(item)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="No se pudo guardar el registro.") from exc
    return item


def _map_scheduling_error(exc: SchedulingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/barber-shops", response_model=BarberShopRead, status_code=HTTPStatus.CREATED)
def create_barber_shop(payload: BarberShopCreate, session: Session = Depends(get_db)) -> BarberShop:
    return _save(session, BarberShop(**payload.model_dump()))


@router.get("/barber-shops", response_model=list[BarberShopRead])
def list_barber_shops(session: Session = Depends(get_db)) -> list[BarberShop]:
    return list(session.scalars(select(BarberShop).order_by(BarberShop.id)).all())


@router.post("/barber-shops/{barber_shop_id}/suspend", response_model=BarberShopRead)
def suspend_shop(
    barber_shop_id: int,
    payload: BarberShopSuspend,
    session: Session = Depends(get_db),
) -> BarberShop:
    try:
        return suspend_barber_shop(session, barber_shop_id, payload.reason)
    except SchedulingError as exc:
        raise _map_scheduling_error(exc) from exc


@router.post("/barber-shops/{barber_shop_id}/activate", response_model=BarberShopRead)
def activate_shop(barber_shop_id: int, session: Session = Depends(get_db)) -> BarberShop:
    try:
        return activate_barber_shop(session, barber_shop_id)
    except SchedulingError as exc:
        raise _map_scheduling_error(exc) from exc


@router.get("/barber-shops/{barber_shop_id}/bot-settings")
def get_shop_bot_settings(barber_shop_id: int, session: Session = Depends(get_db)):
    try:
        return get_or_create_bot_settings(session, barber_shop_id)
    except SchedulingError as exc:
        raise _map_scheduling_error(exc) from exc


@router.put("/barber-shops/{barber_shop_id}/bot-settings")
def update_shop_bot_settings(
    barber_shop_id: int,
    payload: BotSettingsUpdate,
    session: Session = Depends(get_db),
):
    try:
        return update_bot_settings(
            session,
            barber_shop_id=barber_shop_id,
            **payload.model_dump(),
        )
    except SchedulingError as exc:
        raise _map_scheduling_error(exc) from exc


@router.post("/services", response_model=ServiceRead, status_code=HTTPStatus.CREATED)
def create_service(payload: ServiceCreate, session: Session = Depends(get_db)) -> Service:
    _get_or_404(session, BarberShop, payload.barber_shop_id, "Barber shop")
    return _save(session, Service(**payload.model_dump()))


@router.get("/services", response_model=list[ServiceRead])
def list_services(
    barber_shop_id: int | None = Query(default=None),
    session: Session = Depends(get_db),
) -> list[Service]:
    query = select(Service).order_by(Service.id)
    if barber_shop_id is not None:
        query = query.where(Service.barber_shop_id == barber_shop_id)
    return list(session.scalars(query).all())


@router.post("/barbers", response_model=BarberRead, status_code=HTTPStatus.CREATED)
def create_barber(payload: BarberCreate, session: Session = Depends(get_db)) -> Barber:
    _get_or_404(session, BarberShop, payload.barber_shop_id, "Barber shop")
    data = payload.model_dump(exclude={"service_ids"})
    barber = Barber(**data)

    if payload.service_ids:
        services = session.scalars(select(Service).where(Service.id.in_(payload.service_ids))).all()
        if len(services) != len(set(payload.service_ids)):
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="La lista de servicios no es valida.")
        if any(service.barber_shop_id != payload.barber_shop_id for service in services):
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Los servicios deben pertenecer al negocio.")
        barber.services = list(services)

    return _save(session, barber)


@router.get("/barbers", response_model=list[BarberRead])
def list_barbers(
    barber_shop_id: int | None = Query(default=None),
    session: Session = Depends(get_db),
) -> list[Barber]:
    query = select(Barber).order_by(Barber.id)
    if barber_shop_id is not None:
        query = query.where(Barber.barber_shop_id == barber_shop_id)
    return list(session.scalars(query).all())


@router.post("/barbers/{barber_id}/services/{service_id}", response_model=BarberRead)
def assign_service_to_barber(
    barber_id: int,
    service_id: int,
    session: Session = Depends(get_db),
) -> Barber:
    barber = _get_or_404(session, Barber, barber_id, "Barber")
    service = _get_or_404(session, Service, service_id, "Service")
    if barber.barber_shop_id != service.barber_shop_id:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="El servicio debe pertenecer al negocio.")
    if service not in barber.services:
        barber.services.append(service)
    return _save(session, barber)


@router.post("/customers", response_model=CustomerRead, status_code=HTTPStatus.CREATED)
def create_customer(payload: CustomerCreate, session: Session = Depends(get_db)) -> Customer:
    _get_or_404(session, BarberShop, payload.barber_shop_id, "Barber shop")
    return _save(session, Customer(**payload.model_dump()))


@router.get("/customers", response_model=list[CustomerRead])
def list_customers(
    barber_shop_id: int | None = Query(default=None),
    session: Session = Depends(get_db),
) -> list[Customer]:
    query = select(Customer).order_by(Customer.id)
    if barber_shop_id is not None:
        query = query.where(Customer.barber_shop_id == barber_shop_id)
    return list(session.scalars(query).all())


@router.post("/working-schedules", response_model=WorkingScheduleRead, status_code=HTTPStatus.CREATED)
def create_working_schedule(
    payload: WorkingScheduleCreate,
    session: Session = Depends(get_db),
) -> WorkingSchedule:
    _get_or_404(session, Barber, payload.barber_id, "Barber")
    return _save(session, WorkingSchedule(**payload.model_dump()))


@router.get("/working-schedules", response_model=list[WorkingScheduleRead])
def list_working_schedules(
    barber_id: int | None = Query(default=None),
    session: Session = Depends(get_db),
) -> list[WorkingSchedule]:
    query = select(WorkingSchedule).order_by(WorkingSchedule.id)
    if barber_id is not None:
        query = query.where(WorkingSchedule.barber_id == barber_id)
    return list(session.scalars(query).all())


@router.get("/availability", response_model=list[AvailabilitySlot])
def availability(
    barber_id: int,
    service_id: int,
    target_date: date,
    session: Session = Depends(get_db),
) -> list[dict]:
    try:
        return get_available_slots(
            session,
            barber_id=barber_id,
            service_id=service_id,
            target_date=target_date,
        )
    except SchedulingError as exc:
        raise _map_scheduling_error(exc) from exc


@router.post("/appointments", response_model=AppointmentRead, status_code=HTTPStatus.CREATED)
def create_booking(payload: AppointmentCreate, session: Session = Depends(get_db)):
    try:
        return create_appointment(session, **payload.model_dump())
    except SchedulingError as exc:
        raise _map_scheduling_error(exc) from exc


@router.get("/appointments", response_model=list[AppointmentRead])
def list_appointments(
    barber_shop_id: int | None = Query(default=None),
    session: Session = Depends(get_db),
):
    from app.models import Appointment

    query = select(Appointment).order_by(Appointment.starts_at)
    if barber_shop_id is not None:
        query = query.where(Appointment.barber_shop_id == barber_shop_id)
    return list(session.scalars(query).all())


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentRead)
def cancel_booking(appointment_id: int, session: Session = Depends(get_db)):
    try:
        return cancel_appointment(session, appointment_id)
    except SchedulingError as exc:
        raise _map_scheduling_error(exc) from exc


@router.post("/appointments/{appointment_id}/confirm", response_model=AppointmentRead)
def confirm_booking(appointment_id: int, session: Session = Depends(get_db)):
    try:
        return update_appointment_status(session, appointment_id, AppointmentStatus.CONFIRMED)
    except SchedulingError as exc:
        raise _map_scheduling_error(exc) from exc


@router.post("/appointments/{appointment_id}/complete", response_model=AppointmentRead)
def complete_booking(appointment_id: int, session: Session = Depends(get_db)):
    try:
        return update_appointment_status(session, appointment_id, AppointmentStatus.COMPLETED)
    except SchedulingError as exc:
        raise _map_scheduling_error(exc) from exc


@router.post("/appointments/{appointment_id}/no-show", response_model=AppointmentRead)
def mark_booking_no_show(appointment_id: int, session: Session = Depends(get_db)):
    try:
        return update_appointment_status(session, appointment_id, AppointmentStatus.NO_SHOW)
    except SchedulingError as exc:
        raise _map_scheduling_error(exc) from exc


@router.post("/appointments/{appointment_id}/paid", response_model=AppointmentRead)
def mark_booking_paid(
    appointment_id: int,
    payload: AppointmentPaymentUpdate,
    session: Session = Depends(get_db),
):
    try:
        return mark_appointment_paid(session, appointment_id, payload.payment_method)
    except SchedulingError as exc:
        raise _map_scheduling_error(exc) from exc


@router.post("/appointments/{appointment_id}/unpaid", response_model=AppointmentRead)
def mark_booking_unpaid(appointment_id: int, session: Session = Depends(get_db)):
    try:
        return mark_appointment_unpaid(session, appointment_id)
    except SchedulingError as exc:
        raise _map_scheduling_error(exc) from exc


@router.post("/appointments/{appointment_id}/reschedule", response_model=AppointmentRead)
def reschedule_booking(
    appointment_id: int,
    payload: AppointmentReschedule,
    session: Session = Depends(get_db),
):
    try:
        return reschedule_appointment(session, appointment_id, payload.starts_at)
    except SchedulingError as exc:
        raise _map_scheduling_error(exc) from exc


@router.post("/supply-sales", response_model=SupplySaleRead, status_code=HTTPStatus.CREATED)
def create_supply_sale_record(payload: SupplySaleCreate, session: Session = Depends(get_db)) -> SupplySale:
    try:
        return create_supply_sale(session, **payload.model_dump())
    except SchedulingError as exc:
        raise _map_scheduling_error(exc) from exc


@router.get("/supply-sales", response_model=list[SupplySaleRead])
def get_supply_sales(
    barber_shop_id: int | None = Query(default=None),
    session: Session = Depends(get_db),
) -> list[SupplySale]:
    return list_supply_sales(session, barber_shop_id)


@router.get("/reminders/pending")
def get_pending_reminders(session: Session = Depends(get_db)):
    return list_pending_reminders(session)
