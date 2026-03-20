"""Find and restore Jmark's evaluations on production via API"""
import requests, json

BASE = "https://www.tradeopss.com"
EMAIL = "traderjmark@gmail.com"

# Step 1: Get version history
print(f"Fetching version history for {EMAIL}...")
r = requests.post(f"{BASE}/api/client/history", json={"email": EMAIL, "limit": 50})
if r.status_code != 200:
    print(f"History API failed: {r.status_code} {r.text[:300]}")
    exit(1)

data = r.json()
history = data.get('history', [])
client_id = data.get('client_id', '?')
print(f"Client: {client_id}, Total versions: {len(history)}\n")

print(f"{'Ver':>5} | {'Date':<22} | {'Action':<15} | {'Source':<20} | {'Changed By':<25} | Description")
print("-" * 130)

for v in history:
    ver = v.get('version', '?')
    date = v.get('created_at', '?')
    action = v.get('action', '?')
    source = v.get('change_source', '') or ''
    by = v.get('changed_by', '?') or '?'
    desc = (v.get('change_description', '') or '')[:60]
    print(f"{ver:>5} | {date:<22} | {action:<15} | {source:<20} | {by:<25} | {desc}")

# Step 2: Check each version for eval count (most recent first)
print(f"\nChecking eval counts per version...")
best_ver = None
best_count = 0

for v in history[:20]:  # check last 20 versions
    ver = v.get('version')
    r2 = requests.post(f"{BASE}/api/client/version", json={"email": EMAIL, "version": ver})
    if r2.status_code == 200:
        vdata = r2.json().get('data', {})
        evals = vdata.get('evaluations', [])
        count = len(evals)
        marker = ""
        if count > best_count:
            best_count = count
            best_ver = ver
            marker = " <-- BEST"
        print(f"  v{ver}: {count} evaluations{marker}")

print(f"\n{'='*60}")
if best_ver:
    print(f"BEST VERSION: v{best_ver} with {best_count} evaluations")
    answer = input(f"\nRollback to v{best_ver}? (yes/no): ")
    if answer.strip().lower() == 'yes':
        r3 = requests.post(f"{BASE}/api/client/rollback", json={
            "email": EMAIL,
            "version": best_ver
        })
        print(f"Rollback response: {r3.status_code}")
        print(json.dumps(r3.json(), indent=2))
    else:
        print("Skipped.")
else:
    print("No version with evaluations found.")
