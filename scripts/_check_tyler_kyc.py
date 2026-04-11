"""Check Tyler Turner KYC portfolio data"""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Use production DB
os.environ['DATABASE_URL'] = os.environ.get('DATABASE_URL', '')

from dashboard.database import get_client_data, get_all_kyc_accounts, is_kyc_primary

primary = 'Tyler Turner'
print(f"Is KYC primary: {is_kyc_primary(primary)}")
accounts = get_all_kyc_accounts(primary)
print(f"KYC accounts: {accounts}")

for name in accounts:
    cdata = get_client_data(name)
    if not cdata:
        print(f"\n--- {name}: NO DATA ---")
        continue
    identity = cdata.get('identity') or {}
    profile = (identity.get('profile') or identity.get('category') or identity.get('source') or 'PRIVATE').upper()
    stats = cdata.get('statistics') or {}
    cashflow = stats.get('cashflow_inprogress', {})
    et = stats.get('eval_totals', {})
    evals = cdata.get('evaluations', [])
    print(f"\n--- {name} (profile={profile}) ---")
    print(f"  Eval count: {len(evals)}")
    print(f"  eval_totals: {json.dumps(et)}")
    print(f"  cashflow: {json.dumps(cashflow)}")
    for i, ev in enumerate(evals[:10]):
        if isinstance(ev, dict):
            pf = ev.get('Prop Firm', '?')
            st = ev.get('Status', '')
            st_p1 = ev.get('Status P1', '')
            fee = ev.get('Fee', '')
            af = ev.get('Activation Fee', '')
            print(f"  Eval {i}: Firm={pf}, Status={st}, StatusP1={st_p1}, Fee={fee}, ActFee={af}")
