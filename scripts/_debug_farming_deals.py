"""Debug: Show ALL farming (FA) deals from stored MT5 data for Chris.
Checks whether we're truly picking the latest vs earliest."""

import sys, os, json, re, datetime, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard', 'dashboard.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def parse_comment(comment):
    """Extract phase and number from deal comment."""
    if not comment:
        return None, None
    c = str(comment).strip()
    # Match patterns like V2-1128_CH1, FNFT-86721_FA, TDFY-83573_CH2
    m = re.search(r'_(CH|FD|DD|FA)(\d*)', c, re.IGNORECASE)
    if m:
        phase = m.group(1).upper()
        num = int(m.group(2)) if m.group(2) else 1
        return phase, num
    return None, None

def extract_account(comment):
    """Extract account number from deal comment."""
    if not comment:
        return None
    c = str(comment).strip()
    # Try FNFT-12345_FA pattern → get 12345
    m = re.search(r'(\d+)_(CH|FD|DD|FA)', c, re.IGNORECASE)
    if m:
        return m.group(1)
    # Try V2-1234_FA
    m = re.search(r'V2-(\d+)_(CH|FD|DD|FA)', c, re.IGNORECASE)
    if m:
        return m.group(1)
    return None

conn = get_db()
row = conn.execute("SELECT deals, evaluations FROM clients_data WHERE client_id = ?", ('Chris',)).fetchone()
if not row:
    print("No data for Chris")
    sys.exit(1)

deals = json.loads(row[0] or '[]')
evaluations = json.loads(row[1] or '[]')

print(f"Total deals in stored data: {len(deals)}")
print()

# Find ALL FA deals
fa_deals = []
for d in deals:
    comment = d.get('comment', '')
    phase, num = parse_comment(comment)
    if phase == 'FA':
        # Get timestamp
        ts = d.get('time', 0)
        if isinstance(ts, str):
            try:
                ts = datetime.datetime.fromisoformat(ts).timestamp()
            except:
                ts = 0
        ts = float(ts)
        
        profit = float(d.get('profit', 0)) + float(d.get('commission', 0)) + float(d.get('swap', 0))
        date_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d') if ts > 0 else 'UNKNOWN'
        time_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S') if ts > 0 else 'UNKNOWN'
        
        acc = extract_account(comment)
        fa_deals.append({
            'comment': comment,
            'account': acc,
            'timestamp': ts,
            'date': date_str,
            'time_str': time_str,
            'profit': profit,
            'type': d.get('type', ''),
            'position_id': d.get('position_id', 0)
        })

print(f"Total FA deals found: {len(fa_deals)}")
print()

# Group by account
from collections import defaultdict
by_account = defaultdict(list)
for fd in fa_deals:
    acc = fd['account'] or 'UNKNOWN'
    by_account[acc].append(fd)

# For each account, show ALL deals sorted by date
for acc in sorted(by_account.keys()):
    deals_list = sorted(by_account[acc], key=lambda x: x['timestamp'])
    
    # Group by date for daily totals
    daily = defaultdict(float)
    daily_count = defaultdict(int)
    for fd in deals_list:
        daily[fd['date']] += fd['profit']
        daily_count[fd['date']] += 1
    
    sorted_dates = sorted(daily.keys())
    total_days = len(sorted_dates)
    earliest_date = sorted_dates[0]
    latest_date = sorted_dates[-1]
    
    print(f"{'='*70}")
    print(f"Account: {acc} | {len(deals_list)} deals | {total_days} farming days")
    print(f"  Date range: {earliest_date} → {latest_date}")
    print()
    
    for i, d in enumerate(sorted_dates):
        slot = i + 1
        marker = " ← PUSHED (last)" if d == latest_date else ""
        print(f"  Day {slot:2d} ({d}): ${daily[d]:>10.2f}  ({daily_count[d]} deals){marker}")
    
    print(f"\n  Pre-compute would write: Hedge Day {total_days} = ${daily[latest_date]:.2f} (date: {latest_date})")
    print()

# Also show what's currently in the evaluations for these accounts' Hedge Day columns
print("\n" + "="*70)
print("CURRENT HEDGE DAY VALUES IN DB EVALUATIONS (farming rows)")
print("="*70)

# Find evals that have any Hedge Day values
for idx, ev in enumerate(evaluations):
    row_num = idx + 2  # Sheet row
    has_farming = False
    farm_vals = {}
    for day in range(1, 35):
        col = f'Hedge Day {day}'
        val = ev.get(col)
        if val and str(val).strip() and str(val).strip() != '$0.00' and str(val).strip() != '0':
            has_farming = True
            farm_vals[col] = val
    
    if has_farming:
        firm = ev.get('Prop Firm', '?')
        acct1 = ev.get('Account #', '')
        acct2 = ev.get('Account #.1', '')
        status_p1 = ev.get('Status P1', '')
        status_f = ev.get('Status', '') or ev.get('Status Funded', '')
        print(f"\nRow {row_num} (idx {idx}): {firm} | Acct={acct1} Acct.1={acct2}")
        print(f"  Status: P1={status_p1}, F={status_f}")
        for col, val in sorted(farm_vals.items(), key=lambda x: int(re.search(r'\d+', x[0]).group())):
            date_key = f'_{col} Date'
            date_val = ev.get(date_key, '')
            print(f"  {col:>15s} = {val:>12s}  (date: {date_val})")
