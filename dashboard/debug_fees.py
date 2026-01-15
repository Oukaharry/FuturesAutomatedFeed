"""Debug the fee calculation"""
import pandas as pd
import requests
from io import StringIO

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E/export?format=csv'

def parse_val(val):
    if pd.isna(val) or val == '' or val == '-':
        return 0.0
    try:
        clean = str(val).replace('$', '').replace(',', '').replace(' ', '')
        if clean == '' or clean == '-':
            return 0.0
        return float(clean)
    except:
        return 0.0

response = requests.get(SHEET_URL)
df = pd.read_csv(StringIO(response.text), header=1)
df = df[df['Prop Firm'].notna()]

# Calculate using different logic variants
print("=== FEE CALCULATION VARIANTS ===")

# Variant 1: Current logic (Fee when P1=Fail + Activation when Status=Fail/Completed)
fee_p1_fail = df[df['Status P1'] == 'Fail']['Fee'].apply(parse_val).sum()
act_funded_ended = df[df['Status'].isin(['Fail', 'Completed'])]['Activation Fee'].apply(parse_val).sum()
print(f"V1 (current): Fee(P1=Fail) + Activation(Status=Fail/Comp) = {fee_p1_fail} + {act_funded_ended} = {fee_p1_fail + act_funded_ended}")

# Variant 2: Fee + Activation when Status = Fail/Completed (ignore P1 fail separate)
fee_funded_ended = df[df['Status'].isin(['Fail', 'Completed'])]['Fee'].apply(parse_val).sum()
act_funded_ended = df[df['Status'].isin(['Fail', 'Completed'])]['Activation Fee'].apply(parse_val).sum()
print(f"V2: Fee+Activation when Status=Fail/Comp = {fee_funded_ended} + {act_funded_ended} = {fee_funded_ended + act_funded_ended}")

# Variant 3: SUMIF logic matching sheet exactly
# Fee where P1=Fail (but Status is not Fail/Completed - i.e., didn't reach funded)
p1_fail_only = df[(df['Status P1'] == 'Fail') & (~df['Status'].isin(['Fail', 'Completed']))]
fee_p1_fail_only = p1_fail_only['Fee'].apply(parse_val).sum()
print(f"V3: Fee(P1=Fail AND Status not ended) = {fee_p1_fail_only}")

# Plus Fee+Activation when Status = Fail/Completed
total_v3 = fee_p1_fail_only + fee_funded_ended + act_funded_ended
print(f"V3 total: {fee_p1_fail_only} + {fee_funded_ended} + {act_funded_ended} = {total_v3}")

# Variant 4: Simple - just SUMIF(Fee, P1=Fail) + SUMIF(Fee, Status=Fail) + SUMIF(Fee, Status=Completed)
#            + SUMIF(Activation, Status=Fail) + SUMIF(Activation, Status=Completed)
fee_p1_fail = df[df['Status P1'] == 'Fail']['Fee'].apply(parse_val).sum()
fee_status_fail = df[df['Status'] == 'Fail']['Fee'].apply(parse_val).sum()
fee_status_comp = df[df['Status'] == 'Completed']['Fee'].apply(parse_val).sum()
act_status_fail = df[df['Status'] == 'Fail']['Activation Fee'].apply(parse_val).sum()
act_status_comp = df[df['Status'] == 'Completed']['Activation Fee'].apply(parse_val).sum()

print(f"\nV4 breakdown:")
print(f"  Fee(P1=Fail): {fee_p1_fail}")
print(f"  Fee(Status=Fail): {fee_status_fail}")
print(f"  Fee(Status=Comp): {fee_status_comp}")
print(f"  Activation(Status=Fail): {act_status_fail}")
print(f"  Activation(Status=Comp): {act_status_comp}")
print(f"  Total: {fee_p1_fail + fee_status_fail + fee_status_comp + act_status_fail + act_status_comp}")

# What the sheet expects
print("\n=== EXPECTED (from screenshot) ===")
print("Challenge Fees Completed: $35,528.18")
