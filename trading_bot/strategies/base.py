"""Strategy base class.

A strategy receives bars and may place orders through the broker
interface. It must not assume anything about where bars come from
(historical file vs. live feed) — that is what keeps backtest results
transferable to paper trading.
"""

from __future__ import annotations

import abc

from trading_bot.broker.base import Broker
from trading_bot.models import Bar


class Strategy(abc.ABC):
    name: str = "strategy"

    @abc.abstractmethod
    def on_bar(self, bar: Bar, broker: Broker) -> None:
        """Called once per completed bar, after pending orders were processed."""

    def describe(self) -> str:
        return self.name
