from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BotConversationState, BotWebhookReceipt, RateLimitBucket, RateLimitEvent


def cleanup_ephemeral_data(session: Session, now: datetime | None = None) -> dict[str, int]:
    current_time = now or datetime.now(UTC)
    conversation_cutoff = current_time - timedelta(days=settings.bot_conversation_ttl_days)
    receipt_cutoff = current_time - timedelta(days=settings.webhook_receipt_ttl_days)
    limiter_cutoff = current_time - timedelta(days=1)

    deleted = {
        "bot_conversations": session.execute(
            delete(BotConversationState).where(BotConversationState.updated_at < conversation_cutoff)
        ).rowcount
        or 0,
        "webhook_receipts": session.execute(
            delete(BotWebhookReceipt).where(BotWebhookReceipt.created_at < receipt_cutoff)
        ).rowcount
        or 0,
        "rate_limit_buckets": session.execute(
            delete(RateLimitBucket).where(RateLimitBucket.updated_at < limiter_cutoff)
        ).rowcount
        or 0,
        "legacy_rate_limit_events": session.execute(
            delete(RateLimitEvent).where(RateLimitEvent.created_at < limiter_cutoff)
        ).rowcount
        or 0,
    }
    session.commit()
    return deleted
