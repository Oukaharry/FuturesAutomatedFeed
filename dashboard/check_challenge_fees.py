"""Check Challenge Fees formula more carefully"""
import pandas as pd
import requests
from io import StringIO

def parse_currency(val):
    if pd.isna(val) or val == '' or val == '-':
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(',', '').replace('$', '').replace(' ', ''))
    except:
        return 0.0

sheet_id = "1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E"
url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv'

r = requests.get(url)
df = pd.read_csv(StringIO(r.text), header=1)

# Columns: D=3 (Fee), H=7 (Status P1), T=19 (Status)
status_p1_col = df.columns[7]
status_col = df.columns[19]
fee_col = df.columns[3]

print("=== Challenge Fees Completed - Different interpretations ===\n")

# Option 1: Fee for P1=Fail PLUS Fee for Status=Fail PLUS Fee for Status=Completed (your current)
p1_fail_rows = df[df[status_p1_col] == 'Fail']
status_fail_rows = df[df[status_col] == 'Fail']
status_completed_rows = df[df[status_col] == 'Completed']

fee_p1_fail = p1_fail_rows[fee_col].apply(parse_currency).sum()
fee_status_fail = status_fail_rows[fee_col].apply(parse_currency).sum()
fee_status_completed = status_completed_rows[fee_col].apply(parse_currency).sum()

print(f"SUMIF(Fee, P1='Fail'): ${fee_p1_fail:.2f} ({len(p1_fail_rows)} rows)")
print(f"SUMIF(Fee, Status='Fail'): ${fee_status_fail:.2f} ({len(status_fail_rows)} rows)")
print(f"SUMIF(Fee, Status='Completed'): ${fee_status_completed:.2f} ({len(status_completed_rows)} rows)")
print(f"\nSum of all three: ${fee_p1_fail + fee_status_fail + fee_status_completed:.2f}")

# Option 2: Using OR logic (unique rows only)
ended_rows = df[(df[status_p1_col] == 'Fail') | (df[status_col] == 'Fail') | (df[status_col] == 'Completed')]
fee_or_logic = ended_rows[fee_col].apply(parse_currency).sum()
print(f"\nOR logic (unique rows): ${fee_or_logic:.2f} ({len(ended_rows)} rows)")

# Option 3: Only Status=Fail or Status=Completed (ignoring P1=Fail)
funded_ended = df[(df[status_col] == 'Fail') | (df[status_col] == 'Completed')]
fee_funded_only = funded_ended[fee_col].apply(parse_currency).sum()
print(f"\nOnly funded ended (Status=Fail OR Completed): ${fee_funded_only:.2f} ({len(funded_ended)} rows)")

# Check overlap between P1=Fail and funded statuses
overlap = df[(df[status_p1_col] == 'Fail') & ((df[status_col] == 'Fail') | (df[status_col] == 'Completed'))]
print(f"\nOverlap (P1=Fail AND (Status=Fail OR Completed)): {len(overlap)} rows")

# What does the actual formula look like in terms of achieving $35,528.18?
print(f"\n=== Target ===")
print(f"Expected: $35,528.18")
