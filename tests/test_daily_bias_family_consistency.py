from trader_companion.prop_firm_manager import PropFirmManager
from trader_companion.trader_app import TradeOpssAIApp


def test_family_bias_uses_canonical_firm_key():
    app = object.__new__(TradeOpssAIApp)

    assert app._broker_login_family("Tradeify Select") == "Tradeify"
    assert app._broker_login_family("Funded Next Flex") == "Funded Next"

    bias = {"Tradeify": "buy", "Funded Next": "sell"}

    assert app._resolve_firm_bias("Tradeify Select", bias) == "buy"
    assert app._resolve_firm_bias("Funded Next Flex", bias) == "sell"


def test_topstep_rtp_shares_topstep_direction():
    app = object.__new__(TradeOpssAIApp)

    for label in ("Topstep", "TopStep RTP", "TopStep_RTP", "TopstepRTP", "topstep rtp"):
        assert app._broker_login_family(label) == "Topstep", label

    bias = {"Topstep": "sell"}
    assert app._resolve_firm_bias("Topstep", bias) == "sell"
    assert app._resolve_firm_bias("TopStep RTP", bias) == "sell"


RAPID_DAILY_LABELS = (
    "FundedNext Rapid Daily",
    "FundedNext Rapid Daily 50K",
    "Funded Next Rapid Daily",
    "funded next rapid daily",
    "FundedNext_Rapid_Daily",
    "fundednextrapiddaily",
    "FN Rapid Daily",
    "Rapid Daily",
)


def test_rapid_daily_never_resolves_to_legacy_funded_next():
    """The generic FundedNext substring must not swallow Rapid Daily."""
    app = object.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = None

    for label in RAPID_DAILY_LABELS:
        assert app._resolve_firm_code(label) == "FundedNext Rapid Daily", label


def test_rapid_daily_labels_load_the_rapid_daily_blueprint():
    mgr = PropFirmManager()
    legacy = mgr.get_firm_info("Funded Next")

    for label in RAPID_DAILY_LABELS:
        blueprint = mgr.get_firm_info(label)
        assert blueprint["name"] == "FundedNext Rapid Daily 50K", label
        assert blueprint is not legacy, label


def test_rapid_daily_shares_funded_next_login_but_not_its_blueprint():
    app = object.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = None

    assert app._broker_login_family("FundedNext Rapid Daily") == "Funded Next"
    assert app._resolve_firm_code("FundedNext Rapid Daily") == "FundedNext Rapid Daily"


def test_ml_mode_requires_password_when_configured(monkeypatch):
    app = object.__new__(TradeOpssAIApp)
    app.ml_mode_var = type("Var", (), {"get": lambda self: True})()
    app.ml_password_var = type("Var", (), {"get": lambda self: ""})()
    monkeypatch.setenv("TRADEOPSS_AI_ML_PASSWORD", "hunter2")

    assert app._ml_mode_enabled() is False

    app.ml_password_var = type("Var", (), {"get": lambda self: "hunter2"})()
    assert app._ml_mode_enabled() is True
