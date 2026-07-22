"""Streaming technical indicators.

Each indicator is a small stateful object with an ``update(value)``
method returning the current indicator value, or ``None`` until enough
data has been seen. Streaming (rather than vectorised) indicators are
what allow the exact same strategy code to run over a historical file
and a live feed.
"""

from __future__ import annotations

from collections import deque


class SMA:
    """Simple moving average over the last ``period`` values."""

    def __init__(self, period: int):
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self._window: deque[float] = deque(maxlen=period)
        self._sum = 0.0

    def update(self, value: float) -> float | None:
        if len(self._window) == self.period:
            self._sum -= self._window[0]
        self._window.append(value)
        self._sum += value
        if len(self._window) < self.period:
            return None
        return self._sum / self.period

    @property
    def value(self) -> float | None:
        if len(self._window) < self.period:
            return None
        return self._sum / self.period


class RSI:
    """Wilder's Relative Strength Index."""

    def __init__(self, period: int = 14):
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self._prev: float | None = None
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None
        self._seed_gains: list[float] = []
        self._seed_losses: list[float] = []
        self.value: float | None = None

    def update(self, value: float) -> float | None:
        if self._prev is None:
            self._prev = value
            return None
        change = value - self._prev
        self._prev = value
        gain = max(change, 0.0)
        loss = max(-change, 0.0)

        if self._avg_gain is None:
            self._seed_gains.append(gain)
            self._seed_losses.append(loss)
            if len(self._seed_gains) < self.period:
                return None
            self._avg_gain = sum(self._seed_gains) / self.period
            self._avg_loss = sum(self._seed_losses) / self.period
        else:
            self._avg_gain = (self._avg_gain * (self.period - 1) + gain) / self.period
            self._avg_loss = (self._avg_loss * (self.period - 1) + loss) / self.period

        if self._avg_loss == 0:
            self.value = 100.0
        else:
            rs = self._avg_gain / self._avg_loss
            self.value = 100.0 - 100.0 / (1.0 + rs)
        return self.value
