"""Raw Chrome DevTools (CDP) traffic capture that does NOT trip Cloudflare.

ChromeDriver enables the DevTools Runtime domain, which Cloudflare bot
management fingerprints — API calls from the page then fail with
net::ERR_FAILED. This client talks CDP over a websocket directly and only
enables the Network domain, so the page behaves exactly like a normal Chrome.

    cap = CDPCapture(port=9333, hosts=("breakoutprop.com",), out_dir="/tmp/x")
    cap.start()            # attaches to the first page target
    ...                    # user drives Chrome by hand
    cap.stop()
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

import websocket  # websocket-client


class CDPCapture:
    def __init__(self, port: int, hosts: tuple, out_dir: str, url_hint: str = ""):
        self.port = port
        self.hosts = hosts
        self.out_dir = out_dir
        self.url_hint = url_hint
        self.ws = None
        self._id = 0
        self._pending: dict = {}
        self._lock = threading.Lock()
        self.reqs: dict = {}
        self.ws_urls: dict = {}
        self.n_rest = self.n_ws = 0
        self._stop = threading.Event()
        self._thread = None
        self.target = None
        os.makedirs(out_dir, exist_ok=True)
        self.rest_f = open(os.path.join(out_dir, "rest.jsonl"), "a")
        self.ws_f = open(os.path.join(out_dir, "ws.jsonl"), "a")

    # ── target discovery ─────────────────────────────────────────────

    def _targets(self) -> list:
        with urllib.request.urlopen(f"http://localhost:{self.port}/json", timeout=3) as r:
            return [t for t in json.load(r) if t.get("type") == "page"]

    def pick_target(self):
        pages = self._targets()
        if not pages:
            raise RuntimeError("no page targets in Chrome")
        for t in pages:
            if self.url_hint and self.url_hint in (t.get("url") or ""):
                return t
        return pages[0]

    def current_url(self) -> str:
        try:
            for t in self._targets():
                if t.get("id") == (self.target or {}).get("id"):
                    return t.get("url") or ""
        except Exception:
            pass
        return ""

    def page_title(self) -> str:
        try:
            for t in self._targets():
                if t.get("id") == (self.target or {}).get("id"):
                    return t.get("title") or ""
        except Exception:
            pass
        return ""

    # ── CDP plumbing ─────────────────────────────────────────────────

    def send(self, method: str, params: dict | None = None, timeout: float = 10.0):
        with self._lock:
            self._id += 1
            mid = self._id
            ev = threading.Event()
            self._pending[mid] = [ev, None]
            self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        if not ev.wait(timeout):
            self._pending.pop(mid, None)
            raise TimeoutError(method)
        return self._pending.pop(mid)[1]

    def start(self):
        self.target = self.pick_target()
        self.ws = websocket.create_connection(self.target["webSocketDebuggerUrl"],
                                              suppress_origin=True, timeout=5)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.send("Network.enable", {"maxTotalBufferSize": 200_000_000,
                                     "maxResourceBufferSize": 50_000_000})
        return self

    def stop(self):
        self._stop.set()
        try:
            self.ws.close()
        except Exception:
            pass
        self.rest_f.close()
        self.ws_f.close()

    def _interesting(self, url: str) -> bool:
        return any(h in (url or "") for h in self.hosts)

    def _loop(self):
        while not self._stop.is_set():
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                if self._stop.is_set():
                    return
                time.sleep(0.5)
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if "id" in msg:
                slot = self._pending.get(msg["id"])
                if slot:
                    slot[1] = msg.get("result") if "result" in msg else {"error": msg.get("error")}
                    slot[0].set()
                continue
            try:
                self._event(msg.get("method"), msg.get("params") or {})
            except Exception:
                pass

    def _body(self, rid: str):
        # Must not block the reader thread: fetch on a helper thread.
        def _go(rec):
            try:
                res = self.send("Network.getResponseBody", {"requestId": rid}, timeout=8)
                body = (res or {}).get("body")
                if body and len(body) > 20000:
                    body = body[:20000] + f"... [{len(body)} chars]"
                rec["response"] = body
            except Exception:
                rec["response"] = None
            self.rest_f.write(json.dumps(rec) + "\n")
            self.rest_f.flush()
            self.n_rest += 1
        return _go

    def _event(self, m: str, p: dict):
        rid = p.get("requestId")
        if m == "Network.requestWillBeSent":
            req = p.get("request", {})
            if self._interesting(req.get("url")):
                hdrs = {k: v for k, v in (req.get("headers") or {}).items()
                        if k.lower() in ("authorization", "content-type", "x-account-id", "cookie")}
                if "Authorization" in hdrs:
                    hdrs["Authorization"] = hdrs["Authorization"][:24] + "…(redacted)"
                if "Cookie" in hdrs:
                    hdrs["Cookie"] = f"<{len(hdrs['Cookie'])} chars>"
                self.reqs[rid] = {"url": req.get("url"), "method": req.get("method"),
                                  "headers": hdrs, "postData": req.get("postData"),
                                  "ts": time.time()}
        elif m == "Network.responseReceived" and rid in self.reqs:
            rec = self.reqs.pop(rid)
            rec["status"] = (p.get("response") or {}).get("status")
            rec["mime"] = (p.get("response") or {}).get("mimeType")
            threading.Thread(target=self._body(rid), args=(rec,), daemon=True).start()
        elif m == "Network.loadingFailed" and rid in self.reqs:
            rec = self.reqs.pop(rid)
            rec["status"] = f"FAILED:{p.get('errorText')}" + (" (blocked)" if p.get("blockedReason") else "")
            rec["response"] = None
            self.rest_f.write(json.dumps(rec) + "\n"); self.rest_f.flush(); self.n_rest += 1
        elif m == "Network.webSocketCreated":
            self.ws_urls[rid] = p.get("url")
        elif m in ("Network.webSocketFrameSent", "Network.webSocketFrameReceived"):
            url = self.ws_urls.get(rid, "")
            if self._interesting(url):
                payload = (p.get("response") or {}).get("payloadData", "")
                if len(payload) > 6000:
                    payload = payload[:6000] + f"... [{len(payload)} chars]"
                self.ws_f.write(json.dumps({"dir": "out" if m.endswith("Sent") else "in",
                                            "url": url, "ts": time.time(), "payload": payload}) + "\n")
                self.ws_f.flush()
                self.n_ws += 1

    # ── convenience ─────────────────────────────────────────────────

    def eval_js(self, expression: str):
        """Runtime.evaluate WITHOUT Runtime.enable (one-shot, not fingerprinted the same way)."""
        res = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        return ((res or {}).get("result") or {}).get("value")

    def navigate(self, url: str):
        return self.send("Page.navigate", {"url": url})
