"""
Test script to check MT5 account deposit/withdrawal fields
"""
import MetaTrader5 as mt5

# Initialize MT5
if not mt5.initialize():
    print('MT5 initialization failed:', mt5.last_error())
    exit()

# Get account info
account = mt5.account_info()
if account:
    print('='*60)
    print('MT5 ACCOUNT INFO TEST')
    print('='*60)
    print(f'Login: {account.login}')
    print(f'Server: {account.server}')
    print(f'Balance: ${account.balance:.2f}')
    print(f'Equity: ${account.equity:.2f}')
    print(f'Profit: ${account.profit:.2f}')
    print()
    print('--- REBALANCE DATA ---')
    
    # Check deposit field
    deposit_val = getattr(account, 'deposit', 'NOT FOUND')
    print(f'Deposit (attr): {deposit_val}')
    
    # Check withdrawal field  
    withdrawal_val = getattr(account, 'withdrawal', 'NOT FOUND')
    print(f'Withdrawal (attr): {withdrawal_val}')
    
    # Check credit
    credit_val = getattr(account, 'credit', 'NOT FOUND')
    print(f'Credit: {credit_val}')
    
    print()
    print('--- ALL AVAILABLE ATTRIBUTES ---')
    for attr in dir(account):
        if not attr.startswith('_'):
            val = getattr(account, attr)
            if not callable(val):
                print(f'  {attr}: {val}')
else:
    print('Could not get account info')

mt5.shutdown()
print()
print('='*60)
print('TEST COMPLETE')
print('='*60)
