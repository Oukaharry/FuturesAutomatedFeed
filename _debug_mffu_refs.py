"""Check what MT5 entries exist for MFFUSFSCL accounts with no phase info."""
import re
from collections import defaultdict
from bs4 import BeautifulSoup

html_path = r'C:\Users\harry\OneDrive\Documents\ReportHistory-3066167.html'
with open(html_path, 'r', encoding='utf-16') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')
table = soup.find('table')
rows = table.find_all('tr')

in_pos = False
pos_header = []

def parse_currency(val):
    if not val or not val.strip(): return 0.0
    s = val.replace('\xa0',' ').strip()
    s = re.sub(r'[−–]', '-', s)
    s = re.sub(r'-\s+', '-', s)
    s = s.replace(' ', '')
    try: return float(s)
    except: return 0.0

positions = []
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
    positions.append({'ref': hidden_val or '', 'net': round(profit + swap + commission, 2)})

# Group by ref
acct_pnl = defaultdict(lambda: {'net':0.0, 'count':0})
for p in positions:
    key = p['ref'] or 'UNKNOWN'
    acct_pnl[key]['net'] += p['net']
    acct_pnl[key]['count'] += 1
for k in acct_pnl:
    acct_pnl[k]['net'] = round(acct_pnl[k]['net'],2)

# Show all entries for specific account suffixes
targets = ['90013','90020','90124','90125','90126','90137','90138']
for t in targets:
    matches = [(k,v) for k,v in acct_pnl.items() if t in k]
    print(f"\nMT5 entries matching *{t}*:")
    for k,v in sorted(matches):
        print(f"  {k:<40} trades={v['count']:>3}  net={v['net']:>10.2f}")
