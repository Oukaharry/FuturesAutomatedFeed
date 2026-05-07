"""
Show raw client-name variants across hierarchy + DB.

This is for diagnosing invisible mismatches:
- trailing spaces
- non-breaking spaces (U+00A0)
- zero-width characters (U+200B..U+200D)

It prints:
- hierarchy occurrences (client list + profiles)
- clients_data client_id variants
- daily_checklists client_id variants
- audit_log details mentions that look like " ... for <client>"
"""

import os
import sys
from datetime import datetime


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def codepoints(s: str) -> str:
    return " ".join(f"U+{ord(ch):04X}" for ch in s)


def norm(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = s.replace("\u00A0", " ").replace("\u200B", "").replace("\u200C", "").replace("\u200D", "")
    s = " ".join(s.split())
    return s.strip()


def fmt(label: str, s: str):
    s = "" if s is None else str(s)
    n = norm(s)
    print(f"- {label}")
    print(f"  raw:  {s!r}")
    print(f"  norm: {n!r}")
    print(f"  cps:  {codepoints(s)}")


def main():
    target = "Maria Mendoza"
    target_norm = norm(target)
    print(f"Target: {target!r} (norm={target_norm!r})")
    print("")

    # ── Hierarchy ───────────────────────────────────────────────────
    from config.hierarchy import get_all_clients as hierarchy_all, get_client_profile

    print("=== HIERARCHY ===")
    h_clients = hierarchy_all() or []
    matches = []
    for c in h_clients:
        if target_norm in norm(c) or "mendoza" in norm(c).lower():
            matches.append(c)
    print(f"All clients count: {len(h_clients)}")
    print(f"Hierarchy matches: {len(matches)}")
    for i, c in enumerate(matches, 1):
        fmt(f"hierarchy client[{i}]", c)
        prof = get_client_profile(c) or {}
        if isinstance(prof, dict):
            fmt(f"  profile.name (derived)", c)
            fmt(f"  profile.trader", prof.get("trader", ""))
            fmt(f"  profile.admin", prof.get("admin", ""))
    print("")

    # ── Database ────────────────────────────────────────────────────
    from dashboard.database import get_connection

    def q_distinct(table: str, where_sql: str, params: tuple):
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT DISTINCT client_id FROM {table} WHERE {where_sql} ORDER BY client_id",
                params,
            )
            rows = cur.fetchall() or []
        return [r["client_id"] for r in rows]

    print("=== DB: clients_data.client_id variants ===")
    try:
        rows = q_distinct("clients_data", "btrim(client_id) = ? OR client_id ILIKE ?", (target_norm, f"%{target_norm}%"))
    except Exception:
        # If ILIKE unsupported in some deployments, fallback to btrim only
        rows = q_distinct("clients_data", "btrim(client_id) = ?", (target_norm,))
    print(f"Found: {len(rows)}")
    for i, r in enumerate(rows, 1):
        fmt(f"clients_data[{i}]", r)
    print("")

    print("=== DB: daily_checklists.client_id variants ===")
    try:
        rows = q_distinct("daily_checklists", "btrim(client_id) = ? OR client_id ILIKE ?", (target_norm, f"%{target_norm}%"))
    except Exception:
        rows = q_distinct("daily_checklists", "btrim(client_id) = ?", (target_norm,))
    print(f"Found: {len(rows)}")
    for i, r in enumerate(rows, 1):
        fmt(f"daily_checklists[{i}]", r)
    print("")

    print("=== DB: audit_log.details mentions (last 200) ===")
    # Pull recent audit rows mentioning Mendoza; parse client after " for "
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT timestamp, action, user_identifier, details "
            "FROM audit_log "
            "WHERE details ILIKE ? "
            "ORDER BY timestamp DESC LIMIT 200",
            (f"%mendoza%",),
        )
        audit = cur.fetchall() or []
    print(f"Found: {len(audit)}")
    import re
    seen_clients = {}
    for row in audit:
        details = row.get("details") or ""
        client = ""
        if " for " in details:
            part = details.split(" for ", 1)[1]
            part = re.sub(r":\s*\d+\s+sections?\s*$", "", part).strip()
            client = part
        key = norm(client) if client else ""
        if key and key not in seen_clients:
            seen_clients[key] = client
    if not seen_clients:
        print("(no parsable ' for <client>' entries found)")
    else:
        for k, raw in seen_clients.items():
            fmt("audit_log parsed client", raw)
    print("")

    print("Done.")


if __name__ == "__main__":
    main()

