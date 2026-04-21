"""
Verify Reece profit split matches dashboard by calling _compute_one path directly.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from dashboard.financial_overview import _get_cached_clients, get_client_profile
from dashboard.watermark_service import compute_waterlog_from_db
from utils.data_processor import parse_currency

_P1_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
_FD_CORE_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 'Hedge Result 5.1']
_FARM_HR_COLS = ['Hedge Result 6', 'Hedge Result 7']
_HEDGE_DAY_COLS = [f'Hedge Day {i}' for i in range(1, 51)]

def _farm_net_set(ev):
    raw = ev.get('Farming Net')
    if raw is None:
        return False
    return str(raw).strip() not in ('', '-')

def _live_in_progress_net(evaluations):
    cf_pay = cf_fees = cf_hedge = cf_farm = 0.0
    for ev in (evaluations or []):
        if not ev or ev.get('_deleted'):
            continue
        sp1 = str(ev.get('Status P1', '') or '').lower()
        sf = str(ev.get('Status') or ev.get('Status Funded', '') or '').lower()
        if 'deleted' in sp1 or 'deleted' in sf:
            continue
        p1 = round(sum(parse_currency(ev.get(c)) for c in _P1_COLS), 2)
        fd = round(sum(parse_currency(ev.get(c)) for c in _FD_CORE_COLS), 2)
        farm_hr = round(sum(parse_currency(ev.get(c)) for c in _FARM_HR_COLS), 2)
        h_days = round(sum(parse_currency(ev.get(c)) for c in _HEDGE_DAY_COLS), 2)
        fee = parse_currency(ev.get('Fee'))
        act = parse_currency(ev.get('Activation Fee'))
        payouts = round(sum(parse_currency(ev.get(f'Payout {i}')) for i in range(1, 7)), 2)
        row_hedge = round(p1 + fd, 2)
        row_farm = round(parse_currency(ev.get('Farming Net')), 2) if _farm_net_set(ev) else round(farm_hr + h_days, 2)
        cf_pay = round(cf_pay + payouts, 2)
        cf_fees = round(cf_fees + fee + act, 2)
        cf_hedge = round(cf_hedge + row_hedge, 2)
        cf_farm = round(cf_farm + row_farm, 2)
    print(f"  payouts={cf_pay}  fees={cf_fees}  hedge={cf_hedge}  farm={cf_farm}")
    return round(cf_pay + cf_hedge + cf_farm - cf_fees, 2)

clients_data = _get_cached_clients()
data = clients_data.get('Reece')
if not data:
    print("Reece not found")
    sys.exit(0)

print("=== Reece live recompute ===")
latest_net = _live_in_progress_net(data.get('evaluations') or [])
print(f"latest_net (recomputed) = {latest_net}")
print(f"Dashboard shows: $53,205.10")

wl = compute_waterlog_from_db('Reece')
periods = wl['periods'] if wl else []
prev_low = 0.0
split_pct = 50
if periods:
    try:
        split_pct = int(periods[-1].get('split_pct', 50) or 50)
    except Exception:
        split_pct = 50
    if len(periods) >= 2:
        raw = str(periods[-2].get('low', '$0')).replace('$', '').replace(',', '').strip()
        prev_low = float(raw)
print(f"prev_low={prev_low}  split_pct={split_pct}")

split = max(0.0, (latest_net - prev_low) * split_pct / 100.0) if latest_net > prev_low else 0.0
print(f"split = ({latest_net} - {prev_low}) * {split_pct}/100 = {split:.2f}")
print(f"Dashboard shows: $3,076")
