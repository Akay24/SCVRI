"""Redis sliding-window rate limiter."""
from __future__ import annotations

import time

import redis.asyncio as aioredis


class RateLimitExceeded(Exception):
    """Raised when the rate limit for a key is exceeded."""

    def __init__(self, key: str, limit: int, window: int) -> None:
        super().__init__(
            f"Rate limit exceeded for '{key}': {limit} requests per {window}s"
        )
        self.key = key
        self.limit = limit
        self.window = window


# Lua script: atomic sliding-window counter using a sorted set.
# Returns 1 if allowed, 0 if rejected.
_SLIDING_WINDOW_LUA = """
local key       = KEYS[1]
local now       = tonumber(ARGV[1])
local window    = tonumber(ARGV[2])
local limit     = tonumber(ARGV[3])
local threshold = now - window * 1000

redis.call('ZREMRANGEBYSCORE', key, '-inf', threshold)
local count = redis.call('ZCARD', key)
if count < limit then
    redis.call('ZADD', key, now, now)
    redis.call('PEXPIRE', key, window * 1000)
    return 1
else
    return 0
end
"""


class SlidingWindowRateLimiter:
    """
    Tenant/endpoint-level sliding-window rate limiter backed by Redis.

    Parameters
    ----------
    redis:
        Async Redis client.
    limit:
        Maximum number of requests allowed within *window* seconds.
    window:
        Window size in seconds.
    prefix:
        Redis key prefix (allows separate limiters per feature).
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        limit: int = 100,
        window: int = 60,
        prefix: str = "rl",
    ) -> None:
        self._redis = redis
        self._limit = limit
        self._window = window
        self._prefix = prefix
        self._script: aioredis.client.Script | None = None

    async def _get_script(self) -> aioredis.client.Script:
        if self._script is None:
            self._script = self._redis.register_script(_SLIDING_WINDOW_LUA)
        return self._script

    def _make_key(self, identifier: str) -> str:
        return f"{self._prefix}:{identifier}"

    async def is_allowed(self, identifier: str) -> bool:
        """Return True if the request is within the limit."""
        now_ms = int(time.time() * 1000)
        key = self._make_key(identifier)
        script = await self._get_script()
        result = await script(keys=[key], args=[now_ms, self._window, self._limit])
        return bool(result)

    async def check(self, identifier: str) -> None:
        """
        Assert that the rate limit is not exceeded.

        Raises :exc:`RateLimitExceeded` if the limit is reached.
        """
        if not await self.is_allowed(identifier):
            raise RateLimitExceeded(identifier, self._limit, self._window)

    async def remaining(self, identifier: str) -> int:
        """Return how many requests remain in the current window."""
        now_ms = int(time.time() * 1000)
        key = self._make_key(identifier)
        threshold = now_ms - self._window * 1000
        await self._redis.zremrangebyscore(key, "-inf", threshold)
        count = await self._redis.zcard(key)
        return max(0, self._limit - count)


# ── Webhook-inbound rate limiter (per tenant, per source) ─────────────────────
# 500 webhooks / minute per tenant  
WEBHOOK_RATE_LIMIT = 500
WEBHOOK_RATE_WINDOW = 60

# ── ERP pull rate limiter (per tenant, per system) ────────────────────────────
ERP_PULL_RATE_LIMIT = 10
ERP_PULL_RATE_WINDOW = 60

# ── Outbound push rate limiter (per endpoint) ─────────────────────────────────
OUTBOUND_RATE_LIMIT = 200
OUTBOUND_RATE_WINDOW = 60
