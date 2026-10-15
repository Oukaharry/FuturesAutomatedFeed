"""MyFundedPerps observer window: visible Chrome on the trading workspace.

The companion trades MyFundedPerps through the REST API (no browser needed),
so until now nothing was visible. Like the Vest observer, this opens a real
Chrome with its own persistent profile, signs in with the login email and the
six-digit code read from the mailbox (`email_codes.Mailbox`, same forwarding
setup as Vest / Breakout), and leaves the terminal open so trades can be
watched. Later launches reuse the profile's session. The API connection is
unaffected — this window is for eyes only.

    python -m trader_companion.perps_login --email you@example.com
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import time

from selenium.webdriver.common.keys import Keys

from trader_companion.vest_probe import (_click_text, _driver, _find_email_input,
                                         _otp_inputs)

log = logging.getLogger("perps-login")

HOME_URL = os.environ.get("MFP_HOME_URL", "https://myfundedperpetuals.com/")
TRADE_URL = os.environ.get("MFP_TRADE_URL", "https://myfundedperpetuals.com/trade")
MAIL_MATCH = ("myfundedperp", "fundedperp", "perpetuals")


def observer_profile(email: str) -> str:
    return "mfp_view_" + re.sub(r"[^a-z0-9]+", "_", (email or "").strip().lower().split("@")[0])[:32]


def _logged_in(d) -> bool:
    try:
        return bool(d.execute_script("""
          const t = (document.body && document.body.innerText) || '';
          const head = t.slice(0, 6000);
          const signedOut = /\\bSign In\\b|\\bSign Up\\b|\\bLog In\\b/i.test(head);
          const workspace = /Account Value|Equity|Balance|Positions|Open Orders|Dashboard|Sign Out|Log Out/i.test(t);
          return workspace && !signedOut;
        """))
    except Exception:
        return False


def _mailbox_code(since: float, recipient: str = None, timeout: int = 180):
    try:
        from trader_companion.email_codes import Mailbox
    except ImportError:
        return None
    mb = Mailbox.from_env()
    if mb is None:
        return None
    log.info("Fetching the MyFundedPerps code for %s from the mailbox…", recipient or "this login")
    code = mb.wait_for_code(since, match=MAIL_MATCH, timeout=timeout, recipient=recipient)
    log.info("Mailbox code: %s", "received" if code else "not received in time")
    return code


def email_login(d, email: str, otp_prompt=None) -> bool:
    """Walk the email + six-digit-code sign-in on an open driver; returns logged-in state."""
    otp_prompt = otp_prompt or (lambda *_: "")
    d.get(TRADE_URL)
    time.sleep(5)
    if _logged_in(d):
        log.info("MyFundedPerps: already signed in (persistent profile)")
        return True
    # Header "Sign In" is present on every screen size per the firm's docs.
    _click_text(d, ["Sign In", "Sign in", "Log In", "Login"])
    time.sleep(2.5)
    _click_text(d, ["Continue with email", "Email", "Use email"])
    time.sleep(1.5)
    inp = _find_email_input(d)
    manual = inp is None
    if manual:
        log.warning("MyFundedPerps: email field not found — complete sign-in by hand in Chrome "
                    "(waiting up to 4 minutes; Cloudflare may be asking for a browser check)")
    else:
        inp.click()
        inp.send_keys(Keys.COMMAND, "a")
        inp.send_keys(Keys.BACKSPACE)
        inp.send_keys(email)
        time.sleep(0.5)
        sent_at = time.time()
        if not _click_text(d, ["Continue", "Send code", "Send Code", "Next", "Submit"]):
            inp.send_keys(Keys.ENTER)
        log.info("MyFundedPerps: email submitted for %s — waiting for the six-digit code", email)
        time.sleep(3)
        code = (_mailbox_code(sent_at, recipient=email) or "").strip()
        if not code:
            code = str(otp_prompt("Enter the 6-digit MyFundedPerps code "
                                  "(or press Enter if you typed it in Chrome): ") or "").strip()
        if code:
            boxes = _otp_inputs(d)
            if len(boxes) >= 6:
                for box, ch in zip(boxes, code):
                    box.send_keys(ch)
            elif boxes:
                boxes[0].send_keys(code)
                boxes[0].send_keys(Keys.ENTER)
            else:
                log.warning("MyFundedPerps: no code inputs found — type the code in Chrome")
            _click_text(d, ["Verify", "Continue", "Confirm"])
    for _ in range(240 if manual else 90):
        if _logged_in(d):
            break
        time.sleep(1)
    ok = _logged_in(d)
    if ok:
        try:
            if "/trade" not in (d.current_url or ""):
                d.get(TRADE_URL)
        except Exception:
            pass
    log.info("MyFundedPerps signed in: %s", ok)
    return ok


def open_observer(email: str, otp_prompt=None):
    """Visible Chrome on the MyFundedPerps workspace. Returns (driver, logged_in);
    the caller owns the driver and must quit it."""
    d = _driver(observer_profile(email))
    try:
        ok = email_login(d, email, otp_prompt=otp_prompt)
    except Exception as exc:
        log.warning("MyFundedPerps observer login failed: %s", exc)
        ok = False
    return d, ok


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--email", required=True)
    p.add_argument("--hold", type=int, default=600, help="seconds to keep the window open")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    d, ok = open_observer(a.email, otp_prompt=input)
    print("Signed in:", ok)
    try:
        time.sleep(a.hold)
    finally:
        d.quit()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
