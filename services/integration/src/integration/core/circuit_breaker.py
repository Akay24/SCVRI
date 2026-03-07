"""Circuit breaker and retry logic using tenacity."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open and the call is rejected."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Circuit '{name}' is OPEN — call rejected")
        self.name = name


_HALF_OPEN_PROBE_LOCK: dict[str, asyncio.Lock] = {}


class CircuitBreaker:
    """
    Simple async circuit breaker with three states: CLOSED → OPEN → HALF-OPEN.

    Parameters
    ----------
    name:
        Logical name (for logging / metrics).
    failure_threshold:
        Number of consecutive failures before tripping to OPEN.
    recovery_timeout:
        Seconds to wait in OPEN state before transitioning to HALF-OPEN.
    success_threshold:
        Consecutive successes in HALF-OPEN before closing again.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = self.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        return self._state

    async def call(self, fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        async with self._lock:
            if self._state == self.OPEN:
                elapsed = asyncio.get_event_loop().time() - (self._opened_at or 0)
                if elapsed >= self.recovery_timeout:
                    logger.info("CircuitBreaker[%s] → HALF-OPEN", self.name)
                    self._state = self.HALF_OPEN
                    self._success_count = 0
                else:
                    raise CircuitOpenError(self.name)

        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:
            async with self._lock:
                self._on_failure()
            raise
        else:
            async with self._lock:
                self._on_success()
            return result

    def _on_failure(self) -> None:
        if self._state == self.HALF_OPEN:
            self._state = self.OPEN
            self._opened_at = asyncio.get_event_loop().time()
            logger.warning("CircuitBreaker[%s] → OPEN (probe failed)", self.name)
            return

        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._state = self.OPEN
            self._opened_at = asyncio.get_event_loop().time()
            logger.warning(
                "CircuitBreaker[%s] → OPEN after %d failures",
                self.name, self._failure_count,
            )

    def _on_success(self) -> None:
        if self._state == self.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state = self.CLOSED
                self._failure_count = 0
                logger.info("CircuitBreaker[%s] → CLOSED (recovered)", self.name)
            return
        # Normal CLOSED: reset failure counter on success
        self._failure_count = 0


def _log_retry(retry_state: RetryCallState) -> None:
    logger.warning(
        "Retry attempt %d for %s",
        retry_state.attempt_number,
        getattr(retry_state.fn, "__name__", "unknown"),
    )


async def with_retry(
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    max_attempts: int = 3,
    wait_min: float = 1.0,
    wait_max: float = 10.0,
    retry_exceptions: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> T:
    """
    Execute *fn* with exponential back-off retry.

    Intended for wrapping individual HTTP calls before the circuit breaker layer.
    """
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=wait_min, max=wait_max),
        retry=retry_if_exception_type(retry_exceptions),
        after=_log_retry,
        reraise=True,
    ):
        with attempt:
            return await fn(*args, **kwargs)


# ── Module-level circuit breakers (one per ERP system) ────────────────────────
_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name)
    return _breakers[name]
