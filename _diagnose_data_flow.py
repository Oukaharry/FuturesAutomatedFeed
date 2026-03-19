#!/usr/bin/env python3
"""
Targeted diagnostic: Test the exact /api/data flow for a specific client.
Run on server: python _diagnose_data_flow.py "Chris Ream"
"""
import sys, os, json, traceback

sys.path.insert(0, '.')

client = sys.argv[1] if len(sys.argv) > 1 else 'Chris Ream'
print(f"Testing data flow for: {client}")
print("=" * 70)

# 1. Test raw data retrieval
print("\n[1] get_client_data")
try:
    from dashboard.database import get_client_data
    data = get_client_data(client)
    if data is None:
        print(f"    RESULT: None — client has no data!")
        sys.exit(1)
    evals = data.get('evaluations', [])
    print(f"    Evaluations: {len(evals)}")
    if evals:
        for i, ev in enumerate(evals[:3]):
            pf = ev.get('Prop Firm', '')
            sp1 = ev.get('Status P1', '')
            acct = ev.get('Account #', '')
            deleted = ev.get('_deleted', False)
            print(f"    [{i}] Prop={pf!r} Status={sp1!r} Acct={acct!r} _deleted={deleted}")
        if len(evals) > 3:
            print(f"    ... and {len(evals) - 3} more rows")
    else:
        print("    NO EVALUATIONS — this is why table is empty!")
except Exception as e:
    print(f"    FAILED: {e}")
    traceback.print_exc()

# 2. Test notes injection
print("\n[2] Notes injection")
try:
    from dashboard.notes_service import get_client_notes
    notes = get_client_notes(client)
    print(f"    Notes: {len(notes)} rows have notes")
except Exception as e:
    print(f"    FAILED: {e}")
    traceback.print_exc()

# 3. Test activity injection
print("\n[3] Activity injection")
try:
    from dashboard.database import get_client_activity
    activity = get_client_activity(client)
    print(f"    Activity: {activity}")
except Exception as e:
    print(f"    FAILED: {e}")
    traceback.print_exc()

# 4. Test full JSON response
print("\n[4] Full JSON serialization")
try:
    data['status'] = 'success'
    try:
        from dashboard.database import get_next_version
        data['_version'] = get_next_version(client) - 1
    except Exception:
        pass
    try:
        data['_activity'] = get_client_activity(client)
    except Exception:
        pass
    
    json_str = json.dumps(data)
    print(f"    JSON size: {len(json_str):,} bytes")
    print(f"    Top-level keys: {list(data.keys())}")
    
    # Check evaluations in JSON
    parsed = json.loads(json_str)
    print(f"    Evaluations in JSON: {len(parsed.get('evaluations', []))}")
except Exception as e:
    print(f"    SERIALIZATION FAILED: {e}")
    traceback.print_exc()
    # Find the bad key
    for key in list(data.keys()):
        try:
            json.dumps({key: data[key]})
        except Exception as e2:
            print(f"    Bad key: {key} -> {e2}")
            val = data[key]
            if isinstance(val, (list, dict)):
                if isinstance(val, list):
                    for i, item in enumerate(val):
                        try:
                            json.dumps(item)
                        except:
                            print(f"      Bad item [{i}]: {type(item)}")
                            if isinstance(item, dict):
                                for k, v in item.items():
                                    try:
                                        json.dumps({k: v})
                                    except:
                                        print(f"        Bad field: {k} = {type(v)} = {repr(v)[:80]}")

# 5. Test Flask endpoint directly
print("\n[5] Flask test client")
try:
    from dashboard.app import app
    # Create a fake session for super_admin
    from dashboard.database import create_session
    token = create_session('super_admin', 'super_admin', '127.0.0.1')
    print(f"    Created test session: {token[:20]}...")
    
    with app.test_client() as tc:
        # Set session cookie
        tc.set_cookie('session_token', token, domain='localhost')
        
        resp = tc.get(f'/api/data?client_id={client}')
        print(f"    Response status: {resp.status_code}")
        
        if resp.status_code == 200:
            rdata = resp.get_json()
            if rdata:
                print(f"    Response status field: {rdata.get('status')}")
                print(f"    Evaluations in response: {len(rdata.get('evaluations', []))}")
                print(f"    Has _activity: {'_activity' in rdata}")
                print(f"    Has _version: {'_version' in rdata}")
                if rdata.get('evaluations'):
                    ev0 = rdata['evaluations'][0]
                    print(f"    First eval keys: {list(ev0.keys())[:10]}")
                elif rdata.get('message'):
                    print(f"    Message: {rdata['message']}")
            else:
                print(f"    Response body: {resp.data[:500]}")
        else:
            print(f"    Error response: {resp.data[:500]}")
except Exception as e:
    print(f"    FAILED: {e}")
    traceback.print_exc()

# 6. Check if the template renders
print("\n[6] Template check")
try:
    from dashboard.app import app
    with app.test_client() as tc:
        tc.set_cookie('session_token', token, domain='localhost')
        resp = tc.get(f'/dashboard/{client}')
        print(f"    Dashboard page status: {resp.status_code}")
        html = resp.data.decode('utf-8', errors='replace')
        print(f"    HTML size: {len(html):,} bytes")
        
        # Check for JS syntax errors in the rendered HTML
        # Look for the validateBeforeSave function
        if 'validateBeforeSave' in html:
            print(f"    validateBeforeSave: FOUND")
        else:
            print(f"    validateBeforeSave: NOT FOUND — code may not be deployed!")
            
        if 'renderActivityIndicators' in html:
            print(f"    renderActivityIndicators: FOUND")
        else:
            print(f"    renderActivityIndicators: NOT FOUND")

        if 'downloadCSV' in html:
            print(f"    downloadCSV: FOUND")
        else:
            print(f"    downloadCSV: NOT FOUND")

        # Check for template errors
        if 'Internal Server Error' in html or 'Traceback' in html:
            print(f"    *** TEMPLATE ERROR DETECTED ***")
            # Find the error
            idx = html.find('Traceback')
            if idx > 0:
                print(f"    {html[idx:idx+500]}")
        
        # Check for unclosed Jinja blocks
        if '{%' in html and '%}' in html:
            print(f"    Jinja tags still in output: possible template error")
        
except Exception as e:
    print(f"    FAILED: {e}")
    traceback.print_exc()

# 7. Check PythonAnywhere error log
print("\n[7] Error logs")
home = os.path.expanduser('~')
log_files = []
try:
    for f in os.listdir(home):
        if f.endswith('.log'):
            log_files.append(os.path.join(home, f))
except:
    pass

# Also check common PA paths
for p in [f'{home}/error.log', f'{home}/access.log',
          '/var/log/ballerquotes.pythonanywhere.com.error.log',
          '/var/log/www.tradeopss.com.error.log']:
    if os.path.isfile(p) and p not in log_files:
        log_files.append(p)

if log_files:
    for lf in log_files:
        print(f"    Log: {lf} ({os.path.getsize(lf):,} bytes)")
        try:
            with open(lf) as f:
                lines = f.readlines()[-15:]
                for line in lines:
                    l = line.strip()
                    if l:
                        print(f"      {l}")
        except:
            pass
else:
    print("    No log files found")

print("\n" + "=" * 70)
print("DONE — share this output")
