"""Breakout walkthrough through the companion's own code path, on the open terminal tab.

    python -m trader_companion.breakout_e2e --side buy --hold 90 [--quantity 0.01] [--force]

--force skips the one-attempt-per-daily-window gate (test trades only).
"""

import argparse
import json
import os
import sys
import time

from trader_companion.prop_firm_manager import PropFirmManager
from trader_companion.trader_app import TradeOpssAIApp
from trader_companion.breakout_connector import BreakoutExecutor, symbol_for_now

LINE = "─" * 78


def step(t):
    print(f"\n{LINE}\n▶ {t}\n{LINE}")


class _Root:
    def after(self, _ms, fn=None, *a):
        if fn:
            fn(*a)


def _app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    app._broker_connections = {}
    app.root = _Root()
    app.log = lambda m, level="INFO": print(f"  [{level}] {m}")
    for n in ("_start_broker_idle_keepalive", "_start_status_poll",
              "_reconcile_connected_broker_history", "_snapshot_pre_trade_balance"):
        setattr(app, n, lambda *a, **k: None)
    app._breach_floor_by_account = {}
    app._active_trade_rows = []
    app._record_breach_floor = lambda acct, floor, on_funded=False: print(
        f"  [FLOOR] {acct} breach floor recorded at ${floor:,.2f}")
    app._mark_trade_in_progress = lambda ev: ev.__setitem__("Status P1", "In Progress")
    app._on_funded_leg = lambda ev: False
    app._funded_payout_count = lambda ev: 0
    return app


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--side", choices=["buy", "sell"], default="buy")
    p.add_argument("--quantity", type=float, default=None)
    p.add_argument("--hold", type=int, default=90)
    p.add_argument("--force", action="store_true")
    p.add_argument("--email", default=os.environ.get("BREAKOUT_EMAIL", "joehickenfpf@gmail.com"))
    a = p.parse_args()

    step("1. CONNECT — companion attaches to the open Breakout terminal tab")
    app = _app()
    app._connect_breakout_broker("Breakout", a.email)
    sess = app._breakout_session()
    if sess is None:
        return 1
    code = sess.get_active_account()

    step("2. SCAN")
    h = sess.get_trade_history()[0]
    me = sess.get_min_equity(code)
    print(f"  account {code}  balance ${h['balance']:,.2f}  SOD ${h['balance_sod']:,.2f}")
    print(f"  floors: max-DD {me['trailing_max_drawdown_limit']}  daily {me['daily_loss_floor']}  "
          f"→ room ${me['drawdown_remaining']:,.2f}   target {me['target_equity']}   reset {me['daily_reset_at']}")
    print(f"  open position: {sess.has_open_position_for_account(code)}   traded this window: "
          f"{app._breakout_traded_today(sess, code)}")

    step(f"3. PLAN — Classic 1-Step spec scaled to this account ({a.side.upper()})")
    if a.force:
        app._breakout_traded_today = lambda s, c: False
    rules = app.prop_firm_mgr.firm_blueprints["Breakout"].setdefault("rules", {})
    if a.quantity:
        rules["breakout_quantity"] = a.quantity
    row = {"acct_num": code, "firm_code": "Breakout",
           "eval": {"Prop Firm": "Breakout", "Status P1": "Not Started"}, "frame": None}
    try:
        executor, code, plan = app._breakout_plan_for_row(sess, row, a.side)
    except Exception as exc:
        print("  BLOCKED:", exc)
        return 2
    bp = plan["blueprint"]
    print(f"  stage {bp['stage']}  attempt {bp['attempt']}  all-in budget ${bp['risk_budget']:,.2f}  "
          f"cost ${bp['cost']:,.2f}")
    print(f"  price stop ${bp['sl_usd']:,.2f} → bracket SL ${plan['sl_usd']:,.2f} (×0.95 buffer)   "
          f"price target ${bp['tp_usd']:,.2f}")
    print(f"  {plan['symbol']} @ {plan['ref_price']:,.2f}  size {plan['quantity_str']}  "
          f"({plan['leverage']:g}x, notional ${plan['notional']:,.0f}, margin ${plan['margin']:,.0f})")
    print(f"  TP {plan['tp_price_str']} (+{plan['tp_pts']:,.1f} pts)   SL {plan['sl_price_str']} (-{plan['sl_pts']:,.1f} pts)")

    step("4. EXECUTE — _auto_execute_breakout_row")
    input("  Press Enter to place the trade (watch the Positions panel in the terminal)… ")
    t0 = time.time()
    ok = app._auto_execute_breakout_row(row, a.side)
    print(f"  result: {'FILLED' if ok else 'FAILED'} in {time.time()-t0:.1f}s   row status: {row['eval'].get('Status P1')}")
    if not ok:
        return 3

    step("5. VERIFY")
    time.sleep(2)
    print("  has_open:", sess.has_open_position_for_account(code))
    for t in sess.trades(code)[:3]:
        print(f"  fill {t.get('transaction_id')}  {t.get('type')} {t.get('volume')} {t.get('pair')} @ {t.get('price')}  "
              f"fee {t.get('fee')}  status {t.get('position_status')}  misc {t.get('misc')}")
    ov = sess.api.overview(code).get("summary", {})
    print(f"  equity {ov['equity']['amount']}  upnl {ov['upnl']['amount']}  used margin {ov['used_margin']['amount']}")

    step(f"6. HOLD {a.hold}s (Ctrl-C to flatten early)")
    end = time.time() + a.hold
    try:
        while time.time() < end:
            time.sleep(15)
            is_open, label = sess.has_open_position_for_account(code)
            if not is_open:
                print("  position closed by TP/SL while holding")
                break
            ov = sess.api.overview(code).get("summary", {})
            print(f"  {time.strftime('%H:%M:%S')}  mark {sess.mark_price(plan['symbol']):,.2f}  "
                  f"upnl {float(ov['upnl']['amount']):+.2f}  ({int(end-time.time())}s left)")
    except KeyboardInterrupt:
        print("  …flattening early")

    step("7. FLATTEN + RECONCILE")
    input("  Press Enter to flatten… ")
    print("  flatten():", json.dumps(executor.flatten(), default=str)[:300])
    time.sleep(3)
    print("  has_open:", sess.has_open_position_for_account(code))
    h = sess.get_trade_history()[0]
    print(f"  balance now ${h['balance']:,.2f}")
    sess.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
