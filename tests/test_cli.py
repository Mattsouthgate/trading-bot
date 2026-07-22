import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from trading_bot.cli import main


class TestCLI(unittest.TestCase):
    def test_generate_then_backtest(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = str(Path(tmp) / "demo.csv")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = main(["generate-data", "--out", csv_path, "--bars", "200"])
            self.assertEqual(rc, 0)

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = main(["backtest", "--data", csv_path, "--strategy", "sma"])
            self.assertEqual(rc, 0)
            self.assertIn("Final equity", out.getvalue())

    def test_paper_session_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = str(Path(tmp) / "state.json")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = main([
                    "paper", "--bars", "30", "--no-realtime",
                    "--seed", "5", "--state", state,
                ])
            self.assertEqual(rc, 0)
            self.assertIn("Paper trading session summary", out.getvalue())
            self.assertTrue(Path(state).exists())


if __name__ == "__main__":
    unittest.main()
