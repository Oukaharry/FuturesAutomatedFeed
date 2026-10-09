"""Auto-sync MyFundedPerps accounts into dashboard evaluation rows.

A client row holds one Read-And-Trade API key; every challenge account on
that key is mirrored here. New accounts become evaluation rows the moment
sync runs (key saved in the UI, or the periodic job); rows we created are
tagged with the MFP account id and get status refreshes on later runs.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

PERPS_FIRM = "MyFundedPerps"
# Per-client cooldown so dashboard-triggered syncs can't hammer the API.
_SYNC_COOLDOWN_SEC = 30
_last_sync: dict = {}
_sync_lock = threading.Lock()


def _sandbox_allowed() -> bool:
    """Sandbox keys are for testing only; set PERPS_SYNC_ALLOW_SANDBOX=1 locally."""
    return str(os.environ.get("PERPS_SYNC_ALLOW_SANDBOX", "0")).strip().lower() in (
        "1", "true", "yes")


# The API has no billing endpoints, so the fee comes from the published
# challenge pricing (Select tier, PERPS code) keyed by starting balance.
# Only stamped at row creation — edits for other tiers/promos are kept.
_CHALLENGE_FEE_BY_SIZE = {
    10000: "28",
    25000: "70",
    50000: "133",
    100000: "252",
}


def _challenge_fee(starting_balance) -> str:
    try:
        return _CHALLENGE_FEE_BY_SIZE.get(int(round(float(starting_balance))), "0")
    except (TypeError, ValueError):
        return "0"


def client_perps_api_key(client_data: dict) -> str:
    for acc in client_data.get("prop_accounts") or []:
        if (acc.get("prop_firm") == PERPS_FIRM
                and str(acc.get("api_key") or "").strip()):
            return str(acc["api_key"]).strip()
    return str(client_data.get("mfp_api_key") or "").strip()


def _fmt_date(epoch_ms) -> str:
    try:
        return datetime.fromtimestamp(float(epoch_ms) / 1000,
                                      tz=timezone.utc).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return ""


def _fmt_size(starting_balance) -> str:
    try:
        return f"${int(round(float(starting_balance))):,}"
    except (TypeError, ValueError):
        return ""


def _row_for_account(acct: dict) -> dict:
    funded = str(acct.get("stage") or "").lower() == "funded"
    failed = str(acct.get("status") or "").lower() in ("failed", "breached")
    row = {
        "Prop Firm": PERPS_FIRM,
        "Account #": acct.get("account_number") or "",
        "Account Size": _fmt_size(acct.get("starting_balance")),
        "Date Purchased": _fmt_date(acct.get("created_at")),
        "Date Started": _fmt_date(acct.get("created_at")),
        "Fee": _challenge_fee(acct.get("starting_balance")),
        "Status P1": ("Fail" if failed else ("Pass" if funded else "In Progress")),
        "Status": "-",
        "_perps_account_id": acct.get("id") or "",
        "_row_added_at": datetime.now(timezone.utc).isoformat(),
    }
    if funded and not failed:
        row["Status Funded"] = "In Progress"
    return row


def _refresh_row_status(row: dict, acct: dict) -> bool:
    """Update a previously-synced row's status; returns True when changed."""
    status = str(acct.get("status") or "").lower()
    funded = str(acct.get("stage") or "").lower() == "funded"
    changed = False
    if status in ("failed", "breached"):
        target_field = "Status Funded" if funded else "Status P1"
        if str(row.get(target_field) or "").strip().lower() != "fail":
            row[target_field] = "Fail"
            changed = True
    elif funded and str(row.get("Status P1") or "").strip().lower() != "pass":
        row["Status P1"] = "Pass"
        row.setdefault("Status Funded", "In Progress")
        changed = True
    return changed


def sync_client_perps_accounts(client_id: str, changed_by: str = "perps_sync",
                               force: bool = False) -> dict:
    """Mirror the client's MFP accounts into evaluation rows. Idempotent."""
    from dashboard.database import get_client_data, save_client_data_with_history

    with _sync_lock:
        last = _last_sync.get(client_id, 0)
        if not force and time.time() - last < _SYNC_COOLDOWN_SEC:
            return {"status": "cooldown", "added": 0, "updated": 0}
        _last_sync[client_id] = time.time()

    client_data = get_client_data(client_id)
    if not client_data:
        return {"status": "no_client", "added": 0, "updated": 0}
    api_key = client_perps_api_key(client_data)
    if not api_key:
        return {"status": "no_key", "added": 0, "updated": 0}
    if api_key.startswith("fp_test_") and not _sandbox_allowed():
        logger.info("[PerpsSync] %s: sandbox key ignored — live keys only", client_id)
        return {"status": "sandbox_key",
                "message": "Sandbox (fp_test_) keys are for testing only — "
                           "enter the client's fp_live_ key to sync real accounts.",
                "added": 0, "updated": 0}

    from trader_companion.perps_connector import MFPClient, MFPError, unwrap
    try:
        accounts = unwrap(MFPClient(api_key, timeout=15).list_accounts()) or []
    except MFPError as exc:
        logger.warning("[PerpsSync] %s: API error %s", client_id, exc)
        return {"status": "api_error", "message": str(exc), "added": 0, "updated": 0}
    except Exception as exc:
        logger.warning("[PerpsSync] %s: %s", client_id, exc)
        return {"status": "error", "message": str(exc), "added": 0, "updated": 0}

    evaluations = client_data.get("evaluations") or []
    by_account = {str(r.get("Account #") or "").strip(): r for r in evaluations}
    by_perps_id = {str(r.get("_perps_account_id") or "").strip(): r
                   for r in evaluations if r.get("_perps_account_id")}

    added = updated = 0
    for acct in accounts:
        if str(acct.get("status") or "").lower() == "archived":
            continue
        num = str(acct.get("account_number") or "").strip()
        row = by_perps_id.get(str(acct.get("id") or "")) or by_account.get(num)
        if row is None:
            if not num:
                continue
            evaluations.append(_row_for_account(acct))
            added += 1
        elif row.get("_perps_account_id") and _refresh_row_status(row, acct):
            updated += 1

    if added or updated:
        client_data["evaluations"] = evaluations
        save_client_data_with_history(
            client_id, client_data, changed_by=changed_by,
            change_source="perps_sync",
            change_description=f"MyFundedPerps sync: {added} added, {updated} updated")
        logger.info("[PerpsSync] %s: %d added, %d updated", client_id, added, updated)
    return {"status": "success", "added": added, "updated": updated,
            "accounts": len(accounts)}


def sync_all_clients_perps() -> dict:
    """Periodic pass over every client that has a perps API key."""
    from dashboard.database import get_all_clients, get_client_data

    totals = {"clients": 0, "added": 0, "updated": 0}
    for client_id in get_all_clients():
        try:
            data = get_client_data(client_id)
            if not data or not client_perps_api_key(data):
                continue
            result = sync_client_perps_accounts(client_id, force=True)
            if result.get("status") == "success":
                totals["clients"] += 1
                totals["added"] += result["added"]
                totals["updated"] += result["updated"]
        except Exception:
            logger.exception("[PerpsSync] failed for %s", client_id)
    return totals
