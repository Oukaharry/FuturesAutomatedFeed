"""
TopStepX API Explorer v4 - Selenium login to get JWT from localStorage,
then call all endpoints with Python requests (no CORS).
"""
import json, time, sys, os, hashlib, tempfile, base64, requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

USERNAME = "livemoreabundantlyllc@gmail.com"
PASSWORD = "FTn4t4fx6Mna"
BASE_URL = "https://www.topstepx.com"
LOGIN_URL = f"{BASE_URL}/login"
USER_API = "https://userapi.topstepx.com"
CHART_API = "https://chartapi.topstepx.com"

USER_ID = "342449"
ACCOUNT_ID = "11751547"

# ── Launch Chrome & Login ──
print("Launching Chrome...")
chrome_options = Options()
unique_hash = hashlib.md5(b"topstepx_explore4").hexdigest()[:8]
user_data_dir = os.path.join(tempfile.gettempdir(), f"chrome_tsx4_{unique_hash}")
chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
chrome_options.add_argument("--remote-debugging-port=9557")
chrome_options.add_argument("--window-size=1400,900")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--disable-extensions")
chrome_options.add_argument("--no-first-run")
chrome_options.add_argument("--no-default-browser-check")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
chrome_options.add_experimental_option('useAutomationExtension', False)
chrome_options.add_argument("--disable-blink-features=AutomationControlled")

driver = webdriver.Chrome(options=chrome_options)
driver.set_page_load_timeout(30)
driver.implicitly_wait(3)
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

print(f"Navigating to {LOGIN_URL}...")
driver.get(LOGIN_URL)
time.sleep(3)

# Check if already logged in (token in localStorage from previous session)
token = driver.execute_script("return localStorage.getItem('token')")
if token and len(token) > 100:
    print(f"Already have token from localStorage (length={len(token)})")
else:
    print(f"Logging in as {USERNAME}...")
    wait = WebDriverWait(driver, 15)
    username_field = wait.until(EC.presence_of_element_located((By.NAME, "userName")))
    username_field.send_keys(Keys.CONTROL + "a")
    time.sleep(0.2)
    username_field.send_keys(USERNAME)
    
    password_field = driver.find_element(By.NAME, "password")
    password_field.send_keys(Keys.CONTROL + "a")
    time.sleep(0.2)
    password_field.send_keys(PASSWORD)
    
    login_button = driver.find_element(By.XPATH, "//button[@type='submit']")
    login_button.click()
    
    for i in range(20):
        time.sleep(1)
        url = driver.current_url
        if "/login" not in url:
            print(f"Logged in! URL: {url}")
            break
    
    time.sleep(5)
    token = driver.execute_script("return localStorage.getItem('token')")

# Also grab all localStorage keys
all_storage = driver.execute_script("""
    const result = {};
    for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        result[k] = localStorage.getItem(k);
    }
    return JSON.stringify(result);
""")
print(f"\nAll localStorage keys:")
try:
    storage = json.loads(all_storage)
    for k, v in storage.items():
        preview = v[:200] if len(v) > 200 else v
        print(f"  {k}: {preview}")
except:
    print(all_storage[:2000])

# Close Chrome - we have the token
driver.quit()
print("\nChrome closed.")

if not token:
    print("FATAL: No token found!")
    sys.exit(1)

# Decode JWT
parts = token.split(".")
if len(parts) >= 2:
    payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
        print(f"\nJWT Claims:")
        for k, v in claims.items():
            print(f"  {k}: {v}")
    except Exception as e:
        print(f"  decode error: {e}")

# ═══════════════════════════════════════════════════════════
# Now use Python requests to call all endpoints
# ═══════════════════════════════════════════════════════════
session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": "https://www.topstepx.com",
    "Referer": "https://www.topstepx.com/",
})

ENDPOINTS = [
    # === Discovered from network capture (v2) ===
    ("GET", f"{USER_API}/TradingRule"),
    ("GET", f"{USER_API}/TradingAccount"),
    ("GET", f"{USER_API}/AccountTemplate/userTemplates"),
    ("GET", f"{USER_API}/Layouts"),
    ("GET", f"{USER_API}/AccountTemplateRule/rules/1/all"),
    ("GET", f"{USER_API}/UserContract/active/nonprofesional"),
    ("GET", f"{USER_API}/custom-sounds/list"),
    ("GET", f"{USER_API}/MarketStatus/markets"),
    ("GET", f"{USER_API}/RiskSettingsLockout/active/{ACCOUNT_ID}"),
    ("GET", f"{USER_API}/UserNotification"),
    ("GET", f"{USER_API}/Metadata"),
    ("GET", f"{USER_API}/LinkedOrder?tradingAccountId={ACCOUNT_ID}"),
    ("GET", f"{USER_API}/Trade/id/{ACCOUNT_ID}"),
    ("GET", f"{USER_API}/Order?accountId={ACCOUNT_ID}"),
    ("GET", f"{USER_API}/Position/all/user/{USER_ID}"),
    ("GET", f"{USER_API}/brackets"),
    ("GET", f"{USER_API}/Violations/active/{ACCOUNT_ID}"),
    ("GET", f"{USER_API}/Tilt/activate/{ACCOUNT_ID}?refreshCount=0"),
    ("GET", f"{USER_API}/charts/all"),
    ("GET", f"{CHART_API}/Config"),
    # === Additional probing ===
    ("GET", f"{USER_API}/Auth/me"),
    ("GET", f"{USER_API}/User"),
    ("GET", f"{USER_API}/User/{USER_ID}"),
    ("GET", f"{USER_API}/TradingAccount/all"),
    ("GET", f"{USER_API}/TradingAccount/{ACCOUNT_ID}"),
    ("GET", f"{USER_API}/TradingAccount/user/{USER_ID}"),
    ("GET", f"{USER_API}/Contract"),
    ("GET", f"{USER_API}/Contract/all"),
    ("GET", f"{USER_API}/Instrument"),
    ("GET", f"{USER_API}/Instrument/all"),
    ("GET", f"{USER_API}/Symbol"),
    ("GET", f"{USER_API}/Symbol/all"),
    ("GET", f"{USER_API}/MarketData"),
    ("GET", f"{USER_API}/AccountBalance"),
    ("GET", f"{USER_API}/AccountBalance/{ACCOUNT_ID}"),
    ("GET", f"{USER_API}/DailyStats"),
    ("GET", f"{USER_API}/DailyStats/{ACCOUNT_ID}"),
    ("GET", f"{USER_API}/TradeHistory"),
    ("GET", f"{USER_API}/TradeHistory/{ACCOUNT_ID}"),
    ("GET", f"{USER_API}/Trade/all/{ACCOUNT_ID}"),
    ("GET", f"{USER_API}/Trade/history/{ACCOUNT_ID}"),
    ("GET", f"{USER_API}/RiskSettings"),
    ("GET", f"{USER_API}/RiskSettings/{ACCOUNT_ID}"),
    ("GET", f"{USER_API}/Performance"),
    ("GET", f"{USER_API}/Performance/{ACCOUNT_ID}"),
    ("GET", f"{USER_API}/Drawdown"),
    ("GET", f"{USER_API}/Drawdown/{ACCOUNT_ID}"),
    ("GET", f"{USER_API}/Equity"),
    ("GET", f"{USER_API}/Equity/{ACCOUNT_ID}"),
    ("GET", f"{USER_API}/UserSettings"),
    ("GET", f"{USER_API}/AccountStats"),
    ("GET", f"{USER_API}/AccountStats/{ACCOUNT_ID}"),
    ("GET", f"{USER_API}/Subscription"),
    ("GET", f"{USER_API}/Subscription/user/{USER_ID}"),
    ("GET", f"{USER_API}/Challenge"),
    ("GET", f"{USER_API}/Challenge/user/{USER_ID}"),
    ("GET", f"{USER_API}/Challenge/{ACCOUNT_ID}"),
    # Auth endpoints
    ("GET", f"{USER_API}/Auth/session"),
    ("GET", f"{USER_API}/Auth/validate"),
    ("POST", f"{USER_API}/Auth/loginByToken"),
    ("POST", f"{USER_API}/Auth/refresh"),
    ("POST", f"{USER_API}/Auth/refreshToken"),
]

print("\n" + "="*70)
print("  CALLING ALL ENDPOINTS VIA PYTHON REQUESTS")
print("="*70)

all_results = {}

for method, url in ENDPOINTS:
    label = url.replace("https://", "")
    try:
        if method == "GET":
            resp = session.get(url, timeout=10)
        else:
            resp = session.post(url, json={"token": token}, timeout=10)
        
        status = resp.status_code
        ct = resp.headers.get("content-type", "")
        
        if status in [404, 405]:
            print(f"  [{status}] {label}")
            continue
        
        # Try JSON
        if "json" in ct or resp.text.strip().startswith(("{", "[")):
            try:
                data = resp.json()
                preview = json.dumps(data, indent=2)
                truncated = preview[:1200]
                if len(preview) > 1200:
                    truncated += f"\n  ... ({len(preview)} chars total)"
                print(f"\n  [{status}] {label}")
                for line in truncated.split("\n"):
                    print(f"    {line}")
                all_results[label] = {"status": status, "data": data}
            except:
                print(f"  [{status}] {label}  =>  {resp.text[:200]}")
        elif "html" in ct:
            print(f"  [{status}] {label}  =>  (HTML)")
        else:
            text = resp.text[:300]
            print(f"  [{status}] {label}  =>  {text}")
            if text.strip():
                all_results[label] = {"status": status, "data": text}
                
    except requests.exceptions.ConnectionError as e:
        print(f"  CONN_ERR  {label}  =>  {str(e)[:100]}")
    except requests.exceptions.Timeout:
        print(f"  TIMEOUT  {label}")
    except Exception as e:
        print(f"  ERR  {label}  =>  {e}")

# ═══════════════════════════════════════════════════════════
# Save results
# ═══════════════════════════════════════════════════════════
output_file = "_topstepx_api_dump.json"
print(f"\n\nSaving {len(all_results)} API responses to {output_file}...")
with open(output_file, "w") as f:
    json.dump(all_results, f, indent=2, default=str)

print(f"\nTotal endpoints with real data: {len(all_results)}")
print("Done.")
