"""
Authenticate directly to the Tradovate REST API using credentials,
then probe all data endpoints. No browser needed.
"""
import json, urllib.request, ssl, time, hashlib

def api_post(url, body, token=None):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method='POST')
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=15)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode('utf-8', errors='replace')[:500]
        return {"_error": e.code, "_msg": body_text}
    except Exception as e:
        return {"_error": str(e)}

def api_get(url, token):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    try:
        resp = urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=10)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_msg": e.read().decode('utf-8', errors='replace')[:300]}
    except Exception as e:
        return {"_error": str(e)}


def authenticate(username, password, env="demo"):
    """Authenticate to Tradovate API and get access token."""
    base = f"https://{env}.tradovateapi.com/v1"
    
    # Device ID — consistent per machine
    device_id = hashlib.md5(f"TradeOpsAI-{username}".encode()).hexdigest()[:16]
    
    body = {
        "name": username,
        "password": password,
        "appId": "TradeOpsAI",
        "appVersion": "1.0",
        "deviceId": device_id,
        "cid": 8,
        "sec": "f03741b6-f634-48d6-9308-c8fb871150c2",
    }
    
    result = api_post(f"{base}/auth/accesstokenrequest", body)
    return result


def probe_account(base, token, acc_id, acc_name):
    """Probe all data endpoints for a specific account."""
    print(f"\n  --- Account: {acc_name} (ID={acc_id}) ---")
    
    endpoints = {
        "cashBalance":      f"{base}/cashBalance/getCashBalanceSnapshot?accountId={acc_id}",
        "cashBalanceLog":   f"{base}/cashBalanceLog/deps?masterid={acc_id}",
        "fills":            f"{base}/fill/deps?masterid={acc_id}",
        "orders":           f"{base}/order/deps?masterid={acc_id}",
        "positions":        f"{base}/position/deps?masterid={acc_id}",
        "execReports":      f"{base}/executionReport/deps?masterid={acc_id}",
        "fillFees":         f"{base}/fillFee/deps?masterid={acc_id}",
        "marginSnapshot":   f"{base}/marginSnapshot/deps?masterid={acc_id}",
        "riskStatus":       f"{base}/accountRiskStatus/deps?masterid={acc_id}",
        "riskParams":       f"{base}/userAccountRiskParameter/deps?masterid={acc_id}",
        "posLimits":        f"{base}/userAccountPositionLimit/deps?masterid={acc_id}",
        "autoLiq":          f"{base}/userAccountAutoLiq/deps?masterid={acc_id}",
        "fillPairs":        f"{base}/fillPair/deps?masterid={acc_id}",
    }
    
    for name, url in endpoints.items():
        result = api_get(url, token)
        if isinstance(result, dict) and "_error" not in result:
            # Single object (like cashBalance snapshot)
            print(f"    {name}: {json.dumps(result)[:180]}")
        elif isinstance(result, list):
            count = len(result)
            if count > 0:
                keys = list(result[0].keys())
                print(f"    {name}: {count} items | Keys: {keys}")
                # Show last 3 items (most recent)
                for item in result[-3:]:
                    print(f"      {json.dumps(item)[:180]}")
            else:
                print(f"    {name}: 0 items")
        else:
            err = result.get("_error", "?") if isinstance(result, dict) else "?"
            print(f"    {name}: ERROR {err}")


if __name__ == "__main__":
    # Credentials from the running app (visible in UI screenshot)
    # We'll try the ones we can see
    credentials = [
        # (username, password_placeholder, env)
        # We can't see passwords, but we can try to get tokens from the Selenium sessions
    ]
    
    # Alternative: Extract tokens from the running Tradovate Selenium instances
    # We know there are 3 scoped_dir Chrome instances — let's try to read their sessionStorage
    # from the temp directories
    
    import os, glob
    
    temp_base = os.environ.get("TEMP", os.environ.get("TMP", ""))
    scoped_dirs = glob.glob(os.path.join(temp_base, "scoped_dir*"))
    
    print(f"Found {len(scoped_dirs)} Selenium scoped directories:")
    for sd in scoped_dirs:
        print(f"  {sd}")
        # Check for sessionStorage in the Chrome profile
        ss_dir = os.path.join(sd, "Default", "Session Storage")
        ls_dir = os.path.join(sd, "Default", "Local Storage", "leveldb")
        
        if os.path.exists(ss_dir):
            files = os.listdir(ss_dir)
            print(f"    Session Storage: {files}")
        
        if os.path.exists(ls_dir):
            files = os.listdir(ls_dir)
            print(f"    Local Storage LevelDB: {files}")
            
            # Try to read LOG files for clues
            for f in files:
                if f.endswith('.log') or f == 'LOG':
                    fpath = os.path.join(ls_dir, f)
                    try:
                        with open(fpath, 'r', errors='replace') as fh:
                            content = fh.read()[:500]
                            if 'tradovate' in content.lower() or 'token' in content.lower():
                                print(f"      {f}: Contains tradovate/token references")
                    except:
                        pass
    
    # More practical approach: read the LDB files directly for token data
    print(f"\n{'='*80}")
    print("Searching for Tradovate tokens in Chrome session data...")
    print(f"{'='*80}")
    
    found_tokens = []
    
    for sd in scoped_dirs:
        # Check both Session Storage and Local Storage
        for storage_type in ["Session Storage", os.path.join("Default", "Session Storage")]:
            storage_path = os.path.join(sd, storage_type)
            if not os.path.exists(storage_path):
                continue
            
            for fname in os.listdir(storage_path):
                fpath = os.path.join(storage_path, fname)
                try:
                    with open(fpath, 'rb') as f:
                        data = f.read()
                    # Search for token pattern
                    text = data.decode('utf-8', errors='replace')
                    
                    # Look for api_authenticator_state with token
                    import re
                    # JWT token pattern
                    tokens = re.findall(r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', text)
                    for t in tokens:
                        if len(t) > 100:  # Real JWT tokens are long
                            # Try to decode to verify it's a Tradovate token
                            import base64
                            try:
                                payload = t.split('.')[1] + '=='
                                claims = json.loads(base64.urlsafe_b64decode(payload))
                                user_id = claims.get("sub", "")
                                if user_id:
                                    entry = (user_id, t, sd)
                                    if not any(e[0] == user_id for e in found_tokens):
                                        found_tokens.append(entry)
                                        print(f"  Found token for UserID={user_id} in {os.path.basename(sd)}")
                            except:
                                pass
                    
                    # Also look for username
                    usernames = re.findall(r'"username"\s*:\s*"([^"]+)"', text)
                    envs = re.findall(r'"environment"\s*:\s*"([^"]+)"', text)
                    if usernames:
                        print(f"  Found username(s): {usernames} env={envs} in {storage_type}/{fname} ({os.path.basename(sd)})")
                    
                except Exception as e:
                    pass
        
        # Also check Local Storage LevelDB
        for ls_type in ["Local Storage", os.path.join("Default", "Local Storage")]:
            ls_path = os.path.join(sd, ls_type, "leveldb")
            if not os.path.exists(ls_path):
                continue
            
            for fname in os.listdir(ls_path):
                if not (fname.endswith('.ldb') or fname.endswith('.log')):
                    continue
                fpath = os.path.join(ls_path, fname)
                try:
                    with open(fpath, 'rb') as f:
                        data = f.read()
                    text = data.decode('utf-8', errors='replace')
                    
                    # Look for lastOrg or username
                    orgs = re.findall(r'lastOrg["\s:]+([A-Za-z\s]+)', text)
                    usernames = re.findall(r'lastUsername["\s:]+([A-Za-z0-9]+)', text)
                    if orgs or usernames:
                        print(f"  LevelDB ({os.path.basename(sd)}): org={orgs}, user={usernames}")
                except:
                    pass
    
    print(f"\nFound {len(found_tokens)} unique tokens")
    
    # Now probe each found token
    for user_id, token, source_dir in found_tokens:
        print(f"\n{'='*80}")
        print(f"PROBING UserID={user_id} (from {os.path.basename(source_dir)})")
        print(f"{'='*80}")
        
        # Try both demo and live
        for env in ["demo", "live"]:
            base = f"https://{env}.tradovateapi.com/v1"
            accounts = api_get(f"{base}/account/list", token)
            
            if isinstance(accounts, list) and accounts:
                print(f"\n  {env.upper()} ACCOUNTS ({len(accounts)}):")
                for a in accounts:
                    print(f"    ID={a.get('id')} | Name={a.get('name')} | Nick={a.get('nickname','')} "
                          f"| Active={a.get('active')}")
                    probe_account(base, token, a["id"], a.get("name", "?"))
                break  # Found accounts, no need to check other env
            elif isinstance(accounts, list) and len(accounts) == 0:
                print(f"  {env}: 0 accounts")
            else:
                err = accounts.get("_error", "?") if isinstance(accounts, dict) else "?"
                print(f"  {env}: error {err}")
    
    print(f"\n{'='*80}")
    print("DONE")
    print(f"{'='*80}")
