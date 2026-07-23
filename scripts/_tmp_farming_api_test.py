"""Standalone test: fetch Tradovate MNQ farming-day history via REST API.

Usage:
    python scripts/_tmp_farming_api_test.py <label> <username> <password> [demo|live]

Mirrors TradovateAccount.get_mnq_daily_pnl() but authenticates directly with
username/password instead of reusing the app's browser session.
"""
import sys
import json
import uuid
from collections import defaultdict

import requests

label, username, password = sys.argv[1], sys.argv[2], sys.argv[3]
env = sys.argv[4] if len(sys.argv) > 4 else "demo"
BASE = f"https://{env}.tradovateapi.com/v1"

sess = requests.Session()
sess.headers.update({"Content-Type": "application/json", "Accept": "application/json"})

auth_body = {
    "name": username,
    "password": password,
    "appId": "Tradovate Trader",
    "appVersion": "1.0",
    "deviceId": str(uuid.uuid4()),
    "cid": 0,
    "sec": "",
}
r = sess.post(f"{BASE}/auth/accesstokenrequest", json=auth_body, timeout=30)
print(f"[{label}] auth status={r.status_code}")
try:
    auth = r.json()
except ValueError:
    print(f"[{label}] non-JSON auth response: {r.text[:300]}")
    sys.exit(1)

if "errorText" in auth or "accessToken" not in auth:
    print(f"[{label}] auth failed: {json.dumps(auth)[:500]}")
    sys.exit(1)

token = auth["accessToken"]
sess.headers["Authorization"] = f"Bearer {token}"
print(f"[{label}] authenticated OK (userId={auth.get('userId')})")


def api(endpoint):
    resp = sess.get(f"{BASE}{endpoint}", timeout=30)
    if resp.status_code != 200:
        print(f"[{label}] GET {endpoint} -> {resp.status_code}: {resp.text[:200]}")
        return None
    return resp.json()


accounts = api("/account/list") or []
print(f"[{label}] accounts: {[(a['id'], a.get('name')) for a in accounts]}")

all_fills = api("/fill/list") or []
print(f"[{label}] total fills: {len(all_fills)}")

contract_cache = {}
for f in all_fills:
    cid = f.get("contractId")
    if cid and cid not in contract_cache:
        c = api(f"/contract/item?id={cid}")
        contract_cache[cid] = c.get("name", str(cid)) if c else str(cid)

mnq_ids = {cid for cid, name in contract_cache.items()
           if str(name).upper().startswith("MNQ")}
print(f"[{label}] contracts seen: {sorted(set(contract_cache.values()))}, MNQ ids: {mnq_ids}")

for acct in accounts:
    aid, aname = acct["id"], acct.get("name", "?")
    mnq_dates = set()
    for f in all_fills:
        if f.get("accountId") == aid and f.get("contractId") in mnq_ids:
            td = f.get("tradeDate", {})
            mnq_dates.add(f"{td.get('year', 0)}-{td.get('month', 1):02d}-{td.get('day', 1):02d}")
    if not mnq_dates:
        print(f"\n[{label}] {aname}: no MNQ fills")
        continue

    logs = api(f"/cashBalanceLog/ldeps?masterids={aid}") or []
    daily = defaultdict(lambda: {"gross": 0.0, "fees": 0.0})
    for e in logs:
        td = e.get("tradeDate", {})
        ds = f"{td.get('year', 0)}-{td.get('month', 1):02d}-{td.get('day', 1):02d}"
        if ds not in mnq_dates:
            continue
        ctype = e.get("cashChangeType", "")
        delta = e.get("delta", 0)
        if ctype == "TradePaired":
            daily[ds]["gross"] += delta
        elif ctype in ("Commission", "ExchangeFee", "ClearingFee", "NfaFee"):
            daily[ds]["fees"] += delta

    print(f"\n[{label}] {aname} (id={aid}) — {len(daily)} MNQ farming day(s):")
    for ds in sorted(daily):
        d = daily[ds]
        net = round(d["gross"] + d["fees"], 2)
        print(f"   {ds}:  net ${net:>10.2f}   (gross {d['gross']:.2f}, fees {d['fees']:.2f})")
