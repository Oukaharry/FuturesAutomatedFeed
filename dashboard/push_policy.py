"""Which clients may push MT5 / hedging data to the dashboard."""

from __future__ import annotations

import time
from typing import Any, Mapping, Optional

# Hard block — survives even if identity.push_blocked is cleared by mistake.
PUSH_BLOCKED_CLIENT_IDS = frozenset({"Fallback"})

# Only dashboard admin toggles may change these identity fields (never companion push).
ADMIN_CONTROLLED_IDENTITY_FIELDS = frozenset({"active_status"})

_VALID_ACTIVE_STATUSES = frozenset({"active", "inactive"})


def normalize_active_status(value: Any, default: str = "active") -> str:
    status = str(value or default).strip().lower()
    return status if status in _VALID_ACTIVE_STATUSES else default


def is_valid_active_status(value: Any) -> bool:
    return str(value or "").strip().lower() in _VALID_ACTIVE_STATUSES


def is_client_inactive(identity: Optional[Mapping[str, Any]] = None) -> bool:
    ident = identity if isinstance(identity, Mapping) else {}
    return normalize_active_status(ident.get("active_status")) == "inactive"


def merge_identity_preserving_admin_fields(
    existing: Optional[Mapping[str, Any]],
    incoming: Optional[Mapping[str, Any]],
) -> dict:
    """Shallow-merge identity; admin-controlled fields always stay on the existing value."""
    base = dict(existing or {})
    if not incoming:
        return base
    merged = {**base, **dict(incoming)}
    for key in ADMIN_CONTROLLED_IDENTITY_FIELDS:
        if key in base:
            merged[key] = base[key]
    return merged

# Personal trading override: Fallback and all KYC-linked accounts under it
# must always be allowed to push companion data.
ALWAYS_ALLOW_PUSH_PRIMARY_CLIENT = "Fallback"

_ALLOW_CACHE_TTL_SECS = 30.0
_allow_cache_until = 0.0
_allow_cache_ids: frozenset[str] = frozenset({ALWAYS_ALLOW_PUSH_PRIMARY_CLIENT})


def _allowed_push_client_ids() -> frozenset[str]:
    """Resolve always-allowed clients: primary + all linked KYC accounts."""
    global _allow_cache_until, _allow_cache_ids

    now = time.monotonic()
    if now < _allow_cache_until:
        return _allow_cache_ids

    resolved = {ALWAYS_ALLOW_PUSH_PRIMARY_CLIENT}
    try:
        # Local import avoids a module-level dependency on database bootstrap.
        from dashboard.database import get_all_kyc_accounts

        for name in get_all_kyc_accounts(ALWAYS_ALLOW_PUSH_PRIMARY_CLIENT) or []:
            cid = str(name or "").strip()
            if cid:
                resolved.add(cid)
    except Exception:
        # If DB is unavailable, keep at least the primary account exempt.
        pass

    _allow_cache_ids = frozenset(resolved)
    _allow_cache_until = now + _ALLOW_CACHE_TTL_SECS
    return _allow_cache_ids


def is_client_push_blocked(
    client_id: Optional[str],
    identity: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Return True if companion pushes must be rejected for this client."""
    cid = str(client_id or "").strip()
    if cid and cid in _allowed_push_client_ids():
        return False
    if is_client_inactive(identity):
        return True
    if cid in PUSH_BLOCKED_CLIENT_IDS:
        return True
    ident = identity if isinstance(identity, Mapping) else {}
    flag = ident.get("push_blocked")
    if flag is True:
        return True
    if str(flag or "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return False


def push_blocked_message(
    client_id: str,
    identity: Optional[Mapping[str, Any]] = None,
) -> str:
    if is_client_inactive(identity):
        return (
            f"Client {client_id} is inactive. "
            "Dashboard sync is disabled until an admin reactivates the account in the dashboard."
        )
    return f"Dashboard data pushes are disabled for {client_id}."
