#!/usr/bin/env python3
"""
View a single client's full evaluation data — exactly as the CSV download.

Usage (on PythonAnywhere):
    python3 _view_client.py "Chris Ream"
    python3 _view_client.py "Chris Ream" --csv          # save CSV only
    python3 _view_client.py "Chris Ream" --rows 1-20    # show display rows 1-20
    python3 _view_client.py "Chris Ream" --cols "Account #,Prop Firm,Account Size,Status"
    python3 _view_client.py "Chris Ream" --empty         # highlight rows missing key fields
    python3 _view_client.py "Chris Ream" --search AFAD   # show only rows matching a term

Outputs:
  1. Terminal table (with row numbers matching the dashboard)
  2. CSV file: _export_<ClientName>.csv (auto-saved)
"""
import sqlite3
import json
import csv
import os
import sys
import re
import argparse
from collections import OrderedDict

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')

# Dashboard column order — matches the HTML template exactly
# EVAL INFO → EVAL PHASE → FUNDED PHASE → FARMING PHASE
DASHBOARD_COLUMN_ORDER = [
    # ── EVAL INFO ──
    'Prop Firm', 'Account Size', 'Date Purchased', 'Fee',
    # ── EVAL PHASE ──
    'Date Started', 'Date Ended', 'Status P1', 'Account #',
    'Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
    'Hedge Result 4', 'Hedge Result 5', 'Hedge Net',
    # ── FUNDED PHASE ──
    'Account #.1', 'Activation Fee', 'Date Started.1', 'Date Ended.1', 'Status',
    'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
    'Hedge Result 4.1', 'Hedge Result 5.1',
    'Hedge Result 6', 'Hedge Result 7', 'Hedge Net.1',
    'Payout 1', 'Date 1', 'Payout 2', 'Date 2',
    'Payout 3', 'Date 3', 'Payout 4', 'Date 4',
    'Payout 5', 'Date 5', 'Payout 6', 'Date 6',
    'Payout 7', 'Date 7', 'Payout 8', 'Date 8',
    # ── FARMING PHASE ──
] + [f'Prop Day {i}' for i in range(1, 61)] \
  + [f'Prop Progress {i}' for i in range(1, 61)] \
  + [f'Hedge Day {i}' for i in range(1, 61)]

# Key columns for default terminal display (subset — skip farming bulk)
KEY_COLUMNS = [
    'Account #', 'Account #.1', 'Prop Firm', 'Account Size',
    'Status', 'Status P1',
    'Date Started', 'Date Ended', 'Date Started.1', 'Date Ended.1',
    'Date Purchased',
    'Payout 1', 'Date 1', 'Payout 2', 'Date 2', 'Payout 3', 'Date 3',
    'Payout 4', 'Date 4', 'Payout 5', 'Date 5', 'Payout 6', 'Date 6',
    'Payout 7', 'Date 7', 'Payout 8', 'Date 8',
    'Fee', 'Activation Fee',
]

# Columns critical for our recovery — highlight if empty
CRITICAL_COLUMNS = ['Account #', 'Account #.1', 'Prop Firm', 'Account Size']


def load_client(client_id):
    """Load evaluations from DB."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        row = conn.execute(
            "SELECT evaluations, statistics FROM clients_data WHERE client_id=?",
            (client_id,)
        ).fetchone()
    except sqlite3.DatabaseError as e:
        # Try with recovery pragmas
        conn.close()
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA ignore_check_constraints=ON")
        row = conn.execute(
            "SELECT evaluations, statistics FROM clients_data WHERE client_id=?",
            (client_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None, None

    evals = json.loads(row[0])
    stats = json.loads(row[1]) if row[1] else {}
    return evals, stats


def build_columns(evals):
    """Build column list matching dashboard order, then any extras."""
    # Collect all keys present in any eval (skip internal _ keys and legacy 'Account Number')
    all_keys = set()
    for ev in evals:
        all_keys.update(k for k in ev if not k.startswith('_') and k != 'Account Number')

    seen = set()
    columns = []
    # Dashboard-ordered columns first
    for col in DASHBOARD_COLUMN_ORDER:
        if col in all_keys and col not in seen:
            seen.add(col)
            columns.append(col)
    # Then any remaining columns not in the dashboard order (in discovery order)
    for ev in evals:
        for key in ev:
            if key not in seen and not key.startswith('_') and key != 'Account Number':
                seen.add(key)
                columns.append(key)
    return columns


def build_display_rows(evals):
    """
    Build visible rows with display numbers matching the dashboard.
    Dashboard shows newest first: display #1 = most recent row.
    Returns list of (display_num, db_index, eval_dict).
    """
    visible = [(i, ev) for i, ev in enumerate(evals) if not ev.get('_deleted')]
    visible.sort(key=lambda x: x[0], reverse=True)
    total = len(visible)
    rows = []
    for rank, (db_idx, ev) in enumerate(visible):
        display_num = total - rank
        rows.append((display_num, db_idx, ev))
    return rows


def truncate(val, maxlen=25):
    """Truncate a string for terminal display."""
    s = str(val).strip()
    if len(s) > maxlen:
        return s[:maxlen - 2] + '..'
    return s


def print_table(rows, columns, col_filter=None, search_term=None, row_range=None,
                show_empty=False):
    """Print a formatted terminal table."""
    # Apply filters
    filtered = rows
    if row_range:
        lo, hi = row_range
        filtered = [(d, i, ev) for d, i, ev in filtered if lo <= d <= hi]
    if search_term:
        term = search_term.lower()
        filtered = [(d, i, ev) for d, i, ev in filtered
                     if any(term in str(v).lower() for v in ev.values())]
    if show_empty:
        filtered = [(d, i, ev) for d, i, ev in filtered
                     if any(not str(ev.get(c, '')).strip() for c in CRITICAL_COLUMNS)]

    if col_filter:
        display_cols = [c for c in col_filter if c in columns]
        # Also include any col_filter items not found (show as missing)
        for c in col_filter:
            if c not in display_cols:
                display_cols.append(c)
    else:
        display_cols = columns

    if not filtered:
        print("  (no rows match filters)")
        return

    # Calculate widths
    max_widths = {'#': 4}
    for col in display_cols:
        header_len = len(col)
        max_val = max((len(truncate(ev.get(col, ''))) for _, _, ev in filtered), default=0)
        max_widths[col] = min(max(header_len, max_val, 3), 28)

    # Print header
    header = f"{'#':>4} | " + ' | '.join(f"{col:{max_widths[col]}s}" for col in display_cols)
    sep = '-' * len(header)
    print(sep)
    print(header)
    print(sep)

    # Print rows (display_num descending = newest first)
    for display_num, db_idx, ev in filtered:
        vals = []
        for col in display_cols:
            v = truncate(ev.get(col, ''))
            # Highlight missing critical fields
            if show_empty and col in CRITICAL_COLUMNS and not v:
                v = '<<<EMPTY>>>'
            vals.append(f"{v:{max_widths[col]}s}")
        print(f"{display_num:>4} | " + ' | '.join(vals))

    print(sep)
    print(f"  Showing {len(filtered)} of {len(rows)} visible rows")


def save_csv(client_id, rows, columns, stats):
    """Save CSV matching the dashboard download format."""
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', client_id)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'_export_{safe}.csv')

    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        # Write in DB order (same as dashboard export — oldest first)
        sorted_rows = sorted(rows, key=lambda x: x[1])  # sort by db_index
        for display_num, db_idx, ev in sorted_rows:
            writer.writerow([ev.get(col, '') for col in columns])

        # Statistics section
        if stats:
            writer.writerow([])
            writer.writerow(['--- Statistics ---'])
            for key, val in stats.items():
                if isinstance(val, dict):
                    for k2, v2 in val.items():
                        writer.writerow([f'{key}.{k2}', v2])
                else:
                    writer.writerow([key, val])

    return path


def print_summary(client_id, evals, rows, columns):
    """Print a quick summary of the client data."""
    total_evals = len(evals)
    deleted = sum(1 for ev in evals if ev.get('_deleted'))
    visible = len(rows)

    # Count empties for critical columns
    empty_counts = {}
    for col in CRITICAL_COLUMNS:
        if col in columns:
            empty = sum(1 for _, _, ev in rows if not str(ev.get(col, '')).strip())
            empty_counts[col] = empty

    # Count firms
    firms = {}
    for _, _, ev in rows:
        f = str(ev.get('Prop Firm', '')).strip()
        if f:
            firms[f] = firms.get(f, 0) + 1

    # Count statuses
    statuses = {}
    for _, _, ev in rows:
        s = str(ev.get('Status', '')).strip() or str(ev.get('Status P1', '')).strip()
        if s:
            statuses[s] = statuses.get(s, 0) + 1

    print(f"\n{'='*60}")
    print(f"  CLIENT: {client_id}")
    print(f"{'='*60}")
    print(f"  Total eval rows: {total_evals}  (deleted: {deleted}, visible: {visible})")
    print(f"  Columns: {len(columns)}")

    if empty_counts:
        print(f"\n  Empty critical fields:")
        for col, cnt in empty_counts.items():
            pct = cnt / visible * 100 if visible else 0
            marker = ' ⚠' if cnt > 0 else ' ✓'
            print(f"    {col:20s}: {cnt:>4} / {visible} ({pct:.0f}%){marker}")

    if firms:
        print(f"\n  Prop Firms:")
        for f in sorted(firms, key=firms.get, reverse=True):
            print(f"    {f:25s}: {firms[f]}")

    if statuses:
        print(f"\n  Statuses:")
        for s in sorted(statuses, key=statuses.get, reverse=True):
            print(f"    {s:25s}: {statuses[s]}")

    print()


def main():
    parser = argparse.ArgumentParser(description='View client evaluation data')
    parser.add_argument('client_id', help='Client name (e.g. "Chris Ream")')
    parser.add_argument('--csv', action='store_true', help='Save CSV only, skip table')
    parser.add_argument('--rows', help='Display row range, e.g. 1-20 or 600-656')
    parser.add_argument('--cols', help='Comma-separated column names to display')
    parser.add_argument('--search', help='Filter rows containing this term')
    parser.add_argument('--empty', action='store_true',
                        help='Show only rows with missing critical fields')
    parser.add_argument('--all-cols', action='store_true',
                        help='Show ALL columns (wide output)')
    parser.add_argument('--head', type=int, default=0,
                        help='Show first N rows (by display number, newest first)')
    parser.add_argument('--tail', type=int, default=0,
                        help='Show last N rows (by display number, oldest)')
    args = parser.parse_args()

    # Load data
    evals, stats = load_client(args.client_id)
    if evals is None:
        print(f"ERROR: Client '{args.client_id}' not found in database.")
        clients = list_clients()
        if clients:
            # Fuzzy match suggestion
            term = args.client_id.lower()
            matches = [c for c in clients if term in c.lower()]
            if matches:
                print(f"  Did you mean: {', '.join(matches[:10])}")
            else:
                print(f"  Available clients ({len(clients)} total):")
                for c in clients[:20]:
                    print(f"    {c}")
                if len(clients) > 20:
                    print(f"    ... and {len(clients)-20} more")
        sys.exit(1)

    columns = build_columns(evals)
    rows = build_display_rows(evals)

    # Summary always
    print_summary(args.client_id, evals, rows, columns)

    # Save CSV
    csv_path = save_csv(args.client_id, rows, columns, stats)
    print(f"  CSV saved: {csv_path}")

    if args.csv:
        return

    # Parse row range
    row_range = None
    if args.rows:
        parts = args.rows.split('-')
        if len(parts) == 2:
            row_range = (int(parts[0]), int(parts[1]))
        else:
            row_range = (int(parts[0]), int(parts[0]))

    # Parse col filter
    col_filter = None
    if args.cols:
        col_filter = [c.strip() for c in args.cols.split(',')]
    elif not args.all_cols:
        # Default: show only key columns that exist
        col_filter = [c for c in KEY_COLUMNS if c in columns]

    # Head/tail
    if args.head:
        # Newest N rows
        display_nums = sorted([d for d, _, _ in rows], reverse=True)[:args.head]
        if display_nums:
            row_range = (min(display_nums), max(display_nums))
    elif args.tail:
        # Oldest N rows
        display_nums = sorted([d for d, _, _ in rows])[:args.tail]
        if display_nums:
            row_range = (min(display_nums), max(display_nums))

    # Print
    print_table(rows, columns, col_filter=col_filter, search_term=args.search,
                row_range=row_range, show_empty=args.empty)


def list_clients():
    """List all client IDs."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        rows = conn.execute("SELECT client_id FROM clients_data ORDER BY client_id").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


if __name__ == '__main__':
    main()
