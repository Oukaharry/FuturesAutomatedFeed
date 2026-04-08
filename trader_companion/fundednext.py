#!/usr/bin/env python3
"""
FundedNext Dashboard Integration - Selenium Browser Automation
Scrapes account statistics from https://app.fundednext.com/accounts
Follows the same pattern as TradovateAccount and TopStepXAccount.
"""

__version__ = "1.00"
__build__ = "20260407"

import os
import sys
import re
import time
import threading
import logging
import hashlib
import tempfile
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import (
    TimeoutException, WebDriverException, 
    NoSuchElementException, StaleElementReferenceException
)
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def retry_on_stale_element(max_retries=3, delay=1):
    """Decorator to retry web operations that may fail due to stale elements"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(self, *args, **kwargs)
                except (StaleElementReferenceException, NoSuchElementException) as e:
                    if attempt == max_retries - 1:
                        self.logger.error(f"Max retries reached for {func.__name__}: {e}")
                        raise e
                    self.logger.warning(f"Retrying {func.__name__} due to stale element (attempt {attempt + 1})")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


class FundedNextAccount:
    """
    FundedNext dashboard automation class with Selenium-based web scraping.
    Reads account statistics from https://app.fundednext.com/accounts.
    
    Supports two connection modes:
      1. attach_to_existing=True  -> Connects to an already-open Chrome via remote debugging
      2. attach_to_existing=False -> Launches a new Chrome and logs in with credentials
    
    Follows the same interface as TradovateAccount and TopStepXAccount:
      - login() / connect()
      - get_account_stats()
      - is_connected()
      - close() / disconnect()
    """
    
    _chrome_instances = {}
    
    def __init__(self, username=None, password=None, pair_id=None, 
                 attach_to_existing=True, debug_port=9444,
                 use_real_profile=False):
        self.username = username or ""
        self.password = password or ""
        self.pair_id = pair_id or "default"
        self.attach_to_existing = attach_to_existing
        self.debug_port = debug_port
        self.use_real_profile = use_real_profile
        self.logged_in = False
        self.driver = None
        self._placing_order = False
        self._login_timestamp = None
        self._first_stats_fetch = True
        self.base_url = "https://app.fundednext.com"
        self.accounts_url = "https://app.fundednext.com/accounts"
        self.login_url = "https://app.fundednext.com"
        self.lock = threading.RLock()
        
        self.logger = logging.getLogger(f"FundedNext_{self.username}_{self.pair_id}")
        self.logger.info(f"[INIT] FundedNextAccount initializing for user={username}, pair_id={pair_id}, attach={attach_to_existing}")
        
        instance_key = f"fundednext_{username}_{self.pair_id}"
        
        # Reuse existing Chrome instance if available
        if instance_key in self._chrome_instances:
            self.logger.info(f"[INIT] Reusing existing Chrome instance for FundedNext: {username}")
            existing_driver = self._chrome_instances[instance_key]
            try:
                existing_driver.current_url
                self.driver = existing_driver
                self.logger.info("[INIT] Successfully connected to existing Chrome instance")
                return
            except Exception as e:
                self.logger.info(f"[INIT] Existing Chrome instance dead ({e}), creating new one")
                del self._chrome_instances[instance_key]
        
        try:
            self.driver = self._initialize_driver()
            self._chrome_instances[instance_key] = self.driver
            self.logger.info(f"[INIT] Chrome instance registered for FundedNext: {username}")
        except Exception as e:
            self.logger.error(f"[INIT ERROR] Failed to initialize WebDriver: {e}")
            raise Exception(f"Failed to initialize WebDriver: {e}")

    def _get_chromedriver_path(self):
        """Let Selenium Manager handle ChromeDriver automatically"""
        return None

    def _copy_chrome_cookies(self, chrome_profile_src, dest_user_data_dir):
        """Copy Chrome login cookies from user's profile to temp profile"""
        import shutil
        try:
            src_default = os.path.join(chrome_profile_src, "Default")
            dst_default = os.path.join(dest_user_data_dir, "Default")
            os.makedirs(dst_default, exist_ok=True)
            
            # Copy cookie-related files
            cookie_files = ["Cookies", "Cookies-journal", "Login Data", "Login Data-journal",
                            "Web Data", "Web Data-journal", "Preferences", "Secure Preferences"]
            for fname in cookie_files:
                src = os.path.join(src_default, fname)
                dst = os.path.join(dst_default, fname)
                if os.path.exists(src) and not os.path.exists(dst):
                    try:
                        shutil.copy2(src, dst)
                        self.logger.info(f"[PROFILE] Copied {fname}")
                    except Exception as e:
                        self.logger.debug(f"[PROFILE] Could not copy {fname}: {e}")
            
            # Copy Local State for encryption keys
            src_local = os.path.join(chrome_profile_src, "Local State")
            dst_local = os.path.join(dest_user_data_dir, "Local State")
            if os.path.exists(src_local) and not os.path.exists(dst_local):
                shutil.copy2(src_local, dst_local)
                self.logger.info("[PROFILE] Copied Local State (encryption keys)")
                
        except Exception as e:
            self.logger.warning(f"[PROFILE] Cookie copy failed: {e}")

    def _initialize_driver(self):
        """Initialize Chrome WebDriver - attach to existing or launch new with profile cookies"""
        chrome_options = Options()
        
        if self.attach_to_existing:
            # === ATTACH MODE: Connect to already-running Chrome ===
            self.logger.info(f"[DRIVER] Attaching to existing Chrome on port {self.debug_port}...")
            chrome_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{self.debug_port}")
            
            try:
                driver = webdriver.Chrome(options=chrome_options)
                self.logger.info(f"[DRIVER] Attached to Chrome. Current URL: {driver.current_url}")
                
                if "fundednext.com" in driver.current_url:
                    self.logged_in = True
                    self._login_timestamp = time.time()
                    self.logger.info("[DRIVER] Already on FundedNext - session active")
                
                return driver
                
            except Exception as e:
                self.logger.warning(f"[DRIVER] Failed to attach ({e}). Falling back to profile mode...")
                self.attach_to_existing = False
                chrome_options = Options()
        
        # === PROFILE MODE: Launch Chrome with COPY of user's profile for cookies ===
        # This reuses login cookies from the user's normal Chrome session
        chrome_profile_src = os.path.join(os.environ.get('LOCALAPPDATA', ''), 
                                           'Google', 'Chrome', 'User Data')
        
        if self.use_real_profile:
            # USE REAL PROFILE: requires closing all other Chrome instances first
            self.logger.info("[DRIVER] Using real Chrome profile (requires no other Chrome running)")
            user_data_dir = chrome_profile_src
        else:
            unique_id = f"fundednext_{self.username}_{self.pair_id}"
            unique_hash = hashlib.md5(unique_id.encode()).hexdigest()[:8]
            user_data_dir = os.path.join(tempfile.gettempdir(), f"chrome_fundednext_{unique_hash}")
            
            # Copy the Default profile's Cookies file if our temp dir is empty
            profile_default = os.path.join(user_data_dir, "Default")
            if not os.path.exists(os.path.join(profile_default, "Cookies")):
                self._copy_chrome_cookies(chrome_profile_src, user_data_dir)
        
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        
        if not self.use_real_profile:
            debug_port = 9500 + (int(hashlib.md5(f"fundednext_{self.username}_{self.pair_id}".encode()).hexdigest()[:4], 16) % 50)
            chrome_options.add_argument(f"--remote-debugging-port={debug_port}")
        
        # Standard Chrome options
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--no-first-run")
        chrome_options.add_argument("--no-default-browser-check")
        chrome_options.add_argument("--disable-features=TranslateUI")
        chrome_options.add_argument("--window-size=1200,800")
        
        # Anti-detection
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        
        prefs = {
            "profile.default_content_setting_values": {
                "popups": 2,
                "notifications": 2,
            }
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        try:
            self.logger.info("[CHROME] Launching new Chrome instance for FundedNext...")
            start_time = time.time()
            driver = webdriver.Chrome(options=chrome_options)
            elapsed = time.time() - start_time
            self.logger.info(f"[CHROME] Chrome launched in {elapsed:.1f}s")
            
            driver.set_page_load_timeout(30)
            driver.implicitly_wait(2)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            return driver
            
        except Exception as e:
            self.logger.error(f"[DRIVER ERROR] Failed to initialize Chrome: {e}")
            raise

    def login(self, max_retries=3):
        """Login to FundedNext platform"""
        with self.lock:
            # If attached to existing session, just verify we're on FundedNext
            if self.attach_to_existing and self.driver:
                try:
                    current_url = self.driver.current_url
                    if "fundednext.com" in current_url:
                        self.logged_in = True
                        self._login_timestamp = time.time()
                        self.logger.info(f"[LOGIN] Already logged in via existing Chrome: {current_url}")
                        return True
                except Exception:
                    pass
            
            if not self.username or not self.password:
                self.logger.error("Username and password required for FundedNext login")
                return False
            
            for attempt in range(max_retries):
                try:
                    self.logger.info(f"[LOGIN] FundedNext login attempt {attempt + 1}/{max_retries}")
                    
                    if not self.driver:
                        self.driver = self._initialize_driver()
                    
                    self.driver.get(self.login_url)
                    time.sleep(3)
                    
                    wait = WebDriverWait(self.driver, 15)
                    
                    # FundedNext login form - email and password
                    email_field = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 
                            "input[type='email'], input[name='email'], input[placeholder*='mail']"))
                    )
                    email_field.send_keys(Keys.CONTROL + "a")
                    time.sleep(0.2)
                    email_field.send_keys(self.username)
                    
                    password_field = self.driver.find_element(By.CSS_SELECTOR,
                        "input[type='password'], input[name='password']")
                    password_field.send_keys(Keys.CONTROL + "a")
                    time.sleep(0.2)
                    password_field.send_keys(self.password)
                    
                    # Click login button
                    login_button = self.driver.find_element(By.XPATH,
                        "//button[@type='submit'] | //button[contains(text(), 'Login')] | //button[contains(text(), 'Sign')]")
                    login_button.click()
                    
                    # Wait for redirect
                    time.sleep(5)
                    
                    max_wait = 20
                    start_time = time.time()
                    while time.time() - start_time < max_wait:
                        current_url = self.driver.current_url.lower()
                        
                        if any(kw in current_url for kw in ["accounts", "dashboard", "overview"]):
                            self.logged_in = True
                            self._login_timestamp = time.time()
                            self.logger.info(f"[LOGIN] FundedNext login successful: {current_url}")
                            return True
                        
                        # Check for error messages
                        try:
                            error_el = self.driver.find_element(By.CSS_SELECTOR, 
                                "[class*='error'], [class*='alert-danger'], .text-danger")
                            if error_el.is_displayed():
                                self.logger.warning(f"[LOGIN] Error: {error_el.text}")
                                break
                        except NoSuchElementException:
                            pass
                        
                        time.sleep(1)
                    
                    self.logger.warning(f"[LOGIN] Attempt {attempt + 1} timed out")
                    
                except Exception as e:
                    self.logger.error(f"[LOGIN] Attempt {attempt + 1} failed: {e}")
                    time.sleep(3)
            
            return False

    def connect(self):
        """Connect to FundedNext - alias for login()"""
        return self.login()

    def navigate_to_accounts(self):
        """Navigate to the accounts page if not already there"""
        try:
            current_url = self.driver.current_url
            if "/accounts" in current_url:
                return True
            
            self.logger.info("[NAV] Navigating to accounts page...")
            self.driver.get(self.accounts_url)
            time.sleep(3)
            
            # Wait for the account-wrapper to load (confirmed selector from real DOM)
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".account-wrapper"))
            )
            return True
            
        except Exception as e:
            self.logger.error(f"[NAV] Failed to navigate to accounts: {e}")
            return False

    def switch_type_tab(self, tab_name="CFDs"):
        """
        Switch between CFDs and Futures tabs.
        FundedNext uses ant-tabs: .ant-tabs-tab > .ant-tabs-tab-btn
        """
        try:
            tabs = self.driver.find_elements(By.CSS_SELECTOR, ".ant-tabs-tab")
            for tab in tabs:
                if tab.text.strip() == tab_name:
                    tab.click()
                    time.sleep(2)
                    self.logger.info(f"[NAV] Switched to type tab: {tab_name}")
                    return True
            self.logger.warning(f"[NAV] Type tab '{tab_name}' not found")
            return False
        except Exception as e:
            self.logger.error(f"[NAV] Failed to switch type tab: {e}")
            return False

    def switch_status_tab(self, status="Active"):
        """
        Switch between Active/Inactive/Breached status tabs.
        These are buttons inside .account-wrapper__create-account with Tailwind classes.
        """
        try:
            buttons = self.driver.find_elements(
                By.CSS_SELECTOR, ".account-wrapper__create-account button")
            for btn in buttons:
                if btn.text.strip() == status:
                    btn.click()
                    time.sleep(2)
                    self.logger.info(f"[NAV] Switched to status tab: {status}")
                    return True
            self.logger.warning(f"[NAV] Status tab '{status}' not found")
            return False
        except Exception as e:
            self.logger.error(f"[NAV] Failed to switch status tab: {e}")
            return False

    def has_accounts(self):
        """
        Check if the current tab view has any accounts.
        FundedNext shows .no-account-wrapper when empty.
        """
        try:
            no_acct = self.driver.find_elements(By.CSS_SELECTOR, ".no-account-wrapper")
            if no_acct and no_acct[0].is_displayed():
                return False
            return True
        except Exception:
            return False

    def is_connected(self):
        """Check if connected to FundedNext"""
        try:
            if not self.driver:
                return False
            current_url = self.driver.current_url
            return "fundednext.com" in current_url
        except Exception:
            return False

    @retry_on_stale_element(max_retries=3, delay=1)
    def get_account_stats(self):
        """
        Get FundedNext account statistics from the dashboard.
        Returns dict with same keys as Tradovate/TopStepX for GUI compatibility:
          Account Number, Balance, Profit/Loss, Open Trades, Symbol, Direction
        Plus FundedNext-specific fields:
          Equity, Drawdown, Profit Target, Phase, Status
        """
        if not self.lock.acquire(blocking=False):
            return getattr(self, '_cached_stats', self._default_stats("Trading..."))
        
        try:
            if getattr(self, '_placing_order', False):
                return getattr(self, '_cached_stats', self._default_stats("Trading..."))
            
            # Cache TTL
            cache_ttl = 2.0
            current_time = time.time()
            last_fetch = getattr(self, '_stats_last_fetch_time', 0)
            if (current_time - last_fetch) < cache_ttl and hasattr(self, '_cached_stats'):
                return self._cached_stats
            
            if not self.is_connected():
                return self._default_stats("Not Connected")
            
            # Ensure we're on the accounts page
            self.navigate_to_accounts()
            
            stats = {
                "Account Number": "Unknown",
                "Balance": "N/A",
                "Equity": "N/A",
                "Profit/Loss": "N/A",
                "Open Trades": "0",
                "Symbol": "",
                "Direction": "",
                "Drawdown": "N/A",
                "Profit Target": "N/A",
                "Phase": "N/A",
                "Status": "N/A",
            }
            
            try:
                self._extract_account_info(stats)
            except Exception as e:
                self.logger.warning(f"Could not extract account info: {e}")
            
            try:
                self._extract_balance_equity(stats)
            except Exception as e:
                self.logger.warning(f"Could not extract balance/equity: {e}")
            
            try:
                self._extract_drawdown_target(stats)
            except Exception as e:
                self.logger.warning(f"Could not extract drawdown/target: {e}")
            
            try:
                self._extract_phase_status(stats)
            except Exception as e:
                self.logger.warning(f"Could not extract phase/status: {e}")
            
            self._cached_stats = stats
            self._stats_last_fetch_time = time.time()
            return stats
            
        except Exception as e:
            self.logger.error(f"Failed to get FundedNext stats: {e}")
            return self._default_stats("Error")
        finally:
            self.lock.release()

    def get_all_accounts(self):
        """
        Get statistics for ALL accounts listed on the FundedNext accounts page.
        Checks both CFDs and Futures tabs, Active status.
        Returns a list of dicts, one per account.
        """
        if not self.is_connected():
            return []
        
        with self.lock:
            try:
                self.navigate_to_accounts()
                time.sleep(2)
                
                accounts = []
                
                # Check both type tabs
                for type_tab in ["CFDs", "Futures"]:
                    self.switch_type_tab(type_tab)
                    self.switch_status_tab("Active")
                    time.sleep(1)
                    
                    if not self.has_accounts():
                        self.logger.info(f"[ACCOUNTS] No active accounts under {type_tab}")
                        continue
                    
                    acct_elements = self._find_account_elements()
                    for i, element in enumerate(acct_elements):
                        try:
                            acct_stats = self._parse_account_element(element, i)
                            if acct_stats:
                                acct_stats["Type"] = type_tab
                                accounts.append(acct_stats)
                        except Exception as e:
                            self.logger.warning(f"[ACCOUNTS] Failed to parse account {i}: {e}")
                
                self.logger.info(f"[ACCOUNTS] Extracted {len(accounts)} accounts total")
                return accounts
                
            except Exception as e:
                self.logger.error(f"[ACCOUNTS] Failed to get all accounts: {e}")
                return []

    def _find_account_elements(self):
        """Find account card elements in the current tab view.
        
        Real DOM structure (confirmed):
          .account-wrapper__content
            .tw-w-full
              .dashboard-card          <-- THE CARD
                h3  (title: "Futures Legacy Challenge | 50K | Account: FNFT...")
                .active-account-card
                  .border-right
                    p  "Server Type: TRADOVATE"
                    p  "Balance: $49407.6"
                  div
                    p  "Equity: $49,407.60"
                    p  "Account Type: Challenge Account"
              button.activeBusinessType  "Dashboard"
        """
        try:
            cards = self.driver.find_elements(By.CSS_SELECTOR, ".dashboard-card")
            if cards:
                self.logger.info(f"[ACCOUNTS] Found {len(cards)} .dashboard-card elements")
                return cards
        except Exception:
            pass
        
        # Fallback: any element inside account-wrapper with dollar values
        try:
            cards = self.driver.find_elements(
                By.XPATH, "//div[contains(@class, 'account-wrapper__content')]//div[.//p[contains(text(), 'Balance')]]")
            if cards:
                self.logger.info(f"[ACCOUNTS] Found {len(cards)} cards via Balance fallback")
                return cards
        except Exception:
            pass
        
        self.logger.info("[ACCOUNTS] No account elements found")
        return []

    def _parse_account_element(self, element, index):
        """Parse a .dashboard-card element into a stats dict.
        
        Card text format (confirmed):
          Line 0: "Futures Legacy Challenge | 50K | Account: FNFTCHHARRISONOUKA85625"
          Line 1: "Server Type: TRADOVATE"
          Line 2: "Balance: $49407.6"
          Line 3: "Equity: $49,407.60"
          Line 4: "Account Type: Challenge Account"
        """
        try:
            text = element.text
            if not text.strip():
                return None
            
            stats = {
                "Account Number": "Unknown",
                "Balance": "N/A",
                "Equity": "N/A",
                "Profit/Loss": "N/A",
                "Drawdown": "N/A",
                "Profit Target": "N/A",
                "Phase": "N/A",
                "Status": "N/A",
                "Server Type": "N/A",
                "Account Type": "N/A",
                "Challenge": "N/A",
                "Size": "N/A",
            }
            
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            
            for line in lines:
                # Title line: "Futures Legacy Challenge | 50K | Account: FNFT..."
                acct_id = re.search(r'FNFT\w+', line)
                if acct_id:
                    stats["Account Number"] = acct_id.group()
                    # Parse challenge info from title
                    title_match = re.match(r'(.+?)\s*\|\s*(\w+)\s*\|\s*Account:', line)
                    if title_match:
                        stats["Challenge"] = title_match.group(1).strip()
                        stats["Size"] = title_match.group(2).strip()
                    continue
                
                # Labeled values: "Balance: $49407.6", "Equity: $49,407.60" etc.
                labeled = re.match(r'^([A-Za-z ]+):\s*(.+)$', line)
                if labeled:
                    label = labeled.group(1).strip().lower()
                    value = labeled.group(2).strip()
                    
                    if label == 'balance':
                        stats["Balance"] = value
                    elif label == 'equity':
                        stats["Equity"] = value
                    elif label == 'server type':
                        stats["Server Type"] = value
                    elif label == 'account type':
                        stats["Account Type"] = value
                        # Derive status from account type
                        if 'challenge' in value.lower():
                            stats["Status"] = "Challenge"
                        elif 'funded' in value.lower():
                            stats["Status"] = "Funded"
                    elif 'drawdown' in label or 'max loss' in label:
                        stats["Drawdown"] = value
                    elif 'target' in label or 'profit target' in label:
                        stats["Profit Target"] = value
            
            # Set Phase from Challenge name if available
            if stats["Phase"] == "N/A" and stats["Challenge"] != "N/A":
                stats["Phase"] = stats["Challenge"]
            
            return stats
            
        except Exception as e:
            self.logger.warning(f"[PARSE] Failed to parse element {index}: {e}")
            return None

    def _extract_account_info(self, stats):
        """Extract account number from dashboard.
        Real DOM: FNFT ID is in a colored <span> inside h3 within .dashboard-card
        """
        # Primary: span with FNFT ID inside .dashboard-card h3
        try:
            fnft_spans = self.driver.find_elements(
                By.CSS_SELECTOR, ".dashboard-card h3 span span")
            for span in fnft_spans:
                text = span.text.strip()
                if text.startswith("FNFT"):
                    stats["Account Number"] = text
                    self.logger.info(f"[ACCOUNT] Found account: {text}")
                    return
        except Exception:
            pass
        
        # Fallback: search for FNFT pattern anywhere
        try:
            elements = self.driver.find_elements(By.XPATH, "//span[contains(text(), 'FNFT')]")
            for el in elements:
                text = el.text.strip()
                match = re.search(r'FNFT\w+', text)
                if match:
                    stats["Account Number"] = match.group()
                    self.logger.info(f"[ACCOUNT] Found account (fallback): {match.group()}")
                    return
        except Exception:
            pass

    def _extract_balance_equity(self, stats):
        """Extract balance and equity from dashboard.
        Real DOM: <p> tags inside .active-account-card with format "Balance: $49407.6"
        """
        # Primary: p tags inside .active-account-card
        try:
            p_tags = self.driver.find_elements(By.CSS_SELECTOR, ".active-account-card p")
            for p in p_tags:
                text = p.text.strip()
                labeled = re.match(r'^([A-Za-z /&]+):\s*(.+)$', text)
                if not labeled:
                    continue
                label = labeled.group(1).strip().lower()
                value = labeled.group(2).strip()
                
                if label == 'balance':
                    stats["Balance"] = value
                elif label == 'equity':
                    stats["Equity"] = value
                elif label in ('server type',):
                    stats.setdefault("Server Type", value)
                elif label in ('account type',):
                    stats.setdefault("Account Type", value)
        except Exception:
            pass
        
        # Fallback: regex scan body text
        if stats["Balance"] == "N/A":
            try:
                body_text = self.driver.find_element(By.TAG_NAME, "body").text
                for line in body_text.split('\n'):
                    match = re.match(r'Balance:\s*(\$[\d,]+\.?\d*)', line.strip())
                    if match:
                        stats["Balance"] = match.group(1)
                    match = re.match(r'Equity:\s*(\$[\d,]+\.?\d*)', line.strip())
                    if match:
                        stats["Equity"] = match.group(1)
            except Exception:
                pass

    def _extract_drawdown_target(self, stats):
        """Extract drawdown and profit target info"""
        patterns = [
            ("Drawdown", ["drawdown", "max loss", "daily loss", "max drawdown"]),
            ("Profit Target", ["profit target", "target", "goal"]),
        ]
        
        for stat_key, keywords in patterns:
            for keyword in keywords:
                try:
                    xpath = f"//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{keyword}')]"
                    elements = self.driver.find_elements(By.XPATH, xpath)
                    for el in elements:
                        # Check the element itself and its siblings/children for values
                        parent = el.find_element(By.XPATH, "..")
                        parent_text = parent.text
                        
                        # Look for dollar amounts or percentages
                        money = re.search(r'-?\$[\d,]+\.?\d*', parent_text)
                        pct = re.search(r'[\d.]+%', parent_text)
                        
                        if money:
                            stats[stat_key] = money.group()
                            break
                        elif pct:
                            stats[stat_key] = pct.group()
                            break
                    
                    if stats[stat_key] != "N/A":
                        break
                except Exception:
                    continue

    def _extract_phase_status(self, stats):
        """Extract account phase and status from the dashboard-card h3 title.
        Real DOM h3 text: "Futures Legacy Challenge | 50K | Account: FNFT..."
        Account Type p tag: "Account Type: Challenge Account"
        """
        try:
            h3s = self.driver.find_elements(By.CSS_SELECTOR, ".dashboard-card h3")
            for h3 in h3s:
                text = h3.text.strip()
                # Parse: "Futures Legacy Challenge | 50K | Account: FNFT..."
                title_match = re.match(r'(.+?)\s*\|\s*(\w+)\s*\|', text)
                if title_match:
                    stats["Phase"] = title_match.group(1).strip()
                    stats["Size"] = title_match.group(2).strip()
                    break
        except Exception:
            pass
        
        # Status from Account Type <p> tag
        try:
            p_tags = self.driver.find_elements(By.CSS_SELECTOR, ".active-account-card p")
            for p in p_tags:
                text = p.text.strip()
                if text.startswith("Account Type:"):
                    acct_type = text.split(":", 1)[1].strip()
                    stats["Status"] = acct_type
                    break
        except Exception:
            pass
        
        # Section title (e.g. "General Account")
        try:
            section = self.driver.find_elements(By.CSS_SELECTOR, ".account-list-title")
            if section:
                stats.setdefault("Section", section[0].text.strip())
        except Exception:
            pass

    def get_page_snapshot(self):
        """
        Debug helper: Get a text snapshot of the current page content.
        Useful for discovering DOM structure and available selectors.
        """
        try:
            if not self.driver:
                return "No driver available"
            
            snapshot = {
                "url": self.driver.current_url,
                "title": self.driver.title,
                "body_text": "",
                "tables": [],
                "cards": [],
                "dollar_values": [],
            }
            
            # Get full page text
            body = self.driver.find_element(By.TAG_NAME, "body")
            snapshot["body_text"] = body.text[:5000]
            
            # Find all dollar amounts
            dollar_matches = re.findall(r'-?\$[\d,]+\.?\d*', body.text)
            snapshot["dollar_values"] = dollar_matches[:20]
            
            # Find tables
            tables = self.driver.find_elements(By.TAG_NAME, "table")
            for i, table in enumerate(tables[:5]):
                rows = table.find_elements(By.TAG_NAME, "tr")
                table_data = []
                for row in rows[:10]:
                    cells = row.find_elements(By.CSS_SELECTOR, "td, th")
                    table_data.append([c.text.strip() for c in cells])
                snapshot["tables"].append(table_data)
            
            # Find card-like elements
            card_selectors = ["[class*='card']", "[class*='Card']", "[class*='account']"]
            for sel in card_selectors:
                try:
                    cards = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    for card in cards[:10]:
                        text = card.text.strip()
                        if text and len(text) > 10:
                            snapshot["cards"].append(text[:500])
                except Exception:
                    continue
            
            return snapshot
            
        except Exception as e:
            return f"Snapshot failed: {e}"

    def _default_stats(self, account_text="N/A"):
        """Return default stats dict"""
        return {
            "Account Number": account_text,
            "Balance": "N/A",
            "Equity": "N/A",
            "Profit/Loss": "N/A",
            "Open Trades": "0",
            "Symbol": "",
            "Direction": "",
            "Drawdown": "N/A",
            "Profit Target": "N/A",
            "Phase": "N/A",
            "Status": "N/A",
        }

    def get_billing_history(self):
        """
        Scrape billing history from https://app.fundednext.com/billing/billing-history.
        Returns list of dicts with keys:
          sn, account_no, payment_method, invoice, status, date,
          transaction_id, transition_type, paid_amount, funding_package, payment_proof
        
        Uses the Ant Design table: .ant-table-wrapper.billing-page-table
        """
        billing_url = f"{self.base_url}/billing/billing-history"
        try:
            self.logger.info(f"[BILLING] Navigating to {billing_url}")
            self.driver.get(billing_url)
            time.sleep(3)

            # Wait for the billing table to render
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".ant-table-wrapper table"))
                )
            except TimeoutException:
                self.logger.warning("[BILLING] Table did not load in time")
                return []

            rows = self.driver.find_elements(By.CSS_SELECTOR,
                ".ant-table-wrapper table tbody tr.ant-table-row")
            if not rows:
                self.logger.info("[BILLING] No billing rows found")
                return []

            # Column order (confirmed from DOM exploration):
            # SN | Account No | Payment Method | Invoice | Status | Date |
            # Transaction ID | Transition Type | Paid Amount | Funding Package | Payment Proof
            col_keys = [
                "sn", "account_no", "payment_method", "invoice", "status",
                "date", "transaction_id", "transition_type", "paid_amount",
                "funding_package", "payment_proof"
            ]

            billing = []
            for row in rows:
                cells = row.find_elements(By.TAG_NAME, "td")
                entry = {}
                for i, key in enumerate(col_keys):
                    if i < len(cells):
                        entry[key] = cells[i].text.strip()
                    else:
                        entry[key] = ""
                # Clean paid_amount to numeric
                raw_amt = entry.get("paid_amount", "")
                cleaned = re.sub(r'[^\d.]', '', raw_amt)
                entry["paid_amount_numeric"] = float(cleaned) if cleaned else 0.0
                billing.append(entry)

            self.logger.info(f"[BILLING] Extracted {len(billing)} billing records")
            return billing

        except Exception as e:
            self.logger.error(f"[BILLING] Failed to scrape billing: {e}")
            return []

    def disconnect(self):
        """Disconnect from FundedNext"""
        self.logged_in = False
        if self.driver:
            try:
                # If attached to existing Chrome, don't quit - just detach
                if self.attach_to_existing:
                    self.logger.info("[DISCONNECT] Detaching from existing Chrome (not closing)")
                    self.driver = None
                else:
                    self.logger.info("[DISCONNECT] Closing Chrome instance")
                    self.driver.quit()
                    self.driver = None
            except Exception as e:
                self.logger.warning(f"[DISCONNECT] Error: {e}")
                self.driver = None
        
        # Remove from registry
        instance_key = f"fundednext_{self.username}_{self.pair_id}"
        self._chrome_instances.pop(instance_key, None)

    def close(self):
        """Close connection - alias for disconnect()"""
        self.disconnect()


# === CDP-Direct mode for quick page scraping (no Selenium needed) ===
def cdp_scrape(debug_port=9222):
    """
    Scrape FundedNext data via Chrome DevTools Protocol directly.
    Requires Chrome running with --remote-debugging-port=<port>.
    Falls back to Selenium if CDP connection fails.
    """
    import urllib.request
    import json
    
    try:
        data = urllib.request.urlopen(f'http://127.0.0.1:{debug_port}/json', timeout=5).read()
        tabs = json.loads(data)
        fn_tab = next((t for t in tabs if 'fundednext' in t.get('url', '')), None)
        
        if not fn_tab:
            print("FundedNext tab not found. Tabs available:")
            for t in tabs:
                if t.get('type') == 'page':
                    print(f"  {t['title']}: {t['url'][:80]}")
            return None
        
        import websocket
        ws = websocket.create_connection(fn_tab['webSocketDebuggerUrl'], timeout=10)
        
        # Get full page text
        ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 
                            'params': {'expression': 'document.body.innerText', 'returnByValue': True}}))
        body_text = json.loads(ws.recv())['result']['result']['value']
        
        # Get dollar values
        ws.send(json.dumps({'id': 2, 'method': 'Runtime.evaluate',
                            'params': {'expression': '(document.body.innerText.match(/-?\\\\$[\\\\d,]+\\\\.?\\\\d*/g)||[]).join("\\n")', 
                                       'returnByValue': True}}))
        dollars = json.loads(ws.recv())['result']['result']['value']
        
        # Get card elements
        js_cards = '''(() => {
            const cards = document.querySelectorAll('[class*="card"], [class*="Card"], [class*="account"], [class*="Account"]');
            const r = []; cards.forEach((c, i) => {
                if(c.innerText.trim().length > 20) r.push({i: i, cls: c.className.substring(0,200), text: c.innerText.substring(0,600)});
            }); return JSON.stringify(r.slice(0, 15));
        })()'''
        ws.send(json.dumps({'id': 3, 'method': 'Runtime.evaluate', 
                            'params': {'expression': js_cards, 'returnByValue': True}}))
        cards = json.loads(json.loads(ws.recv())['result']['result']['value'])
        
        ws.close()
        
        return {'url': fn_tab['url'], 'title': fn_tab['title'], 
                'body_text': body_text, 'dollars': dollars, 'cards': cards}
    except Exception as e:
        print(f"CDP scrape failed: {e}")
        return None


def quick_test(debug_port=9222, mode="auto"):
    """
    Quick test: Try CDP-direct first, then fall back to Selenium with fresh Chrome.
    mode: "cdp" = CDP only, "selenium" = Selenium only, "auto" = try both
    """
    import time as time_mod
    
    if mode in ("auto", "cdp"):
        print("=== Trying CDP-direct mode ===")
        cdp_data = cdp_scrape(debug_port)
        if cdp_data:
            print(f"\nURL: {cdp_data['url']}")
            print(f"Title: {cdp_data['title']}")
            print(f"\nDollar values:\n{cdp_data['dollars']}")
            print(f"\nCards ({len(cdp_data['cards'])}):")
            for c in cdp_data['cards'][:10]:
                print(f"\n--- Card {c['i']} (class: {c['cls'][:60]}) ---")
                print(c['text'][:400])
            print(f"\nBody text:\n{cdp_data['body_text'][:5000]}")
            return cdp_data
        if mode == "cdp":
            print("CDP mode failed - Chrome debug port not available")
            return None
    
    print("\n=== Selenium mode: launching fresh Chrome ===")
    print("A new Chrome window will open. Please log in to FundedNext when prompted.")
    
    fn = FundedNextAccount(attach_to_existing=False, use_real_profile=False)
    
    # Navigate to FundedNext login
    fn.driver.get("https://app.fundednext.com/accounts")
    time_mod.sleep(3)
    
    current_url = fn.driver.current_url
    print(f"Current URL: {current_url}")
    
    if "fundednext.com/accounts" in current_url:
        fn.logged_in = True
        print("Already logged in!")
    else:
        print("\nPlease log in to FundedNext in the Chrome window that just opened.")
        print("After logging in and reaching the Accounts page, press Enter here...")
        input(">>> Press Enter when you're on the Accounts page: ")
        time_mod.sleep(2)
    
    print(f"\nNow on: {fn.driver.current_url}")
    
    print("\n=== Page Snapshot ===")
    snapshot = fn.get_page_snapshot()
    if isinstance(snapshot, dict):
        print(f"URL: {snapshot['url']}")
        print(f"Title: {snapshot['title']}")
        print(f"\nDollar values found: {snapshot['dollar_values']}")
        print(f"\nCards found: {len(snapshot['cards'])}")
        for i, card in enumerate(snapshot['cards'][:10]):
            print(f"\n--- Card {i} ---")
            print(card[:400])
        print(f"\nBody text (first 3000 chars):\n{snapshot['body_text'][:3000]}")
    else:
        print(snapshot)
    
    print("\n=== Account Stats ===")
    stats = fn.get_account_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")
    
    print("\n=== All Accounts ===")
    all_accts = fn.get_all_accounts()
    for i, acct in enumerate(all_accts):
        print(f"\n--- Account {i+1} ---")
        for k, v in acct.items():
            print(f"  {k}: {v}")
    
    return fn


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FundedNext Dashboard Scraper")
    parser.add_argument("--port", type=int, default=9222, help="Chrome remote debugging port")
    parser.add_argument("--test", action="store_true", help="Run quick test")
    parser.add_argument("--mode", choices=["auto", "cdp", "selenium"], default="auto",
                        help="Connection mode: auto (try both), cdp (direct), selenium (new Chrome)")
    args = parser.parse_args()
    
    if args.test:
        quick_test(debug_port=args.port, mode=args.mode)
    else:
        print("Usage: python fundednext.py --test [--mode auto|cdp|selenium] [--port 9222]")
