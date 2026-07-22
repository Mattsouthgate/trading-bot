"""Broker interface.

Strategies talk only to this interface. Backtesting and paper trading
both use :class:`trading_bot.broker.paper.PaperBroker`; a real broker
adapter would implement the same interface, which is what lets a
strategy graduate from backtest to paper to live without code changes.
"""

from __future__ import annotations

import abc

from trading_bot.models import Bar, Fill, Order, Position


class Broker(abc.ABC):
    @abc.abstractmethod
    def submit_order(self, order: Order) -> Order:
        """Queue an order. Fills happen on a subsequent bar, never instantly."""

    @abc.abstractmethod
    def cancel_order(self, order_id: int) -> bool:
        """Cancel an open order. Returns True if it was cancelled."""

    @abc.abstractmethod
    def get_position(self, symbol: str) -> Position:
        """Current position for a symbol (zero quantity if flat)."""

    @property
    @abc.abstractmethod
    def cash(self) -> float:
        """Settled cash available."""

    @abc.abstractmethod
    def equity(self, last_prices: dict[str, float]) -> float:
        """Cash plus market value of open positions."""

    @abc.abstractmethod
    def process_bar(self, bar: Bar) -> list[Fill]:
        """Advance the simulation clock: try to fill pending orders
        against this bar. Called by the engine, not by strategies."""
