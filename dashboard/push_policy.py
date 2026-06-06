"""Which clients may push MT5 / hedging data to the dashboard."""

from __future__ import annotations

from typing import Any, Mapping, Optional

# Hard block — survives even if identity.push_blocked is cleared by mistake.
PUSH_BLOCKED_CLIENT_IDS = frozenset({"Fallback"})


def is_client_push_blocked(
    client_id: Optional[str],
    identity: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Return True if companion pushes must be rejected for this client."""
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


def push_blocked_message(client_id: str) -> str:
    return f"Dashboard data pushes are disabled for {client_id}."
