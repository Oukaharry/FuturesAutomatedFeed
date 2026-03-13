"""Check the actual API response for Ed - verify _notes presence"""
import json, requests

# Hit the local API the same way the frontend does
# First we need to get a session - simulate login
s = requests.Session()

# Try to get the data endpoint directly 
resp = s.get('http://localhost:5001/api/data', params={'client_id': 'Ed'})
print(f"Status: {resp.status_code}")

if resp.status_code == 200:
    data = resp.json()
    evals = data.get('evaluations', [])
    print(f"Evaluations count: {len(evals)}")
    
    # Count how many evals have _notes
    notes_count = sum(1 for e in evals if '_notes' in e)
    print(f"Evals with _notes: {notes_count}")
    
    # Check specific indices known to have notes
    for idx in [249, 536, 770, 854]:
        if idx < len(evals):
            ev = evals[idx]
            has_notes = '_notes' in ev
            note_keys = list(ev.get('_notes', {}).keys()) if has_notes else []
            prop_progress = {k: v for k, v in ev.get('_notes', {}).items() if k.startswith('Prop Day')}
            print(f"  [{idx}] _notes={has_notes}, prop_progress={prop_progress}")
elif resp.status_code == 401:
    print("Need authentication. Trying with session...")
    # Login first
    login_resp = s.post('http://localhost:5001/login', data={'username': 'admin', 'password': 'admin'})
    print(f"Login status: {login_resp.status_code}")
    resp = s.get('http://localhost:5001/api/data', params={'client_id': 'Ed'})
    print(f"After login - Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        evals = data.get('evaluations', [])
        notes_count = sum(1 for e in evals if '_notes' in e)
        print(f"Evals with _notes: {notes_count}")
else:
    print(f"Response: {resp.text[:500]}")
