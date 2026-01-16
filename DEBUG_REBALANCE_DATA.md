# Debug Guide: Rebalance Data Flow

## What Changed

### 1. **Trader Companion App** (`trader_app.py`)
   - ✅ Made window scrollable with canvas and scrollbar
   - ✅ Added comprehensive debug logging to trace the entire data flow
   - ✅ Logs now show:
     - Total deals retrieved from MT5
     - Number of balance operations found
     - Account balance
     - Calculated deposits and withdrawals
     - Sample balance deals
     - Server response details

### 2. **Backend API** (`dashboard/app.py`)
   - ✅ Added detailed logging of incoming MT5 data
   - ✅ Logs deal types to identify format issues
   - ✅ Logs calculated statistics after processing

### 3. **Data Processor** (`utils/data_processor.py`)
   - ✅ Added console debug output showing:
     - MT5 account data (dict or object)
     - Number of deals processed
     - Number of balance deals vs trade deals
     - Deposits and withdrawals calculated
     - Deal types encountered

## How to Test

### Step 1: Update Your Server (PythonAnywhere)
```bash
cd ~/MT5HedgingEngine
git pull
# Then reload your web app from the "Web" tab
```

### Step 2: Restart Trader Companion
1. Close the current trader app if running
2. Restart it to get the new scrollable version with debug logging

### Step 3: Test the Push
1. **Connect to MT5** in the trader app
2. **Lookup your client** using email
3. **Click "Push Rebalance Data Only"**
4. **Scroll down in the trader app logs** to see the detailed debug trace

### Step 4: Check the Logs

#### Local Trader App Will Show:
```
============================================================
📊 REBALANCE DATA DEBUG TRACE
============================================================
✓ Total deals retrieved: X
✓ Balance operations found: Y
✓ Account Balance: $XXXX.XX
✓ Calculated Deposits: $XXXX.XX
✓ Calculated Withdrawals: $XXXX.XX

📋 Sample balance deals:
   Deal 1: Type=BALANCE, Profit=XXXX.XX, Time=2026-01-XX
   Deal 2: Type=BALANCE, Profit=-XXXX.XX, Time=2026-01-XX

📤 Sending payload with:
   - Account data: 12 fields
   - Balance deals: Y operations
   - Email: your@email.com

🚀 Pushing to: http://your-dashboard/api/client/push

📡 Server response: HTTP 200
✓ Response status: success

✅ MT5 DATA PUSHED SUCCESSFULLY!
   Balance: $XXXX.XX
   Deposits: $XXXX.XX
   Withdrawals: $XXXX.XX
============================================================

💡 TIP: Refresh your dashboard to see updated Live Hedging Review
```

#### Server Logs (PythonAnywhere Error Log) Will Show:
```
📥 Push for ClientName: Y deals, balance=XXXX.XX, 0 evaluations
   Sample deal types: ['BALANCE', 'BALANCE', ...]

🔍 DATA_PROCESSOR DEBUG:
   MT5 Account (dict): balance=$XXXX.XX
   MT5 Deals: Y total
   - Balance deals: Y, Trade deals: 0
   - Deposits: $XXXX.XX, Withdrawals: $XXXX.XX
   - Actual profit: $0.00
   - Deal types seen: ['BALANCE']

✅ Stats calculated:
   - Current balance: $XXXX.XX
   - Total deposits: $XXXX.XX
   - Total withdrawals: $XXXX.XX
   - Actual hedging: $0.00
   - Debug: Y deals processed, types seen: ['BALANCE']
```

## What to Look For

### ✅ SUCCESS INDICATORS:
1. **Trader App shows**: "Balance operations found: X" where X > 0
2. **Server logs show**: "MT5 Deals: X total" where X > 0
3. **Server logs show**: "Balance deals: X" where X > 0
4. **Dashboard displays**: Non-zero values in Live Hedging Review

### ❌ FAILURE INDICATORS:

#### If "Balance operations found: 0"
- **Problem**: MT5 account has no deposits/withdrawals in the last 90 days
- **Solution**: Check MT5 history, try increasing days in `get_deals(days=90)`, or manually deposit/withdraw to create a balance operation

#### If Deal types show numbers instead of "BALANCE"
- **Problem**: Deal type serialization mismatch
- **Check**: Server logs for "Deal types seen: ['2']" (should work, but confirm)

#### If Server shows "MT5 Deals: 0"
- **Problem**: Payload not reaching server correctly
- **Check**: Trader app shows "Sending payload with: Balance deals: X operations"
- **Check**: Network/firewall issues

#### If Dashboard still shows $0.00
- **Problem**: Frontend not refreshing or data structure mismatch
- **Solution**: Hard refresh dashboard (Ctrl+F5), check browser console for errors

## Quick Fixes

### If you see "No balance deals found":
```python
# Option 1: Make a small deposit/withdrawal in MT5 to create a balance operation
# Option 2: Modify push to include ALL deals temporarily to see what types exist:

# In trader_app.py, line ~600, temporarily change:
balance_deals = [d for d in deals if str(d.get('type', '')).upper() == 'BALANCE']
# To:
balance_deals = deals  # TEMPORARY: send all deals to debug
```

### If types are numbers (e.g., '2' instead of 'BALANCE'):
The code already handles this! It checks: `d_type == 2 or str(d_type).upper() == "BALANCE"`

## Next Steps After Testing

1. **If successful**: Remove debug logging (or keep it for troubleshooting)
2. **If failed**: Share the full log output from both Trader App and Server Error Log
3. **Check**: PythonAnywhere error log at `~/mysite_pythonanywhere_com_error_log.txt`

## Data Flow Summary

```
MT5 Account
    ↓
[trader_app.py] 
  - Fetches deals with get_deals(days=90)
  - Filters for type="BALANCE"
  - Creates payload
    ↓
[HTTP POST to /api/client/push]
    ↓
[app.py] 
  - Receives payload
  - Logs incoming data
  - Calls calculate_statistics()
    ↓
[data_processor.py]
  - Processes mt5_deals
  - Identifies BALANCE type deals
  - Sums deposits/withdrawals
  - Returns stats dict
    ↓
[app.py]
  - Saves to database
  - Returns success response
    ↓
[Dashboard Frontend]
  - Loads stats from API
  - Displays in "Live Hedging Review"
```

## Contact Points for Debugging

1. **Local Logs**: Trader App console (now scrollable!)
2. **Server Logs**: PythonAnywhere → Files → `~/mysite_pythonanywhere_com_error_log.txt`
3. **Database**: PythonAnywhere → `dashboard/dashboard.db` (SQLite browser)
4. **API Response**: Check Network tab in browser DevTools when dashboard loads
