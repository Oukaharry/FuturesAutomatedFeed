import logging
import os
import json
import time
from typing import Any, Dict, Optional


_HANDLER_TAG = "_mt5_trading_log_handler"


def ensure_mt5_trading_log_handler(log_path: Optional[str] = None) -> None:
    """Ensure every logger writes to mt5_trading.log.

    We attach a FileHandler to the *root* logger so that existing loggers across
    the companion (Tradovate/TopStepX/MT5/GUI) all propagate into the same file.
    """
    root = logging.getLogger()
    if getattr(root, _HANDLER_TAG, False):
        return

    # Default to CWD log file to match current mt5_trading.py behavior.
    log_path = log_path or os.path.join(os.getcwd(), "mt5_trading.log")
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root.addHandler(handler)

    # Keep root permissive; individual loggers can filter.
    if root.level == logging.NOTSET:
        root.setLevel(logging.INFO)

    setattr(root, _HANDLER_TAG, True)


def audit(event: str, **fields: Any) -> None:
    """Single-line structured audit log to mt5_trading.log."""
    ensure_mt5_trading_log_handler()
    logger = logging.getLogger("AUDIT")
    try:
        payload: Dict[str, Any] = {
            "ts": int(time.time() * 1000),
            "event": event,
            **fields,
        }
        # Keep one-line JSON so it's easy to grep.
        logger.info("[AUDIT] %s", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        # Never break trading flows due to logging.
        logger.info("[AUDIT] %s %s", event, fields)

