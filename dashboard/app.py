from flask import Flask, render_template, jsonify, request, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import threading
import json
import os
import sys
import logging

# Add project root to sys.path to import config and dashboard modules properly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from functools import wraps
import secrets
import hashlib
import re
from datetime import datetime, timedelta
from dashboard.financial_overview import calculate_propfirm_overview, get_payouts_history, get_portfolio_growth_data, get_payouts_growth_data, get_cumulative_deposits, get_cumulative_trading_profit, get_cumulative_fees_data, get_cumulative_hedge_data, get_cumulative_farming_data, calculate_trader_stats, parse_date, get_cached_clients_dataset, calculate_all_financials, get_client_performance_stats

from config.hierarchy import (
    SYSTEM_HIERARCHY, add_admin, add_trader, add_client, 
    update_admin_details, update_trader_details, update_client_details, update_client_category,
    get_client_by_email, get_user_by_email,
    remove_admin, remove_trader, remove_client,
    move_client, move_trader,
    rename_admin, rename_trader, rename_client
)

# Import database module for secure storage
from dashboard.database import (
    init_database, 
    validate_api_key, generate_api_key, list_api_keys, revoke_api_key,
    verify_admin_password, set_admin_password,
    save_client_data, get_client_data, get_all_clients, get_clients_count, update_client_field, delete_client_data,
    log_action, get_audit_log,
    create_session, validate_session, delete_session,
    create_user, verify_user_password, verify_client_login, update_user_password,
    delete_user_credential, update_user_email, rename_user_credential, rename_client_in_db,
    get_user, list_users, deactivate_user, reset_user_password, user_exists,
    record_login_attempt, is_account_locked,
    find_user_by_identifier, verify_user_by_identifier,
    # History management
    save_client_data_with_history, get_data_history, get_data_version,
    rollback_to_version, compare_versions, get_latest_version
)
from dashboard.notes_service import (
    get_client_notes, save_client_note, delete_client_note
)
from dashboard.utils.trade_matcher import UnifiedTradeMatcher

# Start Midnight Watermark Scheduler
try:
    from dashboard.scheduler import start_scheduler
    start_scheduler()
    logging.info("Midnight Watermark Scheduler started.")
except ImportError:
    logging.warning("Could not start Watermark Scheduler (ImportError).")
except Exception as e:
    logging.error(f"Failed to start Watermark Scheduler: {e}")

# Initialize logging to file - RESTART MODE (Overwrite) - WITH AUTO-FLUSH AND FSYNC
class UnbufferedFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.stream.flush()
        # Force OS to write to disk
        if hasattr(self.stream, 'fileno'):
            try:
                os.fsync(self.stream.fileno())
            except:
                pass

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    force=True, # Py3.8+ Override previous configs
    handlers=[
        logging.StreamHandler(),
        UnbufferedFileHandler('dashboard/server.log', mode='w', encoding='utf-8')  # 'w' mode overwrites file on start, utf-8 encoding
    ]
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
    """
    Extract last N digits from account number.
    Prioritizes digits at the end of the string to avoid prefix contamination.
    """
    import re
    if not account:
        return ""
    
    # Try to extract the final sequence of digits
    match = re.search(r'(\d+)$', str(account).strip())
    if match:
        digits = match.group(1)
        # For Topstep (V2-) or short accounts, ensure we don't demand more digits than exist
        if len(digits) < n:
            return digits
        return digits[-n:]
    
    # Fallback: extract all digits
    digits = ''.join(c for c in str(account) if c.isdigit())
    return digits[-n:] if len(digits) >= n else digits


def match_account_to_evaluation(account_number, evaluations, phase_code):
    """
    Find ALL matching evaluations for an account number based on phase.
    
    For Challenge (CH): Match against 'Account #' column
    For Funded/DoubleDip/Farming (FD, DD, FA): Match against 'Account #.1' column
    
    Returns: List of (eval_index, matched_account)
    """
    import logging
    matches = []
    if not account_number:
        logging.debug(f"[MATCH] No account_number provided.")
        return matches

    target_sig = get_account_signature(account_number)
    target_last5 = get_last_n_digits(account_number, 5)
    logging.debug(f"[MATCH] Target account: {account_number} | Signature: {target_sig} | Last5: {target_last5}")
    if not target_sig and not target_last5:
        logging.debug(f"[MATCH] No signature or last5 for target account.")
        return matches

    def get_prefix(acc_str):
        import re
        s = str(acc_str).strip().upper()
        if '...' in s:
            s = s.split('...')[0]
        if '-' in s:
            return s.split('-')[0]
        m = re.match(r'^([A-Z]+)', s)
        if m:
            return m.group(1)
        return None

    target_prefix = get_prefix(account_number)

    # Combine funded and evaluation accounts for matching
    combined_accounts = []
    for idx, ev in enumerate(evaluations):
        funded_account = str(ev.get('account') or '').strip()
        if funded_account and funded_account.lower() != 'none':
            combined_accounts.append({'idx': idx, 'account': funded_account, 'source': 'funded'})
        for col_name in ['Account #.1', 'Account #']:
            eval_account = str(ev.get(col_name) or '').strip()
            if eval_account and eval_account.lower() != 'none':
                combined_accounts.append({'idx': idx, 'account': eval_account, 'source': col_name})

    is_topstep = str(account_number).upper().startswith('V2')
    seen_row_indices = set()
    for entry in combined_accounts:
        idx = entry['idx']
        eval_account = entry['account']
        source = entry['source']
        if idx in seen_row_indices:
            continue
        eval_sig = get_account_signature(eval_account)
        eval_prefix = get_prefix(eval_account)
        has_letters = any(c.isalpha() for c in str(eval_account).upper())
        
        # Check for strict prefix mismatch
        prefix_mismatch = False
        if target_prefix and has_letters:
            if eval_prefix and target_prefix != eval_prefix:
                # If they are totally different prefixes, mismatch
                # But allow partials like MFFU vs MFFUEV
                 if not (target_prefix.startswith(str(eval_prefix)) or str(eval_prefix).startswith(target_prefix)):
                      # Also check if target_prefix is inside eval_account (e.g. V2 inside EXPRESS-V2)
                      if target_prefix not in eval_account.upper():
                           prefix_mismatch = True

        # eval_last5 = get_last_n_digits(eval_account, 5)
        # logging.debug(f"[MATCH] Comparing to DB account: {eval_account} (source: {source}) | Signature: {eval_sig} | Last5: {eval_last5}")
        if eval_sig == target_sig:
            matches.append((idx, eval_account))
            seen_row_indices.add(idx)
            logging.debug(f"[MATCH] Signature match: {account_number} == {eval_account}")
            continue
        
        # Strict prefix check applies to partial matches below
        if prefix_mismatch:
             logging.debug(f"[MATCH] Rejected partial match due to prefix mismatch: {target_prefix} vs {eval_account}")
             continue

        if target_last5 and len(target_last5) >= 4:
            eval_last5 = get_last_n_digits(eval_account, 5)
            if eval_last5 == target_last5:
                matches.append((idx, eval_account))
                seen_row_indices.add(idx)
                logging.debug(f"[MATCH] Last5 exact match: {target_last5} == {eval_last5}")
                continue
            if len(eval_last5) != len(target_last5) and eval_last5 and target_last5:
                if eval_last5.endswith(target_last5) or target_last5.endswith(eval_last5):
                    matches.append((idx, eval_account))
                    seen_row_indices.add(idx)
                    logging.debug(f"[MATCH] Last5 suffix match: {target_last5} <-> {eval_last5}")
                    continue
            if len(target_last5) >= 4 and len(eval_last5) >= 4:
                if target_last5[-4:] == eval_last5[-4:]:
                    matches.append((idx, eval_account))
                    seen_row_indices.add(idx)
                    logging.debug(f"[MATCH] Last4 match: {target_last5[-4:]} == {eval_last5[-4:]}")
                    continue
        if is_topstep:
            target_last4 = get_last_n_digits(account_number, 4)
            eval_last4 = get_last_n_digits(eval_account, 4)
            if target_last4 and len(target_last4) == 4 and target_last4 == eval_last4:
                matches.append((idx, eval_account))
                seen_row_indices.add(idx)
                logging.debug(f"[MATCH] Topstep relaxed 4-digit match: {target_last4} == {eval_last4}")
                continue
    if not matches:
        logging.debug(f"[MATCH] No match found for {account_number} in any DB account.")
    return matches


def parse_sheet_date(date_str):
    """
    Parse date string from Google Sheet into datetime object.
    Supports formats: DD/MM/YYYY, YYYY-MM-DD, MM/DD/YYYY, etc.
    """
    if not date_str:
        return None
    
    date_str = str(date_str).strip()
    if not date_str:
        return None
        
    formats = [
        '%m/%d/%Y', '%d/%m/%Y', '%Y-%m-%d', 
        '%m/%d/%y', '%d/%m/%y', 
        '%d-%m-%Y', '%Y/%m/%d', '%d.%m.%Y'
    ]
    
    for fmt in formats:
        try:
            val = datetime.strptime(date_str, fmt)
            # FORCE TO UTC or STRIP TIMEZONE? 
            # MT5 timestamps are usually UTC or server time (which we convert to timestamps).
            # If sheet dates are parsed as naive 00:00:00, and we compare to 
            # trade times which might be later in the day, that's fine.
            # But if a trade happens at 23:00 on Feb 18 (UTC), and sheet says Feb 18...
            # The trade timestamp (TS) > Date Purchased TS.
            # But if timezone is involved, eg. Sheet date is parsed as local time?
            # datetime.strptime creates NAIVE datetime.
            
            # If there's a 1-day difference being observed, it's likely a timezone shift display issue?
            # Or the dashboard is displaying dates differently?
            # Or maybe pandas parsing?
            
            # User says: "one day difference between the dates on the sheets and the dates on the dashboard"
            # If Sheet says Feb 18, Dashboard says Feb 17? Or Feb 19?
            
            # If date_str is "2/18/26", datetime is 2026-02-18 00:00:00
            
            # FIX: Use simple parsing - keep naive dates as imported
            # If date_str is "2/18/26", datetime is 2026-02-18 00:00:00
            
            return val
        except ValueError:
            continue
            
    return None


def filter_matches_by_date(matches, evaluations, trade_timestamp, phase_code=None, trade_number=None):
    """
    Filter matches to find the best matching evaluation.
    
    Universal logic for ALL prop firms:
        - When multiple rows match the same account, always prefer the LATEST row
          (highest eval_index = most recently added to the dashboard).
        - Date filtering is used as a secondary signal but never overrides the
          "latest row wins" rule.
    
    Args:
        matches: List of (eval_index, matched_account)
        evaluations: List of evaluation dicts
        trade_timestamp: Timestamp of the trade (float or int)
        phase_code: (Optional) Phase code to help determine target field for placeholder check
        trade_number: (Optional) Trade number for target field check
    """
    if not matches:
        return None
    
    # Universal: always prefer the latest row (highest eval_index)
    if not trade_timestamp:
        return max(matches, key=lambda m: m[0])

    # Convert trade timestamp to datetime
    try:
        val = float(trade_timestamp)
        trade_date = datetime.fromtimestamp(val)
    except (ValueError, TypeError):
         # If not a float, try isoformat string if present
        try:
             trade_date = datetime.fromisoformat(str(trade_timestamp).replace('Z', '+00:00'))
        except ValueError:
             return max(matches, key=lambda m: m[0])
        
    valid_matches = []
    
    # "give it a 2 day window from the date started"
    # Allow trades to be slightly BEFORE date started (e.g. timezone diffs)
    BUFFER_SECONDS = 2 * 24 * 3600 # 2 days

    for eval_idx, matched_acc in matches:
        ev = evaluations[eval_idx]
        # "Date Purchased" is typically at index 2, but we address by name
        date_purchased_str = ev.get('Date Started', '') or ev.get('Date Purchased', '')
        date_purchased = parse_sheet_date(date_purchased_str)
        
        if not date_purchased:
            # If no date purchased, keep as fallback
            valid_matches.append({
                'match': (eval_idx, matched_acc),
                'delta': float('inf'),
                'valid_date': False,
                'start_date': 'None'
            })
            continue
            
        # Reset time to midnight for comparison
        dp_date = date_purchased.replace(hour=0, minute=0, second=0, microsecond=0)
        td_date = trade_date.replace(hour=0, minute=0, second=0, microsecond=0)
        
        raw_delta_seconds = (td_date - dp_date).total_seconds()
        
        # Check if Trade Date is within valid window relative to Start Date
        # Valid: Trade >= Start - 2 days
        if raw_delta_seconds >= -BUFFER_SECONDS:
            valid_matches.append({
                'match': (eval_idx, matched_acc),
                'delta': raw_delta_seconds,
                'valid_date': True,
                'start_date': dp_date.strftime('%Y-%m-%d')
            })
            
    if not valid_matches:
        # Fallback if no valid dates found — prefer latest row (highest eval_index)
        # Prefer the latest row (highest eval_index = most recently added account)
        return max(matches, key=lambda m: m[0])
        
    # When multiple valid matches exist, prefer the latest row (highest eval_index).
    # This ensures data always goes to the most recently added account on the dashboard.
    dated_valid = [m for m in valid_matches if m['valid_date']]
    if dated_valid:
        match_result = max(dated_valid, key=lambda m: m['match'][0])['match']
    else:
        match_result = max(valid_matches, key=lambda m: m['match'][0])['match']
    return match_result


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
        # Double Dip: DD1 maps to Hedge Result 1.1, DD2->2.1 etc
        if trade_number is not None:
             return f"Hedge Result {trade_number}.1"
    
    elif phase_code == 'FA':
        ev = evaluations[eval_idx] if (eval_idx is not None and evaluations and eval_idx < len(evaluations)) else {}
        incoming_date = str(farming_date or '').strip()

        logging.info(f"[FA SELECT] eval_idx={eval_idx} incoming_date={incoming_date}")

        # Reuse same slot if same date already exists
        for day_num in range(1, 51):
            date_key = f"_Hedge Day {day_num} Date"
            saved_date = str(ev.get(date_key, '')).strip()
            if saved_date and incoming_date and saved_date == incoming_date:
                logging.info(f"[FA SELECT] Reusing Hedge Day {day_num} for date {incoming_date}")
                return f"Hedge Day {day_num}"

        # Otherwise use first empty slot
        for day_num in range(1, 51):
            value_key = f"Hedge Day {day_num}"
            date_key = f"_Hedge Day {day_num} Date"

            existing_value = ev.get(value_key)
            existing_date = ev.get(date_key)

            is_empty_value = existing_value in (None, '', 0, '0', '$0', '$0.00')
            is_empty_date = existing_date in (None, '')

            if is_empty_value and is_empty_date:
                logging.info(f"[FA SELECT] Using empty slot Hedge Day {day_num} for date {incoming_date}")
                return value_key

        logging.warning(f"[FA SELECT] No empty slot found, defaulting to Hedge Day 1")
        return "Hedge Day 1"
    
    return None


def update_evaluations_from_aggregated_data(evaluations, aggregated_data=None, raw_deals=None):
    """
    Update evaluation hedge result fields from aggregated MT5 comment data OR raw deals.
    
    If 'raw_deals' is provided, performs server-side aggregation (Session Matching).
    Otherwise, uses client-provided 'aggregated_data'.
    
    Args:
        evaluations: List of evaluation records
        aggregated_data: List of aggregated trade data (from client)
        raw_deals: List of raw MT5 deal objects (from client)
    
    Returns:
        Tuple of (updated_evaluations, match_log)
    """
    aggregated_data = aggregated_data or []
    
    # -------------------------------------------------------------------------
    # SERVER-SIDE SESSION MATCHING LOGIC
    # -------------------------------------------------------------------------
    if raw_deals:
        import datetime
        
        match_log = ["🔄 Using SERVER-SIDE Session Matching (ignoring client aggregation)"]
        
        # Helper: Parse simple comment patterns
        def parse_comment(c):
            if not c: return None, None
            # Standard Pattern: PRE...12345_CH1
            m = re.search(r'_(CH|FD|DD|FA)(\d+)?', c, re.IGNORECASE)
            if m:
                return m.group(1).upper(), int(m.group(2)) if m.group(2) else None
            return None, None

        def parse_full_comment_structure(c):
            # Returns (PropPrefix, AccountNum, PhaseStr, PhaseNum)
            # Example: MFFU...60076_FD1 -> ('MFFU', '60076', 'FD', 1)
            # Example: V2-...4610_CH2 -> ('V2-', '4610', 'CH', 2)
            # Example: FNFT...G8326_CH1 -> ('FNFT', 'G8326', 'CH', 1)
            if not c: return None, None, None, None
            
            # Regex for "PREFIX...ALPHANUM_PHASE"
            # Support prefixes with digits and dashes (e.g. V2-)
            # 1. Prefix: Letters, Digits, Dashes, min length 2
            # 2. Filler: non-alphanumeric chars (dots, spaces, etc)
            # 3. Account: Alphanumeric (Letters + Digits)
            # 4. Underscore + Phase Code + Num
            m = re.search(r'^([A-Z0-9\-]+)[^A-Z0-9]+([A-Z0-9]+)_(CH|FD|DD|FA)(\d+)?$', c.strip(), re.IGNORECASE)
            if m:
                return m.group(1).upper(), m.group(2).upper(), m.group(3).upper(), int(m.group(4)) if m.group(4) else 1
            return None, None, None, None
            
        def get_ts(d):
            t = d.get('time')
            if isinstance(t, (int, float)): return t
            if isinstance(t, str):
                try:
                    return datetime.datetime.fromisoformat(t).timestamp()
                except:
                    pass
            return 0

        # Helper: Parse simple comment patterns to extract identifying account number
        def extract_account_from_comment(c):
            if not c: return None
            
            # Known prefixes logic - moved to TOP priority
            known_prefixes = ['MFFU', 'AFAD', 'V2', 'FNFT', 'TDFY', 'ELTD', 'TDF']
            c_upper = c.upper()
            found_prefix = None
            for kp in known_prefixes:
                if kp in c_upper:
                    found_prefix = kp
                    break
            
            # If we see a known prefix, we want to capture that + the number (or alphanumeric code)
            if found_prefix:
                # Try to find the number/alphanum pattern specific to the prefix logic
                # For FNFT, account numbers can start with G?
                # Generally look for the part after dots and before _PHASE
                
                # Check for Structure: PREFIX...ACCOUNT_PHASE
                # Grab whatever is between ... and _
                # Use regex to find alphanumeric chars immediately preceding _PHASE
                m_phase = re.search(r'([A-Z0-9]+)_(CH|FD|DD|FA)', c, re.IGNORECASE)
                if m_phase:
                     # This captures G8326 from ...G8326_CH1
                     # But we want to prepend prefix if not present?
                     extracted = m_phase.group(1)
                     # If extracted matches digits, or starts with G, etc.
                     # If found_prefix is already in extracted (e.g. FNFT12345), return extracted
                     if found_prefix in extracted.upper():
                         return extracted
                     # Else return PREFIX-ACCOUNT
                     return f"{found_prefix}-{extracted}"

                # Fallback: Just first number sequence if phase not found (shouldn't happen for valid comments)
                num_match = re.search(r'(\d+)', c)
                if num_match:
                    return f"{found_prefix}-{num_match.group(1)}"
            
            # Look for alphanumeric string of length 4+ (including letters) before phase
            # This covers alphanumeric accounts like "MFFU12345"
            m = re.search(r'([A-Za-z0-9]{3,})_(CH|FD|DD|FA)', c, re.IGNORECASE)
            if m:
                val = m.group(1)
                # If it's just digits, fine
                if val.isdigit():
                    return val
                
                # If it has letters, it might contain the prefix already in the group
                # e.g. MFFU12345
                return val

            # Fallback: Just look for digits before phase
            m = re.search(r'(\d+)_(CH|FD|DD|FA)', c, re.IGNORECASE)
            if m:
                 return m.group(1)
            return None

        # 1. Group by Account Number (from login or comment)
        # Note: raw_deals usually come from a single login, but might contain history for that login.
        
        # --- NEW: Group Deals by Position ID FIRST ---
        # The user requested "extract data from positions not deals".
        # We synthesize "Position Objects" from raw deals by grouping on 'position_id'.
        # This ensures that Exit deals (often comment-less) are linked to Entry deals (with comments).
        
        position_map = {}
        non_position_deals = []
        
        # Initial pass to group
        for d in raw_deals:
            pos_id = d.get('position_id')
            # Check if it's a trade deal (not balance/credit) and has valid position_id
            # Balance ops usually have position_id=0 or are distinct types
            d_type = str(d.get('type', '')).upper()
            is_balance = d_type in ['BALANCE', 'CREDIT', '2', '3', 'CHARGE', 'CORRECTION', 'BONUS']
            
            if not is_balance and pos_id and pos_id > 0:
                if pos_id not in position_map:
                    position_map[pos_id] = []
                position_map[pos_id].append(d)
            else:
                non_position_deals.append(d)
                
        # Synthesize Positions
        synthesized_deals = []
        
        # Add non-position deals (Balance/Credit) directly
        synthesized_deals.extend(non_position_deals)
        
        for pos_id, p_deals in position_map.items():
            # Create a single 'deal' representing the whole position
            
            # 1. Find best comment (from entry usually)
            # Sort by time to find entry
            p_deals.sort(key=get_ts)
            
            common_comment = ""
            for pd in p_deals:
                c = pd.get('comment', '')
                if c and not common_comment:
                    common_comment = c
                # Prefer comments that match our parser pattern
                if parse_comment(c)[0]: 
                    common_comment = c
                    break
            
            # 2. Sum Profits
            total_profit = sum(float(pd.get('profit', 0)) + float(pd.get('commission', 0)) + float(pd.get('swap', 0)) for pd in p_deals)
            
            # 3. Create Synthesized Object
            # Use Entry Time as the time for this position
            entry_time = get_ts(p_deals[0])
            
            syn_deal = {
                'time': entry_time,
                'profit': total_profit, # Net result of position
                'comment': common_comment,
                'type': 'POSITION',
                'position_id': pos_id,
                'deal_count': len(p_deals)
            }
            
            # --- FILTER UNKNOWN FORMATS ---
            # If we cannot extract an account number OR a valid phase from the comment,
            # this position is likely "Unknown" and should be ignored as per user request.
            # We use likelyhood check: if extraction returns None, it's unknown format.
            ac_check = extract_account_from_comment(common_comment)
            ph_check, _ = parse_comment(common_comment)
            
            if not ac_check and not ph_check:
                 # logging.debug(f"[FILTER] Skipping position {pos_id} due to unrecognized comment format: '{common_comment}'")
                 continue
            
            synthesized_deals.append(syn_deal)
            
        # Replace raw_deals with our improved list
        raw_deals = synthesized_deals
        match_log.append(f"🔄 Grouped {len(position_map)} positions from raw deals for accurate P&L tracking")
        
        # --- NEW DATE FILTERING LOGIC ---
        # The user requested to only process trades from "today" (active day)
        # OR if no trades today, process trades from the "last active day".
        if raw_deals:
            # Helper to extract YYYY-MM-DD from timestamp (assuming timestamp is seconds)
            # syn_deal['time'] is already a timestamp float/int
            def get_date_str(ts):
                try:
                    if isinstance(ts, str):
                        # Try parsing ISO string
                        dt = datetime.datetime.fromisoformat(ts)
                        return dt.strftime('%Y-%m-%d')
                    return datetime.datetime.fromtimestamp(float(ts)).strftime('%Y-%m-%d')
                except Exception as e:
                    logging.warning(f"Failed to parse timestamp {ts}: {e}")
                    return "1970-01-01"
            
            # Count FA deals for logging
            fa_count = sum(1 for d in raw_deals if parse_comment(d.get('comment', ''))[0] == 'FA')
            if fa_count:
                match_log.append(f"🌾 Found {fa_count} farming deals in data")

            # --- PRE-COMPUTE FARMING DAILY PROFITS PER ACCOUNT (before date filter) ---
            # Scan ALL FA deals to build: {account_num: {date_str: total_profit}}
            # This lets us know how many farming days exist for each account
            # and which Hedge Day slot each date maps to.
            fa_account_days = {}
            for _d in raw_deals:
                _phase, _num = parse_comment(_d.get('comment', ''))
                if _phase != 'FA':
                    continue
                _acc = extract_account_from_comment(_d.get('comment', ''))
                if not _acc:
                    continue
                _ts = get_ts(_d)
                _date = datetime.datetime.fromtimestamp(_ts).strftime('%Y-%m-%d')
                _profit = float(_d.get('profit', 0)) + float(_d.get('commission', 0)) + float(_d.get('swap', 0))
                if _acc not in fa_account_days:
                    fa_account_days[_acc] = {}
                fa_account_days[_acc][_date] = fa_account_days[_acc].get(_date, 0.0) + _profit

            if fa_account_days:
                for _acc, _days in fa_account_days.items():
                    logging.info(f"[FA PRE-COMPUTE] account={_acc} farming_days={len(_days)} dates={sorted(_days.keys())}")
                match_log.append(f"🌾 Pre-computed farming: {len(fa_account_days)} account(s), {sum(len(d) for d in fa_account_days.values())} total farming day(s)")

            # Track which evals have already had their Hedge Days written by FA pre-compute
            fa_evals_written = set()
            
            # Identify Today
            today_date = datetime.datetime.now().strftime('%Y-%m-%d')
            
            # Identify all unique dates in the data
            unique_dates = sorted(list({get_date_str(d['time']) for d in raw_deals})) if raw_deals else []
            
            target_date = None
            filter_reason = ""
            
            # SIMPLIFIED LOGIC: Always take the LATEST date found in the data.
            # This handles both "Today (if trades exist)" and "Last Active Day (if no trades today)"
            # without relying on server timezone matching MT5 timezone.
            if unique_dates:
                target_date = unique_dates[-1]
                filter_reason = f"Latest Active Date ({target_date})"
            
            if target_date:
                original_count = len(raw_deals)
                # Filter non-FA deals to target_date only; keep ALL FA deals so they form sessions
                raw_deals = [d for d in raw_deals
                             if get_date_str(d['time']) == target_date
                             or parse_comment(d.get('comment', ''))[0] == 'FA']
                match_log.append(f"📅 Filtered trades to {filter_reason}: {len(raw_deals)}/{original_count} positions kept (FA deals preserved).")
                logging.info(f"   [DATE FILTER] Keeping trades for {target_date} ONLY + all FA deals ({len(raw_deals)} positions).")
            

        # --------------------------------
        
        # ---------------------------------------------
        
        # Let's assume passed 'aggregated_data' logic was doing groupings.
        # We will iterate raw_deals, extracting (Phase, TradeNum) from comment.
        # And Group by Time Gaps (> 7 days) -> New Session.
        
        raw_deals.sort(key=get_ts)
        
        # Group into sessions by Time Gap (24h) OR Phase Change
        sessions = []
        
        # Helper to init session
        def new_session_dict(start_t, acc_guess=None):
            return {
                'deals': [], 
                'start': start_t, 
                'end': start_t, 
                'account_guess': acc_guess,
                'phase_guess': None,
                'phase_num': None
            }
        
        # Initialize with first deal info
        first_deal = raw_deals[0]
        start_ts = get_ts(first_deal)
        
        if len(raw_deals) > 0:
             logging.info(f"[DEBUG] First 20 Raw Comments: {[d.get('comment') for d in raw_deals[:20]]}")

        # Extract initial account guess
        first_acc_guess = None
        for d in raw_deals:
             guess = extract_account_from_comment(d.get('comment', ''))
             if guess:
                 first_acc_guess = guess
                 break
        
        current_session = new_session_dict(start_ts, first_acc_guess)
        last_ts = start_ts
        
        # Initial phase guess
        p_init, n_init = parse_comment(first_deal.get('comment', ''))
        if p_init:
            current_session['phase_guess'] = p_init
            current_session['phase_num'] = n_init
        
        for d in raw_deals:
            ts = get_ts(d)
            p, n = parse_comment(d.get('comment', ''))
            
            # Check for Phase Change
            is_phase_change = False
            if p and current_session['phase_guess']:
                if p != current_session['phase_guess'] or n != current_session['phase_num']:
                    is_phase_change = True

            # Check for Account Change
            is_account_change = False
            current_account_guess = extract_account_from_comment(d.get('comment', ''))
            
            # Only trigger change if we had a guess and the new guess is DEFINITELY different
            if current_account_guess and current_session['account_guess']:
                if current_account_guess != current_session['account_guess']:
                    is_account_change = True
                    logging.debug(f"[SPLIT] Account changed from {current_session['account_guess']} to {current_account_guess}")

            # Check Time Gap (36 hours) - lowered from 7 days
            time_gap = (ts - last_ts) > (36 * 3600)
            
            # Balance Reset
            is_balance_reset = str(d.get('type', '')).upper() == 'BALANCE' and float(d.get('profit', 0)) > 0
            
            # Split Session Logic (Phase, Time, Balance, Account)
            should_split = (time_gap or is_balance_reset or is_phase_change or is_account_change)
            
            if should_split and current_session['deals']:
                sessions.append(current_session)
                
                # Determine next account guess for the new session
                next_acc_guess = current_account_guess if current_account_guess else current_session['account_guess']
                
                # Create new session
                current_session = new_session_dict(ts, next_acc_guess)
                
                if p:
                    current_session['phase_guess'] = p
                    current_session['phase_num'] = n
            
            current_session['deals'].append(d)
            current_session['end'] = max(current_session['end'], ts)
            last_ts = ts
            
            # Update tracking
            if p and not current_session['phase_guess']:
                current_session['phase_guess'] = p
                current_session['phase_num'] = n
                
            # If we don't have an account guess yet (or it's None), see if this comment has one
            if current_account_guess and not current_session['account_guess']:
                current_session['account_guess'] = current_account_guess
        
        if current_session['deals']:
            sessions.append(current_session)
        
        match_log.append(f"   Found {len(sessions)} distinct sessions based on Phase/Time gaps")
        
        # --- NEW: Summary Aggregation Structure ---
        # { PropFirm: { AccountNumber: { PhaseKey: { profit: 0.0, trades: 0 } } } }
        trade_summary = {}
        # ------------------------------------------



        # Now match each session to an Evaluation
        updates_made = 0
        
        for session in sessions:
            if not session['account_guess']:
                logging.warning(f"Session without account guess skipped. Deals: {len(session['deals'])}")
                continue # Can't match without account number

            logging.info(f"[DEBUG] Processing Session: AccountGuess={session['account_guess']}, Deals={len(session['deals'])}")
                
            # Aggregate stats for session
            session_profit = sum(float(d.get('profit', 0)) + float(d.get('commission', 0)) + float(d.get('swap', 0)) for d in session['deals'])
            
            # Determine Phase/TradeNum from MOST frequent in session
            # (To handle noise)
            phases = {}
            full_comment_info = None
            
            for d in session['deals']:
                # Try full structure parse first
                prefix, acc_part, p, n = parse_full_comment_structure(d.get('comment', ''))
                if prefix and acc_part:
                    full_comment_info = (prefix, acc_part, p, n)
                
                # Fallback to simple parse for counting
                p_simple, n_simple = parse_comment(d.get('comment', ''))
                if p_simple:
                    key = (p_simple, n_simple)
                    phases[key] = phases.get(key, 0) + 1
            
            if not phases:
                continue
                
            best_phase, best_num = max(phases.items(), key=lambda x: x[1])[0]
            logging.info(
                f"[SESSION] account_guess={session['account_guess']} "
                f"best_phase={best_phase} best_num={best_num} "
                f"start={datetime.datetime.fromtimestamp(session['start'])} "
                f"end={datetime.datetime.fromtimestamp(session['end'])} "
                f"profit={session_profit}"
            )
            
            # If we found a full comment structure, prefer that for matching
            if full_comment_info:
                 target_prefix, target_acc_part, target_phase, target_num = full_comment_info
                 # Use the derived phase/num from the full comment if available, or fallback to frequency
                 if target_phase: 
                     best_phase = target_phase
                 if target_num:
                     best_num = target_num
                 
                 acc_num = target_acc_part # Use extracted regex digits as the account number to match
                 
                 # NEW: If acc_num is purely digits, but we found a PREFIX, try to append it?
                 # Or better: Check if appending prefix helps match against verbose DB accounts?
                 # e.g. TDFY-72031 might be better search key than 72031 if DB is verbose?
                 # But our matching logic 's_acc in ac1' works better with SHORTER s_acc.
                 # So keeps '72031'.
            else:
                 acc_num = session['account_guess']

            start_date_ts = session['start']
            
            # Find candidate evaluations
            # Check match against BOTH Account # and Account #.1
            
            def normalize_acc(a): return str(a).strip().upper()
            
            # Strip prefix from s_acc if we are relying on substring matching?
            # If s_acc is "TDFY-72031", and DB has "TDFYSL...72031", "TDFY-72031" is NOT in it.
            # But "72031" IS in it.
            # So we should probably strip known prefixes from s_acc before matching loop if we want flexible matching.
            
            s_acc_raw = normalize_acc(acc_num)
            
            # Preserve the comment prefix (e.g. 'V2-', 'MFFU', 'FNFT') for firm validation
            # even when acc_num itself has no hyphen (full_comment_info strips prefix from acc_part)
            comment_prefix = None
            if full_comment_info and full_comment_info[0]:
                comment_prefix = full_comment_info[0].rstrip('-').upper()
            
            # If s_acc contains a hyphen, try splitting
            if '-' in s_acc_raw:
                # Keep full for strict check, but try short version for loose check?
                s_acc_short = s_acc_raw.split('-')[-1]
            else:
                s_acc_short = s_acc_raw
            
            # Use the SHORTER version for candidate finding to maximize hits
            s_search = s_acc_short
            
            candidates = []
            
            # Determines if we have a strict structural match up front
            matches_full_strict = (full_comment_info is not None)

            for e in evaluations:
                is_match = False
                ac1 = normalize_acc(e.get('Account #', ''))
                ac2 = normalize_acc(e.get('Account #.1', ''))
                
                # Strip Top Step prefixes (50KTC- for challenge, EXPRESS- for funded) before matching
                for _ts_prefix in ['50KTC-', 'EXPRESS-']:
                    if ac1.startswith(_ts_prefix): ac1 = ac1[len(_ts_prefix):]
                    if ac2.startswith(_ts_prefix): ac2 = ac2[len(_ts_prefix):]
                
                # Use ENDING digits matching only — never substring containment
                s = s_search
                
                # Extract trailing digits for comparison
                import re as _re
                s_digits = _re.search(r'(\d+)$', s)
                s_trail = s_digits.group(1) if s_digits else s
                
                # Check ac1
                if ac1:
                    ac1_digits = _re.search(r'(\d+)$', ac1)
                    ac1_trail = ac1_digits.group(1) if ac1_digits else ac1
                    if s == ac1:
                        is_match = True
                    elif ac1_trail.endswith(s_trail) or s_trail.endswith(ac1_trail):
                        is_match = True
                
                # Check ac2
                if not is_match and ac2:
                    ac2_digits = _re.search(r'(\d+)$', ac2)
                    ac2_trail = ac2_digits.group(1) if ac2_digits else ac2
                    if s == ac2:
                        is_match = True
                    elif ac2_trail.endswith(s_trail) or s_trail.endswith(ac2_trail):
                        is_match = True
                
                # STRICT PREFIX CHECK — use comment_prefix (from full_comment_info) OR s_acc_raw hyphen prefix
                prefix_part = comment_prefix  # e.g. 'V2' from V2-1128_CH2
                if not prefix_part and '-' in s_acc_raw:
                    prefix_part = s_acc_raw.split('-')[0]
                
                try:
                    if is_match and prefix_part:
                        pf_val = str(e.get('Prop Firm', '')).upper()
                        
                        # Only proceed if we have a valid Prop Firm string to check against
                        if pf_val and prefix_part not in pf_val and pf_val not in prefix_part:
                            mapping = {
                                'MFFU': ['MYFUNDED', 'MFFU', 'MY FUNDED'],
                                'AFAD': ['ALPHA', 'AFAD'],
                                'V2': ['TOPSTEP', 'TOP STEP', 'V2'],
                                'FNFT': ['FUNDEDNEXT', 'FUNDED NEXT', 'FNFT'],
                                'TDFY': ['TRADEIFY', 'TDFY'],
                                'ELTD': ['TRADEDAY', 'ELTD'],
                                'TDF': ['TRADEDAY', 'TDF', 'TRADEIFY'],
                                'FTDF': ['TRADEDAY', 'TDF', 'TRADEIFY']
                            }
                            if prefix_part in mapping:
                                valid_keywords = mapping[prefix_part]
                                if not any(k in pf_val for k in valid_keywords):
                                    is_match = False
                except Exception as ex:
                    logging.error(f"Error in Strict Prefix Check for {s_acc_raw} prefix={prefix_part}: {ex}")

                if matches_full_strict and is_match:
                     pass

                if is_match:
                    candidates.append(e)

            if not candidates:
                match_log.append(f"⚠️ No evaluation found for session {acc_num} (Start: {str(datetime.datetime.fromtimestamp(start_date_ts))})")
                continue

            # Filter by Date Purchased
            # We want Evaluation.DatePurchased <= Session.Start
            # And closest to it
            valid_candidates = []
            
            # STRICT MATCH OVERRIDE: If we have a perfectly parsed comment (Structure: PREFIX...ACC_PHASE),
            # and we found matching accounts, we TRUST the account number match primarily.
            # Skip date filtering for ALL firms with a structural match — latest row always wins.
            skip_date_filter = matches_full_strict

            for e in candidates:
                if skip_date_filter:
                     # Trust the account match implicitly (all matches are suffix-based)
                     valid_candidates.append((e, 0))
                     continue

                dp_str = str(e.get('Date Started', '')) or str(e.get('Date Purchased', ''))
                try:
                    # Try common formats
                    dp_dt = None
                    for fmt in ["%m/%d/%y", "%Y-%m-%d", "%m/%d/%Y"]:
                        try:
                            dp_dt = datetime.datetime.strptime(dp_str, fmt)
                            break
                        except: pass
                    
                    if dp_dt:
                        diff = start_date_ts - dp_dt.timestamp()
                        # Allow session to start slightly before purchase? (Maybe same day timezone diff?)
                        # Allow -24h slack.
                        # BUFFER: If strict comment match, assume it's correct even if dates are weird?
                        # But typically we still want the LATEST one if duplications exist.
                        # Let's keep date logic but maybe relax it for strict matches?
                        if diff > -86400 * 2: # 48 hours buffer
                            valid_candidates.append((e, diff))
                    else:
                        # If no date found, but we have a STRICT digit match?
                        # Keep it as a candidate with high drift (unless only one candidate)
                         valid_candidates.append((e, float('inf')))
                except:
                    pass
            
            # Decision Time
            if not valid_candidates:
                # If we had a strict comment match, and no valid dates, maybe just pick the best text match?
                if matches_full_strict and candidates:
                     # Always prefer the latest row (highest eval_index)
                     best_eval = max(candidates, key=lambda e: evaluations.index(e))
                     match_log.append(f"⚠️ Date mismatch but strict ID match for {acc_num}, using latest row.")
                else:
                     match_log.append(f"⚠️ No valid date match for {acc_num}")
                     continue
            else:
                # Always prefer the latest row (highest eval_index = most recently added)
                # regardless of date proximity — the bigger the row number, the more recent the account
                best_eval = max(
                    [vc[0] for vc in valid_candidates],
                    key=lambda e: evaluations.index(e)
                )
                drift = next(vc[1] for vc in valid_candidates if vc[0] is best_eval)
                    
                logging.info(
                    f"[MATCHED EVAL] eval_idx={evaluations.index(best_eval)} "
                    f"account={acc_num} phase={best_phase} num={best_num} drift={drift}"
                )
            
            # Determined Field Name
            field_name = "Hedge Result" # Default
            
            # Use parsed phase/num from strict match if available
            if matches_full_strict: 
                 _, _, best_phase, best_num = full_comment_info
            
            if best_phase == 'CH':
                # CH1 -> Hedge Result 1
                # CH2 -> Hedge Result 2
                if best_num and best_num > 1:
                     field_name = f"Hedge Result {best_num}"
                else:
                     field_name = "Hedge Result 1" # Default to 'Hedge Result 1' to match sheet headers

            elif best_phase == 'FD':
                 # FD1 -> Hedge Result 1.1? Or just Hedge Result?
                 # User provided logic: "last part is the cell to put the data in" (CH2 -> HR2)
                 # Wait, for FD, existing logic says "Hedge Result 1.1" usually.
                 # Let's check get_field_name_for_phase implementation again if possible, or replicate:
                 if best_num is not None:
                      # MFFU logic: FD0->1.1, FD1->2.1? Or FD1->1.1?
                      # Standard implementation elsewhere:
                      # FD -> 1.1 usually means "Funded Account 1"
                      # Let's assume matches 1:1 if possible?
                      # Logic in get_field_name_for_phase (read earlier):
                      # "MFFU accounts: FD0->HR1.1, FD1->HR2.1"
                      # "Other: FD0/1 -> HR1.1"
                      
                      # Re-implement simplified version here:
                      normalized_prefix = (target_prefix or '').upper()
                      if 'MFFU' in normalized_prefix:
                           # MFFU Logic
                           # FD0 -> 1.1 ?? Wait, previous code said FD0->1.1, FD1->2.1
                           # Let's safer assume user wants mapped to *.1
                           # Map FD1 -> Hedge Result 1.1
                           # FD2 -> Hedge Result 2.1
                           if best_num == 0: field_name = "Hedge Result 1.1" # FD0 match
                           else: field_name = f"Hedge Result {best_num}.1"
                      else:
                           # Standard FD
                           field_name = f"Hedge Result {best_num}.1"

            elif best_phase == 'DD':
                 field_name = f"Hedge Result {best_num}.1"

            elif best_phase == 'FA':
                # --- FARMING: Count farming days from MT5 history, only update the LAST one ---
                # fa_account_days has ALL farming dates per account from full MT5 history.
                # Count distinct dates to know which Hedge Day slot the latest trade belongs to.
                # e.g. 5 farming days total → only write Hedge Day 5 with the latest day's profit.
                best_eval_idx = evaluations.index(best_eval)
                row_num = best_eval_idx + 2

                # --- Active account check: skip inactive evals for farming ---
                _s_p1 = str(best_eval.get('Status P1', '')).lower()
                _s_funded = str(best_eval.get('Status', '') or best_eval.get('Status Funded', '')).lower()
                _inactive_kw = ('fail', 'breach', 'sl', 'closed', 'delete')
                _is_inactive = (
                    any(kw in _s_p1 for kw in _inactive_kw) or
                    any(kw in _s_funded for kw in (*_inactive_kw, 'complete'))
                )
                if _is_inactive:
                    match_log.append(f"   ⏩ Skipping FA for inactive eval row {row_num} (P1='{_s_p1}', Funded='{_s_funded}')")
                    logging.info(f"[FA SKIP] eval_idx={best_eval_idx} inactive — P1='{_s_p1}' Funded='{_s_funded}'")
                    continue

                # Only write once per eval
                if best_eval_idx in fa_evals_written:
                    continue
                fa_evals_written.add(best_eval_idx)

                # Get this account's farming data from the pre-computed map
                # Pre-compute keys have prefix (e.g. "FNFT-76770"), but acc_num may be just digits ("76770")
                # Try exact match first, then substring fallback
                account_days = fa_account_days.get(acc_num, {})
                if not account_days:
                    # Substring match: find key where acc_num appears in it or it appears in acc_num
                    for _fa_key, _fa_days in fa_account_days.items():
                        if acc_num in _fa_key or _fa_key in acc_num:
                            account_days = _fa_days
                            logging.info(f"[FA WRITE] Matched acc_num={acc_num} to pre-computed key={_fa_key}")
                            break
                if not account_days:
                    logging.warning(f"[FA WRITE] No pre-computed farming data for account {acc_num} (eval_idx={best_eval_idx})")
                    continue

                # Only write if this account has farming activity on the target date
                # (otherwise it's stale data from a previous push)
                sorted_dates = sorted(account_days.keys())
                if target_date and target_date not in account_days:
                    logging.info(f"[FA SKIP] account={acc_num} has no farming on target_date={target_date} (last={sorted_dates[-1]}), skipping")
                    fa_evals_written.discard(best_eval_idx)  # Allow re-check if another session hits this eval
                    continue

                # Sort dates chronologically — position = Hedge Day number
                total_farming_days = len(sorted_dates)
                last_date = sorted_dates[-1]
                last_profit = account_days[last_date]
                slot = total_farming_days  # e.g. 5 dates → Hedge Day 5

                if slot > 50:
                    logging.warning(f"[FA WRITE] eval_idx={best_eval_idx} has {slot} farming days, capping at 50")
                    slot = 50

                field_name = f'Hedge Day {slot}'

                best_eval[field_name] = f'${last_profit:.2f}'
                best_eval[f'_{field_name} Date'] = last_date
                updates_made += 1

                match_log.append(f"✅ 🌾 Row {row_num} | {field_name}: ${last_profit:.2f} ({last_date}) [day {slot} of {total_farming_days}]")
                logging.info(
                    f"[FA WRITE] row={row_num} account={acc_num} "
                    f"total_farming_days={total_farming_days} → {field_name}=${last_profit:.2f} date={last_date}"
                )

                # --- Also add to trade_summary for logging ---
                try:
                    p_firm = best_eval.get('Prop Firm') or 'Unknown Firm'
                    report_acc = best_eval.get('Account #') or best_eval.get('Account #.1') or acc_num
                    phase_label = f"FA{best_num or ''}"
                    if p_firm not in trade_summary: trade_summary[p_firm] = {}
                    if report_acc not in trade_summary[p_firm]: trade_summary[p_firm][report_acc] = {}
                    if phase_label not in trade_summary[p_firm][report_acc]:
                        trade_summary[p_firm][report_acc][phase_label] = {
                            'profit': 0.0, 'trades': 0, 'source_accounts': set(),
                            'comments': set(), 'target_field': field_name,
                            'detailed_trades': [], 'row_index': row_num
                        }
                    sn = trade_summary[p_firm][report_acc][phase_label]
                    # Use the pre-computed last-date profit (what was actually written),
                    # NOT the session profit (which may come from the earliest session)
                    sn['profit'] = float(last_profit)
                    sn['trades'] = total_farming_days
                    sn['source_accounts'].add(str(acc_num))
                    sn['target_field'] = field_name
                    # Find the actual trade timestamp for the last farming date
                    _last_ts_str = last_date
                    for _fd in reversed(raw_deals):
                        _fp, _ = parse_comment(_fd.get('comment', ''))
                        if _fp == 'FA':
                            _fa_acc = extract_account_from_comment(_fd.get('comment', ''))
                            if _fa_acc and (acc_num in _fa_acc or _fa_acc in acc_num):
                                _fts = get_ts(_fd)
                                _fdate = datetime.datetime.fromtimestamp(_fts).strftime('%Y-%m-%d') if _fts > 0 else ''
                                if _fdate == last_date:
                                    _last_ts_str = datetime.datetime.fromtimestamp(_fts).strftime('%Y-%m-%d %H:%M:%S')
                                    break
                    sn['detailed_trades'] = [f"[{_last_ts_str}] [{session['deals'][0].get('comment', '')}] {acc_num} -> ${last_profit:.2f}"]
                except Exception as e:
                    logging.error(f"Error accumulating FA stats: {e}")

                continue  # Skip normal write logic — FA is handled above

            
            # Update Logic: ACCUMULATE profit for this push
            # Since we are processing all history in this push, we should sum up sessions for the same eval/field.
            # But be careful not to sum with existing OLD values from DB if we are replacing them?
            # Actually, update_evaluations... is called on the existing 'evaluations' list from DB.
            # If we just add, we might double count if we run this multiple times?
            # No, 'evaluations' object is transient for this request (loaded from DB/Sheet).
            # The 'session_profit' is from the NEW deals being pushed.
            # Users usually push ALL history.
            # So we should probably clear the field first if it's the first time we touch it IN THIS REQUEST?
            # Or just assume we are recalculating from scratch for these deals.
            
            # For robustness: valid numeric check (handle $ formatting)
            try:
                raw_val = str(best_eval.get(field_name, 0) or 0)
                clean_val = raw_val.replace('$', '').replace(',', '').strip()
                current_val = float(clean_val) if clean_val else 0.0
            except:
                current_val = 0.0
                
            # SPECIAL CASE: FundedNext (or others) where multiple evals share account?
            # The user said: "one account number belongs to several prop firm evaluations, this only happens for funded next"
            # "The rest should just push directly" 
            # If we touch the same field multiple times in this loop (multiple sessions for same eval), we MUST accumulate.
            # If the eval field already has value from previous pushes (DB), and we are pushing partial data?
            # Usually pushes contain full history.
            # Let's assume we accumulate.
            
            # However, if this is the FIRST time we are updating this specific field IN THIS BATCH,
            # and we want to overwrite old DB data with new calculation?
            # The 'evaluations' list comes from DB.
            # If we want to replace the old 'Hedge Result' with the new value from this push,
            # We should probably track which fields we've updated.
            
            # Key to track uniqueness: (Eval Index, Field Name)
            update_key = (candidates.index(best_eval) if best_eval in candidates else -1, field_name)
            
            # This is tricky because we don't have unique IDs easily accessible here without strict indexing
            # Let's rely on the object identity `id(best_eval)`
            
            eval_id = id(best_eval)
            
            # Simple aggregation logic: If it's the first time we see this field for this eval in THIS REQUEST,
            # we overwrite it (assuming full push). Subsequent sessions add to it.
            if '_updated_fields' not in best_eval:
                best_eval['_updated_fields'] = set()
            
            if field_name not in best_eval['_updated_fields']:
                new_val = session_profit
                best_eval['_updated_fields'].add(field_name)
            else:
                new_val = current_val + session_profit
            
            # FORMAT WITH DOLLAR SIGN FOR PUSH
            best_eval[field_name] = f"${new_val:.2f}"

            updates_made += 1
            if 'Match Log' not in best_eval:
                 best_eval['Match Log'] = []
            best_eval['Match Log'].append(f"Matched matched session (start {datetime.datetime.fromtimestamp(start_date_ts)}) -> {field_name}: ${float(session_profit):.2f} (Total: ${float(new_val):.2f})")
            
            # Add explicit cell confirmation log
            current_row_idx = evaluations.index(best_eval) + 2
            match_log.append(f"✅ Matched session (Start {datetime.datetime.fromtimestamp(start_date_ts)}) -> Column: [{field_name}] | Row: {current_row_idx} | New Value: ${new_val:.2f}")

            # --- AGGREGATE SUMMARY STATS ---
            try:
                # 1. Prop Firm
                # Uses col "Prop Firm" if exists, or guess from prefix
                p_firm = best_eval.get('Prop Firm') 
                if not p_firm:
                     # Try to guess from account number prefix or comments
                     guesser = normalize_acc(acc_num)
                     # Also check comments in session for clues if account number is ambiguous
                     session_comments = " ".join([d.get('comment', '') for d in session['deals'][:5]])
                     
                     if 'MFF' in guesser or 'MFF' in session_comments.upper(): p_firm = 'My Funded Futures'
                     elif 'V2' in guesser or 'V2' in session_comments.upper(): p_firm = 'Topstep'
                     elif 'FN' in guesser or 'FNFT' in session_comments.upper(): p_firm = 'FundedNext'
                     elif 'AF' in guesser or 'AFAD' in session_comments.upper(): p_firm = 'Alpha Futures'
                     else: p_firm = 'Unknown Firm'
                
                # 2. Account Number (Use the one from the evaluation record if possible for consistency)
                # "Account #" for Challenge or "Account #.1" for Funded
                # Or just use the Evaluation Index/Name to be clearer? 
                # User asked for "Account Number"
                report_acc = best_eval.get('Account #') or best_eval.get('Account #.1') or acc_num
                
                # 3. Phase Key (e.g. CH1, FD1)
                phase_label = f"{best_phase}{best_num or ''}"
                
                # InitDicts
                if p_firm not in trade_summary: trade_summary[p_firm] = {}
                if report_acc not in trade_summary[p_firm]: trade_summary[p_firm][report_acc] = {}
                if phase_label not in trade_summary[p_firm][report_acc]: 
                     trade_summary[p_firm][report_acc][phase_label] = {
                         'profit': 0.0, 
                         'trades': 0,
                         'source_accounts': set(), # The raw account number from mt5/comment
                         'comments': set(),        # Sample comments used for classification
                         'target_field': field_name,
                         'detailed_trades': [],    # List of specific trade details
                         'row_index': -1           # Will be set below
                     }
                
                # Add
                summary_node = trade_summary[p_firm][report_acc][phase_label]
                
                # Find row index (Add 2 because Sheet usually has headers, Python list is 0-indexed)
                try:
                    row_idx = evaluations.index(best_eval) + 2
                    summary_node['row_index'] = row_idx
                except:
                    summary_node['row_index'] = '??'

                summary_node['profit'] += float(session_profit)
                
                # We need to count synthesized "deals" (which are actually positions) as 1 trade each
                summary_node['trades'] += len(session['deals'])
                summary_node['source_accounts'].add(str(acc_num))
                
                # Add detailed trade info
                for d in session['deals']:
                    t_profit = float(d.get('profit', 0))
                    t_comment = d.get('comment', '')
                    t_acc = extract_account_from_comment(t_comment) or "N/A"
                    
                    # Format timestamp
                    t_ts = get_ts(d)
                    t_time_str = "Unknown Time"
                    if t_ts > 0:
                        t_time_str = datetime.datetime.fromtimestamp(t_ts).strftime('%Y-%m-%d %H:%M:%S')

                    # Add to list (limit size if needed, but user asked for detail)
                    summary_node['detailed_trades'].append(f"[{t_time_str}] [{t_comment}] {t_acc} -> ${t_profit:.2f}")

                # Add sample comments (limit to 3 unique ones per phase to avoid spam)
                current_comments = [d.get('comment', '') for d in session['deals'] if d.get('comment')]
                for c in current_comments:
                    if len(summary_node['comments']) < 3:
                        summary_node['comments'].add(c)
                
            except Exception as e:
                logging.error(f"Error accumulating stats: {e}")
            # -------------------------------



        # CLEANUP: Remove temporary tracking fields before returning
        for ev in evaluations:
            if '_updated_fields' in ev:
                del ev['_updated_fields']
            if 'Match Log' in ev:
                del ev['Match Log']

        # --- LOG SUMMARY ---
        # "Group for me all trades under a specific propfirm, like topstep 2 trades etc, break it even further interms of the account number and phases"
        logging.info("="*30)
        logging.info(" TRADE PROCESSING SUMMARY")
        logging.info("="*30)
        
        # Sort firms
        sorted_firms = sorted(trade_summary.keys())
        for firm in sorted_firms:
             firm_data = trade_summary[firm]
             # Total trades for firm
             total_firm_trades = 0
             for acc_data in firm_data.values():
                 for stats in acc_data.values():
                     total_firm_trades += stats['trades']
                     
             logging.info(f"📂 {firm} ({total_firm_trades} trades)")
             
             sorted_accs = sorted(firm_data.keys(), key=lambda x: str(x))
             for acc in sorted_accs:
                  acc_data = firm_data[acc]
                  # Total trades for account
                  total_acc_trades = sum(item['trades'] for item in acc_data.values())
                  logging.info(f"   └── 👤 Dashboard Account: {acc} ({total_acc_trades} trades)")
                  
                  sorted_phases = sorted(acc_data.keys())
                  for phase in sorted_phases:
                       stats = acc_data[phase]
                       profit_str = f"${stats['profit']:,.2f}"
                       trades_count = stats['trades']
                       target_field = stats.get('target_field', 'Unknown')
                       
                       # Format comments and source accounts
                       sources_str = ", ".join(sorted(list(stats['source_accounts'])))
                       
                       row_idx = stats.get('row_index', '??')
                       
                       logging.info(f"       └── 🏷️  Phase {phase} -> [{target_field}] (Row #{row_idx})")
                       logging.info(f"           - Profit: {profit_str}")
                       logging.info(f"           - Trades: {trades_count}")
                       
                       # Detailed Trade Listing
                       count = 0
                       for t_detail in stats.get('detailed_trades', []):
                           logging.info(f"             - {t_detail}")
                           count += 1
                           if count > 50: # Safety limit
                               logging.info(f"             ... and {trades_count - 50} more")
                               break
                       
                       logging.info(f"           - Source ID(s): {sources_str}")
        logging.info("="*30)
        # -------------------

        # Return the computed sessions so they can be saved as 'aggregated_by_comment'
        return evaluations, match_log, sessions

    # -------------------------------------------------------------------------
    # LEGACY CLIENT-SIDE AGGREGATION LOGIC (Fallback)
    # -------------------------------------------------------------------------

    """
    Update evaluation hedge result fields from aggregated MT5 comment data.
    
    Args:
        evaluations: List of evaluation records
        aggregated_data: List of aggregated trade data with account_number, phase_code, etc.
    
    Returns:
        Tuple of (updated_evaluations, match_log)
    """
    if not evaluations or not aggregated_data:
        # If no server-side matching occurred (raw_deals was None), just return None for sessions
        return evaluations, ["No evaluations or aggregated data to process"], None
    
    match_log = []
    updates_made = 0
    
    match_log.append(f"📊 Processing {len(aggregated_data)} aggregated trade groups")
    match_log.append(f"   Against {len(evaluations)} evaluation records")
    
    # Sort aggregated data to ensure farming days are processed chronologically
    # Sort by account, then by timestamp (or farming_date)
    def sort_key(x):
        # Ensure consistent string type for comparison to avoid TypeError between float/str
        ts = x.get('timestamp') or x.get('farming_date') or ''
        return (
            str(x.get('account_number', '')),
            str(ts)
        )
    
    try:
        aggregated_data.sort(key=sort_key)
    except Exception as e:
        match_log.append(f"⚠️ Warning: Sorting failed ({str(e)}), processing unsorted.")
    
    # --- FNFT FILTERING LOGIC ---
    # For FundedNext accounts:
    # 1. Only process the active (latest) phase.
    # 2. Within that phase, only process the LATEST DAY (ignore prior history for same phase).
    
    # Map: account_sig -> (max_timestamp, (phase_code, trade_number))
    fnft_latest_phase_map = {} 
    
    # 1. Identify latest phase AND latest timestamp for that phase
    for agg in aggregated_data:
        acc = str(agg.get('account_number', '')).upper()
        if 'FNFT' in acc or 'FUNDEDNEXT' in acc:
            sig = get_account_signature(acc)
            ts = agg.get('timestamp') or 0
            
            # Update global max timestamp for account (determines active phase)
            curr_max_ts, curr_combo = fnft_latest_phase_map.get(sig, (0, None))
            
            if ts >= curr_max_ts:
                p_code = agg.get('phase_code')
                t_num = agg.get('trade_number')
                fnft_latest_phase_map[sig] = (ts, (p_code, t_num))

    # 2. Filter loop
    filtered_data = []
    for agg in aggregated_data:
        acc = str(agg.get('account_number', '')).upper()
        if 'FNFT' in acc or 'FUNDEDNEXT' in acc:
            sig = get_account_signature(acc)
            max_ts_global, latest_combo = fnft_latest_phase_map.get(sig, (0, None))
            
            this_combo = (agg.get('phase_code'), agg.get('trade_number'))
            this_ts = agg.get('timestamp') or 0
            this_phase_code = agg.get('phase_code', '')
            
            # Check 1: Is this the active phase?
            if latest_combo and this_combo != latest_combo:
                 match_log.append(f"⏩ FNFT: Skipping {acc} old phase {this_combo} (Active: {latest_combo})")
                 continue
            
            # Check 2: Age Check applied ONLY to Challenge (CH) phase
            # "only checking the current days trades will check this"
            if this_phase_code == 'CH':
                # Strictly filter to the "Current Day" (represented by max_ts_global).
                # We discard any data older than 18 hours from the latest timestamp.
                # This ensures we don't sum up "Old Reset" results (e.g. from 2 days ago)
                # with "New Reset" results (Today).
                AGE_THRESHOLD = 18 * 3600 # 18 hours (Current session only)
                time_diff = max_ts_global - this_ts
                
                if time_diff > AGE_THRESHOLD:
                     match_log.append(f"⏩ FNFT: Skipping {acc} old Challenge history {this_combo} (Age: {time_diff/3600:.1f}h)")
                     continue
            else:
                 # Pass through FA/FD/DD to allow standard logic as requested
                 pass

        filtered_data.append(agg)
        
    aggregated_data = filtered_data
    # ----------------------------

    # Track next available slot for Farming (FA) phase per evaluation
    # This ensures we overwrite from Day 1 sequentially instead of appending
    fa_slot_tracker = {}
    
    # Track accumulated values for standard phases (CH, FD, DD) because client now sends daily chunks
    # Key: (eval_idx, field_name) -> value
    accumulation_tracker = {}

    for agg in aggregated_data:
        account_number = agg.get('account_number', '')
        phase_code = agg.get('phase_code', '')
        trade_number = agg.get('trade_number')
        farming_date = agg.get('farming_date')
        net_profit = agg.get('net_profit', 0)
        deal_count = agg.get('deal_count', 0)
        
        if account_number and str(account_number).lower().startswith("unknown"):
             continue

        # Find matching evaluation
        matches = match_account_to_evaluation(account_number, evaluations, phase_code)
        
        # Use date filtering to pick the best match
        # Try to get timestamp from agg if available, otherwise it will fallback to first match
        trade_timestamp = agg.get('timestamp') 
        match = filter_matches_by_date(
            matches, 
            evaluations, 
            trade_timestamp, 
            phase_code=phase_code, 
            trade_number=trade_number
        )
        
        if not match:
            sig = get_account_signature(account_number)
            match_log.append(f"⚠️ No match: {account_number} ({sig}) _{phase_code}{trade_number or ''} = ${net_profit:.2f}")
            continue

        eval_idx, matched_account = match
        logging.info(f"MATCHED: MT5 Account {account_number} -> Dashboard Account {matched_account}")
        
        # Determine field to update
        field_name = None
        
        if phase_code == 'FA':
            # Special handling for Farming: Always overwrite sequentially from Day 1
            # Get next slot for this evaluation
            current_slot = fa_slot_tracker.get(eval_idx, 1)
            field_name = f"Hedge Day {current_slot}"
            fa_slot_tracker[eval_idx] = current_slot + 1
        else:
            field_name = get_field_name_for_phase(phase_code, trade_number, farming_date, evaluations, eval_idx, account_number)
        
        if not field_name:
            match_log.append(f"⚠️ Unknown field for {phase_code}{trade_number or ''}")
            continue
        
        # Determine whether to Accumulate (CH, FD, DD) or Overwrite (FA)
        # UPDATE: FNFT Challenge (CH) should NOT accumulate if we are strictly enforcing "Current Day" in client.
        # However, checking 'is_fnft' here is tricky without context.
        # But wait - if we are now only sending today's data, accumulation of *just today's* trades is correct if they came in multiple chunks.
        # But we do NOT want to read the OLD value from DB and add to it.
        # The logic below `accumulation_tracker[key] = current_val + float(net_profit)` only sums up what is in `aggregated_data` (the current request/payload).
        # It does NOT pull from evaluations[eval_idx][field_name] first.
        # So it is effectively a "Fresh Sum of Payload".
        # This is correct behavior for "Current Day Only" payload.
        
        should_accumulate = phase_code in ['CH', 'FD', 'DD']
        
        if should_accumulate:
            # Add to accumulator (sums up multiple entries in SAME payload)
            key = (eval_idx, field_name)
            current_val = accumulation_tracker.get(key, 0.0)
            accumulation_tracker[key] = current_val + float(net_profit)
            
            # Log individual contribution
            # sig = get_account_signature(account_number)
            # match_log.append(f"   + {account_number} ({sig}) → [{field_name}] += ${net_profit:.2f}")
        else:
            # Direct overwrite (Farming)
            evaluations[eval_idx][field_name] = net_profit
            updates_made += 1
            sig = get_account_signature(account_number)
            match_log.append(f"✅ {account_number} ({sig}) _{phase_code}{trade_number or ''} → [{field_name}] = ${net_profit:.2f}")
            match_log.append(f"   Matched to: {matched_account}")
            
    # Apply accumulated updates
    for (eval_idx, field_name), total_profit in accumulation_tracker.items():
        evaluations[eval_idx][field_name] = total_profit
        updates_made += 1
        # Log the final total update
        # We can't easily show which account number triggered it if multiple did, but usually it's one.
        match_log.append(f"✅ [Accumulated] → Eval #{eval_idx} [{field_name}] = ${total_profit:.2f}")
    
    match_log.append(f"\n📈 Total updates: {updates_made}/{len(aggregated_data)}")
    return evaluations, match_log, None

# Initialize admin password if not exists
def init_admin_password():
    """Initialize default admin password if not set."""
    admin_password = os.getenv('ADMIN_PASSWORD', 'BallerAdmin@123')
    set_admin_password('super_admin', admin_password)
    print("Admin password initialized")

# Run initialization
init_database()
init_admin_password()

def provision_hierarchy_passwords():
    """Auto-create user_credentials with default password for all hierarchy users who don't have one yet."""
    default_pw = 'Test@123'
    created = 0
    for admin_name, admin_data in hierarchy.get('admins', {}).items():
        if not user_exists(admin_name, 'admin'):
            if create_user(admin_name, default_pw, 'admin', admin_data.get('email')):
                created += 1
        for trader_name, trader_data in admin_data.get('traders', {}).items():
            if not user_exists(trader_name, 'trader'):
                if create_user(trader_name, default_pw, 'trader', trader_data.get('email'), admin_name):
                    created += 1
            for client in trader_data.get('clients', []):
                c_name = client.get('name') if isinstance(client, dict) else client
                c_email = client.get('email', '') if isinstance(client, dict) else ''
                if not user_exists(c_name, 'client'):
                    if create_user(c_name, default_pw, 'client', c_email, admin_name, trader_name):
                        created += 1
    if created:
        print(f"[AUTH] Provisioned {created} users with default password")

provision_hierarchy_passwords()

# ============ Authentication Decorators ============

def require_api_key(f):
    """Decorator to require valid API key for endpoint access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        client_ip = get_remote_address()
        
        if not api_key:
            log_action('API_ACCESS_DENIED', 'unknown', 'no_key', client_ip, 'Missing API key', False)
            return jsonify({"status": "error", "message": "API key required"}), 401
        
        user_info = validate_api_key(api_key)
        if not user_info:
            log_action('API_ACCESS_DENIED', 'unknown', api_key[:12], client_ip, 'Invalid API key', False)
            return jsonify({"status": "error", "message": "Invalid API key"}), 403
        
        # Reject read-only keys from full-access endpoints
        if user_info.get('scope') == 'readonly':
            log_action('API_ACCESS_DENIED', 'unknown', api_key[:12], client_ip, 'Readonly key on full-access endpoint', False)
            return jsonify({"status": "error", "message": "This API key is read-only and cannot access this endpoint"}), 403
        
        # Add user info to request context
        request.api_user = user_info
        log_action('API_ACCESS', 'trader', user_info.get('trader', 'unknown'), client_ip, f"Endpoint: {request.endpoint}")
        return f(*args, **kwargs)
    return decorated_function

def require_admin_password(f):
    """Decorator to require admin password for endpoint access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_ip = get_remote_address()
        
        # Check for password in request body or headers
        admin_password = None
        if request.is_json:
            admin_password = request.json.get('admin_password')
        if not admin_password:
            admin_password = request.headers.get('X-Admin-Password')
        
        if not admin_password:
            log_action('ADMIN_ACCESS_DENIED', 'admin', 'unknown', client_ip, 'Missing password', False)
            return jsonify({"status": "error", "message": "Admin password required"}), 401
        
        if not verify_admin_password('super_admin', admin_password):
            log_action('ADMIN_ACCESS_DENIED', 'admin', 'super_admin', client_ip, 'Invalid password', False)
            return jsonify({"status": "error", "message": "Invalid admin password"}), 403
        
        log_action('ADMIN_ACCESS', 'admin', 'super_admin', client_ip, f"Endpoint: {request.endpoint}")
        return f(*args, **kwargs)
    return decorated_function

def require_role(*allowed_roles):
    """Decorator to require specific roles via session authentication."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            session_token = request.cookies.get('session_token')
            
            if not session_token:
                return jsonify({"status": "error", "message": "Authentication required"}), 401
            
            session_info = validate_session(session_token)
            if not session_info:
                return jsonify({"status": "error", "message": "Invalid or expired session"}), 401
            
            user_type = session_info.get('user_type')
            if user_type not in allowed_roles:
                log_action('ACCESS_DENIED', user_type, session_info.get('user_identifier'), 
                          get_remote_address(), f"Required roles: {allowed_roles}", False)
                return jsonify({"status": "error", "message": "Access denied. Insufficient permissions."}), 403
            
            request.session_user = session_info
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_session(f):
    """Decorator to require valid session for web access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = request.cookies.get('session_token')
        
        if not session_token:
            return redirect(url_for('index'))
        
        session_info = validate_session(session_token)
        if not session_info:
            return redirect(url_for('index'))
        
        request.session_user = session_info
        return f(*args, **kwargs)
    return decorated_function

# ============ Web Routes ============

@app.route('/')
def index():
    # Check if already logged in
    session_token = request.cookies.get('session_token')
    if session_token:
        session_info = validate_session(session_token)
        if session_info:
            # Redirect to appropriate dashboard
            user_type = session_info.get('user_type')
            user_id = session_info.get('user_identifier')
            if user_type == 'super_admin':
                return redirect('/super_admin')
            elif user_type == 'admin':
                return redirect(f'/admin/{user_id}')
            elif user_type == 'trader':
                return redirect(f'/trader/{user_id}')
            elif user_type == 'client':
                return redirect(f'/dashboard/{user_id}')
    return render_template('login.html')

@app.route('/super_admin')
@require_session
def super_admin():
    if request.session_user.get('user_type') != 'super_admin':
        return redirect('/')
    return render_template('super_admin.html')

@app.route('/admin/<admin_name>')
@require_session
def admin_dashboard(admin_name):
    session_user = request.session_user
    # Allow super_admin to access any admin dashboard
    if session_user.get('user_type') == 'super_admin':
        return render_template('admin_dashboard.html', admin_name=admin_name)
    # Check if user is the correct admin
    if session_user.get('user_type') != 'admin' or session_user.get('user_identifier') != admin_name:
        return redirect('/')
    return render_template('admin_dashboard.html', admin_name=admin_name)

@app.route('/financial_overview')
@require_session
def financial_overview():
    session_user = request.session_user
    # Only allow super_admin
    if session_user.get('user_type') != 'super_admin':
         return redirect('/')
    
    profile_filter = request.args.get('profile', 'ALL')
    
    # NEW: Use optimized single-pass aggregator
    all_data = calculate_all_financials(profile_filter=profile_filter)
    
    overview_data = all_data['overview']
    global_stats = all_data.get('global_stats', {})
    growth_dates, growth_values = all_data['growth']
    payouts_dates, payouts_values = all_data['payouts']
    net_profit_dates, net_profit_values = all_data['net_profit']
    deposits_dates, deposits_values = all_data['deposits']
    fees_dates, fees_values = all_data['fees']
    hedge_dates, hedge_values = all_data['hedge']
    farming_dates, farming_values = all_data['farming']
    
    return render_template('financial_overview.html', 
                           overview=overview_data,
                           global_stats=global_stats,
                           selected_profile=profile_filter,
                           growth_dates=growth_dates,
                           growth_values=growth_values,
                           payouts_dates=payouts_dates,
                           payouts_values=payouts_values,
                           net_profit_dates=net_profit_dates,
                           net_profit_values=net_profit_values,
                           deposits_dates=deposits_dates,
                           deposits_values=deposits_values,
                           fees_dates=fees_dates,
                           fees_values=fees_values,
                           hedge_dates=hedge_dates,
                           hedge_values=hedge_values,
                           farming_dates=farming_dates,
                           farming_values=farming_values)

@app.route('/payout_history')
@require_session
def payout_history():
    session_user = request.session_user
    if session_user.get('user_type') != 'super_admin':
         return redirect('/')

    # Filter dates
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    start_date = None
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        except:
            pass
            
    end_date = None
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        except:
            pass

    prop_firm_filter = request.args.get('prop_firm')
    profile_filter = request.args.get('profile', 'ALL')
    
    # We need overview data just to get the list of prop firms for the dropdown
    overview_data = calculate_propfirm_overview()
    sorted_prop_firms = sorted(overview_data.keys())
    
    payouts_list = get_payouts_history(start_date, end_date, prop_firm_filter, profile_filter=profile_filter)
    
    return render_template('payout_history.html', 
                           payouts=payouts_list,
                           start_date=start_date_str,
                           end_date=end_date_str,
                           selected_prop_firm=prop_firm_filter,
                           selected_profile=profile_filter,
                           prop_firms=sorted_prop_firms)

@app.route('/client_performance')
@require_session
def client_performance():
    session_user = request.session_user
    if session_user.get('user_type') != 'super_admin':
         return redirect('/')
    return render_template('client_performance.html')

@app.route('/trader_performance')
@require_session
def trader_performance():
    session_user = request.session_user
    if session_user.get('user_type') != 'super_admin':
         return redirect('/')
         
    profile_filter = request.args.get('profile', 'ALL')
    traders_data = calculate_trader_stats(profile_filter=profile_filter)
    return render_template('trader_performance.html', traders=traders_data, selected_profile=profile_filter)


@app.route('/trader/<trader_name>')
@require_session
def trader_dashboard(trader_name):
    session_user = request.session_user
    # Allow super_admin to access any trader dashboard
    if session_user.get('user_type') == 'super_admin':
        return render_template('trader_dashboard.html', trader_name=trader_name)
    # Allow admin to access traders under them
    if session_user.get('user_type') == 'admin':
        return render_template('trader_dashboard.html', trader_name=trader_name)
    # Check if user is the correct trader
    if session_user.get('user_type') != 'trader' or session_user.get('user_identifier') != trader_name:
        return redirect('/')
    return render_template('trader_dashboard.html', trader_name=trader_name)

@app.route('/dashboard/<client_id>')
@require_session
def client_dashboard(client_id):
    session_user = request.session_user
    user_type = session_user.get('user_type')
    
    # Get client email for version history feature
    client_email = ''
    client_data = get_client_data(client_id)
    if client_data and client_data.get('identity'):
        client_email = client_data['identity'].get('email', '')
    
    # Allow super_admin, admin, and trader to access any client dashboard
    if user_type in ['super_admin', 'admin', 'trader']:
        return render_template('index.html', client_id=client_id, user_type=user_type, 
                               can_edit_hedging=True, client_email=client_email)
    # Check if user is the correct client
    if user_type != 'client' or session_user.get('user_identifier') != client_id:
        return redirect('/')
    return render_template('index.html', client_id=client_id, user_type=user_type, 
                           can_edit_hedging=False, client_email=client_email)

# ============ Hierarchy API with Role-Based Access Control ============

def get_filtered_hierarchy(user_type, user_identifier):
    """
    Returns hierarchy filtered based on user role:
    - super_admin: sees everything
    - admin: sees only their traders and clients
    - trader: sees only their clients
    - client: sees only themselves
    """
    full_hierarchy = hierarchy
    
    if user_type == 'super_admin':
        return full_hierarchy
    
    if user_type == 'admin':
        # Admin sees only their own data (case-insensitive match)
        admin_name = user_identifier
        admin_name_lower = admin_name.strip().lower()
        for key in full_hierarchy.get('admins', {}):
            if key.strip().lower() == admin_name_lower:
                return {
                    'admins': {
                        key: full_hierarchy['admins'][key]
                    }
                }
        return {'admins': {}}
    
    if user_type == 'trader':
        # Trader sees only their clients - need to find which admin they belong to
        trader_name = user_identifier.strip()
        trader_name_lower = trader_name.lower()
        for admin_name, admin_data in full_hierarchy.get('admins', {}).items():
            traders = admin_data.get('traders', {})
            for t_key in traders:
                if t_key.strip().lower() == trader_name_lower:
                    return {
                        'admins': {
                            admin_name: {
                                'email': '',  # Hide admin email from trader
                                'traders': {
                                    t_key: traders[t_key]
                                }
                            }
                        }
                    }
        return {'admins': {}}
    
    if user_type == 'client':
        # Client sees only themselves (case-insensitive match)
        client_name = user_identifier
        client_name_lower = client_name.strip().lower()
        for admin_name, admin_data in full_hierarchy.get('admins', {}).items():
            for trader_name, trader_data in admin_data.get('traders', {}).items():
                for client in trader_data.get('clients', []):
                    cname = (client.get('name') or '').strip().lower()
                    cemail = (client.get('email') or '').strip().lower()
                    if cname == client_name_lower or cemail == client_name_lower:
                        return {
                            'admins': {
                                admin_name: {
                                    'email': '',
                                    'traders': {
                                        trader_name: {
                                            'email': '',
                                            'clients': [client]
                                        }
                                    }
                                }
                            }
                        }
        return {'admins': {}}
    
    return {'admins': {}}

@app.route('/api/hierarchy')
def get_hierarchy():
    """Returns hierarchy filtered by user's role."""
    session_token = request.cookies.get('session_token')
    
    if not session_token:
        # Check for simple API key header for scripts
        api_key = request.headers.get('X-API-Key')
        if not api_key:
             return jsonify({"status": "error", "message": "Authentication required"}), 401
    
    user_type = 'super_admin' # Fallback for trusted scripts
    user_identifier = 'baller'
    
    if session_token:
        session_info = validate_session(session_token)
        if not session_info:
            return jsonify({"status": "error", "message": "Invalid session"}), 401
        
        user_type = session_info.get('user_type')
        user_identifier = session_info.get('user_identifier')
    
    # Reload hierarchy to get latest changes from file
    from config.hierarchy import reload_hierarchy
    reload_hierarchy()
    
    filtered = get_filtered_hierarchy(user_type, user_identifier)
    
    # Debug logging for empty hierarchy results
    if not filtered.get('admins') or all(
        not admin_data.get('traders', {}) for admin_data in filtered.get('admins', {}).values()
    ):
        logging.warning(f"[HIERARCHY] Empty result for user_type={user_type} user_identifier='{user_identifier}' — available trader keys: {[t for a in hierarchy.get('admins', {}).values() for t in a.get('traders', {}).keys()]}")
    
    return jsonify(filtered)

from dashboard.financial_overview import calculate_all_financials

@app.route('/api/super_admin/totals')
def get_super_admin_totals():
    """Get aggregated totals across all clients for super admin dashboard."""
    session_token = request.cookies.get('session_token')
    
    if not session_token:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    
    # Check session
    # ... (auth check logic is fine, keeping it implicitly via context if needed or re-implementing if I replace the whole function body)
    # The snippet below replaces the body.
    
    session_info = validate_session(session_token)
    if not session_info or session_info.get('user_type') != 'super_admin':
        return jsonify({"status": "error", "message": "Super admin access required"}), 403
    
    profile_filter = request.args.get('profile', 'ALL').upper()

    # Use the centralized financial calculation
    data = calculate_all_financials(profile_filter)
    stats = data['global_stats']
    overview = data['overview']
    
    # Calculate Deposits separately if not in global_stats
    # In financial_overview.py, deposits are in data['deposits'] tuple (dates, cum_values)
    # The last value of cum_values is the total.
    total_deposits = 0.0
    if data.get('deposits') and data['deposits'][1]:
        total_deposits = data['deposits'][1][-1]
        
    # Calculate Totals
    active_accounts = 0
    passed_accounts = 0
    failed_accounts = 0
    
    total_hedge = 0.0
    total_farming = 0.0
    
    for firm, f_data in overview.items():
        active_accounts += f_data.get('active_accounts', 0)
        passed_accounts += f_data.get('passed_accounts', 0)
        failed_accounts += f_data.get('failed_accounts', 0)
        total_hedge += f_data.get('hedge_results', 0.0)
        total_farming += f_data.get('farming_results', 0.0)
        
    response_data = {
        "status": "success",
        "totals": {
            "total_payouts": 0.0, # Not in global_stats explicitly, need to sum?
            # global_stats keys: net, ended, expected_value, ev_per_day
            "total_deposits": round(total_deposits, 2),
            "total_fees": 0.0,
            "total_net_profit": round(stats.get('net', 0), 2),
            "active_accounts": active_accounts,
            "completed_accounts": passed_accounts,
            "failed_accounts": failed_accounts,
            "total_hedge": round(total_hedge, 2),
            "total_farming": round(total_farming, 2),
            "expected_value": round(stats.get('expected_value', 0), 2),
            "ev_per_day": round(stats.get('ev_per_day', 0), 2)
        }
    }
    
    # Sum up Payouts and Fees from overview to fill gaps
    t_pay = 0.0
    t_fees = 0.0
    for firm, f_data in overview.items():
        t_pay += f_data.get('total_payouts', 0)
        t_fees += f_data.get('total_fees', 0) + f_data.get('total_activation_fees', 0)
        
    response_data['totals']['total_payouts'] = round(t_pay, 2)
    response_data['totals']['total_fees'] = round(t_fees, 2)
    
    # Add Client Performance Stats used by client_performance.html
    response_data['clients'] = get_client_performance_stats(profile_filter)

    # 4. Global Watermarks (14 days)
    # Import here to avoid circular
    from dashboard.watermark_service import get_aggregate_watermarks
    global_watermarks = get_aggregate_watermarks(14)
    
    # Ensure values are non-negative
    hwm = global_watermarks.get('hwm', 0.0)
    lwm = global_watermarks.get('lwm', 0.0)
    
    response_data['totals']['total_hwm'] = round(max(0.0, float(hwm)), 2)
    response_data['totals']['total_lwm'] = round(max(0.0, float(lwm)), 2)
    
    return jsonify(response_data)

@app.route('/api/super_admin/recalculate_stats', methods=['POST'])
@require_session
def recalculate_all_stats():
    """Recalculate and save statistics for all clients from stored evaluations."""
    if request.session_user.get('user_type') != 'super_admin':
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    from utils.data_processor import calculate_statistics
    all_clients = get_all_clients()
    results = []
    for client_id, client_data in all_clients.items():
        try:
            evals = client_data.get('evaluations', [])
            existing_mt5 = client_data.get('account')
            existing_hr = client_data.get('statistics', {}).get('hedging_review', {})
            existing_hist = existing_hr.get('historical_accounts')
            old_fees = client_data.get('statistics', {}).get('profitability_completed', {}).get('challenge_fees', 0)
            new_stats = calculate_statistics(evals, mt5_account=existing_mt5, historical_accounts=existing_hist)
            # Preserve historical account fields
            if existing_hist:
                new_stats.setdefault('hedging_review', {})['historical_accounts'] = existing_hist
                new_stats['hedging_review']['historical_deposits'] = existing_hr.get('historical_deposits', 0)
                new_stats['hedging_review']['historical_withdrawals'] = existing_hr.get('historical_withdrawals', 0)
                new_stats['hedging_review']['historical_balance'] = existing_hr.get('historical_balance', 0)
            new_fees = new_stats.get('profitability_completed', {}).get('challenge_fees', 0)
            save_client_data(client_id, {'statistics': new_stats})
            results.append({"client_id": client_id, "old_fees": old_fees, "new_fees": new_fees, "changed": abs(float(new_fees) - float(old_fees)) > 0.01})
        except Exception as e:
            results.append({"client_id": client_id, "error": str(e)})
    return jsonify({"status": "success", "recalculated": len(results), "results": results})

@app.route('/api/client/update_source', methods=['POST'])
@require_session
def update_client_source():
    """Update client source (BEF/Private)."""
    session_user = request.session_user
    if session_user.get('user_type') != 'super_admin':
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
        
    data = request.get_json(silent=True) or {}
    client_id = data.get('client_id')
    source = data.get('source')
    allowed = ['BEF', 'Private']

    if not client_id or source not in allowed:
        return jsonify({"status": "error", "message": "Invalid data"}), 400
    
    # Update Database
    client_data = get_client_data(client_id)
    if not client_data:
        return jsonify({"status": "error", "message": "Client not found"}), 404
        
    identity = client_data.get('identity', {}) or {}
    # Update all relevant fields for consistency
    identity['profile'] = source
    identity['category'] = source
    identity['source'] = source
    update_client_field(client_id, 'identity', identity)

    # clear cache
    from dashboard.financial_overview import clear_financial_cache
    clear_financial_cache()
    
    # Also update Hierarchy.json if possible
    try:
        from config.hierarchy import get_client_profile, update_client_category
        profile = get_client_profile(client_id)
        if profile:
            update_client_category(profile['admin'], profile['trader'], client_id, source)
    except Exception as e:
        log_action('UPDATE_CLIENT_SOURCE', 'super_admin', client_id, get_remote_address(), str(e), success=False)
    
    log_action('UPDATE_CLIENT_SOURCE', 'super_admin', client_id, get_remote_address(), f"To: {source}")
    return jsonify({"status": "success"})

@app.route('/api/client/lookup', methods=['POST'])
@require_api_key
def api_client_lookup():
    """Look up client hierarchy info by email."""
    email = request.json.get('email', '').strip()
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    client = get_client_by_email(email)
    if client:
        return jsonify({
            "status": "success",
            "client": client['client'],
            "trader": client['trader'],
            "admin": client['admin'],
            "email": client['email']
        })
    
    return jsonify({"status": "error", "message": "Email not found in system"}), 404


@app.route('/api/check_email', methods=['GET', 'POST', 'OPTIONS'], strict_slashes=False)
def api_check_email():
    """
    Check whether an email (or username) exists in the system.

    Accepts both GET (?email=...) and POST (JSON body: {"email": "..."}).
    Requires X-API-Key header (accepts both 'full' and 'readonly' scoped keys).

    Response (200):
        {"exists": true,  "user_type": "client", "username": "John Doe"}
        {"exists": false}
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({"status": "ok"})
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key'
        return response, 200

    # Manual key validation — accepts both 'full' and 'readonly' scope
    api_key = request.headers.get('X-API-Key')
    client_ip = get_remote_address()
    if not api_key:
        return jsonify({"status": "error", "message": "API key required"}), 401
    user_info = validate_api_key(api_key)
    if not user_info:
        log_action('API_ACCESS_DENIED', 'unknown', api_key[:12], client_ip, 'Invalid API key on check_email', False)
        return jsonify({"status": "error", "message": "Invalid API key"}), 403
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        email = data.get('email', '').strip()
    else:
        email = request.args.get('email', '').strip()

    if not email:
        return jsonify({"status": "error", "message": "email parameter required"}), 400

    from dashboard.database import find_user_by_identifier
    from config.hierarchy import reload_hierarchy

    def _find_client_email(search_email):
        """Check both user_credentials (DB) and hierarchy.json for a client with this email."""
        search_email_lower = search_email.lower()
        # 1. Check DB
        user = find_user_by_identifier(search_email)
        if user and user.get('user_type') == 'client':
            return {'username': user.get('username'), 'source': 'db'}
        # 2. Check hierarchy.json
        h = reload_hierarchy()
        for admin_data in h.get('admins', {}).values():
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    if (client.get('email') or '').lower() == search_email_lower:
                        return {'username': client.get('name', ''), 'source': 'hierarchy'}
        return None

    found = _find_client_email(email)
    if found:
        return jsonify({
            "exists": True,
            "user_type": "client",
            "username": found['username']
        })

    return jsonify({"exists": False})


@app.route('/api/list_emails', methods=['GET', 'POST', 'OPTIONS'], strict_slashes=False)
def api_list_emails():
    """
    GET  — Return all emails registered in the system (each entry includes exists: true).
    POST — Bulk check: pass {"emails": ["a@b.com", ...]} and get back exists true/false per email.

    Requires X-API-Key header (accepts both 'full' and 'readonly' scoped keys).

    GET query params:
        ?user_type=client|trader|admin   — filter by role (default: all)
        ?active_only=true                — only include active accounts (default: true)

    GET response:
        {"count": 2, "emails": [
            {"email": "john@example.com", "username": "John", "user_type": "client", "exists": true},
            ...
        ]}

    POST response:
        {"results": [
            {"email": "john@example.com", "exists": true,  "user_type": "client", "username": "John"},
            {"email": "unknown@x.com",    "exists": false}
        ]}
    """
    if request.method == 'OPTIONS':
        response = jsonify({"status": "ok"})
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key'
        return response, 200

    # Validate key — accepts readonly and full scopes
    api_key = request.headers.get('X-API-Key')
    client_ip = get_remote_address()
    if not api_key:
        return jsonify({"status": "error", "message": "API key required"}), 401
    user_info = validate_api_key(api_key)
    if not user_info:
        log_action('API_ACCESS_DENIED', 'unknown', api_key[:12], client_ip, 'Invalid API key on list_emails', False)
        return jsonify({"status": "error", "message": "Invalid API key"}), 403

    from dashboard.database import list_users, find_user_by_identifier
    from config.hierarchy import reload_hierarchy

    def _all_hierarchy_clients():
        """Return all clients from hierarchy.json as a list of {email, username} dicts."""
        results = []
        h = reload_hierarchy()
        for admin_data in h.get('admins', {}).values():
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    email = (client.get('email') or '').strip()
                    if email:
                        results.append({'email': email, 'username': client.get('name', '')})
        return results

    def _find_client_email(search_email):
        search_email_lower = search_email.lower()
        user = find_user_by_identifier(search_email)
        if user and user.get('user_type') == 'client':
            return {'username': user.get('username')}
        h = reload_hierarchy()
        for admin_data in h.get('admins', {}).values():
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    if (client.get('email') or '').lower() == search_email_lower:
                        return {'username': client.get('name', '')}
        return None

    # ── POST: bulk existence check ──────────────────────────────────────────
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        emails_to_check = data.get('emails', [])
        if not isinstance(emails_to_check, list):
            return jsonify({"status": "error", "message": "'emails' must be a list"}), 400

        results = []
        for email in emails_to_check:
            email = str(email).strip()
            if not email:
                continue
            found = _find_client_email(email)
            if found:
                results.append({
                    "email": email,
                    "exists": True,
                    "user_type": "client",
                    "username": found['username']
                })
            else:
                results.append({"email": email, "exists": False})

        log_action('API_ACCESS', 'reader', user_info.get('trader', 'unknown'), client_ip,
                   f"bulk_check_emails: {len(results)} checked")
        return jsonify({"results": results})

    # ── GET: return all client emails (DB + hierarchy.json) ─────────────────
    active_only = request.args.get('active_only', 'true').lower() != 'false'

    # Collect from DB
    seen_emails = set()
    results = []
    for u in list_users(user_type='client'):
        if active_only and not u.get('is_active'):
            continue
        email = (u.get('email') or '').strip()
        if email:
            seen_emails.add(email.lower())
            results.append({'email': email, 'username': u.get('username'), 'user_type': 'client', 'exists': True})

    # Also collect from hierarchy.json (clients not in DB)
    for c in _all_hierarchy_clients():
        if c['email'].lower() not in seen_emails:
            seen_emails.add(c['email'].lower())
            results.append({'email': c['email'], 'username': c['username'], 'user_type': 'client', 'exists': True})

    log_action('API_ACCESS', 'reader', user_info.get('trader', 'unknown'), client_ip,
               f"list_emails: {len(results)} returned")
    return jsonify({"count": len(results), "emails": results})


# ============ PUBLIC CLIENT API (No API Key Required) ============

@app.route('/api/client/auth', methods=['POST'])
@limiter.limit("30 per minute")
def api_client_auth():
    """
    Public endpoint - authenticate client by email only.
    Returns client hierarchy info if email exists in system.
    No API key required - just the client email.
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"status": "error", "message": "Invalid JSON or Content-Type"}), 400
            
        email = data.get('email', '').strip().lower()
        
        if not email:
            return jsonify({"status": "error", "message": "Email required"}), 400
        
        client = get_client_by_email(email)
        
        # Safe logging
        try:
            remote_addr = get_remote_address()
        except:
            remote_addr = "0.0.0.0"

        if client:
            try:
                log_action('CLIENT_AUTH', 'client', email, remote_addr, 'Email verified')
            except Exception as e:
                print(f"Log action error: {e}", file=sys.stderr)
                
            return jsonify({
                "status": "success",
                "identity": {
                    "admin": client['admin'],
                    "trader": client['trader'],
                    "client": client['client'],
                    "email": client['email'],
                    "category": client.get('category', '')
                }
            })
        
        try:
            log_action('CLIENT_AUTH_FAILED', 'client', email, remote_addr, 'Email not found', False)
        except:
            pass
            
        return jsonify({"status": "error", "message": "Email not registered in the system"}), 404
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/client/push', methods=['POST'])
@limiter.limit("60 per minute")
def api_client_push():
    """
    Public endpoint - push data using client email only (no API key).
    Automatically looks up hierarchy from email.
    Recalculates statistics using MT5 deals/account data if provided.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    # Look up client by email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered in the system"}), 404
    
    admin_id = client_info['admin']
    trader_id = client_info['trader']
    client_id = client_info['client']
    
    # Get MT5 data from push
    mt5_deals = data.get("deals", [])
    mt5_account = data.get("account", {})
    
    # Get existing data to merge evaluations if needed
    existing_data = get_client_data(client_id) or {}
    
    # Only use new evaluations if explicitly provided and not empty
    # If "evaluations" key is missing or None, preserve existing data
    if "evaluations" in data and data["evaluations"]:
        evaluations = data["evaluations"]
        app.logger.info(f"   Using {len(evaluations)} NEW evaluations from push")
    else:
        evaluations = existing_data.get("evaluations", [])
        app.logger.info(f"   Preserving {len(evaluations)} EXISTING evaluations")
    
    # Normalize Account Size values to standard format
    evaluations = normalize_evaluations(evaluations)
    
    # Check for aggregated comment data (from Push by Comment feature) OR raw deals
    aggregated_by_comment = data.get("aggregated_by_comment", [])
    comment_summary = data.get("comment_summary", {})
    hedge_match_log = []
    
    if aggregated_by_comment or mt5_deals:
        app.logger.info(f"📋 Received {len(aggregated_by_comment)} aggregated groups, {len(mt5_deals)} raw deals")
        
        # Update evaluations with hedge results from aggregated data OR raw deals
        if evaluations:
            app.logger.info(f"🔄 Matching hedge results to evaluations...")
            evaluations, hedge_match_log, generated_sessions = update_evaluations_from_aggregated_data(evaluations, aggregated_data=aggregated_by_comment, raw_deals=mt5_deals)
            
            # If server-side aggregation occurred, use THAT instead of the client's.
            if generated_sessions:
                aggregated_by_comment = generated_sessions
                app.logger.info(f"✅ Replaced client aggregation with {len(generated_sessions)} server-side sessions")
            
            for log_line in hedge_match_log:
                app.logger.info(f"   {log_line}")
    
    # Debug logging
    acct_balance = mt5_account.get('balance', 0) if mt5_account else 0
    app.logger.info(f"📥 Push for {client_id}: {len(mt5_deals)} deals, balance={acct_balance}, {len(evaluations)} evaluations")
    
    # Log deal types to debug
    if mt5_deals:
        deal_types = [str(d.get('type', 'unknown')) for d in mt5_deals[:5]]
        app.logger.info(f"   Sample deal types: {deal_types}")
    
    # ALWAYS recalculate statistics when we have evaluations or MT5 data
    # This ensures discrepancy is only calculated when we have actual MT5 data
    statistics = data.get("statistics", {})
    push_sheet_url = existing_data.get('sheet_url') or (existing_data.get('identity') or {}).get('sheet_url')
    if evaluations or mt5_deals or mt5_account:
        try:
            from utils.data_processor import calculate_statistics
            
            # Log what we're passing to calculate_statistics
            app.logger.info(f"🔧 Calling calculate_statistics with:")
            app.logger.info(f"   - mt5_account type: {type(mt5_account)}, has data: {bool(mt5_account)}")
            if mt5_account:
                app.logger.info(f"   - mt5_account.balance: {mt5_account.get('balance', 'N/A')}")
                app.logger.info(f"   - mt5_account.total_deposits: {mt5_account.get('total_deposits', 'N/A')}")
                app.logger.info(f"   - mt5_account.total_withdrawals: {mt5_account.get('total_withdrawals', 'N/A')}")
            
            # Pass MT5 data - if empty, discrepancy will be 0
            mt5_acc_param = mt5_account if mt5_account else None
            mt5_deals_param = mt5_deals if mt5_deals else None
            
            # Fetch Stats tab values from Google Sheet so the SUMIF stats
            # use formula-precision values instead of CSV-rounded values.
            push_xlsx_notes = None
            if push_sheet_url:
                try:
                    from utils.data_processor import fetch_evaluations as _fe
                    _result = _fe(push_sheet_url)
                    if isinstance(_result, tuple) and len(_result) == 2:
                        _, push_xlsx_notes = _result
                        if push_xlsx_notes and '__stats_tab__' in push_xlsx_notes:
                            app.logger.info(f"📊 Stats tab override loaded from sheet")
                except Exception as _e:
                    app.logger.warning(f"Stats tab fetch failed (non-critical): {_e}")
            
            statistics = calculate_statistics(evaluations, mt5_deals_param, mt5_acc_param, xlsx_notes=push_xlsx_notes,
                                              historical_accounts=existing_data.get('statistics', {}).get('hedging_review', {}).get('historical_accounts'))
            
            # Preserve historical MT5 accounts from existing data
            existing_hr = existing_data.get('statistics', {}).get('hedging_review', {})
            if 'historical_accounts' in existing_hr:
                statistics.setdefault('hedging_review', {})['historical_accounts'] = existing_hr['historical_accounts']
                statistics['hedging_review']['historical_deposits'] = existing_hr.get('historical_deposits', 0)
                statistics['hedging_review']['historical_withdrawals'] = existing_hr.get('historical_withdrawals', 0)
                statistics['hedging_review']['historical_balance'] = existing_hr.get('historical_balance', 0)
            
            # Push-once: if hedging_review was already populated (non-zero deposits
            # or balance), keep the existing values. Only the first push or manual
            # edits via /api/hedging_review can set these.
            if existing_hr.get('total_deposits', 0) != 0 or existing_hr.get('current_balance', 0) != 0:
                app.logger.info(f"📌 Hedging review already populated — preserving existing values (push-once)")
                statistics['hedging_review'] = existing_hr
            
            # Log the hedging review results
            hr = statistics.get('hedging_review', {})
            app.logger.info(f"Stats calculated:")
            app.logger.info(f"   - Current balance: ${hr.get('current_balance', 0):.2f}")
            app.logger.info(f"   - Total deposits: ${hr.get('total_deposits', 0):.2f}")
            app.logger.info(f"   - Total withdrawals: ${hr.get('total_withdrawals', 0):.2f}")
            app.logger.info(f"   - Actual hedging: ${hr.get('actual_hedging_results', 0):.2f}")
            
            # Debug info
            if '_debug_deal_count' in hr:
                app.logger.info(f"   - Debug: {hr.get('_debug_deal_count')} deals processed, types seen: {hr.get('_debug_deal_types', [])}")
        except Exception as e:
            app.logger.error(f"Error recalculating stats: {e}")
            import traceback
            app.logger.error(traceback.format_exc())
            # Keep the provided statistics if recalc fails
    
    # Prepare client data
    client_data = {
        "deals": mt5_deals,
        "positions": data.get("positions", []),
        "account": mt5_account,
        "evaluations": evaluations,
        "statistics": statistics,
        "dropdown_options": data.get("dropdown_options", {}),
        "identity": {
            "admin": admin_id,
            "trader": trader_id,
            "client": client_id,
            "email": email,
            "sheet_url": push_sheet_url
        },
        # Store aggregated comment data if provided (from Push by Comment feature)
        "aggregated_by_comment": aggregated_by_comment if aggregated_by_comment else existing_data.get("aggregated_by_comment", []),
        "comment_summary": comment_summary if comment_summary else existing_data.get("comment_summary", {})
    }
    
    # Final verification before save
    hr_final = statistics.get('hedging_review', {})
    app.logger.info(f"FINAL DATA TO SAVE for {client_id}:")
    app.logger.info(f"   - hedging_review.total_deposits: ${hr_final.get('total_deposits', 0):.2f}")
    app.logger.info(f"   - hedging_review.total_withdrawals: ${hr_final.get('total_withdrawals', 0):.2f}")
    app.logger.info(f"   - hedging_review.current_balance: ${hr_final.get('current_balance', 0):.2f}")
    app.logger.info(f"   - account.total_deposits: ${mt5_account.get('total_deposits', 0) if mt5_account else 0:.2f}")
    if aggregated_by_comment:
        app.logger.info(f"   - aggregated_by_comment: {len(aggregated_by_comment)} groups")
    
    # Determine change source for history tracking
    change_source = 'trader_app'
    if aggregated_by_comment:
        change_source = 'mt5_push_with_comments'
    elif mt5_account or mt5_deals:
        change_source = 'mt5_push'
    
    # Save to database WITH history tracking
    success, version = save_client_data_with_history(
        client_id, 
        client_data,
        action='DATA_PUSH',
        changed_by=email,
        changed_by_type='client',
        ip_address=get_remote_address(),
        change_source=change_source,
        change_description=f"Data push from trader app with {len(evaluations)} evaluations"
    )
    
    # Update Hierarchy (in case new)
    add_admin(admin_id)
    add_trader(admin_id, trader_id)
    add_client(admin_id, trader_id, client_id)
    
    log_action('CLIENT_DATA_PUSH', 'client', email, get_remote_address(), f"Data pushed for {client_id} (v{version})")
    
    response_data = {
        "status": "success", 
        "message": f"Data updated for {client_id}",
        "version": version,
        "identity": {
            "admin": admin_id,
            "trader": trader_id,
            "client": client_id
        }
    }
    
    # Include hedge match log if we processed aggregated data
    if hedge_match_log:
        response_data["hedge_match_log"] = hedge_match_log
        response_data["hedge_updates"] = len([l for l in hedge_match_log if l.startswith("✅")])
    
    return jsonify(response_data)


@app.route('/api/client/migrate_sheet', methods=['POST'])
@limiter.limit("10 per minute")
def api_migrate_sheet():
    """
    Public endpoint - migrate data from Google Sheets using client email.
    Fetches data from Google Sheet and pushes it to the dashboard.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    sheet_url = data.get('sheet_url', '').strip()
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    if not sheet_url:
        return jsonify({"status": "error", "message": "Google Sheet URL required"}), 400
    
    # Look up client by email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered in the system"}), 404
    
    admin_id = client_info['admin']
    trader_id = client_info['trader']
    client_id = client_info['client']
    
    # Fetch data from Google Sheets
    try:
        # Import the data processor
        from utils.data_processor import fetch_evaluations, calculate_statistics, fetch_waterlog_history
        from dashboard.watermark_service import bulk_save_history
        import concurrent.futures

        try:
            from utils.sheet_helper import fetch_waterlog_data, fetch_waterlog_periods_from_sheet
        except ImportError:
            try:
                from dashboard.utils.sheet_helper import fetch_waterlog_data, fetch_waterlog_periods_from_sheet
            except ImportError:
                fetch_waterlog_data = None
                fetch_waterlog_periods_from_sheet = None
        try:
            from dashboard.watermark_service import save_waterlog_periods
        except ImportError:
            from watermark_service import save_waterlog_periods

        # Fetch evaluations, waterlog history and waterlog data in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_eval = executor.submit(fetch_evaluations, sheet_url)
            future_wl_hist = executor.submit(fetch_waterlog_history, sheet_url)
            future_wl_data = executor.submit(fetch_waterlog_data, sheet_url) if fetch_waterlog_data else None

            eval_result = future_eval.result()
            waterlog_history = future_wl_hist.result()
            wl_full = future_wl_data.result() if future_wl_data else None

        if isinstance(eval_result, tuple):
            evaluations, xlsx_notes = eval_result
        else:
            evaluations = eval_result
            xlsx_notes = {}
        if not evaluations:
            return jsonify({"status": "error", "message": "Could not fetch data from sheet. Make sure it's shared as 'Anyone with the link'. (Evaluations Tab)"}), 400
        
        # Save daily waterlog history
        waterlog_count = 0
        if waterlog_history:
            bulk_save_history(client_id, waterlog_history)
            waterlog_count = len(waterlog_history)

        # Save the bi-weekly period schedule WITH Low/High values
        if wl_full:
            from datetime import datetime as _wldt
            import re as _re

            def _parse_currency_str(s):
                try:
                    return float(_re.sub(r'[^0-9.\-]', '', str(s))) if s else None
                except Exception:
                    return None

            def _to_iso(date_str):
                """Convert M/D/YYYY to YYYY-MM-DD."""
                try:
                    return _wldt.strptime(date_str.strip(), '%m/%d/%Y').strftime('%Y-%m-%d')
                except Exception:
                    return None

            wl_periods = []
            wl_values  = {}
            for row in wl_full:
                fd = _to_iso(row.get('from_date', ''))
                td = _to_iso(row.get('to_date', ''))
                if fd and td:
                    wl_periods.append((fd, td))
                    low  = _parse_currency_str(row.get('low'))
                    high = _parse_currency_str(row.get('high'))
                    if low is not None or high is not None:
                        wl_values[fd] = {
                            'low':       low,
                            'high':      high,
                            'split_pct': row.get('split_pct', 25),
                        }

            if wl_periods:
                save_waterlog_periods(client_id, wl_periods, period_values=wl_values)
        elif fetch_waterlog_periods_from_sheet:
            # Fallback: save dates only (no Low/High)
            wl_periods = fetch_waterlog_periods_from_sheet(sheet_url)
            if wl_periods:
                save_waterlog_periods(client_id, wl_periods)
        
        # Get existing data to preserve MT5 account and historical accounts
        existing_import_data = get_client_data(client_id) or {}
        existing_mt5 = existing_import_data.get('account') or None
        existing_hist = existing_import_data.get('statistics', {}).get('hedging_review', {}).get('historical_accounts')
        
        # Calculate statistics including existing MT5 data and historical accounts
        statistics = calculate_statistics(evaluations, None, existing_mt5 if existing_mt5 else None, xlsx_notes=xlsx_notes,
                                          historical_accounts=existing_hist)
        
        # Preserve historical accounts in the new statistics
        if existing_hist:
            existing_hr = existing_import_data.get('statistics', {}).get('hedging_review', {})
            statistics.setdefault('hedging_review', {})['historical_accounts'] = existing_hist
            statistics['hedging_review']['historical_deposits'] = existing_hr.get('historical_deposits', 0)
            statistics['hedging_review']['historical_withdrawals'] = existing_hr.get('historical_withdrawals', 0)
            statistics['hedging_review']['historical_balance'] = existing_hr.get('historical_balance', 0)
        
        # Prepare client data
        client_data = {
            "deals": existing_import_data.get('deals', []),
            "positions": existing_import_data.get('positions', []),
            "account": existing_mt5 or {},
            "evaluations": evaluations,
            "statistics": statistics,
            "dropdown_options": {},
            "identity": {
                "admin": admin_id,
                "trader": trader_id,
                "client": client_id,
                "email": email,
                "sheet_url": sheet_url
            },
            "sheet_url": sheet_url,
            "migrated_at": datetime.now().isoformat()
        }
        
        # Save to database WITH history tracking - full overwrite (import replaces all existing data)
        success, version = save_client_data_with_history(
            client_id, 
            client_data,
            action='SHEET_IMPORT',
            changed_by=email,
            changed_by_type='client',
            ip_address=get_remote_address(),
            change_source='sheet_migration',
            change_description=f"Imported {len(evaluations)} records from Google Sheets",
            overwrite=True
        )
        
        # Save cell comments as notes (for Prop Progress display)
        notes_saved = 0
        if xlsx_notes:
            for row_idx, col_notes in xlsx_notes.items():
                if isinstance(row_idx, int) and isinstance(col_notes, dict):
                    for col_key, content in col_notes.items():
                        if content and str(content).strip():
                            save_client_note(client_id, row_idx, col_key, str(content).strip(), 'sheet_import')
                            notes_saved += 1

        # Update Hierarchy
        add_admin(admin_id)
        add_trader(admin_id, trader_id)
        add_client(admin_id, trader_id, client_id)
        
        log_action('SHEET_MIGRATION', 'client', email, get_remote_address(), 
                   f"Migrated {len(evaluations)} records + {waterlog_count} waterlog entries + {notes_saved} notes from Google Sheets for {client_id} (v{version})")
        
        # Return statistics for verification
        return jsonify({
            "status": "success", 
            "message": f"Successfully migrated {len(evaluations)} records and {waterlog_count} waterlog entries",
            "records_imported": len(evaluations),
            "version": version,
            "statistics": statistics,  # Include stats for client-side verification
            "identity": {
                "admin": admin_id,
                "trader": trader_id,
                "client": client_id
            }
        })
        
    except Exception as e:
        log_action('SHEET_MIGRATION_FAILED', 'client', email, get_remote_address(), str(e), False)
        return jsonify({"status": "error", "message": f"Migration failed: {str(e)}"}), 500


@app.route('/api/client/watermark_history/<client_id>')
@require_session
def api_get_watermark_history(client_id):
    """
    Get daily watermark history for a client.
    Restricted: Clients can only see their own waterlog history.
    """
    session_user = request.session_user
    user_type = session_user.get('user_type')
    user_id = session_user.get('user_identifier')
    
    # Handle URL encoding spaces if necessary (Flask usually decodes)
    # Check authorization
    is_authorized = False
    if user_type in ['super_admin', 'admin', 'trader']:
        is_authorized = True
    elif user_type == 'client':
        # Check specific client ownership
        if user_id == client_id:
            is_authorized = True
        else:
            # Check if email matches (some systems use email as identifier)
            # Or if user_id is the email and client_id is the name?
            # 'client_id' in URL is the NAME (e.g. Jiang Quang Huang)
            # 'user_identifier' in session for client is usually the EMAIL.
            # We need to resolve email -> client_id
            client_by_email = get_client_by_email(user_id)
            if client_by_email and client_by_email['client'] == client_id:
                is_authorized = True
    
    if not is_authorized:
        return jsonify({"status": "error", "message": "Unauthorized access to client waterlog"}), 403

    try:
        from dashboard.watermark_service import get_watermark_history, get_lower_watermark, save_daily_profit
        from dashboard.database import get_client_data

        # --- Always snapshot today's live net profit so the Low Watermark is current ---
        today_str = __import__('datetime').datetime.now().strftime('%Y-%m-%d')
        try:
            client_data = get_client_data(client_id)
            if client_data:
                # Pull net profit directly from stored statistics
                # (already includes discrepancy from the last data push)
                stored_stats = client_data.get('statistics', {})
                live_net = None
                if isinstance(stored_stats, dict):
                    live_net = stored_stats.get('cashflow_inprogress', {}).get('net_profit')
                    if live_net is None:
                        live_net = stored_stats.get('profitability_completed', {}).get('net_profit')
                if live_net is not None:
                    save_daily_profit(client_id, live_net, today_str, source='live')
        except Exception as snap_err:
            logging.warning(f"Live watermark snapshot failed for {client_id}: {snap_err}")

        # Get history for the requested period (14 days)
        history = get_watermark_history(client_id, days=14)

        # Low watermark among previous days only (exclude today so live value is shown separately)
        prev_history = [h for h in history if h['date'] < today_str]
        low_watermark = min(prev_history, key=lambda x: x['profit']) if prev_history else None

        # Today's live entry
        today_entry = next((h for h in history if h['date'] == today_str), None)

        return jsonify({
            "status": "success",
            "history": history,
            "low_watermark": low_watermark,
            "today": today_entry
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/login', methods=['POST'])
@limiter.limit("10 per minute")
def api_login():
    email = request.json.get('email')
    client_ip = get_remote_address()
    
    if not email: 
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    client = get_client_by_email(email)
    if client:
        log_action('CLIENT_LOGIN', 'client', email, client_ip, 'Successful login')
        return jsonify({"status": "success", "redirect": f"/dashboard/{client['client']}"})
    
    log_action('CLIENT_LOGIN_FAILED', 'client', email, client_ip, 'Email not found', False)
    return jsonify({"status": "error", "message": "Email not found"}), 404

@app.route('/api/admin_login', methods=['POST'])
@limiter.limit("5 per minute")
def api_admin_login():
    """Secure admin login with session creation."""
    password = request.json.get('password')
    client_ip = get_remote_address()
    
    if not password:
        return jsonify({"status": "error", "message": "Password required"}), 400
    
    if verify_admin_password('super_admin', password):
        session_token = create_session('admin', 'super_admin', client_ip)
        log_action('ADMIN_LOGIN', 'admin', 'super_admin', client_ip, 'Successful login')
        
        response = jsonify({"status": "success", "redirect": "/super_admin"})
        response.set_cookie('session_token', session_token, httponly=True, secure=not app.debug, samesite='Strict')
        return response

@app.route('/logout')
def logout():
    """Logout via GET request - clears session and redirects to login."""
    session_token = request.cookies.get('session_token')
    if session_token:
        delete_session(session_token)
        log_action('LOGOUT', 'user', 'session', get_remote_address())
    
    response = redirect('/')
    response.delete_cookie('session_token')
    return response

@app.route('/api/logout', methods=['POST'])
def api_logout():
    """Logout and invalidate session (API endpoint)."""
    session_token = request.cookies.get('session_token')
    if session_token:
        delete_session(session_token)
    
    response = jsonify({"status": "success"})
    response.delete_cookie('session_token')
    return response

# ============ Unified Authentication Endpoint ============

@app.route('/api/auth/check-admin', methods=['POST'])
@limiter.limit("20 per minute")
def check_admin_identifier():
    """Returns whether the given identifier requires a password (all users do)."""
    data = request.json or {}
    identifier = data.get('identifier', '').strip()
    if not identifier:
        return jsonify({"requires_password": False})
    user = find_user_by_identifier(identifier)
    if not user and '@' in identifier:
        user = get_user_by_email(identifier)
    # All recognised users require a password
    requires_password = bool(user)
    return jsonify({"requires_password": requires_password})

@app.route('/api/auth/login', methods=['POST'])
@limiter.limit("10 per minute")
def unified_login():
    """
    Unified login endpoint - auto-detects user type from email/username.
    All user types require email + password. Default password: Test@123
    """
    data = request.json
    identifier = data.get('identifier', '').strip()
    password = data.get('password', '')
    remember = data.get('remember', False)
    client_ip = get_remote_address()
    
    if not identifier:
        return jsonify({"status": "error", "message": "Email is required"}), 400
    
    # Find user by identifier (email or username)
    user = find_user_by_identifier(identifier)
    
    # If not found in DB, check hierarchy (for email-only logins)
    # This allows users defined in hierarchy.json but not yet in user_credentials to login
    if not user and '@' in identifier:
        hierarchy_user = get_user_by_email(identifier)
        if hierarchy_user:
            user = hierarchy_user
    
    if not user:
        log_action('LOGIN_FAILED', 'unknown', identifier, client_ip, 'User not found', False)
        return jsonify({"status": "error", "message": "Email not found in system"}), 403
    
    user_type = user.get('user_type')
    username = user.get('username', identifier).strip()
    
    # Check account lockout
    if is_account_locked(username, user_type):
        log_action('LOGIN_LOCKED', user_type, username, client_ip, 'Account locked', False)
        return jsonify({"status": "error", "message": "Account locked. Too many failed attempts. Try again in 15 minutes."}), 429
    
    # Handle Super Admin login - REQUIRES PASSWORD
    if user_type == 'super_admin':
        if not password:
            return jsonify({"status": "error", "message": "Password is required for Super Admin"}), 400
        
        if verify_admin_password('super_admin', password):
            session_token = create_session('super_admin', 'super_admin', client_ip)
            record_login_attempt('super_admin', 'super_admin', client_ip, True)
            log_action('LOGIN_SUCCESS', 'super_admin', 'super_admin', client_ip)
            
            max_age = 30 * 24 * 60 * 60 if remember else 86400  # 30 days or 24 hours
            response = jsonify({
                "status": "success",
                "user_type": "super_admin",
                "redirect": "/super_admin",
                "must_change_password": False
            })
            response.set_cookie('session_token', session_token, httponly=True, secure=not app.debug, samesite='Lax', max_age=max_age)
            return response
        
        record_login_attempt('super_admin', 'super_admin', client_ip, False)
        log_action('LOGIN_FAILED', 'super_admin', 'super_admin', client_ip, 'Invalid password', False)
        return jsonify({"status": "error", "message": "Invalid password"}), 403
    
    # Handle Admin/Trader/Client login - PASSWORD REQUIRED
    if not password:
        return jsonify({"status": "error", "message": "Password is required"}), 400

    # Auto-provision credentials if user exists in hierarchy but not in user_credentials DB
    if not find_user_by_identifier(username) and not find_user_by_identifier(user.get('email', '')):
        default_pw = 'Test@123'
        create_user(username, default_pw, user_type,
                    user.get('email'), user.get('parent_admin'), user.get('parent_trader'))

    # Verify password
    verified = verify_user_password(username, user_type, password)
    if not verified:
        record_login_attempt(username, user_type, client_ip, False)
        log_action('LOGIN_FAILED', user_type, username, client_ip, 'Invalid password', False)
        return jsonify({"status": "error", "message": "Invalid password"}), 403

    record_login_attempt(username, user_type, client_ip, True)
    log_action('LOGIN_SUCCESS', user_type, username, client_ip)
    
    # Determine redirect URL based on user type
    redirect_map = {
        'admin': f'/admin/{username}',
        'trader': f'/trader/{username}',
        'client': f'/dashboard/{username}'
    }
    redirect_url = redirect_map.get(user_type, '/')
    
    must_change = verified.get('must_change_password', False)
    
    max_age = 30 * 24 * 60 * 60 if remember else 86400
    session_token = create_session(user_type, username, client_ip)
    response = jsonify({
        "status": "success",
        "user_type": user_type,
        "redirect": redirect_url,
        "must_change_password": must_change
    })
    response.set_cookie('session_token', session_token, httponly=True, secure=not app.debug, samesite='Lax', max_age=max_age)
    return response

# ============ User Management Endpoints (Admin only) ============

@app.route('/api/admin/create_user', methods=['POST'])
@require_role('super_admin')
@limiter.limit("20 per hour")
def api_create_user():
    """Create a new user account."""
    data = request.json
    username = data.get('username')
    user_type = data.get('user_type')  # admin, trader, or client
    email = data.get('email')
    
    # Auto-generate password if not provided
    password = data.get('password')
    if not password:
        password = 'Test@123'
    
    parent_admin = data.get('parent_admin')
    parent_trader = data.get('parent_trader')
    
    if not username or not user_type:
        return jsonify({"status": "error", "message": "Username and user_type required"}), 400
    
    if user_type not in ['admin', 'trader', 'client']:
        return jsonify({"status": "error", "message": "Invalid user type"}), 400
    
    # Check if user already exists in DB
    user_db_exists = user_exists(username, user_type)
    
    # Check if user exists in Hierarchy
    hierarchy_exists = False
    if user_type == 'admin':
        if username in hierarchy.get('admins', {}):
            hierarchy_exists = True
    elif user_type == 'trader':
        for adm in hierarchy.get('admins', {}).values():
            if username in adm.get('traders', {}):
                hierarchy_exists = True
                break
    elif user_type == 'client':
        for adm in hierarchy.get('admins', {}).values():
            for tr in adm.get('traders', {}).values():
                clients = tr.get('clients', [])
                for cl in clients:
                    c_name = cl.get('name') if isinstance(cl, dict) else cl
                    if c_name == username:
                        hierarchy_exists = True
                        break
                if hierarchy_exists: break
            if hierarchy_exists: break

    if user_db_exists and hierarchy_exists:
        return jsonify({"status": "error", "message": f"{user_type.title()} '{username}' already exists"}), 400
    
    # Create user in database (auth) if not exists
    if not user_db_exists:
        if not create_user(username, password, user_type, email, parent_admin, parent_trader):
            return jsonify({"status": "error", "message": "Failed to create user"}), 500

    # Update Hierarchy (for display) - even if they existed in DB but not hierarchy
    try:
        if user_type == 'admin':
            if not hierarchy_exists:
                add_admin(username, email)
        elif user_type == 'trader':
            if not hierarchy_exists:
                # Map parent_user to parent_admin for simple logic if needed, 
                # but request.json usually sends 'parent_user' which we need to grab
                p_admin = data.get('parent_user') or parent_admin
                if p_admin:
                    add_trader(p_admin, username, email)
        elif user_type == 'client':
            if not hierarchy_exists:
                p_trader = data.get('parent_user') or parent_trader
                # We need to find the admin for this trader to call add_client(admin, trader, client)
                # Search hierarchy for the trader
                found_admin = None
                if hierarchy.get('admins'):
                    for adm, a_data in hierarchy['admins'].items():
                        if p_trader in a_data.get('traders', {}):
                            found_admin = adm
                            break
                if found_admin and p_trader:
                    add_client(found_admin, p_trader, username, email)
    except Exception as e:
        print(f"Hierarchy update failed: {e}")
        # Continue, as user was created in DB

    log_action('CREATE_USER', 'admin', username, get_remote_address(), f"Type: {user_type}")
    return jsonify({"status": "success", "message": f"{user_type.title()} '{username}' created successfully"})

def can_manage_user(manager_type, manager_identifier, target_username, target_user_type):
    """Check if a user can manage (reset password, deactivate) another user."""
    if manager_type == 'super_admin':
        return True  # Super admin can manage everyone
    
    if manager_type == 'admin':
        # Admin can manage traders and clients under them
        admin_data = hierarchy.get('admins', {}).get(manager_identifier, {})
        
        if target_user_type == 'trader':
            # Check if trader is under this admin
            return target_username in admin_data.get('traders', {})
        
        if target_user_type == 'client':
            # Check if client is under any of this admin's traders
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    if client.get('name') == target_username or client.get('email') == target_username:
                        return True
            return False
        
        return False  # Admin cannot manage other admins
    
    if manager_type == 'trader':
        # Trader can only manage their clients
        if target_user_type != 'client':
            return False
        
        for admin_data in hierarchy.get('admins', {}).values():
            trader_data = admin_data.get('traders', {}).get(manager_identifier, {})
            for client in trader_data.get('clients', []):
                if client.get('name') == target_username or client.get('email') == target_username:
                    return True
        return False
    
    return False

@app.route('/api/admin/list_users', methods=['GET'])
@require_admin_password
def api_list_users():
    """List all users."""
    user_type = request.args.get('type')
    users = list_users(user_type)
    return jsonify({"status": "success", "users": users})

@app.route('/api/user/reset_password', methods=['POST'])
@require_role('super_admin', 'admin', 'trader')
def api_reset_password_rbac():
    """Reset a user's password with role-based access control."""
    from dashboard.email_service import send_password_reset_with_temp
    
    session_user = request.session_user
    manager_type = session_user.get('user_type')
    manager_id = session_user.get('user_identifier')
    
    data = request.json
    username = data.get('username')
    user_type = data.get('user_type')
    email = data.get('email')
    
    if not username or not user_type:
        return jsonify({"status": "error", "message": "Username and user_type required"}), 400
    
    # Check if user has permission to reset this user's password
    if not can_manage_user(manager_type, manager_id, username, user_type):
        log_action('RESET_PASSWORD_DENIED', manager_type, manager_id, get_remote_address(), 
                   f"Attempted to reset: {username} ({user_type})", False)
        return jsonify({"status": "error", "message": "Access denied. You can only manage users under your hierarchy."}), 403
    
    temp_password = reset_user_password(username, user_type)
    if temp_password:
        log_action('RESET_PASSWORD', manager_type, username, get_remote_address(), f"By: {manager_id}")
        
        email_sent = False
        if email:
            email_sent = send_password_reset_with_temp(email, username, temp_password)
        
        return jsonify({
            "status": "success", 
            "message": f"Password reset for {username}",
            "temporary_password": temp_password,
            "email_sent": email_sent
        })
    
    return jsonify({"status": "error", "message": "User not found"}), 404

@app.route('/api/admin/reset_password', methods=['POST'])
@require_admin_password
def api_reset_password():
    """Reset a user's password (legacy - uses password header)."""
    from dashboard.email_service import send_password_reset_with_temp
    
    data = request.json
    username = data.get('username')
    user_type = data.get('user_type')
    email = data.get('email')  # Optional - for email notification
    
    if not username or not user_type:
        return jsonify({"status": "error", "message": "Username and user_type required"}), 400
    
    temp_password = reset_user_password(username, user_type)
    if temp_password:
        log_action('RESET_PASSWORD', 'admin', username, get_remote_address(), f"Type: {user_type}")
        
        # Send email notification if email provided
        email_sent = False
        if email:
            email_sent = send_password_reset_with_temp(email, username, temp_password)
        
        return jsonify({
            "status": "success", 
            "message": f"Password reset for {username}",
            "temporary_password": temp_password,
            "email_sent": email_sent
        })
    
    return jsonify({"status": "error", "message": "User not found"}), 404

@app.route('/api/admin/set_password', methods=['POST'])
@require_role('super_admin')
def api_set_password():
    """Super admin sets a specific password for any user."""
    data = request.json
    username = data.get('username')
    user_type = data.get('user_type')
    new_password = data.get('new_password')

    if not username or not user_type or not new_password:
        return jsonify({"status": "error", "message": "username, user_type and new_password required"}), 400
    if len(new_password) < 6:
        return jsonify({"status": "error", "message": "Password must be at least 6 characters"}), 400

    # Auto-provision if the user has no credentials row yet
    if not user_exists(username, user_type):
        create_user(username, new_password, user_type)
        log_action('SET_PASSWORD', 'super_admin', username, get_remote_address(), f"Created + set ({user_type})")
        return jsonify({"status": "success", "message": f"Credentials created for {username} with provided password"})

    if update_user_password(username, user_type, new_password):
        log_action('SET_PASSWORD', 'super_admin', username, get_remote_address(), f"Type: {user_type}")
        return jsonify({"status": "success", "message": f"Password set for {username}"})

    return jsonify({"status": "error", "message": "Failed to set password"}), 500

@app.route('/api/admin/deactivate_user', methods=['POST'])
@require_admin_password
def api_deactivate_user():
    """Deactivate a user account."""
    data = request.json
    username = data.get('username')
    user_type = data.get('user_type')
    
    if not username or not user_type:
        return jsonify({"status": "error", "message": "Username and user_type required"}), 400
    
    if deactivate_user(username, user_type):
        log_action('DEACTIVATE_USER', 'admin', username, get_remote_address(), f"Type: {user_type}")
        return jsonify({"status": "success", "message": f"User '{username}' deactivated"})
    
    return jsonify({"status": "error", "message": "User not found"}), 404

# ============ Change Password Endpoint ============

@app.route('/change-password')
@require_session
def change_password_page():
    """Page to change password."""
    return render_template('change_password.html')

@app.route('/api/auth/change_password', methods=['POST'])
@require_session
@limiter.limit("5 per hour")
def api_change_password():
    """Change user's own password."""
    from dashboard.email_service import send_password_changed_notification
    
    data = request.json
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    
    if not current_password or not new_password:
        return jsonify({"status": "error", "message": "Current and new password required"}), 400
    
    if len(new_password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters"}), 400
    
    session_user = request.session_user
    user_type = session_user.get('user_type')
    username = session_user.get('user_identifier')
    user_email = session_user.get('email', username)  # Use email if available
    
    # Verify current password
    if user_type == 'super_admin':
        if not verify_admin_password('super_admin', current_password):
            return jsonify({"status": "error", "message": "Current password is incorrect"}), 403
        if set_admin_password('super_admin', new_password):
            log_action('CHANGE_PASSWORD', 'super_admin', 'super_admin', get_remote_address())
            # Send email notification
            if user_email:
                send_password_changed_notification(user_email, 'Super Admin', 'self')
            return jsonify({"status": "success", "message": "Password changed successfully"})
    else:
        user_info = verify_user_password(username, user_type, current_password)
        if not user_info:
            return jsonify({"status": "error", "message": "Current password is incorrect"}), 403
        if update_user_password(username, user_type, new_password):
            log_action('CHANGE_PASSWORD', user_type, username, get_remote_address())
            # Send email notification
            if user_email and '@' in user_email:
                send_password_changed_notification(user_email, username, 'self')
            return jsonify({"status": "success", "message": "Password changed successfully"})
    
    return jsonify({"status": "error", "message": "Failed to change password"}), 500

# ============ Admin/Trader/Client Management ============

@app.route('/api/add_admin', methods=['POST'])
def api_add_admin():
    name = request.json.get('name')
    email = request.json.get('email', '')
    if not name: return jsonify({"status": "error", "message": "Name required"}), 400
    
    if add_admin(name, email):
        log_action('ADD_ADMIN', 'system', name, get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Admin exists"}), 400

@app.route('/api/delete_user', methods=['POST'])
@require_role('super_admin')
def api_delete_user():
    data = request.json
    user_type = data.get('type')
    name = data.get('name')
    admin = data.get('admin')
    trader = data.get('trader')
    
    if not user_type or not name:
        return jsonify({"status": "error", "message": "Missing arguments"}), 400
        
    result = False
    if user_type == 'admin':
        result = remove_admin(name)
        delete_user_credential(name, 'admin')
            
    elif user_type == 'trader':
        if not admin: return jsonify({"status": "error", "message": "Admin parent required"}), 400
        result = remove_trader(admin, name)
        delete_user_credential(name, 'trader')
            
    elif user_type == 'client':
        result = remove_client(admin or '', trader or '', name)
        delete_user_credential(name, 'client')
        # Always delete client data from database (even if hierarchy removal failed,
        # e.g. name mismatch between identity display name and hierarchy name)
        delete_client_data(name)
        if not result:
            # Try to find and remove from hierarchy by searching all admins/traders
            from config.hierarchy import SYSTEM_HIERARCHY, save_hierarchy
            for a_name, a_data in SYSTEM_HIERARCHY.get("admins", {}).items():
                for t_name, t_data in a_data.get("traders", {}).items():
                    for i, client in enumerate(t_data.get("clients", [])):
                        if client.get("name") == name:
                            del t_data["clients"][i]
                            save_hierarchy(SYSTEM_HIERARCHY)
                            result = True
                            break
                    if result:
                        break
                if result:
                    break
            if not result:
                # Client data was still deleted from DB, consider it a success
                result = True
    
    if result:
        log_action(f'DELETE_{user_type.upper()}', user_type, name, get_remote_address())
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "error", "message": "Delete failed (not found)"}), 400

@app.route('/api/update_admin', methods=['POST'])
def api_update_admin():
    name = request.json.get('name')
    email = request.json.get('email')
    new_name = request.json.get('new_name', '').strip()
    if not name: return jsonify({"status": "error", "message": "Name required"}), 400
    
    # Rename if new_name provided and different
    if new_name and new_name != name:
        if not rename_admin(name, new_name, email):
            return jsonify({"status": "error", "message": "Rename failed (name taken or not found)"}), 400
        rename_user_credential(name, new_name, 'admin')
        log_action('RENAME_ADMIN', 'admin', f'{name} -> {new_name}', get_remote_address())
        return jsonify({"status": "success"})
    
    if update_admin_details(name, email):
        update_user_email(name, 'admin', email)
        log_action('UPDATE_ADMIN', 'admin', name, get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Admin not found"}), 400

@app.route('/api/update_trader', methods=['POST'])
def api_update_trader():
    admin = request.json.get('admin')
    name = request.json.get('name')
    email = request.json.get('email')
    new_name = request.json.get('new_name', '').strip()
    if not admin or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    # Rename if new_name provided and different
    if new_name and new_name != name:
        if not rename_trader(admin, name, new_name, email):
            return jsonify({"status": "error", "message": "Rename failed (name taken or not found)"}), 400
        rename_user_credential(name, new_name, 'trader')
        log_action('RENAME_TRADER', 'trader', f'{name} -> {new_name}', get_remote_address(), f"Admin: {admin}")
        return jsonify({"status": "success"})
    
    if update_trader_details(admin, name, email):
        update_user_email(name, 'trader', email)
        log_action('UPDATE_TRADER', 'admin', name, get_remote_address(), f"Admin: {admin}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Trader not found"}), 400

@app.route('/api/update_client', methods=['POST'])
def api_update_client():
    admin = request.json.get('admin')
    trader = request.json.get('trader')
    name = request.json.get('name')
    email = request.json.get('email', '')
    category = request.json.get('category', '')
    new_name = request.json.get('new_name', '').strip()
    
    if not admin or not trader or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    # Rename if new_name provided and different
    if new_name and new_name != name:
        if not rename_client(admin, trader, name, new_name, email, category or None):
            return jsonify({"status": "error", "message": "Rename failed (not found)"}), 400
        rename_client_in_db(name, new_name)
        rename_user_credential(name, new_name, 'client')
        log_action('RENAME_CLIENT', 'client', f'{name} -> {new_name}', get_remote_address(), f"Trader: {trader}")
        return jsonify({"status": "success"})
    
    if category:
        update_client_category(admin, trader, name, category)
        
    if update_client_details(admin, trader, name, email):
        update_user_email(name, 'client', email)
        log_action('UPDATE_CLIENT', 'trader', name, get_remote_address(), f"Trader: {trader}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Client not found"}), 400

@app.route('/api/add_trader', methods=['POST'])
def api_add_trader():
    admin = request.json.get('admin')
    name = request.json.get('name')
    email = request.json.get('email', '')
    if not admin or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    if add_trader(admin, name, email):
        # Also ensure record exists in database
        try:
            # We don't have a "trader" table in database, user_credentials holds trader logins.
            if not user_exists(name, 'trader'):
                 temp_pass = "trader123" 
                 create_user(name, temp_pass, 'trader', email)
        except Exception as e:
            print(f"Error creating trader DB user: {e}")

        log_action('ADD_TRADER', 'admin', name, get_remote_address(), f"Admin: {admin}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Invalid request or Trader exists"}), 400

@app.route('/api/add_client', methods=['POST'])
def api_add_client():
    admin = request.json.get('admin')
    trader = request.json.get('trader')
    name = request.json.get('name')
    email = request.json.get('email', '')
    category = request.json.get('category', '')
    
    if not admin or not trader or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    if add_client(admin, trader, name, email, category):
        # IMPORTANT: Initialize database record for new client
        try:
            if not get_client_data(name): 
                initial_data = {
                    "identity": {
                        "name": name,
                        "email": email,
                        "category": category,
                        "profile": category,
                        "source": category or "Private",
                        "admin": admin,
                        "trader": trader,
                        "client": name
                    }
                }
                save_client_data(name, initial_data)
                
            # Create user credential for client portal access
            if email and not user_exists(name, 'client') and not find_user_by_identifier(email):
                 temp_pass = "client123"
                 create_user(name, temp_pass, 'client', email)
                 
        except Exception as e:
             print(f"Error creating client DB record: {e}")
             
        log_action('ADD_CLIENT', 'trader', name, get_remote_address(), f"Trader: {trader}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Invalid request or Client exists"}), 400

@app.route('/api/move_user', methods=['POST'])
def api_move_user():
    data = request.json
    user_type = data.get('type')
    name = data.get('name')
    
    if user_type == 'trader':
        old_admin = data.get('old_admin')
        new_admin = data.get('new_admin')
        if not all([name, old_admin, new_admin]): 
            return jsonify({"status": "error", "message": "Missing fields"}), 400
            
        if move_trader(name, old_admin, new_admin):
            try:
                # Update DB using raw SQL since no helper exposes raw update
                # We need to manually get a connection from the pool/manager
                # get_connection is imported from dashboard.database
                with get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("UPDATE user_credentials SET parent_admin = ? WHERE username = ? AND user_type = 'trader'", (new_admin, name))
                    # Also update all clients of this trader to point to new admin
                    cursor.execute("UPDATE user_credentials SET parent_admin = ? WHERE parent_trader = ? AND user_type = 'client'", (new_admin, name))
                    conn.commit()
            except Exception as e:
                print(f"DB update failed: {e}")
                
            log_action('MOVE_TRADER', 'super_admin', name, get_remote_address(), f"{old_admin} -> {new_admin}")
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error", "message": "Move failed (invalid target or user not found)"}), 400
            
    elif user_type == 'client':
        old_trader = data.get('old_trader')
        old_admin = data.get('old_admin')
        new_trader = data.get('new_trader') # The target trader
        new_admin = data.get('new_admin')   # The admin of the target trader (required for consistency)
        
        if not all([name, old_trader, old_admin, new_trader, new_admin]): 
             return jsonify({"status": "error", "message": "Missing fields"}), 400
             
        # Signature: move_client(client_name, old_admin, old_trader, new_admin, new_trader)
        if move_client(name, old_admin, old_trader, new_admin, new_trader):
            try:
                with get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE user_credentials SET parent_trader = ?, parent_admin = ? WHERE username = ? AND user_type = 'client'", 
                        (new_trader, new_admin, name)
                    )
                    conn.commit()
            except Exception as e:
                print(f"DB update failed: {e}")
                
            log_action('MOVE_CLIENT', 'super_admin', name, get_remote_address(), f"{old_trader} -> {new_trader}")
            return jsonify({"status": "success"})
        else:
             return jsonify({"status": "error", "message": "Move failed (duplicate name?)"}), 400

    return jsonify({"status": "error", "message": "Invalid type"}), 400

@app.route('/api/update_client_profile', methods=['POST'])
@require_session
def api_update_client_profile():
    session_user = request.session_user
    if session_user.get('user_type') not in ['admin', 'super_admin']:
         return jsonify({"status": "error", "message": "Access denied"}), 403

    data = request.json
    admin = data.get('admin')
    trader = data.get('trader')
    name = data.get('name')
    category = data.get('category')
    
    if not admin or not trader or not name or category is None:
         return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    from config.hierarchy import update_client_category
    
    if update_client_category(admin, trader, name, category):
        # Determine client_id (assuming it's the name)
        client_id = name
        
        # Also update the dashboard.db logic
        try:
             client_data = get_client_data(client_id)
             if client_data:
                 identity = client_data.get('identity', {})
                 # Update both for compatibility
                 identity['profile'] = category 
                 identity['category'] = category
                 update_client_field(client_id, 'identity', identity)
        except Exception as e:
             print(f"Error updating DB identity profile: {e}")

        log_action('UPDATE_CLIENT_PROFILE', session_user.get('user_type'), name, get_remote_address(), f"To: {category}")
        return jsonify({"status": "success"})
    
    return jsonify({"status": "error", "message": "Client not found"}), 404

@app.route('/api/remove_admin', methods=['POST'])
def api_remove_admin():
    name = request.json.get('name')
    if not name: return jsonify({"status": "error", "message": "Name required"}), 400
    
    if remove_admin(name):
        log_action('REMOVE_ADMIN', 'system', name, get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Admin not found"}), 400

@app.route('/api/remove_trader', methods=['POST'])
def api_remove_trader():
    admin = request.json.get('admin')
    name = request.json.get('name')
    if not admin or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    if remove_trader(admin, name):
        log_action('REMOVE_TRADER', 'admin', name, get_remote_address(), f"Admin: {admin}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Trader not found"}), 400

@app.route('/api/remove_client', methods=['POST'])
def api_remove_client():
    admin = request.json.get('admin')
    trader = request.json.get('trader')
    name = request.json.get('name')
    if not admin or not trader or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    # Save a final snapshot before deletion so data can be recovered
    client_data = get_client_data(name)
    if client_data:
        from dashboard.database import save_data_snapshot
        save_data_snapshot(
            name, client_data,
            action='CLIENT_DELETED',
            changed_by='system',
            changed_by_type='admin',
            ip_address=get_remote_address(),
            change_source='client_removal',
            change_description=f"Final snapshot before client removal (Trader: {trader}, Admin: {admin})"
        )
    
    if remove_client(admin, trader, name):
        log_action('REMOVE_CLIENT', 'trader', name, get_remote_address(), f"Trader: {trader}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Client not found"}), 400

@app.route('/api/client/delete_evaluation', methods=['POST'])
@limiter.limit("30 per minute")
def api_delete_evaluation():
    """
    Delete an evaluation row with history tracking.
    The data is removed from current view but can be recovered from version history.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    evaluation_index = data.get('index')
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    if evaluation_index is None:
        return jsonify({"status": "error", "message": "Evaluation index required"}), 400
    
    # Look up client by email
    from config.hierarchy import get_client_by_email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered"}), 404
    
    client_id = client_info['client']
    
    # Get current client data
    client_data = get_client_data(client_id)
    if not client_data:
        return jsonify({"status": "error", "message": "Client data not found"}), 404
    
    evaluations = client_data.get('evaluations', [])
    
    if evaluation_index < 0 or evaluation_index >= len(evaluations):
        return jsonify({"status": "error", "message": "Invalid evaluation index"}), 400
    
    # Get details of what we're deleting for the log
    deleted_eval = evaluations[evaluation_index]
    deleted_info = f"Row {evaluation_index + 1}: {deleted_eval.get('Prop Firm', 'Unknown')} - {deleted_eval.get('Account Size', 'Unknown')}"
    
    # Remove the evaluation
    evaluations.pop(evaluation_index)
    client_data['evaluations'] = evaluations
    
    # Recalculate statistics with existing MT5 + historical accounts
    from utils.data_processor import calculate_statistics
    existing_mt5 = client_data.get('account') or None
    existing_hist = client_data.get('statistics', {}).get('hedging_review', {}).get('historical_accounts')
    new_stats = calculate_statistics(evaluations, None, existing_mt5 if existing_mt5 else None,
                                     historical_accounts=existing_hist)
    # Preserve historical accounts
    if existing_hist:
        old_hr = client_data.get('statistics', {}).get('hedging_review', {})
        new_stats.setdefault('hedging_review', {})['historical_accounts'] = existing_hist
        new_stats['hedging_review']['historical_deposits'] = old_hr.get('historical_deposits', 0)
        new_stats['hedging_review']['historical_withdrawals'] = old_hr.get('historical_withdrawals', 0)
        new_stats['hedging_review']['historical_balance'] = old_hr.get('historical_balance', 0)
    client_data['statistics'] = new_stats
    
    # Save with history tracking - the previous version contains the deleted row
    success, version = save_client_data_with_history(
        client_id,
        client_data,
        action='DELETE_EVALUATION',
        changed_by=email,
        changed_by_type='client',
        ip_address=get_remote_address(),
        change_source='dashboard_delete',
        change_description=f"Deleted evaluation: {deleted_info}"
    )
    
    log_action('DELETE_EVALUATION', 'client', email, get_remote_address(), 
               f"Deleted {deleted_info} from {client_id} (v{version})")
    
    return jsonify({
        "status": "success",
        "message": f"Evaluation deleted. Use Version History to recover if needed.",
        "version": version,
        "deleted": deleted_info
    })

@app.route('/api/move_client', methods=['POST'])
def api_move_client():
    data = request.json
    if move_client(data['client_name'], data['old_admin'], data['old_trader'], data['new_admin'], data['new_trader']):
        log_action('MOVE_CLIENT', 'admin', data['client_name'], get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Move failed"}), 400

@app.route('/api/move_trader', methods=['POST'])
def api_move_trader():
    data = request.json
    if move_trader(data['trader_name'], data['old_admin'], data['new_admin']):
        log_action('MOVE_TRADER', 'admin', data['trader_name'], get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Move failed"}), 400

@app.route('/super_admin/clients')
@require_session
def client_management():
    if request.session_user.get('user_type') != 'super_admin':
        return redirect('/')
    return render_template('client_management.html')

# ============ Data API with Role-Based Access Control ============

def can_access_client(user_type, user_identifier, target_client):
    """Check if user has permission to access a client's data."""
    if user_type == 'super_admin':
        return True
    
    if user_type == 'client':
        # Client can only access their own data
        return user_identifier == target_client
    
    # For admins and traders, check hierarchy
    for admin_name, admin_data in hierarchy.get('admins', {}).items():
        for trader_name, trader_data in admin_data.get('traders', {}).items():
            for client in trader_data.get('clients', []):
                client_name = client.get('name', '')
                client_email = client.get('email', '')
                
                if client_name == target_client or client_email == target_client:
                    if user_type == 'admin' and user_identifier == admin_name:
                        return True
                    if user_type == 'trader' and user_identifier == trader_name:
                        return True
    
    return False

def get_accessible_clients(user_type, user_identifier):
    """Get list of client names this user can access."""
    clients = []
    
    if user_type == 'super_admin':
        # Super admin can access all clients
        for admin_data in hierarchy.get('admins', {}).values():
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    clients.append(client.get('name'))
        return clients
    
    if user_type == 'admin':
        # Admin can access all clients under their traders
        admin_data = hierarchy.get('admins', {}).get(user_identifier, {})
        for trader_data in admin_data.get('traders', {}).values():
            for client in trader_data.get('clients', []):
                clients.append(client.get('name'))
        return clients
    
    if user_type == 'trader':
        # Trader can access only their clients
        for admin_data in hierarchy.get('admins', {}).values():
            trader_data = admin_data.get('traders', {}).get(user_identifier, {})
            for client in trader_data.get('clients', []):
                clients.append(client.get('name'))
        return clients
    
    if user_type == 'client':
        # Client can only access themselves
        return [user_identifier]
    
    return []

@app.route('/api/hedging_review/<client_id>', methods=['POST'])
@require_session
def update_hedging_review(client_id):
    """Update hedging review values manually - only for traders, admins, and super_admins."""
    session_user = request.session_user
    user_type = session_user.get('user_type')
    user_identifier = session_user.get('user_identifier')
    
    # Only allow traders, admins, and super_admins to edit
    if user_type not in ['trader', 'admin', 'super_admin']:
        log_action('HEDGING_EDIT_DENIED', user_type, user_identifier, get_remote_address(), 
                   f"Client tried to edit hedging for: {client_id}", False)
        return jsonify({"status": "error", "message": "Only traders, admins, and super admins can edit hedging review"}), 403
    
    # Check if user can access this client
    if not can_access_client(user_type, user_identifier, client_id):
        log_action('HEDGING_EDIT_DENIED', user_type, user_identifier, get_remote_address(), 
                   f"No access to client: {client_id}", False)
        return jsonify({"status": "error", "message": "Access denied to this client"}), 403
    
    data = request.json
    
    # Get existing client data
    client_data = get_client_data(client_id)
    if not client_data:
        return jsonify({"status": "error", "message": "Client data not found"}), 404
    
    # Update hedging review in statistics
    if 'statistics' not in client_data:
        client_data['statistics'] = {}
    if 'hedging_review' not in client_data['statistics']:
        client_data['statistics']['hedging_review'] = {}
    
    hr = client_data['statistics']['hedging_review']
    hr['total_deposits'] = float(data.get('total_deposits', hr.get('total_deposits', 0)))
    hr['total_withdrawals'] = float(data.get('total_withdrawals', hr.get('total_withdrawals', 0)))
    hr['current_balance'] = float(data.get('current_balance', hr.get('current_balance', 0)))
    hr['actual_hedging_results'] = float(data.get('actual_hedging_results', hr.get('actual_hedging_results', 0)))
    hr['discrepancy'] = float(data.get('discrepancy', hr.get('discrepancy', 0)))
    
    # Also store in account for consistency with MT5 push
    if 'account' not in client_data:
        client_data['account'] = {}
    client_data['account']['balance'] = hr['current_balance']
    client_data['account']['total_deposits'] = hr['total_deposits']
    client_data['account']['total_withdrawals'] = hr['total_withdrawals']
    
    # Save updated data
    save_client_data(client_id, client_data)
    
    log_action('HEDGING_EDIT', user_type, user_identifier, get_remote_address(), 
               f"Updated hedging review for {client_id}: deposits={hr['total_deposits']}, withdrawals={hr['total_withdrawals']}, balance={hr['current_balance']}")
    
    return jsonify({
        "status": "success", 
        "message": "Hedging review updated",
        "hedging_review": hr
    })

@app.route('/api/historical_mt5/<client_id>', methods=['POST'])
@require_session
def manage_historical_mt5(client_id):
    """Manage historical MT5 accounts - add/delete. Only for traders, admins, and super_admins."""
    session_user = request.session_user
    user_type = session_user.get('user_type')
    user_identifier = session_user.get('user_identifier')
    
    # Only allow traders, admins, and super_admins to edit
    if user_type not in ['trader', 'admin', 'super_admin']:
        log_action('HISTORICAL_MT5_DENIED', user_type, user_identifier, get_remote_address(), 
                   f"Client tried to edit historical MT5 for: {client_id}", False)
        return jsonify({"status": "error", "message": "Only traders, admins, and super admins can manage historical MT5 accounts"}), 403
    
    # Check if user can access this client
    if not can_access_client(user_type, user_identifier, client_id):
        log_action('HISTORICAL_MT5_DENIED', user_type, user_identifier, get_remote_address(), 
                   f"No access to client: {client_id}", False)
        return jsonify({"status": "error", "message": "Access denied to this client"}), 403
    
    data = request.json
    action = data.get('action')  # 'add' or 'delete'
    
    # Get existing client data
    client_data = get_client_data(client_id)
    if not client_data:
        return jsonify({"status": "error", "message": "Client data not found"}), 404
    
    # Save snapshot BEFORE making changes (for recovery)
    from dashboard.database import save_data_snapshot
    save_data_snapshot(
        client_id, client_data,
        action='BEFORE_HISTORICAL_MT5_' + action.upper(),
        changed_by=user_identifier,
        changed_by_type=user_type,
        ip_address=get_remote_address(),
        change_source='historical_mt5_management',
        change_description=f"Snapshot before {action} historical MT5 account"
    )
    
    # Ensure hedging_review structure exists
    if 'statistics' not in client_data:
        client_data['statistics'] = {}
    if 'hedging_review' not in client_data['statistics']:
        client_data['statistics']['hedging_review'] = {}
    
    hr = client_data['statistics']['hedging_review']
    
    # Initialize historical_accounts array if not exists
    if 'historical_accounts' not in hr:
        hr['historical_accounts'] = []
    
    if action == 'add':
        account = data.get('account', {})
        hr['historical_accounts'].append({
            'name': account.get('name', 'MT5 Account'),
            'deposits': float(account.get('deposits', 0)),
            'withdrawals': float(account.get('withdrawals', 0)),
            'final_balance': float(account.get('final_balance', 0)),
            'date_added': account.get('date_added', '')
        })
        
        log_action('HISTORICAL_MT5_ADD', user_type, user_identifier, get_remote_address(), 
                   f"Added historical MT5 for {client_id}: {account.get('name')}")
        
    elif action == 'delete':
        index = data.get('index')
        if index is not None and 0 <= index < len(hr['historical_accounts']):
            deleted = hr['historical_accounts'].pop(index)
            log_action('HISTORICAL_MT5_DELETE', user_type, user_identifier, get_remote_address(), 
                       f"Deleted historical MT5 for {client_id}: {deleted.get('name')}")
        else:
            return jsonify({"status": "error", "message": "Invalid index"}), 400
    else:
        return jsonify({"status": "error", "message": "Invalid action"}), 400
    
    # Recalculate totals including historical accounts
    hist_deposits = sum(acc.get('deposits', 0) for acc in hr['historical_accounts'])
    hist_withdrawals = sum(acc.get('withdrawals', 0) for acc in hr['historical_accounts'])
    hist_balance = sum(acc.get('final_balance', 0) for acc in hr['historical_accounts'])
    
    # Store historical totals for data_processor to use
    hr['historical_deposits'] = hist_deposits
    hr['historical_withdrawals'] = hist_withdrawals
    hr['historical_balance'] = hist_balance
    
    # Save updated data WITH history tracking
    email = client_data.get('identity', {}).get('email', '')
    success, version = save_client_data_with_history(
        client_id, client_data,
        action='HISTORICAL_MT5_' + action.upper(),
        changed_by=user_identifier,
        changed_by_type=user_type,
        ip_address=get_remote_address(),
        change_source='historical_mt5_management',
        change_description=f"{action.capitalize()} historical MT5 account"
    )
    
    return jsonify({
        "status": "success", 
        "message": f"Historical MT5 {action}ed successfully",
        "historical_accounts": hr['historical_accounts'],
        "historical_totals": {
            "deposits": hist_deposits,
            "withdrawals": hist_withdrawals,
            "balance": hist_balance
        }
    })

@app.route('/api/data')
def get_data():
    """Get client data - requires authentication and role-based access."""
    client_id = request.args.get('client_id')
    
    # Check authentication
    session_token = request.cookies.get('session_token')
    if not session_token:
        # Also check API Key for trader apps
        api_key = request.headers.get('X-API-Key')
        if not api_key:
             return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        # Validate API Key
        key_info = validate_api_key(api_key)
        if not key_info:
             return jsonify({"status": "error", "message": "Invalid API Key"}), 401
        
        user_type = 'api'
        user_identifier = key_info.get('owner') 
    else:
        session_info = validate_session(session_token)
        if not session_info:
            return jsonify({"status": "error", "message": "Invalid session"}), 401
    
        user_type = session_info.get('user_type')
        user_identifier = session_info.get('user_identifier')
    
    if client_id:
        # Check if user can access this client's data
        if not can_access_client(user_type, user_identifier, client_id):
            log_action('ACCESS_DENIED', user_type, user_identifier, get_remote_address(), f"Tried to access: {client_id}", False)
            return jsonify({"status": "error", "message": "Access denied"}), 403
        
        data = get_client_data(client_id)
        if data is None:
            return jsonify({"status": "error", "message": f"No data found for client '{client_id}'. The client may not exist or has no saved data yet."}), 404

        if data:
            # Inject Visual Notes
            if 'evaluations' in data:
                try:
                    notes = get_client_notes(client_id)
                    # notes is { row_index: { col: text } }
                    for i, ev in enumerate(data['evaluations']):
                        if i in notes:
                            ev['_notes'] = notes[i]
                except Exception as e:
                    logging.error(f"Error injecting notes: {e}")

            # Historical MT5 values are shown separately in the MT5 Accounts Overview table.
            # The hedging_review values (deposits, withdrawals, balance, discrepancy) are
            # served as-is from data_processor.py — single source of truth.
            
            data['status'] = 'success'
            # Include current version so frontend can detect stale refreshes
            try:
                from dashboard.database import get_next_version
                data['_version'] = get_next_version(client_id) - 1
            except Exception:
                pass
            return jsonify(data)
    
    # If no client specified, return empty
    return jsonify({
        "status": "success",
        "deals": [], "positions": [], "account": {}, 
        "evaluations": [], "statistics": {}, "dropdown_options": {}, 
        "last_updated": "Never"
    })

@app.route('/api/notes', methods=['POST'])
@require_session
def update_note():
    """Update or Delete a cell note."""
    try:
        session_user = request.session_user
        user_type = session_user.get('user_type')
        user_identifier = session_user.get('user_identifier')
        
        data = request.json
        client_id = data.get('client_id')
        row_index = data.get('row_index')
        column_key = data.get('column_key')
        content = data.get('content')

        # Clients have full notes access
        
        if not client_id or row_index is None or not column_key:
            return jsonify({"status": "error", "message": "Missing required fields"}), 400

        # Ensure user has access
        if not can_access_client(user_type, user_identifier, client_id):
            log_action('ACCESS_DENIED', user_type, user_identifier, get_remote_address(), f"Note access denied: {client_id}", False)
            return jsonify({"status": "error", "message": "Access denied"}), 403

        if content:
            save_client_note(client_id, row_index, column_key, content, user_identifier)
            action = 'UPDATE_NOTE'
        else:
            # Empty content means delete
            delete_client_note(client_id, row_index, column_key)
            action = 'DELETE_NOTE'
            
        log_action(action, user_type, user_identifier, get_remote_address(), f"Note on {client_id} row {row_index} col {column_key}", True)
        return jsonify({"status": "success"})
    except Exception as e:
        logging.error(f"Error updating note: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/notes/delete', methods=['POST'])
@require_session
def delete_note():
    data = request.json
    client_id = data.get('client_id')
    row_index = data.get('row_index')
    column_key = data.get('column_key')
    
    session_user = request.session_user
        
    if delete_client_note(client_id, row_index, column_key):
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Database error"}), 500

@app.route('/api/update_data', methods=['POST'])
@limiter.limit("60 per minute")
def update_data():
    """Update client data - supports both session and API key authentication."""
    try:
        data = request.json
        identity = data.get('identity', {})
        
        # Try session authentication first (for dashboard UI)
        session_token = request.cookies.get('session_token')
        api_key = request.headers.get('X-API-Key')
        
        if session_token:
            session_info = validate_session(session_token)
            if session_info:
                user_type = session_info.get('user_type')
                user_identifier = session_info.get('user_identifier')
                
                # Get client_id from request data
                client_id = identity.get('client') or data.get('client_id')
                
                if not client_id:
                    return jsonify({"status": "error", "message": "Client ID required"}), 400
                
                # Check if user can access this client's data
                if not can_access_client(user_type, user_identifier, client_id):
                    log_action('UPDATE_DENIED', user_type, user_identifier, get_remote_address(), 
                              f"Tried to update: {client_id}", False)
                    return jsonify({"status": "error", "message": "Access denied"}), 403
                
                # Get existing data to preserve fields not being updated
                existing_data = get_client_data(client_id) or {}
                
                # Get evaluations and normalize Account Size values
                evaluations = data.get("evaluations", existing_data.get("evaluations", []))
                evaluations = normalize_evaluations(evaluations)
                
                # Deep-merge evaluations: preserve push-sourced fields (Hedge Results, deals, etc.)
                # that the stale frontend may not have received yet.
                existing_evals = existing_data.get("evaluations", [])
                PUSH_SOURCED_KEYS = {
                    'Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
                    'Hedge Result 4', 'Hedge Result 5',
                    'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
                    'Hedge Result 4.1', 'Hedge Result 5.1',
                    'Hedge Result 6', 'Hedge Result 7',
                    'Hedge Net', 'Hedge Net.1',
                }

                # Fields the user explicitly touched in this edit session
                # (sent by frontend so we can distinguish intentional clears from stale data)
                raw_changed = data.get('_changedFields', {})
                user_changed = {}  # { int(eval_index): set(field_names) }
                for idx_str, fields in raw_changed.items():
                    try:
                        user_changed[int(idx_str)] = set(fields) if isinstance(fields, list) else set()
                    except (ValueError, TypeError):
                        pass

                for i, ev in enumerate(evaluations):
                    explicitly_changed = user_changed.get(i, set())

                    if i < len(existing_evals):
                        existing_ev = existing_evals[i]
                        
                        # Preserve DB-only internal keys the frontend doesn't send
                        for k, v in existing_ev.items():
                            if k.startswith('_') and k not in ev:
                                ev[k] = v
                        
                        for key in PUSH_SOURCED_KEYS:
                            # If the user explicitly cleared this field, respect the clear
                            if key in explicitly_changed:
                                continue
                            existing_val = existing_ev.get(key)
                            incoming_val = ev.get(key)
                            # Keep the existing (push-sourced) value when the frontend sends empty/missing
                            if existing_val and (not incoming_val or str(incoming_val).strip() == ''):
                                ev[key] = existing_val


                
                # Merge the update data with existing data
                merged_statistics = data.get("statistics", existing_data.get("statistics", {}))
                
                # Always preserve hedging_review from DB — it is only authoritative
                # when set by /api/client/push or /api/hedging_review, never from
                # stale frontend copies sent during evaluation edits.
                existing_hr = existing_data.get('statistics', {}).get('hedging_review')
                if existing_hr:
                    merged_statistics['hedging_review'] = existing_hr

                client_data = {
                    "deals": data.get("deals", existing_data.get("deals", [])),
                    "positions": data.get("positions", existing_data.get("positions", [])),
                    "account": data.get("account", existing_data.get("account", {})),
                    "hedge_accounts": data.get("hedge_accounts", existing_data.get("hedge_accounts", [])),
                    "prop_accounts": data.get("prop_accounts", existing_data.get("prop_accounts", [])),
                    "vps_accounts": data.get("vps_accounts", existing_data.get("vps_accounts", [])),
                    "payment_info": data.get("payment_info", existing_data.get("payment_info", [])),
                    "payment_address": data.get("payment_address", existing_data.get("payment_address", {})),
                    "evaluations": evaluations,
                    "statistics": merged_statistics,
                    "dropdown_options": data.get("dropdown_options", existing_data.get("dropdown_options", {})),
                    # Persist match log when updating from dashboard
                    "aggregated_by_comment": existing_data.get("aggregated_by_comment", []),
                    "comment_summary": existing_data.get("comment_summary", {}),
                    "identity": data.get("identity", existing_data.get("identity", {}))
                }
                
                # Ensure client ID is in identity
                if 'client' not in client_data['identity']:
                    client_data['identity']['client'] = client_id
                
                # Allow custom action/description from frontend
                action_type = data.get('action_type', 'UPDATE')
                description = data.get('change_description', f'Manual edit from dashboard by {user_type}')

                # Clients are view+edit only — block add/delete of evaluations
                if user_type == 'client' and action_type in ('CREATE', 'DELETE'):
                    return jsonify({"status": "error", "message": "Clients cannot add or delete evaluations"}), 403

                # Save with history tracking
                success, version = save_client_data_with_history(
                    client_id,
                    client_data,
                    action=action_type,
                    changed_by=user_identifier,
                    changed_by_type=user_type,
                    ip_address=get_remote_address(),
                    change_source='dashboard_edit',
                    change_description=description
                )
                
                if success:
                    log_action('DATA_UPDATE', user_type, user_identifier, get_remote_address(), 
                              f"Client: {client_id} (v{version})")
                    return jsonify({"status": "success", "message": "Data updated", "version": version})
                else:
                    return jsonify({"status": "error", "message": "Failed to save data"}), 500
        
        # Fall back to API key authentication
        if api_key:
            user_info = validate_api_key(api_key)
            if user_info:
                return update_data_with_api_key(data, identity, user_info)
            else:
                return jsonify({"status": "error", "message": "Invalid API key"}), 403
        
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    except Exception as e:
        print(f"Error in update_data: {e}")
        return jsonify({"status": "error", "message": f"Server error: {str(e)}"}), 500


def update_data_with_api_key(data, identity, user_info):
    """Handle update with API key authentication (for external API calls)."""
    # Use authenticated user info if no identity provided
    if not identity:
        identity = {
            'admin': user_info.get('admin'),
            'trader': user_info.get('trader'),
            'client': user_info.get('client')
        }
    
    admin_id = identity.get('admin', 'Admin1')
    trader_id = identity.get('trader', 'Trader1')
    client_id = identity.get('client', 'Client1')
    email = identity.get('email', '')
    
    # Get existing data to prevent overwriting evaluations with empty list
    existing_data = get_client_data(client_id) or {}
    
    # Smart merge for evaluations:
    # Only overwrite if incoming evaluations list is NOT empty
    incoming_evals = data.get("evaluations")
    if incoming_evals and len(incoming_evals) > 0:
        evaluations = incoming_evals
    else:
        # If incoming is empty or missing, preserve existing
        evaluations = existing_data.get("evaluations", [])
        
    evaluations = normalize_evaluations(evaluations)
    
    # Smart merge for statistics (preserve hedging_review if present in existing)
    incoming_stats = data.get("statistics", {})
    existing_stats = existing_data.get("statistics", {})
    
    # Start with existing stats, update with incoming
    # This preserves keys like 'hedging_review' that the trader app doesn't send
    statistics = existing_stats.copy()
    statistics.update(incoming_stats)
    
    # Always preserve hedging_review from DB — only /api/client/push and
    # /api/hedging_review are authoritative sources for this data.
    existing_hr = existing_stats.get('hedging_review')
    if existing_hr:
        statistics['hedging_review'] = existing_hr
    
    # Smart merge for dropdown_options (preserve if incoming is empty)
    incoming_options = data.get("dropdown_options", {})
    if not incoming_options:
        dropdown_options = existing_data.get("dropdown_options", {})
    else:
        dropdown_options = incoming_options

    # Prepare client data
    client_data = {
        "deals": data.get("deals", []),
        "positions": data.get("positions", []),
        "account": data.get("account", {}),
        "evaluations": evaluations,
        "statistics": statistics,
        "dropdown_options": dropdown_options,
        "aggregated_by_comment": existing_data.get("aggregated_by_comment", []),
        "comment_summary": existing_data.get("comment_summary", {}),
        "identity": identity
    }
    
    # Save to database WITH history tracking
    success, version = save_client_data_with_history(
        client_id,
        client_data,
        action='UPDATE',
        changed_by=email or trader_id,
        changed_by_type='api',
        ip_address=get_remote_address(),
        change_source='api_push',
        change_description='Update via API'
    )
    
    # Update Hierarchy
    add_admin(admin_id)
    add_trader(admin_id, trader_id)
    add_client(admin_id, trader_id, client_id)
    
    log_action('DATA_UPDATE', 'trader', trader_id, get_remote_address(), f"Client: {client_id} (v{version})")
    return jsonify({"status": "success", "message": "Data updated", "version": version})

# ============ API Key Management (Admin only) ============

@app.route('/api/admin/generate_key', methods=['POST'])
@require_admin_password
@limiter.limit("10 per hour")
def api_generate_key():
    """Generate a new API key for a trader."""
    trader_info = request.json.get('trader_info', {})
    admin = trader_info.get('admin')
    trader = trader_info.get('trader')
    client = trader_info.get('client', '')
    
    if not admin or not trader:
        return jsonify({"status": "error", "message": "Admin and trader required"}), 400
    
    # Generate hashed API key
    api_key = generate_api_key(admin, trader, client)
    
    if api_key:
        log_action('GENERATE_API_KEY', 'admin', trader, get_remote_address())
        return jsonify({
            "status": "success",
            "api_key": api_key,  # Only time the full key is visible
            "trader_info": {"admin": admin, "trader": trader, "client": client}
        })
    
    return jsonify({"status": "error", "message": "Failed to generate key"}), 500

@app.route('/api/admin/list_keys', methods=['GET'])
@require_admin_password
def api_list_keys():
    """List all API keys (showing only prefix)."""
    keys = list_api_keys()
    log_action('LIST_API_KEYS', 'admin', 'super_admin', get_remote_address())
    return jsonify({"status": "success", "keys": keys})

@app.route('/api/admin/revoke_key', methods=['POST'])
@require_admin_password
def api_revoke_key():
    """Revoke an API key."""
    key_prefix = request.json.get('key_prefix')
    
    if not key_prefix:
        return jsonify({"status": "error", "message": "Key prefix required"}), 400
    
    if revoke_api_key(key_prefix):
        log_action('REVOKE_API_KEY', 'admin', key_prefix, get_remote_address())
        return jsonify({"status": "success", "message": "API key revoked"})
    
    return jsonify({"status": "error", "message": "API key not found"}), 404

# ============ Audit Log (Admin only) ============

@app.route('/api/admin/audit_log', methods=['GET'])
@require_admin_password
def api_audit_log():
    """Get audit log entries."""
    limit = request.args.get('limit', 100, type=int)
    action_filter = request.args.get('action', None)
    
    logs = get_audit_log(limit, action_filter)
    return jsonify({"status": "success", "logs": logs})

# ============ Trader Push Endpoints ============

@app.route('/api/trader/push_account', methods=['POST'])
@require_api_key
@limiter.limit("30 per minute")
def push_account_data():
    """Endpoint for traders to push account information."""
    data = request.json
    client_id = data.get('client_id') or request.api_user.get('client', 'Client1')
    
    update_client_field(client_id, 'account', data.get('account', {}))
    log_action('PUSH_ACCOUNT', 'trader', request.api_user.get('trader'), get_remote_address(), f"Client: {client_id}")
    
    return jsonify({"status": "success", "message": "Account data updated"})

@app.route('/api/trader/push_positions', methods=['POST'])
@require_api_key
@limiter.limit("30 per minute")
def push_positions():
    """Endpoint for traders to push current positions."""
    data = request.json
    client_id = data.get('client_id') or request.api_user.get('client', 'Client1')
    
    update_client_field(client_id, 'positions', data.get('positions', []))
    log_action('PUSH_POSITIONS', 'trader', request.api_user.get('trader'), get_remote_address(), f"Client: {client_id}")
    
    return jsonify({"status": "success", "message": "Positions updated"})

@app.route('/api/trader/push_deals', methods=['POST'])
@require_api_key
@limiter.limit("30 per minute")
def push_deals():
    """Endpoint for traders to push deal history."""
    data = request.json
    client_id = data.get('client_id') or request.api_user.get('client', 'Client1')
    
    update_client_field(client_id, 'deals', data.get('deals', []))
    log_action('PUSH_DEALS', 'trader', request.api_user.get('trader'), get_remote_address(), f"Client: {client_id}")
    
    return jsonify({"status": "success", "message": "Deals updated"})

@app.route('/api/trader/push_evaluations', methods=['POST'])
@require_api_key
@limiter.limit("30 per minute")
def push_evaluations():
    """Endpoint for traders to push evaluation data."""
    data = request.json
    client_id = data.get('client_id') or request.api_user.get('client', 'Client1')
    
    update_client_field(client_id, 'evaluations', data.get('evaluations', []))
    log_action('PUSH_EVALUATIONS', 'trader', request.api_user.get('trader'), get_remote_address(), f"Client: {client_id}")
    
    return jsonify({"status": "success", "message": "Evaluations updated"})

# ============ Data History & Version Control ============

@app.route('/api/client/history', methods=['POST'])
@limiter.limit("30 per minute")
def api_get_client_history():
    """
    Get the change history for a client's data.
    Requires client email for authentication.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    limit = data.get('limit', 50)
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    # Look up client by email
    from config.hierarchy import get_client_by_email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered"}), 404
    
    client_id = client_info['client']
    history = get_data_history(client_id, limit)
    
    return jsonify({
        "status": "success",
        "client_id": client_id,
        "history": history,
        "total_versions": len(history)
    })

@app.route('/api/client/version', methods=['POST'])
@limiter.limit("30 per minute")
def api_get_client_version():
    """
    Get a specific version of client data.
    Useful for viewing what the data looked like at a previous point.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    version = data.get('version')
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    if version is None:
        return jsonify({"status": "error", "message": "Version number required"}), 400
    
    # Look up client by email
    from config.hierarchy import get_client_by_email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered"}), 404
    
    client_id = client_info['client']
    version_data = get_data_version(client_id, int(version))
    
    if not version_data:
        return jsonify({"status": "error", "message": f"Version {version} not found"}), 404
    
    return jsonify({
        "status": "success",
        "client_id": client_id,
        "version_info": {
            "version": version_data['version'],
            "action": version_data['action'],
            "changed_by": version_data['changed_by'],
            "change_source": version_data['change_source'],
            "change_description": version_data['change_description'],
            "created_at": version_data['created_at']
        },
        "data": version_data['data']
    })

@app.route('/api/client/rollback', methods=['POST'])
@limiter.limit("5 per hour")
def api_rollback_client_data():
    """
    Rollback client data to a specific previous version.
    Creates a new version marking this as a rollback.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    version = data.get('version') or data.get('rollback_version')  # support both field names
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    if version is None:
        return jsonify({"status": "error", "message": "Version number required"}), 400
    
    # Look up client by email
    from config.hierarchy import get_client_by_email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered"}), 404
    
    client_id = client_info['client']
    
    # Check if version exists
    version_data = get_data_version(client_id, int(version))
    if not version_data:
        return jsonify({"status": "error", "message": f"Version {version} not found"}), 404
    
    # Perform rollback
    success, new_version = rollback_to_version(
        client_id, 
        int(version),
        rolled_back_by=email,
        rolled_back_by_type='client',
        ip_address=get_remote_address()
    )
    
    if success:
        log_action('DATA_ROLLBACK', 'client', email, get_remote_address(), 
                   f"Rolled back {client_id} to version {version} (new version: {new_version})")
        
        return jsonify({
            "status": "success",
            "message": f"Data rolled back to version {version}",
            "client_id": client_id,
            "rolled_back_to_version": version,
            "new_version": new_version,
            "rolled_back_from_date": version_data['created_at']
        })
    else:
        return jsonify({"status": "error", "message": "Failed to rollback data"}), 500

@app.route('/api/client/compare_versions', methods=['POST'])
@limiter.limit("30 per minute")
def api_compare_versions():
    """
    Compare two versions of client data to see what changed.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    version1 = data.get('version1')
    version2 = data.get('version2')
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    if version1 is None or version2 is None:
        return jsonify({"status": "error", "message": "Both version1 and version2 required"}), 400
    
    # Look up client by email
    from config.hierarchy import get_client_by_email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered"}), 404
    
    client_id = client_info['client']
    
    comparison = compare_versions(client_id, int(version1), int(version2))
    
    if not comparison:
        return jsonify({"status": "error", "message": "One or both versions not found"}), 404
    
    return jsonify({
        "status": "success",
        "client_id": client_id,
        "comparison": comparison
    })

@app.route('/api/admin/all_history', methods=['GET'])
@require_admin_password
def api_get_all_history():
    """
    Admin endpoint to get all history across all clients.
    """
    from dashboard.database import get_connection
    
    limit = request.args.get('limit', 100, type=int)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, client_id, version, action, changed_by, changed_by_type,
                   change_source, change_description, created_at
            FROM data_history 
            ORDER BY created_at DESC
            LIMIT ?
        ''', (limit,))
        history = [dict(row) for row in cursor.fetchall()]
    
    return jsonify({
        "status": "success",
        "history": history,
        "total_entries": len(history)
    })

# ============ Health Check ============

@app.route('/health', methods=['GET'])
@app.route('/api/health', methods=['GET'])
def health_check():
    """Simple health check endpoint."""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "clients_count": get_clients_count()
    })

# ============ Change Password Endpoint ============

@app.route('/api/admin/change_password', methods=['POST'])
@require_admin_password
@limiter.limit("3 per hour")
def change_admin_password():
    """Change admin password."""
    new_password = request.json.get('new_password')
    
    if not new_password or len(new_password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters"}), 400
    
    if set_admin_password('super_admin', new_password):
        log_action('CHANGE_PASSWORD', 'admin', 'super_admin', get_remote_address())
        return jsonify({"status": "success", "message": "Password changed successfully"})
    
    return jsonify({"status": "error", "message": "Failed to change password"}), 500

# ============ Sheet Data Endpoints ============
try:
    from dashboard.utils.sheet_helper import fetch_stats_data, fetch_waterlog_data
except ImportError:
    # Fallback if utils package structure is wacky
    try:
        from utils.sheet_helper import fetch_stats_data, fetch_waterlog_data
    except ImportError:
        logging.error("Could not import sheet_helper")

@app.route('/api/sheet/stats')
@require_session
def get_stats_sheet_data():
    """Fetches stats data directly from the Google Sheet."""
    try:
        data = fetch_stats_data()
        if data:
            return jsonify({"status": "success", "data": data})
        return jsonify({"status": "error", "message": "Failed to fetch stats data"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/sheet/waterlog')
@require_session
def get_waterlog_sheet_data():
    """Returns the Profit Share History table.

    Priority:
      1. Compute from DB (daily_watermarks + waterlog_periods) — fully offline,
         updates automatically as daily data is snapshotted.
      2. Fall back to live Google Sheet fetch only if no period schedule is
         stored yet (i.e. before the first import).

    Query params:
      ?client_id=<id>   — required to identify whose schedule/daily data to use
      ?sheet_url=<url>  — fallback sheet URL for pre-import clients
    """
    try:
        from dashboard.watermark_service import compute_waterlog_from_db
    except ImportError:
        from watermark_service import compute_waterlog_from_db

    try:
        client_id_param = request.args.get('client_id')
        sheet_url = request.args.get('sheet_url') or None

        # ── 1. Try fully-offline DB computation ──────────────────────────────
        if client_id_param:
            data = compute_waterlog_from_db(client_id_param)
            if data is not None:  # None means no periods stored yet
                return jsonify({"status": "success", "data": data})

        # ── 2. First-time / pre-import fall-back: read live from the sheet ──
        if client_id_param:
            client_data = get_client_data(client_id_param)
            if client_data:
                sheet_url = client_data.get('sheet_url') or sheet_url

        data = fetch_waterlog_data(sheet_url=sheet_url)
        if data:
            return jsonify({"status": "success", "data": data})
        return jsonify({"status": "error", "message": "Failed to fetch waterlog data"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ============ Main Entry Point ============

def run_dashboard():
    print(f"\n{'='*60}")
    print("SECURE DASHBOARD API SERVER STARTING")
    print(f"{'='*60}")
    print(f"Database: SQLite with encrypted storage")
    print(f"Rate Limiting: Enabled")
    print(f"Password Hashing: PBKDF2-SHA256 (100,000 iterations)")
    print(f"API Keys: Hashed with SHA-256")
    print(f"Audit Logging: Enabled")
    print(f"\nClients in database: {get_clients_count()}")
    print(f"{'='*60}\n")
    app.run(host='0.0.0.0', port=5001, debug=True)

if __name__ == '__main__':
    run_dashboard()
