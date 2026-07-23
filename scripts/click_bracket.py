"""Click the bracket-checkbox and observe state changes."""
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)

before = driver.execute_script(
    'var cb=document.querySelector(".bracket-checkbox"); return cb ? cb.className : "NOT FOUND";')
print("BEFORE:", repr(before))

driver.execute_script(
    'var cb=document.querySelector(".bracket-checkbox"); if(cb) cb.click();')
time.sleep(0.8)

after = driver.execute_script(
    'var cb=document.querySelector(".bracket-checkbox"); return cb ? cb.className : "NOT FOUND";')
print("AFTER click:", repr(after))

inputs = driver.execute_script(
    'return Array.from(document.querySelectorAll(\'input[placeholder="0.00"]\')'
    ').filter(function(el){return el.offsetParent !== null;}).length;')
print("TP/SL inputs visible:", inputs)

driver.service.stop()
