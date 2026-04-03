#!/usr/bin/env python3
"""
DETECT & RECONSTRUCT MISSING EVALUATION ROWS
=============================================
Compares eval_count from push logs vs current DB.
If rows are missing (added during the lost week), creates skeleton rows
with Account Number and Prop Firm from logs.
"""

import sqlite3
import json
import os
from datetime import datetime
from collections import defaultdict

DB_PATH = os.path.expanduser('~/MT5Dashboard/dashboard/dashboard.db')
REPORT_PATH = os.path.expanduser('~/MT5Dashboard/_log_push_report.json')


def load_push_report():
    """Load the JSON report from the reconstruction script."""
    with open(REPORT_PATH) as f:
        return json.load(f)


def get_db_eval_counts():
    """Get current eval counts from the live DB."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        'SELECT client_id, evaluations FROM clients_data ORDER BY client_id'
    ).fetchall()
    conn.close()

    counts = {}
    data = {}
    for cid, evals_json in rows:
        evals = json.loads(evals_json or '[]')
        counts[cid] = len(evals)
        data[cid] = evals
    return counts, data


def detect_missing_rows(report, db_counts):
    """
    Compare push log eval_count (at latest push) vs current DB count.
    Returns list of clients with discrepancies.
    """
    discrepancies = []

    for client_id, client_data in report.get('clients', {}).items():
        pushes = client_data.get('pushes', [])
        if not pushes:
            continue

        # Get the maximum eval_count seen across ALL pushes
        max_log_count = max(p.get('eval_count', 0) for p in pushes)
        # Also get the latest push eval_count
        latest_count = pushes[-1].get('eval_count', 0)

        db_count = db_counts.get(client_id, 0)

        if max_log_count > db_count:
            discrepancies.append({
                'client_id': client_id,
                'db_count': db_count,
                'log_max_count': max_log_count,
                'log_latest_count': latest_count,
                'missing_rows': max_log_count - db_count,
                'push_count': len(pushes),
                'eval_account_map': client_data.get('eval_account_map', {}),
                'firms': client_data.get('firms', {}),
                'session_accounts': client_data.get('session_accounts', []),
            })

    return sorted(discrepancies, key=lambda x: -x['missing_rows'])


def reconstruct_missing_rows(discrepancies, db_data):
    """
    For clients with missing eval rows, create skeleton rows with
    Account Number and Prop Firm from log data.
    """
    # Exact Prop Firm names from dashboard dropdown
    PREFIX_TO_FIRM = {
        'FNFT': 'My Funded Futures',
        'MFFU': 'My Funded Futures',
        'TDF': 'Tradeify',
        'TDFY': 'Tradeify',
        'AFAD': 'Apex',
        'V2': 'Topstep',
        '50KTC': 'Topstep',
        'ELTD': 'Other',
    }

    reconstructions = []

    for d in discrepancies:
        cid = d['client_id']
        current_evals = db_data.get(cid, [])
        db_count = len(current_evals)
        target_count = d['log_max_count']

        # Build suffix → full session account lookup
        session_accts = d.get('session_accounts', [])
        suffix_to_full = {}
        for full_acct in session_accts:
            if '-' in full_acct:
                suffix = full_acct.rsplit('-', 1)[1]
                suffix_to_full.setdefault(suffix, full_acct)

        # Build row index -> partial account mapping
        row_to_acct = {}
        for row_str, acct in d.get('eval_account_map', {}).items():
            if isinstance(acct, str):
                row_to_acct[int(row_str)] = acct
            elif isinstance(acct, dict):
                row_to_acct[int(row_str)] = str(acct.get('account', ''))
            else:
                row_to_acct[int(row_str)] = str(acct)

        # Create skeleton rows for missing indices
        new_rows = []
        for row_idx in range(db_count, target_count):
            partial = row_to_acct.get(row_idx, '')
            if not isinstance(partial, str):
                partial = str(partial)

            # Map partial → full session account (e.g. "10374" → "FNFT-10374")
            full_acct = suffix_to_full.get(partial, '')

            # Derive Prop Firm from full account prefix
            firm = ''
            if full_acct and '-' in full_acct:
                prefix = full_acct.rsplit('-', 1)[0].upper()
                firm = PREFIX_TO_FIRM.get(prefix, '')

            # Use full account as Account Number, fall back to partial
            acct_display = full_acct if full_acct else partial

            skeleton = {
                'Account Number': acct_display,
                'Prop Firm': firm,
                'Account Size': '$50,000',
                'Fee': '',
                'Date Purchased': '',
                'Date Started': '',
                'Date Ended': '',
                'Status P1': '',
                'Funded Status': '',
            }
            new_rows.append((row_idx, skeleton))

        if new_rows:
            reconstructions.append({
                'client_id': cid,
                'db_count': db_count,
                'target_count': target_count,
                'new_rows': new_rows,
            })

    return reconstructions


def repair_empty_rows(report, db_data, dry_run=True):
    """
    Find eval rows that exist but have blank Account Number / Prop Firm,
    and fill them from the push report data.
    Returns (repairs_list, updated_count, error_count).
    """
    # Exact Prop Firm names from dashboard dropdown
    PREFIX_TO_FIRM = {
        'FNFT': 'My Funded Futures',
        'MFFU': 'My Funded Futures',
        'TDF': 'Tradeify',
        'TDFY': 'Tradeify',
        'AFAD': 'Apex',
        'V2': 'Topstep',
        '50KTC': 'Topstep',
        'ELTD': 'Other',
    }

    repairs = []

    for client_id, client_data in report.get('clients', {}).items():
        evals = db_data.get(client_id, [])
        if not evals:
            continue

        # Build suffix → full session account lookup
        session_accts = client_data.get('session_accounts', [])
        suffix_to_full = {}
        for full_acct in session_accts:
            if '-' in full_acct:
                suffix = full_acct.rsplit('-', 1)[1]
                suffix_to_full.setdefault(suffix, full_acct)

        # Build row index -> partial account mapping
        row_to_acct = {}
        for row_str, acct in client_data.get('eval_account_map', {}).items():
            if isinstance(acct, dict):
                row_to_acct[int(row_str)] = str(acct.get('account', ''))
            elif isinstance(acct, str):
                row_to_acct[int(row_str)] = acct
            else:
                row_to_acct[int(row_str)] = str(acct)

        # Find empty rows
        row_fixes = []
        for idx, ev in enumerate(evals):
            has_acct = bool(ev.get('Account Number', '').strip())
            has_firm = bool(ev.get('Prop Firm', '').strip())
            if has_acct and has_firm:
                continue  # Already populated

            partial = row_to_acct.get(idx, '')
            if not partial:
                continue  # No log data for this row

            full_acct = suffix_to_full.get(partial, '')
            firm = ''
            if full_acct and '-' in full_acct:
                prefix = full_acct.rsplit('-', 1)[0].upper()
                firm = PREFIX_TO_FIRM.get(prefix, '')

            acct_display = full_acct if full_acct else partial

            if (not has_acct and acct_display) or (not has_firm and firm):
                row_fixes.append({
                    'idx': idx,
                    'account': acct_display if not has_acct else None,
                    'firm': firm if not has_firm else None,
                })

        if row_fixes:
            repairs.append({
                'client_id': client_id,
                'fixes': row_fixes,
            })

    if not repairs:
        print("  No empty rows to repair.")
        return repairs, 0, 0

    # Print summary
    total_fixes = sum(len(r['fixes']) for r in repairs)
    print(f"\n  Found {total_fixes} empty rows across {len(repairs)} clients to repair.\n")

    for repair in repairs[:20]:
        cid = repair['client_id']
        print(f"  📋 {cid}: {len(repair['fixes'])} rows to fix")
        for fix in repair['fixes'][:5]:
            acct_str = fix['account'] or '(keep existing)'
            firm_str = fix['firm'] or '(keep existing)'
            print(f"    Row {fix['idx']}: Account={acct_str}, Firm={firm_str}")
        if len(repair['fixes']) > 5:
            print(f"    ... and {len(repair['fixes']) - 5} more")

    if dry_run:
        print(f"\n  DRY RUN — would repair {total_fixes} rows in {len(repairs)} clients.")
        return repairs, 0, 0

    # Apply fixes
    conn = sqlite3.connect(DB_PATH)
    updated = 0
    errors = 0

    for repair in repairs:
        cid = repair['client_id']
        try:
            row = conn.execute(
                'SELECT evaluations FROM clients_data WHERE client_id = ?', (cid,)
            ).fetchone()
            if not row:
                errors += 1
                continue

            evals = json.loads(row[0] or '[]')
            changed = False

            for fix in repair['fixes']:
                idx = fix['idx']
                if idx >= len(evals):
                    continue
                if fix['account'] and not evals[idx].get('Account Number', '').strip():
                    evals[idx]['Account Number'] = fix['account']
                    changed = True
                if fix['firm'] and not evals[idx].get('Prop Firm', '').strip():
                    evals[idx]['Prop Firm'] = fix['firm']
                    changed = True

            if changed:
                conn.execute(
                    'UPDATE clients_data SET evaluations = ? WHERE client_id = ?',
                    (json.dumps(evals), cid)
                )
                updated += 1
                print(f"  ✅ {cid}: Repaired {len(repair['fixes'])} rows")

        except Exception as e:
            print(f"  ❌ {cid}: Error — {e}")
            errors += 1

    conn.commit()
    conn.close()
    print(f"\n  Repair complete: {updated} clients updated, {errors} errors")
    return repairs, updated, errors


def apply_missing_rows(reconstructions, dry_run=True):
    """Apply missing rows to the DB."""
    if not reconstructions:
        print("  No missing rows to apply.")
        return

    conn = sqlite3.connect(DB_PATH)
    updated = 0
    errors = 0

    for recon in reconstructions:
        cid = recon['client_id']
        try:
            row = conn.execute(
                'SELECT evaluations FROM clients_data WHERE client_id = ?', (cid,)
            ).fetchone()
            if not row:
                print(f"  ❌ {cid}: Not found in DB")
                errors += 1
                continue

            evals = json.loads(row[0] or '[]')
            current_count = len(evals)

            if current_count >= recon['target_count']:
                print(f"  ⏭️  {cid}: Already has {current_count} evals (target {recon['target_count']})")
                continue

            # Add skeleton rows
            for row_idx, skeleton in recon['new_rows']:
                if row_idx < len(evals):
                    # Row already exists — update account/firm if blank
                    existing = evals[row_idx]
                    if not existing.get('Account Number') and skeleton['Account Number']:
                        existing['Account Number'] = skeleton['Account Number']
                    if not existing.get('Prop Firm') and skeleton['Prop Firm']:
                        existing['Prop Firm'] = skeleton['Prop Firm']
                else:
                    # Need to pad up to this index
                    while len(evals) <= row_idx:
                        evals.append({})
                    evals[row_idx] = skeleton

            action = "Would update" if dry_run else "Updated"
            print(f"  ✅ {cid}: {action} {current_count} → {len(evals)} eval rows "
                  f"(+{len(evals) - current_count} new)")

            if not dry_run:
                conn.execute(
                    'UPDATE clients_data SET evaluations = ? WHERE client_id = ?',
                    (json.dumps(evals), cid)
                )
                updated += 1

        except Exception as e:
            print(f"  ❌ {cid}: Error — {e}")
            errors += 1

    if not dry_run:
        conn.commit()
    conn.close()

    return updated, errors


def main():
    import sys

    print("=" * 100)
    print("MISSING EVALUATION ROW DETECTION & RECONSTRUCTION")
    print(f"Time: {datetime.now()}")
    print("=" * 100)

    # Load data
    print(f"\n{'='*80}")
    print("LOADING DATA")
    print(f"{'='*80}\n")

    report = load_push_report()
    db_counts, db_data = get_db_eval_counts()

    print(f"  Push report: {len(report.get('clients', {}))} clients")
    print(f"  Live DB: {len(db_counts)} clients")

    # Detect discrepancies
    print(f"\n{'='*80}")
    print("EVAL COUNT: PUSH LOGS vs LIVE DB")
    print(f"{'='*80}\n")

    discrepancies = detect_missing_rows(report, db_counts)

    # Also show ALL clients comparison
    print(f"  {'Client':<30} {'DB Count':>10} {'Log Max':>10} {'Log Latest':>10} {'Diff':>8}")
    print(f"  {'─'*30} {'─'*10} {'─'*10} {'─'*10} {'─'*8}")

    all_clients = sorted(report.get('clients', {}).keys())
    total_missing = 0
    clients_with_missing = 0

    for cid in all_clients:
        client_data = report['clients'][cid]
        pushes = client_data.get('pushes', [])
        if not pushes:
            continue

        max_count = max(p.get('eval_count', 0) for p in pushes)
        latest_count = pushes[-1].get('eval_count', 0)
        db_count = db_counts.get(cid, 0)
        diff = max_count - db_count

        marker = ''
        if diff > 0:
            marker = f' ❌ MISSING {diff}'
            total_missing += diff
            clients_with_missing += 1
        elif diff < 0:
            marker = f' ➕ Extra {-diff}'  # DB has more (post-incident additions)

        if diff != 0:
            print(f"  {cid:<30} {db_count:>10} {max_count:>10} {latest_count:>10} {diff:>+8}{marker}")

    # Show matching clients count
    matching = len(all_clients) - clients_with_missing - sum(
        1 for cid in all_clients
        if max(report['clients'][cid].get('pushes', [{}])[-1:] or [{'eval_count': 0}],
               key=lambda p: p.get('eval_count', 0)).get('eval_count', 0) < db_counts.get(cid, 0)
    )

    print(f"\n  SUMMARY:")
    print(f"    Clients with matching eval counts: {len(all_clients) - clients_with_missing}")
    print(f"    Clients with MISSING rows: {clients_with_missing} ({total_missing} total rows)")

    if not discrepancies:
        print(f"\n  ✅ ALL CLIENTS have correct eval row counts — no rows are missing!")

    if discrepancies:
        # Reconstruct
        print(f"\n{'='*80}")
        print("MISSING ROW RECONSTRUCTION PLAN")
        print(f"{'='*80}\n")

        reconstructions = reconstruct_missing_rows(discrepancies, db_data)

        for recon in reconstructions:
            cid = recon['client_id']
            print(f"\n  📋 {cid}: needs {recon['target_count'] - recon['db_count']} new rows "
                  f"(DB: {recon['db_count']} → Target: {recon['target_count']})")
            for row_idx, skeleton in recon['new_rows'][:10]:
                acct = skeleton.get('Account Number', '?')
                firm = skeleton.get('Prop Firm', '?')
                print(f"    Row {row_idx}: {firm} | {acct}")
            if len(recon['new_rows']) > 10:
                print(f"    ... and {len(recon['new_rows']) - 10} more rows")

        # Dry run
        print(f"\n{'='*80}")
        print("DRY RUN — APPLYING MISSING ROWS")
        print(f"{'='*80}\n")

        apply_missing_rows(reconstructions, dry_run=True)

        # Apply if --apply
        if '--apply' in sys.argv:
            print(f"\n{'='*80}")
            print("APPLYING MISSING ROWS TO LIVE DB")
            print(f"{'='*80}\n")

            updated, errors = apply_missing_rows(reconstructions, dry_run=False)
            print(f"\n  Applied: {updated}, Errors: {errors}")

            # Reload DB data after adding rows
            db_counts, db_data = get_db_eval_counts()

    # ── Phase 2: Repair empty rows (Account Number + Prop Firm) ──
    print(f"\n{'='*80}")
    print("PHASE 2: REPAIR EMPTY EVAL ROWS (Account Number + Prop Firm)")
    print(f"{'='*80}\n")

    repair_empty_rows(report, db_data, dry_run=True)

    if '--apply' in sys.argv:
        print(f"\n{'='*80}")
        print("APPLYING REPAIRS TO EMPTY ROWS")
        print(f"{'='*80}\n")
        repair_empty_rows(report, db_data, dry_run=False)

    if '--apply' not in sys.argv:
        print(f"\n  To apply all changes: python3 _detect_missing_evals.py --apply")

    print(f"\n{'='*100}")
    print("COMPLETE")
    print(f"{'='*100}")


if __name__ == '__main__':
    main()
