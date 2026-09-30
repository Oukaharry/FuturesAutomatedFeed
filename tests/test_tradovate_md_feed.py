"""Tradovate MD feed: contract roll, bar parsing, MT5-shape conversion, cache."""

from datetime import datetime, timezone

import numpy as np

from trader_companion.tradovate_md_feed import (
    bars_to_mt5_rates, front_quarter_symbol, parse_chart_bars,
)
from trader_companion.mt5_market_feed import MT5MarketFeed


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_front_quarter_symbol_rolls_near_expiry():
    assert front_quarter_symbol("NQ", _dt(2026, 9, 1)) == "NQU6"   # 17d to Sep 18 expiry
    assert front_quarter_symbol("NQ", _dt(2026, 9, 14)) == "NQZ6"  # inside roll window
    assert front_quarter_symbol("NQ", _dt(2026, 9, 30)) == "NQZ6"
    assert front_quarter_symbol("NQ", _dt(2026, 12, 15)) == "NQH7"  # year rollover
    assert front_quarter_symbol("MNQ", _dt(2026, 1, 10)) == "MNQH6"


def test_parse_chart_bars_normalizes_and_skips_eoh():
    event = {"charts": [
        {"id": 1, "bars": [
            {"timestamp": "2026-09-30T07:30:00.000Z", "open": 20000.0,
             "high": 20010.5, "low": 19995.0, "close": 20005.25,
             "upVolume": 120, "downVolume": 80},
            {"timestamp": "2026-09-30T07:31:12Z", "close": 20007.0},  # sparse bar
        ]},
        {"id": 2, "eoh": True},
    ]}
    bars = parse_chart_bars(event)
    assert len(bars) == 2
    assert bars[0] == {"time": 1790753400, "open": 20000.0, "high": 20010.5,
                       "low": 19995.0, "close": 20005.25, "volume": 200}
    assert bars[1]["time"] % 60 == 0  # minute-aligned
    assert bars[1]["open"] == bars[1]["close"] == 20007.0
    assert parse_chart_bars({}) == []


def test_bars_to_mt5_rates_shape_and_limit():
    bars = {t: {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 7}
            for t in (300, 60, 240, 120, 180)}
    rates = bars_to_mt5_rates(bars, limit=3)
    assert list(rates["time"]) == [180, 240, 300]  # newest 3, ascending
    assert rates.dtype.names == ("time", "open", "high", "low", "close",
                                 "tick_volume", "spread", "real_volume")
    assert float(rates[-1]["close"]) == 1.5
    assert int(rates[-1]["tick_volume"]) == 7
    assert bars_to_mt5_rates({}) is None


def test_inject_rates_serves_cache_without_poller():
    feed = MT5MarketFeed()
    rates = bars_to_mt5_rates({60: {"open": 1, "high": 1, "low": 1, "close": 2, "volume": 1},
                               120: {"open": 2, "high": 2, "low": 2, "close": 3, "volume": 1}})
    feed.inject_rates("USTECH", rates, source="tradovate")
    got = feed.get_rates("ustech", 10)  # case-insensitive lookup
    assert got is not None and len(got) == 2
    assert float(got[-1]["close"]) == 3.0


def test_inject_never_overwrites_mt5_sourced_bars():
    feed = MT5MarketFeed()
    mt5_rates = bars_to_mt5_rates({60: {"open": 9, "high": 9, "low": 9, "close": 9, "volume": 9}})
    with feed._data_lock:
        feed._cache["USTECH"] = {"rates": mt5_rates, "source": "mt5"}
    injected = bars_to_mt5_rates({60: {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}})
    feed.inject_rates("USTECH", injected, source="tradovate")
    assert float(feed.get_rates("USTECH", 1)[-1]["close"]) == 9.0
