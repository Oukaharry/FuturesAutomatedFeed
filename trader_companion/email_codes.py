"""Pull one-time codes and sign-in links straight from the login mailbox (Gmail IMAP).

Needs a Google App Password (2-Step Verification → App passwords) in .env:

    GMAIL_IMAP_USER=you@gmail.com
    GMAIL_IMAP_APP_PASSWORD=xxxx xxxx xxxx xxxx

    from trader_companion.email_codes import Mailbox
    mb = Mailbox.from_env()
    code = mb.wait_for_code(since=time.time(), match=("vest", "privy"))          # "123456"
    link = mb.wait_for_link(since=time.time(), match=("breakout",), link_match="breakoutprop.com")

Only messages that arrived after `since` are considered, newest first, so a
stale code from an earlier attempt is never reused.
"""

from __future__ import annotations

import email
import email.utils
import html
import imaplib
import logging
import os
import re
import time
from email.header import decode_header, make_header
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

IMAP_HOST = os.environ.get("GMAIL_IMAP_HOST", "imap.gmail.com")
CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
LINK_RE = re.compile(r"https?://[^\s\"'<>\]\)]+")


class Mailbox:
    def __init__(self, user: str, app_password: str, host: str = IMAP_HOST, folder: str = "INBOX"):
        self.user = user
        self.password = app_password.replace(" ", "")
        self.host = host
        self.folder = folder

    @classmethod
    def from_env(cls) -> Optional["Mailbox"]:
        user = (os.environ.get("GMAIL_IMAP_USER") or "").strip()
        pw = (os.environ.get("GMAIL_IMAP_APP_PASSWORD") or "").strip()
        if not user or not pw:
            return None
        return cls(user, pw)

    @staticmethod
    def configured() -> bool:
        return Mailbox.from_env() is not None

    # ── IMAP ─────────────────────────────────────────────────────────

    def _connect(self) -> imaplib.IMAP4_SSL:
        m = imaplib.IMAP4_SSL(self.host)
        m.login(self.user, self.password)
        m.select(self.folder)
        return m

    def check(self) -> bool:
        """Login + select; raises on bad credentials."""
        m = self._connect()
        try:
            m.noop()
        finally:
            try:
                m.logout()
            except Exception:
                pass
        return True

    @staticmethod
    def _text(msg: email.message.Message) -> str:
        parts = []
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html"):
                continue
            try:
                payload = part.get_payload(decode=True) or b""
                txt = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            except Exception:
                continue
            if ctype == "text/html":
                hrefs = re.findall(r'href=["\']([^"\']+)["\']', txt, flags=re.I)
                txt = re.sub(r"<[^>]+>", " ", txt)
                txt += "\n" + "\n".join(hrefs)
            parts.append(html.unescape(txt))
        return "\n".join(parts)

    def recent(self, since: float, lookback_sec: int = 900) -> list:
        """[{ts, from, subject, text}] newer than `since`, newest first."""
        m = self._connect()
        try:
            day = time.strftime("%d-%b-%Y", time.gmtime(min(since, time.time()) - lookback_sec))
            typ, data = m.search(None, f'(SINCE "{day}")')
            ids = (data[0] or b"").split()
            out = []
            for mid in reversed(ids[-40:]):
                typ, raw = m.fetch(mid, "(RFC822)")
                if typ != "OK" or not raw or not raw[0]:
                    continue
                msg = email.message_from_bytes(raw[0][1])
                try:
                    ts = email.utils.mktime_tz(email.utils.parsedate_tz(msg.get("Date") or ""))
                except Exception:
                    ts = time.time()
                if ts < since - 90:          # clock skew tolerance
                    continue
                subj = str(make_header(decode_header(msg.get("Subject") or "")))
                out.append({"ts": ts, "from": msg.get("From") or "", "subject": subj, "text": self._text(msg)})
            return out
        finally:
            try:
                m.logout()
            except Exception:
                pass

    # ── extraction ───────────────────────────────────────────────────

    @staticmethod
    def _matches(rec: dict, match: Iterable[str]) -> bool:
        hay = (rec["from"] + " " + rec["subject"] + " " + rec["text"][:4000]).lower()
        return any(k.lower() in hay for k in match)

    def find_code(self, since: float, match: Iterable[str]) -> Optional[str]:
        for rec in self.recent(since):
            if not self._matches(rec, match):
                continue
            # Prefer a code in the subject, then the first in the body.
            for src in (rec["subject"], rec["text"]):
                m = CODE_RE.search(src)
                if m:
                    return m.group(1)
        return None

    def find_link(self, since: float, match: Iterable[str], link_match: str) -> Optional[str]:
        for rec in self.recent(since):
            if not self._matches(rec, match):
                continue
            for url in LINK_RE.findall(rec["text"]):
                if link_match.lower() in url.lower() and not url.lower().endswith((".png", ".jpg", ".gif", ".css")):
                    return url.rstrip(".,;")
        return None

    def wait_for_code(self, since: float, match: Iterable[str], timeout: int = 180, poll: float = 4.0) -> Optional[str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                code = self.find_code(since, match)
                if code:
                    return code
            except Exception as exc:
                logger.warning("mailbox poll failed: %s", exc)
            time.sleep(poll)
        return None

    def wait_for_link(self, since: float, match: Iterable[str], link_match: str,
                      timeout: int = 180, poll: float = 4.0) -> Optional[str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                link = self.find_link(since, match, link_match)
                if link:
                    return link
            except Exception as exc:
                logger.warning("mailbox poll failed: %s", exc)
            time.sleep(poll)
        return None


def _main():
    import argparse
    import json
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("cmd", choices=["check", "recent", "code", "link"])
    p.add_argument("--match", default="vest,privy")
    p.add_argument("--link-match", default="breakoutprop.com")
    p.add_argument("--minutes", type=int, default=30)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    mb = Mailbox.from_env()
    if mb is None:
        raise SystemExit("set GMAIL_IMAP_USER and GMAIL_IMAP_APP_PASSWORD in .env")
    since = time.time() - a.minutes * 60
    match = [s for s in a.match.split(",") if s]
    if a.cmd == "check":
        print("IMAP login OK" if mb.check() else "failed")
    elif a.cmd == "recent":
        for r in mb.recent(since):
            print(time.strftime("%H:%M:%S", time.localtime(r["ts"])), "|", r["from"][:40], "|", r["subject"][:70])
    elif a.cmd == "code":
        print(mb.find_code(since, match))
    elif a.cmd == "link":
        print(mb.find_link(since, match, a.link_match))


if __name__ == "__main__":
    _main()
