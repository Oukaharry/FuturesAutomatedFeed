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


def test_tradovate_bars_own_the_signal_alias():
    # Tradovate is the signal authority: injection overwrites MT5 bars
    feed = MT5MarketFeed()
    mt5_rates = bars_to_mt5_rates({60: {"open": 9, "high": 9, "low": 9, "close": 9, "volume": 9}})
    with feed._data_lock:
        feed._cache["USTECH"] = {"rates": mt5_rates, "source": "mt5"}
    injected = bars_to_mt5_rates({60: {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}})
    feed.inject_rates("USTECH", injected, source="tradovate")
    assert float(feed.get_rates("USTECH", 1)[-1]["close"]) == 1.0


def test_feed_serves_m1_and_m5_and_ml_fetch_uses_it():
    import trader_companion.tradovate_md_feed as md
    from trader_companion.signals import ml_direction

    feed = md.TradovateMDFeed(lambda: None)
    feed._ingest(1, [{"time": 60, "open": 1, "high": 1, "low": 1, "close": 2, "volume": 3}])
    feed._ingest(5, [{"time": 300 * i, "open": 1, "high": 1, "low": 1, "close": 5, "volume": 3}
                     for i in range(1, 8)])
    assert feed.bar_count(1) == 1 and feed.bar_count(5) == 7
    m5 = feed.get_rates_minutes(5, 5)
    assert len(m5) == 5 and float(m5[-1]["close"]) == 5.0

    old = md._md_feed_singleton
    md._md_feed_singleton = feed
    try:
        rates = ml_direction._fetch_rates("ustech", 5, 5)
        assert rates is not None and len(rates) == 5
        assert ml_direction._fetch_rates("ustech", 1, 10) is not None
        assert ml_direction.fetch_recent_ticks("ustech") is None  # MT5 ticks disabled
    finally:
        md._md_feed_singleton = old
