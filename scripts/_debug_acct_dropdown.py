import sys, time, json
sys.path.insert(0, '.')
from connectors.alphatrader_connector import AlphaTraderConnector

c = AlphaTraderConnector(email='joehickenfpf@gmail.com', password='I5!b4lnYLr')
c.connect()
time.sleep(3)

accounts = c._rest_get_accounts()
for a in (accounts or []):
    print(f"REST: {a['account_name']}  is_default={a.get('is_default')}  status={a['status']}")

print("_account_name:", c._account_name)
print("DOM active:", c.get_active_account())

driver = c._driver
w = driver.execute_script("""
    var w = document.querySelector('.accountSelectorWrapper');
    if (!w) return 'no wrapper';
    var ctrl = w.querySelector('[class*="-control"]');
    if (!ctrl) ctrl = w;
    ctrl.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
    ctrl.click();
    return 'opened';
""")
print("Dropdown:", w)
time.sleep(1.5)

opts = driver.execute_script("""
    return Array.from(document.querySelectorAll('[role="option"], [class*="-option"]')).map(function(o) {
        var r = o.getBoundingClientRect();
        return {
            text: o.textContent.trim().slice(0,60),
            offsetParent: o.offsetParent !== null,
            w: Math.round(r.width), h: Math.round(r.height)
        };
    });
""")
print(f"Options found: {len(opts)}")
for o in opts:
    print(f"  {o}")

driver.execute_script("document.querySelector('body').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
time.sleep(1)

# Now try switch_account to a different account
current = c.get_active_account()
target = 'ADVEV2026060800394' if '605' in (current or '') else 'ADVEV2026060800605'
print(f"\nTrying switch_account({target!r})...")
ok = c.switch_account(target)
print("switch_account returned:", ok)
print("Active now:", c.get_active_account())

c._driver.quit()
