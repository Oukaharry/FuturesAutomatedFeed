#!/usr/bin/env python3
"""
Export all clients from dashboard.db to CSV, and reimport from CSV.

This reads from the CORRUPT .corrupt files (where the real data lives),
exports to CSV, then imports back into the active dashboard.db.

EXPORT: Reads clients_data + cell_notes + daily_watermarks + waterlog_periods
        from the best available source (corrupt backups or live DB).
        Writes one CSV with all evaluation rows flattened, plus JSON sidecar files.

IMPORT: Reads the CSV + JSON sidecars and writes to dashboard.db using
        save_client_data_with_history() for full versioning.

USAGE:
  python3 _export_import_clients.py                           # Export from best source (auto-detect)
  python3 _export_import_clients.py --source /path/to/db      # Export from a specific DB file
  python3 _export_import_clients.py --import                   # Import CSV back into dashboard.db
  python3 _export_import_clients.py --import --execute         # Actually write (default is dry-run)
  python3 _export_import_clients.py --import --client "Chris"  # Import single client

OUTPUT FILES (in ~/MT5Dashboard/):
  clients_export.csv             — One row per client, JSON fields as strings
  clients_export_notes.csv       — All cell_notes
  clients_export_watermarks.csv  — All daily_watermarks
  clients_export_periods.csv     — All waterlog_periods
"""
import os
import sys
import json
import csv
import sqlite3
import time
import glob
from datetime import datetime

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
EXPORT_DIR = os.path.expanduser('~/MT5Dashboard')
EXPORT_CSV = os.path.join(EXPORT_DIR, 'clients_export.csv')
EXPORT_NOTES = os.path.join(EXPORT_DIR, 'clients_export_notes.csv')
EXPORT_WATERMARKS = os.path.join(EXPORT_DIR, 'clients_export_watermarks.csv')
EXPORT_PERIODS = os.path.join(EXPORT_DIR, 'clients_export_periods.csv')

# All columns in clients_data that store JSON
JSON_COLUMNS = [
    'deals', 'positions', 'account', 'evaluations', 'statistics',
    'dropdown_options', 'identity', 'hedge_accounts', 'prop_accounts',
    'vps_accounts', 'payment_info', 'payment_address',
]
# Plain text columns
PLAIN_COLUMNS = ['client_id', 'last_updated']
ALL_COLUMNS = PLAIN_COLUMNS + JSON_COLUMNS


def safe_connect(db_path, readonly=False):
    if readonly:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=60)
    else:
        conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def try_read_table(conn, table, order_by=None):
    """Try multiple strategies to read a table from a potentially corrupt DB."""
    order = f' ORDER BY {order_by}' if order_by else ''
    rows = []
    cols = []

    # Get column names first (small read, usually works)
    try:
        info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        cols = [c[1] for c in info]
    except Exception as e:
        print(f"   Cannot read schema for {table}: {e}")
        return [], []

    # Strategy 1: Normal full read
    try:
        rows = conn.execute(f'SELECT * FROM "{table}"{order}').fetchall()
        return [dict(r) for r in rows], cols
    except Exception as e:
        print(f"   Full read failed: {e}")
        print(f"   Trying row-by-row via ROWID...")

    # Strategy 2: Read by ROWID one at a time (skips corrupt pages)
    try:
        # Get all rowids first
        rowids = []
        try:
            rowids = [r[0] for r in conn.execute(f'SELECT rowid FROM "{table}" ORDER BY rowid')]
        except:
            # If even rowid scan fails, try a range
            try:
                max_id = conn.execute(f'SELECT MAX(rowid) FROM "{table}"').fetchone()[0]
                if max_id:
                    rowids = list(range(1, max_id + 1))
            except:
                pass

        if not rowids:
            print(f"   Cannot enumerate rows for {table}")
            return [], cols

        ok = 0
        fail = 0
        for rid in rowids:
            try:
                row = conn.execute(f'SELECT * FROM "{table}" WHERE rowid = ?', (rid,)).fetchone()
                if row:
                    rows.append(dict(row))
                    ok += 1
            except:
                fail += 1

        print(f"   Row-by-row: {ok} recovered, {fail} corrupt/skipped")
        return rows, cols
    except Exception as e:
        print(f"   Row-by-row also failed: {e}")

    # Strategy 3: Read by primary key field if it exists (e.g., client_id)
    if 'client_id' in cols:
        try:
            print(f"   Trying individual client_id reads...")
            cids = [r[0] for r in conn.execute(f'SELECT DISTINCT client_id FROM "{table}"')]
            ok = 0
            for cid in cids:
                try:
                    for row in conn.execute(f'SELECT * FROM "{table}" WHERE client_id = ?', (cid,)):
                        rows.append(dict(row))
                        ok += 1
                except:
                    pass
            print(f"   By client_id: {ok} recovered from {len(cids)} clients")
            return rows, cols
        except Exception as e:
            print(f"   client_id strategy failed: {e}")

    return rows, cols


def _try_connect(db_path):
    """Try multiple connection strategies. Returns (conn, strategy_name) or (None, error)."""
    import urllib.parse
    # Ensure absolute path for URI
    abs_path = os.path.abspath(db_path)

    strategies = [
        ('immutable', f"file:{urllib.parse.quote(abs_path)}?immutable=1"),
        ('readonly', f"file:{urllib.parse.quote(abs_path)}?mode=ro"),
        ('normal', None),
    ]
    last_err = None
    for name, uri in strategies:
        try:
            if uri:
                conn = sqlite3.connect(uri, uri=True, timeout=30)
            else:
                conn = sqlite3.connect(abs_path, timeout=30)
            conn.row_factory = sqlite3.Row
            # Test that we can actually read
            conn.execute('SELECT COUNT(*) FROM clients_data').fetchone()
            return conn, name
        except Exception as e:
            last_err = e
            try:
                conn.close()
            except:
                pass
    return None, str(last_err)


def find_best_source(report_fn=print):
    """Find the best database to export from — prefer .corrupt files with the most clients."""
    db_dir = os.path.dirname(DB_PATH)
    db_name = os.path.basename(DB_PATH)

    if not os.path.isdir(db_dir):
        report_fn(f"ERROR: Directory {db_dir} not found")
        return None

    candidates = []

    # Check all .corrupt* files (skip tiny ones < 1 MB first pass, check large ones first)
    all_files = []
    for f in sorted(os.listdir(db_dir)):
        if not f.startswith(db_name):
            continue
        if f.endswith('-wal') or f.endswith('-shm'):
            continue
        fpath = os.path.join(db_dir, f)
        if not os.path.isfile(fpath):
            continue
        size_mb = os.path.getsize(fpath) / 1024 / 1024
        all_files.append((f, fpath, size_mb))

    # Sort largest first (more likely to have data)
    all_files.sort(key=lambda x: x[2], reverse=True)

    for f, fpath, size_mb in all_files:
        info = {'path': fpath, 'name': f, 'size_mb': size_mb, 'clients': -1, 'readable': False, 'strategy': None, 'error': None}

        # Skip tiny files (< 0.5 MB) — they're empty DBs
        if size_mb < 0.5:
            info['error'] = 'too small'
            candidates.append(info)
            report_fn(f"  {f}: {size_mb:.1f} MB — skipped (too small)")
            continue

        conn, result = _try_connect(fpath)
        if conn:
            try:
                info['clients'] = conn.execute('SELECT COUNT(*) FROM clients_data').fetchone()[0]
                info['readable'] = True
                info['strategy'] = result
                conn.close()
            except Exception as e:
                info['error'] = str(e)
                try: conn.close()
                except: pass
        else:
            info['error'] = result

        candidates.append(info)
        if info['readable']:
            report_fn(f"  {f}: {size_mb:.1f} MB, {info['clients']} clients [{info['strategy']}]")
        else:
            report_fn(f"  {f}: {size_mb:.1f} MB, UNREADABLE ({info['error'][:80]})")

    if not candidates:
        report_fn("No database files found!")
        return None

    # Sort: most clients wins, then largest file
    candidates.sort(key=lambda x: (x['readable'], x.get('clients', -1), x['size_mb']), reverse=True)
    best = candidates[0]

    if not best['readable'] or best['clients'] <= 0:
        report_fn(f"\nERROR: No readable database with client data found")
        report_fn(f"  Try specifying a file directly: python3 _export_import_clients.py --source /path/to/file")
        return None

    report_fn(f"\n  BEST: {best['name']} ({best['clients']} clients, {best['size_mb']:.1f} MB) [{best['strategy']}]")
    return best['path']


# ═══════════════════════════════════════════════════════════════
#  EXPORT
# ═══════════════════════════════════════════════════════════════

def export_clients(source_path):
    """Export all client data from source DB to CSV files."""
    print(f"\n{'='*70}")
    print(f"EXPORTING from: {source_path}")
    print(f"{'='*70}")

    conn, strategy = _try_connect(source_path)
    if not conn:
        print(f"\nERROR: Cannot connect to {source_path}")
        print(f"  Last error: {strategy}")
        return False
    print(f"\n  Connected via {strategy}")

    # ── 1. Export clients_data ──
    print(f"\n1. Exporting clients_data...")
    client_rows, cols = try_read_table(conn, 'clients_data', order_by='client_id')

    if not client_rows:
        print(f"   ERROR: No client data recovered!")
        conn.close()
        return False

    os.makedirs(EXPORT_DIR, exist_ok=True)

    with open(EXPORT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=ALL_COLUMNS, extrasaction='ignore')
        writer.writeheader()
        for row in client_rows:
            row_dict = {}
            for col in ALL_COLUMNS:
                val = row.get(col)
                if col in JSON_COLUMNS:
                    row_dict[col] = val if val else ('[]' if col.endswith('s') or col in ('deals','positions','hedge_accounts','prop_accounts','vps_accounts','payment_info') else '{}')
                else:
                    row_dict[col] = val
            writer.writerow(row_dict)

    print(f"   {len(client_rows)} clients -> {EXPORT_CSV}")

    # ── 2. Export cell_notes ──
    print(f"\n2. Exporting cell_notes...")
    try:
        note_rows, note_cols = try_read_table(conn, 'cell_notes', order_by='client_id')
        if note_rows and note_cols:
            with open(EXPORT_NOTES, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=note_cols)
                writer.writeheader()
                for n in note_rows:
                    writer.writerow({c: n.get(c) for c in note_cols})
            print(f"   {len(note_rows)} notes -> {EXPORT_NOTES}")
        else:
            print(f"   0 notes (empty or unreadable)")
    except Exception as e:
        print(f"   cell_notes: {e}")

    # ── 3. Export daily_watermarks ──
    print(f"\n3. Exporting daily_watermarks...")
    try:
        wm_rows, wm_cols = try_read_table(conn, 'daily_watermarks', order_by='client_id')
        if wm_rows and wm_cols:
            with open(EXPORT_WATERMARKS, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=wm_cols)
                writer.writeheader()
                for w in wm_rows:
                    writer.writerow({c: w.get(c) for c in wm_cols})
            print(f"   {len(wm_rows)} watermarks -> {EXPORT_WATERMARKS}")
        else:
            print(f"   0 watermarks (empty or unreadable)")
    except Exception as e:
        print(f"   daily_watermarks: {e}")

    # ── 4. Export waterlog_periods ──
    print(f"\n4. Exporting waterlog_periods...")
    try:
        wp_rows, wp_cols = try_read_table(conn, 'waterlog_periods', order_by='client_id')
        if wp_rows and wp_cols:
            with open(EXPORT_PERIODS, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=wp_cols)
                writer.writeheader()
                for p in wp_rows:
                    writer.writerow({c: p.get(c) for c in wp_cols})
            print(f"   {len(wp_rows)} periods -> {EXPORT_PERIODS}")
        else:
            print(f"   0 periods (empty or unreadable)")
    except Exception as e:
        print(f"   waterlog_periods: {e}")

    conn.close()

    # ── Summary ──
    print(f"\n{'='*70}")
    print(f"EXPORT COMPLETE — {len(client_rows)} clients")
    print(f"  Main CSV:    {EXPORT_CSV}")
    print(f"  Notes:       {EXPORT_NOTES}")
    print(f"  Watermarks:  {EXPORT_WATERMARKS}")
    print(f"  Periods:     {EXPORT_PERIODS}")
    print(f"{'='*70}")
    return True


# ═══════════════════════════════════════════════════════════════
#  IMPORT
# ═══════════════════════════════════════════════════════════════

def import_clients(dry_run=True, client_filter=None):
    """Import clients from CSV back into dashboard.db."""
    print(f"\n{'='*70}")
    print(f"IMPORTING to: {DB_PATH}")
    print(f"Mode: {'DRY RUN' if dry_run else 'EXECUTE'}")
    if client_filter:
        print(f"Filter: {client_filter}")
    print(f"{'='*70}")

    if not os.path.exists(EXPORT_CSV):
        print(f"ERROR: No export CSV found at {EXPORT_CSV}")
        print(f"  Run: python3 _export_import_clients.py   (to export first)")
        return False

    # Read the CSV
    print(f"\n1. Reading {EXPORT_CSV}...")
    clients = []
    with open(EXPORT_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if client_filter and row['client_id'] != client_filter:
                continue
            clients.append(row)
    print(f"   {len(clients)} clients to import")

    if not clients:
        print("   No matching clients found in CSV")
        return False

    # Read notes CSV
    notes_by_client = {}
    if os.path.exists(EXPORT_NOTES):
        with open(EXPORT_NOTES, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                cid = row.get('client_id', '')
                if client_filter and cid != client_filter:
                    continue
                notes_by_client.setdefault(cid, []).append(row)
        print(f"   {sum(len(v) for v in notes_by_client.values())} notes loaded")

    # Read watermarks CSV
    watermarks_by_client = {}
    if os.path.exists(EXPORT_WATERMARKS):
        with open(EXPORT_WATERMARKS, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                cid = row.get('client_id', '')
                if client_filter and cid != client_filter:
                    continue
                watermarks_by_client.setdefault(cid, []).append(row)
        print(f"   {sum(len(v) for v in watermarks_by_client.values())} watermarks loaded")

    # Read periods CSV
    periods_by_client = {}
    if os.path.exists(EXPORT_PERIODS):
        with open(EXPORT_PERIODS, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                cid = row.get('client_id', '')
                if client_filter and cid != client_filter:
                    continue
                periods_by_client.setdefault(cid, []).append(row)
        print(f"   {sum(len(v) for v in periods_by_client.values())} periods loaded")

    if dry_run:
        print(f"\n2. DRY RUN — showing what would be imported:\n")
        for c in clients:
            cid = c['client_id']
            evals = json.loads(c.get('evaluations', '[]'))
            identity = json.loads(c.get('identity', '{}'))
            sheet = identity.get('sheet_url', 'none')[:60] if isinstance(identity, dict) else 'none'
            n_notes = len(notes_by_client.get(cid, []))
            n_wm = len(watermarks_by_client.get(cid, []))
            n_per = len(periods_by_client.get(cid, []))
            print(f"  {cid}: {len(evals)} evals, {n_notes} notes, {n_wm} watermarks, {n_per} periods | sheet={sheet}")
        print(f"\n  To execute: python3 _export_import_clients.py --import --execute")
        return True

    # ── Actually import ──
    from dashboard.database import save_client_data_with_history
    from dashboard.notes_service import save_client_note
    from dashboard.watermark_service import bulk_save_history, save_waterlog_periods

    print(f"\n2. Importing {len(clients)} clients...")
    ok_count = 0
    fail_count = 0

    for c in clients:
        cid = c['client_id']
        try:
            # Parse JSON fields
            client_data = {}
            for col in JSON_COLUMNS:
                raw = c.get(col, '{}' if col in ('account','statistics','dropdown_options','identity','payment_address') else '[]')
                try:
                    client_data[col] = json.loads(raw) if raw else ([] if col.endswith('s') or col in ('deals','positions','hedge_accounts','prop_accounts','vps_accounts','payment_info') else {})
                except json.JSONDecodeError:
                    client_data[col] = [] if col.endswith('s') or col in ('deals','positions','hedge_accounts','prop_accounts','vps_accounts','payment_info') else {}

            # Preserve sheet_url at top level (reimport_all_sheets.py pattern)
            identity = client_data.get('identity', {})
            if isinstance(identity, dict) and identity.get('sheet_url'):
                client_data['sheet_url'] = identity['sheet_url']

            n_evals = len(client_data.get('evaluations', []))

            # Save with history
            success, version = save_client_data_with_history(
                cid,
                client_data,
                action='CSV_REIMPORT',
                changed_by='export_import_script',
                changed_by_type='super_admin',
                ip_address='127.0.0.1',
                change_source='_export_import_clients.py',
                change_description=f"Reimported from CSV export ({n_evals} evaluations)",
                overwrite=True
            )

            # Import cell notes
            n_notes = 0
            for note in notes_by_client.get(cid, []):
                try:
                    save_client_note(
                        cid,
                        int(note['row_index']),
                        note['column_key'],
                        note.get('note_content', ''),
                        note.get('created_by', 'csv_reimport')
                    )
                    n_notes += 1
                except Exception:
                    pass

            # Import watermarks
            wm_list = watermarks_by_client.get(cid, [])
            if wm_list:
                wm_data = {}
                for wm in wm_list:
                    date = wm.get('date', '')
                    try:
                        val = float(wm.get('net_profit_complete', 0))
                    except:
                        val = 0.0
                    if date:
                        wm_data[date] = val
                if wm_data:
                    bulk_save_history(cid, wm_data)

            # Import waterlog periods
            per_list = periods_by_client.get(cid, [])
            if per_list:
                period_tuples = []
                period_values = {}
                for p in per_list:
                    fd = p.get('from_date', '')
                    td = p.get('to_date', '')
                    if fd and td:
                        period_tuples.append((fd, td))
                        try:
                            low = float(p['period_low']) if p.get('period_low') not in (None, '', 'None') else None
                            high = float(p['period_high']) if p.get('period_high') not in (None, '', 'None') else None
                            split = int(p.get('split_pct', 50)) if p.get('split_pct') not in (None, '', 'None') else 50
                        except:
                            low, high, split = None, None, 50
                        if low is not None or high is not None:
                            period_values[fd] = {'low': low, 'high': high, 'split_pct': split}
                if period_tuples:
                    save_waterlog_periods(cid, period_tuples,
                                          period_values=period_values if period_values else None)

            if success:
                ok_count += 1
                print(f"  OK  {cid}: {n_evals} evals, {n_notes} notes, {len(wm_list)} wm, {len(per_list)} periods (v{version})")
            else:
                fail_count += 1
                print(f"  FAIL {cid}: save returned False")

        except Exception as e:
            fail_count += 1
            print(f"  FAIL {cid}: {e}")

    print(f"\n{'='*70}")
    print(f"IMPORT COMPLETE — {ok_count} ok, {fail_count} failed")
    print(f"{'='*70}")
    return fail_count == 0


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Export/import all clients to/from CSV')
    parser.add_argument('--source', default=None, help='Path to source DB (default: auto-detect best .corrupt file)')
    parser.add_argument('--import', dest='do_import', action='store_true', help='Import from CSV into dashboard.db')
    parser.add_argument('--execute', action='store_true', help='Actually write (default is dry-run)')
    parser.add_argument('--client', default=None, help='Filter to a single client')
    args = parser.parse_args()

    if args.do_import:
        return import_clients(dry_run=not args.execute, client_filter=args.client)
    else:
        # Export mode
        if args.source:
            source = args.source
        else:
            print("Scanning for database files...")
            source = find_best_source()
        if not source:
            return False
        return export_clients(source)


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
