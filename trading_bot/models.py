"""Core value objects shared by every layer of the system.

These are deliberately plain dataclasses with no behaviour beyond
validation, so that feeds, brokers, strategies and engines can exchange
them without depending on each other.
"""

from __future__ import annotations

import enum
import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone


class Side(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, enum.Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, enum.Enum):
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Bar:
    """One OHLCV candle for a symbol."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError(f"Bar low {self.low} > high {self.high}")
        for name in ("open", "close"):
            px = getattr(self, name)
            if not (self.low <= px <= self.high):
                raise ValueError(f"Bar {name} {px} outside [low, high]")
        if self.volume < 0:
            raise ValueError("Bar volume must be >= 0")


_order_ids = itertools.count(1)


@dataclass
class Order:
    symbol: str
    side: Side
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    id: int = field(default_factory=lambda: next(_order_ids))
    status: OrderStatus = OrderStatus.OPEN
    reason: str = ""

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("Order quantity must be > 0")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("Limit order requires limit_price")


@dataclass(frozen=True)
class Fill:
    order_id: int
    symbol: str
    side: Side
    quantity: float
    price: float
    commission: float
    timestamp: datetime


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0

    def market_value(self, price: float) -> float:
        return self.quantity * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.avg_price) * self.quantity


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
