"""
Parse Chris Ream's full MT5 report (ReportHistory-3063841.html).
Extract all trades with account/phase info from both Positions and Deals sections.
Group into sessions and compute hedge results per account.
Compare with DB to find missing data.
"""
import re, json, sqlite3
from html.parser import HTMLParser
from datetime import datetime, timedelta
from collections import defaultdict

HTML_FILE = 'trader_companion/ReportHistory-3063841.html'

# ============================================================
# Step 1: Parse the HTML to extract all deals
# ============================================================
class MT5ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_deals = False
        self.deals_header_seen = False
        self.current_row = []
        self.current_cell = ''
        self.in_cell = False
        self.in_row = False
        self.skip_hidden = False
        self.cell_is_hidden = False
        self.deals = []
        self.positions = []
        self.in_positions = False
        self.section = None  # 'positions' or 'deals'
        self.all_text = ''
        
    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == 'tr':
            self.current_row = []
            self.in_row = True
        elif tag == 'td' and self.in_row:
            self.in_cell = True
            self.current_cell = ''
            self.cell_is_hidden = 'hidden' in attrs_d.get('class', '')
        elif tag == 'th':
            self.in_cell = True
            self.current_cell = ''
            
    def handle_endtag(self, tag):
        if tag == 'td' and self.in_cell:
            self.current_row.append((self.current_cell.strip(), self.cell_is_hidden))
            self.in_cell = False
            self.cell_is_hidden = False
        elif tag == 'th' and self.in_cell:
            text = self.current_cell.strip()
            if text == 'Positions':
                self.section = 'positions'
            elif text == 'Deals':
                self.section = 'deals'
            elif text == 'Orders':
                self.section = 'orders'
            self.in_cell = False
        elif tag == 'tr' and self.in_row:
            self.in_row = False
            if self.section == 'deals' and len(self.current_row) >= 14:
                self.deals.append(self.current_row)
            elif self.section == 'positions' and len(self.current_row) >= 5:
                self.positions.append(self.current_row)
                
    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data

print("Parsing HTML report...")
with open(HTML_FILE, 'rb') as f:
    raw = f.read()
# Detect encoding
if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
    html_content = raw.decode('utf-16')
else:
    html_content = raw.decode('utf-8', errors='replace')

parser = MT5ReportParser()
parser.feed(html_content)

print(f"Positions rows: {len(parser.positions)}")
print(f"Deals rows: {len(parser.deals)}")

# ============================================================
# Step 2: Extract deal info
# ============================================================
# Deal columns: Time, Deal, Symbol, Type, Direction, Volume, Price, Order, [hidden:Cost], Commission, Fee, Swap, Profit, Balance, Comment
# But the hidden Cost cell is included in the row data

parsed_deals = []
for row in parser.deals:
    # Extract visible cells only (skip hidden ones for column alignment)
    cells = [(text, hidden) for text, hidden in row]
    
    # Get all visible cell texts
    visible = [text for text, hidden in cells if not hidden]
    hidden = [text for text, hidden in cells if hidden]
    
    # The comment might be in the last visible cell
    if len(visible) >= 13:
        time_str = visible[0]
        deal_id = visible[1]
        symbol = visible[2]
        deal_type = visible[3]
        direction = visible[4]
        volume = visible[5]
        price = visible[6]
        order = visible[7]
        commission = visible[8]
        fee = visible[9]
        swap = visible[10]
        profit_str = visible[11]
        balance = visible[12]
        comment = visible[13] if len(visible) >= 14 else ''
    else:
        continue
    
    # Parse profit
    profit_clean = profit_str.replace(' ', '').replace('\xa0', '')
    try:
        profit = float(profit_clean)
    except:
        profit = 0.0
    
    # Parse time
    try:
        dt = datetime.strptime(time_str, '%Y.%m.%d %H:%M:%S')
    except:
        dt = None
    
    parsed_deals.append({
        'time': dt,
        'time_str': time_str,
        'deal_id': deal_id,
        'symbol': symbol,
        'type': deal_type,
        'direction': direction,
        'volume': volume,
        'price': price,
        'order': order,
        'commission': commission,
        'profit': profit,
        'balance': balance,
        'comment': comment,
    })

# Also extract from positions section (has hidden comment with phase)
position_comments = {}  # order_id -> comment with phase
for row in parser.positions:
    cells = [(text, hidden) for text, hidden in row]
    visible = [text for text, hidden in cells if not hidden]
    hidden_texts = [text for text, hidden in cells if hidden]
    
    # Position columns: Time, Position, Symbol, Type, [hidden comment], Volume, Price, S/L, T/P, Time, Price, Comm, Swap, Profit
    if hidden_texts:
        for ht in hidden_texts:
            # This hidden text is the full comment like "MFFU...80217_CH2"
            if ht and len(ht) > 3:
                # The position ID is in visible[1]
                if len(visible) >= 2:
                    pos_id = visible[1]
                    position_comments[pos_id] = ht

print(f"\nPosition comments with phase info: {len(position_comments)}")

# ============================================================
# Step 3: Enrich deals with position comments
# ============================================================
# The deal's "order" field maps to position_comments keys
for d in parsed_deals:
    if d['order'] in position_comments:
        full_comment = position_comments[d['order']]
        d['full_comment'] = full_comment
    elif d['comment'] and '...' not in d['comment']:
        d['full_comment'] = d['comment']
    else:
        d['full_comment'] = d['comment']  # might be truncated

# ============================================================
# Step 4: Parse account and phase from comments
# ============================================================
# Comment patterns:
# "MFFU...80217_CH2" -> account ending 80217, phase CH2
# "V2-...8738_FD1" -> account ending 8738, phase FD1
# "TDFY...92031_CH2" -> account ending 92031, phase CH2
# "FNFT...93002_CH1" -> account ending 93002, phase CH1
# Opening trades have the account comment, closing trades have [sl X] or [tp X]
# Comments without underscore phase: "MFFU...80023" -> CH1 (first challenge, default)

PHASE_RE = re.compile(r'_?(CH\d|FD\d)\s*$')
ACCT_RE = re.compile(r'(?:MFFU|FTPR|V2-|TDFY|FNFT|AFAD|FTDF)[.]*(\.\.\.)?([\w]+?)(?:_(CH\d|FD\d))?$')

# Simpler: extract trailing digits and any phase suffix
COMMENT_RE = re.compile(r'^([A-Z0-9]+)\.\.\.(\w+?)(?:_(CH\d|FD\d))?$')

trade_sessions = []  # grouped by account

for d in parsed_deals:
    comment = d.get('full_comment', '')
    if not comment or comment.startswith('[') or comment == 'internal transfer':
        continue
    
    m = COMMENT_RE.match(comment)
    if m:
        prefix = m.group(1)
        acct_part = m.group(2)
        phase = m.group(3)  # None if no phase suffix (means CH1)
        d['prefix'] = prefix
        d['acct_part'] = acct_part
        d['phase'] = phase if phase else 'CH1'
    else:
        # Try direct match for non-truncated comments
        # e.g. just numbers, or non-standard format
        d['prefix'] = ''
        d['acct_part'] = comment
        d['phase'] = 'CH1'

# ============================================================
# Step 5: Group deals into sessions by account+phase
# ============================================================
# A "session" = all opening trades for the same account+phase that are closed together
# Opening trades have direction "in", closing trades have direction "out"
# The profit comes from the closing trade

# Group opening trades by (acct_part, phase)
from collections import defaultdict

account_phase_trades = defaultdict(list)

for d in parsed_deals:
    if 'acct_part' not in d:
        continue
    if d['direction'] == 'in' and d['symbol']:
        key = (d['prefix'], d['acct_part'], d['phase'])
        account_phase_trades[key].append(d)

print(f"\nUnique (prefix, account, phase) combinations: {len(account_phase_trades)}")

# Count by phase
phase_counts = defaultdict(int)
for (prefix, acct, phase), trades in account_phase_trades.items():
    phase_counts[phase] += 1

print("\nPhase distribution of opening trades:")
for phase, count in sorted(phase_counts.items()):
    print(f"  {phase}: {count} account groups")

# ============================================================
# Step 6: Now compute session profit for each account+phase
# ============================================================
# For each opening trade, find the matching closing trade by order ID
# The closing trade's profit is the session result

# Build order->closing profit map
closing_profits = {}
for d in parsed_deals:
    if d['direction'] == 'out' and d['symbol']:
        closing_profits[d['order']] = d['profit']

# For each account+phase group, sum the closing profits
session_results = []

for (prefix, acct, phase), trades in account_phase_trades.items():
    total_profit = 0.0
    trade_count = 0
    first_time = None
    
    for t in trades:
        order = t['order']
        if order in closing_profits:
            total_profit += closing_profits[order]
            trade_count += 1
        if first_time is None or (t['time'] and (first_time is None or t['time'] < first_time)):
            first_time = t['time']
    
    session_results.append({
        'prefix': prefix,
        'acct_part': acct,
        'phase': phase,
        'profit': round(total_profit, 2),
        'trade_count': trade_count,
        'open_count': len(trades),
        'first_time': first_time,
    })

session_results.sort(key=lambda x: x['first_time'] or datetime.min)

print(f"\nTotal session results: {len(session_results)}")
print(f"\nFirst 20 sessions:")
for s in session_results[:20]:
    ts = s['first_time'].strftime('%Y-%m-%d %H:%M') if s['first_time'] else '?'
    print(f"  {ts} | {s['prefix']:>4}...{s['acct_part']:<12} | {s['phase']} | profit=${s['profit']:>10.2f} | {s['trade_count']}/{s['open_count']} matched")

print(f"\nLast 20 sessions:")
for s in session_results[-20:]:
    ts = s['first_time'].strftime('%Y-%m-%d %H:%M') if s['first_time'] else '?'
    print(f"  {ts} | {s['prefix']:>4}...{s['acct_part']:<12} | {s['phase']} | profit=${s['profit']:>10.2f} | {s['trade_count']}/{s['open_count']} matched")

# ============================================================
# Step 7: Map to hedge result columns
# ============================================================
phase_to_col = {
    'CH1': 'Hedge Result 1',
    'CH2': 'Hedge Result 2', 
    'CH3': 'Hedge Result 3',
    'FD1': 'Hedge Result 1.1',
    'FD2': 'Hedge Result 2.1',
    'FD3': 'Hedge Result 3.1',
}

# ============================================================
# Step 8: Compare with DB
# ============================================================
print(f"\n{'='*100}")
print(f"COMPARING MT5 REPORT vs DATABASE")
print(f"{'='*100}")

db = sqlite3.connect('dashboard/dashboard.db')
row = db.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'").fetchone()
evals = json.loads(row[0])

# Build lookup from DB: account trailing digits -> eval index + data
db_lookup = defaultdict(list)
for i, ev in enumerate(evals):
    acct = str(ev.get('Account #', '')).strip()
    acct1 = str(ev.get('Account #.1', '')).strip()
    
    if acct:
        # Extract trailing digits
        digits = re.sub(r'[^0-9]', '', acct)
        if len(digits) >= 4:
            db_lookup[digits[-5:]].append((i, ev))
            db_lookup[digits[-4:]].append((i, ev))
            if len(digits) >= 6:
                db_lookup[digits[-6:]].append((i, ev))
    if acct1:
        digits1 = re.sub(r'[^0-9]', '', acct1)
        if len(digits1) >= 4:
            db_lookup[digits1[-5:]].append((i, ev))
            db_lookup[digits1[-4:]].append((i, ev))

# For each MT5 session, check if the hedge result is in DB 
missing_from_db = []
already_filled = []
mismatched = []

for s in session_results:
    col = phase_to_col.get(s['phase'])
    if not col:
        continue
    
    acct_digits = re.sub(r'[^0-9]', '', s['acct_part'])
    if not acct_digits:
        continue
    
    # Try matching
    candidates = []
    for trail_len in [6, 5, 4]:
        if len(acct_digits) >= trail_len:
            trail = acct_digits[-trail_len:]
            if trail in db_lookup:
                candidates.extend(db_lookup[trail])
    
    # Deduplicate
    seen = set()
    unique_candidates = []
    for idx, ev in candidates:
        if idx not in seen:
            seen.add(idx)
            unique_candidates.append((idx, ev))
    
    if not unique_candidates:
        missing_from_db.append(s)
        continue
    
    # Check if any candidate has this column filled
    for idx, ev in unique_candidates:
        db_val = str(ev.get(col, '')).strip()
        if db_val and db_val != 'nan':
            # Compare values
            try:
                db_num = float(db_val.replace('$', '').replace(',', ''))
                mt5_num = s['profit']
                if abs(db_num - mt5_num) < 0.1:
                    already_filled.append((s, idx, db_val))
                else:
                    mismatched.append((s, idx, db_val, mt5_num))
            except:
                already_filled.append((s, idx, db_val))
        else:
            # Column is empty - this is a recovery opportunity!
            missing_from_db.append(s)

print(f"\nMT5 sessions matched & filled in DB: {len(already_filled)}")
print(f"MT5 sessions with MISMATCHED values: {len(mismatched)}")
print(f"MT5 sessions with EMPTY DB column (recovery opportunities): {len(missing_from_db)}")

if mismatched:
    print(f"\n--- MISMATCHED VALUES ---")
    for s, idx, db_val, mt5_val in mismatched[:30]:
        ts = s['first_time'].strftime('%Y-%m-%d') if s['first_time'] else '?'
        print(f"  Row {idx}: {s['prefix']}...{s['acct_part']} {s['phase']} | DB={db_val} MT5=${mt5_val:.2f} | {ts}")

if missing_from_db:
    print(f"\n--- EMPTY IN DB (could fill from MT5) ---")
    for s in missing_from_db[:50]:
        ts = s['first_time'].strftime('%Y-%m-%d') if s['first_time'] else '?'
        print(f"  {ts} | {s['prefix']}...{s['acct_part']} | {s['phase']} -> {phase_to_col[s['phase']]} | profit=${s['profit']:.2f}")

# ============================================================
# Step 9: Focus on our 5 target accounts
# ============================================================
print(f"\n{'='*100}")
print(f"TARGET ACCOUNTS: CH2 SESSIONS IN MT5 REPORT")
print(f"{'='*100}")

target_trails = {'5509', '5151', '2421', '93002', '37253',
                 '10905509', '51535151', '92712421'}

for s in session_results:
    acct = s['acct_part']
    for t in target_trails:
        if acct.endswith(t) or t.endswith(acct):
            ts = s['first_time'].strftime('%Y-%m-%d %H:%M') if s['first_time'] else '?'
            print(f"  {ts} | {s['prefix']}...{s['acct_part']} | {s['phase']} | profit=${s['profit']:.2f}")

# ============================================================
# Step 10: Summary stats
# ============================================================
print(f"\n{'='*100}")
print(f"OVERALL MT5 REPORT SUMMARY")
print(f"{'='*100}")

total_trades = len([d for d in parsed_deals if d['symbol'] and d['direction'] == 'in'])
total_sessions = len(session_results)
date_range = f"{session_results[0]['first_time'].strftime('%Y-%m-%d')} to {session_results[-1]['first_time'].strftime('%Y-%m-%d')}" if session_results else 'N/A'

print(f"  Total opening trades: {total_trades}")
print(f"  Total sessions (account+phase groups): {total_sessions}")
print(f"  Date range: {date_range}")
print(f"  Sessions by phase:")
for phase in ['CH1', 'CH2', 'CH3', 'FD1', 'FD2', 'FD3']:
    count = sum(1 for s in session_results if s['phase'] == phase)
    total = sum(s['profit'] for s in session_results if s['phase'] == phase)
    print(f"    {phase}: {count} sessions, total profit=${total:.2f}")

db.close()
