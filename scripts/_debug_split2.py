from dashboard.watermark_service import get_waterlog_periods_with_values, get_all_daily_watermarks, compute_waterlog_from_db
from dashboard.database import get_connection
from datetime import date
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
        
        daily = get_all_daily_watermarks(cid)
        
        # Transition net = last daily value in 2/24-3/20
        transition_vals = [v for (d, v) in daily if date(2026,2,24) <= d <= date(2026,3,20)]
        t_net = transition_vals[-1] if transition_vals else 0
        
        # Last old period before transition
        old_periods = [p for p in periods if p['from_date'] < '2026-02-24' and p['to_date'] < '2026-02-24']
        last_old = old_periods[-1] if old_periods else None
        last_old_low = float(last_old['period_low']) if last_old and last_old['period_low'] is not None else 0
        
        result = compute_waterlog_from_db(cid)
        if result and result['periods']:
            print(f'\n=== {cid} ===')
            print(f'  Last old period: {last_old["from_date"]} -> {last_old["to_date"]} low={last_old_low}' if last_old else '  No old periods')
            print(f'  Transition net (last daily in 2/24-3/20): {t_net}')
            if t_net > last_old_low:
                print(f'  Expected transition split: 50% x ({t_net} - {last_old_low}) = {(t_net - last_old_low) * 0.5:.0f}')
            else:
                print(f'  Expected transition split: $0 (net <= prev)')
            for r in result['periods'][-3:]:
                print(f'  {r["from_date"]} -> {r["to_date"]}  net={r["low"]}  split={r["profit_split"]}  pct={r["split_pct"]}')
