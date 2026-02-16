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
import re
from datetime import datetime, timedelta
from dashboard.financial_overview import calculate_propfirm_overview, get_payouts_history, get_portfolio_growth_data, get_payouts_growth_data, get_cumulative_deposits, get_cumulative_trading_profit, get_cumulative_fees_data, get_cumulative_hedge_data, get_cumulative_farming_data, calculate_trader_stats, parse_date, get_cached_clients_dataset, calculate_all_financials, get_client_performance_stats

# Add project root to sys.path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.hierarchy import (
    SYSTEM_HIERARCHY, add_admin, add_trader, add_client, 
    update_admin_details, update_trader_details, update_client_details, update_client_category,
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
    delete_user_credential, update_user_email,
    get_user, list_users, deactivate_user, reset_user_password, user_exists,
    record_login_attempt, is_account_locked,
    find_user_by_identifier, verify_user_by_identifier,
    # History management
    save_client_data_with_history, get_data_history, get_data_version,
    rollback_to_version, compare_versions, get_latest_version
)
from dashboard.utils.trade_matcher import UnifiedTradeMatcher

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
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
            
    return None


def filter_matches_by_date(matches, evaluations, trade_timestamp, phase_code=None, trade_number=None):
    """
    Filter matches to find the best matching evaluation.
    
    For FundedNext (FNFT):
        - Ignores trade timestamps (mostly).
        - Priority 1: Check if the TARGET FIELD (e.g. Hedge Result 1) contains a PLACEHOLDER ("DAY", "/Y", etc).
          If found, this is the active reset account expecting data.
        - Priority 2: Sort by Date Started (Newest first).
        
    For Others:
        - Filters by Trade Date >= Date Purchased (with small buffer).
        - If multiple valid matches, picks the one closest to trade date.
    
    Args:
        matches: List of (eval_index, matched_account)
        evaluations: List of evaluation dicts
        trade_timestamp: Timestamp of the trade (float or int)
        phase_code: (Optional) Phase code to help determine target field for placeholder check
        trade_number: (Optional) Trade number for target field check
    """
    if not matches:
        return None
        
    # Check if this is a FundedNext account (FNFT prefix)
    is_fnft = False
    match_acc_str = str(matches[0][1]).upper()
    if 'FNFT' in match_acc_str or 'FUNDEDNEXT' in match_acc_str:
        is_fnft = True
    
    if is_fnft:
        # FNFT Priority Logic
        
        # Helper to detect placeholders in a specific field content
        def has_placeholder(val):
            s = str(val).upper()
            placeholders = ['DAY', '/Y', 'MON', 'TUE', 'WED', 'THU', 'FRI']
            return any(p in s for p in placeholders)

        # 1. Try to find a match where the expected TARGET FIELD has a placeholder
        # We need to guess the field name. 
        if phase_code:
            target_field = None
            # Replicate simpler version of get_field_name logic or use it if context allows
            # Since we are outside the update loop, we simulate field name logic
            if phase_code == 'CH' and trade_number:
                target_field = f"Hedge Result {trade_number}"
            elif phase_code == 'FD' and trade_number:
                # FNFT: FD0->1.1 (Wait, FNFT usually starts at 1?)
                # FNFT logic in get_field_name: "Other firms: FD0->HR1.1, FD1->HR1.1"
                # Let's assume standard behavior for now.
                target_field = f"Hedge Result {trade_number}.1" if trade_number > 0 else "Hedge Result 1.1"
            elif phase_code == 'DD' and trade_number:
                target_field = f"Hedge Result {trade_number}.1"
            
            # If we identified a potential target field, check candidates
            if target_field:
                for idx, acc in matches:
                    ev = evaluations[idx]
                    existing_val = ev.get(target_field, '')
                    if has_placeholder(existing_val):
                         # Found a winner! This "new" account is waiting for data.
                         return (idx, acc)

        # 2. Fallback: Sort matches by Date Started (Descending) -> Newest first
        def fnft_latest_sorter(match_tuple):
            idx, _ = match_tuple
            ev = evaluations[idx]
            d_str = ev.get('Date Started', '') or ev.get('Date Purchased', '')
            d_obj = parse_sheet_date(d_str)
            
            # Key 1: Timestamp (0 if missing)
            ts = d_obj.timestamp() if d_obj else 0
            # Key 2: Index (Original order)
            return (ts, idx)

        # Sort descending to get max date/index at the top
        matches.sort(key=fnft_latest_sorter, reverse=True)
        return matches[0]

    # --- Standard Logic for other firms ---
    
    if not trade_timestamp:
        return matches[0]

    # Convert trade timestamp to datetime
    try:
        val = float(trade_timestamp)
        trade_date = datetime.fromtimestamp(val)
    except (ValueError, TypeError):
         # If not a float, try isoformat string if present
        try:
             trade_date = datetime.fromisoformat(str(trade_timestamp).replace('Z', '+00:00'))
        except ValueError:
             return matches[0]
        
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
        # Fallback for non-FNFT if no valid dates found (relaxed matching)
        return matches[0]
        
    # Sort matches:
    # 1. Prefer Non-Negative Delta (Trade >= Start) -> Logic: Trade follows Start.
    # 2. Then Smallest Absolute Delta (Closest date).
    def match_sorter(x):
        delta = x['delta']
        valid_date = x['valid_date']
        
        if not valid_date:
             return (2, 0) # Least preferred
        
        # If delta is negative (Trade < Start), it is a "buffer match". 
        # We penalize it slightly so that if we have a "real match" (Trade > Start), we pick that.
        if delta < 0:
             return (1, abs(delta)) 
        
        return (0, delta) # Best match: Positive delta, smallest value
        
    valid_matches.sort(key=match_sorter)
    
    match_result = valid_matches[0]['match']
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
            m = re.search(r'_(CH|FD|DD|FA)(\d+)?', c, re.IGNORECASE)
            if m:
                return m.group(1).upper(), int(m.group(2)) if m.group(2) else None
            return None, None
            
        def get_ts(d):
            t = d.get('time')
            if isinstance(t, (int, float)): return t
            if isinstance(t, str):
                try:
                    return datetime.datetime.fromisoformat(t).timestamp()
                except:
                    pass
            return 0

        # 1. Group by Account Number (from login or comment)
        # Note: raw_deals usually come from a single login, but might contain history for that login.
        # But we need the 'Account Number' string (e.g. "208226") which is usually in the content or derived.
        # The 'deals' from client don't explicitly have 'account_number' field in each deal dict usually, 
        # unless added by get_deals. 
        # But we know the push is for ONE account.
        # We can try to extract 'Account Number' from comments if possible (e.g. MFFU...12345)
        # Or if available in deal.
        
        # Let's assume passed 'aggregated_data' logic was doing groupings.
        # We will iterate raw_deals, extracting (Phase, TradeNum) from comment.
        # And Group by Time Gaps (> 7 days) -> New Session.
        
        raw_deals.sort(key=get_ts)
        
        # Group into sessions strictly by Time Gap
        sessions = []
        if raw_deals:
            current_session = {'deals': [], 'start': get_ts(raw_deals[0]), 'end': get_ts(raw_deals[0]), 'account_guess': None}
            last_ts = current_session['start']
            
            for d in raw_deals:
                ts = get_ts(d)
                # 7 Days Gap OR Balance op (Reset)
                time_gap = ts - last_ts > (7 * 24 * 3600)
                is_balance_reset = str(d.get('type', '')).upper() == 'BALANCE' and float(d.get('profit', 0)) > 0
                
                if (time_gap or is_balance_reset) and current_session['deals']:
                    sessions.append(current_session)
                    current_session = {'deals': [], 'start': ts, 'end': ts, 'account_guess': None}
                
                current_session['deals'].append(d)
                current_session['end'] = max(current_session['end'], ts)
                last_ts = ts
                
                # Try to guess account number from comment
                c = d.get('comment', '')
                # MFFU...12345_CH1
                # Regex for account number before _Phase
                # (Acc)(_Phase)
                # Usually: [A-Za-z0-9]+_
                match = re.search(r'([A-Za-z0-9]{4,})_(CH|FD|DD|FA)', c)
                if match:
                    current_session['account_guess'] = match.group(1)
            
            if current_session['deals']:
                sessions.append(current_session)
        
        match_log.append(f"   Found {len(sessions)} distinct sessions based on 7-day gaps")
        
        # Now match each session to an Evaluation
        updates_made = 0
        
        for session in sessions:
            if not session['account_guess']:
                continue # Can't match without account number
                
            # Aggregate stats for session
            session_profit = sum(float(d.get('profit', 0)) + float(d.get('commission', 0)) + float(d.get('swap', 0)) for d in session['deals'])
            
            # Determine Phase/TradeNum from MOST frequent in session
            # (To handle noise)
            phases = {}
            for d in session['deals']:
                p, n = parse_comment(d.get('comment', ''))
                if p:
                    key = (p, n)
                    phases[key] = phases.get(key, 0) + 1
            
            if not phases:
                continue
                
            best_phase, best_num = max(phases.items(), key=lambda x: x[1])[0]
            
            # MATCHING LOGIC
            acc_num = session['account_guess']
            start_date_ts = session['start']
            
            # Find candidate evaluations
            # Filter by Account Number
            candidates = [e for e in evaluations if str(e.get('Account Number', '')).endswith(acc_num) or acc_num.endswith(str(e.get('Account Number', '')))]
            
            if not candidates:
                match_log.append(f"⚠️ No evaluation found for session {acc_num} (Start: {datetime.datetime.fromtimestamp(start_date_ts)})")
                continue
            
            # Filter by Date Purchased
            # We want Evaluation.DatePurchased <= Session.Start
            # And closest to it.
            valid_candidates = []
            for e in candidates:
                dp_str = str(e.get('Date Purchased', ''))
                try:
                    # Try common formats
                    # 1/20/25, 2025-01-20, etc.
                    # Use helper parse_date from global context if available or simple
                    # Assume parse_date is available (imported)
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
                        if diff > -86400:
                            valid_candidates.append((e, diff))
                except:
                    pass
            
            if not valid_candidates:
                # If no dates parse, fallback to last added?
                # Or try matching by Phase Code?
                match_log.append(f"⚠️ No valid date match for {acc_num}")
                continue
            
            # Sort by diff (smallest diff is closest match)
            valid_candidates.sort(key=lambda x: x[1])
            best_eval, drift = valid_candidates[0]
            
            # Determine Field Name
            # (Reuse existing logic or simplified)
            field_name = "Hedge Result" # Default?
            # Actually we usually map CH1 -> Hedge Result, CH2 -> Hedge Result 2
            # Or use 'get_field_name_for_phase' if available
            
            # Let's use simple mapping for now to maintain robustness
            if best_phase == 'CH':
                field_name = f"Hedge Result {best_num}" if best_num and best_num > 1 else "Hedge Result"
            elif best_phase == 'FD':
                field_name = f"Hedge Result {best_num}" if best_num else "Hedge Result" # ?
            elif best_phase == 'FA':
                 # Farming logic is sequential usually
                 # We can append?
                 match_log.append("   Matched Farming session - aggregating total")
                 field_name = "Hedge Result" # Placeholder
            
            # Update
            best_eval[field_name] = session_profit
            updates_made += 1
            match_log.append(f"✅ Matched {acc_num} Session (Start {datetime.datetime.fromtimestamp(start_date_ts)}) to Eval {best_eval.get('id')} -> {field_name} = ${session_profit:.2f}")

        return evaluations, match_log

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
        return evaluations, ["No evaluations or aggregated data to process"]
    
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
    return evaluations, match_log

# Initialize admin password if not exists
def init_admin_password():
    """Initialize default admin password if not set."""
    admin_password = os.getenv('ADMIN_PASSWORD', 'BallerAdmin@123')
    set_admin_password('super_admin', admin_password)
    print("Admin password initialized")

# Run initialization
init_database()
init_admin_password()

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
        # Admin sees only their own data
        admin_name = user_identifier
        if admin_name in full_hierarchy.get('admins', {}):
            return {
                'admins': {
                    admin_name: full_hierarchy['admins'][admin_name]
                }
            }
        return {'admins': {}}
    
    if user_type == 'trader':
        # Trader sees only their clients - need to find which admin they belong to
        trader_name = user_identifier
        for admin_name, admin_data in full_hierarchy.get('admins', {}).items():
            traders = admin_data.get('traders', {})
            if trader_name in traders:
                return {
                    'admins': {
                        admin_name: {
                            'email': '',  # Hide admin email from trader
                            'traders': {
                                trader_name: traders[trader_name]
                            }
                        }
                    }
                }
        return {'admins': {}}
    
    if user_type == 'client':
        # Client sees only themselves
        client_name = user_identifier
        for admin_name, admin_data in full_hierarchy.get('admins', {}).items():
            for trader_name, trader_data in admin_data.get('traders', {}).items():
                for client in trader_data.get('clients', []):
                    if client.get('name') == client_name or client.get('email') == client_name:
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
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    
    session_info = validate_session(session_token)
    if not session_info:
        return jsonify({"status": "error", "message": "Invalid session"}), 401
    
    user_type = session_info.get('user_type')
    user_identifier = session_info.get('user_identifier')
    
    filtered = get_filtered_hierarchy(user_type, user_identifier)
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
    
    return jsonify(response_data)

@app.route('/api/client/update_source', methods=['POST'])
@require_session
def update_client_source():
    """Update client source (BEF/Private)."""
    session_user = request.session_user
    if session_user.get('user_type') != 'super_admin':
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
        
    data = request.json
    client_id = data.get('client_id')
    source = data.get('source')
    
    if not client_id or not source:
        return jsonify({"status": "error", "message": "Missing fields"}), 400
        
    # Update Database
    client_data = get_client_data(client_id)
    if client_data:
        identity = client_data.get('identity', {})
        # Update all relevant fields for consistency
        identity['profile'] = source
        identity['category'] = source
        identity['source'] = source
        update_client_field(client_id, 'identity', identity)
        
        # Also update Hierarchy.json if possible
        from config.hierarchy import get_client_profile, update_client_category
        profile = get_client_profile(client_id)
        if profile:
            update_client_category(profile['admin'], profile['trader'], client_id, source)
    
        log_action('UPDATE_CLIENT_SOURCE', 'super_admin', client_id, get_remote_address(), f"To: {source}")
        return jsonify({"status": "success"})
        
    return jsonify({"status": "error", "message": "Client not found"}), 404
    
    if not client_id or source not in ['BEF', 'Private']:
        return jsonify({"status": "error", "message": "Invalid data"}), 400
        
    client_data = get_client_data(client_id)
    if not client_data:
        return jsonify({"status": "error", "message": "Client not found"}), 404
        
    if 'identity' not in client_data:
        client_data['identity'] = {}
        
    client_data['identity']['source'] = source
    
    # Save using update_client_field to persist changes
    # We ideally should create a new history version but for metadata direct update might be okay?
    # Actually update_client_field handles persistence
    update_client_field(client_id, 'identity', client_data['identity'])
    
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
            evaluations, hedge_match_log = update_evaluations_from_aggregated_data(evaluations, aggregated_data=aggregated_by_comment, raw_deals=mt5_deals)
            
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
            statistics = calculate_statistics(evaluations, mt5_deals_param, mt5_acc_param)
            
            # Log the hedging review results
            hr = statistics.get('hedging_review', {})
            app.logger.info(f"✅ Stats calculated:")
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
            "email": email
        },
        # Store aggregated comment data if provided (from Push by Comment feature)
        "aggregated_by_comment": aggregated_by_comment if aggregated_by_comment else existing_data.get("aggregated_by_comment", []),
        "comment_summary": comment_summary if comment_summary else existing_data.get("comment_summary", {})
    }
    
    # Final verification before save
    hr_final = statistics.get('hedging_review', {})
    app.logger.info(f"📦 FINAL DATA TO SAVE for {client_id}:")
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
        from utils.data_processor import fetch_evaluations, calculate_statistics
        
        evaluations = fetch_evaluations(sheet_url)
        if not evaluations:
            return jsonify({"status": "error", "message": "Could not fetch data from sheet. Make sure it's public."}), 400
        
        # Calculate statistics without MT5 data (discrepancy will be 0)
        statistics = calculate_statistics(evaluations, None, None)
        
        # Prepare client data
        client_data = {
            "deals": [],
            "positions": [],
            "account": {},
            "evaluations": evaluations,
            "statistics": statistics,
            "dropdown_options": {},
            "identity": {
                "admin": admin_id,
                "trader": trader_id,
                "client": client_id,
                "email": email
            },
            "sheet_url": sheet_url,
            "migrated_at": datetime.now().isoformat()
        }
        
        # Save to database WITH history tracking
        success, version = save_client_data_with_history(
            client_id, 
            client_data,
            action='SHEET_IMPORT',
            changed_by=email,
            changed_by_type='client',
            ip_address=get_remote_address(),
            change_source='sheet_migration',
            change_description=f"Imported {len(evaluations)} records from Google Sheets"
        )
        
        # Update Hierarchy
        add_admin(admin_id)
        add_trader(admin_id, trader_id)
        add_client(admin_id, trader_id, client_id)
        
        log_action('SHEET_MIGRATION', 'client', email, get_remote_address(), 
                   f"Migrated {len(evaluations)} records from Google Sheets for {client_id} (v{version})")
        
        # Return statistics for verification
        return jsonify({
            "status": "success", 
            "message": f"Successfully migrated {len(evaluations)} evaluation records",
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
        response.set_cookie('session_token', session_token, httponly=True, secure=True, samesite='Strict')
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

@app.route('/api/auth/login', methods=['POST'])
@limiter.limit("10 per minute")
def unified_login():
    """
    Unified login endpoint - auto-detects user type from email/username.
    - Super Admin: requires email + password
    - Admin/Trader/Client: only requires email (no password)
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
    username = user.get('username', identifier)
    
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
            response.set_cookie('session_token', session_token, httponly=True, secure=True, samesite='Lax', max_age=max_age)
            return response
        
        record_login_attempt('super_admin', 'super_admin', client_ip, False)
        log_action('LOGIN_FAILED', 'super_admin', 'super_admin', client_ip, 'Invalid password', False)
        return jsonify({"status": "error", "message": "Invalid password"}), 403
    
    # Handle Admin/Trader/Client login - NO PASSWORD REQUIRED (email only)
    # Just verify the email exists in hierarchy
    session_token = create_session(user_type, username, client_ip)
    record_login_attempt(username, user_type, client_ip, True)
    log_action('LOGIN_SUCCESS', user_type, username, client_ip, 'Email-only login')
    
    # Determine redirect URL based on user type
    redirect_map = {
        'admin': f'/admin/{username}',
        'trader': f'/trader/{username}',
        'client': f'/dashboard/{username}'
    }
    redirect_url = redirect_map.get(user_type, '/')
    
    max_age = 30 * 24 * 60 * 60 if remember else 86400
    response = jsonify({
        "status": "success",
        "user_type": user_type,
        "redirect": redirect_url,
        "must_change_password": False
    })
    response.set_cookie('session_token', session_token, httponly=True, secure=True, samesite='Lax', max_age=max_age)
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
        import secrets
        import string
        alphabet = string.ascii_letters + string.digits
        password = ''.join(secrets.choice(alphabet) for i in range(12))
    
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
        if not admin or not trader: return jsonify({"status": "error", "message": "Parents required"}), 400
        result = remove_client(admin, trader, name)
        delete_user_credential(name, 'client')
    
    if result:
        log_action(f'DELETE_{user_type.upper()}', user_type, name, get_remote_address())
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "error", "message": "Delete failed (not found)"}), 400

@app.route('/api/update_admin', methods=['POST'])
def api_update_admin():
    name = request.json.get('name')
    email = request.json.get('email')
    if not name: return jsonify({"status": "error", "message": "Name required"}), 400
    
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
    if not admin or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
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
    
    if not admin or not trader or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
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
    
    # Recalculate statistics
    from utils.data_processor import calculate_statistics
    client_data['statistics'] = calculate_statistics(evaluations, None, None)
    
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
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    
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
        if data:
            # Add historical MT5 values to hedging_review totals
            if 'statistics' in data and 'hedging_review' in data['statistics']:
                hr = data['statistics']['hedging_review']
                hist_accounts = hr.get('historical_accounts', [])
                
                # Calculate historical totals
                hist_deposits = sum(acc.get('deposits', 0) for acc in hist_accounts)
                hist_withdrawals = sum(acc.get('withdrawals', 0) for acc in hist_accounts)
                hist_balance = sum(acc.get('final_balance', 0) for acc in hist_accounts)
                
                # Add to current values if there are historical accounts
                if hist_accounts:
                    hr['total_deposits'] = hr.get('total_deposits', 0) + hist_deposits
                    hr['total_withdrawals'] = hr.get('total_withdrawals', 0) + hist_withdrawals
                    hr['current_balance'] = hr.get('current_balance', 0) + hist_balance
                    
                    # Recalculate actual hedging and discrepancy with combined values
                    net_deposits = hr['total_deposits'] + hr['total_withdrawals']
                    hr['actual_hedging_results'] = hr['current_balance'] - net_deposits
                    hr['discrepancy'] = hr['actual_hedging_results'] - hr.get('sheet_hedging_results', 0)
            
            return jsonify(data)
    
    # If no client specified, return empty
    return jsonify({
        "deals": [], "positions": [], "account": {}, 
        "evaluations": [], "statistics": {}, "dropdown_options": {}, 
        "last_updated": "Never"
    })

# ============ Session-based Update (for Dashboard UI) ============

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
                
                # Merge the update data with existing data
                client_data = {
                    "deals": data.get("deals", existing_data.get("deals", [])),
                    "positions": data.get("positions", existing_data.get("positions", [])),
                    "account": data.get("account", existing_data.get("account", {})),
                    "evaluations": evaluations,
                    "statistics": data.get("statistics", existing_data.get("statistics", {})),
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
