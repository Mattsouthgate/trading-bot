"""Moving-average crossover: long when the fast SMA is above the slow SMA."""

from __future__ import annotations

from trading_bot.broker.base import Broker
from trading_bot.indicators import SMA
from trading_bot.models import Bar, Order, Side
from trading_bot.risk import PositionSizer
from trading_bot.strategies.base import Strategy


class SMACrossover(Strategy):
    name = "sma"

    def __init__(
        self,
        fast: int = 10,
        slow: int = 30,
        *,
        sizer: PositionSizer | None = None,
    ):
        if fast >= slow:
            raise ValueError("fast period must be < slow period")
        self.fast = SMA(fast)
        self.slow = SMA(slow)
        self.sizer = sizer or PositionSizer()
        self._prev_diff: float | None = None

    def on_bar(self, bar: Bar, broker: Broker) -> None:
        fast = self.fast.update(bar.close)
        slow = self.slow.update(bar.close)
        if fast is None or slow is None:
            return
        diff = fast - slow
        prev = self._prev_diff
        self._prev_diff = diff
        if prev is None:
            return

        position = broker.get_position(bar.symbol)
        crossed_up = prev <= 0 < diff
        crossed_down = prev >= 0 > diff

        if crossed_up and position.quantity == 0:
            qty = self.sizer.size(broker, bar)
            if qty > 0:
                broker.submit_order(Order(symbol=bar.symbol, side=Side.BUY, quantity=qty))
        elif crossed_down and position.quantity > 0:
            broker.submit_order(
                Order(symbol=bar.symbol, side=Side.SELL, quantity=position.quantity)
            )

    def describe(self) -> str:
        return f"sma(fast={self.fast.period}, slow={self.slow.period})"
