from __future__ import annotations

from collections import defaultdict, deque
from threading import RLock
import time


class InMemoryRateLimiter:
    """Small single-process limiter for expensive public demo endpoints."""

    def __init__(self, *, limit: int, window_seconds: int = 60) -> None:
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("rate limit and window must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = RLock()

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = max(1, int(events[0] + self.window_seconds - now) + 1)
                return False, retry_after
            events.append(now)
        return True, 0
