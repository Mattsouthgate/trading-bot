"""Performance metrics computed from an equity curve and fill log."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from trading_bot.models import Fill, Side


@dataclass(frozen=True)
class EquityPoint:
    timestamp: datetime
    equity: float


@dataclass(frozen=True)
class Metrics:
    starting_equity: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float | None
    num_trades: int
    num_round_trips: int
    win_rate_pct: float | None
    profit_factor: float | None

    def as_lines(self) -> list[str]:
        def fmt(v, suffix=""):
            return "n/a" if v is None else f"{v:,.2f}{suffix}"

        return [
            f"Starting equity : {self.starting_equity:,.2f}",
            f"Final equity    : {self.final_equity:,.2f}",
            f"Total return    : {self.total_return_pct:+.2f}%",
            f"Max drawdown    : {self.max_drawdown_pct:.2f}%",
            f"Sharpe (per-bar): {fmt(self.sharpe)}",
            f"Fills           : {self.num_trades}",
            f"Round trips     : {self.num_round_trips}",
            f"Win rate        : {fmt(self.win_rate_pct, '%')}",
            f"Profit factor   : {fmt(self.profit_factor)}",
        ]


def max_drawdown(equity: list[float]) -> float:
    """Largest peak-to-trough decline, as a fraction of the peak."""
    peak = -math.inf
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst

def sharpe_ratio(equity: list[float]) -> float | None:
    """Annualisation-free Sharpe on per-bar returns (risk-free rate 0).

    Reported per-bar because the framework does not know the bar
    interval; callers comparing runs should use the same interval.
    """
    if len(equity) < 3:
        return None
    returns = [
        (b - a) / a for a, b in zip(equity, equity[1:]) if a > 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std == 0:
        return None
    return mean / std


def round_trips(fills: list[Fill]) -> list[float]:
    """Realised PnL per closed lot, FIFO-matched per symbol."""
    lots: dict[str, list[list[float]]] = {}  # symbol -> [[qty, price], ...]
    pnls: list[float] = []
    for fill in fills:
        book = lots.setdefault(fill.symbol, [])
        if fill.side is Side.BUY:
            book.append([fill.quantity, fill.price])
        else:
            remaining = fill.quantity
            realised = 0.0
            while remaining > 1e-9 and book:
                lot = book[0]
                matched = min(lot[0], remaining)
                realised += (fill.price - lot[1]) * matched
                lot[0] -= matched
                remaining -= matched
                if lot[0] <= 1e-9:
                    book.pop(0)
            pnls.append(realised - fill.commission)
    return pnls


def compute(equity_curve: list[EquityPoint], fills: list[Fill]) -> Metrics:
    if not equity_curve:
        raise ValueError("empty equity curve")
    equity = [p.equity for p in equity_curve]
    start, final = equity[0], equity[-1]
    trips = round_trips(fills)
    wins = [p for p in trips if p > 0]
    losses = [p for p in trips if p < 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    return Metrics(
        starting_equity=start,
        final_equity=final,
        total_return_pct=(final - start) / start * 100 if start else 0.0,
        max_drawdown_pct=max_drawdown(equity) * 100,
        sharpe=sharpe_ratio(equity),
        num_trades=len(fills),
        num_round_trips=len(trips),
        win_rate_pct=(len(wins) / len(trips) * 100) if trips else None,
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else None,
    )
