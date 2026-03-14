"""
Re-import all clients' Google Sheets from the server side.
Fetches evaluations, waterlog history, waterlog periods, and notes
from each client's stored sheet_url, then recalculates statistics
while preserving MT5 account data, historical accounts, and other fields.

Usage:
    python reimport_all_sheets.py              # dry-run (shows what would happen)
    python reimport_all_sheets.py --execute    # actually performs the reimport
    python reimport_all_sheets.py --execute --client "Chris"  # single client
"""
import sys, os, json, re, time, traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.database import (
    get_all_clients, get_client_data, save_client_data_with_history
)
from dashboard.notes_service import save_client_note
from dashboard.watermark_service import bulk_save_history, save_waterlog_periods
from utils.data_processor import fetch_evaluations, calculate_statistics, fetch_waterlog_history

try:
    from utils.sheet_helper import fetch_waterlog_data, fetch_waterlog_periods_from_sheet
except ImportError:
    try:
        from dashboard.utils.sheet_helper import fetch_waterlog_data, fetch_waterlog_periods_from_sheet
    except ImportError:
        fetch_waterlog_data = None
        fetch_waterlog_periods_from_sheet = None


def _parse_currency_str(s):
    try:
        return float(re.sub(r'[^0-9.\-]', '', str(s))) if s else None
    except Exception:
        return None


def _to_iso(date_str):
    """Convert M/D/YYYY to YYYY-MM-DD."""
    try:
        return datetime.strptime(date_str.strip(), '%m/%d/%Y').strftime('%Y-%m-%d')
    except Exception:
        return None


def _run_with_timeout(fn, args=(), timeout=60):
    """Run a function with a timeout. Returns result or raises TimeoutError."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn, *args)
        return future.result(timeout=timeout)


def reimport_client(client_id, existing_data, dry_run=True):
    """Re-import a single client's Google Sheet. Returns (success, message)."""
    identity = existing_data.get('identity') or {}
    sheet_url = identity.get('sheet_url') or existing_data.get('sheet_url')

    if not sheet_url:
        return False, "No sheet_url stored"

    # --- Fetch evaluations (timeout 90s) ---
    try:
        eval_result = _run_with_timeout(fetch_evaluations, (sheet_url,), timeout=90)
        if isinstance(eval_result, tuple):
            evaluations, xlsx_notes = eval_result
        else:
            evaluations = eval_result
            xlsx_notes = {}
    except FuturesTimeout:
        return False, "Timed out fetching evaluations (90s)"
    except Exception as e:
        return False, f"Failed to fetch evaluations: {e}"

    if not evaluations:
        return False, "Could not fetch evaluations from sheet (empty or inaccessible)"

    # --- Fetch waterlog history (timeout 30s) ---
    try:
        waterlog_history = _run_with_timeout(fetch_waterlog_history, (sheet_url,), timeout=30)
    except FuturesTimeout:
        print("WARN waterlog history timed out ", end="")
        waterlog_history = None
    except Exception as e:
        print(f"WARN waterlog history: {e} ", end="")
        waterlog_history = None
    waterlog_count = len(waterlog_history) if waterlog_history else 0

    # --- Fetch waterlog periods with Low/High ---
    wl_periods = []
    wl_values = {}
    try:
        if fetch_waterlog_data:
            wl_full = fetch_waterlog_data(sheet_url)
            if wl_full:
                for row in wl_full:
                    fd = _to_iso(row.get('from_date', ''))
                    td = _to_iso(row.get('to_date', ''))
                    if fd and td:
                        wl_periods.append((fd, td))
                        low = _parse_currency_str(row.get('low'))
                        high = _parse_currency_str(row.get('high'))
                        if low is not None or high is not None:
                            wl_values[fd] = {
                                'low': low,
                                'high': high,
                                'split_pct': row.get('split_pct', 25),
                            }
        elif fetch_waterlog_periods_from_sheet:
            wl_periods = fetch_waterlog_periods_from_sheet(sheet_url) or []
    except Exception as e:
        print(f"WARN waterlog periods: {e} ", end="")
        wl_periods = []
        wl_values = {}

    if dry_run:
        return True, f"Would import {len(evaluations)} evals, {waterlog_count} waterlog entries, {len(wl_periods)} periods, {len(xlsx_notes)} note rows"

    # --- Save waterlog history ---
    if waterlog_history:
        bulk_save_history(client_id, waterlog_history)

    # --- Save waterlog periods ---
    if wl_periods:
        save_waterlog_periods(client_id, wl_periods, period_values=wl_values if wl_values else None)

    # --- Preserve existing MT5 / historical accounts ---
    existing_mt5 = existing_data.get('account') or None
    existing_hr = existing_data.get('statistics', {}).get('hedging_review', {})
    existing_hist = existing_hr.get('historical_accounts')

    # --- Calculate statistics ---
    statistics = calculate_statistics(
        evaluations,
        mt5_account=existing_mt5 if existing_mt5 else None,
        xlsx_notes=xlsx_notes,
        historical_accounts=existing_hist
    )

    # Preserve historical account fields
    if existing_hist:
        statistics.setdefault('hedging_review', {})['historical_accounts'] = existing_hist
        statistics['hedging_review']['historical_deposits'] = existing_hr.get('historical_deposits', 0)
        statistics['hedging_review']['historical_withdrawals'] = existing_hr.get('historical_withdrawals', 0)
        statistics['hedging_review']['historical_balance'] = existing_hr.get('historical_balance', 0)

    # --- Build client_data (preserve all existing fields) ---
    client_data = {
        "deals": existing_data.get('deals', []),
        "positions": existing_data.get('positions', []),
        "account": existing_mt5 or {},
        "evaluations": evaluations,
        "statistics": statistics,
        "dropdown_options": existing_data.get('dropdown_options', {}),
        "identity": identity,
        "sheet_url": sheet_url,
        "migrated_at": datetime.now().isoformat(),
        "hedge_accounts": existing_data.get('hedge_accounts', []),
        "prop_accounts": existing_data.get('prop_accounts', []),
        "vps_accounts": existing_data.get('vps_accounts', []),
        "payment_info": existing_data.get('payment_info', []),
        "payment_address": existing_data.get('payment_address', {}),
    }

    # --- Save with history ---
    success, version = save_client_data_with_history(
        client_id,
        client_data,
        action='SHEET_REIMPORT',
        changed_by='server_script',
        changed_by_type='super_admin',
        ip_address='127.0.0.1',
        change_source='reimport_script',
        change_description=f"Re-imported {len(evaluations)} records from Google Sheets",
        overwrite=True
    )

    # --- Save cell notes ---
    notes_saved = 0
    if xlsx_notes:
        for row_idx, col_notes in xlsx_notes.items():
            if isinstance(row_idx, int) and isinstance(col_notes, dict):
                for col_key, content in col_notes.items():
                    if content and str(content).strip():
                        save_client_note(client_id, row_idx, col_key, str(content).strip(), 'sheet_reimport')
                        notes_saved += 1

    return True, f"Imported {len(evaluations)} evals, {waterlog_count} waterlog, {len(wl_periods)} periods, {notes_saved} notes (v{version})"


def main():
    dry_run = '--execute' not in sys.argv

    # Optional: filter to a single client
    client_filter = None
    if '--client' in sys.argv:
        idx = sys.argv.index('--client')
        if idx + 1 < len(sys.argv):
            client_filter = sys.argv[idx + 1].lower()

    if dry_run:
        print("=" * 60)
        print("  DRY RUN — pass --execute to actually reimport")
        print("=" * 60)
    else:
        print("=" * 60)
        print("  EXECUTING — reimporting all client sheets")
        print("=" * 60)

    print()

    all_clients = get_all_clients()

    # Apply client filter if specified
    if client_filter:
        all_clients = {k: v for k, v in all_clients.items() if client_filter in k.lower()}
        if not all_clients:
            print(f"No client found matching '{client_filter}'")
            return

    total = len(all_clients)
    success_count = 0
    skip_count = 0
    fail_count = 0

    for i, (client_id, data) in enumerate(all_clients.items(), 1):
        print(f"[{i}/{total}] {client_id} ... ", end="", flush=True)
        try:
            ok, msg = reimport_client(client_id, data, dry_run=dry_run)
            if ok:
                print(f"OK — {msg}")
                success_count += 1
            else:
                print(f"SKIP — {msg}")
                skip_count += 1
        except Exception as e:
            print(f"FAIL — {e}")
            traceback.print_exc()
            fail_count += 1

        # Small delay between clients to avoid hammering Google
        if not dry_run and i < total:
            time.sleep(1)

    print()
    print(f"Done: {success_count} success, {skip_count} skipped, {fail_count} failed (total {total})")


if __name__ == '__main__':
    main()
