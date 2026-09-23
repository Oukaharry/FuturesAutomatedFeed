from datetime import timedelta

from trader_companion.signals import direction_feed
from trader_companion.trader_app import TradeOpssAIApp


def _ml(direction, ready=True, confidence=0.71):
    return {"ready": ready, "direction": direction, "confidence": confidence,
            "probability": 0.71, "model": "ensemble"}


def _signal(direction="buy", age_sec=0):
    published = direction_feed.eat_now() - timedelta(seconds=age_sec)
    return {"direction": direction,
            "published_at": published.isoformat(timespec="seconds")}


class _Entry:
    """Stands in for the Tk entry the real app reads the dashboard URL from."""

    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


def _app(url="http://dash"):
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.log = lambda *a, **k: None
    app.url_entry = _Entry(url)
    return app


# --- signal shaping -----------------------------------------------------


def test_a_ready_buy_reading_becomes_a_broadcastable_signal():
    signal = direction_feed.build_signal(_ml("buy"), symbol="USTECH", source="a@b.c")

    assert signal["direction"] == "buy"
    assert signal["symbol"] == "USTECH"
    assert signal["confidence"] == 0.71
    assert direction_feed.direction_from(signal) == "buy"


def test_an_untrained_model_publishes_nothing():
    assert direction_feed.build_signal(_ml("buy", ready=False)) is None


def test_a_neutral_reading_publishes_nothing():
    # Publishing neutral would bury the last actionable signal in the window.
    assert direction_feed.build_signal(_ml("neutral")) is None


# --- freshness window ---------------------------------------------------


def test_a_signal_from_seconds_ago_is_live():
    assert direction_feed.direction_from(_signal("sell", age_sec=5)) == "sell"


def test_a_signal_from_three_minutes_ago_is_still_inside_the_window():
    assert direction_feed.direction_from(_signal("sell", age_sec=180)) == "sell"


def test_a_signal_older_than_the_window_is_refused():
    assert direction_feed.direction_from(_signal("sell", age_sec=360)) is None


def test_the_window_is_configurable_per_call():
    signal = _signal("buy", age_sec=300)

    assert direction_feed.direction_from(signal, max_age_sec=600) == "buy"
    assert direction_feed.direction_from(signal, max_age_sec=60) is None


def test_a_signal_dated_in_the_future_is_refused():
    # A publisher with a skewed clock could otherwise pin a stale direction.
    assert direction_feed.direction_from(_signal("buy", age_sec=-600)) is None


def test_a_signal_without_a_direction_or_timestamp_is_refused():
    assert direction_feed.direction_from({"published_at": "not a date"}) is None
    assert direction_feed.direction_from({"direction": "buy"}) is None
    assert direction_feed.direction_from(None) is None


def test_a_naive_timestamp_is_read_as_east_africa_time():
    naive = direction_feed.eat_now().replace(tzinfo=None).isoformat(timespec="seconds")

    assert direction_feed.direction_from(
        {"direction": "buy", "published_at": naive}) == "buy"


def test_a_corrupt_stored_signal_decodes_to_empty():
    assert direction_feed.loads("not json") == {}
    assert direction_feed.loads(None) == {}
    assert direction_feed.loads('{"direction": "buy"}') == {"direction": "buy"}


# --- live direction lookup ----------------------------------------------


def test_every_firm_follows_the_one_live_reading(monkeypatch):
    monkeypatch.setattr(direction_feed, "fetch", lambda *a, **k: _signal("sell"))

    assert _app()._get_firm_directions(["Tradeify", "TopStep"]) == {
        "Tradeify": "sell", "TopStep": "sell"}


def test_no_direction_is_invented_when_the_window_is_empty(monkeypatch):
    monkeypatch.setattr(direction_feed, "fetch",
                        lambda *a, **k: _signal("sell", age_sec=3600))

    assert _app()._get_firm_directions(["Tradeify"]) == {}


def test_a_later_reading_flips_the_direction(monkeypatch):
    # The signal is live, so it must never be frozen for the session.
    app = _app()

    monkeypatch.setattr(direction_feed, "fetch", lambda *a, **k: _signal("buy"))
    first = app._get_firm_directions(["Tradeify"])

    monkeypatch.setattr(direction_feed, "fetch", lambda *a, **k: _signal("sell"))
    app._broadcast_direction_at = None  # expire the fetch cache
    second = app._get_firm_directions(["Tradeify"])

    assert first == {"Tradeify": "buy"}
    assert second == {"Tradeify": "sell"}


def test_the_dashboard_is_not_refetched_for_every_firm(monkeypatch):
    calls = []

    def _fetch(*a, **k):
        calls.append(1)
        return _signal("buy")

    monkeypatch.setattr(direction_feed, "fetch", _fetch)
    app = _app()

    app._get_firm_directions(["A", "B", "C"])
    app._get_firm_directions(["D"])

    assert len(calls) == 1


def test_a_fetch_failure_yields_no_direction(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("dashboard down")

    monkeypatch.setattr(direction_feed, "fetch", _boom)

    assert _app()._broadcast_direction() is None


def test_the_execution_path_reads_the_live_signal(monkeypatch):
    monkeypatch.setattr(TradeOpssAIApp, "_direct_mt5_ml_direction",
                        lambda *a, **k: "buy")

    assert _app()._get_signal_direction("USTECH") == "buy"


def test_the_execution_path_returns_none_rather_than_guessing(monkeypatch):
    monkeypatch.setattr(TradeOpssAIApp, "_direct_mt5_ml_direction",
                        lambda *a, **k: None)

    assert _app()._get_signal_direction("USTECH") is None


def test_the_dashboard_url_comes_from_the_connection_entry(monkeypatch):
    # Reading it from anywhere else raised AttributeError on every live fetch.
    seen = []
    monkeypatch.setattr(direction_feed, "fetch",
                        lambda url, **k: seen.append(url) or _signal("buy"))

    assert _app("http://configured/")._broadcast_direction() == "buy"
    assert seen == ["http://configured"]


def test_no_configured_dashboard_means_no_direction(monkeypatch):
    monkeypatch.setattr(direction_feed, "fetch", lambda *a, **k: _signal("buy"))

    assert _app("   ")._broadcast_direction() is None
