"""
Normalize all date fields across the entire database.
Converts every parseable date to a consistent MM/DD/YYYY format.

Usage:
  python normalize_dates.py --dry-run    # Preview changes (default)
  python normalize_dates.py --apply      # Actually write changes to DB
"""
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.database import get_client_data, save_client_data, get_connection
from config.hierarchy import get_all_clients

# ── Date parser (same logic as app.py) ────────────────────────

def parse_date(val):
    """Parse a date string, return datetime object or None."""
    if not val:
        return None
    val = str(val).strip().rstrip('.')
    if not val or len(val) < 3:
        return None
    if val[0].isalpha() and '/' not in val and '-' not in val:
        return None

    normalized = val.replace('.', '/').replace('//', '/')
    while normalized and not normalized[0].isdigit():
        normalized = normalized[1:]
    if not normalized:
        return None

    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%m-%d-%Y', '%m-%d-%y',
                '%b %d, %Y', '%B %d, %Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue

    # M/D (no year)
    parts = normalized.split('/')
    if len(parts) == 2:
        try:
            month, day = int(parts[0]), int(parts[1])
            if 1 <= month <= 12 and 1 <= day <= 31:
                now = datetime.now()
                candidate = datetime(now.year, month, day)
                if candidate > now:
                    candidate = datetime(now.year - 1, month, day)
                return candidate
        except (ValueError, TypeError):
            pass

    return None


def normalize_date(val):
    """Convert any date string to MM/DD/YYYY. Returns original if unparseable."""
    dt = parse_date(val)
    if dt:
        return dt.strftime('%m/%d/%Y')
    return val  # Return original if can't parse


# ── Date field names to normalize ─────────────────────────────

DATE_FIELDS = [
    'Date Purchased', 'Date Started', 'Date Ended',
    'Date Started.1', 'Date Ended.1',
    'Date 1', 'Date 2', 'Date 3', 'Date 4',
    'Payout Date',
]

def is_farming_date_key(key):
    """Check if key is a farming progress date column."""
    k = str(key)
    return ('Prop Day' in k or 'Hedge Day' in k) and not k.startswith('_')


# ── Main ──────────────────────────────────────────────────────

def main():
    dry_run = '--apply' not in sys.argv

    if dry_run:
        print("=" * 70)
        print("  DRY RUN — No changes will be written")
        print("  Run with --apply to write changes to the database")
        print("=" * 70)
    else:
        print("=" * 70)
        print("  APPLYING CHANGES to the database")
        print("=" * 70)

    all_clients = get_all_clients()
    print(f"\nScanning {len(all_clients)} clients...\n")

    total_fixed = 0
    total_already_ok = 0
    total_unparseable = 0
    clients_modified = 0
    unparseable_samples = []

    for client_name in sorted(all_clients):
        data = get_client_data(client_name)
        if not data:
            continue

        evaluations = data.get('evaluations', [])
        if not evaluations:
            continue

        client_fixes = 0
        modified = False

        for idx, ev in enumerate(evaluations):
            if ev.get('_deleted'):
                continue

            # Check standard date fields
            for field in DATE_FIELDS:
                old_val = str(ev.get(field, '') or '').strip()
                if not old_val:
                    continue

                new_val = normalize_date(old_val)
                if new_val != old_val:
                    dt = parse_date(old_val)
                    if dt:
                        ev[field] = new_val
                        client_fixes += 1
                        modified = True
                    else:
                        total_unparseable += 1
                        if len(unparseable_samples) < 20:
                            unparseable_samples.append((client_name, idx + 1, field, old_val))
                else:
                    # Check if already in MM/DD/YYYY format
                    if parse_date(old_val):
                        total_already_ok += 1

            # Check farming progress date columns
            for key in list(ev.keys()):
                if not is_farming_date_key(key):
                    continue
                old_val = str(ev.get(key, '') or '').strip()
                if not old_val:
                    continue

                new_val = normalize_date(old_val)
                if new_val != old_val:
                    dt = parse_date(old_val)
                    if dt:
                        ev[key] = new_val
                        client_fixes += 1
                        modified = True
                    else:
                        total_unparseable += 1
                        if len(unparseable_samples) < 20:
                            unparseable_samples.append((client_name, idx + 1, key, old_val))
                else:
                    if parse_date(old_val):
                        total_already_ok += 1

        if client_fixes > 0:
            total_fixed += client_fixes
            clients_modified += 1
            print(f"  {client_name}: {client_fixes} dates normalized")

            if not dry_run:
                save_client_data(client_name, {'evaluations': evaluations}, overwrite=False)

    # Summary
    print("\n" + "=" * 70)
    print(f"  SUMMARY")
    print(f"  Clients scanned:    {len(all_clients)}")
    print(f"  Clients modified:   {clients_modified}")
    print(f"  Dates normalized:   {total_fixed}")
    print(f"  Already correct:    {total_already_ok}")
    print(f"  Unparseable:        {total_unparseable}")
    print("=" * 70)

    if unparseable_samples:
        print(f"\n  Unparseable date samples (first {len(unparseable_samples)}):")
        for client, row, field, val in unparseable_samples:
            print(f"    {client} Row {row} [{field}]: '{val}'")

    if dry_run and total_fixed > 0:
        print(f"\n  Run with --apply to write these {total_fixed} changes to the database.")
    elif not dry_run and total_fixed > 0:
        print(f"\n  Done! {total_fixed} dates normalized across {clients_modified} clients.")
    else:
        print(f"\n  All dates are already in the correct format.")


if __name__ == '__main__':
    main()
