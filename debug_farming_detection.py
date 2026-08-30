#!/usr/bin/env python3
"""Debug farming trade detection for harryodhiambo16@gmail.com account FNFTAHARRISONOUKA79286"""

import sys
sys.path.insert(0, r'c:\Users\harry\Music\MT5HedgingEngine')

try:
    import MetaTrader5 as mt5
except:
    print("❌ MetaTrader5 not available")
    sys.exit(1)

from trader_companion.mt5_comment_parser import MT5CommentParser, parse_mt5_comment
from datetime import datetime, timedelta

print("=" * 80)
print("FARMING TRADE DETECTION DIAGNOSTIC")
print("=" * 80)
print(f"Account: FNFTAHARRISONOUKA79286")
print(f"Email: harryodhiambo16@gmail.com")
print(f"Prop Firm: Funded Next Flex")
print()

# Initialize MT5
if not mt5.initialize():
    print("❌ Failed to initialize MT5")
    print(f"Error: {mt5.last_error()}")
    sys.exit(1)

print("✅ MT5 initialized successfully")
print()

# Get recent deals (last 30 days)
from_date = datetime.now() - timedelta(days=30)
deals = mt5.history_deals_get(from_date, datetime.now())

if deals is None or len(deals) == 0:
    print("⚠️  No deals found in the last 30 days")
    mt5.shutdown()
    sys.exit(0)

print(f"📊 Found {len(deals)} total deals in last 30 days")
print()

# Filter for the specific account
account_patterns = [
    "FNFTAHARRISONOUKA79286",
    "FNFT...79286",  # Truncated format
    "HARRISONOUKA79286",
    "79286",  # Just the suffix
]

parser = MT5CommentParser()
farming_deals = []
all_matching_deals = []

print("🔍 Searching for deals matching account patterns:")
for pattern in account_patterns:
    print(f"   - {pattern}")
print()

for deal in deals:
    comment = deal.comment if hasattr(deal, 'comment') else ""
    if not comment:
        continue
    
    # Check if comment contains any of our patterns
    comment_upper = comment.upper()
    matches_account = any(pattern.upper() in comment_upper for pattern in account_patterns)
    
    if matches_account:
        all_matching_deals.append(deal)
        
        # Parse the comment
        parsed = parser.parse(comment)
        
        # Check if it's a farming trade
        if parsed.is_valid and parsed.phase_code == 'FA':
            farming_deals.append((deal, parsed))
            print(f"✅ FARMING TRADE DETECTED:")
            print(f"   Comment: {comment}")
            print(f"   Account: {parsed.account_number}")
            print(f"   Phase: {parsed.phase_code}")
            print(f"   Trade #: {parsed.trade_number}")
            print(f"   Date: {parsed.farming_date}")
            print(f"   Deal Time: {deal.time}")
            print(f"   Profit: ${deal.profit}")
            print()

print("=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"Total deals matching account: {len(all_matching_deals)}")
print(f"Farming trades detected: {len(farming_deals)}")
print()

if len(all_matching_deals) > 0:
    print("📋 All matching deals comments:")
    unique_comments = set()
    for deal in all_matching_deals:
        comment = deal.comment if hasattr(deal, 'comment') else ""
        if comment:
            unique_comments.add(comment)
    
    for comment in sorted(unique_comments):
        parsed = parser.parse(comment)
        status = "✅ VALID" if parsed.is_valid else "❌ INVALID"
        phase = f"Phase: {parsed.phase_code}" if parsed.is_valid else "No phase detected"
        print(f"   {status} | {comment} | {phase}")
    print()

if len(farming_deals) == 0:
    print("⚠️  NO FARMING TRADES DETECTED")
    print()
    print("POSSIBLE CAUSES:")
    print("1. MT5 comment format is incorrect - should be:")
    print("   - FNFTAHARRISONOUKA79286_FA  (simple farming)")
    print("   - FNFT...79286_FA  (truncated)")
    print("   - FNFTAHARRISONOUKA79286_FA_210826  (farming with date)")
    print()
    print("2. No farming trades have been placed yet in MT5")
    print()
    print("3. The account number in MT5 comment doesn't match:")
    print("   Expected: FNFTAHARRISONOUKA79286")
    print()
    print("EXPECTED COMMENT FORMAT:")
    print("   {AccountNumber}_FA")
    print("   Example: FNFTAHARRISONOUKA79286_FA")
    print()
    
    if len(all_matching_deals) > 0:
        print("💡 FOUND DEALS WITH MATCHING ACCOUNT BUT WRONG COMMENT FORMAT")
        print("   The trades exist but the MT5 comment doesn't have '_FA' suffix")
        print("   Please check the MT5 comment format on your farming trades!")

mt5.shutdown()
print()
print("=" * 80)
