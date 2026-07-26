# trading-bot

A small, dependency-free trading framework with a **backtesting engine** and a
**paper trading engine** that share the same event loop, broker simulation and
strategy interface — so a strategy validated on historical data runs unchanged
in (simulated) live mode.

Requires Python 3.10+. No third-party packages.

## Quick start

```bash
# 1. Generate a deterministic sample price history (500 daily bars)
python -m trading_bot generate-data --out data/sample/DEMO.csv --bars 500

# 2. Backtest a strategy against it
python -m trading_bot backtest --data data/sample/DEMO.csv --strategy sma
python -m trading_bot backtest --data data/sample/DEMO.csv --strategy rsi

# 3. Paper trade on a simulated live feed (1-minute bars at 60x speed)
python -m trading_bot paper --strategy sma --speed 60
#    ... Ctrl-C to stop; the session persists to .paper/state.json and
#    resumes from there next time (cash, positions, fill log, drawdown-guard
#    state and the halt flag all carry over; a tripped guard stays tripped
#    until you delete the state file). Add --bars 100 to auto-stop.

# Run the test suite
python -m unittest discover -s tests
```

Backtest output looks like:

```
Backtest: sma(fast=10, slow=30) on data/sample/DEMO.csv (500 bars)
--------------------------------------------
Starting equity : 100,000.00
Final equity    : 97,037.94
Total return    : -2.96%
Max drawdown    : 16.45%
Sharpe (per-bar): -0.01
Fills           : 21
Round trips     : 10
Win rate        : 40.00%
Profit factor   : 0.68
```

## Using your own data

`backtest --data` accepts any CSV with the header
`timestamp,open,high,low,close,volume` (ISO-8601 timestamps, strictly
increasing). Export daily bars from your data provider in that shape and point
the backtester at the file.

## Built-in strategies

| Name  | Idea                                                    | Parameters (defaults)                  |
|-------|---------------------------------------------------------|----------------------------------------|
| `sma` | Trend following: long while fast SMA is above slow SMA  | fast=10, slow=30                       |
| `rsi` | Mean reversion: buy oversold, exit on recovery          | period=14, oversold=30, exit_level=55  |

Both use a common position sizer (95% of equity per entry) and an optional
drawdown guard (`--max-drawdown`, default 0.25) that liquidates and halts
trading if equity falls 25% from its peak.

## Writing a strategy

Subclass `Strategy`, place orders through the `Broker` interface, and register
it in `trading_bot/strategies/__init__.py`:

```python
from trading_bot.models import Bar, Order, Side
from trading_bot.strategies.base import Strategy

class MyStrategy(Strategy):
    name = "mine"

    def on_bar(self, bar: Bar, broker) -> None:
        if broker.get_position(bar.symbol).quantity == 0 and self.should_buy(bar):
            broker.submit_order(Order(symbol=bar.symbol, side=Side.BUY, quantity=10))
```

Orders placed on bar *N* fill no earlier than bar *N+1*'s open (market orders)
or when price crosses the limit (limit orders) — the framework will not let a
strategy trade on a close it has only just observed. This holds across
symbols too: the broker stamps each order with the timestamp of the last bar
it processed and only fills on a strictly later bar, so seeing symbol A's
close cannot buy symbol B at that same period's prices.

## How fills are simulated

* Market orders fill at the **next bar's open** plus slippage (`--slippage-bps`).
* Limit orders fill when the bar range crosses the limit, at the better of the
  limit price and the bar open (gap price improvement).
* A flat per-trade commission (`--commission`) is charged on every fill, and
  round-trip PnL (win rate, profit factor) is net of commissions on both the
  entry and the exit.
* Buys that would overdraw cash and sells exceeding the held quantity are
  rejected. Short selling is not supported (`allow_short=True` raises
  `NotImplementedError` rather than producing wrong accounting).

## Project layout

```
trading_bot/
├── models.py            # Bar, Order, Fill, Position — shared value objects
├── indicators.py        # streaming SMA, RSI
├── risk.py              # position sizing, drawdown guard
├── metrics.py           # return, drawdown, Sharpe, win rate, profit factor
├── data/feed.py         # CSVDataFeed (historical), SyntheticDataFeed (live-ish)
├── broker/
│   ├── base.py          # Broker interface strategies code against
│   └── paper.py         # simulated fills, cash/position accounting, state I/O
├── strategies/          # sma_crossover, rsi_reversion + registry
├── engine/
│   ├── backtest.py      # event loop + result/metrics assembly
│   └── paper.py         # same loop over a live feed, with state persistence
└── cli.py               # backtest / paper / generate-data commands
tests/                   # 64 unit + integration tests (stdlib unittest)
docs/ARCHITECTURE.md     # structure evaluation & maintenance guide
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design rationale,
an honest assessment of current limitations, and the recommended path to
real-market data and live brokers.

## Disclaimer

This is a research/education tool. The paper broker is a simplified model of
market microstructure; nothing here is investment advice, and no real orders
are ever placed.
