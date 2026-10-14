"""Mailbox code/link extraction (no IMAP; `recent` is stubbed)."""

import time

from trader_companion.email_codes import Mailbox


def _mb(records):
    mb = Mailbox("u@example.com", "secret")
    mb.recent = lambda since, lookback_sec=900: [r for r in records if r["ts"] >= since - 90]
    return mb


def test_gmail_app_password_spaces_stripped_titan_password_kept():
    assert Mailbox("u", "abcd efgh ijkl mnop", host="imap.gmail.com").password == "abcdefghijklmnop"
    assert Mailbox("u", "p@ss word").password == "p@ss word" and Mailbox("u", "x").host == "imap.titan.email"


def test_from_env_prefers_titan_vars_then_gmail(monkeypatch):
    for k in ("MAIL_IMAP_USER", "MAIL_IMAP_PASSWORD", "MAIL_IMAP_HOST", "GMAIL_IMAP_USER", "GMAIL_IMAP_APP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    assert Mailbox.from_env() is None
    monkeypatch.setenv("GMAIL_IMAP_USER", "g@gmail.com"); monkeypatch.setenv("GMAIL_IMAP_APP_PASSWORD", "a b c d")
    mb = Mailbox.from_env(); assert mb.host == "imap.gmail.com" and mb.password == "abcd"
    monkeypatch.setenv("MAIL_IMAP_USER", "ops@titan.test"); monkeypatch.setenv("MAIL_IMAP_PASSWORD", "t p")
    mb = Mailbox.from_env(); assert mb.host == "imap.titan.email" and mb.port == 993 and mb.password == "t p"


def test_find_code_prefers_matching_sender_and_subject():
    now = time.time()
    recs = [
        {"ts": now + 5, "from": "noreply@privy.io", "subject": "Your Vest login code is 482913",
         "text": "Use 482913 to sign in. Order #123456789 is unrelated."},
        {"ts": now + 1, "from": "news@other.com", "subject": "Promo 999999", "text": "x"},
    ]
    assert _mb(recs).find_code(now, match=("vest", "privy")) == "482913"


def test_find_code_ignores_mail_older_than_attempt():
    now = time.time()
    recs = [{"ts": now - 600, "from": "noreply@privy.io", "subject": "Vest code 111111", "text": ""}]
    assert _mb(recs).find_code(now, match=("vest",)) is None


def test_find_link_extracts_breakout_link_from_html():
    now = time.time()
    recs = [{"ts": now + 3, "from": "no-reply@breakoutprop.com", "subject": "Sign in to Breakout",
             "text": 'Click <a href="https://auth.portal.breakoutprop.com/v1/verify?t=abc.def">here</a> '
                     "https://auth.portal.breakoutprop.com/v1/verify?t=abc.def https://img.breakoutprop.com/logo.png"}]
    assert _mb(recs).find_link(now, match=("breakout",), link_match="breakoutprop.com") \
        == "https://auth.portal.breakoutprop.com/v1/verify?t=abc.def"


def test_wait_for_code_times_out_quickly_when_nothing_arrives():
    mb = _mb([])
    t0 = time.time()
    assert mb.wait_for_code(time.time(), match=("vest",), timeout=1, poll=0.2) is None
    assert time.time() - t0 < 3
