"""
Test script to get deposits/withdrawals from MT5 deal history
"""
import MetaTrader5 as mt5
from datetime import datetime
import time

# Initialize MT5
if not mt5.initialize():
    print('MT5 initialization failed:', mt5.last_error())
    exit()

print('='*60)
print('MT5 DEAL HISTORY - BALANCE OPERATIONS')
print('='*60)

# Get all history (from account creation to now)
from_timestamp = 0  # From the beginning
to_timestamp = time.time() + 86400  # To tomorrow

deals = mt5.history_deals_get(from_timestamp, to_timestamp)

if deals is None or len(deals) == 0:
    print('No deals found in history')
    mt5.shutdown()
    exit()

print(f'Total deals found: {len(deals)}')
print()

# Filter balance operations
total_deposits = 0.0
total_withdrawals = 0.0
balance_deals = []

# Deal type 2 = BALANCE operation in MT5
for deal in deals:
    if deal.type == 2:  # DEAL_TYPE_BALANCE
        balance_deals.append(deal)
        if deal.profit > 0:
            total_deposits += deal.profit
        else:
            total_withdrawals += deal.profit

print(f'Balance operations found: {len(balance_deals)}')
print()
print('--- BALANCE OPERATIONS LIST ---')
for deal in balance_deals:
    deal_time = datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M')
    sign = '+' if deal.profit > 0 else ''
    op_type = 'DEPOSIT' if deal.profit > 0 else 'WITHDRAWAL'
    print(f'  {deal_time} | {op_type:10} | {sign}${deal.profit:.2f} | {deal.comment}')

print()
print('='*60)
print('CALCULATED TOTALS')
print('='*60)
print(f'Total Deposits:    ${total_deposits:.2f}')
print(f'Total Withdrawals: ${total_withdrawals:.2f}')
print(f'Net:               ${total_deposits + total_withdrawals:.2f}')
print()

# Current account balance for comparison
account = mt5.account_info()
if account:
    print(f'Current Balance:   ${account.balance:.2f}')
    print(f'Current Profit:    ${account.profit:.2f}')

mt5.shutdown()
print()
print('='*60)
print('TEST COMPLETE')
print('='*60)
