from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    BarberShop,
    Customer,
    Service,
    WorkingSchedule,
)
from app.services.appointments import barber_shop_has_access


def test_initial_model_tables_are_registered() -> None:
    expected_tables = {
        "appointments",
        "barber_services",
        "barber_shops",
        "barbers",
        "customers",
        "services",
        "supply_sales",
        "working_schedules",
    }

    assert expected_tables.issubset(Base.metadata.tables.keys())


def test_can_create_related_shop_data() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    starts_at = datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc)
    service = Service(name="Haircut", duration_minutes=30, price=Decimal("5000.00"))
    barber = Barber(
        name="Martin",
        phone="1111111111",
        services=[service],
        working_schedules=[
            WorkingSchedule(
                day_of_week=5,
                start_time=time(9, 0),
                end_time=time(18, 0),
            )
        ],
    )
    shop = BarberShop(
        name="TurnoFlow Demo",
        phone="2222222222",
        address="Main Street 123",
        barbers=[barber],
        services=[service],
        customers=[Customer(full_name="Santi Cliente", phone="3333333333")],
    )
    appointment = Appointment(
        barber_shop=shop,
        barber=barber,
        customer=shop.customers[0],
        service=service,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=service.duration_minutes),
    )

    with Session(engine) as session:
        session.add_all([shop, appointment])
        session.commit()

        assert shop.id is not None
        assert barber.id is not None
        assert service.id is not None
        assert appointment.id is not None
        assert appointment.status == AppointmentStatus.PENDING.value
        assert barber.services == [service]


def test_barber_shop_defaults_to_basic_plan() -> None:
    shop = BarberShop(name="Plan Demo")

    assert shop.plan is None

    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        session.add(shop)
        session.commit()
        session.refresh(shop)

        assert shop.plan == "basic"
        assert shop.trial_ends_at is not None
        remaining = shop.trial_ends_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
        assert timedelta(days=14) < remaining <= timedelta(days=15)


def test_barber_shop_trial_controls_access_without_changing_payment_status() -> None:
    now = datetime.now(timezone.utc)
    shop = BarberShop(name="Trial Demo", access_status="active", trial_ends_at=now + timedelta(days=1))

    assert barber_shop_has_access(shop, now=now)

    shop.trial_ends_at = now - timedelta(seconds=1)
    assert not barber_shop_has_access(shop, now=now)

    shop.trial_ends_at = None
    assert barber_shop_has_access(shop, now=now)

    shop.access_status = "suspended"
    assert not barber_shop_has_access(shop, now=now)
