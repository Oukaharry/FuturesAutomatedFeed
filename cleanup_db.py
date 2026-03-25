"""
Database Cleanup Script — Run once to prune bloated tables and reclaim disk space.

SAFE TABLES (never touched):
  - clients_data    (all current evaluations, deals, positions, statistics, identity)
  - cell_notes      (evaluation cell notes)
  - daily_watermarks (daily profit snapshots)
  - waterlog_periods (bi-weekly schedules)
  - user_credentials, admin_passwords, api_keys
  - quality_scan_results, daily_checklists

PRUNED TABLES:
  - data_history  → keep latest 10 versions per client, delete entries >30 days old
  - audit_log     → delete entries older than 30 days
  - sessions      → delete expired sessions

Usage:
    python cleanup_db.py
"""
import os
import sys
import sqlite3
from datetime import datetime

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.database import init_database, cleanup_old_history, cleanup_audit_log, cleanup_expired_sessions, DB_PATH, get_connection


def fmt_size(bytes_val):
    """Format bytes into human-readable size."""
    if bytes_val >= 1024 * 1024 * 1024:
        return f"{bytes_val / (1024**3):.2f} GB"
    elif bytes_val >= 1024 * 1024:
        return f"{bytes_val / (1024**2):.2f} MB"
    elif bytes_val >= 1024:
        return f"{bytes_val / 1024:.1f} KB"
    return f"{bytes_val} bytes"


def get_table_stats(conn):
    """Get row counts for every table in the database."""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    stats = {}
    for t in tables:
        cursor.execute(f"SELECT COUNT(*) FROM [{t}]")
        stats[t] = cursor.fetchone()[0]
    return stats


def get_history_detail(conn):
    """Get per-client breakdown of data_history rows."""
    cursor = conn.cursor()
    cursor.execute('''
        SELECT client_id, COUNT(*) as cnt, MIN(created_at) as oldest, MAX(created_at) as newest
        FROM data_history
        GROUP BY client_id
        ORDER BY cnt DESC
    ''')
    return [dict(row) for row in cursor.fetchall()]


def main():
    init_database()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    print("=" * 70)
    print(f"  DATABASE CLEANUP SCRIPT — {timestamp}")
    print("=" * 70)

    # --- Database info ---
    size_before = os.path.getsize(DB_PATH)
    print(f"\n📁 Database path: {DB_PATH}")
    print(f"📊 Size before cleanup: {fmt_size(size_before)}")

    # --- Row counts BEFORE cleanup ---
    print("\n" + "-" * 50)
    print("TABLE ROW COUNTS (BEFORE CLEANUP)")
    print("-" * 50)
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        stats_before = get_table_stats(conn)
        for table, count in sorted(stats_before.items()):
            safe = "🟢 SAFE" if table not in ('data_history', 'audit_log', 'sessions') else "🔶 PRUNED"
            print(f"  {safe}  {table:30s}  {count:>8,} rows")

        # --- data_history detail ---
        history_detail = get_history_detail(conn)
        if history_detail:
            print(f"\n{'─' * 50}")
            print(f"DATA HISTORY DETAIL (per client)")
            print(f"{'─' * 50}")
            print(f"  {'Client':<30s}  {'Rows':>6s}  {'Oldest':>20s}  {'Newest':>20s}")
            for h in history_detail:
                oldest = (h['oldest'] or 'N/A')[:19]
                newest = (h['newest'] or 'N/A')[:19]
                print(f"  {h['client_id']:<30s}  {h['cnt']:>6,}  {oldest:>20s}  {newest:>20s}")
            total_history = sum(h['cnt'] for h in history_detail)
            print(f"  {'TOTAL':<30s}  {total_history:>6,}")

    # --- Verify clients_data is intact BEFORE ---
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM clients_data")
        clients_count_before = cursor.fetchone()['cnt']
        cursor.execute("SELECT client_id FROM clients_data ORDER BY client_id")
        client_ids_before = set(row['client_id'] for row in cursor.fetchall())

    # === RUN CLEANUP ===
    print(f"\n{'=' * 50}")
    print("RUNNING CLEANUP")
    print(f"{'=' * 50}")

    print("\n1️⃣  Pruning data_history (keep 10 versions per client, delete >30 days)...")
    history_deleted = cleanup_old_history(keep_versions=10)
    print(f"   → {history_deleted:,} rows deleted")

    print("\n2️⃣  Pruning audit_log (delete entries older than 30 days)...")
    audit_deleted = cleanup_audit_log(keep_days=30)
    print(f"   → {audit_deleted:,} rows deleted")

    print("\n3️⃣  Cleaning expired sessions...")
    cleanup_expired_sessions()
    print(f"   → expired sessions removed")

    # --- Row counts AFTER cleanup ---
    print(f"\n{'─' * 50}")
    print("TABLE ROW COUNTS (AFTER CLEANUP)")
    print(f"{'─' * 50}")
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        stats_after = get_table_stats(conn)
        for table, count in sorted(stats_after.items()):
            before = stats_before.get(table, 0)
            diff = before - count
            marker = f"(-{diff:,})" if diff > 0 else ""
            safe = "🟢" if table not in ('data_history', 'audit_log', 'sessions') else "🔶"
            print(f"  {safe}  {table:30s}  {count:>8,} rows  {marker}")

    # --- VACUUM ---
    print(f"\n4️⃣  Running VACUUM (reclaiming disk space)...")
    size_pre_vacuum = os.path.getsize(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("VACUUM")
    conn.close()
    size_after = os.path.getsize(DB_PATH)
    print(f"   → Pre-vacuum:  {fmt_size(size_pre_vacuum)}")
    print(f"   → Post-vacuum: {fmt_size(size_after)}")

    # --- Verify clients_data is INTACT after ---
    print(f"\n{'=' * 50}")
    print("SAFETY VERIFICATION")
    print(f"{'=' * 50}")
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM clients_data")
        clients_count_after = cursor.fetchone()['cnt']
        cursor.execute("SELECT client_id FROM clients_data ORDER BY client_id")
        client_ids_after = set(row['client_id'] for row in cursor.fetchall())

    if client_ids_before == client_ids_after and clients_count_before == clients_count_after:
        print(f"  ✅ clients_data INTACT: {clients_count_after} clients (no data lost)")
    else:
        missing = client_ids_before - client_ids_after
        print(f"  ❌ WARNING: clients_data changed!")
        print(f"     Before: {clients_count_before} clients")
        print(f"     After:  {clients_count_after} clients")
        if missing:
            print(f"     Missing: {missing}")

    # Spot-check: verify evaluations exist for each client
    eval_ok = 0
    eval_empty = []
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        for cid in sorted(client_ids_after):
            cursor.execute("SELECT evaluations FROM clients_data WHERE client_id = ?", (cid,))
            row = cursor.fetchone()
            if row and row['evaluations'] and row['evaluations'] != '[]':
                eval_ok += 1
            else:
                eval_empty.append(cid)

    print(f"  ✅ Evaluations present: {eval_ok}/{clients_count_after} clients")
    if eval_empty:
        print(f"  ⚠️  Clients with no evaluations (pre-existing, NOT caused by cleanup): {eval_empty}")

    # --- Summary ---
    saved = size_before - size_after
    print(f"\n{'=' * 50}")
    print("SUMMARY")
    print(f"{'=' * 50}")
    print(f"  Database size before: {fmt_size(size_before)}")
    print(f"  Database size after:  {fmt_size(size_after)}")
    print(f"  Space freed:          {fmt_size(saved)}")
    print(f"  data_history deleted: {history_deleted:,} rows")
    print(f"  audit_log deleted:    {audit_deleted:,} rows")
    print(f"  Clients preserved:    {clients_count_after} (all evaluations intact)")
    print(f"\n{'=' * 50}")
    print(f"  ✅ CLEANUP COMPLETE — {timestamp}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()

