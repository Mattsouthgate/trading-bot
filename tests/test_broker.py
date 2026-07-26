import unittest

from tests.helpers import make_bar
from trading_bot.broker.paper import PaperBroker
from trading_bot.models import Order, OrderStatus, OrderType, Side


class TestPaperBrokerMarketOrders(unittest.TestCase):
    def setUp(self):
        self.broker = PaperBroker(
            starting_cash=10_000, commission_per_trade=1.0, slippage_bps=0.0
        )

    def test_market_buy_fills_at_next_bar_open(self):
        self.broker.submit_order(Order(symbol="TEST", side=Side.BUY, quantity=10))
        fills = self.broker.process_bar(make_bar(105, open_=101, high=106, low=100))
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].price, 101)  # open, not close
        self.assertEqual(self.broker.get_position("TEST").quantity, 10)
        self.assertAlmostEqual(self.broker.cash, 10_000 - 101 * 10 - 1.0)

    def test_no_fill_without_pending_order(self):
        fills = self.broker.process_bar(make_bar(100))
        self.assertEqual(fills, [])

    def test_slippage_worsens_buy_price(self):
        broker = PaperBroker(starting_cash=10_000, slippage_bps=100)  # 1%
        broker.submit_order(Order(symbol="TEST", side=Side.BUY, quantity=1))
        fills = broker.process_bar(make_bar(100, open_=100))
        self.assertAlmostEqual(fills[0].price, 101.0)

    def test_sell_roundtrip_updates_cash_and_position(self):
        self.broker.submit_order(Order(symbol="TEST", side=Side.BUY, quantity=10))
        self.broker.process_bar(make_bar(100, open_=100, index=0))
        self.broker.submit_order(Order(symbol="TEST", side=Side.SELL, quantity=10))
        self.broker.process_bar(make_bar(110, open_=110, index=1))
        self.assertEqual(self.broker.get_position("TEST").quantity, 0)
        self.assertAlmostEqual(self.broker.cash, 10_000 + 10 * 10 - 2.0)

    def test_buy_rejected_when_insufficient_cash(self):
        self.broker.submit_order(Order(symbol="TEST", side=Side.BUY, quantity=1000))
        fills = self.broker.process_bar(make_bar(100, open_=100))
        self.assertEqual(fills, [])
        self.assertEqual(len(self.broker.rejected), 1)
        self.assertEqual(self.broker.rejected[0].status, OrderStatus.REJECTED)
        self.assertEqual(self.broker.cash, 10_000)

    def test_sell_rejected_when_no_position(self):
        self.broker.submit_order(Order(symbol="TEST", side=Side.SELL, quantity=5))
        fills = self.broker.process_bar(make_bar(100))
        self.assertEqual(fills, [])
        self.assertEqual(self.broker.rejected[0].reason,
                         "insufficient position (no short selling)")

    def test_allow_short_is_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            PaperBroker(starting_cash=10_000, allow_short=True)

    def test_slippage_worsens_sell_price(self):
        broker = PaperBroker(starting_cash=10_000, slippage_bps=100)  # 1%
        broker.submit_order(Order(symbol="TEST", side=Side.BUY, quantity=1))
        broker.process_bar(make_bar(100, open_=100, index=0))
        broker.submit_order(Order(symbol="TEST", side=Side.SELL, quantity=1))
        fills = broker.process_bar(make_bar(100, open_=100, index=1))
        self.assertAlmostEqual(fills[0].price, 99.0)

    def test_sell_rejected_when_commission_exceeds_cash_plus_proceeds(self):
        broker = PaperBroker(
            starting_cash=200, commission_per_trade=150.0, slippage_bps=0
        )
        # Buy 1 @ 10 leaves cash 200 - 10 - 150 = 40.
        broker.submit_order(Order(symbol="TEST", side=Side.BUY, quantity=1))
        broker.process_bar(make_bar(10, open_=10, index=0))
        self.assertAlmostEqual(broker.cash, 40.0)
        # Selling for 10 cannot cover the 150 commission -> reject, cash stays >= 0.
        broker.submit_order(Order(symbol="TEST", side=Side.SELL, quantity=1))
        fills = broker.process_bar(make_bar(10, open_=10, index=1))
        self.assertEqual(fills, [])
        self.assertEqual(broker.rejected[0].reason, "insufficient cash for commission")
        self.assertGreaterEqual(broker.cash, 0)

    def test_no_cross_symbol_same_timestamp_fill(self):
        # Seeing symbol A's bar at time T must not allow a fill on symbol
        # B's bar at the same time T (that would trade end-of-period-T
        # information at period-T prices).
        broker = PaperBroker(starting_cash=100_000, slippage_bps=0)
        broker.process_bar(make_bar(150, symbol="A", index=0))
        broker.submit_order(Order(symbol="B", side=Side.BUY, quantity=10))
        fills_same_ts = broker.process_bar(make_bar(100, symbol="B", index=0))
        self.assertEqual(fills_same_ts, [])
        fills_next = broker.process_bar(
            make_bar(120, symbol="B", open_=110, index=1)
        )
        self.assertEqual(len(fills_next), 1)
        self.assertEqual(fills_next[0].price, 110)

    def test_cancel_order(self):
        order = self.broker.submit_order(Order(symbol="TEST", side=Side.BUY, quantity=1))
        self.assertTrue(self.broker.cancel_order(order.id))
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(self.broker.process_bar(make_bar(100)), [])
        self.assertFalse(self.broker.cancel_order(order.id))

    def test_orders_for_other_symbols_untouched(self):
        self.broker.submit_order(Order(symbol="OTHER", side=Side.BUY, quantity=1))
        fills = self.broker.process_bar(make_bar(100, symbol="TEST"))
        self.assertEqual(fills, [])
        self.assertEqual(len(self.broker.open_orders()), 1)


class TestPaperBrokerLimitOrders(unittest.TestCase):
    def setUp(self):
        self.broker = PaperBroker(starting_cash=10_000, slippage_bps=0.0)

    def test_limit_buy_waits_for_price(self):
        self.broker.submit_order(
            Order(symbol="TEST", side=Side.BUY, quantity=10,
                  order_type=OrderType.LIMIT, limit_price=95)
        )
        # Bar never trades down to 95 -> no fill.
        self.assertEqual(
            self.broker.process_bar(make_bar(100, open_=100, low=98, high=101)), []
        )
        # Bar dips to 94 -> fills at the limit (open was above it).
        fills = self.broker.process_bar(
            make_bar(96, open_=99, low=94, high=99, index=1)
        )
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].price, 95)

    def test_limit_buy_gets_price_improvement_on_gap(self):
        self.broker.submit_order(
            Order(symbol="TEST", side=Side.BUY, quantity=1,
                  order_type=OrderType.LIMIT, limit_price=95)
        )
        # Gap down open at 90 -> better than limit.
        fills = self.broker.process_bar(make_bar(92, open_=90, low=89, high=93))
        self.assertEqual(fills[0].price, 90)

    def test_limit_sell_fills_when_high_crosses(self):
        self.broker.submit_order(Order(symbol="TEST", side=Side.BUY, quantity=5))
        self.broker.process_bar(make_bar(100, open_=100))
        self.broker.submit_order(
            Order(symbol="TEST", side=Side.SELL, quantity=5,
                  order_type=OrderType.LIMIT, limit_price=110)
        )
        self.assertEqual(
            self.broker.process_bar(make_bar(105, open_=105, high=108, index=1)), []
        )
        fills = self.broker.process_bar(
            make_bar(109, open_=107, high=112, low=106, index=2)
        )
        self.assertEqual(fills[0].price, 110)


class TestPaperBrokerState(unittest.TestCase):
    def test_state_roundtrip(self):
        broker = PaperBroker(starting_cash=50_000, commission_per_trade=2.0)
        broker.submit_order(Order(symbol="TEST", side=Side.BUY, quantity=10))
        broker.process_bar(make_bar(100, open_=100))

        restored = PaperBroker.from_state(broker.to_state())
        self.assertAlmostEqual(restored.cash, broker.cash)
        self.assertEqual(restored.get_position("TEST").quantity, 10)
        self.assertEqual(len(restored.fills), 1)
        self.assertEqual(restored.fills[0].side, Side.BUY)

    def test_equity_requires_price_for_open_position(self):
        broker = PaperBroker(starting_cash=10_000)
        broker.submit_order(Order(symbol="TEST", side=Side.BUY, quantity=10))
        broker.process_bar(make_bar(100, open_=100))
        with self.assertRaises(KeyError):
            broker.equity({})
        self.assertAlmostEqual(
            broker.equity({"TEST": 110}), broker.cash + 1100
        )


if __name__ == "__main__":
    unittest.main()
