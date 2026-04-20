"""
TopStepX Account Switcher Probe - Check if multiple accounts exist
and how the UI account selector works.
"""
import json, time, os, hashlib, tempfile, base64, requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

USERNAME = "livemoreabundantlyllc@gmail.com"
PASSWORD = "FTn4t4fx6Mna"

# ── Launch Chrome & Login ──
print("Launching Chrome...")
chrome_options = Options()
unique_hash = hashlib.md5(b"topstepx_explore5").hexdigest()[:8]
user_data_dir = os.path.join(tempfile.gettempdir(), f"chrome_tsx5_{unique_hash}")
chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
chrome_options.add_argument("--remote-debugging-port=9558")
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

print("Navigating to login...")
driver.get("https://www.topstepx.com/login")
time.sleep(3)

# Check if already logged in
token = driver.execute_script("return localStorage.getItem('token')")
if token and len(token) > 100:
    print("Already have token from previous session")
    driver.get("https://www.topstepx.com/trade")
    time.sleep(5)
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
    driver.find_element(By.XPATH, "//button[@type='submit']").click()
    for i in range(20):
        time.sleep(1)
        if "/login" not in driver.current_url:
            print(f"Logged in! URL: {driver.current_url}")
            break
    time.sleep(5)
    token = driver.execute_script("return localStorage.getItem('token')")

# ── API: List all accounts ──
print("\n" + "="*70)
print("  API: ALL TRADING ACCOUNTS")
print("="*70)

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": "https://www.topstepx.com",
    "Referer": "https://www.topstepx.com/",
})

resp = session.get("https://userapi.topstepx.com/TradingAccount", timeout=10)
accounts = resp.json()
print(f"\nTotal accounts: {len(accounts)}")
for i, acct in enumerate(accounts):
    print(f"\n--- Account {i+1} ---")
    print(f"  accountId:      {acct.get('accountId')}")
    print(f"  accountName:    {acct.get('accountName')}")
    print(f"  balance:        ${acct.get('balance', 0):,.2f}")
    print(f"  startingBalance:${acct.get('startingBalance', 0):,.2f}")
    print(f"  profitAndLoss:  ${acct.get('profitAndLoss', 0):,.2f}")
    print(f"  status:         {acct.get('status')}")
    print(f"  ineligible:     {acct.get('ineligible')}")
    print(f"  type:           {acct.get('type')}")
    print(f"  templateId:     {acct.get('templateId')}")
    print(f"  totalTrades:    {acct.get('totalTrades')}")
    print(f"  winRate:        {acct.get('winRate')}")

# ── UI: Inspect account selector element ──
print("\n" + "="*70)
print("  UI: ACCOUNT SELECTOR INSPECTION")
print("="*70)

# Check what the account selector looks like
result = driver.execute_script("""
    const results = {};
    
    // Find all MuiSelect elements
    const selects = document.querySelectorAll('[class*="MuiSelect"], select, [role="combobox"], [role="listbox"]');
    results.selects = Array.from(selects).map(el => ({
        tag: el.tagName,
        classes: el.className?.substring?.(0, 200) || '',
        text: el.textContent?.substring?.(0, 200) || '',
        role: el.getAttribute('role'),
        ariaLabel: el.getAttribute('aria-label'),
    }));
    
    // Find the account display area (contains "V2-" or "50KTC")
    const accountEls = [];
    document.querySelectorAll('*').forEach(el => {
        const text = el.textContent || '';
        if ((text.includes('V2-') || text.includes('50KTC')) && el.children.length < 5) {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0 && rect.height < 100) {
                accountEls.push({
                    tag: el.tagName,
                    classes: el.className?.substring?.(0, 200) || '',
                    text: el.textContent?.substring?.(0, 200) || '',
                    role: el.getAttribute('role'),
                    clickable: el.onclick !== null || el.tagName === 'BUTTON' || el.getAttribute('role') === 'button',
                    cursor: window.getComputedStyle(el).cursor,
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                });
            }
        }
    });
    results.accountElements = accountEls;
    
    // Find the "Accounts" tab
    const tabs = document.querySelectorAll('[role="tab"], [class*="tab"]');
    results.tabs = Array.from(tabs).map(el => ({
        tag: el.tagName,
        text: el.textContent?.substring?.(0, 100) || '',
        role: el.getAttribute('role'),
    }));
    
    return JSON.stringify(results);
""")

try:
    data = json.loads(result)
    
    print(f"\nSelects/Comboboxes found: {len(data.get('selects', []))}")
    for s in data.get('selects', []):
        print(f"  {s['tag']} role={s.get('role')} text={s['text'][:100]}")
    
    print(f"\nAccount-related elements ({len(data.get('accountElements', []))}):")
    for el in data.get('accountElements', []):
        print(f"  <{el['tag']}> cursor={el['cursor']} clickable={el['clickable']} rect={el['rect']}")
        print(f"    text: {el['text'][:150]}")
        print(f"    classes: {el['classes'][:150]}")
    
    print(f"\nTabs ({len(data.get('tabs', []))}):")
    for t in data.get('tabs', []):
        print(f"  {t['text'][:50]}")
        
except Exception as e:
    print(f"Parse error: {e}")
    print(result[:3000])

# ── Try clicking the account area to see if a dropdown appears ──
print("\n" + "="*70)
print("  TRYING TO OPEN ACCOUNT SELECTOR")
print("="*70)

try:
    # Look for the account name display area and click it
    account_display = driver.find_element(By.XPATH, 
        "//span[contains(text(), 'V2-')] | //div[contains(text(), '50KTC')]")
    print(f"Found account display: '{account_display.text[:100]}'")
    print(f"Tag: {account_display.tag_name}, clickable cursor: {account_display.value_of_css_property('cursor')}")
    
    # Click it
    account_display.click()
    time.sleep(2)
    
    # Check if a dropdown appeared
    dropdown_items = driver.execute_script("""
        const items = [];
        // Check for MUI popover/menu/dropdown
        document.querySelectorAll('[role="listbox"], [role="menu"], [class*="Popover"], [class*="Menu"], [class*="dropdown"]').forEach(el => {
            if (el.offsetHeight > 0) {
                items.push({
                    tag: el.tagName,
                    classes: el.className?.substring?.(0, 200) || '',
                    text: el.textContent?.substring?.(0, 500) || '',
                    children: el.children.length,
                });
            }
        });
        // Also check for any new overlay/modal
        document.querySelectorAll('[class*="MuiPopover"], [class*="MuiMenu"], [class*="MuiModal"]').forEach(el => {
            if (el.offsetHeight > 0) {
                items.push({
                    tag: el.tagName,
                    classes: el.className?.substring?.(0, 200) || '',
                    text: el.textContent?.substring?.(0, 500) || '',
                    children: el.children.length,
                });
            }
        });
        return JSON.stringify(items);
    """)
    
    dd = json.loads(dropdown_items)
    if dd:
        print(f"\nDropdown/menu appeared! ({len(dd)} elements)")
        for item in dd:
            print(f"  <{item['tag']}> children={item['children']}")
            print(f"    text: {item['text'][:300]}")
    else:
        print("No dropdown appeared after clicking account display")
        
        # Try the Accounts tab at the bottom
        try:
            accounts_tab = driver.find_element(By.XPATH, "//div[text()='Accounts' and @role='tab'] | //button[text()='Accounts']")
            print(f"\nFound 'Accounts' tab, clicking...")
            accounts_tab.click()
            time.sleep(2)
            
            # Check what appeared
            grid_text = driver.execute_script("""
                const grid = document.querySelector('[role="grid"], [class*="DataGrid"]');
                return grid ? grid.textContent?.substring(0, 1000) : 'No grid found';
            """)
            print(f"Grid content: {grid_text[:500]}")
            
            # Check grid rows
            rows = driver.find_elements(By.XPATH, "//div[@role='row'][@data-id]")
            print(f"\nGrid rows with data-id: {len(rows)}")
            for row in rows[:10]:
                cells = row.find_elements(By.XPATH, ".//div[@role='gridcell']")
                cell_texts = [c.text.strip() for c in cells[:8]]
                print(f"  Row: {cell_texts}")
                
        except Exception as e:
            print(f"Accounts tab not found or error: {e}")

except Exception as e:
    print(f"Could not find/click account display: {e}")

print("\n\nDone. Chrome window remains open.")
try:
    input("Press Enter to quit...")
except:
    pass
driver.quit()
