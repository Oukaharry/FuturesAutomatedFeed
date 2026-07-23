"""Probe alternative Tradovate endpoints for deeper trade/P&L history."""
import json
import urllib.request

import websocket

PORT = 55476

JS = r"""
(async function() {
    var auth = JSON.parse(sessionStorage.getItem('api_authenticator_state') || '{}');
    var token = auth.token || '';
    var env = auth.environment || 'demo';
    var base = 'https://' + env + '.tradovateapi.com/v1';
    async function api(ep, method, body) {
        var opts = {method: method || 'GET', headers: {
            'Authorization': 'Bearer ' + token, 'Accept': 'application/json',
            'Content-Type': 'application/json'}};
        if (body) opts.body = JSON.stringify(body);
        var r = await fetch(base + ep, opts);
        var txt = await r.text();
        var d = null; try { d = JSON.parse(txt); } catch(e) { d = txt.slice(0, 150); }
        return {status: r.status, data: d};
    }
    var accounts = (await api('/account/list')).data || [];
    var acct = accounts.find(a => a.name.startsWith('FTDFYSLX50878260627')) || accounts[0];
    var aid = acct.id;
    var out = {account: acct.name, aid: aid, probes: {}};

    function summarize(r) {
        if (!Array.isArray(r.data)) return {status: r.status, resp: String(JSON.stringify(r.data)).slice(0, 150)};
        var dates = new Set();
        for (var e of r.data) {
            var td = e.tradeDate || {};
            if (td.year) dates.add(td.year + '-' + String(td.month).padStart(2,'0')
                                   + '-' + String(td.day).padStart(2,'0'));
            else if (e.timestamp) dates.add(String(e.timestamp).slice(0, 10));
        }
        return {status: r.status, count: r.data.length, dates: [...dates].sort()};
    }

    out.probes['fillPair_ldeps'] = summarize(await api('/fillPair/ldeps?masterids=' + aid));
    out.probes['fill_ldeps'] = summarize(await api('/fill/ldeps?masterids=' + aid));
    out.probes['cbl_archived'] = summarize(await api('/cashBalanceLog/ldeps?masterids=' + aid + '&archived=true'));
    out.probes['order_ldeps'] = summarize(await api('/order/ldeps?masterids=' + aid));
    out.probes['position_ldeps'] = summarize(await api('/position/ldeps?masterids=' + aid));
    out.probes['tradeDate_pnl'] = summarize(await api('/tradeDatePnL/ldeps?masterids=' + aid));
    out.probes['accountPnL'] = summarize(await api('/accountPnL/ldeps?masterids=' + aid));
    // WebSocket sync entity names sometimes exposed via REST too:
    out.probes['cashBalance_snapshot'] = (await api('/cashBalance/getCashBalanceSnapshot', 'POST', {accountId: aid}));
    return JSON.stringify(out);
})()
"""

with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=10) as r:
    targets = json.loads(r.read())
page = next(t for t in targets
            if t.get("type") == "page" and "tradovate" in (t.get("url") or "").lower())
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=180, suppress_origin=True)
ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                    "params": {"expression": JS, "awaitPromise": True,
                               "returnByValue": True, "timeout": 150000}}))
while True:
    msg = json.loads(ws.recv())
    if msg.get("id") == 1:
        res = msg.get("result", {})
        if "exceptionDetails" in res:
            print("JS exception:", json.dumps(res["exceptionDetails"])[:800])
        else:
            print(json.dumps(json.loads(res["result"]["value"]), indent=2)[:5000])
        break
ws.close()
