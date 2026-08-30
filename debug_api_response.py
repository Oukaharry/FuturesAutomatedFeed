#!/usr/bin/env python3
"""Check what the dashboard API returns for harryodhiambo16@gmail.com"""

import requests
import json

email = "harryodhiambo16@gmail.com"
dashboard_url = "https://www.tradeopss.com"

print("=" * 80)
print("DASHBOARD API RESPONSE CHECK")
print("=" * 80)
print(f"Email: {email}")
print(f"Dashboard: {dashboard_url}")
print()

try:
    response = requests.post(
        f"{dashboard_url}/api/client/data",
        json={"email": email},
        headers={"Content-Type": "application/json"},
        timeout=15
    )
    
    if response.status_code != 200:
        print(f"❌ API returned HTTP {response.status_code}")
        print(response.text[:500])
        exit(1)
    
    data = response.json()
    evaluations = data.get("evaluations", [])
    
    print(f"✅ API returned {len(evaluations)} evaluations")
    print()
    
    # Find Funded Next Flex evaluations
    fn_flex_evals = [ev for ev in evaluations if 
                     str(ev.get('Prop Firm', '')).strip() == 'Funded Next Flex']
    
    print(f"🔍 Found {len(fn_flex_evals)} Funded Next Flex evaluations")
    print()
    
    if not fn_flex_evals:
        print("❌ No Funded Next Flex evaluations found!")
        print("\nAll prop firms in response:")
        firms = set(str(ev.get('Prop Firm', '')).strip() for ev in evaluations)
        for firm in sorted(firms):
            count = sum(1 for ev in evaluations if str(ev.get('Prop Firm', '')).strip() == firm)
            print(f"  - {firm}: {count} evaluation(s)")
        exit(0)
    
    # Check each Funded Next Flex evaluation
    for i, ev in enumerate(fn_flex_evals, 1):
        print(f"{'=' * 80}")
        print(f"EVALUATION #{i}")
        print(f"{'=' * 80}")
        print(f"Client ID: {ev.get('Client ID')}")
        print(f"Account #: {ev.get('Account #')}")
        print(f"Account #.1: {ev.get('Account #.1')}")
        print(f"Status: {ev.get('Status')}")
        print(f"Status Funded: {ev.get('Status Funded')}")
        print(f"_is_active: {ev.get('_is_active')}")
        print()
        
        # Check for Hedge Day fields
        hedge_days = {}
        for day in range(1, 35):
            field = f"Hedge Day {day}"
            value = ev.get(field)
            if value is not None and str(value).strip():
                hedge_days[day] = str(value).strip()
        
        if hedge_days:
            print(f"📅 Hedge Day fields found ({len(hedge_days)}):")
            for day, value in sorted(hedge_days.items()):
                is_day_name = value.upper() in ['MONDAY', 'TUESDAY', 'WEDNESDAY', 
                                                  'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY',
                                                  'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']
                marker = "📌 DAY PLACEHOLDER" if is_day_name else "💰"
                print(f"   Hedge Day {day}: {value} {marker}")
        else:
            print("❌ No Hedge Day fields found!")
            print("\nAll fields in evaluation:")
            for key in sorted(ev.keys()):
                if 'Hedge' in key or 'Day' in key:
                    print(f"  - {key}: {ev[key]}")
        print()
        
        # Check if TUESDAY placeholder exists
        tuesday_found = False
        for day, value in hedge_days.items():
            if value.upper() in ['TUESDAY', 'TUE']:
                tuesday_found = True
                print(f"✅ TUESDAY placeholder found in Hedge Day {day}!")
                break
        
        if not tuesday_found:
            print("❌ No TUESDAY placeholder found in any Hedge Day field")
        print()

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("=" * 80)
