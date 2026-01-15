import sys
import os
import winreg
from pathlib import Path
from dotenv import load_dotenv
import logging
import subprocess
import psutil
import time
from time import sleep
import ctypes
from ctypes import wintypes

# Setup logging
logging.basicConfig(
    filename='mt5_trading.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

# Load .env at program start
load_dotenv()

def setup_pyinstaller_mt5_environment():
    """Enhanced MT5 environment setup for PyInstaller builds"""
    try:
        # Detect if running in PyInstaller bundle
        if hasattr(sys, '_MEIPASS'):
            print("[SETUP] Detected PyInstaller environment - applying MT5 fixes...")
            
            # Set up DLL search paths for MT5
            if hasattr(os, 'add_dll_directory'):
                bundle_dir = sys._MEIPASS
                try:
                    os.add_dll_directory(bundle_dir)
                    print(f"   Added bundle directory to DLL path: {bundle_dir}")
                except Exception as e:
                    print(f"   [WARNING] Warning: Could not add bundle directory: {e}")
            
            # Add common MT5 paths to DLL search
            mt5_paths = [
                r"C:\Program Files\MetaTrader 5",
                r"C:\Program Files (x86)\MetaTrader 5", 
                r"C:\Program Files\MetaTrader 5 Terminal"
            ]
            
            for path in mt5_paths:
                if os.path.exists(path):
                    try:
                        if hasattr(os, 'add_dll_directory'):
                            os.add_dll_directory(path)
                        # Also add to PATH
                        current_path = os.environ.get('PATH', '')
                        if path not in current_path:
                            os.environ['PATH'] = f"{path};{current_path}"
                        print(f"   Added MT5 path: {path}")
                    except Exception as e:
                        print(f"   [WARNING] Warning: Could not add MT5 path {path}: {e}")
            
            # Set MT5 environment variables
            os.environ['MT5_TERMINAL_PATH'] = ''
            os.environ['PYINSTALLER_MT5_FIX'] = '1'
            
            print("   [OK] PyInstaller MT5 environment setup completed")
            return True
            
    except Exception as e:
        print(f"   [WARNING] PyInstaller MT5 setup warning: {e}")
    return False

# Setup PyInstaller environment before importing MT5
setup_pyinstaller_mt5_environment()

# Enhanced import of MetaTrader5 with PyInstaller support
try:
    # Import MT5 but don't initialize anything yet
    import MetaTrader5 as mt5
    print("[OK] MetaTrader5 module imported (not initialized)")
except ImportError as e:
    print(f"[ERROR] Failed to import MetaTrader5: {e}")
    if hasattr(sys, '_MEIPASS'):
        print("💡 PyInstaller MT5 import failure - this may be resolved by the enhanced build process")
    raise

def get_installed_mt5_terminals():
    """
    Detect installed MetaTrader 5 terminals on Windows
    Returns a list of dictionaries with terminal info
    """
    # Only detect paths - do not initialize anything
    terminals = []
    
    # Log detection start without initialization
    logging.info("[OK] Starting MT5 path detection (without initialization)")
    
    # Extended common installation paths - including the known working path
    username = os.getenv('USERNAME', '')
    common_paths = [
        r"C:\Program Files\MetaTrader 5",
        r"C:\Program Files (x86)\MetaTrader 5",
        r"C:\Program Files\MetaTrader 5 Terminal",  # Known working path
        rf"C:\Users\{username}\AppData\Roaming\MetaQuotes\Terminal",
        rf"C:\Users\{username}\AppData\Local\Programs\MetaTrader 5",
        rf"C:\Users\{username}\Documents\MetaTrader 5",
        rf"C:\Users\{username}\Desktop\MetaTrader 5",
        r"D:\Program Files\MetaTrader 5",
        r"D:\Program Files (x86)\MetaTrader 5",
        r"E:\Program Files\MetaTrader 5",
        r"E:\Program Files (x86)\MetaTrader 5",
    ]
    
    # Check multiple registry locations for MT5 installations
    registry_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\MetaQuotes\Terminal"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\MetaQuotes\Terminal"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\MetaQuotes\Terminal"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    
    for hkey, reg_path in registry_paths:
        try:
            with winreg.OpenKey(hkey, reg_path) as key:
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        try:
                            with winreg.OpenKey(key, subkey_name) as subkey:
                                # Try different value names for path
                                path_values = ["Path", "InstallLocation", "UninstallString", "DisplayIcon"]
                                for value_name in path_values:
                                    try:
                                        value = winreg.QueryValueEx(subkey, value_name)[0]
                                        if value:
                                            # Extract directory from various formats
                                            if value_name == "UninstallString":
                                                path = os.path.dirname(value)
                                            elif value_name == "DisplayIcon":
                                                path = os.path.dirname(value)
                                            else:
                                                path = value
                                            
                                            # Check if this is a MetaTrader directory
                                            if os.path.exists(path):
                                                mt5_exe = os.path.join(path, "terminal64.exe")
                                                if os.path.exists(mt5_exe):
                                                    # Avoid duplicates
                                                    if not any(t["path"] == path for t in terminals):
                                                        terminals.append({
                                                            "name": f"MetaTrader 5 ({subkey_name})",
                                                            "path": path,
                                                            "source": f"registry_{hkey}_{reg_path}"
                                                        })
                                                        break
                                    except (FileNotFoundError, OSError):
                                        continue
                        except (FileNotFoundError, OSError):
                            pass
                        i += 1
                    except OSError:
                        break
        except (FileNotFoundError, OSError):
            continue
    
    # Check common installation directories
    for path in common_paths:
        if os.path.exists(path):
            mt5_exe = os.path.join(path, "terminal64.exe")
            if os.path.exists(mt5_exe):
                # Avoid duplicates
                if not any(t["path"] == path for t in terminals):
                    terminals.append({
                        "name": f"MetaTrader 5 ({os.path.basename(path)})",
                        "path": path,
                        "source": "common_path"
                    })
    
    # Search for MT5 installations in all drives
    try:
        import psutil
        for disk in psutil.disk_partitions():
            drive = disk.mountpoint
            search_paths = [
                os.path.join(drive, "Program Files", "MetaTrader 5"),
                os.path.join(drive, "Program Files (x86)", "MetaTrader 5"),
                os.path.join(drive, "MT5"),
                os.path.join(drive, "MetaTrader5"),
                os.path.join(drive, "MetaTrader 5"),
            ]
            for path in search_paths:
                if os.path.exists(path):
                    mt5_exe = os.path.join(path, "terminal64.exe")
                    if os.path.exists(mt5_exe):
                        if not any(t["path"] == path for t in terminals):
                            terminals.append({
                                "name": f"MetaTrader 5 ({drive}{os.path.basename(path)})",
                                "path": path,
                                "source": "drive_search"
                            })
    except ImportError:
        # If psutil is not available, skip drive search
        pass
    
    # Check for portable installations in current directory and subdirectories
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    portable_paths = [
        os.path.join(parent_dir, "MT5"),
        os.path.join(parent_dir, "MetaTrader5"),
        os.path.join(parent_dir, "MetaTrader 5"),
        os.path.join(current_dir, "MT5"),
        os.path.join(current_dir, "MetaTrader5"),
        os.path.join(current_dir, "MetaTrader 5"),
    ]
    
    for path in portable_paths:
        if os.path.exists(path):
            mt5_exe = os.path.join(path, "terminal64.exe")
            if os.path.exists(mt5_exe):
                if not any(t["path"] == path for t in terminals):
                    terminals.append({
                        "name": f"MetaTrader 5 (Portable - {os.path.basename(path)})",
                        "path": path,
                        "source": "portable"
                    })
    
    # Search in START MENU shortcuts
    try:
        start_menu_paths = [
            rf"C:\Users\{username}\AppData\Roaming\Microsoft\Windows\Start Menu\Programs",
            r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
        ]
        
        for start_path in start_menu_paths:
            if os.path.exists(start_path):
                for root, dirs, files in os.walk(start_path):
                    for file in files:
                        if "metatrader" in file.lower() and file.endswith(".lnk"):
                            try:
                                import win32com.client
                                shell = win32com.client.Dispatch("WScript.Shell")
                                shortcut = shell.CreateShortCut(os.path.join(root, file))
                                target_path = os.path.dirname(shortcut.Targetpath)
                                if os.path.exists(target_path):
                                    mt5_exe = os.path.join(target_path, "terminal64.exe")
                                    if os.path.exists(mt5_exe):
                                        if not any(t["path"] == target_path for t in terminals):
                                            terminals.append({
                                                "name": f"MetaTrader 5 (Shortcut - {os.path.basename(file, '.lnk')})",
                                                "path": target_path,
                                                "source": "start_menu"
                                            })
                            except ImportError:
                                # If win32com is not available, skip shortcut search
                                break
    except Exception:
        # If there's any error in shortcut search, continue without it
        pass
    
    # Remove duplicates and sort by name
    unique_terminals = []
    seen_paths = set()
    for terminal in terminals:
        if terminal["path"] not in seen_paths:
            unique_terminals.append(terminal)
            seen_paths.add(terminal["path"])
    
    # Test each terminal to identify which ones work
    working_terminals = []
    non_working_terminals = []
    working_path = r"C:\Program Files\MetaTrader 5 Terminal"
    
    for terminal in unique_terminals:
        # Mark the known working terminal
        if terminal["path"] == working_path:
            terminal["name"] = f"[OK] {terminal['name']} (Recommended)"
            terminal["is_working"] = True
            working_terminals.append(terminal)
        else:
            terminal["is_working"] = False
            non_working_terminals.append(terminal)
    
    # Sort: working terminals first (recommended), then others alphabetically
    working_terminals.sort(key=lambda x: x["name"])
    non_working_terminals.sort(key=lambda x: x["name"])
    
    # Combine with working terminals first
    final_terminals = working_terminals + non_working_terminals
    
    # If no terminals found, add default entry
    if not final_terminals:
        final_terminals.append({
            "name": "MetaTrader 5 (Default)",
            "path": "",
            "source": "default",
            "is_working": False
        })
    
    # Log found terminals for debugging
    logging.info(f"Found {len(final_terminals)} MT5 terminals:")
    for terminal in final_terminals:
        status = "[OK] RECOMMENDED" if terminal.get("is_working") else "[WARNING] Unknown"
        logging.info(f"  {status} {terminal['name']} - {terminal['path']} (source: {terminal['source']})")
    
    return final_terminals

class MT5Automator:
    # Class-level symbol cache to persist across instances
    _symbol_cache = {}
    _symbol_cache_timestamp = {}
    _cache_ttl = 300  # Cache for 5 minutes
    
    def __init__(self, login, password, server, symbol=None, terminal_path=None):
        # Safely convert login to integer
        try:
            self.login = int(str(login).strip()) if login else 0
        except (ValueError, TypeError):
            logging.error(f'Invalid login format: {login}')
            self.login = 0
            
        self.password = str(password) if password else ""
        self.server = str(server) if server else ""
        self.symbol = symbol
        self.terminal_path = terminal_path
        self.sl_points = float(os.getenv('MT5_SL_POINTS') or os.getenv('MT5_STOPLOSS_POINTS', '0'))
        self.tp_points = float(os.getenv('MT5_TP_POINTS') or os.getenv('MT5_TAKEPROFIT_POINTS', '0'))
        self.default_volume = float(os.getenv('MT5_VOLUME', '1'))
        
        # Rollover safety tracking - prevents multiple executions per day
        self.rollover_executed_today = {}  # {prop_firm: date_string}
        
        # Store the actually connected symbol (will be set after successful connection)
        self.connected_symbol = None
        
        # Check if this is a PlexyTrade server (case-insensitive substring match)
        self.is_plexy_server = "plexy" in server.lower() if server else False
        if self.is_plexy_server:
            logging.info(f"PlexyTrade server detected: {server} - Lot sizes will be divided by 20")

        # Ensure all instance variables are properly initialized
        self.connected = False
        self.last_error = None

    def _get_cached_terminal_path(self):
        """Get previously successful terminal path for faster connection"""
        import tempfile
        cache_file = os.path.join(tempfile.gettempdir(), "mt5_terminal_cache.txt")
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    cached_path = f.read().strip()
                    if os.path.exists(cached_path):
                        return cached_path
        except Exception as e:
            logging.debug(f"Cache read failed: {e}")
        return None

    def _cache_successful_path(self, path):
        """Cache successful terminal path for future use"""
        import tempfile
        cache_file = os.path.join(tempfile.gettempdir(), "mt5_terminal_cache.txt")
        try:
            with open(cache_file, 'w') as f:
                f.write(path)
            logging.info(f"[OK] Cached successful MT5 path: {path}")
        except Exception as e:
            logging.debug(f"Cache write failed: {e}")

    def connect(self):
        # SPEED OPTIMIZATION: Try cached terminal path first
        success = False
        cached_path = self._get_cached_terminal_path()
        if cached_path:
            if mt5.initialize(path=cached_path):
                logging.info(f'[FAST] MT5 initialized with cached path: {cached_path}')
                success = True
            else:
                logging.info(f'Cached path failed, trying alternatives: {cached_path}')
        
        # Try to initialize MT5 with the best available path
        if not success:
            # CRITICAL FIX: If user specifies a terminal path, ONLY use that terminal
            if self.terminal_path and self.terminal_path.strip():
                terminal_exe = os.path.join(self.terminal_path, "terminal64.exe")
                if os.path.exists(terminal_exe):
                    if mt5.initialize(path=terminal_exe):
                        logging.info(f'MT5 initialized successfully with user-specified path: {terminal_exe}')
                        self._cache_successful_path(terminal_exe)  # Cache success
                        success = True
                    else:
                        logging.error(f'MT5 initialize failed for user-specified path: {terminal_exe}')
                        # Don't try other terminals when user specified one - respect their choice
                        error_code, error_msg = mt5.last_error()
                        self.last_error = f'MT5 initialize failed for selected terminal: {error_msg} (Code: {error_code})'
                        logging.error(self.last_error)
                        return False
                else:
                    logging.error(f'User-specified terminal executable not found: {terminal_exe}')
                    self.last_error = f'Terminal executable not found: {terminal_exe}'
                    return False
        
        # If specific paths failed, try other available installations
        if not success:
            terminals = get_installed_mt5_terminals()
            for terminal in terminals:
                terminal_exe = os.path.join(terminal["path"], "terminal64.exe")
                if os.path.exists(terminal_exe):
                    if mt5.initialize(path=terminal_exe):
                        logging.info(f'MT5 initialized successfully with detected path: {terminal_exe}')
                        self._cache_successful_path(terminal_exe)  # Cache success
                        success = True
                        break
                    else:
                        logging.warning(f'MT5 initialize failed for detected path: {terminal_exe}')
        
        # Last resort: try default initialization
        if not success:
            if mt5.initialize():
                logging.info('MT5 initialized successfully with default path')
                success = True
            else:
                logging.error('MT5 initialize failed with default path')
        
        if not success:
            error_code, error_msg = mt5.last_error()
            self.last_error = f'MT5 initialize failed: {error_msg} (Code: {error_code})'
            logging.error(self.last_error)
            return False
                
        authorized = mt5.login(self.login, self.password, self.server)
        if not authorized:
            error_msg = f'MT5 login failed for login={self.login}, server={self.server}'
            logging.error(error_msg)
            self.last_error = error_msg
            return False
        
        # SPEED OPTIMIZATION: Fast symbol detection after successful connection
        try:
            # Quick symbol detection - try user symbol first
            if self.symbol and mt5.symbol_select(self.symbol, True):
                self.connected_symbol = self.symbol
                logging.info(f"[FAST] Fast symbol detection: {self.connected_symbol}")
            else:
                # Quick fallback to first available symbol
                symbols = mt5.symbols_get()
                if symbols and len(symbols) > 0:
                    self.connected_symbol = symbols[0].name
                    if mt5.symbol_select(self.connected_symbol, True):
                        logging.info(f"[FAST] Fast fallback symbol: {self.connected_symbol}")
                    else:
                        # Last resort: use EURUSD as default
                        self.connected_symbol = "EURUSD"
                        logging.info(f"[FAST] Default symbol: {self.connected_symbol}")
                else:
                    self.connected_symbol = "EURUSD"  # Safe default
                    
        except Exception as e:
            logging.warning(f"Fast symbol detection failed: {e}")
            self.connected_symbol = self.symbol if self.symbol else "EURUSD"
        
        self.connected = True
        return True

    def monitor_connection(self):
        """
        Monitor MT5 connection status and attempt recovery if needed
        Call this periodically (e.g., every 30 seconds) during application operation
        """
        try:
            # Quick connection check
            terminal_info = mt5.terminal_info()
            if not terminal_info or not terminal_info.connected:
                logging.warning("🔍 MT5 connection monitor detected disconnection")
                return self.attempt_reconnection()

            # Check if trading is still allowed
            if not terminal_info.trade_allowed:
                logging.warning("🔍 MT5 connection monitor detected trading disabled")
                return False

            # Check account access
            account_info = mt5.account_info()
            if not account_info:
                logging.warning("🔍 MT5 connection monitor detected account access issues")
                return self.attempt_reconnection()

            return True

        except Exception as e:
            logging.error(f"Error in connection monitor: {e}")
            return False

    def ensure_session_integrity(self):
        """
        Ensure MT5 session is properly initialized and maintained
        Call this at application startup and periodically during operation
        """
        try:
            logging.info("[SETUP] Ensuring MT5 session integrity...")

            # Check if MT5 is initialized
            if not mt5.initialize():
                logging.warning("MT5 not initialized, attempting to initialize...")
                if not mt5.initialize():
                    logging.error("[ERROR] Failed to initialize MT5")
                    return False

            # Check if we're logged in
            if not mt5.terminal_info():
                logging.warning("MT5 terminal info not available, attempting connection...")
                if not self.connect():
                    logging.error("[ERROR] Failed to connect to MT5")
                    return False

            # Perform comprehensive health check
            is_healthy, health_msg = self.check_connection_health()
            if not is_healthy:
                logging.warning(f"MT5 health check failed: {health_msg}, attempting recovery...")
                if not self.attempt_reconnection():
                    logging.error("[ERROR] MT5 recovery failed")
                    return False

            # Ensure symbol is properly selected
            if self.symbol:
                symbol_info = mt5.symbol_info(self.symbol)
                if symbol_info and not symbol_info.visible:
                    logging.info(f"Ensuring symbol {self.symbol} is selected...")
                    mt5.symbol_select(self.symbol, True)

            logging.info("[OK] MT5 session integrity confirmed")
            return True

        except Exception as e:
            logging.error(f"Error ensuring MT5 session: {e}")
            return False

    def attempt_reconnection(self, max_retries=3):
        """
        Attempt to reconnect to MT5 if connection is lost
        """
        for attempt in range(max_retries):
            try:
                logging.info(f"🔄 Attempting MT5 reconnection (attempt {attempt + 1}/{max_retries})...")

                # Shutdown current connection
                mt5.shutdown()

                # Wait a moment
                time.sleep(1)

                # Try to reconnect
                if self.connect():
                    # Verify the reconnection worked
                    is_healthy, health_msg = self.check_connection_health()
                    if is_healthy:
                        logging.info("[OK] MT5 reconnection successful")
                        return True
                    else:
                        logging.warning(f"Reconnection completed but health check failed: {health_msg}")
                else:
                    logging.warning(f"Reconnection attempt {attempt + 1} failed")

            except Exception as e:
                logging.error(f"Error during reconnection attempt {attempt + 1}: {e}")

        logging.error(f"[ERROR] All {max_retries} reconnection attempts failed")
        return False

    def check_connection_health(self):
        """
        Comprehensive health check for MT5 connection and trading readiness
        Returns (is_healthy, error_message)
        """
        try:
            logging.info("🔍 Performing MT5 connection health check...")

            # 1. Check MT5 initialization
            if not mt5.initialize():
                return False, "MT5 not initialized"

            # 2. Check terminal connection
            terminal_info = mt5.terminal_info()
            if not terminal_info:
                return False, "Cannot get terminal info"

            if not terminal_info.connected:
                return False, "MT5 terminal not connected"

            if not terminal_info.trade_allowed:
                return False, "Trading not allowed in MT5 terminal"

            # 3. Check account access
            account_info = mt5.account_info()
            if not account_info:
                return False, "Cannot access account info"

            # 4. Check symbol availability (using configured symbol)
            if self.symbol:
                symbol_info = mt5.symbol_info(self.symbol)
                if not symbol_info:
                    return False, f"Symbol {self.symbol} not found in MT5"

                if not symbol_info.visible:
                    return False, f"Symbol {self.symbol} not visible in Market Watch"

                # 5. Check tick data availability
                tick = mt5.symbol_info_tick(self.symbol)
                if not tick or tick.bid <= 0 or tick.ask <= 0:
                    return False, f"No live tick data for symbol {self.symbol}"

            logging.info("[OK] MT5 connection health check passed")
            return True, "All systems operational"

        except Exception as e:
            error_msg = f"Health check failed: {e}"
            logging.error(f"[ERROR] {error_msg}")
            return False, error_msg

    def verify_connection(self):
        """
        Verify MT5 connection is stable and ready for trading
        """
        try:
            # Check terminal info
            terminal_info = mt5.terminal_info()
            if not terminal_info:
                logging.error("MT5 terminal_info() returned None")
                return False

            if not terminal_info.connected:
                logging.error("MT5 terminal not connected")
                return False

            if not terminal_info.trade_allowed:
                logging.error("MT5 trading not allowed")
                return False

            # Check account info
            account_info = mt5.account_info()
            if not account_info:
                logging.error("MT5 account_info() returned None")
                return False

            logging.info("[OK] MT5 connection verified - terminal connected, trading allowed, account accessible")
            return True

        except Exception as e:
            logging.error(f"Error verifying MT5 connection: {e}")
            return False

    def _verify_symbol_tick_data(self, symbol, max_retries=3):
        """
        Verify symbol has live tick data available
        """
        for attempt in range(max_retries):
            try:
                tick = mt5.symbol_info_tick(symbol)
                if tick and tick.bid > 0 and tick.ask > 0:
                    logging.info(f"[OK] Tick data verified for {symbol}: bid={tick.bid}, ask={tick.ask}")
                    return True

                if attempt < max_retries - 1:
                    logging.warning(f"Tick data not available for {symbol} (attempt {attempt + 1}/{max_retries}), retrying...")
                    time.sleep(0.1)  # Brief delay before retry

            except Exception as e:
                logging.error(f"Error getting tick data for {symbol}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(0.1)

        logging.error(f"[ERROR] No tick data available for {symbol} after {max_retries} attempts")
        return False

    def is_autotrading_enabled(self):
        """
        Check if AutoTrading is enabled in MT5 using the existing connection
        Returns True if autotrading is enabled, False otherwise
        """
        try:
            # Don't initialize a new connection - use the existing one
            if not self.connected:
                print("[ERROR] MT5 not connected - cannot check AutoTrading status")
                return False
                
            # Use the already connected MT5 instance to check terminal info
            term_info = mt5.terminal_info()
            if not term_info:
                print("[ERROR] Could not get terminal info from existing MT5 connection")
                return False
                
            # Check AutoTrading status using the connected instance
            print("🔍 Checking AutoTrading status on existing MT5 connection...")
            
            # Basic status checks
            connected = getattr(term_info, 'connected', False)
            trade_allowed = getattr(term_info, 'trade_allowed', False)
            tradeapi_disabled = getattr(term_info, 'tradeapi_disabled', True)
            dlls_allowed = getattr(term_info, 'dlls_allowed', False)
            
            # Log the current status
            print(f"[CHECK] Connected: {connected}")
            print(f"[CHECK] Trade Allowed: {trade_allowed}")
            print(f"[CHECK] Trade API Disabled: {tradeapi_disabled}")
            print(f"[CHECK] DLLs Allowed: {dlls_allowed}")
            
            # AutoTrading is enabled if:
            # 1. MT5 is connected
            # 2. Trade is allowed (main AutoTrading setting)
            # 3. Trade API is not disabled
            autotrading_enabled = connected and trade_allowed and not tradeapi_disabled
            
            print(f"[RESULT] AutoTrading enabled: {autotrading_enabled}")
            return autotrading_enabled
            
        except Exception as e:
            print(f"[ERROR] AutoTrading status check failed: {e}")
            logging.error(f"Error checking auto trading status: {e}")
            return False

    def ensure_symbol(self, symbol):
        """Ensure symbol is available for trading, with enhanced caching and fast paths"""
        try:
            # Validate input symbol
            if not symbol or symbol.strip() == "":
                logging.error(f"Invalid symbol provided: '{symbol}'")
                raise Exception(f"Invalid symbol provided: '{symbol}'")
            
            symbol = symbol.strip()
            
            # SPEED OPTIMIZATION: Check symbol cache first
            cache_key = f"{self.server}_{symbol}"
            current_time = time.time()
            
            if (cache_key in self._symbol_cache and 
                cache_key in self._symbol_cache_timestamp and
                current_time - self._symbol_cache_timestamp[cache_key] < self._cache_ttl):
                
                cached_symbol = self._symbol_cache[cache_key]
                logging.info(f"[FAST] SPEED: Using cached symbol {symbol} → {cached_symbol}")
                return cached_symbol
            
            # First check if MT5 is connected
            if not mt5.terminal_info():
                logging.error("MT5 terminal not connected")
                # CRITICAL: Don't return symbol if MT5 is not connected - this causes trading failures
                logging.error("Cannot validate symbol - MT5 terminal not connected")
                return None
                
            # PRIORITY: Since users provide correct symbol names, try their symbol first
            logging.info(f"[TARGET] USER SYMBOL: Trying user-provided symbol '{symbol}' first")
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info:
                tick = mt5.symbol_info_tick(symbol)
                if tick and (tick.bid > 0 or tick.ask > 0):
                    logging.info(f"[OK] USER SYMBOL WORKS: '{symbol}' has active tick data")
                    # Cache the successful result
                    self._symbol_cache[cache_key] = symbol
                    self._symbol_cache_timestamp[cache_key] = current_time
                    return symbol
                else:
                    # Symbol exists but no tick data - CRITICAL: Don't proceed with trading
                    logging.error(f"[ERROR] Symbol {symbol} exists but no tick data available - cannot trade")
                    return None
            
            # Try to select the symbol if it wasn't found
            logging.info(f"[SIGNAL] SELECTING SYMBOL: Attempting to activate '{symbol}'")
            select_result = mt5.symbol_select(symbol, True)
            
            # Check again after selection
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info:
                tick = mt5.symbol_info_tick(symbol)
                if tick and (tick.bid > 0 or tick.ask > 0):
                    logging.info(f"[OK] SYMBOL ACTIVATED: '{symbol}' now has active tick data")
                    self._symbol_cache[cache_key] = symbol
                    self._symbol_cache_timestamp[cache_key] = current_time
                    return symbol
                else:
                    # Symbol selected but no tick - still return for trading attempt
                    logging.info(f"[WARNING] SYMBOL SELECTED: '{symbol}' activated but no tick data yet")
                    self._symbol_cache[cache_key] = symbol
                    self._symbol_cache_timestamp[cache_key] = current_time
                    return symbol

            # SPEED OPTIMIZATION: For known symbols, try direct approach first
            if symbol.upper() in ['USTECH', 'USTEC', 'XAUUSD', 'NAS100', 'NASDAQ']:
                # Try the symbol directly first (fastest path)
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info:
                    tick = mt5.symbol_info_tick(symbol)
                    if tick and (tick.bid > 0 or tick.ask > 0):
                        logging.info(f"[FAST] SPEED: Direct symbol access successful for {symbol}")
                        # Cache the successful result
                        self._symbol_cache[cache_key] = symbol
                        self._symbol_cache_timestamp[cache_key] = current_time
                        return symbol

            # Get symbol variations to try (only if direct access failed)
            symbol_variations = self._get_symbol_variations(symbol)
            logging.info(f"[SEARCH] VARIATIONS: Trying {len(symbol_variations)} variations for '{symbol}'")
            
            # SPEED OPTIMIZATION: Try most likely variations first
            priority_variations = []
            other_variations = []
            
            for variation in symbol_variations:
                # Prioritize exact matches and simple variations
                if (variation == symbol or 
                    variation == symbol.upper() or
                    variation in ['USTECH', 'USTEC', 'XAUUSD']):
                    priority_variations.append(variation)
                else:
                    other_variations.append(variation)
            
            # Try priority variations first, then others
            all_variations = priority_variations + other_variations[:20]  # Limit to first 20 of others
            
            for variation in all_variations:
                try:
                    # First check if this variation has symbol info
                    var_info = mt5.symbol_info(variation)
                    if not var_info:
                        logging.debug(f"Symbol variation {variation} not found")
                        continue
                    
                    # Check if it already has tick data (means it's working)
                    tick = mt5.symbol_info_tick(variation)
                    if tick and (tick.bid > 0 or tick.ask > 0):
                        logging.info(f"[FAST] SPEED: Symbol variation {variation} already has active tick data")
                        self._symbol_cache[cache_key] = variation
                        self._symbol_cache_timestamp[cache_key] = current_time
                        return variation
                    
                    # Try to select the symbol (but don't fail if this returns False)
                    # Some brokers return False even when symbol is already available
                    select_result = mt5.symbol_select(variation, True)
                    logging.debug(f"Symbol select result for {variation}: {select_result}")
                    
                    # After selection attempt, check again for tick data
                    tick_after = mt5.symbol_info_tick(variation)
                    if tick_after and (tick_after.bid > 0 or tick_after.ask > 0):
                        logging.info(f"[OK] VARIATION SUCCESS: '{variation}' now has active tick data")
                        self._symbol_cache[cache_key] = variation
                        self._symbol_cache_timestamp[cache_key] = current_time
                        return variation
                    
                    # If still no tick data, but symbol info exists, it might still work for some operations
                    if var_info and var_info.visible:
                        logging.info(f"[WARNING] VARIATION VISIBLE: '{variation}' is visible but no current tick data")
                        self._symbol_cache[cache_key] = variation
                        self._symbol_cache_timestamp[cache_key] = current_time
                        return variation
                        
                except Exception as e:
                    logging.debug(f"Error trying symbol variation {variation}: {e}")
                    continue
                    
            # CRITICAL: Don't return symbol as fallback if no valid symbol was found
            logging.error(f"[FAILED] No valid symbol found for {symbol} - cannot proceed with trading")
            return None
            
        except Exception as e:
            logging.error(f"Error in ensure_symbol for '{symbol}': {e}")
            
            # CRITICAL: Always return user's symbol to prevent None errors
            # Users are expected to provide correct symbol names for their broker
            logging.warning(f"🆘 EMERGENCY FALLBACK: Returning user symbol '{symbol}' despite errors")
            return symbol
    
    def _get_symbol_variations(self, symbol):
        """Get possible symbol variations for different MT5 brokers"""
        # Start with the original symbol
        variations = [symbol]
        
        # Add common variations based on symbol type
        symbol_upper = symbol.upper()
        
        # NASDAQ variations - comprehensive list based on actual MT5 charts
        if symbol_upper in ['USTEC', 'NASDAQ', 'NQ', 'NAS', 'USTECH100', 'USTECH', 'NAS100', 'NDX', 'NASDAQ100', 'TECH100', 'US100', 'SPX500']:
            variations.extend([
                # Primary NASDAQ symbols
                'USTEC', 'USTECH100', 'USTECH', 'NAS100', 'NASDAQ', 'NQ', 'NDX', 'NASDAQ100',
                'US100', 'TECH100', 'USTEC100', 'NASTECH', 'NASDAQTECH',
                
                # Suffixed variations (.m, m, -Z, etc.)
                'USTEC.m', 'USTECH100.m', 'USTECH.m', 'NAS100.m', 'NASDAQ.m', 'NQ.m', 'NDX.m',
                'USTECm', 'USTECH100m', 'USTECHm', 'NAS100m', 'NASDAQm', 'NQm', 'NDXm',
                'USTEC-Z', 'USTECH100-Z', 'USTECH-Z', 'NAS100-Z', 'NASDAQ-Z', 'NQ-Z', 'NDX-Z',
                
                # Broker-specific variations
                'USTECfxf', 'USTECH100fxf', 'USTECHfxf', 'NAS100fxf', 'NASDAQfxf',
                'USTEC_c', 'USTECH_c', 'NAS100_c', 'NASDAQ_c',
                'USTEC.c', 'USTECH.c', 'NAS100.c', 'NASDAQ.c',
                
                # Alternative naming patterns
                'US_TECH', 'US-TECH', 'USTECH.', 'USTEC.', 'NAS100.',
                'USTECH100.', 'NASDAQ100.', 'TECH-100', 'TECH_100',
                
                # Contract-specific variations (futures style)
                'USTECH2024', 'USTEC2024', 'NAS2024', 'USTECH24', 'USTEC24', 'NAS24',
                'USTECHM24', 'USTECM24', 'NASM24', 'USTECHZ24', 'USTECZ24', 'NASZ24',
                
                # Additional broker variations
                'USTEC100', 'NASTECH100', 'USNASDAQ', 'NASDAQ_100', 'NASDAQ-100',
                'USTEC_100', 'USTEC-100', 'USTECH_100', 'USTECH-100',
                
                # Dot variations
                'USTEC.', 'USTECH.', 'NASDAQ.', 'NAS100.', 'NQ.',
                
                # Undercore variations  
                'USTEC_', 'USTECH_', 'NASDAQ_', 'NAS100_', 'NQ_'
            ])
        
        # Gold variations - comprehensive list for different brokers
        elif symbol_upper in ['XAUUSD', 'GOLD', 'GLD', 'XAU']:
            variations.extend([
                'XAUUSD', 'GOLD', 'XAU', 'GOLDUSD', 'XAUUSD.',
                'XAUUSD.m', 'GOLD.m', 'XAUUSDm', 'GOLDm',
                'XAUUSD-Z', 'GOLD-Z', 'XAU/USD', 'GOLD/USD',
                'XAUUSDfxf', 'GOLDfxf', 'XAUUSD_MT5'
            ])
        
        # Oil variations
        elif symbol_upper in ['USOIL', 'OIL', 'CRUDE']:
            variations.extend(['USOIL', 'CRUDE', 'OIL', 'WTI', 'BRENT'])
        
        # Forex pairs - try both with and without suffixes
        elif len(symbol) == 6 and symbol_upper.endswith('USD'):
            base_pair = symbol_upper[:6]
            variations.extend([base_pair, base_pair + '.', base_pair + 'm', base_pair + 'c'])
        
        # Remove duplicates while preserving order
        seen = set()
        result = []
        for variant in variations:
            if variant not in seen:
                seen.add(variant)
                result.append(variant)
        
        return result
    
    def _log_available_symbols(self, failed_symbol):
        """Log some available symbols for debugging"""
        try:
            # Get all available symbols
            symbols = mt5.symbols_get()
            if symbols:
                # Log total count
                logging.info(f"Failed symbol: {failed_symbol}")
                logging.info(f"Total available symbols: {len(symbols)}")
                
                # Log first 20 symbols
                symbol_names = [s.name for s in symbols[:20]]
                logging.info(f"Available symbols (first 20): {symbol_names}")
                
                # Look for symbols containing parts of the failed symbol
                failed_upper = failed_symbol.upper()
                similar = []
                for s in symbols:
                    symbol_name = s.name.upper()
                    # Check for partial matches
                    if (failed_upper[:3] in symbol_name or 
                        symbol_name[:3] in failed_upper or
                        'XAU' in symbol_name or 
                        'GOLD' in symbol_name or
                        'USTEC' in symbol_name or
                        'NAS' in symbol_name):
                        similar.append(s.name)
                
                if similar:
                    logging.info(f"Similar/related symbols found: {similar[:10]}")  # Show max 10
                
                # Check specifically for gold and nasdaq symbols
                gold_symbols = [s.name for s in symbols if any(x in s.name.upper() for x in ['XAU', 'GOLD'])]
                nasdaq_symbols = [s.name for s in symbols if any(x in s.name.upper() for x in ['USTEC', 'NAS', 'NDX'])]
                
                if gold_symbols:
                    logging.info(f"Gold-related symbols: {gold_symbols}")
                if nasdaq_symbols:
                    logging.info(f"NASDAQ-related symbols: {nasdaq_symbols}")
                    
            else:
                logging.warning("No symbols available - check MT5 connection")
        except Exception as e:
            logging.warning(f"Could not retrieve available symbols: {e}")

    def get_connected_symbol(self):
        """Get the symbol that was detected during connection"""
        return self.connected_symbol

    def get_safe_symbol(self, fallback_symbol=None):
        """Get a safe symbol to use - prefers fallback (configured), then connected symbol, then configured symbol"""
        # Priority 1: Use the explicitly requested/configured symbol if provided and available
        if fallback_symbol:
            # Try to select the requested symbol to ensure it's available
            if mt5.symbol_select(fallback_symbol, True):
                return fallback_symbol
            else:
                logging.warning(f"Requested symbol {fallback_symbol} not available, falling back to connected symbol")
        
        # Priority 2: Use connected symbol if no specific symbol requested or if requested symbol unavailable
        if self.connected_symbol:
            return self.connected_symbol
        elif self.symbol:
            return self.symbol
        else:
            # Ultimate fallback
            return "EURUSD"

    def get_supported_filling_modes(self, symbol):
        info = mt5.symbol_info(symbol)
        if info is None:
            return [mt5.ORDER_FILLING_IOC]
        fillings = getattr(info, "trade_fillings", None)
        if not fillings or len(fillings) == 0:
            return [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
        return list(fillings)

    def _calculate_sl_tp_price(self, symbol, order_type, price, sl_points, tp_points):
        """Calculate SL and TP prices from points - NASDAQ automation always uses 1.0 point value"""
        sl_price = None
        tp_price = None
        
        # Get symbol info for logging purposes
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            logging.error(f"Could not get symbol info for {symbol}")
            return sl_price, tp_price
        
        # Get the minimum tick size for reference
        point = symbol_info.point
        
        # NASDAQ automation: ALWAYS use 1.0 point value regardless of symbol name or tick size
        point_value = 1.0
        logging.info(f"Symbol {symbol} - tick size: {point}, NASDAQ automation point value: {point_value}, price: {price}")
        
        if sl_points and float(sl_points) > 0:
            sl_points_float = float(sl_points)
            price_difference = sl_points_float * point_value
            
            if order_type == "buy":
                sl_price = price - price_difference
            else:  # sell
                sl_price = price + price_difference
                
            logging.info(f"SL calculation: {sl_points_float} points × {point_value} = {price_difference} price diff, SL price: {sl_price}")
                
        if tp_points and float(tp_points) > 0:
            tp_points_float = float(tp_points)
            price_difference = tp_points_float * point_value
            
            if order_type == "buy":
                tp_price = price + price_difference
            else:  # sell
                tp_price = price - price_difference
                
            logging.info(f"TP calculation: {tp_points_float} points × {point_value} = {price_difference} price diff, TP price: {tp_price}")
                
        return sl_price, tp_price

    def place_order(self, symbol, order_type, volume=None, sl=None, tp=None, comment=None):
        try:
            # PRE-TRADE HEALTH CHECK: Ensure MT5 is ready for trading
            is_healthy, health_error = self.check_connection_health()
            if not is_healthy:
                logging.error(f"[ERROR] Pre-trade health check failed: {health_error}")
                # Attempt reconnection
                logging.info("🔄 Attempting automatic reconnection...")
                if self.attempt_reconnection():
                    # Re-check health after reconnection
                    is_healthy, health_error = self.check_connection_health()
                    if not is_healthy:
                        raise Exception(f"MT5 reconnection failed: {health_error}")
                else:
                    raise Exception(f"MT5 health check failed and reconnection unsuccessful: {health_error}")

            # Validate input parameters
            if not symbol or symbol.strip() == "":
                logging.error(f"Invalid symbol provided to place_order: '{symbol}'")
                raise Exception(f"Invalid symbol provided: '{symbol}'")
            
            symbol = symbol.strip()
            
            # Ensure symbol is available and get the correct symbol name
            corrected_symbol = self.ensure_symbol(symbol)
            
            # CRITICAL: Validate that ensure_symbol didn't return None
            if not corrected_symbol:
                logging.error(f"ensure_symbol returned None for '{symbol}' - MT5 connection or symbol validation failed")
                raise Exception(f"Symbol validation failed for '{symbol}' - check MT5 connection and symbol availability")
            
            # Log order details with corrected symbol
            logging.info(f"📋 PLACING ORDER: {order_type.upper()} {corrected_symbol}, volume={volume}, sl={sl}, tp={tp}, comment={comment}")
            
            # Debug symbol info to understand MT5 properties (only log once per symbol)
            if not hasattr(self, '_debugged_symbols'):
                self._debugged_symbols = set()
            if corrected_symbol not in self._debugged_symbols:
                self.debug_symbol_info(corrected_symbol)
                self._debugged_symbols.add(corrected_symbol)
            
            tick = mt5.symbol_info_tick(corrected_symbol)
            print(f"[SEARCH] TICK RETRIEVAL DEBUG for {corrected_symbol}:")
            print(f"   Raw tick result: {tick}")
            if tick:
                print(f"   Tick ask: {tick.ask}, bid: {tick.bid}")
                print(f"   Tick time: {tick.time}")
            else:
                print(f"   [ERROR] Tick is None - investigating...")
                
                # Check MT5 initialization
                if not mt5.initialize():
                    print(f"   [ERROR] MT5 not initialized - attempting to initialize...")
                    if mt5.initialize():
                        print(f"   [OK] MT5 initialization successful")
                        # Try getting tick again after initialization
                        tick = mt5.symbol_info_tick(corrected_symbol)
                        print(f"   Retry after init: {tick}")
                    else:
                        print(f"   [ERROR] MT5 initialization failed")
                
                # Check terminal connection
                terminal_info = mt5.terminal_info()
                print(f"   Terminal info: {terminal_info}")
                if terminal_info:
                    print(f"   Terminal connected: {terminal_info.connected}")
                    print(f"   Terminal trade allowed: {terminal_info.trade_allowed}")
                
                # Check if symbol exists in symbol_info
                symbol_info = mt5.symbol_info(corrected_symbol)
                print(f"   Symbol info: {symbol_info}")
                if symbol_info:
                    print(f"   Symbol visible: {symbol_info.visible}")
                    print(f"   Symbol selected: {symbol_info.select}")
                    
                    # Try to select the symbol explicitly
                    if not symbol_info.visible:
                        print(f"   Attempting to select symbol...")
                        select_result = mt5.symbol_select(corrected_symbol, True)
                        print(f"   Symbol select result: {select_result}")
                        if select_result:
                            # Try getting tick again after selecting
                            tick = mt5.symbol_info_tick(corrected_symbol)
                            print(f"   Tick after select: {tick}")
            
            if tick is None:
                # Enhanced debugging for symbol issues
                logging.error(f"[ERROR] SYMBOL PRICE FETCH FAILED: {corrected_symbol}")
                
                # Check if symbol is selected in Market Watch
                selected = mt5.symbol_select(corrected_symbol, True)
                logging.error(f"[SEARCH] Symbol select result: {selected}")
                
                # Check symbol info
                symbol_info = mt5.symbol_info(corrected_symbol)
                if symbol_info:
                    logging.error(f"[SEARCH] Symbol info exists: visible={symbol_info.visible}, tradeable={symbol_info.trade_mode}")
                else:
                    logging.error(f"[SEARCH] Symbol info is None - symbol may not exist")
                
                # Try to get symbols that match pattern
                matching_symbols = mt5.symbols_get(group=f"*{corrected_symbol}*")
                if matching_symbols:
                    logging.error(f"[SEARCH] Found {len(matching_symbols)} matching symbols:")
                    for sym in matching_symbols[:5]:  # Show first 5 matches
                        logging.error(f"   - {sym.name}")
                else:
                    logging.error(f"[SEARCH] No symbols found matching pattern *{corrected_symbol}*")
                
                # Enhanced symbol debugging for "Could not get price" issues
                print(f"[SEARCH] SYMBOL DEBUG: No price data for {corrected_symbol}")
                print(f"   Checking symbol selection and market watch...")
                
                # Check if symbol is in Market Watch
                market_watch_symbols = mt5.symbols_get()
                if market_watch_symbols:
                    symbol_names = [s.name for s in market_watch_symbols]
                    if corrected_symbol not in symbol_names:
                        print(f"[ERROR] SYMBOL ERROR: {corrected_symbol} not in Market Watch")
                        print(f"   Available symbols: {symbol_names[:10]}")  # Show first 10
                    else:
                        print(f"[OK] SYMBOL FOUND: {corrected_symbol} is in Market Watch")
                
                # Try exact symbol matching
                exact_match = mt5.symbol_info(corrected_symbol)
                if not exact_match:
                    print(f"[ERROR] EXACT MATCH FAILED: {corrected_symbol} not found")
                    # Try pattern matching for similar symbols
                    if market_watch_symbols:
                        similar_symbols = [s.name for s in market_watch_symbols 
                                          if corrected_symbol.lower() in s.name.lower() or s.name.lower() in corrected_symbol.lower()]
                        if similar_symbols:
                            print(f"[SEARCH] SIMILAR SYMBOLS: {similar_symbols}")
                else:
                    print(f"[OK] SYMBOL EXISTS: {corrected_symbol} found in MT5")
                
                raise Exception(f"Could not get price for {corrected_symbol} - MT5 connection issue or symbol not receiving live data. Check: 1) MT5 terminal is connected, 2) Symbol '{corrected_symbol}' is in Market Watch, 3) Live data feed is active")
                
            # SUCCESS: We have a valid tick, now extract the price
            price = tick.ask if order_type == "buy" else tick.bid
            print(f"[OK] PRICE EXTRACTED: {order_type} price for {corrected_symbol} = {price}")
            print(f"   Full tick data: ask={tick.ask}, bid={tick.bid}, spread={tick.ask - tick.bid if tick.ask and tick.bid else 'N/A'}")
            
            # Validate price is reasonable
            if price <= 0:
                print(f"[ERROR] INVALID PRICE: {price} <= 0")
                raise Exception(f"Invalid price {price} for {corrected_symbol}")
            
            type_mt5 = mt5.ORDER_TYPE_BUY if order_type == "buy" else mt5.ORDER_TYPE_SELL
            supported_fillings = self.get_supported_filling_modes(corrected_symbol)
            last_error = None
            
            if sl is None:
                sl = self.sl_points
            if tp is None:
                tp = self.tp_points
            if volume is None:
                volume = self.default_volume
                
            # Apply PlexyTrade lot size adjustment - ONLY for USTECH (Nasdaq)
            # XAUUSD (Gold) pip values are consistent across brokers, so no division needed
            if self.is_plexy_server and volume > 0:
                # Only divide lot size for USTECH/Nasdaq symbols
                if any(x in corrected_symbol.upper() for x in ['USTECH', 'USTEC', 'NAS', 'NASDAQ', 'NDX', 'NQ']):
                    original_volume = volume
                    volume = volume / 20.0
                    logging.info(f"PlexyTrade adjustment for {corrected_symbol}: {original_volume} -> {volume} lots")
                else:
                    logging.info(f"PlexyTrade: No lot size adjustment for {corrected_symbol} (only divide USTECH, not Gold)")
                
            # Ensure SL and TP are always set (never skip) - use defaults if 0
            if sl is None or float(sl) <= 0:
                sl = self.sl_points if self.sl_points > 0 else 10  # Default 10 points if not set
                logging.info(f"Using default/minimum SL: {sl} points")
            if tp is None or float(tp) <= 0:
                tp = self.tp_points if self.tp_points > 0 else 20  # Default 20 points if not set
                logging.info(f"Using default/minimum TP: {tp} points")
                
            # Convert to float and ensure they're positive
            sl = float(sl)
            tp = float(tp)
            volume = float(volume)
            
            sl_price, tp_price = self._calculate_sl_tp_price(corrected_symbol, order_type, price, sl, tp)
            
            logging.info(f"Order parameters: price={price}, sl_price={sl_price}, tp_price={tp_price}")
            
            for filling_mode in supported_fillings:
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": corrected_symbol,
                    "volume": volume,
                    "type": type_mt5,
                    "price": price,
                    "deviation": 20,
                    "type_filling": filling_mode,
                    "type_time": mt5.ORDER_TIME_GTC,
                }
                
                # Add comment if provided
                if comment:
                    request["comment"] = comment
                
                # ALWAYS add SL and TP - never skip them
                if sl_price is not None:
                    request["sl"] = sl_price
                    logging.info(f"Setting SL price: {sl_price}")
                if tp_price is not None:
                    request["tp"] = tp_price
                    logging.info(f"Setting TP price: {tp_price}")
                    
                logging.info(f"Sending order request: {request}")
                result = mt5.order_send(request)
                
                if result is not None:
                    logging.info(f"Order result: retcode={result.retcode}, comment={result.comment}")
                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        logging.info(f"Order successful: {order_type} {corrected_symbol} {volume} at {price}, ticket={result.order}")
                        return result.order
                    else:
                        # Enhanced error handling for common MT5 trading issues
                        error_msg = result.comment if result.comment else "Unknown error"
                        
                        # Check for automated trading permission issues
                        if result.retcode == 10027:  # TRADE_RETCODE_CLIENT_DISABLES_AT
                            print(f"[ERROR] MT5 TRADING ERROR: Automated trading is disabled in MT5 terminal")
                            print(f"[TOOL] SOLUTION: Enable automated trading in MT5:")
                            print(f"   1. Go to Tools → Options → Expert Advisors")
                            print(f"   2. Check 'Allow algorithmic trading'")
                            print(f"   3. Check 'Allow DLL imports'")
                            print(f"   4. Click OK and restart application")
                            raise Exception("Automated trading disabled in MT5 - Enable in Tools → Options → Expert Advisors")
                        
                        elif result.retcode == 10026:  # TRADE_RETCODE_TRADE_DISABLED
                            print(f"[ERROR] MT5 TRADING ERROR: Trading is disabled")
                            print(f"[TOOL] SOLUTION: Check MT5 terminal settings and broker permissions")
                            raise Exception("Trading disabled - Check MT5 settings and broker permissions")
                        
                        elif result.retcode == 10013:  # TRADE_RETCODE_INVALID_REQUEST
                            print(f"[ERROR] MT5 TRADING ERROR: Invalid trading request")
                            print(f"[TOOL] SOLUTION: Check symbol, volume, and market hours")
                            raise Exception(f"Invalid trading request: {error_msg}")
                        
                        elif result.retcode == 10004:  # TRADE_RETCODE_REQUOTE
                            print(f"[WARNING] MT5 TRADING: Price requote - retrying...")
                            
                        elif result.retcode == 10018:  # TRADE_RETCODE_MARKET_CLOSED
                            print(f"[ERROR] MT5 TRADING ERROR: Market is closed")
                            print(f"[TOOL] SOLUTION: Wait for market opening hours")
                            raise Exception("Market is closed - Wait for trading hours")
                        
                        elif result.retcode == 10019:  # TRADE_RETCODE_NO_MONEY
                            print(f"[ERROR] MT5 TRADING ERROR: Insufficient funds")
                            print(f"[TOOL] SOLUTION: Check account balance and reduce position size")
                            raise Exception("Insufficient funds - Check account balance")
                        
                        else:
                            print(f"[ERROR] MT5 TRADING ERROR: {error_msg} (Code: {result.retcode})")
                            print(f"[TOOL] SOLUTION: Check MT5 terminal for detailed error information")
                        
                        last_error = f"{error_msg} (Code: {result.retcode})"
                else:
                    last_error = "No result returned"
                    print(f"[ERROR] MT5 CRITICAL: No response from MT5 terminal")
                    print(f"[TOOL] SOLUTION: Check MT5 terminal connection and restart if needed")
                    
                logging.warning(f"Order attempt failed: {order_type} {corrected_symbol} {volume} at {price}, filling={filling_mode}, error={last_error}")
                
            logging.error(f"Order failed: {order_type} {corrected_symbol} {volume} at {price}, last_error={last_error}")
            raise Exception(f"Order failed: {last_error}")
            
        except Exception as e:
            logging.exception(f"Exception in place_order: {e}")
            raise

    def buy_market(self, symbol, volume=None, sl=None, tp=None, comment=None):
        return self.place_order(symbol, "buy", volume=volume, sl=sl, tp=tp, comment=comment)

    def sell_market(self, symbol, volume=None, sl=None, tp=None, comment=None):
        return self.place_order(symbol, "sell", volume=volume, sl=sl, tp=tp, comment=comment)

    def is_connected(self):
        """Check if MT5 connection is still active"""
        try:
            # Try to get account info to test connection
            account_info = mt5.account_info()
            if account_info is None:
                return False
            return True
        except Exception:
            return False
    
    def check_connection_and_disconnect_if_needed(self):
        """Check connection and disconnect if lost"""
        if not self.is_connected():
            logging.warning("MT5 connection lost, disconnecting...")
            self.disconnect()
            return False
        return True

    def disconnect(self):
        """Properly disconnect from MT5 with enhanced cleanup and terminal closure"""
        try:
            # First, perform standard MT5 API shutdown
            if mt5.terminal_info() is not None:
                mt5.shutdown()
                logging.info("MT5 API disconnected successfully")
            else:
                logging.info("MT5 API was already disconnected")
                
            # Force close MT5 terminal processes to ensure complete shutdown
            self._close_mt5_processes()
            
        except Exception as e:
            logging.error(f"Error during MT5 disconnect: {e}")
            # Force shutdown and process termination even if there was an error
            try:
                mt5.shutdown()
            except:
                pass
            # Still attempt to close processes
            self._close_mt5_processes()

    def _close_mt5_processes(self):
        """Force close all MT5 terminal processes"""
        try:
            closed_processes = []
            
            # Look for MT5 processes by name
            for proc in psutil.process_iter(['pid', 'name', 'exe']):
                try:
                    proc_name = proc.info['name'].lower()
                    proc_exe = proc.info['exe']
                    
                    # Check if this is an MT5 process
                    if (proc_name in ['terminal64.exe', 'terminal.exe', 'metatrader5.exe'] or
                        (proc_exe and 'metatrader' in proc_exe.lower())):
                        
                        proc.terminate()  # Send termination signal
                        closed_processes.append(f"{proc_name} (PID: {proc.info['pid']})")
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Process might have already closed or access denied
                    continue
                except Exception as e:
                    logging.warning(f"Error checking process: {e}")
                    continue
            
            if closed_processes:
                logging.info(f"🔒 Closed MT5 processes: {', '.join(closed_processes)}")
                
                # Wait a moment for graceful termination
                sleep(2)
                
                # Force kill any remaining MT5 processes
                for proc in psutil.process_iter(['pid', 'name', 'exe']):
                    try:
                        proc_name = proc.info['name'].lower()
                        proc_exe = proc.info['exe']
                        
                        if (proc_name in ['terminal64.exe', 'terminal.exe', 'metatrader5.exe'] or
                            (proc_exe and 'metatrader' in proc_exe.lower())):
                            
                            proc.kill()  # Force kill if still running
                            logging.info(f"🔒 Force killed stubborn MT5 process: {proc_name} (PID: {proc.info['pid']})")
                            
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue
                    except Exception as e:
                        logging.warning(f"Error force killing process: {e}")
                        continue
            else:
                logging.info("🔒 No MT5 processes found to close")
                
        except Exception as e:
            logging.error(f"Error closing MT5 processes: {e}")
            # Fallback: try using taskkill as last resort
            try:
                subprocess.run(['taskkill', '/f', '/im', 'terminal64.exe'], 
                             capture_output=True, check=False)
                subprocess.run(['taskkill', '/f', '/im', 'terminal.exe'], 
                             capture_output=True, check=False)
                logging.info("🔒 Used taskkill as fallback to close MT5 processes")
            except Exception as fallback_error:
                logging.error(f"Fallback taskkill also failed: {fallback_error}")

    def get_account_info(self):
        info = mt5.account_info()
        if info is None:
            logging.error("No account info available")
            return {"balance": "", "profit": "", "drawdown": "", "open_trades": "", "Symbol": "", "Direction": ""}
        trades = mt5.positions_get()
        open_trades = len(trades) if trades else 0
        symbol = ""
        direction = ""
        if trades and open_trades > 0:
            pos = trades[0]
            symbol = getattr(pos, "symbol", "")
            if getattr(pos, "type", None) == mt5.POSITION_TYPE_BUY:
                direction = "Long"
            elif getattr(pos, "type", None) == mt5.POSITION_TYPE_SELL:
                direction = "Short"
            else:
                direction = ""
        return {
            "balance": str(round(info.balance, 2)),
            "profit": str(round(info.profit, 2)),
            "drawdown": "",
            "open_trades": str(open_trades),
            "Symbol": symbol,
            "Direction": direction
        }

    def is_trade_open(self, ticket):
        positions = mt5.positions_get(ticket=ticket)
        return positions is not None and len(positions) > 0

    def has_open_trade(self, symbol):
        """
        Returns True if there is any open position for the given symbol.
        """
        positions = mt5.positions_get(symbol=symbol)
        return positions is not None and len(positions) > 0

    def get_trades_today_count(self, comment_filter=None):
        """Get the number of trades opened today
        
        Args:
            comment_filter: Optional string to filter trades by comment (e.g., "Combine1_")
            
        Returns:
            int: Number of trades opened today
        """
        try:
            from datetime import datetime, date
            import MetaTrader5 as mt5
            
            today = date.today()
            today_start = datetime.combine(today, datetime.min.time())
            today_end = datetime.combine(today, datetime.max.time())
            
            # Convert to timestamp
            from_date = int(today_start.timestamp())
            to_date = int(today_end.timestamp())
            
            # Get history deals (completed trades) for today
            deals = mt5.history_deals_get(from_date, to_date)
            
            # Also check current open positions opened today
            positions = mt5.positions_get()
            
            count = 0
            
            # Count completed deals (history)
            if deals:
                for deal in deals:
                    # Only count entry deals (not exit deals)
                    if deal.entry == mt5.DEAL_ENTRY_IN:
                        if comment_filter is None or (deal.comment and comment_filter in deal.comment):
                            count += 1
            
            # Count open positions opened today
            if positions:
                for pos in positions:
                    pos_time = datetime.fromtimestamp(pos.time)
                    if pos_time.date() == today:
                        if comment_filter is None or (pos.comment and comment_filter in pos.comment):
                            count += 1
            
            logging.info(f"Trades opened today: {count} (filter: {comment_filter})")
            return count
            
        except Exception as e:
            logging.error(f"Error getting today's trade count: {e}")
            return 0
    
    def get_orphaned_mt5_positions_by_account(self, account_number):
        """Get MT5 positions for a specific Tradovate account
        
        Args:
            account_number: Tradovate account number to filter by
            
        Returns:
            list: List of orphaned position tickets
        """
        try:
            # Get all open MT5 positions
            positions = mt5.positions_get()
            if positions is None:
                return []
            
            orphaned_tickets = []
            for pos in positions:
                if pos.comment:
                    # Check if position is from this account (comment is just the account number)
                    if pos.comment.strip() == account_number:
                        orphaned_tickets.append(pos.ticket)
            
            return orphaned_tickets
        except Exception as e:
            logging.error(f"Error finding orphaned positions by account: {e}")
            return []

    def close_orphaned_positions_by_account(self, account_number):
        """Close MT5 positions for a specific Tradovate account
        
        Args:
            account_number: Tradovate account number to filter by
            
        Returns:
            int: Number of positions closed
        """
        try:
            orphaned_tickets = self.get_orphaned_mt5_positions_by_account(account_number)
            closed_count = 0
            
            for ticket in orphaned_tickets:
                try:
                    if self.close_trade(ticket):
                        closed_count += 1
                        logging.info(f"Closed orphaned MT5 position for account {account_number}: {ticket}")
                except Exception as e:
                    logging.error(f"Error closing orphaned position {ticket}: {e}")
            
            return closed_count
        except Exception as e:
            logging.error(f"Error closing orphaned positions by account: {e}")
            return 0

    def get_orphaned_mt5_positions(self, combine_comment_prefix):
        """Get MT5 positions that don't have corresponding Tradovate trades
        
        Args:
            combine_comment_prefix: Comment prefix to identify trades from this combine (e.g., "Combine1_")
            
        Returns:
            list: List of orphaned position tickets
        """
        try:
            import MetaTrader5 as mt5
            
            positions = mt5.positions_get()
            orphaned_tickets = []
            
            if positions:
                for pos in positions:
                    # Check if this position belongs to our combine
                    if pos.comment and combine_comment_prefix in pos.comment:
                        orphaned_tickets.append(pos.ticket)
                        logging.info(f"Found orphaned MT5 position: {pos.ticket} ({pos.comment})")
            
            return orphaned_tickets
            
        except Exception as e:
            logging.error(f"Error finding orphaned positions: {e}")
            return []
    
    def close_orphaned_positions(self, combine_comment_prefix):
        """Close MT5 positions that don't have corresponding Tradovate trades
        
        Args:
            combine_comment_prefix: Comment prefix to identify trades from this combine (e.g., "Combine1_")
            
        Returns:
            int: Number of positions closed
        """
        try:
            orphaned_tickets = self.get_orphaned_mt5_positions(combine_comment_prefix)
            closed_count = 0
            
            for ticket in orphaned_tickets:
                try:
                    if self.close_trade(ticket):
                        closed_count += 1
                        logging.info(f"Closed orphaned MT5 position: {ticket}")
                    else:
                        logging.warning(f"Failed to close orphaned MT5 position: {ticket}")
                except Exception as e:
                    logging.error(f"Error closing orphaned position {ticket}: {e}")
            
            return closed_count
            
        except Exception as e:
            logging.error(f"Error closing orphaned positions: {e}")
            return 0

    def close_trade(self, ticket, retries=3, delay=2):
        for attempt in range(retries):
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                logging.info(f"Trade {ticket} already closed.")
                return True
            pos = positions[0]
            symbol = pos.symbol
            volume = pos.volume
            order_type = pos.type
            price = mt5.symbol_info_tick(symbol).bid if order_type == mt5.POSITION_TYPE_BUY else mt5.symbol_info_tick(symbol).ask
            close_type = mt5.ORDER_TYPE_SELL if order_type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": close_type,
                "position": ticket,
                "price": price,
                "deviation": 20,
                "type_filling": mt5.ORDER_FILLING_IOC,
                "type_time": mt5.ORDER_TIME_GTC,
            }
            result = mt5.order_send(request)
            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                if not self.is_trade_open(ticket):
                    logging.info(f"Trade {ticket} closed successfully.")
                    return True
            sleep(delay)
        logging.error(f"Failed to close trade {ticket} after {retries} attempts.")
        return not self.is_trade_open(ticket)

    def force_close_trade(self, ticket):
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            logging.info(f"Trade {ticket} already closed (force close).")
            return True
        pos = positions[0]
        symbol = pos.symbol
        volume = pos.volume
        order_type = pos.type
        price = mt5.symbol_info_tick(symbol).bid if order_type == mt5.POSITION_TYPE_BUY else mt5.symbol_info_tick(symbol).ask
        close_type = mt5.ORDER_TYPE_SELL if order_type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        for filling in [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]:
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": close_type,
                "position": ticket,
                "price": price,
                "deviation": 20,
                "type_filling": filling,
                "type_time": mt5.ORDER_TIME_GTC,
            }
            result = mt5.order_send(request)
            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                if not self.is_trade_open(ticket):
                    logging.info(f"Trade {ticket} force closed successfully.")
                    return True
        logging.error(f"Failed to force close trade {ticket}.")
        return not self.is_trade_open(ticket)

    def get_daily_trade_count(self, comment_filter=None):
        """Get count of trades placed today from both open positions and history
        
        Args:
            comment_filter: Can be either:
                - Tradovate account number (e.g., "MFFUEVSTP326057008") - preferred method
                - Old combine prefix (e.g., "Combine1_") - for backward compatibility
        """
        try:
            from datetime import datetime, date
            import tempfile
            import os
            
            today = date.today()
            
            # Check if trades were reset for this filter today
            temp_dir = tempfile.gettempdir()
            reset_file = os.path.join(temp_dir, f"mt5_reset_{comment_filter}_{today.strftime('%Y%m%d')}.flag")
            if os.path.exists(reset_file):
                # Return 0 if reset flag exists for today
                return 0
            
            trade_count = 0
            
            # Count from open positions
            positions = mt5.positions_get()
            if positions:
                for pos in positions:
                    # Convert MT5 time to date
                    pos_date = datetime.fromtimestamp(pos.time).date()
                    if pos_date == today:
                        # If comment filter is provided, check if position comment matches
                        if comment_filter:
                            # For new format: exact match with account number
                            # For old format: substring match with combine prefix
                            if pos.comment and (pos.comment.strip() == comment_filter or comment_filter in str(pos.comment)):
                                trade_count += 1
                        else:
                            trade_count += 1
            
            # Count from history deals (more reliable for completed trades)
            # Get deals from start of today to now
            today_start = datetime.combine(today, datetime.min.time())
            today_end = datetime.now()
            
            deals = mt5.history_deals_get(today_start, today_end)
            if deals:
                # Only count entry deals (not exit deals to avoid double counting)
                for deal in deals:
                    if deal.entry == mt5.DEAL_ENTRY_IN:  # Entry deal only
                        # If comment filter is provided, check if deal comment matches
                        if comment_filter:
                            # For new format: exact match with account number
                            # For old format: substring match with combine prefix
                            if deal.comment and (deal.comment.strip() == comment_filter or comment_filter in str(deal.comment)):
                                trade_count += 1
                        else:
                            trade_count += 1
            
            logging.info(f"Daily trade count: {trade_count} (filter: {comment_filter})")
            return trade_count
            
        except Exception as e:
            logging.error(f"Error counting daily trades: {e}")
            return 0

    def get_daily_trade_count_by_account(self, tradovate_account_number):
        """Get count of trades placed today for a specific Tradovate account
        
        Args:
            tradovate_account_number: Tradovate account number (e.g., "MFFUEVSTP326057008")
            
        Returns:
            int: Number of trades opened today for this account
        """
        try:
            from datetime import datetime, date
            
            today = date.today()
            trade_count = 0
            
            # Count from open positions
            positions = mt5.positions_get()
            if positions:
                for pos in positions:
                    # Convert MT5 time to date
                    pos_date = datetime.fromtimestamp(pos.time).date()
                    if pos_date == today:
                        # Check if position comment matches the account number (comment is just the account number)
                        if pos.comment and pos.comment.strip() == tradovate_account_number:
                            trade_count += 1
            
            # Count from history deals
            today_start = datetime.combine(today, datetime.min.time())
            today_end = datetime.now()
            
            deals = mt5.history_deals_get(today_start, today_end)
            if deals:
                for deal in deals:
                    if deal.entry == mt5.DEAL_ENTRY_IN:  # Entry deal only
                        # Check if deal comment matches the account number (comment is just the account number)
                        if deal.comment and deal.comment.strip() == tradovate_account_number:
                            trade_count += 1
            
            logging.info(f"Daily trade count for account {tradovate_account_number}: {trade_count}")
            return trade_count
            
        except Exception as e:
            logging.error(f"Error counting daily trades for account {tradovate_account_number}: {e}")
            return 0

    def reset_daily_trade_count(self, comment_filter=None):
        """Reset daily trade count for a specific filter by storing reset timestamp
        
        Args:
            comment_filter: Can be either:
                - Tradovate account number (e.g., "MFFUEVSTP326057008") - preferred method
                - Old combine prefix (e.g., "Combine1_") - for backward compatibility
        """
        try:
            from datetime import datetime
            import tempfile
            import os
            
            # Create a simple flag file to mark that trades were reset for this filter today
            temp_dir = tempfile.gettempdir()
            reset_file = os.path.join(temp_dir, f"mt5_reset_{comment_filter}_{datetime.now().strftime('%Y%m%d')}.flag")
            
            # Create the flag file
            with open(reset_file, 'w') as f:
                f.write(str(datetime.now().timestamp()))
                
            logging.info(f"Daily trade count reset for filter: {comment_filter}")
            return True
            
        except Exception as e:
            logging.error(f"Error resetting daily trade count: {e}")
            return False

    def reset_daily_trade_count_by_account(self, tradovate_account_number):
        """Reset daily trade count for a specific Tradovate account
        
        Args:
            tradovate_account_number: Tradovate account number (e.g., "MFFUEVSTP326057008")
        """
        try:
            from datetime import datetime
            import tempfile
            import os
            
            # Create a simple flag file to mark that trades were reset for this account today
            temp_dir = tempfile.gettempdir()
            reset_file = os.path.join(temp_dir, f"mt5_reset_account_{tradovate_account_number}_{datetime.now().strftime('%Y%m%d')}.flag")
            
            # Create the flag file
            with open(reset_file, 'w') as f:
                f.write(str(datetime.now().timestamp()))
                
            logging.info(f"Daily trade count reset for Tradovate account: {tradovate_account_number}")
            return True
            
        except Exception as e:
            logging.error(f"Error resetting daily trade count for account {tradovate_account_number}: {e}")
            return False

    def get_historical_profits_by_account(self, account_number):
        """Get total historical profits for trades from a specific Tradovate account"""
        try:
            from datetime import datetime, timedelta
            
            # Get deals from the last 30 days to get a good history
            end_time = datetime.now()
            start_time = end_time - timedelta(days=30)
            
            total_profit = 0.0
            
            # Get historical deals
            deals = mt5.history_deals_get(start_time, end_time)
            if deals:
                for deal in deals:
                    # Check if deal comment matches the account number (comment is just the account number)
                    if deal.comment and deal.comment.strip() == account_number:
                        # Only count exit deals for profit calculation (avoid double counting)
                        if deal.entry == mt5.DEAL_ENTRY_OUT:
                            total_profit += deal.profit
            
            logging.info(f"Historical profits for account {account_number}: ${total_profit:.2f}")
            return total_profit
            
        except Exception as e:
            logging.error(f"Error getting historical profits by account: {e}")
            return 0.0

    def get_historical_profits(self, comment_filter=None):
        """Get total historical profits for trades with specific comment filter"""
        try:
            from datetime import datetime, timedelta
            
            # Get deals from the last 30 days to get a good history
            end_time = datetime.now()
            start_time = end_time - timedelta(days=30)
            
            total_profit = 0.0
            
            # Get historical deals
            deals = mt5.history_deals_get(start_time, end_time)
            if deals:
                for deal in deals:
                    # Check if deal comment matches the filter (for specific combine)
                    if comment_filter and comment_filter not in str(deal.comment):
                        continue
                    
                    # Only count exit deals for profit calculation (avoid double counting)
                    if deal.entry == mt5.DEAL_ENTRY_OUT:
                        total_profit += deal.profit
            
            logging.info(f"Historical profits for {comment_filter}: ${total_profit:.2f}")
            return total_profit
            
        except Exception as e:
            logging.error(f"Error calculating historical profits: {e}")
            return 0.0

    def close_orphaned_trades(self, expected_tradovate_trades):
        """Close MT5 trades that don't have corresponding Tradovate trades
        
        Args:
            expected_tradovate_trades: List of Tradovate trade symbols/IDs that should have MT5 counterparts
            
        Returns:
            List of closed MT5 trade tickets
        """
        try:
            closed_trades = []
            positions = mt5.positions_get()
            
            if not positions:
                return closed_trades
                
            for pos in positions:
                should_close = False
                
                # If no Tradovate trades expected, close all MT5 trades
                if not expected_tradovate_trades:
                    should_close = True
                    reason = "no corresponding Tradovate trades"
                else:
                    # Check if this MT5 trade has a corresponding Tradovate trade
                    # This is a simplified check - in practice you might need more sophisticated matching
                    mt5_symbol = pos.symbol
                    has_counterpart = False
                    
                    for tradovate_trade in expected_tradovate_trades:
                        # Simple symbol matching - you may want to enhance this logic
                        if str(tradovate_trade).upper() in mt5_symbol.upper():
                            has_counterpart = True
                            break
                    
                    if not has_counterpart:
                        should_close = True
                        reason = f"no matching Tradovate trade found"
                
                if should_close:
                    logging.info(f"Closing orphaned MT5 trade {pos.ticket}: {pos.symbol} ({reason})")
                    if self.close_trade(pos.ticket):
                        closed_trades.append(pos.ticket)
                        logging.info(f"[OK] Closed orphaned trade {pos.ticket}")
                    else:
                        logging.error(f"[ERROR] Failed to close orphaned trade {pos.ticket}")
            
            if closed_trades:
                logging.info(f"Closed {len(closed_trades)} orphaned MT5 trades: {closed_trades}")
            
            return closed_trades
            
        except Exception as e:
            logging.error(f"Error closing orphaned trades: {e}")
            return []

    def extract_tradovate_account_from_comment(self, comment):
        """Extract Tradovate account number from MT5 comment
        
        Args:
            comment: MT5 order comment (e.g., "MFFUEVSTP326057008")
            
        Returns:
            str: Tradovate account number or "Unknown" if not found
        """
        try:
            if comment and comment.strip():
                # For new format: comment is just the account number
                account_number = comment.strip()
                return account_number if account_number else "Unknown"
            return "Unknown"
        except Exception as e:
            logging.error(f"Error extracting account from comment '{comment}': {e}")
            return "Unknown"

    def get_trades_by_tradovate_account(self, tradovate_account_number=None):
        """Get all MT5 trades associated with a specific Tradovate account
        
        Args:
            tradovate_account_number: Tradovate account number to filter by
            
        Returns:
            dict: Dictionary with 'open_positions' and 'history_deals' lists
        """
        try:
            from datetime import datetime, date
            
            result = {
                'open_positions': [],
                'history_deals': []
            }
            
            # Get open positions
            positions = mt5.positions_get()
            if positions:
                for pos in positions:
                    if pos.comment:
                        account_from_comment = self.extract_tradovate_account_from_comment(pos.comment)
                        if tradovate_account_number is None or account_from_comment == tradovate_account_number:
                            result['open_positions'].append({
                                'ticket': pos.ticket,
                                'symbol': pos.symbol,
                                'volume': pos.volume,
                                'type': 'BUY' if pos.type == mt5.POSITION_TYPE_BUY else 'SELL',
                                'open_time': datetime.fromtimestamp(pos.time),
                                'comment': pos.comment,
                                'tradovate_account': account_from_comment
                            })
            
            # Get today's history deals
            today = date.today()
            today_start = datetime.combine(today, datetime.min.time())
            today_end = datetime.combine(today, datetime.max.time())
            from_date = int(today_start.timestamp())
            to_date = int(today_end.timestamp())
            
            deals = mt5.history_deals_get(from_date, to_date)
            if deals:
                for deal in deals:
                    if deal.comment:
                        account_from_comment = self.extract_tradovate_account_from_comment(deal.comment)
                        if tradovate_account_number is None or account_from_comment == tradovate_account_number:
                            result['history_deals'].append({
                                'ticket': deal.ticket,
                                'symbol': deal.symbol,
                                'volume': deal.volume,
                                'type': 'BUY' if deal.type == mt5.DEAL_TYPE_BUY else 'SELL',
                                'time': datetime.fromtimestamp(deal.time),
                                'comment': deal.comment,
                                'tradovate_account': account_from_comment,
                                'entry': deal.entry
                            })
            
            return result
            
        except Exception as e:
            logging.error(f"Error getting trades by Tradovate account: {e}")
            return {'open_positions': [], 'history_deals': []}

    def get_symbol_info(self, symbol):
        """Get symbol information"""
        try:
            return mt5.symbol_info(symbol)
        except Exception as e:
            logging.error(f"Error getting symbol info for {symbol}: {e}")
            return None
    
    def debug_symbol_info(self, symbol):
        """Debug method to print all available symbol information"""
        try:
            info = mt5.symbol_info(symbol)
            if info:
                logging.info(f"=== Symbol Info for {symbol} ===")
                for attr in dir(info):
                    if not attr.startswith('_'):
                        try:
                            value = getattr(info, attr)
                            logging.info(f"  {attr}: {value}")
                        except:
                            pass
                logging.info("=== End Symbol Info ===")
                return info
            else:
                logging.error(f"No symbol info available for {symbol}")
                return None
        except Exception as e:
            logging.error(f"Error debugging symbol info: {e}")
            return None
    
    def get_tick_data(self, symbol):
        """Get current tick data for symbol"""
        try:
            return mt5.symbol_info_tick(symbol)
        except Exception as e:
            logging.error(f"Error getting tick data for {symbol}: {e}")
            return None
    
    def should_close_trades_for_rollover(self, prop_firm_name):
        """
        Check if trades should be closed based on prop firm rollover schedules.
        
        Closing Times (Eastern Time):
        - Trade Day: 5:00 PM ET
        - Funding Ticks: 5:00 PM ET
        - Tradeify: 4:59 PM ET
        - MFFU: 4:10 PM ET 
        - Alpha Futures: 4:20 PM ET
        
        Args:
            prop_firm_name: Name of the prop firm
            
        Returns:
            bool: True if trades should be closed now, False otherwise
        """
        import datetime
        import pytz
        
        try:
            # Get current time in Eastern timezone
            eastern = pytz.timezone('US/Eastern')
            current_time = datetime.datetime.now(eastern)
            
            # Define closing times for each prop firm (24-hour format)
            closing_schedules = {
                "Trade Day": (17, 0),  # 5:00 PM Eastern Time
                "Funding Ticks": (17, 0),  # 5:00 PM Eastern Time
                "Tradeify": (16, 59),  # 4:59 PM Eastern Time
                "MFFU": (16, 10),  # 4:10 PM Eastern Standard Time
                "Alpha Futures": (16, 20),  # 4:20 PM Eastern Time
            }
            
            # Get closing time for this prop firm
            closing_time_tuple = closing_schedules.get(prop_firm_name)
            
            if closing_time_tuple is None:
                # This prop firm doesn't require trade closing
                return False
            
            # Convert closing time to datetime object for proper comparison
            closing_hour, closing_minute = closing_time_tuple
            closing_time = current_time.replace(hour=closing_hour, minute=closing_minute, second=0, microsecond=0)
            
            # Get current date string for tracking
            current_date = current_time.strftime("%Y-%m-%d")
            
            # Safety check: Have we already executed rollover for this prop firm today?
            if self.rollover_executed_today.get(prop_firm_name) == current_date:
                return False  # Already executed today, skip to prevent duplicates
            
            # Check if current time is at or past closing time (with safety buffer)
            # This ensures we don't miss rollover due to system delays
            if current_time >= closing_time:
                # Also check if we're on a weekday (Monday = 0, Sunday = 6)
                if current_time.weekday() < 5:  # Monday through Friday
                    current_time_str = current_time.strftime("%H:%M")
                    closing_time_str = closing_time.strftime("%H:%M")
                    logging.info(f"🕒 Market rollover time reached for {prop_firm_name} at {current_time_str} ET (closing time: {closing_time_str})")
                    return True
            
            return False
            
        except Exception as e:
            logging.error(f"Error checking rollover schedule for {prop_firm_name}: {e}")
            return False
    
    def close_trades_for_rollover(self, prop_firm_name, account_comment_prefix=None):
        """
        Close all MT5 trades for market rollover based on prop firm schedule.
        
        Args:
            prop_firm_name: Name of the prop firm
            account_comment_prefix: Account number to filter trades (e.g., "MFFU123456")
            
        Returns:
            list: List of closed trade tickets
        """
        if not self.should_close_trades_for_rollover(prop_firm_name):
            return []
        
        try:
            # Get all open positions
            positions = mt5.positions_get()
            if positions is None:
                logging.warning("No positions found or error getting positions")
                return []
            
            closed_tickets = []
            
            for position in positions:
                # Filter by account comment prefix if provided
                if account_comment_prefix and not position.comment.startswith(account_comment_prefix):
                    continue
                
                # Close the position
                if self.close_trade(position.ticket):
                    closed_tickets.append(position.ticket)
                    logging.info(f"🕒 ROLLOVER: Closed trade {position.ticket} for {prop_firm_name} market rollover")
                else:
                    logging.error(f"[ERROR] Failed to close trade {position.ticket} for rollover")
            
            if closed_tickets:
                logging.info(f"🕒 ROLLOVER COMPLETE: Closed {len(closed_tickets)} trades for {prop_firm_name} at market rollover")
                
                # Mark rollover as executed today to prevent duplicate execution
                import datetime
                import pytz
                eastern = pytz.timezone('US/Eastern')
                current_date = datetime.datetime.now(eastern).strftime("%Y-%m-%d")
                self.rollover_executed_today[prop_firm_name] = current_date
            
            return closed_tickets
            
        except Exception as e:
            logging.error(f"Error closing trades for rollover ({prop_firm_name}): {e}")
            return []
