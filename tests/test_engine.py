import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_series
from trading_bot.broker.paper import PaperBroker
from trading_bot.data.feed import SyntheticDataFeed
from trading_bot.engine import backtest
from trading_bot.engine.paper import PaperTradingEngine
from trading_bot.models import Order, Side
from trading_bot.risk import DrawdownGuard
from trading_bot.strategies.base import Strategy
from trading_bot.strategies.sma_crossover import SMACrossover


class BuyOnceStrategy(Strategy):
    """Buys a fixed quantity on the first bar, then holds."""

    def __init__(self, quantity: int = 10):
        self.quantity = quantity
        self.bought = False

    def on_bar(self, bar, broker):
        if not self.bought:
            broker.submit_order(
                Order(symbol=bar.symbol, side=Side.BUY, quantity=self.quantity)
            )
            self.bought = True


class TestBacktestEngine(unittest.TestCase):
    def test_orders_fill_on_next_bar_not_same_bar(self):
        closes = [100, 105, 110]
        broker = PaperBroker(starting_cash=10_000, slippage_bps=0)
        result = backtest.run(make_series(closes), BuyOnceStrategy(), broker)
        self.assertEqual(len(result.fills), 1)
        # Order placed on bar 0 (close 100); bar 1 opens at 100.
        self.assertEqual(result.fills[0].price, 100)
        self.assertEqual(result.fills[0].timestamp, result.equity_curve[1].timestamp)

    def test_equity_curve_marks_to_close(self):
        closes = [100, 100, 120]
        broker = PaperBroker(starting_cash=10_000, slippage_bps=0,
                             commission_per_trade=0)
        result = backtest.run(make_series(closes), BuyOnceStrategy(10), broker)
        # After buying 10 @ 100, a close of 120 marks +200.
        self.assertAlmostEqual(result.equity_curve[-1].equity, 10_200)

    def test_empty_feed_is_an_error(self):
        with self.assertRaises(ValueError):
            backtest.run([], BuyOnceStrategy(), PaperBroker())

    def test_deterministic_over_synthetic_feed(self):
        def run_once():
            feed = SyntheticDataFeed("X", bars=300, seed=11)
            return backtest.run(feed, SMACrossover(fast=5, slow=20)).metrics

        self.assertEqual(run_once(), run_once())

    def test_drawdown_guard_liquidates_and_halts(self):
        closes = [100, 100, 100] + [100 - 5 * i for i in range(1, 15)]
        broker = PaperBroker(starting_cash=10_000, slippage_bps=0,
                             commission_per_trade=0)
        guard = DrawdownGuard(max_drawdown=0.10)
        result = backtest.run(make_series(closes), BuyOnceStrategy(50), broker, guard=guard)
        self.assertTrue(result.guard_tripped)
        self.assertEqual(broker.get_position("TEST").quantity, 0)
        sides = [f.side for f in result.fills]
        self.assertEqual(sides, [Side.BUY, Side.SELL])


class TestPaperTradingEngine(unittest.TestCase):
    def test_session_persists_and_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            feed = SyntheticDataFeed("X", bars=5, seed=3, realtime=False)
            broker = PaperBroker(starting_cash=25_000)
            engine = PaperTradingEngine(
                feed, BuyOnceStrategy(10), broker,
                state_path=state, printer=lambda _: None,
            )
            engine.run()
            self.assertTrue(state.exists())
            saved = json.loads(state.read_text())
            self.assertEqual(saved["broker"]["starting_cash"], 25_000)
            self.assertEqual(len(saved["broker"]["fills"]), 1)
            self.assertFalse(saved["halted"])

            resumed, guard, halted = PaperTradingEngine.load_session(
                state, PaperBroker()
            )
            self.assertEqual(resumed.get_position("X").quantity, 10)
            self.assertAlmostEqual(resumed.cash, broker.cash)
            self.assertFalse(halted)

    def test_load_session_returns_defaults_when_no_state(self):
        default = PaperBroker(starting_cash=1234)
        default_guard = DrawdownGuard(0.5)
        broker, guard, halted = PaperTradingEngine.load_session(
            "/nonexistent/state.json", default, default_guard
        )
        self.assertIs(broker, default)
        self.assertIs(guard, default_guard)
        self.assertFalse(halted)

    def test_resume_keeps_drawdown_guard_tripped(self):
        # A tripped kill-switch must survive a process restart: the
        # resumed session may not trade again.
        closes = [100, 100, 100] + [100 - 6 * i for i in range(1, 10)]
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            broker = PaperBroker(starting_cash=10_000, slippage_bps=0,
                                 commission_per_trade=0)
            engine = PaperTradingEngine(
                make_series(closes, symbol="X"), BuyOnceStrategy(80), broker,
                state_path=state, guard=DrawdownGuard(0.10),
                printer=lambda _: None,
            )
            engine.run()
            self.assertTrue(engine._halted)
            fills_before = len(broker.fills)

            resumed, guard, halted = PaperTradingEngine.load_session(
                state, PaperBroker(), DrawdownGuard(0.10)
            )
            self.assertTrue(halted)
            self.assertTrue(guard.tripped)

            # Rising prices that would normally trigger a fresh buy.
            rally = make_series([60, 65, 70, 75, 80, 85, 90], symbol="X")
            engine2 = PaperTradingEngine(
                rally, BuyOnceStrategy(10), resumed,
                state_path=state, guard=guard, halted=halted,
                printer=lambda _: None,
            )
            engine2.run()
            self.assertEqual(len(resumed.fills), fills_before)  # no new trades

    def test_order_ids_stay_unique_after_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            feed = SyntheticDataFeed("X", bars=5, seed=3, realtime=False)
            engine = PaperTradingEngine(
                feed, BuyOnceStrategy(10), PaperBroker(),
                state_path=state, printer=lambda _: None,
            )
            engine.run()

            # Simulate a fresh process, where the module-level counter
            # would restart at 1 and collide with persisted fill ids.
            from trading_bot import models
            original = models._order_ids
            models._order_ids = models._OrderIdGenerator()
            self.addCleanup(setattr, models, "_order_ids", original)

            resumed, _, _ = PaperTradingEngine.load_session(state, PaperBroker())
            existing_ids = {f.order_id for f in resumed.fills}
            new_id = models._order_ids()
            self.assertNotIn(new_id, existing_ids)

    def test_max_bars_limits_run(self):
        feed = SyntheticDataFeed("X", bars=100, seed=3, realtime=False)
        engine = PaperTradingEngine(
            feed, BuyOnceStrategy(1), PaperBroker(), printer=lambda _: None
        )
        engine.run(max_bars=7)
        self.assertEqual(len(engine.equity_curve), 7)


if __name__ == "__main__":
    unittest.main()
