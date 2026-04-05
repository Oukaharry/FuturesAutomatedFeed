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


def find_best_source(report_fn=print):
    """Find the best database to export from — prefer .corrupt files with the most clients."""
    db_dir = os.path.dirname(DB_PATH)
    db_name = os.path.basename(DB_PATH)

    if not os.path.isdir(db_dir):
        report_fn(f"ERROR: Directory {db_dir} not found")
        return None

    candidates = []

    # Check all .corrupt* files
    for f in sorted(os.listdir(db_dir)):
        if not f.startswith(db_name):
            continue
        if f.endswith('-wal') or f.endswith('-shm'):
            continue
        fpath = os.path.join(db_dir, f)
        if not os.path.isfile(fpath):
            continue

        size_mb = os.path.getsize(fpath) / 1024 / 1024
        info = {'path': fpath, 'name': f, 'size_mb': size_mb, 'clients': -1, 'readable': False}

        try:
            conn = safe_connect(fpath, readonly=True)
            info['clients'] = conn.execute('SELECT COUNT(*) FROM clients_data').fetchone()[0]
            info['readable'] = True
            conn.close()
        except:
            pass

        candidates.append(info)
        status = f"{info['clients']} clients" if info['readable'] else "UNREADABLE"
        report_fn(f"  {f}: {size_mb:.1f} MB, {status}")

    if not candidates:
        report_fn("No database files found!")
        return None

    # Sort: most clients wins, then largest file
    candidates.sort(key=lambda x: (x['readable'], x['clients'], x['size_mb']), reverse=True)
    best = candidates[0]

    if not best['readable'] or best['clients'] <= 0:
        report_fn(f"ERROR: No readable database with client data found")
        return None

    report_fn(f"\n  BEST: {best['name']} ({best['clients']} clients, {best['size_mb']:.1f} MB)")
    return best['path']


# ═══════════════════════════════════════════════════════════════
#  EXPORT
# ═══════════════════════════════════════════════════════════════

def export_clients(source_path):
    """Export all client data from source DB to CSV files."""
    print(f"\n{'='*70}")
    print(f"EXPORTING from: {source_path}")
    print(f"{'='*70}")

    conn = safe_connect(source_path, readonly=True)

    # ── 1. Export clients_data ──
    print(f"\n1. Exporting clients_data...")
    rows = conn.execute('SELECT * FROM clients_data ORDER BY client_id').fetchall()
    cols = [desc[0] for desc in conn.execute('SELECT * FROM clients_data LIMIT 1').description]

    os.makedirs(EXPORT_DIR, exist_ok=True)

    with open(EXPORT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=ALL_COLUMNS, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            row_dict = {}
            for col in ALL_COLUMNS:
                val = row[col] if col in cols else None
                if col in JSON_COLUMNS:
                    # Store JSON as-is (it's already a JSON string in the DB)
                    row_dict[col] = val if val else ('[]' if col.endswith('s') or col in ('deals','positions','hedge_accounts','prop_accounts','vps_accounts','payment_info') else '{}')
                else:
                    row_dict[col] = val
            writer.writerow(row_dict)

    print(f"   {len(rows)} clients -> {EXPORT_CSV}")

    # ── 2. Export cell_notes ──
    print(f"\n2. Exporting cell_notes...")
    try:
        notes = conn.execute('SELECT * FROM cell_notes ORDER BY client_id, row_index, column_key').fetchall()
        note_cols = [desc[0] for desc in conn.execute('SELECT * FROM cell_notes LIMIT 1').description] if notes else []
        if notes and note_cols:
            with open(EXPORT_NOTES, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=note_cols)
                writer.writeheader()
                for n in notes:
                    writer.writerow({c: n[c] for c in note_cols})
            print(f"   {len(notes)} notes -> {EXPORT_NOTES}")
        else:
            print(f"   0 notes (table empty)")
    except Exception as e:
        print(f"   cell_notes: {e}")

    # ── 3. Export daily_watermarks ──
    print(f"\n3. Exporting daily_watermarks...")
    try:
        wm = conn.execute('SELECT * FROM daily_watermarks ORDER BY client_id, date').fetchall()
        wm_cols = [desc[0] for desc in conn.execute('SELECT * FROM daily_watermarks LIMIT 1').description] if wm else []
        if wm and wm_cols:
            with open(EXPORT_WATERMARKS, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=wm_cols)
                writer.writeheader()
                for w in wm:
                    writer.writerow({c: w[c] for c in wm_cols})
            print(f"   {len(wm)} watermarks -> {EXPORT_WATERMARKS}")
        else:
            print(f"   0 watermarks (table empty)")
    except Exception as e:
        print(f"   daily_watermarks: {e}")

    # ── 4. Export waterlog_periods ──
    print(f"\n4. Exporting waterlog_periods...")
    try:
        wp = conn.execute('SELECT * FROM waterlog_periods ORDER BY client_id, from_date').fetchall()
        wp_cols = [desc[0] for desc in conn.execute('SELECT * FROM waterlog_periods LIMIT 1').description] if wp else []
        if wp and wp_cols:
            with open(EXPORT_PERIODS, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=wp_cols)
                writer.writeheader()
                for p in wp:
                    writer.writerow({c: p[c] for c in wp_cols})
            print(f"   {len(wp)} periods -> {EXPORT_PERIODS}")
        else:
            print(f"   0 periods (table empty)")
    except Exception as e:
        print(f"   waterlog_periods: {e}")

    conn.close()

    # ── Summary ──
    print(f"\n{'='*70}")
    print(f"EXPORT COMPLETE — {len(rows)} clients")
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
