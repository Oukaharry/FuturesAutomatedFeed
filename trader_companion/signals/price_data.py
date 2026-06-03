"""
Cached MT5 OHLC access for signal indicators.

Prefer M1 bars from MT5MarketFeed (60s refresh). Falls back to direct MT5 API.
"""

from __future__ import annotations

import logging
from typing import Optional

import MetaTrader5 as mt5

logger = logging.getLogger(__name__)

# Saved before trader_app patches mt5.copy_rates_from_pos (feed/sync must use this).
_copy_rates_from_pos = mt5.copy_rates_from_pos


def copy_rates_from_pos_raw(symbol: str, timeframe: int, start_pos: int, count: int):
    """Direct MT5 API — use from feed poller and dashboard sync (never the cache wrapper)."""
    return _copy_rates_from_pos(symbol, timeframe, start_pos, count)


def copy_rates_from_pos_cached(symbol: str, timeframe: int, start_pos: int, count: int):
    """
    Drop-in for mt5.copy_rates_from_pos with M1 cache when feed is running.

    Only caches start_pos==0 and TIMEFRAME_M1. Other timeframes hit MT5 directly.
    """
    if start_pos != 0:
        return _copy_rates_from_pos(symbol, timeframe, start_pos, count)

    if timeframe == mt5.TIMEFRAME_M1:
        try:
            from trader_companion.mt5_market_feed import get_market_feed

            feed = get_market_feed()
            if feed.is_running:
                cached = feed.get_rates(symbol, count)
                if cached is not None and len(cached) > 0:
                    return cached
        except Exception as exc:
            logger.debug("M1 cache miss for %s: %s", symbol, exc)

    return _copy_rates_from_pos(symbol, timeframe, start_pos, count)


def get_close_prices(symbol: str, timeframe: int, count: int = 100) -> Optional[list]:
    """Closing prices for indicators (RSI, etc.)."""
    rates = copy_rates_from_pos_cached(symbol, timeframe, 0, count)
    if rates is None or len(rates) == 0:
        return None
    return [float(rate[4]) for rate in rates]
