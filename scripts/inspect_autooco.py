"""Inspect the AutoOCO toggle button on the live AlphaTrader Chrome page via CDP."""
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# Attach to already-running Chrome on port 9222
opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)

def run_js(expr):
    return driver.execute_script(f"return (function(){{ {expr} }})()")
  var btns = Array.from(document.querySelectorAll('button[role="switch"]'));
  return JSON.stringify(btns.map(function(b){
    return {
      ariaChecked: b.getAttribute('aria-checked'),
      classes: b.className,
      outerHTML: b.outerHTML.slice(0,400),
      visible: b.offsetParent !== null,
      textNear: b.closest('[class]') ? b.closest('[class]').innerText.slice(0,120) : ''
    };
  }));
})()""", msg_id=1)

print("=== button[role=switch] ===")
try:
    for i, s in enumerate(json.loads(switches)):
        print(f"\n--- switch #{i} ---")
        for k, v in s.items():
            print(f"  {k}: {v}")
except Exception as e:
    print("raw:", switches, "err:", e)

# 2. Find the "AutoOCO" text leaf and its parent tree
autooco = run_js("""(function(){
  var leaf = Array.from(document.querySelectorAll('*')).find(function(el){
    return el.children.length === 0 && (el.textContent||'').trim().indexOf('AutoOCO') !== -1;
  });
  if(!leaf) return JSON.stringify({found: false});
  var info = {
    found: true,
    tag: leaf.tagName,
    text: leaf.textContent.trim(),
    parentHTML: leaf.parentElement ? leaf.parentElement.outerHTML.slice(0,600) : '',
    grandparentHTML: (leaf.parentElement && leaf.parentElement.parentElement)
      ? leaf.parentElement.parentElement.outerHTML.slice(0,800) : ''
  };
  return JSON.stringify(info);
})()""", msg_id=2)

print("\n=== AutoOCO text node ===")
try:
    for k, v in json.loads(autooco).items():
        print(f"  {k}: {v}")
except Exception as e:
    print("raw:", autooco, "err:", e)

ws.close()
