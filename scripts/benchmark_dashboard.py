from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from time import perf_counter

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Appointment, AppointmentStatus, Barber, BarberShop, Customer, Service


def seed_volume(session: Session) -> None:
    shop = BarberShop(name="Benchmark")
    service = Service(
        barber_shop=shop,
        name="Servicio benchmark",
        duration_minutes=30,
        price=Decimal("15000.00"),
    )
    barber = Barber(barber_shop=shop, name="Profesional benchmark", services=[service])
    customers = [
        Customer(barber_shop=shop, full_name=f"Cliente {index}", phone=f"555{index:04d}")
        for index in range(50)
    ]
    session.add_all([shop, service, barber, *customers])
    session.flush()

    base_time = datetime(2026, 1, 1, 9, 0)
    appointments = []
    for index in range(500):
        starts_at = base_time + timedelta(minutes=30 * index)
        appointments.append(
            Appointment(
                barber_shop_id=shop.id,
                barber_id=barber.id,
                customer_id=customers[index % len(customers)].id,
                service_id=service.id,
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=30),
                status=(
                    AppointmentStatus.COMPLETED.value
                    if index % 3
                    else AppointmentStatus.CANCELLED.value
                ),
                is_paid=index % 3 != 0,
            )
        )
    session.add_all(appointments)
    session.commit()


def main() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with testing_session_local() as session:
        seed_volume(session)

    def override_get_db():
        with testing_session_local() as session:
            yield session

    original_auth_enabled = settings.auth_enabled
    settings.auth_enabled = False
    app.dependency_overrides[get_db] = override_get_db
    select_count = 0

    def count_selects(execute_state) -> None:
        nonlocal select_count
        if execute_state.is_select:
            select_count += 1

    try:
        with TestClient(app) as client:
            client.get("/admin")
            event.listen(Session, "do_orm_execute", count_selects)
            durations = []
            response_size = 0
            for _ in range(5):
                started = perf_counter()
                response = client.get("/admin")
                durations.append(perf_counter() - started)
                response_size = len(response.content)
                response.raise_for_status()
            event.remove(Session, "do_orm_execute", count_selects)
    finally:
        app.dependency_overrides.clear()
        settings.auth_enabled = original_auth_enabled
        engine.dispose()

    print(f"appointments=500 customers=50 median_seconds={median(durations):.4f}")
    print(f"selects_per_request={select_count / len(durations):.1f} response_bytes={response_size}")


if __name__ == "__main__":
    main()
