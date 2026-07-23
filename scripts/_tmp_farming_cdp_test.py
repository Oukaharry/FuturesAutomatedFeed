"""Fetch Tradovate MNQ farming-day history via the app's OWN Chrome session.

Attaches to the running Selenium Chrome over the DevTools protocol and runs
the same REST calls as get_mnq_daily_pnl(), reusing the page's session token.
Fills are mapped to accounts via /order/list (fill/list has no accountId).
"""
import json
import urllib.request

import websocket

SESSIONS = {
    "Tradeify (TDFYU995561466)": 55476,
}

FARMING_JS = r"""
(async function() {
    var auth = JSON.parse(sessionStorage.getItem('api_authenticator_state') || '{}');
    var token = auth.token || '';
    var env = auth.environment || 'demo';
    var base = 'https://' + env + '.tradovateapi.com/v1';
    if (!token) return JSON.stringify({error: 'no session token in this page'});
    async function api(ep) {
        var r = await fetch(base + ep, {headers: {
            'Authorization': 'Bearer ' + token,
            'Accept': 'application/json'}});
        if (!r.ok) return null;
        return await r.json();
    }
    var accounts = await api('/account/list') || [];
    var fills = await api('/fill/list') || [];
    var orders = await api('/order/list') || [];
    var orderAcct = {};
    for (var o of orders) orderAcct[o.id] = o.accountId;

    var contracts = {};
    for (var f of fills) {
        var cid = f.contractId;
        if (cid && !(cid in contracts)) {
            var c = await api('/contract/item?id=' + cid);
            contracts[cid] = c ? c.name : String(cid);
        }
    }
    var mnqIds = new Set(Object.keys(contracts).filter(
        cid => String(contracts[cid]).toUpperCase().startsWith('MNQ')).map(Number));

    var out = [];
    for (var acct of accounts) {
        var aid = acct.id, aname = acct.name;
        var mnqDates = new Set();
        for (var f of fills) {
            var facct = f.accountId !== undefined ? f.accountId : orderAcct[f.orderId];
            if (facct === aid && mnqIds.has(f.contractId)) {
                var td = f.tradeDate || {};
                mnqDates.add(td.year + '-' + String(td.month).padStart(2,'0')
                             + '-' + String(td.day).padStart(2,'0'));
            }
        }
        // Full daily P&L from cashBalanceLog (all dates), tagging MNQ-fill days.
        var logs = await api('/cashBalanceLog/ldeps?masterids=' + aid) || [];
        var daily = {};
        for (var e of logs) {
            var td = e.tradeDate || {};
            var ds = td.year + '-' + String(td.month).padStart(2,'0')
                     + '-' + String(td.day).padStart(2,'0');
            if (!(ds in daily)) daily[ds] = {gross: 0, fees: 0};
            if (e.cashChangeType === 'TradePaired') daily[ds].gross += e.delta;
            else if (['Commission','ExchangeFee','ClearingFee','NfaFee'].includes(e.cashChangeType))
                daily[ds].fees += e.delta;
        }
        var days = Object.keys(daily).sort().map(ds => ({
            date: ds,
            net: Math.round((daily[ds].gross + daily[ds].fees) * 100) / 100,
            mnq_confirmed: mnqDates.has(ds),
        })).filter(d => d.net !== 0 || d.mnq_confirmed);
        out.push({account: aname, account_id: aid, days: days,
                  mnq_fill_dates: [...mnqDates].sort()});
    }
    return JSON.stringify({env: env, results: out});
})()
"""


def cdp_eval(port, expression):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=10) as r:
        targets = json.loads(r.read())
    page = next((t for t in targets
                 if t.get("type") == "page" and "tradovate" in (t.get("url") or "").lower()), None)
    if not page:
        pages = [(t.get("type"), (t.get("url") or "")[:80]) for t in targets]
        raise RuntimeError(f"no tradovate page found; targets: {pages}")
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


for label, port in SESSIONS.items():
    print(f"\n{'=' * 60}\n{label} - DevTools port {port}\n{'=' * 60}")
    try:
        raw = cdp_eval(port, FARMING_JS)
        data = json.loads(raw)
        if "error" in data:
            print(f"  ERROR: {data['error']}")
            continue
        print(f"  environment: {data['env']}")
        for acct in data["results"]:
            days = acct["days"]
            if not days:
                print(f"\n  {acct['account']}: no trading-day P&L found")
                continue
            print(f"\n  {acct['account']} (id={acct.get('account_id')}) - "
                  f"{len(days)} trading day(s), MNQ fills visible on: {acct['mnq_fill_dates'] or 'none'}")
            for d in days:
                tag = "  [MNQ today]" if d["mnq_confirmed"] else ""
                print(f"     {d['date']}:  net ${d['net']:>10.2f}{tag}")
    except Exception as e:
        print(f"  FAILED: {e}")
