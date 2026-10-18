import pickle

import numpy as np
import pandas as pd

from trader_companion.signals import ml_direction
from trader_companion.trader_app import TradeOpssAIApp


class _Var:
    def __init__(self, value=False):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


def _app(enabled=False):
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.ml_mode_var = _Var(enabled)
    return app


def test_the_real_password_unlocks_publishing():
    assert TradeOpssAIApp._ml_password_ok("Predictions@123") is True


def test_a_wrong_password_is_refused():
    assert TradeOpssAIApp._ml_password_ok("predictions@123") is False
    assert TradeOpssAIApp._ml_password_ok("Predictions@1234") is False
    assert TradeOpssAIApp._ml_password_ok("wrong") is False


def test_a_blank_password_is_refused():
    # The previous gate accepted any non-empty string, so this is the fix.
    assert TradeOpssAIApp._ml_password_ok("") is False
    assert TradeOpssAIApp._ml_password_ok("   ") is False
    assert TradeOpssAIApp._ml_password_ok(None) is False


def test_surrounding_whitespace_is_tolerated():
    assert TradeOpssAIApp._ml_password_ok("  Predictions@123  ") is True


def test_the_plaintext_password_is_not_in_the_source():
    # Only the digest ships, so `strings` on the exe cannot reveal it.
    import inspect
    source = inspect.getsource(TradeOpssAIApp._ml_password_ok)

    assert "Predictions@123" not in source


def test_an_environment_override_replaces_the_builtin_secret(monkeypatch):
    monkeypatch.setenv("TRADEOPSS_AI_ML_PASSWORD", "rotated-secret")

    assert TradeOpssAIApp._ml_password_ok("rotated-secret") is True
    assert TradeOpssAIApp._ml_password_ok("Predictions@123") is False


def test_publishing_is_off_until_unlocked():
    assert _app(enabled=False)._ml_mode_enabled() is False


def test_publishing_is_on_once_unlocked():
    assert _app(enabled=True)._ml_mode_enabled() is True


def test_a_companion_without_the_toggle_never_publishes():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)

    assert app._ml_mode_enabled() is False


def test_a_locked_companion_skips_the_publish_cycle():
    published = []
    app = _app(enabled=False)
    app.auto_push_enabled = True
    app._publish_ml_direction = lambda: published.append(1)

    app._run_direction_publish_if_due()

    assert published == []


def test_stale_in_memory_bundle_remains_available(monkeypatch):
    bundle = {"trained": True, "trained_at": 1}
    monkeypatch.setattr(ml_direction, "_model_symbol_key", lambda _symbol: "ustech")
    monkeypatch.setattr(ml_direction, "_cache", {("ustech", 5): bundle})
    monkeypatch.setattr(ml_direction, "_load_bundle_from_disk",
                        lambda *_args: None)

    assert ml_direction.get_cached_bundle("ustech", 5) is bundle


def test_stale_disk_bundle_is_loaded_for_serving(monkeypatch):
    bundle = {"trained": True, "trained_at": 1}
    monkeypatch.setattr(ml_direction, "_model_symbol_key", lambda _symbol: "ustech")
    monkeypatch.setattr(ml_direction, "_cache", {})
    monkeypatch.setattr(ml_direction, "_load_bundle_from_disk",
                        lambda *_args: bundle)

    assert ml_direction.get_cached_bundle("ustech", 5) is bundle
    assert ml_direction._cache[("ustech", 5)] is bundle


def test_challenger_split_keeps_label_horizon_out_of_holdout():
    trained_at = 1_700_000_000
    seconds = [trained_at - 1800, trained_at - 1200, trained_at - 300,
               trained_at, trained_at + 300, trained_at + 1500]
    index = pd.to_datetime(seconds, unit="s", utc=True)
    features = pd.DataFrame({"x": range(len(seconds))}, index=index)
    labels = pd.Series(np.ones(len(seconds)), index=index)

    train_mask, validation_mask = ml_direction._challenger_split(
        features, labels, trained_at, timeframe_minutes=5)

    assert np.flatnonzero(train_mask).tolist() == [0, 1]
    assert np.flatnonzero(validation_mask).tolist() == [4, 5]


def test_challenger_must_clear_sample_and_accuracy_margins():
    assert not ml_direction._challenger_beats_incumbent(0.70, 0.60, 99)
    assert not ml_direction._challenger_beats_incumbent(0.61, 0.60, 100)
    assert ml_direction._challenger_beats_incumbent(0.62, 0.60, 100)


def _stub_candidate_training(monkeypatch, candidate_accuracy, incumbent_accuracy):
    trained_at = 1_700_000_000
    seconds = [trained_at - 1800, trained_at - 1500, trained_at - 1200,
               trained_at - 900, trained_at - 600, trained_at - 300,
               trained_at + 300, trained_at + 600, trained_at + 900]
    index = pd.to_datetime(seconds, unit="s", utc=True)
    features = pd.DataFrame({"feature": range(len(seconds))}, index=index)
    labels = pd.Series(np.ones(len(seconds)), index=index)
    incumbent = {
        "trained": True, "trained_at": trained_at,
        "gbm": object(), "mlp": object(), "et": object(),
        "feature_columns": ["feature"], "used_columns": ["feature"],
    }
    scores = iter((candidate_accuracy, incumbent_accuracy))
    promoted = []
    monkeypatch.setattr(ml_direction, "rates_to_df", lambda _rates: pd.DataFrame(
        {"close": np.ones(len(index))}, index=index))
    monkeypatch.setattr(ml_direction, "make_features", lambda _df: features)
    monkeypatch.setattr(ml_direction, "make_labels", lambda _df: labels)
    monkeypatch.setattr(ml_direction, "MIN_TRAIN_ROWS", 2)
    monkeypatch.setattr(ml_direction, "MIN_CHALLENGER_VALIDATION_ROWS", 2)
    monkeypatch.setattr(ml_direction, "_walk_forward", lambda *_args: {"accuracy": 0.6})
    monkeypatch.setattr(ml_direction, "_fit", lambda *_args: (
        object(), object(), object(), ["feature"]))
    monkeypatch.setattr(ml_direction, "_score_bundle",
                        lambda *_args: next(scores))
    monkeypatch.setattr(ml_direction, "_promote_bundle",
                        lambda *_args: promoted.append(True))
    return incumbent, promoted


def test_losing_challenger_does_not_replace_incumbent(monkeypatch):
    incumbent, promoted = _stub_candidate_training(monkeypatch, 0.60, 0.60)

    candidate = ml_direction.train_on_rates(rates=[1], incumbent=incumbent)

    assert candidate["trained"] is True
    assert candidate["promoted"] is False
    assert promoted == []


def test_winning_challenger_is_promoted(monkeypatch):
    incumbent, promoted = _stub_candidate_training(monkeypatch, 0.65, 0.60)

    candidate = ml_direction.train_on_rates(rates=[1], incumbent=incumbent)

    assert candidate["promoted"] is True
    assert promoted == [True]


def test_promoted_bundle_is_persisted_atomically(monkeypatch, tmp_path):
    path = tmp_path / "model.pkl"
    monkeypatch.setattr(ml_direction, "_model_cache_path", lambda *_args: str(path))
    bundle = {
        "gbm": "gbm", "mlp": "mlp", "et": "et",
        "feature_columns": ["feature"], "used_columns": ["feature"],
        "walk_forward": {"accuracy": 0.6}, "n_labeled": 500,
        "trained_at": 123.0, "promotion_eval": {"n_validation": 100},
    }

    ml_direction._save_bundle_to_disk("ustech", 5, bundle)

    with path.open("rb") as model_file:
        saved = pickle.load(model_file)
    assert saved["promotion_eval"] == {"n_validation": 100}
    assert not (tmp_path / "model.pkl.tmp").exists()


def test_stale_bundle_starts_refresh_in_background(monkeypatch):
    incumbent = {"trained": True, "trained_at": 1}
    threads = []

    class _Thread:
        def __init__(self, **kwargs):
            threads.append(kwargs)

        def start(self):
            pass

    monkeypatch.setattr(ml_direction, "_model_symbol_key", lambda _symbol: "ustech")
    monkeypatch.setattr(ml_direction, "get_cached_bundle", lambda *_args: incumbent)
    monkeypatch.setattr(ml_direction, "SKLEARN_AVAILABLE", True)
    monkeypatch.setattr(ml_direction, "_training", set())
    monkeypatch.setattr(ml_direction, "_last_train_attempt", {})
    monkeypatch.setattr(ml_direction.threading, "Thread", _Thread)

    assert ml_direction.ensure_trained_async("ustech") is False
    assert len(threads) == 1
    assert incumbent["trained_at"] == 1


def test_stale_model_scores_immediately_while_refresh_starts(monkeypatch):
    class _Model:
        classes_ = np.array([0.0, 1.0])

        def predict_proba(self, features):
            return np.tile([0.2, 0.8], (len(features), 1))

    index = pd.date_range("2020-01-01", periods=100, freq="5min", tz="UTC")
    bars = pd.DataFrame(index=index)
    features = pd.DataFrame(
        {"feature": np.ones(len(index)), "vote_score": np.zeros(len(index))},
        index=index)
    bundle = {
        "trained": True, "trained_at": 1,
        "gbm": _Model(), "mlp": _Model(), "et": _Model(),
        "feature_columns": ["feature", "vote_score"],
        "used_columns": ["feature", "vote_score"],
        "walk_forward": {"accuracy": 0.6}, "n_labeled": 1000,
    }
    refreshes = []
    monkeypatch.setattr(ml_direction, "get_cached_bundle", lambda *_args: bundle)
    monkeypatch.setattr(ml_direction, "_bundle_is_fresh", lambda _bundle: False)
    monkeypatch.setattr(ml_direction, "ensure_trained_async",
                        lambda *args, **kwargs: refreshes.append(True))
    monkeypatch.setattr(ml_direction, "rates_to_df", lambda _rates: bars)
    monkeypatch.setattr(ml_direction, "make_features", lambda _df: features)
    monkeypatch.setattr(ml_direction, "compute_tick_micro_features",
                        lambda _ticks: {"ready": False})
    monkeypatch.setattr(ml_direction, "prediction_tracker", None)

    result = ml_direction.get_ml_direction(rates=[1])

    assert result["ready"] is True
    assert result["direction"] == "buy"
    assert refreshes == [True]


def test_async_ml_direction_refresh_applies_callback(monkeypatch):
    logs = []
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app._ai_direction_refresh_running = False
    app._active_trade_rows = []
    app._broker_login_family = lambda firm: firm
    app._resolve_mt5_hedge_symbol = lambda: "USTECH"
    app._direct_mt5_ml_direction = lambda _symbol: "buy"
    app.root = type("Root", (), {"after": lambda _self, _delay, callback: callback()})()
    app.log = lambda message: logs.append(message)

    class _ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr("trader_companion.trader_app.threading.Thread", _ImmediateThread)

    app._refresh_ai_direction_async(["TopStep"])

    assert any("Current ML bias (Tradovate NQ): BUY" in line for line in logs)
    assert app._ai_direction_refresh_running is False
