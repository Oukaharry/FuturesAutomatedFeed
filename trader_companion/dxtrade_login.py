"""Open Chrome on the DXtrade terminal and log in — the Tradovate way.

Reads DXTRADE_USERNAME / DXTRADE_PASSWORD (and optional DXTRADE_HOST,
DXTRADE_DOMAIN) from .env, launches a persistent Chrome profile, fills the
login form, waits for the trading workspace, then obtains a REST session
token and prints a read-only account summary (balance / equity / positions).

The Chrome window stays open until you press Enter so you can inspect it.
If the broker asks for a 2FA code, type it in the Chrome window.

Usage:
    python -m trader_companion.dxtrade_login
    python -m trader_companion.dxtrade_login --host dx.other-broker.com
"""

import argparse
import json
import logging

from dotenv import load_dotenv

from trader_companion.dxtrade_browser import DXTradeBrowserSession, credentials_from_env
from trader_companion.dxtrade_connector import DXTradeError


def main():
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default=None)
    p.add_argument("--domain", default=None)
    p.add_argument("--no-api", action="store_true",
                   help="UI login only; skip the REST session token")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    creds = credentials_from_env()
    if not creds["username"] or not creds["password"]:
        print("Missing DXTRADE_USERNAME / DXTRADE_PASSWORD in .env")
        return 1

    sess = DXTradeBrowserSession.from_env(host=args.host, domain=args.domain)
    print(f"Opening Chrome → {sess.login_url} as {sess.username}")
    try:
        sess.login(api_login=not args.no_api)
    except Exception as exc:
        print(f"LOGIN FAILED: {exc}")
        input("Chrome left open for inspection. Press Enter to close…")
        sess.close()
        return 1

    print("✓ Web terminal ready")

    if sess.api.logged_in:
        print(f"✓ REST token acquired (timeout={sess.api.token_timeout})")
        try:
            users = sess.api.get_users()
            print("\n/users:")
            print(json.dumps(users, indent=2)[:3000])
            codes = sess.api.list_account_codes()
            print(f"\nAccount codes: {codes or '(none parsed — see raw /users above)'}")
            for code in codes:
                m = sess.api.get_metrics(code)
                print(f"[{code}] balance={m.get('balance')} equity={m.get('equity')} "
                      f"available={m.get('availableBalance')}")
                pos = sess.api.list_positions(code)
                print(f"[{code}] open positions: {len(pos)}")
        except DXTradeError as exc:
            print(f"REST read failed: {exc}")
    else:
        print("REST token not acquired (UI login only). If the REST /login kept failing, "
              "the login 'domain' may not be 'default' — try --domain <value>.")

    input("\nChrome is open. Press Enter to log out and close…")
    sess.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
