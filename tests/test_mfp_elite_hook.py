"""Elite planner hook: attempt index from equity, NY-day gating, routing."""

import pytest

from trader_companion.prop_firm_manager import PropFirmManager
from trader_companion.trader_app import TradeOpssAIApp


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    app.log = lambda *a, **k: None
    app._broker_connections = {}
    app._mfp_elite_last_attempt = {}
    return app


class _Client:
    def __init__(self, equity, stage="evaluation", fills=None):
        self._equity, self._stage, self._fills = equity, stage, fills or []

    def get_account(self, _id):
        return {"data": {"id": _id, "account_number": "MFP-1", "stage": self._stage,
                         "starting_balance": 50000, "risk": {"equity": self._equity}}}

    def list_fills(self, account_id=None, cursor=None):
        return {"data": self._fills}


def _plan(equity, stage="evaluation", fills=None, ev=None):
    app = _app()
    app._funded_payout_count = lambda ev: 0
    app._on_funded_leg = lambda ev: stage == "funded"
    row = {"firm_code": "MyFundedPerps Elite", "eval": ev or {"Prop Firm": "MyFundedPerps Elite"}}
    plan, _ = app._mfp_elite_plan(_Client(equity, stage, fills), {"id": "a1", "account_number": "MFP-1"}, row)
    return plan


@pytest.mark.parametrize("equity,attempt,sl,tp", [
    (50000, 1, 1000, 5000),
    (49000, 2, 1000, 6000),
    (48000, 3, 450, 7000),
    (49980, 1, 1000, 5020),   # small fee drift still attempt 1
])
def test_attempt_index_is_derived_from_equity(equity, attempt, sl, tp):
    p = _plan(equity)
    assert p["allowed"]
    assert p["attempt"] == attempt
    assert (p["sl_usd"], p["tp_usd"]) == (sl, tp)


def test_ladder_exhausted_after_three_losses():
    p = _plan(47550)
    assert not p["allowed"] and "exhausted" in p["reason"]


def test_fill_today_in_new_york_blocks_second_attempt():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now_ny = datetime.now(ZoneInfo("America/New_York")).isoformat()
    p = _plan(49000, fills=[{"filled_at": now_ny}])
    assert not p["allowed"] and "daily reset" in p["reason"]


def test_old_fill_does_not_block():
    p = _plan(49000, fills=[{"filled_at": "2020-01-01T12:00:00+00:00"}])
    assert p["allowed"]


def test_in_memory_marker_blocks_until_next_ny_day():
    app = _app()
    app._mark_mfp_elite_attempt("a1")
    assert app._mfp_elite_traded_today(_Client(50000), "a1")
    assert not app._mfp_elite_traded_today(_Client(50000), "other")


def test_funded_stage_uses_cycle_target():
    app = _app()
    app.prop_firm_mgr._account_random_state["MFP-1"] = {"mfp_elite_T_cycle_0": 4000.0}
    app._funded_payout_count = lambda ev: 0
    app._on_funded_leg = lambda ev: True
    row = {"firm_code": "MyFundedPerps Elite", "eval": {"Prop Firm": "MyFundedPerps Elite"}}
    plan, _ = app._mfp_elite_plan(_Client(50000, "funded"), {"id": "a1", "account_number": "MFP-1"}, row)
    assert plan["stage"] == "funded" and plan["T"] == 4000
    assert plan["tp_usd"] == 4000 and plan["payout_cash"] == 3200


def test_elite_rows_are_still_perps_rows_and_detected_as_elite():
    app = _app()
    assert app._is_perps_firm("MyFundedPerps Elite")       # routes via perps path
    assert app._is_mfp_elite_row({"firm_code": "MyFundedPerps Elite", "eval": {}})
    assert app._is_mfp_elite_row({"firm_code": "x", "eval": {"Prop Firm": "MFP Elite"}})
    assert not app._is_mfp_elite_row({"firm_code": "MyFundedPerps", "eval": {}})
