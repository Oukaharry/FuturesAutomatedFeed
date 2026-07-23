import sys
sys.path.insert(0, '.')
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option('debuggerAddress', 'localhost:9222')
d = webdriver.Chrome(options=opts)

rows = d.execute_script("""
    var rows = [];
    var all = Array.from(document.querySelectorAll('*'));
    for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (el.children.length > 0) continue;
        var t = el.textContent.trim();
        if (!t || t.length > 80) continue;
        var r = el.getBoundingClientRect();
        if (r.x < 900 || r.y > 700) continue;
        rows.push({text: t, x: Math.round(r.x), y: Math.round(r.y)});
    }
    rows.sort(function(a,b){ return a.y - b.y || a.x - b.x; });
    return rows;
""")
for row in rows:
    print(f"  ({row['x']:5d},{row['y']:4d})  {repr(row['text'])}")
