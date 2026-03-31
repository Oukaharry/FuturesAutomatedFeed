"""
Fix currency formatting in the database.
Normalizes values like "$-600" -> "-600" (clean numeric) in evaluations,
so the dashboard display logic correctly renders them as "-$600.00".

Also fixes values in hedge_accounts, prop_accounts, statistics, and data_history.
"""
import sqlite3
import json
import re
import os
import shutil
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'dashboard', 'dashboard.db')

# Keys that hold money values inside evaluations
MONEY_PREFIXES = ('Prop Day', 'Hedge Day', 'Hedge Result', 'Fee', 'Payout', 'Activation Fee',
                  'Farming Net', 'Hedge Days', 'P1 Hedges', 'Funded Hedges', 'Net Profit')


def normalize_currency(value):
    """
    Strip $ and commas from a value, returning a clean numeric string.
    Examples:
      "$-600"    -> "-600"
      "$150.00"  -> "150.00"
      "-$600"    -> "-600"
      "$-156.64" -> "-156.64"
      "$1,200"   -> "1200"
      "-600"     -> "-600"  (already clean)
      "150"      -> "150"   (already clean)
      ""         -> ""      (empty stays empty)
    """
    if value is None or value == '':
        return value

    s = str(value).strip()
    if not s:
        return value

    # Check if it contains a $ sign at all — if not, nothing to fix
    if '$' not in s:
        return value

    # Strip $ and commas
    cleaned = s.replace('$', '').replace(',', '').strip()

    # Validate it's actually numeric
    try:
        float(cleaned)
        return cleaned
    except (ValueError, TypeError):
        # Not a number after stripping, leave as-is
        return value


def fix_evaluations(evaluations):
    """Fix currency values in a list of evaluation dicts. Returns (fixed_list, change_count)."""
    changes = 0
    for ev in evaluations:
        for key in list(ev.keys()):
            if any(key.startswith(prefix) for prefix in MONEY_PREFIXES):
                old_val = ev[key]
                new_val = normalize_currency(old_val)
                if new_val != old_val:
                    ev[key] = new_val
                    changes += 1
    return evaluations, changes


def fix_json_column(json_text, key_check_fn):
    """
    Generic fixer for JSON columns. key_check_fn decides if a key holds money.
    Returns (fixed_json_str, change_count).
    """
    changes = 0
    try:
        data = json.loads(json_text) if json_text else None
    except (json.JSONDecodeError, TypeError):
        return json_text, 0

    if data is None:
        return json_text, 0

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                for key in list(item.keys()):
                    if key_check_fn(key):
                        old_val = item[key]
                        new_val = normalize_currency(old_val)
                        if new_val != old_val:
                            item[key] = new_val
                            changes += 1
    elif isinstance(data, dict):
        for key in list(data.keys()):
            if key_check_fn(key):
                old_val = data[key]
                new_val = normalize_currency(old_val)
                if new_val != old_val:
                    data[key] = new_val
                    changes += 1

    if changes > 0:
        return json.dumps(data), changes
    return json_text, 0


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        return

    # Backup the database first
    backup_path = DB_PATH + f'.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    shutil.copy2(DB_PATH, backup_path)
    print(f"Database backed up to: {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # --- Fix clients_data.evaluations ---
    print("\n=== Fixing clients_data.evaluations ===")
    cursor.execute("SELECT id, client_id, evaluations FROM clients_data WHERE evaluations IS NOT NULL AND evaluations != '[]'")
    rows = cursor.fetchall()
    total_eval_changes = 0
    clients_fixed = 0

    for row_id, client_id, eval_json in rows:
        try:
            evals = json.loads(eval_json) if eval_json else []
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(evals, list):
            continue

        evals_fixed, change_count = fix_evaluations(evals)
        if change_count > 0:
            cursor.execute("UPDATE clients_data SET evaluations = ? WHERE id = ?",
                           (json.dumps(evals_fixed), row_id))
            total_eval_changes += change_count
            clients_fixed += 1
            print(f"  {client_id}: fixed {change_count} values")

    print(f"  Total: {total_eval_changes} values fixed across {clients_fixed} clients")

    # --- Fix clients_data.statistics ---
    print("\n=== Fixing clients_data.statistics ===")
    stat_money_keys = {'net_profit', 'total_profit', 'total_loss', 'balance', 'equity',
                       'margin', 'free_margin', 'payout', 'fee', 'hedge_result'}
    cursor.execute("SELECT id, client_id, statistics FROM clients_data WHERE statistics IS NOT NULL AND statistics != '{}'")
    rows = cursor.fetchall()
    total_stat_changes = 0

    for row_id, client_id, stat_json in rows:
        fixed_json, changes = fix_json_column(stat_json, lambda k: k.lower() in stat_money_keys)
        if changes > 0:
            cursor.execute("UPDATE clients_data SET statistics = ? WHERE id = ?", (fixed_json, row_id))
            total_stat_changes += changes
            print(f"  {client_id}: fixed {changes} values")

    print(f"  Total: {total_stat_changes} values fixed")

    # --- Fix clients_data.hedge_accounts ---
    print("\n=== Fixing clients_data.hedge_accounts ===")
    cursor.execute("SELECT id, client_id, hedge_accounts FROM clients_data WHERE hedge_accounts IS NOT NULL AND hedge_accounts != '[]'")
    rows = cursor.fetchall()
    total_hedge_changes = 0

    for row_id, client_id, hedge_json in rows:
        fixed_json, changes = fix_json_column(hedge_json,
                                              lambda k: any(k.startswith(p) for p in MONEY_PREFIXES) or 'balance' in k.lower() or 'profit' in k.lower())
        if changes > 0:
            cursor.execute("UPDATE clients_data SET hedge_accounts = ? WHERE id = ?", (fixed_json, row_id))
            total_hedge_changes += changes
            print(f"  {client_id}: fixed {changes} values")

    print(f"  Total: {total_hedge_changes} values fixed")

    # --- Fix data_history.evaluations ---
    print("\n=== Fixing data_history.evaluations ===")
    try:
        cursor.execute("SELECT id, client_id, evaluations FROM data_history WHERE evaluations IS NOT NULL AND evaluations != '[]'")
        rows = cursor.fetchall()
        total_hist_changes = 0
        hist_rows_fixed = 0

        for row_id, client_id, eval_json in rows:
            try:
                evals = json.loads(eval_json) if eval_json else []
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(evals, list):
                continue

            evals_fixed, change_count = fix_evaluations(evals)
            if change_count > 0:
                cursor.execute("UPDATE data_history SET evaluations = ? WHERE id = ?",
                               (json.dumps(evals_fixed), row_id))
                total_hist_changes += change_count
                hist_rows_fixed += 1

        print(f"  Total: {total_hist_changes} values fixed across {hist_rows_fixed} history rows")
    except sqlite3.OperationalError as e:
        print(f"  Skipped (table may not have evaluations column): {e}")

    conn.commit()
    conn.close()

    grand_total = total_eval_changes + total_stat_changes + total_hedge_changes
    print(f"\n{'='*50}")
    print(f"DONE — {grand_total} total values normalized.")
    print(f"Backup saved at: {backup_path}")
    print("All '$-600' style values are now stored as '-600' (clean numeric).")
    print("The dashboard will display them correctly as '-$600.00'.")


if __name__ == '__main__':
    main()
