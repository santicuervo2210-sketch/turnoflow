from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.models import RateLimitEvent

WINDOW_SECONDS = 60


def is_rate_limited(
    session: Session,
    key: str,
    limit: int,
    now: datetime | None = None,
) -> bool:
    current_time = now or datetime.now(UTC)
    threshold = current_time - timedelta(seconds=WINDOW_SECONDS)

    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})

    session.execute(
        delete(RateLimitEvent).where(
            RateLimitEvent.key == key,
            RateLimitEvent.created_at <= threshold,
        )
    )
    event_count = session.scalar(
        select(func.count(RateLimitEvent.id)).where(
            RateLimitEvent.key == key,
            RateLimitEvent.created_at > threshold,
        )
    ) or 0
    if event_count >= limit:
        session.commit()
        return True

    session.add(RateLimitEvent(key=key, created_at=current_time))
    session.commit()
    return False


def reset_rate_limits(session: Session) -> None:
    session.execute(delete(RateLimitEvent))
    session.commit()
