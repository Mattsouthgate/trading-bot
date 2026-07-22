"""Paper trading engine.

Runs the same per-bar event sequence as the backtester
(:func:`trading_bot.engine.backtest.run_bar`) over a live-ish feed,
printing a status line per bar and persisting broker state to a JSON
file after every bar so a session can be stopped and resumed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

from trading_bot.broker.paper import PaperBroker
from trading_bot.engine.backtest import run_bar
from trading_bot.metrics import EquityPoint, compute
from trading_bot.models import Bar
from trading_bot.risk import DrawdownGuard
from trading_bot.strategies.base import Strategy


class PaperTradingEngine:
    def __init__(
        self,
        feed: Iterable[Bar],
        strategy: Strategy,
        broker: PaperBroker,
        *,
        state_path: str | Path | None = None,
        guard: DrawdownGuard | None = None,
        printer: Callable[[str], None] = print,
    ):
        self.feed = feed
        self.strategy = strategy
        self.broker = broker
        self.state_path = Path(state_path) if state_path else None
        self.guard = guard
        self.printer = printer
        self.equity_curve: list[EquityPoint] = []
        self._halted = False

    @staticmethod
    def load_broker(state_path: str | Path, default: PaperBroker) -> PaperBroker:
        """Resume from a saved session if the state file exists."""
        path = Path(state_path)
        if not path.exists():
            return default
        with path.open() as fh:
            return PaperBroker.from_state(json.load(fh))

    def run(self, max_bars: int | None = None) -> None:
        last_prices: dict[str, float] = {}
        bars = 0
        try:
            for bar in self.feed:
                point, self._halted = run_bar(
                    bar,
                    self.broker,
                    self.strategy,
                    self.guard,
                    last_prices,
                    trading_halted=self._halted,
                )
                self.equity_curve.append(point)
                self._save_state()
                self._report(bar, point)
                bars += 1
                if max_bars is not None and bars >= max_bars:
                    break
        except KeyboardInterrupt:
            self.printer("\nStopped by user; state saved.")
        self._summary()

    def _report(self, bar: Bar, point: EquityPoint) -> None:
        pos = self.broker.get_position(bar.symbol)
        halted = "  [HALTED: drawdown guard]" if self._halted else ""
        self.printer(
            f"{bar.timestamp:%Y-%m-%d %H:%M} {bar.symbol} close={bar.close:>10.2f} "
            f"pos={pos.quantity:>6.0f} cash={self.broker.cash:>12.2f} "
            f"equity={point.equity:>12.2f}{halted}"
        )

    def _save_state(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.broker.to_state(), indent=2))
        tmp.replace(self.state_path)  # atomic on POSIX: no torn state files

    def _summary(self) -> None:
        if not self.equity_curve:
            self.printer("No bars processed.")
            return
        self.printer("\n=== Paper trading session summary ===")
        for line in compute(self.equity_curve, self.broker.fills).as_lines():
            self.printer(line)
        if self.state_path:
            self.printer(f"State saved to {self.state_path}")
