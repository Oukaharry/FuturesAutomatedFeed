"""Check farming results stored in DB vs what should be there"""
import sys; sys.path.insert(0,'.')
from dashboard.database import get_all_clients
from utils.data_processor import parse_currency

clients = get_all_clients()
print(f'Total clients: {len(clients)}')
for cid, data in clients.items():
    if not data: continue
    stats = data.get('statistics', {})
    evals = data.get('evaluations', [])
    ci = stats.get('cashflow_inprogress', {}) if stats else {}
    pc = stats.get('profitability_completed', {}) if stats else {}
    # Recalculate farming from stored evals
    recalc_farm = sum(
        sum(parse_currency(ev.get(f'Hedge Day {i}')) for i in range(1, 35))
        for ev in evals
    )
    recalc_farm_15 = sum(
        sum(parse_currency(ev.get(f'Hedge Day {i}')) for i in range(1, 16))
        for ev in evals
    )
    stored_farm_ci = ci.get('farming_results', 0)
    print(f'client={cid}')
    print(f'  stored ci.farming   = {stored_farm_ci:.2f}')
    print(f'  recalc 1-34         = {recalc_farm:.2f}')
    print(f'  recalc 1-15         = {recalc_farm_15:.2f}')
    print(f'  match 1-34?  {abs(stored_farm_ci - recalc_farm) < 0.1}')
    print(f'  match 1-15?  {abs(stored_farm_ci - recalc_farm_15) < 0.1}')
    # Show max hedge day in any eval
    max_day = 0
    for ev in evals:
        for k in ev:
            if k.startswith('Hedge Day ') and 'Note' not in k:
                try:
                    day_num = int(k.replace('Hedge Day ', ''))
                    if day_num > max_day: max_day = day_num
                except: pass
    print(f'  max hedge day in evals: {max_day}')
