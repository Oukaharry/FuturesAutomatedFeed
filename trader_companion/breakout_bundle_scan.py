"""Pull Breakout's JS bundles through the live Chrome tab (Cloudflare-safe) and
grep them for internal API routes. Read-only helper for the probe session."""

import json
import re
import sys
import urllib.request

from trader_companion.cdp_capture import CDPCapture

PORT = 9333
OUT = "/tmp/breakout_capture"


def main():
    cap = CDPCapture(PORT, ("breakoutprop.com",), OUT + "/bundles", url_hint="trade.breakoutprop.com")
    cap.target = cap.pick_target()
    import websocket
    cap.ws = websocket.create_connection(cap.target["webSocketDebuggerUrl"], suppress_origin=True, timeout=60)
    import threading
    cap._thread = threading.Thread(target=cap._loop, daemon=True); cap._thread.start()
    urls = cap.eval_js("[...document.scripts].map(s => s.src).filter(Boolean)") or []
    print("scripts:", urls)
    paths = set()
    for u in urls:
        if "breakoutprop.com" not in u:
            continue
        js = cap.eval_js(f"fetch({json.dumps(u)}).then(r => r.text())") if False else None
        # Runtime.evaluate with awaitPromise
        res = cap.send("Runtime.evaluate", {"expression": f"fetch({json.dumps(u)}).then(r => r.text())",
                                            "awaitPromise": True, "returnByValue": True}, timeout=120)
        js = ((res or {}).get("result") or {}).get("value") or ""
        name = u.rsplit("/", 1)[-1]
        with open(f"{OUT}/{name}", "w") as f:
            f.write(js)
        print(f"{name}: {len(js):,} chars")
        for m in re.finditer(r'["`\'](/api/internal/[A-Za-z0-9_./${}\-]+|/prop-trading/[A-Za-z0-9_./${}\-]+|/v\d/[a-z][A-Za-z0-9_./${}\-]+)["`\']', js):
            paths.add(m.group(1))
    print("\n--- API paths in bundles ---")
    for p in sorted(paths):
        print(" ", p)
    cap.stop()


if __name__ == "__main__":
    main()
