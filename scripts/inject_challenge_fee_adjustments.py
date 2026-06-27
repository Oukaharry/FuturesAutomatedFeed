#!/usr/bin/env python3
"""
Apply manual challenge-fee reductions for clients where prop-firm billing
could not be reconciled automatically.

Updates statistics.profitability_completed.challenge_fees and
statistics.cashflow_inprogress.challenge_fees, then recomputes net_profit
(payouts + hedging + farming - challenge_fees + discrepancy).

Dry-run by default. Pass --apply to write to the database (creates history snapshot).

Presets (client-reported discrepancies):
  Glen Quebec  — reduce challenge fees by $4,460
  Matt Runge   — reduce challenge fees by $1,700

Usage:
  python scripts/inject_challenge_fee_adjustments.py --presets
  python scripts/inject_challenge_fee_adjustments.py --presets --apply
  python scripts/inject_challenge_fee_adjustments.py --client "Glen Quebec" --reduce 4460 --apply
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.data_processor import apply_discrepancy_to_net_profit

# Client-reported fee gaps: recorded OPSS fees higher than actual prop-firm billing.
PRESETS = {
    'Glen Quebec': {
        'reduce_by': 4460.0,
        'note': 'Topstep / Tradeify / Alpha Futures billing reconciliation (−$4,460)',
    },
    'Matt Runge': {
        'reduce_by': 1700.0,
        'note': 'Client-reported fee reconciliation (−$1,700)',
    },
}


def _to_float(v: Any) -> float:
    try:
        return float(str(v).replace('$', '').replace(',', '').strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _backup_path(client_id: str, out_dir: str) -> str:
    safe = ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in (client_id or 'client'))
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(out_dir, f'_backup_{safe}_fee_adjust_{ts}.json')


def _section_summary(stats: dict, section: str) -> dict:
    sec = (stats or {}).get(section) or {}
    hr = (stats or {}).get('hedging_review') or {}
    disc = _to_float(hr.get('discrepancy'))
    hedge_ui = _to_float(sec.get('hedging_results')) + _to_float(sec.get('farming_results')) + disc
    return {
        'payouts': round(_to_float(sec.get('payouts')), 2),
        'hedging_ui': round(hedge_ui, 2),
        'challenge_fees': round(_to_float(sec.get('challenge_fees')), 2),
        'net_profit': round(_to_float(sec.get('net_profit')), 2),
    }


def apply_fee_reduction(data: dict, reduce_by: float, note: str) -> dict:
    if reduce_by <= 0:
        raise ValueError('reduce_by must be positive')

    out = copy.deepcopy(data)
    stats = out.setdefault('statistics', {})
    adjustments = stats.setdefault('manual_fee_adjustments', [])

    before = {
        'profitability_completed': _section_summary(stats, 'profitability_completed'),
        'cashflow_inprogress': _section_summary(stats, 'cashflow_inprogress'),
    }

    for section in ('profitability_completed', 'cashflow_inprogress'):
        sec = stats.setdefault(section, {})
        old_fees = _to_float(sec.get('challenge_fees'))
        new_fees = round(max(0.0, old_fees - reduce_by), 2)
        sec['challenge_fees'] = new_fees

    apply_discrepancy_to_net_profit(stats)

    after = {
        'profitability_completed': _section_summary(stats, 'profitability_completed'),
        'cashflow_inprogress': _section_summary(stats, 'cashflow_inprogress'),
    }

    adjustments.append({
        'at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'reduce_challenge_fees_by': round(reduce_by, 2),
        'note': note,
        'before': before,
        'after': after,
    })

    return out


def _print_client_report(client_id: str, reduce_by: float, note: str, before: dict, after: dict):
    print(f'\n{"=" * 60}')
    print(f'Client: {client_id}')
    print(f'Adjustment: −${reduce_by:,.2f} from challenge_fees (both sections)')
    print(f'Note: {note}')
    print(f'{"=" * 60}')
    for section, label in (
        ('cashflow_inprogress', 'Net Profit In Progress'),
        ('profitability_completed', 'Profitability – Completed'),
    ):
        b = before[section]
        a = after[section]
        print(f'\n{label}:')
        print(f'  {"":18} {"Before":>14} {"After":>14}')
        print(f'  {"Payouts":18} {b["payouts"]:>14,.2f} {a["payouts"]:>14,.2f}')
        print(f'  {"Hedging (UI)":18} {b["hedging_ui"]:>14,.2f} {a["hedging_ui"]:>14,.2f}')
        print(f'  {"Challenge fees":18} {b["challenge_fees"]:>14,.2f} {a["challenge_fees"]:>14,.2f}')
        print(f'  {"Net profit":18} {b["net_profit"]:>14,.2f} {a["net_profit"]:>14,.2f}')


def process_client(client_id: str, reduce_by: float, note: str, apply: bool, backup_dir: str) -> bool:
    from dashboard.database import get_client_data, save_client_data_with_history

    data = get_client_data(client_id)
    if not data:
        print(f'ERROR: Client not found: {client_id}', file=sys.stderr)
        return False

    stats = data.get('statistics') or {}
    before = {
        'profitability_completed': _section_summary(stats, 'profitability_completed'),
        'cashflow_inprogress': _section_summary(stats, 'cashflow_inprogress'),
    }
    updated = apply_fee_reduction(data, reduce_by, note)
    after = {
        'profitability_completed': _section_summary(updated['statistics'], 'profitability_completed'),
        'cashflow_inprogress': _section_summary(updated['statistics'], 'cashflow_inprogress'),
    }

    _print_client_report(client_id, reduce_by, note, before, after)

    if not apply:
        print('\n  [dry-run] No changes written. Re-run with --apply to persist.')
        return True

    os.makedirs(backup_dir, exist_ok=True)
    backup_file = _backup_path(client_id, backup_dir)
    with open(backup_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, default=str)
    print(f'\n  Backup: {backup_file}')

    ok, version = save_client_data_with_history(
        client_id,
        updated,
        action='FEE_ADJUSTMENT',
        changed_by='inject_challenge_fee_adjustments.py',
        changed_by_type='script',
        change_source='scripts/inject_challenge_fee_adjustments.py',
        change_description=f'Reduced challenge_fees by ${reduce_by:,.2f}: {note}',
        overwrite=True,
    )
    if ok:
        print(f'  Saved {client_id} (history v{version})')
        return True

    print(f'  ERROR: Failed to save {client_id}', file=sys.stderr)
    return False


def main():
    parser = argparse.ArgumentParser(description='Inject manual challenge fee reductions.')
    parser.add_argument('--presets', action='store_true', help='Run Glen Quebec + Matt Runge presets')
    parser.add_argument('--client', help='Single client_id')
    parser.add_argument('--reduce', type=float, help='Amount to subtract from challenge_fees')
    parser.add_argument('--note', default='Manual fee adjustment', help='Audit note')
    parser.add_argument('--apply', action='store_true', help='Write changes (default: dry-run)')
    parser.add_argument('--backup-dir', default=os.path.join(ROOT, 'pg_backups'), help='Backup JSON directory')
    args = parser.parse_args()

    jobs = []
    if args.presets:
        for cid, cfg in PRESETS.items():
            jobs.append((cid, cfg['reduce_by'], cfg['note']))
    elif args.client and args.reduce:
        jobs.append((args.client, args.reduce, args.note))
    else:
        parser.error('Use --presets or both --client and --reduce')

    if not args.apply:
        print('DRY RUN — pass --apply to persist to the database\n')

    ok_all = True
    for client_id, reduce_by, note in jobs:
        if not process_client(client_id, reduce_by, note, args.apply, args.backup_dir):
            ok_all = False

    sys.exit(0 if ok_all else 1)


if __name__ == '__main__':
    main()
