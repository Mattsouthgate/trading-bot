"""Simulated broker used for both backtesting and paper trading.

Fill model (chosen to avoid look-ahead bias):

* An order submitted while bar N is the current bar can fill no earlier
  than bar N+1 — you cannot trade on a close you have only just seen.
* Market orders fill at the next bar's open, plus slippage.
* Limit orders fill when the bar's range crosses the limit price; the
  fill price is the better of the limit and the bar open.
* Orders are stamped with the timestamp of the last bar the broker has
  processed and only fill on a strictly later bar — so end-of-period
  information can never trade at that same period's prices, even across
  symbols sharing a timestamp.
* Buys are rejected if they would overdraw cash; sells are rejected if
  they would exceed the held quantity (short selling is not supported).
"""

from __future__ import annotations

from datetime import datetime

from trading_bot.broker.base import Broker
from trading_bot.models import (
    Bar,
    Fill,
    Order,
    OrderStatus,
    OrderType,
    Position,
    Side,
)


class PaperBroker(Broker):
    def __init__(
        self,
        starting_cash: float = 100_000.0,
        *,
        commission_per_trade: float = 0.0,
        slippage_bps: float = 1.0,
        allow_short: bool = False,
    ):
        if starting_cash <= 0:
            raise ValueError("starting_cash must be > 0")
        if allow_short:
            raise NotImplementedError(
                "Short selling accounting is not implemented; allow_short must be False"
            )
        self.starting_cash = starting_cash
        self._cash = starting_cash
        self.commission_per_trade = commission_per_trade
        self.slippage_bps = slippage_bps
        self.allow_short = allow_short
        self._positions: dict[str, Position] = {}
        self._open_orders: dict[int, Order] = {}
        self.fills: list[Fill] = []
        self.rejected: list[Order] = []
        self._now: datetime | None = None  # timestamp of the last processed bar

    # -- Broker interface -------------------------------------------------

    def submit_order(self, order: Order) -> Order:
        if order.status is not OrderStatus.OPEN:
            raise ValueError(f"Cannot submit order in status {order.status}")
        order.submitted_at = self._now
        self._open_orders[order.id] = order
        return order

    def cancel_order(self, order_id: int) -> bool:
        order = self._open_orders.pop(order_id, None)
        if order is None:
            return False
        order.status = OrderStatus.CANCELLED
        return True

    def get_position(self, symbol: str) -> Position:
        return self._positions.get(symbol, Position(symbol=symbol))

    def positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.quantity != 0]

    @property
    def cash(self) -> float:
        return self._cash

    def equity(self, last_prices: dict[str, float]) -> float:
        value = self._cash
        for pos in self._positions.values():
            if pos.quantity == 0:
                continue
            try:
                value += pos.market_value(last_prices[pos.symbol])
            except KeyError:
                raise KeyError(
                    f"equity() needs a last price for open position {pos.symbol!r}"
                ) from None
        return value

    def open_orders(self, symbol: str | None = None) -> list[Order]:
        orders = list(self._open_orders.values())
        if symbol is not None:
            orders = [o for o in orders if o.symbol == symbol]
        return orders

    def process_bar(self, bar: Bar) -> list[Fill]:
        if self._now is None or bar.timestamp > self._now:
            self._now = bar.timestamp
        filled: list[Fill] = []
        for order in list(self._open_orders.values()):
            if order.symbol != bar.symbol:
                continue
            if order.submitted_at is not None and bar.timestamp <= order.submitted_at:
                # Order was placed on information from this period (possibly
                # another symbol's bar) — it may only fill on a later bar.
                continue
            price = self._fill_price(order, bar)
            if price is None:
                continue
            fill = self._execute(order, price, bar)
            if fill is not None:
                filled.append(fill)
        return filled

    # -- internals --------------------------------------------------------

    def _fill_price(self, order: Order, bar: Bar) -> float | None:
        slip = self.slippage_bps / 10_000.0
        if order.order_type is OrderType.MARKET:
            direction = 1 if order.side is Side.BUY else -1
            return bar.open * (1 + direction * slip)
        assert order.limit_price is not None
        if order.side is Side.BUY and bar.low <= order.limit_price:
            return min(bar.open, order.limit_price)
        if order.side is Side.SELL and bar.high >= order.limit_price:
            return max(bar.open, order.limit_price)
        return None

    def _execute(self, order: Order, price: float, bar: Bar) -> Fill | None:
        cost = price * order.quantity
        pos = self._positions.setdefault(order.symbol, Position(symbol=order.symbol))

        if order.side is Side.BUY:
            if cost + self.commission_per_trade > self._cash:
                return self._reject(order, "insufficient cash")
        else:
            if order.quantity > pos.quantity:
                return self._reject(order, "insufficient position (no short selling)")
            if self._cash + cost < self.commission_per_trade:
                return self._reject(order, "insufficient cash for commission")

        if order.side is Side.BUY:
            new_qty = pos.quantity + order.quantity
            if new_qty != 0:
                pos.avg_price = (
                    pos.avg_price * pos.quantity + price * order.quantity
                ) / new_qty
            pos.quantity = new_qty
            self._cash -= cost
        else:
            pos.quantity -= order.quantity
            if pos.quantity == 0:
                pos.avg_price = 0.0
            self._cash += cost
        self._cash -= self.commission_per_trade

        order.status = OrderStatus.FILLED
        del self._open_orders[order.id]
        fill = Fill(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            commission=self.commission_per_trade,
            timestamp=bar.timestamp,
        )
        self.fills.append(fill)
        return fill

    def _reject(self, order: Order, reason: str) -> None:
        order.status = OrderStatus.REJECTED
        order.reason = reason
        del self._open_orders[order.id]
        self.rejected.append(order)
        return None

    # -- persistence (used by the paper trading engine) -------------------

    def to_state(self) -> dict:
        return {
            "starting_cash": self.starting_cash,
            "cash": self._cash,
            "commission_per_trade": self.commission_per_trade,
            "slippage_bps": self.slippage_bps,
            "allow_short": self.allow_short,
            "positions": [
                {"symbol": p.symbol, "quantity": p.quantity, "avg_price": p.avg_price}
                for p in self._positions.values()
                if p.quantity != 0
            ],
            "fills": [
                {
                    "order_id": f.order_id,
                    "symbol": f.symbol,
                    "side": f.side.value,
                    "quantity": f.quantity,
                    "price": f.price,
                    "commission": f.commission,
                    "timestamp": f.timestamp.isoformat(),
                }
                for f in self.fills
            ],
        }

    @classmethod
    def from_state(cls, state: dict) -> "PaperBroker":
        from datetime import datetime

        broker = cls(
            starting_cash=state["starting_cash"],
            commission_per_trade=state["commission_per_trade"],
            slippage_bps=state["slippage_bps"],
            allow_short=state["allow_short"],
        )
        broker._cash = state["cash"]
        for p in state["positions"]:
            broker._positions[p["symbol"]] = Position(
                symbol=p["symbol"], quantity=p["quantity"], avg_price=p["avg_price"]
            )
        for f in state["fills"]:
            broker.fills.append(
                Fill(
                    order_id=f["order_id"],
                    symbol=f["symbol"],
                    side=Side(f["side"]),
                    quantity=f["quantity"],
                    price=f["price"],
                    commission=f["commission"],
                    timestamp=datetime.fromisoformat(f["timestamp"]),
                )
            )
        return broker
