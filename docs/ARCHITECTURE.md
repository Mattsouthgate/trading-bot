# Architecture & Structure Evaluation

This document does two jobs: it records the design decisions behind the
codebase, and it evaluates the structure honestly — strengths, current
limitations, and what to do next — so future maintenance decisions have
context instead of folklore.

## 1. Starting point

The repository previously contained no code (a bare README and LICENSE), so
there was no legacy structure to preserve. The layout below was designed from
scratch around the stated goals: working backtesting ("back checking"), working
paper trading, and long-term stability and maintainability.

## 2. Design principles

**One event loop, two modes.** The single most common failure in hobby trading
systems is a backtester and a live engine that drift apart until backtest
results say nothing about live behaviour. Here both engines call the same
`run_bar()` function (`trading_bot/engine/backtest.py`), which fixes the
per-bar sequence: fill pending orders → let the strategy react → mark equity →
check the drawdown guard. The paper engine adds only pacing, printing and
persistence. Any change to trading semantics automatically applies to both.

**No look-ahead by construction.** Orders submitted while observing bar *N*
cannot fill before bar *N+1*. Two mechanisms enforce this in the broker, not
by strategy discipline: fills only happen inside `process_bar`, which runs
*before* the strategy sees the bar; and every order is stamped at submission
with the timestamp of the last bar the broker processed, and may only fill on
a bar with a strictly later timestamp. The stamp is what closes the
cross-symbol hole (found by independent audit): without it, seeing symbol A's
close at time T could fill an order on symbol B's bar at the same time T.

**Strict layering, dependencies point inward.**

```
cli ──▶ engine ──▶ strategy ──▶ broker interface ──▶ models
              └──▶ feed ─────────────────────────┘
```

* `models.py` depends on nothing.
* Feeds yield `Bar`s and know nothing about brokers or strategies.
* Strategies see only the `Broker` ABC, never `PaperBroker` specifics.
* Engines wire the pieces together; the CLI only parses arguments and calls
  engines.

This is what makes the parts replaceable: a real broker adapter, a real data
feed, or a new strategy each touch exactly one layer.

**Zero third-party dependencies.** Everything uses the Python standard library
(`dataclasses`, `csv`, `json`, `unittest`). For a project meant to still build
in five years, no dependency churn is a bigger stability win than pandas
convenience. The cost — hand-rolled indicators and metrics — is contained in
two small, heavily tested modules. If numeric ambitions grow, add numpy behind
`indicators.py`/`metrics.py` without touching their interfaces.

**Determinism everywhere it matters.** The synthetic feed is seeded, sample
data generation is seeded and pinned to a fixed start date, and the engine
introduces no randomness of its own. Identical inputs give identical results,
which makes regressions detectable by tests rather than by eyeballing P&L.

**Fail loudly on bad data.** The CSV feed rejects missing columns, malformed
rows, invalid OHLC relationships and out-of-order timestamps instead of
soldiering on. Silent data corruption is the classic source of "the backtest
said +40%" disasters.

## 3. Module responsibilities

| Module | Responsibility | Must NOT know about |
|---|---|---|
| `models.py` | Validated value objects (Bar, Order, Fill, Position) | everything else |
| `data/feed.py` | Produce chronological `Bar`s | brokers, strategies |
| `indicators.py` | Streaming SMA/RSI state machines | bars, orders |
| `broker/base.py` | The interface strategies code against | concrete simulators |
| `broker/paper.py` | Fill simulation, cash/position accounting, state (de)serialisation | strategies, engines |
| `risk.py` | Position sizing, drawdown guard | signal logic |
| `strategies/*` | Turn bars into orders via the broker interface | feeds, engines, concrete brokers |
| `engine/backtest.py` | The canonical per-bar sequence + result assembly | CLI concerns |
| `engine/paper.py` | Same loop with pacing, reporting, persistence | fill mechanics |
| `metrics.py` | Pure functions from equity curve + fills to statistics | live state |
| `cli.py` | Argument parsing and wiring only | trading semantics |

A useful review heuristic for future PRs: if a diff violates the "must not know
about" column, the layering is eroding.

## 4. Key mechanics worth knowing

* **Fill model** — market orders fill at next open ± slippage (bps); limit
  orders fill when the bar range crosses the limit, at the better of limit and
  open (gap price improvement). Flat commission per fill. Buys are rejected on
  insufficient cash, sells on insufficient position (no shorting by default).
* **Paper persistence** — session state is written atomically
  (`write temp + rename`) to JSON after every bar: broker state (cash,
  positions, fill log), the drawdown guard's peak/tripped state, the halted
  flag, and the order-id counter. A tripped guard therefore stays tripped
  across restarts, and fill ids stay unique. What is *not* persisted:
  strategy indicator state, which re-warms from live bars on resume —
  strategies only enter when flat so a held position is never doubled, but an
  exit signal can be missed until indicators are warm again. Resuming also
  ignores `--cash/--commission/--slippage-bps` (the saved session's settings
  win); the CLI says so explicitly, and refuses to resume a session whose
  held positions don't match the feed's symbol.
* **Drawdown guard** — portfolio-level kill switch: at N% below peak equity it
  cancels open orders, liquidates every position, and halts the strategy for
  the rest of the run. Latching, including across process restarts (the
  tripped state is persisted) — restarting after a blowout is a human
  decision, made by deleting the state file. Caveat: liquidation is a market
  order for the next bar, so a guard trip on the *final* bar of a backtest
  leaves the position open; the CLI reports this case distinctly.
* **Metrics** — Sharpe is reported *per bar* and unannualised because the
  framework doesn't assume a bar interval; compare runs at the same interval.
  Round trips are FIFO-matched per symbol, net of commissions on both sides
  (entry commission is carried per-lot and charged pro-rata as lots close).
* **Short selling is not supported.** `allow_short=True` raises
  `NotImplementedError` at construction rather than silently producing wrong
  accounting (short avg-price, cover PnL and guard liquidation would all need
  dedicated handling that does not exist yet).

## 5. Honest assessment for long-term maintenance

### Strengths

1. **Small surface area.** ~1,200 lines of library code; a new maintainer can
   read the whole thing in an hour. This is the single best predictor of a
   side-project surviving.
2. **The invariants are enforced structurally**, not by convention: no
   look-ahead (broker fill timing), no engine drift (shared `run_bar`), no
   silent bad data (validating feed), no torn state files (atomic writes).
3. **64 fast, deterministic tests** covering fill timing, rejection paths,
   limit-order edge cases, state round-tripping, guard liquidation, metric
   values against hand-computed numbers, and CLI end-to-end smoke tests.
   The suite runs in well under a second, so there is no excuse not to run it.
4. **Zero dependencies** — nothing to pin, upgrade, or get CVE-paged about.

### Limitations and risks (current, known, accepted)

1. **No real market data or real broker yet.** Paper trading runs on a
   synthetic random walk. This is the right first milestone (the plumbing is
   proven end-to-end) but results carry no information about real markets.
   The seams to fix this already exist: implement a feed that yields `Bar`s
   from a data API, and later a `Broker` implementation against a broker's
   paper API. Nothing else changes.
2. **Float arithmetic for money.** Fine for simulation; not fine if this ever
   routes real orders. Before any real-broker adapter, migrate cash/position
   accounting in `broker/paper.py` to `decimal.Decimal` (the tests pin current
   behaviour, which makes that migration safe).
3. **Effectively single-symbol at the CLI.** The broker, fill timing
   (including cross-symbol timestamp checks) and guard liquidation all handle
   multiple symbols, but the CLI wires exactly one feed. Multi-symbol trading
   needs a feed multiplexer and multi-feed CLI plumbing.
4. **Simplified microstructure.** No partial fills, order book depth, volume
   limits, borrow costs, or overnight gaps modelling. Every backtest is
   optimistic to some degree; treat results as relative strategy comparisons,
   not absolute P&L forecasts.
5. **Strategy indicator state is not persisted across paper restarts.**
   Indicators re-warm from live bars, so a resumed session is briefly
   signal-blind (it cannot enter — it only enters when flat and warm — but it
   can be late to exit a held position). Fixing this properly means a
   `Strategy.to_state()/from_state()` protocol; do it when a real-money
   adapter makes it matter.
6. **The persistence protocol is `PaperBroker`-specific.** The `Broker` ABC
   now covers everything the engines call during trading (`open_orders`,
   `positions`, etc.), so a real adapter drops into the *event loop*
   unchanged — but `to_state`/`from_state` live on `PaperBroker`, so session
   persistence would need a small state protocol on the ABC (or become a
   no-op for a broker that holds its own state server-side).
7. **Strategy parameters are code-level defaults.** The CLI can select a
   strategy but not yet pass, e.g., `--fast 5 --slow 20`. Add per-strategy
   argparse groups or a small config file when tuning becomes routine —
   resist the temptation to grow a config framework before then.
8. **`print`-based reporting.** Adequate at this size; switch to the stdlib
   `logging` module when a real feed introduces retries/timeouts worth
   diagnosing after the fact.

### Recommended roadmap (in order)

1. **Real historical data** — a small fetcher that downloads daily OHLCV to
   CSV (the backtester already consumes it; no engine changes).
2. **Strategy parameters via CLI/config**, so tuning doesn't require edits.
3. **Decimal money types** in the broker (prerequisite for anything real).
4. **Live paper feed adapter** (polling a quote API) — drops into
   `PaperTradingEngine` unchanged.
5. **Real broker paper API adapter** (e.g. a brokerage's sandbox) as a second
   `Broker` implementation — the interface is already the contract.
6. Only after all of the above: multi-symbol portfolios and richer fill
   modelling.

### Maintenance ground rules

* Every behaviour change lands with a test; the suite must stay under a few
  seconds so it is always run.
* New strategies register in `strategies/__init__.py` and touch nothing else.
* Keep `models.py` dependency-free and keep dependencies pointing inward
  (see the table in §3).
* CI (GitHub Actions) runs the suite on every push across supported Python
  versions; keep it green.

## 6. Audit record

**2026-07-24 — independent adversarial audit** of the initial implementation
(a separate agent, read-only, with reproduction scripts required for every
claimed bug). Verified findings and their resolutions, kept here because
knowing *why* code is shaped a certain way is half of maintenance:

| Finding | Severity | Resolution |
|---|---|---|
| Cross-symbol look-ahead: order placed on A@T could fill on B@T | major | Orders stamped with submission time; fills require a strictly later bar (`broker/paper.py`), regression test added |
| Paper restart silently un-tripped the drawdown guard and re-entered the market | major | Guard peak/tripped + halted flag persisted in session state; CLI announces a halted session; test pins it |
| Round-trip PnL ignored buy-side commission, inflating win rate / profit factor | major | Per-lot pro-rata entry commission in `metrics.round_trips`; tests fixed (one had pinned the bug) |
| `allow_short=True` produced broken accounting (avg-price, cover PnL, guard skip) | major | Now raises `NotImplementedError` until properly implemented |
| Order ids restarted at 1 per process, duplicating ids in the persisted fill log | minor | Order-id counter persisted and fast-forwarded on resume |
| Resume with a different `--symbol` crashed with `KeyError`; CLI flags silently ignored on resume | minor | Friendly startup validation + explicit resume notice |
| Guard liquidation only flattened the current bar's symbol | minor | Liquidates all positions via new `Broker.positions()` |
| Sell commission could overdraw cash | minor | Sells rejected when commission exceeds cash + proceeds |
| "Liquidated" printed even when the guard tripped on the final bar (order never filled) | minor | CLI distinguishes the liquidation-pending case |
| Engine called `PaperBroker`-only methods, weakening the "adapter drops in" claim | minor | `open_orders()`/`positions()` added to the `Broker` ABC; remaining gap (state protocol) documented in §5 |

Also from the audit: test gaps closed (sell-side slippage, duplicate CSV
timestamps, RSI vs. an independent Wilder reference, resumed-engine
behaviour), and the docs claims corrected above. Suite grew from 54 to 64
tests. Non-findings worth recording: SMA rolling-sum drift measured
negligible (~5e-8 after 2M updates), limit-order fill logic, slippage
directions, drawdown/Sharpe math and atomic state writes all verified
correct.
