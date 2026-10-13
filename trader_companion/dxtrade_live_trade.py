"""Place one DXtrade bracket using the price read from the Chrome terminal.

Chrome logs in (persistent profile), the live BTC/USD top-of-book is scraped
from the Market Depth widget, SL/TP are derived from it, and the bracket is
sent through the REST API (IF-THEN group: MARKET + STOP + LIMIT).

    python -m trader_companion.dxtrade_live_trade --side buy --qty 0.01 \
        --sl-pct 1.0 --tp-pct 2.0            # dry run (prints the order)
    python -m trader_companion.dxtrade_live_trade ... --yes   # places it
"""

import argparse
import json
import logging
import time

from dotenv import load_dotenv

from trader_companion.dxtrade_browser import DXTradeBrowserSession
from trader_companion.dxtrade_connector import DXTradeError


def main():
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", default="BTC/USD")
    p.add_argument("--side", choices=["buy", "sell"], default="buy")
    p.add_argument("--qty", type=float, default=0.01)
    p.add_argument("--sl-pct", type=float, default=1.0)
    p.add_argument("--tp-pct", type=float, default=2.0)
    p.add_argument("--sl", type=float, default=None, help="explicit SL price")
    p.add_argument("--tp", type=float, default=None, help="explicit TP price")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--hold", type=int, default=20, help="seconds to keep Chrome open after")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    sess = DXTradeBrowserSession.from_env()
    sess.login(api_login=True)
    api = sess.api
    if not api.logged_in:
        print("REST session not established — cannot trade")
        sess.close()
        return 1
    codes = api.list_account_codes()
    account = codes[0]
    time.sleep(6)  # let the Market Depth widget stream

    q = sess.quote(a.symbol)  # switches the depth widget to the symbol if needed
    print(f"Terminal quote {a.symbol}: bid={q['bid']} ask={q['ask']} mid={q['mid']}")

    # Real margin rate for this instrument on this account (0.2 = 5:1, 0.5 = 2:1).
    margin_rate = 0.2
    try:
        det = api._get(f"/accounts/{api._acct(account)}/instruments/"
                       + a.symbol.replace('/', '%2F')).get("instrumentDetails")
        det = det[0] if isinstance(det, list) and det else det
        margin_rate = float(det["marginRate"]["tiers"][0]["value"])
        print(f"Instrument: minSize={det.get('minOrderSize')} step={det.get('minOrderSizeIncrement')} "
              f"marginRate={margin_rate} (={1/margin_rate:.0f}:1) status={det.get('tradingStatus')}")
    except Exception as exc:
        print(f"(could not read instrument details: {exc}; assuming marginRate={margin_rate})")

    ref = q["ask"] if a.side == "buy" else q["bid"]
    sgn = 1 if a.side == "buy" else -1
    sl = a.sl if a.sl is not None else round(ref * (1 - sgn * a.sl_pct / 100), 2)
    tp = a.tp if a.tp is not None else round(ref * (1 + sgn * a.tp_pct / 100), 2)

    m = api.get_metrics(account)
    print(f"Account {account}: balance={m.get('balance')} equity={m.get('equity')} "
          f"available={m.get('availableBalance')}")
    notional = ref * a.qty
    print("\nBRACKET TO SEND:")
    print(f"  {a.side.upper()} {a.qty} {a.symbol} @~{ref}  notional≈${notional:,.2f} "
          f"margin≈${notional * margin_rate:,.2f} ({1/margin_rate:.0f}:1)")
    print(f"  SL={sl}  (risk≈${abs(ref - sl) * a.qty:,.2f})")
    print(f"  TP={tp}  (reward≈${abs(tp - ref) * a.qty:,.2f})")

    if not a.yes:
        print("\nDry run — re-run with --yes to place.")
        sess.close()
        return 0

    try:
        resp = api.place_bracket(account, instrument=a.symbol, side=a.side,
                                 quantity=a.qty, stop_price=sl, limit_price=tp,
                                 metadata={"source": "tradeops", "mode": "test"})
    except DXTradeError as e:
        print(f"\nREJECTED: {e}")
        print(json.dumps(e.payload, indent=2))
        sess.close()
        return 1
    print("\nACCEPTED:", json.dumps(resp))

    pos = api.wait_for_position(account, timeout_sec=20)
    print(f"\n{len(pos)} open position(s):")
    for pz in pos:
        print("  ", {k: pz.get(k) for k in ("positionCode", "symbol", "side", "quantity",
                                            "openPrice", "stopLossPrice", "takeProfitPrice")})
    orders = api.list_open_orders(account)
    print(f"{len(orders)} working order(s):")
    for o in orders:
        print("  ", {k: o.get(k) for k in ("orderCode", "orderId", "type", "side", "status",
                                           "quantity", "stopPrice", "limitPrice")})
    m2 = api.get_metrics(account)
    print(f"\nAfter: balance={m2.get('balance')} equity={m2.get('equity')} "
          f"openPnL={m2.get('openPnL')} margin={m2.get('margin')}")

    if a.hold:
        print(f"\nHolding Chrome open {a.hold}s so you can see the position…")
        time.sleep(a.hold)
    sess.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
