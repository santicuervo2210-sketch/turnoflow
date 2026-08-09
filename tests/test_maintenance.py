from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BarberShop, BotConversationState, BotWebhookReceipt, RateLimitBucket
from app.services.maintenance import cleanup_ephemeral_data


def test_maintenance_endpoint_requires_its_own_secret(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "cron_secret", "cron-secret-with-at-least-32-characters")

    unauthorized = client.get("/internal/maintenance")
    authorized = client.get(
        "/internal/maintenance",
        headers={"Authorization": "Bearer cron-secret-with-at-least-32-characters"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["status"] == "ok"


def test_cleanup_removes_only_expired_ephemeral_data(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "bot_conversation_ttl_days", 30)
    monkeypatch.setattr(settings, "webhook_receipt_ttl_days", 30)
    now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    old = now - timedelta(days=31)
    recent = now - timedelta(days=1)
    shop = BarberShop(name="Mantenimiento")
    db_session.add(shop)
    db_session.flush()
    db_session.add_all(
        [
            BotConversationState(barber_shop_id=shop.id, phone="old", updated_at=old),
            BotConversationState(barber_shop_id=shop.id, phone="recent", updated_at=recent),
            BotWebhookReceipt(
                barber_shop_id=shop.id,
                provider_message_id="old",
                status="completed",
                created_at=old,
            ),
            RateLimitBucket(
                key="old",
                window_started_at=old,
                request_count=1,
                updated_at=old,
            ),
        ]
    )
    db_session.commit()

    deleted = cleanup_ephemeral_data(db_session, now=now)

    assert deleted["bot_conversations"] == 1
    assert deleted["webhook_receipts"] == 1
    assert deleted["rate_limit_buckets"] == 1
    assert db_session.scalars(select(BotConversationState)).one().phone == "recent"
