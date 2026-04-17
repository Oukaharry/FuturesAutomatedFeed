"""Get billing table's React fiber dataSource."""
import time, json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
d = webdriver.Chrome(options=opts)
d.get("https://app.fundednext.com/billing/billing-history")
time.sleep(5)
print("On billing page", flush=True)

ds = d.execute_script("""
    function gf(el) {
        var k = Object.keys(el);
        for (var i=0; i<k.length; i++) {
            if (k[i].indexOf('__reactFiber') !== -1) return el[k[i]];
        }
        return null;
    }
    var t = document.querySelector('.ant-table');
    if (!t) return 'no table';
    var f = gf(t);
    if (!f) return 'no fiber';
    var n = f;
    for (var i=0; i<30 && n; i++) {
        var p = n.memoizedProps;
        if (p && p.dataSource) return JSON.stringify(p.dataSource).substring(0, 8000);
        if (p && p.data && Array.isArray(p.data)) return JSON.stringify(p.data).substring(0, 8000);
        n = n.return;
    }
    return 'no dataSource found';
""")

print("Result:", flush=True)
try:
    data = json.loads(ds)
    print(json.dumps(data, indent=2)[:5000], flush=True)
except:
    print(ds[:3000], flush=True)

print("DONE", flush=True)
