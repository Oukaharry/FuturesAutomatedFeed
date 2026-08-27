"""Check for closed Tradovate trades that have not been pushed to the dashboard.

1. Open positions per account (are we flat?)
2. Daily net P&L per account from the retained cashBalanceLog window
3. Fresh dashboard pull - compare Prop Day cells against those daily nets
"""
import json
import urllib.request

import requests
import websocket

PORT = 55476
EMAIL = "harryodhiambo16@gmail.com"
DASH_URL = "https://www.tradeopss.com/api/client/data"

JS = r"""
(async function() {
    var auth = JSON.parse(sessionStorage.getItem('api_authenticator_state') || '{}');
    var token = auth.token || '';
    var env = auth.environment || 'demo';
    var base = 'https://' + env + '.tradovateapi.com/v1';
    async function api(ep) {
        var r = await fetch(base + ep, {headers: {
            'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}});
        if (!r.ok) return null;
        return await r.json();
    }
    var accounts = await api('/account/list') || [];
    var out = [];
    for (var acct of accounts) {
        var aid = acct.id;
        var positions = await api('/position/ldeps?masterids=' + aid) || [];
        var open = positions.filter(p => (p.netPos || 0) !== 0)
                            .map(p => ({contractId: p.contractId, netPos: p.netPos}));
        var logs = await api('/cashBalanceLog/ldeps?masterids=' + aid) || [];
        var daily = {};
        for (var e of logs) {
            var td = e.tradeDate || {};
            var ds = td.year + '-' + String(td.month).padStart(2,'0')
                     + '-' + String(td.day).padStart(2,'0');
            if (!(ds in daily)) daily[ds] = 0;
            if (e.cashChangeType === 'TradePaired'
                || ['Commission','ExchangeFee','ClearingFee','NfaFee'].includes(e.cashChangeType))
                daily[ds] += e.delta;
        }
        var days = Object.keys(daily).sort().map(ds => ({
            date: ds, net: Math.round(daily[ds] * 100) / 100})).filter(d => d.net !== 0);
        out.push({account: acct.name, open_positions: open, days: days});
    }
    return JSON.stringify(out);
})()
"""


def cdp_eval(port, expression):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=10) as r:
        targets = json.loads(r.read())
    page = next(t for t in targets
                if t.get("type") == "page" and "tradovate" in (t.get("url") or "").lower())
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=180,
                                     suppress_origin=True)
    try:
        ws.send(json.dumps({
            "id": 1, "method": "Runtime.evaluate",
            "params": {"expression": expression, "awaitPromise": True,
                       "returnByValue": True, "timeout": 150000}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                res = msg.get("result", {})
                if "exceptionDetails" in res:
                    raise RuntimeError(res["exceptionDetails"])
                return res.get("result", {}).get("value")
    finally:
        ws.close()


print("=" * 64)
print("1) LIVE TRADOVATE (Tradeify) - positions + daily nets")
print("=" * 64)
tv = json.loads(cdp_eval(PORT, JS))
for a in tv:
    pos = a["open_positions"]
    pos_str = "FLAT" if not pos else f"OPEN {pos}"
    print(f"\n  {a['account']}: {pos_str}")
    for d in a["days"]:
        print(f"     {d['date']}: net ${d['net']:>10.2f}")

print()
print("=" * 64)
print("2) DASHBOARD - farming rows for the same accounts")
print("=" * 64)
r = requests.post(DASH_URL, json={"email": EMAIL},
                  headers={"Content-Type": "application/json"}, timeout=30)
r.raise_for_status()
evals = r.json().get("evaluations", []) or []

tv_accounts = {a["account"]: a for a in tv}
for ev in evals:
    if ev.get("_deleted"):
        continue
    acct = (ev.get("Account #.1") or ev.get("Account #") or "").strip()
    match = None
    for tv_name in tv_accounts:
        if acct and (acct in tv_name or tv_name in acct):
            match = tv_name
            break
    if not match:
        continue
    prop_days = {}
    for i in range(1, 61):
        v = str(ev.get(f"Prop Day {i}", "") or "").strip()
        if v:
            prop_days[i] = v
    filled = ", ".join(f"D{i}={prop_days[i]}" for i in sorted(prop_days)) or "(none)"
    print(f"\n  {acct} [{ev.get('Prop Firm')}] status={ev.get('Status') or ev.get('Status P1')}")
    print(f"     Prop Days filled ({len(prop_days)}): {filled}")
    tv_days = tv_accounts[match]["days"]
    print(f"     Tradovate window: {['%s: %.2f' % (d['date'], d['net']) for d in tv_days]}")
