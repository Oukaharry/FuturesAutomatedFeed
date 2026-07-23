"""Probe how much cashBalanceLog history Tradovate really returns."""
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
    async function api(ep) {
        var r = await fetch(base + ep, {headers: {
            'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}});
        return {status: r.status, data: r.ok ? await r.json() : (await r.text()).slice(0, 200)};
    }
    var accounts = (await api('/account/list')).data || [];
    var out = {env: env, probes: {}};
    // Probe multiple endpoints on the first farming account
    var acct = accounts.find(a => a.name.startsWith('FTDFYSLX50878260627')) || accounts[0];
    var aid = acct.id;
    out.account = acct.name;

    var eps = {
        'ldeps': '/cashBalanceLog/ldeps?masterids=' + aid,
        'deps': '/cashBalanceLog/deps?masterid=' + aid,
        'list': '/cashBalanceLog/list',
    };
    for (var k in eps) {
        var r = await api(eps[k]);
        if (Array.isArray(r.data)) {
            var dates = {};
            var types = {};
            for (var e of r.data) {
                var td = e.tradeDate || {};
                var ds = td.year + '-' + String(td.month).padStart(2,'0')
                         + '-' + String(td.day).padStart(2,'0');
                dates[ds] = (dates[ds] || 0) + 1;
                types[e.cashChangeType] = (types[e.cashChangeType] || 0) + 1;
            }
            out.probes[k] = {status: r.status, count: r.data.length,
                             dates: dates, types: types,
                             first: r.data[0], last: r.data[r.data.length - 1]};
        } else {
            out.probes[k] = {status: r.status, resp: r.data};
        }
    }
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
            print(json.dumps(json.loads(res["result"]["value"]), indent=2)[:6000])
        break
ws.close()
