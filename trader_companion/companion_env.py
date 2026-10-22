"""Load companion .env from standard locations (exe folder, cwd, LocalAppData)."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_LOADED_FROM: Optional[Path] = None


def companion_dotenv_paths() -> list[Path]:
    """Search order: existing env wins; first file found is loaded (override=False)."""
    paths: list[Path] = []
    if getattr(sys, "frozen", False):
        paths.append(Path(sys.executable).resolve().parent / ".env")
    paths.append(Path.cwd() / ".env")
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        paths.append(Path(local) / "TradeOpsAI" / ".env")
    paths.append(Path(__file__).resolve().parents[1] / ".env")
    # de-dupe while preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def load_companion_dotenv() -> Optional[Path]:
    """Load the first .env found; safe to call repeatedly."""
    global _LOADED_FROM
    if _LOADED_FROM is not None:
        return _LOADED_FROM
    try:
        from dotenv import load_dotenv
    except ImportError:
        return None
    for path in companion_dotenv_paths():
        if path.is_file():
            load_dotenv(path, override=False)
            _LOADED_FROM = path
            logger.debug("Loaded companion env from %s", path)
            return path
    return None


def log_mailbox_boot_status(boot_logger: logging.Logger) -> None:
    """One line at startup so remote logs show whether auto OTP/link fetch will work."""
    load_companion_dotenv()
    try:
        from trader_companion.email_codes import Mailbox
    except ImportError:
        boot_logger.warning(
            "Login mailbox (IMAP): email_codes unavailable — Vest/Breakout sign-in may need manual codes")
        return
    mb = Mailbox.from_env()
    if mb:
        boot_logger.info(
            "Login mailbox (IMAP): %s @ %s:%s — Vest/Breakout/MFP codes fetched per "
            "dashboard login email (forward each client Gmail to this inbox)",
            mb.user, mb.host, mb.port)
        try:
            mb.check()
            boot_logger.info("Login mailbox (IMAP): connection check OK")
        except Exception as exc:
            boot_logger.warning(
                "Login mailbox (IMAP): configured but login failed (%s) — fix credentials on this host",
                exc)
    else:
        boot_logger.warning(
            "Login mailbox (IMAP): NOT configured on this PC — add MAIL_IMAP_USER and "
            "MAIL_IMAP_PASSWORD to .env next to TradeopssAI.exe or %%LOCALAPPDATA%%\\TradeOpsAI\\.env "
            "(all clients: forward firm login Gmail → that inbox; dashboard vest_email / breakout_email "
            "must match each login address)")
