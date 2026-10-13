"""Vest Capital (Vest Markets) connector + companion wiring tests — no network."""

import json
import time
import uuid

import pytest

from trader_companion.prop_firm_manager import PropFirmManager
from trader_companion.trader_app import TradeOpssAIApp
from trader_companion import vest_connector as vc
from trader_companion.vest_connector import VestClient, VestExecutor, VestError

ACCT = "875c7864-2672-5a3f-890b-a9f594ef1c32"
NDX_SPEC = {"symbol": "NDX-USD-PERP", "sizeDecimals": 4, "priceDecimals": 2,
            "minTickSize": "0.25", "capitalInitMarginRatio": "0.02000000",
            "tradingStatus": "TRADING", "capitalTradingStatus": "TRADING"}
CAP = {"id": ACCT, "initial_capital": "5000.00000000", "target_equity": "5500.00000000",
       "max_drawdown_limit": "4700.00000000", "daily_loss_floor": "4850.000000000000000",
       "daily_reset_balance": "5000.000000000000000", "max_leverage": "5.0000", "stage": 1}


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    app.log = lambda *a, **k: None
    app._broker_connections = {}
    return app


def _tok(exp_in_s=900, **extra):
    now = time.time() * 1000
    d = {"accessToken": "acc-" + uuid.uuid4().hex, "refreshToken": "ref-" + uuid.uuid4().hex,
         "accessExpiresAtMs": now + exp_in_s * 1000, "refreshExpiresAtMs": now + 30 * 86400_000}
    d.update(extra)
    return d


# ── identity / routing ─────────────────────────────────────────────────

@pytest.mark.parametrize("label", ["Vest Capital", "vest capital", "VestCapital", "Vest Markets", "vest"])
def test_is_vest_firm_matches_variants(label):
    assert _app()._is_vest_firm(label)


@pytest.mark.parametrize("label", ["Tradeify247", "MyFundedPerps", "Tradeify", "Investor", ""])
def test_is_vest_firm_rejects_others(label):
    assert not _app()._is_vest_firm(label)


def test_vest_is_api_only_and_platform_vest():
    app = _app()
    class _V:
        def get(self): return "Tradovate"
    app.broker_var = _V()
    assert app._is_api_only_firm("Vest Capital")
    assert app._platform_for_firm("Vest Capital") == "Vest"
    assert app._broker_login_family("Vest Capital") == "Vest Capital"
    assert TradeOpssAIApp._FIRM_MAP["Vest Markets"] == "Vest Capital"


@pytest.mark.parametrize("acct", [ACCT, ACCT.upper()])
def test_manager_detects_vest_uuid_accounts(acct):
    assert PropFirmManager().detect_prop_firm(acct) == "Vest Capital"


@pytest.mark.parametrize("acct", ["1S10K2166973", "TDFYSL50469269857", "875c7864-2672", "not-a-uuid-at-all-xx"])
def test_vest_detection_does_not_steal_others(acct):
    assert PropFirmManager().detect_prop_firm(acct) != "Vest Capital"


# ── blueprint planner ─────────────────────────────────────────────────

def test_vest_rules_prefer_live_record_over_percentages():
    r = PropFirmManager().vest_rules_for_balance(5000, live=CAP)
    assert r["evaluation_goal"] == 5500 and r["static_loss_floor"] == 4700
    assert r["daily_loss_floor"] == 4850 and r["max_leverage"] == 5.0
    assert r["reserve_floor"] == 4710


def test_vest_rules_percentage_fallback():
    r = PropFirmManager().vest_rules_for_balance(10000)
    assert r["evaluation_goal"] == 11000 and r["daily_loss"] == 300 and r["static_loss_floor"] == 9400


def test_vest_plan_caps_sl_to_daily_room_minus_reserve():
    p = PropFirmManager().plan_vest_attempt(equity=5000, balance_sod=5000, starting_balance=5000,
                                            on_funded=False, live=CAP)
    assert p["allowed"] and p["tp_usd"] == 500 and p["sl_usd"] == 140  # 150 room − 10 reserve
    assert p["leverage"] == 5.0


def test_vest_plan_blocks_when_no_room_or_at_target():
    m = PropFirmManager()
    assert not m.plan_vest_attempt(equity=4850, balance_sod=5000, starting_balance=5000,
                                   on_funded=False, live=CAP)["allowed"]
    assert not m.plan_vest_attempt(equity=5500, balance_sod=5000, starting_balance=5000,
                                   on_funded=False, live=CAP)["allowed"]


# ── client: token chain handling (fake HTTP) ──────────────────────────

class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._b = body
        self.content = b"x"
        self.text = json.dumps(body)
    def json(self): return self._b


class _FakeHTTP:
    """Simulates Vest's rotating refresh tokens + account-token minting."""

    def __init__(self, user, account):
        self.valid_refresh = {user["refreshToken"], account["refreshToken"]}
        self.calls = []
        self.open_bodies = []
        self.open_headers = []

    def _rotate(self, body, with_account):
        rt = body.get("refreshToken")
        if rt not in self.valid_refresh:
            return _Resp(401, {"code": 1002, "msg": "Unauthorized"})
        self.valid_refresh.discard(rt)
        new = _tok(accountId=ACCT, isFunded=True) if with_account else _tok()
        self.valid_refresh.add(new["refreshToken"])
        return _Resp(200, new)

    def request(self, method, url, json=None, params=None, headers=None, timeout=None):
        path = url.replace(vc.REST_URL, "")
        self.calls.append((method, path))
        if path == "/v3/auth/refresh":
            return self._rotate(json, with_account="acct" in (json.get("refreshToken") or ""))
        if path == "/v3/auth/account-token":
            new = _tok(accountId=ACCT, isFunded=True)
            new["refreshToken"] = "acct-" + uuid.uuid4().hex
            self.valid_refresh.add(new["refreshToken"])
            return _Resp(200, new)
        if path == "/v3/exchangeInfo":
            return _Resp(200, {"symbols": [NDX_SPEC]})
        if path == "/v3/ticker/latest":
            return _Resp(200, {"tickers": [{"symbol": "NDX-USD-PERP", "markPrice": "30000.00"}]})
        if path == "/v3/accounts":
            return _Resp(200, {"accounts": [{"account_id": ACCT, "amount": "5000.00", "active": True}]})
        if path == "/v3/capital/accounts/active":
            return _Resp(200, {"accounts": [dict(CAP)]})
        if path == "/v3/positions/opened":
            return _Resp(200, {"positions": None})
        if path == "/v3/positions":
            return _Resp(200, {"positions": []})
        if path == "/v3/positions/open":
            self.open_bodies.append(json)
            self.open_headers.append(headers)
            return _Resp(200, {"positionId": "p1", "orderId": "o1", "commandId": "c1",
                               "stopLossIds": ["s1"], "takeProfitIds": ["t1"]})
        return _Resp(404, {"code": 1, "msg": path})

    def post(self, url, json=None, headers=None, timeout=None):
        return self.request("POST", url, json=json, headers=headers, timeout=timeout)

    def get(self, url, headers=None, timeout=None, params=None):
        return self.request("GET", url, params=params, headers=headers, timeout=timeout)


def _client(tmp_path, user=None, account=None):
    user = user or _tok()
    account = account or _tok(accountId=ACCT)
    account["refreshToken"] = "acct-" + uuid.uuid4().hex
    c = VestClient(token_file=str(tmp_path / "vest.json"))
    c.import_tokens(user=user, account=account)
    c._http = _FakeHTTP(user, account)
    return c


def test_import_tokens_persists_and_reloads(tmp_path):
    c = _client(tmp_path)
    again = VestClient(token_file=str(tmp_path / "vest.json"))
    assert again.account_id == ACCT and again.logged_in
    assert again.account["refreshToken"] == c.account["refreshToken"]


def test_login_rotates_account_chain_and_saves(tmp_path):
    c = _client(tmp_path, account=_tok(exp_in_s=10, accountId=ACCT))
    old = c.account["refreshToken"]
    assert c.login()
    assert c.account["refreshToken"] != old
    assert ("POST", "/v3/auth/refresh") in c._http.calls
    on_disk = json.load(open(tmp_path / "vest.json"))
    assert on_disk["account"]["refreshToken"] == c.account["refreshToken"]


def test_login_falls_back_to_user_chain_when_account_chain_dead(tmp_path):
    c = _client(tmp_path, account=_tok(exp_in_s=10, accountId=ACCT))
    c._http.valid_refresh.discard(c.account["refreshToken"])   # chain killed elsewhere
    assert c.login()
    assert ("POST", "/v3/auth/account-token") in c._http.calls
    assert c.account["accountId"] == ACCT


def test_login_raises_when_both_chains_dead(tmp_path):
    c = _client(tmp_path, account=_tok(exp_in_s=10, accountId=ACCT), user=_tok(exp_in_s=10))
    c._http.valid_refresh.clear()
    with pytest.raises(VestError):
        c.login()


def test_401_forces_one_rotation_then_retries(tmp_path):
    c = _client(tmp_path)
    http = c._http
    first = {"n": 0}
    orig = http.request
    def flaky(method, url, **kw):
        if url.endswith("/v3/accounts") and first["n"] == 0:
            first["n"] += 1
            return _Resp(401, {"code": 1002, "msg": "Unauthorized"})
        return orig(method, url, **kw)
    http.request = flaky
    assert c.balance() == 5000.0
    assert ("POST", "/v3/auth/refresh") in http.calls


# ── client facade ─────────────────────────────────────────────────────

def test_facade_contract(tmp_path):
    c = _client(tmp_path)
    assert c.account_codes() == [ACCT]
    assert c._code_for(ACCT) == ACCT and c._code_for(ACCT[-8:]) == ACCT and c._code_for("nope") is None
    assert c.has_open_position_for_account(ACCT) == (False, "flat")
    hist = c.get_trade_history()
    assert hist[0]["account_name"] == ACCT and hist[0]["balance"] == 5000.0
    assert hist[0]["balance_sod"] == 5000.0
    me = c.get_min_equity(ACCT)
    assert me["min_equity"] == 4850.0 and me["trailing_max_drawdown_limit"] == 4700.0
    assert me["target_equity"] == 5500.0 and me["max_leverage"] == 5.0


# ── executor ──────────────────────────────────────────────────────────

def test_plan_sizes_to_leverage_cap_and_tick_rounds(tmp_path):
    ex = VestExecutor(_client(tmp_path))
    plan = ex.plan_bracket("NDX-USD-PERP", "buy", tp_usd=500, sl_usd=140)
    # 5000 × 0.97 × 5x / 30000 = 0.8083 → floor to 0.0001
    assert plan["quantity"] == pytest.approx(0.8083)
    assert plan["leverage"] == 5.0
    assert plan["margin"] == pytest.approx(0.8083 * 30000 / 5, rel=1e-4)
    assert plan["tp_pts"] == pytest.approx(500 / 0.8083, rel=1e-3)
    assert plan["sl_pts"] == pytest.approx(140 * 0.95 / 0.8083, rel=1e-3)
    assert plan["tp_price"] > 30000 > plan["sl_price"]
    assert (plan["tp_price"] / 0.25) == pytest.approx(round(plan["tp_price"] / 0.25))
    assert plan["quantity_str"] == "0.8083" and plan["vest_side"] == "long"


def test_plan_sell_and_fixed_quantity(tmp_path):
    ex = VestExecutor(_client(tmp_path))
    plan = ex.plan_bracket("NDX-USD-PERP", "sell", tp_usd=10, sl_usd=10, quantity=0.001)
    assert plan["vest_side"] == "short" and plan["quantity_str"] == "0.0010"
    assert plan["tp_price"] < 30000 < plan["sl_price"]
    with pytest.raises(ValueError):
        ex.plan_bracket("NDX-USD-PERP", "buy", tp_usd=1, sl_usd=1, quantity=0.00001)


def test_plan_never_exceeds_capital_leverage_cap(tmp_path):
    ex = VestExecutor(_client(tmp_path))
    plan = ex.plan_bracket("NDX-USD-PERP", "buy", tp_usd=10, sl_usd=10, leverage=50)
    assert plan["leverage"] == 5.0


def test_execute_sends_lowercase_enums_inline_tpsl_and_idempotency_key(tmp_path):
    c = _client(tmp_path)
    ex = VestExecutor(c)
    plan = ex.plan_bracket("NDX-USD-PERP", "buy", tp_usd=10, sl_usd=10, quantity=0.001)
    res = ex.execute(plan)
    body = c._http.open_bodies[0]
    assert body["side"] == "long" and body["orderType"] == "market"
    assert body["leverage"] == "5.000000" and body["quantity"] == "0.0010"
    assert body["takeProfits"][0]["triggerPrice"] == plan["tp_price_str"]
    assert body["stopLosses"][0]["triggerPrice"] == plan["sl_price_str"]
    assert c._http.open_headers[0].get("Idempotency-Key")
    assert res["position_id"] == "p1"


def test_symbol_for_now_weekend_switch(monkeypatch):
    monkeypatch.delenv("VEST_SYMBOL", raising=False)
    assert vc.symbol_for_now(weekday=2) == "NDX-USD-PERP"
    assert vc.symbol_for_now(weekday=6) == "BTC-PERP"
    monkeypatch.setenv("VEST_SYMBOL", "SPX-USD-PERP")
    assert vc.symbol_for_now(weekday=6) == "SPX-USD-PERP"


# ── companion plan hook ───────────────────────────────────────────────

def test_vest_plan_for_row_uses_live_rules(tmp_path):
    app = _app()
    app._on_funded_leg = lambda ev: False
    c = _client(tmp_path)
    row = {"acct_num": ACCT, "eval": {"Prop Firm": "Vest Capital"}, "firm_code": "Vest Capital"}
    executor, code, plan = app._vest_plan_for_row(c, row, "buy")
    assert code == ACCT
    assert plan["blueprint"]["tp_usd"] == 500 and plan["blueprint"]["sl_usd"] == 140
    assert plan["tp_usd"] == 500 and plan["sl_usd"] == pytest.approx(140 * 0.95)
    assert plan["leverage"] == 5.0
