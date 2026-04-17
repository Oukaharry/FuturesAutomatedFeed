"""
Parse Chris Ream's full MT5 report (ReportHistory-3063841.html) v2.
Uses the Positions section which has complete trade data: 
  - Hidden td with account comment + phase suffix
  - Open/close times, profit per position
Groups by (account, phase) and sums profits to get hedge results.
Compares with DB to find missing/mismatched data.
"""
import re, json, sqlite3
from html.parser import HTMLParser
from datetime import datetime
from collections import defaultdict

HTML_FILE = 'trader_companion/ReportHistory-3063841.html'

# ============================================================
# Step 1: Parse the HTML positions section
# ============================================================
# Position row structure:
# <td>open_time</td> <td>position_id</td> <td>symbol</td> <td>type</td>
# <td class="hidden" colspan="8">COMMENT</td>
# <td class="">volume</td> <td class="">open_price</td> <td class="">SL</td> <td class="">TP</td>
# <td class="">close_time</td> <td class="">close_price</td> <td class="">commission</td> <td class="">swap</td>
# <td colspan="2">profit</td>

print("Parsing HTML report...")
with open(HTML_FILE, 'rb') as f:
    raw = f.read()
if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
    html_content = raw.decode('utf-16')
else:
    html_content = raw.decode('utf-8', errors='replace')

# Use regex to extract position rows directly
# Each position row has a hidden td with the comment
POS_RE = re.compile(
    r'<tr\s+bgcolor="[^"]*"\s+align="right">\s*'
    r'<td>(\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2}:\d{2})</td>\s*'  # open time
    r'<td>(\d+)</td>\s*'  # position id
    r'<td>(\w*)</td>\s*'  # symbol
    r'<td>(\w+)</td>\s*'  # type (buy/sell)
    r'<td\s+class="hidden"\s+colspan="\d+">([^<]*)</td>\s*'  # HIDDEN COMMENT
    r'<td\s+class="">([^<]*)</td>\s*'  # volume
    r'<td\s+class="">([^<]*)</td>\s*'  # open price
    r'<td\s+class="">([^<]*)</td>\s*'  # SL
    r'<td\s+class="">([^<]*)</td>\s*'  # TP
    r'<td\s+class="">([^<]*)</td>\s*'  # close time
    r'<td\s+class="">([^<]*)</td>\s*'  # close price
    r'<td\s+class="">([^<]*)</td>\s*'  # commission
    r'<td\s+class="">([^<]*)</td>\s*'  # swap
    r'<td\s+colspan="\d+">([^<]*)</td>',  # profit
    re.DOTALL
)

positions = []
for m in POS_RE.finditer(html_content):
    open_time_str = m.group(1)
    pos_id = m.group(2)
    symbol = m.group(3)
    trade_type = m.group(4)
    comment = m.group(5).strip()
    volume = m.group(6)
    close_time_str = m.group(10)
    profit_str = m.group(14).replace('\xa0', '').replace(' ', '').strip()
    
    try:
        open_time = datetime.strptime(open_time_str, '%Y.%m.%d %H:%M:%S')
    except:
        open_time = None
    
    try:
        profit = float(profit_str)
    except:
        profit = 0.0
    
    positions.append({
        'open_time': open_time,
        'pos_id': pos_id,
        'symbol': symbol,
        'type': trade_type,
        'comment': comment,
        'volume': volume,
        'profit': profit,
        'close_time_str': close_time_str,
    })

print(f"Parsed {len(positions)} positions from Positions section")

# ============================================================
# Step 2: Parse account and phase from comments
# ============================================================
# Comment patterns:
# "276391383" - early trades, just a number (no account info - pre-automation)
# "MFFU...80217_CH2" -> prefix=MFFU, acct=80217, phase=CH2
# "V2-...8738_FD1" -> prefix=V2-, acct=8738, phase=FD1
# "TDFY...92031_CH2" -> prefix=TDFY, acct=92031, phase=CH2
# "FNFT...93002_CH1" -> prefix=FNFT, acct=93002, phase=CH1
# "V2-...2763_CH1" -> prefix=V2-, acct=2763, phase=CH1
# No phase suffix -> CH1 (default)

COMMENT_PARSE_RE = re.compile(
    r'^([A-Z0-9\-]+?)\.\.\.(\w+?)(?:_(CH\d|FD\d))?$'
)

for p in positions:
    comment = p['comment']
    m = COMMENT_PARSE_RE.match(comment)
    if m:
        p['prefix'] = m.group(1)
        p['acct_part'] = m.group(2)
        p['phase'] = m.group(3) if m.group(3) else 'CH1'
    elif re.match(r'^\d+$', comment):
        # Pure numeric - early trades without account tagging
        p['prefix'] = ''
        p['acct_part'] = comment
        p['phase'] = 'UNKNOWN'
    else:
        p['prefix'] = ''
        p['acct_part'] = comment
        p['phase'] = 'UNKNOWN'

# Filter to only positions with known accounts
tagged = [p for p in positions if p['phase'] != 'UNKNOWN']
untagged = [p for p in positions if p['phase'] == 'UNKNOWN']
print(f"Tagged positions (with account+phase): {len(tagged)}")
print(f"Untagged positions (early/unknown): {len(untagged)}")

# ============================================================
# Step 3: Group by (prefix, account, phase) and sum profits
# ============================================================
# Each account+phase combo = one hedge session with multiple legs
# The hedge result = sum of all position profits for that session

session_groups = defaultdict(list)
for p in tagged:
    key = (p['prefix'], p['acct_part'], p['phase'])
    session_groups[key].append(p)

print(f"\nUnique sessions (account+phase combos): {len(session_groups)}")

session_results = []
for (prefix, acct, phase), trades in session_groups.items():
    total_profit = sum(t['profit'] for t in trades)
    first_time = min(t['open_time'] for t in trades if t['open_time'])
    
    session_results.append({
        'prefix': prefix,
        'acct_part': acct,
        'phase': phase,
        'profit': round(total_profit, 2),
        'trade_count': len(trades),
        'first_time': first_time,
    })

session_results.sort(key=lambda x: x['first_time'] or datetime.min)

# Phase distribution
phase_counts = defaultdict(int)
phase_profits = defaultdict(float)
for s in session_results:
    phase_counts[s['phase']] += 1
    phase_profits[s['phase']] += s['profit']

print("\nPhase distribution:")
for phase in ['CH1', 'CH2', 'CH3', 'FD0', 'FD1', 'FD2', 'FD3']:
    if phase in phase_counts:
        print(f"  {phase}: {phase_counts[phase]} sessions, total profit=${phase_profits[phase]:.2f}")

# ============================================================
# Step 4: Map phases to DB columns
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
# Step 5: Load DB evals and build matching index
# ============================================================
db = sqlite3.connect('dashboard/dashboard.db')
row = db.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'").fetchone()
evals = json.loads(row[0])

# Build lookup: trailing digits of account -> list of (eval_index, eval_dict)
# We need to match MT5 comment endings (like "80217") to DB Account # (like "MFFUEVSCL372280217")
def extract_trail(acct_str, lengths=[4,5,6]):
    digits = re.sub(r'[^0-9]', '', str(acct_str))
    trails = set()
    for L in lengths:
        if len(digits) >= L:
            trails.add(digits[-L:])
    return trails

# Index by trailing digits
db_trail_index = defaultdict(list)
for i, ev in enumerate(evals):
    acct = str(ev.get('Account #', '')).strip()
    acct1 = str(ev.get('Account #.1', '')).strip()
    firm = str(ev.get('Prop Firm', '')).strip().upper()
    
    for a in [acct, acct1]:
        if a:
            for trail in extract_trail(a):
                db_trail_index[trail].append(i)

# Also build prefix->firm mapping for disambiguation
PREFIX_FIRM = {
    'MFFU': ['MY FUNDED FUTURES', 'MFFU'],
    'FTPR': ['FUNDEDNEXT', 'FUNDED NEXT', 'FTPROPLUS', 'FNFT'],
    'V2-': ['TOPSTEP', 'TOP STEP'],
    'V2': ['TOPSTEP', 'TOP STEP'],
    'TDFY': ['TRADEIFY', 'TDFY', 'TRADEDAY', 'TRADE DAY'],
    'FNFT': ['FUNDEDNEXT', 'FUNDED NEXT', 'FNFT'],
    'AFAD': ['ALPHA FUTURES', 'ALPHA', 'AFAD'],
    'ELTD': ['FUNDEDNEXT', 'FUNDED NEXT'],
    'FTDF': ['FUNDING TICKS', 'FUNDINGTICKETS'],
}

def firm_matches_prefix(firm_str, prefix):
    firm_up = firm_str.upper()
    keywords = PREFIX_FIRM.get(prefix, [])
    if not keywords:
        return True  # can't validate, accept
    return any(k in firm_up for k in keywords)

# ============================================================
# Step 6: Match MT5 sessions to DB evals
# ============================================================
print(f"\n{'='*100}")
print("MATCHING MT5 SESSIONS TO DATABASE")
print(f"{'='*100}")

matched = []
mismatched = []
missing_in_db = []  # MT5 has data but DB column is empty
no_match = []  # Can't find the account in DB at all

for s in session_results:
    col = phase_to_col.get(s['phase'])
    if not col:
        continue
    
    acct_trail = re.sub(r'[^0-9]', '', s['acct_part'])
    if not acct_trail:
        no_match.append(s)
        continue
    
    # Find candidate evals
    candidate_indices = set()
    for L in [6, 5, 4]:
        if len(acct_trail) >= L:
            trail = acct_trail[-L:]
            if trail in db_trail_index:
                candidate_indices.update(db_trail_index[trail])
    
    if not candidate_indices:
        no_match.append(s)
        continue
    
    # Filter by prefix-firm match
    filtered = []
    for idx in candidate_indices:
        ev = evals[idx]
        firm = str(ev.get('Prop Firm', '')).strip()
        if firm_matches_prefix(firm, s['prefix']):
            filtered.append(idx)
    
    if not filtered:
        # Relax: use any candidate
        filtered = list(candidate_indices)
    
    # Check if any candidate has this column filled vs empty
    best_match = None
    for idx in filtered:
        ev = evals[idx]
        db_val = str(ev.get(col, '')).strip()
        if db_val and db_val != 'nan':
            best_match = ('filled', idx, db_val)
            break
    
    if best_match is None:
        # Column is empty for all candidates - recovery opportunity
        best_match = ('empty', filtered[0], '')
    
    status, idx, db_val = best_match
    
    if status == 'filled':
        # Check if values match
        try:
            db_num = float(db_val.replace('$', '').replace(',', ''))
            mt5_num = s['profit']
            if abs(db_num - mt5_num) < 0.5:
                matched.append((s, idx, db_val))
            else:
                mismatched.append((s, idx, db_val, mt5_num))
        except:
            matched.append((s, idx, db_val))
    else:
        missing_in_db.append((s, idx))

print(f"\n  Matched (values agree): {len(matched)}")
print(f"  Mismatched (different values): {len(mismatched)}")
print(f"  Empty in DB (recovery opportunity): {len(missing_in_db)}")
print(f"  No DB match found at all: {len(no_match)}")

# ============================================================
# Step 7: Show mismatches
# ============================================================
if mismatched:
    print(f"\n{'='*100}")
    print(f"MISMATCHED VALUES ({len(mismatched)})")
    print(f"{'='*100}")
    for s, idx, db_val, mt5_val in mismatched[:40]:
        ev = evals[idx]
        acct = str(ev.get('Account #', ''))
        firm = str(ev.get('Prop Firm', ''))
        ts = s['first_time'].strftime('%Y-%m-%d') if s['first_time'] else '?'
        col = phase_to_col[s['phase']]
        print(f"  Row {idx:>3} | {firm:<20} | {acct:<30} | {s['prefix']}...{s['acct_part']} {s['phase']}")
        print(f"         DB {col}={db_val}  vs  MT5=${mt5_val:.2f}  | {ts}")

# ============================================================
# Step 8: Show recovery opportunities (empty in DB)
# ============================================================
if missing_in_db:
    print(f"\n{'='*100}")
    print(f"EMPTY IN DB - CAN FILL FROM MT5 ({len(missing_in_db)})")
    print(f"{'='*100}")
    
    by_phase = defaultdict(list)
    for s, idx in missing_in_db:
        by_phase[s['phase']].append((s, idx))
    
    for phase in ['CH1', 'CH2', 'CH3', 'FD1', 'FD2', 'FD3']:
        items = by_phase.get(phase, [])
        if items:
            col = phase_to_col[phase]
            print(f"\n  --- {phase} ({col}) - {len(items)} gaps ---")
            for s, idx in items:
                ev = evals[idx]
                acct = str(ev.get('Account #', ''))
                firm = str(ev.get('Prop Firm', ''))
                ts = s['first_time'].strftime('%Y-%m-%d') if s['first_time'] else '?'
                print(f"    Row {idx:>3} | {firm:<20} | {acct:<30} | MT5=${s['profit']:>10.2f} | {ts}")

# ============================================================
# Step 9: Focus on the 5 target accounts
# ============================================================
print(f"\n{'='*100}")
print("TARGET ACCOUNTS: ALL MT5 SESSIONS")
print(f"{'='*100}")

target_trails = {'5509', '5151', '2421', '93002', '37253',
                 '10905509', '51535151', '92712421'}

for s in session_results:
    acct = s['acct_part']
    acct_digits = re.sub(r'[^0-9]', '', acct)
    found = False
    for t in target_trails:
        if acct_digits.endswith(t) or t.endswith(acct_digits):
            found = True
            break
    if found:
        ts = s['first_time'].strftime('%Y-%m-%d %H:%M') if s['first_time'] else '?'
        col = phase_to_col.get(s['phase'], s['phase'])
        print(f"  {ts} | {s['prefix']}...{s['acct_part']} | {s['phase']} -> {col} | profit=${s['profit']:.2f} | {s['trade_count']} trades")

# ============================================================
# Step 10: Check ALL CH2 sessions
# ============================================================
print(f"\n{'='*100}")
print("ALL CH2 SESSIONS IN MT5 REPORT")
print(f"{'='*100}")

ch2_sessions = [s for s in session_results if s['phase'] == 'CH2']
for s in ch2_sessions:
    ts = s['first_time'].strftime('%Y-%m-%d %H:%M') if s['first_time'] else '?'
    print(f"  {ts} | {s['prefix']}...{s['acct_part']} | profit=${s['profit']:>10.2f} | {s['trade_count']} trades")

# ============================================================
# Step 11: All sessions date range summary
# ============================================================
print(f"\n{'='*100}")
print("MT5 REPORT SUMMARY")
print(f"{'='*100}")
print(f"  Total positions: {len(positions)}")
print(f"  Tagged sessions: {len(session_results)}")
if session_results:
    print(f"  Date range: {session_results[0]['first_time'].strftime('%Y-%m-%d')} to {session_results[-1]['first_time'].strftime('%Y-%m-%d')}")
print(f"\n  Sessions by phase:")
for phase in ['CH1', 'CH2', 'CH3', 'FD0', 'FD1', 'FD2', 'FD3']:
    count = phase_counts.get(phase, 0)
    profit = phase_profits.get(phase, 0)
    if count:
        print(f"    {phase}: {count:>4} sessions, total profit=${profit:>12.2f}")

# Which accounts have sessions for CH1, CH2 both?
ch1_accts = set()
ch2_accts = set()
for s in session_results:
    acct_key = re.sub(r'[^0-9]', '', s['acct_part'])[-5:]
    if s['phase'] == 'CH1':
        ch1_accts.add(acct_key)
    elif s['phase'] == 'CH2':
        ch2_accts.add(acct_key)

print(f"\n  Accounts with CH1 trades: {len(ch1_accts)}")
print(f"  Accounts with CH2 trades: {len(ch2_accts)}")
print(f"  Accounts with CH1 but NO CH2: {len(ch1_accts - ch2_accts)}")
print(f"  Accounts with both CH1+CH2: {len(ch1_accts & ch2_accts)}")

db.close()
