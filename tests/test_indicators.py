import unittest

from trading_bot.indicators import RSI, SMA


class TestSMA(unittest.TestCase):
    def test_returns_none_until_warm(self):
        sma = SMA(3)
        self.assertIsNone(sma.update(1))
        self.assertIsNone(sma.update(2))
        self.assertEqual(sma.update(3), 2.0)

    def test_rolls_window(self):
        sma = SMA(3)
        for v in (1, 2, 3):
            sma.update(v)
        self.assertEqual(sma.update(4), 3.0)
        self.assertEqual(sma.update(7), (3 + 4 + 7) / 3)

    def test_period_one_tracks_input(self):
        sma = SMA(1)
        self.assertEqual(sma.update(5), 5.0)
        self.assertEqual(sma.update(9), 9.0)

    def test_rejects_bad_period(self):
        with self.assertRaises(ValueError):
            SMA(0)


class TestRSI(unittest.TestCase):
    def test_warmup_length(self):
        rsi = RSI(14)
        values = [rsi.update(float(i)) for i in range(15)]
        self.assertTrue(all(v is None for v in values[:14]))
        self.assertIsNotNone(values[14])

    def test_all_gains_is_100(self):
        rsi = RSI(3)
        out = None
        for v in (1, 2, 3, 4, 5):
            out = rsi.update(v)
        self.assertEqual(out, 100.0)

    def test_all_losses_is_0(self):
        rsi = RSI(3)
        out = None
        for v in (5, 4, 3, 2, 1):
            out = rsi.update(v)
        self.assertAlmostEqual(out, 0.0)

    def test_mixed_moves_bounded(self):
        rsi = RSI(3)
        out = None
        for v in (10, 11, 10.5, 11.5, 10.8, 11.2):
            out = rsi.update(v)
        self.assertIsNotNone(out)
        self.assertTrue(0 < out < 100)

    def test_matches_batch_wilder_reference(self):
        # Independent (non-streaming) Wilder RSI, to pin the smoothing
        # arithmetic against regressions.
        def reference(prices, period):
            changes = [b - a for a, b in zip(prices, prices[1:])]
            gains = [max(c, 0.0) for c in changes]
            losses = [max(-c, 0.0) for c in changes]
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period
            for g, l in zip(gains[period:], losses[period:]):
                avg_gain = (avg_gain * (period - 1) + g) / period
                avg_loss = (avg_loss * (period - 1) + l) / period
            if avg_loss == 0:
                return 100.0
            return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

        prices = [44.0, 44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10,
                  45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28,
                  46.00, 46.03, 46.41, 46.22, 45.64]
        for period in (5, 14):
            streaming = RSI(period)
            out = None
            for p in prices:
                out = streaming.update(p)
            self.assertAlmostEqual(out, reference(prices, period), places=10)


if __name__ == "__main__":
    unittest.main()
