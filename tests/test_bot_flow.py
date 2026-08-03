from fastapi.testclient import TestClient
import httpx
from datetime import time
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Appointment, Barber, BarberShop, Customer, Service, WorkingSchedule
from app.services.bot_flow import BotConversationContext, process_bot_message


def _create_bot_demo_data(client: TestClient) -> tuple[int, int, int]:
    shop_response = client.post("/api/barber-shops", json={"name": "Bot Demo"})
    shop_id = shop_response.json()["id"]

    service_response = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Corte",
            "duration_minutes": 30,
            "price": "10000.00",
        },
    )
    service_id = service_response.json()["id"]

    barber_response = client.post(
        "/api/barbers",
        json={
            "barber_shop_id": shop_id,
            "name": "Martin",
            "service_ids": [service_id],
        },
    )
    barber_id = barber_response.json()["id"]

    client.post(
        "/api/working-schedules",
        json={
            "barber_id": barber_id,
            "day_of_week": 5,
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )

    customer_response = client.post(
        "/api/customers",
        json={
            "barber_shop_id": shop_id,
            "full_name": "Santi Cliente",
            "phone": "3333333333",
        },
    )
    customer_id = customer_response.json()["id"]

    return barber_id, customer_id, service_id


def _seed_bot_shop(session: Session, *, name: str, service_name: str, price: str) -> BarberShop:
    shop = BarberShop(name=name)
    service = Service(barber_shop=shop, name=service_name, duration_minutes=30, price=price)
    barber = Barber(barber_shop=shop, name=f"{name} Pro")
    barber.services.append(service)
    schedule = WorkingSchedule(
        barber=barber,
        day_of_week=5,
        start_time=time(9, 0),
        end_time=time(18, 0),
    )
    session.add_all([shop, service, barber, schedule])
    session.commit()
    session.refresh(shop)
    return shop


def _create_full_bot_demo_data(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Full Bot Demo"})
    shop_id = shop_response.json()["id"]
    service_ids = []

    for name, price in (
        ("Corte", "10000.00"),
        ("Claritos", "30000.00"),
        ("Corte + claritos", "35000.00"),
    ):
        service_response = client.post(
            "/api/services",
            json={
                "barber_shop_id": shop_id,
                "name": name,
                "duration_minutes": 30,
                "price": price,
            },
        )
        service_ids.append(service_response.json()["id"])

    barber_response = client.post(
        "/api/barbers",
        json={
            "barber_shop_id": shop_id,
            "name": "Martin",
            "service_ids": service_ids,
        },
    )
    barber_id = barber_response.json()["id"]

    client.post(
        "/api/working-schedules",
        json={
            "barber_id": barber_id,
            "day_of_week": 5,
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    client.post(
        "/api/customers",
        json={
            "barber_shop_id": shop_id,
            "full_name": "Santi Cliente",
            "phone": "3333333333",
        },
    )


def _create_bot_demo_data_without_customer(client: TestClient) -> tuple[int, int, int]:
    shop_response = client.post("/api/barber-shops", json={"name": "Phone Customer Demo"})
    shop_id = shop_response.json()["id"]
    service_response = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Corte",
            "duration_minutes": 30,
            "price": "10000.00",
        },
    )
    service_id = service_response.json()["id"]
    barber_response = client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Martin", "service_ids": [service_id]},
    )
    barber_id = barber_response.json()["id"]
    client.post(
        "/api/working-schedules",
        json={
            "barber_id": barber_id,
            "day_of_week": 5,
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    return shop_id, barber_id, service_id


def test_bot_message_can_list_availability_and_book(client: TestClient) -> None:
    barber_id, customer_id, service_id = _create_bot_demo_data(client)

    availability_response = client.post(
        "/bot-simulator/message",
        data={"message": f"horarios {barber_id} {service_id} 2026-08-01"},
    )
    assert availability_response.status_code == 200
    assert "09:00" in availability_response.text

    booking_response = client.post(
        "/bot-simulator/message",
        data={"message": f"reservar {barber_id} {customer_id} {service_id} 2026-08-01 09:00"},
    )
    assert booking_response.status_code == 200
    assert "confirmado y reflejado en Gestion" in booking_response.text

    appointments_response = client.get("/api/appointments")
    appointments = appointments_response.json()
    assert len(appointments) == 1
    assert appointments[0]["status"] == "confirmed"


def test_bot_creates_customer_from_sender_phone_when_booking(client: TestClient) -> None:
    shop_id, _, _ = _create_bot_demo_data_without_customer(client)

    response = client.post(
        "/bot-simulator/message",
        data={"message": "reservame corte el 2026-08-01 a las 09:00"},
    )

    assert response.status_code == 200
    assert "te confirme el turno" in response.text
    customers = client.get("/api/customers", params={"barber_shop_id": shop_id}).json()
    assert len(customers) == 1
    assert customers[0]["phone"] == "+5491100000000"
    appointment = client.get("/api/appointments").json()[0]
    assert appointment["customer_id"] == customers[0]["id"]


def test_bot_webhook_resolves_shop_from_business_number(client: TestClient) -> None:
    shop_response = client.post(
        "/api/barber-shops",
        json={"name": "Webhook Demo", "phone": "+5491199999999"},
    )
    shop_id = shop_response.json()["id"]
    service_response = client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_id,
            "name": "Corte",
            "duration_minutes": 30,
            "price": "10000.00",
        },
    )
    service_id = service_response.json()["id"]
    client.post(
        "/api/barbers",
        json={"barber_shop_id": shop_id, "name": "Martin", "service_ids": [service_id]},
    )

    response = client.post(
        "/bot/webhook",
        json={
            "from_phone": "+5491111111111",
            "to_business_number": "+5491199999999",
            "message": "cuanto sale corte",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["barber_shop_id"] == shop_id
    assert payload["messages"][0]["sender"] == "bot"
    assert "Corte cuesta $10000.00" in payload["messages"][0]["text"]


def test_bot_webhook_rejects_unknown_business_number(client: TestClient) -> None:
    response = client.post(
        "/bot/webhook",
        json={
            "from_phone": "+5491111111111",
            "to_business_number": "+5491188888888",
            "message": "hola",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Business number is not configured"


def test_bot_answers_service_price_with_common_phrases(client: TestClient) -> None:
    _create_bot_demo_data(client)

    messages = (
        "cuanto vale el corte?",
        "que vale el corte",
        "cual es el valor del corte",
        "que precio esta para cortarme",
        "cuanto sale",
        "cuanto cuesta?",
        "que valor tiene el corte",
    )

    for message in messages:
        response = client.post("/bot-simulator/message", data={"message": message})

        assert response.status_code == 200
        assert "Corte cuesta $10000.00" in response.text


def test_bot_simulator_does_not_list_services_from_another_shop(client: TestClient) -> None:
    shop_a_response = client.post("/api/barber-shops", json={"name": "Bot Shop A"})
    shop_b_response = client.post("/api/barber-shops", json={"name": "Bot Shop B"})
    shop_a_id = shop_a_response.json()["id"]
    shop_b_id = shop_b_response.json()["id"]

    client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_a_id,
            "name": "Corte A",
            "duration_minutes": 30,
            "price": "10000.00",
        },
    )
    client.post(
        "/api/services",
        json={
            "barber_shop_id": shop_b_id,
            "name": "Tatuaje B",
            "duration_minutes": 60,
            "price": "50000.00",
        },
    )

    response = client.post("/bot-simulator/message", data={"message": "servicios"})

    assert response.status_code == 200
    assert "<strong>bot:</strong> Corte A cuesta $10000.00" in response.text
    assert "$50000.00" not in response.text


def test_bot_conversation_does_not_return_or_modify_another_shop(db_session: Session) -> None:
    shop_a = _seed_bot_shop(db_session, name="Bot Shop A", service_name="Corte", price="10000.00")
    shop_b = _seed_bot_shop(db_session, name="Bot Shop B", service_name="Corte Premium", price="50000.00")
    context = BotConversationContext()

    price_messages = process_bot_message(
        db_session,
        "cuanto sale el corte",
        shop_a.id,
        "+5491111111111",
        context,
    )

    assert "10000.00" in price_messages[0][1]
    assert "50000.00" not in price_messages[0][1]

    booking_messages = process_bot_message(
        db_session,
        "reservame corte el 2026-08-01 a las 09:00",
        shop_a.id,
        "+5491111111111",
        context,
    )

    assert "te confirme el turno" in booking_messages[0][1]
    appointments = list(db_session.scalars(select(Appointment)).all())
    assert len(appointments) == 1
    assert appointments[0].barber_shop_id == shop_a.id
    assert appointments[0].barber_shop_id != shop_b.id
    shop_b_customers = list(
        db_session.scalars(select(Customer).where(Customer.barber_shop_id == shop_b.id)).all()
    )
    assert shop_b_customers == []


def test_bot_prefers_simple_cut_when_cut_and_combo_services_exist(client: TestClient) -> None:
    shop_response = client.post("/api/barber-shops", json={"name": "Combo Demo"})
    shop_id = shop_response.json()["id"]
    for name, price in (
        ("Corte", "10000.00"),
        ("Claritos", "30000.00"),
        ("Corte + claritos", "35000.00"),
    ):
        client.post(
            "/api/services",
            json={
                "barber_shop_id": shop_id,
                "name": name,
                "duration_minutes": 30,
                "price": price,
            },
        )

    response = client.post("/bot-simulator/message", data={"message": "cuanto sale el corte"})

    assert response.status_code == 200
    assert "Corte cuesta $10000.00" in response.text
    assert "Encontre varios servicios posibles" not in response.text


def test_bot_answers_when_customer_only_says_wanted_service(client: TestClient) -> None:
    _create_full_bot_demo_data(client)

    cut_response = client.post("/bot-simulator/message", data={"message": "quiero corte"})
    assert cut_response.status_code == 200
    assert "Perfecto. Corte cuesta $10000.00" in cut_response.text
    assert "Tengo lugar" in cut_response.text

    highlights_response = client.post("/bot-simulator/message", data={"message": "quiero claritos"})
    assert highlights_response.status_code == 200
    assert "Perfecto. Claritos cuesta $30000.00" in highlights_response.text

    combo_response = client.post("/bot-simulator/message", data={"message": "quiero corte y claritos"})
    assert combo_response.status_code == 200
    assert "Perfecto. Corte + claritos cuesta $35000.00" in combo_response.text


def test_bot_simulator_keeps_context_for_guided_booking(client: TestClient) -> None:
    _create_full_bot_demo_data(client)
    client.post("/bot-simulator/reset")

    first_response = client.post("/bot-simulator/message", data={"message": "quiero un turno"})
    assert first_response.status_code == 200
    assert "Decime que servicio queres" in first_response.text
    assert "Corte" in first_response.text

    service_response = client.post("/bot-simulator/message", data={"message": "Corte"})
    assert service_response.status_code == 200
    assert "Perfecto. Corte cuesta $10000.00" in service_response.text

    day_response = client.post("/bot-simulator/message", data={"message": "2026-08-01"})
    assert day_response.status_code == 200
    assert "Para Corte el" in day_response.text
    assert "10:00" in day_response.text

    time_response = client.post("/bot-simulator/message", data={"message": "10"})
    assert time_response.status_code == 200
    assert "te confirme el turno" in time_response.text

    appointments_response = client.get("/api/appointments")
    appointments = appointments_response.json()
    assert len(appointments) == 1
    assert appointments[0]["status"] == "confirmed"


def test_bot_simulator_keeps_separate_context_per_sender_phone(client: TestClient) -> None:
    _create_full_bot_demo_data(client)

    first_service_response = client.post(
        "/bot-simulator/message",
        data={"from_phone": "+5491111111111", "message": "quiero corte"},
    )
    assert first_service_response.status_code == 200
    assert "Perfecto. Corte cuesta $10000.00" in first_service_response.text

    second_service_response = client.post(
        "/bot-simulator/message",
        data={"from_phone": "+5491122222222", "message": "quiero claritos"},
    )
    assert second_service_response.status_code == 200
    assert "Perfecto. Claritos cuesta $30000.00" in second_service_response.text

    first_day_response = client.post(
        "/bot-simulator/message",
        data={"from_phone": "+5491111111111", "message": "2026-08-01"},
    )
    assert first_day_response.status_code == 200
    assert "Para Corte el" in first_day_response.text

    second_day_response = client.post(
        "/bot-simulator/message",
        data={"from_phone": "+5491122222222", "message": "2026-08-01"},
    )
    assert second_day_response.status_code == 200
    assert "Para Claritos el" in second_day_response.text


def test_bot_can_book_from_one_natural_message(client: TestClient) -> None:
    _create_bot_demo_data(client)
    client.post("/bot-simulator/reset")

    response = client.post(
        "/bot-simulator/message",
        data={"message": "hola quiero corte el 2026-08-01 a las 10"},
    )

    assert response.status_code == 200
    assert "te confirme el turno" in response.text
    appointment = client.get("/api/appointments").json()[0]
    assert appointment["status"] == "confirmed"
    assert appointment["starts_at"] == "2026-08-01T10:00:00"


def test_bot_lists_available_days_and_times_for_service(client: TestClient) -> None:
    _create_bot_demo_data(client)

    days_response = client.post("/bot-simulator/message", data={"message": "que dias puedo cortarme"})
    assert days_response.status_code == 200
    assert "Para Corte tengo estos dias libres" in days_response.text

    times_response = client.post(
        "/bot-simulator/message",
        data={"message": "que horarios tenes para corte el 2026-08-01"},
    )
    assert times_response.status_code == 200
    assert "09:00" in times_response.text


def test_bot_understands_weekday_as_availability_request(client: TestClient) -> None:
    _create_bot_demo_data(client)

    response = client.post("/bot-simulator/message", data={"message": "quiero cortarme el sábado"})

    assert response.status_code == 200
    assert "Para Corte el" in response.text
    assert "tengo libre" in response.text


def test_bot_natural_booking_is_confirmed_and_blocks_recent_double_booking(client: TestClient) -> None:
    _create_bot_demo_data(client)

    booking_response = client.post(
        "/bot-simulator/message",
        data={"message": "reservame corte el 2026-08-01 a las 09:00"},
    )
    assert booking_response.status_code == 200
    assert "te confirme el turno" in booking_response.text

    appointments_response = client.get("/api/appointments")
    appointments = appointments_response.json()
    assert appointments[0]["status"] == "confirmed"

    second_booking_response = client.post(
        "/bot-simulator/message",
        data={"message": "reservame corte el 2026-08-01 a las 10:00"},
    )
    assert second_booking_response.status_code == 200
    assert "Ya tenes un turno activo reciente" in second_booking_response.text


def test_bot_can_reschedule_and_cancel_active_appointment(client: TestClient) -> None:
    _create_bot_demo_data(client)
    client.post("/bot-simulator/reset")

    booking_response = client.post(
        "/bot-simulator/message",
        data={"message": "reservame corte el 2026-08-01 a las 09:00"},
    )
    assert booking_response.status_code == 200
    assert "te confirme el turno" in booking_response.text

    reschedule_response = client.post(
        "/bot-simulator/message",
        data={"message": "reprogramar el 2026-08-01 a las 10:00"},
    )
    assert reschedule_response.status_code == 200
    assert "reprograme el turno" in reschedule_response.text

    appointments_after_reschedule = client.get("/api/appointments").json()
    assert appointments_after_reschedule[0]["starts_at"] == "2026-08-01T10:00:00"
    assert appointments_after_reschedule[0]["status"] == "confirmed"

    cancel_response = client.post("/bot-simulator/message", data={"message": "cancelar turno"})
    assert cancel_response.status_code == 200
    assert "cancele el turno" in cancel_response.text

    appointments_after_cancel = client.get("/api/appointments").json()
    assert appointments_after_cancel[0]["status"] == "cancelled"


def test_bot_does_not_show_occupied_slot(client: TestClient) -> None:
    barber_id, customer_id, service_id = _create_bot_demo_data(client)
    client.post(
        "/api/appointments",
        json={
            "barber_id": barber_id,
            "customer_id": customer_id,
            "service_id": service_id,
            "starts_at": "2026-08-01T09:00:00",
        },
    )

    response = client.post(
        "/bot-simulator/message",
        data={"message": "que horarios tenes para corte el 2026-08-01"},
    )

    assert response.status_code == 200
    assert "tengo libre: 09:00" not in response.text
    assert "tengo libre: 09:15" not in response.text
    assert "09:30" in response.text


def test_bot_can_use_mocked_ollama_intent(client: TestClient, monkeypatch) -> None:
    _create_bot_demo_data(client)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"message": {"content": '{"intent": "list_services"}'}}

    def fake_post(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(settings, "bot_ai_provider", "ollama")
    monkeypatch.setattr("app.services.ai_bot.httpx.post", fake_post)

    response = client.post("/bot-simulator/message", data={"message": "Que me puedo hacer?"})

    assert response.status_code == 200
    assert "Corte" in response.text


def test_bot_falls_back_to_rules_when_ollama_is_unavailable(client: TestClient, monkeypatch) -> None:
    _create_bot_demo_data(client)

    def fake_post(*args, **kwargs):
        raise httpx.ConnectError("Ollama is not running")

    monkeypatch.setattr(settings, "bot_ai_provider", "ollama")
    monkeypatch.setattr("app.services.ai_bot.httpx.post", fake_post)

    response = client.post("/bot-simulator/message", data={"message": "servicios"})

    assert response.status_code == 200
    assert "Corte" in response.text
