"""RSI mean reversion: buy oversold, exit when RSI recovers."""

from __future__ import annotations

from trading_bot.broker.base import Broker
from trading_bot.indicators import RSI
from trading_bot.models import Bar, Order, Side
from trading_bot.risk import PositionSizer
from trading_bot.strategies.base import Strategy


class RSIReversion(Strategy):
    name = "rsi"

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        exit_level: float = 55.0,
        *,
        sizer: PositionSizer | None = None,
    ):
        if not 0 < oversold < exit_level < 100:
            raise ValueError("Require 0 < oversold < exit_level < 100")
        self.rsi = RSI(period)
        self.oversold = oversold
        self.exit_level = exit_level
        self.sizer = sizer or PositionSizer()

    def on_bar(self, bar: Bar, broker: Broker) -> None:
        value = self.rsi.update(bar.close)
        if value is None:
            return
        position = broker.get_position(bar.symbol)
        if value < self.oversold and position.quantity == 0:
            qty = self.sizer.size(broker, bar)
            if qty > 0:
                broker.submit_order(Order(symbol=bar.symbol, side=Side.BUY, quantity=qty))
        elif value > self.exit_level and position.quantity > 0:
            broker.submit_order(
                Order(symbol=bar.symbol, side=Side.SELL, quantity=position.quantity)
            )

    def describe(self) -> str:
        return (
            f"rsi(period={self.rsi.period}, oversold={self.oversold}, "
            f"exit={self.exit_level})"
        )
