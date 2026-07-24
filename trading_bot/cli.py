"""Command-line interface.

    python -m trading_bot backtest --data data/sample/DEMO.csv --strategy sma
    python -m trading_bot paper --strategy sma --bars 200 --speed 600
    python -m trading_bot generate-data --out data/sample/DEMO.csv --bars 500
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from trading_bot import strategies
from trading_bot.broker.paper import PaperBroker
from trading_bot.data.feed import CSVDataFeed, SyntheticDataFeed
from trading_bot.engine import backtest
from trading_bot.engine.paper import PaperTradingEngine
from trading_bot.risk import DrawdownGuard


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--strategy", default="sma", choices=sorted(strategies.STRATEGIES))
    parser.add_argument("--cash", type=float, default=100_000.0, help="starting cash")
    parser.add_argument("--commission", type=float, default=1.0, help="per-trade commission")
    parser.add_argument("--slippage-bps", type=float, default=1.0)
    parser.add_argument(
        "--max-drawdown",
        type=float,
        default=0.25,
        help="liquidate and halt when equity drops this fraction from its peak (0 disables)",
    )


def _build(args) -> tuple[PaperBroker, object, DrawdownGuard | None]:
    broker = PaperBroker(
        starting_cash=args.cash,
        commission_per_trade=args.commission,
        slippage_bps=args.slippage_bps,
    )
    strategy = strategies.build(args.strategy)
    guard = DrawdownGuard(args.max_drawdown) if args.max_drawdown > 0 else None
    return broker, strategy, guard


def cmd_backtest(args) -> int:
    broker, strategy, guard = _build(args)
    feed = CSVDataFeed(args.data, symbol=args.symbol)
    result = backtest.run(feed, strategy, broker, guard=guard)
    print(f"Backtest: {strategy.describe()} on {args.data} ({result.bars_processed} bars)")
    print("-" * 44)
    for line in result.metrics.as_lines():
        print(line)
    if result.rejected:
        print(f"Rejected orders : {len(result.rejected)} (first: {result.rejected[0].reason})")
    if result.guard_tripped:
        print("NOTE: drawdown guard tripped — trading halted and position liquidated.")
    return 0


def cmd_paper(args) -> int:
    broker, strategy, guard = _build(args)
    state_path = Path(args.state)
    broker = PaperTradingEngine.load_broker(state_path, broker)
    feed = SyntheticDataFeed(
        args.symbol,
        start_price=args.start_price,
        bars=args.bars,
        interval_seconds=args.interval,
        seed=args.seed,
        realtime=not args.no_realtime,
        speed=args.speed,
    )
    engine = PaperTradingEngine(
        feed, strategy, broker, state_path=state_path, guard=guard
    )
    print(
        f"Paper trading {strategy.describe()} on synthetic {args.symbol} "
        f"({args.interval}s bars at {args.speed}x speed). Ctrl-C to stop."
    )
    engine.run(max_bars=args.bars)
    return 0


def cmd_generate_data(args) -> int:
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    feed = SyntheticDataFeed(
        "GEN",
        start_price=args.start_price,
        bars=args.bars,
        interval_seconds=args.interval,
        seed=args.seed,
        start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    with out.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for bar in feed:
            writer.writerow(
                [
                    bar.timestamp.isoformat(),
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    int(bar.volume),
                ]
            )
    print(f"Wrote {args.bars} bars to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading_bot")
    sub = parser.add_subparsers(dest="command", required=True)

    p_back = sub.add_parser("backtest", help="run a strategy over a historical CSV")
    p_back.add_argument("--data", required=True, help="CSV file of OHLCV bars")
    p_back.add_argument("--symbol", default="DEMO")
    _add_common(p_back)
    p_back.set_defaults(func=cmd_backtest)

    p_paper = sub.add_parser("paper", help="paper-trade a strategy on a simulated live feed")
    p_paper.add_argument("--symbol", default="DEMO")
    p_paper.add_argument("--bars", type=int, default=None, help="stop after N bars (default: run until Ctrl-C)")
    p_paper.add_argument("--interval", type=int, default=60, help="bar interval in seconds")
    p_paper.add_argument("--speed", type=float, default=60.0, help="time acceleration factor")
    p_paper.add_argument("--no-realtime", action="store_true", help="emit bars without sleeping")
    p_paper.add_argument("--start-price", type=float, default=100.0)
    p_paper.add_argument("--seed", type=int, default=None, help="RNG seed (default: random)")
    p_paper.add_argument("--state", default=".paper/state.json", help="session state file")
    _add_common(p_paper)
    p_paper.set_defaults(func=cmd_paper)

    p_gen = sub.add_parser("generate-data", help="write a deterministic sample OHLCV CSV")
    p_gen.add_argument("--out", required=True)
    p_gen.add_argument("--bars", type=int, default=500)
    p_gen.add_argument("--interval", type=int, default=86400, help="bar interval in seconds")
    p_gen.add_argument("--start-price", type=float, default=100.0)
    p_gen.add_argument("--seed", type=int, default=42)
    p_gen.set_defaults(func=cmd_generate_data)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
