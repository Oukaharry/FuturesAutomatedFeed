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


def bootstrap(email: str, token_file: str = None, profile: str = None, settle: int = 12,
              otp_prompt=None) -> "VestClient":
    """Chrome + Privy login for `email` (code read from the mailbox when configured),
    harvest the token chain into `token_file`, quit Chrome, rotate once. Raises on failure."""
    import trader_companion.vest_probe as probe
    probe.OUT = os.path.join(tempfile.gettempdir(), "vest_login_capture", str(int(time.time())))
    os.makedirs(probe.OUT, exist_ok=True)
    d = _driver(profile or "vest_login_" + str(int(time.time())))
    cap = Capture(d).start()
    try:
        ok = email_login(d, email, otp_prompt=otp_prompt or (lambda *_: ""))
        if not ok:
            raise RuntimeError("Vest login did not complete (no code received / typed)")
        time.sleep(settle)
        cap.stop()
        user, account = _harvest(os.path.join(probe.OUT, "rest.jsonl"))
    finally:
        try:
            d.quit()
        except Exception:
            pass
    if not user and not account:
        raise RuntimeError("no Vest auth responses captured — login flow may have changed")
    client = VestClient(token_file=token_file or default_token_file(email))
    client.import_tokens(user=user, account=account)
    client.login()
    for name in ("rest.jsonl", "ws.jsonl"):
        try:
            os.remove(os.path.join(probe.OUT, name))
        except OSError:
            pass
    return client


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--email", required=True)
    p.add_argument("--token-file", default=None)
    p.add_argument("--profile", default="vest_login_" + str(int(time.time())),
                   help="Chrome profile key (fresh by default so no stale chain is reused)")
    p.add_argument("--settle", type=int, default=12, help="seconds to let the app mint tokens")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        client = bootstrap(a.email, token_file=a.token_file, profile=a.profile, settle=a.settle,
                           otp_prompt=input)
    except RuntimeError as exc:
        print(exc)
        return 1
    cap_rec = client.capital_account()
    print(f"Saved Vest session → {client.token_file}")
    print(f"Account {client.account_id}  balance ${client.balance():,.2f}  "
          f"plan: {cap_rec.get('plan_name') or 'n/a'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
