"""
Cleanup a client whose name differs only by whitespace across hierarchy/DB.

For the given pair:
  legacy_id  = 'Maria Mendoza '   (trailing space, as seen in hierarchy)
  canonical  = 'Maria Mendoza'

Actions:
1) Update hierarchy JSON so the client name is canonical (trimmed).
2) Merge duplicate clients_data rows:
   - Pick the "winner" record using latest last_updated (fallback: canonical)
   - Ensure only one row remains under canonical id.
3) Update related tables to replace legacy_id -> canonical where safe.

This script is safe to re-run: it prints what it did.
"""

import os
import sys
from datetime import datetime


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


LEGACY_ID = "Maria Mendoza "
CANONICAL_ID = "Maria Mendoza"


def _norm(s: str) -> str:
    if s is None:
        return ""
    s = str(s).replace("\u00A0", " ").replace("\u200B", "").replace("\u200C", "").replace("\u200D", "")
    s = " ".join(s.split())
    return s.strip()


def _parse_iso(ts: str):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def cleanup_hierarchy():
    from config.hierarchy import reload_hierarchy, save_hierarchy, SYSTEM_HIERARCHY

    reload_hierarchy()
    changed = 0
    for admin_name, admin_data in (SYSTEM_HIERARCHY.get("admins") or {}).items():
        traders = admin_data.get("traders") or {}
        for trader_name, trader_data in traders.items():
            clients = trader_data.get("clients") or []
            for client in clients:
                if not isinstance(client, dict):
                    continue
                nm = client.get("name")
                if nm == LEGACY_ID:
                    client["name"] = CANONICAL_ID
                    changed += 1
    if changed:
        save_hierarchy(SYSTEM_HIERARCHY)
    return changed


def _row_jsonloads(row, key, default):
    import json

    try:
        v = row.get(key)
    except Exception:
        v = None
    if v is None:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


def _upsert_clients_data(conn, client_id: str, payload: dict):
    import json

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


def merge_clients_data():
    from dashboard.database import get_connection

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM clients_data WHERE client_id IN (?, ?) ORDER BY client_id", (CANONICAL_ID, LEGACY_ID))
        rows = cur.fetchall() or []

        by_id = {r["client_id"]: r for r in rows}
        canon = by_id.get(CANONICAL_ID)
        legacy = by_id.get(LEGACY_ID)

        if not legacy and not canon:
            return {"status": "noop", "reason": "No clients_data rows found for either id"}

        if legacy and not canon:
            # simple rename: delete any canonical (none) and update legacy id
            cur.execute("UPDATE clients_data SET client_id = ? WHERE client_id = ?", (CANONICAL_ID, LEGACY_ID))
            return {"status": "renamed", "winner": LEGACY_ID}

        if canon and not legacy:
            return {"status": "noop", "reason": "Only canonical row exists"}

        # both exist: pick winner by latest last_updated
        canon_ts = _parse_iso(canon.get("last_updated"))
        legacy_ts = _parse_iso(legacy.get("last_updated"))

        winner_id = CANONICAL_ID
        loser_id = LEGACY_ID
        if legacy_ts and canon_ts and legacy_ts > canon_ts:
            winner_id, loser_id = LEGACY_ID, CANONICAL_ID
        elif legacy_ts and not canon_ts:
            winner_id, loser_id = LEGACY_ID, CANONICAL_ID

        winner_row = by_id[winner_id]

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

        # Force-save payload under canonical id, then delete both and keep one canonical row
        _upsert_clients_data(conn, CANONICAL_ID, payload)
        cur.execute("DELETE FROM clients_data WHERE client_id = ?", (LEGACY_ID,))

        return {
            "status": "merged",
            "winner": winner_id,
            "loser": loser_id,
            "canon_last_updated": canon.get("last_updated"),
            "legacy_last_updated": legacy.get("last_updated"),
        }


def update_related_tables():
    """
    Update legacy_id -> canonical across related tables.
    We only do updates that cannot violate a unique constraint in typical schema.
    (If a conflict happens, we catch and continue so the script doesn't brick.)
    """
    from dashboard.database import get_connection

    tables = [
        ("data_history", "client_id"),
        ("cell_notes", "client_id"),
        ("daily_watermarks", "client_id"),
        ("waterlog_periods", "client_id"),
        ("daily_checklists", "client_id"),
        ("quality_scan_results", "client_id"),
    ]
    # KYC links have different column names
    kyc_cols = [("kyc_links", "primary_client"), ("kyc_links", "linked_client")]

    counts = {}
    with get_connection() as conn:
        cur = conn.cursor()
        for tbl, col in tables:
            try:
                cur.execute(f"UPDATE {tbl} SET {col} = ? WHERE {col} = ?", (CANONICAL_ID, LEGACY_ID))
                counts[f"{tbl}.{col}"] = int(cur.rowcount)
            except Exception as e:
                counts[f"{tbl}.{col}"] = f"error: {e}"
        for tbl, col in kyc_cols:
            try:
                cur.execute(f"UPDATE {tbl} SET {col} = ? WHERE {col} = ?", (CANONICAL_ID, LEGACY_ID))
                counts[f"{tbl}.{col}"] = int(cur.rowcount)
            except Exception as e:
                counts[f"{tbl}.{col}"] = f"error: {e}"
    return counts


def main():
    assert _norm(LEGACY_ID) == _norm(CANONICAL_ID), "This script expects IDs to differ only by whitespace"

    print(f"Legacy:    {LEGACY_ID!r}")
    print(f"Canonical: {CANONICAL_ID!r}")
    print("")

    h = cleanup_hierarchy()
    print(f"[hierarchy] renamed entries: {h}")

    m = merge_clients_data()
    print(f"[clients_data] {m}")

    rel = update_related_tables()
    print("[related tables] updated rows:")
    for k in sorted(rel.keys()):
        print(f"  - {k}: {rel[k]}")

    print("")
    print("Done. Restart the server to reload hierarchy cache.")


if __name__ == "__main__":
    main()

