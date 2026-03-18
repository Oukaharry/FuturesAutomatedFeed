"""
Diagnostic script for Hailee Wood — investigate missing dashboard data.
Run on the server: python _debug_hailee.py
"""
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.database import get_client_data, get_data_history, get_data_version

CLIENT_ID = "Hailee Wood"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard', 'dashboard.db')

def main():
    print(f"{'='*80}")
    print(f"  DIAGNOSTIC REPORT: {CLIENT_ID}")
    print(f"{'='*80}\n")

    # 0. Direct DB check — look for ALL client IDs containing "hailee" or "wood"
    print(f"--- STEP 0: Direct DB scan for similar client IDs ---\n")
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        # Check clients_data table
        cur.execute("SELECT client_id, last_updated, length(evaluations) FROM clients_data WHERE lower(client_id) LIKE '%hailee%' OR lower(client_id) LIKE '%wood%'")
        rows = cur.fetchall()
        print(f"  clients_data matches: {len(rows)}")
        for r in rows:
            print(f"    client_id='{r[0]}' | last_updated={r[1]} | eval_json_len={r[2]}")
        
        # Check data_history table
        cur.execute("SELECT client_id, COUNT(*) as versions, MIN(created_at), MAX(created_at) FROM data_history WHERE lower(client_id) LIKE '%hailee%' OR lower(client_id) LIKE '%wood%' GROUP BY client_id")
        rows = cur.fetchall()
        print(f"\n  data_history matches: {len(rows)}")
        for r in rows:
            print(f"    client_id='{r[0]}' | versions={r[1]} | first={r[2]} | last={r[3]}")
        
        # Check user_credentials table
        cur.execute("SELECT username, email, user_type, parent_admin, parent_trader, is_active FROM user_credentials WHERE lower(username) LIKE '%hailee%' OR lower(username) LIKE '%wood%' OR lower(email) LIKE '%hailee%' OR lower(email) LIKE '%wood%'")
        rows = cur.fetchall()
        print(f"\n  user_credentials matches: {len(rows)}")
        for r in rows:
            print(f"    username='{r[0]}' | email='{r[1]}' | type={r[2]} | admin={r[3]} | trader={r[4]} | active={r[5]}")
        
        # Check hierarchy.json too
        hierarchy_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'hierarchy.json')
        if os.path.exists(hierarchy_path):
            with open(hierarchy_path) as f:
                h = json.load(f)
            found = []
            for admin_name, admin_data in h.get('admins', {}).items():
                for trader_name, trader_data in admin_data.get('traders', {}).items():
                    for client in trader_data.get('clients', []):
                        cname = client.get('name', '')
                        if 'hailee' in cname.lower() or 'wood' in cname.lower():
                            found.append((admin_name, trader_name, client))
            print(f"\n  hierarchy.json matches: {len(found)}")
            for admin, trader, cli in found:
                print(f"    admin={admin} | trader={trader} | client={cli}")
        
        conn.close()
    except Exception as e:
        print(f"  DB scan error: {e}")
    
    print()

    # 1. Current live data
    data = get_client_data(CLIENT_ID)
    if not data:
        print("❌ NO DATA FOUND in clients_data table for this client!")
        print("   The client row may have been deleted or never created.\n")
    else:
        print(f"✅ Live data found. Last updated: {data.get('last_updated', 'N/A')}")
        evals = data.get('evaluations', [])
        print(f"   Evaluations count: {len(evals)}")
        for i, ev in enumerate(evals):
            pf = ev.get('Prop Firm', '?')
            acc = ev.get('Account #', '') or ev.get('Account #.1', '')
            size = ev.get('Account Size', '')
            status = ev.get('Status P1', '') or ev.get('Status', '')
            dp = ev.get('Date Purchased', '') or ev.get('Date Started', '')
            # Check for hedge data
            hedge_fields = {k: v for k, v in ev.items() 
                           if k.startswith('Hedge') and v and str(v).strip()}
            print(f"   [{i}] {pf} | {size} | Acc: {acc} | Status: {status} | Date: {dp} | Hedge fields: {len(hedge_fields)}")
            if hedge_fields:
                for hk, hv in sorted(hedge_fields.items()):
                    print(f"        {hk}: {hv}")
        
        # Check other data sections
        deals = data.get('deals', [])
        account = data.get('account', {})
        stats = data.get('statistics', {})
        print(f"\n   Deals stored: {len(deals)}")
        print(f"   Account info: balance={account.get('balance', 'N/A')}")
        print(f"   Statistics keys: {list(stats.keys()) if stats else 'EMPTY'}")
        identity = data.get('identity', {})
        print(f"   Identity: admin={identity.get('admin')}, trader={identity.get('trader')}, client={identity.get('client')}")
        print(f"   Sheet URL: {identity.get('sheet_url', 'N/A')}")

    # 2. Version history
    print(f"\n{'='*80}")
    print(f"  VERSION HISTORY (most recent first)")
    print(f"{'='*80}\n")

    history = get_data_history(CLIENT_ID, limit=100)
    if not history:
        print("❌ NO HISTORY FOUND — no versions recorded for this client.")
        return

    print(f"Total versions: {len(history)}\n")
    print(f"{'Ver':>4} | {'Action':<20} | {'Changed By':<25} | {'Source':<25} | {'Date':<22} | {'Description'}")
    print(f"{'-'*4}-+-{'-'*20}-+-{'-'*25}-+-{'-'*25}-+-{'-'*22}-+-{'-'*30}")
    
    for h in history:
        ver = h.get('version', '?')
        action = h.get('action', '?')
        by = h.get('changed_by', '?')
        by_type = h.get('changed_by_type', '')
        source = h.get('change_source', '')
        desc = h.get('change_description', '')
        date = h.get('created_at', '?')
        print(f"{ver:>4} | {action:<20} | {by} ({by_type}){'':<{max(0, 22-len(str(by))-len(str(by_type)))}} | {str(source):<25} | {str(date):<22} | {desc}")

    # 3. Compare latest vs previous versions — find where data disappeared
    print(f"\n{'='*80}")
    print(f"  DATA CHANGE ANALYSIS — tracking evaluation count across versions")
    print(f"{'='*80}\n")

    # Check last N versions for eval count changes
    versions_to_check = history[:30]  # Most recent 30
    prev_eval_count = None
    prev_ver = None
    data_drop_versions = []

    for h in reversed(versions_to_check):
        ver = h.get('version')
        try:
            snapshot = get_data_version(CLIENT_ID, ver)
            if snapshot and 'data' in snapshot:
                snap_data = snapshot['data']
                evals = snap_data.get('evaluations', [])
                eval_count = len(evals)
                
                # Check identity
                ident = snap_data.get('identity', {})
                has_email = '✉' if ident.get('email') else ' '
                
                # Count non-empty hedge fields across all evals
                total_hedge = 0
                for ev in evals:
                    for k, v in ev.items():
                        if k.startswith('Hedge') and v and str(v).strip():
                            total_hedge += 1
                
                marker = ""
                if prev_eval_count is not None:
                    if eval_count < prev_eval_count:
                        marker = f" ⚠️ EVALS DROPPED from {prev_eval_count} to {eval_count}!"
                        data_drop_versions.append(ver)
                    elif eval_count > 0 and prev_eval_count > 0 and total_hedge == 0:
                        marker = " ⚠️ HEDGE DATA GONE!"
                        data_drop_versions.append(ver)
                
                action = h.get('action', '?')
                source = h.get('change_source', '')
                by = h.get('changed_by', '')
                date = h.get('created_at', '?')
                print(f"  v{ver:>3} | evals={eval_count:>3} | hedge={total_hedge:>4} | {has_email} | {action:<15} | {source:<20} | {by:<25} | {date}{marker}")
                
                prev_eval_count = eval_count
                prev_ver = ver
            else:
                print(f"  v{ver:>3} | ❌ Could not load snapshot")
        except Exception as e:
            print(f"  v{ver:>3} | ❌ Error: {e}")

    # 4. If we found drops, show detail comparison
    if data_drop_versions:
        print(f"\n{'='*80}")
        print(f"  DETAILED COMPARISON AT DATA DROP POINTS")
        print(f"{'='*80}")
        
        for drop_ver in data_drop_versions[:3]:  # Show first 3 drops max
            before_ver = drop_ver - 1
            print(f"\n--- Comparing v{before_ver} (BEFORE) vs v{drop_ver} (AFTER) ---\n")
            
            try:
                snap_before = get_data_version(CLIENT_ID, before_ver)
                snap_after = get_data_version(CLIENT_ID, drop_ver)
                
                if snap_before and snap_after:
                    evals_before = snap_before.get('data', {}).get('evaluations', [])
                    evals_after = snap_after.get('data', {}).get('evaluations', [])
                    
                    print(f"  BEFORE (v{before_ver}): {len(evals_before)} evaluations")
                    for i, ev in enumerate(evals_before):
                        pf = ev.get('Prop Firm', '?')
                        acc = ev.get('Account #', '') or ev.get('Account #.1', '')
                        hc = sum(1 for k, v in ev.items() if k.startswith('Hedge') and v and str(v).strip())
                        print(f"    [{i}] {pf} | {acc} | hedge_fields={hc}")
                    
                    print(f"\n  AFTER  (v{drop_ver}): {len(evals_after)} evaluations")
                    for i, ev in enumerate(evals_after):
                        pf = ev.get('Prop Firm', '?')
                        acc = ev.get('Account #', '') or ev.get('Account #.1', '')
                        hc = sum(1 for k, v in ev.items() if k.startswith('Hedge') and v and str(v).strip())
                        print(f"    [{i}] {pf} | {acc} | hedge_fields={hc}")
                    
                    # Show what changed
                    print(f"\n  CHANGES:")
                    action = next((h.get('action') for h in history if h.get('version') == drop_ver), '?')
                    source = next((h.get('change_source') for h in history if h.get('version') == drop_ver), '?')
                    by = next((h.get('changed_by') for h in history if h.get('version') == drop_ver), '?')
                    desc = next((h.get('change_description') for h in history if h.get('version') == drop_ver), '?')
                    print(f"    Action: {action}")
                    print(f"    Source: {source}")
                    print(f"    Changed by: {by}")
                    print(f"    Description: {desc}")
                    
                    # Find fields that had data before but are empty after
                    if len(evals_before) == len(evals_after):
                        for i in range(len(evals_before)):
                            lost_fields = {}
                            for k, v in evals_before[i].items():
                                if k.startswith('_'):
                                    continue
                                old_val = str(v).strip() if v else ''
                                new_val = str(evals_after[i].get(k, '')).strip() if evals_after[i].get(k) else ''
                                if old_val and not new_val:
                                    lost_fields[k] = old_val
                            if lost_fields:
                                print(f"\n    ⚠️ Eval [{i}] LOST these fields:")
                                for fk, fv in sorted(lost_fields.items()):
                                    print(f"      {fk}: '{fv}' → (empty)")
            except Exception as e:
                print(f"  Error comparing: {e}")
    
    # 5. Check for the most recent "good" version (one with actual data)
    print(f"\n{'='*80}")
    print(f"  FINDING LAST 'GOOD' VERSION (with hedge/evaluation data)")
    print(f"{'='*80}\n")
    
    best_version = None
    best_hedge_count = 0
    
    for h in history:
        ver = h.get('version')
        try:
            snapshot = get_data_version(CLIENT_ID, ver)
            if snapshot and 'data' in snapshot:
                evals = snapshot.get('data', {}).get('evaluations', [])
                total_hedge = sum(
                    1 for ev in evals for k, v in ev.items()
                    if k.startswith('Hedge') and v and str(v).strip()
                )
                if total_hedge > best_hedge_count:
                    best_hedge_count = total_hedge
                    best_version = ver
        except:
            pass
    
    if best_version:
        print(f"✅ Best version found: v{best_version} with {best_hedge_count} hedge fields")
        print(f"   To rollback, run on server:")
        print(f"   python -c \"from dashboard.database import rollback_to_version; print(rollback_to_version('{CLIENT_ID}', {best_version}))\"")
    else:
        print("❌ No version found with hedge data.")
    
    print(f"\n{'='*80}")
    print(f"  END OF DIAGNOSTIC REPORT")
    print(f"{'='*80}")

if __name__ == '__main__':
    main()
