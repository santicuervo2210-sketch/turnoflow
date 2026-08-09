from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.models import RateLimitBucket, RateLimitEvent

WINDOW_SECONDS = 60


def is_rate_limited(
    session: Session,
    key: str,
    limit: int,
    now: datetime | None = None,
) -> bool:
    current_time = now or datetime.now(UTC)
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})

    bucket = session.get(RateLimitBucket, key)
    if bucket is None:
        session.add(
            RateLimitBucket(
                key=key,
                window_started_at=current_time,
                request_count=1,
                updated_at=current_time,
            )
        )
        session.commit()
        return False

    window_started_at = bucket.window_started_at
    if window_started_at.tzinfo is None:
        window_started_at = window_started_at.replace(tzinfo=UTC)

    if current_time - window_started_at >= timedelta(seconds=WINDOW_SECONDS):
        bucket.window_started_at = current_time
        bucket.request_count = 1
        bucket.updated_at = current_time
        session.commit()
        return False

    if bucket.request_count >= limit:
        session.commit()
        return True

    bucket.request_count += 1
    bucket.updated_at = current_time
    session.commit()
    return False


def reset_rate_limits(session: Session) -> None:
    session.execute(delete(RateLimitBucket))
    session.execute(delete(RateLimitEvent))
    session.commit()
