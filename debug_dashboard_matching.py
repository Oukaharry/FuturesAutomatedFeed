#!/usr/bin/env python3
"""Check dashboard matching for harryodhiambo16@gmail.com"""

import sys
sys.path.insert(0, r'c:\Users\harry\Music\MT5HedgingEngine')

from dashboard.database import get_all_evaluations
from trader_companion.mt5_comment_parser import get_account_signature

print("=" * 80)
print("DASHBOARD ACCOUNT MATCHING CHECK")
print("=" * 80)
print()

# Get all evaluations
evals = get_all_evaluations()
print(f"📊 Total evaluations loaded: {len(evals)}")
print()

# Find the user's evaluations
user_email = "harryodhiambo16@gmail.com"
user_evals = [ev for ev in evals if ev.get('User') == user_email]

print(f"🔍 Evaluations for {user_email}: {len(user_evals)}")
print()

if len(user_evals) == 0:
    print(f"❌ No evaluations found for {user_email}")
    sys.exit(1)

# Display details for each evaluation
for i, ev in enumerate(user_evals, 1):
    print(f"{'=' * 80}")
    print(f"EVALUATION #{i}")
    print(f"{'=' * 80}")
    print(f"Client ID: {ev.get('Client ID')}")
    print(f"Prop Firm: {ev.get('Prop Firm')}")
    print(f"Account #: {ev.get('Account #')}")
    print(f"Account #.1: {ev.get('Account #.1')}")
    print(f"Status: {ev.get('Status')}")
    print(f"Status Funded: {ev.get('Status Funded')}")
    print()
    
    # Get account signatures
    challenge_acct = str(ev.get('Account #', '')).strip()
    funded_acct = str(ev.get('Account #.1', '')).strip()
    
    if challenge_acct:
        sig = get_account_signature(challenge_acct)
        print(f"Challenge Account Signature: {sig}")
    
    if funded_acct:
        sig = get_account_signature(funded_acct)
        print(f"Funded Account Signature: {sig}")
    
    # Check if this matches our MT5 account
    mt5_account = "FNFT...79286"
    mt5_sig = get_account_signature(mt5_account)
    print(f"MT5 Account ({mt5_account}) Signature: {mt5_sig}")
    print()
    
    # Check for farming data
    farming_fields = []
    for day in range(1, 35):
        day_field = f"Hedge Day {day}"
        date_field = f"_Hedge Day {day} Date"
        day_value = ev.get(day_field)
        date_value = ev.get(date_field)
        
        if day_value or date_value:
            farming_fields.append({
                'day': day,
                'value': day_value,
                'date': date_value
            })
    
    if farming_fields:
        print(f"📅 Farming data found ({len(farming_fields)} days):")
        for f in farming_fields:
            print(f"   Day {f['day']}: {f['value']} (date: {f['date']})")
    else:
        print("📅 No farming data found in this evaluation")
    
    print()

# Check if MT5 account signature matches
print("=" * 80)
print("SIGNATURE MATCHING CHECK")
print("=" * 80)
print()

mt5_account = "FNFT...79286"
mt5_sig = get_account_signature(mt5_account)
print(f"MT5 Account: {mt5_account}")
print(f"MT5 Signature: {mt5_sig}")
print()

# Also check full account number
mt5_full = "FNFTAHARRISONOUKA79286"
mt5_full_sig = get_account_signature(mt5_full)
print(f"Full Account: {mt5_full}")
print(f"Full Signature: {mt5_full_sig}")
print()

# Check all matching evaluations
matches = []
for ev in evals:
    challenge_acct = str(ev.get('Account #', '')).strip()
    funded_acct = str(ev.get('Account #.1', '')).strip()
    
    for acct in [challenge_acct, funded_acct]:
        if acct:
            sig = get_account_signature(acct)
            if sig == mt5_sig or sig == mt5_full_sig:
                matches.append({
                    'client_id': ev.get('Client ID'),
                    'user': ev.get('User'),
                    'account': acct,
                    'signature': sig,
                    'prop_firm': ev.get('Prop Firm')
                })

print(f"Found {len(matches)} evaluations with matching account signatures:")
for m in matches:
    print(f"  - {m['client_id']} | {m['user']} | {m['account']} ({m['signature']}) | {m['prop_firm']}")

print()
print("=" * 80)
