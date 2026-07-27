"""Which clients may push MT5 / hedging data to the dashboard."""

from __future__ import annotations

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


def is_client_push_blocked(
    client_id: Optional[str],
    identity: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Return True if companion pushes must be rejected for this client."""
    if is_client_inactive(identity):
        return True
    cid = str(client_id or "").strip()
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
