"""Check if same accounts are being double-counted"""
import pandas as pd
import requests
from io import StringIO

sheet_id = "1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E"
url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv'

r = requests.get(url)
df = pd.read_csv(StringIO(r.text), header=1)

# Columns: H = Status P1 (index 7), T = Status (index 19)
status_p1_col = df.columns[7]
status_col = df.columns[19]
fee_col = df.columns[3]  # D = Fee

print(f"Column H (7): {status_p1_col}")
print(f"Column T (19): {status_col}")  
print(f"Column D (3): {fee_col}")

# Count rows in each category
p1_fail = df[df[status_p1_col] == 'Fail']
status_fail = df[df[status_col] == 'Fail']
status_completed = df[df[status_col] == 'Completed']

print(f"\nRows where P1='Fail': {len(p1_fail)}")
print(f"Rows where Status='Fail': {len(status_fail)}")
print(f"Rows where Status='Completed': {len(status_completed)}")

# Check for overlap: accounts with BOTH P1=Fail AND (Status=Fail or Status=Completed)
p1_fail_and_funded_ended = df[(df[status_p1_col] == 'Fail') & (df[status_col].isin(['Fail', 'Completed']))]
print(f"\nRows with BOTH P1='Fail' AND (Status='Fail' or 'Completed'): {len(p1_fail_and_funded_ended)}")

# Calculate fees correctly with OR logic (no double count)
fee_p1_fail = pd.to_numeric(p1_fail[fee_col], errors='coerce').fillna(0).sum()
fee_status_fail = pd.to_numeric(status_fail[fee_col], errors='coerce').fillna(0).sum()
fee_status_completed = pd.to_numeric(status_completed[fee_col], errors='coerce').fillna(0).sum()

print(f"\nIndividual SUMIF results:")
print(f"  SUMIF(Fee, P1='Fail'): ${fee_p1_fail:.2f}")
print(f"  SUMIF(Fee, Status='Fail'): ${fee_status_fail:.2f}")
print(f"  SUMIF(Fee, Status='Completed'): ${fee_status_completed:.2f}")
print(f"  Simple sum: ${fee_p1_fail + fee_status_fail + fee_status_completed:.2f}")

# But with OR logic (unique rows), we should use:
ended_rows = df[(df[status_p1_col] == 'Fail') | (df[status_col] == 'Fail') | (df[status_col] == 'Completed')]
fee_or_logic = pd.to_numeric(ended_rows[fee_col], errors='coerce').fillna(0).sum()
print(f"  OR-logic (unique rows): ${fee_or_logic:.2f}")

print(f"\nExpected Challenge Fees Completed: $35,528.18")
