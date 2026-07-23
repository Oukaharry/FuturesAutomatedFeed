"""Diagnostic: raw fill/contract data from the Tradeify Chrome session."""
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
    if (!token) return JSON.stringify({error: 'no token'});
    async function api(ep) {
        var r = await fetch(base + ep, {headers: {
            'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}});
        return {status: r.status, data: r.ok ? await r.json() : await r.text()};
    }
    var fills = await api('/fill/list');
    var out = {env: env, fill_status: fills.status};
    if (Array.isArray(fills.data)) {
        out.fill_count = fills.data.length;
        out.sample_fills = fills.data.slice(-5);
        var cids = [...new Set(fills.data.map(f => f.contractId))];
        out.contract_ids = cids;
        out.contracts = {};
        for (var cid of cids.slice(0, 20)) {
            var c = await api('/contract/item?id=' + cid);
            out.contracts[cid] = (c.data && c.data.name) ? c.data.name : c;
        }
    } else {
        out.fill_error = String(fills.data).slice(0, 300);
    }
    return JSON.stringify(out);
})()
"""

with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=10) as r:
    targets = json.loads(r.read())
page = next(t for t in targets
            if t.get("type") == "page" and "tradovate" in (t.get("url") or "").lower())
print("page url:", page.get("url"))
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=120, suppress_origin=True)
ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                    "params": {"expression": JS, "awaitPromise": True,
                               "returnByValue": True, "timeout": 100000}}))
while True:
    msg = json.loads(ws.recv())
    if msg.get("id") == 1:
        res = msg.get("result", {})
        if "exceptionDetails" in res:
            print("JS exception:", json.dumps(res["exceptionDetails"])[:500])
        else:
            print(json.dumps(json.loads(res["result"]["value"]), indent=2)[:4000])
        break
ws.close()
