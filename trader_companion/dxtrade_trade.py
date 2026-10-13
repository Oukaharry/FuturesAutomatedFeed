"""DXtrade trading CLI — discover, quote, open a bracket, inspect, close.

Uses the REST session (token auth) with credentials from .env. Every
mutating command prints exactly what it will send and requires --yes.

    python -m trader_companion.dxtrade_trade accounts
    python -m trader_companion.dxtrade_trade instruments [--filter BTC]
    python -m trader_companion.dxtrade_trade quote <ACCOUNT> <SYMBOL>
    python -m trader_companion.dxtrade_trade positions <ACCOUNT>
    python -m trader_companion.dxtrade_trade open <ACCOUNT> <SYMBOL> buy|sell <QTY> \
        [--sl PRICE] [--tp PRICE] [--sl-pct 1.0] [--tp-pct 2.0] --yes
    python -m trader_companion.dxtrade_trade close <ACCOUNT> <POSITION_CODE> --yes
    python -m trader_companion.dxtrade_trade close-all <ACCOUNT> --yes
"""

import argparse
import json
import sys

from dotenv import load_dotenv

from trader_companion.dxtrade_browser import credentials_from_env
from trader_companion.dxtrade_connector import DXTradeClient, DXTradeError


def _client() -> DXTradeClient:
    load_dotenv()
    c = credentials_from_env()
    if not c["username"] or not c["password"]:
        sys.exit("Missing DXTRADE_USERNAME / DXTRADE_PASSWORD in .env")
    api = DXTradeClient(c["host"], c["username"], c["password"], domain=c["domain"])
    api.login()
    return api


def _pj(obj, limit=6000):
    s = json.dumps(obj, indent=2, default=str)
    print(s if len(s) <= limit else s[:limit] + f"\n… ({len(s) - limit} more chars)")


def cmd_accounts(api, _a):
    users = api.get_users()
    _pj(users)
    codes = api.list_account_codes()
    print(f"\nAccount codes: {codes}")
    for code in codes:
        m = api.get_metrics(code)
        print(f"[{code}] balance={m.get('balance')} equity={m.get('equity')} "
              f"available={m.get('availableBalance')} openPnL={m.get('openPnL')}")


def cmd_instruments(api, a):
    items = api.list_instruments(symbols=a.symbols, types=a.types, limit=a.limit)
    flt = (a.filter or "").lower()
    rows = []
    for it in items:
        sym = str(it.get("symbol") or it.get("name") or "")
        if flt and flt not in sym.lower() and flt not in json.dumps(it).lower():
            continue
        rows.append(it)
    print(f"{len(rows)} instrument(s)" + (f" matching '{a.filter}'" if flt else ""))
    for it in rows[: a.limit]:
        keys = ("symbol", "type", "description", "lotSize", "minOrderSize",
                "maxOrderSize", "orderSizeStep", "pipSize", "priceIncrement",
                "currency", "tradingHours")
        print({k: it.get(k) for k in keys if k in it})
    if rows and a.raw:
        _pj(rows[0])


def cmd_quote(api, a):
    q = api.get_quote(a.account, a.symbol)
    _pj(q)


def cmd_positions(api, a):
    pos = api.list_positions(a.account)
    print(f"{len(pos)} open position(s)")
    for p in pos:
        print({k: p.get(k) for k in ("positionCode", "symbol", "side", "quantity",
                                    "openPrice", "stopLossPrice", "takeProfitPrice",
                                    "openTime")})
    orders = api.list_open_orders(a.account)
    print(f"{len(orders)} working order(s)")
    for o in orders:
        print({k: o.get(k) for k in ("orderCode", "orderId", "type", "side", "status",
                                    "quantity", "stopPrice", "limitPrice", "positionCode")})


def _derive_prices(api, a):
    sl, tp = a.sl, a.tp
    if (a.sl_pct or a.tp_pct) and (sl is None or tp is None):
        q = api.get_quote(a.account, a.symbol) or {}
        bid, ask = q.get("bid"), q.get("ask")
        if bid is None or ask is None:
            sys.exit(f"No quote for {a.symbol}; pass --sl/--tp explicitly. Quote={q}")
        ref = float(ask) if a.side == "buy" else float(bid)
        sgn = 1 if a.side == "buy" else -1
        if sl is None and a.sl_pct:
            sl = round(ref * (1 - sgn * a.sl_pct / 100.0), 6)
        if tp is None and a.tp_pct:
            tp = round(ref * (1 + sgn * a.tp_pct / 100.0), 6)
        print(f"ref price={ref} (bid={bid} ask={ask}) → sl={sl} tp={tp}")
    return sl, tp


def cmd_open(api, a):
    sl, tp = _derive_prices(api, a)
    print("\nWILL SEND bracket:")
    print(f"  account={a.account} symbol={a.symbol} side={a.side.upper()} qty={a.qty} "
          f"sl={sl} tp={tp}")
    if not a.yes:
        sys.exit("Dry run. Re-run with --yes to place.")
    try:
        resp = api.place_bracket(a.account, instrument=a.symbol, side=a.side,
                                 quantity=a.qty, stop_price=sl, limit_price=tp,
                                 metadata={"source": "tradeops"})
    except DXTradeError as e:
        print(f"REJECTED: {e}")
        _pj(e.payload)
        return 1
    print("ACCEPTED:")
    _pj(resp)
    pos = api.wait_for_position(a.account, timeout_sec=15)
    print(f"\n{len(pos)} open position(s) after fill:")
    for p in pos:
        print({k: p.get(k) for k in ("positionCode", "symbol", "side", "quantity",
                                    "openPrice", "stopLossPrice", "takeProfitPrice")})
    return 0


def cmd_close(api, a):
    pos = [p for p in api.list_positions(a.account)
           if str(p.get("positionCode")) == str(a.position_code)]
    if not pos:
        sys.exit(f"No open position {a.position_code} on {a.account}")
    p = pos[0]
    close_side = "SELL" if str(p.get("side")).upper() == "BUY" else "BUY"
    print(f"WILL CLOSE {p.get('symbol')} {p.get('side')} qty={p.get('quantity')} "
          f"via {close_side} MARKET")
    if not a.yes:
        sys.exit("Dry run. Re-run with --yes to close.")
    _pj(api.close_position(a.account, position_code=a.position_code,
                           instrument=p["symbol"], close_side=close_side))


def cmd_close_all(api, a):
    pos = api.list_positions(a.account)
    print(f"WILL CLOSE {len(pos)} position(s) on {a.account}")
    if not a.yes:
        sys.exit("Dry run. Re-run with --yes to close all.")
    for p in pos:
        close_side = "SELL" if str(p.get("side")).upper() == "BUY" else "BUY"
        try:
            r = api.close_position(a.account, position_code=p["positionCode"],
                                   instrument=p["symbol"], close_side=close_side)
            print(f"closed {p['positionCode']}: {r}")
        except DXTradeError as e:
            print(f"close {p['positionCode']} failed: {e}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("accounts")
    s = sub.add_parser("instruments")
    s.add_argument("--filter", default=None, help="client-side substring filter")
    s.add_argument("--symbols", default=None, help="server query, e.g. 'BTC*' or 'BTCUSDC.P'")
    s.add_argument("--types", default=None, help="server query, e.g. 'CRYPTO' or 'INDEX,STOCK'")
    s.add_argument("--limit", type=int, default=40)
    s.add_argument("--raw", action="store_true")
    s = sub.add_parser("quote"); s.add_argument("account"); s.add_argument("symbol")
    s = sub.add_parser("positions"); s.add_argument("account")
    s = sub.add_parser("open")
    s.add_argument("account"); s.add_argument("symbol")
    s.add_argument("side", choices=["buy", "sell"]); s.add_argument("qty", type=float)
    s.add_argument("--sl", type=float); s.add_argument("--tp", type=float)
    s.add_argument("--sl-pct", type=float); s.add_argument("--tp-pct", type=float)
    s.add_argument("--yes", action="store_true")
    s = sub.add_parser("close"); s.add_argument("account"); s.add_argument("position_code")
    s.add_argument("--yes", action="store_true")
    s = sub.add_parser("close-all"); s.add_argument("account")
    s.add_argument("--yes", action="store_true")

    a = p.parse_args()
    api = _client()
    try:
        fn = {"accounts": cmd_accounts, "instruments": cmd_instruments, "quote": cmd_quote,
              "positions": cmd_positions, "open": cmd_open, "close": cmd_close,
              "close-all": cmd_close_all}[a.cmd]
        return fn(api, a) or 0
    except DXTradeError as e:
        print(f"API error: {e}")
        _pj(e.payload)
        return 1
    finally:
        try:
            api.logout()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
