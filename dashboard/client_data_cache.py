"""In-process cache for POST /api/client/data companion payloads."""

from __future__ import annotations

import os
import threading
import time

# Covers scan + outcome correction + load-trades in one UTC minute (no companion upgrade).
_DEFAULT_TTL_SEC = 75.0
CLIENT_DATA_CACHE_SEC = max(
    5.0,
    float(os.environ.get("CLIENT_DATA_CACHE_SEC", str(_DEFAULT_TTL_SEC))),
)

_lock = threading.Lock()
# client_id -> (monotonic_ts, companion_scan_epoch, payload dict)
_entries: dict[str, tuple[float, str, dict]] = {}


def _current_scan_epoch() -> str:
    try:
        from dashboard.database import get_setting

        return (get_setting("companion_scan_epoch") or "").strip()
    except Exception:
        return ""


def get_cached_client_data_payload(client_id: str) -> dict | None:
    """Return cached JSON payload if still valid for this scan minute."""
    if not client_id:
        return None
    now = time.monotonic()
    epoch = _current_scan_epoch()
    with _lock:
        entry = _entries.get(client_id)
        if not entry:
            return None
        stored_at, stored_epoch, payload = entry
        if (now - stored_at) >= CLIENT_DATA_CACHE_SEC:
            _entries.pop(client_id, None)
            return None
        if epoch and stored_epoch and epoch != stored_epoch:
            return None
        return payload


def store_client_data_payload(client_id: str, payload: dict) -> None:
    if not client_id:
        return
    epoch = _current_scan_epoch()
    with _lock:
        _entries[client_id] = (time.monotonic(), epoch, payload)


def invalidate_client_data_cache(client_id: str | None) -> None:
    if not client_id:
        return
    with _lock:
        _entries.pop(client_id, None)
