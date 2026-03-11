"""Quick test: simulate matching logic for V2-1128 with the fix"""
import sqlite3, json, re

conn = sqlite3.connect('dashboard/dashboard.db')
row = conn.execute("SELECT evaluations FROM clients_data WHERE client_id=?", ('Chris',)).fetchone()
evs = json.loads(row[0])

# Simulating: comment = V2-...1128_CH2
# full_comment_info = ('V2-', '1128', 'CH', 2)
acc_num = '1128'
comment_prefix = 'V2'  # from full_comment_info[0].rstrip('-').upper()

s_acc_raw = acc_num.upper()
s_search = s_acc_raw  # no hyphen, so stays as-is

print(f"Searching for: acc_num={acc_num}, comment_prefix={comment_prefix}, s_search={s_search}")
print()

for i, e in enumerate(evs):
    ac1_orig = str(e.get('Account #', '')).strip().upper()
    ac2_orig = str(e.get('Account #.1', '')).strip().upper()
    
    # NEW: Strip Top Step prefixes
    ac1 = ac1_orig
    ac2 = ac2_orig
    for pfx in ['50KTC-', 'EXPRESS-']:
        if ac1.startswith(pfx): ac1 = ac1[len(pfx):]
        if ac2.startswith(pfx): ac2 = ac2[len(pfx):]
    
    is_match = False
    s = s_search
    
    if ac1:
        if s == ac1: is_match = True
        elif s.endswith(ac1) or ac1.endswith(s): is_match = True
        elif len(s) >= 4 and s in ac1: is_match = True
    if not is_match and ac2:
        if s == ac2: is_match = True
        elif s.endswith(ac2) or ac2.endswith(s): is_match = True
        elif len(s) >= 4 and s in ac2: is_match = True
    
    if not is_match:
        continue
    
    # STRICT PREFIX CHECK with comment_prefix
    prefix_part = comment_prefix
    pf_val = str(e.get('Prop Firm', '')).upper()
    
    mapping = {
        'MFFU': ['MYFUNDED', 'MFFU', 'MY FUNDED'],
        'V2': ['TOPSTEP', 'TOP STEP', 'V2'],
        'FNFT': ['FUNDEDNEXT', 'FUNDED NEXT', 'FNFT'],
        'TDFY': ['TRADEIFY', 'TDFY'],
        'ELTD': ['TRADEDAY', 'ELTD'],
        'TDF': ['TRADEDAY', 'TDF', 'TRADEIFY'],
        'FTDF': ['TRADEDAY', 'TDF', 'TRADEIFY']
    }
    
    rejected = False
    if prefix_part and pf_val and prefix_part not in pf_val and pf_val not in prefix_part:
        if prefix_part in mapping:
            valid_keywords = mapping[prefix_part]
            if not any(k in pf_val for k in valid_keywords):
                rejected = True
    
    status = "REJECTED by prefix check" if rejected else "ACCEPTED"
    stripped = f" (stripped: {ac1})" if ac1 != ac1_orig else ""
    print(f"  idx={i} row={i+2} firm={e.get('Prop Firm','?')} ac1={ac1_orig}{stripped} -> {status}")
