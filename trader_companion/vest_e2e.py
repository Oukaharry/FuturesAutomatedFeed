"""End-to-end Vest Capital walkthrough using the companion's own code paths.

Headless connect from the saved token chain → account scan → blueprint plan →
live bracket → status reconciliation → optional hold → flatten. Mirrors
TradeOpssAIApp._connect_vest_broker / _vest_plan_for_row / _auto_execute_vest_row.

    python -m trader_companion.vest_e2e --side buy --hold 120 [--quantity 0.001] [--keep]

--observe opens Chrome on the Vest trade page first and runs the trade through
the BROWSER's session token (read off its network log), so the position, TP/SL
and close appear live in the UI without the two sessions fighting over one
refresh chain. The bot's own token file is left untouched.

    python -m trader_companion.vest_e2e --observe --side buy --hold 180
"""

import argparse
import json
import logging
import os
import sys
import tempfile
import threading
import time

from trader_companion.prop_firm_manager import PropFirmManager
from trader_companion.trader_app import TradeOpssAIApp
from trader_companion.vest_connector import VestClient, VestExecutor

LINE = "─" * 78


def step(title):
    print(f"\n{LINE}\n▶ {title}\n{LINE}")


def _observer_client(email, symbol, profile):
    """Open Chrome (logged in), borrow its freshest account token, return (client, driver)."""
    import trader_companion.vest_probe as probe
    from trader_companion.vest_login import _harvest

    probe.OUT = os.path.join(tempfile.gettempdir(), "vest_observe_capture")
    os.makedirs(probe.OUT, exist_ok=True)
    rest = os.path.join(probe.OUT, "rest.jsonl")
    for name in ("rest.jsonl", "ws.jsonl"):
        try:
            os.remove(os.path.join(probe.OUT, name))
        except OSError:
            pass
    d = probe._driver(profile)
    cap = probe.Capture(d).start()
    ok = probe.email_login(d, email, symbol)
    if not ok:
        raise SystemExit("Chrome login did not complete")
    print("  waiting for the browser to mint its account token…")
    user = account = None
    for _ in range(45):
        user, account = _harvest(rest)
        if account:
            break
        time.sleep(1)
    if not account:
        # Nudge the app: a reload makes it refresh + mint again.
        d.refresh()
        for _ in range(30):
            user, account = _harvest(rest)
            if account:
                break
            time.sleep(1)
    if not account:
        raise SystemExit("could not read the browser's account token from its traffic")
    client = VestClient(token_file=os.path.join(probe.OUT, "observer_session.json"))
    client.import_tokens(user=user, account=account)
    exp_min = (account.get("accessExpiresAtMs", 0) - time.time() * 1000) / 60000
    print(f"  borrowed browser account token for {account.get('accountId')} "
          f"(valid {exp_min:.1f} min — no refresh needed for this run)")
    client._observer_capture = cap
    return client, d


class _Root:
    """Minimal Tk-root stand-in: run callbacks inline, in order."""

    def after(self, _ms, fn=None, *a):
        if fn:
            fn(*a)


def _headless_app():
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    app._broker_connections = {}
    app.root = _Root()
    app.log = lambda msg, level="INFO": print(f"  [{level}] {msg}")
    # No-ops for GUI-only bookkeeping the connect path schedules.
    for name in ("_start_broker_idle_keepalive", "_start_status_poll",
                 "_reconcile_connected_broker_history", "_snapshot_pre_trade_balance"):
        setattr(app, name, lambda *a, **k: None)
    app._breach_floor_by_account = {}
    app._active_trade_rows = []
    app._record_breach_floor = lambda acct, floor, on_funded=False: print(
        f"  [FLOOR] {acct[:8]}… breach floor recorded at ${floor:,.2f} (funded={on_funded})")
    app._mark_trade_in_progress = lambda ev: ev.__setitem__("Status P1", "In Progress")
    app._on_funded_leg = lambda ev: False
    return app


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--side", choices=["buy", "sell"], default="buy")
    p.add_argument("--quantity", type=float, default=None,
                   help="fixed size (e.g. 0.001); default = blueprint sizing at the leverage cap")
    p.add_argument("--hold", type=int, default=120, help="seconds to hold before flattening")
    p.add_argument("--keep", action="store_true", help="leave the position open (do not flatten)")
    p.add_argument("--observe", action="store_true",
                   help="open Chrome on Vest and trade through the browser's session so you can watch")
    p.add_argument("--email", default=os.environ.get("VEST_EMAIL", "joehickenfpf@gmail.com"))
    p.add_argument("--profile", default="vest_observe_" + str(int(time.time())),
                   help="Chrome profile key (fresh by default so a stale session never blocks login)")
    a = p.parse_args()
    logging.basicConfig(level=logging.WARNING)

    driver = None
    if a.observe:
        step("1. LOGIN — Chrome on next.vestmarkets.com (watch here); bot borrows the browser session")
        client, driver = _observer_client(a.email, "NDX-USD-PERP", a.profile)
        client.login = lambda: True   # never rotate the browser's chain from here
        print("  Chrome stays open — keep the Positions panel in view.")
    else:
        step("1. LOGIN — headless, from the persisted token chain (no Chrome)")
        client = VestClient()
        print(f"  token file : {client.token_file}")
        print(f"  logged_in  : {client.logged_in}  (account access expires in "
              f"{(client.account.get('accessExpiresAtMs', 0) - time.time()*1000)/60000:.1f} min)")
        t0 = time.time()
        client.login()
        print(f"  login()    : OK in {time.time()-t0:.2f}s → Bearer account token ready")

    step("2. CONNECT — companion registers Vest Capital as a broker")
    app = _headless_app()
    if a.observe:
        app._broker_connections["Vest Capital"] = {"account": client, "creds_source": "browser"}
        app.log(f"🔑 Vest Capital connected (browser session) — account {client.account_id} "
                f"(${client.balance():,.2f})")
    else:
        app._connect_vest_broker("Vest Capital")
    conn = app._vest_client()
    assert conn is not None, "connect failed"
    print(f"  _vest_client()           : {type(conn).__name__} for {conn.account_id}")
    print(f"  _platform_for_firm       : {app._platform_for_firm('Vest Capital', default='Tradovate')}")
    print(f"  _is_api_only_firm        : {app._is_api_only_firm('Vest Capital')}")

    step("3. SCAN — account truth the companion reads before trading")
    hist = conn.get_trade_history()[0]
    me = conn.get_min_equity(conn.account_id)
    cap = conn.capital_account()
    print(f"  balance / SOD            : ${hist['balance']:,.2f} / ${hist['balance_sod']:,.2f}")
    print(f"  plan                     : {cap.get('plan_name')}")
    print(f"  target equity            : ${me['target_equity']:,.2f}")
    print(f"  daily-loss floor         : ${me['daily_loss_floor']:,.2f}")
    print(f"  max-drawdown floor       : ${me['trailing_max_drawdown_limit']:,.2f}")
    print(f"  min_equity (binding)     : ${me['min_equity']:,.2f}  room ${me['drawdown_remaining']:,.2f}")
    print(f"  leverage cap             : {me['max_leverage']:g}x")
    print(f"  open position?           : {conn.has_open_position_for_account(conn.account_id)}")
    print(f"  daily P&L history        : {json.dumps(hist['daily_pnl'])}")

    step(f"4. PLAN — blueprint → $ targets → price levels ({a.side.upper()})")
    row = {"acct_num": conn.account_id, "firm_code": "Vest Capital",
           "eval": {"Prop Firm": "Vest Capital", "Status P1": "Not Started"}, "frame": None}
    if a.quantity is not None:
        app.prop_firm_mgr.firm_blueprints["Vest Capital"]["rules"] = {"vest_quantity": a.quantity}
    executor, code, plan = app._vest_plan_for_row(conn, row, a.side)
    bp = plan["blueprint"]
    print(f"  blueprint stage          : {bp['stage']}  allowed={bp['allowed']}")
    print(f"  blueprint $ plan         : TP +${bp['tp_usd']:,.2f}  SL -${bp['sl_usd']:,.2f} "
          f"(daily room ${bp['daily_room']:,.2f}, static room ${bp['static_room']:,.2f})")
    print(f"  symbol / ref price       : {plan['symbol']} @ {plan['ref_price']:,.2f}")
    print(f"  size                     : {plan['quantity_str']} ({plan['leverage']:g}x, "
          f"notional ${plan['notional']:,.2f}, margin ${plan['margin']:,.2f})")
    print(f"  TP level                 : {plan['tp_price_str']}  (+{plan['tp_pts']:,.2f} pts = +${plan['tp_usd']:,.2f})")
    print(f"  SL level                 : {plan['sl_price_str']}  (-{plan['sl_pts']:,.2f} pts = -${plan['sl_usd']:,.2f})")

    step("5. EXECUTE — companion auto-trade path (_auto_execute_vest_row)")
    if a.observe:
        input("  Press Enter to place the trade (watch the Positions panel in Chrome)… ")
    t0 = time.time()
    ok = app._auto_execute_vest_row(row, a.side)
    print(f"  result                   : {'FILLED' if ok else 'FAILED'} in {time.time()-t0:.2f}s")
    print(f"  row status after fill    : {row['eval'].get('Status P1')}")
    if not ok:
        return 1

    step("6. VERIFY — what the exchange reports")
    time.sleep(2)
    pos = conn.open_positions()
    for q in pos:
        print(f"  position {q['positionId'][:8]}…  {q['side']} {q['quantity']} {q['symbol']} "
              f"@ {float(q['openPrice']):,.2f}  pnl {q['pnl']}  fee {q['fee']}  collateral {q['collateral']}")
        for s in q.get("stopLosses", []):
            print(f"     SL  {float(s['triggerPrice']):,.2f}  [{s['status']}]")
        for t in q.get("takeProfits", []):
            print(f"     TP  {float(t['triggerPrice']):,.2f}  [{t['status']}]")
    print(f"  has_open_position        : {conn.has_open_position_for_account(conn.account_id)}")

    if a.keep:
        print("\n  --keep set: leaving the position open with its TP/SL.")
        _finish(driver)
        return 0

    step(f"7. HOLD {a.hold}s — watch it live on next.vestmarkets.com, then flatten")
    if a.observe:
        print("  (press Ctrl-C at any time to flatten early)")
    end = time.time() + a.hold
    try:
        while time.time() < end:
            time.sleep(min(15, max(1, end - time.time())))
            pos = conn.open_positions()
            if not pos:
                print("  position closed by TP/SL while holding")
                break
            q = pos[0]
            mark = conn.mark_price(q["symbol"])
            print(f"  {time.strftime('%H:%M:%S')}  mark {mark:,.2f}  unrealised {float(q['pnl']):+.4f}  "
                  f"({int(end-time.time())}s left)")
    except KeyboardInterrupt:
        print("  …flattening early")

    step("8. FLATTEN + RECONCILE")
    if a.observe:
        input("  Press Enter to flatten (watch the position close in Chrome)… ")
    print(f"  flatten()                : {executor.flatten()}")
    time.sleep(3)
    print(f"  has_open_position        : {conn.has_open_position_for_account(conn.account_id)}")
    closed = conn.closed_positions(since_ms=int((time.time() - 600) * 1000))
    for q in closed[:1]:
        print(f"  closed {q['positionId'][:8]}…  open {float(q['openPrice']):,.2f} → close "
              f"{float(q['closePrice']):,.2f}  pnl {float(q['pnl']):+.4f}  fee {q['fee']}  reason {q.get('closeReason')}")
    hist = conn.get_trade_history()[0]
    print(f"  balance now              : ${hist['balance']:,.2f}   today: {json.dumps(hist['daily_pnl'][-1:])}")
    _finish(driver)
    return 0


def _finish(driver):
    if driver is None:
        return
    try:
        input("\n  Done. Press Enter to close Chrome… ")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
