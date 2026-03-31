"""
Per-backend rate limiter with token bucket algorithm.
Supports requests-per-minute and concurrent request limits.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional


class RateLimiter:
    """
    Async token bucket rate limiter.

    Limits:
        - requests per minute (RPM)
        - concurrent requests (semaphore)
    """

    def __init__(
        self,
        requests_per_minute: int = 60,
        max_concurrent: int = 10,
    ):
        self.rpm = requests_per_minute
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tokens = float(requests_per_minute)
        self._max_tokens = float(requests_per_minute)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire rate limit slot. Blocks if over limit."""
        # Token bucket: refill tokens based on elapsed time
        await self._semaphore.acquire()
        try:
            await self._wait_for_token()
        except Exception:
            self._semaphore.release()
            raise

    def release(self) -> None:
        """Release the concurrent slot."""
        self._semaphore.release()

    async def _wait_for_token(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                # Refill at rate of rpm/60 per second
                self._tokens = min(
                    self._max_tokens,
                    self._tokens + elapsed * (self.rpm / 60.0),
                )
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                # How long to wait for next token
                wait_time = (1.0 - self._tokens) / (self.rpm / 60.0)

            await asyncio.sleep(min(wait_time, 1.0))

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        self.release()


class NoOpRateLimiter:
    """Passthrough rate limiter (no limiting). For MockBackend."""

    async def acquire(self) -> None:
        pass

    def release(self) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass
