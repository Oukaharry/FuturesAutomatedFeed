# MT5 Dashboard - Cloud Deployment Guide

## Overview
Your dashboard is now configured as an **API-based system** where:
- **Dashboard (Cloud)**: Hosted on PythonAnywhere (or similar), receives data via REST API
- **Traders (Local)**: Run MT5 software on their machines, push data to dashboard using API keys

## Architecture
```
┌─────────────────────┐
│  Trader 1 (Local)   │
│  MT5 + Python       │──┐
└─────────────────────┘  │
                         │   HTTPS/API
┌─────────────────────┐  │   (with API Key)
│  Trader 2 (Local)   │──┼──────────────►  ┌──────────────────────┐
│  MT5 + Python       │  │                  │  Dashboard (Cloud)   │
└─────────────────────┘  │                  │  PythonAnywhere      │
                         │                  │  - Receives data     │
┌─────────────────────┐  │                  │  - Stores in JSON    │
│  Trader N (Local)   │──┘                  │  - Serves web UI     │
│  MT5 + Python       │                     └──────────────────────┘
└─────────────────────┘
```

---

## Step 1: Deploy Dashboard to PythonAnywhere

### 1.1 Create Account
1. Go to [PythonAnywhere.com](https://www.pythonanywhere.com/)
2. Sign up for a **FREE account**
3. Note your username (e.g., `harrytrader`)

### 1.2 Upload Files
1. Click **"Files"** tab
2. Create directory: `/home/harrytrader/MT5Dashboard`
3. Upload these folders/files:
   ```
   MT5Dashboard/
   ├── dashboard/
   │   ├── app.py
   │   ├── api_client.py
   │   ├── manage_api_keys.py
   │   ├── static/
   │   └── templates/
   ├── config/
   │   ├── hierarchy.py
   │   ├── hierarchy.json
   │   └── settings.py
   ├── utils/
   │   ├── __init__.py
   │   └── data_processor.py
   └── requirements.txt
   ```

### 1.3 Install Dependencies
1. Click **"Consoles"** tab → Start a **Bash console**
2. Run:
   ```bash
   cd MT5Dashboard
   pip install --user -r requirements.txt
   ```

### 1.4 Set Admin Password (Security)
1. In the Bash console:
   ```bash
   echo 'export ADMIN_PASSWORD="YourSecurePassword123"' >> ~/.bashrc
   source ~/.bashrc
   ```

### 1.5 Configure Web App
1. Click **"Web"** tab
2. Click **"Add a new web app"**
3. Choose **"Flask"** → Python version **3.10**
4. Set source code path: `/home/harrytrader/MT5Dashboard`
5. Click **"WSGI configuration file"** link and edit it:

```python
import sys
import os

# Add your project directory to the sys.path
project_home = '/home/harrytrader/MT5Dashboard'
if project_home not in sys.path:
    sys.path = [project_home] + sys.path

# Set environment variable
os.environ['ADMIN_PASSWORD'] = 'YourSecurePassword123'

# Import Flask app
from dashboard.app import app as application
```

6. Save the file
7. Click **"Reload"** button
8. Your dashboard is now live at: `https://harrytrader.pythonanywhere.com`

---

## Step 2: Generate API Keys for Traders

### 2.1 On Your Local Machine
1. Open terminal in your project folder
2. Activate your Python environment:
   ```powershell
   .venv\Scripts\Activate.ps1
   ```

3. Run the API key manager:
   ```powershell
   python dashboard\manage_api_keys.py
   ```

4. Enter:
   - Dashboard URL: `https://harrytrader.pythonanywhere.com`
   - Admin Password: `YourSecurePassword123`

5. Select **"1. Generate new API key"**
6. Enter trader details:
   - Admin: `Philip`
   - Trader: `Philip`
   - Client: `Chris` (optional)

7. **COPY THE API KEY** - it looks like:
   ```
   xK7j9mP2nQ8vR5tY3wZ1aB4cD6eF0gH8iJ2kL4mN6oP8qR
   ```

8. Share this API key **securely** with the trader (use encrypted messaging)

### 2.2 Alternative: Use curl (Advanced)
```bash
curl -X POST https://harrytrader.pythonanywhere.com/api/admin/generate_key \
  -H 'Content-Type: application/json' \
  -d '{
    "admin_password": "YourSecurePassword123",
    "trader_info": {
      "admin": "Philip",
      "trader": "Philip",
      "client": "Chris"
    }
  }'
```

---

## Step 3: Configure Traders' Local Software

Each trader needs to modify their local `main.py` or MT5 automation script to push data to the dashboard.

### 3.1 Install Dashboard Client (On Each Trader's PC)
Ensure `requests` is installed:
```powershell
pip install requests
```

### 3.2 Copy API Client Module
Copy `dashboard/api_client.py` to each trader's project folder.

### 3.3 Integrate into MT5 Software

Add this to your `main.py` or automation script:

```python
from dashboard.api_client import DashboardAPIClient

# Configuration (trader sets these)
DASHBOARD_URL = "https://harrytrader.pythonanywhere.com"
API_KEY = "xK7j9mP2nQ8vR5tY3wZ1aB4cD6eF0gH8iJ2kL4mN6oP8qR"  # From Step 2
CLIENT_ID = "Chris"  # This trader's client name

# Initialize dashboard client
dashboard = DashboardAPIClient(DASHBOARD_URL, API_KEY, CLIENT_ID)

# Test connection
health = dashboard.health_check()
print(f"Dashboard connection: {health}")

# In your main loop or update function:
def send_data_to_dashboard():
    """Send current MT5 data to dashboard."""
    
    # Get account info from MT5
    account_info = mt5.account_info()
    if account_info:
        dashboard.push_account_data({
            "balance": account_info.balance,
            "equity": account_info.equity,
            "margin": account_info.margin,
            "free_margin": account_info.margin_free,
            "margin_level": account_info.margin_level,
            "profit": account_info.profit
        })
    
    # Get positions
    positions = mt5.positions_get()
    if positions:
        positions_list = []
        for pos in positions:
            positions_list.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "type": "BUY" if pos.type == 0 else "SELL",
                "volume": pos.volume,
                "price": pos.price_open,
                "current_price": pos.price_current,
                "profit": pos.profit,
                "sl": pos.sl,
                "tp": pos.tp
            })
        dashboard.push_positions(positions_list)
    
    # Get deals (optional)
    deals = mt5.history_deals_get(datetime.now() - timedelta(days=7), datetime.now())
    if deals:
        deals_list = []
        for deal in deals:
            deals_list.append({
                "ticket": deal.ticket,
                "order": deal.order,
                "time": deal.time,
                "symbol": deal.symbol,
                "type": "BUY" if deal.type == 0 else "SELL",
                "volume": deal.volume,
                "price": deal.price,
                "profit": deal.profit
            })
        dashboard.push_deals(deals_list)
    
    print("✓ Data sent to dashboard")

# Call this function periodically (e.g., every 5 minutes)
# You can use threading or schedule it in your main loop
```

### 3.4 Schedule Automatic Updates

Add to your main loop:
```python
import time
from threading import Thread

def dashboard_update_loop():
    """Background thread to update dashboard every 5 minutes."""
    while True:
        try:
            send_data_to_dashboard()
        except Exception as e:
            print(f"Dashboard update error: {e}")
        time.sleep(300)  # 5 minutes

# Start background thread
Thread(target=dashboard_update_loop, daemon=True).start()
```

---

## Step 4: Test Everything

### 4.1 Test Dashboard API
```powershell
curl https://harrytrader.pythonanywhere.com/api/health
```
Should return:
```json
{
  "status": "ok",
  "timestamp": "2026-01-07T10:30:00",
  "clients_count": 0
}
```

### 4.2 Test from Trader's Machine
Run the trader's script - you should see:
```
Dashboard connection: {'status': 'ok', 'timestamp': '...', 'clients_count': 0}
✓ Data sent to dashboard
```

### 4.3 View Dashboard
1. Open browser: `https://harrytrader.pythonanywhere.com`
2. Login with trader email
3. See live data from MT5!

---

## Security Considerations

### ✓ Implemented
- API Key authentication for all trader endpoints
- Admin password protection for key management
- HTTPS encryption (provided by PythonAnywhere)

### 🔒 Additional Recommendations
1. **Change admin password** from `change_me_in_production`
2. **Never commit** `api_keys.json` to Git - add to `.gitignore`
3. **Rotate API keys** periodically (every 3-6 months)
4. **Use environment variables** for sensitive data:
   ```python
   import os
   from dotenv import load_dotenv
   
   load_dotenv()
   API_KEY = os.getenv('DASHBOARD_API_KEY')
   ```

---

## Monitoring & Maintenance

### Check Dashboard Logs (PythonAnywhere)
1. Go to **"Web"** tab
2. Click **"Log files"**
3. View `error.log` and `server.log`

### View API Keys
```powershell
python dashboard\manage_api_keys.py
# Select option 2
```

### Revoke Compromised Key
```powershell
python dashboard\manage_api_keys.py
# Select option 3
```

---

## Troubleshooting

### Trader can't connect to dashboard
1. Check firewall settings
2. Verify API key is correct
3. Check dashboard is running: `curl https://harrytrader.pythonanywhere.com/api/health`

### Dashboard not updating
1. Check trader's console for errors
2. Verify API endpoint URLs are correct
3. Check PythonAnywhere logs

### "Invalid API key" error
1. Generate new key using `manage_api_keys.py`
2. Update trader's configuration
3. Restart trader's script

---

## Cost Breakdown

### FREE Tier (PythonAnywhere)
- ✓ 1 web app
- ✓ HTTPS included
- ✓ 512 MB storage
- ✓ Good for up to ~20 traders

### Paid Tier ($5/month - Hacker Plan)
- ✓ Multiple web apps
- ✓ Always-on tasks
- ✓ 1 GB storage
- ✓ Good for 50+ traders

---

## Next Steps

1. ☐ Deploy dashboard to PythonAnywhere
2. ☐ Generate API keys for all traders
3. ☐ Update traders' `main.py` with API client code
4. ☐ Test with 1-2 traders first
5. ☐ Roll out to all traders
6. ☐ Monitor logs for issues
7. ☐ Set up backup schedule for `dashboard_data.json` and `api_keys.json`

---

## Support

For issues, check:
1. PythonAnywhere forums: https://www.pythonanywhere.com/forums/
2. Flask documentation: https://flask.palletsprojects.com/
3. Your project's error logs

Good luck with your deployment! 🚀
