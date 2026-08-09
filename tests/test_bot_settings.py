from datetime import UTC, datetime, time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import BarberShop, BotSettings
from app.services.bot_settings import _as_naive_datetime, get_or_create_bot_settings_map


def test_reminders_normalize_postgres_timezone_datetimes() -> None:
    postgres_value = datetime(2026, 8, 3, 20, 30, tzinfo=UTC)

    assert _as_naive_datetime(postgres_value) == datetime(2026, 8, 3, 20, 30)


def test_bot_settings_for_multiple_shops_are_loaded_in_one_query(db_session: Session) -> None:
    shops = [BarberShop(name=f"Negocio {index}") for index in range(3)]
    db_session.add_all(shops)
    db_session.flush()
    shop_ids = [shop.id for shop in shops]
    db_session.add_all(BotSettings(barber_shop_id=shop.id) for shop in shops)
    db_session.commit()

    select_count = 0

    def count_selects(orm_execute_state) -> None:
        nonlocal select_count
        if orm_execute_state.is_select:
            select_count += 1

    event.listen(db_session, "do_orm_execute", count_selects)
    try:
        settings_by_shop = get_or_create_bot_settings_map(
            db_session,
            shop_ids,
        )
    finally:
        event.remove(db_session, "do_orm_execute", count_selects)

    assert set(settings_by_shop) == set(shop_ids)
    assert select_count == 1


def test_bot_settings_can_disable_bot(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Bot Settings Demo"})
    shop_id = shop_response.json()["id"]

    update_response = client.put(
        f"/api/barber-shops/{shop_id}/bot-settings",
        json={
            "bot_enabled": False,
            "reminders_enabled": True,
            "reminder_hours_before": 24,
            "greeting_message": "Hola",
            "reminder_template": "Recordatorio para {customer_name}",
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["bot_enabled"] is False

    bot_response = client.post("/bot-simulator/message", data={"message": "servicios"})
    assert bot_response.status_code == 200
    assert "El bot esta desactivado" in bot_response.text


def test_bot_uses_configured_menu_message(client: TestClient) -> None:
    shop = client.post("/api/barber-shops", json={"name": "Menu propio"}).json()
    response = client.put(
        f"/api/barber-shops/{shop['id']}/bot-settings",
        json={
            "bot_enabled": True,
            "reminders_enabled": False,
            "reminder_hours_before": 24,
            "greeting_message": "Hola desde el estudio.",
            "menu_message": "1. Reservar | 2. Consultar | 3. Cambiar turno",
            "reminder_template": "Turno de {customer_name}",
        },
    )

    assert response.status_code == 200
    bot_response = client.post("/bot-simulator/message", data={"message": "hola"})
    assert "Hola desde el estudio." in bot_response.text
    assert "1. Reservar | 2. Consultar | 3. Cambiar turno" in bot_response.text


def test_pending_reminders_are_generated_from_real_appointments(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Reminder Demo"})
    shop_id = shop_response.json()["id"]

    client.put(
        f"/api/barber-shops/{shop_id}/bot-settings",
        json={
            "bot_enabled": True,
            "reminders_enabled": True,
            "reminder_hours_before": 168,
            "greeting_message": "Hola",
            "reminder_template": "Hola {customer_name}, turno en {shop_name} el {starts_at}",
        },
    )

    service_response = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Haircut",
            "duration_minutes": 30,
            "price": "5000.00",
        },
    )
    service_id = service_response.json()["id"]

    barber_response = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Martin", "service_ids": [service_id]},
    )
    barber_id = barber_response.json()["id"]

    starts_at = (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)).replace(
        minute=0,
        second=0,
        microsecond=0,
    )
    client.post(
        "/api/working-schedules",
        json={
            "barber_id": barber_id,
            "day_of_week": starts_at.weekday(),
            "start_time": time(0, 0).isoformat(),
            "end_time": time(23, 59).isoformat(),
        },
    )

    customer_response = client.post(
        "/api/customers",
        json={"barber_shop_id": shop_id, "full_name": "Santi Cliente", "phone": "333"},
    )
    customer_id = customer_response.json()["id"]

    appointment_response = client.post(
        "/api/appointments",
        json={
            "barber_id": barber_id,
            "customer_id": customer_id,
            "service_id": service_id,
            "starts_at": starts_at.isoformat(),
        },
    )
    assert appointment_response.status_code == 201

    reminders_response = client.get("/api/reminders/pending")
    assert reminders_response.status_code == 200
    assert reminders_response.json()[0]["customer_name"] == "Santi Cliente"
    assert "Reminder Demo" in reminders_response.json()[0]["message"]
