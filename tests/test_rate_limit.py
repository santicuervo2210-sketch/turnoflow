from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import is_rate_limited


def test_login_rate_limit_rejects_too_many_attempts(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "login_rate_limit_per_minute", 2)

    first_response = client.post("/login", data={"username": "owner", "password": "bad"})
    second_response = client.post("/login", data={"username": "owner", "password": "bad"})
    third_response = client.post("/login", data={"username": "owner", "password": "bad"})

    assert first_response.status_code == 401
    assert second_response.status_code == 401
    assert third_response.status_code == 429


def test_bot_webhook_rate_limit_rejects_too_many_messages(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "bot_webhook_rate_limit_per_minute", 1)
    client.post("/api/barber-shops", json={"name": "Rate Bot", "phone": "+5491111111111"})

    first_response = client.post(
        "/bot/webhook",
        json={
            "from_phone": "+5491122222222",
            "to_business_number": "+5491111111111",
            "message": "hola",
        },
        headers={"X-TurnoFlow-Webhook-Secret": "test-webhook-secret-with-at-least-32-characters"},
    )
    second_response = client.post(
        "/bot/webhook",
        json={
            "from_phone": "+5491122222222",
            "to_business_number": "+5491111111111",
            "message": "hola de nuevo",
        },
        headers={"X-TurnoFlow-Webhook-Secret": "test-webhook-secret-with-at-least-32-characters"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429


def test_rate_limit_is_persisted_in_database(db_session: Session) -> None:
    now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)

    assert not is_rate_limited(db_session, "persistent-key", 1, now=now)
    db_session.expire_all()
    assert is_rate_limited(db_session, "persistent-key", 1, now=now)
