# DEPLOYMENT CHECKLIST

Use this checklist to track your deployment progress.

## Pre-Deployment
- [ ] All files in `deployment_package/` folder
- [ ] Read `DEPLOYMENT_STEPS.md`
- [ ] Have email ready for PythonAnywhere signup

## PythonAnywhere Setup
- [ ] Created PythonAnywhere account
- [ ] Username: ballerquotes ✓
- [ ] Uploaded all files to `/home/ballerquotes/TrackingDashboard`
- [ ] Installed packages: `pip3.10 install --user flask requests python-dotenv`
- [ ] Set admin password in `~/.bashrc`
- [ ] Admin password: _________________ (write it securely!)

## Web App Configuration
- [ ] Created Flask web app (Python 3.10)
- [ ] Configured WSGI file with correct username and password
- [ ] Clicked "Reload" button
- [ ] Dashboard loads in browser: https://ballerquotes.pythonanywhere.com

## Testing
- [ ] Ran test script from local machine
- [ ] Health check returns "ok"
- [ ] Can access login page

## API Keys
- [ ] Generated API key for trader: Philip
- [ ] Generated API key for trader: Samuel  
- [ ] Generated API key for trader: Max
- [ ] Generated API key for trader: ________________
- [ ] Saved all keys in `api_keys_generated.txt`

## Trader Integration
- [ ] Sent Philip his API key and instructions
- [ ] Sent Samuel his API key and instructions
- [ ] Sent Max his API key and instructions
- [ ] Sent ________ his API key and instructions

## Verification
- [ ] At least one trader successfully pushed data
- [ ] Can see trader data in dashboard
- [ ] All traders can login with their emails
- [ ] No errors in PythonAnywhere error.log

## Security
- [ ] Changed admin password from default
- [ ] Added `api_keys.json` to `.gitignore`
- [ ] Instructed traders to keep API keys private
- [ ] Set up regular API key rotation schedule

## Documentation
- [ ] Shared dashboard URL with all stakeholders
- [ ] Created backup of `api_keys.json`
- [ ] Created backup of `dashboard_data.json`
- [ ] Documented who has which API key

---

## Important URLs & Info

**Dashboard URL**: https://ballerquotes.pythonanywhere.com

**Admin Password**: _________________ (keep secure!)

**Files Location**: `/home/ballerquotes/TrackingDashboard`

**Support**: https://www.pythonanywhere.com/forums/

---

## Maintenance Schedule

- [ ] Weekly: Check error logs
- [ ] Monthly: Backup dashboard_data.json
- [ ] Quarterly: Rotate API keys
- [ ] As needed: Generate new keys for new traders

---

When all checkboxes are checked, your deployment is complete! 🎉
