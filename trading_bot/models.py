"""Core value objects shared by every layer of the system.

These are deliberately plain dataclasses with no behaviour beyond
validation, so that feeds, brokers, strategies and engines can exchange
them without depending on each other.
"""

from __future__ import annotations

import enum
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


class _OrderIdGenerator:
    """Monotonic order-id source that can be fast-forwarded on session
    resume so ids stay unique across process restarts."""

    def __init__(self, start: int = 1):
        self._next = start

    def __call__(self) -> int:
        value = self._next
        self._next += 1
        return value

    def peek(self) -> int:
        return self._next

    def ensure_at_least(self, value: int) -> None:
        self._next = max(self._next, value)


_order_ids = _OrderIdGenerator()


def peek_next_order_id() -> int:
    return _order_ids.peek()


def ensure_order_ids_at_least(value: int) -> None:
    _order_ids.ensure_at_least(value)


@dataclass
class Order:
    symbol: str
    side: Side
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    id: int = field(default_factory=_order_ids)
    status: OrderStatus = OrderStatus.OPEN
    reason: str = ""
    # Stamped by the broker on submission with the timestamp of the last
    # bar it has processed; fills require a strictly later bar, which is
    # what prevents look-ahead even across symbols sharing a timestamp.
    submitted_at: datetime | None = None

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
