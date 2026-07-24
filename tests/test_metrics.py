import unittest
from datetime import datetime, timezone

from trading_bot.metrics import (
    EquityPoint,
    compute,
    max_drawdown,
    round_trips,
    sharpe_ratio,
)
from trading_bot.models import Fill, Side

TS = datetime(2025, 1, 1, tzinfo=timezone.utc)


def fill(side: Side, qty: float, price: float, commission: float = 0.0) -> Fill:
    return Fill(
        order_id=1, symbol="TEST", side=side, quantity=qty,
        price=price, commission=commission, timestamp=TS,
    )


class TestMaxDrawdown(unittest.TestCase):
    def test_monotonic_up_has_zero_drawdown(self):
        self.assertEqual(max_drawdown([100, 110, 120]), 0.0)

    def test_known_drawdown(self):
        # Peak 200, trough 150 -> 25%
        self.assertAlmostEqual(max_drawdown([100, 200, 150, 180]), 0.25)

    def test_uses_worst_peak_to_trough(self):
        self.assertAlmostEqual(max_drawdown([100, 90, 120, 60]), 0.5)


class TestSharpe(unittest.TestCase):
    def test_needs_enough_points(self):
        self.assertIsNone(sharpe_ratio([100, 101]))

    def test_constant_equity_has_no_sharpe(self):
        self.assertIsNone(sharpe_ratio([100, 100, 100, 100]))

    def test_positive_for_uptrend(self):
        self.assertGreater(sharpe_ratio([100, 101, 103, 104, 106]), 0)


class TestRoundTrips(unittest.TestCase):
    def test_simple_win(self):
        pnls = round_trips([fill(Side.BUY, 10, 100), fill(Side.SELL, 10, 110)])
        self.assertEqual(pnls, [100.0])

    def test_fifo_matching_across_lots(self):
        pnls = round_trips([
            fill(Side.BUY, 10, 100),
            fill(Side.BUY, 10, 120),
            fill(Side.SELL, 15, 130),
        ])
        # 10 @ (130-100) + 5 @ (130-120) = 350
        self.assertEqual(pnls, [350.0])

    def test_commissions_on_both_sides_reduce_pnl(self):
        pnls = round_trips([
            fill(Side.BUY, 1, 100, commission=0.5),
            fill(Side.SELL, 1, 101, commission=0.5),
        ])
        self.assertEqual(pnls, [0.0])

    def test_buy_commission_alone_reduces_pnl(self):
        # A marginal trade must not be flattered into a winner by
        # ignoring the entry commission.
        pnls = round_trips([
            fill(Side.BUY, 10, 100, commission=5.0),
            fill(Side.SELL, 10, 100.5, commission=0.0),
        ])
        self.assertEqual(pnls, [0.0])

    def test_buy_commission_prorated_across_partial_exits(self):
        pnls = round_trips([
            fill(Side.BUY, 10, 100, commission=10.0),  # 1.0 per unit
            fill(Side.SELL, 4, 110),
            fill(Side.SELL, 6, 120),
        ])
        self.assertEqual(pnls, [4 * 10 - 4.0, 6 * 20 - 6.0])


class TestCompute(unittest.TestCase):
    def test_end_to_end(self):
        curve = [EquityPoint(TS, e) for e in (1000, 1100, 1050, 1200)]
        fills = [fill(Side.BUY, 10, 100), fill(Side.SELL, 10, 120)]
        m = compute(curve, fills)
        self.assertAlmostEqual(m.total_return_pct, 20.0)
        self.assertEqual(m.num_round_trips, 1)
        self.assertEqual(m.win_rate_pct, 100.0)
        self.assertIsNone(m.profit_factor)  # no losing trades

    def test_empty_curve_rejected(self):
        with self.assertRaises(ValueError):
            compute([], [])


if __name__ == "__main__":
    unittest.main()
