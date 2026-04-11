import sqlite3, json

conn = sqlite3.connect('dashboard/dashboard.db')
cursor = conn.cursor()
cursor.execute('SELECT evaluations FROM clients_data WHERE client_id = ?', ('Chris',))
row = cursor.fetchone()
if row:
    evals = json.loads(row[0])
    print(f"Total evaluations: {len(evals)}")
    
    # Check specific eval indices from the logs - these are the ones that got FA data
    targets = {
        392: 'V2-2641/6337 (Topstep FA)',
        445: 'FNFT-76770 (FA)',
        446: 'FNFT-46494 (FA)',
        448: 'TDF-57582 (FA)',
        449: 'TDF-33548 (FA)',
    }
    
    # Also check the ones with "No evaluation found" - MFFU-80230
    # And the skipped inactive ones
    unmatched = {
        394: 'MFFU-80229 (skipped inactive)',
        408: 'MFFU-80233 (skipped inactive)',
        426: 'MFFU-80237 (skipped inactive)',
        423: 'V2-1753 (skipped inactive)',
        424: 'V2-2531 (skipped inactive)',
        415: 'TDF-20330 (skipped inactive)',
        417: 'TDF-79051 (skipped inactive)',
        277: 'FNFT-23825 (skipped inactive)',
        282: 'FNFT-62524 (skipped inactive)',
        447: 'TDF-59522 (skipped inactive)',
    }
    
    print("\n" + "="*70)
    print("ACTIVE ACCOUNTS WITH FA DATA WRITTEN:")
    print("="*70)
    for idx, label in sorted(targets.items()):
        if idx < len(evals):
            ev = evals[idx]
            print(f"\n--- eval_idx={idx} row={idx+2} ({label}) ---")
            print(f"  Prop Firm: {ev.get('Prop Firm')}")
            print(f"  Account #: {ev.get('Account #')}")
            print(f"  Account #.1: {ev.get('Account #.1')}")
            print(f"  Status P1: {ev.get('Status P1')}")
            status = ev.get('Status') or ev.get('Status Funded', '')
            print(f"  Status: {status}")
            for d in range(1, 15):
                val = ev.get(f"Hedge Day {d}")
                date_val = ev.get(f"_Hedge Day {d} Date")
                if val and val not in ('', 0, '$0.00'):
                    print(f"  Hedge Day {d}: {val}  (date: {date_val})")
                elif date_val:
                    print(f"  Hedge Day {d}: EMPTY  (date: {date_val})")

    print("\n" + "="*70)
    print("SKIPPED (INACTIVE) FA ACCOUNTS - checking for stale data:")
    print("="*70)
    for idx, label in sorted(unmatched.items()):
        if idx < len(evals):
            ev = evals[idx]
            print(f"\n--- eval_idx={idx} row={idx+2} ({label}) ---")
            print(f"  Prop Firm: {ev.get('Prop Firm')}")
            print(f"  Account #: {ev.get('Account #')}")
            print(f"  Status P1: {ev.get('Status P1')}")
            status = ev.get('Status') or ev.get('Status Funded', '')
            print(f"  Status: {status}")
            has_farming = False
            for d in range(1, 15):
                val = ev.get(f"Hedge Day {d}")
                if val and val not in ('', 0, '$0.00'):
                    has_farming = True
                    print(f"  Hedge Day {d}: {val}")
            if not has_farming:
                print(f"  (no farming data)")

    # Also search for account 80230 which never matched
    print("\n" + "="*70)
    print("SEARCHING FOR ACCOUNT 80230 (never matched to any eval):")
    print("="*70)
    for i, ev in enumerate(evals):
        acc = str(ev.get('Account #', ''))
        acc1 = str(ev.get('Account #.1', ''))
        if '80230' in acc or '80230' in acc1:
            print(f"  FOUND at eval_idx={i} row={i+2}")
            print(f"    Prop Firm: {ev.get('Prop Firm')}")
            print(f"    Account #: {acc}")
            print(f"    Account #.1: {acc1}")
            print(f"    Status P1: {ev.get('Status P1')}")
            status = ev.get('Status') or ev.get('Status Funded', '')
            print(f"    Status: {status}")
            for d in range(1, 15):
                val = ev.get(f"Hedge Day {d}")
                if val and val not in ('', 0, '$0.00'):
                    print(f"    Hedge Day {d}: {val}")

conn.close()
