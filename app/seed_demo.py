from datetime import time
from decimal import Decimal

from sqlalchemy import select

from app.db.init_db import create_db_tables
from app.db.session import SessionLocal
from app.models import Barber, BarberShop, Customer, Service, SupplySale, WorkingSchedule

DEMO_SERVICES = (
    ("Corte", Decimal("10000.00")),
    ("Claritos", Decimal("30000.00")),
    ("Corte + claritos", Decimal("35000.00")),
)
DEMO_SERVICE_DURATION_MINUTES = 30


def _ensure_demo_supply_sale(session, shop: BarberShop) -> None:
    existing_sale = session.scalars(
        select(SupplySale).where(SupplySale.barber_shop_id == shop.id)
    ).first()
    if existing_sale is not None:
        return

    session.add(
        SupplySale(
            barber_shop_id=shop.id,
            name="Pomada",
            quantity=1,
            unit_price=Decimal("2500.00"),
        )
    )
    session.commit()


def _ensure_demo_services(session, shop: BarberShop) -> list[Service]:
    services: list[Service] = []
    existing_services_by_name = {service.name.lower(): service for service in shop.services}

    old_haircut = existing_services_by_name.get("haircut")
    if old_haircut is not None:
        old_haircut.name = "Corte"
        old_haircut.duration_minutes = DEMO_SERVICE_DURATION_MINUTES
        old_haircut.price = Decimal("10000.00")
        existing_services_by_name["corte"] = old_haircut

    for service_name, price in DEMO_SERVICES:
        service = existing_services_by_name.get(service_name.lower())
        if service is None:
            service = Service(
                barber_shop_id=shop.id,
                name=service_name,
                duration_minutes=DEMO_SERVICE_DURATION_MINUTES,
                price=price,
            )
            session.add(service)
            shop.services.append(service)
        else:
            service.duration_minutes = DEMO_SERVICE_DURATION_MINUTES
            service.price = price
            service.is_active = True
        services.append(service)

    session.commit()
    return services


def _ensure_demo_barber_can_do_services(session, shop: BarberShop, services: list[Service]) -> None:
    barber = next((item for item in shop.barbers if item.name == "Martin"), None)
    if barber is None:
        barber = Barber(
            barber_shop_id=shop.id,
            name="Martin",
            phone="1111111111",
            working_schedules=[
                WorkingSchedule(day_of_week=0, start_time=time(9, 0), end_time=time(18, 0)),
                WorkingSchedule(day_of_week=1, start_time=time(9, 0), end_time=time(18, 0)),
                WorkingSchedule(day_of_week=2, start_time=time(9, 0), end_time=time(18, 0)),
                WorkingSchedule(day_of_week=3, start_time=time(9, 0), end_time=time(18, 0)),
                WorkingSchedule(day_of_week=4, start_time=time(9, 0), end_time=time(18, 0)),
                WorkingSchedule(day_of_week=5, start_time=time(9, 0), end_time=time(14, 0)),
            ],
        )
        shop.barbers.append(barber)

    for service in services:
        if service not in barber.services:
            barber.services.append(service)

    session.commit()


def seed_demo_data() -> None:
    create_db_tables()

    with SessionLocal() as session:
        existing_shop = session.scalars(
            select(BarberShop).where(BarberShop.name == "TurnoFlow Demo")
        ).first()
        if existing_shop is not None:
            services = _ensure_demo_services(session, existing_shop)
            _ensure_demo_barber_can_do_services(session, existing_shop, services)
            _ensure_demo_supply_sale(session, existing_shop)
            print("Demo data already exists and was updated.")
            return

        services = [
            Service(
                name=service_name,
                duration_minutes=DEMO_SERVICE_DURATION_MINUTES,
                price=price,
            )
            for service_name, price in DEMO_SERVICES
        ]
        barber = Barber(
            name="Martin",
            phone="1111111111",
            services=services,
            working_schedules=[
                WorkingSchedule(day_of_week=0, start_time=time(9, 0), end_time=time(18, 0)),
                WorkingSchedule(day_of_week=1, start_time=time(9, 0), end_time=time(18, 0)),
                WorkingSchedule(day_of_week=2, start_time=time(9, 0), end_time=time(18, 0)),
                WorkingSchedule(day_of_week=3, start_time=time(9, 0), end_time=time(18, 0)),
                WorkingSchedule(day_of_week=4, start_time=time(9, 0), end_time=time(18, 0)),
                WorkingSchedule(day_of_week=5, start_time=time(9, 0), end_time=time(14, 0)),
            ],
        )
        shop = BarberShop(
            name="TurnoFlow Demo",
            phone="2222222222",
            address="Main Street 123",
            services=services,
            barbers=[barber],
            customers=[
                Customer(full_name="Santi Cliente", phone="3333333333"),
                Customer(full_name="Cliente Prueba", phone="4444444444"),
            ],
        )

        session.add(shop)
        session.commit()
        _ensure_demo_supply_sale(session, shop)
        print("Demo data created.")


if __name__ == "__main__":
    seed_demo_data()
