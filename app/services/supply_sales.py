from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Appointment, SupplySale
from app.services.appointments import SchedulingError, ensure_barber_shop_can_operate


def create_supply_sale(
    session: Session,
    *,
    barber_shop_id: int,
    appointment_id: int | None,
    name: str,
    quantity: int,
    unit_price: Decimal,
) -> SupplySale:
    ensure_barber_shop_can_operate(session, barber_shop_id)

    if appointment_id is not None:
        appointment = session.get(Appointment, appointment_id)
        if appointment is None:
            raise SchedulingError("Appointment not found", HTTPStatus.NOT_FOUND)
        if appointment.barber_shop_id != barber_shop_id:
            raise SchedulingError("Appointment must belong to barber shop")

    sale = SupplySale(
        barber_shop_id=barber_shop_id,
        appointment_id=appointment_id,
        name=name,
        quantity=quantity,
        unit_price=unit_price,
    )
    session.add(sale)
    session.commit()
    session.refresh(sale)
    return sale


def list_supply_sales(session: Session, barber_shop_id: int | None = None) -> list[SupplySale]:
    query = select(SupplySale).order_by(SupplySale.id)
    if barber_shop_id is not None:
        query = query.where(SupplySale.barber_shop_id == barber_shop_id)
    return list(session.scalars(query).all())
