"""Fetch Vest/Breakout OTP from the dashboard (server-side IMAP on tradeopss.com)."""

from __future__ import annotations

import logging
import time
from typing import Iterable, Optional

import requests

log = logging.getLogger("TradeOpssAI.mailbox")

_ctx: dict[str, str] = {"dashboard_url": "", "client_email": ""}


def set_companion_mailbox_context(dashboard_url: str, client_email: str) -> None:
    _ctx["dashboard_url"] = (dashboard_url or "").strip().rstrip("/")
    _ctx["client_email"] = (client_email or "").strip().lower()


def _companion_headers() -> dict[str, str]:
    try:
        from trader_companion.trader_app import APP_VERSION
    except ImportError:
        APP_VERSION = "1.12.9"
    return {"Content-Type": "application/json", "X-Companion-Version": APP_VERSION}


def _poll(dashboard_url: str, client_email: str, payload: dict) -> Optional[dict]:
    try:
        resp = requests.post(
            f"{dashboard_url}/api/companion/mailbox/poll",
            json={"email": client_email, **payload},
            headers=_companion_headers(),
            timeout=45,
        )
    except requests.RequestException as exc:
        log.warning("Dashboard mailbox request failed: %s", exc)
        return None
    if resp.status_code == 503:
        log.warning("Dashboard MAIL_IMAP not configured — set MAIL_IMAP_* on tradeopss.com")
        return {"error": "server_mailbox"}
    if resp.status_code >= 400:
        try:
            msg = (resp.json() or {}).get("message") or resp.text[:200]
        except Exception:
            msg = resp.text[:200]
        log.warning("Dashboard mailbox poll HTTP %s: %s", resp.status_code, msg)
        return None
    try:
        return resp.json() or {}
    except ValueError:
        return None


def wait_for_code_remote(
    since: float,
    recipient: str,
    match: Iterable[str],
    timeout: int = 180,
    poll: float = 4.0,
) -> Optional[str]:
    dashboard_url = _ctx.get("dashboard_url") or ""
    client_email = _ctx.get("client_email") or ""
    if not dashboard_url or not client_email:
        log.warning("Dashboard mailbox: companion not logged in (no dashboard URL / client email)")
        return None
    match_s = ",".join(match) if not isinstance(match, str) else match
    log.info("Fetching Vest/OTP code for %s via dashboard mailbox…", recipient or "login")
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = _poll(dashboard_url, client_email, {
            "recipient": recipient,
            "since": since,
            "kind": "code",
            "match": match_s,
        })
        if body and body.get("code"):
            return str(body["code"])
        if body and body.get("error") == "server_mailbox":
            return None
        time.sleep(poll)
    log.warning("Dashboard mailbox: no code in time for %s", recipient or "login")
    return None


def wait_for_numbered_links_remote(
    since: float,
    recipient: str,
    match: Iterable[str],
    link_match: str,
    timeout: int = 180,
    poll: float = 4.0,
) -> dict:
    dashboard_url = _ctx.get("dashboard_url") or ""
    client_email = _ctx.get("client_email") or ""
    if not dashboard_url or not client_email:
        log.warning("Dashboard mailbox: companion not logged in (no dashboard URL / client email)")
        return {}
    match_s = ",".join(match) if not isinstance(match, str) else match
    log.info("Fetching Breakout links for %s via dashboard mailbox…", recipient or "login")
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = _poll(dashboard_url, client_email, {
            "recipient": recipient,
            "since": since,
            "kind": "numbered_links",
            "match": match_s,
            "link_match": link_match,
        })
        links = (body or {}).get("links")
        if isinstance(links, dict) and links:
            return links
        if body and body.get("error") == "server_mailbox":
            return {}
        time.sleep(poll)
    log.warning("Dashboard mailbox: no Breakout links in time for %s", recipient or "login")
    return {}
