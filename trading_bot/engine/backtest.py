"""Backtesting engine.

The event loop is the single source of truth for ordering:

1. ``broker.process_bar(bar)`` — pending orders (submitted on earlier
   bars) fill against this bar first,
2. ``strategy.on_bar(bar, broker)`` — the strategy sees the completed
   bar and may submit new orders, which can only fill from the next bar,
3. equity is marked at the bar close and the drawdown guard is checked.

The paper trading engine reuses this exact loop over a live feed, which
is what makes backtest results comparable to paper results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from trading_bot.broker.paper import PaperBroker
from trading_bot.metrics import EquityPoint, Metrics, compute
from trading_bot.models import Bar, Fill, Order, Side
from trading_bot.risk import DrawdownGuard
from trading_bot.strategies.base import Strategy


@dataclass
class BacktestResult:
    metrics: Metrics
    equity_curve: list[EquityPoint]
    fills: list[Fill]
    rejected: list[Order]
    guard_tripped: bool = False
    bars_processed: int = 0
    last_prices: dict[str, float] = field(default_factory=dict)


def run_bar(
    bar: Bar,
    broker: PaperBroker,
    strategy: Strategy,
    guard: DrawdownGuard | None,
    last_prices: dict[str, float],
    *,
    trading_halted: bool,
) -> tuple[EquityPoint, bool]:
    """Process one bar through the standard event sequence.

    Returns the equity point at this bar's close and whether trading is
    (now) halted by the drawdown guard. Shared by backtest and paper
    engines so their semantics cannot drift apart.
    """
    broker.process_bar(bar)
    if not trading_halted:
        strategy.on_bar(bar, broker)
    last_prices[bar.symbol] = bar.close
    equity = broker.equity(last_prices)

    if guard is not None and guard.update(equity) and not trading_halted:
        # Liquidate everything at the next bar and stop trading.
        trading_halted = True
        for order in broker.open_orders():
            broker.cancel_order(order.id)
        pos = broker.get_position(bar.symbol)
        if pos.quantity > 0:
            broker.submit_order(
                Order(symbol=bar.symbol, side=Side.SELL, quantity=pos.quantity)
            )
    return EquityPoint(timestamp=bar.timestamp, equity=equity), trading_halted


def run(
    feed: Iterable[Bar],
    strategy: Strategy,
    broker: PaperBroker | None = None,
    *,
    guard: DrawdownGuard | None = None,
) -> BacktestResult:
    broker = broker or PaperBroker()
    equity_curve: list[EquityPoint] = []
    last_prices: dict[str, float] = {}
    halted = False
    bars = 0

    for bar in feed:
        point, halted = run_bar(
            bar, broker, strategy, guard, last_prices, trading_halted=halted
        )
        equity_curve.append(point)
        bars += 1

    if not equity_curve:
        raise ValueError("Feed produced no bars — nothing to backtest")

    return BacktestResult(
        metrics=compute(equity_curve, broker.fills),
        equity_curve=equity_curve,
        fills=broker.fills,
        rejected=broker.rejected,
        guard_tripped=halted,
        bars_processed=bars,
        last_prices=last_prices,
    )
