"""Dashboard account numbers must find their broker history despite naming drift."""
from trader_companion.trader_app import AccountHistoryMap, TradeOpssAIApp


def _history(*names):
    return AccountHistoryMap({n.lower(): {"account_name": n, "balance": 50000.0}
                              for n in names})


def test_exact_and_normalised_names_resolve():
    history = _history("FNFT85625", "FTDFYSLX50969754357")

    assert history.get("fnft85625")["account_name"] == "FNFT85625"
    assert history.get("FNFT-85625")["account_name"] == "FNFT85625"
    assert history.get(" fnft 85625 ")["account_name"] == "FNFT85625"
    assert "FTDFYSLX-50969754357" in history


def test_unique_account_number_run_resolves_a_shorter_dashboard_key():
    history = _history("TDFY-01419740", "TDFY-01419999")

    assert history.get("01419740")["account_name"] == "TDFY-01419740"
    assert history["TDFY 01419740"]["account_name"] == "TDFY-01419740"


def test_ambiguous_or_short_keys_do_not_match():
    history = _history("APEX-5000012345", "APEX-5000012346")

    assert history.get("APEX") is None
    assert history.get("1234") is None
    assert history.get("5000012345")["account_name"] == "APEX-5000012345"
    assert "99999" not in history


def test_status_derivation_sees_a_dashed_dashboard_account(monkeypatch):
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app._trade_outcome_history = lambda force=False: _history("FNFT85625")

    assert app._account_balance("FNFT-85625") == 50000.0
    assert app._account_balance("FNFT-00000") is None
