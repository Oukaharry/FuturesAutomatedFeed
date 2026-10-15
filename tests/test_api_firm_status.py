"""API-only firms derive Pass / Fail from their own $-ladder blueprints, never
from the futures $48k / $50,100 floors."""
from unittest.mock import Mock

from trader_companion.prop_firm_manager import PropFirmManager
from trader_companion.trader_app import AccountHistoryMap, TradeOpssAIApp


def _app(history):
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    app.log = Mock()
    app._broker_connections = {}
    app._trade_outcome_history = lambda force=False: AccountHistoryMap(history)
    app._pending_breach_alerts = []
    app._breach_alerts_sent = set()
    app._save_breach_state = lambda: None
    app._funded_payout_count = lambda ev: 0
    return app


def _entry(balance, sod=None, trades=1):
    return {"balance": balance, "balance_sod": sod if sod is not None else balance,
            "daily_pnl": [{"date": "2026-10-15", "trades": trades, "net_pnl": 0.0}]}


def _row(firm, account, size="", traded=True):
    row = {"Prop Firm": firm, "Account #": account, "Account Size": size,
           "Status P1": "In Progress"}
    if traded:
        row["Hedge Result 1"] = "$0.00"
    return row


def test_rules_scale_to_each_firm():
    m = PropFirmManager()
    assert m.api_firm_status_rules("Breakout Turbo", 5000) == {
        "blueprint": "Breakout Turbo", "starting_balance": 5000.0,
        "evaluation_goal": 5450.0, "static_loss_floor": 4850.0,
        "daily_loss": 150.0, "daily_loss_floor": None}
    t = m.api_firm_status_rules("Tradeify247", 25000)
    assert (t["evaluation_goal"], t["static_loss_floor"], t["daily_loss"]) == (28000.0, 23500.0, 750.0)
    v = m.api_firm_status_rules("Vest Capital", 25000)
    assert (v["evaluation_goal"], v["static_loss_floor"], v["daily_loss"]) == (27500.0, 23500.0, 750.0)
    p = m.api_firm_status_rules("MyFundedPerps")
    assert (p["evaluation_goal"], p["static_loss_floor"], p["daily_loss"]) == (55000.0, 47500.0, 1500.0)
    assert m.api_firm_status_rules("Tradeify", 50000) is None


def test_breakout_turbo_5k_is_not_failed_by_the_futures_floor():
    app = _app({"w3m6-shmx-y67z-melw": _entry(4990.0, sod=5000.0)})
    status, _ = app._derive_account_status(_row("Breakout Turbo", "W3M6-SHMX-Y67Z-MELW", "$5,000"))
    assert status is None  # -$10 on a $5K account is a live account, not a breach


def test_breakout_turbo_fails_at_its_own_static_floor():
    app = _app({"w3m6-shmx-y67z-melw": _entry(4840.0, sod=5000.0)})
    status, reason = app._derive_account_status(_row("Breakout Turbo", "W3M6-SHMX-Y67Z-MELW", "$5,000"))
    assert status == "Fail" and "4,850.00" in reason
    assert app._pending_breach_alerts[0]["account"] == "W3M6-SHMX-Y67Z-MELW"


def test_daily_loss_floor_is_a_hard_breach():
    # Vest $25K: SOD $26,000, DLL $750 → floor $25,250 even though static floor is $23,500.
    app = _app({"vest-1": _entry(25200.0, sod=26000.0)})
    status, reason = app._derive_account_status(_row("Vest Capital", "VEST-1", "$25,000"))
    assert status == "Fail" and "daily loss floor" in reason


def test_evaluation_goal_passes():
    app = _app({"1s10k2166973": _entry(11250.0, sod=11000.0)})
    status, reason = app._derive_account_status(_row("Tradeify247", "1S10K2166973", "$10,000"))
    assert status == "Pass" and "11,200.00" in reason


def test_untraded_account_is_left_alone():
    app = _app({"mfp-1": _entry(47000.0, trades=0)})
    status, _ = app._derive_account_status(_row("MyFundedPerps", "MFP-1", "$50,000", traded=False))
    assert status is None


def test_live_broker_floor_tightens_the_threshold():
    app = _app({"vest-1": _entry(24400.0, sod=24400.0)})
    broker = Mock()
    broker.get_min_equity = lambda account_id=None, **_: {"min_equity": 24500.0}
    app._broker_connections = {"Vest Capital": {"account": broker}}
    app._is_api_only_firm = lambda n: True
    app._broker_login_family = lambda n: "vest"
    status, reason = app._derive_account_status(_row("Vest Capital", "VEST-1", "$25,000"))
    assert status == "Fail" and "broker floor" in reason
