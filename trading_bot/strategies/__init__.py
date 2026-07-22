"""Strategy registry.

New strategies register themselves here so the CLI can discover them by
name without the engine knowing about concrete classes.
"""

from __future__ import annotations

from trading_bot.strategies.base import Strategy
from trading_bot.strategies.rsi_reversion import RSIReversion
from trading_bot.strategies.sma_crossover import SMACrossover

STRATEGIES: dict[str, type[Strategy]] = {
    "sma": SMACrossover,
    "rsi": RSIReversion,
}


def build(name: str, **params) -> Strategy:
    try:
        cls = STRATEGIES[name]
    except KeyError:
        raise ValueError(
            f"Unknown strategy {name!r}; available: {', '.join(sorted(STRATEGIES))}"
        ) from None
    return cls(**params)
