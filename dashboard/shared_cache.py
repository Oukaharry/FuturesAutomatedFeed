"""
Shared API response cache (Postgres L2 + in-process L1).

Phase 1: endpoint TTL + single-flight (per worker lock + Postgres advisory lock).
Phase 2: Postgres table shared across all uWSGI workers on PythonAnywhere.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_table_ready = False
_table_lock = threading.Lock()
_local: dict[str, tuple[Any, float]] = {}
_local_guard = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}
_key_locks_guard = threading.Lock()

# Default TTLs (seconds)
HIERARCHY_CACHE_TTL = 90
SUPER_ADMIN_TOTALS_CACHE_TTL = 180


def _ensure_table() -> None:
    global _table_ready
    if _table_ready:
        return
    with _table_lock:
        if _table_ready:
            return
        try:
            from dashboard.database import get_connection

            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS api_response_cache (
                        cache_key   TEXT PRIMARY KEY,
                        payload     TEXT NOT NULL,
                        expires_at  TIMESTAMPTZ NOT NULL,
                        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_api_response_cache_expires
                    ON api_response_cache (expires_at)
                    """
                )
                conn.commit()
            _table_ready = True
        except Exception as e:
            logger.warning("[shared_cache] table ensure failed: %s", e)


def _local_get(key: str) -> Optional[Any]:
    now = time.time()
    with _local_guard:
        row = _local.get(key)
        if not row:
            return None
        value, expiry = row
        if now >= expiry:
            del _local[key]
            return None
        return value


def _local_set(key: str, value: Any, ttl: int) -> None:
    with _local_guard:
        if len(_local) > 100:
            now = time.time()
            expired = [k for k, (_, exp) in _local.items() if now >= exp]
            for k in expired:
                del _local[k]
        _local[key] = (value, time.time() + ttl)


def _local_delete_prefix(prefix: str) -> None:
    with _local_guard:
        for k in list(_local.keys()):
            if k.startswith(prefix):
                del _local[k]


def cache_get(key: str) -> Optional[Any]:
    """Return cached JSON-decoded value if present and not expired."""
    hit = _local_get(key)
    if hit is not None:
        return hit

    _ensure_table()
    try:
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT payload FROM api_response_cache
                WHERE cache_key = ? AND expires_at > NOW()
                """,
                (key,),
            )
            row = cur.fetchone()
            if not row:
                return None
            payload = row["payload"] if hasattr(row, "keys") else row[0]
            value = json.loads(payload)
            # Warm L1 with remaining TTL approximated from default short window
            _local_set(key, value, 30)
            return value
    except Exception as e:
        logger.debug("[shared_cache] cache_get miss %s: %s", key, e)
        return None


def cache_set(key: str, value: Any, ttl: int) -> None:
    _local_set(key, value, ttl)
    _ensure_table()
    try:
        from dashboard.database import get_connection

        payload = json.dumps(value, default=str)
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO api_response_cache (cache_key, payload, expires_at, updated_at)
                VALUES (?, ?, NOW() + (? * INTERVAL '1 second'), NOW())
                ON CONFLICT (cache_key) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = NOW()
                """,
                (key, payload, int(ttl)),
            )
            conn.commit()
    except Exception as e:
        logger.warning("[shared_cache] cache_set failed %s: %s", key, e)


def invalidate_prefix(prefix: str) -> None:
    """Drop all keys starting with prefix (L1 + Postgres)."""
    _local_delete_prefix(prefix)
    _ensure_table()
    try:
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM api_response_cache WHERE cache_key LIKE ?",
                (prefix + "%",),
            )
            conn.commit()
    except Exception as e:
        logger.warning("[shared_cache] invalidate_prefix failed %s: %s", prefix, e)


def invalidate_key(key: str) -> None:
    with _local_guard:
        _local.pop(key, None)
    _ensure_table()
    try:
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM api_response_cache WHERE cache_key = ?", (key,))
            conn.commit()
    except Exception as e:
        logger.warning("[shared_cache] invalidate_key failed %s: %s", key, e)


def _lock_for_key(key: str) -> threading.Lock:
    with _key_locks_guard:
        lock = _key_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _key_locks[key] = lock
        return lock


def _try_pg_advisory_lock(key: str) -> bool:
    _ensure_table()
    try:
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_lock(hashtext(?))", (key,))
            row = cur.fetchone()
            locked = row["pg_try_advisory_lock"] if hasattr(row, "keys") else row[0]
            conn.commit()
            return bool(locked)
    except Exception as e:
        logger.debug("[shared_cache] advisory lock unavailable %s: %s", key, e)
        return True  # proceed without cross-worker lock if PG unsupported


def _pg_advisory_unlock(key: str) -> None:
    try:
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT pg_advisory_unlock(hashtext(?))", (key,))
            conn.commit()
    except Exception:
        pass


def get_or_compute(
    key: str,
    ttl: int,
    compute_fn: Callable[[], Any],
    *,
    max_wait: float = 45.0,
) -> Any:
    """
    Return cached value or compute once (single-flight across workers when possible).
    """
    cached = cache_get(key)
    if cached is not None:
        return cached

    lock = _lock_for_key(key)
    with lock:
        cached = cache_get(key)
        if cached is not None:
            return cached

        got_pg_lock = _try_pg_advisory_lock(key)
        if got_pg_lock:
            try:
                cached = cache_get(key)
                if cached is not None:
                    return cached
                value = compute_fn()
                cache_set(key, value, ttl)
                return value
            finally:
                _pg_advisory_unlock(key)

        # Another worker is computing — wait for Postgres L2
        deadline = time.time() + max_wait
        while time.time() < deadline:
            time.sleep(0.25)
            cached = cache_get(key)
            if cached is not None:
                return cached

        logger.warning("[shared_cache] wait timeout for %s — computing locally", key)
        value = compute_fn()
        cache_set(key, value, ttl)
        return value
