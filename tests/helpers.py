from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trading_bot.models import Bar

T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def make_bar(
    close: float,
    *,
    index: int = 0,
    symbol: str = "TEST",
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: float = 1000.0,
) -> Bar:
    open_ = close if open_ is None else open_
    high = max(open_, close) if high is None else high
    low = min(open_, close) if low is None else low
    return Bar(
        symbol=symbol,
        timestamp=T0 + timedelta(days=index),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def make_series(closes: list[float], symbol: str = "TEST") -> list[Bar]:
    bars = []
    prev = closes[0]
    for i, close in enumerate(closes):
        bars.append(
            make_bar(
                close,
                index=i,
                symbol=symbol,
                open_=prev,
                high=max(prev, close),
                low=min(prev, close),
            )
        )
        prev = close
    return bars
