from __future__ import annotations

import time
from collections import defaultdict, deque

WINDOW_SECONDS = 60
_events: dict[str, deque[float]] = defaultdict(deque)


def is_rate_limited(key: str, limit: int, now: float | None = None) -> bool:
    current_time = time.time() if now is None else now
    events = _events[key]

    while events and events[0] <= current_time - WINDOW_SECONDS:
        events.popleft()

    if len(events) >= limit:
        return True

    events.append(current_time)
    return False


def reset_rate_limits() -> None:
    _events.clear()
