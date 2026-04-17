"""Fetch the full account data and billing data to find the mapping."""
import time, json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9549")
driver = webdriver.Chrome(options=opts)

token = driver.execute_script("""
    const c = document.cookie.split(';').find(c => c.trim().startsWith('tokenV1='));
    return c ? decodeURIComponent(c.split('=')[1]) : null;
""")

base = "https://api.fundednext.com/api/v1"

# 1. Get active accounts
print("=== ACTIVE ACCOUNTS ===")
result = driver.execute_script("""
    const resp = await fetch(arguments[0], {
        headers: {'Authorization': 'Bearer ' + arguments[1], 'Accept': 'application/json'}
    });
    return await resp.text();
""", f"{base}/get-accounts?type=active&page=1&limit=50", token)
print(result[:8000])

# 2. Get inactive accounts
print("\n\n=== INACTIVE ACCOUNTS ===")
result2 = driver.execute_script("""
    const resp = await fetch(arguments[0], {
        headers: {'Authorization': 'Bearer ' + arguments[1], 'Accept': 'application/json'}
    });
    return await resp.text();
""", f"{base}/get-accounts?type=inactive", token)
print(result2[:8000])

# 3. Billing with correct params
print("\n\n=== BILLING HISTORY ===")
result3 = driver.execute_script("""
    const resp = await fetch(arguments[0], {
        headers: {'Authorization': 'Bearer ' + arguments[1], 'Accept': 'application/json'}
    });
    return await resp.text();
""", f"{base}/pending-payment-history?email=harryodhiambo17@gmail.com&type=1&account_id=&page=1&limit=20", token)
print(result3[:8000])

# 4. Wrappable accounts
print("\n\n=== WRAP ELIGIBLE ACCOUNTS ===")
result4 = driver.execute_script("""
    const resp = await fetch(arguments[0], {
        headers: {'Authorization': 'Bearer ' + arguments[1], 'Accept': 'application/json'}
    });
    return await resp.text();
""", f"{base}/wrap/eligible-accounts", token)
print(result4[:5000])

print("\n\nDONE")
