"""Restore original dashboard account values that were cleared by our audit scripts.
Only log-derived accounts should use the PREFIX-XXXXX format.
Dashboard-original accounts (any format) should be kept as-is."""
import json, re, sqlite3
from collections import Counter

DB_PATH = 'dashboard/dashboard.db'

db = sqlite3.connect(DB_PATH)
cur = db.cursor()

# Get current state
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
current_evals = json.loads(cur.fetchone()[0])

# Get all versions to find the state BEFORE our audit scripts ran
cur.execute("SELECT version, evaluations, created_at, change_description FROM data_history WHERE client_id='Chris' ORDER BY version DESC")
versions = cur.fetchall()
db.close()

print(f'Total versions: {len(versions)}')
for v, _, ts, desc in versions[:10]:
    print(f'  v{v}: {ts} - {(desc or "")[:80]}')

# The pre-audit state is the version just before we started running _deep_log_v2.py
# Let's check the most recent few versions to find it
print(f'\n=== Checking recent versions for account state ===')
for v, evals_json, ts, desc in versions[:5]:
    try:
        ver_evals = json.loads(evals_json)
    except:
        continue
    # Count non-empty accounts
    non_empty_a = sum(1 for ev in ver_evals if (ev.get('Account #') or '').strip())
    non_empty_a1 = sum(1 for ev in ver_evals if (ev.get('Account #.1') or '').strip())
    print(f'  v{v}: {len(ver_evals)} evals, {non_empty_a} Acct#, {non_empty_a1} Acct#.1  ({ts})')
