"""Task scheduler and progress tracker."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class ProgressTracker:
    """Thread-safe progress tracker for async batch jobs."""

    total: int
    completed: int = 0
    failed: int = 0
    _start_time: float = field(default_factory=time.monotonic, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def increment(self, success: bool = True) -> None:
        async with self._lock:
            if success:
                self.completed += 1
            else:
                self.failed += 1

    @property
    def processed(self) -> int:
        return self.completed + self.failed

    @property
    def progress(self) -> float:
        return self.processed / self.total if self.total > 0 else 0.0

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start_time

    @property
    def rate(self) -> float:
        """Completions per second."""
        elapsed = self.elapsed
        return self.processed / elapsed if elapsed > 0 else 0.0

    @property
    def eta_seconds(self) -> Optional[float]:
        rate = self.rate
        if rate == 0:
            return None
        remaining = self.total - self.processed
        return remaining / rate

    def summary(self) -> str:
        eta = self.eta_seconds
        eta_str = f"ETA: {eta:.0f}s" if eta else "ETA: --"
        return (
            f"{self.processed}/{self.total} ({self.progress:.1%}) | "
            f"✓ {self.completed} ✗ {self.failed} | "
            f"{self.rate:.1f}/s | {eta_str}"
        )
