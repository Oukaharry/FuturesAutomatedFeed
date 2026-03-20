#!/usr/bin/env python3
"""
TopStepX Trading Platform Integration - MFFU Blueprint Compatible
Handles connection and trading operations with TopStepX platform using MFFU blueprint structure
"""

__version__ = "2.90"
__build__ = "20260219"

import os
import sys
import time
import threading
import logging
import random
import hashlib
import tempfile
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException, StaleElementReferenceException
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv

# Load .env at program start
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Import prop firm manager for blueprint validation
try:
    from prop_firm_manager import PropFirmManager
    PROP_FIRM_MANAGER_AVAILABLE = True
except ImportError:
    PROP_FIRM_MANAGER_AVAILABLE = False
    logging.warning("PropFirmManager not available - blueprint validation disabled")

DEFAULT_SYMBOL = os.getenv("TOPSTEPX_SYMBOL") or "MNQM25"
DEFAULT_TP = os.getenv("TOPSTEPX_TAKEPROFIT_TICKS")
DEFAULT_SL = os.getenv("TOPSTEPX_STOPLOSS_TICKS")

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
                except Exception as e:
                    # Don't retry for other exceptions
                    raise e
            return None
        return wrapper
    return decorator

class TopStepXAccount:
    """
    TopStepX trading automation class with robust Selenium-based web automation.
    Handles login, symbol selection, order placement, and account statistics.
    Ensures single Chrome instance per account to prevent resource conflicts.
    Follows MFFU blueprint pattern for consistency.
    """
    
    # Class-level registry to track Chrome instances per account
    _chrome_instances = {}
    
    def __init__(self, username=None, password=None, pair_id=None):
        self.username = username or ""
        self.password = password or ""
        self.pair_id = pair_id or "default"
        self.logged_in = False
        self.driver = None
        self.first_trade_attempted = False
        self._first_stats_fetch = True
        self._placing_order = False  # Flag to block stats fetching during order placement
        self._login_timestamp = None  # Track when we logged in for debugging
        self.base_url = "https://www.topstepx.com"
        self.login_url = "https://www.topstepx.com/login"
        self._delay_snapshots_enabled = True  # Enable automatic snapshot capture on delays
        self.lock = threading.RLock()  # Thread safety for Selenium operations
        
        # Initialize logger - MFFU blueprint standard
        self.logger = logging.getLogger(f"TopStepX_{self.username}_{self.pair_id}")
        self.logger.info(f"[INIT] TopStepXAccount initializing for user={username}, pair_id={pair_id}")
        
        # Create unique instance key using both username and pair_id
        instance_key = f"{username}_{self.pair_id}"
        self.logger.info(f"[INIT] Instance key: {instance_key}")
        
        # Check if Chrome instance already exists for this specific account+pair combination
        if instance_key in self._chrome_instances:
            self.logger.info(f"[INIT] Reusing existing Chrome instance for TopStepX account: {username} (Pair: {self.pair_id})")
            existing_driver = self._chrome_instances[instance_key]
            # Test if existing driver is still alive
            try:
                existing_driver.current_url
                self.driver = existing_driver
                self.logger.info("[INIT] Successfully connected to existing Chrome instance")
                return
            except Exception as e:
                self.logger.info(f"[INIT] Existing Chrome instance is dead ({e}), creating new one")
                # Remove dead instance from registry
                del self._chrome_instances[instance_key]
        
        # Initialize driver with error handling
        self.logger.info("[INIT] No existing Chrome instance found - creating new WebDriver")
        try:
            self.logger.info("[INIT] Calling _initialize_driver()...")
            self.driver = self._initialize_driver()
            self.logger.info(f"[INIT] WebDriver created successfully: {self.driver}")
            # Register the Chrome instance for this specific account+pair combination
            self._chrome_instances[instance_key] = self.driver
            self.logger.info(f"[INIT] Chrome instance registered for TopStepX: {username} (Pair: {self.pair_id})")
        except Exception as e:
            self.logger.error(f"[INIT ERROR] Failed to initialize WebDriver: {str(e)}")
            import traceback
            self.logger.error(f"[INIT ERROR] Full traceback:\n{traceback.format_exc()}")
            raise Exception(f"Failed to initialize WebDriver: {str(e)}. This may indicate VPS Chrome setup issues.")

    def _get_chromedriver_path(self):
        """Get the path to ChromeDriver executable with auto-compatibility check"""
        # SELENIUM 4.15+ AUTO-MANAGEMENT: Let Selenium Manager handle ChromeDriver automatically
        # This ensures ChromeDriver always matches the installed Chrome version
        logging.info("[AUTO] Using Selenium Manager for automatic ChromeDriver version matching")
        return None  # Return None to let Selenium Manager handle it

    def _ensure_chrome_compatibility(self):
        """Ensure Chrome-ChromeDriver version compatibility"""
        try:
            # Import the compatibility manager
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            from chrome_auto_compatibility import ChromeVersionManager  # type: ignore
            
            manager = ChromeVersionManager()
            success = manager.ensure_compatibility()
            
            if success:
                logging.info("[CHECK] Chrome-ChromeDriver compatibility verified")
            else:
                logging.warning("[WARNING] Chrome-ChromeDriver compatibility could not be ensured")
                
        except Exception as e:
            logging.warning(f"Chrome compatibility check failed: {e}")
            # Continue anyway - don't break existing functionality

    def _initialize_driver(self):
        """Initialize Chrome WebDriver with crash-resistant options"""
        self.logger.info("[DRIVER] Starting Chrome WebDriver initialization...")
        chrome_options = Options()
        
        # Create persistent user data directory per account+pair to ensure separate Chrome instances
        # Use username+pair_id hash to create unique directory per account+pair combination
        unique_id = f"{self.username}_{self.pair_id}"
        unique_hash = hashlib.md5(unique_id.encode()).hexdigest()[:8]
        user_data_dir = os.path.join(tempfile.gettempdir(), f"chrome_topstepx_{unique_hash}")
        self.logger.info(f"[DRIVER] User data dir: {user_data_dir}")
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        
        # Use unique debugging port per account+pair
        port_base = 9322  # Different from Tradovate (9222) to avoid conflicts
        port_offset = int(unique_hash[:4], 16) % 100  # 0-99 offset based on unique_id
        debug_port = port_base + port_offset
        self.logger.info(f"[DRIVER] Remote debugging port: {debug_port}")
        chrome_options.add_argument(f"--remote-debugging-port={debug_port}")
        
        # Position windows differently for each pair to avoid overlapping
        pair_num = 0
        try:
            # Handle various pair_id formats: "pair_0", "topstepx_pair_0", "default", etc.
            if "pair_" in self.pair_id:
                # Extract number from formats like "pair_0" or "topstepx_pair_0"
                pair_part = self.pair_id.split("pair_")[-1]  # Get the part after last "pair_"
                pair_num = int(pair_part) if pair_part.isdigit() else 0
            elif self.pair_id.isdigit():
                pair_num = int(self.pair_id)
        except (ValueError, IndexError):
            pair_num = 0  # Fallback to 0 if parsing fails
            
        window_x = 150 + (pair_num * 50)  # Offset from Tradovate windows
        window_y = 100 + (pair_num * 50)
        self.logger.info(f"[DRIVER] Window position: {window_x}, {window_y}")
        chrome_options.add_argument(f"--window-position={window_x},{window_y}")
        
        # SPEED OPTIMIZATION: Essential options only for fastest startup
        self.logger.info("[DRIVER] Adding Chrome options...")
        chrome_options.add_argument("--no-sandbox")  
        chrome_options.add_argument("--disable-dev-shm-usage")  
        chrome_options.add_argument("--disable-gpu")  
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--no-first-run")
        chrome_options.add_argument("--no-default-browser-check")
        chrome_options.add_argument("--disable-features=TranslateUI")
        
        # SPEED OPTIMIZATION: Smaller window for faster rendering
        chrome_options.add_argument("--window-size=1200,800")  # Reduced from 1400,900  
        
        # Anti-detection settings (keep minimal)
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        
        # Minimal preferences to prevent crashes
        prefs = {
            "profile.default_content_setting_values": {
                "popups": 2,  # Block popups only
                "notifications": 2,  # Block notifications only
            }
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        try:
            # Get ChromeDriver path (returns None for auto-management in Selenium 4.15+)
            chromedriver_path = self._get_chromedriver_path()
            
            # Create the WebDriver instance - let Selenium Manager handle ChromeDriver automatically
            self.logger.info("[CHROME] Initializing Chrome browser...")
            self.logger.info("[CHROME] Using Selenium Manager for automatic ChromeDriver version matching")
            self.logger.info("[CHROME] Selenium Manager will download ChromeDriver if needed (happens once per Chrome update)")
            self.logger.info("[CHROME] If already cached, Chrome will launch immediately...")
            
            import time
            start_time = time.time()
            driver = webdriver.Chrome(options=chrome_options)
            elapsed = time.time() - start_time
            
            if elapsed > 5:
                self.logger.info(f"[CHROME] ✓ Chrome launched in {elapsed:.1f}s (ChromeDriver was downloaded/updated)")
            else:
                self.logger.info(f"[CHROME] ✓ Chrome launched in {elapsed:.1f}s (using cached ChromeDriver)")
            
            self.logger.info("[DRIVER] Chrome instance created, setting timeouts...")
            # SPEED OPTIMIZATION: Aggressive timeouts for faster performance
            driver.set_page_load_timeout(15)  # Reduced from 30
            driver.implicitly_wait(2)  # Reduced from 3
            
            # Remove automation detection
            self.logger.info("[DRIVER] Executing anti-detection script...")
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            self.logger.info(f"[DRIVER] Chrome WebDriver initialized successfully for TopStepX {self.username}")
            return driver
            
        except Exception as e:
            self.logger.error(f"[DRIVER ERROR] Failed to initialize Chrome WebDriver: {e}")
            import traceback
            self.logger.error(f"[DRIVER ERROR] Full traceback:\n{traceback.format_exc()}")
            raise Exception(f"ChromeDriver initialization failed: {e}")
    
    def login(self, max_retries=3):
        """
        Login to TopStepX platform
        """
        # Acquire lock to prevent stats fetching during login
        with self.lock:
            if not self.username or not self.password:
                self.logger.error("Username and password are required for TopStepX login")
                return False
            
            for attempt in range(max_retries):
                try:
                    self.logger.info(f"TopStepX login attempt {attempt + 1}/{max_retries}")
                    
                    if not self.driver:
                        if not self.initialize_driver():
                            raise Exception("Failed to initialize WebDriver")
                    
                    # Navigate to login page
                    self.logger.info(f"Navigating to TopStepX login: {self.login_url}")
                    self.driver.get(self.login_url)
                    time.sleep(3)
                    
                    # Log current page info
                    self.logger.info(f"Current URL: {self.driver.current_url}")
                    self.logger.info(f"Page title: {self.driver.title}")
                    
                    # Wait for login form
                    wait = WebDriverWait(self.driver, 15)
                    
                    # Find and fill username field (TopStepX uses 'userName' not 'email')
                    username_field = wait.until(
                        EC.presence_of_element_located((By.NAME, "userName"))
                    )
                    # Highlight existing value and type over it (no deletion needed)
                    username_field.send_keys(Keys.CONTROL + "a")  # Select all existing text
                    time.sleep(0.2)  # Allow selection to complete
                    username_field.send_keys(self.username)  # Type over selected text
                    self.logger.info(f"Username field filled: {self.username}")
                    
                    # Find and fill password field
                    password_field = self.driver.find_element(By.NAME, "password")
                    # Highlight existing value and type over it (no deletion needed)
                    password_field.send_keys(Keys.CONTROL + "a")  # Select all existing text
                    time.sleep(0.2)  # Allow selection to complete
                    password_field.send_keys(self.password)  # Type over selected text
                    self.logger.info("Password field filled")
                    
                    # Click login button (Sign In button)
                    login_button = self.driver.find_element(By.XPATH, "//button[@type='submit']")
                    self.logger.info("Clicking Sign In button")
                    login_button.click()
                    
                    # Wait for page to load after login
                    time.sleep(3)
                    
                    # Wait for either success or error indicators
                    success_indicators = [
                        "dashboard",
                        "trading",
                        "account",
                        "logout"  # logout button indicates successful login
                    ]
                    
                    # Check if login was successful
                    max_wait_time = 15
                    start_time = time.time()
                    
                    while time.time() - start_time < max_wait_time:
                        current_url = self.driver.current_url.lower()
                        page_source = self.driver.page_source.lower()
                        
                        # Check for success indicators
                        if any(indicator in current_url for indicator in success_indicators):
                            self.logged_in = True
                            self._login_timestamp = time.time()  # Track login time
                            self.logger.info(f"TopStepX login successful - redirected to: {current_url}")
                            # Trigger stats update after successful login
                            self._first_stats_fetch = True
                            return True
                        
                        # Check if we're no longer on the login page (indicates success)
                        if "/login" not in current_url and "topstepx.com" in current_url:
                            self.logged_in = True
                            self._login_timestamp = time.time()  # Track login time
                            self.logger.info(f"TopStepX login successful - left login page: {current_url}")
                            # Trigger stats update after successful login
                            self._first_stats_fetch = True
                            return True
                        
                        # Check for error messages or still on login page
                        if "sign in" in page_source and "/login" in current_url:
                            # Still on login page, check for errors
                            error_elements = self.driver.find_elements(By.XPATH, "//*[contains(@class, 'error') or contains(@class, 'alert') or contains(text(), 'invalid') or contains(text(), 'incorrect')]")
                            if error_elements:
                                error_text = error_elements[0].text
                                self.logger.error(f"TopStepX login failed: {error_text}")
                                break
                        
                        time.sleep(1)
                    
                    # If we get here, login likely failed
                    self.logger.error("TopStepX login failed: Timeout or unknown error")
                    
                except TimeoutException:
                    self.logger.error(f"TopStepX login attempt {attempt + 1} timed out")
                except Exception as e:
                    self.logger.error(f"TopStepX login attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries - 1:
                    time.sleep(5)  # Wait before retry
            
            return False
    
    def is_connected(self):
        """Check if we're connected to TopStepX"""
        try:
            if not self.driver or not self.logged_in:
                return False
                
            # Check if we're still on a valid TopStepX page
            current_url = self.driver.current_url
            return "topstepx.com" in current_url and self.logged_in
            
        except Exception:
            return False

    def validate_credentials(self):
        """
        Validate if credentials are set and ready for login
        Returns (is_valid, message)
        """
        if not self.username:
            return False, "Username is required"
        if not self.password:
            return False, "Password is required"
        return True, "Credentials are valid"

    def get_blueprint_config(self, phase_key="challenge_trade1", size_key="50k"):
        """
        Get TopStepX blueprint configuration from PropFirmManager
        Returns config for the specified phase and account size
        """
        if not PROP_FIRM_MANAGER_AVAILABLE:
            logging.warning("PropFirmManager not available - using defaults")
            return {
                'topstepx_symbol': DEFAULT_SYMBOL,
                'topstepx_qty': 1,  
                'topstepx_tp_ticks': DEFAULT_TP,
                'topstepx_sl_ticks': DEFAULT_SL
            }
        
        try:
            manager = PropFirmManager()
            
            # Force TopStep firm code since this is TopStepX integration
            # We don't need to detect from username because we are in the TopStepX module
            firm_code = "TopStep"
            
            # Get strategy config for TopStepX
            manager.set_prop_firm(firm_code)
            config = manager.get_prop_firm_strategy_config(phase_key, size_key)
            
            if config and 'topstepx_symbol' in config:
                logging.info(f"TopStepX blueprint loaded: {phase_key}/{size_key} -> {config}")
                return config
            else:
                logging.warning("No TopStepX-specific config found, using defaults")
                return {
                    'topstepx_symbol': DEFAULT_SYMBOL,
                    'topstepx_qty': 1,
                    'topstepx_tp_ticks': DEFAULT_TP,
                    'topstepx_sl_ticks': DEFAULT_SL
                }
                
        except Exception as e:
            logging.error(f"Failed to get TopStepX blueprint config: {e}")
            return {
                'topstepx_symbol': DEFAULT_SYMBOL,
                'topstepx_qty': 1,
                'topstepx_tp_ticks': DEFAULT_TP,
                'topstepx_sl_ticks': DEFAULT_SL
            }

    def cleanup_chrome_instance(self):
        """
        Clean up Chrome instance for this specific account+pair combination
        Part of MFFU blueprint pattern for proper resource management
        """
        instance_key = f"{self.username}_{self.pair_id}"
        
        try:
            if instance_key in self._chrome_instances:
                driver = self._chrome_instances[instance_key]
                try:
                    driver.quit()
                    logging.info(f"Chrome instance cleaned up for TopStepX: {self.username} (Pair: {self.pair_id})")
                except Exception as e:
                    logging.warning(f"Error closing Chrome instance for TopStepX {self.username}: {e}")
                
                # Remove from registry
                del self._chrome_instances[instance_key]
                
        except Exception as e:
            logging.error(f"Error during TopStepX Chrome cleanup: {e}")

    def disconnect(self):
        """
        Disconnect from TopStepX and clean up resources
        MFFU blueprint standard method
        """
        try:
            self.logged_in = False
            
            if self.driver:
                try:
                    # Try to logout gracefully first
                    if "topstepx.com" in self.driver.current_url:
                        logout_selectors = [
                            "//button[contains(text(), 'Logout')]",
                            "//a[contains(text(), 'Logout')]",
                            "//button[contains(@class, 'logout')]",
                            "//a[contains(@class, 'logout')]"
                        ]
                        
                        for selector in logout_selectors:
                            try:
                                logout_btn = self.driver.find_element(By.XPATH, selector)
                                logout_btn.click()
                                time.sleep(1)
                                logging.info("TopStepX logout successful")
                                break
                            except:
                                continue
                                
                except Exception as e:
                    logging.warning(f"Graceful TopStepX logout failed: {e}")
                
                # Clean up Chrome instance
                self.cleanup_chrome_instance()
                self.driver = None
                
            logging.info(f"TopStepX disconnection completed for {self.username}")
            
        except Exception as e:
            logging.error(f"Error during TopStepX disconnection: {e}")

    def __del__(self):
        """
        Destructor to ensure cleanup on object deletion
        MFFU blueprint standard pattern
        """
        try:
            if hasattr(self, 'driver') and self.driver:
                self.disconnect()
        except:
            pass  # Ignore errors during cleanup
    
    def _capture_delay_snapshot(self, context_name, delay_ms, threshold_ms=200):
        """
        Capture DOM snapshot when a delay exceeds threshold.
        
        Args:
            context_name: Description of what operation was delayed (e.g., "contract_to_quantity")
            delay_ms: Actual delay in milliseconds
            threshold_ms: Threshold in milliseconds (default 200ms)
        """
        if not self._delay_snapshots_enabled or delay_ms < threshold_ms:
            return
        
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Include milliseconds
            
            # Create filename with delay info
            filename = f"delay_snapshot_{context_name}_{int(delay_ms)}ms_{timestamp}.html"
            
            # Capture full page source
            page_source = self.driver.page_source
            
            # Capture focused element info
            focused_element_info = "Unknown"
            try:
                focused = self.driver.execute_script("return document.activeElement.outerHTML;")
                focused_element_info = focused[:500] if focused else "None"
            except:
                pass
            
            # Capture contract field state
            contract_field_info = "Unknown"
            try:
                contract_field = self.driver.find_element(By.XPATH, "//input[contains(@class, 'MuiAutocomplete-input')]")
                contract_field_info = f"Value: '{contract_field.get_attribute('value')}', Enabled: {contract_field.is_enabled()}, Displayed: {contract_field.is_displayed()}"
            except:
                pass
            
            # Capture quantity field state
            quantity_field_info = "Unknown"
            try:
                quantity_field = self.driver.find_element(By.XPATH, "//input[@type='number'][@min='1']")
                quantity_field_info = f"Value: '{quantity_field.get_attribute('value')}', Enabled: {quantity_field.is_enabled()}, Displayed: {quantity_field.is_displayed()}"
            except:
                pass
            
            # Build comprehensive HTML with metadata
            html_content = f"""<!-- DELAY SNAPSHOT -->
<!-- Context: {context_name} -->
<!-- Delay: {delay_ms}ms (threshold: {threshold_ms}ms) -->
<!-- Timestamp: {timestamp} -->
<!-- Current URL: {self.driver.current_url} -->
<!-- Focused Element: {focused_element_info} -->
<!-- Contract Field: {contract_field_info} -->
<!-- Quantity Field: {quantity_field_info} -->

{page_source}
"""
            
            # Write to file
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            self.logger.warning(f"⏱️ DELAY DETECTED: {context_name} took {delay_ms}ms (>{threshold_ms}ms threshold)")
            self.logger.warning(f"📸 Snapshot saved: {filename}")
            
        except Exception as e:
            self.logger.debug(f"Could not capture delay snapshot: {e}")
    
    def get_account_info(self):
        """Get TopStepX account information"""
        try:
            if not self.is_connected():
                raise Exception("Not connected to TopStepX")
            
            # Only navigate to trading page if we're clearly not on a trading-related page
            current_url = self.driver.current_url
            if "/trade" not in current_url and "/dashboard" not in current_url and "/account" not in current_url:
                self.logger.info("Not on trading/account page, navigating to get account info")
                self._ensure_on_trading_page()
            else:
                self.logger.debug("Already on trading/account page, skipping navigation for account info")
            
            account_info = {
                "platform": "TopStepX",
                "status": "Connected",
                "balance": "N/A",
                "equity": "N/A",
                "margin": "N/A",
                "account_type": "N/A"
            }
            
            # Extract account balance information from the interface
            try:
                # Look for balance displays - based on HTML analysis
                balance_selectors = [
                    "//span[contains(text(), 'BAL:')]/following-sibling::span",
                    "//div[contains(@aria-label, 'Current Account Balance')]//span[contains(text(), '$')]",
                    "//span[contains(text(), '$') and contains(@class, 'balance')]"
                ]
                
                for selector in balance_selectors:
                    try:
                        balance_element = self.driver.find_element(By.XPATH, selector)
                        balance_text = balance_element.text.strip()
                        if '$' in balance_text:
                            account_info["balance"] = balance_text
                            account_info["equity"] = balance_text  # Often the same in trading accounts
                            break
                    except:
                        continue
                
                # Look for account type information
                account_type_selectors = [
                    "//span[contains(text(), 'Trading Combine') or contains(text(), 'Funded') or contains(text(), 'Demo')]",
                    "//div[contains(@class, 'account')]//span[contains(text(), 'K')]"
                ]
                
                for selector in account_type_selectors:
                    try:
                        account_element = self.driver.find_element(By.XPATH, selector)
                        account_info["account_type"] = account_element.text.strip()
                        break
                    except:
                        continue
                
                # Look for P&L information
                pnl_selectors = [
                    "//span[contains(text(), 'RP&L:')]/following-sibling::span",
                    "//span[contains(text(), 'UP&L:')]/following-sibling::span"
                ]
                
                realized_pnl = unrealized_pnl = "N/A"
                try:
                    realized_element = self.driver.find_element(By.XPATH, pnl_selectors[0])
                    realized_pnl = realized_element.text.strip()
                except:
                    pass
                
                try:
                    unrealized_element = self.driver.find_element(By.XPATH, pnl_selectors[1])
                    unrealized_pnl = unrealized_element.text.strip()
                except:
                    pass
                
                account_info["realized_pnl"] = realized_pnl
                account_info["unrealized_pnl"] = unrealized_pnl
                
            except Exception as e:
                self.logger.warning(f"Could not extract all account info: {e}")
            
            self.logger.info(f"TopStepX account info retrieved: {account_info}")
            return account_info
            
        except Exception as e:
            self.logger.error(f"Failed to get TopStepX account info: {e}")
            return None

    def get_account_stats(self):
        """Get TopStepX account statistics from positions tab - required by GUI"""
        # Use lock to prevent conflict with order placement
        if not self.lock.acquire(blocking=False):
            # If locked (e.g. placing order), return cached stats immediately
            return getattr(self, '_cached_stats', {
                "Account Number": "Trading...",
                "Balance": "N/A", 
                "Profit/Loss": "N/A",
                "Open Trades": "N/A",
                "Symbol": "",
                "Direction": ""
            })
            
        try:
            if getattr(self, '_placing_order', False):
                return getattr(self, '_cached_stats', {
                    "Account Number": "Trading...",
                    "Balance": "N/A", 
                    "Profit/Loss": "N/A",
                    "Open Trades": "N/A",
                    "Symbol": "",
                    "Direction": ""
                })
            
            # PERFORMANCE OPTIMIZATION: Return cached stats if fetched within the last 2 seconds
            # This prevents excessive DOM queries when GUI polls every 1 second
            cache_ttl = 2.0  # Cache time-to-live in seconds
            current_time = time.time()
            last_fetch_time = getattr(self, '_stats_last_fetch_time', 0)
            time_since_fetch = current_time - last_fetch_time
            
            if time_since_fetch < cache_ttl and hasattr(self, '_cached_stats'):
                # Return cached stats (still fresh)
                return self._cached_stats
            
            try:
                if not self.is_connected():
                    return {
                        "Account Number": "Not Connected",
                        "Balance": "N/A",
                        "Profit/Loss": "N/A",
                        "Open Trades": "N/A",
                        "Symbol": "",
                        "Direction": ""
                    }
                
                # Initialize default stats
                stats = {
                    "Account Number": "Unknown",
                    "Balance": "N/A",
                    "Profit/Loss": "N/A",
                    "Open Trades": "0",
                    "Symbol": "",
                    "Direction": ""
                }
                
                try:
                    # Check if positions data is already visible before clicking tabs
                    positions_visible = False
                    try:
                        # Look for positions grid or position data
                        self.driver.find_element(By.XPATH, "//div[@role='grid'] | //div[contains(@class, 'MuiDataGrid')] | //*[contains(text(), 'Symbol')]")
                        positions_visible = True
                        self.logger.debug("Positions data already visible, skipping tab navigation")
                    except:
                        pass
                    
                    # Navigate to positions tab to extract stats
                    if not positions_visible:
                        if not self.switch_to_positions_tab():
                            self.logger.warning("Could not switch to Positions tab")
                    
                    # Extract stats from positions DataGrid
                    self._extract_positions_stats(stats)
                    
                    # Try to get account balance from top bar or other locations
                    self._extract_account_balance(stats)
                    
                except Exception as e:
                    self.logger.warning(f"Could not extract all stats from positions: {e}")
                
                # Cache the stats WITH TIMESTAMP for performance optimization
                self._cached_stats = stats
                self._stats_last_fetch_time = time.time()
                return stats
                
            except Exception as e:
                self.logger.error(f"Failed to get TopStepX account stats: {e}")
                return {
                    "Account Number": "Error",
                    "Balance": "Error",
                    "Profit/Loss": "Error",
                    "Open Trades": "Error",
                    "Symbol": "",
                    "Direction": ""
                }
        finally:
            self.lock.release()
    
    def _extract_positions_stats(self, stats):
        """Extract statistics from the positions DataGrid"""
        try:
            # Count open positions from the DataGrid rows
            position_rows = self.driver.find_elements(By.XPATH, "//div[@role='row'][@data-id]")
            open_trades_count = len(position_rows)
            stats["Open Trades"] = str(open_trades_count)
            
            if open_trades_count > 0:
                # Get symbol and position info from first position
                try:
                    # Extract symbol from first position row
                    symbol_cell = self.driver.find_element(By.XPATH, "//div[@role='row'][@data-id][1]//div[@data-field='symbolName']")
                    symbol_text = symbol_cell.text.strip()
                    if symbol_text:
                        stats["Symbol"] = symbol_text
                    
                    # Extract position size to determine direction
                    position_cell = self.driver.find_element(By.XPATH, "//div[@role='row'][@data-id][1]//div[@data-field='positionSize']")
                    position_size = position_cell.text.strip()
                    if position_size:
                        try:
                            size_num = int(position_size)
                            stats["Direction"] = "Long" if size_num > 0 else "Short" if size_num < 0 else ""
                        except:
                            stats["Direction"] = "Long"  # Default assumption
                    
                    # Extract P&L from positions
                    pnl_cells = self.driver.find_elements(By.XPATH, "//div[@data-field='profitAndLoss']//span")
                    total_pnl = 0.0
                    for cell in pnl_cells:
                        pnl_text = cell.text.strip()
                        if '$' in pnl_text:
                            try:
                                # Extract numeric value from $-1.00 format
                                pnl_value = float(pnl_text.replace('$', '').replace(',', ''))
                                total_pnl += pnl_value
                            except:
                                continue
                    
                    stats["Profit/Loss"] = f"${total_pnl:.2f}"
                    
                except Exception as e:
                    self.logger.warning(f"Could not extract position details: {e}")
            
        except Exception as e:
            self.logger.warning(f"Could not extract positions stats: {e}")
    
    def _extract_account_balance(self, stats):
        """Extract account balance from various UI locations"""
        try:
            # Look for balance in common locations
            balance_selectors = [
                "//span[contains(text(), 'BAL:')]/following-sibling::span",
                "//div[contains(@class, 'balance')]//span[contains(text(), '$')]",
                "//span[contains(text(), '$') and contains(@class, 'balance')]",
                "//div[contains(@aria-label, 'balance')]//span",
                "//span[text()[contains(., 'Balance')]]/following-sibling::span"
            ]
            
            for selector in balance_selectors:
                try:
                    balance_element = self.driver.find_element(By.XPATH, selector)
                    balance_text = balance_element.text.strip()
                    if '$' in balance_text and any(char.isdigit() for char in balance_text):
                        stats["Balance"] = balance_text
                        break
                except:
                    continue
            
            # Try to get account number from HTML element (most reliable)
            try:
                self.logger.info(f"[ACCOUNT] Looking for account number in HTML elements...")
                
                # Target the specific span element containing the account number
                # <div class="MuiBox-root css-8uhtka"><span>...</span><span>|</span><span>50KTC-V2-342449-32181797</span></div>
                account_selectors = [
                    "//div[contains(@class, 'MuiBox-root')]//span[contains(text(), 'V2-')]",  # Span with V2 in MuiBox
                    "//span[contains(text(), '50KTC-V2-')]",  # Direct span with account pattern
                    "//span[contains(text(), 'V2-') and contains(text(), '-')]",  # Any span with V2 pattern
                    "//div[contains(@class, 'css-8uhtka')]//span[last()]",  # Last span in the specific div
                    "//div[contains(@class, 'css-8uhtka')]//span[3]"  # Third span in the specific div (likely the account number)
                ]
                
                account_found = False
                for i, selector in enumerate(account_selectors):
                    try:
                        account_element = self.driver.find_element(By.XPATH, selector)
                        account_text = account_element.text.strip()
                        self.logger.info(f"[ACCOUNT] Selector {i} found: '{account_text}'")
                        
                        if account_text and "V2-" in account_text and "-" in account_text:
                            # Format: "50KTC-V2-342449-32181797" -> "V2-...1797"
                            account_parts = account_text.split("-")
                            self.logger.info(f"[ACCOUNT] Account parts: {account_parts}")
                            if len(account_parts) >= 4:  # ["50KTC", "V2", "342449", "32181797"]
                                last_part = account_parts[-1]  # "32181797"
                                if len(last_part) >= 4:
                                    formatted_account = f"V2-...{last_part[-4:]}"  # "V2-...1797"
                                    stats["Account Number"] = formatted_account
                                    self.logger.info(f"✅ [ACCOUNT] Formatted TopStepX account number: {formatted_account}")
                                    account_found = True
                                    break
                    except Exception as selector_error:
                        self.logger.debug(f"[ACCOUNT] Selector {i} failed: {selector_error}")
                        continue
                
                if not account_found:
                    self.logger.info(f"[ACCOUNT] No account number found in HTML elements")
                    
            except Exception as e:
                self.logger.warning(f"Could not extract account from HTML: {e}")
            
            # If title extraction didn't work, try page elements  
            if stats["Account Number"] == "Unknown":
                self.logger.info("[ACCOUNT] Title extraction failed, trying page elements...")
                account_selectors = [
                    "//span[contains(text(), 'Account')]/following-sibling::span",
                    "//div[contains(@class, 'account')]//span",
                    "//span[contains(@class, 'account-number')]",
                    "//span[contains(text(), 'Trading Combine')]",  # This might be picking up the wrong text
                    "//span[contains(text(), '50K')]"
                ]
                
                for i, selector in enumerate(account_selectors):
                    try:
                        account_element = self.driver.find_element(By.XPATH, selector)
                        account_text = account_element.text.strip()
                        self.logger.info(f"[ACCOUNT] Selector {i} found: '{account_text}'")
                        
                        if account_text and len(account_text) > 3:
                            # Skip if this is just descriptive text we don't want
                            if account_text in ["$50K TRADING COMBINE", "Trading Combine", "50K"]:
                                self.logger.info(f"[ACCOUNT] Skipping descriptive text: '{account_text}'")
                                continue
                                
                            # Format TopStepX account number like other prop firms
                            # From "50KTC-V2-342449-32181797" to "V2-...1797"
                            if "V2-" in account_text and "-" in account_text:
                                parts = account_text.split("-")
                                # Find V2 part and get last 4 digits of final part
                                v2_index = -1
                                for j, part in enumerate(parts):
                                    if part == "V2":
                                        v2_index = j
                                        break
                                
                                if v2_index >= 0 and len(parts) > v2_index + 1:
                                    last_part = parts[-1]  # Get the last part (32181797)
                                    if len(last_part) >= 4:
                                        formatted_account = f"V2-...{last_part[-4:]}"  # V2-...1797
                                        stats["Account Number"] = formatted_account
                                        self.logger.info(f"✅ [ACCOUNT] Element-based formatted account: {formatted_account}")
                                        break
                            
                            # Only use as fallback if it contains useful info (not descriptive text)
                            if not any(bad_text in account_text for bad_text in ["TRADING", "COMBINE", "50K", "$"]):
                                stats["Account Number"] = account_text
                                self.logger.info(f"[ACCOUNT] Using fallback account text: '{account_text}'")
                                break
                    except Exception as e:
                        self.logger.debug(f"Selector {i} failed: {e}")
                        continue
            
            # Final check - ensure we have a proper account number
            final_account = stats["Account Number"]
            if final_account == "Unknown":
                stats["Account Number"] = "TopStepX"
                self.logger.info("[ACCOUNT] Using final fallback: TopStepX")
            
            self.logger.info(f"🏁 [ACCOUNT] Final account number: '{stats['Account Number']}'")
                
        except Exception as e:
            self.logger.warning(f"Could not extract account balance: {e}")

    def place_order(self, symbol, quantity, side, order_type="market", price=None, tp_dollars=None, sl_dollars=None):
        """Generic method to place orders on TopStepX"""
        try:
            side = side.upper()
            if side == "BUY":
                return self.place_buy_order(symbol, quantity, order_type, tp_dollars, sl_dollars)
            elif side == "SELL":
                return self.place_sell_order(symbol, quantity, order_type, tp_dollars, sl_dollars)
            else:
                raise ValueError(f"Invalid order side: {side}. Must be 'BUY' or 'SELL'")
                
        except Exception as e:
            self.logger.error(f"Failed to place {side} order: {e}")
            return {
                "success": False,
                "message": f"Failed to place {side} order: {e}",
                "platform": "TopStepX"
            }
    
    def prepare_buy_order(self, symbol, quantity):
        """
        THREADING OPTIMIZATION: Prepare BUY order (symbol search, quantity setup) WITHOUT clicking button.
        Use this before threading to minimize time inside parallel execution.
        
        Returns: True if preparation successful, False otherwise
        """
        with self.lock:
            try:
                if not self.is_connected():
                    raise Exception("Not connected to TopStepX")
                
                self.logger.info(f"[⚡ PRE-THREAD] Preparing TopStepX BUY order: {symbol} x{quantity}")
                
                # Ensure we're on the Order tab
                if not self.switch_to_order_tab():
                    self.logger.warning("Could not switch to Order tab")
                    return False
                
                # Step 1: Set contract symbol (SLOW - do this before threading)
                self.logger.info(f"[⚡ PRE-THREAD] Setting symbol: {symbol}")
                if not self._set_contract_symbol(symbol):
                    self.logger.error(f"Failed to set contract symbol: {symbol}")
                    return False
                
                # Step 2: Set quantity (SLOW - do this before threading)
                self.logger.info(f"[⚡ PRE-THREAD] Setting quantity: {quantity}")
                if not self._set_quantity(quantity):
                    self.logger.error(f"Failed to set quantity: {quantity}")
                    return False
                
                self.logger.info(f"✅ [⚡ PRE-THREAD] Order prepared - ready for button click")
                return True
                
            except Exception as e:
                self.logger.error(f"[⚡ PRE-THREAD] Preparation failed: {e}")
                return False
    
    def execute_prepared_buy_order(self):
        """
        THREADING OPTIMIZATION: Execute already-prepared BUY order (just click button).
        Call prepare_buy_order() first, then use this inside threading for instant execution.
        
        Returns: Order result dict
        """
        with self.lock:
            try:
                self.logger.info(f"[⚡ THREAD-EXEC] Clicking BUY button...")
                
                # Just click the button - everything else is already prepared
                if not self._click_buy_button(skip_post_trade_setup=True):
                    raise Exception("Failed to click BUY button")
                
                self.logger.info(f"✅ [⚡ THREAD-EXEC] BUY button clicked")
                
                order_id = f"TSX_BUY_{int(time.time())}"
                return {
                    "success": True,
                    "message": "TopStepX BUY order executed",
                    "order_id": order_id,
                    "platform": "TopStepX",
                    "side": "BUY"
                }
                
            except Exception as e:
                self.logger.error(f"[⚡ THREAD-EXEC] Execution failed: {e}")
                return {
                    "success": False,
                    "message": f"TopStepX BUY execution failed: {e}",
                    "platform": "TopStepX"
                }
    
    def prepare_sell_order(self, symbol, quantity):
        """
        THREADING OPTIMIZATION: Prepare SELL order (symbol search, quantity setup) WITHOUT clicking button.
        Use this before threading to minimize time inside parallel execution.
        
        Returns: True if preparation successful, False otherwise
        """
        with self.lock:
            try:
                if not self.is_connected():
                    raise Exception("Not connected to TopStepX")
                
                self.logger.info(f"[⚡ PRE-THREAD] Preparing TopStepX SELL order: {symbol} x{quantity}")
                
                # Ensure we're on the Order tab
                if not self.switch_to_order_tab():
                    self.logger.warning("Could not switch to Order tab")
                    return False
                
                # Step 1: Set contract symbol (SLOW - do this before threading)
                self.logger.info(f"[⚡ PRE-THREAD] Setting symbol: {symbol}")
                if not self._set_contract_symbol(symbol):
                    self.logger.error(f"Failed to set contract symbol: {symbol}")
                    return False
                
                # Step 2: Set quantity (SLOW - do this before threading)
                self.logger.info(f"[⚡ PRE-THREAD] Setting quantity: {quantity}")
                if not self._set_quantity(quantity):
                    self.logger.error(f"Failed to set quantity: {quantity}")
                    return False
                
                self.logger.info(f"✅ [⚡ PRE-THREAD] Order prepared - ready for button click")
                return True
                
            except Exception as e:
                self.logger.error(f"[⚡ PRE-THREAD] Preparation failed: {e}")
                return False
    
    def execute_prepared_sell_order(self):
        """
        THREADING OPTIMIZATION: Execute already-prepared SELL order (just click button).
        Call prepare_sell_order() first, then use this inside threading for instant execution.
        
        Returns: Order result dict
        """
        with self.lock:
            try:
                self.logger.info(f"[⚡ THREAD-EXEC] Clicking SELL button...")
                
                # Just click the button - everything else is already prepared
                if not self._click_sell_button(skip_post_trade_setup=True):
                    raise Exception("Failed to click SELL button")
                
                self.logger.info(f"✅ [⚡ THREAD-EXEC] SELL button clicked")
                
                order_id = f"TSX_SELL_{int(time.time())}"
                return {
                    "success": True,
                    "message": "TopStepX SELL order executed",
                    "order_id": order_id,
                    "platform": "TopStepX",
                    "side": "SELL"
                }
                
            except Exception as e:
                self.logger.error(f"[⚡ THREAD-EXEC] Execution failed: {e}")
                return {
                    "success": False,
                    "message": f"TopStepX SELL execution failed: {e}",
                    "platform": "TopStepX"
                }

    def place_buy_order(self, symbol, quantity, order_type="market", tp_dollars=None, sl_dollars=None, skip_post_trade_setup=False):
        """
        Place a BUY order on TopStepX with optional post-trade TP/SL setup
        
        Args:
            symbol: Trading symbol (e.g., 'NQM25')
            quantity: Number of contracts
            order_type: Order type (default: 'market')
            tp_dollars: Take profit in dollars
            sl_dollars: Stop loss in dollars
            skip_post_trade_setup: If True, skip TP/SL editing in Positions tab.
                                  Caller should manually call setup_post_trade_tp_sl_positions() later.
                                  Use this in hedging mode to place MT5 trade first for speed.
        """
        # Acquire lock to prevent stats fetching during order placement
        with self.lock:
            try:
                # TIME CHECKPOINT: Start overall timing
                order_start_time = time.time()
                
                if not self.is_connected():
                    raise Exception("Not connected to TopStepX")
                
                if skip_post_trade_setup:
                    self.logger.info(f"⚡ [FAST MODE] Placing TopStepX BUY order: {symbol} x{quantity} (TP/SL setup deferred)")
                else:
                    self.logger.info(f"Placing TopStepX BUY order: {symbol} x{quantity}")
                
                # Ensure we're on the Order tab for trade entry
                if not self.switch_to_order_tab():
                    self.logger.warning("Could not switch to Order tab, attempting trade anyway")
                
                # MANDATORY: Setup TP/SL values are REQUIRED
                if tp_dollars is None and sl_dollars is None:
                    raise Exception("❌ TRADE BLOCKED: TP and SL values are REQUIRED before placing any trade")
                
                if tp_dollars is None or sl_dollars is None:
                    self.logger.warning(f"⚠️  Missing TP or SL: TP=${tp_dollars}, SL=${sl_dollars}")
                    # Set default values if only one is missing
                    if tp_dollars is None:
                        tp_dollars = 500  # Default TP: $500
                        self.logger.warning(f"🔧 Using default TP: ${tp_dollars}")
                    if sl_dollars is None:
                        sl_dollars = 1000  # Default SL: $1000
                        self.logger.warning(f"🔧 Using default SL: ${sl_dollars}")
                
                # Enhanced execution with detailed logging
                self.logger.info(f"[TRADE] Starting TopStepX BUY order execution sequence")
                self.logger.info(f"[PARAMS] Symbol: {symbol}, Quantity: {quantity}, TP: ${tp_dollars}, SL: ${sl_dollars}")
                
                # Set contract symbol with detailed logging
                self.logger.info(f"[STEP 1] Setting contract symbol: {symbol}")
                symbol_result = self._set_contract_symbol(symbol)
                if not symbol_result:
                    error_msg = f"Failed to set contract symbol: {symbol}"
                    self.logger.error(f"❌ [STEP 1] {error_msg}")
                    raise Exception(error_msg)
                else:
                    self.logger.info(f"✅ [STEP 1] Contract symbol set successfully: {symbol}")
                
                # Set quantity with detailed logging
                self.logger.info(f"[STEP 2] Setting quantity: {quantity}")
                quantity_result = self._set_quantity(quantity)
                if not quantity_result:
                    error_msg = f"Failed to set quantity: {quantity}"
                    self.logger.error(f"❌ [STEP 2] {error_msg}")
                    raise Exception(error_msg)
                else:
                    self.logger.info(f"✅ [STEP 2] Quantity set successfully: {quantity}")
                
                # OPTIMIZED: In FAST mode, skip everything and go straight to BUY button
                if skip_post_trade_setup:
                    # FAST MODE: Go directly from quantity → BUY button
                    self.logger.info(f"⚡ [FAST MODE] Skipping order type, TP/SL - going straight to BUY")
                else:
                    # NORMAL MODE: Set order type if not market
                    if order_type.lower() != "market":
                        self.logger.info(f"[STEP 3] Setting order type: {order_type}")
                        if not self._set_order_type(order_type):
                            self.logger.warning(f"⚠️ [STEP 3] Failed to set order type to {order_type}, using market order")
                        else:
                            self.logger.info(f"✅ [STEP 3] Order type set: {order_type}")
                    else:
                        self.logger.info(f"[STEP 3] Using default market order type")
                
                # OPTIMIZED: In FAST mode, TP/SL already skipped above
                if not skip_post_trade_setup:
                    # NORMAL MODE: Set TP/SL on order form before placing trade
                    if tp_dollars and tp_dollars > 0:
                        self.logger.info(f"[STEP 4] Setting Take Profit: ${tp_dollars}")
                        if not self._set_take_profit_price(tp_dollars):
                            self.logger.warning(f"⚠️ [STEP 4] Failed to set Take Profit on order form")
                        else:
                            self.logger.info(f"✅ [STEP 4] Take Profit set: ${tp_dollars}")
                    else:
                        self.logger.info(f"[STEP 4] Skipping Take Profit (tp_dollars={tp_dollars})")
                    
                    if sl_dollars and sl_dollars > 0:
                        self.logger.info(f"[STEP 5] Setting Stop Loss: ${sl_dollars}")
                        if not self._set_stop_loss_price(sl_dollars):
                            self.logger.warning(f"⚠️ [STEP 5] Failed to set Stop Loss on order form")
                        else:
                            self.logger.info(f"✅ [STEP 5] Stop Loss set: ${sl_dollars}")
                    else:
                        self.logger.info(f"[STEP 5] Skipping Stop Loss (sl_dollars={sl_dollars})")
                
                # Click BUY button with detailed loggingging
                self.logger.info(f"[STEP 6] Clicking BUY button")
                buy_result = self._click_buy_button(skip_post_trade_setup=skip_post_trade_setup)
                if not buy_result:
                    error_msg = "Failed to click BUY button"
                    self.logger.error(f"❌ [STEP 6] {error_msg}")
                    raise Exception(error_msg)
                else:
                    self.logger.info(f"✅ [STEP 6] BUY button clicked successfully")
                
                # OPTIMIZED: Minimal wait reduced from 0.3s to 0.1s
                time.sleep(0.1)
                
                # CONDITIONAL: Skip post-trade setup if requested (for hedging mode speed)
                if skip_post_trade_setup:
                    # TIME CHECKPOINT: End timing for fast mode
                    order_end_time = time.time()
                    total_order_time_ms = (order_end_time - order_start_time) * 1000
                    
                    self.logger.info("⚡ FAST MODE: Skipping post-trade TP/SL setup for hedging mode")
                    self.logger.info("📝 Caller should call setup_post_trade_tp_sl_positions() after MT5 hedge placement")
                    self.logger.info(f"⏱️ Total order placement time: {total_order_time_ms:.1f}ms")
                    
                    # Capture snapshot if order placement took too long
                    self._capture_delay_snapshot("fast_order_placement", total_order_time_ms, threshold_ms=1000)
                    
                    order_id = f"TSX_BUY_{int(time.time())}"
                    self.logger.info(f"✅ TopStepX BUY order submitted (fast mode): {symbol} x{quantity}")
                    
                    return {
                    "success": True,
                    "message": f"TopStepX BUY order placed (fast mode): {symbol} x{quantity}",
                    "order_id": order_id,
                    "platform": "TopStepX",
                    "symbol": symbol,
                    "quantity": quantity,
                    "side": "BUY",
                    "tp_dollars": tp_dollars,  # Return these for later setup
                    "sl_dollars": sl_dollars,
                    "placement_time_ms": total_order_time_ms
                    }
                
                # NORMAL MODE: Continue with TP/SL setup as before
                self.logger.info(f"[POST-TRADE] Verifying TP/SL setup")
                
                # Switch to positions tab to verify trade and setup TP/SL if needed
                if tp_dollars or sl_dollars:
                    if self.switch_to_positions_tab():
                        self.logger.info("✅ Switched to Positions tab for TP/SL verification")
                    else:
                        self.logger.warning("⚠ Could not switch to Positions tab")
                
                # Only setup in positions if we couldn't set on order form
                if (tp_dollars and tp_dollars > 0) or (sl_dollars and sl_dollars > 0):
                    setup_result = self.setup_post_trade_tp_sl_positions(tp_dollars, sl_dollars)
                    if not setup_result:
                        self.logger.warning("⚠️ TP/SL setup in positions failed - trade placed but risk not managed")
                    else:
                        self.logger.info("✅ TP/SL setup completed in positions")
                else:
                    self.logger.info("ℹ️ No TP/SL values to set")
                
                order_id = f"TSX_BUY_{int(time.time())}"
                self.logger.info(f"TopStepX BUY order submitted: {symbol} x{quantity}")
                
                # POST-TRADE VERIFICATION: Check what was actually executed (DELAYED)
                # Delay this check significantly to avoid interrupting trade processing
                actual_executed_symbol = None
                try:
                    self.logger.info("[POST-TRADE] Scheduling delayed verification in 3 seconds...")
                    # Use a separate thread or delayed execution to avoid blocking
                    import threading

                    def delayed_verification():
                        try:
                            time.sleep(3)  # Wait longer for trade to fully process
                            # Check positions table for the actual executed symbol
                            stats = self.get_account_stats()
                            if stats and stats.get("Symbol"):
                                executed_symbol = stats["Symbol"]
                                self.logger.info(f"[POST-TRADE] Actual executed symbol: '{executed_symbol}'")

                                # Critical verification
                                if symbol.upper() in ['NQM25', 'NQM26'] and executed_symbol:
                                    if 'MNQ' in executed_symbol.upper() and symbol.upper() not in executed_symbol.upper():
                                        self.logger.error(f"🚨 CRITICAL MISMATCH DETECTED:")
                                        self.logger.error(f"   Requested: {symbol} (full contract)")
                                        self.logger.error(f"   Executed:  {executed_symbol} (micro contract)")
                                        self.logger.error(f"   Result: 5x smaller position size than intended!")
                                    elif executed_symbol.upper() == symbol.upper():
                                        self.logger.info(f"✅ VERIFIED: Correct contract executed - {executed_symbol}")
                                    else:
                                        self.logger.warning(f"⚠️ Unexpected executed symbol: {executed_symbol}")
                        except Exception as verify_error:
                            self.logger.warning(f"Delayed post-trade verification failed: {verify_error}")

                    # Start verification in background thread to avoid blocking
                    verification_thread = threading.Thread(target=delayed_verification, daemon=True)
                    verification_thread.start()

                except Exception as verify_error:
                    self.logger.warning(f"Could not start delayed verification: {verify_error}")
            
                    return {
                        "success": True,
                        "message": f"TopStepX BUY order placed: {symbol} x{quantity}",
                        "order_id": order_id,
                        "platform": "TopStepX",
                        "symbol": symbol,
                        "executed_symbol": actual_executed_symbol or symbol,  # Include actual executed symbol
                        "quantity": quantity,
                        "side": "BUY"
                    }
        
            except Exception as e:
                self.logger.error(f"TopStepX BUY order failed: {e}")
                return {
                    "success": False,
                    "message": f"TopStepX BUY order failed: {e}",
                    "platform": "TopStepX"
                }
    
    def place_sell_order(self, symbol, quantity, order_type="market", tp_dollars=None, sl_dollars=None, skip_post_trade_setup=False):
        """
        Place a SELL order on TopStepX with optional post-trade TP/SL setup
        
        Args:
            symbol: Trading symbol (e.g., 'NQM25')
            quantity: Number of contracts
            order_type: Order type (default: 'market')
            tp_dollars: Take profit in dollars
            sl_dollars: Stop loss in dollars
            skip_post_trade_setup: If True, skip TP/SL editing in Positions tab.
                                  Caller should manually call setup_post_trade_tp_sl_positions() later.
                                  Use this in hedging mode to place MT5 trade first for speed.
        """
        # Acquire lock to prevent stats fetching during order placement
        with self.lock:
            try:
                # TIME CHECKPOINT: Start overall timing
                order_start_time = time.time()
                
                if not self.is_connected():
                    raise Exception("Not connected to TopStepX")
                
                if skip_post_trade_setup:
                    self.logger.info(f"⚡ [FAST MODE] Placing TopStepX SELL order: {symbol} x{quantity} (TP/SL setup deferred)")
                else:
                    self.logger.info(f"Placing TopStepX SELL order: {symbol} x{quantity}")
                
                # Ensure we're on the Order tab for trade entry
                if not self.switch_to_order_tab():
                    self.logger.warning("Could not switch to Order tab, attempting trade anyway")
                
                # MANDATORY: Setup TP/SL values are REQUIRED
                if tp_dollars is None and sl_dollars is None:
                    raise Exception("❌ TRADE BLOCKED: TP and SL values are REQUIRED before placing any trade")
                
                if tp_dollars is None or sl_dollars is None:
                    self.logger.warning(f"⚠️  Missing TP or SL: TP=${tp_dollars}, SL=${sl_dollars}")
                    # Set default values if only one is missing
                    if tp_dollars is None:
                        tp_dollars = 500  # Default TP: $500
                        self.logger.warning(f"🔧 Using default TP: ${tp_dollars}")
                    if sl_dollars is None:
                        sl_dollars = 1000  # Default SL: $1000
                        self.logger.warning(f"🔧 Using default SL: ${sl_dollars}")
                
                # Set contract symbol - re-enabled for exact test replication
                self.logger.info(f"🧪 [EXACT-TEST-SELL] Setting contract symbol: {symbol}")
                if not self._set_contract_symbol(symbol):
                    raise Exception(f"Failed to set contract symbol: {symbol}")
                
                # Set quantity
                self.logger.info(f"[STEP 2] Setting quantity: {quantity}")
                if not self._set_quantity(quantity):
                    raise Exception(f"Failed to set quantity: {quantity}")
                else:
                    self.logger.info(f"✅ [STEP 2] Quantity set successfully: {quantity}")
                
                # OPTIMIZED: In FAST mode, skip everything and go straight to SELL button
                if skip_post_trade_setup:
                    # FAST MODE: Go directly from quantity → SELL button
                    self.logger.info(f"⚡ [FAST MODE] Skipping order type, TP/SL - going straight to SELL")
                else:
                    # NORMAL MODE: Set order type if not market
                    if order_type.lower() != "market":
                        if not self._set_order_type(order_type):
                            self.logger.warning(f"Failed to set order type to {order_type}, using market order")
                
                # OPTIMIZED: In FAST mode, TP/SL already skipped above
                if not skip_post_trade_setup:
                    # NORMAL MODE: Set TP/SL on order form before placing trade
                    if tp_dollars and tp_dollars > 0:
                        self.logger.info(f"Setting Take Profit: ${tp_dollars}")
                        if not self._set_take_profit_price(tp_dollars):
                            self.logger.warning(f"Failed to set Take Profit on order form")
                        else:
                            self.logger.info(f"Take Profit set: ${tp_dollars}")
                    
                    if sl_dollars and sl_dollars > 0:
                        self.logger.info(f"Setting Stop Loss: ${sl_dollars}")
                        if not self._set_stop_loss_price(sl_dollars):
                            self.logger.warning(f"Failed to set Stop Loss on order form")
                        else:
                            self.logger.info(f"Stop Loss set: ${sl_dollars}")
                
                # Click SELL button
                if not self._click_sell_button(skip_post_trade_setup=skip_post_trade_setup):
                    raise Exception("Failed to click SELL button")
                
                # Minimal wait for order processing
                time.sleep(0.1)
                
                # CONDITIONAL: Skip post-trade setup if requested (for hedging mode speed)
                if skip_post_trade_setup:
                    # TIME CHECKPOINT: End timing for fast mode
                    order_end_time = time.time()
                    total_order_time_ms = (order_end_time - order_start_time) * 1000
                    
                    self.logger.info("⚡ FAST MODE: Skipping post-trade TP/SL setup for hedging mode")
                    self.logger.info("📝 Caller should call setup_post_trade_tp_sl_positions() after MT5 hedge placement")
                    self.logger.info(f"⏱️ Total order placement time: {total_order_time_ms:.1f}ms")
                    
                    # Capture snapshot if order placement took too long
                    self._capture_delay_snapshot("fast_sell_order_placement", total_order_time_ms, threshold_ms=1000)
                    
                    order_id = f"TSX_SELL_{int(time.time())}"
                    self.logger.info(f"✅ TopStepX SELL order submitted (fast mode): {symbol} x{quantity}")
                    
                    return {
                        "success": True,
                        "message": f"TopStepX SELL order placed (fast mode): {symbol} x{quantity}",
                        "order_id": order_id,
                        "platform": "TopStepX",
                        "symbol": symbol,
                        "quantity": quantity,
                        "side": "SELL",
                        "tp_dollars": tp_dollars,  # Return these for later setup
                        "sl_dollars": sl_dollars,
                        "placement_time_ms": total_order_time_ms
                    }
                
                # NORMAL MODE: Continue with TP/SL setup as before
                self.logger.info(f"[POST-TRADE] Verifying TP/SL setup")
                
                # Switch to positions tab to verify trade and setup TP/SL if needed
                if tp_dollars or sl_dollars:
                    if self.switch_to_positions_tab():
                        self.logger.info("✅ Switched to Positions tab for TP/SL verification")
                    else:
                        self.logger.warning("⚠ Could not switch to Positions tab")
                
                # Only setup in positions if we couldn't set on order form
                if (tp_dollars and tp_dollars > 0) or (sl_dollars and sl_dollars > 0):
                    setup_result = self.setup_post_trade_tp_sl_positions(tp_dollars, sl_dollars)
                    if not setup_result:
                        self.logger.warning("TP/SL setup in positions failed - trade placed but risk not managed")
                    else:
                        self.logger.info("TP/SL setup completed in positions")
                
                order_id = f"TSX_SELL_{int(time.time())}"
                self.logger.info(f"TopStepX SELL order submitted: {symbol} x{quantity}")
            
                return {
                    "success": True,
                    "message": f"TopStepX SELL order placed: {symbol} x{quantity}",
                    "order_id": order_id,
                    "platform": "TopStepX",
                    "symbol": symbol,
                    "quantity": quantity,
                    "side": "SELL"
                }
        
            except Exception as e:
                self.logger.error(f"TopStepX SELL order failed: {e}")
                return {
                    "success": False,
                    "message": f"TopStepX SELL order failed: {e}",
                    "platform": "TopStepX"
                }
    
    def close_all_positions(self):
        """Close all open positions on TopStepX"""
        try:
            if not self.is_connected():
                raise Exception("Not connected to TopStepX")
            
            self.logger.info("Closing all TopStepX positions")
            
            # Navigate to trading page if not already there
            self._ensure_on_trading_page()
            
            # Click "Flatten All" button to close all positions
            if not self._click_flatten_all_button():
                self.logger.warning("Failed to click Flatten All button, trying alternative methods")
                
                # Alternative: Check for individual position close buttons
                if not self._close_individual_positions():
                    raise Exception("Failed to close positions using any method")
            
            # Wait for positions to close
            time.sleep(2)
            
            self.logger.info("All TopStepX positions closed successfully")
            return {
                "success": True,
                "message": "All TopStepX positions closed",
                "platform": "TopStepX"
            }
            
        except Exception as e:
            self.logger.error(f"Failed to close TopStepX positions: {e}")
            return {
                "success": False,
                "message": f"Failed to close TopStepX positions: {e}",
                "platform": "TopStepX"
            }

    def get_positions(self):
        """Get current positions from TopStepX"""
        try:
            if not self.is_connected():
                raise Exception("Not connected to TopStepX")
            
            self._ensure_on_trading_page()
            
            # Navigate to positions tab if needed
            positions_tab_selectors = [
                "//div[contains(text(), 'Positions')][@role='tab']",
                "//button[contains(text(), 'Positions')]",
                "//tab[contains(text(), 'Position')]"
            ]
            
            for selector in positions_tab_selectors:
                try:
                    positions_tab = self.driver.find_element(By.XPATH, selector)
                    positions_tab.click()
                    time.sleep(1)
                    break
                except:
                    continue
            
            positions = []
            
            # Look for position data in the grid
            try:
                # Check if there are any positions
                no_positions_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'No Positions') or contains(text(), 'No Active Position')]")
                
                if no_positions_elements:
                    self.logger.info("No positions found on TopStepX")
                    return positions
                
                # Try to extract position data from the grid
                position_rows = self.driver.find_elements(By.XPATH, "//div[@role='grid']//div[@role='row'][position()>1]")  # Skip header row
                
                for row in position_rows:
                    try:
                        cells = row.find_elements(By.XPATH, ".//div[@role='gridcell']")
                        if len(cells) >= 4:  # Ensure we have enough data
                            position = {
                                "symbol": cells[1].text.strip() if len(cells) > 1 else "N/A",
                                "quantity": cells[2].text.strip() if len(cells) > 2 else "0",
                                "side": "LONG" if "+" in cells[2].text else "SHORT" if "-" in cells[2].text else "N/A",
                                "entry_price": cells[3].text.strip() if len(cells) > 3 else "N/A",
                                "pnl": cells[6].text.strip() if len(cells) > 6 else "N/A",
                                "platform": "TopStepX"
                            }
                            positions.append(position)
                    except Exception as e:
                        self.logger.warning(f"Failed to parse position row: {e}")
                        continue
                        
            except Exception as e:
                self.logger.warning(f"Failed to extract position data: {e}")
            
            self.logger.info(f"Retrieved {len(positions)} positions from TopStepX")
            return positions
            
        except Exception as e:
            self.logger.error(f"Failed to get TopStepX positions: {e}")
            return []

    def get_orders(self):
        """Get current pending orders from TopStepX"""
        try:
            if not self.is_connected():
                raise Exception("Not connected to TopStepX")
            
            self._ensure_on_trading_page()
            
            # Navigate to orders tab
            orders_tab_selectors = [
                "//div[contains(text(), 'Orders')][@role='tab']",
                "//button[contains(text(), 'Orders')]",
                "//tab[contains(text(), 'Order')]"
            ]
            
            for selector in orders_tab_selectors:
                try:
                    orders_tab = self.driver.find_element(By.XPATH, selector)
                    orders_tab.click()
                    time.sleep(1)
                    break
                except:
                    continue
            
            orders = []
            
            # Look for order data in the grid
            try:
                # Check if there are any orders
                no_orders_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'No Orders') or contains(text(), 'No Pending Orders')]")
                
                if no_orders_elements:
                    self.logger.info("No pending orders found on TopStepX")
                    return orders
                
                # Try to extract order data from the grid
                order_rows = self.driver.find_elements(By.XPATH, "//div[@role='grid']//div[@role='row'][position()>1]")  # Skip header row
                
                for row in order_rows:
                    try:
                        cells = row.find_elements(By.XPATH, ".//div[@role='gridcell']")
                        if len(cells) >= 4:
                            order = {
                                "symbol": cells[1].text.strip() if len(cells) > 1 else "N/A",
                                "quantity": cells[2].text.strip() if len(cells) > 2 else "0",
                                "side": "BUY" if "Buy" in cells[3].text else "SELL" if "Sell" in cells[3].text else "N/A",
                                "order_type": cells[4].text.strip() if len(cells) > 4 else "N/A",
                                "price": cells[5].text.strip() if len(cells) > 5 else "N/A",
                                "status": cells[6].text.strip() if len(cells) > 6 else "PENDING",
                                "platform": "TopStepX"
                            }
                            orders.append(order)
                    except Exception as e:
                        self.logger.warning(f"Failed to parse order row: {e}")
                        continue
                        
            except Exception as e:
                self.logger.warning(f"Failed to extract order data: {e}")
            
            self.logger.info(f"Retrieved {len(orders)} orders from TopStepX")
            return orders
            
        except Exception as e:
            self.logger.error(f"Failed to get TopStepX orders: {e}")
            return []

    def cancel_all_orders(self):
        """Cancel all pending orders on TopStepX"""
        try:
            if not self.is_connected():
                raise Exception("Not connected to TopStepX")
            
            self.logger.info("Cancelling all TopStepX orders")
            
            # Navigate to trading page
            self._ensure_on_trading_page()
            
            # Click "Cancel All" button
            cancel_all_selectors = [
                "//button[contains(text(), 'Cancel All')]",
                "//button[contains(text(), 'CANCEL ALL')]"
            ]
            
            cancel_button = None
            for selector in cancel_all_selectors:
                try:
                    cancel_button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    break
                except TimeoutException:
                    continue
            
            if cancel_button:
                cancel_button.click()
                self.logger.info("Cancel All button clicked")
                
                # Handle confirmation if needed
                time.sleep(1)
                self._handle_order_confirmation()
                
                return {
                    "success": True,
                    "message": "All TopStepX orders cancelled",
                    "platform": "TopStepX"
                }
            else:
                self.logger.warning("Cancel All button not found or not enabled")
                return {
                    "success": False,
                    "message": "Cancel All button not available",
                    "platform": "TopStepX"
                }
                
        except Exception as e:
            self.logger.error(f"Failed to cancel TopStepX orders: {e}")
            return {
                "success": False,
                "message": f"Failed to cancel TopStepX orders: {e}",
                "platform": "TopStepX"
            }

    def edit_position_tp_sl(self, symbol=None, tp_dollars=None, sl_dollars=None):
        """
        Edit Take Profit and Stop Loss for existing positions on TopStepX
        Args:
            symbol: Symbol to edit (optional, if None edits first position)
            tp_dollars: Take Profit amount in dollars
            sl_dollars: Stop Loss amount in dollars
        """
        try:
            if not self.is_connected():
                raise Exception("Not connected to TopStepX")
            
            self.logger.info(f"Editing TP/SL for TopStepX position: TP=${tp_dollars}, SL=${sl_dollars}")
            
            # Navigate to trading page
            self._ensure_on_trading_page()
            
            # Navigate to Positions tab
            if not self._navigate_to_positions_tab():
                raise Exception("Failed to navigate to Positions tab")
            
            # Find the position row to edit
            position_row = self._find_position_row(symbol)
            if not position_row:
                raise Exception(f"Position not found for symbol: {symbol or 'any'}")
            
            # Edit Take Profit if specified
            if tp_dollars is not None:
                if self._edit_position_tp(position_row, tp_dollars):
                    self.logger.info(f"Successfully set TP to ${tp_dollars}")
                else:
                    self.logger.warning(f"Failed to set TP to ${tp_dollars}")
            
            # Edit Stop Loss if specified  
            if sl_dollars is not None:
                if self._edit_position_sl(position_row, sl_dollars):
                    self.logger.info(f"Successfully set SL to ${sl_dollars}")
                else:
                    self.logger.warning(f"Failed to set SL to ${sl_dollars}")
            
            return {
                "success": True,
                "message": f"TopStepX TP/SL updated: TP=${tp_dollars}, SL=${sl_dollars}",
                "platform": "TopStepX"
            }
            
        except Exception as e:
            self.logger.error(f"Failed to edit TopStepX TP/SL: {e}")
            return {
                "success": False,
                "message": f"Failed to edit TopStepX TP/SL: {e}",
                "platform": "TopStepX"
            }

    def _navigate_to_positions_tab(self):
        """Navigate to the Positions tab using TopStepX-specific selectors"""
        try:
            # Look for Positions tab using the exact HTML structure provided
            positions_tab_selectors = [
                # Primary selector based on provided HTML - targets the clickable tab button
                "//div[@role='tab' and contains(@id, 'positionTab')]",
                "//div[@class='dock-tab-btn' and contains(@aria-controls, 'positionTab')]",
                # Secondary selector - targets the drag initiator with Positions text
                "//div[@class='drag-initiator' and @role='tab' and contains(text(), 'Positions')]",
                # Fallback selectors for different UI variations
                "//div[contains(@class, 'dock-tab') and .//text()[contains(., 'Positions')]]",
                "//div[contains(text(), 'Positions')][@role='tab']",
                "//button[contains(text(), 'Positions')]",
                # Generic fallback
                "//div[contains(@class, 'tab') and contains(text(), 'Positions')]"
            ]
            
            self.logger.info("Attempting to navigate to Positions tab...")
            
            for i, selector in enumerate(positions_tab_selectors, 1):
                try:
                    self.logger.debug(f"Trying selector {i}: {selector}")
                    positions_tab = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    
                    # Click the tab
                    positions_tab.click()
                    time.sleep(1.5)  # Allow tab content to load
                    
                    # Verify we're on the positions tab by checking for positions content
                    try:
                        # Look for positions grid or "No Positions" message
                        WebDriverWait(self.driver, 3).until(
                            EC.any_of(
                                EC.presence_of_element_located((By.XPATH, "//div[@role='grid']")),
                                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'No Positions') or contains(text(), 'No Active Position')]"))
                            )
                        )
                        self.logger.info(f"✓ Successfully navigated to Positions tab using selector {i}")
                        return True
                    except TimeoutException:
                        self.logger.warning(f"Tab clicked but positions content not found with selector {i}")
                        continue
                        
                except TimeoutException:
                    self.logger.debug(f"Selector {i} not found: {selector}")
                    continue
                except Exception as e:
                    self.logger.warning(f"Error with selector {i}: {e}")
                    continue
            
            self.logger.error("Could not find or click Positions tab with any selector")
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to navigate to Positions tab: {e}")
            return False

    def _navigate_to_trading_tab(self):
        """Navigate to the Trading tab using TopStepX-specific selectors"""
        try:
            # Look for Trading tab using similar structure to positions tab
            trading_tab_selectors = [
                # Primary selector - targets the trading tab button
                "//div[@role='tab' and contains(@id, 'trading')]",
                "//div[@class='dock-tab-btn' and contains(@aria-controls, 'trading')]",
                # Secondary selector - targets tab with Trading text
                "//div[@class='drag-initiator' and @role='tab' and contains(text(), 'Trading')]",
                # Fallback selectors for different UI variations
                "//div[contains(@class, 'dock-tab') and .//text()[contains(., 'Trading')]]",
                "//div[contains(text(), 'Trading')][@role='tab']",
                "//button[contains(text(), 'Trading')]",
                # Generic fallback
                "//div[contains(@class, 'tab') and contains(text(), 'Trading')]"
            ]
            
            self.logger.info("Attempting to navigate to Trading tab...")
            
            for i, selector in enumerate(trading_tab_selectors, 1):
                try:
                    self.logger.debug(f"Trying selector {i}: {selector}")
                    trading_tab = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    
                    # Click the tab
                    trading_tab.click()
                    time.sleep(1.5)  # Allow tab content to load
                    
                    # Verify we're on the trading tab by checking for trading interface elements
                    try:
                        # Look for Buy/Sell buttons or order form
                        WebDriverWait(self.driver, 3).until(
                            EC.any_of(
                                EC.presence_of_element_located((By.XPATH, "//button[contains(text(), 'Buy') or contains(text(), 'BUY')]")),
                                EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Quantity' or contains(@aria-label, 'Quantity')]"))
                            )
                        )
                        self.logger.info(f"✓ Successfully navigated to Trading tab using selector {i}")
                        return True
                    except TimeoutException:
                        self.logger.warning(f"Tab clicked but trading content not found with selector {i}")
                        continue
                        
                except TimeoutException:
                    self.logger.debug(f"Selector {i} not found: {selector}")
                    continue
                except Exception as e:
                    self.logger.warning(f"Error with selector {i}: {e}")
                    continue
            
            self.logger.error("Could not find or click Trading tab with any selector")
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to navigate to Trading tab: {e}")
            return False

    def _click_order_tab(self):
        """Click the Order tab to access order editing fields after placing an order"""
        try:
            self.logger.info("🎯 Attempting to click Order tab...")
            
            # Simplified selectors based on actual HTML structure
            order_tab_selectors = [
                # Most specific - targets the exact button with orderCardTab ID
                "//div[@role='tab' and contains(@id, 'orderCardTab')]",
                
                # Targets dock-tab-btn with Order text inside
                "//div[@class='dock-tab-btn' and .//span[text()='Order']]",
                
                # Any tab role containing Order text
                "//div[@role='tab' and contains(., 'Order') and not(contains(., 'Positions'))]",
                
                # Broadest fallback
                "//*[contains(@class, 'dock-tab') and .//text()='Order']"
            ]
            
            for i, selector in enumerate(order_tab_selectors, 1):
                try:
                    self.logger.info(f"[ATTEMPT {i}] Trying selector: {selector}")
                    
                    # Try to find the element
                    order_tab = WebDriverWait(self.driver, 3).until(
                        EC.presence_of_element_located((By.XPATH, selector))
                    )
                    
                    self.logger.info(f"✓ Element found with selector {i}")
                    
                    # Try multiple click methods
                    click_success = False
                    
                    # Method 1: Standard click
                    try:
                        order_tab.click()
                        self.logger.info(f"✓ Standard click succeeded")
                        click_success = True
                    except Exception as e:
                        self.logger.warning(f"Standard click failed: {e}")
                    
                    # Method 2: JavaScript click (more reliable)
                    if not click_success:
                        try:
                            self.driver.execute_script("arguments[0].click();", order_tab)
                            self.logger.info(f"✓ JavaScript click succeeded")
                            click_success = True
                        except Exception as e:
                            self.logger.warning(f"JavaScript click failed: {e}")
                    
                    # Method 3: Action chains click
                    if not click_success:
                        try:
                            from selenium.webdriver.common.action_chains import ActionChains
                            ActionChains(self.driver).move_to_element(order_tab).click().perform()
                            self.logger.info(f"✓ ActionChains click succeeded")
                            click_success = True
                        except Exception as e:
                            self.logger.warning(f"ActionChains click failed: {e}")
                    
                    if click_success:
                        self.logger.info(f"✅ Order tab clicked successfully with selector {i}")
                        time.sleep(1.5)  # Allow tab to activate
                        return True
                    else:
                        self.logger.warning(f"All click methods failed for selector {i}")
                        continue
                        
                except TimeoutException:
                    self.logger.debug(f"Selector {i} not found within timeout")
                    continue
                except Exception as e:
                    self.logger.warning(f"Error with selector {i}: {e}")
                    continue
            
            # If all selectors failed, log available tabs for debugging
            self.logger.error("❌ Could not click Order tab with any selector")
            try:
                all_tabs = self.driver.find_elements(By.XPATH, "//div[@role='tab']")
                self.logger.info(f"Available tabs ({len(all_tabs)}):")
                for idx, tab in enumerate(all_tabs):
                    tab_text = tab.text.strip() or tab.get_attribute('id') or 'Unknown'
                    self.logger.info(f"  Tab {idx+1}: {tab_text}")
            except:
                pass
                
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to click Order tab: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def switch_tab(self, tab_name):
        """
        Generic method to switch between tabs in the TopStepX interface
        OPTIMIZED: Fast tab switching with reduced timeouts
        
        Args:
            tab_name (str): Name of the tab to switch to. Options:
                - 'Positions' - View open positions and P&L
                - 'Order' - Access order entry form
                - 'Trades' - View trade history
                - 'Quotes' - View market quotes
                - 'Accounts' - View account information
                - 'Chart' - View charts
        
        Returns:
            bool: True if tab switch was successful, False otherwise
        """
        try:
            # Build selectors based on tab name (prioritize fastest/most reliable)
            selectors = [
                # Strategy 1: By exact text match (fastest)
                f"//div[@role='tab']//div[text()='{tab_name}']",
                # Strategy 2: By tab ID containing the tab name
                f"//div[@role='tab' and contains(@id, '{tab_name.lower()}')]",
                # Strategy 3: By partial text match
                f"//div[@role='tab' and contains(., '{tab_name}')]"
            ]
            
            for selector in selectors:
                try:
                    # FAST: Reduced timeout from 3s to 0.5s per selector
                    tab_element = WebDriverWait(self.driver, 0.5).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    
                    # FAST: Use only JS click for speed
                    self.driver.execute_script("arguments[0].click();", tab_element)
                    time.sleep(0.1)  # Minimal wait - reduced from 0.5s
                    return True
                    
                except TimeoutException:
                    continue
                except Exception:
                    continue
            
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to switch to '{tab_name}' tab: {e}")
            return False
    def switch_to_positions_tab(self):
        """
        Switch to the Positions tab to view open positions
        OPTIMIZED: Fast switch with minimal verification
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Switch to Positions tab
            if not self.switch_tab("Positions"):
                return False
            
            # FAST: Minimal wait - reduced from 3s to 0.5s
            try:
                WebDriverWait(self.driver, 0.5).until(
                    EC.presence_of_element_located((By.XPATH, "//div[@role='grid' or contains(@class, 'MuiDataGrid')]"))
                )
            except TimeoutException:
                pass  # Continue anyway
                
            return True
                
        except Exception as e:
            self.logger.error(f"Failed to switch to Positions tab: {e}")
            return False

    def switch_to_order_tab(self):
        """
        Switch to the Order tab to access order entry form
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Switch to Order tab
            if not self.switch_tab("Order"):
                self.logger.warning("Could not switch to Order tab")
                return False
            
            # Verify Buy button or quantity input is visible after switch
            try:
                WebDriverWait(self.driver, 3).until(
                    EC.any_of(
                        EC.presence_of_element_located((By.XPATH, "//button[contains(text(), 'Buy') or contains(text(), 'BUY')]")),
                        EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Quantity' or contains(@aria-label, 'Quantity')]"))
                    )
                )
                self.logger.debug("Verified order form is visible")
                return True
            except TimeoutException:
                self.logger.warning("Order tab switched but form not visible")
                return True  # Still return True as tab switch succeeded
                
        except Exception as e:
            self.logger.error(f"Failed to switch to Order tab: {e}")
            return False

    def get_active_tab(self):
        """
        Detect which tab is currently active
        
        Returns:
            str: Name of active tab, or None if cannot determine
            
        Example:
            current_tab = self.get_active_tab()
            if current_tab == "Positions":
                # Already on positions tab
                pass
        """
        try:
            # Find element with class 'dock-tab-active'
            active_tab = self.driver.find_element(
                By.XPATH, 
                "//div[contains(@class, 'dock-tab-active')]"
            )
            
            # Extract tab name from text content
            tab_text = active_tab.text.strip()
            
            # Normalize tab name (remove extra characters, emojis, etc.)
            # The Order tab may have emoji and "H" for hotkey
            if "Order" in tab_text:
                return "Order"
            elif "Position" in tab_text:
                return "Positions"
            elif "Trade" in tab_text and "Trader" not in tab_text:
                return "Trades"
            elif "Quote" in tab_text:
                return "Quotes"
            elif "Account" in tab_text:
                return "Accounts"
            elif "Chart" in tab_text:
                return "Chart"
            else:
                # Return the cleaned text
                return tab_text
                
        except Exception as e:
            self.logger.debug(f"Could not detect active tab: {e}")
            return None

    def _find_position_row(self, symbol=None):
        """Find the position row in the positions grid"""
        try:
            # Wait for positions grid to load after tab switch
            self.logger.info("Waiting for positions grid to load...")
            time.sleep(2)
            
            # Check if there are no positions first
            no_positions_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'No Positions') or contains(text(), 'No Active Position') or contains(text(), 'No positions')]")
            if no_positions_elements:
                self.logger.warning("No positions found on TopStepX - positions grid is empty")
                return None
            
            # Look for position rows in the MUI DataGrid with multiple selector patterns
            position_row_selectors = [
                # MUI DataGrid specific selectors (most likely)
                "//div[contains(@class, 'MuiDataGrid-main')]//div[@role='row'][position()>1]",  # MUI DataGrid rows (skip header)
                "//div[@role='grid']//div[@role='row'][position()>1]",  # Standard grid rows (skip header)
                "//div[contains(@class, 'MuiDataGrid-row')]",  # MUI DataGrid row class
                "//div[contains(@class, 'grid')]//div[contains(@class, 'row')][position()>1]",  # Alternative grid structure
                "//table//tr[position()>1]",  # Table-based positions
                "//div[@role='rowgroup']//div[@role='row']"  # Row group structure
            ]
            
            position_rows = []
            for selector in position_row_selectors:
                try:
                    rows = self.driver.find_elements(By.XPATH, selector)
                    if rows:
                        position_rows = rows
                        self.logger.info(f"Found {len(rows)} position rows using selector: {selector}")
                        break
                except Exception as e:
                    self.logger.debug(f"Selector failed: {selector} - {e}")
                    continue
            
            if not position_rows:
                self.logger.warning("No position rows found in grid")
                return None
            
            # If no specific symbol, return first position
            if symbol is None:
                self.logger.info(f"Using first available position (total: {len(position_rows)})")
                return position_rows[0]
            
            # Look for position with matching symbol  
            self.logger.info(f"Searching for position with symbol: {symbol}")
            for i, row in enumerate(position_rows):
                try:
                    # Try different cell selection methods
                    cell_selectors = [
                        ".//div[@role='gridcell']",
                        ".//div[contains(@class, 'cell')]",
                        ".//td"
                    ]
                    
                    cells = []
                    for cell_selector in cell_selectors:
                        cells = row.find_elements(By.XPATH, cell_selector)
                        if cells:
                            break
                    
                    if len(cells) > 1:
                        # Check multiple potential symbol columns (usually column 1 or 2)
                        for col_idx in [1, 2, 0]:  # Try column 1, then 2, then 0
                            if col_idx < len(cells):
                                row_symbol = cells[col_idx].text.strip()
                                if row_symbol and symbol.upper() in row_symbol.upper():
                                    self.logger.info(f"✓ Found position row {i+1} for symbol: {row_symbol} (column {col_idx})")
                                    return row
                                
                        # Log what we found for debugging
                        cell_contents = [cell.text.strip() for cell in cells[:5]]  # First 5 columns
                        self.logger.debug(f"Row {i+1} contents: {cell_contents}")
                        
                except Exception as e:
                    self.logger.warning(f"Failed to check row {i+1} symbol: {e}")
                    continue
            
            self.logger.warning(f"Position not found for symbol: {symbol}")
            # Log available positions for debugging
            try:
                self.logger.info("Available positions:")
                for i, row in enumerate(position_rows[:3]):  # Show first 3 rows
                    cells = row.find_elements(By.XPATH, ".//div[@role='gridcell'] | .//div[contains(@class, 'cell')] | .//td")
                    if cells:
                        cell_contents = [cell.text.strip() for cell in cells[:3]]
                        self.logger.info(f"  Row {i+1}: {cell_contents}")
            except:
                pass
                
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to find position row: {e}")
            return None

    def _edit_position_tp(self, position_row, tp_dollars):
        """Edit Take Profit by clicking the 'To Make' column (data-field='toMake')"""
        try:
            # Find the 'To Make' cell using the exact HTML structure provided
            # Look for MUI DataGrid cell with data-field="toMake"
            to_make_cell_selectors = [
                # Primary selector: exact data-field match for "toMake"
                ".//div[@role='cell' and @data-field='toMake']",
                # Secondary: MUI DataGrid cell with toMake field
                ".//div[contains(@class, 'MuiDataGrid-cell') and @data-field='toMake']",
                # Fallback: cell containing the pencil icon and $ value in toMake context
                ".//div[@role='cell' and contains(@data-field, 'toMake')]",
                # Generic fallback: look for editable cell with $ and pencil icon
                ".//div[@role='cell' and contains(@class, 'editable') and .//span[contains(text(), '$')] and .//svg[@data-icon='pencil']]"
            ]
            
            to_make_cell = None
            for i, selector in enumerate(to_make_cell_selectors, 1):
                try:
                    to_make_cell = position_row.find_element(By.XPATH, selector)
                    self.logger.info(f"✓ Found 'To Make' cell using selector {i}: {selector}")
                    break
                except:
                    self.logger.debug(f"Selector {i} not found: {selector}")
                    continue
            
            if not to_make_cell:
                self.logger.error("Could not find 'To Make' cell with any selector")
                return False
            
            # Click the pencil icon or the cell itself to activate editing
            pencil_icon_selectors = [
                # Click the pencil icon specifically
                ".//svg[@data-icon='pencil']",
                # Click the span containing the $ value
                ".//span[contains(@class, 'css-') and contains(text(), '$')]",
                # Click the cell itself if no pencil found
                "."
            ]
            
            clicked = False
            for selector in pencil_icon_selectors:
                try:
                    click_target = to_make_cell.find_element(By.XPATH, selector)
                    self.logger.info(f"Clicking TP edit target: {selector}")
                    ActionChains(self.driver).click(click_target).perform()
                    clicked = True
                    break
                except:
                    continue
            
            if not clicked:
                # Fallback: double-click the cell directly
                ActionChains(self.driver).double_click(to_make_cell).perform()
            
            time.sleep(0.5)  # Reduced from 1.5s
            
            # Look for input field that appears after clicking
            input_field = None
            
            # First try to get the currently focused element (most reliable)
            try:
                active_element = self.driver.switch_to.active_element
                if active_element and active_element.tag_name == 'input':
                    current_value = active_element.get_attribute("value")
                    if not (current_value and ("1000" in str(current_value) or len(str(current_value).replace(".", "")) > 6)):
                        input_field = active_element
            except:
                pass
            
            # If no focused input found, try our selectors
            if not input_field:
                input_selectors = [
                    # First try to find input within the clicked cell
                    ".//input[@type='text']",
                    ".//input[@type='number']",
                    ".//input[contains(@class, 'MuiInput')]",
                    ".//input",
                    # Then try to find input in the modal/dialog that might appear
                    "//div[contains(@class, 'MuiDialog') or contains(@class, 'modal')]//input[@type='text']",
                    "//div[contains(@class, 'MuiDialog') or contains(@class, 'modal')]//input[@type='number']",
                    # Try any visible input field (but be careful this might find wrong field)
                    "//input[@type='text' and not(@disabled)]",
                    "//input[@type='number' and not(@disabled)]"
                ]
                
                for selector in input_selectors:
                    try:
                        if selector.startswith(".//"):
                            # Search within the To Make cell
                            input_field = to_make_cell.find_element(By.XPATH, selector)
                        else:
                            # Search globally 
                            input_field = WebDriverWait(self.driver, 3).until(
                                EC.element_to_be_clickable((By.XPATH, selector))
                            )
                        self.logger.info(f"Found TP input field: {selector}")
                        break
                    except (TimeoutException, Exception):
                        continue
            
            if input_field:
                # Clear and enter the TP value (FAST - edit only ONCE)
                input_field.click()
                input_field.send_keys(Keys.CONTROL + "a")
                input_field.send_keys(Keys.DELETE)
                input_field.send_keys(str(tp_dollars))
                input_field.send_keys(Keys.ENTER)
                time.sleep(0.3)  # Reduced from 0.5s
                return True
            else:
                self.logger.error("Could not find input field for TP edit")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to edit position TP: {e}")
            return False

    def _edit_position_sl(self, position_row, sl_dollars):
        """Edit Stop Loss by clicking the 'Risk' column (data-field='risk')"""
        try:
            # Find the 'Risk' cell using the exact HTML structure provided
            # Look for MUI DataGrid cell with data-field="risk"
            risk_cell_selectors = [
                # Primary selector: exact data-field match for "risk"
                ".//div[@role='cell' and @data-field='risk']",
                # Secondary: MUI DataGrid cell with risk field
                ".//div[contains(@class, 'MuiDataGrid-cell') and @data-field='risk']",
                # Fallback: cell containing the pencil icon and $ value in risk context
                ".//div[@role='cell' and contains(@data-field, 'risk')]",
                # Generic fallback: look for editable cell with $ and pencil icon (not toMake)
                ".//div[@role='cell' and contains(@class, 'editable') and .//span[contains(text(), '$')] and .//svg[@data-icon='pencil'] and not(@data-field='toMake')]"
            ]
            
            risk_cell = None
            for i, selector in enumerate(risk_cell_selectors, 1):
                try:
                    risk_cell = position_row.find_element(By.XPATH, selector)
                    self.logger.info(f"✓ Found 'Risk' cell using selector {i}: {selector}")
                    break
                except:
                    self.logger.debug(f"Selector {i} not found: {selector}")
                    continue
            
            if not risk_cell:
                self.logger.error("Could not find 'Risk' cell with any selector")
                return False
            
            # Click the pencil icon or the cell itself to activate editing
            pencil_icon_selectors = [
                # Click the pencil icon specifically
                ".//svg[@data-icon='pencil']",
                # Click the span containing the $ value
                ".//span[contains(@class, 'css-') and contains(text(), '$')]",
                # Click the cell itself if no pencil found
                "."
            ]
            
            clicked = False
            for selector in pencil_icon_selectors:
                try:
                    click_target = risk_cell.find_element(By.XPATH, selector)
                    self.logger.info(f"Clicking SL edit target: {selector}")
                    ActionChains(self.driver).click(click_target).perform()
                    clicked = True
                    break
                except:
                    continue
            
            if not clicked:
                # Fallback: double-click the cell directly
                self.logger.info("Fallback: Double-clicking 'Risk' cell directly")
                ActionChains(self.driver).double_click(risk_cell).perform()
            
            time.sleep(1.5)
            
            # Look for input field that appears after clicking
            # Priority: Find the currently focused/active input field first
            input_field = None
            
            # First try to get the currently focused element (most reliable)
            try:
                active_element = self.driver.switch_to.active_element
                if active_element and active_element.tag_name == 'input':
                    # Validate this is not a contract quantity field
                    current_value = active_element.get_attribute("value")
                    if not (current_value and ("1000" in str(current_value) or len(str(current_value).replace(".", "")) > 6)):
                        input_field = active_element
                        self.logger.info("✓ Using focused input field as SL target")
            except Exception as e:
                self.logger.debug(f"Could not get active element: {e}")
            
            # If no focused input found, try our selectors
            if not input_field:
                input_selectors = [
                    # First try to find input within the clicked cell
                    ".//input[@type='text']",
                    ".//input[@type='number']",
                    ".//input[contains(@class, 'MuiInput')]",
                    ".//input",
                    # Then try to find input in the modal/dialog that might appear
                    "//div[contains(@class, 'MuiDialog') or contains(@class, 'modal')]//input[@type='text']",
                    "//div[contains(@class, 'MuiDialog') or contains(@class, 'modal')]//input[@type='number']",
                    # Try any visible input field (but be careful this might find wrong field)
                    "//input[@type='text' and not(@disabled)]",
                    "//input[@type='number' and not(@disabled)]"
                ]
                
                for selector in input_selectors:
                    try:
                        if selector.startswith(".//"):
                            # Search within the Risk cell
                            input_field = risk_cell.find_element(By.XPATH, selector)
                        else:
                            # Search globally 
                            input_field = WebDriverWait(self.driver, 3).until(
                                EC.element_to_be_clickable((By.XPATH, selector))
                            )
                        self.logger.info(f"Found SL input field: {selector}")
                        break
                    except (TimeoutException, Exception):
                        continue
            
            if input_field:
                # Clear and enter the SL value (FAST - edit only ONCE)
                input_field.click()
                input_field.send_keys(Keys.CONTROL + "a")
                input_field.send_keys(Keys.DELETE)
                input_field.send_keys(str(sl_dollars))
                input_field.send_keys(Keys.ENTER)
                time.sleep(0.3)  # Reduced from 0.5s
                return True
            else:
                self.logger.error("Could not find input field for SL edit")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to edit position SL: {e}")
            return False

    def setup_post_trade_tp_sl_positions(self, tp_dollars, sl_dollars):
        """
        Setup TP/SL in the positions section AFTER trade is placed
        OPTIMIZED: Edits each field exactly once with no retries for speed
        """
        try:
            self.logger.info(f"[TP/SL-SETUP] Starting - TP: ${tp_dollars}, SL: ${sl_dollars}")
            
            # CRITICAL: Switch to Positions tab first
            self.logger.info("[TP/SL-SETUP] Switching to Positions tab...")
            if not self.switch_to_positions_tab():
                self.logger.error("[TP/SL-SETUP] ❌ Failed to switch to Positions tab")
                return False
            
            self.logger.info("[TP/SL-SETUP] ✅ On Positions tab")
            
            # Wait for positions grid to load - Increased wait for reliability
            time.sleep(1.5)  # Increased from 0.3s to 1.5s to ensure grid is fully interactive
            self.logger.info("[TP/SL-SETUP] Grid load wait completed")

            # Track if we've successfully edited each field
            sl_edited = False
            tp_edited = False

            # Edit Risk field (SL) - SINGLE EDIT, NO RETRIES
            if sl_dollars and sl_dollars > 0:
                self.logger.info(f"[TP/SL-SETUP] Editing SL (Risk) field: ${sl_dollars}")
                sl_edited = self._edit_sl_field_fast(sl_dollars)
                if sl_edited:
                    self.logger.info("[TP/SL-SETUP] ✅ SL edited successfully")
                else:
                    self.logger.error("[TP/SL-SETUP] ❌ SL edit failed")

            # Edit To Make field (TP) - SINGLE EDIT, NO RETRIES
            if tp_dollars and tp_dollars > 0:
                self.logger.info(f"[TP/SL-SETUP] Editing TP (To Make) field: ${tp_dollars}")
                tp_edited = self._edit_tp_field_fast(tp_dollars)
                if tp_edited:
                    self.logger.info("[TP/SL-SETUP] ✅ TP edited successfully")
                else:
                    self.logger.error("[TP/SL-SETUP] ❌ TP edit failed")

            # Determine overall success
            if tp_dollars and sl_dollars:
                success = tp_edited and sl_edited
                self.logger.info(f"[TP/SL-SETUP] Final result - TP: {tp_edited}, SL: {sl_edited}, Overall: {success}")
            elif tp_dollars:
                success = tp_edited
                self.logger.info(f"[TP/SL-SETUP] Final result - TP only: {tp_edited}")
            elif sl_dollars:
                success = sl_edited
                self.logger.info(f"[TP/SL-SETUP] Final result - SL only: {sl_edited}")
            else:
                success = True  # Nothing to edit
                self.logger.info("[TP/SL-SETUP] No TP/SL values to edit")

            return success

        except Exception as e:
            self.logger.error(f"[TP/SL-SETUP] ❌ Exception during TP/SL setup: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def _edit_sl_field_fast(self, sl_dollars):
        """FAST: Edit SL (Risk) field directly without searching for position row"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.logger.info(f"[FAST-SL] Starting SL edit (Attempt {attempt+1}/{max_retries}): ${sl_dollars}")
                
                # CRITICAL: We need to click on the actual dollar VALUE, not the pencil icon
                # The pencil is just an indicator - clicking the $ value activates editing
                value_selectors = [
                    # Click the span with the dollar value inside the Risk cell
                    "//div[@data-field='risk']//span[contains(text(), '$')]",
                    # Or click anywhere in the Risk cell that's editable
                    "//div[@data-field='risk' and contains(@class, 'MuiDataGrid-cell--editable')]",
                    # Or just the Risk cell itself
                    "//div[@data-field='risk' and @role='cell']",
                ]
                
                clicked = False
                for i, selector in enumerate(value_selectors, 1):
                    try:
                        value_element = WebDriverWait(self.driver, 1.0).until(
                            EC.element_to_be_clickable((By.XPATH, selector))
                        )
                        self.logger.info(f"[FAST-SL] Found Risk value element with selector {i}")
                        
                        # Double-click to activate editing (common pattern for editable grids)
                        from selenium.webdriver.common.action_chains import ActionChains
                        ActionChains(self.driver).double_click(value_element).perform()
                        self.logger.info("[FAST-SL] Double-clicked Risk value")
                        clicked = True
                        break
                    except Exception as e:
                        self.logger.debug(f"[FAST-SL] Selector {i} failed: {e}")
                        continue
                
                if not clicked:
                    self.logger.warning(f"[FAST-SL] Attempt {attempt+1}: Could not find or click Risk value")
                    time.sleep(0.5)
                    continue
                
                time.sleep(0.5)  # Wait for input to appear
                
                # Use active element (most reliable)
                input_field = self.driver.switch_to.active_element
                self.logger.info(f"[FAST-SL] Active element after double-click: {input_field.tag_name if input_field else 'None'}")
                
                if input_field and input_field.tag_name == 'input':
                    self.logger.info(f"[FAST-SL] Found input field, typing ${sl_dollars}")
                    # Clear field and type new value
                    input_field.send_keys(Keys.CONTROL + "a")
                    input_field.send_keys(Keys.DELETE)
                    input_field.send_keys(str(sl_dollars))
                    input_field.send_keys(Keys.ENTER)
                    time.sleep(0.2)  # Minimal wait
                    self.logger.info("[FAST-SL] ✅ SL edit completed")
                    return True
                else:
                    self.logger.warning(f"[FAST-SL] Attempt {attempt+1}: Active element is not an input: {input_field.tag_name if input_field else 'None'}")
                    # Try to find input field manually
                    try:
                        input_field = WebDriverWait(self.driver, 1.0).until(
                            EC.presence_of_element_located((By.XPATH, "//div[@data-field='risk']//input"))
                        )
                        self.logger.info("[FAST-SL] Found input field manually")
                        input_field.send_keys(Keys.CONTROL + "a")
                        input_field.send_keys(Keys.DELETE)
                        input_field.send_keys(str(sl_dollars))
                        input_field.send_keys(Keys.ENTER)
                        time.sleep(0.2)
                        self.logger.info("[FAST-SL] ✅ SL edit completed (manual input find)")
                        return True
                    except Exception as e:
                        self.logger.error(f"[FAST-SL] Could not find input manually: {e}")
                
                # If we got here, something failed but didn't raise exception
                time.sleep(0.5)
                
            except Exception as e:
                self.logger.error(f"[FAST-SL] ❌ Attempt {attempt+1} Exception: {e}")
                time.sleep(0.5)
        
        self.logger.error(f"[FAST-SL] Failed to edit SL after {max_retries} attempts")
        return False

    def _edit_tp_field_fast(self, tp_dollars):
        """FAST: Edit TP (To Make) field directly without searching for position row"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.logger.info(f"[FAST-TP] Starting TP edit (Attempt {attempt+1}/{max_retries}): ${tp_dollars}")
                
                # CRITICAL: We need to click on the actual dollar VALUE, not the pencil icon
                # The pencil is just an indicator - clicking the $ value activates editing
                value_selectors = [
                    # Click the span with the dollar value inside the To Make cell
                    "//div[@data-field='toMake']//span[contains(text(), '$')]",
                    # Or click anywhere in the To Make cell that's editable
                    "//div[@data-field='toMake' and contains(@class, 'MuiDataGrid-cell--editable')]",
                    # Or just the To Make cell itself
                    "//div[@data-field='toMake' and @role='cell']",
                ]
                
                clicked = False
                for i, selector in enumerate(value_selectors, 1):
                    try:
                        value_element = WebDriverWait(self.driver, 1.0).until(
                            EC.element_to_be_clickable((By.XPATH, selector))
                        )
                        self.logger.info(f"[FAST-TP] Found To Make value element with selector {i}")
                        
                        # Double-click to activate editing (common pattern for editable grids)
                        from selenium.webdriver.common.action_chains import ActionChains
                        ActionChains(self.driver).double_click(value_element).perform()
                        self.logger.info("[FAST-TP] Double-clicked To Make value")
                        clicked = True
                        break
                    except Exception as e:
                        self.logger.debug(f"[FAST-TP] Selector {i} failed: {e}")
                        continue
                
                if not clicked:
                    self.logger.warning(f"[FAST-TP] Attempt {attempt+1}: Could not find or click To Make value")
                    time.sleep(0.5)
                    continue
                
                time.sleep(0.5)  # Wait for input to appear
                
                # Use active element (most reliable)
                input_field = self.driver.switch_to.active_element
                self.logger.info(f"[FAST-TP] Active element after double-click: {input_field.tag_name if input_field else 'None'}")
                
                if input_field and input_field.tag_name == 'input':
                    self.logger.info(f"[FAST-TP] Found input field, typing ${tp_dollars}")
                    # Clear field and type new value
                    input_field.send_keys(Keys.CONTROL + "a")
                    input_field.send_keys(Keys.DELETE)
                    input_field.send_keys(str(tp_dollars))
                    input_field.send_keys(Keys.ENTER)
                    time.sleep(0.2)  # Minimal wait
                    self.logger.info("[FAST-TP] ✅ TP edit completed")
                    return True
                else:
                    self.logger.warning(f"[FAST-TP] Attempt {attempt+1}: Active element is not an input: {input_field.tag_name if input_field else 'None'}")
                    # Try to find input field manually
                    try:
                        input_field = WebDriverWait(self.driver, 1.0).until(
                            EC.presence_of_element_located((By.XPATH, "//div[@data-field='toMake']//input"))
                        )
                        self.logger.info("[FAST-TP] Found input field manually")
                        input_field.send_keys(Keys.CONTROL + "a")
                        input_field.send_keys(Keys.DELETE)
                        input_field.send_keys(str(tp_dollars))
                        input_field.send_keys(Keys.ENTER)
                        time.sleep(0.2)
                        self.logger.info("[FAST-TP] ✅ TP edit completed (manual input find)")
                        return True
                    except Exception as e:
                        self.logger.error(f"[FAST-TP] Could not find input manually: {e}")
                
                # If we got here, something failed but didn't raise exception
                time.sleep(0.5)
                
            except Exception as e:
                self.logger.error(f"[FAST-TP] ❌ Attempt {attempt+1} Exception: {e}")
                time.sleep(0.5)
        
        self.logger.error(f"[FAST-TP] Failed to edit TP after {max_retries} attempts")
        return False


    def setup_inline_tp_sl(self, tp_dollars, sl_dollars):
        """
        Set TP/SL using inline editable fields in the data grid (NEW METHOD)
        This replaces the old gear button modal approach
        OPTIMIZED: First checks if values are already correct before attempting edits
        """
        try:
            self.logger.info(f"🎯 Setting up inline TP/SL - SL: ${sl_dollars}, TP: ${tp_dollars}")
            
            # Set Risk (SL) field if sl_dollars > 0
            if sl_dollars > 0:
                # FIRST: Check if Risk field is already set to the correct value
                self.logger.info(f"[CHECK] Checking if Risk field is already set to ${sl_dollars}")
                if self._validate_risk_field_value(sl_dollars):
                    self.logger.info(f"✅ Risk field already correctly set to ${sl_dollars} - skipping edit")
                else:
                    if not self._edit_risk_field(sl_dollars):
                        self.logger.error("Failed to set Risk (SL) field")
                        return False
            else:
                self.logger.info("Skipping Risk field (SL=0)")
            
            # Set To Make (TP) field if tp_dollars > 0  
            if tp_dollars > 0:
                # FIRST: Check if To Make field is already set to the correct value
                self.logger.info(f"[CHECK] Checking if To Make field is already set to ${tp_dollars}")
                if self._validate_to_make_field_value(tp_dollars):
                    self.logger.info(f"✅ To Make field already correctly set to ${tp_dollars} - skipping edit")
                else:
                    if not self._edit_to_make_field(tp_dollars):
                        self.logger.error("Failed to set To Make (TP) field")
                        return False
            else:
                self.logger.info("Skipping To Make field (TP=0)")
            
            self.logger.info("✅ Inline TP/SL setup completed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to setup inline TP/SL: {e}")
            return False
    
    def _edit_risk_field(self, sl_dollars):
        """Edit the Risk field in the data grid to set SL"""
        try:
            self.logger.info(f"🔧 Editing Risk field to ${sl_dollars}")
            
            # Find the Risk field using the data attributes from the HTML
            risk_selectors = [
                "//div[@data-field='risk']//svg[contains(@class, 'fa-pencil')]",
                "//div[@role='cell'][@data-field='risk']//svg[@data-icon='pencil']",
                "//div[contains(@class, 'MuiDataGrid-cell') and @data-field='risk']//svg",
                ".MuiDataGrid-cell[data-field='risk'] svg[data-icon='pencil']"
            ]
            
            # Find and click the pencil icon to start editing
            pencil_icon = None
            for selector in risk_selectors:
                try:
                    if selector.startswith("//"):
                        pencil_icon = self.driver.find_element(By.XPATH, selector)
                    else:
                        pencil_icon = self.driver.find_element(By.CSS_SELECTOR, selector)
                    
                    if pencil_icon.is_displayed():
                        self.logger.info(f"Found Risk pencil icon with selector: {selector}")
                        break
                except:
                    continue
            
            if not pencil_icon:
                self.logger.error("Could not find Risk field pencil icon")
                return False
            
            # Click the pencil icon to start editing
            pencil_icon.click()
            time.sleep(0.5)
            
            # Look for the input field that appears
            input_selectors = [
                "//div[@data-field='risk']//input",
                "//input[contains(@class, 'MuiInputBase-input')]",
                "//div[contains(@class, 'MuiDataGrid-cell') and @data-field='risk']//input"
            ]
            
            input_field = None
            for selector in input_selectors:
                try:
                    input_field = WebDriverWait(self.driver, 3).until(
                        EC.presence_of_element_located((By.XPATH, selector))
                    )
                    if input_field.is_displayed():
                        break
                except:
                    continue
            
            if not input_field:
                self.logger.error("Could not find Risk input field after clicking pencil")
                return False
            
            # Clear and enter the value
            input_field.click()
            time.sleep(0.2)
            input_field.send_keys(Keys.CONTROL + "a")  # Select all
            time.sleep(0.2)
            input_field.send_keys(str(sl_dollars))  # Type new value
            time.sleep(0.3)
            input_field.send_keys(Keys.ENTER)  # Confirm
            time.sleep(0.5)
            
            self.logger.info(f"✅ Risk field set to ${sl_dollars}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to edit Risk field: {e}")
            return False
    
    def _edit_to_make_field(self, tp_dollars):
        """Edit the To Make field in the data grid to set TP"""
        try:
            self.logger.info(f"🔧 Editing To Make field to ${tp_dollars}")
            
            # Find the To Make field using the data attributes from the HTML
            to_make_selectors = [
                "//div[@data-field='toMake']//svg[contains(@class, 'fa-pencil')]",
                "//div[@role='cell'][@data-field='toMake']//svg[@data-icon='pencil']",
                "//div[contains(@class, 'MuiDataGrid-cell') and @data-field='toMake']//svg",
                ".MuiDataGrid-cell[data-field='toMake'] svg[data-icon='pencil']"
            ]
            
            # Find and click the pencil icon to start editing
            pencil_icon = None
            for selector in to_make_selectors:
                try:
                    if selector.startswith("//"):
                        pencil_icon = self.driver.find_element(By.XPATH, selector)
                    else:
                        pencil_icon = self.driver.find_element(By.CSS_SELECTOR, selector)
                    
                    if pencil_icon.is_displayed():
                        self.logger.info(f"Found To Make pencil icon with selector: {selector}")
                        break
                except:
                    continue
            
            if not pencil_icon:
                self.logger.error("Could not find To Make field pencil icon")
                return False
            
            # Click the pencil icon to start editing
            pencil_icon.click()
            time.sleep(0.5)
            
            # Look for the input field that appears
            input_selectors = [
                "//div[@data-field='toMake']//input",
                "//input[contains(@class, 'MuiInputBase-input')]",
                "//div[contains(@class, 'MuiDataGrid-cell') and @data-field='toMake']//input"
            ]
            
            input_field = None
            for selector in input_selectors:
                try:
                    input_field = WebDriverWait(self.driver, 3).until(
                        EC.presence_of_element_located((By.XPATH, selector))
                    )
                    if input_field.is_displayed():
                        break
                except:
                    continue
            
            if not input_field:
                self.logger.error("Could not find To Make input field after clicking pencil")
                return False
            
            # Clear and enter the value
            input_field.click()
            time.sleep(0.2)
            input_field.send_keys(Keys.CONTROL + "a")  # Select all
            time.sleep(0.2)
            input_field.send_keys(str(tp_dollars))  # Type new value
            time.sleep(0.3)
            input_field.send_keys(Keys.ENTER)  # Confirm
            time.sleep(0.5)
            
            self.logger.info(f"✅ To Make field set to ${tp_dollars}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to edit To Make field: {e}")
            return False

    def _edit_positions_risk_field(self, sl_dollars):
        """
        Edit the Risk field (SL) in the positions section by clicking the cell to make it editable
        """
        try:
            self.logger.info(f"🎯 Clicking Risk cell to make it editable for SL=${sl_dollars}")
            
            # First ensure we find the positions table to avoid targeting order form
            positions_table = None
            try:
                positions_table = self.driver.find_element(By.XPATH, "//div[contains(@class, 'MuiDataGrid-root')]")
                self.logger.info("[CONTEXT] Found positions DataGrid table")
            except:
                self.logger.warning("Could not find positions table context")
            
            # Find and double-click the Risk cell directly - matching exact HTML structure
            risk_cell_selectors = [
                "//div[@class='MuiDataGrid-cell--withRenderer MuiDataGrid-cell MuiDataGrid-cell--textCenter MuiDataGrid-cell--editable MuiDataGrid-withBorderColor'][@data-field='risk']",  # Exact match
                "//td[@data-field='risk']",  # Simple Risk cell
                "//div[@data-field='risk']",  # Risk div
                "//td[contains(@class, 'MuiDataGrid-cell--editable') and @data-field='risk']",  # Editable Risk cell
                "//div[contains(@class, 'MuiDataGrid-cell--editable') and @data-field='risk']",  # Editable Risk div
            ]
            
            risk_cell = None
            for selector in risk_cell_selectors:
                try:
                    risk_cell = self.driver.find_element(By.XPATH, selector)
                    if risk_cell.is_displayed():
                        break
                except:
                    continue
            
            if not risk_cell:
                self.logger.error("Could not find Risk cell in positions section")
                return False
            
            # Double-click the cell to make it editable and enter value directly
            self.logger.info(f"[DOUBLE-CLICK] Double-clicking Risk cell to edit value")
            
            # Use ActionChains for reliable double-click
            from selenium.webdriver.common.action_chains import ActionChains
            actions = ActionChains(self.driver)
            actions.double_click(risk_cell).perform()
            time.sleep(0.15)  # Reduced: Wait for cell to become editable
            
            # Type the value directly (cell should now be in edit mode)
            self.logger.info(f"[TYPE] Typing ${sl_dollars} into Risk field")
            
            # SAFEGUARD: Don't proceed if sl_dollars is 0 or invalid
            if not sl_dollars or sl_dollars <= 0:
                self.logger.error(f"❌ BLOCKED: Will not set Risk field to invalid value: {sl_dollars}")
                return False
            
            actions.send_keys(Keys.CONTROL + "a").perform()  # Select all
            time.sleep(0.05)  # Reduced: Brief pause after select all
            
            # SAFEGUARD: Double-check we're about to type a valid value
            value_to_type = str(sl_dollars)
            if not value_to_type or value_to_type in ['0', '0.0', '']:
                self.logger.error(f"❌ BLOCKED: Will not type invalid value: '{value_to_type}'")
                return False
                
            actions.send_keys(value_to_type).perform()  # Type new value
            actions.send_keys(Keys.ENTER).perform()  # Confirm
            time.sleep(0.1)  # Reduced: Brief pause after confirmation
            
            self.logger.info(f"Risk field set to ${sl_dollars}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to edit positions Risk field: {e}")
            return False

    def _edit_positions_to_make_field(self, tp_dollars):
        """
        Edit the To Make field (TP) in the positions section by clicking the cell to make it editable
        """
        try:
            self.logger.info(f"🎯 Clicking To Make cell to make it editable for TP=${tp_dollars}")
            
            # First ensure we find the positions table to avoid targeting order form
            positions_table = None
            try:
                positions_table = self.driver.find_element(By.XPATH, "//div[contains(@class, 'MuiDataGrid-root')]")
                self.logger.info("[CONTEXT] Found positions DataGrid table")
            except:
                self.logger.warning("Could not find positions table context")
            
            # Find and double-click the To Make cell directly - matching exact HTML structure
            to_make_cell_selectors = [
                "//div[@class='MuiDataGrid-cell--withRenderer MuiDataGrid-cell MuiDataGrid-cell--textCenter MuiDataGrid-cell--editable MuiDataGrid-withBorderColor'][@data-field='toMake']",  # Exact match
                "//td[@data-field='toMake']",  # Simple To Make cell
                "//div[@data-field='toMake']",  # To Make div
                "//td[contains(@class, 'MuiDataGrid-cell--editable') and @data-field='toMake']",  # Editable To Make cell
                "//div[contains(@class, 'MuiDataGrid-cell--editable') and @data-field='toMake']",  # Editable To Make div
            ]
            
            to_make_cell = None
            for selector in to_make_cell_selectors:
                try:
                    to_make_cell = self.driver.find_element(By.XPATH, selector)
                    if to_make_cell.is_displayed():
                        break
                except:
                    continue
            
            if not to_make_cell:
                self.logger.error("Could not find To Make cell in positions section")
                return False
            
            # Double-click the cell to make it editable and enter value directly
            self.logger.info(f"[DOUBLE-CLICK] Double-clicking To Make cell to edit value")
            
            # Use ActionChains for reliable double-click
            from selenium.webdriver.common.action_chains import ActionChains
            actions = ActionChains(self.driver)
            actions.double_click(to_make_cell).perform()
            time.sleep(0.15)  # Reduced: Wait for cell to become editable
            
            # Type the value directly (cell should now be in edit mode)
            self.logger.info(f"[TYPE] Typing ${tp_dollars} into To Make field")
            
            # SAFEGUARD: Don't proceed if tp_dollars is 0 or invalid
            if not tp_dollars or tp_dollars <= 0:
                self.logger.error(f"❌ BLOCKED: Will not set To Make field to invalid value: {tp_dollars}")
                return False
            
            actions.send_keys(Keys.CONTROL + "a").perform()  # Select all
            time.sleep(0.05)  # Reduced: Brief pause after select all
            
            # SAFEGUARD: Double-check we're about to type a valid value
            value_to_type = str(tp_dollars)
            if not value_to_type or value_to_type in ['0', '0.0', '']:
                self.logger.error(f"❌ BLOCKED: Will not type invalid value: '{value_to_type}'")
                return False
                
            actions.send_keys(value_to_type).perform()  # Type new value
            actions.send_keys(Keys.ENTER).perform()  # Confirm
            time.sleep(0.1)  # Reduced: Brief pause after confirmation
            
            self.logger.info(f"To Make field set to ${tp_dollars}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to edit positions To Make field: {e}")
            return False

    def _validate_risk_field_value(self, expected_sl_dollars):
        """
        Validate that the Risk field was set to the correct SL value
        Returns True if the value matches, False otherwise
        Uses the same selectors as the editing function for consistency
        """
        try:
            self.logger.info(f"🔍 Validating Risk field value (expected: ${expected_sl_dollars})")

            # Use the same selectors as _edit_position_sl for consistency
            risk_cell_selectors = [
                # Primary selector: exact data-field match for "risk"
                ".//div[@role='cell' and @data-field='risk']",
                # Secondary: MUI DataGrid cell with risk field
                ".//div[contains(@class, 'MuiDataGrid-cell') and @data-field='risk']",
                # Fallback: cell containing the pencil icon and $ value in risk context
                ".//div[@role='cell' and contains(@data-field, 'risk')]",
            ]

            current_value = None
            for selector in risk_cell_selectors:
                try:
                    # Search from the body element to ensure we find the right cell
                    body_element = self.driver.find_element(By.TAG_NAME, "body")
                    risk_cell = body_element.find_element(By.XPATH, selector)
                    text_content = risk_cell.text.strip()

                    # Look for dollar amounts in the text
                    if '$' in text_content or text_content.replace('.', '').replace(',', '').isdigit():
                        current_value = text_content
                        self.logger.debug(f"Found Risk field text: '{text_content}' using selector: {selector}")
                        break
                except:
                    continue

            if current_value:
                # Extract numeric value from the text (remove $ and other chars)
                import re
                # More robust regex to handle various formats: $1,510, $1510, 1510, $1,510.00, etc.
                numeric_match = re.search(r'[\d,]+(?:\.\d+)?', current_value.replace('$', ''))
                if numeric_match:
                    # Remove commas and convert to float
                    clean_value = numeric_match.group().replace(',', '')
                    current_numeric = float(clean_value)
                    expected_numeric = float(expected_sl_dollars)

                    # Check if values match (with small tolerance for float comparison)
                    if abs(current_numeric - expected_numeric) < 0.01:
                        self.logger.info(f"✅ Risk field validation passed: '{current_value}' matches expected ${expected_sl_dollars}")
                        return True
                    else:
                        self.logger.warning(f"❌ Risk field validation failed: '{current_value}' != ${expected_sl_dollars} (parsed: {current_numeric})")
                        return False
                else:
                    self.logger.warning(f"Could not extract numeric value from Risk field: '{current_value}'")
                    return False
            else:
                self.logger.warning("Could not find Risk field value for validation")
                return False

        except Exception as e:
            self.logger.error(f"Error validating Risk field: {e}")
            return False

    def _validate_to_make_field_value(self, expected_tp_dollars):
        """
        Validate that the To Make field was set to the correct TP value
        Returns True if the value matches, False otherwise
        Uses the same selectors as the editing function for consistency
        """
        try:
            self.logger.info(f"🔍 Validating To Make field value (expected: ${expected_tp_dollars})")

            # Use the same selectors as _edit_position_tp for consistency
            to_make_cell_selectors = [
                # Primary selector: exact data-field match for "toMake"
                ".//div[@role='cell' and @data-field='toMake']",
                # Secondary: MUI DataGrid cell with toMake field
                ".//div[contains(@class, 'MuiDataGrid-cell') and @data-field='toMake']",
                # Fallback: cell containing the pencil icon and $ value in toMake context
                ".//div[@role='cell' and contains(@data-field, 'toMake')]",
            ]

            current_value = None
            for selector in to_make_cell_selectors:
                try:
                    # Search from the body element to ensure we find the right cell
                    body_element = self.driver.find_element(By.TAG_NAME, "body")
                    to_make_cell = body_element.find_element(By.XPATH, selector)
                    text_content = to_make_cell.text.strip()

                    # Look for dollar amounts in the text
                    if '$' in text_content or text_content.replace('.', '').replace(',', '').isdigit():
                        current_value = text_content
                        self.logger.debug(f"Found To Make field text: '{text_content}' using selector: {selector}")
                        break
                except:
                    continue

            if current_value:
                # Extract numeric value from the text (remove $ and other chars)
                import re
                # More robust regex to handle various formats: $1,510, $1510, 1510, $1,510.00, etc.
                numeric_match = re.search(r'[\d,]+(?:\.\d+)?', current_value.replace('$', ''))
                if numeric_match:
                    # Remove commas and convert to float
                    clean_value = numeric_match.group().replace(',', '')
                    current_numeric = float(clean_value)
                    expected_numeric = float(expected_tp_dollars)

                    # Check if values match (with small tolerance for float comparison)
                    if abs(current_numeric - expected_numeric) < 0.01:
                        self.logger.info(f"✅ To Make field validation passed: '{current_value}' matches expected ${expected_tp_dollars}")
                        return True
                    else:
                        self.logger.warning(f"❌ To Make field validation failed: '{current_value}' != ${expected_tp_dollars} (parsed: {current_numeric})")
                        return False
                else:
                    self.logger.warning(f"Could not extract numeric value from To Make field: '{current_value}'")
                    return False
            else:
                self.logger.warning("Could not find To Make field value for validation")
                return False

        except Exception as e:
            self.logger.error(f"Error validating To Make field: {e}")
            return False

    def _ensure_on_trading_page(self):
        """Ensure we're on the main trading page and on the Trading tab"""
        try:
            # Check if we're already on the trading page
            current_url = self.driver.current_url
            if "topstepx.com" in current_url and "/login" not in current_url:
                # If we're already on /trade, be more patient waiting for the Buy button
                if "/trade" in current_url:
                    self.logger.info("Already on trading page, waiting for interface to load...")
                    wait = WebDriverWait(self.driver, 20)  # Wait longer if already on /trade
                    try:
                        wait.until(EC.presence_of_element_located((By.XPATH, "//button[contains(text(), 'Buy') or contains(text(), 'BUY')]")))
                        
                        # Also ensure we're on the Trading tab
                        self.logger.info("Ensuring we're on the Trading tab...")
                        if not self._navigate_to_trading_tab():
                            self.logger.warning("Could not navigate to Trading tab, but Buy button found")
                        
                        return True
                    except TimeoutException:
                        self.logger.warning("Buy button not found on /trade page after 20 seconds")
                        pass
                else:
                    # Not on /trade, check if Buy button exists on current page
                    wait = WebDriverWait(self.driver, 5)  # Shorter wait for non-trading pages
                    try:
                        wait.until(EC.presence_of_element_located((By.XPATH, "//button[contains(text(), 'Buy') or contains(text(), 'BUY')]")))
                        return True
                    except TimeoutException:
                        pass
            
            # Only navigate if we're not already on the trading page
            if "/trade" not in current_url:
                trading_url = f"{self.base_url}/trade"
                self.logger.info(f"Navigating to trading page: {trading_url}")
                self.driver.get(trading_url)
                time.sleep(3)
                
                # Wait for trading interface to load
                wait = WebDriverWait(self.driver, 15)
                wait.until(EC.presence_of_element_located((By.XPATH, "//button[contains(text(), 'Buy') or contains(text(), 'BUY')]")))
            else:
                self.logger.warning("Already on /trade but Buy button not found - page may not be fully loaded")
                return False
            
            # Ensure we're on the Trading tab
            self.logger.info("Ensuring we're on the Trading tab...")
            if not self._navigate_to_trading_tab():
                self.logger.warning("Could not navigate to Trading tab after navigating to trading page")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to navigate to trading page: {e}")
            return False
    
    @retry_on_stale_element(max_retries=2, delay=0.5)
    def _set_contract_symbol(self, symbol):
        """
        ULTRA-FAST: Direct symbol entry with minimal waits
        """
        try:
            start_time = time.time()
            
            # Find the contract symbol field (no logging for speed)
            # Try multiple selectors for the symbol field
            symbol_selectors = [
                "//input[contains(@class, 'MuiAutocomplete-input') and @role='combobox']",
                "//input[contains(@class, 'MuiAutocomplete-input')]",
                "//input[@placeholder='Symbol']",
                "//input[@placeholder='Search Symbol']",
                "//input[@aria-label='Symbol']",
                "//input[@type='text' and contains(@class, 'MuiInputBase-input')]"
            ]
            
            symbol_field = None
            for selector in symbol_selectors:
                try:
                    symbol_field = WebDriverWait(self.driver, 1).until(
                        EC.element_to_be_clickable((By.XPATH, selector)))
                    if symbol_field:
                        break
                except:
                    continue
            
            if not symbol_field:
                raise Exception("Could not find symbol input field with any selector")
            
            # COMPLETE CLEAR: Focus, select all, delete, then JS clear to be absolutely sure
            symbol_field.click()
            symbol_field.send_keys(Keys.CONTROL + "a")
            symbol_field.send_keys(Keys.DELETE)
            
            # JS clear to ensure it's 100% empty
            self.driver.execute_script("""
                var field = arguments[0];
                field.value = '';
                field.dispatchEvent(new Event('input', { bubbles: true }));
                field.dispatchEvent(new Event('change', { bubbles: true }));
            """, symbol_field)
            
            # Type first letter to trigger dropdown
            first_char = symbol[0] if symbol else 'N'
            symbol_field.send_keys(first_char)
            time.sleep(0.15)  # Reduced wait
            
            # FAST DROPDOWN: Reduced timeout and no debug logging
            dropdown_clicked = False
            try:
                dropdown_options = WebDriverWait(self.driver, 2).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li.MuiAutocomplete-option"))
                )
                
                # Fast loop - find and click match immediately (no logging)
                for option in dropdown_options:
                    try:
                        spans = option.find_elements(By.TAG_NAME, "span")
                        if len(spans) < 2:
                            continue
                        
                        opt_symbol = spans[0].text.strip().upper()
                        opt_desc = spans[1].text.strip().upper()
                        
                        # Match logic (streamlined)
                        matched = False
                        if symbol.upper() in ['NQM6', 'NQM25', 'NQM26']:
                            matched = (opt_symbol == 'NQM25' or opt_symbol == 'NQM26') and 'MICRO' not in opt_desc
                        elif symbol.upper() in ['MNQM6', 'MNQM25', 'MNQM26']:
                            matched = (opt_symbol == 'MNQM25' or opt_symbol == 'MNQM26') and 'MICRO' in opt_desc
                        elif symbol.upper() in ['NQH6', 'NQH25', 'NQH26']:
                            matched = (opt_symbol == 'NQH25' or opt_symbol == 'NQH26') and 'MICRO' not in opt_desc
                        elif symbol.upper() in ['MNQH6', 'MNQH25', 'MNQH26']:
                            matched = (opt_symbol == 'MNQH25' or opt_symbol == 'MNQH26') and 'MICRO' in opt_desc
                        elif opt_symbol == symbol.upper():
                            matched = True
                        
                        if matched:
                            # Fast click - JS only
                            self.driver.execute_script("arguments[0].click();", option)
                            dropdown_clicked = True
                            time.sleep(0.1)  # Minimal wait
                            break
                    except:
                        continue
                
            except:
                pass  # Silent fail, will use fallback
            
            # FAST VERIFY: Quick check and fallback if needed
            time.sleep(0.15)  # Reduced wait
            
            # Re-find the field for verification using the same robust selectors
            found_field = None
            for selector in symbol_selectors:
                try:
                    found_field = self.driver.find_element(By.XPATH, selector)
                    if found_field and found_field.is_displayed():
                        symbol_field = found_field
                        break
                except:
                    continue
            
            final_value = symbol_field.get_attribute('value') or '' if symbol_field else ''
            
            # Fast fallback: If dropdown didn't work, type directly
            if not dropdown_clicked or final_value.strip().upper() != symbol.upper():
                if symbol_field:
                    # Clear and type full symbol
                    symbol_field.click()
                    symbol_field.send_keys(Keys.CONTROL + "a")
                    symbol_field.send_keys(Keys.DELETE)
                    symbol_field.send_keys(symbol.upper())
                    symbol_field.send_keys(Keys.ENTER)
                    time.sleep(0.15)  # Reduced wait
                    final_value = symbol_field.get_attribute('value') or ''
                else:
                    self.logger.warning("Could not find symbol field for fallback entry")
            
            # Final verification (streamlined)
            success = False
            if final_value:
                if symbol.upper() in ['NQM6', 'NQM25', 'NQM26']:
                    success = 'NQM25' in final_value.upper() or 'NQM26' in final_value.upper()
                elif symbol.upper() in ['MNQM6', 'MNQM25', 'MNQM26']:
                    success = 'MNQM25' in final_value.upper() or 'MNQM26' in final_value.upper()
                elif symbol.upper() in ['NQH6', 'NQH25', 'NQH26']:
                    success = 'NQH25' in final_value.upper() or 'NQH26' in final_value.upper()
                elif symbol.upper() in ['MNQH6', 'MNQH25', 'MNQH26']:
                    success = 'MNQH25' in final_value.upper() or 'MNQH26' in final_value.upper()
                else:
                    success = symbol.upper() in final_value.upper()
            
            elapsed_ms = (time.time() - start_time) * 1000
            
            if success:
                self.logger.info(f"✅ Symbol set: {final_value} ({elapsed_ms:.0f}ms)")
                return True
            else:
                self.logger.error(f"❌ Symbol failed: expected '{symbol}', got '{final_value}'")
                return False
            
        except Exception as e:
            self.logger.error(f"❌ Symbol selection error: {e}")
            return False
    
    def _get_current_contract_symbol(self):
        """Get the currently selected contract symbol from the field"""
        try:
            # Find the contract symbol input field
            symbol_selectors = [
                "input[placeholder*='Search']",
                "input[aria-label*='symbol']", 
                "input[aria-label*='contract']",
                ".MuiAutocomplete-input",
                "input[data-testid*='symbol']"
            ]
            
            for selector in symbol_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        if element.is_displayed():
                            current_value = element.get_attribute('value')
                            if current_value and ('NQ' in current_value or 'MNQ' in current_value):
                                self.logger.info(f"📋 Found current symbol: {current_value}")
                                return current_value
                except:
                    continue
            
            self.logger.warning("⚠️ Could not find current symbol in any field")
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Error getting current symbol: {e}")
            return None
    
    @retry_on_stale_element(max_retries=3, delay=1)
    def _set_quantity(self, quantity):
        """FAST: Set quantity field with minimal waits"""
        try:
            # Fast selector - most specific first
            quantity_field = WebDriverWait(self.driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, "//input[@type='number'][@min='1']"))
            )
            
            # Fast keyboard interaction (triggers React onChange)
            quantity_field.click()
            quantity_field.send_keys(Keys.CONTROL + "a")
            quantity_field.send_keys(str(quantity))
            quantity_field.send_keys(Keys.TAB)
            time.sleep(0.05)  # Minimal wait
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Qty failed: {e}")
            return False
    
    def _set_order_type(self, order_type):
        """Set the order type (Market, Limit, etc.)"""
        try:
            wait = WebDriverWait(self.driver, 10)
            
            # Find order type dropdown
            order_type_selectors = [
                "//div[contains(@aria-label, 'Order Type')]",
                "//select[contains(@id, 'orderType')]",
                "//div[contains(text(), 'Market')]"  # Current order type display
            ]
            
            order_type_field = None
            for selector in order_type_selectors:
                try:
                    order_type_field = wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                    break
                except TimeoutException:
                    continue
            
            if not order_type_field:
                self.logger.warning("Could not find order type field")
                return False
            
            # Click on the dropdown
            order_type_field.click()
            time.sleep(1)
            
            # Select the desired order type
            option_xpath = f"//li[contains(text(), '{order_type.title()}')]"
            try:
                option = self.driver.find_element(By.XPATH, option_xpath)
                option.click()
                time.sleep(0.5)
                
                self.logger.info(f"Order type set to: {order_type}")
                return True
            except:
                self.logger.warning(f"Could not find order type option: {order_type}")
                return False
            
        except Exception as e:
            self.logger.error(f"Failed to set order type: {e}")
            return False
    
    @retry_on_stale_element(max_retries=3, delay=1)
    def _click_buy_button(self, skip_post_trade_setup=False):
        """ULTRA-FAST: Click BUY immediately"""
        try:
            # Fast find and click
            buy_button = WebDriverWait(self.driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Buy')]"))
            )
            self.driver.execute_script("arguments[0].click();", buy_button)
            
            # In fast mode, minimal wait
            if skip_post_trade_setup:
                time.sleep(0.3)
                return True
            
            # Normal mode: handle confirmation
            time.sleep(0.5)
            self._handle_order_confirmation()
            return True
            
        except Exception as e:
            self.logger.error(f"❌ BUY failed: {e}")
            return False
    
    @retry_on_stale_element(max_retries=3, delay=1)
    def _click_sell_button(self, skip_post_trade_setup=False):
        """ULTRA-FAST: Click SELL immediately"""
        try:
            # Fast find and click
            sell_button = WebDriverWait(self.driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Sell')]"))
            )
            self.driver.execute_script("arguments[0].click();", sell_button)
            
            # In fast mode, minimal wait
            if skip_post_trade_setup:
                time.sleep(0.3)
                return True
            
            # Normal mode: handle confirmation
            time.sleep(0.5)
            self._handle_order_confirmation()
            return True
            
        except Exception as e:
            self.logger.error(f"❌ SELL failed: {e}")
            return False
            if not self._click_order_tab():
                self.logger.warning("Failed to click Order tab after SELL button")
            
            # Wait for any confirmation dialogs and handle them
            time.sleep(1)
            self._handle_order_confirmation()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to click SELL button: {e}")
            return False
    
    def _click_flatten_all_button(self):
        """Click the Flatten All button to close all positions"""
        try:
            wait = WebDriverWait(self.driver, 10)
            
            # Find Flatten All button - based on HTML analysis
            flatten_selectors = [
                "//button[contains(text(), 'Flatten All')]",
                "//button[contains(text(), 'Close All')]",
                "//button[contains(text(), 'FLATTEN ALL')]"
            ]
            
            flatten_button = None
            for selector in flatten_selectors:
                try:
                    flatten_button = wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                    break
                except TimeoutException:
                    continue
            
            if not flatten_button:
                self.logger.warning("Could not find Flatten All button")
                return False
            
            # Click the Flatten All button
            flatten_button.click()
            self.logger.info("Flatten All button clicked")
            
            # Handle any confirmation dialogs
            time.sleep(1)
            self._handle_order_confirmation()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to click Flatten All button: {e}")
            return False
    
    def _close_individual_positions(self):
        """Try to close individual positions if Flatten All is not available"""
        try:
            # Look for individual position close buttons
            close_buttons = self.driver.find_elements(By.XPATH, "//button[contains(text(), 'Close Position')]")
            
            if not close_buttons:
                self.logger.warning("No individual position close buttons found")
                return False
            
            for button in close_buttons:
                if button.is_enabled():
                    button.click()
                    time.sleep(1)
                    self._handle_order_confirmation()
            
            self.logger.info("Individual positions closed")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to close individual positions: {e}")
            return False
    
    def _handle_order_confirmation(self):
        """Handle any order confirmation dialogs that may appear"""
        try:
            # Look for confirmation dialogs and click confirm if present
            confirmation_selectors = [
                "//button[contains(text(), 'Confirm')]",
                "//button[contains(text(), 'YES')]",
                "//button[contains(text(), 'OK')]",
                "//button[contains(text(), 'Submit')]"
            ]
            
            for selector in confirmation_selectors:
                try:
                    confirm_button = WebDriverWait(self.driver, 2).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    confirm_button.click()
                    self.logger.info("Order confirmation handled")
                    time.sleep(0.5)
                    break
                except TimeoutException:
                    continue
            
        except Exception as e:
            # No confirmation dialog is fine
            pass

    def disconnect(self):
        """Disconnect from TopStepX and clean up"""
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None
            
            self.logged_in = False
            self.logger.info("Disconnected from TopStepX")
            
        except Exception as e:
            self.logger.error(f"Error during TopStepX disconnect: {e}")
    
    def close(self):
        """
        Close the TopStepX connection and quit Chrome driver
        Alias for disconnect() to match Tradovate interface
        Ensures Chrome browser always closes on disconnect
        """
        self.disconnect()

    def prepare_field_for_input(self, field_element, field_name="Field"):
        """
        Prepare field for new input by selecting all existing content
        Uses highlight-and-type-over approach instead of deletion
        """
        try:
            self.logger.info(f"[PREPARE] Preparing {field_name} for new input")
            
            # Select all existing content (no deletion needed)
            field_element.send_keys(Keys.CONTROL + "a")
            time.sleep(0.2)  # Allow selection to complete
            
            # Verify field is ready for input
            current_value = field_element.get_attribute("value") or ""
            self.logger.info(f"[PREPARE] {field_name} current value: '{current_value}' (will be replaced)")
            
            return True
                
        except Exception as e:
            self.logger.error(f"[CLEAR] Error clearing {field_name}: {e}")
            return False
    
    def _set_field_with_clearing(self, selectors, value, field_name, input_type="text"):
        """
        OPTIMIZED: Generic method to set any field with fast clearing
        FAST-FAIL: Reduced timeout to 0.5s for quick failure on non-existent fields
        """
        try:
            # CRITICAL: Reduced from 3s to 0.5s for fast-fail on missing fields
            wait = WebDriverWait(self.driver, 0.5)
            
            # Find the field using provided selectors
            field_element = None
            for selector in selectors:
                try:
                    field_element = wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                    break
                except TimeoutException:
                    continue
            
            if not field_element:
                self.logger.debug(f"Could not find {field_name} field")
                return False
            
            # OPTIMIZED: Fast JavaScript clear and set (no delays)
            self.driver.execute_script("""
                var field = arguments[0];
                var value = arguments[1];
                field.focus();
                field.value = value;
                field.dispatchEvent(new Event('input', { bubbles: true }));
                field.dispatchEvent(new Event('change', { bubbles: true }));
            """, field_element, str(value))
            
            self.logger.info(f"⚡ {field_name}: {value}")
            return True
            
        except Exception as e:
            self.logger.debug(f"Skip {field_name}: {e}")
            return False
    
    def _set_stop_loss_price(self, price):
        """Set stop loss price if such field exists"""
        stop_loss_selectors = [
            "//input[contains(@placeholder, 'Stop Loss') or contains(@aria-label, 'Stop Loss')]",
            "//input[contains(@id, 'stopLoss') or contains(@id, 'stop-loss')]",
            "//input[contains(@class, 'stop-loss') or contains(@class, 'stopLoss')]",
            "//input[@type='number'][contains(..//label//text(), 'Stop')]"
        ]
        return self._set_field_with_clearing(stop_loss_selectors, price, "Stop Loss Price", "number")
    
    def _set_take_profit_price(self, price):
        """Set take profit price if such field exists"""
        take_profit_selectors = [
            "//input[contains(@placeholder, 'Take Profit') or contains(@aria-label, 'Take Profit')]",
            "//input[contains(@id, 'takeProfit') or contains(@id, 'take-profit')]",
            "//input[contains(@class, 'take-profit') or contains(@class, 'takeProfit')]",
            "//input[@type='number'][contains(..//label//text(), 'Target')]"
        ]
        return self._set_field_with_clearing(take_profit_selectors, price, "Take Profit Price", "number")
    
    def _set_limit_price(self, price):
        """Set limit price if such field exists"""
        limit_price_selectors = [
            "//input[contains(@placeholder, 'Limit Price') or contains(@aria-label, 'Limit Price')]",
            "//input[contains(@id, 'limitPrice') or contains(@id, 'limit-price')]",
            "//input[contains(@class, 'limit-price') or contains(@class, 'limitPrice')]",
            "//input[@type='number'][contains(..//label//text(), 'Limit')]"
        ]
        return self._set_field_with_clearing(limit_price_selectors, price, "Limit Price", "number")
    
    def clear_all_visible_inputs(self):
        """
        Optimized method to quickly clear main trading input fields only
        Focuses on contract and quantity fields for speed
        """
        try:
            # Only clear the essential trading fields for speed
            essential_selectors = [
                "//input[contains(@class, 'MuiAutocomplete-input')]",  # Contract field
                "//input[@type='number'][@min='1']",                    # Quantity field
            ]
            
            cleared_count = 0
            for selector in essential_selectors:
                try:
                    input_elem = self.driver.find_element(By.XPATH, selector)
                    if input_elem.is_displayed() and input_elem.is_enabled():
                        field_value = input_elem.get_attribute("value") or ""
                        
                        if field_value.strip():  # Only clear if it has content
                            # Fast JavaScript clear - no delays
                            self.driver.execute_script("""
                                arguments[0].focus();
                                arguments[0].select();
                                arguments[0].value = '';
                                arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                            """, input_elem)
                            cleared_count += 1
                            
                except Exception:
                    continue  # Skip if field not found
            
            return cleared_count > 0
            
        except Exception as e:
            self.logger.debug(f"Field clearing skipped: {e}")
            return False


    def __del__(self):
        """Cleanup when object is destroyed"""
        self.disconnect()


# Example usage and testing functions
def test_topstepx_connection():
    """Test TopStepX connection with sample credentials"""
    print("🧪 Testing TopStepX Trading Integration")
    print("=" * 50)
    
    # These would need to be real credentials for actual testing
    test_username = input("Enter TopStepX username (or 'skip' to skip test): ")
    if test_username.lower() == 'skip':
        print("⏭️ TopStepX test skipped")
        return
    
    test_password = input("Enter TopStepX password: ")
    
    account = TopStepXAccount(username=test_username, password=test_password)
    
    try:
        print("\n📡 Attempting TopStepX login...")
        if account.login():
            print("✅ TopStepX login successful!")
            
            # Test account info
            print("\n📊 Getting account information...")
            account_info = account.get_account_info()
            if account_info:
                print(f"Account Info: {account_info}")
            
            # Test getting positions
            print("\n📈 Getting current positions...")
            positions = account.get_positions()
            print(f"Positions: {positions}")
            
            # Test getting orders
            print("\n📋 Getting current orders...")
            orders = account.get_orders()
            print(f"Orders: {orders}")
            
            # Ask user if they want to test actual trading
            test_trading = input("\n⚠️ Do you want to test actual order placement? (yes/no): ").lower()
            if test_trading == 'yes':
                print("\n🚨 WARNING: This will place real orders!")
                confirm = input("Type 'CONFIRM' to proceed with live trading test: ")
                
                if confirm == 'CONFIRM':
                    print("\n🔄 Testing order placement...")
                    
                    # Test small market orders
                    symbol = input("Enter symbol to trade (e.g., MNQM25): ") or "MNQM25"
                    quantity = int(input("Enter quantity (default 1): ") or "1")
                    
                    print(f"\n📈 Placing BUY order: {symbol} x{quantity}")
                    buy_result = account.place_buy_order(symbol, quantity)
                    print(f"BUY Result: {buy_result}")
                    
                    if buy_result.get("success"):
                        # Wait a moment then close the position
                        time.sleep(2)
                        print(f"\n📉 Placing SELL order to close: {symbol} x{quantity}")
                        sell_result = account.place_sell_order(symbol, quantity)
                        print(f"SELL Result: {sell_result}")
                    
                    # Test close all positions
                    print("\n🔄 Testing close all positions...")
                    close_result = account.close_all_positions()
                    print(f"Close All Result: {close_result}")
                    
                else:
                    print("🛑 Live trading test cancelled")
            else:
                print("🛑 Order placement test skipped")
                
                # Test order methods without actual execution (dry run)
                print("\n🧪 Testing order methods (dry run)...")
                print("Note: These would place real orders in a live environment")
                
        else:
            print("❌ TopStepX login failed")
            
    except Exception as e:
        print(f"⚠ TopStepX test error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup - disconnect
        try:
            account.disconnect()
            print("� Disconnected from TopStepX")
        except:
            pass


def test_topstepx_connection():
    """Test the TopStepX connection and basic functionality"""
    from dotenv import load_dotenv
    load_dotenv()
    
    account = TopStepXAccount()
    
    try:
        print("🔌 Connecting to TopStepX...")
        if account.connect():
            print("✅ Connected successfully!")
            
            # Test navigation
            print("🧭 Testing navigation...")
            account._ensure_on_trading_page()
            
            print("✅ Basic functionality test passed")
        else:
            print("❌ Connection failed")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🔌 Disconnecting from TopStepX...")
        account.disconnect()
        print("✅ TopStepX test completed")


if __name__ == "__main__":
    test_topstepx_connection()
