"""Check actual client data in database"""
from database import get_connection, init_database
import json

init_database()

with get_connection() as conn:
    cursor = conn.cursor()
    
    cursor.execute("SELECT client_id, statistics, evaluations FROM clients_data")
    rows = cursor.fetchall()
    
    for row in rows:
        client_id = row[0]
        stats = json.loads(row[1]) if row[1] else {}
        evals = json.loads(row[2]) if row[2] else []
        
        print(f"\n{'='*50}")
        print(f"Client: {client_id}")
        print(f"Evaluations count: {len(evals)}")
        print(f"Statistics keys: {list(stats.keys())}")
        
        if stats.get('profitability_completed'):
            prof = stats['profitability_completed']
            print(f"\n  Profitability (Completed):")
            print(f"    Challenge Fees:  ${prof.get('challenge_fees', 0):,.2f}")
            print(f"    Hedging Results: ${prof.get('hedging_results', 0):,.2f}")
            print(f"    Net Profit:      ${prof.get('net_profit', 0):,.2f}")
        else:
            print(f"\n  No profitability_completed data")
