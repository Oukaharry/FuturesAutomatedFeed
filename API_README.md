# MT5 Dashboard API - Quick Start Guide

## What Changed?

Your dashboard is now an **API-based system** where traders send data from their local MT5 software to a cloud-hosted dashboard.

```
Traders (Local MT5) ──[API]──> Dashboard (Cloud) ──[Web UI]──> Managers/Admins
```

## For Administrators

### 1. Start the Dashboard Locally
```powershell
python dashboard\app.py
```

### 2. Test Everything Works
```powershell
python test_dashboard_api.py
```

### 3. Generate API Keys for Traders
```powershell
python dashboard\manage_api_keys.py
```

Follow the prompts to:
- Enter dashboard URL (e.g., `http://localhost:5001` for testing)
- Enter admin password (default: `change_me_in_production`)
- Generate keys for each trader

### 4. Deploy to Cloud
See **[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)** for step-by-step PythonAnywhere deployment.

---

## For Traders

### 1. Get Your API Key
Ask your administrator for:
- Dashboard URL (e.g., `https://harrytrader.pythonanywhere.com`)
- Your personal API key
- Your client ID

### 2. Install Requirements
```powershell
pip install requests
```

### 3. Copy Files to Your Project
Copy these files to your MT5 project folder:
- `dashboard/api_client.py`
- `dashboard_integration_example.py`

### 4. Add to Your Code

**Option A: Automatic Updates (Recommended)**
```python
from dashboard_integration_example import start_dashboard_integration

# At the start of your main.py
start_dashboard_integration()

# Your normal trading code continues...
# Dashboard updates happen automatically every 5 minutes in the background
```

**Option B: Manual Updates**
```python
from dashboard.api_client import DashboardAPIClient

DASHBOARD_URL = "https://harrytrader.pythonanywhere.com"
API_KEY = "your-api-key-here"
CLIENT_ID = "Chris"

dashboard = DashboardAPIClient(DASHBOARD_URL, API_KEY, CLIENT_ID)

# Send data whenever you want
dashboard.push_account_data({
    "balance": 50000,
    "equity": 50125.50,
    "profit": 125.50
})

dashboard.push_positions([...])
dashboard.push_deals([...])
```

### 5. Configure Your Settings
Edit `dashboard_integration_example.py`:
```python
DASHBOARD_URL = "https://harrytrader.pythonanywhere.com"  # Your dashboard URL
API_KEY = "xK7j9mP2nQ8vR5tY3wZ1aB4cD6eF0gH8iJ2kL4mN6oP8qR"  # From admin
CLIENT_ID = "Chris"  # Your client name
UPDATE_INTERVAL = 300  # Seconds between updates (300 = 5 minutes)
```

---

## API Endpoints

### Public Endpoints (No Auth Required)
- `GET /api/health` - Health check
- `GET /api/data?client_id=Chris` - Get client data
- `GET /api/hierarchy` - Get user hierarchy

### Trader Endpoints (Requires API Key)
- `POST /api/trader/push_account` - Push account info
- `POST /api/trader/push_positions` - Push open positions
- `POST /api/trader/push_deals` - Push deal history
- `POST /api/trader/push_evaluations` - Push evaluation data
- `POST /api/update_data` - Push all data at once

### Admin Endpoints (Requires Admin Password)
- `POST /api/admin/generate_key` - Generate API key
- `GET /api/admin/list_keys` - List all API keys
- `POST /api/admin/revoke_key` - Revoke API key

---

## File Structure

```
MT5HedgingEngine/
├── dashboard/
│   ├── app.py                    # Main dashboard server
│   ├── api_client.py             # Client library for traders
│   ├── manage_api_keys.py        # API key management tool
│   ├── api_keys.json             # API keys storage (DO NOT COMMIT!)
│   ├── dashboard_data.json       # Client data storage
│   ├── templates/                # Web UI templates
│   └── static/                   # CSS, JS files
├── config/
│   ├── hierarchy.py              # User hierarchy management
│   └── hierarchy.json            # User hierarchy data
├── DEPLOYMENT_GUIDE.md           # Full deployment instructions
├── dashboard_integration_example.py  # Example integration code
├── test_dashboard_api.py         # API testing script
└── requirements.txt              # Python dependencies
```

---

## Testing

### Test Locally Before Deployment
```powershell
# Terminal 1: Start dashboard
python dashboard\app.py

# Terminal 2: Run tests
python test_dashboard_api.py
```

### Test After Cloud Deployment
```powershell
python test_dashboard_api.py https://harrytrader.pythonanywhere.com
```

---

## Security

### ✓ What's Protected
- API endpoints require authentication (API keys)
- Admin functions require admin password
- HTTPS encryption (when deployed to cloud)
- API keys are stored server-side

### 🔒 Important
1. **Change admin password** in production:
   ```python
   export ADMIN_PASSWORD="YourSecurePassword123"
   ```

2. **Never commit** `api_keys.json` to Git:
   ```bash
   echo "dashboard/api_keys.json" >> .gitignore
   ```

3. **Rotate API keys** every 3-6 months

4. **Use environment variables** for sensitive data:
   ```python
   import os
   API_KEY = os.getenv('DASHBOARD_API_KEY')
   ```

---

## Troubleshooting

### Dashboard won't start
```
Error: Address already in use
```
**Fix:** Another service is using port 5001
```powershell
# Change port in app.py or kill existing process
netstat -ano | findstr :5001
taskkill /PID <pid> /F
```

### "Invalid API key" error
**Fix:** Generate a new key
```powershell
python dashboard\manage_api_keys.py
```

### Data not updating
**Fix:** Check trader's console for errors
- Verify API key is correct
- Check dashboard URL is correct
- Ensure dashboard is running

### Can't connect to cloud dashboard
**Fix:** 
- Check URL is correct (should start with `https://`)
- Verify dashboard is running on PythonAnywhere
- Check firewall settings

---

## Quick Commands

```powershell
# Start dashboard locally
python dashboard\app.py

# Test API
python test_dashboard_api.py

# Manage API keys
python dashboard\manage_api_keys.py

# Generate API key (command line)
python dashboard\manage_api_keys.py generate http://localhost:5001 admin_pass Philip Philip Chris

# List API keys (command line)
python dashboard\manage_api_keys.py list http://localhost:5001 admin_pass
```

---

## Support

- Full deployment guide: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
- Integration examples: [dashboard_integration_example.py](dashboard_integration_example.py)
- API testing: [test_dashboard_api.py](test_dashboard_api.py)

---

## Next Steps

1. ☐ Test locally with `test_dashboard_api.py`
2. ☐ Deploy to PythonAnywhere (see DEPLOYMENT_GUIDE.md)
3. ☐ Generate API keys for traders
4. ☐ Update traders' code with integration example
5. ☐ Test with 1-2 traders first
6. ☐ Roll out to all traders

Good luck! 🚀
