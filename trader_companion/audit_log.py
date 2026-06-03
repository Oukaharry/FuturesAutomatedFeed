"""
Companion file logging — all modules write to mt5_trading.log for remote monitoring.

Log file location (client PC):
  - Next to TradeOpssAI.exe when packaged, OR
  - trader_companion/mt5_trading.log when run from source, OR
  - override with env COMPANION_LOG_PATH
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Dict, Optional


_HANDLER_TAG = "_mt5_trading_log_handler"
_LOGGERS_CONFIGURED = False


def companion_log_dir() -> str:
    """Directory where mt5_trading.log is written on this machine."""
    override = (os.environ.get("COMPANION_LOG_PATH") or "").strip()
    if override:
        return os.path.dirname(os.path.abspath(override)) or "."
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def default_log_path() -> str:
    override = (os.environ.get("COMPANION_LOG_PATH") or "").strip()
    if override:
        return os.path.abspath(override)
    return os.path.join(companion_log_dir(), "mt5_trading.log")


def ensure_mt5_trading_log_handler(log_path: Optional[str] = None) -> str:
    """
    Attach a FileHandler to the root logger so all companion loggers share one file.
    Returns the absolute log file path.
    """
    path = os.path.abspath(log_path or default_log_path())
    root = logging.getLogger()
    if getattr(root, _HANDLER_TAG, False):
        return path

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    root.addHandler(handler)

    if root.level == logging.NOTSET:
        root.setLevel(logging.DEBUG)

    setattr(root, _HANDLER_TAG, True)

    boot = logging.getLogger("TradeOpssAI.boot")
    boot.info("=" * 60)
    boot.info("TradeOpssAI companion logging started")
    boot.info("Log file: %s", path)
    boot.info("Working directory: %s", os.getcwd())
    boot.info("=" * 60)

    _configure_module_loggers()
    return path


def _configure_module_loggers() -> None:
    """Ensure M1 feed/sync and GUI loggers propagate at INFO+."""
    global _LOGGERS_CONFIGURED
    if _LOGGERS_CONFIGURED:
        return
    for name in (
        "TradeOpssAI",
        "TradeOpssAI.m1",
        "trader_companion.mt5_market_feed",
        "trader_companion.m1_bars_sync",
        "AUDIT",
    ):
        lg = logging.getLogger(name)
        lg.setLevel(logging.DEBUG)
        lg.propagate = True
    _LOGGERS_CONFIGURED = True


def get_companion_logger(name: str = "TradeOpssAI") -> logging.Logger:
    """Return a logger that writes to mt5_trading.log."""
    ensure_mt5_trading_log_handler()
    return logging.getLogger(name)


def log_gui(message: str, level: str = "INFO") -> None:
    """Mirror in-app activity log lines to mt5_trading.log."""
    ensure_mt5_trading_log_handler()
    lg = logging.getLogger("TradeOpssAI")
    lvl = (level or "INFO").upper()
    if lvl == "ERROR":
        lg.error(message)
    elif lvl == "WARN" or lvl == "WARNING":
        lg.warning(message)
    elif lvl == "DEBUG":
        lg.debug(message)
    else:
        lg.info(message)


def audit(event: str, **fields: Any) -> None:
    """Single-line structured JSON audit log (easy to grep on client PCs)."""
    ensure_mt5_trading_log_handler()
    logger = logging.getLogger("AUDIT")
    try:
        payload: Dict[str, Any] = {
            "ts": int(time.time() * 1000),
            "event": event,
            **fields,
        }
        logger.info("[AUDIT] %s", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        logger.info("[AUDIT] %s %s", event, fields)


def audit_m1(event: str, **fields: Any) -> None:
    """Structured M1 feed / dashboard sync events."""
    audit(event, component="m1", **fields)
