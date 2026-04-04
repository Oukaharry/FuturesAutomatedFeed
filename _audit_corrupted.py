"""Deep audit Part 2: Find corrupted accounts that look wrong.
Also re-examine logs with broader patterns including FINAL DATA blocks."""
import json, sqlite3, re, os, glob
from collections import defaultdict, Counter

DB_PATH = 'dashboard/dashboard.db'
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

# Known valid prefixes by firm
FIRM_PREFIX = {
    'My Funded Futures': ['MFFU'],
    'FundedNext': ['FNFT'],
    'Tradeify': ['TDFY'],
    'Topstep': ['V2'],
    'TradeDay': ['TDF', 'ELTD'],
    'Funding Ticks': ['FTKS'],
    'Alpha Futures': ['AFAD'],
    'Apex Trader Funding': ['APEX'],
}

# Expected account format: PREFIX-XXXXX (5 or fewer chars after dash, possibly alphanumeric)
VALID_ACCOUNT_RE = re.compile(r'^[A-Z]{2,4}-[A-Z0-9]{3,6}$')

print('=== Corrupted Account # values ===')
corrupted_acct = []
for i, ev in enumerate(evals):
    for field in ['Account #', 'Account #.1']:
        val = (ev.get(field) or '').strip()
        if not val:
            continue
        firm = (ev.get('Prop Firm') or '').strip()
        
        # Check for corrupted patterns
        issues = []
        
        # 1. FTPROPLUS pattern (Funding Ticks junk)
        if 'FTPROPLUS' in val:
            issues.append('FTPROPLUS corrupted')
        
        # 2. FNFTCHCHRISREAM pattern
        if 'CHCHRISREAM' in val:
            issues.append('CHCHRISREAM corrupted')
        
        # 3. MFFUEV/MFFUSF pattern
        if re.match(r'.*MFFU(EV|SF)(STP|SCL|FLX|CRFLX)', val):
            issues.append('MFFU concatenation')
        
        # 4. TDFYSL pattern
        if 'TDFYSL' in val:
            issues.append('TDFYSL corrupted')
        
        # 5. 50KTC-V2 pattern  
        if '50KTC-V2' in val:
            issues.append('50KTC-V2 corrupted')
        
        # 6. EXPRESS-V2 pattern
        if 'EXPRESS-V2' in val:
            issues.append('EXPRESS-V2 format')
        
        # 7. ELTDEN pattern (TradeDay raw)
        if val.startswith('ELTD') and len(val) > 12:
            issues.append('ELTDEN raw format')
        
        # 8. AFADVEV/AFADQAS pattern
        if re.match(r'AFAD-(AFAD|QAS)', val):
            issues.append('AFAD concatenation')
            
        # 9. FNFT-FNFT pattern
        if val.startswith('FNFT-FNFT'):
            issues.append('FNFT double prefix')
            
        # 10. MFFU-MFFU pattern
        if val.startswith('MFFU-MFFU'):
            issues.append('MFFU double prefix')
        
        # 11. TDFY-FTDF pattern
        if val.startswith('TDFY-FTDF'):
            issues.append('TDFY-FTDF corrupted')
        
        # 12. TDFY-MFFU pattern (wrong prefix in value)
        if val.startswith('TDFY-MFFU'):
            issues.append('TDFY-MFFU cross-prefix')
        
        # 13. Just raw numbers (Funding Ticks)
        if re.match(r'^\d{6,}$', val) and firm != 'Funding Ticks':
            issues.append(f'Raw number on {firm}')
        
        # 14. Prefix doesn't match firm
        if firm in FIRM_PREFIX and '-' in val:
            prefix = val.split('-')[0]
            if prefix not in FIRM_PREFIX[firm]:
                # Check if it's a sub-pattern
                if not any(val.startswith(p + '-') for p in FIRM_PREFIX[firm]):
                    issues.append(f'Prefix {prefix} wrong for {firm}')
        
        if issues:
            corrupted_acct.append((i, field, val, firm, issues))
            
print(f'Total corrupted values: {len(corrupted_acct)}')
for i, field, val, firm, issues in corrupted_acct:
    print(f'  Row {i:>3} {field:<12}: {val:<40} Firm={firm:<22} Issues={", ".join(issues)}')

# Count by issue type
issue_counts = Counter()
for _, _, _, _, issues in corrupted_acct:
    for issue in issues:
        issue_counts[issue] += 1
print(f'\nIssue counts:')
for issue, c in issue_counts.most_common():
    print(f'  {issue}: {c}')
