"""MyFundedPerps streaming clients: frame handling and bar conversion."""

from trader_companion.perps_account_stream import (
    LIVE_STREAM_URL, SANDBOX_STREAM_URL, MFPAccountStream, stream_url_for_key,
)
from trader_companion.perps_md_feed import PerpsMDFeed, candle_to_bar


def test_stream_url_routes_by_key_prefix():
    assert stream_url_for_key("fp_test_x") == SANDBOX_STREAM_URL
    assert stream_url_for_key("fp_live_x") == LIVE_STREAM_URL


def _stream():
    return MFPAccountStream("fp_test_x")


def test_snapshot_populates_account_state():
    s = _stream()
    s._handle_frame({"type": "snapshot", "seq": 1,
                     "account": {"id": "a1", "balance": 100000},
                     "positions": [{"id": "p1", "side": "long"}],
                     "orders": [{"id": "o1", "status": "working"}]})
    assert s.get_account("a1")["balance"] == 100000
    assert s.get_positions("a1") == [{"id": "p1", "side": "long"}]
    assert s._last_seq == 1


def test_terminal_order_and_closed_position_are_removed():
    s = _stream()
    s._handle_frame({"type": "snapshot", "seq": 1, "account": {"id": "a1"},
                     "positions": [{"id": "p1"}], "orders": [{"id": "o1"}]})
    s._handle_frame({"type": "order", "event": "filled", "seq": 2,
                     "account_id": "a1", "order": {"id": "o1"}})
    s._handle_frame({"type": "position", "event": "closed", "seq": 3,
                     "account_id": "a1", "position": {"id": "p1"}})
    assert s.orders["a1"] == {}
    assert s.get_positions("a1") == []


def test_account_removed_clears_all_state():
    s = _stream()
    s._handle_frame({"type": "snapshot", "seq": 1, "account": {"id": "a1"},
                     "positions": [], "orders": []})
    s._handle_frame({"type": "account", "event": "removed", "seq": 2,
                     "account_id": "a1"})
    assert s.get_account("a1") is None


def test_events_reach_callback_but_heartbeats_do_not():
    seen = []
    s = MFPAccountStream("fp_test_x", on_event=seen.append)
    s._handle_frame({"type": "heartbeat"})
    s._handle_frame({"type": "fill", "seq": 1, "account_id": "a1",
                     "fill": {"id": "f1"}})
    assert [f["type"] for f in seen] == ["fill"]


def test_resume_url_after_frames():
    s = _stream()
    s._handle_frame({"type": "hello", "stream_id": "sid1"})
    s._handle_frame({"type": "fill", "seq": 7, "time": 1791535000000,
                     "account_id": "a1", "fill": {"id": "f1"}})
    url = s._connect_url()
    assert "resume=sid1" in url and "last_seq=7" in url and "since=1791535000000" in url


def test_candle_to_bar_converts_decimal_strings():
    bar = candle_to_bar({"openTime": 1791535000000, "open": "82500.1",
                         "high": "82510", "low": "82490", "close": "82505.5",
                         "volume": "12.3", "interval": "1m", "isFinal": True})
    assert bar == {"time": 1791535000, "open": 82500.1, "high": 82510.0,
                   "low": 82490.0, "close": 82505.5, "volume": 12.3}
    assert candle_to_bar({"open": "bad"}) is None


def test_feed_ingest_produces_mt5_rates():
    feed = PerpsMDFeed()
    feed._ingest([
        {"interval": "1m", "openTime": 60000, "open": "1", "high": "2",
         "low": "0.5", "close": "1.5", "volume": "3", "isFinal": True},
        {"interval": "1m", "openTime": 120000, "open": "1.5", "high": "2.5",
         "low": "1", "close": "2", "volume": "4", "isFinal": False},
        {"interval": "5m", "openTime": 0, "open": "1", "high": "2.5",
         "low": "0.5", "close": "2", "volume": "7", "isFinal": False},
    ])
    assert feed.bar_count(1) == 2 and feed.bar_count(5) == 1
    rates = feed.get_rates_minutes(1, 10)
    assert list(rates["time"]) == [60, 120]
    assert rates[-1]["close"] == 2.0
