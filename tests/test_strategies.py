import unittest

from tests.helpers import make_series
from trading_bot.broker.paper import PaperBroker
from trading_bot.engine import backtest
from trading_bot.strategies.rsi_reversion import RSIReversion
from trading_bot.strategies.sma_crossover import SMACrossover


class TestSMACrossover(unittest.TestCase):
    def test_rejects_fast_not_less_than_slow(self):
        with self.assertRaises(ValueError):
            SMACrossover(fast=10, slow=10)

    def test_buys_on_cross_up_and_sells_on_cross_down(self):
        # Down, then sharply up (fast crosses above slow), then sharply down.
        closes = [100, 98, 96, 94, 92, 90, 95, 100, 105, 110, 115,
                  110, 100, 90, 80, 70, 65, 60]
        broker = PaperBroker(starting_cash=100_000, slippage_bps=0)
        result = backtest.run(
            make_series(closes), SMACrossover(fast=2, slow=4), broker
        )
        sides = [f.side.value for f in result.fills]
        self.assertEqual(sides, ["buy", "sell"])

    def test_no_orders_during_warmup(self):
        closes = [100, 101, 102]
        broker = PaperBroker()
        result = backtest.run(make_series(closes), SMACrossover(fast=5, slow=10), broker)
        self.assertEqual(result.fills, [])


class TestRSIReversion(unittest.TestCase):
    def test_buys_after_selloff_and_exits_on_recovery(self):
        closes = [100] + [100 - 3 * i for i in range(1, 8)]  # steady selloff
        closes += [82, 85, 88, 91, 94, 97, 100, 103]          # recovery
        broker = PaperBroker(starting_cash=100_000, slippage_bps=0)
        result = backtest.run(
            make_series(closes), RSIReversion(period=5, oversold=30, exit_level=60),
            broker,
        )
        sides = [f.side.value for f in result.fills]
        self.assertIn("buy", sides)
        self.assertEqual(sides[0], "buy")
        self.assertIn("sell", sides)

    def test_validates_thresholds(self):
        with self.assertRaises(ValueError):
            RSIReversion(oversold=60, exit_level=50)


if __name__ == "__main__":
    unittest.main()
