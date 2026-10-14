"""Breakout e2e through the companion's dashboard data path (no Tk).

Feeds a dashboard-shaped payload (prop_accounts + evaluations) through the same
functions the companion runs on "Load trades": _partition_evaluations_for_scan →
_populate_broker_rows (connects Breakout from the dashboard email, hands-off
sign-in) → _auto_execute_breakout_row (blueprint plan + bracket) → flatten.

    python -m trader_companion.breakout_dashboard_e2e --email harry@... --account WFAU-... \
        [--firm "Breakout Turbo"] [--hold 60] [--no-trade]
"""

import argparse
import json
import os
import sys
import time

from trader_companion import trader_app as ta
from trader_companion.prop_firm_manager import PropFirmManager
from trader_companion.trader_app import TradeOpssAIApp, kenya_today

LINE = "─" * 78


def step(t):
    print(f"\n{LINE}\n▶ {t}\n{LINE}")


class _Root:
    def after(self, _ms, fn=None, *a):
        if fn:
            fn(*a)


def _app():
    ta.CTK_AVAILABLE = False
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    app._broker_connections = {}

    class _Frame:                       # Tk stand-in for the broker rows container
        def winfo_children(self): return []
        def pack(self, *a, **k): pass
    app._broker_rows_frame = _Frame()
    app.root = _Root()
    app.log = lambda m, level="INFO": print(f"  [{level}] {m}")
    for n in ("_start_broker_idle_keepalive", "_start_status_poll", "_reconcile_connected_broker_history",
              "_snapshot_pre_trade_balance", "_start_perps_md_feed", "_auto_connect_populated_brokers"):
        setattr(app, n, lambda *a, **k: None)
    app._breach_floor_by_account = {}
    app._active_trade_rows = []
    app._record_breach_floor = lambda acct, floor, on_funded=False: print(
        f"  [FLOOR] {acct} breach floor recorded at ${floor:,.2f}")
    app._mark_trade_in_progress = lambda ev: ev.__setitem__("Status P1", "In Progress")
    app._funded_payout_count = lambda ev: 0
    return app


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--email", default=os.environ.get("BREAKOUT_EMAIL", "harryodhiambo17@gmail.com"))
    p.add_argument("--account", required=True)
    p.add_argument("--firm", default="Breakout Turbo")
    p.add_argument("--side", choices=["buy", "sell"], default="buy")
    p.add_argument("--hold", type=int, default=60)
    p.add_argument("--no-trade", action="store_true")
    a = p.parse_args()

    today_wd = kenya_today().weekday()
    day = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"][today_wd]
    payload = {
        "prop_accounts": [{"prop_firm": a.firm, "breakout_email": a.email}],
        "evaluations": [{"Prop Firm": a.firm, "Account #": a.account, "Account Size": "$5,000",
                         "Status P1": "Not Started", "Hedge Result 1": day,
                         "Date Started": kenya_today().isoformat()}],
    }
    step("1. DASHBOARD PAYLOAD (what /api/client/data returns after you add the account)")
    print(json.dumps(payload, indent=1))

    app = _app()
    step("2. SCAN — _partition_evaluations_for_scan")
    active, connect, skipped = app._partition_evaluations_for_scan(payload["evaluations"], today_wd)
    print(f"  active today: {[e['Account #'] for e in active]}   connect: {len(connect)}   skipped: {skipped}")
    if not active:
        print("  nothing active — check the day placeholder/status"); return 2

    step("3. BROKER ROWS — _populate_broker_rows (connects from the dashboard email)")
    app._populate_broker_rows(connect, payload["prop_accounts"], priority_firms=[a.firm])
    for _ in range(300):
        time.sleep(1)
        if app._breakout_session() is not None:
            break
    sess = app._breakout_session()
    print("  connected:", sess is not None, "| family key:", app._broker_login_family(a.firm),
          "| conn keys:", list(app._broker_connections))
    if sess is None:
        return 3
    code = sess._code_for(a.account)
    me = sess.get_min_equity(code)
    print(f"  account {code}  balance ${me['net_liq']:,.2f}  floors {me['trailing_max_drawdown_limit']}/{me['daily_loss_floor']}  target {me['target_equity']}")

    step("4. ROW + PLAN — exactly what the trade row carries")
    ev = active[0]
    firm_code = app._FIRM_MAP.get(ev["Prop Firm"], ev["Prop Firm"])
    row = {"acct_num": a.account, "firm_code": firm_code, "eval": ev, "frame": None,
           "acct_size": ev["Account Size"], "current_phase": "Challenge"}
    print(f"  firm_code {firm_code} | platform {app._platform_for_firm(firm_code, default='Tradovate')} | api-only {app._is_api_only_firm(firm_code)}")
    try:
        executor, code, plan = app._breakout_plan_for_row(sess, row, a.side)
    except Exception as exc:
        print("  BLOCKED:", exc); return 4
    bp = plan["blueprint"]
    print(f"  blueprint {bp['blueprint']} ({bp['kind']})  stage {bp['stage']}  attempt {bp['attempt']}  "
          f"budget ${bp['risk_budget']}  cost ${bp['cost']}  → stop ${bp['sl_usd']} / target ${bp['tp_usd']}")
    print(f"  {plan['symbol']} @ {plan['ref_price']:,.2f}  size {plan['quantity_str']}  TP {plan['tp_price_str']}  SL {plan['sl_price_str']}")
    if a.no_trade:
        print("  --no-trade: stopping here"); return 0

    step("5. EXECUTE — _auto_execute_breakout_row")
    ok = app._auto_execute_breakout_row(row, a.side)
    print("  result:", "FILLED" if ok else "FAILED", "| row status:", ev.get("Status P1"))
    if not ok:
        return 5
    time.sleep(2)
    print("  has_open:", sess.has_open_position_for_account(code))

    step(f"6. HOLD {a.hold}s then FLATTEN")
    end = time.time() + a.hold
    while time.time() < end:
        time.sleep(15)
        is_open, _ = sess.has_open_position_for_account(code)
        if not is_open:
            print("  closed by TP/SL"); break
        ov = sess.api.overview(code).get("summary", {})
        print(f"  {time.strftime('%H:%M:%S')} upnl {float(ov['upnl']['amount']):+.2f}")
    print("  flatten():", json.dumps(executor.flatten(), default=str)[:200])
    time.sleep(3)
    print("  has_open:", sess.has_open_position_for_account(code), "| stats:", sess.get_account_stats())
    sess.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
