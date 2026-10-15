"""Breakout Prop live probe — plain Chrome + raw CDP (Cloudflare-safe).

Breakout (portal.breakoutprop.com → trade.breakoutprop.com, Kraken-backed) sits
behind Cloudflare bot management, which blocks every API call the moment
ChromeDriver is attached. This probe therefore launches a *normal* Chrome with a
DevTools port and drives it over a raw CDP socket (Network domain only).

Login is Descope's **enchanted link**: email → "Continue with Email" → you click
the link in the email (same browser profile is not required) → the sign-in tab
authenticates itself and redirects to the trade app. Every API request/response
and WS frame is written to /tmp/breakout_capture/*.jsonl. Nothing is traded.

    python -m trader_companion.breakout_probe --email you@example.com --hold 900
"""

import argparse
import json
import logging
import os
import re
import subprocess
import time
import urllib.request

from trader_companion.cdp_capture import CDPCapture


def _open_helper_tab(url: str, port: int = None):
    """Open `url` in a new tab of the plain Chrome (same as clicking it); return its target id."""
    req = urllib.request.Request(f"http://localhost:{port or PORT}/json/new?{url}", method="PUT")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r).get("id")


def _close_tab(target_id: str, port: int = None):
    try:
        urllib.request.urlopen(f"http://localhost:{port or PORT}/json/close/{target_id}", timeout=5)
    except Exception:
        pass


COOKIES_EL = "document.querySelector('#onetrust-accept-btn-handler')"


def accept_cookies(cap: "CDPCapture", tries: int = 20) -> bool:
    """Click the OneTrust 'Accept All Cookies' banner if/when it shows (it blocks the Descope flow)."""
    for _ in range(tries):
        try:
            vis = cap.eval_js(f"(() => {{ const b = {COOKIES_EL}; if (!b) return false; "
                              f"const r = b.getBoundingClientRect(); return r.width > 0 && r.height > 0; }})()")
            if vis and _click_center(cap, COOKIES_EL):
                time.sleep(0.6)
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _drive_helper_tab(target_id: str, port: int, wait_sec: int = 60, url: str = None):
    """Attach to the link tab (before navigating when `url` is given), accept cookies,
    wait for the verification to settle, and report the Descope calls it made."""
    helper = CDPCapture(port, HOSTS + ("descope",), OUT + "/helper")
    try:
        helper.target = next(t for t in helper._targets() if t.get("id") == target_id)
    except StopIteration:
        return
    import websocket, threading
    helper.ws = websocket.create_connection(helper.target["webSocketDebuggerUrl"], suppress_origin=True, timeout=30)
    helper._thread = threading.Thread(target=helper._loop, daemon=True)
    helper._thread.start()
    try:
        helper.send("Network.enable", {})
        if url:
            helper.navigate(url)
        accepted = accept_cookies(helper, tries=30)
        print("  helper tab: cookies", "accepted" if accepted else "banner not shown")
        last = ""
        for _ in range(wait_sec):
            time.sleep(1)
            txt = (helper.eval_js(DEEP_TEXT_JS) or "").strip()
            if txt and txt.lower() != "loading...":
                last = txt
                break
        print("  helper tab says:", (last or helper.eval_js(DEEP_TEXT_JS) or "")[:160])
        accept_cookies(helper, tries=4)
    finally:
        helper.stop()
    try:
        for line in open(OUT + "/helper/rest.jsonl"):
            r = json.loads(line)
            u = r["url"]
            if "auth.portal" in u or "descope" in u or "/api/internal/" in u:
                if r["method"] != "OPTIONS":
                    print(f"  helper {r['method']} {u.split('?')[0][-60:]} -> {r.get('status')}")
    except OSError:
        pass


def _mailbox_numbered_links(since: float, recipient: str = None, timeout: int = 180) -> dict:
    """{number: url} from the Breakout 'click the number that matches your screen' mail."""
    try:
        from trader_companion.email_codes import Mailbox
    except ImportError:
        return {}
    mb = Mailbox.from_env()
    if mb is None:
        return {}
    print(f"Fetching the numbered sign-in links for {recipient or 'this login'} from the mailbox…")
    links = mb.wait_for_numbered_links(since, match=("breakout",), link_match="descope-login-flow=",
                                       timeout=timeout, recipient=recipient)
    print("Mailbox links:", sorted(links) if links else "not received in time")
    return links


# Descope renders inside web components; walk shadow roots for the visible text.
DEEP_TEXT_JS = """(() => { const out=[]; const skip=new Set(['SCRIPT','STYLE','NOSCRIPT','TEMPLATE']);
 const walk = (root) => { for (const el of root.querySelectorAll('*')) {
   if (skip.has(el.tagName)) continue;
   if (el.shadowRoot) walk(el.shadowRoot);
   const r=el.getBoundingClientRect(); if (!r.width && !r.height) continue;
   if (el.children.length===0) { const t=(el.textContent||'').trim(); if (t && t.length<200) out.push(t); } } };
 walk(document); return out.join(' | '); })()"""


def screen_number(cap: CDPCapture, timeout: int = 30):
    """The number the Descope screen tells the user to click in the email."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        txt = cap.eval_js(DEEP_TEXT_JS) or ""
        m = re.search(r"click the following number[^|]*\|\s*(\d{1,3})\b", txt, flags=re.I)
        if m:
            return m.group(1)
        time.sleep(1)
    return None


DESCOPE_BASE = "https://auth.portal.breakoutprop.com"
DESCOPE_PROJECT = "P30ebYsO2pb5jXy4sBRBSn1DHfJa"


def verify_link_in_tab(cap: CDPCapture, link: str) -> dict:
    """Consume the enchanted link without opening it: the link page only ever
    POSTs /v1/flow/next {executionId, stepId, interactionId:'submit', input:{token}}
    (captured live). Doing that from the polling tab keeps everything in one tab."""
    from urllib.parse import urlparse, parse_qs, unquote
    q = parse_qs(urlparse(link).query)
    flow = unquote((q.get("descope-login-flow") or [""])[0])      # "<flowId>|#|<execId>_<stepId>"
    token = (q.get("t") or [""])[0]
    if "|#|" not in flow or not token:
        return {"ok": False, "error": "link has no flow/token"}
    flow_id, rest = flow.split("|#|", 1)
    exec_id, _, step_id = rest.partition("_")
    project = cap.eval_js("""(() => { const el = document.querySelector('descope-wc,[project-id]');
        return (el && el.getAttribute('project-id')) || null; })()""") or DESCOPE_PROJECT
    body = {"executionId": f"{flow_id}|#|{exec_id}", "stepId": step_id or "8.end",
            "interactionId": "submit", "version": 7, "componentsVersion": "3.17.0",
            "input": {"token": token}, "isCustomScreen": False}
    js = f"""fetch({json.dumps(DESCOPE_BASE + '/v1/flow/next')}, {{method:'POST',
        headers: {{'authorization': 'Bearer {project}', 'content-type': 'application/json'}},
        body: {json.dumps(json.dumps(body))}}})
      .then(async r => ({{status: r.status, text: await r.text()}}))
      .catch(e => ({{status: -1, text: String(e)}}))"""
    res = cap.send("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True}, timeout=60)
    v = ((res or {}).get("result") or {}).get("value") or {}
    try:
        data = json.loads(v.get("text") or "{}")
    except ValueError:
        data = {}
    ok = v.get("status") == 200 and not data.get("error")
    return {"ok": ok, "status": v.get("status"), "stepName": data.get("stepName"),
            "flowStatus": data.get("status"), "error": (data.get("error") or {}).get("message")
            if isinstance(data.get("error"), dict) else data.get("error")}

OUT = "/tmp/breakout_capture"
HOSTS = ("breakoutprop.com", "kraken.com", "payward")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9333
PROFILE = "/tmp/chrome_profiles/breakout_cdp"
TRADE_URL = "https://trade.breakoutprop.com/app"
PORTAL_APP = "portal.breakoutprop.com/app"
SIGNIN_URL = "https://portal.breakoutprop.com/sign-in?redirect=https%3A%2F%2Ftrade.breakoutprop.com%2Fapp"
log = logging.getLogger("breakout-probe")


def chrome_for(email: str) -> tuple:
    """(port, profile_dir) for one login — each client gets its own plain Chrome."""
    import hashlib
    key = (email or "").strip().lower()
    if not key:
        return PORT, PROFILE
    h = int(hashlib.sha1(key.encode()).hexdigest()[:6], 16)
    slug = re.sub(r"[^a-z0-9]+", "_", key.split("@")[0])[:24]
    return 9400 + (h % 400), f"/tmp/chrome_profiles/breakout_{slug}"


def _cdp_alive(port: int = None) -> bool:
    try:
        urllib.request.urlopen(f"http://localhost:{port or PORT}/json/version", timeout=1.5)
        return True
    except Exception:
        return False


def launch_chrome(url=SIGNIN_URL, port: int = None, profile: str = None):
    port = port or PORT
    profile = profile or PROFILE
    if _cdp_alive(port):
        return
    os.makedirs(profile, exist_ok=True)
    subprocess.Popen([CHROME, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                      "--no-first-run", "--no-default-browser-check", "--window-size=1280,900", url],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(40):
        if _cdp_alive(port):
            return
        time.sleep(0.5)
    raise RuntimeError("Chrome did not expose the DevTools port")


def quit_chrome(port: int = None, wait_sec: float = 5.0) -> bool:
    """Close the plain Chrome on `port` (Browser.close over CDP, then kill fallback).

    launch_chrome starts Chrome detached (start_new_session) and keeps no
    handle, so without this the Breakout window outlived the companion.
    """
    port = port or PORT
    if not _cdp_alive(port):
        return True
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=2) as r:
            ws_url = json.load(r).get("webSocketDebuggerUrl")
        if ws_url:
            import websocket  # websocket-client
            ws = websocket.create_connection(ws_url, timeout=3, suppress_origin=True)
            try:
                ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
            finally:
                try:
                    ws.close()
                except Exception:
                    pass
    except Exception as exc:
        log.debug("Browser.close on port %s failed: %s", port, exc)
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if not _cdp_alive(port):
            return True
        time.sleep(0.25)
    # Chrome ignored the request (e.g. a beforeunload prompt) — kill by port flag.
    try:
        subprocess.run(["pkill", "-f", f"--remote-debugging-port={port}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except Exception as exc:
        log.debug("pkill for Chrome port %s failed: %s", port, exc)
    time.sleep(0.5)
    return not _cdp_alive(port)


def body_text(cap: CDPCapture) -> str:
    try:
        return cap.eval_js("document.body ? document.body.innerText : ''") or ""
    except Exception:
        return ""


def on_trade_app(cap: CDPCapture) -> bool:
    url = cap.current_url()
    if not url.startswith("https://trade.breakoutprop.com"):
        return False
    if "cloudflare" in cap.page_title().lower():
        return False
    return bool(re.search(r"Balance|Equity|Buy|Sell|Positions|Orders?", body_text(cap)))


def _type(cap: CDPCapture, text: str):
    for ch in text:
        cap.send("Input.dispatchKeyEvent", {"type": "keyDown", "text": ch, "key": ch})
        cap.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": ch})
        time.sleep(0.03)


def _click_center(cap: CDPCapture, js_selector_expr: str) -> bool:
    """Real mouse click at the centre of the element returned by `js_selector_expr`."""
    rect = cap.eval_js(f"""(() => {{ const el = {js_selector_expr}; if (!el) return null;
        el.scrollIntoView({{block:'center'}}); const r = el.getBoundingClientRect();
        return {{x: r.left + r.width/2, y: r.top + r.height/2, w: r.width}}; }})()""")
    if not rect or not rect.get("w"):
        return False
    x, y = rect["x"], rect["y"]
    cap.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    cap.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    cap.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
    return True


EMAIL_EL = "document.querySelector(\"input[name='email'],input[autocomplete='email'],input[type='email']\")"
CONTINUE_EL = ("[...document.querySelectorAll('button')].find(b => /Continue with Email/i.test(b.innerText))")


def email_login(cap: CDPCapture, email: str, otp_prompt=None, port: int = None) -> bool:
    """portal sign-in: email → Continue → numbered link matched to the screen → trade app."""
    port = port or cap.port
    if on_trade_app(cap):
        print("Already on the trade app (session persisted).")
        return True
    if "portal.breakoutprop.com/sign-in" not in cap.current_url():
        cap.navigate(SIGNIN_URL)
    for i in range(45):
        time.sleep(1)
        if on_trade_app(cap):
            print("Already logged in.")
            return True
        if "cloudflare" in cap.page_title().lower():
            if i % 10 == 9:
                print("  Cloudflare interstitial — waiting…")
            continue
        if cap.eval_js(f"!!{EMAIL_EL}"):
            break
    else:
        print("Email field not found — complete the sign-in manually in Chrome.")
    accept_cookies(cap, tries=6)
    time.sleep(0.5)
    sent_at = None
    if _click_center(cap, EMAIL_EL):
        cap.eval_js(f"{EMAIL_EL}.value=''")
        _type(cap, email)
        time.sleep(0.4)
        sent_at = time.time()
        if not _click_center(cap, CONTINUE_EL):
            cap.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "windowsVirtualKeyCode": 13})
            cap.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "windowsVirtualKeyCode": 13})
        time.sleep(4)
        print("Page now says:", body_text(cap)[:220].replace("\n", " | "))
    links = _mailbox_numbered_links(sent_at, recipient=email) if sent_at else {}
    if links:
        want = screen_number(cap)
        print(f"Screen asks for number {want}; email offers {sorted(links)}")
        link = links.get(want) if want else None
        if not link and len(links) == 1:
            link = next(iter(links.values()))
        if link:
            # Replay what the link page would do — one POST to Descope — from the
            # polling tab itself, so no second tab is ever opened and the polling
            # tab receives the session and redirects on its own.
            print(f"Verifying link #{want} from this tab…")
            res = verify_link_in_tab(cap, link)
            print("  verify:", res)
            if not res.get("ok"):
                print("  falling back to opening the link in this tab…")
                cap.navigate(link)
                for i in range(90):
                    time.sleep(1)
                    if i % 3 == 0:
                        accept_cookies(cap, tries=1)
                    if on_trade_app(cap) or PORTAL_APP in cap.current_url():
                        break
                if not on_trade_app(cap):
                    cap.navigate(TRADE_URL)
        else:
            print("  no link matches the on-screen number — click it yourself in the email")
    else:
        print(f"\nA sign-in link has been emailed to {email}. Click the number shown on screen — this tab\n"
              f"will authenticate itself. Waiting up to 5 minutes…")
    for i in range(300):
        time.sleep(1)
        if on_trade_app(cap):
            break
        if i % 5 == 4:
            accept_cookies(cap, tries=1)      # the sign-in tab can show the banner too
        if i % 30 == 29:
            print(f"  … still waiting ({cap.current_url()[:70]})")
    ok = on_trade_app(cap)
    print("Logged in:", ok, "|", cap.current_url())
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--email", default=os.environ.get("BREAKOUT_EMAIL") or os.environ.get("VEST_EMAIL", ""))
    p.add_argument("--hold", type=int, default=900)
    a = p.parse_args()
    logging.basicConfig(level=logging.WARNING)

    os.makedirs(OUT, exist_ok=True)
    for name in ("rest.jsonl", "ws.jsonl"):
        try:
            os.remove(os.path.join(OUT, name))
        except OSError:
            pass
    launch_chrome()
    time.sleep(2)
    cap = CDPCapture(PORT, HOSTS, OUT, url_hint="breakoutprop.com").start()
    print("Attached to:", cap.target.get("url"))

    if a.email:
        email_login(cap, a.email)
    else:
        input("Log in to Breakout in the Chrome window, then press Enter here… ")
    time.sleep(8)

    try:
        ls = cap.eval_js("""(() => { const o={}; for (const k of Object.keys(localStorage)) {
            const v=localStorage.getItem(k)||''; o[k] = v.length>60 ? v.slice(0,40)+'…['+v.length+']' : v; }
            return o; })()""") or {}
        with open(f"{OUT}/localStorage.json", "w") as f:
            json.dump(ls, f, indent=1)
        print("localStorage keys:", sorted(ls.keys()))
        cookies = cap.send("Network.getCookies", {"urls": ["https://trade.breakoutprop.com",
                                                             "https://iapi.breakoutprop.com",
                                                             "https://portal.breakoutprop.com"]})
        print("cookies:", sorted({c["name"] for c in (cookies or {}).get("cookies", [])}))
    except Exception as exc:
        print("storage read failed:", exc)
    txt = body_text(cap)
    with open(f"{OUT}/body.txt", "w") as f:
        f.write(txt)
    m = re.search(r"(Balance|Equity|Account)[\s\S]{0,160}", txt)
    print("page snippet:", (m.group(0).replace("\n", " | ") if m else txt[:300].replace("\n", " | ")))

    print(f"\nCapturing for {a.hold}s (rest={cap.n_rest} ws={cap.n_ws} so far). Browse the trade "
          f"screen: order ticket, leverage, positions, history.\nFiles: {OUT}/rest.jsonl  {OUT}/ws.jsonl  "
          f"(Ctrl-C to stop early; Chrome is left open)")
    try:
        t_end = time.time() + a.hold
        while time.time() < t_end:
            time.sleep(10)
            print(f"  … rest={cap.n_rest} ws={cap.n_ws}")
    except KeyboardInterrupt:
        pass
    cap.stop()
    print(f"Done. rest={cap.n_rest} ws={cap.n_ws}. Chrome left open on port {PORT}.")


if __name__ == "__main__":
    main()
