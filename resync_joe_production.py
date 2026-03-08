"""
Post-deploy resync script: triggers Joe's data reimport on the production server.
Run this AFTER uploading the fixed data_processor.py to PythonAnywhere and reloading the web app.

Usage:
    python resync_joe_production.py <PRODUCTION_URL>

Example:
    python resync_joe_production.py https://harrytrader.pythonanywhere.com
"""
import sys
import requests

SHEET_URL = "https://docs.google.com/spreadsheets/d/1J-pZGelB9DxtahUc1JL3IXkT5C2_ajd_qvE_oqxUia4/edit?usp=sharing"
JOE_EMAIL = "joehickenfpf@gmail.com"

if len(sys.argv) < 2:
    print("Usage: python resync_joe_production.py <PRODUCTION_URL>")
    print("Example: python resync_joe_production.py https://harrytrader.pythonanywhere.com")
    sys.exit(1)

production_url = sys.argv[1].rstrip('/')

print(f"Target: {production_url}")
print(f"Email:  {JOE_EMAIL}")
print(f"Sheet:  {SHEET_URL}")
print()
print("Calling /api/client/migrate_sheet ...")

try:
    response = requests.post(
        f"{production_url}/api/client/migrate_sheet",
        json={"email": JOE_EMAIL, "sheet_url": SHEET_URL},
        headers={"Content-Type": "application/json"},
        timeout=120
    )

    print(f"Status: {response.status_code}")
    try:
        data = response.json()
        print(f"Response: {data}")
        if response.status_code == 200:
            print("\n✅ Resync succeeded.")
        else:
            print(f"\n❌ Resync failed: {data.get('message', 'Unknown error')}")
    except Exception:
        print(f"Response text: {response.text[:500]}")

except requests.exceptions.ConnectionError:
    print(f"❌ Could not connect to {production_url}")
except requests.exceptions.Timeout:
    print("❌ Request timed out (server may still be processing)")
