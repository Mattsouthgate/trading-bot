"""Paper trading engine.

Runs the same per-bar event sequence as the backtester
(:func:`trading_bot.engine.backtest.run_bar`) over a live-ish feed,
printing a status line per bar and persisting session state to a JSON
file after every bar so a session can be stopped and resumed.

Persisted per session: broker state (cash, positions, fill log), the
drawdown guard's peak/tripped state, the halted flag, and the order-id
counter — so a tripped kill-switch stays tripped across restarts and
fill ids stay unique. NOT persisted: strategy indicator state, which
re-warms from live bars on resume (strategies only enter when flat, so
a held position is not doubled, but an exit signal can be missed until
indicators are warm again).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

from trading_bot import models
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
        halted: bool = False,
    ):
        self.feed = feed
        self.strategy = strategy
        self.broker = broker
        self.state_path = Path(state_path) if state_path else None
        self.guard = guard
        self.printer = printer
        self.equity_curve: list[EquityPoint] = []
        self._halted = halted

    @staticmethod
    def load_session(
        state_path: str | Path,
        default_broker: PaperBroker,
        default_guard: DrawdownGuard | None = None,
    ) -> tuple[PaperBroker, DrawdownGuard | None, bool]:
        """Resume a saved session if the state file exists.

        Returns ``(broker, guard, halted)``. When a state file is found,
        the broker (including its cost settings), the guard's tripped
        state and the halted flag all come from the file — a tripped
        drawdown guard therefore stays tripped across restarts — and the
        order-id counter is fast-forwarded past all persisted fills.
        """
        path = Path(state_path)
        if not path.exists():
            return default_broker, default_guard, False
        state = json.loads(path.read_text())
        if "broker" not in state:  # v1 file: broker fields at top level
            state = {"broker": state, "guard": None, "halted": False}
        broker = PaperBroker.from_state(state["broker"])
        guard = (
            DrawdownGuard.from_state(state["guard"])
            if state.get("guard")
            else default_guard
        )
        next_id = state.get("next_order_id")
        if next_id is None and broker.fills:
            next_id = max(f.order_id for f in broker.fills) + 1
        if next_id is not None:
            models.ensure_order_ids_at_least(next_id)
        return broker, guard, bool(state.get("halted"))

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
            if self.state_path is not None:
                self.printer("\nStopped by user; state saved.")
            else:
                self.printer("\nStopped by user.")
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
        payload = {
            "broker": self.broker.to_state(),
            "guard": self.guard.to_state() if self.guard is not None else None,
            "halted": self._halted,
            "next_order_id": models.peek_next_order_id(),
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
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
