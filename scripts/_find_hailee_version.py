"""
Find best version of a client's data and provide rollback command.
Run on server: python _find_hailee_version.py "Client Name"
"""
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.database import get_data_version, rollback_to_version

CLIENT_ID = sys.argv[1] if len(sys.argv) > 1 else "Hailee Wood"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard', 'dashboard.db')

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Get ALL versions for this client, ordered newest first
    cur.execute("""
        SELECT version, action, changed_by, changed_by_type, change_source, 
               change_description, created_at, length(evaluations) as eval_json_len
        FROM data_history 
        WHERE client_id = ?
        ORDER BY version DESC
    """, (CLIENT_ID,))
    rows = cur.fetchall()

    if not rows:
        # Try case-insensitive search
        cur.execute("""
            SELECT DISTINCT client_id FROM data_history 
            WHERE lower(client_id) LIKE '%hailee%' OR lower(client_id) LIKE '%wood%'
        """)
        alts = cur.fetchall()
        print(f"No versions found for '{CLIENT_ID}'.")
        if alts:
            print(f"Did you mean: {[r['client_id'] for r in alts]}")
        
        # Also check clients_data
        cur.execute("""
            SELECT DISTINCT client_id FROM clients_data 
            WHERE lower(client_id) LIKE '%hailee%' OR lower(client_id) LIKE '%wood%'
        """)
        alts2 = cur.fetchall()
        if alts2:
            print(f"clients_data matches: {[r['client_id'] for r in alts2]}")
        conn.close()
        return

    print(f"Found {len(rows)} total versions for '{CLIENT_ID}'\n")
    print(f"{'Ver':>5} | {'Date':<22} | {'Evals':>5} | {'Hedge':>5} | {'Email':>5} | {'Action':<15} | {'Source':<20} | {'Changed By':<25} | Description")
    print("-" * 160)

    best_version = None
    best_eval_count = 0
    best_hedge_count = 0

    for row in rows:
        ver = row['version']
        date = row['created_at'] or '?'
        action = row['action'] or '?'
        source = row['change_source'] or ''
        by = row['changed_by'] or '?'
        desc = (row['change_description'] or '')[:60]
        eval_json_len = row['eval_json_len'] or 0

        # Load full snapshot to count evals and hedge fields
        try:
            snapshot = get_data_version(CLIENT_ID, ver)
            if snapshot and 'data' in snapshot:
                evals = snapshot['data'].get('evaluations', [])
                eval_count = len(evals)
                ident = snapshot['data'].get('identity', {})
                has_email = 'YES' if ident.get('email') else 'NO'
                
                total_hedge = 0
                for ev in evals:
                    for k, v in ev.items():
                        if k.startswith('Hedge') and v and str(v).strip():
                            total_hedge += 1
                
                marker = ""
                if eval_count > best_eval_count:
                    best_eval_count = eval_count
                    best_hedge_count = total_hedge
                    best_version = ver
                    marker = " ◀ BEST"
                
                print(f"{ver:>5} | {date:<22} | {eval_count:>5} | {total_hedge:>5} | {has_email:>5} | {action:<15} | {source:<20} | {by:<25} | {desc}{marker}")
            else:
                print(f"{ver:>5} | {date:<22} | {'?':>5} | {'?':>5} | {'?':>5} | {action:<15} | {source:<20} | {by:<25} | {desc} [LOAD FAILED]")
        except Exception as e:
            print(f"{ver:>5} | {date:<22} | {'?':>5} | {'?':>5} | {'?':>5} | {action:<15} | {source:<20} | {by:<25} | ERROR: {e}")

    conn.close()

    print(f"\n{'='*80}")
    if best_version:
        print(f"✅ BEST VERSION: v{best_version} — {best_eval_count} evaluations, {best_hedge_count} hedge fields")
        print(f"\n   To rollback, run:")
        print(f"   python -c \"import sys,os; sys.path.insert(0,os.getcwd()); from dashboard.database import rollback_to_version; print(rollback_to_version('{CLIENT_ID}', {best_version}))\"")
    else:
        print("❌ No usable version found.")
    print(f"{'='*80}")

if __name__ == '__main__':
    main()
