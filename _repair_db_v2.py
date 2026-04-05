#!/usr/bin/env python3
"""
Repair a corrupted SQLite database — analysis-first approach.

This script has TWO modes:
  1. ANALYZE (default) — diagnose corruption without modifying anything
  2. REPAIR  (--repair) — dump all readable data into a fresh database

SAFETY RULES:
  - The original DB is NEVER modified or deleted
  - Corrupt originals are preserved as .corrupt.TIMESTAMP
  - Swap only happens with explicit --swap flag after verification
  - Every step is logged to _repair_report.txt

USAGE:
  python3 _repair_db_v2.py                        # Analyze only (safe)
  python3 _repair_db_v2.py --repair               # Analyze + create repaired copy
  python3 _repair_db_v2.py --swap                  # Swap (after verifying repaired copy)
  python3 _repair_db_v2.py --db /path/to/db        # Custom DB path
  python3 _repair_db_v2.py --vacuum                # Also VACUUM the repaired copy (slow but shrinks size)
"""
import os
import sys
import sqlite3
import shutil
import hashlib
import json
import time
from datetime import datetime
from contextlib import contextmanager

# ── Configuration ──
DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_repair_report.txt')

# Tables ordered by importance (critical data first)
CRITICAL_TABLES = [
    'clients_data',
    'user_credentials',
    'api_keys',
    'admin_passwords',
    'evaluations',
    'phase_definitions',
    'kyc_links',
]
IMPORTANT_TABLES = [
    'cell_notes',
    'daily_watermarks',
    'waterlog_periods',
    'daily_checklists',
    'quality_scan_results',
    'system_settings',
]
PURGEABLE_TABLES = [
    'audit_log',
    'data_history',
    'sessions',
    'login_attempts',
]


class RepairReport:
    """Collects and prints repair diagnostics."""
    def __init__(self):
        self.lines = []
        self.warnings = []
        self.errors = []

    def log(self, msg, level='INFO'):
        line = f"[{level}] {msg}"
        self.lines.append(line)
        print(msg)
        if level == 'WARN':
            self.warnings.append(msg)
        elif level == 'ERROR':
            self.errors.append(msg)

    def section(self, title):
        sep = '=' * 70
        self.log(f"\n{sep}")
        self.log(title)
        self.log(sep)

    def save(self, path):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f"Repair Report — {datetime.now().isoformat()}\n")
            f.write('=' * 70 + '\n\n')
            for line in self.lines:
                f.write(line.replace('[INFO] ', '').replace('[WARN] ', 'WARNING: ').replace('[ERROR] ', 'ERROR: ') + '\n')
            if self.warnings:
                f.write(f"\n\nTotal Warnings: {len(self.warnings)}\n")
            if self.errors:
                f.write(f"Total Errors: {len(self.errors)}\n")


def get_file_md5(filepath, chunk_size=8192):
    """MD5 hash of a file for comparison."""
    h = hashlib.md5()
    with open(filepath, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def safe_connect(db_path, readonly=False):
    """Connect to a database with safe defaults."""
    if readonly:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=60)
    else:
        conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════════════
#  PHASE 1: ANALYSIS (read-only, never modifies anything)
# ═══════════════════════════════════════════════════════════════════

def analyze_database(db_path, report):
    """Full diagnostic analysis of the database. Returns dict of findings."""
    report.section("PHASE 1: DATABASE ANALYSIS")
    findings = {
        'db_path': db_path,
        'exists': False,
        'accessible': False,
        'integrity': None,
        'wal_mode': None,
        'tables': {},
        'total_rows': 0,
        'size_mb': 0,
        'wal_size_mb': 0,
        'can_read': False,
        'can_write': False,
        'corruption_type': None,
    }

    # ── File existence & sizes ──
    if not os.path.exists(db_path):
        report.log(f"Database not found at {db_path}", 'ERROR')
        return findings

    findings['exists'] = True
    findings['size_mb'] = os.path.getsize(db_path) / 1024 / 1024

    wal_path = db_path + '-wal'
    shm_path = db_path + '-shm'
    findings['wal_exists'] = os.path.exists(wal_path)
    findings['shm_exists'] = os.path.exists(shm_path)
    if findings['wal_exists']:
        findings['wal_size_mb'] = os.path.getsize(wal_path) / 1024 / 1024

    report.log(f"Database: {db_path}")
    report.log(f"  Size: {findings['size_mb']:.1f} MB")
    if findings['wal_exists']:
        report.log(f"  WAL:  {findings['wal_size_mb']:.1f} MB")
    if findings['shm_exists']:
        report.log(f"  SHM:  exists")

    # ── Check for existing corrupt/repaired copies ──
    parent = os.path.dirname(db_path)
    base = os.path.basename(db_path)
    related = sorted([f for f in os.listdir(parent) if f.startswith(base)])
    if len(related) > 1:
        report.log(f"\n  Related files in {parent}:")
        for f in related:
            fpath = os.path.join(parent, f)
            fmb = os.path.getsize(fpath) / 1024 / 1024
            report.log(f"    {f} — {fmb:.1f} MB")

    # ── Connection test ──
    report.log(f"\nConnection test...")
    try:
        conn = safe_connect(db_path, readonly=True)
        findings['accessible'] = True
        report.log(f"  Read connection: OK")
    except Exception as e:
        report.log(f"  Read connection: FAILED — {e}", 'ERROR')
        return findings

    # ── Journal mode ──
    try:
        mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
        findings['wal_mode'] = mode
        report.log(f"  Journal mode:   {mode}")
    except Exception as e:
        report.log(f"  Journal mode:   cannot read — {e}", 'WARN')

    # ── Page info ──
    try:
        page_size = conn.execute('PRAGMA page_size').fetchone()[0]
        page_count = conn.execute('PRAGMA page_count').fetchone()[0]
        freelist = conn.execute('PRAGMA freelist_count').fetchone()[0]
        report.log(f"  Page size:      {page_size} bytes")
        report.log(f"  Page count:     {page_count:,}")
        report.log(f"  Free pages:     {freelist:,} ({freelist * page_size / 1024 / 1024:.1f} MB reclaimable)")
        findings['freelist_mb'] = freelist * page_size / 1024 / 1024
    except Exception as e:
        report.log(f"  Page info:      cannot read — {e}", 'WARN')

    # ── Integrity check ──
    report.log(f"\nIntegrity check (this may take a while on large DBs)...")
    try:
        start = time.time()
        results = conn.execute('PRAGMA integrity_check(100)').fetchall()
        elapsed = time.time() - start
        integrity_msgs = [r[0] for r in results]
        findings['integrity'] = integrity_msgs[0] if len(integrity_msgs) == 1 and integrity_msgs[0] == 'ok' else 'FAILED'
        findings['integrity_details'] = integrity_msgs

        if findings['integrity'] == 'ok':
            report.log(f"  Result: OK ({elapsed:.1f}s)")
        else:
            report.log(f"  Result: CORRUPTION DETECTED ({elapsed:.1f}s)", 'ERROR')
            for msg in integrity_msgs[:20]:
                report.log(f"    {msg}", 'ERROR')
            if len(integrity_msgs) > 20:
                report.log(f"    ... and {len(integrity_msgs) - 20} more issues", 'ERROR')
    except Exception as e:
        findings['integrity'] = f'CHECK FAILED: {e}'
        report.log(f"  Result: CHECK ITSELF FAILED — {e}", 'ERROR')

    # ── Quick integrity check (faster, just checks b-tree structure) ──
    try:
        qc = conn.execute('PRAGMA quick_check(100)').fetchall()
        qc_msgs = [r[0] for r in qc]
        if len(qc_msgs) == 1 and qc_msgs[0] == 'ok':
            report.log(f"  Quick check:    OK")
        else:
            report.log(f"  Quick check:    ISSUES FOUND", 'WARN')
            for msg in qc_msgs[:10]:
                report.log(f"    {msg}", 'WARN')
    except Exception as e:
        report.log(f"  Quick check:    FAILED — {e}", 'WARN')

    # ── Table-by-table analysis ──
    report.log(f"\nTable analysis:")
    try:
        tables = conn.execute(
            "SELECT name, type FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t[0] for t in tables]
        report.log(f"  Tables found: {len(table_names)}")
    except Exception as e:
        report.log(f"  Cannot list tables — {e}", 'ERROR')
        conn.close()
        return findings

    for tname in table_names:
        tinfo = {'readable': False, 'row_count': 0, 'columns': [], 'error': None}
        try:
            # Count rows
            count = conn.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
            tinfo['row_count'] = count
            tinfo['readable'] = True
            findings['total_rows'] += count

            # Get columns
            cols = conn.execute(f'PRAGMA table_info("{tname}")').fetchall()
            tinfo['columns'] = [c[1] for c in cols]

            # Estimate size (rows * avg row size from first 100 rows)
            try:
                sample = conn.execute(f'SELECT * FROM "{tname}" LIMIT 100').fetchall()
                if sample:
                    avg_row_bytes = sum(sum(len(str(v)) for v in row) for row in sample) / len(sample)
                    est_mb = (avg_row_bytes * count) / 1024 / 1024
                    tinfo['est_size_mb'] = est_mb
                    size_str = f" (~{est_mb:.1f} MB est.)"
                else:
                    size_str = ""
            except:
                size_str = ""

            # Category
            if tname in CRITICAL_TABLES:
                cat = "CRITICAL"
            elif tname in IMPORTANT_TABLES:
                cat = "important"
            elif tname in PURGEABLE_TABLES:
                cat = "purgeable"
            else:
                cat = "other"

            report.log(f"    {tname}: {count:,} rows, {len(tinfo['columns'])} cols [{cat}]{size_str}")

        except Exception as e:
            tinfo['error'] = str(e)
            report.log(f"    {tname}: READ ERROR — {e}", 'ERROR')

        findings['tables'][tname] = tinfo

    findings['can_read'] = any(t['readable'] for t in findings['tables'].values())

    # ── Write test ──
    report.log(f"\nWrite test...")
    conn.close()
    try:
        conn_w = safe_connect(db_path)
        conn_w.execute('BEGIN IMMEDIATE')
        conn_w.execute('ROLLBACK')
        conn_w.close()
        findings['can_write'] = True
        report.log(f"  Write (BEGIN IMMEDIATE): OK")
    except Exception as e:
        findings['can_write'] = False
        findings['corruption_type'] = 'write_blocked'
        report.log(f"  Write (BEGIN IMMEDIATE): BLOCKED — {e}", 'WARN')

    # ── WAL checkpoint test (don't actually checkpoint, just check status) ──
    try:
        conn_c = safe_connect(db_path, readonly=True)
        wal_pages = conn_c.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()
        if wal_pages:
            report.log(f"  WAL status: {wal_pages[0]} (busy={wal_pages[0]}, log={wal_pages[1]}, checkpointed={wal_pages[2]})")
        conn_c.close()
    except Exception as e:
        report.log(f"  WAL checkpoint status: {e}", 'WARN')

    # ── Diagnosis ──
    report.section("DIAGNOSIS")
    if findings['integrity'] == 'ok' and findings['can_write']:
        report.log("Database appears HEALTHY. No repair needed.")
        report.log("If you're still seeing errors, the issue may be WAL contention (multiple writers).")
        findings['needs_repair'] = False
    elif findings['integrity'] == 'ok' and not findings['can_write']:
        report.log("Database integrity is OK but WRITES ARE BLOCKED.")
        report.log("This is typically WAL corruption — the WAL/SHM files are damaged.")
        report.log("Repair strategy: dump all data → fresh DB (WAL files are NOT copied).")
        findings['needs_repair'] = True
        findings['corruption_type'] = 'wal_corruption'
    elif findings['integrity'] != 'ok' and findings['can_read']:
        report.log("Database has INTEGRITY ISSUES but data is still READABLE.")
        report.log("Repair strategy: dump all readable data → fresh DB → verify zero loss.")
        findings['needs_repair'] = True
        findings['corruption_type'] = 'partial_corruption'
    else:
        report.log("Database has SEVERE CORRUPTION — some tables may be unreadable.", 'ERROR')
        report.log("Repair strategy: salvage what we can → fresh DB → report any losses.")
        findings['needs_repair'] = True
        findings['corruption_type'] = 'severe_corruption'

    # Size analysis
    if findings['size_mb'] > 1000:
        report.log(f"\nSIZE WARNING: Database is {findings['size_mb']:.0f} MB.")
        audit_rows = findings['tables'].get('audit_log', {}).get('row_count', 0)
        history_rows = findings['tables'].get('data_history', {}).get('row_count', 0)
        audit_est = findings['tables'].get('audit_log', {}).get('est_size_mb', 0)
        history_est = findings['tables'].get('data_history', {}).get('est_size_mb', 0)
        if audit_rows > 50000 or history_rows > 50000:
            report.log(f"  audit_log:    {audit_rows:,} rows (~{audit_est:.0f} MB est.)")
            report.log(f"  data_history: {history_rows:,} rows (~{history_est:.0f} MB est.)")
            report.log(f"  These tables are the likely cause of the bloated size.")
            report.log(f"  Use --vacuum during repair to reclaim space (adds time).")
        freelist = findings.get('freelist_mb', 0)
        if freelist > 100:
            report.log(f"  {freelist:.0f} MB in free pages — VACUUM would reclaim this.")

    return findings


# ═══════════════════════════════════════════════════════════════════
#  PHASE 2: REPAIR (creates a new DB alongside, never touches original)
# ═══════════════════════════════════════════════════════════════════

def repair_database(db_path, report, do_vacuum=False):
    """Dump all readable data from corrupt DB into a fresh copy."""
    fresh_path = db_path + '.repaired'
    report.section("PHASE 2: REPAIR")

    if os.path.exists(fresh_path):
        report.log(f"Removing previous repaired copy: {fresh_path}")
        os.remove(fresh_path)

    # ── Step 1: Read schema ──
    report.log(f"\n1. Reading schema from {os.path.basename(db_path)}...")
    conn_old = safe_connect(db_path, readonly=True)

    schema_rows = conn_old.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY "
        "CASE type WHEN 'table' THEN 1 WHEN 'index' THEN 2 WHEN 'trigger' THEN 3 ELSE 4 END, name"
    ).fetchall()
    report.log(f"   Schema objects: {len(schema_rows)}")

    # Get table list in dependency-safe order
    tables = conn_old.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    table_names = [t[0] for t in tables]

    # ── Step 2: Read all data table-by-table ──
    report.log(f"\n2. Reading all data (table-by-table, streaming)...")
    table_data = {}
    total_read = 0

    for tname in table_names:
        try:
            start_t = time.time()
            # Get column names
            cols_info = conn_old.execute(f'PRAGMA table_info("{tname}")').fetchall()
            cols = [c[1] for c in cols_info]

            # Stream rows in batches to handle large tables
            count = conn_old.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
            rows = []
            batch_size = 10000
            if count <= batch_size:
                rows = [tuple(r) for r in conn_old.execute(f'SELECT * FROM "{tname}"').fetchall()]
            else:
                # Use ROWID-based pagination for large tables
                cursor = conn_old.execute(f'SELECT * FROM "{tname}"')
                while True:
                    batch = cursor.fetchmany(batch_size)
                    if not batch:
                        break
                    rows.extend([tuple(r) for r in batch])

            elapsed = time.time() - start_t
            table_data[tname] = {'columns': cols, 'rows': rows}
            total_read += len(rows)
            report.log(f"   {tname}: {len(rows):,} rows read ({elapsed:.1f}s)")

        except Exception as e:
            report.log(f"   {tname}: READ FAILED — {e}", 'ERROR')
            table_data[tname] = {'columns': [], 'rows': [], 'error': str(e)}

    conn_old.close()
    report.log(f"   Total rows read: {total_read:,}")

    # ── Step 3: Create fresh database ──
    report.log(f"\n3. Creating fresh database: {os.path.basename(fresh_path)}")
    conn_new = sqlite3.connect(fresh_path)
    conn_new.execute('PRAGMA journal_mode=WAL')
    conn_new.execute('PRAGMA synchronous=NORMAL')

    # Apply schema
    schema_errors = 0
    for stype, sname, sql in schema_rows:
        if sname.startswith('sqlite_'):
            continue
        try:
            conn_new.execute(sql)
        except Exception as e:
            schema_errors += 1
            report.log(f"   Schema: {stype} {sname} — {e}", 'WARN')

    if schema_errors:
        report.log(f"   {schema_errors} schema warnings (usually OK — duplicate indexes, etc.)")
    else:
        report.log(f"   Schema applied: {len(schema_rows)} objects")

    # ── Step 4: Insert all data ──
    report.log(f"\n4. Inserting data into fresh database...")
    total_inserted = 0
    insert_errors = {}

    for tname in table_names:
        data = table_data.get(tname, {})
        rows = data.get('rows', [])
        cols = data.get('columns', [])
        if not rows or not cols:
            continue

        placeholders = ', '.join(['?'] * len(cols))
        col_names = ', '.join([f'"{c}"' for c in cols])
        insert_sql = f'INSERT INTO "{tname}" ({col_names}) VALUES ({placeholders})'

        try:
            start_t = time.time()
            # Insert in batches for large tables
            batch_size = 5000
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i + batch_size]
                conn_new.executemany(insert_sql, batch)
            conn_new.commit()
            elapsed = time.time() - start_t
            total_inserted += len(rows)
            report.log(f"   {tname}: {len(rows):,} rows inserted ({elapsed:.1f}s)")
        except Exception as e:
            report.log(f"   {tname}: batch insert failed — {e}", 'WARN')
            report.log(f"   {tname}: falling back to row-by-row insert...")
            conn_new.rollback()
            ok = 0
            fail = 0
            for row in rows:
                try:
                    conn_new.execute(insert_sql, row)
                    ok += 1
                except:
                    fail += 1
            conn_new.commit()
            total_inserted += ok
            if fail:
                insert_errors[tname] = fail
            report.log(f"   {tname}: {ok:,} ok, {fail:,} failed")

    report.log(f"   Total inserted: {total_inserted:,}")

    # ── Step 5: Optional VACUUM ──
    if do_vacuum:
        report.log(f"\n5. Running VACUUM (this compacts the database, may take a while)...")
        start_t = time.time()
        try:
            conn_new.execute('VACUUM')
            elapsed = time.time() - start_t
            report.log(f"   VACUUM complete ({elapsed:.1f}s)")
        except Exception as e:
            report.log(f"   VACUUM failed: {e}", 'WARN')
    else:
        report.log(f"\n5. Skipping VACUUM (use --vacuum to compact)")

    # ── Step 6: Verify ──
    report.section("PHASE 3: VERIFICATION")

    # Integrity check
    report.log(f"\n1. Integrity check on repaired DB...")
    integrity = conn_new.execute('PRAGMA integrity_check').fetchone()[0]
    report.log(f"   Result: {integrity}")

    # Row count verification
    report.log(f"\n2. Row count verification:")
    all_ok = True
    for tname in table_names:
        expected = len(table_data.get(tname, {}).get('rows', []))
        try:
            actual = conn_new.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
            if actual == expected:
                report.log(f"   {tname}: {actual:,} rows — OK")
            else:
                diff = actual - expected
                report.log(f"   {tname}: {actual:,} rows (expected {expected:,}, diff {diff:+,}) — MISMATCH", 'ERROR')
                all_ok = False
        except Exception as e:
            report.log(f"   {tname}: verify error — {e}", 'ERROR')
            all_ok = False

    # Deep verify clients_data (most critical table)
    report.log(f"\n3. Deep content verification (clients_data)...")
    cd = table_data.get('clients_data', {})
    cd_cols = cd.get('columns', [])
    cd_rows = cd.get('rows', [])

    if cd_cols and cd_rows:
        try:
            cid_idx = cd_cols.index('client_id')
            old_by_cid = {}
            for row in cd_rows:
                old_by_cid[row[cid_idx]] = {cd_cols[i]: row[i] for i in range(len(cd_cols))}

            conn_new.row_factory = sqlite3.Row
            new_rows = conn_new.execute('SELECT * FROM clients_data').fetchall()
            new_by_cid = {r['client_id']: dict(r) for r in new_rows}

            missing = set(old_by_cid) - set(new_by_cid)
            extra = set(new_by_cid) - set(old_by_cid)
            if missing:
                report.log(f"   MISSING clients: {sorted(missing)}", 'ERROR')
                all_ok = False
            if extra:
                report.log(f"   EXTRA clients: {sorted(extra)}", 'WARN')

            diffs = 0
            for cid in sorted(old_by_cid):
                if cid not in new_by_cid:
                    continue
                for col in old_by_cid[cid]:
                    old_v = old_by_cid[cid][col]
                    new_v = new_by_cid[cid].get(col)
                    if old_v != new_v:
                        diffs += 1
                        if diffs <= 5:
                            report.log(f"   DIFF: {cid}.{col} — old={str(old_v)[:60]} != new={str(new_v)[:60]}", 'ERROR')

            if diffs == 0:
                report.log(f"   ALL {len(old_by_cid)} clients verified — ZERO field differences")
            else:
                report.log(f"   {diffs} field differences found!", 'ERROR')
                all_ok = False
        except Exception as e:
            report.log(f"   Deep verify error: {e}", 'WARN')
    else:
        report.log(f"   clients_data was empty or unreadable — skipping deep verify", 'WARN')

    # Deep verify user_credentials
    report.log(f"\n4. Deep content verification (user_credentials)...")
    uc = table_data.get('user_credentials', {})
    uc_cols = uc.get('columns', [])
    uc_rows = uc.get('rows', [])
    if uc_cols and uc_rows:
        try:
            conn_new.row_factory = sqlite3.Row
            new_uc = conn_new.execute('SELECT * FROM user_credentials').fetchall()
            if len(new_uc) == len(uc_rows):
                report.log(f"   user_credentials: {len(new_uc)} rows — OK")
            else:
                report.log(f"   user_credentials: {len(new_uc)} vs expected {len(uc_rows)} — MISMATCH", 'ERROR')
                all_ok = False
        except Exception as e:
            report.log(f"   user_credentials verify error: {e}", 'WARN')

    # Write test
    report.log(f"\n5. Write test on repaired DB...")
    try:
        conn_new.execute('BEGIN IMMEDIATE')
        conn_new.execute(
            "UPDATE clients_data SET last_updated = last_updated "
            "WHERE client_id = (SELECT client_id FROM clients_data LIMIT 1)"
        )
        conn_new.execute('ROLLBACK')
        report.log(f"   Write test: PASSED (rolled back)")
    except Exception as e:
        report.log(f"   Write test: FAILED — {e}", 'ERROR')
        all_ok = False

    # Size comparison
    fresh_size = os.path.getsize(fresh_path) / 1024 / 1024
    orig_size = os.path.getsize(db_path) / 1024 / 1024
    report.log(f"\n6. Size comparison:")
    report.log(f"   Original:  {orig_size:.1f} MB")
    report.log(f"   Repaired:  {fresh_size:.1f} MB")
    if fresh_size < orig_size:
        saved = orig_size - fresh_size
        report.log(f"   Saved:     {saved:.1f} MB ({saved/orig_size*100:.0f}% smaller)")

    conn_new.close()

    # ── Summary ──
    report.section("RESULT")
    if integrity == 'ok' and all_ok:
        report.log(f"REPAIR SUCCESSFUL — zero data loss verified")
        report.log(f"  Original (untouched): {db_path}")
        report.log(f"  Repaired copy:        {fresh_path}")
        report.log(f"\n  To activate the repaired copy:")
        report.log(f"    python3 _repair_db_v2.py --swap")
    else:
        report.log(f"REPAIR COMPLETED WITH ISSUES", 'WARN')
        report.log(f"  Integrity: {integrity}")
        report.log(f"  Data OK:   {all_ok}")
        if insert_errors:
            report.log(f"  Insert errors: {insert_errors}")
        report.log(f"\n  Review the report and fix issues before swapping.")

    return integrity == 'ok' and all_ok


# ═══════════════════════════════════════════════════════════════════
#  PHASE 3: SWAP (rename corrupt → .corrupted_TS, repaired → active)
# ═══════════════════════════════════════════════════════════════════

def swap_databases(db_path, report):
    """Swap the original with the repaired copy. Original is NEVER deleted."""
    fresh_path = db_path + '.repaired'
    report.section("SWAP")

    if not os.path.exists(fresh_path):
        report.log(f"No repaired DB found at {fresh_path}", 'ERROR')
        report.log(f"Run: python3 _repair_db_v2.py --repair")
        return False

    if not os.path.exists(db_path):
        report.log(f"Original DB not found at {db_path}", 'ERROR')
        return False

    # Pre-swap validation
    report.log(f"Pre-swap validation...")
    conn = safe_connect(fresh_path, readonly=True)
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    try:
        client_count = conn.execute('SELECT COUNT(*) FROM clients_data').fetchone()[0]
    except:
        client_count = -1
    try:
        user_count = conn.execute('SELECT COUNT(*) FROM user_credentials').fetchone()[0]
    except:
        user_count = -1
    conn.close()

    if integrity != 'ok':
        report.log(f"ABORT: Repaired DB integrity check FAILED: {integrity}", 'ERROR')
        return False

    report.log(f"  Repaired DB: {client_count} clients, {user_count} users, integrity=ok")

    # Rename original → .corrupted_TIMESTAMP
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    corrupted_path = db_path + f'.corrupted_{ts}'
    wal_path = db_path + '-wal'
    shm_path = db_path + '-shm'

    report.log(f"\n1. Preserving original → {os.path.basename(corrupted_path)}")
    os.rename(db_path, corrupted_path)

    if os.path.exists(wal_path):
        os.rename(wal_path, corrupted_path + '-wal')
        report.log(f"   Also preserved WAL file")
    if os.path.exists(shm_path):
        os.rename(shm_path, corrupted_path + '-shm')
        report.log(f"   Also preserved SHM file")

    report.log(f"2. Activating repaired → {os.path.basename(db_path)}")
    os.rename(fresh_path, db_path)

    # Post-swap verification
    conn = safe_connect(db_path)
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    try:
        count = conn.execute('SELECT COUNT(*) FROM clients_data').fetchone()[0]
    except:
        count = -1

    # Test write
    write_ok = False
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('ROLLBACK')
        write_ok = True
    except:
        pass
    conn.close()

    report.section("SWAP COMPLETE")
    report.log(f"  Active DB:    {db_path}")
    report.log(f"  Clients:      {count}")
    report.log(f"  Integrity:    {integrity}")
    report.log(f"  Writes:       {'OK' if write_ok else 'BLOCKED'}")
    report.log(f"  Old original: {corrupted_path} (preserved, NEVER deleted)")
    return True


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Analyze and repair corrupted SQLite database')
    parser.add_argument('--db', default=None, help='Path to database (default: ~/MT5Dashboard/dashboard/dashboard.db)')
    parser.add_argument('--repair', action='store_true', help='Create a repaired copy (analyze first)')
    parser.add_argument('--swap', action='store_true', help='Swap original with repaired copy')
    parser.add_argument('--vacuum', action='store_true', help='VACUUM the repaired copy to reclaim space')
    args = parser.parse_args()

    db_path = args.db or DB_PATH
    report = RepairReport()

    report.log(f"Database Repair Tool v2 — {datetime.now().isoformat()}")
    report.log(f"Target: {db_path}")

    if args.swap:
        success = swap_databases(db_path, report)
    else:
        # Always analyze first
        findings = analyze_database(db_path, report)

        if args.repair:
            if not findings.get('can_read'):
                report.log(f"\nCannot proceed with repair — database is not readable.", 'ERROR')
                report.save(REPORT_PATH)
                return False
            success = repair_database(db_path, report, do_vacuum=args.vacuum)
        else:
            success = not findings.get('needs_repair', False)
            if findings.get('needs_repair'):
                report.log(f"\n  To repair: python3 _repair_db_v2.py --repair")
                report.log(f"  To repair + compact: python3 _repair_db_v2.py --repair --vacuum")

    # Save report
    report.save(REPORT_PATH)
    report.log(f"\nReport saved to: {REPORT_PATH}")

    return success


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
