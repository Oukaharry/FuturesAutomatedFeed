# STEP-BY-STEP DEPLOYMENT GUIDE

## Your deployment package is ready in: `deployment_package/`

Follow these steps exactly:

---

## STEP 1: Create PythonAnywhere Account (5 minutes)

1. Go to: https://www.pythonanywhere.com
2. Click "Start running Python online in less than a minute!"
3. Choose "Create a Beginner account" (FREE) or Hacker plan ($12/month)
4. Sign up with your email
5. **Username**: ballerquotes (already chosen)

---

## STEP 2: Upload Files (10 minutes)

1. Log in to PythonAnywhere
2. Click **"Files"** tab at the top
3. You'll be in `/home/ballerquotes/`
4. Create a new directory:
   - Type in the "Directories" box: `TrackingDashboard`
   - Click "New directory"
5. Click on `TrackingDashboard` to enter it
6. Upload ALL files from your `deployment_package` folder:
   - Click "Upload a file"
   - Select files one by one OR zip them first and upload
   - Make sure you upload:
     - `dashboard/` folder (with all its contents)
     - `config/` folder
     - `utils/` folder
     - `requirements.txt`
     - `.gitignore`

**TIP**: Zip the deployment_package folder first, upload the zip, then unzip it in PythonAnywhere Bash console:
```bash
cd MT5Dashboard
unzip deployment_package.zip
mv deployment_package/* .
rm -rf deployment_package
```

---

## STEP 3: Install Python Packages (5 minutes)

1. Click **"Consoles"** tab
2. Click "Bash" under "Start a new console"
3. In the console, type these commands:

```bash
cd TrackingDashboard
pip3.10 install --user flask requests python-dotenv
```

4. Wait for installation to complete (should see "Successfully installed...")

---

## STEP 4: Set Admin Password (2 minutes)

1. Still in the Bash console, run:

```bash
echo 'export ADMIN_PASSWORD="YourSecurePassword123"' >> ~/.bashrc
source ~/.bashrc
```

2. **IMPORTANT**: Replace `YourSecurePassword123` with YOUR OWN strong password
3. Write down this password - you'll need it to generate API keys

---

## STEP 5: Create Web App (5 minutes)

1. Click **"Web"** tab
2. Click "Add a new web app"
3. Click "Next" for your domain: `ballerquotes.pythonanywhere.com`
4. Select "Flask"
5. Select "Python 3.10"
6. For "Path", enter: `/home/ballerquotes/TrackingDashboard/dashboard/app.py`
7. Click "Next"

---

## STEP 6: Configure WSGI File (3 minutes) ⚠️ CRITICAL

1. Still on the "Web" tab
2. Scroll down to "Code" section
3. Click on the link for "WSGI configuration file" (e.g., `/var/www/ballerquotes_pythonanywhere_com_wsgi.py`)
4. **DELETE EVERYTHING** in that file (PythonAnywhere auto-generates Flask code - ignore it!)
5. **Paste ONLY this** (change the password):

```python
import sys
import os

# Your PythonAnywhere username
USERNAME = "ballerquotes"

# CHANGE THIS to your admin password (same as Step 4)
ADMIN_PASSWORD = "YourSecurePassword123"

# Add project directory
project_home = f'/home/{USERNAME}/TrackingDashboard'
if project_home not in sys.path:
    sys.path = [project_home] + sys.path

# Set environment variable
os.environ['ADMIN_PASSWORD'] = ADMIN_PASSWORD

# Import Flask app
from dashboard.app import app as application
```

6. Click "Save"
7. **IMPORTANT**: Go back to Web tab and click the green "Reload" button

**Common mistake**: If you see "Hello from Flask!" instead of your login page, you didn't delete all the auto-generated code. Go back and make sure the WSGI file contains ONLY the code above.

---

## STEP 7: Start Your Dashboard (1 minute)

1. Go back to **"Web"** tab
2. Scroll to top
3. Click the big green **"Reload ballerquotes.pythonanywhere.com"** button
4. Wait 10 seconds
5. Click the link to your site: `https://ballerquotes.pythonanywhere.com`

**You should see your dashboard login page!**

---

## STEP 8: Test Your Dashboard (2 minutes)

### From your local machine:

```powershell
python deployment_package/test_deployed.py https://ballerquotes.pythonanywhere.com
```

You should see:
```
✓ Dashboard is online!
  Status: ok
  Clients: 0
```

---

## STEP 9: Generate API Keys for Traders (5 minutes)

### On your local machine:

```powershell
python dashboard/manage_api_keys.py
```

1. Enter Dashboard URL: `https://ballerquotes.pythonanywhere.com`
2. Enter Admin Password: (the one you set in Step 4)
3. Select option **1** (Generate new API key)
4. Enter trader details:
   - Admin: `Philip`
   - Trader: `Philip`
   - Client: `Chris`
5. **COPY the API key** that's generated
6. Repeat for each trader

**The API keys are saved in:** `api_keys_generated.txt`

---

## STEP 10: Give API Keys to Traders (per trader)

Send each trader:
1. Their API key
2. The dashboard URL: `https://ballerquotes.pythonanywhere.com`
3. The file: `dashboard/api_client.py`
4. Instructions from `dashboard_integration_example.py`

Each trader should:
1. Copy `api_client.py` to their MT5 project
2. Add this to their `main.py`:

```python
from dashboard.api_client import DashboardAPIClient

# Configuration
DASHBOARD_URL = "https://ballerquotes.pythonanywhere.com"
API_KEY = "their-api-key-here"
CLIENT_ID = "their-client-name"

dashboard = DashboardAPIClient(DASHBOARD_URL, API_KEY, CLIENT_ID)

# Test connection
health = dashboard.health_check()
print(f"Dashboard: {health}")
```

---

## DONE! 🎉

Your dashboard is now:
- ✓ Running 24/7 in the cloud
- ✓ Accessible via HTTPS
- ✓ Ready to receive data from traders
- ✓ Secured with API keys

---

## Troubleshooting

### Seeing "Hello from Flask!" instead of login page?
**Fix**: The WSGI file still has auto-generated code
1. Go to Web tab → WSGI configuration file
2. Delete EVERYTHING in the file
3. Paste ONLY the code from Step 6 (starting with `import sys`)
4. Make sure it ends with `from dashboard.app import app as application`
5. Save and click "Reload" on Web tab

### Error: "Site not found"
- Go to Web tab and click "Reload"
- Check WSGI file has correct username

### Error: "Import error"
- Go to Bash console
- Run: `cd TrackingDashboard && pip3.10 install --user flask requests python-dotenv`

### Can't generate API keys
- Check admin password is correct
- Make sure dashboard URL starts with `https://`
- Verify dashboard is running (visit the URL in browser)

### Dashboard shows errors
- Click "Error log" link on Web tab
- Check for Python errors
- Common fix: Check file paths in WSGI config

---

## Need Help?

- PythonAnywhere Forums: https://www.pythonanywhere.com/forums/
- Your deployment package: `deployment_package/`
- API documentation: `API_README.md`
- Full guide: `DEPLOYMENT_GUIDE.md`

---

## Next: Monitor Your Dashboard

View logs on PythonAnywhere:
1. Go to **"Web"** tab
2. Click **"Log files"**
3. Check `error.log` and `server.log` for any issues

**Your dashboard URL**: `https://ballerquotes.pythonanywhere.com`
