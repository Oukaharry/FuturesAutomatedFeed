"""Pull one-time codes and sign-in links straight from the login mailbox over IMAP.

Works with any IMAP provider. Titan Email (imap.titan.email:993, normal mailbox
password) is the default; Gmail needs an App Password. Configure in .env:

    MAIL_IMAP_HOST=imap.titan.email      # default when MAIL_IMAP_USER is set
    MAIL_IMAP_PORT=993
    MAIL_IMAP_USER=ops@yourdomain.com
    MAIL_IMAP_PASSWORD=...
    # legacy fallback: GMAIL_IMAP_USER / GMAIL_IMAP_APP_PASSWORD (imap.gmail.com)

The firm may send the code to a different address (e.g. a Gmail login that
auto-forwards to the Titan inbox) — forwarding keeps the sender/subject/body,
so matching is unaffected.

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

TITAN_IMAP_HOST = "imap.titan.email"
GMAIL_IMAP_HOST = "imap.gmail.com"
CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
LINK_RE = re.compile(r"https?://[^\s\"'<>\]\)]+")


class Mailbox:
    def __init__(self, user: str, password: str, host: str = TITAN_IMAP_HOST, port: int = 993,
                 folder: str = "INBOX"):
        self.user = user
        # Google shows app passwords in 4-char groups; real passwords keep their spaces.
        self.password = password.replace(" ", "") if host == GMAIL_IMAP_HOST else password
        self.host = host
        self.port = int(port)
        self.folder = folder

    @classmethod
    def from_env(cls) -> Optional["Mailbox"]:
        user = (os.environ.get("MAIL_IMAP_USER") or "").strip()
        pw = (os.environ.get("MAIL_IMAP_PASSWORD") or "").strip()
        host = (os.environ.get("MAIL_IMAP_HOST") or "").strip()
        if user and pw:
            return cls(user, pw, host=host or TITAN_IMAP_HOST,
                       port=int(os.environ.get("MAIL_IMAP_PORT") or 993),
                       folder=os.environ.get("MAIL_IMAP_FOLDER") or "INBOX")
        guser = (os.environ.get("GMAIL_IMAP_USER") or "").strip()
        gpw = (os.environ.get("GMAIL_IMAP_APP_PASSWORD") or "").strip()
        if guser and gpw:
            return cls(guser, gpw, host=os.environ.get("GMAIL_IMAP_HOST") or GMAIL_IMAP_HOST)
        return None

    @staticmethod
    def configured() -> bool:
        return Mailbox.from_env() is not None

    # ── IMAP ─────────────────────────────────────────────────────────

    def _connect(self) -> imaplib.IMAP4_SSL:
        m = imaplib.IMAP4_SSL(self.host, self.port)
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

    @staticmethod
    def _html(msg: email.message.Message) -> str:
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    return (part.get_payload(decode=True) or b"").decode(
                        part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    return ""
        return ""

    @staticmethod
    def numbered_links(html_body: str, link_match: str) -> dict:
        """{label: url} for anchors whose visible text is a number (Descope 'click the
        number that matches your screen' emails)."""
        out = {}
        for a in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html_body, flags=re.S | re.I):
            href = html.unescape(a.group(1))
            if link_match.lower() not in href.lower():
                continue
            label = re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]+>", " ", a.group(2))))
            if label.isdigit():
                out.setdefault(label, href)
        return out

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
                rcpts = " ".join(str(v) for h in ("To", "Delivered-To", "X-Forwarded-For", "X-Original-To",
                                                  "Envelope-To", "Cc")
                                 for v in (msg.get_all(h) or []))
                out.append({"ts": ts, "from": msg.get("From") or "", "subject": subj,
                            "recipients": rcpts.lower(), "text": self._text(msg), "html": self._html(msg)})
            return out
        finally:
            try:
                m.logout()
            except Exception:
                pass

    # ── extraction ───────────────────────────────────────────────────

    @staticmethod
    def _matches(rec: dict, match: Iterable[str], recipient: Optional[str] = None) -> bool:
        hay = (rec["from"] + " " + rec["subject"] + " " + rec["text"][:4000]).lower()
        if not any(k.lower() in hay for k in match):
            return False
        if recipient:
            # Forwarded mail keeps the original To/Delivered-To/X-Forwarded-For,
            # so each client's code is routed by their own login address.
            return recipient.lower() in (rec.get("recipients") or "")
        return True

    def find_code(self, since: float, match: Iterable[str], recipient: Optional[str] = None) -> Optional[str]:
        for rec in self.recent(since):
            if not self._matches(rec, match, recipient):
                continue
            # Prefer a code in the subject, then the first in the body.
            for src in (rec["subject"], rec["text"]):
                m = CODE_RE.search(src)
                if m:
                    return m.group(1)
        return None

    def find_link(self, since: float, match: Iterable[str], link_match: str,
                  recipient: Optional[str] = None) -> Optional[str]:
        for rec in self.recent(since):
            if not self._matches(rec, match, recipient):
                continue
            for url in LINK_RE.findall(rec["text"]):
                if link_match.lower() in url.lower() and not url.lower().endswith((".png", ".jpg", ".gif", ".css")):
                    return url.rstrip(".,;")
        return None

    def find_numbered_links(self, since: float, match: Iterable[str], link_match: str,
                            recipient: Optional[str] = None) -> dict:
        """{label: url} from the newest matching mail (empty when none)."""
        for rec in self.recent(since):
            if not self._matches(rec, match, recipient):
                continue
            links = self.numbered_links(rec.get("html") or "", link_match)
            if links:
                return links
        return {}

    def wait_for_numbered_links(self, since: float, match: Iterable[str], link_match: str,
                                timeout: int = 180, poll: float = 4.0,
                                recipient: Optional[str] = None) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                links = self.find_numbered_links(since, match, link_match, recipient)
                if links:
                    return links
            except Exception as exc:
                logger.warning("mailbox poll failed: %s", exc)
            time.sleep(poll)
        return {}

    def wait_for_code(self, since: float, match: Iterable[str], timeout: int = 180, poll: float = 4.0,
                      recipient: Optional[str] = None) -> Optional[str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                code = self.find_code(since, match, recipient)
                if code:
                    return code
            except Exception as exc:
                logger.warning("mailbox poll failed: %s", exc)
            time.sleep(poll)
        return None

    def wait_for_link(self, since: float, match: Iterable[str], link_match: str,
                      timeout: int = 180, poll: float = 4.0, recipient: Optional[str] = None) -> Optional[str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                link = self.find_link(since, match, link_match, recipient)
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
    p.add_argument("--recipient", default=None, help="original login email (forwarded To:)")
    p.add_argument("--minutes", type=int, default=30)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    mb = Mailbox.from_env()
    if mb is None:
        raise SystemExit("set MAIL_IMAP_USER / MAIL_IMAP_PASSWORD (Titan) or GMAIL_IMAP_USER / GMAIL_IMAP_APP_PASSWORD in .env")
    since = time.time() - a.minutes * 60
    match = [s for s in a.match.split(",") if s]
    if a.cmd == "check":
        print(f"IMAP login OK ({mb.user} @ {mb.host}:{mb.port}, folder {mb.folder})" if mb.check() else "failed")
    elif a.cmd == "recent":
        for r in mb.recent(since):
            print(time.strftime("%H:%M:%S", time.localtime(r["ts"])), "|", r["from"][:40], "|", r["subject"][:60],
                  "| to:", r["recipients"][:60])
    elif a.cmd == "code":
        print(mb.find_code(since, match, a.recipient))
    elif a.cmd == "link":
        print(mb.find_link(since, match, a.link_match, a.recipient))


if __name__ == "__main__":
    _main()
