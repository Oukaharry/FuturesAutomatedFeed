from dashboard.watermark_service import get_waterlog_periods_with_values, get_all_daily_watermarks, compute_waterlog_from_db
from dashboard.database import get_connection
import json

with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute('SELECT client_id, identity FROM clients_data')
    for row in cursor.fetchall():
        identity = json.loads(row['identity']) if row['identity'] else {}
        name = identity.get('name', '')
        cid = row['client_id']
        periods = get_waterlog_periods_with_values(cid)
        if not periods:
            continue
        
        result = compute_waterlog_from_db(cid)
        if result and result['periods']:
            print(f'\n=== {cid} ===')
            for r in result['periods'][-3:]:
                print(f'  {r["from_date"]} -> {r["to_date"]}  net={r["low"]}  split={r["profit_split"]}  pct={r["split_pct"]}')
