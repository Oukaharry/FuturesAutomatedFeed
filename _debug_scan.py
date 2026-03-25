"""Debug quality scan to find the 500 error."""
import sys, os
sys.path.insert(0, '.')
os.environ['DATABASE_PATH'] = 'dashboard/mt5_dashboard.db'

from dashboard.database import get_client_data, get_client_activity
from config.hierarchy import get_all_clients, get_client_profile
from datetime import datetime
import traceback

all_clients = get_all_clients()
now = datetime.now()
scan_date_str = now.strftime('%Y-%m-%d')
print(f"Total clients: {len(all_clients)}")

# Import the actual scan function pieces
from dashboard.app import get_client_notes, _estimate_issue_date, _get_row_dates, _parse_date_str

for client_name in all_clients:
    try:
        profile = get_client_profile(client_name)
        trader = profile.get('trader', '') if profile else ''
        admin = profile.get('admin', '') if profile else ''
        data = get_client_data(client_name)
        if not data:
            print(f"  {client_name}: no data")
            continue
        
        identity = data.get('identity', {})
        if isinstance(identity, dict) and identity.get('active_status') == 'inactive':
            print(f"  {client_name}: inactive, skip")
            continue

        evaluations = data.get('evaluations', [])
        
        # Test notes injection
        try:
            notes = get_client_notes(client_name)
            for i, ev in enumerate(evaluations):
                if i in notes:
                    ev['_notes'] = notes[i]
        except Exception:
            pass

        # Test activity
        activity = get_client_activity(client_name) or {}
        last_push = activity.get('last_push_at')
        if last_push:
            push_dt = datetime.fromisoformat(last_push)
        
        # Test each evaluation row
        for idx, ev in enumerate(evaluations):
            if ev.get('_deleted'):
                continue
            status_p1 = str(ev.get('Status P1', '') or '').strip().lower()
            status_p2 = str(ev.get('Status', '') or '').strip().lower()
            prop_firm = str(ev.get('Prop Firm', '') or '').strip()
            acct_size = str(ev.get('Account Size', '') or '').strip()
            has_data = bool(prop_firm or acct_size)
            
            if not has_data:
                continue
            
            # Test _estimate_issue_date
            if not status_p1 and has_data:
                _estimate_issue_date(ev, 'Status blank', scan_date_str)
            
            # Test parse_num and hedge net
            def _parse_num(v):
                try: return float(str(v).replace('$', '').replace(',', '').strip())
                except (ValueError, TypeError): return None
            
            hedge_net = _parse_num(ev.get('Hedge Net', ''))
            if hedge_net is not None and hedge_net < 0:
                cell_notes = ev.get('_notes', {}) or {}
                has_any_note = isinstance(cell_notes, dict) and any(v for v in cell_notes.values() if v and str(v).strip())

        # Test hedge/prop check
        hedge_accounts = data.get('hedge_accounts') or []
        prop_accounts = data.get('prop_accounts') or []
        _hedge_filled = any(
            str(hacc.get('login', '') or '').strip() or str(hacc.get('password', '') or '').strip()
            for hacc in hedge_accounts
            if isinstance(hacc, dict)
        )
        _prop_filled = any(
            str(pa.get('login', '') or '').strip() or str(pa.get('password', '') or '').strip()
            for pa in prop_accounts
            if isinstance(pa, dict)
        )
        
        print(f"  OK: {client_name} (evals={len(evaluations)}, hedge={len(hedge_accounts)}, prop={len(prop_accounts)})")
    except Exception as e:
        print(f"  FAIL: {client_name}")
        traceback.print_exc()
        print()

print("Done")
