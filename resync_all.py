"""
resync_all.py
─────────────
Re-fetches evaluations from each client's stored Google Sheet URL and
recalculates statistics using the current (fixed) data_processor code.

This is the universal backfill for all bug fixes applied to
fetch_evaluations / calculate_statistics.  Run it once whenever a new
data-processing fix is deployed; afterwards every normal sheet import
will stay in sync automatically.

Clients WITHOUT a stored sheet_url (e.g. Amber, Jiang) are skipped and
listed at the end — they need a manual re-import from the trader app.
"""
import sys, json
from datetime import datetime

sys.path.insert(0, '.')
from dashboard.database import get_connection, get_all_clients
from utils.data_processor import fetch_evaluations, calculate_statistics

# ── helpers ────────────────────────────────────────────────────────────────────
SEP = "─" * 70

def fmt(v):
    return f"${v:>12,.2f}" if v is not None else "        N/A"

def print_stats(label, stats):
    ci = stats.get('cashflow_inprogress', {})
    cc = stats.get('cashflow_completed', {})
    pc = stats.get('profitability_completed', {})
    print(f"  [{label}]")
    print(f"    cashflow_inprogress  challenge_fees={fmt(ci.get('challenge_fees'))}  "
          f"hedging={fmt(ci.get('hedging_results'))}  net={fmt(ci.get('net_profit'))}")
    print(f"    cashflow_completed   challenge_fees={fmt(cc.get('challenge_fees'))}  "
          f"hedging={fmt(cc.get('hedging_results'))}  net={fmt(cc.get('net_profit'))}")
    print(f"    profitability_comp   challenge_fees={fmt(pc.get('challenge_fees'))}  "
          f"hedging={fmt(pc.get('hedging_results'))}  net={fmt(pc.get('net_profit'))}")

# ── main ───────────────────────────────────────────────────────────────────────
all_clients = get_all_clients()
print(f"\n{SEP}")
print(f"  resync_all.py — {len(all_clients)} clients in DB")
print(SEP)

to_resync   = []   # (client_id, name, sheet_url)
no_sheet    = []   # (client_id, name)

for cid, data in all_clients.items():
    name      = (data.get('identity') or {}).get('name', '') or \
                (data.get('identity') or {}).get('client', '') or cid
    sheet_url = (data.get('sheet_url') or '').strip()
    if sheet_url:
        to_resync.append((cid, name, sheet_url))
    else:
        no_sheet.append((cid, name))

print(f"\n  Will resync  : {[n for _, n, _ in to_resync]}")
print(f"  No sheet URL : {[n for _, n in no_sheet]}  (need manual import in app)")

if not to_resync:
    print("\n  Nothing to do.")
    sys.exit(0)

answer = input("\nProceed? [y/N] ").strip().lower()
if answer != 'y':
    print("Aborted – no changes made.")
    sys.exit(0)

success_count = 0
fail_count    = 0
now           = datetime.now().isoformat()

for cid, name, sheet_url in to_resync:
    print(f"\n{SEP}")
    print(f"  {name}  ({cid})")
    print(f"  Sheet: {sheet_url[:80]}...")

    try:
        # ── fetch ──────────────────────────────────────────────────────────────
        print("  Fetching evaluations…", end=' ', flush=True)
        result       = fetch_evaluations(sheet_url)
        evals_sheet  = result[0] if isinstance(result, tuple) else result
        evals_notes  = result[1] if isinstance(result, tuple) and len(result) > 1 else {}
        print(f"{len(evals_sheet)} rows")

        if not evals_sheet:
            print("  ⚠️  Empty evaluation list — skipping (sheet may not be public)")
            fail_count += 1
            continue

        # ── old stats for diff ─────────────────────────────────────────────────
        old_data  = all_clients[cid]
        old_evals = old_data.get('evaluations', [])
        old_stats = old_data.get('statistics', {})

        # ── recalculate ────────────────────────────────────────────────────────
        print("  Recalculating statistics…", end=' ', flush=True)
        new_stats = calculate_statistics(evals_sheet, None, None)
        print("done")

        print_stats("OLD", old_stats)
        print_stats("NEW", new_stats)

        # show key deltas
        for section in ('cashflow_inprogress', 'cashflow_completed', 'profitability_completed'):
            o = old_stats.get(section, {})
            n = new_stats.get(section, {})
            for key in ('challenge_fees', 'hedging_results', 'farming_results',
                        'payouts', 'net_profit'):
                delta = n.get(key, 0) - o.get(key, 0)
                if abs(delta) > 0.005:
                    print(f"    Δ {section}.{key}: {fmt(delta)}")

        # ── write ──────────────────────────────────────────────────────────────
        with get_connection() as conn:
            conn.execute(
                'UPDATE clients_data SET evaluations = ?, statistics = ?, last_updated = ? '
                'WHERE client_id = ?',
                (json.dumps(evals_sheet), json.dumps(new_stats), now, cid)
            )
            conn.commit()

        print(f"  ✅ Written  ({len(old_evals)} → {len(evals_sheet)} rows)")
        success_count += 1

    except Exception as exc:
        import traceback
        print(f"  ❌ FAILED: {exc}")
        traceback.print_exc()
        fail_count += 1

# ── summary ────────────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print(f"  Done.  ✅ {success_count} resynced   ❌ {fail_count} failed")
if no_sheet:
    print(f"\n  Clients needing manual import (no sheet URL in DB):")
    for cid, name in no_sheet:
        print(f"    • {name} ({cid})")
    print("  → Open the trader app, enter their sheet URL and click 'Import from Sheet'.")
print()
