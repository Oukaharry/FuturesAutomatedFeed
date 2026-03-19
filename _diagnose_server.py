#!/usr/bin/env python3
"""
Server Diagnostic Script — Run on PythonAnywhere to diagnose why client data is not loading.

Usage: python _diagnose_server.py
"""
import sys, os, json, traceback

print("=" * 70)
print("MT5 HEDGING ENGINE — SERVER DIAGNOSTIC")
print("=" * 70)

# 1. Check Python + working directory
print(f"\n[1] Environment")
print(f"    Python: {sys.version}")
print(f"    CWD:    {os.getcwd()}")
print(f"    Script: {os.path.abspath(__file__)}")

# 2. Check key files exist
print(f"\n[2] File Checks")
key_files = [
    'dashboard/app.py',
    'dashboard/database.py',
    'dashboard/templates/index.html',
    'dashboard/templates/quality_dashboard.html',
    'config/hierarchy.py',
]
for f in key_files:
    exists = os.path.isfile(f)
    size = os.path.getsize(f) if exists else 0
    status = f"OK ({size:,} bytes)" if exists else "MISSING!"
    print(f"    {f}: {status}")

# 3. Check database file
print(f"\n[3] Database")
db_paths = [
    'dashboard/dashboard.db',
    'data/dashboard.db',
    'dashboard.db',
]
db_found = None
for dp in db_paths:
    if os.path.isfile(dp):
        db_found = dp
        print(f"    Found: {dp} ({os.path.getsize(dp):,} bytes)")
        break
if not db_found:
    # Search for it
    import glob
    dbs = glob.glob('**/*.db', recursive=True)
    if dbs:
        for d in dbs[:5]:
            print(f"    Found: {d} ({os.path.getsize(d):,} bytes)")
        db_found = dbs[0]
    else:
        print("    NO DATABASE FILE FOUND!")

# 4. Try importing the app
print(f"\n[4] App Import Test")
try:
    sys.path.insert(0, '.')
    from dashboard.app import app
    print("    dashboard.app imported OK")
    
    # List quality-related routes
    quality_routes = [r.rule for r in app.url_map.iter_rules() 
                      if 'quality' in r.rule or 'import_csv' in r.rule or 'scorecard' in r.rule]
    print(f"    New routes registered: {len(quality_routes)}")
    for r in quality_routes:
        print(f"      {r}")
except Exception as e:
    print(f"    IMPORT FAILED: {e}")
    traceback.print_exc()

# 5. Try database operations
print(f"\n[5] Database Operations Test")
try:
    from dashboard.database import init_database
    init_database()
    print("    init_database() OK")
except Exception as e:
    print(f"    init_database() FAILED: {e}")
    traceback.print_exc()

try:
    from dashboard.database import get_client_data
    # Pick a test client
    from config.hierarchy import get_all_clients
    all_clients = get_all_clients()
    print(f"    Total clients in hierarchy: {len(all_clients)}")
    
    if all_clients:
        test_client = all_clients[0]
        print(f"    Testing get_client_data('{test_client}')...")
        data = get_client_data(test_client)
        if data is None:
            print(f"    Result: None (no data for this client)")
        elif data:
            evals = data.get('evaluations', [])
            print(f"    Result: OK — {len(evals)} evaluations, keys: {list(data.keys())[:8]}")
        else:
            print(f"    Result: Empty dict/falsy")
except Exception as e:
    print(f"    get_client_data FAILED: {e}")
    traceback.print_exc()

# 6. Test get_client_activity (new function)
print(f"\n[6] Activity Function Test")
try:
    from dashboard.database import get_client_activity
    if all_clients:
        activity = get_client_activity(all_clients[0])
        print(f"    get_client_activity('{all_clients[0]}'): {activity}")
    else:
        print("    No clients to test with")
except Exception as e:
    print(f"    get_client_activity FAILED: {e}")
    traceback.print_exc()

# 7. Check if new tables exist
print(f"\n[7] New Tables Check")
try:
    import sqlite3
    if db_found:
        conn = sqlite3.connect(db_found)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"    All tables: {tables}")
        
        new_tables = ['quality_scan_results', 'daily_checklists']
        for t in new_tables:
            if t in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {t}")
                count = cursor.fetchone()[0]
                print(f"    {t}: EXISTS ({count} rows)")
            else:
                print(f"    {t}: MISSING — needs init_database()")
        
        # Check data_history table for the change_source column
        cursor.execute("PRAGMA table_info(data_history)")
        cols = [row[1] for row in cursor.fetchall()]
        print(f"    data_history columns: {cols}")
        if 'change_source' in cols:
            print(f"    change_source column: OK")
        else:
            print(f"    change_source column: MISSING — activity queries will fail!")
        
        conn.close()
except Exception as e:
    print(f"    Table check FAILED: {e}")
    traceback.print_exc()

# 8. Simulate the /api/data endpoint logic
print(f"\n[8] Simulate /api/data Response")
try:
    from dashboard.database import get_client_data, get_client_notes
    if all_clients:
        test_client = all_clients[0]
        data = get_client_data(test_client)
        if data:
            # Inject notes (same as endpoint)
            try:
                notes = get_client_notes(test_client)
                for i, ev in enumerate(data.get('evaluations', [])):
                    if i in notes:
                        ev['_notes'] = notes[i]
                print(f"    Note injection: OK")
            except Exception as e:
                print(f"    Note injection FAILED: {e}")
                traceback.print_exc()

            # Version injection
            try:
                from dashboard.database import get_next_version
                ver = get_next_version(test_client) - 1
                data['_version'] = ver
                print(f"    Version injection: OK (version={ver})")
            except Exception as e:
                print(f"    Version injection FAILED: {e}")
                traceback.print_exc()

            # Activity injection  
            try:
                from dashboard.database import get_client_activity
                data['_activity'] = get_client_activity(test_client)
                print(f"    Activity injection: OK")
            except Exception as e:
                print(f"    Activity injection FAILED: {e}")
                traceback.print_exc()

            # Try json serialization (this is what jsonify does)
            try:
                data['status'] = 'success'
                json_str = json.dumps(data)
                print(f"    JSON serialization: OK ({len(json_str):,} bytes)")
            except Exception as e:
                print(f"    JSON serialization FAILED: {e}")
                traceback.print_exc()
                # Find the non-serializable value
                for key, val in data.items():
                    try:
                        json.dumps({key: val})
                    except:
                        print(f"    → Non-serializable key: '{key}' = {type(val)}")
                        if isinstance(val, dict):
                            for k2, v2 in val.items():
                                try:
                                    json.dumps({k2: v2})
                                except:
                                    print(f"      → Nested non-serializable: '{k2}' = {type(v2)} = {repr(v2)[:100]}")
        else:
            print(f"    No data for {test_client}")
except Exception as e:
    print(f"    Simulation FAILED: {e}")
    traceback.print_exc()

# 9. Check the quality scan function can load without error
print(f"\n[9] Quality Scan Function Check")
try:
    # Just check it imports, don't run it
    from config.hierarchy import get_all_clients as hgac, get_client_profile
    print(f"    hierarchy imports: OK")
    profile = get_client_profile(all_clients[0]) if all_clients else None
    print(f"    get_client_profile: {profile}")
except Exception as e:
    print(f"    FAILED: {e}")
    traceback.print_exc()

# 10. Check server error log if available
print(f"\n[10] Recent Error Log")
log_paths = [
    '/var/log/tradeopss.com.error.log',
    '/home/Oukaharry/error.log',
    'error.log',
]
for lp in log_paths:
    if os.path.isfile(lp):
        print(f"    Found: {lp}")
        try:
            with open(lp, 'r') as f:
                lines = f.readlines()
                last_lines = lines[-30:] if len(lines) > 30 else lines
                for line in last_lines:
                    line = line.strip()
                    if line:
                        print(f"      {line}")
        except Exception as e:
            print(f"    Could not read: {e}")
        break
else:
    # Try PythonAnywhere specific paths
    pa_logs = []
    home = os.path.expanduser('~')
    for f in os.listdir(home) if os.path.isdir(home) else []:
        if 'error' in f.lower() and f.endswith('.log'):
            pa_logs.append(os.path.join(home, f))
    if pa_logs:
        for lp in pa_logs[:2]:
            print(f"    Found: {lp}")
            try:
                with open(lp, 'r') as f:
                    lines = f.readlines()[-20:]
                    for line in lines:
                        if line.strip():
                            print(f"      {line.strip()}")
            except:
                pass
    else:
        print("    No error log found. Check PythonAnywhere 'Error log' tab.")

print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
print("\nCopy-paste the full output above and share it so I can identify the issue.")
