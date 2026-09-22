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
