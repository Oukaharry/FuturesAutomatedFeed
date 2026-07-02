#!/usr/bin/env python3
"""
Apply manual challenge-fee adjustments for clients where prop-firm billing
could not be reconciled automatically.

Stored as statistics.manual_fee_adjustments[].reduce_challenge_fees_by:
  positive = subtract from eval-derived fees (fees too high in OPSS)
  negative = add to eval-derived fees (fees too low in OPSS)

Per-prop-firm remainder (By Prop Firm fees column + matching total challenge fees):
  statistics.manual_fee_adjustments[].prop_firm_adjustments[firm] = {
    add_fees, target_fees, eval_fees
  }

Updates statistics.profitability_completed.challenge_fees and
statistics.cashflow_inprogress.challenge_fees, then recomputes net_profit.

Dry-run by default. Pass --apply to write to the database (creates history snapshot).

Usage:
  python scripts/inject_challenge_fee_adjustments.py --presets
  python scripts/inject_challenge_fee_adjustments.py --client "Matt Runge" --reduce 1700 --apply
  python scripts/inject_challenge_fee_adjustments.py --client "Matt Runge" --target-ip-fees 25100 --apply
  python scripts/inject_challenge_fee_adjustments.py --client "Matt Runge" --add 1371.88 --apply
  python scripts/inject_challenge_fee_adjustments.py --client "Anaa Cederwall" --prop-firm FundedNext --target-firm-fees 6179.06 --apply
  python scripts/inject_challenge_fee_adjustments.py --client "Anaa Cederwall" --prop-firm FundedNext --add-firm-fees 122.50 --apply
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

from utils.data_processor import (
    apply_discrepancy_to_net_profit,
    calculate_statistics,
    compute_fees_by_prop_firm,
    prop_firm_stats_parent,
)

# Legacy presets (fee reductions). Prefer --target-ip-fees for client-verified totals.
PRESETS = {
    'Glen Quebec': {
        'reduce_by': 4460.0,
        'note': 'Topstep / Tradeify / Alpha Futures billing reconciliation (−$4,460)',
    },
    'Matt Runge': {
        'target_ip_fees': 25100.0,
        'note': 'Client-verified challenge fees (in progress) = $25,100',
    },
    'Anaa Cederwall': {
        'prop_firm': 'FundedNext',
        'target_firm_fees': 6179.06,
        'note': 'FundedNext billing history total verified ($6,179.06)',
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


def eval_baseline_fees(data: dict) -> tuple[float, float]:
    """Return (cashflow_inprogress, profitability_completed) eval-derived challenge fees."""
    stats = data.get('statistics') or {}
    old_hr = stats.get('hedging_review') or {}
    base = calculate_statistics(
        data.get('evaluations') or [],
        mt5_account=data.get('account'),
        historical_accounts=old_hr.get('historical_accounts'),
    )
    ip = _to_float((base.get('cashflow_inprogress') or {}).get('challenge_fees'))
    pc = _to_float((base.get('profitability_completed') or {}).get('challenge_fees'))
    return ip, pc


def apply_fee_adjustment(
    data: dict,
    reduce_by: float,
    note: str,
    *,
    target_ip_fees: float | None = None,
    eval_ip_fees: float | None = None,
    eval_pc_fees: float | None = None,
    prop_firm_adjustments: dict | None = None,
) -> dict:
    """
    Set challenge fees using reduce_by = eval_ip_fees - target_ip_fees convention.
    Same delta is applied to both sections so recalc stays consistent.
    """
    if reduce_by == 0:
        raise ValueError('reduce_by must be non-zero')

    out = copy.deepcopy(data)
    stats = out.setdefault('statistics', {})
    adjustments = stats.setdefault('manual_fee_adjustments', [])

    if eval_ip_fees is None or eval_pc_fees is None:
        eval_ip_fees, eval_pc_fees = eval_baseline_fees(out)

    before = {
        'profitability_completed': _section_summary(stats, 'profitability_completed'),
        'cashflow_inprogress': _section_summary(stats, 'cashflow_inprogress'),
    }

    target_ip = target_ip_fees if target_ip_fees is not None else round(eval_ip_fees - reduce_by, 2)
    delta = round(target_ip - eval_ip_fees, 2)
    target_pc = round(eval_pc_fees + delta, 2)

    stats.setdefault('cashflow_inprogress', {})['challenge_fees'] = round(max(0.0, target_ip), 2)
    stats.setdefault('profitability_completed', {})['challenge_fees'] = round(max(0.0, target_pc), 2)
    apply_discrepancy_to_net_profit(stats)

    after = {
        'profitability_completed': _section_summary(stats, 'profitability_completed'),
        'cashflow_inprogress': _section_summary(stats, 'cashflow_inprogress'),
    }

    entry = {
        'at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'reduce_challenge_fees_by': round(reduce_by, 2),
        'note': note,
        'eval_ip_fees': round(eval_ip_fees, 2),
        'eval_pc_fees': round(eval_pc_fees, 2),
        'target_ip_fees': round(target_ip, 2),
        'target_pc_fees': round(target_pc, 2),
        'before': before,
        'after': after,
    }
    if prop_firm_adjustments:
        entry['prop_firm_adjustments'] = prop_firm_adjustments
    # Replace prior adjustments — targets are authoritative, not cumulative.
    stats['manual_fee_adjustments'] = [entry]

    return out


def _print_client_report(
    client_id: str,
    reduce_by: float,
    note: str,
    before: dict,
    after: dict,
    eval_ip: float,
    eval_pc: float,
):
    sign = '−' if reduce_by > 0 else '+'
    amt = abs(reduce_by)
    print(f'\n{"=" * 60}')
    print(f'Client: {client_id}')
    print(f'Eval baseline IP fees: ${eval_ip:,.2f}   PC fees: ${eval_pc:,.2f}')
    print(f'Adjustment: {sign}${amt:,.2f} from eval IP fees (reduce_by={reduce_by:,.2f})')
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


def _merge_prop_firm_adjustments(existing: dict, firm: str, blob: dict) -> dict:
    merged = dict(existing or {})
    merged[firm] = blob
    return merged


def _prop_firm_job_from_cfg(cfg: dict) -> tuple[str, float | None, float | None]:
    prop_firm = str(cfg.get('prop_firm') or '').strip()
    if not prop_firm:
        raise ValueError('prop_firm preset entry requires prop_firm')
    if cfg.get('target_firm_fees') is not None:
        return prop_firm, float(cfg['target_firm_fees']), None
    if cfg.get('add_firm_fees') is not None:
        return prop_firm, None, float(cfg['add_firm_fees'])
    raise ValueError('prop_firm preset requires target_firm_fees or add_firm_fees')


def process_prop_firm_client(
    client_id: str,
    prop_firm: str,
    note: str,
    apply: bool,
    backup_dir: str,
    *,
    target_firm_fees: float | None = None,
    add_firm_fees: float | None = None,
) -> bool:
    from dashboard.database import get_client_data, save_client_data_with_history

    data = get_client_data(client_id)
    if not data:
        print(f'ERROR: Client not found: {client_id}', file=sys.stderr)
        return False

    canon = prop_firm_stats_parent(prop_firm)
    by_firm = compute_fees_by_prop_firm(data.get('evaluations') or [])
    eval_firm = by_firm.get(canon, 0.0)
    if eval_firm <= 0 and canon not in by_firm:
        print(
            f'WARNING: No eval fees found for firm {canon!r} on {client_id}. '
            f'Known firms: {", ".join(sorted(by_firm.keys())[:12])}',
            file=sys.stderr,
        )

    if target_firm_fees is not None:
        add_firm = round(float(target_firm_fees) - eval_firm, 2)
        target_firm = round(float(target_firm_fees), 2)
    elif add_firm_fees is not None:
        add_firm = round(float(add_firm_fees), 2)
        target_firm = round(eval_firm + add_firm, 2)
    else:
        print('ERROR: target_firm_fees or add_firm_fees required', file=sys.stderr)
        return False

    if add_firm == 0:
        print(f'{client_id}: {canon} fees already ${eval_firm:,.2f} (target ${target_firm:,.2f})')
        return True

    stats = data.get('statistics') or {}
    prior = (stats.get('manual_fee_adjustments') or [])
    prior_pf = {}
    if prior and isinstance(prior[-1], dict):
        prior_pf = dict(prior[-1].get('prop_firm_adjustments') or {})

    prop_firm_adjustments = _merge_prop_firm_adjustments(
        prior_pf,
        canon,
        {
            'add_fees': add_firm,
            'target_fees': target_firm,
            'eval_fees': round(eval_firm, 2),
        },
    )
    total_add = round(
        sum(_to_float(v.get('add_fees')) for v in prop_firm_adjustments.values() if isinstance(v, dict)),
        2,
    )

    eval_ip, eval_pc = eval_baseline_fees(data)
    target_ip = round(eval_ip + total_add, 2)
    reduce_by = round(eval_ip - target_ip, 2)

    before = {
        'profitability_completed': _section_summary(stats, 'profitability_completed'),
        'cashflow_inprogress': _section_summary(stats, 'cashflow_inprogress'),
    }
    updated = apply_fee_adjustment(
        data,
        reduce_by,
        note,
        target_ip_fees=target_ip,
        eval_ip_fees=eval_ip,
        eval_pc_fees=eval_pc,
        prop_firm_adjustments=prop_firm_adjustments,
    )
    after = {
        'profitability_completed': _section_summary(updated['statistics'], 'profitability_completed'),
        'cashflow_inprogress': _section_summary(updated['statistics'], 'cashflow_inprogress'),
    }

    print(f'\n{"=" * 60}')
    print(f'Client: {client_id}')
    print(f'Prop firm: {canon}')
    print(f'Eval By-Prop-Firm fees: ${eval_firm:,.2f}  →  target ${target_firm:,.2f}  (add ${add_firm:,.2f})')
    print(f'Eval total IP fees: ${eval_ip:,.2f}  →  target ${target_ip:,.2f}')
    print(f'Note: {note}')
    _print_client_report(client_id, reduce_by, note, before, after, eval_ip, eval_pc)

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
        change_description=f'{canon} fee adjust add=${add_firm:,.2f}: {note}',
        overwrite=True,
    )
    if ok:
        print(f'  Saved {client_id} (history v{version})')
        return True

    print(f'  ERROR: Failed to save {client_id}', file=sys.stderr)
    return False


def process_client(
    client_id: str,
    reduce_by: float,
    note: str,
    apply: bool,
    backup_dir: str,
    *,
    target_ip_fees: float | None = None,
) -> bool:
    from dashboard.database import get_client_data, save_client_data_with_history

    data = get_client_data(client_id)
    if not data:
        print(f'ERROR: Client not found: {client_id}', file=sys.stderr)
        return False

    eval_ip, eval_pc = eval_baseline_fees(data)
    if target_ip_fees is not None:
        reduce_by = round(eval_ip - target_ip_fees, 2)
        if reduce_by == 0:
            print(f'{client_id}: eval IP fees already ${eval_ip:,.2f} (target ${target_ip_fees:,.2f})')
            return True

    stats = data.get('statistics') or {}
    before = {
        'profitability_completed': _section_summary(stats, 'profitability_completed'),
        'cashflow_inprogress': _section_summary(stats, 'cashflow_inprogress'),
    }
    updated = apply_fee_adjustment(
        data,
        reduce_by,
        note,
        target_ip_fees=target_ip_fees,
        eval_ip_fees=eval_ip,
        eval_pc_fees=eval_pc,
    )
    after = {
        'profitability_completed': _section_summary(updated['statistics'], 'profitability_completed'),
        'cashflow_inprogress': _section_summary(updated['statistics'], 'cashflow_inprogress'),
    }

    _print_client_report(client_id, reduce_by, note, before, after, eval_ip, eval_pc)

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
        change_description=f'Fee adjust reduce_by={reduce_by:,.2f}: {note}',
        overwrite=True,
    )
    if ok:
        print(f'  Saved {client_id} (history v{version})')
        return True

    print(f'  ERROR: Failed to save {client_id}', file=sys.stderr)
    return False


def main():
    parser = argparse.ArgumentParser(description='Inject manual challenge fee adjustments.')
    parser.add_argument('--presets', action='store_true', help='Run configured client presets')
    parser.add_argument('--client', help='Single client_id')
    parser.add_argument('--reduce', type=float, help='Subtract from eval IP fees (positive=lower fees)')
    parser.add_argument('--add', type=float, help='Add to eval IP fees (stored as negative reduce_by)')
    parser.add_argument('--target-ip-fees', type=float, help='Set in-progress challenge fees to this exact total')
    parser.add_argument('--prop-firm', help='Prop firm for per-firm fee remainder (e.g. FundedNext)')
    parser.add_argument('--target-firm-fees', type=float, help='Set By Prop Firm fees for --prop-firm to this total')
    parser.add_argument('--add-firm-fees', type=float, help='Add this amount to --prop-firm fees (and total challenge fees)')
    parser.add_argument('--note', default='Manual fee adjustment', help='Audit note')
    parser.add_argument('--apply', action='store_true', help='Write changes (default: dry-run)')
    parser.add_argument('--backup-dir', default=os.path.join(ROOT, 'pg_backups'), help='Backup JSON directory')
    args = parser.parse_args()

    jobs: list[tuple[str, float | None, float | None, str, dict]] = []

    if args.presets:
        for cid, cfg in PRESETS.items():
            if cfg.get('prop_firm'):
                pf, tf, af = _prop_firm_job_from_cfg(cfg)
                jobs.append((cid, None, None, cfg['note'], {
                    'mode': 'prop_firm',
                    'prop_firm': pf,
                    'target_firm_fees': tf,
                    'add_firm_fees': af,
                }))
            elif cfg.get('target_ip_fees') is not None:
                jobs.append((cid, None, cfg['target_ip_fees'], cfg['note'], {'mode': 'total'}))
            else:
                jobs.append((cid, cfg['reduce_by'], None, cfg['note'], {'mode': 'total'}))
    elif args.client:
        if args.prop_firm:
            if args.target_firm_fees is None and args.add_firm_fees is None:
                parser.error('Use --target-firm-fees or --add-firm-fees with --prop-firm')
            jobs.append((args.client, None, None, args.note, {
                'mode': 'prop_firm',
                'prop_firm': args.prop_firm,
                'target_firm_fees': args.target_firm_fees,
                'add_firm_fees': args.add_firm_fees,
            }))
        elif args.target_ip_fees is not None:
            jobs.append((args.client, None, args.target_ip_fees, args.note, {'mode': 'total'}))
        elif args.add is not None:
            jobs.append((args.client, -abs(args.add), None, args.note, {'mode': 'total'}))
        elif args.reduce is not None:
            jobs.append((args.client, abs(args.reduce), None, args.note, {'mode': 'total'}))
        else:
            parser.error('Use --target-ip-fees, --reduce, --add, or --prop-firm with --client')
    else:
        parser.error('Use --presets or --client with an adjustment flag')

    if not args.apply:
        print('DRY RUN — pass --apply to persist to the database\n')

    ok_all = True
    for client_id, reduce_by, target_ip, note, meta in jobs:
        if meta.get('mode') == 'prop_firm':
            ok = process_prop_firm_client(
                client_id,
                meta['prop_firm'],
                note,
                args.apply,
                args.backup_dir,
                target_firm_fees=meta.get('target_firm_fees'),
                add_firm_fees=meta.get('add_firm_fees'),
            )
        else:
            ok = process_client(
                client_id,
                reduce_by or 0.0,
                note,
                args.apply,
                args.backup_dir,
                target_ip_fees=target_ip,
            )
        if not ok:
            ok_all = False

    sys.exit(0 if ok_all else 1)


if __name__ == '__main__':
    main()
