import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from trader_companion import trader_app
from trader_companion.signals import prediction_tracker as pt
from trader_companion.signals import trade_learning_journal as tlj
from trader_companion.trader_app import KENYA_TZ, TradeOpssAIApp

SYM = "ustech"
TODAY = "2026-06-10"
ENTRY_TS = datetime(2026, 6, 10, 9, 0, tzinfo=KENYA_TZ).timestamp()


@pytest.fixture(autouse=True)
def isolated_tracker(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "_journal_path", lambda symbol: str(tmp_path / f"journal_{symbol}.jsonl"))
    for store in (pt._records, pt._entries):
        store.clear()
    pt._loaded.clear()
    pt._entries_loaded.clear()
    monkeypatch.setattr(pt.time, "time", lambda: ENTRY_TS + 3600)
    yield


def _entry(account="ACC1", side="buy", tp=62.5, sl=25.0, ts=ENTRY_TS, trend="buy",
           source="local_ml", direction=None, date=TODAY):
    return pt.record_trade_entry(
        SYM, account=account, entry_date=date, side=side, entry_ts=ts, confidence=0.7,
        p_up=0.7, tp_points=tp, sl_points=sl, trend_direction=trend,
        signal_direction=direction or side, signal_source=source)


def _records():
    return [r for r in pt._records.get(SYM, []) if r.get("source") == "trade"]


# ── edge scoring ────────────────────────────────────────────────────────

@pytest.mark.parametrize("tp,sl", [(25, 25), (62.5, 25), (25, 62.5), (100, 10)])
def test_coin_flip_scores_half_whatever_the_geometry(tp, sl):
    p_win = sl / (tp + sl)
    expected = p_win * pt.trade_edge_score(True, tp, sl) + (1 - p_win) * pt.trade_edge_score(False, tp, sl)
    assert expected == pytest.approx(0.5, abs=0.01)


def test_even_geometry_is_plain_accuracy():
    assert pt.trade_edge_score(True, 25, 25) == 1.0
    assert pt.trade_edge_score(False, 25, 25) == 0.0


def test_scores_stay_inside_zero_one():
    for tp, sl in [(1, 100), (100, 1), (62.5, 25)]:
        for won in (True, False):
            assert 0.0 <= pt.trade_edge_score(won, tp, sl) <= 1.0


# ── remembering entries ────────────────────────────────────────────────

def test_only_ml_followed_trades_are_remembered():
    assert _entry() is True
    assert _entry("B", source="none") is False
    assert _entry("C", side="sell", direction="buy") is False   # side was forced
    assert _entry("D", tp=0) is False
    assert _entry("E", side="hold") is False


def test_retried_entry_is_not_duplicated():
    assert _entry() is True
    assert _entry() is False


# ── learning from outcomes ─────────────────────────────────────────────

def test_outcome_becomes_a_verified_live_sample():
    _entry()
    assert pt.ingest_trade_outcome(SYM, account="ACC1", entry_date=TODAY, outcome="tp", net_pnl=500.0)
    rec = _records()[0]
    assert rec["verified"] and not rec["simulated"] and rec["correct"] is True
    assert rec["lean"] == "buy" and rec["trend_direction"] == "buy" and rec["net_pnl"] == 500.0
    assert rec["edge_score"] == pt.trade_edge_score(True, 62.5, 25.0)


def test_loss_and_breach_are_both_losses():
    _entry("A1")
    _entry("A2", tp=50, sl=20)
    pt.ingest_trade_outcome(SYM, account="A1", entry_date=TODAY, outcome="sl")
    pt.ingest_trade_outcome(SYM, account="A2", entry_date=TODAY, outcome="breach")
    sl, breach = _records()
    assert sl["correct"] is False and not sl["breach"]
    assert breach["correct"] is False and breach["breach"] is True and breach["outcome"] == "sl"


def test_unknown_or_unattributed_outcomes_are_ignored():
    assert pt.ingest_trade_outcome(SYM, account="NOPE", entry_date=TODAY, outcome="tp") is False
    _entry()
    assert pt.ingest_trade_outcome(SYM, account="ACC1", entry_date=TODAY, outcome="weird") is False
    assert _records() == []


def test_an_outcome_is_learned_only_once():
    _entry()
    assert pt.ingest_trade_outcome(SYM, account="ACC1", entry_date=TODAY, outcome="tp") is True
    assert pt.ingest_trade_outcome(SYM, account="ACC1", entry_date=TODAY, outcome="tp") is False
    _entry()  # a retried ledger push re-sends the entry; it must not re-open learning
    assert pt.ingest_trade_outcome(SYM, account="ACC1", entry_date=TODAY, outcome="tp") is False
    assert len(_records()) == 1


def test_many_accounts_on_one_plan_count_as_one_decision():
    for i in range(5):
        _entry(f"ACC{i}", ts=ENTRY_TS + i * 25)
    added = [pt.ingest_trade_outcome(SYM, account=f"ACC{i}", entry_date=TODAY, outcome="tp")
             for i in range(5)]
    assert added == [True, False, False, False, False]


def test_different_geometry_or_time_are_separate_decisions():
    _entry("A", tp=62.5, sl=25)
    _entry("B", tp=37.5, sl=25)
    _entry("C", ts=ENTRY_TS + 7200)
    results = [pt.ingest_trade_outcome(SYM, account=a, entry_date=TODAY, outcome="tp") for a in "ABC"]
    assert results == [True, True, True]


def test_learning_survives_a_restart():
    _entry()
    pt._records.clear(); pt._entries.clear(); pt._loaded.clear(); pt._entries_loaded.clear()
    assert pt.ingest_trade_outcome(SYM, account="ACC1", entry_date=TODAY, outcome="tp") is True


def test_old_entries_are_pruned(monkeypatch):
    _entry(date="2020-01-01")
    _entry("NEW")
    assert all(e["entry_date"] != "2020-01-01" for e in pt._entries[SYM].values())


# ── effect on the live model ───────────────────────────────────────────

def test_trade_results_do_not_skew_direction_accuracy():
    _entry()
    pt.ingest_trade_outcome(SYM, account="ACC1", entry_date=TODAY, outcome="sl")
    assert pt.get_stats(SYM, live_only=True) == {"n_verified": 0}


def test_trade_stats_compare_the_win_rate_with_chance():
    for i, outcome in enumerate(["tp", "sl", "tp", "sl"]):
        _entry(f"A{i}", ts=ENTRY_TS + i * 7200)
        pt.ingest_trade_outcome(SYM, account=f"A{i}", entry_date=TODAY, outcome=outcome)
    stats = pt.get_trade_stats(SYM)
    assert stats["n"] == 4 and stats["wins"] == 2 and stats["win_rate"] == 0.5
    assert stats["expected_win_rate"] == pytest.approx(25 / 87.5, abs=0.001)
    assert stats["edge"] == pytest.approx(0.5 - 25 / 87.5, abs=0.001)


def test_real_results_move_the_trend_vs_reversal_weights():
    base = pt.get_regime_blend_weights(SYM)
    assert base["source"] == "default"
    for i in range(4):   # trade WITH the trend keeps winning ...
        _entry(f"W{i}", ts=ENTRY_TS + i * 7200, trend="buy", side="buy")
        pt.ingest_trade_outcome(SYM, account=f"W{i}", entry_date=TODAY, outcome="tp")
    for i in range(4):   # ... while trades AGAINST it keep losing
        _entry(f"R{i}", ts=ENTRY_TS + (10 + i) * 7200, trend="sell", side="buy")
        pt.ingest_trade_outcome(SYM, account=f"R{i}", entry_date=TODAY, outcome="sl")
    learned = pt.get_regime_blend_weights(SYM)
    assert learned["source"] == "learned" and learned["n_trade_outcomes"] == 8
    assert learned["w_trend"] > base["w_trend"]


def test_losing_trend_trades_shift_weight_to_reversal():
    for i in range(4):
        _entry(f"L{i}", ts=ENTRY_TS + i * 7200, trend="buy", side="buy")
        pt.ingest_trade_outcome(SYM, account=f"L{i}", entry_date=TODAY, outcome="sl")
    for i in range(4):
        _entry(f"V{i}", ts=ENTRY_TS + (10 + i) * 7200, trend="sell", side="buy")
        pt.ingest_trade_outcome(SYM, account=f"V{i}", entry_date=TODAY, outcome="tp")
    assert pt.get_regime_blend_weights(SYM)["w_trend"] < pt.DEFAULT_W_TREND


def test_trade_samples_never_masquerade_as_the_prediction_at_entry():
    _entry()
    pt.ingest_trade_outcome(SYM, account="ACC1", entry_date=TODAY, outcome="tp")
    assert tlj._prediction_at_time(list(pt._records[SYM]), int(ENTRY_TS) + 60) is None


# ── the app hook ───────────────────────────────────────────────────────

def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.log = Mock()
    app.root = SimpleNamespace(after=lambda delay, fn=None: fn() if fn else None)
    app._pending_ledger_events = []
    app._ledger_events_lock = __import__("threading").Lock()
    return app


def _entry_event(account="APP1"):
    return {"event": "entry", "account": account, "entry_date": TODAY,
            "entry_time": datetime.fromtimestamp(ENTRY_TS, KENYA_TZ).isoformat(),
            "side": "buy", "tp_ticks": 250, "sl_ticks": 100, "signal_source": "local_ml",
            "signal": {"direction": "buy", "confidence": 0.7, "probability": 0.7,
                       "trend_direction": "buy"}}


def test_ledger_entry_and_outcome_teach_the_model(monkeypatch):
    monkeypatch.setattr(trader_app, "RELEASE_DISABLE_ML", False)
    app = _app()
    app._queue_ledger_event(_entry_event())
    app._queue_ledger_event({"event": "outcome", "account": "APP1", "entry_date": TODAY,
                             "outcome": "tp", "net_pnl": 480.0})
    rec = _records()[0]
    assert rec["tp_points"] == 62.5 and rec["sl_points"] == 25.0   # ticks → points
    assert "Learned from TP" in app.log.call_args[0][0]
    assert len(app._pending_ledger_events) == 2                  # still sent to the dashboard


def test_retried_ledger_events_do_not_learn_twice(monkeypatch):
    monkeypatch.setattr(trader_app, "RELEASE_DISABLE_ML", False)
    app = _app()
    outcome = {"event": "outcome", "account": "APP1", "entry_date": TODAY, "outcome": "sl"}
    for event in (_entry_event(), outcome, _entry_event(), outcome):
        app._queue_ledger_event(event)
    assert len(_records()) == 1


def test_trader_build_without_ml_does_not_learn(monkeypatch):
    monkeypatch.setattr(trader_app, "RELEASE_DISABLE_ML", True)
    app = _app()
    app._queue_ledger_event(_entry_event())
    assert pt._entries == {} and len(app._pending_ledger_events) == 1


def test_bad_events_never_break_the_ledger(monkeypatch):
    monkeypatch.setattr(trader_app, "RELEASE_DISABLE_ML", False)
    app = _app()
    app._queue_ledger_event({"event": "entry", "entry_time": "garbage"})
    app._queue_ledger_event({"event": "outcome"})
    assert len(app._pending_ledger_events) == 2


def test_signal_context_keeps_the_trend_for_the_ledger():
    app = _app()
    app._set_signal_context("buy", source="local_ml",
                            result={"confidence": 0.7, "probability": 0.71, "trend_direction": "sell"})
    event = app._build_ledger_entry_event(
        account="X", prop_firm="Tradeify", phase_key="challenge_trade1", platform="Tradovate",
        symbol="NQ", side="buy", config={"tradovate_tp_ticks": 250, "tradovate_sl_ticks": 100})
    assert event["signal"]["trend_direction"] == "sell"


# ── the Learning line ──────────────────────────────────────────────────

def test_learning_line_reports_real_results(monkeypatch):
    monkeypatch.setattr(trader_app, "RELEASE_DISABLE_ML", False)
    app = _app()
    text, _ = app._learning_summary()
    assert text.startswith("No real trades learned yet") and "(default)" in text
    app._learning_cache = None
    for i in range(3):
        _entry(f"S{i}", ts=ENTRY_TS + i * 7200)
        pt.ingest_trade_outcome(SYM, account=f"S{i}", entry_date=TODAY, outcome="tp")
    text, color = app._learning_summary()
    assert "3 real trades learned" in text and "100% won" in text


def test_learning_line_is_off_in_the_trader_build(monkeypatch):
    monkeypatch.setattr(trader_app, "RELEASE_DISABLE_ML", True)
    assert _app()._learning_summary()[0] == "Off in this build"
