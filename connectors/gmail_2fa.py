"""
gmail_2fa.py — Gmail API poller for BlackArrow 2FA codes.

SETUP (one-time):
  1. Go to https://console.cloud.google.com/
  2. Create a project → Enable "Gmail API"
  3. Create OAuth2 credentials (Desktop app) → Download as credentials.json
  4. Place credentials.json next to this file (or pass path to GmailTwoFactor)
  5. First run will open a browser for consent → saves token.json for reuse

USAGE:
    from connectors.gmail_2fa import GmailTwoFactor
    g = GmailTwoFactor()
    code = g.wait_for_code(timeout=120)   # blocks until code arrives or timeout
"""

import os
import re
import time
import base64
import logging
import json
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Lazy imports — only loaded when GmailTwoFactor is instantiated
_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _get_creds(credentials_path: str, token_path: str):
    """Return valid OAuth2 credentials, running browser auth flow if needed."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, _SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds


class GmailTwoFactor:
    """
    Polls the Gmail inbox for a BlackArrow 2FA email and extracts the 6-digit code.

    Parameters
    ----------
    credentials_path : str
        Path to the OAuth2 credentials.json file downloaded from Google Cloud Console.
    token_path : str
        Where to cache the access/refresh token after the first auth.
    sender_filter : str
        Substring of the sender address to match (default: 'blackarrow' or 'nelogica').
    poll_interval : float
        Seconds between Gmail checks (default: 3).
    """

    # BlackArrow / Nelogica send 2FA from this domain
    SENDER_KEYWORDS = ["blackarrow", "nelogica", "noreply", "no-reply"]
    CODE_RE = re.compile(r"\b(\d{6})\b")

    def __init__(
        self,
        credentials_path: str = None,
        token_path: str = None,
        sender_filter: str = None,
        poll_interval: float = 3.0,
    ):
        base_dir = Path(__file__).parent
        self.credentials_path = credentials_path or str(base_dir / "credentials.json")
        self.token_path = token_path or str(base_dir / "token.json")
        self.sender_filter = sender_filter
        self.poll_interval = poll_interval
        self._service = None

    def _build_service(self):
        """Lazily build (and cache) the Gmail API service."""
        if self._service is not None:
            return self._service
        try:
            from googleapiclient.discovery import build
        except ImportError:
            raise ImportError(
                "google-api-python-client is not installed. "
                "Run: pip install google-api-python-client google-auth-httplib2 "
                "google-auth-oauthlib"
            )
        creds = _get_creds(self.credentials_path, self.token_path)
        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def wait_for_code(self, timeout: float = 120, after_ts: float = None) -> str | None:
        """
        Block until a 2FA code is found in Gmail or timeout is reached.

        Parameters
        ----------
        timeout : float
            Maximum seconds to wait.
        after_ts : float
            Unix timestamp — only consider emails received after this time.
            Defaults to now minus 60 seconds (catches very-recently-sent emails).

        Returns
        -------
        str | None
            The 6-digit code, or None if timeout elapsed.
        """
        if after_ts is None:
            after_ts = time.time() - 60  # catch emails from the last minute

        svc = self._build_service()
        deadline = time.time() + timeout
        logger.info("Gmail 2FA: waiting for code (timeout=%ss)…", timeout)

        while time.time() < deadline:
            code = self._scan_inbox(svc, after_ts)
            if code:
                logger.info("Gmail 2FA: found code %s", code)
                return code
            time.sleep(self.poll_interval)

        logger.warning("Gmail 2FA: timed out after %ss without finding a code", timeout)
        return None

    def get_latest_code(self, lookback_seconds: float = 300) -> str | None:
        """
        Non-blocking: return the most-recent 2FA code from the last N seconds, or None.
        """
        svc = self._build_service()
        return self._scan_inbox(svc, time.time() - lookback_seconds)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _scan_inbox(self, svc, after_ts: float) -> str | None:
        """Search Gmail for 2FA emails received after after_ts, return code or None."""
        # Gmail search query: recent messages from known senders
        # after: uses Unix epoch seconds
        query_parts = [f"after:{int(after_ts)}"]
        if self.sender_filter:
            query_parts.append(f"from:{self.sender_filter}")

        query = " ".join(query_parts)

        try:
            result = (
                svc.users()
                .messages()
                .list(userId="me", q=query, maxResults=10)
                .execute()
            )
        except Exception as e:
            logger.warning("Gmail list error: %s", e)
            return None

        messages = result.get("messages", [])
        if not messages:
            return None

        # Newest first (Gmail returns newest by default)
        for msg_ref in messages:
            code = self._extract_code_from_message(svc, msg_ref["id"])
            if code:
                return code

        return None

    def _extract_code_from_message(self, svc, msg_id: str) -> str | None:
        """Fetch a message and extract a 6-digit code from its body/subject."""
        try:
            msg = (
                svc.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
        except Exception as e:
            logger.warning("Gmail get message error: %s", e)
            return None

        # Check sender
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        sender = headers.get("from", "").lower()

        if self.sender_filter:
            if self.sender_filter.lower() not in sender:
                return None
        else:
            # Default: must be from a recognised sender
            if not any(kw in sender for kw in self.SENDER_KEYWORDS):
                return None

        # Try subject first (fastest)
        subject = headers.get("subject", "")
        code = self._find_code_in_text(subject)
        if code:
            return code

        # Walk the payload parts for the plain-text body
        body_text = self._get_body_text(msg.get("payload", {}))
        if body_text:
            code = self._find_code_in_text(body_text)
            if code:
                return code

        return None

    def _get_body_text(self, payload: dict) -> str:
        """Recursively extract plain-text body from a Gmail message payload."""
        mime = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")

        if mime == "text/plain" and body_data:
            try:
                return base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="ignore")
            except Exception:
                pass

        if mime == "text/html" and body_data:
            try:
                html = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="ignore")
                # Strip tags for a quick regex
                return re.sub(r"<[^>]+>", " ", html)
            except Exception:
                pass

        for part in payload.get("parts", []):
            text = self._get_body_text(part)
            if text:
                return text

        return ""

    def _find_code_in_text(self, text: str) -> str | None:
        """Return the first 6-digit number in text, or None."""
        matches = self.CODE_RE.findall(text)
        # Prefer matches that are not years (avoid "2026" etc.)
        for m in matches:
            if not re.match(r"^20[0-9]{2}$", m):  # skip year-like numbers
                return m
        return matches[0] if matches else None


# ------------------------------------------------------------------ #
# Quick CLI test
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    g = GmailTwoFactor()
    print("Scanning last 5 minutes for a 2FA code…")
    code = g.get_latest_code(lookback_seconds=300)
    if code:
        print(f"Found code: {code}")
    else:
        print("No code found. Waiting up to 120s…")
        code = g.wait_for_code(timeout=120)
        print(f"Result: {code}")
