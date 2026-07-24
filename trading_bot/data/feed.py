"""Market data feeds.

A feed is anything iterable that yields ``Bar`` objects in chronological
order. Backtesting iterates a historical feed as fast as possible; paper
trading iterates a live-ish feed that produces one bar per interval.

Feeds never know about brokers or strategies.
"""

from __future__ import annotations

import csv
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from trading_bot.models import Bar


class FeedError(Exception):
    pass


class CSVDataFeed:
    """Reads bars from a CSV file with a header row:

    ``timestamp,open,high,low,close,volume``

    Timestamps must be ISO-8601 and strictly increasing; out-of-order
    rows are rejected rather than silently reordered, because unsorted
    history is almost always a data bug worth surfacing.
    """

    def __init__(self, path: str | Path, symbol: str):
        self.path = Path(path)
        self.symbol = symbol

    def __iter__(self) -> Iterator[Bar]:
        last_ts: datetime | None = None
        with self.path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            required = {"timestamp", "open", "high", "low", "close", "volume"}
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise FeedError(
                    f"{self.path}: CSV header must contain {sorted(required)}, "
                    f"got {reader.fieldnames}"
                )
            for lineno, row in enumerate(reader, start=2):
                try:
                    ts = datetime.fromisoformat(row["timestamp"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    bar = Bar(
                        symbol=self.symbol,
                        timestamp=ts,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                except (ValueError, KeyError) as exc:
                    raise FeedError(f"{self.path}:{lineno}: bad row: {exc}") from exc
                if last_ts is not None and bar.timestamp <= last_ts:
                    raise FeedError(
                        f"{self.path}:{lineno}: timestamps not strictly increasing"
                    )
                last_ts = bar.timestamp
                yield bar


class SyntheticDataFeed:
    """Deterministic geometric random-walk bars, for demos and paper trading.

    With ``realtime=True`` it sleeps ``interval_seconds / speed`` between
    bars, emulating a live market data stream.
    """

    def __init__(
        self,
        symbol: str,
        *,
        start_price: float = 100.0,
        bars: int | None = None,
        interval_seconds: int = 60,
        drift: float = 0.0001,
        volatility: float = 0.004,
        seed: int | None = 42,
        realtime: bool = False,
        speed: float = 60.0,
        start_time: datetime | None = None,
    ):
        if start_price <= 0:
            raise ValueError("start_price must be > 0")
        self.symbol = symbol
        self.start_price = start_price
        self.bars = bars
        self.interval = timedelta(seconds=interval_seconds)
        self.drift = drift
        self.volatility = volatility
        self.seed = seed
        self.realtime = realtime
        self.sleep_seconds = interval_seconds / max(speed, 1e-9)
        self.start_time = start_time

    def __iter__(self) -> Iterator[Bar]:
        rng = random.Random(self.seed)
        price = self.start_price
        ts = self.start_time or datetime.now(timezone.utc)
        produced = 0
        while self.bars is None or produced < self.bars:
            if self.realtime and produced > 0:
                time.sleep(self.sleep_seconds)
            open_px = price
            path = [open_px]
            for _ in range(4):  # a few intra-bar steps to shape high/low
                path.append(path[-1] * (1 + rng.gauss(self.drift, self.volatility)))
            close_px = path[-1]
            yield Bar(
                symbol=self.symbol,
                timestamp=ts,
                open=round(open_px, 4),
                high=round(max(path), 4),
                low=round(min(path), 4),
                close=round(close_px, 4),
                volume=float(rng.randint(1_000, 50_000)),
            )
            price = close_px
            ts += self.interval
            produced += 1
