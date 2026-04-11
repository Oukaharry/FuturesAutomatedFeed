import sys, os
sys.path.insert(0, '.')
os.environ['FLASK_SKIP_SCHEDULER'] = '1'
from dashboard.financial_overview import get_client_performance_stats
from dashboard.watermark_service import get_bulk_watermarks

print("=== Bulk Watermarks (raw from DB) ===")
wm = get_bulk_watermarks(14)
for cid, vals in wm.items():
    if vals.get('low') and vals['low'] != 0:
        print(f"  {cid}: low={vals['low']}, high={vals['high']}")
print(f"  Total entries: {len(wm)}")

print("\n=== Per-client stats LWM (BEF) ===")
clients = get_client_performance_stats('BEF')
print(f"Total BEF clients: {len(clients)}")
for c in clients:
    lwm = c.get('lwm')
    hwm = c.get('hwm')
    print(f"  {c['client_id']}: lwm={lwm} (type={type(lwm).__name__}), hwm={hwm}")

total = sum((c.get('lwm', 0) or 0) for c in clients if (c.get('lwm', 0) or 0) > 0)
print(f"\nSum of positive LWM: {total}")
