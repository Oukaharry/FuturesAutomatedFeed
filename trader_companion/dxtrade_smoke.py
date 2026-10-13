"""Smoke-test the DXtrade REST API against a real broker instance.

Read-only by default: logs in, lists accounts, prints balance/equity and open
positions, then logs out. Nothing is placed unless you pass --quote (still
read-only — it only requests a price snapshot).

Usage:
    python trader_companion/dxtrade_smoke.py                 # Tradeify247
    python trader_companion/dxtrade_smoke.py --host dx.other.com --domain default
    python trader_companion/dxtrade_smoke.py --quote BTCUSDC.P

You are prompted for username/password in the terminal (password hidden) —
never pass them as CLI flags.
"""

import argparse
import getpass
import json

from trader_companion.dxtrade_connector import (
    DXTradeClient, DXTradeError, TRADEIFY247_HOST,
)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default=TRADEIFY247_HOST)
    p.add_argument("--domain", default="default",
                   help="DXtrade login domain (usually 'default')")
    p.add_argument("--quote", default=None,
                   help="Symbol to request a one-shot quote for (read-only)")
    args = p.parse_args()

    username = input("DXtrade username: ").strip()
    password = getpass.getpass("DXtrade password (hidden): ")

    c = DXTradeClient(args.host, username, password, domain=args.domain)
    print(f"Logging in to {c.base_url} as {username} (domain={args.domain}) ...")
    try:
        data = c.login()
    except DXTradeError as e:
        print(f"LOGIN FAILED: {e}")
        if e.is_auth:
            print("  → check username/password, and try --domain if not 'default'")
        return 1
    print(f"OK  token={c.session_token[:8]}…  timeout={data.get('timeout')}")

    try:
        users = c.get_users()
        print("\n/users:")
        print(json.dumps(users, indent=2)[:3000])
        codes = c.list_account_codes()
        print(f"\nAccount codes: {codes or '(none parsed — see raw /users above)'}")

        for code in codes:
            try:
                m = c.get_metrics(code)
                print(f"\n[{code}] balance={m.get('balance')} equity={m.get('equity')} "
                      f"available={m.get('availableBalance')} openPnL={m.get('openPnL')}")
                pos = c.list_positions(code)
                print(f"[{code}] open positions: {len(pos)}")
                for pz in pos:
                    print("   ", {k: pz.get(k) for k in
                                 ("positionCode", "symbol", "side", "quantity",
                                  "openPrice", "stopLossPrice", "takeProfitPrice")})
                if args.quote:
                    q = c.get_quote(code, args.quote)
                    print(f"[{code}] quote {args.quote}: {q}")
            except DXTradeError as e:
                print(f"[{code}] error: {e}")
    finally:
        c.logout()
        print("\nLogged out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
