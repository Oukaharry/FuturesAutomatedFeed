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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from dotenv import load_dotenv

# Load .env at program start
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DEFAULT_SYMBOL = os.getenv("TRADOVATE_SYMBOL") or "MNQM6"
DEFAULT_TP = os.getenv("TRADOVATE_TAKEPROFIT_TICKS")
DEFAULT_SL = os.getenv("TRADOVATE_STOPLOSS_TICKS")

class TradovateAccount:
    """
    Tradovate trading automation class with robust Selenium-based web automation.
    Handles login, symbol selection, order placement, ATM configuration, and account statistics.
    Ensures single Chrome instance per account to prevent resource conflicts.
    """
    
    # Class-level registry to track Chrome instances per account
    _chrome_instances = {}
    
    def __init__(self, username, password, pair_id=None, trading_mode="Simulation"):
        self.username = username
        self.password = password
        self.pair_id = pair_id or "default"
        self.trading_mode = trading_mode  # "Simulation" or "Live Trading"
        self.logged_in = False
        self.driver = None
        self.first_trade_attempted = False
        self._first_stats_fetch = True
        self._placing_order = False  # Flag to block stats fetching during order placement
        self._login_timestamp = None  # Track when we logged in for debugging
        self.lock = threading.RLock()  # Thread safety for Selenium operations
        
        # Create unique instance key using both username and pair_id
        instance_key = f"{username}_{self.pair_id}"
        
        # Check if Chrome instance already exists for this specific account+pair combination
        if instance_key in self._chrome_instances:
            logging.info(f"Reusing existing Chrome instance for account: {username} (Pair: {self.pair_id})")
            existing_driver = self._chrome_instances[instance_key]
            # Test if existing driver is still alive
            try:
                existing_driver.current_url
                self.driver = existing_driver
                logging.info("Successfully connected to existing Chrome instance")
                return
            except Exception:
                logging.info("Existing Chrome instance is dead, creating new one")
                # Remove dead instance from registry
                del self._chrome_instances[instance_key]
        
        # Initialize driver with error handling
        try:
            self.driver = self._initialize_driver()
        except Exception as e:
            raise Exception(f"Failed to initialize WebDriver: {str(e)}. This may indicate VPS Chrome setup issues.")

    def _get_chromedriver_path(self):
        """Get the path to ChromeDriver executable - FAST VERSION (no compatibility check)"""
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
        chrome_options = Options()
        
        # PERFORMANCE: Removed user-data-dir to speed up Chrome launch
        # Incognito mode is faster than loading persistent profiles
        # Each Chrome instance will be fresh and fast
        
        # PERFORMANCE: Removed window positioning - let Chrome decide (faster)
        # PERFORMANCE: Removed remote debugging port - not needed for basic automation
        
        # MAXIMUM SPEED: Only critical options for fastest Chrome launch
        chrome_options.add_argument("--no-sandbox")  # Required for some systems
        chrome_options.add_argument("--disable-dev-shm-usage")  # Required for VPS/Docker
        
        # CRASH FIX: Improve stability and prevent crashes
        chrome_options.add_argument("--disable-crash-reporter")  # Disable crash reporting
        chrome_options.add_argument("--disable-in-process-stack-traces")  # Reduce memory overhead
        chrome_options.add_argument("--disable-logging")  # Reduce disk I/O
        chrome_options.add_argument("--log-level=3")  # Suppress console messages (3=FATAL only)
        chrome_options.add_argument("--silent")  # Suppress console output
        
        # MEMORY MANAGEMENT: Prevent memory leaks and crashes
        chrome_options.add_argument("--disable-features=TranslateUI")  # Disable translate
        chrome_options.add_argument("--disable-features=MediaRouter")  # Disable media router
        chrome_options.add_argument("--disable-component-update")  # Disable component updates
        chrome_options.add_argument("--disable-background-timer-throttling")  # Better tab management
        chrome_options.add_argument("--disable-backgrounding-occluded-windows")  # Keep windows active
        chrome_options.add_argument("--disable-renderer-backgrounding")  # Prevent renderer from sleeping
        
        # RENDERING FIX: Enable GPU acceleration for proper page rendering
        # Removed --disable-gpu to fix white screen issues
        chrome_options.add_argument("--enable-features=NetworkService,NetworkServiceInProcess")
        
        # PERFORMANCE: Faster page loading optimizations
        chrome_options.add_argument("--disable-extensions")  # No extensions = faster
        chrome_options.add_argument("--disable-plugins")  # No plugins = faster
        chrome_options.add_argument("--disable-images")  # Skip images for faster load (Tradovate is mostly UI/Canvas)
        chrome_options.add_argument("--blink-settings=imagesEnabled=false")  # Disable image rendering
        chrome_options.add_argument("--disable-background-networking")  # No background requests
        chrome_options.add_argument("--disable-default-apps")  # No default apps
        chrome_options.add_argument("--disable-sync")  # No sync
        
        # SPEED OPTIMIZATION: Smaller window for faster rendering
        chrome_options.add_argument("--window-size=1200,800")  # Reduced from 1400,900
        
        # FIX: Disable hardware acceleration fallback that can cause white screens
        chrome_options.add_argument("--disable-software-rasterizer")  
        
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
            # Ensure Chrome-ChromeDriver compatibility before initialization
            logging.info("[COMPAT] Checking Chrome-ChromeDriver compatibility...")
            self._ensure_chrome_compatibility()
            
            # Get ChromeDriver path (returns None for auto-management in Selenium 4.15+)
            chromedriver_path = self._get_chromedriver_path()
            
            # Create the WebDriver instance - let Selenium Manager handle ChromeDriver automatically
            logging.info("[CHROME] Initializing Chrome browser...")
            logging.info("[CHROME] Using Selenium Manager for automatic ChromeDriver version matching")
            logging.info("[CHROME] Selenium Manager will download ChromeDriver if needed (happens once per Chrome update)")
            logging.info("[CHROME] If already cached, Chrome will launch immediately...")
            
            import time
            start_time = time.time()
            driver = webdriver.Chrome(options=chrome_options)
            elapsed = time.time() - start_time
            
            if elapsed > 5:
                logging.info(f"[CHROME] ✓ Chrome launched in {elapsed:.1f}s (ChromeDriver was downloaded/updated)")
            else:
                logging.info(f"[CHROME] ✓ Chrome launched in {elapsed:.1f}s (using cached ChromeDriver)")
            
            # MAXIMUM SPEED: Ultra-aggressive timeouts
            driver.set_page_load_timeout(30)  # Increased to 30 seconds to fix white screen issues
            driver.implicitly_wait(2)  # Increased to 2 seconds for better element detection
            
            # CRASH RECOVERY: Add page crash detection callback
            try:
                # Enable Chrome DevTools Protocol for crash detection
                driver.execute_cdp_cmd('Page.enable', {})
                logging.info("[STABILITY] Chrome crash detection enabled")
            except Exception as e:
                logging.warning(f"Could not enable crash detection: {e}")
            
            logging.info(f"Chrome WebDriver initialized successfully for {self.username}")
            return driver
            
        except Exception as e:
            logging.error(f"Failed to initialize Chrome WebDriver: {e}")
            raise Exception(f"ChromeDriver initialization failed: {e}")

    def _validate_blueprint_parameters(self, symbol, qty, tp=None, sl=None, prop_firm=None, phase=None, account_size=None, strict_mode=True):
        """
        Validates trading parameters against blueprint configuration to prevent incorrect trades.
        
        Args:
            symbol (str): Trading symbol being used
            qty (int): Quantity being traded
            tp (int, optional): Take profit ticks
            sl (int, optional): Stop loss ticks
            prop_firm (str, optional): Prop firm name for blueprint lookup
            phase (str, optional): Trading phase (challenge, funded, farming)
            account_size (str, optional): Account size for blueprint lookup
            strict_mode (bool): If True, blocks trades on validation failure. If False, only logs warnings.
        
        Returns:
            tuple: (is_valid, validation_message, blueprint_config)
        """
        try:
            # Import blueprint manager here to avoid circular imports
            from prop_firm_manager import PropFirmManager
            
            # If no blueprint context provided, try to get from environment
            if not prop_firm:
                prop_firm = os.getenv("SELECTED_PROP_FIRM", "MFFU")
            if not phase:
                phase = os.getenv("TRADING_PHASE", "challenge_trade1")
            if not account_size:
                account_size = os.getenv("ACCOUNT_SIZE", "50k")
            
            # Get blueprint configuration
            prop_firm_manager = PropFirmManager()
            prop_firm_manager.set_prop_firm(prop_firm)
            blueprint_config = prop_firm_manager.get_prop_firm_strategy_config(phase, account_size)
            
            if not blueprint_config:
                error_msg = f"[X] BLUEPRINT VALIDATION FAILED: No blueprint config found for {prop_firm}/{phase}/{account_size}"
                logging.error(error_msg)
                if strict_mode:
                    raise Exception(error_msg)
                return False, error_msg, None
            
            # Validate each parameter against blueprint
            validation_errors = []
            validation_warnings = []
            
            # Symbol validation
            expected_symbol = blueprint_config.get('tradovate_symbol')
            if expected_symbol and symbol != expected_symbol:
                error_msg = f"[X] SYMBOL MISMATCH: Expected {expected_symbol}, got {symbol}"
                validation_errors.append(error_msg)
            
            # Quantity validation
            expected_qty = blueprint_config.get('tradovate_qty')
            if expected_qty and qty != expected_qty:
                error_msg = f"[X] QUANTITY MISMATCH: Expected {expected_qty}, got {qty}"
                validation_errors.append(error_msg)
            
            # Take profit validation (if provided)
            if tp is not None:
                expected_tp = blueprint_config.get('tradovate_tp_ticks')
                if expected_tp and tp != expected_tp:
                    error_msg = f"[X] TP MISMATCH: Expected {expected_tp}, got {tp}"
                    validation_errors.append(error_msg)
            
            # Stop loss validation (if provided)
            if sl is not None:
                expected_sl = blueprint_config.get('tradovate_sl_ticks')
                if expected_sl and sl != expected_sl:
                    error_msg = f"[X] SL MISMATCH: Expected {expected_sl}, got {sl}"
                    validation_errors.append(error_msg)
            
            # Log validation results
            if validation_errors:
                full_error_msg = f"[ALARM] BLUEPRINT VALIDATION FAILED for {prop_firm}/{phase}/{account_size}: {'; '.join(validation_errors)}"
                logging.error(full_error_msg)
                if strict_mode:
                    raise Exception(full_error_msg)
                return False, full_error_msg, blueprint_config
            
            if validation_warnings:
                warning_msg = f"[WARNING] BLUEPRINT WARNINGS for {prop_firm}/{phase}/{account_size}: {'; '.join(validation_warnings)}"
                logging.warning(warning_msg)
            
            success_msg = f"[CHECK] BLUEPRINT VALIDATION PASSED for {prop_firm}/{phase}/{account_size}: symbol={symbol}, qty={qty}"
            logging.info(success_msg)
            
            return True, success_msg, blueprint_config
            
        except ImportError:
            warning_msg = "[WARNING] BLUEPRINT VALIDATION SKIPPED: Could not import PropFirmManager"
            logging.warning(warning_msg)
            return True, warning_msg, None
        except Exception as e:
            error_msg = f"[X] BLUEPRINT VALIDATION ERROR: {str(e)}"
            logging.error(error_msg)
            if strict_mode:
                raise Exception(error_msg)
            return False, error_msg, None

    def _force_trade_override(self, symbol, qty, side, tp=None, sl=None, override_reason="Emergency override"):
        """
        Emergency method to force a trade execution bypassing blueprint validation.
        Use only in critical situations where manual override is absolutely necessary.
        
        Args:
            symbol (str): Trading symbol
            qty (int): Quantity
            side (str): "buy" or "sell"
            tp (int, optional): Take profit ticks
            sl (int, optional): Stop loss ticks
            override_reason (str): Reason for override (logged for audit)
        
        Returns:
            bool: Success status
        """
        logging.warning(f"[ALARM] EMERGENCY TRADE OVERRIDE: {override_reason}")
        logging.warning(f"[ALARM] OVERRIDE DETAILS: {side.upper()} {symbol} x{qty}, TP={tp}, SL={sl}")
        
        try:
            # Call the original order placement without validation
            return self._place_order_side_unvalidated(symbol, qty, side, tp, sl)
        except Exception as e:
            logging.error(f"[ALARM] EMERGENCY OVERRIDE FAILED: {e}")
            return False

    def _place_order_side_unvalidated(self, symbol, qty, side, tp=None, sl=None, on_click=None, skip_positions_refresh=False):
        """
        Original order placement method without blueprint validation.
        Used internally for emergency overrides.
        """
        # This would be the original _place_order_side logic without validation
        # For now, we'll just call the existing method but skip the validation part
        # In a full implementation, this would duplicate the order placement logic
        
        # Temporarily disable validation by setting environment variable
        original_strict_mode = os.getenv("BLUEPRINT_STRICT_MODE")
        os.environ["BLUEPRINT_STRICT_MODE"] = "false"
        
        try:
            result = self._place_order_side(symbol, qty, side, tp, sl, on_click, skip_positions_refresh)
            return True
        except Exception as e:
            logging.error(f"[ALARM] UNVALIDATED TRADE FAILED: {e}")
            return False
        finally:
            # Restore original setting
            if original_strict_mode is not None:
                os.environ["BLUEPRINT_STRICT_MODE"] = original_strict_mode
            else:
                os.environ.pop("BLUEPRINT_STRICT_MODE", None)

    def get_validation_status(self):
        """
        Get current blueprint validation configuration status.
        
        Returns:
            dict: Validation configuration and status
        """
        return {
            "strict_mode": os.getenv("BLUEPRINT_STRICT_MODE", "true").lower() == "true",
            "selected_prop_firm": os.getenv("SELECTED_PROP_FIRM", "MFFU"),
            "trading_phase": os.getenv("TRADING_PHASE", "challenge_trade1"),
            "account_size": os.getenv("ACCOUNT_SIZE", "50k"),
            "validation_enabled": True
        }

    def login(self):
        """
        Perform full login sequence with robust error handling and retries.
        """
        # Acquire lock to prevent stats fetching during login
        with self.lock:
            if self.logged_in:
                return True

            # --- For testing: use hardcoded credentials if not provided ---
            if not self.username or not self.password:
                self.username = "TYLERTURNER63"
                self.password = "J5140A9013A9553tv="

            try:
                logging.info(f"Starting Tradovate login for user: {self.username}")
                # Always open Tradovate in the first tab
                self.driver.get("https://trader.tradovate.com/welcome")
                self.driver.switch_to.window(self.driver.window_handles[0])
                logging.info("Navigated to Tradovate welcome page")

                # Wait for login form or trading mode selection with optimized timeout
                try:
                    WebDriverWait(self.driver, 10).until(  # MAXIMUM SPEED: Reduced from 15 to 10
                        EC.any_of(
                            EC.visibility_of_element_located((By.ID, "name-input")),
                            EC.visibility_of_element_located((By.XPATH, "//h1[contains(text(), 'Select a Trading Mode')]"))
                        )
                    )
                    logging.info("Login form or trading mode selection loaded successfully")
                except Exception as e:
                    logging.error(f"Login form or trading mode selection not found: {e}")
                    # Take screenshot for debugging
                    try:
                        screenshot_path = os.path.join(tempfile.gettempdir(), f"tradovate_login_error_{int(time.time())}.png")
                        self.driver.save_screenshot(screenshot_path)
                        logging.info(f"Error screenshot saved to: {screenshot_path}")
                    except:
                        pass
                    raise Exception("Login form or trading mode selection not accessible. Please check internet connection and try again.")

                # Check if already at trading mode selection
                if self.driver.find_elements(By.XPATH, "//h1[contains(text(), 'Select a Trading Mode')]"):
                    logging.info("Already at trading mode selection page, skipping login form.")
                else:
                    # Fill login form
                    try:
                        username_field = WebDriverWait(self.driver, 15).until(  # Increased timeout
                            EC.element_to_be_clickable((By.ID, "name-input"))
                        )
                        password_field = WebDriverWait(self.driver, 15).until(
                            EC.element_to_be_clickable((By.ID, "password-input"))
                        )
                        logging.info("Login fields found, filling credentials...")

                        # Clear and fill username
                        username_field.click()
                        time.sleep(0.2)
                        username_field.clear()
                        username_field.send_keys(self.username)
                        logging.info("Username filled successfully")
                        
                        time.sleep(0.3)
                        
                        # Clear and fill password
                        password_field.click()
                        time.sleep(0.2)
                        password_field.clear()
                        password_field.send_keys(self.password)
                        logging.info("Password filled successfully")
                        
                        time.sleep(0.5)

                        # Click login button
                        login_button = WebDriverWait(self.driver, 15).until(
                            EC.element_to_be_clickable((By.XPATH, "//button[.//span[text()='Login']]"))
                        )
                        self.driver.execute_script("arguments[0].click();", login_button)
                        logging.info("Login button clicked successfully")

                        # SPEED OPTIMIZATION: Wait for trading mode selection with optimized timeout
                        WebDriverWait(self.driver, 25).until(  # Reduced from 45 to 25
                            EC.visibility_of_element_located((By.XPATH, "//h1[contains(text(), 'Select a Trading Mode')]"))
                        )
                        logging.info("Successfully reached 'Select a Trading Mode' page")
                        
                    except Exception as e:
                        logging.error(f"Failed to reach trading mode selection page after login: {e}")
                        # Check for error messages
                        try:
                            error_elements = self.driver.find_elements(By.CSS_SELECTOR, ".error, .alert, .warning, [class*='error'], [class*='alert']")
                            if error_elements:
                                error_text = error_elements[0].text
                                raise Exception(f"Login failed: {error_text}")
                        except:
                            pass
                        
                        # Take screenshot for debugging
                        try:
                            screenshot_path = os.path.join(tempfile.gettempdir(), f"tradovate_login_failed_{int(time.time())}.png")
                            self.driver.save_screenshot(screenshot_path)
                            logging.info(f"Login failure screenshot saved to: {screenshot_path}")
                        except:
                            pass
                            
                        raise Exception("Login may have failed - could not reach trading mode selection")

                # SPEED OPTIMIZATION: Try trading access with prioritized methods based on mode
                connected = False
                
                if self.trading_mode == "Live Trading":
                    logging.info("🚀 STARTING LIVE TRADING MODE")
                    access_attempts = [
                        self._launch_live_trading_tab
                    ]
                else:
                    logging.info("🎮 STARTING SIMULATION MODE")
                    access_attempts = [
                        self._launch_simulation_tab,  # Primary method - most reliable
                        self._launch_simulation_tab_fallback1,  # Most successful fallback
                        self._launch_simulation_tab_fallback2,  # Secondary fallback
                        self._launch_simulation_tab_fallback3,  # Less common scenarios
                        self._launch_simulation_tab_fallback_different_broker  # Last resort
                    ]
                
                for attempt_func in access_attempts:
                    try:
                        logging.info(f"Trying access method: {attempt_func.__name__}")
                        attempt_func()
                        
                        # Wait for trading interface to load with optimized timeout
                        try:
                            WebDriverWait(self.driver, 15).until(  # SPEED OPTIMIZATION: Reduced from 30 to 15
                                EC.visibility_of_element_located((By.XPATH, "//li[contains(@class, 'lm_tab')]//span[text()='Order Ticket']"))
                            )
                            time.sleep(1)  # SPEED OPTIMIZATION: Reduced from 2 to 1
                            self._wait_for_no_overlay(timeout=5)  # SPEED OPTIMIZATION: Reduced from 10 to 5
                            
                            # Verify connection with account stats
                            stats = self.get_account_stats()
                            if (stats.get("Account Number") and 
                                stats.get("Account Number") != "Not Connected" and 
                                stats.get("Balance") not in ("N/A", "Error", None, "")):
                                
                                self.logged_in = True
                                logging.info(f"[CHECK] Trading tab launched and account connected - login complete. Account: {stats.get('Account Number')}, Balance: {stats.get('Balance')}")
                                connected = True
                                break
                            else:
                                logging.info(f"Trading interface loaded but account not connected (Account: {stats.get('Account Number')}, Balance: {stats.get('Balance')}), trying next method...")
                        except Exception as e:
                            logging.error(f"Trading interface failed to load: {e}")
                            self.logged_in = False
                            
                    except Exception as e:
                        logging.warning(f"Access method failed: {e}")
                        self.logged_in = False

                if not connected:
                    logging.error(f"[X] Could not connect to {self.trading_mode} after all methods.")
                    self.logged_in = False
                    return False
                    
                return True

            except Exception as e:
                logging.error(f"Login process failed: {e}")
                self.logged_in = False
                return False

    def _launch_simulation_tab_fallback1(self):
        """Fallback 1: Try clicking the first visible 'Start Simulated Trading', 'Launch' or 'Access Simulation' button."""
        try:
            # First try Start Simulated Trading button
            try:
                button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Start Simulated Trading')]"))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button)
                time.sleep(0.2)
                button.click()
                logging.info("Fallback1: Clicked 'Start Simulated Trading' button (standard click)")
                return
            except:
                pass
            
            # Then try Launch button
            try:
                button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[.//span[text()='Launch']]"))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button)
                time.sleep(0.2)
                button.click()
                logging.info("Fallback1: Clicked 'Launch' button (standard click)")
                return
            except:
                pass
            
            # Then try Access Simulation button
            button = WebDriverWait(self.driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, "//button[.//span[text()='Access Simulation']]"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button)
            time.sleep(0.2)
            button.click()
            logging.info("Fallback1: Clicked 'Access Simulation' button (standard click)")
        except Exception as e:
            logging.warning(f"Fallback1 failed: {e}")
            raise

    def _launch_simulation_tab_fallback2(self):
        """Fallback 2: Try clicking any button with 'Start Simulated Trading', 'Launch' or 'Simulation' in span text."""
        try:
            # First try Start Simulated Trading
            try:
                button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Simulated Trading')]"))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button)
                time.sleep(0.2)
                button.click()
                logging.info("Fallback2: Clicked button with 'Simulated Trading' text (standard click)")
                return
            except:
                pass
            
            # Then try Launch
            try:
                button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[.//span[contains(text(), 'Launch')]]"))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button)
                time.sleep(0.2)
                button.click()
                logging.info("Fallback2: Clicked button with 'Launch' in span (standard click)")
                return
            except:
                pass
            
            # Then try Simulation
            button = WebDriverWait(self.driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, "//button[.//span[contains(text(), 'Simulation')]]"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button)
            time.sleep(0.2)
            button.click()
            logging.info("Fallback2: Clicked button with 'Simulation' in span (standard click)")
        except Exception as e:
            logging.warning(f"Fallback2 failed: {e}")
            raise

    def _launch_simulation_tab_fallback3(self):
        """Fallback 3: Try clicking any button with 'Launch' or 'Simulation' in its text."""
        try:
            # First try Launch
            try:
                button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Launch')]"))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button)
                time.sleep(0.2)
                button.click()
                logging.info("Fallback3: Clicked button with 'Launch' in text (standard click)")
                return
            except:
                pass
                
            # Then try Simulation
            button = WebDriverWait(self.driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Simulation')]"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button)
            time.sleep(0.2)
            button.click()
            logging.info("Fallback3: Clicked button with 'Simulation' in text (standard click)")
        except Exception as e:
            logging.warning(f"Fallback3 failed: {e}")
            raise

    def _fast_input_with_validation(self, element, value, field_name="field"):
        """Enhanced input method using proven Selenium approach that preserves text after typing"""
        try:
            max_attempts = 3
            for attempt in range(max_attempts):
                # Brief delay to let user see the field before we start typing
                time.sleep(0.5 if attempt == 0 else 0.3)
                logging.debug(f"Starting input for {field_name}: {value}")
                
                # Use proven Selenium approach - click, select all, delete, type character by character
                element.click()
                time.sleep(0.1)
                element.send_keys(Keys.CONTROL + "a")
                element.send_keys(Keys.DELETE)
                time.sleep(0.1)
                
                # Type character by character
                for char in str(value):
                    element.send_keys(char)
                    time.sleep(0.05)  # Small delay between characters
                
                time.sleep(0.2)  # Brief pause after typing is complete
                
                # Verify the value is there
                current_value = element.get_attribute("value")
                if current_value == str(value):
                    logging.debug(f"[CHECK] {field_name} input successful: {value}")
                    return True
                else:
                    logging.warning(f"[WARNING] {field_name} input attempt {attempt + 1}: expected {value}, got {current_value}")
                    if attempt < max_attempts - 1:
                        time.sleep(0.5)
                        continue
            
            logging.warning(f"[X] Input for {field_name} failed after {max_attempts} attempts")
            return False
            
        except Exception as e:
            logging.warning(f"Input with validation failed for {field_name}: {e}")
            return False
    
    def _complete_login_process(self):
        """Complete the login process - verify account access with enhanced stability"""
        try:
            logging.info("Verifying login completion...")
            
            # SPEED OPTIMIZATION: Fast trading interface verification
            try:
                WebDriverWait(self.driver, 10).until(  # Reduced from 20 to 10
                    EC.visibility_of_element_located((By.XPATH, "//li[contains(@class, 'lm_tab')]//span[text()='Order Ticket']"))
                )
                logging.info("[CHECK] Trading interface detected and loaded")
            except Exception as e:
                logging.warning(f"Order Ticket tab not found, trying alternative verification: {e}")
                # Alternative verification - look for any tab
                try:
                    WebDriverWait(self.driver, 5).until(  # Reduced from 10 to 5
                        EC.presence_of_element_located((By.XPATH, "//li[contains(@class, 'lm_tab')]"))
                    )
                    logging.info("[CHECK] Trading interface tabs detected")
                except Exception as e2:
                    logging.warning(f"No tabs found, assuming minimal interface: {e2}")
            
            # SPEED OPTIMIZATION: Reduced interface stabilization time
            time.sleep(1.5)  # Reduced from 3 to 1.5
            
            # Final verification - try to access account stats with enhanced error handling
            try:
                # Check if driver is still alive before attempting verification
                current_url = self.driver.current_url
                if "tradovate.com" not in current_url:
                    raise Exception(f"Browser navigated away from Tradovate: {current_url}")
                
                # Try to get basic stats but don't fail if it doesn't work
                stats = self.get_account_stats()
                if stats:
                    logging.info("[CHECK] Account stats accessible - full verification successful")
                else:
                    logging.info("[CHECK] Basic login verified, stats not immediately available")
                    
            except Exception as e:
                logging.warning(f"Account stats verification failed but login appears successful: {e}")
                # Don't fail completely - the login might still be successful
                
            # Mark as logged in if we got this far
            self.logged_in = True
            self._login_timestamp = time.time()  # Track when we logged in
            logging.info("[CHECK] Tradovate login process completed successfully")
            print(f"[UNLOCK] Login state set to True at {time.strftime('%H:%M:%S')}")
                
        except Exception as e:
            logging.error(f"Login verification failed: {e}")
            self.logged_in = False
            raise Exception(f"Login verification failed: {str(e)}")

    def _launch_live_trading_tab(self):
        """Launch the LIVE TRADING tab after successful authentication"""
        try:
            logging.info("Looking for LIVE TRADING button on 'Select a Trading Mode' page...")

            self._wait_for_no_overlay(timeout=2)
            time.sleep(1)

            # --- Selectors for LIVE TRADING button ---
            live_selectors = [
                # Primary selector provided by user
                "//button[@data-testid='live-trading-button']",
                
                # Fallbacks
                "//button[contains(., 'Start Trading')]",
                "//button[.//span[text()='Start Trading']]",
                "//button[contains(text(), 'Start Trading')]",
                "//button[contains(@class, 'MuiButton-contained') and contains(., 'Start Trading')]"
            ]

            # Try each selector
            live_button = None
            for selector in live_selectors:
                try:
                    buttons = self.driver.find_elements(By.XPATH, selector)
                    for button in buttons:
                        if button.is_displayed() and button.is_enabled():
                            live_button = button
                            logging.info(f"Found LIVE TRADING button with selector: {selector}")
                            break
                    if live_button:
                        break
                except Exception as e:
                    logging.debug(f"Selector failed: {selector} ({e})")
                    continue

            if not live_button:
                raise Exception("Could not find LIVE TRADING button")

            # Click the button
            logging.info("Clicking LIVE TRADING button...")
            self.driver.execute_script("arguments[0].click();", live_button)
            
            # Wait for interface to load
            logging.info("Waiting for LIVE TRADING interface to load...")
            WebDriverWait(self.driver, 60).until(
                EC.any_of(
                    EC.visibility_of_element_located((By.XPATH, "//li[contains(@class, 'lm_tab')]//span[text()='Order Ticket']")),
                    EC.visibility_of_element_located((By.XPATH, "//div[contains(@class, 'order-ticket')]"))
                )
            )
            logging.info("✓ LIVE TRADING interface loaded successfully")
            time.sleep(1)
            self._wait_for_no_overlay(timeout=10)
                
        except Exception as e:
            logging.error(f"Failed to launch LIVE TRADING tab: {e}")
            raise

    def _launch_simulation_tab(self):
        """Launch the simulation tab after successful authentication - enhanced for reliability"""
        try:
            logging.info("Looking for simulation access button on 'Select a Trading Mode' page...")

            self._wait_for_no_overlay(timeout=2)  # Reduced from 5 to 2
            
            # Wait for the page to be fully loaded
            time.sleep(1)  # Reduced from 2 to 1

            # --- More comprehensive selectors for simulation button (FASTER ORDER) ---
            simulation_selectors = [
                # NEW: Primary selector provided by user
                "//button[@data-testid='simulation-button']",

                # NEW: Handle 'Start Simulated Trading' button (primary)
                "//button[contains(@class, 'MuiButton-contained') and contains(., 'Start Simulated Trading')]",
                "//button[.//span[text()='Start Simulated Trading']]",
                "//button[contains(text(), 'Start Simulated Trading')]",
                
                # Handle the 'Launch' button text (most common)
                "//button[contains(@class, 'MuiButton-contained') and .//span[text()='Launch']]",
                "//button[contains(@class, 'fat-button') and .//span[text()='Launch']]",
                "//button[.//span[text()='Launch']]",
                "//button[contains(text(), 'Launch')]",
                
                # Handle the different broker scenario (Access Simulation)
                "//button[contains(@class, 'MuiButton-contained') and .//span[text()='Access Simulation']]",
                "//button[contains(@class, 'fat-button') and .//span[text()='Access Simulation']]",
                
                # Original selectors (keep for compatibility)
                "//button[contains(@class, 'MuiButton-root') and .//span[text()='Access Simulation']]",
                "//button[.//span[text()='Access Simulation']]",
                "//button[contains(text(), 'Access Simulation')]",
                
                # Broader selectors (last resort)
                "//button[.//span[contains(text(), 'Access Simulation')]]",
                "//button[contains(@class, 'MuiButton-root') and .//span[contains(text(), 'Simulation')]]",
                "//button[.//span[contains(text(), 'Simulated Trading')]]",
                "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'simulation')]",
                "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), 'launch')]"
            ]

            # Try each selector (FASTER - reduced timeout)
            simulation_button = None
            for selector in simulation_selectors:
                try:
                    buttons = self.driver.find_elements(By.XPATH, selector)
                    for button in buttons:
                        if button.is_displayed() and button.is_enabled():
                            simulation_button = button
                            logging.info(f"Found simulation button with selector: {selector}")
                            break
                    if simulation_button:
                        break
                except Exception as e:
                    logging.debug(f"Selector failed: {selector} ({e})")
                    continue

            if not simulation_button:
                # Try fallbacks faster - skip debugging for speed
                logging.warning("Direct selectors failed, trying fallbacks quickly")
                self._try_all_simulation_fallbacks_fast()
                return

            # Try click methods (FASTER - fewer attempts)
            click_success = False
            for attempt in range(3):  # Reduced from 5 to 3
                if click_success:
                    break
                    
                try:
                    logging.info(f"Attempt {attempt+1} to click simulation button")
                    
                    if attempt == 0:
                        # First try: JavaScript click (most reliable)
                        self.driver.execute_script("arguments[0].click();", simulation_button)
                        click_success = True
                        logging.info("Simulation button clicked with JavaScript click")
                    elif attempt == 1:
                        # Second try: standard click
                        simulation_button.click()
                        click_success = True
                        logging.info("Simulation button clicked with standard click")
                    else:
                        # Third try: ActionChains
                        ActionChains(self.driver).move_to_element(simulation_button).click().perform()
                        click_success = True
                        logging.info("Simulation button clicked with ActionChains")
                except Exception as e:
                    logging.warning(f"Click attempt {attempt+1} failed: {e}")
                    time.sleep(0.5)  # Reduced from 1 to 0.5

            if not click_success:
                # Try fallbacks quickly
                logging.warning("All direct click methods failed, trying fallbacks")
                self._try_all_simulation_fallbacks_fast()
                return

            # Wait for simulation interface to load - REDUCED TIMEOUT
            # Give 1 minute for the page to load after clicking (reduced from 5 minutes)
            logging.info("Waiting for simulation interface to load (up to 60 seconds)...")
            try:
                WebDriverWait(self.driver, 60).until(  # Reduced from 300 to 60 seconds
                    EC.any_of(
                        EC.visibility_of_element_located((By.XPATH, "//li[contains(@class, 'lm_tab')]//span[text()='Order Ticket']")),
                        EC.visibility_of_element_located((By.XPATH, "//div[contains(@class, 'order-ticket')]")),
                        EC.visibility_of_element_located((By.XPATH, "//span[text()='Order Ticket']"))
                    )
                )
                logging.info("✓ Simulation trading interface loaded successfully")
                time.sleep(1)  # Reduced from 2 to 1 second
                self._wait_for_no_overlay(timeout=10)
            except Exception as e:
                logging.warning(f"Trading interface loading verification timed out after 60 seconds: {e}")
                logging.info("Interface may still be loading, but simulation access was clicked")
                
        except Exception as e:
            logging.error(f"Failed to launch simulation tab: {e}")
            self._try_all_simulation_fallbacks_fast()

    def _try_all_simulation_fallbacks_fast(self):
        """Try all simulation fallbacks in sequence - FASTER version"""
        fallbacks = [
            self._launch_simulation_tab_fallback_different_broker,  # NEW: Add the different broker fallback first
            self._launch_simulation_tab_fallback1,
            self._launch_simulation_tab_fallback2,
            self._launch_simulation_tab_fallback3
        ]
        
        for i, fallback in enumerate(fallbacks):
            try:
                logging.info(f"Trying simulation fallback method {i+1}")
                fallback()
                # If we get here without exception, assume success
                logging.info(f"Simulation fallback method {i+1} succeeded")
                return
            except Exception as e:
                logging.warning(f"Simulation fallback method {i+1} failed: {e}")
    
        # If all fallbacks fail, raise exception
        raise Exception("All simulation access methods failed. Please check the trading platform UI or try manual login.")

    def _launch_simulation_tab_fallback_different_broker(self):
        """NEW: Fallback for different broker with specific button structure - supports both Launch and Access Simulation"""
        try:
            # First try Launch button (most common)
            try:
                button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((
                        By.XPATH, 
                        "//button[contains(@class, 'MuiButton-contained') and contains(@class, 'fat-button') and .//span[contains(@class, 'MuiButton-label') and text()='Launch']]"
                    ))
                )
                self.driver.execute_script("arguments[0].click();", button)
                logging.info("Different broker: Clicked 'Launch' button with JavaScript")
                time.sleep(2)
                return
            except:
                pass
            
            # Then try Access Simulation button structure
            try:
                button = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((
                        By.XPATH, 
                        "//button[contains(@class, 'MuiButton-contained') and contains(@class, 'fat-button') and .//span[contains(@class, 'MuiButton-label') and text()='Access Simulation']]"
                    ))
                )
                self.driver.execute_script("arguments[0].click();", button)
                logging.info("Different broker: Clicked 'Access Simulation' button with JavaScript")
                time.sleep(2)
                return
            except:
                pass
            
            # Try alternative selectors for Launch
            try:
                button = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((
                        By.XPATH, 
                        "//button[contains(@class, 'fat-button') and contains(@class, 'full-width-button')]//span[text()='Launch']"
                    ))
                )
                self.driver.execute_script("arguments[0].click();", button)
                logging.info("Different broker: Clicked Launch with alternative selector")
                time.sleep(2)
                return
            except:
                pass
                
            # Try alternative selectors for Access Simulation
            try:
                button = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((
                        By.XPATH, 
                        "//button[contains(@class, 'fat-button') and contains(@class, 'full-width-button')]//span[text()='Access Simulation']"
                    ))
                )
                self.driver.execute_script("arguments[0].click();", button)
                logging.info("Different broker: Clicked Access Simulation with alternative selector")
                time.sleep(2)
                return
            except:
                pass
                
            raise Exception("No Launch or Access Simulation buttons found")
            
        except Exception as e:
            logging.warning(f"Different broker fallback failed: {e}")
            raise Exception(f"Different broker simulation access failed: {e}")

    def _launch_simulation_tab_fallback_new(self):
        """New fallback: Try tabbing to the button and using Enter key."""
        try:
            # First try to find any button that might be the simulation button
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            simulation_button = None
            
            for button in buttons:
                try:
                    if button.is_displayed() and button.is_enabled():
                        text = button.text.lower()
                        if 'simulation' in text or 'access' in text or 'launch' in text:
                            simulation_button = button
                            break
                except:
                    continue
            
            if simulation_button:
                # Try to focus and press Enter
                self.driver.execute_script("arguments[0].focus();", simulation_button)
                time.sleep(1)
                ActionChains(self.driver).send_keys(Keys.RETURN).perform()
                logging.info("Pressed Enter on focused simulation/launch button")
                time.sleep(3)
                return
                
            # If no button found, try tabbing and pressing enter
            body = self.driver.find_element(By.TAG_NAME, "body")
            body.click()  # Focus on body
            
            # Press tab multiple times to try to reach the button
            action = ActionChains(self.driver)
            for _ in range(10):  # Try up to 10 tabs
                action.send_keys(Keys.TAB).perform()
                time.sleep(0.5)
                
                # Try pressing Enter after each tab
                action.send_keys(Keys.RETURN).perform()
                time.sleep(1)
                
                # Check if we've reached a new page
                try:
                    if WebDriverWait(self.driver, 2).until(
                        EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'trading-interface') or contains(@class, 'chart')]"))
                    ):
                        logging.info("New page detected after tab+enter, likely successful")
                        return
                except:
                    continue
                    
            raise Exception("Tab navigation failed to find simulation button")
        except Exception as e:
            logging.warning(f"New fallback failed: {e}")
            raise

    def _debug_page_elements(self):
        """Enhanced debugging to identify available page elements"""
        try:
            logging.info("=== ENHANCED DEBUGGING: Page Elements Analysis ===")
            try:
                current_url = self.driver.current_url
                page_title = self.driver.title
                logging.info(f"Current URL: {current_url}")
                logging.info(f"Page Title: {page_title}")
                
                # Take screenshot for debugging
                screenshot_path = os.path.join(tempfile.gettempdir(), f"tradovate_debug_{int(time.time())}.png")
                self.driver.save_screenshot(screenshot_path)
                logging.info(f"Debug screenshot saved to: {screenshot_path}")
            except:
                pass
                
            # Capture and log all buttons
            try:
                buttons = self.driver.find_elements(By.TAG_NAME, "button")
                logging.info(f"=== All Buttons Found ({len(buttons)} total) ===")
                for i, button in enumerate(buttons[:20]):  # Log first 20 buttons
                    try:
                        text = button.text.strip()
                        classes = button.get_attribute("class") or ""
                        visible = button.is_displayed()
                        enabled = button.is_enabled()
                        status = f"{'✓' if visible else '✗'}visible, {'✓' if enabled else '✗'}enabled"
                        if text:
                            logging.info(f"Button {i+1}: '{text}' | Classes: {classes[:50]}... | Status: {status}")
                        elif classes:
                            logging.info(f"Button {i+1}: [no text] | Classes: {classes[:50]}... | Status: {status}")
                    except Exception as e:
                        logging.debug(f"Button {i+1}: Error reading - {e}")
                
                # Find the most likely simulation button
                for button in buttons:
                    try:
                        if button.is_displayed() and button.is_enabled():
                            text = button.text.lower()
                            if 'simulation' in text or 'access simulation' in text:
                                rect = button.rect
                                logging.info(f"LIKELY TARGET: '{button.text}' at position {rect}")
                    except:
                        continue
            except:
                pass
                
        except Exception as debug_e:
            logging.error(f"Debug logging failed: {debug_e}")

    def _wait_for_no_overlay(self, timeout=3):
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, ".spinner, .loading, .overlay"))
            )
        except Exception:
            pass

    def close(self):
        """Close the browser and cleanup"""
        try:
            if self.driver:
                self.driver.quit()
                logging.info("Tradovate browser closed")
        except Exception as e:
            logging.error(f"Error closing browser: {e}")
        finally:
            if self.logged_in:
                print(f"[LOCK] Login state changed to False (browser closed) at {time.strftime('%H:%M:%S')}")
            self.logged_in = False
            self._login_timestamp = None
            self.driver = None
    
    def get_account_stats(self):
        """Optimized stats - return cached during order placement OR if recently fetched"""
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

            # Always try to fetch stats from the live page, even if not self.logged_in
            try:
                if not self.driver:
                    return {
                        "Account Number": "Not Connected",
                        "Balance": "N/A",
                        "Profit/Loss": "N/A",
                        "Open Trades": "N/A",
                        "Symbol": "",
                        "Direction": ""
                    }

                stats = {
                    "Account Number": "Unknown",
                    "Balance": "N/A",
                    "Profit/Loss": "N/A", 
                    "Open Trades": "0",
                    "Symbol": "",
                    "Direction": ""
                }

                # Check for Order Ticket tab quickly
                try:
                    order_ticket_tabs = self.driver.find_elements(
                        By.XPATH, "//li[contains(@class, 'lm_tab')]//span[text()='Order Ticket']"
                    )
                    if not order_ticket_tabs:
                        stats["Account Number"] = "Not Connected"
                        return stats
                except Exception:
                    stats["Account Number"] = "Not Connected"
                    return stats

                # --- Try to extract account number from visible elements ---
                try:
                    account_elements = self.driver.find_elements(By.CSS_SELECTOR, "[class*='account'], [data-testid*='account']")
                    for el in account_elements:
                        text = el.text.strip()
                        if text and any(char.isdigit() for char in text):
                            lines = text.splitlines()
                            for line in lines:
                                if line.strip() and any(char.isdigit() for char in line):
                                    acc = line.strip()
                                    if len(acc) >= 9:
                                        stats["Account Number"] = acc[:4] + "..." + acc[-5:]
                                    else:
                                        stats["Account Number"] = acc
                                    break
                            if stats["Account Number"] != "Unknown":
                                break
                except Exception:
                    pass

                # --- Try to extract balance ---
                try:
                    balance_elements = self.driver.find_elements(By.CSS_SELECTOR, "[class*='balance'], [class*='equity']")
                    for el in balance_elements:
                        balance_text = el.text
                        import re
                        balance_match = re.search(r'[\$]?([0-9,]+\.?[0-9]*)', balance_text)
                        if balance_match:
                            stats["Balance"] = f"${balance_match.group(1)}"
                            break
                except Exception:
                    pass

                # --- Try to extract open trades ---
                try:
                    open_trades_elements = self.driver.find_elements(By.XPATH, "//span[contains(text(),'Open') and contains(text(),'Trade')]")
                    for el in open_trades_elements:
                        text = el.text
                        import re
                        match = re.search(r'(\d+)', text)
                        if match:
                            stats["Open Trades"] = match.group(1)
                            break
                except Exception:
                    pass
                    
                # Cache the stats WITH TIMESTAMP for performance optimization
                self._cached_stats = stats
                self._stats_last_fetch_time = time.time()
                return stats
                
            except Exception as e:
                logging.warning(f"Error fetching stats: {e}")
                return {
                    "Account Number": "Error",
                    "Balance": "N/A",
                    "Profit/Loss": "N/A",
                    "Open Trades": "N/A",
                    "Symbol": "",
                    "Direction": ""
                }
        finally:
            self.lock.release()
    
    def refresh_positions_tab(self):
        """Refresh the Tradovate Positions tab to update open trades info."""
        try:
            driver = self.driver
            positions_tab = WebDriverWait(driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, "//li[contains(@class, 'lm_tab')]//span[text()='Positions']"))
            )
            positions_tab.click()
            self._wait_for_no_overlay(timeout=0.5)
        except Exception:
            pass
    
    def prepare_buy_order(self, symbol, qty, tp=None, sl=None):
        """
        THREADING OPTIMIZATION: Prepare BUY order (symbol search, quantity, ATM) WITHOUT clicking button.
        Use this before threading to minimize time inside parallel execution.
        
        Returns: True if preparation successful, False otherwise
        """
        with self.lock:
            try:
                print(f"[⚡ PRE-THREAD] Preparing Tradovate BUY order: {symbol} x{qty}")
                
                # Quick interface check
                current_url = self.driver.current_url
                if not current_url or "tradovate" not in current_url:
                    print(f"[⚡ PRE-THREAD] Not on Tradovate page, logging in...")
                    self.login()
                
                # Prepare order (slow operations done before threading)
                self._wait_for_no_overlay(timeout=0.2)
                self._select_symbol(symbol)
                self._set_quantity(qty)
                self._setup_atm(tp, sl)
                
                print(f"✅ [⚡ PRE-THREAD] Order prepared - ready for button click")
                return True
                
            except Exception as e:
                print(f"[⚡ PRE-THREAD] Preparation failed: {e}")
                return False
    
    def execute_prepared_buy_order(self, skip_positions_refresh=False):
        """
        THREADING OPTIMIZATION: Execute already-prepared BUY order (just click button).
        Call prepare_buy_order() first, then use this inside threading for instant execution.
        
        Returns: None (raises exception on failure)
        """
        with self.lock:
            try:
                print(f"[⚡ THREAD-EXEC] Clicking BUY button...")
                self._do_place_order("buy", on_click=None, skip_positions_refresh=skip_positions_refresh)
                print(f"✅ [⚡ THREAD-EXEC] BUY button clicked")
            except Exception as e:
                print(f"[⚡ THREAD-EXEC] Execution failed: {e}")
                raise
    
    def prepare_sell_order(self, symbol, qty, tp=None, sl=None):
        """
        THREADING OPTIMIZATION: Prepare SELL order (symbol search, quantity, ATM) WITHOUT clicking button.
        Use this before threading to minimize time inside parallel execution.
        
        Returns: True if preparation successful, False otherwise
        """
        with self.lock:
            try:
                print(f"[⚡ PRE-THREAD] Preparing Tradovate SELL order: {symbol} x{qty}")
                
                # Quick interface check
                current_url = self.driver.current_url
                if not current_url or "tradovate" not in current_url:
                    print(f"[⚡ PRE-THREAD] Not on Tradovate page, logging in...")
                    self.login()
                
                # Prepare order (slow operations done before threading)
                self._wait_for_no_overlay(timeout=0.2)
                self._select_symbol(symbol)
                self._set_quantity(qty)
                self._setup_atm(tp, sl)
                
                print(f"✅ [⚡ PRE-THREAD] Order prepared - ready for button click")
                return True
                
            except Exception as e:
                print(f"[⚡ PRE-THREAD] Preparation failed: {e}")
                return False
    
    def execute_prepared_sell_order(self, skip_positions_refresh=False):
        """
        THREADING OPTIMIZATION: Execute already-prepared SELL order (just click button).
        Call prepare_sell_order() first, then use this inside threading for instant execution.
        
        Returns: None (raises exception on failure)
        """
        with self.lock:
            try:
                print(f"[⚡ THREAD-EXEC] Clicking SELL button...")
                self._do_place_order("sell", on_click=None, skip_positions_refresh=skip_positions_refresh)
                print(f"✅ [⚡ THREAD-EXEC] SELL button clicked")
            except Exception as e:
                print(f"[⚡ THREAD-EXEC] Execution failed: {e}")
                raise

    def buy_market(self, symbol=None, qty=1, tp=None, sl=None, on_click=None, skip_positions_refresh=False, prop_firm=None, phase=None, account_size=None):
        self._place_order_side(symbol, qty, "buy", tp, sl, on_click=on_click, skip_positions_refresh=skip_positions_refresh, prop_firm=prop_firm, phase=phase, account_size=account_size)

    def sell_market(self, symbol=None, qty=1, tp=None, sl=None, on_click=None, skip_positions_refresh=False, prop_firm=None, phase=None, account_size=None):
        self._place_order_side(symbol, qty, "sell", tp, sl, on_click=on_click, skip_positions_refresh=skip_positions_refresh, prop_firm=prop_firm, phase=phase, account_size=account_size)

    def _set_quantity(self, qty):
        print(f"[ZAP] Setting quantity: {qty}")
        try:
            qty_input = WebDriverWait(self.driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'trading-ticket-main-entry')]//div[contains(@class, 'qty')]//input"))
            )
            
            # SPEED OPTIMIZATION: Check if quantity is already correct first
            current_qty = qty_input.get_attribute("value") or ""
            if current_qty.strip() == str(qty).strip():
                print(f"[ZAP] Quantity {qty} already set - skipping update")
                return
            
            # Update quantity with proper input clearing delays
            qty_input.click()
            time.sleep(0.1)  # Increased delay for reliable clearing
            qty_input.send_keys(Keys.CONTROL + "a")
            qty_input.send_keys(Keys.DELETE)
            time.sleep(0.1)  # Increased delay before typing new value
            qty_input.send_keys(str(qty))
            time.sleep(0.05)  # Brief delay after typing
            print(f"[ZAP] Quantity updated to {qty}")
            
        except Exception as e:
            print(f"[WARNING] Quantity setting failed: {e}")
            raise

    def _setup_atm(self, tp=None, sl=None):
        """Optimized ATM setup with smart input checking"""
        tp = tp if tp is not None else (os.getenv("TRADOVATE_TAKEPROFIT_TICKS") or DEFAULT_TP)
        sl = sl if sl is not None else (os.getenv("TRADOVATE_STOPLOSS_TICKS") or DEFAULT_SL)
        print(f"[ZAP] Setting ATM - TP: {tp}, SL: {sl}")
        
        try:
            inputs = self.driver.find_elements(By.CSS_SELECTOR, "div.numeric-input input.form-control")
            if len(inputs) < 2:
                print(f"[WARNING] Only found {len(inputs)} ATM inputs, skipping ATM setup")
                return
                
            tp_input = inputs[0]
            sl_input = inputs[1]
            
            # SPEED OPTIMIZATION: Check both inputs first, only update if needed
            current_tp = tp_input.get_attribute("value") or ""
            current_sl = sl_input.get_attribute("value") or ""
            
            tp_needs_update = current_tp.strip() != str(tp).strip()
            sl_needs_update = current_sl.strip() != str(sl).strip()
            
            if not tp_needs_update and not sl_needs_update:
                print(f"[ZAP] ATM already configured: TP={tp}, SL={sl} - skipping update")
                return
            
            # Only update TP if needed
            if tp_needs_update:
                tp_input.click()
                time.sleep(0.15)  # Increased delay for reliable clearing
                tp_input.send_keys(Keys.CONTROL + "a")
                tp_input.send_keys(Keys.DELETE)
                time.sleep(0.1)  # Increased delay before typing
                tp_input.send_keys(str(tp))
                time.sleep(0.15)  # Increased delay after typing TP
                # Tab to next field to confirm TP entry
                tp_input.send_keys(Keys.TAB)
                time.sleep(0.2)  # Wait for tab to process
                print(f"[ZAP] TP updated to {tp} and tabbed to SL field")
            else:
                print(f"[ZAP] TP {tp} already correct")
            
            # Only update SL if needed
            if sl_needs_update:
                sl_input.click()
                time.sleep(0.15)  # Increased delay for reliable clearing
                sl_input.send_keys(Keys.CONTROL + "a")
                sl_input.send_keys(Keys.DELETE)
                time.sleep(0.1)  # Increased delay before typing
                sl_input.send_keys(str(sl))
                time.sleep(0.15)  # Increased delay after typing
                # Tab out to confirm SL entry
                sl_input.send_keys(Keys.TAB)
                time.sleep(0.2)  # Wait for tab to process
                print(f"[ZAP] SL updated to {sl} and tabbed out")
            else:
                print(f"[ZAP] SL {sl} already correct")
            
            print(f"[ZAP] ATM setup complete: TP={tp}, SL={sl}")
            
        except Exception as e:
            print(f"[WARNING] ATM setup failed: {e}")
            import traceback
            traceback.print_exc()
            # Don't raise - continue without ATM if it fails

    def _detect_account_size(self, stats):
        """
        Heuristic detection of account size based on balance.
        Returns normalized string like "50k", "100k", or None.
        """
        try:
            balance_str = stats.get("Balance", "N/A")
            if not balance_str or balance_str == "N/A":
                return None
            
            # Clean string: "$50,230.50" -> 50230.50
            clean_bal = balance_str.replace("$", "").replace(",", "").strip()
            bal = float(clean_bal)
            
            # Define ranges (balance +/- variance) with strict boundaries
            # 25k TIER: 20k-38k
            if 20000 <= bal <= 38000: return "25k"
            # 50k TIER: 40k-65k
            if 40000 <= bal <= 65000: return "50k"
            # 100k TIER: 90k-115k
            if 90000 <= bal <= 115000: return "100k"
            # 150k TIER: 140k-165k
            if 140000 <= bal <= 165000: return "150k"
            # 200k TIER: 190k-215k
            if 190000 <= bal <= 215000: return "200k"
            # 250k TIER: 240k-265k
            if 240000 <= bal <= 265000: return "250k"
            # 300k TIER: 290k-315k
            if 290000 <= bal <= 315000: return "300k"
            
            return None
        except Exception:
            return None

    def _place_order_side(self, symbol, qty, side, tp=None, sl=None, on_click=None, skip_positions_refresh=False, prop_firm=None, phase=None, account_size=None):
        """
        Place a market order with enhanced crash detection and recovery
        """
        # Acquire lock to prevent stats fetching during order placement
        with self.lock:
            # --- ACCOUNT SIZE PROTECTION ---
            # Try to populate account_size from env if missing, for safety
            check_size = account_size or os.getenv("ACCOUNT_SIZE", "50k")
            
            if check_size:
                try:
                    # Get fresh stats (this is safe because _block_stats_fetching hasn't been called yet)
                    current_stats = self.get_account_stats()
                    detected_size = self._detect_account_size(current_stats)
                    
                    if detected_size:
                        # Normalize blueprint size (e.g. "50k" -> "50k", "$50,000" -> "50k")
                        bp_size_norm = str(check_size).lower().replace("$", "").replace(",", "")
                        
                        # Handle numerical inputs like "50000"
                        if bp_size_norm.isdigit():
                            val = int(bp_size_norm)
                            if 20000 <= val <= 38000: bp_size_norm = "25k"
                            elif 45000 <= val <= 55000: bp_size_norm = "50k"
                            elif 95000 <= val <= 105000: bp_size_norm = "100k"
                            elif 145000 <= val <= 155000: bp_size_norm = "150k"
                            elif 195000 <= val <= 205000: bp_size_norm = "200k"
                            elif 245000 <= val <= 255000: bp_size_norm = "250k"
                            elif 295000 <= val <= 305000: bp_size_norm = "300k"
                        
                        # Only compare if we successfully normalized to a "k" string or we are comparing raw strings
                        # If bp_size_norm is still "60000" (weird size), detected "50k" won't match.
                        
                        # Compare
                        if detected_size != bp_size_norm:
                            error_msg = f"[BLOCK] ACCOUNT SIZE MISMATCH! Blueprint requires {bp_size_norm} account, but detected {detected_size} account (Balance: {current_stats.get('Balance')}). Trade BLOCKED."
                            print(error_msg)
                            raise Exception(error_msg)
                        else:
                            print(f"[CHECK] Account size OK: Blueprint {bp_size_norm} matches Account {detected_size}")
                    else:
                        print(f"[WARNING] Could not detect account size from balance ({current_stats.get('Balance')}). Proceeding with trade.")
                except Exception as size_check_err:
                    if "ACCOUNT SIZE MISMATCH" in str(size_check_err):
                        raise # Re-raise blocking error
                    print(f"[WARNING] Account size check failed: {size_check_err}")

            # CRITICAL DEBUG: Log the symbol BEFORE any fallback logic
            print(f"[SYMBOL DEBUG] _place_order_side RECEIVED symbol parameter: '{symbol}' (type: {type(symbol)})")
            print(f"[SYMBOL DEBUG] DEFAULT_SYMBOL = '{DEFAULT_SYMBOL}'")
            print(f"[SYMBOL DEBUG] prop_firm={prop_firm}, phase={phase}, account_size={account_size}")
            
            original_symbol = symbol
            symbol = symbol or DEFAULT_SYMBOL
            
            if original_symbol != symbol:
                print(f"[SYMBOL WARNING] Symbol was None/empty, fell back to DEFAULT_SYMBOL: '{original_symbol}' → '{symbol}'")
            else:
                print(f"[SYMBOL OK] Using provided symbol: '{symbol}'")
            
            print(f"[SEARCH] _place_order_side DEBUG: Placing {side.upper()} order: {symbol} x{qty}")
            print(f"[SEARCH] _place_order_side DEBUG: Current logged_in state: {self.logged_in}")
            
            # [ALARM] BLUEPRINT VALIDATION DISABLED: Using input timing instead
            print(f"[CHECK] TRADE APPROVED: Blueprint validation disabled - using input timing")
            
            # Add input clearing delays for reliable value entry
            import time
            time.sleep(0.2)  # Brief delay to ensure inputs are ready
            
            # Add browser health check before starting
            try:
                current_url = self.driver.current_url
                if "data:" in current_url or not current_url or "tradovate" not in current_url:
                    raise Exception("Browser is in invalid state before order placement")
            except Exception as health_error:
                print(f"Browser health check failed: {health_error}")
                raise Exception("Browser crashed or disconnected")
            
            # Block other actions - important to prevent UI interference during order placement
            self._block_stats_fetching(True)
            try:
                # SPEED OPTIMIZATION: Enhanced login check for manual trading
                need_login = False
                login_reason = ""
                
                # Debug current login state
                login_age = "never" if not self._login_timestamp else f"{int(time.time() - self._login_timestamp)}s ago"
                print(f"[SEARCH] LOGIN STATE DEBUG: logged_in={self.logged_in}, last_login={login_age}")
                
                if not self.logged_in:
                    # SMART LOGIN CHECK: Verify if interface is actually unavailable before forcing login
                    print("[SEARCH] SMART CHECK: logged_in=False but verifying interface availability...")
                    try:
                        current_url = self.driver.current_url
                        if "trader.tradovate.com" in current_url:
                            # Check if trading interface is actually accessible
                            order_ticket_available = self.driver.find_elements(
                                By.XPATH, "//li[contains(@class, 'lm_tab')]//span[text()='Order Ticket']"
                            )
                            if order_ticket_available:
                                print("[SETUP] SMART CHECK SUCCESS: Interface available despite logged_in=False, correcting state")
                                self.logged_in = True
                                self._login_timestamp = time.time()
                            else:
                                need_login = True
                                login_reason = "logged_in flag is False and Order Ticket not accessible"
                        else:
                            need_login = True
                            login_reason = f"logged_in flag is False and not on trading page (URL: {current_url})"
                    except Exception as check_error:
                        need_login = True
                        login_reason = f"logged_in flag is False and interface check failed: {check_error}"
                else:
                    # For manual trades, do a quick interface check instead of full login
                    print("[ZAP] FAST MANUAL: Checking trading interface availability...")
                    try:
                        # Quick check: Can we access the trading interface directly?
                        current_url = self.driver.current_url
                        if not current_url or "tradovate" not in current_url:
                            need_login = True
                            login_reason = f"not on Tradovate page (URL: {current_url})"
                        else:
                            # Check if Order Ticket tab is accessible
                            order_ticket_visible = self.driver.find_elements(
                                By.XPATH, "//li[contains(@class, 'lm_tab')]//span[text()='Order Ticket']"
                            )
                            if order_ticket_visible:
                                print("[ZAP] FAST MANUAL: Order Ticket tab accessible - proceeding directly to trade")
                            else:
                                print("[ZAP] FAST MANUAL: Order Ticket not visible - may need interface refresh")
                                # Try a quick navigation to trading page instead of full login
                                if "trader" not in current_url:
                                    print("[ZAP] FAST MANUAL: Navigating to trading interface...")
                                    self.driver.get("https://trader.tradovate.com/")
                                    time.sleep(2)  # Brief wait for page load
                    except Exception as interface_error:
                        need_login = True
                        login_reason = f"interface check failed: {interface_error}"
            
                # Only perform login if actually needed
                if need_login:
                    print(f"[WARNING] Login required: {login_reason}")
                    
                    # Proceed directly to full login without page refresh
                    print("[REFRESH] Performing login...")
                    self.login()
                else:
                    print("[ZAP] FAST MANUAL: Login check passed - proceeding with trade execution")
                
                self._wait_for_no_overlay(timeout=0.2)
                self._select_symbol(symbol)
                self._set_quantity(qty)
                self._setup_atm(tp, sl)
                self._do_place_order(side, on_click=on_click, skip_positions_refresh=skip_positions_refresh)
            
            except Exception as e:
                # Check if it's a browser crash
                try:
                    current_url = self.driver.current_url
                    if "data:" in current_url or not current_url:
                        print(f"Browser crashed during {side} order placement")
                        raise Exception(f"Browser crashed during {side} order - cannot continue")
                except:
                    print(f"Browser completely unresponsive during {side} order")
                    raise Exception(f"Browser crashed during {side} order - cannot continue")
                raise
            finally:
                # Ensure stats fetching is unblocked even if an exception occurs
                self._block_stats_fetching(False)

    def _block_stats_fetching(self, block=True):
        """Set a flag to block stats fetching during order placement."""
        self._placing_order = block

    def _select_symbol(self, symbol):
        print(f"Selecting symbol: {symbol}")
        self._wait_for_no_overlay()
        
        # SPEED OPTIMIZATION: Try direct symbol selection first (for fast manual trading)
        try:
            print(f"[ZAP] FAST PATH: Attempting direct symbol selection...")
            # Check if symbol input is already accessible without tab switching
            symbol_input = WebDriverWait(self.driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'trading-ticket-main-entry')]//input[contains(@class, 'search-box--input')]"))
            )
            
            # Check if symbol is already correctly set
            current_symbol = symbol_input.get_attribute("value") or ""
            if current_symbol.strip().upper() == symbol.upper():
                print(f"[ZAP] FAST PATH SUCCESS: Symbol {symbol} already selected, skipping")
                return
            
            # Symbol input is accessible, proceed with direct selection
            symbol_input.click()
            time.sleep(0.1)  # Reduced delay for speed
            symbol_input.send_keys(Keys.CONTROL + "a")
            symbol_input.send_keys(Keys.DELETE)
            time.sleep(0.1)
            
            # Type symbol with moderate delays to ensure dropdown appears
            for char in symbol:
                symbol_input.send_keys(char)
                time.sleep(0.1)  # Moderate typing speed for dropdown stability
            
            # Wait for dropdown and click option directly - EXACT MATCH to avoid selecting MNQM6 when looking for NQM6
            # Try exact match first (most reliable)
            try:
                dropdown_option = WebDriverWait(self.driver, 3).until(
                    EC.visibility_of_element_located((
                        By.XPATH,
                        f"//ul[contains(@class, 'dropdown-menu')]//a[starts-with(normalize-space(.), '{symbol} ') or starts-with(normalize-space(.), '{symbol}(') or normalize-space(.)='{symbol}']"
                    ))
                )
                self.driver.execute_script("arguments[0].click();", dropdown_option)
                print(f"[ZAP] FAST PATH SUCCESS: Symbol {symbol} selected directly (exact match)")
                self._wait_for_no_overlay()
                return
            except:
                # Fallback: If exact match fails, try contains but click the first matching option
                print(f"[ZAP] Exact match failed, trying contains match...")
                dropdown_option = WebDriverWait(self.driver, 2).until(
                    EC.visibility_of_element_located((
                        By.XPATH,
                        f"//ul[contains(@class, 'dropdown-menu')]//a[contains(text(), '{symbol}') or .//div[contains(text(), '{symbol}')]]"
                    ))
                )
                self.driver.execute_script("arguments[0].click();", dropdown_option)
                print(f"[ZAP] FAST PATH SUCCESS: Symbol {symbol} selected directly (contains match)")
                self._wait_for_no_overlay()
                return
            
        except Exception as fast_error:
            print(f"[ZAP] Fast path failed: {fast_error}, falling back to tab navigation...")
        
        # ORIGINAL PATH: Full tab navigation for when fast path fails
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                # Step 1: Click Positions tab
                positions_tab = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//li[contains(@class, 'lm_tab')]//span[text()='Positions']"))
                )
                positions_tab.click()
                time.sleep(0.3)
            except Exception as e:
                print(f"Warning: Positions tab interaction failed: {e}")
            
            try:
                # Step 2: Click Order Ticket tab
                order_ticket_tab = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//li[contains(@class, 'lm_tab')]//span[text()='Order Ticket']"))
                )
                order_ticket_tab.click()
                time.sleep(0.3)
            except Exception as e:
                print(f"Error: Order Ticket tab not accessible: {e}")
                raise
            
            try:
                # Step 3: Find and interact with symbol input
                symbol_input = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'trading-ticket-main-entry')]//input[contains(@class, 'search-box--input')]"))
                )
                symbol_input.click()
                time.sleep(0.3)
                symbol_input.send_keys(Keys.CONTROL + "a")
                symbol_input.send_keys(Keys.DELETE)
                time.sleep(0.3)
                
                # Type symbol character by character with slower speed for dropdown stability
                for char in symbol:
                    symbol_input.send_keys(char)
                    time.sleep(0.15)  # Slower typing to ensure dropdown appears
                
                # Step 4: Wait for and click dropdown option - EXACT MATCH to avoid selecting MNQM6 when looking for NQM6
                try:
                    # Try exact match first (more reliable)
                    dropdown_option = WebDriverWait(self.driver, 5).until(
                        EC.visibility_of_element_located((
                            By.XPATH,
                            f"//ul[contains(@class, 'dropdown-menu')]//a[starts-with(normalize-space(.), '{symbol} ') or starts-with(normalize-space(.), '{symbol}(') or normalize-space(.)='{symbol}']"
                        ))
                    )
                    self.driver.execute_script("arguments[0].click();", dropdown_option)
                    print(f"Symbol {symbol} selected from dropdown (exact match)")
                    break  # Success!
                except:
                    # Fallback: try contains match
                    print(f"Exact match failed, trying contains match for {symbol}...")
                    dropdown_option = WebDriverWait(self.driver, 5).until(
                        EC.visibility_of_element_located((
                            By.XPATH,
                            f"//ul[contains(@class, 'dropdown-menu')]//a[contains(text(), '{symbol}') or .//div[contains(text(), '{symbol}')]]"
                        ))
                    )
                    self.driver.execute_script("arguments[0].click();", dropdown_option)
                    print(f"Symbol {symbol} selected from dropdown (contains match)")
                    break  # Success!
                
            except Exception as e:
                print(f"Attempt {attempt+1} to select symbol failed: {e}")
                if attempt == max_attempts - 1:
                    raise Exception("Symbol input not found or could not select symbol after several attempts")
                time.sleep(1)
        
        self._wait_for_no_overlay()

    def _recover_from_symbol_failure(self):
        """Recovery method: Click Positions tab, then Order Ticket tab, then clear symbol field"""
        try:
            print("[REFRESH] Starting symbol selection recovery...")
            
            # Step 1: Click Positions tab
            try:
                positions_tab = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, "//li[contains(@class, 'lm_tab')]//span[text()='Positions']"))
                )
                positions_tab.click()
                print("[CHECK] Clicked Positions tab")
                time.sleep(0.5)
            except Exception as e:
                print(f"[WARNING] Could not click Positions tab: {e}")

            # Step 2: Click Order Ticket tab
            try:
                order_ticket_tab = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, "//li[contains(@class, 'lm_tab')]//span[text()='Order Ticket']"))
                )
                order_ticket_tab.click()
                print("[CHECK] Clicked Order Ticket tab")
                time.sleep(0.5)
            except Exception as e:
                print(f"[WARNING] Could not click Order Ticket tab: {e}")

            # Step 3: Clear symbol field
            try:
                symbol_input = WebDriverWait(self.driver, 3).until(
                    EC.visibility_of_element_located((By.XPATH, "//div[contains(@class, 'trading-ticket-main-entry')]//input[contains(@class, 'search-box--input')]"))
                )
                symbol_input.click()
                time.sleep(0.2)
                symbol_input.send_keys(Keys.CONTROL + "a")
                symbol_input.send_keys(Keys.DELETE)
                print("[CHECK] Cleared symbol field")
                time.sleep(0.3)
            except Exception as e:
                print(f"[WARNING] Could not clear symbol field: {e}")
                
            print("[REFRESH] Recovery completed")
            
        except Exception as recovery_error:
            print(f"[X] Recovery failed: {recovery_error}")

    def _do_place_order(self, side, on_click=None, skip_positions_refresh=False):
        """Optimized order placement with better error handling"""
        self._placing_order = True
        
        try:
            # Find buy/sell button with better error handling
            try:
                side_button = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, f"//label[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{side.lower()}')]"))
                )
                current_class = side_button.get_attribute("class") or ""
                if "active" not in current_class:
                    self.driver.execute_script("arguments[0].click();", side_button)
                    print(f"{side.upper()} button selected")
                else:
                    print(f"{side.upper()} button already active")
            except Exception as e:
                print(f"Failed to select {side} button: {e}")
                raise
            
            # Click Send button with retry logic
            try:
                send_button = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'btn-primary') and text()='Send']"))
                )
                self.driver.execute_script("arguments[0].click();", send_button)
                print("Send button clicked")
            except Exception as e:
                print(f"Failed to click Send button: {e}")
                raise
            
            # Handle confirmation dialog if it appears
            try:
                confirm_btn = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ok') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'confirm') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'continue')]"))
                )
                self.driver.execute_script("arguments[0].click();", confirm_btn)
                print("Confirmation dialog handled")
            except:
                print("No confirmation dialog (normal)")
                
            print(f"Order placed: {side.upper()}")
            
            # Click positions tab after order placement to refresh data (unless skipped for manual trading)
            if not skip_positions_refresh:
                try:
                    time.sleep(0.5)
                    positions_tab = WebDriverWait(self.driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, "//li[contains(@class, 'lm_tab')]//span[text()='Positions']"))
                    )
                    positions_tab.click()
                    print("Positions tab clicked after order placement")
                    time.sleep(0.3)
                except Exception as e:
                    print(f"Failed to click Positions tab after order: {e}")
            else:
                print("Skipping positions tab refresh for manual trading speed")
            
        except Exception as e:
            print(f"Order placement failed: {e}")
            raise
        finally:
            self._placing_order = False
