import tempfile
import unittest
from pathlib import Path

from trading_bot.data.feed import CSVDataFeed, FeedError, SyntheticDataFeed


class TestCSVDataFeed(unittest.TestCase):
    def _write(self, content: str) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".csv", delete=False, dir=tempfile.gettempdir()
        )
        tmp.write(content)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return Path(tmp.name)

    def test_reads_valid_file(self):
        path = self._write(
            "timestamp,open,high,low,close,volume\n"
            "2025-01-01T00:00:00+00:00,100,102,99,101,5000\n"
            "2025-01-02T00:00:00+00:00,101,103,100,102,6000\n"
        )
        bars = list(CSVDataFeed(path, "TEST"))
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].close, 101)
        self.assertEqual(bars[1].symbol, "TEST")

    def test_rejects_missing_columns(self):
        path = self._write("timestamp,close\n2025-01-01,100\n")
        with self.assertRaises(FeedError):
            list(CSVDataFeed(path, "TEST"))

    def test_rejects_duplicate_timestamps(self):
        path = self._write(
            "timestamp,open,high,low,close,volume\n"
            "2025-01-01T00:00:00+00:00,100,102,99,101,5000\n"
            "2025-01-01T00:00:00+00:00,101,103,100,102,6000\n"
        )
        with self.assertRaises(FeedError):
            list(CSVDataFeed(path, "TEST"))

    def test_rejects_out_of_order_timestamps(self):
        path = self._write(
            "timestamp,open,high,low,close,volume\n"
            "2025-01-02T00:00:00+00:00,100,102,99,101,5000\n"
            "2025-01-01T00:00:00+00:00,101,103,100,102,6000\n"
        )
        with self.assertRaises(FeedError):
            list(CSVDataFeed(path, "TEST"))

    def test_rejects_bad_ohlc(self):
        path = self._write(
            "timestamp,open,high,low,close,volume\n"
            "2025-01-01T00:00:00+00:00,100,99,100,100,5000\n"  # high < low
        )
        with self.assertRaises(FeedError):
            list(CSVDataFeed(path, "TEST"))

    def test_naive_timestamps_get_utc(self):
        path = self._write(
            "timestamp,open,high,low,close,volume\n"
            "2025-01-01T00:00:00,100,102,99,101,5000\n"
        )
        bars = list(CSVDataFeed(path, "TEST"))
        self.assertIsNotNone(bars[0].timestamp.tzinfo)


class TestSyntheticDataFeed(unittest.TestCase):
    def test_deterministic_with_seed(self):
        a = list(SyntheticDataFeed("X", bars=50, seed=7))
        b = list(SyntheticDataFeed("X", bars=50, seed=7))
        self.assertEqual([bar.close for bar in a], [bar.close for bar in b])

    def test_bars_are_valid_and_continuous(self):
        bars = list(SyntheticDataFeed("X", bars=100, seed=1))
        self.assertEqual(len(bars), 100)
        for prev, cur in zip(bars, bars[1:]):
            self.assertGreater(cur.timestamp, prev.timestamp)
            self.assertEqual(cur.open, prev.close)  # no gaps in the walk
            self.assertLessEqual(cur.low, cur.high)


if __name__ == "__main__":
    unittest.main()
