import os
import threading
import uuid
from datetime import datetime, time

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.config import normalize_database_url
from app.db.base import Base
from app.models import Appointment, Barber, BarberShop, Customer, Service, WorkingSchedule


POSTGRES_TEST_URL = (
    normalize_database_url(os.environ["TEST_POSTGRES_DATABASE_URL"])
    if os.environ.get("TEST_POSTGRES_DATABASE_URL")
    else None
)

pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason=(
        "Set TEST_POSTGRES_DATABASE_URL to a disposable Postgres database URL to run manually, "
        "for example: TEST_POSTGRES_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/turnoflow_test"
    ),
)


def test_postgres_exclusion_constraint_rejects_concurrent_overlapping_appointments() -> None:
    schema_name = f"turnoflow_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(POSTGRES_TEST_URL, connect_args={"prepare_threshold": None})

    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))

    engine = create_engine(POSTGRES_TEST_URL, connect_args={"prepare_threshold": None})

    @event.listens_for(engine, "connect")
    def set_search_path(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute(f'SET search_path TO "{schema_name}"')
        cursor.close()

    try:
        Base.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
            connection.execute(
                text(
                    """
                    ALTER TABLE appointments
                    ADD CONSTRAINT ex_appointments_no_active_overlap
                    EXCLUDE USING gist (
                        barber_id WITH =,
                        tstzrange(starts_at, ends_at, '[)') WITH &&
                    )
                    WHERE (status IN ('pending', 'confirmed'))
                    """
                )
            )

        session_local = sessionmaker(bind=engine, expire_on_commit=False)
        with session_local() as session:
            shop = BarberShop(name="Race Test")
            service = Service(barber_shop=shop, name="Haircut", duration_minutes=30, price="10000.00")
            barber = Barber(barber_shop=shop, name="Martin")
            barber.services.append(service)
            first_customer = Customer(barber_shop=shop, full_name="Cliente Uno", phone="111")
            second_customer = Customer(barber_shop=shop, full_name="Cliente Dos", phone="222")
            schedule = WorkingSchedule(
                barber=barber,
                day_of_week=5,
                start_time=time(9, 0),
                end_time=time(18, 0),
            )
            session.add_all([shop, service, barber, first_customer, second_customer, schedule])
            session.commit()
            barber_id = barber.id
            shop_id = shop.id
            service_id = service.id
            customer_ids = [first_customer.id, second_customer.id]

        barrier = threading.Barrier(2)
        results: list[str] = []
        starts_at = datetime(2026, 8, 1, 10, 0)
        ends_at = datetime(2026, 8, 1, 10, 30)

        def insert_appointment(customer_id: int) -> None:
            db = session_local()
            try:
                barrier.wait(timeout=5)
                db.add(
                    Appointment(
                        barber_shop_id=shop_id,
                        barber_id=barber_id,
                        customer_id=customer_id,
                        service_id=service_id,
                        starts_at=starts_at,
                        ends_at=ends_at,
                    )
                )
                db.commit()
                results.append("created")
            except IntegrityError:
                db.rollback()
                results.append("blocked")
            finally:
                db.close()

        threads = [threading.Thread(target=insert_appointment, args=(customer_id,)) for customer_id in customer_ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        with session_local() as session:
            appointment_count = session.scalar(select(func.count()).select_from(Appointment))

        assert sorted(results) == ["blocked", "created"]
        assert appointment_count == 1
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        admin_engine.dispose()
