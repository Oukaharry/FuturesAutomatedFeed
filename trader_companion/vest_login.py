"""One-time Vest Markets login → persisted token chain for the headless connector.

Opens Chrome, walks the Privy email login (you type the one-time code), reads
the user + account token responses straight off the network log, seeds the
VestClient session file, QUITS Chrome, then rotates the chain once so the
browser copy can never race the bot (reuse of a rotated refresh token returns
401 and kills the chain).

    python -m trader_companion.vest_login --email you@example.com
    python -m trader_companion.vest_login --email ... --token-file /path/vest_session.json

Afterwards the companion connects Vest Capital with no browser:
    python -m trader_companion.vest_connector status
"""

import argparse
import json
import logging
import os
import tempfile
import time

from trader_companion.vest_connector import VestClient, default_token_file
from trader_companion.vest_probe import Capture, _driver, email_login

log = logging.getLogger("vest-login")


def _harvest(rest_jsonl: str):
    """Newest user-level and account-level token payloads from the capture."""
    user = account = None
    try:
        with open(rest_jsonl) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("method") != "POST" or r.get("status") != 200 or not r.get("response"):
                    continue
                url = (r.get("url") or "").split("?")[0]
                try:
                    body = json.loads(r["response"])
                except ValueError:
                    continue
                if not isinstance(body, dict) or not body.get("refreshToken"):
                    continue
                if url.endswith("/v3/auth/account-token") or body.get("accountId"):
                    account = body
                elif url.endswith(("/v3/auth/refresh", "/v3/auth/register", "/v3/auth/login")):
                    user = body
    except OSError:
        pass
    return user, account


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--email", required=True)
    p.add_argument("--token-file", default=None)
    p.add_argument("--profile", default="vest_login_" + str(int(time.time())),
                   help="Chrome profile key (fresh by default so no stale chain is reused)")
    p.add_argument("--settle", type=int, default=12, help="seconds to let the app mint tokens")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Keep this capture separate from the probe's default directory.
    import trader_companion.vest_probe as probe
    probe.OUT = os.path.join(tempfile.gettempdir(), "vest_login_capture")
    os.makedirs(probe.OUT, exist_ok=True)
    for name in ("rest.jsonl", "ws.jsonl"):
        try:
            os.remove(os.path.join(probe.OUT, name))
        except OSError:
            pass

    d = _driver(a.profile)
    cap = Capture(d).start()
    try:
        ok = email_login(d, a.email)
        if not ok:
            print("Login did not complete — nothing saved.")
            return 1
        time.sleep(a.settle)
        cap.stop()
        user, account = _harvest(os.path.join(probe.OUT, "rest.jsonl"))
    finally:
        try:
            d.quit()
        except Exception:
            pass

    if not user and not account:
        print("No Vest auth responses were captured — login flow may have changed.")
        return 2

    client = VestClient(token_file=a.token_file or default_token_file())
    client.import_tokens(user=user, account=account)
    # Rotate now so the browser's copy of the chain is dead and the bot owns it.
    client.login()
    cap_rec = client.capital_account()
    print(f"Saved Vest session → {client.token_file}")
    print(f"Account {client.account_id}  balance ${client.balance():,.2f}  "
          f"plan: {cap_rec.get('plan_name') or 'n/a'}")
    try:
        for name in ("rest.jsonl", "ws.jsonl"):
            os.remove(os.path.join(probe.OUT, name))
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
