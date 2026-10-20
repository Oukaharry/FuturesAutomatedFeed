"""Only the latest companion may work: server defaults and the companion's own lock."""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import dashboard.app as dapp
from trader_companion.trader_app import TradeOpssAIApp

ROOT = Path(__file__).resolve().parent.parent
LATEST = "1.12.9"


def _app_version():
    source = (ROOT / "trader_companion" / "trader_app.py").read_text(encoding="utf-8")
    return re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', source, re.MULTILINE).group(1)


def _denied(version, **config):
    """Run the real gate under a request carrying ``version``."""
    defaults = {"REQUIRED_COMPANION_VERSION": LATEST, "MIN_COMPANION_VERSION": LATEST,
                "COMPANION_VERSION_EXACT": True}
    defaults.update(config)
    headers = {"X-Companion-Version": version} if version else {}
    original = {k: dapp.app.config.get(k) for k in defaults}
    dapp.app.config.update(defaults)
    try:
        with dapp.app.test_request_context("/api/client/data", headers=headers):
            return dapp._companion_version_denied({})
    finally:
        dapp.app.config.update(original)


# ── server: only the latest build gets in ──────────────────────────────

def test_server_default_matches_the_companion_version():
    assert dapp.LATEST_COMPANION_VERSION == _app_version() == LATEST


def test_production_config_defaults_to_the_latest_only():
    source = (ROOT / "config" / "production.py").read_text(encoding="utf-8")
    assert f"REQUIRED_COMPANION_VERSION', '{LATEST}'" in source
    assert f"MIN_COMPANION_VERSION', '{LATEST}'" in source
    assert "COMPANION_VERSION_EXACT', '1'" in source


def test_app_config_defaults_to_the_latest_only(monkeypatch):
    for name in ("REQUIRED_COMPANION_VERSION", "MIN_COMPANION_VERSION", "COMPANION_VERSION_EXACT"):
        monkeypatch.delenv(name, raising=False)
    with dapp.app.app_context():
        assert dapp._required_companion_version() == LATEST
        assert dapp._min_companion_version() == LATEST
    cfg = dict(dapp.app.config)
    dapp.app.config.pop("COMPANION_VERSION_EXACT")
    try:
        with dapp.app.app_context():
            assert dapp._companion_version_exact_required() is True
    finally:
        dapp.app.config.update(cfg)


@pytest.mark.parametrize("old", ["1.12.8", "1.12.7", "1.12.6", "1.11.0", "1.0.1", "0.9"])
def test_older_builds_are_refused(old):
    response, status = _denied(old)
    body = response.get_json()
    assert status == 403
    assert body["required_version"] == LATEST and f"v{LATEST}" in body["message"]


def test_the_latest_build_is_accepted():
    assert _denied(LATEST) is None


def test_newer_builds_are_not_locked_out():
    assert _denied("1.12.10") is None
    assert _denied("1.13.0") is None


def test_missing_version_is_refused():
    response, status = _denied("")
    assert status == 403 and response.get_json()["required_version"] == LATEST


def test_the_pin_follows_the_required_version():
    assert _denied("1.12.9", REQUIRED_COMPANION_VERSION="1.12.10")[1] == 403
    assert _denied("1.12.10", REQUIRED_COMPANION_VERSION="1.12.10") is None


def test_the_floor_can_still_be_loosened_on_purpose():
    assert _denied("1.12.7", COMPANION_VERSION_EXACT=False, MIN_COMPANION_VERSION="1.12.6") is None


# ── companion: locks itself when refused ───────────────────────────────

def _response(status=403, body=None):
    reply = Mock(status_code=status)
    reply.json.return_value = body if body is not None else {}
    return reply


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.log = Mock()
    app.status_var = Mock()
    app.auto_push_enabled = True
    app.stop_auto_push = Mock()
    app.auto_trade_enabled = True
    app._stop_auto_trade = Mock()
    app.auto_trade_btn = Mock()
    app.load_trades_btn = Mock()
    app.root = SimpleNamespace(after=lambda delay, fn=None, *a: fn() if fn else None)
    return app


@pytest.fixture(autouse=True)
def no_dialogs(monkeypatch):
    shown = Mock()
    monkeypatch.setattr("trader_companion.trader_app.messagebox.showerror", shown)
    return shown


def test_a_version_refusal_locks_the_companion(no_dialogs):
    app = _app()
    refusal = _response(403, {"status": "error", "required_version": "1.13.0",
                              "message": "Update TradeOpssAI to v1.13.0 (you have v1.12.9)."})
    assert app._note_version_refusal(refusal) is True
    assert app._update_required["required"] == "1.13.0"
    app.stop_auto_push.assert_called_once()
    app._stop_auto_trade.assert_called_once()
    app.auto_trade_btn.configure.assert_called_with(state="disabled")
    app.load_trades_btn.configure.assert_called_with(state="disabled")
    no_dialogs.assert_called_once()
    assert "Update TradeOpssAI to v1.13.0" in no_dialogs.call_args[0][1]


def test_only_one_lock_and_one_dialog(no_dialogs):
    app = _app()
    refusal = _response(403, {"required_version": "1.13.0"})
    app._note_version_refusal(refusal)
    app._note_version_refusal(refusal)
    no_dialogs.assert_called_once()
    app._stop_auto_trade.assert_called_once()


@pytest.mark.parametrize("reply", [
    _response(403, {"status": "inactive", "message": "Account inactive"}),   # not a version issue
    _response(403, {"status": "blocked"}),
    _response(500, {"required_version": "1.13.0"}),
    _response(200, {"required_version": "1.13.0"}),
    _response(403, None),
])
def test_other_errors_do_not_lock(reply):
    app = _app()
    assert app._note_version_refusal(reply) is False
    assert getattr(app, "_update_required", None) is None


def test_unreadable_responses_do_not_lock():
    app = _app()
    broken = Mock(status_code=403)
    broken.json.side_effect = ValueError("not json")
    assert app._note_version_refusal(broken) is False
    assert app._note_version_refusal(None) is False


def test_locked_companion_cannot_trade():
    app = _app()
    app._lock_for_update("1.13.0")
    assert app._update_blocks_trading("Auto-trade") is True
    assert app._start_auto_trade() is False
    app._finish_auto_trade_batch = Mock()
    app._auto_execute_all_trades(stop_when_done=False)
    app._finish_auto_trade_batch.assert_called_once_with(stop_when_done=False)
    app._execute_row_trade("buy", {})          # returns without touching any broker


def test_unlocked_companion_is_not_blocked():
    assert _app()._update_blocks_trading() is False


def test_the_today_banner_shows_the_lock():
    app = _app()
    app._lock_for_update("1.13.0")
    app._active_trade_rows = []
    app._auto_trade_scheduled_dt = None
    app._auto_trade_total = 0
    app._kyc_batch_starts = {}
    app._auto_wake_client_email = "x@y.z"
    app._auto_wake_state = {}
    app._broker_connections = {}
    app.client_email_entry = SimpleNamespace(get=lambda: "x@y.z")
    app.trading_mode_var = SimpleNamespace(get=lambda: "Simulation")
    app.direction_var = SimpleNamespace(get=lambda: "All Trades")
    app._learning_cache = (1e18, ("off", "#64748B"))
    app.auto_trade_enabled = False
    summary = app._today_summary()
    assert "Update required" in summary["state"] and "1.13.0" in summary["state"]
    assert summary["state_color"] == "#F87171"
