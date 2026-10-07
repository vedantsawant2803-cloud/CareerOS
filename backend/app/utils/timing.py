"""Timing helpers for latency metadata and logs."""

from __future__ import annotations

import time
from types import TracebackType


class Timer:
    """Context manager that measures wall-clock milliseconds.

    Example:
        >>> with Timer() as timer:
        ...     _ = sum(range(1000))
        >>> timer.elapsed_ms >= 0
        True
    """

    def __init__(self) -> None:
        self._start: float = 0.0
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.elapsed_ms = round((time.perf_counter() - self._start) * 1000, 2)


def now_ms() -> float:
    """Current monotonic time in milliseconds."""
    return time.perf_counter() * 1000


def elapsed_since(start_ms: float) -> float:
    """Milliseconds elapsed since ``start_ms`` (from :func:`now_ms`)."""
    return round(now_ms() - start_ms, 2)
