from flask import Flask, render_template, jsonify, request, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import threading
import json
import os
import sys
from functools import wraps
import secrets
import hashlib
from datetime import datetime
from dashboard.financial_overview import calculate_propfirm_overview, get_payouts_history, get_portfolio_growth_data, get_payouts_growth_data, get_cumulative_deposits, get_cumulative_trading_profit, get_cumulative_fees, get_propfirm_breakdown, get_trader_performance_data

# Add project root to sys.path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.hierarchy import (
    SYSTEM_HIERARCHY, add_admin, add_trader, add_client, 
    update_admin_details, update_trader_details, update_client_details,
    get_client_by_email, get_user_by_email,
    remove_admin, remove_trader, remove_client,
    move_client, move_trader
)

# Import database module for secure storage
from dashboard.database import (
    init_database, 
    validate_api_key, generate_api_key, list_api_keys, revoke_api_key,
    verify_admin_password, set_admin_password,
    save_client_data, get_client_data, get_all_clients, get_clients_count, update_client_field,
    log_action, get_audit_log,
    create_session, validate_session, delete_session,
    create_user, verify_user_password, verify_client_login, update_user_password,
    get_user, list_users, deactivate_user, reset_user_password, user_exists,
    record_login_attempt, is_account_locked,
    find_user_by_identifier, verify_user_by_identifier,
    # History management
    save_client_data_with_history, get_data_history, get_data_version,
    rollback_to_version, compare_versions, get_latest_version
)

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))

# ============ Rate Limiting ============
# Note: For local development, use higher limits. 
# For production, consider: ["200 per day", "50 per hour"]
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["10000 per day", "2000 per hour"],
    storage_uri="memory://"
)

# Initialize Hierarchy from Config
hierarchy = SYSTEM_HIERARCHY


def get_account_signature(account_number):
    """
    Extract account signature for matching: first 4 + last 4/5 digits.
    This handles truncated account numbers in MT5 comments.
    
    Handles truncated format with '...' like: FNFT...59574
    
    Examples:
        MFFUEVSTP326057008 -> mffu7008 (full account)
        FNFT...59574 -> fnft59574 (truncated - keep last 5)
        12345678 -> 12345678
    """
    if not account_number:
        return None
    
    account_str = str(account_number).strip()
    
    # Handle MT5 truncated TopStep format: V2-...SUFFIX
    # This must come before the generic '...' handler to avoid including 'v2-' in the prefix
    if account_str.lower().startswith('v2-...'):
        return account_str.split('...')[-1].lower()

    # Handle TopStep/Dashboard formats: 50KTC-V2-..., EXPRESS-V2-...
    # Extract the last part which is likely the actual account number used in MT5
    if ('-V2-' in account_str) or ('50KTC' in account_str) or ('EXPRESS' in account_str):
        parts = account_str.split('-')
        last_part = parts[-1] 
        # Only treat as account number if it's alphanumeric but mostly digits/lengthy
        # Case: 50KTC-V2-472054-49197160 -> last is 49197160
        if len(parts) > 1:
            account_str = last_part
    
    # Handle truncated format: PREFIX...SUFFIX
    if '...' in account_str:
        parts = account_str.split('...')
        if len(parts) == 2:
            prefix = parts[0][:4] if len(parts[0]) >= 4 else parts[0]
            suffix = parts[1]  # Keep full suffix (usually 5 digits)
            return (prefix + suffix).lower()
    
    # Standard format: first 4 + last 4
    if len(account_str) < 8:
        return account_str.lower()
    
    # First 4 + last 4
    return (account_str[:4] + account_str[-4:]).lower()


def get_last_n_digits(account: str, n: int = 5) -> str:
    """Extract last N digits from account number."""
    if not account:
        return ""
        
    # Handle V2-... prefix exclusion (TopStep) to ensure we get actual account digits
    clean_account = account
    lower_acc = account.lower()
    if lower_acc.startswith('v2-...'):
        clean_account = account.split('...')[-1]
        
    # Extract only digits from the end
    digits = ''.join(c for c in clean_account if c.isdigit())
    return digits[-n:] if len(digits) >= n else digits


def match_account_to_evaluation(account_number, evaluations, phase_code):
    """
    Find matching evaluation for an account number based on phase.
    
    For Challenge (CH): Match against 'Account #' column
    For Funded/DoubleDip/Farming (FD, DD, FA): Match against 'Account #.1' column
    
    Matching strategy:
    1. Try signature match (first4 + last4/5)
    2. Fallback: Try last 5 digits match (for truncated accounts like FNFT...59574)
    """
    if not account_number or not evaluations:
        return None, None
    
    target_sig = get_account_signature(account_number)
    target_last5 = get_last_n_digits(account_number, 5)
    
    if not target_sig and not target_last5:
        return None, None
    
    # Determine which column to check based on phase
    if phase_code == 'CH':
        column_name = 'Account #'  # Challenge accounts
    else:
        column_name = 'Account #.1'  # Funded accounts for FD, DD, FA
    
    # First pass: Try signature match
    for idx, ev in enumerate(evaluations):
        eval_account = str(ev.get(column_name, '')).strip()
        if not eval_account:
            continue
        
        eval_sig = get_account_signature(eval_account)
        if eval_sig == target_sig:
            return idx, eval_account
    
    # Second pass: Try last 5 digits match (for truncated accounts)
    if target_last5:
        # Check against evaluations
        for idx, ev in enumerate(evaluations):
            eval_account = str(ev.get(column_name, '')).strip()
            if not eval_account:
                continue
            
            # Get last 5 digits of evaluation account
            eval_last5 = get_last_n_digits(eval_account, 5)
            
            # Standard exact match of 5 digits
            if len(target_last5) == 5 and eval_last5 == target_last5:
                return idx, eval_account
            
            # Fallback for TopStep: If target is short (4 digits) and matches end of eval
            if len(target_last5) >= 4 and eval_last5.endswith(target_last5):
                 return idx, eval_account
    
    return None, None


def normalize_account_size(value):
    """
    Normalize account size values to standard format: $X,XXX
    
    Handles:
        - "50k", "50K" → "$50,000"
        - "100000", "100,000" → "$100,000"
        - "$50,000" → "$50,000" (already correct)
        - "5000" → "$5,000"
    """
    import re
    if not value:
        return value
    
    val = str(value).strip().upper()
    
    # Already in correct format
    if re.match(r'^\$[\d,]+$', val):
        return value
    
    # Handle "50k" or "50K" format
    match = re.match(r'^[\$]?(\d+\.?\d*)K$', val, re.IGNORECASE)
    if match:
        num = float(match.group(1)) * 1000
        return f"${num:,.0f}"
    
    # Handle plain numbers like "50000" or "50,000"
    val_clean = re.sub(r'[\$,\s]', '', val)
    try:
        num = float(val_clean)
        return f"${num:,.0f}"
    except:
        pass
    
    # Return original if can't parse
    return value


def normalize_evaluations(evaluations):
    """Normalize field values in evaluations list."""
    if not evaluations:
        return evaluations
    
    for ev in evaluations:
        if 'Account Size' in ev and ev['Account Size']:
            ev['Account Size'] = normalize_account_size(ev['Account Size'])
    
    return evaluations


def get_field_name_for_phase(phase_code, trade_number, farming_date, evaluations, eval_idx, account_number=None):
    """
    Determine the correct field name to update based on phase.
    
    Phase mappings:
    - CH1-5: Hedge Result 1-5 (Challenge)
    - FD (MFFU with FD0): FD0→Hedge Result 1, FD1→Hedge Result 2, etc.
    - FD (Other starting FD1): FD1→Hedge Result 1, FD2→Hedge Result 2, etc.
    - DD1-4: Additional funded hedge results
    - FA: Hedge Day N (based on date or next available slot)
    """
    if phase_code == 'CH':
        # Challenge: CH1 → Hedge Result 1, CH2 → Hedge Result 2, etc.
        if trade_number is not None and 1 <= trade_number <= 5:
            return f"Hedge Result {trade_number}"
    
    elif phase_code == 'FD':
        # Determine if this is an MFFU account (uses FD0)
        # MFFU accounts: FD0→HR1.1, FD1→HR2.1, FD2→HR3.1, etc.
        # Other accounts: FD0→HR1.1 (rare), FD1→HR1.1, FD2→HR2.1, etc.
        is_mffu = account_number and account_number.upper().startswith('MFFU')
        
        if trade_number is not None:
            if is_mffu:
                # MFFU: FD0→Hedge Result 1.1, FD1→Hedge Result 2.1, etc.
                return f"Hedge Result {trade_number + 1}.1"
            else:
                # Other firms: FD0→HR1.1, FD1→HR1.1, FD2→HR2.1, etc.
                # FD0 is rare for non-MFFU, treat same as FD1
                if trade_number == 0:
                    return "Hedge Result 1.1"
                else:
                    return f"Hedge Result {trade_number}.1"
    
    elif phase_code == 'DD':

    
        # Double Dip: DD1 -> Hedge Result 1.1, DD2 -> Hedge Result 2.1

    
        if trade_number is not None and trade_number >= 1:

    
            return f"Hedge Result {trade_number}.1" 
    
    elif phase_code == 'FA':
        # Farming: Find next available Hedge Day slot
        if eval_idx is not None and evaluations:
            ev = evaluations[eval_idx] if eval_idx < len(evaluations) else {}
            for day_num in range(1, 35):
                field_name = f"Hedge Day {day_num}"
                existing_value = ev.get(field_name)
                if existing_value is None or existing_value == '' or existing_value == 0:
                    return field_name
        # Default to Hedge Day 1 if no slot found
        return "Hedge Day 1"
    
    return None


def update_evaluations_from_aggregated_data(evaluations, aggregated_data):
    """
    Update evaluation hedge result fields from aggregated MT5 comment data.
    
    Args:
        evaluations: List of evaluation records
        aggregated_data: List of aggregated trade data with account_number, phase_code, etc.
    
    Returns:
        Tuple of (updated_evaluations, match_log)
    """
    if not evaluations or not aggregated_data:
        return evaluations, ["No evaluations or aggregated data to process"]
    
    match_log = []
    updates_made = 0
    grouped_aggs = {}
    
    # 1. Group aggregations
    for agg in aggregated_data:
        acc = agg.get('account_number', '')
        phase = agg.get('phase_code', 'UNK')
        if phase == 'FA': trade = 'ALL' 
        else: trade = agg.get('trade_number')
        group_key = (acc, phase, trade)
        if group_key not in grouped_aggs: grouped_aggs[group_key] = []
        grouped_aggs[group_key].append(agg)
        
    # 2. Process groups
    for (account_number, phase, trade_number), agg_list in grouped_aggs.items():
        # Sort by date
        agg_list.sort(key=lambda x: x.get('farming_date') or '')
        
        # Find Matches
        eval_matches = match_account_to_evaluation_all(account_number, evaluations, phase)
        if not eval_matches: continue
            
        # Sort Evaluations by Date
        def get_p_date(eval_tuple):
            ev = evaluations[eval_tuple[0]]
            return str(ev.get('Date Purchased') or ev.get('Date Created') or '')
        eval_matches.sort(key=get_p_date)
        
        # Farming Logic
        if phase == 'FA':
            target_idx, _ = eval_matches[-1] # Use latest
            for current_agg in agg_list:
                amt = current_agg.get('net_profit', 0)
                col = get_next_empty_farming_slot(evaluations[target_idx])
                if col:
                    evaluations[target_idx][col] = amt
                    updates_made += 1
            continue

        # Standard Logic
        eval_ptr = 0
        for agg in agg_list:
            if eval_ptr < len(eval_matches):
                target_tuple = eval_matches[eval_ptr]
                eval_ptr += 1 
            else: target_tuple = eval_matches[-1]
            
            target_idx, account_type = target_tuple
            eff_phase = phase
            eff_trade = agg.get('trade_number')
            if phase == 'UNK':
                eff_phase = 'CH' if account_type == 'challenge' else 'FD'
                eff_trade = 1

            field = get_field_name_for_phase(eff_phase, eff_trade, None, evaluations, target_idx, account_number)
            if field:
                 evaluations[target_idx][field] = agg.get('net_profit', 0)
                 match_log.append(f"✅ Match -> {field}")
                 updates_made += 1
        
    return evaluations, match_log

def get_next_empty_farming_slot(eval_row):
    for i in range(1, 40): 
        col = f"Hedge Day {i}"
        val = eval_row.get(col)
        if not val: return col
    return "Hedge Day 35"

def match_account_to_evaluation_all(account_number, evaluations, phase_code):
    matches = []
    tsig = get_account_signature(account_number)
    tlast5 = get_last_n_digits(account_number, 5)
    
    if phase_code in ['CH', 'UNK']:
        matches.extend(_scan_evals(evaluations, 'Account #', tsig, tlast5, 'challenge'))
    if phase_code != 'CH':
        matches.extend(_scan_evals(evaluations, 'Account #.1', tsig, tlast5, 'funded'))
    return matches

def _scan_evals(evaluations, col_name, tsig, tlast5, label):
    found = []
    for idx, ev in enumerate(evaluations):
        val = str(ev.get(col_name, '')).strip()
        if not val: continue
        if tsig and get_account_signature(val) == tsig:
            found.append((idx, label))
            continue
        ev5 = get_last_n_digits(val, 5)
        if tlast5 and len(tlast5)>=4:
             if ev5 == tlast5 or (len(ev5)>=len(tlast5) and ev5.endswith(tlast5)):
                 found.append((idx, label))
    return found


app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))

# ============ Rate Limiting ============
# Note: For local development, use higher limits. 
# For production, consider: ["200 per day", "50 per hour"]
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["10000 per day", "2000 per hour"],
    storage_uri="memory://"
)

# Initialize Hierarchy from Config
hierarchy = SYSTEM_HIERARCHY


def get_account_signature(account_number):
    """
    Extract account signature for matching: first 4 + last 4/5 digits.
    This handles truncated account numbers in MT5 comments.
    
    Handles truncated format with '...' like: FNFT...59574
    
    Examples:
        MFFUEVSTP326057008 -> mffu7008 (full account)
        FNFT...59574 -> fnft59574 (truncated - keep last 5)
        12345678 -> 12345678
    """
    if not account_number:
        return None
    
    account_str = str(account_number).strip()
    
    # Handle MT5 truncated TopStep format: V2-...SUFFIX
    # This must come before the generic '...' handler to avoid including 'v2-' in the prefix
    if account_str.lower().startswith('v2-...'):
        return account_str.split('...')[-1].lower()

    # Handle TopStep/Dashboard formats: 50KTC-V2-..., EXPRESS-V2-...
    # Extract the last part which is likely the actual account number used in MT5
    if ('-V2-' in account_str) or ('50KTC' in account_str) or ('EXPRESS' in account_str):
        parts = account_str.split('-')
        last_part = parts[-1] 
        # Only treat as account number if it's alphanumeric but mostly digits/lengthy
        # Case: 50KTC-V2-472054-49197160 -> last is 49197160
        if len(parts) > 1:
            account_str = last_part
    
    # Handle truncated format: PREFIX...SUFFIX
    if '...' in account_str:
        parts = account_str.split('...')
        if len(parts) == 2:
            prefix = parts[0][:4] if len(parts[0]) >= 4 else parts[0]
            suffix = parts[1]  # Keep full suffix (usually 5 digits)
            return (prefix + suffix).lower()
    
    # Standard format: first 4 + last 4
    if len(account_str) < 8:
        return account_str.lower()
    
    # First 4 + last 4
    return (account_str[:4] + account_str[-4:]).lower()


def get_last_n_digits(account: str, n: int = 5) -> str:
    """Extract last N digits from account number."""
    if not account:
        return ""
        
    # Handle V2-... prefix exclusion (TopStep) to ensure we get actual account digits
    clean_account = account
    lower_acc = account.lower()
    if lower_acc.startswith('v2-...'):
        clean_account = account.split('...')[-1]
        
    # Extract only digits from the end
    digits = ''.join(c for c in clean_account if c.isdigit())
    return digits[-n:] if len(digits) >= n else digits


def match_account_to_evaluation(account_number, evaluations, phase_code):
    """
    Find matching evaluation for an account number based on phase.
    
    For Challenge (CH): Match against 'Account #' column
    For Funded/DoubleDip/Farming (FD, DD, FA): Match against 'Account #.1' column
    
    Matching strategy:
    1. Try signature match (first4 + last4/5)
    2. Fallback: Try last 5 digits match (for truncated accounts like FNFT...59574)
    """
    if not account_number or not evaluations:
        return None, None
    
    target_sig = get_account_signature(account_number)
    target_last5 = get_last_n_digits(account_number, 5)
    
    if not target_sig and not target_last5:
        return None, None
    
    # Determine which column to check based on phase
    if phase_code == 'CH':
        column_name = 'Account #'  # Challenge accounts
    else:
        column_name = 'Account #.1'  # Funded accounts for FD, DD, FA
    
    # First pass: Try signature match
    for idx, ev in enumerate(evaluations):
        eval_account = str(ev.get(column_name, '')).strip()
        if not eval_account:
            continue
        
        eval_sig = get_account_signature(eval_account)
        if eval_sig == target_sig:
            return idx, eval_account
    
    # Second pass: Try last 5 digits match (for truncated accounts)
    if target_last5:
        # Check against evaluations
        for idx, ev in enumerate(evaluations):
            eval_account = str(ev.get(column_name, '')).strip()
            if not eval_account:
                continue
            
            # Get last 5 digits of evaluation account
            eval_last5 = get_last_n_digits(eval_account, 5)
            
            # Standard exact match of 5 digits
            if len(target_last5) == 5 and eval_last5 == target_last5:
                return idx, eval_account
            
            # Fallback for TopStep: If target is short (4 digits) and matches end of eval
            if len(target_last5) >= 4 and eval_last5.endswith(target_last5):
                 return idx, eval_account
    
    return None, None


def normalize_account_size(value):
    """
    Normalize account size values to standard format: $X,XXX
    
    Handles:
        - "50k", "50K" → "$50,000"
        - "100000", "100,000" → "$100,000"
        - "$50,000" → "$50,000" (already correct)
        - "5000" → "$5,000"
    """
    import re
    if not value:
        return value
    
    val = str(value).strip().upper()
    
    # Already in correct format
    if re.match(r'^\$[\d,]+$', val):
        return value
    
    # Handle "50k" or "50K" format
    match = re.match(r'^[\$]?(\d+\.?\d*)K$', val, re.IGNORECASE)
    if match:
        num = float(match.group(1)) * 1000
        return f"${num:,.0f}"
    
    # Handle plain numbers like "50000" or "50,000"
    val_clean = re.sub(r'[\$,\s]', '', val)
    try:
        num = float(val_clean)
        return f"${num:,.0f}"
    except:
        pass
    
    # Return original if can't parse
    return value


def normalize_evaluations(evaluations):
    """Normalize field values in evaluations list."""
    if not evaluations:
        return evaluations
    
    for ev in evaluations:
        if 'Account Size' in ev and ev['Account Size']:
            ev['Account Size'] = normalize_account_size(ev['Account Size'])
    
    return evaluations


def get_field_name_for_phase(phase_code, trade_number, farming_date, evaluations, eval_idx, account_number=None):
    """
    Determine the correct field name to update based on phase.
    
    Phase mappings:
    - CH1-5: Hedge Result 1-5 (Challenge)
    - FD (MFFU with FD0): FD0→Hedge Result 1, FD1→Hedge Result 2, etc.
    - FD (Other starting FD1): FD1→Hedge Result 1, FD2→Hedge Result 2, etc.
    - DD1-4: Additional funded hedge results
    - FA: Hedge Day N (based on date or next available slot)
    """
    if phase_code == 'CH':
        # Challenge: CH1 → Hedge Result 1, CH2 → Hedge Result 2, etc.
        if trade_number is not None and 1 <= trade_number <= 5:
            return f"Hedge Result {trade_number}"
    
    elif phase_code == 'FD':
        # Determine if this is an MFFU account (uses FD0)
        # MFFU accounts: FD0→HR1.1, FD1→HR2.1, FD2→HR3.1, etc.
        # Other accounts: FD0→HR1.1 (rare), FD1→HR1.1, FD2→HR2.1, etc.
        is_mffu = account_number and account_number.upper().startswith('MFFU')
        
        if trade_number is not None:
            if is_mffu:
                # MFFU: FD0→Hedge Result 1.1, FD1→Hedge Result 2.1, etc.
                return f"Hedge Result {trade_number + 1}.1"
            else:
                # Other firms: FD0→HR1.1, FD1→HR1.1, FD2→HR2.1, etc.
                # FD0 is rare for non-MFFU, treat same as FD1
                if trade_number == 0:
                    return "Hedge Result 1.1"
                else:
                    return f"Hedge Result {trade_number}.1"
    
    elif phase_code == 'DD':

    
        # Double Dip: DD1 -> Hedge Result 1.1, DD2 -> Hedge Result 2.1

    
        if trade_number is not None and trade_number >= 1:

    
            return f"Hedge Result {trade_number}.1" 
    
    elif phase_code == 'FA':
        # Farming: Find next available Hedge Day slot
        if eval_idx is not None and evaluations:
            ev = evaluations[eval_idx] if eval_idx < len(evaluations) else {}
            for day_num in range(1, 35):
                field_name = f"Hedge Day {day_num}"
                existing_value = ev.get(field_name)
                if existing_value is None or existing_value == '' or existing_value == 0:
                    return field_name
        # Default to Hedge Day 1 if no slot found
        return "Hedge Day 1"
    
    return None


def update_evaluations_from_aggregated_data(evaluations, aggregated_data):
    """
    Update evaluation hedge result fields from aggregated MT5 comment data.
    
    Args:
        evaluations: List of evaluation records
        aggregated_data: List of aggregated trade data with account_number, phase_code, etc.
    
    Returns:
        Tuple of (updated_evaluations, match_log)
    """
    if not evaluations or not aggregated_data:
        return evaluations, ["No evaluations or aggregated data to process"]
    
    match_log = []
    updates_made = 0
    grouped_aggs = {}
    
    # 1. Group aggregations
    for agg in aggregated_data:
        acc = agg.get('account_number', '')
        phase = agg.get('phase_code', 'UNK')
        if phase == 'FA': trade = 'ALL' 
        else: trade = agg.get('trade_number')
        group_key = (acc, phase, trade)
        if group_key not in grouped_aggs: grouped_aggs[group_key] = []
        grouped_aggs[group_key].append(agg)
        
    # 2. Process groups
    for (account_number, phase, trade_number), agg_list in grouped_aggs.items():
        # Sort by date
        agg_list.sort(key=lambda x: x.get('farming_date') or '')
        
        # Find Matches
        eval_matches = match_account_to_evaluation_all(account_number, evaluations, phase)
        if not eval_matches: continue
            
        # Sort Evaluations by Date
        def get_p_date(eval_tuple):
            ev = evaluations[eval_tuple[0]]
            return str(ev.get('Date Purchased') or ev.get('Date Created') or '')
        eval_matches.sort(key=get_p_date)
        
        # Farming Logic
        if phase == 'FA':
            target_idx, _ = eval_matches[-1] # Use latest
            for current_agg in agg_list:
                amt = current_agg.get('net_profit', 0)
                col = get_next_empty_farming_slot(evaluations[target_idx])
                if col:
                    evaluations[target_idx][col] = amt
                    updates_made += 1
            continue

        # Standard Logic
        eval_ptr = 0
        for agg in agg_list:
            if eval_ptr < len(eval_matches):
                target_tuple = eval_matches[eval_ptr]
                eval_ptr += 1 
            else: target_tuple = eval_matches[-1]
            
            target_idx, account_type = target_tuple
            eff_phase = phase
            eff_trade = agg.get('trade_number')
            if phase == 'UNK':
                eff_phase = 'CH' if account_type == 'challenge' else 'FD'
                eff_trade = 1

            field = get_field_name_for_phase(eff_phase, eff_trade, None, evaluations, target_idx, account_number)
            if field:
                 evaluations[target_idx][field] = agg.get('net_profit', 0)
                 match_log.append(f"✅ Match -> {field}")
                 updates_made += 1
        
    return evaluations, match_log

def get_next_empty_farming_slot(eval_row):
    for i in range(1, 40): 
        col = f"Hedge Day {i}"
        val = eval_row.get(col)
        if not val: return col
    return "Hedge Day 35"

def match_account_to_evaluation_all(account_number, evaluations, phase_code):
    matches = []
    tsig = get_account_signature(account_number)
    tlast5 = get_last_n_digits(account_number, 5)
    
    if phase_code in ['CH', 'UNK']:
        matches.extend(_scan_evals(evaluations, 'Account #', tsig, tlast5, 'challenge'))
    if phase_code != 'CH':
        matches.extend(_scan_evals(evaluations, 'Account #.1', tsig, tlast5, 'funded'))
    return matches

def _scan_evals(evaluations, col_name, tsig, tlast5, label):
    found = []
    for idx, ev in enumerate(evaluations):
        val = str(ev.get(col_name, '')).strip()
        if not val: continue
        if tsig and get_account_signature(val) == tsig:
            found.append((idx, label))
            continue
        ev5 = get_last_n_digits(val, 5)
        if tlast5 and len(tlast5)>=4:
             if ev5 == tlast5 or (len(ev5)>=len(tlast5) and ev5.endswith(tlast5)):
                 found.append((idx, label))
    return found


app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))

# ============ Rate Limiting ============
# Note: For local development, use higher limits. 
# For production, consider: ["200 per day", "50 per hour"]
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["10000 per day", "2000 per hour"],
    storage_uri="memory://"
)

# Initialize Hierarchy from Config
hierarchy = SYSTEM_HIERARCHY


def get_account_signature(account_number):
    """
    Extract account signature for matching: first 4 + last 4/5 digits.
    This handles truncated account numbers in MT5 comments.
    
    Handles truncated format with '...' like: FNFT...59574
    
    Examples:
        MFFUEVSTP326057008 -> mffu7008 (full account)
        FNFT...59574 -> fnft59574 (truncated - keep last 5)
        12345678 -> 12345678
    """
    if not account_number:
        return None
    
    account_str = str(account_number).strip()
    
    # Handle MT5 truncated TopStep format: V2-...SUFFIX
    # This must come before the generic '...' handler to avoid including 'v2-' in the prefix
    if account_str.lower().startswith('v2-...'):
        return account_str.split('...')[-1].lower()

    # Handle TopStep/Dashboard formats: 50KTC-V2-..., EXPRESS-V2-...
    # Extract the last part which is likely the actual account number used in MT5
    if ('-V2-' in account_str) or ('50KTC' in account_str) or ('EXPRESS' in account_str):
        parts = account_str.split('-')
        last_part = parts[-1] 
        # Only treat as account number if it's alphanumeric but mostly digits/lengthy
        # Case: 50KTC-V2-472054-49197160 -> last is 49197160
        if len(parts) > 1:
            account_str = last_part
    
    # Handle truncated format: PREFIX...SUFFIX
    if '...' in account_str:
        parts = account_str.split('...')
        if len(parts) == 2:
            prefix = parts[0][:4] if len(parts[0]) >= 4 else parts[0]
            suffix = parts[1]  # Keep full suffix (usually 5 digits)
            return (prefix + suffix).lower()
    
    # Standard format: first 4 + last 4
    if len(account_str) < 8:
        return account_str.lower()
    
    # First 4 + last 4
    return (account_str[:4] + account_str[-4:]).lower()


def get_last_n_digits(account: str, n: int = 5) -> str:
    """Extract last N digits from account number."""
    if not account:
        return ""
        
    # Handle V2-... prefix exclusion (TopStep) to ensure we get actual account digits
    clean_account = account
    lower_acc = account.lower()
    if lower_acc.startswith('v2-...'):
        clean_account = account.split('...')[-1]
        
    # Extract only digits from the end
    digits = ''.join(c for c in clean_account if c.isdigit())
    return digits[-n:] if len(digits) >= n else digits


def match_account_to_evaluation(account_number, evaluations, phase_code):
    """
    Find matching evaluation for an account number based on phase.
    
    For Challenge (CH): Match against 'Account #' column
    For Funded/DoubleDip/Farming (FD, DD, FA): Match against 'Account #.1' column
    
    Matching strategy:
    1. Try signature match (first4 + last4/5)
    2. Fallback: Try last 5 digits match (for truncated accounts like FNFT...59574)
    """
    if not account_number or not evaluations:
        return None, None
    
    target_sig = get_account_signature(account_number)
    target_last5 = get_last_n_digits(account_number, 5)
    
    if not target_sig and not target_last5:
        return None, None
    
    # Determine which column to check based on phase
    if phase_code == 'CH':
        column_name = 'Account #'  # Challenge accounts
    else:
        column_name = 'Account #.1'  # Funded accounts for FD, DD, FA
    
    # First pass: Try signature match
    for idx, ev in enumerate(evaluations):
        eval_account = str(ev.get(column_name, '')).strip()
        if not eval_account:
            continue
        
        eval_sig = get_account_signature(eval_account)
        if eval_sig == target_sig:
            return idx, eval_account
    
    # Second pass: Try last 5 digits match (for truncated accounts)
    if target_last5:
        # Check against evaluations
        for idx, ev in enumerate(evaluations):
            eval_account = str(ev.get(column_name, '')).strip()
            if not eval_account:
                continue
            
            # Get last 5 digits of evaluation account
            eval_last5 = get_last_n_digits(eval_account, 5)
            
            # Standard exact match of 5 digits
            if len(target_last5) == 5 and eval_last5 == target_last5:
                return idx, eval_account
            
            # Fallback for TopStep: If target is short (4 digits) and matches end of eval
            if len(target_last5) >= 4 and eval_last5.endswith(target_last5):
                 return idx, eval_account
    
    return None, None


def normalize_account_size(value):
    """
    Normalize account size values to standard format: $X,XXX
    
    Handles:
        - "50k", "50K" → "$50,000"
        - "100000", "100,000" → "$100,000"
        - "$50,000" → "$50,000" (already correct)
        - "5000" → "$5,000"
    """
    import re
    if not value:
        return value
    
    val = str(value).strip().upper()
    
    # Already in correct format
    if re.match(r'^\$[\d,]+$', val):
        return value
    
    # Handle "50k" or "50K" format
    match = re.match(r'^[\$]?(\d+\.?\d*)K$', val, re.IGNORECASE)
    if match:
        num = float(match.group(1)) * 1000
        return f"${num:,.0f}"
    
    # Handle plain numbers like "50000" or "50,000"
    val_clean = re.sub(r'[\$,\s]', '', val)
    try:
        num = float(val_clean)
        return f"${num:,.0f}"
    except:
        pass
    
    # Return original if can't parse
    return value


def normalize_evaluations(evaluations):
    """Normalize field values in evaluations list."""
    if not evaluations:
        return evaluations
    
    for ev in evaluations:
        if 'Account Size' in ev and ev['Account Size']:
            ev['Account Size'] = normalize_account_size(ev['Account Size'])
    
    return evaluations


def get_field_name_for_phase(phase_code, trade_number, farming_date, evaluations, eval_idx, account_number=None):
    """
    Determine the correct field name to update based on phase.
    
    Phase mappings:
    - CH1-5: Hedge Result 1-5 (Challenge)
    - FD (MFFU with FD0): FD0→Hedge Result 1, FD1→Hedge Result 2, etc.
    - FD (Other starting FD1): FD1→Hedge Result 1, FD2→Hedge Result 2, etc.
    - DD1-4: Additional funded hedge results
    - FA: Hedge Day N (based on date or next available slot)
    """
    if phase_code == 'CH':
        # Challenge: CH1 → Hedge Result 1, CH2 → Hedge Result 2, etc.
        if trade_number is not None and 1 <= trade_number <= 5:
            return f"Hedge Result {trade_number}"
    
    elif phase_code == 'FD':
        # Determine if this is an MFFU account (uses FD0)
        # MFFU accounts: FD0→HR1.1, FD1→HR2.1, FD2→HR3.1, etc.
        # Other accounts: FD0→HR1.1 (rare), FD1→HR1.1, FD2→HR2.1, etc.
        is_mffu = account_number and account_number.upper().startswith('MFFU')
        
        if trade_number is not None:
            if is_mffu:
                # MFFU: FD0→Hedge Result 1.1, FD1→Hedge Result 2.1, etc.
                return f"Hedge Result {trade_number + 1}.1"
            else:
                # Other firms: FD0→HR1.1, FD1→HR1.1, FD2→HR2.1, etc.
                # FD0 is rare for non-MFFU, treat same as FD1
                if trade_number == 0:
                    return "Hedge Result 1.1"
                else:
                    return f"Hedge Result {trade_number}.1"
    
    elif phase_code == 'DD':

    
        # Double Dip: DD1 -> Hedge Result 1.1, DD2 -> Hedge Result 2.1

    
        if trade_number is not None and trade_number >= 1:

    
            return f"Hedge Result {trade_number}.1" 
    
    elif phase_code == 'FA':
        # Farming: Find next available Hedge Day slot
        if eval_idx is not None and evaluations:
            ev = evaluations[eval_idx] if eval_idx < len(evaluations) else {}
            for day_num in range(1, 35):
                field_name = f"Hedge Day {day_num}"
                existing_value = ev.get(field_name)
                if existing_value is None or existing_value == '' or existing_value == 0:
                    return field_name
        # Default to Hedge Day 1 if no slot found
        return "Hedge Day 1"
    
    return None


def update_evaluations_from_aggregated_data(evaluations, aggregated_data):
    """
    Update evaluation hedge result fields from aggregated MT5 comment data.
    
    Args:
        evaluations: List of evaluation records
        aggregated_data: List of aggregated trade data with account_number, phase_code, etc.
    
    Returns:
        Tuple of (updated_evaluations, match_log)
    """
    if not evaluations or not aggregated_data:
        return evaluations, ["No evaluations or aggregated data to process"]
    
    match_log = []
    updates_made = 0
    grouped_aggs = {}
    
    # 1. Group aggregations
    for agg in aggregated_data:
        acc = agg.get('account_number', '')
        phase = agg.get('phase_code', 'UNK')
        if phase == 'FA': trade = 'ALL' 
        else: trade = agg.get('trade_number')
        group_key = (acc, phase, trade)
        if group_key not in grouped_aggs: grouped_aggs[group_key] = []
        grouped_aggs[group_key].append(agg)
        
    # 2. Process groups
    for (account_number, phase, trade_number), agg_list in grouped_aggs.items():
        # Sort by date
        agg_list.sort(key=lambda x: x.get('farming_date') or '')
        
        # Find Matches
        eval_matches = match_account_to_evaluation_all(account_number, evaluations, phase)
        if not eval_matches: continue
            
        # Sort Evaluations by Date
        def get_p_date(eval_tuple):
            ev = evaluations[eval_tuple[0]]
            return str(ev.get('Date Purchased') or ev.get('Date Created') or '')
        eval_matches.sort(key=get_p_date)
        
        # Farming Logic
        if phase == 'FA':
            target_idx, _ = eval_matches[-1] # Use latest
            for current_agg in agg_list:
                amt = current_agg.get('net_profit', 0)
                col = get_next_empty_farming_slot(evaluations[target_idx])
                if col:
                    evaluations[target_idx][col] = amt
                    updates_made += 1
            continue

        # Standard Logic
        eval_ptr = 0
        for agg in agg_list:
            if eval_ptr < len(eval_matches):
                target_tuple = eval_matches[eval_ptr]
                eval_ptr += 1 
            else: target_tuple = eval_matches[-1]
            
            target_idx, account_type = target_tuple
            eff_phase = phase
            eff_trade = agg.get('trade_number')
            if phase == 'UNK':
                eff_phase = 'CH' if account_type == 'challenge' else 'FD'
                eff_trade = 1

            field = get_field_name_for_phase(eff_phase, eff_trade, None, evaluations, target_idx, account_number)
            if field:
                 evaluations[target_idx][field] = agg.get('net_profit', 0)
                 match_log.append(f"✅ Match -> {field}")
                 updates_made += 1
        
    return evaluations, match_log

def get_next_empty_farming_slot(eval_row):
    for i in range(1, 40): 
        col = f"Hedge Day {i}"
        val = eval_row.get(col)
        if not val: return col
    return "Hedge Day 35"

def match_account_to_evaluation_all(account_number, evaluations, phase_code):
    matches = []
    tsig = get_account_signature(account_number)
    tlast5 = get_last_n_digits(account_number, 5)
    
    if phase_code in ['CH', 'UNK']:
        matches.extend(_scan_evals(evaluations, 'Account #', tsig, tlast5, 'challenge'))
    if phase_code != 'CH':
        matches.extend(_scan_evals(evaluations, 'Account #.1', tsig, tlast5, 'funded'))
    return matches

def _scan_evals(evaluations, col_name, tsig, tlast5, label):
    found = []
    for idx, ev in enumerate(evaluations):
        val = str(ev.get(col_name, '')).strip()
        if not val: continue
        if tsig and get_account_signature(val) == tsig:
            found.append((idx, label))
            continue
        ev5 = get_last_n_digits(val, 5)
        if tlast5 and len(tlast5)>=4:
             if ev5 == tlast5 or (len(ev5)>=len(tlast5) and ev5.endswith(tlast5)):
                 found.append((idx, label))
    return found


app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))

# ============ Rate Limiting ============
# Note: For local development, use higher limits. 
# For production, consider: ["200 per day", "50 per hour"]
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["10000 per day", "2000 per hour"],
    storage_uri="memory://"
)

# Initialize Hierarchy from Config
hierarchy = SYSTEM_HIERARCHY


def get_account_signature(account_number):
    """
    Extract account signature for matching: first 4 + last 4/5 digits.
    This handles truncated account numbers in MT5 comments.
    
    Handles truncated format with '...' like: FNFT...59574
    
    Examples:
        MFFUEVSTP326057008 -> mffu7008 (full account)
        FNFT...59574 -> fnft59574 (truncated - keep last 5)
        12345678 -> 12345678
    """
    if not account_number:
        return None
    
    account_str = str(account_number).strip()
    
    # Handle MT5 truncated TopStep format: V2-...SUFFIX
    # This must come before the generic '...' handler to avoid including 'v2-' in the prefix
    if account_str.lower().startswith('v2-...'):
        return account_str.split('...')[-1].lower()

    # Handle TopStep/Dashboard formats: 50KTC-V2-..., EXPRESS-V2-...
    # Extract the last part which is likely the actual account number used in MT5
    if ('-V2-' in account_str) or ('50KTC' in account_str) or ('EXPRESS' in account_str):
        parts = account_str.split('-')
        last_part = parts[-1] 
        # Only treat as account number if it's alphanumeric but mostly digits/lengthy
        # Case: 50KTC-V2-472054-49197160 -> last is 49197160
        if len(parts) > 1:
            account_str = last_part
    
    # Handle truncated format: PREFIX...SUFFIX
    if '...' in account_str:
        parts = account_str.split('...')
        if len(parts) == 2:
            prefix = parts[0][:4] if len(parts[0]) >= 4 else parts[0]
            suffix = parts[1]  # Keep full suffix (usually 5 digits)
            return (prefix + suffix).lower()
    
    # Standard format: first 4 + last 4
    if len(account_str) < 8:
        return account_str.lower()
    
    # First 4 + last 4
    return (account_str[:4] + account_str[-4:]).lower()


def get_last_n_digits(account: str, n: int = 5) -> str:
    """Extract last N digits from account number."""
    if not account:
        return ""
        
    # Handle V2-... prefix exclusion (TopStep) to ensure we get actual account digits
    clean_account = account
    lower_acc = account.lower()
    if lower_acc.startswith('v2-...'):
        clean_account = account.split('...')[-1]
        
    # Extract only digits from the end
    digits = ''.join(c for c in clean_account if c.isdigit())
    return digits[-n:] if len(digits) >= n else digits


def match_account_to_evaluation(account_number, evaluations, phase_code):
    """
    Find matching evaluation for an account number based on phase.
    
    For Challenge (CH): Match against 'Account #' column
    For Funded/DoubleDip/Farming (FD, DD, FA): Match against 'Account #.1' column
    
    Matching strategy:
    1. Try signature match (first4 + last4/5)
    2. Fallback: Try last 5 digits match (for truncated accounts like FNFT...59574)
    """
    if not account_number or not evaluations:
        return None, None
    
    target_sig = get_account_signature(account_number)
    target_last5 = get_last_n_digits(account_number, 5)
    
    if not target_sig and not target_last5:
        return None, None
    
    # Determine which column to check based on phase
    if phase_code == 'CH':
        column_name = 'Account #'  # Challenge accounts
    else:
        column_name = 'Account #.1'  # Funded accounts for FD, DD, FA
    
    # First pass: Try signature match
    for idx, ev in enumerate(evaluations):
        eval_account = str(ev.get(column_name, '')).strip()
        if not eval_account:
            continue
        
        eval_sig = get_account_signature(eval_account)
        if eval_sig == target_sig:
            return idx, eval_account
    
    # Second pass: Try last 5 digits match (for truncated accounts)
    if target_last5:
        # Check against evaluations
        for idx, ev in enumerate(evaluations):
            eval_account = str(ev.get(column_name, '')).strip()
            if not eval_account:
                continue
            
            # Get last 5 digits of evaluation account
            eval_last5 = get_last_n_digits(eval_account, 5)
            
            # Standard exact match of 5 digits
            if len(target_last5) == 5 and eval_last5 == target_last5:
                return idx, eval_account
            
            # Fallback for TopStep: If target is short (4 digits) and matches end of eval
            if len(target_last5) >= 4 and eval_last5.endswith(target_last5):
                 return idx, eval_account
    
    return None, None


def normalize_account_size(value):
    """
    Normalize account size values to standard format: $X,XXX
    
    Handles:
        - "50k", "50K" → "$50,000"
        - "100000", "100,000" → "$100,000"
        - "$50,000" → "$50,000" (already correct)
        - "5000" → "$5,000"
    """
    import re
    if not value:
        return value
    
    val = str(value).strip().upper()
    
    # Already in correct format
    if re.match(r'^\$[\d,]+$', val):
        return value
    
    # Handle "50k" or "50K" format
    match = re.match(r'^[\$]?(\d+\.?\d*)K$', val, re.IGNORECASE)
    if match:
        num = float(match.group(1)) * 1000
        return f"${num:,.0f}"
    
    # Handle plain numbers like "50000" or "50,000"
    val_clean = re.sub(r'[\$,\s]', '', val)
    try:
        num = float(val_clean)
        return f"${num:,.0f}"
    except:
        pass
    
    # Return original if can't parse
    return value


def normalize_evaluations(evaluations):
    """Normalize field values in evaluations list."""
    if not evaluations:
        return evaluations
    
    for ev in evaluations:
        if 'Account Size' in ev and ev['Account Size']:
            ev['Account Size'] = normalize_account_size(ev['Account Size'])
    
    return evaluations


def get_field_name_for_phase(phase_code, trade_number, farming_date, evaluations, eval_idx, account_number=None):
    """
    Determine the correct field name to update based on phase.
    
    Phase mappings:
    - CH1-5: Hedge Result 1-5 (Challenge)
    - FD (MFFU with FD0): FD0→Hedge Result 1, FD1→Hedge Result 2, etc.
    - FD (Other starting FD1): FD1→Hedge Result 1, FD2→Hedge Result 2, etc.
    - DD1-4: Additional funded hedge results
    - FA: Hedge Day N (based on date or next available slot)
    """
    if phase_code == 'CH':
        # Challenge: CH1 → Hedge Result 1, CH2 → Hedge Result 2, etc.
        if trade_number is not None and 1 <= trade_number <= 5:
            return f"Hedge Result {trade_number}"
    
    elif phase_code == 'FD':
        # Determine if this is an MFFU account (uses FD0)
        # MFFU accounts: FD0→HR1.1, FD1→HR2.1, FD2→HR3.1, etc.
        # Other accounts: FD0→HR1.1 (rare), FD1→HR1.1, FD2→HR2.1, etc.
        is_mffu = account_number and account_number.upper().startswith('MFFU')
        
        if trade_number is not None:
            if is_mffu:
                # MFFU: FD0→Hedge Result 1.1, FD1→Hedge Result 2.1, etc.
                return f"Hedge Result {trade_number + 1}.1"
            else:
                # Other firms: FD0→HR1.1, FD1→HR1.1, FD2→HR2.1, etc.
                # FD0 is rare for non-MFFU, treat same as FD1
                if trade_number == 0:
                    return "Hedge Result 1.1"
                else:
                    return f"Hedge Result {trade_number}.1"
    
    elif phase_code == 'DD':

    
        # Double Dip: DD1 -> Hedge Result 1.1, DD2 -> Hedge Result 2.1

    
        if trade_number is not None and trade_number >= 1:

    
            return f"Hedge Result {trade_number}.1" 
    
    elif phase_code == 'FA':
        # Farming: Find next available Hedge Day slot
        if eval_idx is not None and evaluations:
            ev = evaluations[eval_idx] if eval_idx < len(evaluations) else {}
            for day_num in range(1, 35):
                field_name = f"Hedge Day {day_num}"
                existing_value = ev.get(field_name)
                if existing_value is None or existing_value == '' or existing_value == 0:
                    return field_name
        # Default to Hedge Day 1 if no slot found
        return "Hedge Day 1"
    
    return None


def update_evaluations_from_aggregated_data(evaluations, aggregated_data):
    """
    Update evaluation hedge result fields from aggregated MT5 comment data.
    
    Args:
        evaluations: List of evaluation records
        aggregated_data: List of aggregated trade data with account_number, phase_code, etc.
    
    Returns:
        Tuple of (updated_evaluations, match_log)
    """
    if not evaluations or not aggregated_data:
        return evaluations, ["No evaluations or aggregated data to process"]
    
    match_log = []
    updates_made = 0
    grouped_aggs = {}
    
    # 1. Group aggregations
    for agg in aggregated_data:
        acc = agg.get('account_number', '')
        phase = agg.get('phase_code', 'UNK')
        if phase == 'FA': trade = 'ALL' 
        else: trade = agg.get('trade_number')
        group_key = (acc, phase, trade)
        if group_key not in grouped_aggs: grouped_aggs[group_key] = []
        grouped_aggs[group_key].append(agg)
        
    # 2. Process groups
    for (account_number, phase, trade_number), agg_list in grouped_aggs.items():
        # Sort by date
        agg_list.sort(key=lambda x: x.get('farming_date') or '')
        
        # Find Matches
        eval_matches = match_account_to_evaluation_all(account_number, evaluations, phase)
        if not eval_matches: continue
            
        # Sort Evaluations by Date
        def get_p_date(eval_tuple):
            ev = evaluations[eval_tuple[0]]
            return str(ev.get('Date Purchased') or ev.get('Date Created') or '')
        eval_matches.sort(key=get_p_date)
        
        # Farming Logic
        if phase == 'FA':
            target_idx, _ = eval_matches[-1] # Use latest
            for current_agg in agg_list:
                amt = current_agg.get('net_profit', 0)
                col = get_next_empty_farming_slot(evaluations[target_idx])
                if col:
                    evaluations[target_idx][col] = amt
                    updates_made += 1
            continue

        # Standard Logic
        eval_ptr = 0
        for agg in agg_list:
            if eval_ptr < len(eval_matches):
                target_tuple = eval_matches[eval_ptr]
                eval_ptr += 1 
            else: target_tuple = eval_matches[-1]
            
            target_idx, account_type = target_tuple
            eff_phase = phase
            eff_trade = agg.get('trade_number')
            if phase == 'UNK':
                eff_phase = 'CH' if account_type == 'challenge' else 'FD'
                eff_trade = 1

            field = get_field_name_for_phase(eff_phase, eff_trade, None, evaluations, target_idx, account_number)
            if field:
                 evaluations[target_idx][field] = agg.get('net_profit', 0)
                 match_log.append(f"✅ Match -> {field}")
                 updates_made += 1
        
    return evaluations, match_log

def get_next_empty_farming_slot(eval_row):
    for i in range(1, 40): 
        col = f"Hedge Day {i}"
        val = eval_row.get(col)
        if not val: return col
    return "Hedge Day 35"

def match_account_to_evaluation_all(account_number, evaluations, phase_code):
    matches = []
    tsig = get_account_signature(account_number)
    tlast5 = get_last_n_digits(account_number, 5)
    
    if phase_code in ['CH', 'UNK']:
        matches.extend(_scan_evals(evaluations, 'Account #', tsig, tlast5, 'challenge'))
    if phase_code != 'CH':
        matches.extend(_scan_evals(evaluations, 'Account #.1', tsig, tlast5, 'funded'))
    return matches

def _scan_evals(evaluations, col_name, tsig, tlast5, label):
    found = []
    for idx, ev in enumerate(evaluations):
        val = str(ev.get(col_name, '')).strip()
        if not val: continue
        if tsig and get_account_signature(val) == tsig:
            found.append((idx, label))
            continue
        ev5 = get_last_n_digits(val, 5)
        if tlast5 and len(tlast5)>=4:
             if ev5 == tlast5 or (len(ev5)>=len(tlast5) and ev5.endswith(tlast5)):
                 found.append((idx, label))
    return found


app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))

# ============ Rate Limiting ============
# Note: For local development, use higher limits. 
# For production, consider: ["200 per day", "50 per hour"]
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["10000 per day", "2000 per hour"],
    storage_uri="memory://"
)

# Initialize Hierarchy from Config
hierarchy = SYSTEM_HIERARCHY


def get_account_signature(account_number):
    """
    Extract account signature for matching: first 4 + last 4/5 digits.
    This handles truncated account numbers in MT5 comments.
    
    Handles truncated format with '...' like: FNFT...59574
    
    Examples:
        MFFUEVSTP326057008 -> mffu7008 (full account)
        FNFT...59574 -> fnft59574 (truncated - keep last 5)
        12345678 -> 12345678
    """
    if not account_number:
        return None
    
    account_str = str(account_number).strip()
    
    # Handle MT5 truncated TopStep format: V2-...SUFFIX
    # This must come before the generic '...' handler to avoid including 'v2-' in the prefix
    if account_str.lower().startswith('v2-...'):
        return account_str.split('...')[-1].lower()

    # Handle TopStep/Dashboard formats: 50KTC-V2-..., EXPRESS-V2-...
    # Extract the last part which is likely the actual account number used in MT5
    if ('-V2-' in account_str) or ('50KTC' in account_str) or ('EXPRESS' in account_str):
        parts = account_str.split('-')
        last_part = parts[-1] 
        # Only treat as account number if it's alphanumeric but mostly digits/lengthy
        # Case: 50KTC-V2-472054-49197160 -> last is 49197160
        if len(parts) > 1:
            account_str = last_part
    
    # Handle truncated format: PREFIX...SUFFIX
    if '...' in account_str:
        parts = account_str.split('...')
        if len(parts) == 2:
            prefix = parts[0][:4] if len(parts[0]) >= 4 else parts[0]
            suffix = parts[1]  # Keep full suffix (usually 5 digits)
            return (prefix + suffix).lower()
    
    # Standard format: first 4 + last 4
    if len(account_str) < 8:
        return account_str.lower()
    
    # First 4 + last 4
    return (account_str[:4] + account_str[-4:]).lower()


def get_last_n_digits(account: str, n: int = 5) -> str:
    """Extract last N digits from account number."""
    if not account:
        return ""
        
    # Handle V2-... prefix exclusion (TopStep) to ensure we get actual account digits
    clean_account = account
    lower_acc = account.lower()
    if lower_acc.startswith('v2-...'):
        clean_account = account.split('...')[-1]
        
    # Extract only digits from the end
    digits = ''.join(c for c in clean_account if c.isdigit())
    return digits[-n:] if len(digits) >= n else digits


def match_account_to_evaluation(account_number, evaluations, phase_code):
    """
    Find matching evaluation for an account number based on phase.
    
    For Challenge (CH): Match against 'Account #' column
    For Funded/DoubleDip/Farming (FD, DD, FA): Match against 'Account #.1' column
    
    Matching strategy:
    1. Try signature match (first4 + last4/5)
    2. Fallback: Try last 5 digits match (for truncated accounts like FNFT...59574)
    """
    if not account_number or not evaluations:
        return None, None
    
    target_sig = get_account_signature(account_number)
    target_last5 = get_last_n_digits(account_number, 5)
    
    if not target_sig and not target_last5:
        return None, None
    
    # Determine which column to check based on phase
    if phase_code == 'CH':
        column_name = 'Account #'  # Challenge accounts
    else:
        column_name = 'Account #.1'  # Funded accounts for FD, DD, FA
    
    # First pass: Try signature match
    for idx, ev in enumerate(evaluations):
        eval_account = str(ev.get(column_name, '')).strip()
        if not eval_account:
            continue
        
        eval_sig = get_account_signature(eval_account)
        if eval_sig == target_sig:
            return idx, eval_account
    
    # Second pass: Try last 5 digits match (for truncated accounts)
    if target_last5:
        # Check against evaluations
        for idx, ev in enumerate(evaluations):
            eval_account = str(ev.get(column_name, '')).strip()
            if not eval_account:
                continue
            
            # Get last 5 digits of evaluation account
            eval_last5 = get_last_n_digits(eval_account, 5)
            
            # Standard exact match of 5 digits
            if len(target_last5) == 5 and eval_last5 == target_last5:
                return idx, eval_account
            
            # Fallback for TopStep: If target is short (4 digits) and matches end of eval
            if len(target_last5) >= 4 and eval_last5.endswith(target_last5):
                 return idx, eval_account
    
    return None, None


def normalize_account_size(value):
    """
    Normalize account size values to standard format: $X,XXX
    
    Handles:
        - "50k", "50K" → "$50,000"
        - "100000", "100,000" → "$100,000"
        - "$50,000" → "$50,000" (already correct)
        - "5000" → "$5,000"
    """
    import re
    if not value:
        return value
    
    val = str(value).strip().upper()
    
    # Already in correct format
    if re.match(r'^\$[\d,]+$', val):
        return value
    
    # Handle "50k" or "50K" format
    match = re.match(r'^[\$]?(\d+\.?\d*)K$', val, re.IGNORECASE)
    if match:
        num = float(match.group(1)) * 1000
        return f"${num:,.0f}"
    
    # Handle plain numbers like "50000" or "50,000"
    val_clean = re.sub(r'[\$,\s]', '', val)
    try:
        num = float(val_clean)
        return f"${num:,.0f}"
    except:
        pass
    
    # Return original if can't parse
    return value


def normalize_evaluations(evaluations):
    """Normalize field values in evaluations list."""
    if not evaluations:
        return evaluations
    
    for ev in evaluations:
        if 'Account Size' in ev and ev['Account Size']:
            ev['Account Size'] = normalize_account_size(ev['Account Size'])
    
    return evaluations


def get_field_name_for_phase(phase_code, trade_number, farming_date, evaluations, eval_idx, account_number=None):
    """
    Determine the correct field name to update based on phase.
    
    Phase mappings:
    - CH1-5: Hedge Result 1-5 (Challenge)
    - FD (MFFU with FD0): FD0→Hedge Result 1, FD1→Hedge Result 2, etc.
    - FD (Other starting FD1): FD1→Hedge Result 1, FD2→Hedge Result 2, etc.
    - DD1-4: Additional funded hedge results
    - FA: Hedge Day N (based on date or next available slot)
    """
    if phase_code == 'CH':
        # Challenge: CH1 → Hedge Result 1, CH2 → Hedge Result 2, etc.
        if trade_number is not None and 1 <= trade_number <= 5:
            return f"Hedge Result {trade_number}"
    
    elif phase_code == 'FD':
        # Determine if this is an MFFU account (uses FD0)
        # MFFU accounts: FD0→HR1.1, FD1→HR2.1, FD2→HR3.1, etc.
        # Other accounts: FD0→HR1.1 (rare), FD1→HR1.1, FD2→HR2.1, etc.
        is_mffu = account_number and account_number.upper().startswith('MFFU')
        
        if trade_number is not None:
            if is_mffu:
                # MFFU: FD0→Hedge Result 1.1, FD1→Hedge Result 2.1, etc.
                return f"Hedge Result {trade_number + 1}.1"
            else:
                # Other firms: FD0→HR1.1, FD1→HR1.1, FD2→HR2.1, etc.
                # FD0 is rare for non-MFFU, treat same as FD1
                if trade_number == 0:
                    return "Hedge Result 1.1"
                else:
                    return f"Hedge Result {trade_number}.1"
    
    elif phase_code == 'DD':

    
        # Double Dip: DD1 -> Hedge Result 1.1, DD2 -> Hedge Result 2.1

    
        if trade_number is not None and trade_number >= 1:

    
            return f"Hedge Result {trade_number}.1" 
    
    elif phase_code == 'FA':
        # Farming: Find next available Hedge Day slot
        if eval_idx is not None and evaluations:
            ev = evaluations[eval_idx] if eval_idx < len(evaluations) else {}
            for day_num in range(1, 35):
                field_name = f"Hedge Day {day_num}"
                existing_value = ev.get(field_name)
                if existing_value is None or existing_value == '' or existing_value == 0:
                    return field_name
        # Default to Hedge Day 1 if no slot found
        return "Hedge Day 1"
    
    return None


def update_evaluations_from_aggregated_data(evaluations, aggregated_data):
    """
    Update evaluation hedge result fields from aggregated MT5 comment data.
    
    Args:
        evaluations: List of evaluation records
        aggregated_data: List of aggregated trade data with account_number, phase_code, etc.
    
    Returns:
        Tuple of (updated_evaluations, match_log)
    """
    if not evaluations or not aggregated_data:
        return evaluations, ["No evaluations or aggregated data to process"]
    
    match_log = []
    updates_made = 0
    grouped_aggs = {}
    
    # 1. Group aggregations
    for agg in aggregated_data:
        acc = agg.get('account_number', '')
        phase = agg.get('phase_code', 'UNK')
        if phase == 'FA': trade = 'ALL' 
        else: trade = agg.get('trade_number')
        group_key = (acc, phase, trade)
        if group_key not in grouped_aggs: grouped_aggs[group_key] = []
        grouped_aggs[group_key].append(agg)
        
    # 2. Process groups
    for (account_number, phase, trade_number), agg_list in grouped_aggs.items():
        # Sort by date
        agg_list.sort(key=lambda x: x.get('farming_date') or '')
        
        # Find Matches
        eval_matches = match_account_to_evaluation_all(account_number, evaluations, phase)
        if not eval_matches: continue
            
        # Sort Evaluations by Date
        def get_p_date(eval_tuple):
            ev = evaluations[eval_tuple[0]]
            return str(ev.get('Date Purchased') or ev.get('Date Created') or '')
        eval_matches.sort(key=get_p_date)
        
        # Farming Logic
        if phase == 'FA':
            target_idx, _ = eval_matches[-1] # Use latest
            for current_agg in agg_list:
                amt = current_agg.get('net_profit', 0)
                col = get_next_empty_farming_slot(evaluations[target_idx])
                if col:
                    evaluations[target_idx][col] = amt
                    updates_made += 1
            continue

        # Standard Logic
        eval_ptr = 0
        for agg in agg_list:
            if eval_ptr < len(eval_matches):
                target_tuple = eval_matches[eval_ptr]
                eval_ptr += 1 
            else: target_tuple = eval_matches[-1]
            
            target_idx, account_type = target_tuple
            eff_phase = phase
            eff_trade = agg.get('trade_number')
            if phase == 'UNK':
                eff_phase = 'CH' if account_type == 'challenge' else 'FD'
                eff_trade = 1

            field = get_field_name_for_phase(eff_phase, eff_trade, None, evaluations, target_idx, account_number)
            if field:
                 evaluations[target_idx][field] = agg.get('net_profit', 0)
                 match_log.append(f"✅ Match -> {field}")
                 updates_made += 1
        
    return evaluations, match_log

def get_next_empty_farming_slot(eval_row):
    for i in range(1, 40): 
        col = f"Hedge Day {i}"
        val = eval_row.get(col)
        if not val: return col
    return "Hedge Day 35"

def match_account_to_evaluation_all(account_number, evaluations, phase_code):
    matches = []
    tsig = get_account_signature(account_number)
    tlast5 = get_last_n_digits(account_number, 5)
    
    if phase_code in ['CH', 'UNK']:
        matches.extend(_scan_evals(evaluations, 'Account #', tsig, tlast5, 'challenge'))
    if phase_code != 'CH':
        matches.extend(_scan_evals(evaluations, 'Account #.1', tsig, tlast5, 'funded'))
    return matches

def _scan_evals(evaluations, col_name, tsig, tlast5, label):
    found = []
    for idx, ev in enumerate(evaluations):
        val = str(ev.get(col_name, '')).strip()
        if not val: continue
        if tsig and get_account_signature(val) == tsig:
            found.append((idx, label))
            continue
        ev5 = get_last_n_digits(val, 5)
        if tlast5 and len(tlast5)>=4:
             if ev5 == tlast5 or (len(ev5)>=len(tlast5) and ev5.endswith(tlast5)):
                 found.append((idx, label))
    return found
