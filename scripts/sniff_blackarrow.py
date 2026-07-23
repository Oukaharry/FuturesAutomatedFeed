"""
scripts/sniff_blackarrow.py

Attaches to the BlackArrow Chrome session via Selenium (debug port 9222),
injects a JavaScript network interceptor that patches WebSocket and
XMLHttpRequest/fetch, then waits while you place a trade.

Captured traffic is saved to logs/blackarrow_traffic.json.

Usage:
    python scripts/sniff_blackarrow.py            # capture 45s
    python scripts/sniff_blackarrow.py --duration 60
"""

import argparse
import json
import sys
import os
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

ROOT = os.path.join(os.path.dirname(__file__), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEBUG_PORT = 9222

# JavaScript that monkey-patches WebSocket and XHR/fetch to log all traffic
# into window.__ba_traffic (a global array of plain objects).
INTERCEPTOR_JS = r"""
return (function() {
  if (window.__ba_patched) return 'already_patched';
  window.__ba_patched = true;
  window.__ba_traffic = [];

  // --- WebSocket ---
  var OrigWS = window.WebSocket;
  function PatchedWS(url, protocols) {
    var ws = protocols ? new OrigWS(url, protocols) : new OrigWS(url);
    window.__ba_traffic.push({type:'WS_OPEN', url:url, ts: Date.now()});

    var origSend = ws.send.bind(ws);
    ws.send = function(data) {
      window.__ba_traffic.push({type:'WS_SENT', url:url, data: String(data), ts: Date.now()});
      return origSend(data);
    };
    ws.addEventListener('message', function(ev) {
      var d = (typeof ev.data === 'string') ? ev.data : '[binary]';
      window.__ba_traffic.push({type:'WS_RECV', url:url, data: d, ts: Date.now()});
    });
    return ws;
  }
  PatchedWS.prototype = OrigWS.prototype;
  PatchedWS.CONNECTING = OrigWS.CONNECTING;
  PatchedWS.OPEN = OrigWS.OPEN;
  PatchedWS.CLOSING = OrigWS.CLOSING;
  PatchedWS.CLOSED = OrigWS.CLOSED;
  window.WebSocket = PatchedWS;

  // --- XMLHttpRequest ---
  var OrigXHR = window.XMLHttpRequest;
  window.XMLHttpRequest = function() {
    var xhr = new OrigXHR();
    var method, url;
    var origOpen = xhr.open.bind(xhr);
    xhr.open = function(m, u) { method = m; url = u; return origOpen.apply(xhr, arguments); };
    var origSend = xhr.send.bind(xhr);
    xhr.send = function(body) {
      window.__ba_traffic.push({type:'XHR_REQ', method:method, url:url,
                                 body: body ? String(body).slice(0,2000) : null, ts: Date.now()});
      xhr.addEventListener('load', function() {
        window.__ba_traffic.push({type:'XHR_RESP', url:url, status:xhr.status,
                                   body: xhr.responseText ? xhr.responseText.slice(0,2000) : null,
                                   ts: Date.now()});
      });
      return origSend.apply(xhr, arguments);
    };
    return xhr;
  };

  // --- fetch ---
  var origFetch = window.fetch;
  window.fetch = function(input, init) {
    var url = (typeof input === 'string') ? input : (input.url || String(input));
    var method = (init && init.method) || 'GET';
    var body = (init && init.body) ? String(init.body).slice(0,2000) : null;
    window.__ba_traffic.push({type:'FETCH_REQ', method:method, url:url, body:body, ts:Date.now()});
    return origFetch.apply(window, arguments).then(function(resp) {
      resp.clone().text().then(function(text) {
        window.__ba_traffic.push({type:'FETCH_RESP', url:url, status:resp.status,
                                   body: text.slice(0,2000), ts:Date.now()});
      }).catch(function(){});
      return resp;
    });
  };

  return 'patched';
})();
"""

PATCH_EXISTING_JS = r"""
return (function() {
  if (window.__ba_proto_patched) return 'proto_already_patched';
  window.__ba_proto_patched = true;
  if (!window.__ba_traffic) window.__ba_traffic = [];

  // Patch prototype.send — captures sends on ALL open WS instances
  var origProtoSend = WebSocket.prototype.send;
  WebSocket.prototype.send = function(data) {
    window.__ba_traffic.push({
      type: 'WS_SENT', url: this.url,
      data: (typeof data === 'string') ? data : '[binary]',
      ts: Date.now()
    });
    return origProtoSend.call(this, data);
  };

  // Patch prototype.addEventListener to capture 'message' on existing sockets
  var origAddEL = WebSocket.prototype.addEventListener;
  WebSocket.prototype.addEventListener = function(type, handler, opts) {
    if (type === 'message') {
      var url = this.url;
      var wrapped = function(ev) {
        var d = (typeof ev.data === 'string') ? ev.data : '[binary]';
        window.__ba_traffic.push({type:'WS_RECV', url:url, data:d, ts:Date.now()});
        return handler.apply(this, arguments);
      };
      return origAddEL.call(this, type, wrapped, opts);
    }
    return origAddEL.apply(this, arguments);
  };

  return 'proto_patched';
})();
"""

READ_JS = "return JSON.stringify(window.__ba_traffic || []);"

CLEAR_JS = "window.__ba_traffic = []; window.__ba_patched = false; window.__ba_proto_patched = false; return 'cleared';"


def attach_driver(port: int) -> webdriver.Chrome:
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    # Don't create a new browser — attach to the existing one
    driver = webdriver.Chrome(options=opts)
    return driver


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEBUG_PORT)
    parser.add_argument("--duration", type=int, default=45,
                        help="Seconds to capture traffic (default 45)")
    args = parser.parse_args()

    print(f"\nAttaching to Chrome on port {args.port}...")
    driver = attach_driver(args.port)
    print(f"Attached. Page title: {driver.title}\n")

    # Clear any state from previous runs
    print(f"Clear: {driver.execute_script(CLEAR_JS)}")
    # Patch window.WebSocket for new connections + fetch/XHR
    print(f"Fetch/XHR interceptor: {driver.execute_script(INTERCEPTOR_JS)}")
    # Patch WebSocket.prototype for EXISTING open connections
    print(f"WS prototype patch: {driver.execute_script(PATCH_EXISTING_JS)}\n")

    print(f"Capturing for {args.duration}s...")
    print(">> NOW: place a trade manually (Buy at Mkt / Sell at Mkt) in the browser")
    print("   or run:  python scripts/probe_blackarrow.py --side buy --qty 1 --auto\n")

    # Poll and print new events every 3 seconds so you see them in real-time
    seen = 0
    deadline = time.time() + args.duration
    while time.time() < deadline:
        time.sleep(3)
        raw = driver.execute_script(READ_JS)
        events = json.loads(raw)
        new = events[seen:]
        for e in new:
            t = e.get("type", "?")
            if t == "WS_SENT":
                print(f"  [WS >>>] {e['url'].split('?')[0][-60:]}  |  {str(e['data'])[:300]}")
            elif t == "WS_RECV":
                d = str(e.get("data", ""))
                if len(d) < 500 or any(k in d.lower() for k in
                                        ("order", "trade", "fill", "exec", "buy", "sell")):
                    print(f"  [WS <<<] {d[:300]}")
            elif t in ("XHR_REQ", "FETCH_REQ"):
                url = e.get("url", "")
                if not url.startswith("data:"):
                    print(f"  [{t}] {e.get('method','?')} {url}")
                    if e.get("body"):
                        print(f"         body: {e['body'][:200]}")
            elif t == "WS_OPEN":
                print(f"  [WS NEW] {e.get('url','')}")
        seen = len(events)

    raw = driver.execute_script(READ_JS)
    events = json.loads(raw)

    print(f"\n\n{'='*60}")
    print(f"Capture complete. {len(events)} events total.")

    out = os.path.join(ROOT, "logs", "blackarrow_traffic.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2)
    print(f"Full log saved to: {out}")

    ws_sent = [e for e in events if e["type"] == "WS_SENT"]
    ws_recv = [e for e in events if e["type"] == "WS_RECV"]
    http_req = [e for e in events if e["type"] in ("XHR_REQ", "FETCH_REQ")]
    print(f"\nWS sent: {len(ws_sent)}, WS received: {len(ws_recv)}, HTTP/XHR: {len(http_req)}")

    print("\nUnique WebSocket URLs opened:")
    for e in events:
        if e["type"] == "WS_OPEN":
            print(f"  {e['url']}")

    print("\nHTTP(S) requests to API-like endpoints:")
    for e in http_req:
        url = e.get("url", "")
        if any(k in url.lower() for k in ("api", "order", "trade", "auth", "session", "exec")):
            print(f"  {e.get('method','?')} {url}")
            if e.get("body"):
                print(f"    body: {e['body'][:300]}")

    # Don't quit driver — it's attached to existing Chrome, quitting would close it
    driver.service.stop()


if __name__ == "__main__":
    main()

