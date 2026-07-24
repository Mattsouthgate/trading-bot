"""Position sizing and portfolio-level risk limits.

Kept separate from strategies so sizing policy can change without
touching signal logic, and separate from the broker so the broker stays
a dumb execution simulator.
"""

from __future__ import annotations

from trading_bot.broker.base import Broker
from trading_bot.models import Bar


class PositionSizer:
    """Risk a fixed fraction of current equity per entry, with a cash
    buffer so slippage/commission on the next open cannot bounce the order."""

    def __init__(self, fraction: float = 0.95, cash_buffer: float = 0.02):
        if not 0 < fraction <= 1:
            raise ValueError("fraction must be in (0, 1]")
        self.fraction = fraction
        self.cash_buffer = cash_buffer

    def size(self, broker: Broker, bar: Bar) -> int:
        budget = broker.cash * self.fraction * (1 - self.cash_buffer)
        qty = int(budget / bar.close)
        return max(qty, 0)


class DrawdownGuard:
    """Trips once equity falls a given fraction below its running peak.

    The engine checks this after every bar; when tripped, the engine
    liquidates and stops trading. A tripped guard stays tripped.
    """

    def __init__(self, max_drawdown: float = 0.25):
        if not 0 < max_drawdown < 1:
            raise ValueError("max_drawdown must be in (0, 1)")
        self.max_drawdown = max_drawdown
        self.peak: float | None = None
        self.tripped = False

    def update(self, equity: float) -> bool:
        if self.peak is None or equity > self.peak:
            self.peak = equity
        if not self.tripped and equity < self.peak * (1 - self.max_drawdown):
            self.tripped = True
        return self.tripped
