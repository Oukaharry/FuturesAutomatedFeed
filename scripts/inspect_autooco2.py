"""Inspect the AutoOCO toggle button via Selenium attached to the running Chrome."""
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)

# 1. All button[role="switch"]
switches = driver.execute_script("""
    var btns = Array.from(document.querySelectorAll('button[role="switch"]'));
    return btns.map(function(b){
        return {
            ariaChecked: b.getAttribute('aria-checked'),
            classes: b.className,
            outerHTML: b.outerHTML.slice(0,400),
            visible: b.offsetParent !== null,
            textNear: b.closest('[class]') ? b.closest('[class]').innerText.slice(0,120) : ''
        };
    });
""")

print("=== button[role=switch] ===")
for i, s in enumerate(switches or []):
    print(f"\n--- switch #{i} ---")
    for k, v in s.items():
        print(f"  {k}: {v}")

if not switches:
    print("  (none found)")

# 2. AutoOCO text leaf and its DOM context
info = driver.execute_script("""
    var leaf = Array.from(document.querySelectorAll('*')).find(function(el){
        return el.children.length === 0 &&
               (el.textContent||'').trim().indexOf('AutoOCO') !== -1;
    });
    if(!leaf) return {found: false};
    return {
        found: true,
        tag: leaf.tagName,
        text: leaf.textContent.trim(),
        parentTag: leaf.parentElement ? leaf.parentElement.tagName : '',
        parentClasses: leaf.parentElement ? leaf.parentElement.className : '',
        parentHTML: leaf.parentElement ? leaf.parentElement.outerHTML.slice(0,500) : '',
        grandparentHTML: (leaf.parentElement && leaf.parentElement.parentElement)
            ? leaf.parentElement.parentElement.outerHTML.slice(0,800) : ''
    };
""")

print("\n=== AutoOCO text node ===")
if info:
    for k, v in info.items():
        print(f"  {k}: {v}")

# Don't quit — leave Chrome running
driver.service.stop()
