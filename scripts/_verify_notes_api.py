"""Simulate /api/data to verify _notes injection reaches the JSON response"""
from dashboard.database import get_connection
from dashboard.notes_service import get_client_notes
import json

# Simulate get_client_data
with get_connection() as conn:
    cur = conn.cursor()
    cur.execute("SELECT evaluations FROM clients_data WHERE client_id = 'Ed'")
    row = cur.fetchone()
    evals_raw = row[0]
    evals = json.loads(evals_raw) if isinstance(evals_raw, str) else evals_raw

# Simulate note injection (same as app.py lines 4187-4191)
notes = get_client_notes('Ed')
injected = 0
for i, ev in enumerate(evals):
    if i in notes:
        ev['_notes'] = notes[i]
        injected += 1

print(f"Injected _notes into {injected} / {len(evals)} evaluations")

# Check specific rows that have Prop Day notes
for idx in [249, 536, 560]:
    if idx < len(evals):
        ev = evals[idx]
        n = ev.get('_notes', {})
        prop_notes = {k: v for k, v in n.items() if k.startswith('Prop Day')}
        print(f"\n  eval[{idx}] _notes Prop Day keys: {prop_notes}")

# Now simulate JSON serialization (what jsonify does)
# Check if _notes survives JSON round-trip
test_ev = evals[536]
json_str = json.dumps(test_ev)
parsed = json.loads(json_str)
print(f"\nAfter JSON round-trip for eval[536]:")
print(f"  _notes present: {'_notes' in parsed}")
if '_notes' in parsed:
    prop_notes = {k: v for k, v in parsed['_notes'].items() if k.startswith('Prop Day')}
    print(f"  Prop Day notes: {prop_notes}")

# Now check: does the frontend code see ev._notes correctly?
# The issue might be how currentData is loaded
# Check the main data loading function
print("\n--- Checking how data loads ---")
# The /api/data endpoint returns the full data dict
# Let's check what get_client_data returns
from dashboard.database import get_client_data
data = get_client_data('Ed')
print(f"get_client_data type: {type(data)}")
print(f"evaluations count: {len(data.get('evaluations', []))}")

# Inject notes the same way
for i, ev in enumerate(data['evaluations']):
    if i in notes:
        ev['_notes'] = notes[i]

# Check a specific eval
ev536 = data['evaluations'][536]
print(f"eval[536]._notes: {ev536.get('_notes', 'MISSING')}")

# Serialize full response like jsonify would
full_json = json.dumps(data)
full_parsed = json.loads(full_json)
ev536_parsed = full_parsed['evaluations'][536]
print(f"After full JSON round-trip, eval[536]._notes: {ev536_parsed.get('_notes', 'MISSING')}")
