"""Redis-siz yüngül in-memory rate limiter."""
from __future__ import annotations

import time
from collections import deque


_buckets: dict[str, deque[float]] = {}


async def init_redis():
    return None


async def allow(key: str, limit: int, per_seconds: int) -> bool:
    now = time.monotonic()
    bucket = _buckets.setdefault(key, deque())
    cutoff = now - per_seconds
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True
