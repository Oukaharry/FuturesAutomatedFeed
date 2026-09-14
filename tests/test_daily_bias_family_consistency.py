from trader_companion.trader_app import TradeOpssAIApp


def test_family_bias_uses_canonical_firm_key():
    app = object.__new__(TradeOpssAIApp)

    assert app._broker_login_family("Tradeify Select") == "Tradeify"
    assert app._broker_login_family("Funded Next Flex") == "Funded Next"

    bias = {"Tradeify": "buy", "Funded Next": "sell"}

    assert app._resolve_firm_bias("Tradeify Select", bias) == "buy"
    assert app._resolve_firm_bias("Funded Next Flex", bias) == "sell"


def test_ml_mode_requires_password_when_configured(monkeypatch):
    app = object.__new__(TradeOpssAIApp)
    app.ml_mode_var = type("Var", (), {"get": lambda self: True})()
    app.ml_password_var = type("Var", (), {"get": lambda self: ""})()
    monkeypatch.setenv("TRADEOPSS_AI_ML_PASSWORD", "hunter2")

    assert app._ml_mode_enabled() is False

    app.ml_password_var = type("Var", (), {"get": lambda self: "hunter2"})()
    assert app._ml_mode_enabled() is True
