#!/usr/bin/env python3
"""Repair a partially applied client rename across hierarchy and DB.

Typical failure mode:
- hierarchy/auth resolves the client as the new name
- clients_data and related tables still store the old name

This script is safe by default: it only reports what it would change.
Use --apply to persist changes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _parse_iso(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _row_jsonloads(row, key, default):
    try:
        value = row.get(key)
    except Exception:
        value = None
    if value is None:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _find_hierarchy_matches(old_name: str, new_name: str, email: str | None):
    from config.hierarchy import reload_hierarchy, SYSTEM_HIERARCHY

    reload_hierarchy()
    old_hits = []
    new_hits = []
    email_hits = []
    admins = (SYSTEM_HIERARCHY or {}).get("admins") or {}
    for admin_name, admin_data in admins.items():
        traders = (admin_data or {}).get("traders") or {}
        for trader_name, trader_data in traders.items():
            for client in (trader_data or {}).get("clients") or []:
                if not isinstance(client, dict):
                    continue
                name = str(client.get("name") or "").strip()
                client_email = str(client.get("email") or "").strip().lower()
                record = {
                    "admin": admin_name,
                    "trader": trader_name,
                    "name": name,
                    "email": client_email,
                    "category": client.get("category", ""),
                }
                if name == old_name:
                    old_hits.append(record)
                if name == new_name:
                    new_hits.append(record)
                if email and client_email == email.lower().strip():
                    email_hits.append(record)
    return old_hits, new_hits, email_hits


def repair_hierarchy(old_name: str, new_name: str, email: str | None, apply: bool) -> dict:
    from config.hierarchy import reload_hierarchy, save_hierarchy, SYSTEM_HIERARCHY

    old_hits, new_hits, email_hits = _find_hierarchy_matches(old_name, new_name, email)
    result = {
        "old_hits": old_hits,
        "new_hits": new_hits,
        "email_hits": email_hits,
        "renamed": 0,
    }
    if not apply:
        return result

    reload_hierarchy()
    changed = 0
    admins = (SYSTEM_HIERARCHY or {}).get("admins") or {}
    for admin_data in admins.values():
        traders = (admin_data or {}).get("traders") or {}
        for trader_data in traders.values():
            for client in (trader_data or {}).get("clients") or []:
                if not isinstance(client, dict):
                    continue
                name = str(client.get("name") or "").strip()
                client_email = str(client.get("email") or "").strip().lower()
                should_rename = name == old_name
                if not should_rename and email and client_email == email.lower().strip() and name != new_name:
                    should_rename = True
                if should_rename:
                    client["name"] = new_name
                    if email:
                        client["email"] = email
                    changed += 1
    if changed:
        save_hierarchy(SYSTEM_HIERARCHY)
    result["renamed"] = changed
    return result


def inspect_db_state(old_name: str, new_name: str) -> dict:
    from dashboard.database import get_connection, _lookup_client_data_row, _normalize_identifier

    table_specs = [
        ("clients_data", "client_id"),
        ("data_history", "client_id"),
        ("cell_notes", "client_id"),
        ("daily_watermarks", "client_id"),
        ("waterlog_periods", "client_id"),
        ("daily_checklists", "client_id"),
        ("quality_scan_results", "client_id"),
        ("quality_issue_baseline", "client_id"),
        ("quality_issue_resolution", "client_id"),
        ("qa_resolutions", "client_id"),
        ("m1_bars", "client_id"),
        ("api_keys", "client"),
        ("kyc_links", "primary_client"),
        ("kyc_links", "linked_client"),
    ]
    state = {"tables": {}, "old_row": None, "new_row": None}
    with get_connection() as conn:
        cur = conn.cursor()
        for table, column in table_specs:
            key = f"{table}.{column}"
            try:
                cur.execute(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE {column} IN (?, ?)",
                    (old_name, new_name),
                )
                count = (cur.fetchone() or {}).get("count", 0)
            except Exception:
                count = None
                conn.rollback()
            state["tables"][key] = count

        try:
            row, legacy_id = _lookup_client_data_row(
                old_name,
                _normalize_identifier(old_name),
                _conn=conn,
            )
            state["old_row"] = dict(row) if row else None
            state["old_legacy_id"] = legacy_id
        except Exception:
            state["old_row"] = None
            state["old_legacy_id"] = None
        try:
            row, legacy_id = _lookup_client_data_row(
                new_name,
                _normalize_identifier(new_name),
                _conn=conn,
            )
            state["new_row"] = dict(row) if row else None
            state["new_legacy_id"] = legacy_id
        except Exception:
            state["new_row"] = None
            state["new_legacy_id"] = None
    return state


def _upsert_clients_data(conn, client_id: str, payload: dict):
    cur = conn.cursor()
    now = datetime.now().isoformat()
    cur.execute(
        """
        INSERT INTO clients_data (
            client_id, deals, positions, account, evaluations,
            statistics, dropdown_options, identity, last_updated,
            hedge_accounts, prop_accounts, vps_accounts, payment_info, payment_address,
            mt5_credentials, firm_billing
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            deals = excluded.deals,
            positions = excluded.positions,
            account = excluded.account,
            evaluations = excluded.evaluations,
            statistics = excluded.statistics,
            dropdown_options = excluded.dropdown_options,
            identity = excluded.identity,
            last_updated = excluded.last_updated,
            hedge_accounts = excluded.hedge_accounts,
            prop_accounts = excluded.prop_accounts,
            vps_accounts = excluded.vps_accounts,
            payment_info = excluded.payment_info,
            payment_address = excluded.payment_address,
            mt5_credentials = excluded.mt5_credentials,
            firm_billing = excluded.firm_billing
        """,
        (
            client_id,
            json.dumps(payload.get("deals", [])),
            json.dumps(payload.get("positions", [])),
            json.dumps(payload.get("account", {})),
            json.dumps(payload.get("evaluations", [])),
            json.dumps(payload.get("statistics", {})),
            json.dumps(payload.get("dropdown_options", {})),
            json.dumps(payload.get("identity", {})),
            now,
            json.dumps(payload.get("hedge_accounts", [])),
            json.dumps(payload.get("prop_accounts", [])),
            json.dumps(payload.get("vps_accounts", [])),
            json.dumps(payload.get("payment_info", [])),
            json.dumps(payload.get("payment_address", {})),
            json.dumps(payload.get("mt5_credentials", {})),
            json.dumps(payload.get("firm_billing", {})),
        ),
    )


def merge_client_rows(old_name: str, new_name: str, apply: bool) -> dict:
    from dashboard.database import get_connection

    state = inspect_db_state(old_name, new_name)
    old_row = state["old_row"]
    new_row = state["new_row"]
    result = {
        "old_exists": bool(old_row),
        "new_exists": bool(new_row),
        "winner": None,
        "merged": False,
    }
    if not old_row and not new_row:
        return result

    winner_row = new_row or old_row
    winner_name = new_name if new_row else old_name
    old_ts = _parse_iso((old_row or {}).get("last_updated") if old_row else None)
    new_ts = _parse_iso((new_row or {}).get("last_updated") if new_row else None)

    if old_row and new_row:
        old_evals = len(_row_jsonloads(old_row, "evaluations", []))
        new_evals = len(_row_jsonloads(new_row, "evaluations", []))
        if old_evals > new_evals:
            winner_row = old_row
            winner_name = old_name
        elif new_evals > old_evals:
            winner_row = new_row
            winner_name = new_name
        elif old_ts and new_ts and old_ts > new_ts:
            winner_row = old_row
            winner_name = old_name

    result["winner"] = winner_name
    if not apply:
        return result

    payload = {
        "deals": _row_jsonloads(winner_row, "deals", []),
        "positions": _row_jsonloads(winner_row, "positions", []),
        "account": _row_jsonloads(winner_row, "account", {}),
        "evaluations": _row_jsonloads(winner_row, "evaluations", []),
        "statistics": _row_jsonloads(winner_row, "statistics", {}),
        "dropdown_options": _row_jsonloads(winner_row, "dropdown_options", {}),
        "identity": _row_jsonloads(winner_row, "identity", {}),
        "hedge_accounts": _row_jsonloads(winner_row, "hedge_accounts", []),
        "prop_accounts": _row_jsonloads(winner_row, "prop_accounts", []),
        "vps_accounts": _row_jsonloads(winner_row, "vps_accounts", []),
        "payment_info": _row_jsonloads(winner_row, "payment_info", []),
        "payment_address": _row_jsonloads(winner_row, "payment_address", {}),
        "mt5_credentials": _row_jsonloads(winner_row, "mt5_credentials", {}),
        "firm_billing": _row_jsonloads(winner_row, "firm_billing", {}),
    }
    identity = payload.get("identity") or {}
    if isinstance(identity, dict):
        identity["name"] = new_name
        identity["client"] = new_name
        payload["identity"] = identity

    with get_connection() as conn:
        cur = conn.cursor()
        _upsert_clients_data(conn, new_name, payload)
        if old_name != new_name:
            cur.execute("DELETE FROM clients_data WHERE client_id = ?", (old_name,))
        conn.commit()

    result["merged"] = True
    return result


def repair_credentials(old_name: str, new_name: str, email: str | None, apply: bool) -> dict:
    from dashboard.database import get_user, rename_user_credential, update_user_email

    old_user = get_user(old_name, "client")
    new_user = get_user(new_name, "client")
    result = {
        "old_exists": bool(old_user),
        "new_exists": bool(new_user),
        "renamed": False,
        "email_updated": False,
    }
    if not apply:
        return result

    if old_user and not new_user:
        result["renamed"] = bool(rename_user_credential(old_name, new_name, "client"))
        new_user = get_user(new_name, "client")
    if email and new_user:
        result["email_updated"] = bool(update_user_email(new_name, "client", email))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair a partially applied client rename.")
    parser.add_argument("--old-client", required=True, help="Legacy/original client name")
    parser.add_argument("--new-client", required=True, help="Target/current client name")
    parser.add_argument("--email", default="", help="Client email to anchor hierarchy/credential fixes")
    parser.add_argument("--apply", action="store_true", help="Persist changes (default is dry-run)")
    args = parser.parse_args()

    old_name = str(args.old_client or "").strip()
    new_name = str(args.new_client or "").strip()
    email = str(args.email or "").strip().lower() or None
    if not old_name or not new_name:
        print("Missing required client names")
        return 2

    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"Old client: {old_name}")
    print(f"New client: {new_name}")
    if email:
        print(f"Email: {email}")

    hierarchy_result = repair_hierarchy(old_name, new_name, email, apply=args.apply)
    db_before = inspect_db_state(old_name, new_name)
    merge_result = merge_client_rows(old_name, new_name, apply=args.apply)

    if args.apply:
        from dashboard.database import rename_client_in_db

        rename_client_in_db(old_name, new_name)
    creds_result = repair_credentials(old_name, new_name, email, apply=args.apply)
    db_after = inspect_db_state(old_name, new_name)

    print("\nHierarchy:")
    print(json.dumps(hierarchy_result, indent=2, default=str))

    print("\nDB before:")
    before_summary = {
        "old_exists": bool(db_before.get("old_row")),
        "new_exists": bool(db_before.get("new_row")),
        "old_evaluations": len(_row_jsonloads(db_before.get("old_row") or {}, "evaluations", [])),
        "new_evaluations": len(_row_jsonloads(db_before.get("new_row") or {}, "evaluations", [])),
        "tables": db_before.get("tables", {}),
    }
    print(json.dumps(before_summary, indent=2, default=str))

    print("\nMerge:")
    print(json.dumps(merge_result, indent=2, default=str))

    print("\nCredentials:")
    print(json.dumps(creds_result, indent=2, default=str))

    print("\nDB after:")
    after_summary = {
        "old_exists": bool(db_after.get("old_row")),
        "new_exists": bool(db_after.get("new_row")),
        "old_evaluations": len(_row_jsonloads(db_after.get("old_row") or {}, "evaluations", [])),
        "new_evaluations": len(_row_jsonloads(db_after.get("new_row") or {}, "evaluations", [])),
        "tables": db_after.get("tables", {}),
    }
    print(json.dumps(after_summary, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())