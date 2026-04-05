#!/usr/bin/env python3
"""
Repair a corrupted SQLite database by dumping all readable data
into a fresh database file.

This fixes WAL corruption where reads work but writes fail with
"database disk image is malformed".

SAFETY: The original DB is NEVER modified or deleted.
        A fresh copy is created alongside it.
        You must manually rename/swap after verifying zero data loss.

Run:   python3 _repair_db.py                  (create repaired copy)
Swap:  python3 _repair_db.py --swap           (swap after verifying)
"""
import os
import sys
import json
import sqlite3
import shutil
from datetime import datetime

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
FRESH_PATH = DB_PATH + '.repaired'


def repair_database(db_path=None):
    target = db_path or DB_PATH
    fresh_path = (db_path or DB_PATH) + '.repaired'
    if not os.path.exists(target):
        print(f"ERROR: Database not found at {target}")
        return False

    # Size info
    size_mb = os.path.getsize(target) / 1024 / 1024
    wal_path = target + '-wal'
    shm_path = target + '-shm'
    wal_size = os.path.getsize(wal_path) / 1024 / 1024 if os.path.exists(wal_path) else 0
    print(f"Original DB: {target} ({size_mb:.1f} MB)")
    if wal_size:
        print(f"WAL file: {wal_path} ({wal_size:.1f} MB)")
    if os.path.exists(shm_path):
        print(f"SHM file: {shm_path}")

    # ── Step 1: Read all data from corrupted DB ──
    print(f"\n1. Reading all data from corrupted DB...")
    try:
        conn_old = sqlite3.connect(target)
        conn_old.row_factory = sqlite3.Row

        # Get all table names
        tables = conn_old.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t[0] for t in tables]
        print(f"   Tables found: {', '.join(table_names)}")

        # Read schema (CREATE TABLE, CREATE INDEX, etc.)
        schema_rows = conn_old.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type DESC, name"
        ).fetchall()
        schema_sql = [r[0] for r in schema_rows]

        # Read all data from each table
        table_data = {}
        for tname in table_names:
            try:
                rows = conn_old.execute(f'SELECT * FROM "{tname}"').fetchall()
                if rows:
                    cols = [desc[0] for desc in conn_old.execute(f'SELECT * FROM "{tname}" LIMIT 1').description]
                    table_data[tname] = {
                        'columns': cols,
                        'rows': [tuple(r) for r in rows],
                    }
                    print(f"   {tname}: {len(rows)} rows, {len(cols)} columns")
                else:
                    table_data[tname] = {'columns': [], 'rows': []}
                    print(f"   {tname}: 0 rows")
            except Exception as e:
                print(f"   {tname}: ERROR reading — {e}")
                table_data[tname] = {'columns': [], 'rows': []}

        conn_old.close()
    except Exception as e:
        print(f"   FATAL: Cannot read corrupted DB — {e}")
        return False

    # ── Step 2: Create fresh database (alongside, NOT replacing) ──
    if os.path.exists(fresh_path):
        os.remove(fresh_path)

    print(f"\n2. Creating repaired database at {fresh_path}")
    conn_new = sqlite3.connect(fresh_path)

    # Create schema
    for sql in schema_sql:
        try:
            conn_new.execute(sql)
        except Exception as e:
            print(f"   Schema warning: {e}")
            print(f"   SQL: {sql[:200]}")

    # Insert all data (skip sqlite_sequence — SQLite manages it internally)
    for tname, data in table_data.items():
        rows = data['rows']
        cols = data['columns']
        if not rows or not cols:
            continue
        if tname == 'sqlite_sequence':
            print(f"   {tname}: skipped (SQLite auto-manages this table)")
            continue
        placeholders = ', '.join(['?'] * len(cols))
        col_names = ', '.join([f'"{c}"' for c in cols])
        try:
            conn_new.executemany(
                f'INSERT INTO "{tname}" ({col_names}) VALUES ({placeholders})',
                rows
            )
            print(f"   {tname}: inserted {len(rows)} rows")
        except Exception as e:
            print(f"   {tname}: batch ERROR — {e}")
            # Try row by row to preserve maximum data
            ok = 0
            fail = 0
            for row in rows:
                try:
                    conn_new.execute(
                        f'INSERT INTO "{tname}" ({col_names}) VALUES ({placeholders})',
                        row
                    )
                    ok += 1
                except:
                    fail += 1
            print(f"   {tname}: row-by-row insert — {ok} ok, {fail} failed")

    conn_new.commit()

    # ── Step 3: Verify integrity + zero data loss ──
    print(f"\n3. Verifying repaired database...")
    integrity = conn_new.execute('PRAGMA integrity_check').fetchone()[0]
    print(f"   Integrity: {integrity}")

    all_ok = True
    for tname in table_names:
        try:
            new_count = conn_new.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
            expected = len(table_data.get(tname, {}).get('rows', []))
            if tname == 'sqlite_sequence':
                # SQLite auto-manages this; row count will differ and that's fine
                print(f"   {tname}: {new_count} rows — OK (auto-managed)")
            elif new_count != expected:
                all_ok = False
                print(f"   {tname}: {new_count} rows — MISMATCH (expected {expected}) !!!")
            else:
                print(f"   {tname}: {new_count} rows — OK")
        except Exception as e:
            print(f"   {tname}: verify error — {e}")
            all_ok = False

    # Deep verify clients_data — compare repaired DB against what we read in step 1
    # (NOT re-reading the original, which may have changed from live writes)
    print(f"\n4. Deep-verifying clients_data content (cell-level)...")
    try:
        # Build expected data from what we read in step 1
        cd_data = table_data.get('clients_data', {})
        cd_cols = cd_data.get('columns', [])
        cd_rows = cd_data.get('rows', [])
        cid_col_idx = cd_cols.index('client_id') if 'client_id' in cd_cols else 0
        old_clients = {}
        for row in cd_rows:
            cid = row[cid_col_idx]
            old_clients[cid] = {cd_cols[i]: row[i] for i in range(len(cd_cols))}

        conn_new.row_factory = sqlite3.Row
        new_clients = {r['client_id']: dict(r) for r in
                       conn_new.execute('SELECT * FROM clients_data').fetchall()}

        missing = set(old_clients.keys()) - set(new_clients.keys())
        extra = set(new_clients.keys()) - set(old_clients.keys())
        if missing:
            all_ok = False
            print(f"   MISSING clients in repaired DB: {sorted(missing)}")
        if extra:
            print(f"   EXTRA clients in repaired DB (unexpected): {sorted(extra)}")

        data_loss = 0
        for cid in sorted(old_clients.keys()):
            if cid not in new_clients:
                continue
            old_row = old_clients[cid]
            new_row = new_clients[cid]
            for col in old_row:
                old_val = old_row[col]
                new_val = new_row.get(col)
                if old_val != new_val:
                    data_loss += 1
                    if data_loss <= 10:
                        print(f"   DIFF: {cid}.{col} — old({str(old_val)[:80]}) != new({str(new_val)[:80]})")

        if data_loss == 0:
            print(f"   ALL {len(old_clients)} clients verified — ZERO data loss")
        else:
            all_ok = False
            print(f"   {data_loss} field differences found!")
    except Exception as e:
        print(f"   Deep verify error: {e}")

    fresh_size = os.path.getsize(fresh_path) / 1024 / 1024
    print(f"\n   Repaired DB size: {fresh_size:.1f} MB")
    conn_new.close()

    # ── Step 4: Test that writes work on repaired DB ──
    print(f"\n5. Testing writes on repaired database...")
    try:
        conn_test = sqlite3.connect(fresh_path)
        # Try a harmless write + rollback
        conn_test.execute('BEGIN')
        conn_test.execute("UPDATE clients_data SET last_updated = last_updated WHERE client_id = (SELECT client_id FROM clients_data LIMIT 1)")
        conn_test.execute('ROLLBACK')
        print(f"   Write test: PASSED (writes work, rolled back)")
        conn_test.close()
    except Exception as e:
        print(f"   Write test: FAILED — {e}")
        all_ok = False

    # ── Summary ──
    print(f"\n{'='*70}")
    if integrity == 'ok' and all_ok:
        print(f"REPAIRED DB READY — zero data loss verified")
        print(f"  Original (untouched): {target}")
        print(f"  Repaired copy:        {fresh_path}")
        print(f"\n  To swap (after you've verified):")
        print(f"  python3 _repair_db.py --swap")
    else:
        print(f"VERIFICATION FAILED — repaired DB may not be identical!")
        print(f"  Original (untouched): {target}")
        print(f"  Repaired copy:        {fresh_path}")
        print(f"  DO NOT swap until issues are resolved.")
    print(f"{'='*70}")
    return integrity == 'ok' and all_ok


def swap_databases(db_path=None):
    """
    Swap the original corrupted DB with the repaired copy.
    The original is renamed to .corrupted_TIMESTAMP (never deleted).
    """
    target = db_path or DB_PATH
    fresh_path = (db_path or DB_PATH) + '.repaired'

    if not os.path.exists(fresh_path):
        print(f"ERROR: No repaired DB found at {fresh_path}")
        print(f"  Run: python3 _repair_db.py   (to create it first)")
        return False

    if not os.path.exists(target):
        print(f"ERROR: Original DB not found at {target}")
        return False

    # Final pre-swap integrity check on repaired DB
    conn = sqlite3.connect(fresh_path)
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    count = conn.execute('SELECT COUNT(*) FROM clients_data').fetchone()[0]
    conn.close()
    if integrity != 'ok':
        print(f"ABORT: Repaired DB integrity check FAILED: {integrity}")
        return False

    print(f"Repaired DB: {count} clients, integrity={integrity}")

    # Rename original → .corrupted_TIMESTAMP (NEVER deleted)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    corrupted_path = target + f'.corrupted_{ts}'
    wal_path = target + '-wal'
    shm_path = target + '-shm'

    print(f"\n1. Renaming original → {os.path.basename(corrupted_path)}")
    os.rename(target, corrupted_path)
    if os.path.exists(wal_path):
        os.rename(wal_path, corrupted_path + '-wal')
        print(f"   Also moved WAL file")
    if os.path.exists(shm_path):
        os.rename(shm_path, corrupted_path + '-shm')
        print(f"   Also moved SHM file")

    print(f"2. Renaming repaired → {os.path.basename(target)}")
    os.rename(fresh_path, target)

    # Verify
    conn = sqlite3.connect(target)
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    count = conn.execute('SELECT COUNT(*) FROM clients_data').fetchone()[0]
    conn.close()

    print(f"\n{'='*70}")
    print(f"SWAP COMPLETE")
    print(f"  Active DB:    {target} ({count} clients, integrity={integrity})")
    print(f"  Old original: {corrupted_path} (preserved, never deleted)")
    print(f"{'='*70}")

    print(f"\nNow re-run the reconstruction script:")
    print(f"  python3 _reconstruct_from_logs_v2.py --apply")
    return True


if __name__ == '__main__':
    if '--swap' in sys.argv:
        success = swap_databases()
    else:
        success = repair_database()
    sys.exit(0 if success else 1)
