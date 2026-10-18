"""Vest Capital (Vest Markets) connector + companion wiring tests — no network."""

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

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


def test_vest_connection_guard_serializes_the_same_token_file(tmp_path):
    app = _app()
    started = threading.Event()
    release = threading.Event()
    calls = []

    def connect_once(firm, token_file=None, account_id=None, email=None):
        calls.append(token_file)
        started.set()
        release.wait(timeout=2)

    app._connect_vest_broker_once = connect_once
    session = str(tmp_path / "vest.json")
    first = threading.Thread(
        target=app._connect_vest_broker,
        args=("Vest Capital", session, None, "login@example.com"))
    first.start()
    assert started.wait(timeout=1)

    app._connect_vest_broker("Vest Capital", session, None, "login@example.com")

    release.set()
    first.join(timeout=2)
    assert not first.is_alive()
    assert calls == [session]


def test_connect_rebootstraps_when_saved_refresh_chain_is_rejected(tmp_path, monkeypatch):
    app = _app()
    token_file = str(tmp_path / "vest.json")
    app.root = SimpleNamespace(after=lambda _delay, callback: callback())
    app._start_broker_idle_keepalive = lambda: None
    app._start_status_poll = lambda: None
    app._mirror_broker_accounts = lambda *_args: None
    app._reconcile_connected_broker_history = lambda: None
    app._open_vest_observer = lambda *_args: None
    bootstrap_calls = []

    class _ExpiredClient:
        def __init__(self, **_kwargs):
            self.logged_in = True
            self.email = "login@example.com"
            self.token_file = token_file

        def login(self):
            raise VestError("refresh rejected", status=401)

    class _FreshClient:
        account_id = ACCT
        email = "login@example.com"

        def __init__(self):
            self.token_file = token_file

        def login(self):
            return True

        def capital_account(self):
            return dict(CAP)

        def balance(self):
            return 5000.0

    def bootstrap(email, **kwargs):
        bootstrap_calls.append((email, kwargs))
        return _FreshClient()

    monkeypatch.setattr(vc, "VestClient", _ExpiredClient)
    monkeypatch.setattr("trader_companion.vest_login.bootstrap", bootstrap)

    app._connect_vest_broker_once(
        "Vest Capital", token_file=token_file, email="login@example.com")

    assert bootstrap_calls
    assert bootstrap_calls[0][0] == "login@example.com"
    assert app._broker_connections["Vest Capital"]["account"].account_id == ACCT


def test_vest_otp_prompt_runs_on_tk_callback(monkeypatch):
    app = _app()
    app.root = SimpleNamespace(after=lambda _delay, callback: callback())
    monkeypatch.setattr("trader_companion.trader_app.GUI_AVAILABLE", True)
    monkeypatch.setattr("trader_companion.trader_app.simpledialog.askstring",
                        lambda *_args, **_kwargs: "654321")

    assert app._prompt_vest_otp("Enter code") == "654321"


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


# ── blueprint planner (Vest Platinum $25K) ────────────────────────────

CAP25 = {"id": ACCT, "initial_capital": "25000.00000000", "target_equity": "27500.00000000",
         "max_drawdown_limit": "23500.00000000", "daily_loss_floor": "24250.0",
         "daily_reset_balance": "25000.0", "max_leverage": "5.0000", "stage": 1}


def test_vest_rules_platinum_25k():
    r = PropFirmManager().vest_rules_for_balance(25000, live=CAP25)
    assert r["evaluation_goal"] == 27500 and r["static_loss_floor"] == 23500
    assert r["risk_1"] == 700 and r["risk_2_pct"] == 0.03 and r["max_attempts"] == 2
    assert r["funded_target_band"] == [3500, 5000] and r["scale"] == 1.0


def test_vest_rules_scale_to_live_tier():
    r = PropFirmManager().vest_rules_for_balance(5000, live=CAP)
    assert r["scale"] == 0.2 and r["risk_1"] == 140
    assert r["evaluation_goal"] == 5500 and r["static_loss_floor"] == 4700 and r["daily_loss_floor"] == 4850
    assert r["funded_target_band"] == [700, 1000]


def test_vest_eval_attempt1_sl700_tp2500():
    p = PropFirmManager().plan_vest_attempt(equity=25000, balance_sod=25000, starting_balance=25000,
                                            on_funded=False, live=CAP25, attempt_index=0)
    assert p["allowed"] and p["sl_usd"] == 700 and p["tp_usd"] == 2500 and p["attempt"] == 1


def test_vest_eval_attempt2_uses_3pct_of_reset_and_tp_grows_by_loss():
    live = dict(CAP25, daily_loss_floor="23571.0")   # 24300 − 729
    p = PropFirmManager().plan_vest_attempt(equity=24300, balance_sod=24300, starting_balance=25000,
                                            on_funded=False, live=live, attempt_index=1)
    assert p["allowed"] and p["sl_usd"] == 729 and p["tp_usd"] == 3200 and p["attempt"] == 2


def test_vest_attempt2_never_breaches_static_floor():
    # Hypothetical: equity only $500 above the static floor — stop is capped there.
    live = dict(CAP25, daily_loss_floor="23000.0")
    p = PropFirmManager().plan_vest_attempt(equity=24000, balance_sod=24000, starting_balance=25000,
                                            on_funded=False, live=live, attempt_index=1)
    assert p["allowed"] and p["sl_usd"] == 500


def test_vest_blocks_third_attempt_and_same_day_repeat():
    m = PropFirmManager()
    assert "retired" in m.plan_vest_attempt(equity=23571, balance_sod=23571, starting_balance=25000,
                                            on_funded=False, live=CAP25, attempt_index=2)["reason"]
    assert "daily reset" in m.plan_vest_attempt(equity=25000, balance_sod=25000, starting_balance=25000,
                                                on_funded=False, live=CAP25, traded_today=True)["reason"]


def test_vest_blocks_at_target():
    assert not PropFirmManager().plan_vest_attempt(equity=27500, balance_sod=27500, starting_balance=25000,
                                                   on_funded=False, live=CAP25)["allowed"]


def test_vest_funded_T_drawn_in_band_whole_dollars_not_multiple_of_100():
    m = PropFirmManager()
    seen = set()
    for i in range(200):
        T = m.vest_cycle_target("acct", i)
        assert 3500 <= T <= 5000 and T == int(T) and T % 100 != 0
        seen.add(T)
    assert len(seen) > 50


def test_vest_funded_T_is_stable_per_cycle_and_redrawn_next_cycle():
    m = PropFirmManager()
    t0 = m.vest_cycle_target("acct", 0)
    assert m.vest_cycle_target("acct", 0) == t0
    p = m.plan_vest_attempt(equity=25000, balance_sod=25000, starting_balance=25000,
                            on_funded=True, live=CAP25, account_key="acct", cycle_index=0)
    assert p["T"] == t0 and p["tp_usd"] == t0 and p["sl_usd"] == 700
    assert p["payout_cash"] == pytest.approx(0.8 * t0)
    p2 = m.plan_vest_attempt(equity=24300, balance_sod=24300, starting_balance=25000,
                             on_funded=True, live=dict(CAP25, daily_loss_floor="23571"),
                             account_key="acct", cycle_index=0, attempt_index=1)
    assert p2["T"] == t0 and p2["tp_usd"] == t0 + 700 and p2["sl_usd"] == 729
    assert m.vest_cycle_target("acct", 1) != t0 or m.vest_cycle_target("acct", 2) != t0


def test_vest_funded_T_scales_with_tier():
    m = PropFirmManager()
    T = m.vest_cycle_target("small", 0, scale=0.2)
    assert 700 <= T <= 1000


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

def test_vest_plan_for_row_uses_platinum_rules_scaled_to_tier(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "trader_companion.trader_app.kenya_now",
        lambda: datetime(2026, 10, 14, tzinfo=timezone.utc),
    )
    app = _app()
    app._on_funded_leg = lambda ev: False
    app._funded_payout_count = lambda ev: 0
    c = _client(tmp_path)
    row = {"acct_num": ACCT, "eval": {"Prop Firm": "Vest Capital"}, "firm_code": "Vest Capital"}
    executor, code, plan = app._vest_plan_for_row(c, row, "buy")
    assert code == ACCT
    bp = plan["blueprint"]
    # $5K tier = 0.2 × Platinum: attempt-1 risk $140, eval TP $500
    assert bp["attempt"] == 1 and bp["tp_usd"] == 500 and bp["sl_usd"] == 140
    assert plan["tp_usd"] == 500 and plan["sl_usd"] == pytest.approx(140 * 0.95)
    assert plan["leverage"] == 5.0


def test_vest_plan_for_row_blocks_second_attempt_same_day(tmp_path):
    app = _app()
    app._on_funded_leg = lambda ev: False
    app._funded_payout_count = lambda ev: 0
    c = _client(tmp_path)
    app._mark_vest_attempt(ACCT)
    row = {"acct_num": ACCT, "eval": {"Prop Firm": "Vest Capital"}, "firm_code": "Vest Capital"}
    with pytest.raises(RuntimeError, match="daily reset"):
        app._vest_plan_for_row(c, row, "buy")
