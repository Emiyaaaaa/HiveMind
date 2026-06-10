"""Rolling window for in-process p95 duration alerting."""

from __future__ import annotations

import math
from collections import deque


class DurationWindow:
    """Fixed-capacity deque of recent durations in seconds."""

    __slots__ = ("_samples",)

    def __init__(self, max_samples: int = 500) -> None:
        if max_samples < 1:
            raise ValueError("max_samples must be >= 1")
        self._samples: deque[float] = deque(maxlen=max_samples)

    def record(self, seconds: float) -> None:
        if seconds >= 0:
            self._samples.append(seconds)

    def count(self) -> int:
        return len(self._samples)

    def p95(self) -> float | None:
        n = len(self._samples)
        if n == 0:
            return None
        ordered = sorted(self._samples)
        idx = min(n - 1, math.ceil(0.95 * n) - 1)
        return ordered[idx]

    def clear(self) -> None:
        self._samples.clear()
