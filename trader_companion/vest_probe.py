"""Vest Markets live probe: Chrome email login + full REST/WS traffic capture.

Opens next.vestmarkets.com in Chrome with CDP network logging, walks the
Privy email login (you type / paste the one-time code when prompted), then
records every api-gateway / ws.hz request with its response body to
/tmp/vest_capture/*.jsonl. Leaves Chrome open for follow-up probing.

    python -m trader_companion.vest_probe --email you@example.com
    python -m trader_companion.vest_probe --email ... --symbol NDX-USD-PERP --hold 900

The OTP prompt reads from the terminal. Nothing is traded by this script.
"""

import argparse
import json
import logging
import os
import re
import tempfile
import threading
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

OUT = "/tmp/vest_capture"
API_HOSTS = ("api-gateway.hz.vestmarkets.com", "server-prod.hz.vestmarkets.com",
             "api-beta-prod.hz.vestmarkets.com", "ws.hz.vestmarkets.com",
             "auth.privy.io", "privy.io")
log = logging.getLogger("vest-probe")


def _driver(profile_key="vest_default"):
    opts = Options()
    profile_dir = os.path.join(tempfile.gettempdir(), "vest_profiles", profile_key)
    os.makedirs(profile_dir, exist_ok=True)
    opts.add_argument(f"--user-data-dir={profile_dir}")
    for a in ("--no-sandbox", "--disable-dev-shm-usage", "--disable-crash-reporter",
              "--log-level=3", "--disable-extensions", "--disable-sync",
              "--window-size=1280,900", "--disable-blink-features=AutomationControlled"):
        opts.add_argument(a)
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)
    # CDP network capture (must be set before launch)
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    opts.add_experimental_option("perfLoggingPrefs", {"enableNetwork": True, "enablePage": False})
    try:
        from trader_companion.tradovate import TradovateAccount
        cached = TradovateAccount._cached_chromedriver_path()
    except Exception:
        cached = None
    d = webdriver.Chrome(service=Service(executable_path=cached), options=opts) if cached \
        else webdriver.Chrome(options=opts)
    d.set_page_load_timeout(60)
    d.implicitly_wait(1)
    d.execute_cdp_cmd("Network.enable", {"maxTotalBufferSize": 200_000_000,
                                         "maxResourceBufferSize": 50_000_000})
    return d


class Capture:
    """Drain Chrome's performance log into REST + WS jsonl files."""

    def __init__(self, driver):
        self.d = driver
        os.makedirs(OUT, exist_ok=True)
        self.rest = open(f"{OUT}/rest.jsonl", "a")
        self.ws = open(f"{OUT}/ws.jsonl", "a")
        self.reqs = {}      # requestId -> {url, method, postData}
        self.ws_urls = {}   # requestId -> url
        self.n_rest = self.n_ws = 0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._t.start(); return self

    def stop(self):
        self._stop.set(); self._t.join(timeout=5); self._drain()
        self.rest.close(); self.ws.close()

    def _interesting(self, url):
        return any(h in (url or "") for h in API_HOSTS)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._drain()
            except Exception as exc:
                log.debug("drain error: %s", exc)
            time.sleep(0.7)

    def _drain(self):
        for entry in self.d.get_log("performance"):
            try:
                msg = json.loads(entry["message"])["message"]
            except Exception:
                continue
            m, p = msg.get("method"), msg.get("params", {})
            rid = p.get("requestId")
            if m == "Network.requestWillBeSent":
                req = p.get("request", {})
                if self._interesting(req.get("url")):
                    self.reqs[rid] = {"url": req.get("url"), "method": req.get("method"),
                                      "headers": {k: v for k, v in (req.get("headers") or {}).items()
                                                  if k.lower() in ("authorization", "content-type", "x-account-id")},
                                      "postData": req.get("postData"), "ts": p.get("timestamp")}
            elif m == "Network.responseReceived" and rid in self.reqs:
                resp = p.get("response", {})
                rec = self.reqs.pop(rid)
                rec["status"] = resp.get("status")
                body = None
                try:
                    b = self.d.execute_cdp_cmd("Network.getResponseBody", {"requestId": rid})
                    body = b.get("body")
                    if body and len(body) > 20000:
                        body = body[:20000] + f"... [{len(body)} chars]"
                except Exception:
                    pass
                rec["response"] = body
                if rec["headers"].get("Authorization") or rec["headers"].get("authorization"):
                    a = rec["headers"].get("Authorization") or rec["headers"].get("authorization")
                    rec["headers"]["Authorization"] = a[:24] + "…(redacted)"
                self.rest.write(json.dumps(rec) + "\n"); self.rest.flush(); self.n_rest += 1
            elif m == "Network.loadingFailed" and rid in self.reqs:
                rec = self.reqs.pop(rid)
                rec["status"] = f"FAILED:{p.get('errorText')}" + (" (blocked)" if p.get("blockedReason") else "")
                rec["response"] = None
                self.rest.write(json.dumps(rec) + "\n"); self.rest.flush(); self.n_rest += 1
            elif m == "Network.webSocketCreated":
                self.ws_urls[rid] = p.get("url")
            elif m in ("Network.webSocketFrameSent", "Network.webSocketFrameReceived"):
                url = self.ws_urls.get(rid, "")
                if self._interesting(url):
                    payload = (p.get("response") or {}).get("payloadData", "")
                    if len(payload) > 6000:
                        payload = payload[:6000] + f"... [{len(payload)} chars]"
                    self.ws.write(json.dumps({"dir": "out" if m.endswith("Sent") else "in",
                                              "url": url, "ts": p.get("timestamp"),
                                              "payload": payload}) + "\n")
                    self.ws.flush(); self.n_ws += 1


def _click_text(d, texts, tags=("button", "a", "div", "span")):
    for t in texts:
        for tag in tags:
            els = d.find_elements(By.XPATH, f"//{tag}[normalize-space(.)='{t}' or contains(normalize-space(.),'{t}')]")
            for el in els:
                try:
                    if el.is_displayed() and el.is_enabled():
                        el.click(); return True
                except Exception:
                    continue
    return False


def _find_email_input(d):
    for sel in ("input[type='email']", "input[name='email']", "input[inputmode='email']",
                "input[placeholder*='mail' i]", "input[autocomplete='email']"):
        for el in d.find_elements(By.CSS_SELECTOR, sel):
            if el.is_displayed():
                return el
    return None


def _otp_inputs(d):
    boxes = [e for e in d.find_elements(By.CSS_SELECTOR,
             "input[inputmode='numeric'], input[autocomplete='one-time-code'], input[type='tel'], input[maxlength='1'], input[maxlength='6']")
             if e.is_displayed()]
    return boxes


def _logged_in(d):
    try:
        return d.execute_script("""
          const t = (document.body.innerText||'');
          if (/Sign Up|Log In|Login|Connect Wallet/i.test(t) && !/Account Value|Trading Power/i.test(t)) return false;
          return Object.keys(localStorage).some(k => /privy|vest|access|token/i.test(k)) &&
                 !/Log In/i.test(t.slice(0, 4000));
        """)
    except Exception:
        return False


def _mailbox_code(since: float, timeout: int = 180):
    """6-digit Privy code from the login mailbox, or None when not configured / not received."""
    try:
        from trader_companion.email_codes import Mailbox
    except ImportError:
        return None
    mb = Mailbox.from_env()
    if mb is None:
        return None
    print("Fetching the code from the mailbox…")
    code = mb.wait_for_code(since, match=("vest", "privy"), timeout=timeout)
    print("Mailbox code:", "received" if code else "not received in time")
    return code


def email_login(d, email, symbol="NDX-USD-PERP", otp_prompt=input) -> bool:
    """Walk the Privy email login on an open driver; returns logged-in state."""
    url = f"https://next.vestmarkets.com/trade/{symbol}"
    print(f"Opening {url}")
    d.get(url)
    time.sleep(5)
    if _logged_in(d):
        print("Already logged in (persistent profile).")
        return True
    print("Starting email login…")
    _click_text(d, ["Log In", "Login", "Sign Up", "Sign in", "Connect"])
    time.sleep(2.5)
    # Privy modal may have an "email" tab/option
    _click_text(d, ["Continue with email", "Email", "Use email"])
    time.sleep(1.5)
    inp = _find_email_input(d)
    manual = inp is None
    if manual:
        print("Could not find the email field — please complete login manually in Chrome "
              "(waiting up to 4 minutes)…")
    else:
        inp.click(); inp.send_keys(Keys.COMMAND, "a"); inp.send_keys(Keys.BACKSPACE)
        inp.send_keys(email)
        time.sleep(0.5)
        sent_at = time.time()
        if not _click_text(d, ["Submit", "Continue", "Send code", "Next"]):
            inp.send_keys(Keys.ENTER)
        print(f"Email submitted for {email}. Waiting for the one-time code…")
        time.sleep(3)
        code = _mailbox_code(sent_at) or ""
        if not code:
            code = otp_prompt("Enter the 6-digit code from the email (or press Enter if you typed it in Chrome): ").strip()
        if code:
            boxes = _otp_inputs(d)
            if len(boxes) >= 6:
                for b, ch in zip(boxes, code):
                    b.send_keys(ch)
            elif boxes:
                boxes[0].send_keys(code)
            else:
                print("No OTP inputs found — type the code in Chrome.")
    for _ in range(240 if manual else 60):
        if _logged_in(d):
            break
        time.sleep(1)
    ok = _logged_in(d)
    print("Logged in:", ok)
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--email", required=True)
    p.add_argument("--symbol", default="NDX-USD-PERP")
    p.add_argument("--hold", type=int, default=600, help="seconds to keep capturing after login")
    p.add_argument("--profile", default="vest_default")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    d = _driver(a.profile)
    cap = Capture(d).start()
    email_login(d, a.email, a.symbol)

    time.sleep(6)
    # Storage snapshot (keys + shapes only; token values redacted)
    try:
        ls = d.execute_script("""
          const o={}; for (const k of Object.keys(localStorage)) { const v=localStorage.getItem(k)||'';
            o[k] = v.length>60 ? v.slice(0,40)+'…['+v.length+']' : v; } return o;""")
        with open(f"{OUT}/localStorage.json", "w") as f:
            json.dump(ls, f, indent=1)
        print("localStorage keys:", sorted(ls.keys()))
    except Exception as exc:
        print("localStorage read failed:", exc)

    try:
        txt = d.execute_script("return document.body.innerText") or ""
        with open(f"{OUT}/body.txt", "w") as f:
            f.write(txt)
        m = re.search(r"Account Value[\s\S]{0,80}", txt)
        print("Account snippet:", (m.group(0).replace("\n", " | ") if m else "n/a"))
    except Exception:
        pass

    print(f"\nCapturing for {a.hold}s (rest={cap.n_rest} ws={cap.n_ws} so far). "
          f"Click around / change leverage / open the order ticket in Chrome to exercise the API.\n"
          f"Files: {OUT}/rest.jsonl  {OUT}/ws.jsonl  (Ctrl-C to stop early)")
    try:
        t_end = time.time() + a.hold
        while time.time() < t_end:
            time.sleep(10)
            print(f"  … rest={cap.n_rest} ws={cap.n_ws}")
    except KeyboardInterrupt:
        pass
    cap.stop()
    print(f"Done. rest={cap.n_rest} ws={cap.n_ws}. Chrome left open? no — closing.")
    d.quit()


if __name__ == "__main__":
    main()
