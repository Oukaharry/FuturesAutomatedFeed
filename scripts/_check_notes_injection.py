"""Check if notes injection works correctly for Ed"""
from dashboard.database import get_connection
from dashboard.notes_service import get_client_notes
import json

with get_connection() as conn:
    cur = conn.cursor()
    
    # Get Ed's evaluations
    cur.execute("SELECT evaluations FROM clients_data WHERE client_id = 'Ed'")
    row = cur.fetchone()
    evals = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    if not isinstance(evals, list):
        evals = []
    
    print(f"Ed has {len(evals)} evaluations")
    
    # Get Ed's notes
    notes = get_client_notes('Ed')
    print(f"Notes dict has {len(notes)} rows with notes")
    print(f"Note row indices: {sorted(notes.keys())}")
    
    # Check the types of the keys
    for k in list(notes.keys())[:3]:
        print(f"  Key type: {type(k)}, value: {k}")
    
    # Simulate the injection
    injected_count = 0
    for i, ev in enumerate(evals):
        if i in notes:
            ev['_notes'] = notes[i]
            injected_count += 1
            if injected_count <= 5:
                print(f"  Injected notes for index {i}: keys={list(notes[i].keys())}")
    
    print(f"\nTotal rows with notes injected: {injected_count}")
    
    # Now check a specific row that should have notes
    # Row 249 should have Prop Day 2-6 notes
    if 249 < len(evals):
        ev249 = evals[249]
        print(f"\neval[249] Prop Firm: {ev249.get('Prop Firm')}")
        print(f"eval[249] _notes: {ev249.get('_notes', 'NO _notes key!')}")
    
    # Check rows visible in screenshot (855 = index 854, 846 = index 845, etc.)
    for display_num in [855, 846, 842, 841, 840, 839, 838]:
        idx = display_num - 1  # since # shows index+1
        if idx < len(evals):
            ev = evals[idx]
            has_notes = '_notes' in ev
            note_keys = list(ev.get('_notes', {}).keys()) if has_notes else []
            prop_day1 = ev.get('Prop Day 1', 'N/A')
            print(f"  #{display_num} (idx={idx}): Prop Firm={ev.get('Prop Firm','N/A')}, Prop Day 1={prop_day1}, has_notes={has_notes}, note_keys={note_keys}")
