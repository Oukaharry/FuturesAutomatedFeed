"""
Extract auth token from running Tradovate Selenium instance, then probe API.
Uses remote debugging on Selenium's Chrome instances.
"""
import subprocess
import json
import re
import os

# Step 1: Find Selenium Chrome instances with debug ports
print("=== Finding Chrome processes ===")
# Get-Process with WMI for full command line
result = subprocess.run(
    ["powershell", "-c", 
     "Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" | "
     "Where-Object { $_.CommandLine -match 'remote-debugging-port|user-data-dir' } | "
     "Select-Object ProcessId, CommandLine | Format-List"],
    capture_output=True, text=True, timeout=10
)
print(result.stdout[:3000] if result.stdout else "No matching Chrome processes")

# Step 2: Find temp user-data-dirs (Selenium creates these)
print("\n=== Selenium temp directories ===")
temp_dir = os.environ.get("TEMP", r"C:\Users\harry\AppData\Local\Temp")
scoped_dirs = []
try:
    for d in os.listdir(temp_dir):
        if d.startswith("scoped_dir") and os.path.isdir(os.path.join(temp_dir, d)):
            full = os.path.join(temp_dir, d)
            # Check if Chrome is using it (has Default/Session Storage)
            ss_path = os.path.join(full, "Default", "Session Storage")
            ls_path = os.path.join(full, "Default", "Local Storage", "leveldb")
            if os.path.exists(ss_path) or os.path.exists(ls_path):
                scoped_dirs.append(full)
                print(f"  {d} (has session data)")
except Exception as e:
    print(f"  Error scanning temp: {e}")

# Step 3: Try to read cookies/storage from the LevelDB files
# LevelDB .log files often contain readable strings including tokens
print("\n=== Scanning for auth tokens in session storage ===")
for sd in scoped_dirs:
    ls_dir = os.path.join(sd, "Default", "Local Storage", "leveldb")
    ss_dir = os.path.join(sd, "Default", "Session Storage")
    
    for storage_dir in [ls_dir, ss_dir]:
        if not os.path.exists(storage_dir):
            continue
        for fname in os.listdir(storage_dir):
            fpath = os.path.join(storage_dir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, "rb") as f:
                    raw = f.read()
                # Search for tokens
                text = raw.decode("utf-8", errors="ignore")
                
                # Look for accessToken pattern
                token_matches = re.findall(r'accessToken["\s:]+([a-zA-Z0-9_\-\.]+)', text)
                if token_matches:
                    dirname = os.path.basename(sd)
                    storage_type = "LocalStorage" if "Local" in storage_dir else "SessionStorage"
                    print(f"\n  [{dirname}/{storage_type}/{fname}]")
                    for t in token_matches:
                        if len(t) > 20:
                            print(f"    Token: {t[:50]}...")
                
                # Look for Tradovate URLs to identify which instance this is
                trado_urls = re.findall(r'(https?://[^\s"]+tradovate[^\s"]*)', text)
                if trado_urls and token_matches:
                    for u in set(trado_urls)[:3]:
                        print(f"    URL: {u[:80]}")
                        
                # Also look for account names
                acct_matches = re.findall(r'(FNFT\w+|TDFY\w+|MFFU\w+|ELTD\w+|LTTZ\w+)', text)
                if acct_matches:
                    dirname = os.path.basename(sd)
                    print(f"\n  [{dirname}/{fname}] Account names: {sorted(set(acct_matches))[:5]}")
                    
            except Exception as e:
                pass

# Step 4: Check cookies for Tradovate
print("\n\n=== Scanning cookies ===")
for sd in scoped_dirs:
    cookies_path = os.path.join(sd, "Default", "Cookies")
    if os.path.exists(cookies_path):
        # SQLite cookie database
        try:
            import sqlite3
            conn = sqlite3.connect(cookies_path)
            cur = conn.cursor()
            cur.execute("SELECT host_key, name, value FROM cookies WHERE host_key LIKE '%tradovate%'")
            rows = cur.fetchall()
            if rows:
                dirname = os.path.basename(sd)
                print(f"\n  [{dirname}] Tradovate cookies:")
                for host, name, value in rows:
                    print(f"    {host} | {name} = {value[:50] if value else '(empty)'}...")
            conn.close()
        except Exception as e:
            pass
