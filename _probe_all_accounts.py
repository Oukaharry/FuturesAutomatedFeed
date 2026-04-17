"""Probe all 3 Tradovate accounts — daily P&L + fill history for each."""
import json, time, sys, os
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))
from trader_companion.tradovate import TradovateAccount

ACCOUNTS = [
    ("FNFTHARRISONFbHey", "yvuQE10##"),
    ("TDFYU995561466", "$|GxpwB$*9ja"),
    ("LTTZ9WS86Z9", "3L6jl3JJ#jr4R"),
]

def bfetch(driver, ep, method="GET", body=None, env="demo"):
    body_js = f"opts.body = JSON.stringify({json.dumps(body)});" if body else ""
    js = f"""
    var cb = arguments[arguments.length - 1];
    (async function() {{
        try {{
            var t = JSON.parse(sessionStorage.getItem('api_authenticator_state')||'{{}}').token||'';
            var env = JSON.parse(sessionStorage.getItem('api_authenticator_state')||'{{}}').environment||'demo';
            var base = 'https://' + env + '.tradovateapi.com/v1';
            var opts = {{method:'{method}', headers:{{'Authorization':'Bearer '+t,'Content-Type':'application/json','Accept':'application/json'}}}};
            {body_js}
            var r = await fetch(base + '{ep}', opts);
            var txt = await r.text();
            var d = null; try{{d=JSON.parse(txt);}}catch(e){{}}
            cb({{s:r.status, ok:r.ok, d:d, env:env}});
        }} catch(e) {{ cb({{error:e.toString()}}); }}
    }})();
    """
    try:
        return driver.execute_async_script(js)
    except Exception as e:
        return {"error": str(e)}

def get_daily_pnl(driver):
    """Extract full daily P&L and fills for the logged-in account."""
    # Get accounts
    r = bfetch(driver, "/account/list")
    if not r.get('ok') or not r.get('d'):
        return {"error": f"No accounts: {r}"}
    
    env = r.get('env', 'demo')
    all_accounts = r['d']
    results = {"env": env, "accounts": []}
    
    for acct in all_accounts:
        aid = acct['id']
        aname = acct['name']
        
        # Get cash balance log
        lr = bfetch(driver, f"/cashBalanceLog/ldeps?masterids={aid}")
        logs = lr.get('d', []) if lr.get('ok') else []
        
        # Get fills
        fr = bfetch(driver, "/fill/list")
        fills = fr.get('d', []) if fr.get('ok') else []
        
        # Get fill fees
        ffr = bfetch(driver, "/fillFee/list")
        fill_fees = ffr.get('d', []) if ffr.get('ok') else []
        
        # Get balance snapshot
        snap = bfetch(driver, "/cashBalance/getCashBalanceSnapshot", "POST", {"accountId": aid})
        snap_data = snap.get('d') if snap.get('ok') else {}
        
        # Get auto-liq (drawdown rules)
        alr = bfetch(driver, "/userAccountAutoLiq/list")
        autoliq = alr.get('d', []) if alr.get('ok') else []
        
        # Resolve contract names
        contract_ids = set(f['contractId'] for f in fills)
        contracts = {}
        for cid in contract_ids:
            cr = bfetch(driver, f"/contract/item?id={cid}")
            if cr.get('ok') and cr.get('d'):
                contracts[cid] = cr['d'].get('name', str(cid))
        
        # Build daily P&L
        daily = defaultdict(lambda: {"trades": 0, "gross_pnl": 0, "fees": 0, "balance_eod": 0, "entries": []})
        for entry in sorted(logs, key=lambda x: x['id']):
            td = entry['tradeDate']
            ds = f"{td['year']}-{td['month']:02d}-{td['day']:02d}"
            ctype = entry['cashChangeType']
            delta = entry['delta']
            daily[ds]["entries"].append(entry)
            daily[ds]["balance_eod"] = entry['amount']
            if ctype == "TradePaired":
                daily[ds]["gross_pnl"] += delta
                daily[ds]["trades"] += 1
            elif ctype in ("Commission", "ExchangeFee", "ClearingFee", "NfaFee"):
                daily[ds]["fees"] += delta
        
        # Build fills by day
        fills_by_day = defaultdict(list)
        for f in fills:
            td = f['tradeDate']
            ds = f"{td['year']}-{td['month']:02d}-{td['day']:02d}"
            fills_by_day[ds].append(f)
        
        results["accounts"].append({
            "name": aname, "id": aid,
            "daily": dict(daily), "fills_by_day": dict(fills_by_day),
            "contracts": contracts, "snapshot": snap_data,
            "autoliq": autoliq, "fill_fees": fill_fees,
            "total_fills": len(fills), "total_log_entries": len(logs),
        })
    
    return results

# ── Main ─────────────────────────────────────────────────────
for username, password in ACCOUNTS:
    print(f"\n{'='*70}")
    print(f"🔐 LOGGING IN: {username}")
    print(f"{'='*70}")
    
    try:
        ta = TradovateAccount(username, password, trading_mode="Simulation")
        ta.login()
        print("✅ Login OK")
    except Exception as e:
        print(f"❌ Login FAILED: {e}")
        try:
            ta.driver.quit()
        except:
            pass
        continue
    
    driver = ta.driver
    time.sleep(3)
    
    try:
        data = get_daily_pnl(driver)
        
        if 'error' in data:
            print(f"❌ {data['error']}")
            continue
        
        print(f"   Environment: {data['env']}")
        
        for acc in data["accounts"]:
            print(f"\n   {'─'*60}")
            print(f"   📋 Account: {acc['name']} (id={acc['id']})")
            print(f"   Total fills: {acc['total_fills']}")
            print(f"   Total log entries: {acc['total_log_entries']}")
            
            # Snapshot
            snap = acc.get('snapshot', {})
            if snap:
                print(f"   💰 Current: netLiq=${snap.get('netLiq',0):,.2f}  realizedPnL=${snap.get('realizedPnL',0):,.2f}  openPnL=${snap.get('openPnL',0):,.2f}")
            
            # Drawdown
            for al in acc.get('autoliq', []):
                print(f"   📏 Drawdown: trailing=${al.get('trailingMaxDrawdown',0):,.2f}  limit=${al.get('trailingMaxDrawdownLimit',0):,.2f}  mode={al.get('trailingMaxDrawdownMode','?')}")
            
            # Daily P&L table
            daily = acc["daily"]
            if daily:
                print(f"\n   {'Date':<12} {'Trades':>6} {'Gross P&L':>10} {'Fees':>10} {'Net P&L':>10} {'Balance':>12}")
                print(f"   {'-'*62}")
                total_gross = total_fees = 0
                for ds in sorted(daily.keys()):
                    d = daily[ds]
                    net = d["gross_pnl"] + d["fees"]
                    if d["trades"] > 0 or d["gross_pnl"] != 0:
                        print(f"   {ds:<12} {d['trades']:>6} {d['gross_pnl']:>+10.2f} {d['fees']:>+10.2f} {net:>+10.2f} {d['balance_eod']:>12,.2f}")
                        total_gross += d["gross_pnl"]
                        total_fees += d["fees"]
                    else:
                        print(f"   {ds:<12} {'--':>6} {'--':>10} {'--':>10} {'--':>10} {d['balance_eod']:>12,.2f}")
                print(f"   {'-'*62}")
                print(f"   {'TOTAL':<12} {'':>6} {total_gross:>+10.2f} {total_fees:>+10.2f} {total_gross+total_fees:>+10.2f}")
            
            # Fills detail
            fills_by_day = acc["fills_by_day"]
            contracts = acc["contracts"]
            if fills_by_day:
                print(f"\n   📊 TRADE FILLS:")
                for ds in sorted(fills_by_day.keys()):
                    print(f"   📅 {ds}")
                    for f in fills_by_day[ds]:
                        cname = contracts.get(f['contractId'], f['contractId'])
                        print(f"      {f['timestamp'][11:19]}  {f['action']:4s}  {f['qty']}x {cname}  @ {f['price']}")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            driver.quit()
        except:
            pass

print(f"\n\n{'='*70}")
print("✅ ALL ACCOUNTS PROBED")
print(f"{'='*70}")
