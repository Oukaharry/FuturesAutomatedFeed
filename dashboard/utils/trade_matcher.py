from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)

class UnifiedTradeMatcher:
    """
    Server-side logic to match MT5 deals to Dashboard Evaluation Rows.
    Solves the 'FundedNext Recycled Account' problem using Time-Based Session Grouping.
    """
    
    def __init__(self, evaluations):
        """
        Args:
            evaluations (list): List of evaluation dicts from dashboard_data.json
        """
        self.evaluations = evaluations
        self.match_log = []
        
        # Build optimized lookup maps
        self.account_map = self._build_account_map()
    
    def _build_account_map(self):
        """
        Map Account Numbers -> List of (RowIndex, DatePurchasedObj, Type)
        Handles fuzzy matching (last 8-10 digits).
        """
        lookup = {}
        
        for idx, row in enumerate(self.evaluations):
            # Parse Dates
            date_purchased = self._parse_date(row.get('Date Purchased'))
            date_started = self._parse_date(row.get('Date Started'))
            
            # Use Started date if available, else Purchased
            ref_date = date_started if date_started else date_purchased
            
            # 1. Challenge Account Check
            acct_ch = str(row.get('Account #', '')).strip()
            if acct_ch and acct_ch.lower() != 'nan':
                self._add_to_lookup(lookup, acct_ch, idx, ref_date, 'challenge')
            
            # 2. Funded Account Check
            acct_fu = str(row.get('Account #.1', '')).strip()
            if acct_fu and acct_fu.lower() != 'nan':
                self._add_to_lookup(lookup, acct_fu, idx, ref_date, 'funded')
                
        return lookup

    def _add_to_lookup(self, lookup, account_str, idx, date, acct_type):
        """Add account and its suffixes to lookup."""
        # Clean account string (remove non-alphanumeric if needed, but usually keep as is)
        # Add full match
        if account_str not in lookup:
            lookup[account_str] = []
        lookup[account_str].append({'idx': idx, 'date': date, 'type': acct_type})
        
        # Add Suffix Matches (Last 8, 10, 12 digits)
        # Useful for 'FN-123456' vs '123456'
        clean_num = re.sub(r'[^0-9]', '', account_str)
        if len(clean_num) > 5:
            for suffix_len in [8, 10, 12]:
                if len(clean_num) >= suffix_len:
                    suffix = clean_num[-suffix_len:]
                    # Only add if suffix distinct from full string
                    if suffix != account_str: 
                        if suffix not in lookup:
                            lookup[suffix] = []
                        # Avoid duplicates
                        if not any(x['idx'] == idx for x in lookup[suffix]):
                            lookup[suffix].append({'idx': idx, 'date': date, 'type': acct_type})

    def _parse_date(self, date_str):
        """Parse 'MM/DD/YY' or ISO format to datetime object."""
        if not date_str or str(date_str).lower() in ['none', 'nan', '']:
            return None
        try:
            # Try MM/DD/YY (Dashboard format)
            return datetime.strptime(str(date_str).split('T')[0], "%m/%d/%y")
        except:
            try:
                # Try ISO
                return datetime.fromisoformat(str(date_str))
            except:
                try:
                    # Try YYYY-MM-DD
                    return datetime.strptime(str(date_str).split('T')[0], "%Y-%m-%d")
                except:
                    return None

    def process_deals(self, deals):
        """
        Main entry point.
        1. Parse Comments -> Get Account + Phase
        2. Group by Session (Time-based)
        3. Match Session to Best Dashboard Row
        4. Update Rows
        
        Returns: 
            updated_evaluations (list)
            log (list of strings)
        """
        if not deals:
            return self.evaluations, ["No deals provided"]

        # Step A: Parse & Sort Deals
        parsed_deals = []
        for d in deals:
            parsed = self._parse_deal_comment(d)
            if parsed:
                parsed['timestamp'] = self._parse_iso(d['time'])
                parsed['profit'] = float(d.get('profit', 0))
                # Store full deal including 'symbol' for potential filtering
                parsed['deal'] = d
                parsed_deals.append(parsed)
        
        if not parsed_deals:
            return self.evaluations, ["No valid parsed deals found"]

        # Sort by time
        parsed_deals.sort(key=lambda x: x['timestamp'])
        
        # Step B: Group by Account Number (The strict MT5 Account Number from comment)
        # Note: 'account_number' here comes from the comment like '12345_CH1' -> '12345'
        deals_by_account = {}
        for pd in parsed_deals:
            acc = pd['account_number'] 
            if acc not in deals_by_account:
                deals_by_account[acc] = []
            deals_by_account[acc].append(pd)
            
        # Step C: Process Each Account's Timeline
        updates_count = 0
        
        for acc_num, acc_deals in deals_by_account.items():
            sessions = self._segment_into_sessions(acc_deals)
            
            for session_idx, session in enumerate(sessions):
                session_start_date = session[0]['timestamp']
                
                # Find Matching Dashboard Row
                target_row_idx = self._find_best_row_match(acc_num, session_start_date)
                
                if target_row_idx is not None:
                    # Apply updates to this row
                    updates, new_logs = self._apply_session_to_row(target_row_idx, session)
                    if updates > 0:
                        updates_count += 1
                        self.match_log.extend(new_logs)
                        # Update Start Date if missing
                        row = self.evaluations[target_row_idx]
                        if not row.get('Date Started') and session_start_date:
                            row['Date Started'] = session_start_date.strftime("%m/%d/%y")
                            self.match_log.append(f"   🗓️ Auto-set 'Date Started' to {row['Date Started']}")
                else:
                    self.match_log.append(f"⚠️ Unmatched Session: Account {acc_num} starting {session_start_date.date()} (No matching row found)")

        self.match_log.append(f"✅ Processed {len(deals)} deals. Updated {updates_count} sessions.")
        return self.evaluations, self.match_log

    def _segment_into_sessions(self, deals):
        """
        Group a list of sorted deals into logical sessions.
        New Session Trigger:
        1. 'CH1' trade appearing (Reset)
        2. Large time gap (> 14 days) between trades
        """
        sessions = []
        current_session = []
        
        for i, deal in enumerate(deals):
            is_start_of_new_session = False
            
            if i == 0:
                is_start_of_new_session = True
            else:
                prev_deal = deals[i-1]
                
                # Rule 1: Phase Reset (CH1 always starts new session unless prev was also CH1 very close)
                # CH1 means Challenge Phase 1. If we see CH1 after say CH2, it's a reset.
                if deal['phase'] == 'CH' and deal['number'] == 1:
                    # If prev was NOT CH1, it's definitely a reset
                    if not (prev_deal['phase'] == 'CH' and prev_deal['number'] == 1):
                         is_start_of_new_session = True
                    # Even if prev was CH1, if > 24 hours gap, assume new attempt
                    elif (deal['timestamp'] - prev_deal['timestamp']).total_seconds() > 86400:
                         is_start_of_new_session = True
                
                # Rule 2: Time Gap (14 Days)
                # If 2 weeks partial silence, assume new attempt if no other indicators
                gap = (deal['timestamp'] - prev_deal['timestamp']).days
                if gap > 14:
                    is_start_of_new_session = True
            
            # Start new session buffer if triggered
            if is_start_of_new_session:
                if current_session:
                    sessions.append(current_session)
                current_session = [deal]
            else:
                current_session.append(deal)
        
        if current_session:
            sessions.append(current_session)
            
        return sessions

    def _find_best_row_match(self, account_num, session_date):
        """
        Find the dashboard row index where:
        1. Account Number matches (fuzzy)
        2. Row Date is closest to Session Date (and not in future)
        """
        # Get candidates from map
        candidates = []
        
        # Exact match
        if account_num in self.account_map:
            candidates.extend(self.account_map[account_num])
        
        # Suffix match (Try last 8 chars)
        if len(account_num) > 8:
            suffix = account_num[-8:]
            if suffix in self.account_map:
                candidates.extend(self.account_map[suffix])
        
        if not candidates:
            return None
        
        # Deduplicate candidates (idx is unique key)
        # We use a dict to deduplicate by idx
        unique_candidates_dict = {}
        for c in candidates:
            unique_candidates_dict[c['idx']] = c
        unique_candidates = list(unique_candidates_dict.values())
        
        best_idx = None
        min_diff = None
        
        for cand in unique_candidates:
            row_date = cand['date']
            
            # If row has no date, treat it as "Old/Default" -> Low priority unless it's the only one
            if not row_date:
                if best_idx is None:
                    best_idx = cand['idx']
                    min_diff = 99999
                continue

            # Calculate gap: Session Date - Row Date
            # Ideally Session Date >= Row Date (Purchased before trade)
            diff = (session_date - row_date).days
            
            # Allow trade to be up to 7 days BEFORE purchase date (admin lag)
            # Allow trade to be anytime AFTER purchase date
            if diff >= -7:
                # We want the SMALLEST difference (Closest purchase date)
                # Prefer positive differences (trade after purchase) over negative ones
                # But mostly just shortest absolute distance from purchase date
                
                if min_diff is None:
                    min_diff = diff
                    best_idx = cand['idx']
                else:
                    # Update if this row is closer in time or (equal and newer index)
                    if abs(diff) < abs(min_diff):
                        min_diff = diff
                        best_idx = cand['idx']
                    # Prefer positive (trade after purchase) over negative if equal magnitude
                    elif abs(diff) == abs(min_diff) and diff >= 0 and min_diff < 0:
                        min_diff = diff
                        best_idx = cand['idx']
        
        return best_idx

    def _apply_session_to_row(self, row_idx, session_deals):
        """ aggregate profits in session and update evaluation row """
        row = self.evaluations[row_idx]
        updates = 0
        local_logs = []
        
        # Calculate Nettings per field
        # Map: "Hedge Result 1" -> 500.00
        field_sums = {}
        
        for d in session_deals:
            field = self._get_field_name(d['phase'], d['number'])
            if field:
                if field not in field_sums:
                    field_sums[field] = 0.0
                field_sums[field] += d['profit']

        # Apply to row - Replaces value (or adds? usually replaces total for that phase)
        # BUT wait: The input 'deals' here are ALL deals for that phase in that session.
        # So we should sum them up and overwrite the field, assuming the client sent full history.
        # If client sends incremental, we might double count.
        # Requirement: "Client sends full history for relevant period".
        # We will overwite based on the sum of provided deals. This is safer than adding to existing which might double count.
        
        for field, profit in field_sums.items():
            # Only update if changed significantly
            old_val = row.get(field)
            # Handle string conversions if necessary (dashboard usually uses strings or floats)
            row[field] = profit
            local_logs.append(f"   ✅ Row {row_idx} {row.get('Account #')} [{field}] <- {profit:.2f}")
            updates += 1
            
        return updates, local_logs

    def _get_field_name(self, phase, number):
        """Map Phase Code to Dashboard Column"""
        if phase == 'CH':
            if 1 <= number <= 5: return f"Hedge Result {number}"
        elif phase == 'FD':
            if number == 0: return "Hedge Result 1.1" # FD0
            if 1 <= number <= 4: return f"Hedge Result {number + 1}.1" # FD1->2.1
            if number >= 5: return f"Hedge Result {number + 1}" # FD5->6
        elif phase == 'FA':
            return "Hedge Day 1" # Simplification for Farming
        return None

    def _parse_deal_comment(self, deal):
        """
        Extract {Account}_{Phase}{Num}
        Regex: ([A-Za-z0-9]+)_([CFD]+)([0-9]+)
        Ex: 123456_CH1 -> Account=123456, Phase=CH, Num=1
        """
        comment = deal.get('comment', '')
        if not comment:
            return None
            
        # Try standard pattern
        # <Account>_<Phase><Num>
        # 123456_CH1
        # MFF123456_FD2
        match = re.search(r'([A-Za-z0-9\-]+)_([A-Z]{2})([0-9]+)', comment)
        if match:
            return {
                'account_number': match.group(1),
                'phase': match.group(2),
                'number': int(match.group(3))
            }
        
        # Try without underscore if failed (e.g. 123456CH1)
        match = re.search(r'([0-9]{5,})([A-Z]{2})([0-9]+)', comment)
        if match:
             return {
                'account_number': match.group(1),
                'phase': match.group(2),
                'number': int(match.group(3))
            }
            
        return None
        
    def _parse_iso(self, date_str):
        try:
            return datetime.fromisoformat(str(date_str).replace('Z', '+00:00'))
        except:
            return datetime.now() # Fallback
