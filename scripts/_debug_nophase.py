"""Debug: show all sheet data (eval + funded + farming) for problematic no-phase accounts,
and show individual MT5 trades for those accounts."""
import re, csv, io
from collections import defaultdict
from bs4 import BeautifulSoup
import requests

def parse_currency(val):
    if not val or not val.strip(): return 0.0
    s = val.replace('\xa0',' ').strip()
    s = re.sub(r'[−–]', '-', s)
    s = re.sub(r'-\s+', '-', s)
    s = s.replace(' ', '')
    try: return float(s)
    except: return 0.0

def parse_sheet_currency(val):
    if not val or not val.strip(): return None
    s = val.strip()
    if s.lower() in ('pass','farming','n/a','-','','fail','breach'): return None
    neg = '(' in s or s.startswith('-')
    s = re.sub(r'[^0-9.]', '', s)
    if not s: return None
    try:
        v = float(s)
        return -v if neg else v
    except: return None

# ── MT5 individual trades for no-phase accounts ──
html_path = r'C:\Users\harry\OneDrive\Documents\ReportHistory-3066167.html'
print("Parsing MT5...")
with open(html_path, 'r', encoding='utf-16') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')
table = soup.find('table')
rows = table.find_all('tr')

in_pos = False; pos_header = []; positions = []
for row in rows:
    tds = row.find_all(['td','th'])
    if not tds: continue
    first = tds[0]
    if first.get('colspan'):
        text = first.get_text(strip=True)
        if text == 'Positions': in_pos = True; continue
        elif text in ('Orders','Deals','Balance:','Credit Facility:'): in_pos = False; continue
    if not in_pos: continue
    bold_count = sum(1 for td in tds if td.find('b'))
    if not pos_header and bold_count >= len(tds)//2 and bold_count >= 3:
        for td in tds:
            if 'hidden' not in td.get('class',[]): pos_header.append(td.get_text(strip=True))
        continue
    visible = []; hidden_val = None
    for td in tds:
        if 'hidden' in td.get('class',[]): hidden_val = td.get_text(strip=True); continue
        visible.append(td.get_text(strip=True))
    if len(visible) < 5: continue
    d = {}
    for i,h in enumerate(pos_header):
        if i < len(visible): d[h.lower()] = visible[i]
    pos_id = d.get('position','')
    if not pos_id or pos_id.lower()=='total': continue
    profit = parse_currency(d.get('profit',''))
    swap = parse_currency(d.get('swap',''))
    commission = parse_currency(d.get('commission',''))
    positions.append({
        'ref': hidden_val or '',
        'symbol': d.get('symbol',''),
        'time': d.get('time',''),
        'type': d.get('type',''),
        'volume': d.get('volume',''),
        'profit': profit, 'swap': swap, 'commission': commission,
        'net': round(profit + swap + commission, 2)
    })

# Show trades for specific no-phase accounts
targets = ['90013','90015','90020','90037','90038','90124','90125']
for t in targets:
    trades = [p for p in positions if t in p['ref'] and '...' in p['ref']]
    if not trades: continue
    # Group by ref
    by_ref = defaultdict(list)
    for tr in trades:
        by_ref[tr['ref']].append(tr)
    for ref, trs in sorted(by_ref.items()):
        total = round(sum(tr['net'] for tr in trs), 2)
        print(f"\n  MT5 Account: {ref}  ({len(trs)} trades, total net={total:.2f})")
        for tr in trs:
            print(f"    {tr['time']:<20} {tr['symbol']:<12} {tr['type']:<6} vol={tr['volume']:<6} profit={tr['profit']:>8.2f} swap={tr['swap']:>6.2f} comm={tr['commission']:>6.2f} net={tr['net']:>8.2f}")

# ── Sheet data for these accounts ──
print("\n\nFetching Sheet...")
sheet_id = '18lcf74au4ez7pdPhGz4qyRdLoELMGeNEzgysJgGrg2U'
url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
resp = requests.get(url, timeout=30)
sheet_rows = list(csv.reader(io.StringIO(resp.text)))

for row_idx in range(2, len(sheet_rows)):
    row = sheet_rows[row_idx]
    if len(row) < 15: continue
    acct1 = str(row[8]).strip()   # eval Account #
    acct2 = str(row[15]).strip()  # funded Account #
    for t in targets:
        if t in acct1 or t in acct2:
            print(f"\nSheet Row {row_idx+1}: Prop={row[0]}")
            print(f"  Eval Account #: {acct1}")
            print(f"  Funded Account #: {acct2}")
            # Eval section
            for c in range(9, 14):
                if c < len(row):
                    v = parse_sheet_currency(str(row[c]).strip())
                    if v is not None: print(f"  Eval Hedge Result {c-8}: {v:.2f}")
            if 14 < len(row):
                v = parse_sheet_currency(str(row[14]).strip())
                if v is not None: print(f"  Eval Hedge Net: {v:.2f}")
            # Funded section
            for c in range(20, 27):
                if c < len(row):
                    v = parse_sheet_currency(str(row[c]).strip())
                    if v is not None: print(f"  Funded Hedge Result {c-19}: {v:.2f}")
            if 27 < len(row):
                v = parse_sheet_currency(str(row[27]).strip())
                if v is not None: print(f"  Funded Hedge Net: {v:.2f}")
            # Farming net
            if 36 < len(row):
                v = parse_sheet_currency(str(row[36]).strip())
                if v is not None: print(f"  Farming Net: {v:.2f}")
            # Hedge Day values
            hdays = []
            for c in range(38, min(len(row), 105), 2):
                v = parse_sheet_currency(str(row[c]).strip())
                if v is not None: hdays.append((f"Day{(c-36)//2}", v))
            if hdays:
                print(f"  Hedge Days ({len(hdays)} days): total={sum(v for _,v in hdays):.2f}")
                for name, v in hdays:
                    print(f"    {name}: {v:.2f}")
            break
