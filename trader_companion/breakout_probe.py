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


def _open_helper_tab(url: str):
    """Open `url` in a new tab of the plain Chrome (same as clicking it); return its target id."""
    req = urllib.request.Request(f"http://localhost:{PORT}/json/new?{url}", method="PUT")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r).get("id")


def _close_tab(target_id: str):
    try:
        urllib.request.urlopen(f"http://localhost:{PORT}/json/close/{target_id}", timeout=5)
    except Exception:
        pass


def _mailbox_link(since: float, recipient: str = None, timeout: int = 180):
    """Breakout/Descope sign-in link addressed to `recipient`, or None."""
    try:
        from trader_companion.email_codes import Mailbox
    except ImportError:
        return None
    mb = Mailbox.from_env()
    if mb is None:
        return None
    print(f"Fetching the sign-in link for {recipient or 'this login'} from the mailbox…")
    # The mail also carries a plain /sign-in footer link; only the Descope flow URL authenticates.
    link = mb.wait_for_link(since, match=("breakout",), link_match="descope-login-flow=",
                            timeout=timeout, recipient=recipient)
    if not link:
        link = mb.wait_for_link(since, match=("breakout",), link_match="descope", timeout=15,
                                recipient=recipient)
    print("Mailbox link:", "received" if link else "not received in time")
    return link

OUT = "/tmp/breakout_capture"
HOSTS = ("breakoutprop.com", "kraken.com", "payward")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9333
PROFILE = "/tmp/chrome_profiles/breakout_cdp"
TRADE_URL = "https://trade.breakoutprop.com/app"
SIGNIN_URL = "https://portal.breakoutprop.com/sign-in?redirect=https%3A%2F%2Ftrade.breakoutprop.com%2Fapp"
log = logging.getLogger("breakout-probe")


def _cdp_alive() -> bool:
    try:
        urllib.request.urlopen(f"http://localhost:{PORT}/json/version", timeout=1.5)
        return True
    except Exception:
        return False


def launch_chrome(url=SIGNIN_URL):
    if _cdp_alive():
        return
    os.makedirs(PROFILE, exist_ok=True)
    subprocess.Popen([CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
                      "--no-first-run", "--no-default-browser-check", "--window-size=1280,900", url],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(40):
        if _cdp_alive():
            return
        time.sleep(0.5)
    raise RuntimeError("Chrome did not expose the DevTools port")


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
COOKIES_EL = "document.querySelector('#onetrust-accept-btn-handler')"


def email_login(cap: CDPCapture, email: str) -> bool:
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
    _click_center(cap, COOKIES_EL)
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
    helper = None
    link = _mailbox_link(sent_at, recipient=email) if sent_at else None
    if link:
        print("Opening the sign-in link in a helper tab…")
        try:
            helper = _open_helper_tab(link)
        except Exception as exc:
            print("  helper tab failed:", exc)
    else:
        print(f"\nA sign-in link has been emailed to {email}. Click it (any browser/phone) — this tab\n"
              f"will authenticate itself. Waiting up to 5 minutes…")
    for i in range(300):
        time.sleep(1)
        if on_trade_app(cap):
            break
        if i % 30 == 29:
            print(f"  … still waiting ({cap.current_url()[:70]})")
    if helper:
        _close_tab(helper)
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
