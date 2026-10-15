"""MyFundedPerps observer window: plain Chrome on the trading workspace.

The companion trades MyFundedPerps through the REST API (no browser needed),
so until now nothing was visible. myfundedperpetuals.com sits behind
Cloudflare Turnstile, which blocks ChromeDriver the same way Breakout does, so
this follows the Breakout model: launch a *normal* Chrome with a DevTools port
(own persistent profile per login) and drive it over raw CDP. Sign-in is the
firm's email + six-digit code flow; the code is read from the ops mailbox
(`email_codes.Mailbox`, same forwarding setup as Vest / Breakout). Later
launches reuse the profile's session. The API connection is unaffected — the
window is for eyes only.

    python -m trader_companion.perps_login --email you@example.com
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import tempfile
import time

from trader_companion import breakout_probe as probe
from trader_companion.cdp_capture import CDPCapture

log = logging.getLogger("perps-login")

HOME_URL = os.environ.get("MFP_HOME_URL", "https://myfundedperpetuals.com/")
TRADE_URL = os.environ.get("MFP_TRADE_URL", "https://myfundedperpetuals.com/trade")
SIGNIN_URL = os.environ.get("MFP_SIGNIN_URL", "https://myfundedperpetuals.com/auth/sign-in")
MAIL_MATCH = ("myfundedperp", "fundedperp", "perpetuals")
HOSTS = ("myfundedperpetuals.com",)

EMAIL_EL = ("document.querySelector(\"input[type='email'],input[name='email'],"
            "input[autocomplete='email'],input[inputmode='email'],input[placeholder*='mail' i]\")")
CODE_INPUTS_JS = ("[...document.querySelectorAll(\"input[inputmode='numeric'],"
                  "input[autocomplete='one-time-code'],input[type='tel'],input[maxlength='1'],"
                  "input[maxlength='6'],input[name*='code' i],input[placeholder*='code' i]\")]"
                  ".filter(e => e.offsetParent !== null)")
BUTTON_JS = ("[...document.querySelectorAll('button,a,[role=button]')].find(b => "
             "b.offsetParent !== null && /{pattern}/i.test((b.innerText||b.textContent||'').trim()))")


def chrome_for(email: str) -> tuple:
    """(port, profile_dir) for one login — its own plain Chrome, like Breakout."""
    key = (email or "").strip().lower()
    h = int(hashlib.sha1(key.encode()).hexdigest()[:6], 16) if key else 0
    slug = re.sub(r"[^a-z0-9]+", "_", key.split("@")[0])[:24] or "default"
    return 9800 + (h % 150), os.path.join(tempfile.gettempdir(), "chrome_profiles", f"mfp_{slug}")


def observer_profile(email: str) -> str:
    return "mfp_view_" + re.sub(r"[^a-z0-9]+", "_", (email or "").strip().lower().split("@")[0])[:32]


def _text(cap: CDPCapture) -> str:
    try:
        return cap.eval_js("document.body ? document.body.innerText : ''") or ""
    except Exception:
        return ""


def _on_cloudflare(cap: CDPCapture) -> bool:
    t = _text(cap)
    return bool(re.search(r"Performing security verification|Verify you are human|Just a moment", t)) \
        or "just a moment" in cap.page_title().lower()


def _logged_in(cap: CDPCapture) -> bool:
    try:
        return bool(cap.eval_js("""(() => {
          const t = (document.body && document.body.innerText) || '';
          if (/Performing security verification|Verify you are human/i.test(t)) return false;
          const head = t.slice(0, 6000);
          const signedOut = /\\bSign In\\b|\\bSign Up\\b|\\bLog In\\b/i.test(head)
                            && !/Sign Out|Log Out/i.test(t);
          const workspace = /Account Value|Equity|Balance|Positions|Open Orders|Dashboard|Sign Out|Log Out/i.test(t);
          return workspace && !signedOut;
        })()"""))
    except Exception:
        return False


def _click(cap: CDPCapture, pattern: str) -> bool:
    return probe._click_center(cap, BUTTON_JS.format(pattern=pattern))


TURNSTILE_RECT_JS = """(() => {
  // Cloudflare renders the widget inside a shadow root; the host div is what
  // we can measure. The checkbox sits at the far left of the widget.
  const deep = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.tagName === 'IFRAME' && /challenges\\.cloudflare\\.com|turnstile/i.test(el.src || el.title || '')) return el;
      if (el.shadowRoot) { const f = deep(el.shadowRoot); if (f) return f; }
    }
    return null;
  };
  let el = deep(document);
  if (!el) el = document.querySelector('#challenge-stage, [id^="cf-chl-widget"], .cf-turnstile, #turnstile-wrapper, [name="cf-turnstile-response"]');
  if (!el) {
    const lbl = [...document.querySelectorAll('label,span,div')].find(e => /Verify you are human/i.test(e.textContent || '') && e.children.length < 3);
    el = lbl ? lbl.closest('div') : null;
  }
  if (!el) return null;
  el.scrollIntoView({block: 'center'});
  const r = el.getBoundingClientRect();
  if (!r.width) return null;
  return {x: r.left + Math.min(28, r.width / 2), y: r.top + r.height / 2, w: r.width};
})()"""


def _turnstile_box(cap: CDPCapture):
    """Content quad of the Turnstile iframe via the CDP DOM domain.

    The widget renders inside a *closed* shadow root, so page JavaScript
    (querySelector / shadowRoot) cannot see it; DOM.getDocument(pierce=true)
    can. Returns (x1, y1, x2, y2) or None.
    """
    try:
        doc = cap.send("DOM.getDocument", {"depth": -1, "pierce": True})
    except Exception:
        return None
    hit = []

    def walk(node):
        if hit:
            return
        attrs = node.get("attributes") or []
        a = dict(zip(attrs[::2], attrs[1::2]))
        if node.get("nodeName") == "IFRAME" and "challenges.cloudflare.com" in (a.get("src") or ""):
            hit.append(node["nodeId"])
            return
        for child in node.get("children") or []:
            walk(child)
        for shadow in node.get("shadowRoots") or []:
            walk(shadow)
        if node.get("contentDocument"):
            walk(node["contentDocument"])

    walk(doc.get("root") or {})
    if not hit:
        return None
    try:
        quad = cap.send("DOM.getBoxModel", {"nodeId": hit[0]})["model"]["content"]
    except Exception:
        return None
    xs, ys = quad[0::2], quad[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def _click_turnstile(cap: CDPCapture) -> bool:
    box = _turnstile_box(cap)
    if not box:
        rect = cap.eval_js(TURNSTILE_RECT_JS)
        if not rect:
            return False
        x, y = rect["x"], rect["y"]
    else:
        x1, y1, x2, y2 = box
        if x2 - x1 < 10 or y2 - y1 < 10:
            return False
        x, y = x1 + 30, (y1 + y2) / 2     # checkbox sits at the widget's left edge
    cap.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    time.sleep(0.15)
    cap.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y,
                                          "button": "left", "clickCount": 1})
    time.sleep(0.08)
    cap.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y,
                                          "button": "left", "clickCount": 1})
    return True


def _wait_past_cloudflare(cap: CDPCapture, wait_sec: int = 120) -> bool:
    """Turnstile sometimes passes by itself in a plain Chrome; otherwise tick the box
    (retrying every few seconds while the widget re-renders)."""
    started = time.time()
    last_nudge = 0.0
    nudges = 0
    while time.time() - started < wait_sec:
        if not _on_cloudflare(cap):
            return True
        if time.time() - last_nudge > 5:
            if _click_turnstile(cap):
                nudges += 1
                log.info("MyFundedPerps: clicked the Cloudflare checkbox (%d)", nudges)
            last_nudge = time.time()
        time.sleep(1)
    return not _on_cloudflare(cap)


def _mailbox_code(since: float, recipient: str = None, timeout: int = 180):
    """Six-digit code from the newest MyFundedPerps mail, or None."""
    try:
        from trader_companion.email_codes import Mailbox
    except ImportError:
        return None
    mb = Mailbox.from_env()
    if mb is None:
        return None
    log.info("Fetching the MyFundedPerps code for %s from the mailbox…", recipient or "this login")
    code = mb.wait_for_code(since, match=MAIL_MATCH, timeout=timeout, recipient=recipient)
    if code:
        log.info("Mailbox: six-digit code received")
    else:
        log.info("Mailbox: no code in time — is %s forwarding to %s?", recipient or "the login", mb.user)
    return code


def _press_enter(cap: CDPCapture):
    cap.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter",
                                        "windowsVirtualKeyCode": 13, "text": "\r"})
    cap.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter",
                                        "windowsVirtualKeyCode": 13})


def email_login(cap: CDPCapture, email: str, otp_prompt=None) -> bool:
    """Walk the email + six-digit-code sign-in on an open tab; returns logged-in state."""
    otp_prompt = otp_prompt or (lambda *_: "")
    cap.navigate(TRADE_URL)
    time.sleep(4)
    if not _wait_past_cloudflare(cap):
        log.warning("MyFundedPerps: Cloudflare check did not clear — tick the box in Chrome")
    if _logged_in(cap):
        log.info("MyFundedPerps: already signed in (persistent profile)")
        return True

    cap.navigate(SIGNIN_URL)
    time.sleep(3)
    _wait_past_cloudflare(cap)
    if not cap.eval_js(f"!!{EMAIL_EL}"):
        _click(cap, r"Sign In|Log In|Login")
        time.sleep(2.5)
        _click(cap, r"Continue with email|Use email|^Email$")
        time.sleep(1.5)

    have_email = False
    for _ in range(20):
        if cap.eval_js(f"!!{EMAIL_EL}"):
            have_email = True
            break
        time.sleep(1)
    manual = not have_email
    if manual:
        log.warning("MyFundedPerps: email field not found — complete sign-in by hand in Chrome "
                    "(waiting up to 4 minutes)")
    else:
        probe._click_center(cap, EMAIL_EL)
        cap.eval_js(f"(() => {{ const e = {EMAIL_EL}; e.focus(); e.value=''; "
                    f"e.dispatchEvent(new Event('input', {{bubbles:true}})); }})()")
        probe._type(cap, email)
        time.sleep(0.5)
        sent_at = time.time()
        if not _click(cap, r"Continue|Send code|Send Code|Next|Submit|Sign In"):
            _press_enter(cap)
        log.info("MyFundedPerps: email submitted for %s — waiting for the six-digit code", email)
        time.sleep(3)
        code = (_mailbox_code(sent_at, recipient=email) or "").strip()
        if not code:
            code = str(otp_prompt("Enter the 6-digit MyFundedPerps code "
                                  "(or press Enter if you typed it in Chrome): ") or "").strip()
            if not code:
                manual = True   # code must be typed in Chrome — allow the long wait
        if code:
            n_boxes = cap.eval_js(f"({CODE_INPUTS_JS}).length") or 0
            if n_boxes:
                probe._click_center(cap, f"({CODE_INPUTS_JS})[0]")
                probe._type(cap, code)   # single field or auto-advancing digit boxes
            else:
                log.warning("MyFundedPerps: no code inputs found — type the code in Chrome")
            time.sleep(1)
            if not _click(cap, r"Verify|Continue|Confirm"):
                _press_enter(cap)
    for _ in range(240 if manual else 90):
        if _logged_in(cap):
            break
        time.sleep(1)
    ok = _logged_in(cap)
    if ok and "/trade" not in cap.current_url():
        cap.navigate(TRADE_URL)
        time.sleep(3)
    log.info("MyFundedPerps signed in: %s (%s)", ok, cap.current_url())
    return ok


class PerpsObserver:
    """Owns the plain-Chrome window for one MyFundedPerps login."""

    def __init__(self, email: str):
        self.email = email
        self.port, self.profile = chrome_for(email)
        self.logged_in = False

    @property
    def title(self):
        """Raises once the window is gone — mirrors the Selenium driver probe."""
        if not probe._cdp_alive(self.port):
            raise RuntimeError("MyFundedPerps window closed")
        return "MyFundedPerps"

    def open(self, otp_prompt=None) -> bool:
        probe.launch_chrome(url=TRADE_URL, port=self.port, profile=self.profile)
        time.sleep(1.5)
        cap = CDPCapture(self.port, HOSTS, os.path.join(tempfile.gettempdir(), "mfp_capture"),
                         url_hint="myfundedperpetuals.com").start()
        try:
            self.logged_in = email_login(cap, self.email, otp_prompt=otp_prompt)
        finally:
            try:
                cap.stop()
            except Exception:
                pass
        return self.logged_in

    def quit(self):
        probe.quit_chrome(self.port)


def open_observer(email: str, otp_prompt=None):
    """Visible Chrome on the MyFundedPerps workspace. Returns (observer, logged_in);
    the caller owns the observer and must quit() it."""
    obs = PerpsObserver(email)
    try:
        ok = obs.open(otp_prompt=otp_prompt)
    except Exception as exc:
        log.warning("MyFundedPerps observer login failed: %s", exc)
        ok = False
    return obs, ok


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--email", required=True)
    p.add_argument("--hold", type=int, default=600, help="seconds to keep the window open")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    def _prompt(msg):
        try:
            return input(msg)
        except EOFError:          # no terminal (stdin closed) — type it in Chrome instead
            return ""

    obs, ok = open_observer(a.email, otp_prompt=_prompt)
    print("Signed in:", ok)
    try:
        time.sleep(a.hold)
    finally:
        obs.quit()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
