"""Inspect TP/SL inputs after toggling AutoOCO ON."""
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)

# Check current state - toggle ON if needed
state = driver.execute_script(
    'var cb=document.querySelector(".bracket-checkbox"); return cb ? cb.className.trim() : "NONE";')
print("Current bracket-checkbox class:", repr(state))

if "active" not in state:
    driver.execute_script('document.querySelector(".bracket-checkbox").click();')
    print("Clicked to enable")
    time.sleep(1.5)

# Dump all inputs with placeholder 0.00 (visible or not)
inputs = driver.execute_script("""
    return Array.from(document.querySelectorAll('input[placeholder="0.00"]')).map(function(el){
        var r = el.getBoundingClientRect();
        return {
            value: el.value,
            type: el.type,
            classes: el.className,
            offsetParent: el.offsetParent !== null,
            visible: el.offsetParent !== null,
            display: window.getComputedStyle(el).display,
            visibility: window.getComputedStyle(el).visibility,
            width: r.width,
            height: r.height,
            parentClasses: el.parentElement ? el.parentElement.className : ''
        };
    });
""")
print(f"\nAll input[placeholder='0.00'] ({len(inputs)} total):")
for i, inp in enumerate(inputs):
    print(f"  #{i}: {inp}")

# Also check for bracket-tp / bracket-sl specific classes
tp_sl = driver.execute_script("""
    var all = Array.from(document.querySelectorAll('[class*="bracket"]'));
    return all.map(function(el){
        return {tag: el.tagName, cls: el.className, html: el.outerHTML.slice(0,300)};
    });
""")
print(f"\nAll [class*=bracket] elements ({len(tp_sl)} total):")
for el in tp_sl:
    print(f"  {el['tag']} .{el['cls'][:60]}")

driver.service.stop()
