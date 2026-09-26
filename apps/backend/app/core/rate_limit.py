"""Sliding-window rate limiting.

Uses an in-process store by default. This protects a single instance; when
running several API replicas, point REDIS_URL at Redis and swap the store
(see docs/deployment.md) so limits are shared.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import RateLimitedError


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = InMemoryRateLimiter()


def rate_limit(bucket: str, limit: int, window_seconds: int):
    """FastAPI dependency factory: ``Depends(rate_limit("auth", 10, 60))``."""

    def _dependency(request: Request) -> None:
        if not get_settings().rate_limit_enabled:
            return
        client = request.client.host if request.client else "unknown"
        if not limiter.hit(f"{bucket}:{client}", limit, window_seconds):
            raise RateLimitedError()

    return _dependency
