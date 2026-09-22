"""Repair farming rows corrupted before the Prop Day slot fix.

Three defects are undone:

  1. A Prop Day / Prop Progress recorded against the slot holding a PAYOUT
     prompt. That is the phantom second cycle.
  2. A weekday placeholder queued while a payout is still outstanding, which
     would trade an account that is meant to be paused.
  3. A payout prompt cleared by hand without restarting the cycle counter,
     which makes the next cycle count from slot 1 and report the wrong day.

The fixed pipeline prevents all three, but it cannot undo them: a row with a
pending payout now returns before touching anything, so it would stay broken
forever. Run this once per environment after deploying.

Dry run by default. Pass --apply to write.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.database import (  # noqa: E402
    get_all_clients,
    get_client_data,
    save_client_data_with_history,
)

WEEKDAYS = ('MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY')
MAX_SLOT = 61


def _cell(row, key):
    return str(row.get(key) or '').strip()


def _pending_payout_slot(row):
    for slot in range(1, MAX_SLOT):
        if _cell(row, f'Hedge Day {slot}').upper() == 'PAYOUT':
            return slot
    return None


def repair_row(row):
    """Apply the three repairs in place and return what changed."""
    changes = []
    payout_slot = _pending_payout_slot(row)

    if payout_slot is not None:
        for key in (f'Prop Day {payout_slot}',
                    f'Prop Progress {payout_slot}',
                    f'_Prop Day {payout_slot} Date'):
            if _cell(row, key):
                changes.append(f'cleared {key} = {row.get(key)!r}')
                row.pop(key, None)
        for slot in range(1, MAX_SLOT):
            if slot == payout_slot:
                continue
            key = f'Hedge Day {slot}'
            if _cell(row, key).upper() in WEEKDAYS:
                changes.append(f'cleared {key} = {row.get(key)!r} (payout pending)')
                row[key] = ''

    for slot in range(1, MAX_SLOT):
        anchor = f'_Hedge Day {slot} Payout Due'
        if anchor not in row:
            continue
        if _cell(row, f'Hedge Day {slot}').upper() == 'PAYOUT':
            continue
        # The prompt was deleted by hand, so this slot opens the new cycle.
        if str(row.get('_Farming Cycle Start') or '') != str(slot):
            changes.append(
                f'_Farming Cycle Start {row.get("_Farming Cycle Start")!r} -> {slot}')
            row['_Farming Cycle Start'] = slot
        changes.append(f'dropped stale {anchor} = {row.get(anchor)!r}')
        row.pop(anchor, None)

    return changes


def _label(row, idx):
    return (f'[{idx}] {row.get("Prop Firm") or "?"} '
            f'ch={row.get("Account #") or "-"} fu={row.get("Account #.1") or "-"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', help='only this client id')
    parser.add_argument('--account', help='only rows whose account ends with this')
    parser.add_argument('--apply', action='store_true', help='write changes')
    args = parser.parse_args()

    if args.client:
        clients = {args.client: get_client_data(args.client)}
    else:
        clients = get_all_clients()

    total_rows = 0
    for client_id, data in (clients or {}).items():
        if not data:
            continue
        evaluations = data.get('evaluations') or []
        touched = []
        for idx, row in enumerate(evaluations):
            if not isinstance(row, dict) or row.get('_deleted'):
                continue
            if args.account:
                joined = f'{row.get("Account #") or ""}{row.get("Account #.1") or ""}'
                if not joined.endswith(args.account):
                    continue
            changes = repair_row(row)
            if changes:
                touched.append((idx, row, changes))

        if not touched:
            continue
        print(f'\n=== {client_id} ===')
        for idx, row, changes in touched:
            print(f'  {_label(row, idx)}')
            for change in changes:
                print(f'      - {change}')
            total_rows += 1

        if args.apply:
            data['evaluations'] = evaluations
            save_client_data_with_history(
                client_id, data,
                changed_by='repair_farming_payout_rows',
                change_source='maintenance',
                change_description='Repair farming rows corrupted before the Prop Day slot fix',
            )
            print(f'  -> saved {client_id}')

    print(f'\n{total_rows} row(s) {"repaired" if args.apply else "would be repaired"}')
    if total_rows and not args.apply:
        print('Re-run with --apply to write.')


if __name__ == '__main__':
    main()
