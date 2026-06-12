# Chapter 7 — The trading engine

_Exported from CODEBASE_REFERENCE.pdf as plain Markdown. Paste this into another Claude conversation, Notion, or any Markdown viewer._

Now we wire the signals and the MT5 connector together. `mt5_trading.py` sends orders and reads positions; `mt5_comment_parser.py` tags those orders with structured strategy metadata; `trade_limit_manager.py` enforces the daily loss/position-size guardrails; and `hedge_protector.py` opens offsetting positions on a hedge account so that drawdown on the funded leg is bounded. This is the heart of the system.

**Files in this chapter:**

- `trader_companion/mt5_trading.py`
- `trader_companion/mt5_comment_parser.py`
- `trader_companion/trade_limit_manager.py`
- `trader_companion/hedge_protector.py`

---

### `trader_companion/mt5_trading.py`

_2561 loc · 1 classes · 2 functions · 12 imports_

**Imports**

```python
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
```

**Classes**

#### `class MT5API`

```python
_symbol_cache = {}
_symbol_cache_timestamp = {}
_cache_ttl = 300
```

```python
class MT5API:
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
        
        # After successful connection, detect and store the connected symbol
        try:
            # Try to get the current symbol from the market watch or from a symbol list
            # First try to get symbols from the market watch
            symbols = mt5.symbols_get()
            if symbols and len(symbols) > 0:
                # Use the first available symbol from market watch as the connected symbol
                self.connected_symbol = symbols[0].name
                logging.info(f"Connected symbol detected: {self.connected_symbol}")
                
                # Try to select this symbol to ensure it's available
                if not mt5.symbol_select(self.connected_symbol, True):
                    logging.warning(f"Could not select detected symbol: {self.connected_symbol}")
                    # Try to find an alternative symbol
                    for symbol in symbols[:5]:  # Try first 5 symbols
                        if mt5.symbol_select(symbol.name, True):
                            self.connected_symbol = symbol.name
                            logging.info(f"Alternative connected symbol selected: {self.connected_symbol}")
                            break
            else:
                # Fallback: try common symbol names if no symbols available
                common_symbols = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD"]
                for symbol in common_symbols:
                    if mt5.symbol_select(symbol, True):
                        self.connected_symbol = symbol
                        logging.info(f"Fallback connected symbol selected: {self.connected_symbol}")
                        break
                        
        except Exception as e:
            logging.warning(f"Could not detect connected symbol: {e}")
            # If detection fails, use the configured symbol if available
            if self.symbol:
                self.connected_symbol = self.symbol
            
        return authorized

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
                # `trade_allowed` is the AutoTrading toggle in the MT5 GUI.
                # Reconnecting won't fix this — the user must enable it.
                return False, (
                    "MT5 AutoTrading is OFF — press Ctrl+E in the MT5 "
                    "terminal (or click the 'AutoTrading' button in the "
                    "top toolbar) to enable. Also verify Tools → Options "
                    "→ Expert Advisors → 'Allow algorithmic trading' is "
                    "checked, and that you are not signed in with the "
                    "investor (read-only) password."
                )

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
                # `trade_allowed` is the AutoTrading toggle in the MT5 GUI.
                # Reconnecting won't fix this — the user must enable it.
                return False, (
                    "MT5 AutoTrading is OFF — press Ctrl+E in the MT5 "
                    "terminal (or click the 'AutoTrading' button in the "
                    "top toolbar) to enable. Also verify Tools → Options "
                    "→ Expert Advisors → 'Allow algorithmic trading' is "
                    "checked, and that you are not signed in with the "
                    "investor (read-only) password."
                )

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
        # EXCEPTION: For XAUUSD (Gold), use the actual point value (usually 0.01) as the blueprint points 
        # are calibrated for standard ticks (e.g. 1710 points = $17.10 price movement)
        if any(x in symbol.upper() for x in ['XAU', 'GOLD', 'GC']):
            point_value = point
            logging.info(f"Gold symbol detected ({symbol}), using actual point value: {point_value}")
        else:
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

            # Normalize volume to meet symbol requirements (step size, min, max)
            sym_info = mt5.symbol_info(corrected_symbol)
            if sym_info:
                step_vol = sym_info.volume_step
                min_vol = sym_info.volume_min
                max_vol = sym_info.volume_max
                
                if step_vol > 0:
                    # Round to nearest multiple of step_vol
                    volume = round(volume / step_vol) * step_vol
                    
                    # Fix floating point precision
                    try:
                        step_str = f"{step_vol:.10f}".rstrip('0').rstrip('.')
                        decimals = 0
                        if "." in step_str:
                            decimals = len(step_str.split(".")[1])
                        volume = round(volume, decimals)
                    except Exception:
                        volume = round(volume, 2)
                
                if min_vol > 0 and volume < min_vol:
                    logging.warning(f"Volume {volume} < min {min_vol}, clamped to min")
                    volume = min_vol
                elif max_vol > 0 and volume > max_vol:
                    logging.warning(f"Volume {volume} > max {max_vol}, clamped to max")
                    volume = max_vol
                
                logging.info(f"Normalized volume: {volume} (Step: {step_vol}, Min: {min_vol})")
            
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
                
                # Add comment if provided.  MT5's MqlTradeRequest.comment
                # is a 32-byte char[] — 31 usable chars.  Any longer
                # value makes order_send return None with last_error
                # (-2, 'Invalid "comment" argument').  Cap defensively so
                # a caller passing a long comment doesn't silently fail.
                if comment:
                    request["comment"] = str(comment)[:31]
                
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
                
                # Add comment if provided.  MT5's MqlTradeRequest.comment
                # is a 32-byte char[] — 31 usable chars.  Any longer
                # value makes order_send return None with last_error
                # (-2, 'Invalid "comment" argument').  Cap defensively so
                # a caller passing a long comment doesn't silently fail.
                if comment:
                    request["comment"] = str(comment)[:31]
                
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
                    # mt5.order_send returned None — the request never reached
                    # the broker.  mt5.last_error() carries the real reason
                    # (code + message).  Without surfacing it, every failure
                    # looks identical and we can't tell AutoTrading-OFF from
                    # an investor-password lockout from a session-closed
                    # state.
                    try:
                        err = mt5.last_error()
                    except Exception:
                        err = None
                    if err and isinstance(err, tuple) and len(err) >= 2:
                        err_code, err_msg = err[0], err[1]
                    elif err:
                        err_code, err_msg = err, ""
                    else:
                        err_code, err_msg = None, ""
                    last_error = (
                        f"order_send returned None — MT5 last_error="
                        f"({err_code}, {err_msg!r})"
                    )
                    print(f"[ERROR] MT5 CRITICAL: order_send returned None")
                    print(
                        f"   mt5.last_error() = ({err_code}, {err_msg!r})"
                    )
                    # Hint at the common cause for each known last_error code.
                    if err_code in (-10004, -10003, 4754):
                        # AutoTrading toggle / read-only / not authorized
                        print(
                            "[TOOL] SOLUTION: enable AutoTrading in the "
                            "MT5 terminal (Ctrl+E), confirm Tools → Options "
                            "→ Expert Advisors → 'Allow algorithmic trading' "
                            "is checked, and verify you are not logged in "
                            "with the investor (read-only) password."
                        )
                    elif err_code in (-10005, 4756):
                        # Trade server connection dropped
                        print(
                            "[TOOL] SOLUTION: MT5 trade-server connection "
                            "looks dropped — bottom-right corner of the "
                            "terminal should say 'connected', not "
                            "'no connection'.  Reconnect there, then retry."
                        )
                    else:
                        print(
                            "[TOOL] SOLUTION: ticks worked but order_send "
                            "did not — most often this is AutoTrading being "
                            "OFF (press Ctrl+E in MT5), an investor "
                            "(read-only) login, the broker session being "
                            "closed for this symbol, or two MT5 installs "
                            "where the wrong one received the initialize() "
                            "call.  Check mt5.last_error() code above for "
                            "the precise cause."
                        )
                    
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
                    # Check if position is from this account (comment starts with account number, may have phase suffix)
                    if pos.comment.strip().startswith(account_number):
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
                        # Check if position comment matches the account number (comment starts with account number, may have phase suffix)
                        if pos.comment and pos.comment.strip().startswith(tradovate_account_number):
                            trade_count += 1
            
            # Count from history deals
            today_start = datetime.combine(today, datetime.min.time())
            today_end = datetime.now()
            
            deals = mt5.history_deals_get(today_start, today_end)
            if deals:
                for deal in deals:
                    if deal.entry == mt5.DEAL_ENTRY_IN:  # Entry deal only
                        # Check if deal comment matches the account number (comment starts with account number, may have phase suffix)
                        if deal.comment and deal.comment.strip().startswith(tradovate_account_number):
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
                    # Check if deal comment matches the account number (comment starts with account number, may have phase suffix)
                    if deal.comment and deal.comment.strip().startswith(account_number):
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
            comment: MT5 order comment (e.g., "MFFUEVSTP326057008_CH1" or "ACCOUNT_FA")
            
        Returns:
            str: Tradovate account number or "Unknown" if not found
        """
        try:
            if comment and comment.strip():
                import re
                # For new format: comment is account number + optional phase suffix
                # Strip the phase suffix if present
                account_number = comment.strip()
                # Remove phase abbreviation suffix if present
                if '_' in account_number:
                    # Check for numbered formats (_CH1-4, _FD1-4, _DD1-4)
                    if re.search(r'_(CH|FD|DD)\d+$', account_number):
                        account_number = re.sub(r'_(CH|FD|DD)\d+$', '', account_number)
                    # Check for simple farming format: _FA
                    elif account_number.endswith('_FA'):
                        account_number = account_number[:-3]
                    # Check for unknown phase marker
                    elif account_number.endswith('_UNK'):
                        account_number = account_number[:-4]
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
```

##### `MT5API.__init__`

```python
def __init__(self, login, password, server, symbol=None, terminal_path=None)
```
**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.
2. Assigns <code>self.password</code> = <code>str(password) if password else ''</code>.
3. Assigns <code>self.server</code> = <code>str(server) if server else ''</code>.
4. Assigns <code>self.symbol</code> = <code>symbol</code>.
5. Assigns <code>self.terminal_path</code> = <code>terminal_path</code>.
6. Assigns <code>self.sl_points</code> = <code>float(os.getenv('MT5_SL_POINTS') or os.getenv('MT5_STOPLO...</code>.
7. Assigns <code>self.tp_points</code> = <code>float(os.getenv('MT5_TP_POINTS') or os.getenv('MT5_TAKEPR...</code>.
8. Assigns <code>self.default_volume</code> = <code>float(os.getenv('MT5_VOLUME', '1'))</code>.
9. Assigns <code>self.rollover_executed_today</code> = <code>{}</code>.
10. Assigns <code>self.connected_symbol</code> = <code>None</code>.
11. Assigns <code>self.is_plexy_server</code> = <code>'plexy' in server.lower() if server else False</code>.
12. <b>if</b> <code>self.is_plexy_server</code>: branches conditionally.
13. Assigns <code>self.connected</code> = <code>False</code>.
14. Assigns <code>self.last_error</code> = <code>None</code>.

```python
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
```

##### `MT5API._get_cached_terminal_path`

```python
def _get_cached_terminal_path(self)
```
> Get previously successful terminal path for faster connection

**What it does, step by step:**

1. Imports <code>tempfile</code> (lazy import inside the function).
2. Assigns <code>cache_file</code> = <code>os.path.join(tempfile.gettempdir(), 'mt5_terminal_cache.t...</code>.
3. <b>try</b> block with 1 <b>except</b> clause.
4. <b>return</b> <code>None</code>.

```python
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
```

##### `MT5API._cache_successful_path`

```python
def _cache_successful_path(self, path)
```
> Cache successful terminal path for future use

**What it does, step by step:**

1. Imports <code>tempfile</code> (lazy import inside the function).
2. Assigns <code>cache_file</code> = <code>os.path.join(tempfile.gettempdir(), 'mt5_terminal_cache.t...</code>.
3. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.connect`

```python
def connect(self)
```
**What it does, step by step:**

1. Assigns <code>success</code> = <code>False</code>.
2. Assigns <code>cached_path</code> = <code>self._get_cached_terminal_path()</code>.
3. <b>if</b> <code>cached_path</code>: branches conditionally.
4. <b>if</b> <code>not success</code>: branches conditionally.
5. <b>if</b> <code>not success</code>: branches conditionally.
6. <b>if</b> <code>not success</code>: branches conditionally.
7. <b>if</b> <code>not success</code>: branches conditionally.
8. Assigns <code>authorized</code> = <code>mt5.login(self.login, self.password, self.server)</code>.
9. <b>if</b> <code>not authorized</code>: branches conditionally.
10. <b>try</b> block with 1 <b>except</b> clause.
11. Assigns <code>self.connected</code> = <code>True</code>.
12. <b>return</b> <code>True</code>.
13. <b>try</b> block with 1 <b>except</b> clause.
14. <b>return</b> <code>authorized</code>.

```python
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
        
        # After successful connection, detect and store the connected symbol
        try:
            # Try to get the current symbol from the market watch or from a symbol list
            # First try to get symbols from the market watch
            symbols = mt5.symbols_get()
            if symbols and len(symbols) > 0:
                # Use the first available symbol from market watch as the connected symbol
                self.connected_symbol = symbols[0].name
                logging.info(f"Connected symbol detected: {self.connected_symbol}")
                
                # Try to select this symbol to ensure it's available
                if not mt5.symbol_select(self.connected_symbol, True):
                    logging.warning(f"Could not select detected symbol: {self.connected_symbol}")
                    # Try to find an alternative symbol
                    for symbol in symbols[:5]:  # Try first 5 symbols
                        if mt5.symbol_select(symbol.name, True):
                            self.connected_symbol = symbol.name
                            logging.info(f"Alternative connected symbol selected: {self.connected_symbol}")
                            break
            else:
                # Fallback: try common symbol names if no symbols available
                common_symbols = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD"]
                for symbol in common_symbols:
                    if mt5.symbol_select(symbol, True):
                        self.connected_symbol = symbol
                        logging.info(f"Fallback connected symbol selected: {self.connected_symbol}")
                        break
                        
        except Exception as e:
            logging.warning(f"Could not detect connected symbol: {e}")
            # If detection fails, use the configured symbol if available
            if self.symbol:
                self.connected_symbol = self.symbol
            
        return authorized
```

##### `MT5API.monitor_connection`

```python
def monitor_connection(self)
```
> Monitor MT5 connection status and attempt recovery if needed Call this periodically (e.g., every 30 seconds) during application operation

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.
2. Module/function docstring.
3. <b>try</b> block with 1 <b>except</b> clause.
4. Module/function docstring.
5. <b>for</b> <code>attempt</code> in <code>range(max_retries)</code>: iterates.
6. Calls <code>logging.error(...)</code> for its side effect.
7. <b>return</b> <code>False</code>.
8. Module/function docstring.
9. <b>try</b> block with 1 <b>except</b> clause.
10. Module/function docstring.
11. <b>try</b> block with 1 <b>except</b> clause.

```python
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
                # `trade_allowed` is the AutoTrading toggle in the MT5 GUI.
                # Reconnecting won't fix this — the user must enable it.
                return False, (
                    "MT5 AutoTrading is OFF — press Ctrl+E in the MT5 "
                    "terminal (or click the 'AutoTrading' button in the "
                    "top toolbar) to enable. Also verify Tools → Options "
                    "→ Expert Advisors → 'Allow algorithmic trading' is "
                    "checked, and that you are not signed in with the "
                    "investor (read-only) password."
                )

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
```

##### `MT5API._verify_symbol_tick_data`

```python
def _verify_symbol_tick_data(self, symbol, max_retries=3)
```
> Verify symbol has live tick data available

**What it does, step by step:**

1. <b>for</b> <code>attempt</code> in <code>range(max_retries)</code>: iterates.
2. Calls <code>logging.error(...)</code> for its side effect.
3. <b>return</b> <code>False</code>.

```python
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
```

##### `MT5API.is_autotrading_enabled`

```python
def is_autotrading_enabled(self)
```
> Check if AutoTrading is enabled in MT5 using the existing connection Returns True if autotrading is enabled, False otherwise

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.ensure_symbol`

```python
def ensure_symbol(self, symbol)
```
> Ensure symbol is available for trading, with enhanced caching and fast paths

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API._get_symbol_variations`

```python
def _get_symbol_variations(self, symbol)
```
> Get possible symbol variations for different MT5 brokers

**What it does, step by step:**

1. Assigns <code>variations</code> = <code>[symbol]</code>.
2. Assigns <code>symbol_upper</code> = <code>symbol.upper()</code>.
3. <b>if</b> <code>symbol_upper in ['USTEC', 'NASDAQ', 'NQ', 'NAS', 'USTECH100', 'USTE...</code>: branches conditionally (with an <b>else</b>/elif arm).
4. Assigns <code>seen</code> = <code>set()</code>.
5. Assigns <code>result</code> = <code>[]</code>.
6. <b>for</b> <code>variant</code> in <code>variations</code>: iterates.
7. <b>return</b> <code>result</code>.

```python
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
```

##### `MT5API._log_available_symbols`

```python
def _log_available_symbols(self, failed_symbol)
```
> Log some available symbols for debugging

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.get_connected_symbol`

```python
def get_connected_symbol(self)
```
> Get the symbol that was detected during connection

**What it does, step by step:**

1. <b>return</b> <code>self.connected_symbol</code>.

```python
def get_connected_symbol(self):
        """Get the symbol that was detected during connection"""
        return self.connected_symbol
```

##### `MT5API.get_safe_symbol`

```python
def get_safe_symbol(self, fallback_symbol=None)
```
> Get a safe symbol to use - prefers fallback (configured), then connected symbol, then configured symbol

**What it does, step by step:**

1. <b>if</b> <code>fallback_symbol</code>: branches conditionally.
2. <b>if</b> <code>self.connected_symbol</code>: branches conditionally (with an <b>else</b>/elif arm).

```python
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
```

##### `MT5API.get_supported_filling_modes`

```python
def get_supported_filling_modes(self, symbol)
```
**What it does, step by step:**

1. Assigns <code>info</code> = <code>mt5.symbol_info(symbol)</code>.
2. <b>if</b> <code>info is None</code>: branches conditionally.
3. Assigns <code>fillings</code> = <code>getattr(info, 'trade_fillings', None)</code>.
4. <b>if</b> <code>not fillings or len(fillings) == 0</code>: branches conditionally.
5. <b>return</b> <code>list(fillings)</code>.

```python
def get_supported_filling_modes(self, symbol):
        info = mt5.symbol_info(symbol)
        if info is None:
            return [mt5.ORDER_FILLING_IOC]
        fillings = getattr(info, "trade_fillings", None)
        if not fillings or len(fillings) == 0:
            return [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
        return list(fillings)
```

##### `MT5API.check_connection_health`

```python
def check_connection_health(self)
```
> Comprehensive health check for MT5 connection and trading readiness Returns (is_healthy, error_message)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
                # `trade_allowed` is the AutoTrading toggle in the MT5 GUI.
                # Reconnecting won't fix this — the user must enable it.
                return False, (
                    "MT5 AutoTrading is OFF — press Ctrl+E in the MT5 "
                    "terminal (or click the 'AutoTrading' button in the "
                    "top toolbar) to enable. Also verify Tools → Options "
                    "→ Expert Advisors → 'Allow algorithmic trading' is "
                    "checked, and that you are not signed in with the "
                    "investor (read-only) password."
                )

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
```

##### `MT5API.attempt_reconnection`

```python
def attempt_reconnection(self, max_retries=3)
```
> Attempt to reconnect to MT5 if connection is lost

**What it does, step by step:**

1. <b>for</b> <code>attempt</code> in <code>range(max_retries)</code>: iterates.
2. Calls <code>logging.error(...)</code> for its side effect.
3. <b>return</b> <code>False</code>.

```python
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
```

##### `MT5API._calculate_sl_tp_price`

```python
def _calculate_sl_tp_price(self, symbol, order_type, price, sl_points, tp_points)
```
> Calculate SL and TP prices from points - NASDAQ automation always uses 1.0 point value

**What it does, step by step:**

1. Assigns <code>sl_price</code> = <code>None</code>.
2. Assigns <code>tp_price</code> = <code>None</code>.
3. Assigns <code>symbol_info</code> = <code>mt5.symbol_info(symbol)</code>.
4. <b>if</b> <code>not symbol_info</code>: branches conditionally.
5. Assigns <code>point</code> = <code>symbol_info.point</code>.
6. <b>if</b> <code>any((x in symbol.upper() for x in ['XAU', 'GOLD', 'GC']))</code>: branches conditionally (with an <b>else</b>/elif arm).
7. <b>if</b> <code>sl_points and float(sl_points) &gt; 0</code>: branches conditionally.
8. <b>if</b> <code>tp_points and float(tp_points) &gt; 0</code>: branches conditionally.
9. <b>return</b> <code>(sl_price, tp_price)</code>.

```python
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
        # EXCEPTION: For XAUUSD (Gold), use the actual point value (usually 0.01) as the blueprint points 
        # are calibrated for standard ticks (e.g. 1710 points = $17.10 price movement)
        if any(x in symbol.upper() for x in ['XAU', 'GOLD', 'GC']):
            point_value = point
            logging.info(f"Gold symbol detected ({symbol}), using actual point value: {point_value}")
        else:
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
```

##### `MT5API.place_order`

```python
def place_order(self, symbol, order_type, volume=None, sl=None, tp=None, comment=None)
```
**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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

            # Normalize volume to meet symbol requirements (step size, min, max)
            sym_info = mt5.symbol_info(corrected_symbol)
            if sym_info:
                step_vol = sym_info.volume_step
                min_vol = sym_info.volume_min
                max_vol = sym_info.volume_max
                
                if step_vol > 0:
                    # Round to nearest multiple of step_vol
                    volume = round(volume / step_vol) * step_vol
                    
                    # Fix floating point precision
                    try:
                        step_str = f"{step_vol:.10f}".rstrip('0').rstrip('.')
                        decimals = 0
                        if "." in step_str:
                            decimals = len(step_str.split(".")[1])
                        volume = round(volume, decimals)
                    except Exception:
                        volume = round(volume, 2)
                
                if min_vol > 0 and volume < min_vol:
                    logging.warning(f"Volume {volume} < min {min_vol}, clamped to min")
                    volume = min_vol
                elif max_vol > 0 and volume > max_vol:
                    logging.warning(f"Volume {volume} > max {max_vol}, clamped to max")
                    volume = max_vol
                
                logging.info(f"Normalized volume: {volume} (Step: {step_vol}, Min: {min_vol})")
            
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
                
                # Add comment if provided.  MT5's MqlTradeRequest.comment
                # is a 32-byte char[] — 31 usable chars.  Any longer
                # value makes order_send return None with last_error
                # (-2, 'Invalid "comment" argument').  Cap defensively so
                # a caller passing a long comment doesn't silently fail.
                if comment:
                    request["comment"] = str(comment)[:31]
                
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
                
                # Add comment if provided.  MT5's MqlTradeRequest.comment
                # is a 32-byte char[] — 31 usable chars.  Any longer
                # value makes order_send return None with last_error
                # (-2, 'Invalid "comment" argument').  Cap defensively so
                # a caller passing a long comment doesn't silently fail.
                if comment:
                    request["comment"] = str(comment)[:31]
                
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
                    # mt5.order_send returned None — the request never reached
                    # the broker.  mt5.last_error() carries the real reason
                    # (code + message).  Without surfacing it, every failure
                    # looks identical and we can't tell AutoTrading-OFF from
                    # an investor-password lockout from a session-closed
                    # state.
                    try:
                        err = mt5.last_error()
                    except Exception:
                        err = None
                    if err and isinstance(err, tuple) and len(err) >= 2:
                        err_code, err_msg = err[0], err[1]
                    elif err:
                        err_code, err_msg = err, ""
                    else:
                        err_code, err_msg = None, ""
                    last_error = (
                        f"order_send returned None — MT5 last_error="
                        f"({err_code}, {err_msg!r})"
                    )
                    print(f"[ERROR] MT5 CRITICAL: order_send returned None")
                    print(
                        f"   mt5.last_error() = ({err_code}, {err_msg!r})"
                    )
                    # Hint at the common cause for each known last_error code.
                    if err_code in (-10004, -10003, 4754):
                        # AutoTrading toggle / read-only / not authorized
                        print(
                            "[TOOL] SOLUTION: enable AutoTrading in the "
                            "MT5 terminal (Ctrl+E), confirm Tools → Options "
                            "→ Expert Advisors → 'Allow algorithmic trading' "
                            "is checked, and verify you are not logged in "
                            "with the investor (read-only) password."
                        )
                    elif err_code in (-10005, 4756):
                        # Trade server connection dropped
                        print(
                            "[TOOL] SOLUTION: MT5 trade-server connection "
                            "looks dropped — bottom-right corner of the "
                            "terminal should say 'connected', not "
                            "'no connection'.  Reconnect there, then retry."
                        )
                    else:
                        print(
                            "[TOOL] SOLUTION: ticks worked but order_send "
                            "did not — most often this is AutoTrading being "
                            "OFF (press Ctrl+E in MT5), an investor "
                            "(read-only) login, the broker session being "
                            "closed for this symbol, or two MT5 installs "
                            "where the wrong one received the initialize() "
                            "call.  Check mt5.last_error() code above for "
                            "the precise cause."
                        )
                    
                logging.warning(f"Order attempt failed: {order_type} {corrected_symbol} {volume} at {price}, filling={filling_mode}, error={last_error}")
                
            logging.error(f"Order failed: {order_type} {corrected_symbol} {volume} at {price}, last_error={last_error}")
            raise Exception(f"Order failed: {last_error}")
            
        except Exception as e:
            logging.exception(f"Exception in place_order: {e}")
            raise
```

##### `MT5API.buy_market`

```python
def buy_market(self, symbol, volume=None, sl=None, tp=None, comment=None)
```
**What it does, step by step:**

1. <b>return</b> <code>self.place_order(symbol, 'buy', volume=volume, sl=sl, tp=tp, commen...</code>.

```python
def buy_market(self, symbol, volume=None, sl=None, tp=None, comment=None):
        return self.place_order(symbol, "buy", volume=volume, sl=sl, tp=tp, comment=comment)
```

##### `MT5API.sell_market`

```python
def sell_market(self, symbol, volume=None, sl=None, tp=None, comment=None)
```
**What it does, step by step:**

1. <b>return</b> <code>self.place_order(symbol, 'sell', volume=volume, sl=sl, tp=tp, comme...</code>.

```python
def sell_market(self, symbol, volume=None, sl=None, tp=None, comment=None):
        return self.place_order(symbol, "sell", volume=volume, sl=sl, tp=tp, comment=comment)
```

##### `MT5API.is_connected`

```python
def is_connected(self)
```
> Check if MT5 connection is still active

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.check_connection_and_disconnect_if_needed`

```python
def check_connection_and_disconnect_if_needed(self)
```
> Check connection and disconnect if lost

**What it does, step by step:**

1. <b>if</b> <code>not self.is_connected()</code>: branches conditionally.
2. <b>return</b> <code>True</code>.

```python
def check_connection_and_disconnect_if_needed(self):
        """Check connection and disconnect if lost"""
        if not self.is_connected():
            logging.warning("MT5 connection lost, disconnecting...")
            self.disconnect()
            return False
        return True
```

##### `MT5API.disconnect`

```python
def disconnect(self)
```
> Properly disconnect from MT5 with enhanced cleanup and terminal closure

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API._close_mt5_processes`

```python
def _close_mt5_processes(self)
```
> Force close all MT5 terminal processes

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.get_account_info`

```python
def get_account_info(self)
```
**What it does, step by step:**

1. Assigns <code>info</code> = <code>mt5.account_info()</code>.
2. <b>if</b> <code>info is None</code>: branches conditionally.
3. Assigns <code>trades</code> = <code>mt5.positions_get()</code>.
4. Assigns <code>open_trades</code> = <code>len(trades) if trades else 0</code>.
5. Assigns <code>symbol</code> = <code>''</code>.
6. Assigns <code>direction</code> = <code>''</code>.
7. <b>if</b> <code>trades and open_trades &gt; 0</code>: branches conditionally.
8. <b>return</b> <code>{'balance': str(round(info.balance, 2)), 'profit': str(round(info.p...</code>.

```python
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
```

##### `MT5API.is_trade_open`

```python
def is_trade_open(self, ticket)
```
**What it does, step by step:**

1. Assigns <code>positions</code> = <code>mt5.positions_get(ticket=ticket)</code>.
2. <b>return</b> <code>positions is not None and len(positions) &gt; 0</code>.

```python
def is_trade_open(self, ticket):
        positions = mt5.positions_get(ticket=ticket)
        return positions is not None and len(positions) > 0
```

##### `MT5API.has_open_trade`

```python
def has_open_trade(self, symbol)
```
> Returns True if there is any open position for the given symbol.

**What it does, step by step:**

1. Assigns <code>positions</code> = <code>mt5.positions_get(symbol=symbol)</code>.
2. <b>return</b> <code>positions is not None and len(positions) &gt; 0</code>.

```python
def has_open_trade(self, symbol):
        """
        Returns True if there is any open position for the given symbol.
        """
        positions = mt5.positions_get(symbol=symbol)
        return positions is not None and len(positions) > 0
```

##### `MT5API.get_trades_today_count`

```python
def get_trades_today_count(self, comment_filter=None)
```
> Get the number of trades opened today  Args:     comment_filter: Optional string to filter trades by comment (e.g., "Combine1_")      Returns:     int: Number of trades opened today

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.get_orphaned_mt5_positions_by_account`

```python
def get_orphaned_mt5_positions_by_account(self, account_number)
```
> Get MT5 positions for a specific Tradovate account  Args:     account_number: Tradovate account number to filter by      Returns:     list: List of orphaned position tickets

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
                    # Check if position is from this account (comment starts with account number, may have phase suffix)
                    if pos.comment.strip().startswith(account_number):
                        orphaned_tickets.append(pos.ticket)
            
            return orphaned_tickets
        except Exception as e:
            logging.error(f"Error finding orphaned positions by account: {e}")
            return []
```

##### `MT5API.close_orphaned_positions_by_account`

```python
def close_orphaned_positions_by_account(self, account_number)
```
> Close MT5 positions for a specific Tradovate account  Args:     account_number: Tradovate account number to filter by      Returns:     int: Number of positions closed

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.get_orphaned_mt5_positions`

```python
def get_orphaned_mt5_positions(self, combine_comment_prefix)
```
> Get MT5 positions that don't have corresponding Tradovate trades  Args:     combine_comment_prefix: Comment prefix to identify trades from this combine (e.g., "Combine1_")      Returns:     list: List of orphaned position tickets

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.close_orphaned_positions`

```python
def close_orphaned_positions(self, combine_comment_prefix)
```
> Close MT5 positions that don't have corresponding Tradovate trades  Args:     combine_comment_prefix: Comment prefix to identify trades from this combine (e.g., "Combine1_")      Returns:     int: Number of positions closed

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.close_trade`

```python
def close_trade(self, ticket, retries=3, delay=2)
```
**What it does, step by step:**

1. <b>for</b> <code>attempt</code> in <code>range(retries)</code>: iterates.
2. Calls <code>logging.error(...)</code> for its side effect.
3. <b>return</b> <code>not self.is_trade_open(ticket)</code>.

```python
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
```

##### `MT5API.force_close_trade`

```python
def force_close_trade(self, ticket)
```
**What it does, step by step:**

1. Assigns <code>positions</code> = <code>mt5.positions_get(ticket=ticket)</code>.
2. <b>if</b> <code>not positions</code>: branches conditionally.
3. Assigns <code>pos</code> = <code>positions[0]</code>.
4. Assigns <code>symbol</code> = <code>pos.symbol</code>.
5. Assigns <code>volume</code> = <code>pos.volume</code>.
6. Assigns <code>order_type</code> = <code>pos.type</code>.
7. Assigns <code>price</code> = <code>mt5.symbol_info_tick(symbol).bid if order_type == mt5.POS...</code>.
8. Assigns <code>close_type</code> = <code>mt5.ORDER_TYPE_SELL if order_type == mt5.POSITION_TYPE_BU...</code>.
9. <b>for</b> <code>filling</code> in <code>[mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_...</code>: iterates.
10. Calls <code>logging.error(...)</code> for its side effect.
11. <b>return</b> <code>not self.is_trade_open(ticket)</code>.

```python
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
```

##### `MT5API.get_daily_trade_count`

```python
def get_daily_trade_count(self, comment_filter=None)
```
> Get count of trades placed today from both open positions and history  Args:     comment_filter: Can be either:         - Tradovate account number (e.g., "MFFUEVSTP326057008") - preferred method         - Old combine prefix (e.g., "Combine1_") - for backward compatibility

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
            return 0
```

##### `MT5API.get_daily_trade_count_by_account`

```python
def get_daily_trade_count_by_account(self, tradovate_account_number)
```
> Get count of trades placed today for a specific Tradovate account  Args:     tradovate_account_number: Tradovate account number (e.g., "MFFUEVSTP326057008")      Returns:     int: Number of trades opened today for this account

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
                        # Check if position comment matches the account number (comment starts with account number, may have phase suffix)
                        if pos.comment and pos.comment.strip().startswith(tradovate_account_number):
                            trade_count += 1
            
            # Count from history deals
            today_start = datetime.combine(today, datetime.min.time())
            today_end = datetime.now()
            
            deals = mt5.history_deals_get(today_start, today_end)
            if deals:
                for deal in deals:
                    if deal.entry == mt5.DEAL_ENTRY_IN:  # Entry deal only
                        # Check if deal comment matches the account number (comment starts with account number, may have phase suffix)
                        if deal.comment and deal.comment.strip().startswith(tradovate_account_number):
                            trade_count += 1
            
            logging.info(f"Daily trade count for account {tradovate_account_number}: {trade_count}")
            return trade_count
            
        except Exception as e:
            logging.error(f"Error counting daily trades for account {tradovate_account_number}: {e}")
            return 0
```

##### `MT5API.reset_daily_trade_count`

```python
def reset_daily_trade_count(self, comment_filter=None)
```
> Reset daily trade count for a specific filter by storing reset timestamp  Args:     comment_filter: Can be either:         - Tradovate account number (e.g., "MFFUEVSTP326057008") - preferred method         - Old combine prefix (e.g., "Combine1_") - for backward compatibility

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.reset_daily_trade_count_by_account`

```python
def reset_daily_trade_count_by_account(self, tradovate_account_number)
```
> Reset daily trade count for a specific Tradovate account  Args:     tradovate_account_number: Tradovate account number (e.g., "MFFUEVSTP326057008")

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.get_historical_profits_by_account`

```python
def get_historical_profits_by_account(self, account_number)
```
> Get total historical profits for trades from a specific Tradovate account

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
                    # Check if deal comment matches the account number (comment starts with account number, may have phase suffix)
                    if deal.comment and deal.comment.strip().startswith(account_number):
                        # Only count exit deals for profit calculation (avoid double counting)
                        if deal.entry == mt5.DEAL_ENTRY_OUT:
                            total_profit += deal.profit
            
            logging.info(f"Historical profits for account {account_number}: ${total_profit:.2f}")
            return total_profit
            
        except Exception as e:
            logging.error(f"Error getting historical profits by account: {e}")
            return 0.0
```

##### `MT5API.get_historical_profits`

```python
def get_historical_profits(self, comment_filter=None)
```
> Get total historical profits for trades with specific comment filter

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.close_orphaned_trades`

```python
def close_orphaned_trades(self, expected_tradovate_trades)
```
> Close MT5 trades that don't have corresponding Tradovate trades  Args:     expected_tradovate_trades: List of Tradovate trade symbols/IDs that should have MT5 counterparts      Returns:     List of closed MT5 trade tickets

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.extract_tradovate_account_from_comment`

```python
def extract_tradovate_account_from_comment(self, comment)
```
> Extract Tradovate account number from MT5 comment  Args:     comment: MT5 order comment (e.g., "MFFUEVSTP326057008_CH1" or "ACCOUNT_FA")      Returns:     str: Tradovate account number or "Unknown" if not found

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def extract_tradovate_account_from_comment(self, comment):
        """Extract Tradovate account number from MT5 comment
        
        Args:
            comment: MT5 order comment (e.g., "MFFUEVSTP326057008_CH1" or "ACCOUNT_FA")
            
        Returns:
            str: Tradovate account number or "Unknown" if not found
        """
        try:
            if comment and comment.strip():
                import re
                # For new format: comment is account number + optional phase suffix
                # Strip the phase suffix if present
                account_number = comment.strip()
                # Remove phase abbreviation suffix if present
                if '_' in account_number:
                    # Check for numbered formats (_CH1-4, _FD1-4, _DD1-4)
                    if re.search(r'_(CH|FD|DD)\d+$', account_number):
                        account_number = re.sub(r'_(CH|FD|DD)\d+$', '', account_number)
                    # Check for simple farming format: _FA
                    elif account_number.endswith('_FA'):
                        account_number = account_number[:-3]
                    # Check for unknown phase marker
                    elif account_number.endswith('_UNK'):
                        account_number = account_number[:-4]
                return account_number if account_number else "Unknown"
            return "Unknown"
        except Exception as e:
            logging.error(f"Error extracting account from comment '{comment}': {e}")
            return "Unknown"
```

##### `MT5API.get_trades_by_tradovate_account`

```python
def get_trades_by_tradovate_account(self, tradovate_account_number=None)
```
> Get all MT5 trades associated with a specific Tradovate account  Args:     tradovate_account_number: Tradovate account number to filter by      Returns:     dict: Dictionary with 'open_positions' and 'history_deals' lists

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.get_symbol_info`

```python
def get_symbol_info(self, symbol)
```
> Get symbol information

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_symbol_info(self, symbol):
        """Get symbol information"""
        try:
            return mt5.symbol_info(symbol)
        except Exception as e:
            logging.error(f"Error getting symbol info for {symbol}: {e}")
            return None
```

##### `MT5API.debug_symbol_info`

```python
def debug_symbol_info(self, symbol)
```
> Debug method to print all available symbol information

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.get_tick_data`

```python
def get_tick_data(self, symbol)
```
> Get current tick data for symbol

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_tick_data(self, symbol):
        """Get current tick data for symbol"""
        try:
            return mt5.symbol_info_tick(symbol)
        except Exception as e:
            logging.error(f"Error getting tick data for {symbol}: {e}")
            return None
```

##### `MT5API.should_close_trades_for_rollover`

```python
def should_close_trades_for_rollover(self, prop_firm_name)
```
> Check if trades should be closed based on prop firm rollover schedules.  Closing Times (Eastern Time): - Trade Day: 5:00 PM ET - Funding Ticks: 5:00 PM ET - Tradeify: 4:59 PM ET - MFFU: 4:10 PM ET  - Alpha Futures: 4:20 PM ET  Args:     prop_firm_name: Name of the prop firm      Returns:     bool: True if trades should be closed now, False otherwise

**What it does, step by step:**

1. Imports <code>datetime</code> (lazy import inside the function).
2. Imports <code>pytz</code> (lazy import inside the function).
3. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

##### `MT5API.close_trades_for_rollover`

```python
def close_trades_for_rollover(self, prop_firm_name, account_comment_prefix=None)
```
> Close all MT5 trades for market rollover based on prop firm schedule.  Args:     prop_firm_name: Name of the prop firm     account_comment_prefix: Account number to filter trades (e.g., "MFFU123456")      Returns:     list: List of closed trade tickets

**What it does, step by step:**

1. <b>if</b> <code>not self.should_close_trades_for_rollover(prop_firm_name)</code>: branches conditionally.
2. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

**Functions**

#### `setup_pyinstaller_mt5_environment`

```python
def setup_pyinstaller_mt5_environment()
```
> Enhanced MT5 environment setup for PyInstaller builds

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.
2. <b>return</b> <code>False</code>.

```python
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
```

#### `get_installed_mt5_terminals`

```python
def get_installed_mt5_terminals()
```
> Detect installed MetaTrader 5 terminals on Windows Returns a list of dictionaries with terminal info

**What it does, step by step:**

1. Assigns <code>terminals</code> = <code>[]</code>.
2. Calls <code>logging.info(...)</code> for its side effect.
3. Assigns <code>username</code> = <code>os.getenv('USERNAME', '')</code>.
4. Assigns <code>common_paths</code> = <code>['C:\\Program Files\\MetaTrader 5', 'C:\\Program Files (x...</code>.
5. Assigns <code>registry_paths</code> = <code>[(winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\MetaQuotes\\Termi...</code>.
6. <b>for</b> <code>(hkey, reg_path)</code> in <code>registry_paths</code>: iterates.
7. <b>for</b> <code>path</code> in <code>common_paths</code>: iterates.
8. <b>try</b> block with 1 <b>except</b> clause.
9. Assigns <code>current_dir</code> = <code>os.path.dirname(os.path.abspath(__file__))</code>.
10. Assigns <code>parent_dir</code> = <code>os.path.dirname(current_dir)</code>.
11. Assigns <code>portable_paths</code> = <code>[os.path.join(parent_dir, 'MT5'), os.path.join(parent_dir...</code>.
12. <b>for</b> <code>path</code> in <code>portable_paths</code>: iterates.
13. <b>try</b> block with 1 <b>except</b> clause.
14. Assigns <code>unique_terminals</code> = <code>[]</code>.
15. <i>... and 13 more statement(s) in the body.</i>

```python
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
```

---

### `trader_companion/mt5_comment_parser.py`

_869 loc · 5 classes · 4 functions · 5 imports_

**Module docstring**

> MT5 Comment Parser Module Parses MT5 trade comments from TradeAccountConnector to extract account info and phase data.
> Comment Format: {TradovateAccountNumber}{PhaseSuffix} Example: MFFUEVSTP326057008_CH1
> Phase Suffix Reference: - _CH1-4: Challenge Trade 1-4 - _FD0: Funded Base (MFFU style) - _FD1-4: Funded/Payout 1-4 - _DD1-4: Double Dip 1-4 - _FA: Farming/Consistency - _FA_DDMMYY: Farming with date (e.g., _FA_210126 = Jan 21, 2026) - _UNK: Unknown phase

**Imports**

```python
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
```

**Classes**

#### `class Phase(Enum)`

> Trading phase types.

```python
CHALLENGE = 'CH'
FUNDED = 'FD'
DOUBLE_DIP = 'DD'
FARMING = 'FA'
UNKNOWN = 'UNK'
LEGACY = 'LEGACY'
```

```python
class Phase(Enum):
    """Trading phase types."""
    CHALLENGE = "CH"       # Challenge trades
    FUNDED = "FD"          # Funded/Payout trades
    DOUBLE_DIP = "DD"      # Double Dip trades
    FARMING = "FA"         # Farming/Consistency phase
    UNKNOWN = "UNK"        # Unknown phase
    LEGACY = "LEGACY"
```

#### `class ParsedComment`

```python
@dataclass
```
> Parsed MT5 comment data.

```python
account_number: Optional[str] = None
phase: Optional[Phase] = None
phase_code: Optional[str] = None
trade_number: Optional[int] = None
farming_date: Optional[datetime] = None
raw_comment: str = ''
is_valid: bool = False
```

```python
class ParsedComment:
    """Parsed MT5 comment data."""
    account_number: Optional[str] = None
    phase: Optional[Phase] = None
    phase_code: Optional[str] = None  # Raw phase code (CH, FD, DD, FA, UNK)
    trade_number: Optional[int] = None
    farming_date: Optional[datetime] = None
    raw_comment: str = ""
    is_valid: bool = False
    
    def __str__(self):
        if not self.is_valid:
            return f"Invalid: {self.raw_comment}"
        
        date_str = f" ({self.farming_date.strftime('%d/%m/%y')})" if self.farming_date else ""
        trade_str = f" Trade #{self.trade_number}" if self.trade_number else ""
        return f"{self.account_number} | {self.phase.name}{trade_str}{date_str}"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "account_number": self.account_number,
            "phase": self.phase.value if self.phase else None,
            "phase_name": self.phase.name if self.phase else None,
            "phase_code": self.phase_code,
            "trade_number": self.trade_number,
            "farming_date": self.farming_date.isoformat() if self.farming_date else None,
            "raw_comment": self.raw_comment,
            "is_valid": self.is_valid
        }
```

##### `ParsedComment.__str__`

```python
def __str__(self)
```
**What it does, step by step:**

1. <b>if</b> <code>not self.is_valid</code>: branches conditionally.
2. Assigns <code>date_str</code> = <code>f" ({self.farming_date.strftime('%d/%m/%y')})" if self.fa...</code>.
3. Assigns <code>trade_str</code> = <code>f' Trade #{self.trade_number}' if self.trade_number else ''</code>.
4. <b>return</b> <code>f'{self.account_number} | {self.phase.name}{trade_str}{date_str}'</code>.

```python
def __str__(self):
        if not self.is_valid:
            return f"Invalid: {self.raw_comment}"
        
        date_str = f" ({self.farming_date.strftime('%d/%m/%y')})" if self.farming_date else ""
        trade_str = f" Trade #{self.trade_number}" if self.trade_number else ""
        return f"{self.account_number} | {self.phase.name}{trade_str}{date_str}"
```

##### `ParsedComment.to_dict`

```python
def to_dict(self) -> Dict
```
> Convert to dictionary.

**What it does, step by step:**

1. <b>return</b> <code>{'account_number': self.account_number, 'phase': self.phase.value i...</code>.

```python
def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "account_number": self.account_number,
            "phase": self.phase.value if self.phase else None,
            "phase_name": self.phase.name if self.phase else None,
            "phase_code": self.phase_code,
            "trade_number": self.trade_number,
            "farming_date": self.farming_date.isoformat() if self.farming_date else None,
            "raw_comment": self.raw_comment,
            "is_valid": self.is_valid
        }
```

#### `class AggregatedTrade`

```python
@dataclass
```
> Aggregated trade data for a specific account/phase combination.

```python
account_number: str
phase: Phase
phase_code: str
trade_number: Optional[int] = None
farming_date: Optional[datetime] = None
total_profit: float = 0.0
total_commission: float = 0.0
total_swap: float = 0.0
total_fee: float = 0.0
deal_count: int = 0
deals: List[Dict] = field(default_factory=list)
earliest_deal_time: Optional[str] = None
latest_deal_time: Optional[str] = None
```

```python
class AggregatedTrade:
    """Aggregated trade data for a specific account/phase combination."""
    account_number: str
    phase: Phase
    phase_code: str
    trade_number: Optional[int] = None
    farming_date: Optional[datetime] = None
    total_profit: float = 0.0
    total_commission: float = 0.0
    total_swap: float = 0.0
    total_fee: float = 0.0
    deal_count: int = 0
    deals: List[Dict] = field(default_factory=list)
    earliest_deal_time: Optional[str] = None  # ISO string of first deal time
    latest_deal_time: Optional[str] = None    # ISO string of last deal time
    
    @property
    def net_profit(self) -> float:
        """Net profit including all costs."""
        return self.total_profit + self.total_commission + self.total_swap + self.total_fee
    
    @property
    def account_signature(self) -> str:
        """Get first4+last4 account signature for matching."""
        return get_account_signature(self.account_number)
    
    def get_key(self) -> str:
        """Get unique key for this aggregation."""
        date_suffix = f"_{self.farming_date.strftime('%d%m%y')}" if self.farming_date else ""
        trade_suffix = str(self.trade_number) if self.trade_number else ""
        return f"{self.account_number}_{self.phase_code}{trade_suffix}{date_suffix}"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "account_number": self.account_number,
            "phase": self.phase.value,
            "phase_name": self.phase.name,
            "phase_code": self.phase_code,
            "trade_number": self.trade_number,
            "farming_date": self.farming_date.isoformat() if self.farming_date else None,
            "timestamp": self.farming_date.timestamp() if self.farming_date else None, # Add timestamp for server filtering
            "total_profit": round(self.total_profit, 2),
            "total_commission": round(self.total_commission, 2),
            "total_swap": round(self.total_swap, 2),
            "total_fee": round(self.total_fee, 2),
            "net_profit": round(self.net_profit, 2),
            "deal_count": self.deal_count,
            "key": self.get_key(),
            "account_signature": self.account_signature,
            "open_time": self.earliest_deal_time,
            "close_time": self.latest_deal_time
        }
```

##### `AggregatedTrade.net_profit`

```python
@property
def net_profit(self) -> float
```
> Net profit including all costs.

**What it does, step by step:**

1. <b>return</b> <code>self.total_profit + self.total_commission + self.total_swap + self....</code>.

```python
def net_profit(self) -> float:
        """Net profit including all costs."""
        return self.total_profit + self.total_commission + self.total_swap + self.total_fee
```

##### `AggregatedTrade.account_signature`

```python
@property
def account_signature(self) -> str
```
> Get first4+last4 account signature for matching.

**What it does, step by step:**

1. <b>return</b> <code>get_account_signature(self.account_number)</code>.

```python
def account_signature(self) -> str:
        """Get first4+last4 account signature for matching."""
        return get_account_signature(self.account_number)
```

##### `AggregatedTrade.get_key`

```python
def get_key(self) -> str
```
> Get unique key for this aggregation.

**What it does, step by step:**

1. Assigns <code>date_suffix</code> = <code>f"_{self.farming_date.strftime('%d%m%y')}" if self.farmin...</code>.
2. Assigns <code>trade_suffix</code> = <code>str(self.trade_number) if self.trade_number else ''</code>.
3. <b>return</b> <code>f'{self.account_number}_{self.phase_code}{trade_suffix}{date_suffix}'</code>.

```python
def get_key(self) -> str:
        """Get unique key for this aggregation."""
        date_suffix = f"_{self.farming_date.strftime('%d%m%y')}" if self.farming_date else ""
        trade_suffix = str(self.trade_number) if self.trade_number else ""
        return f"{self.account_number}_{self.phase_code}{trade_suffix}{date_suffix}"
```

##### `AggregatedTrade.to_dict`

```python
def to_dict(self) -> Dict
```
> Convert to dictionary.

**What it does, step by step:**

1. <b>return</b> <code>{'account_number': self.account_number, 'phase': self.phase.value, ...</code>.

```python
def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "account_number": self.account_number,
            "phase": self.phase.value,
            "phase_name": self.phase.name,
            "phase_code": self.phase_code,
            "trade_number": self.trade_number,
            "farming_date": self.farming_date.isoformat() if self.farming_date else None,
            "timestamp": self.farming_date.timestamp() if self.farming_date else None, # Add timestamp for server filtering
            "total_profit": round(self.total_profit, 2),
            "total_commission": round(self.total_commission, 2),
            "total_swap": round(self.total_swap, 2),
            "total_fee": round(self.total_fee, 2),
            "net_profit": round(self.net_profit, 2),
            "deal_count": self.deal_count,
            "key": self.get_key(),
            "account_signature": self.account_signature,
            "open_time": self.earliest_deal_time,
            "close_time": self.latest_deal_time
        }
```

#### `class MT5CommentParser`

> Parser for MT5 trade comments following TradeAccountConnector format.  Comment Format: {TradovateAccountNumber}{PhaseSuffix}  Examples:     MFFUEVSTP326057008_CH1  -> Account MFFUEVSTP326057008, Challenge Trade 1     MFFUEVSTP326057008_FD2  -> Account MFFUEVSTP326057008, Funded/Payout 2     MFFUEVSTP326057008_FA   -> Account MFFUEVSTP326057008, Farming phase     MFFUEVSTP326057008_FA_210126 -> Farming on Jan 21, 2026     MFFUEVSTP326057008_DD1  -> Double Dip Trade 1

```python
PHASE_MEANINGS = {'MFFU': {'CH': 'Challenge trades', 'FD0': 'Base funded trade', 'FD': 'Payout', 'DD': 'Double Dip...
```

```python
class MT5CommentParser:
    """
    Parser for MT5 trade comments following TradeAccountConnector format.
    
    Comment Format: {TradovateAccountNumber}{PhaseSuffix}
    
    Examples:
        MFFUEVSTP326057008_CH1  -> Account MFFUEVSTP326057008, Challenge Trade 1
        MFFUEVSTP326057008_FD2  -> Account MFFUEVSTP326057008, Funded/Payout 2
        MFFUEVSTP326057008_FA   -> Account MFFUEVSTP326057008, Farming phase
        MFFUEVSTP326057008_FA_210126 -> Farming on Jan 21, 2026
        MFFUEVSTP326057008_DD1  -> Double Dip Trade 1
    """
    
    # Phase mappings by prop firm
    PHASE_MEANINGS = {
        "MFFU": {
            "CH": "Challenge trades",
            "FD0": "Base funded trade",
            "FD": "Payout",
            "DD": "Double Dip",
            "FA": "Farming/Consistency (5 days)"
        },
        "Tradeify": {
            "CH": "Challenge trades",
            "FD": "Payout",
            "DD": "Double Dip",
            "FA": "Consistency"
        },
        "Funding Ticks": {
            "CH": "Challenge trades",
            "FD": "Payout",
            "DD": "Double Dip",
            "FA": "Farming (6 days)"
        },
        "Alpha Futures": {
            "CH": "Challenge trades",
            "FD": "Payout",
            "DD": "Double Dip",
            "FA": "Farming"
        }
    }
    
    def __init__(self):
        """Initialize the parser with regex patterns."""
        # Patterns ordered by specificity (most specific first)
        self.patterns = [
            # Numbered phases: _CH1, _FD2, _DD3
            (r'^(.+?)_(CH|FD|DD)(\d+)$', self._parse_numbered_phase),
            # Farming with date: _FA_DDMMYY
            (r'^(.+?)_FA_(\d{6})$', self._parse_farming_with_date),
            # Simple farming: _FA
            (r'^(.+?)_FA$', self._parse_simple_farming),
            # Unknown phase: _UNK
            (r'^(.+?)_UNK$', self._parse_unknown_phase),
            # Legacy Combine format
            (r'^Combine(\d+)_(.*)$', self._parse_legacy_combine),
        ]
    
    def parse(self, comment: str) -> ParsedComment:
        """
        Parse an MT5 trade comment.
        
        Args:
            comment: The MT5 order comment string
            
        Returns:
            ParsedComment object with extracted data
        """
        result = ParsedComment(raw_comment=comment or "")
        
        if not comment:
            return result
        
        comment = comment.strip()
        
        # Try each pattern
        for pattern, handler in self.patterns:
            match = re.match(pattern, comment, re.IGNORECASE)
            if match:
                return handler(match, comment)
        
        # No pattern matched - check if it's just an account number
        # (comment without phase suffix)
        if comment and not comment.startswith("Combine"):
            result.account_number = comment
            result.is_valid = False  # Mark as not fully valid without phase
        
        return result
    
    def _parse_numbered_phase(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse numbered phases: CH, FD, DD with trade number."""
        account = match.group(1)
        phase_code = match.group(2).upper()
        trade_num = int(match.group(3))
        
        phase_map = {
            "CH": Phase.CHALLENGE,
            "FD": Phase.FUNDED,
            "DD": Phase.DOUBLE_DIP
        }
        
        return ParsedComment(
            account_number=account,
            phase=phase_map.get(phase_code, Phase.UNKNOWN),
            phase_code=phase_code,
            trade_number=trade_num,
            raw_comment=comment,
            is_valid=True
        )
    
    def _parse_farming_with_date(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse farming phase with date: _FA_DDMMYY."""
        account = match.group(1)
        date_str = match.group(2)  # DDMMYY format
        
        farming_date = None
        try:
            farming_date = datetime.strptime(date_str, "%d%m%y")
        except ValueError:
            pass
        
        return ParsedComment(
            account_number=account,
            phase=Phase.FARMING,
            phase_code="FA",
            farming_date=farming_date,
            raw_comment=comment,
            is_valid=True
        )
    
    def _parse_simple_farming(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse simple farming phase: _FA."""
        return ParsedComment(
            account_number=match.group(1),
            phase=Phase.FARMING,
            phase_code="FA",
            raw_comment=comment,
            is_valid=True
        )
    
    def _parse_unknown_phase(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse unknown phase: _UNK."""
        return ParsedComment(
            account_number=match.group(1),
            phase=Phase.UNKNOWN,
            phase_code="UNK",
            raw_comment=comment,
            is_valid=True
        )
    
    def _parse_legacy_combine(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse legacy Combine format: Combine{N}_."""
        combinenum = match.group(1)
        rest = match.group(2)
        # Usually Combine1_Account
        return ParsedComment(
            account_number=rest,
            phase=Phase.CHALLENGE,
            phase_code="CH",
            trade_number=int(combinenum),
            raw_comment=comment,
            is_valid=True
        )

    def get_phase_meaning(self, phase_code: str, prop_firm: str = "MFFU") -> str:
        """
        Get human-readable meaning for a phase code.
        
        Args:
            phase_code: Phase code (CH, FD, DD, FA)
            prop_firm: Prop firm name for context-specific meaning
            
        Returns:
            Description of the phase
        """
        firm_meanings = self.PHASE_MEANINGS.get(prop_firm, self.PHASE_MEANINGS["MFFU"])
        return firm_meanings.get(phase_code, f"Unknown phase: {phase_code}")
```

##### `MT5CommentParser.__init__`

```python
def __init__(self)
```
> Initialize the parser with regex patterns.

**What it does, step by step:**

1. Assigns <code>self.patterns</code> = <code>[('^(.+?)_(CH|FD|DD)(\\d+)$', self._parse_numbered_phase)...</code>.

```python
def __init__(self):
        """Initialize the parser with regex patterns."""
        # Patterns ordered by specificity (most specific first)
        self.patterns = [
            # Numbered phases: _CH1, _FD2, _DD3
            (r'^(.+?)_(CH|FD|DD)(\d+)$', self._parse_numbered_phase),
            # Farming with date: _FA_DDMMYY
            (r'^(.+?)_FA_(\d{6})$', self._parse_farming_with_date),
            # Simple farming: _FA
            (r'^(.+?)_FA$', self._parse_simple_farming),
            # Unknown phase: _UNK
            (r'^(.+?)_UNK$', self._parse_unknown_phase),
            # Legacy Combine format
            (r'^Combine(\d+)_(.*)$', self._parse_legacy_combine),
        ]
```

##### `MT5CommentParser.parse`

```python
def parse(self, comment: str) -> ParsedComment
```
> Parse an MT5 trade comment.  Args:     comment: The MT5 order comment string      Returns:     ParsedComment object with extracted data

**What it does, step by step:**

1. Assigns <code>result</code> = <code>ParsedComment(raw_comment=comment or '')</code>.
2. <b>if</b> <code>not comment</code>: branches conditionally.
3. Assigns <code>comment</code> = <code>comment.strip()</code>.
4. <b>for</b> <code>(pattern, handler)</code> in <code>self.patterns</code>: iterates.
5. <b>if</b> <code>comment and (not comment.startswith('Combine'))</code>: branches conditionally.
6. <b>return</b> <code>result</code>.

```python
def parse(self, comment: str) -> ParsedComment:
        """
        Parse an MT5 trade comment.
        
        Args:
            comment: The MT5 order comment string
            
        Returns:
            ParsedComment object with extracted data
        """
        result = ParsedComment(raw_comment=comment or "")
        
        if not comment:
            return result
        
        comment = comment.strip()
        
        # Try each pattern
        for pattern, handler in self.patterns:
            match = re.match(pattern, comment, re.IGNORECASE)
            if match:
                return handler(match, comment)
        
        # No pattern matched - check if it's just an account number
        # (comment without phase suffix)
        if comment and not comment.startswith("Combine"):
            result.account_number = comment
            result.is_valid = False  # Mark as not fully valid without phase
        
        return result
```

##### `MT5CommentParser._parse_numbered_phase`

```python
def _parse_numbered_phase(self, match: re.Match, comment: str) -> ParsedComment
```
> Parse numbered phases: CH, FD, DD with trade number.

**What it does, step by step:**

1. Assigns <code>account</code> = <code>match.group(1)</code>.
2. Assigns <code>phase_code</code> = <code>match.group(2).upper()</code>.
3. Assigns <code>trade_num</code> = <code>int(match.group(3))</code>.
4. Assigns <code>phase_map</code> = <code>{'CH': Phase.CHALLENGE, 'FD': Phase.FUNDED, 'DD': Phase.D...</code>.
5. <b>return</b> <code>ParsedComment(account_number=account, phase=phase_map.get(phase_cod...</code>.

```python
def _parse_numbered_phase(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse numbered phases: CH, FD, DD with trade number."""
        account = match.group(1)
        phase_code = match.group(2).upper()
        trade_num = int(match.group(3))
        
        phase_map = {
            "CH": Phase.CHALLENGE,
            "FD": Phase.FUNDED,
            "DD": Phase.DOUBLE_DIP
        }
        
        return ParsedComment(
            account_number=account,
            phase=phase_map.get(phase_code, Phase.UNKNOWN),
            phase_code=phase_code,
            trade_number=trade_num,
            raw_comment=comment,
            is_valid=True
        )
```

##### `MT5CommentParser._parse_farming_with_date`

```python
def _parse_farming_with_date(self, match: re.Match, comment: str) -> ParsedComment
```
> Parse farming phase with date: _FA_DDMMYY.

**What it does, step by step:**

1. Assigns <code>account</code> = <code>match.group(1)</code>.
2. Assigns <code>date_str</code> = <code>match.group(2)</code>.
3. Assigns <code>farming_date</code> = <code>None</code>.
4. <b>try</b> block with 1 <b>except</b> clause.
5. <b>return</b> <code>ParsedComment(account_number=account, phase=Phase.FARMING, phase_co...</code>.

```python
def _parse_farming_with_date(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse farming phase with date: _FA_DDMMYY."""
        account = match.group(1)
        date_str = match.group(2)  # DDMMYY format
        
        farming_date = None
        try:
            farming_date = datetime.strptime(date_str, "%d%m%y")
        except ValueError:
            pass
        
        return ParsedComment(
            account_number=account,
            phase=Phase.FARMING,
            phase_code="FA",
            farming_date=farming_date,
            raw_comment=comment,
            is_valid=True
        )
```

##### `MT5CommentParser._parse_simple_farming`

```python
def _parse_simple_farming(self, match: re.Match, comment: str) -> ParsedComment
```
> Parse simple farming phase: _FA.

**What it does, step by step:**

1. <b>return</b> <code>ParsedComment(account_number=match.group(1), phase=Phase.FARMING, p...</code>.

```python
def _parse_simple_farming(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse simple farming phase: _FA."""
        return ParsedComment(
            account_number=match.group(1),
            phase=Phase.FARMING,
            phase_code="FA",
            raw_comment=comment,
            is_valid=True
        )
```

##### `MT5CommentParser._parse_unknown_phase`

```python
def _parse_unknown_phase(self, match: re.Match, comment: str) -> ParsedComment
```
> Parse unknown phase: _UNK.

**What it does, step by step:**

1. <b>return</b> <code>ParsedComment(account_number=match.group(1), phase=Phase.UNKNOWN, p...</code>.

```python
def _parse_unknown_phase(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse unknown phase: _UNK."""
        return ParsedComment(
            account_number=match.group(1),
            phase=Phase.UNKNOWN,
            phase_code="UNK",
            raw_comment=comment,
            is_valid=True
        )
```

##### `MT5CommentParser._parse_legacy_combine`

```python
def _parse_legacy_combine(self, match: re.Match, comment: str) -> ParsedComment
```
> Parse legacy Combine format: Combine{N}_.

**What it does, step by step:**

1. Assigns <code>combinenum</code> = <code>match.group(1)</code>.
2. Assigns <code>rest</code> = <code>match.group(2)</code>.
3. <b>return</b> <code>ParsedComment(account_number=rest, phase=Phase.CHALLENGE, phase_cod...</code>.

```python
def _parse_legacy_combine(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse legacy Combine format: Combine{N}_."""
        combinenum = match.group(1)
        rest = match.group(2)
        # Usually Combine1_Account
        return ParsedComment(
            account_number=rest,
            phase=Phase.CHALLENGE,
            phase_code="CH",
            trade_number=int(combinenum),
            raw_comment=comment,
            is_valid=True
        )
```

##### `MT5CommentParser.get_phase_meaning`

```python
def get_phase_meaning(self, phase_code: str, prop_firm: str='MFFU') -> str
```
> Get human-readable meaning for a phase code.  Args:     phase_code: Phase code (CH, FD, DD, FA)     prop_firm: Prop firm name for context-specific meaning      Returns:     Description of the phase

**What it does, step by step:**

1. Assigns <code>firm_meanings</code> = <code>self.PHASE_MEANINGS.get(prop_firm, self.PHASE_MEANINGS['M...</code>.
2. <b>return</b> <code>firm_meanings.get(phase_code, f'Unknown phase: {phase_code}')</code>.

```python
def get_phase_meaning(self, phase_code: str, prop_firm: str = "MFFU") -> str:
        """
        Get human-readable meaning for a phase code.
        
        Args:
            phase_code: Phase code (CH, FD, DD, FA)
            prop_firm: Prop firm name for context-specific meaning
            
        Returns:
            Description of the phase
        """
        firm_meanings = self.PHASE_MEANINGS.get(prop_firm, self.PHASE_MEANINGS["MFFU"])
        return firm_meanings.get(phase_code, f"Unknown phase: {phase_code}")
```

#### `class MT5DealAggregator`

> Aggregates MT5 deals by account and phase based on comment parsing.

```python
class MT5DealAggregator:
    """
    Aggregates MT5 deals by account and phase based on comment parsing.
    """
    
    def __init__(self):
        """Initialize the aggregator."""
        self.parser = MT5CommentParser()
        self.aggregations: Dict[str, AggregatedTrade] = {}
        self.unmatched_deals: List[Dict] = []
        self.parse_log: List[str] = []
    
    def reset(self):
        """Reset aggregation state."""
        self.aggregations = {}
        self.unmatched_deals = []
        self.parse_log = []
    
    def add_deal(self, deal: Dict) -> Optional[str]:
        """
        Add a single deal to the aggregation.
        
        Args:
            deal: MT5 deal dictionary with fields like:
                  - comment: Order comment
                  - profit: Deal profit
                  - commission: Commission
                  - swap: Swap charges
                  - fee: Additional fees
                  - type: Deal type (BUY, SELL, BALANCE, etc.)
                  - entry: Entry type (IN, OUT, INOUT)
                  
        Returns:
            Aggregation key if matched, None if unmatched
        """
        # Skip balance/credit operations
        deal_type = str(deal.get('type', '')).upper()
        if deal_type in ['BALANCE', 'CREDIT', '2', '3', 'CHARGE', 'CORRECTION', 'BONUS']:
            return None
        
        # Parse the comment
        comment = deal.get('comment', '')
        parsed = self.parser.parse(comment)
        
        if not parsed.is_valid or not parsed.account_number:
            self.unmatched_deals.append(deal)
            self.parse_log.append(f"⚠️ Unmatched: {comment or '(empty)'}")
            return None
        
        # Get deal date for clustering
        deal_time_str = deal.get('time', '')
        deal_date = None
        try:
            if deal_time_str:
                # Handle ISO format string (YYYY-MM-DDTHH:MM:SS)
                if isinstance(deal_time_str, str):
                    if 'T' in deal_time_str:
                        deal_date = datetime.fromisoformat(deal_time_str).date()
                    else:
                        # Fallback parsing if just YYYY-MM-DD
                        deal_date = datetime.strptime(deal_time_str.split()[0], '%Y-%m-%d').date()
                # Handle timestamp
                elif isinstance(deal_time_str, (int, float)):
                    deal_date = datetime.fromtimestamp(deal_time_str).date()
        except:
            pass # Keep deal_date as None if parsing fails

        # For Farming (FA), if no date in comment, use deal date
        # For Reset Accounts (CH/FD), we also want to separate by date to distinguish resets
        # So we update parsed.farming_date if it's currently None, using the deal date
        
        # Override/Set farming_date for grouping if not present in comment
        if not parsed.farming_date and deal_date:
            # Always populate farming_date (used as grouping date for all phases now)
            parsed.farming_date = datetime(deal_date.year, deal_date.month, deal_date.day)

        # Build aggregation key
        key = self._build_key(parsed)
        
        # Create or update aggregation
        if key not in self.aggregations:
            self.aggregations[key] = AggregatedTrade(
                account_number=parsed.account_number,
                phase=parsed.phase,
                phase_code=parsed.phase_code,
                trade_number=parsed.trade_number,
                farming_date=parsed.farming_date
            )
        
        agg = self.aggregations[key]
        agg.total_profit += deal.get('profit', 0) or 0
        agg.total_commission += deal.get('commission', 0) or 0
        agg.total_swap += deal.get('swap', 0) or 0
        agg.total_fee += deal.get('fee', 0) or 0
        agg.deal_count += 1
        agg.deals.append(deal)

        # Track earliest/latest deal times for timestamp notes
        deal_time = deal.get('time')
        if deal_time:
            if agg.earliest_deal_time is None or str(deal_time) < agg.earliest_deal_time:
                agg.earliest_deal_time = str(deal_time)
            if agg.latest_deal_time is None or str(deal_time) > agg.latest_deal_time:
                agg.latest_deal_time = str(deal_time)

        return key
    
    def _build_key(self, parsed: ParsedComment) -> str:
        """
        Build a unique key for an aggregation.
        Now includes DATE for ALL phases to support FundedNext resets.
        """
        parts = [parsed.account_number, parsed.phase_code]
        
        if parsed.trade_number is not None:
            parts.append(str(parsed.trade_number))
        
        # Always append date to separate trades by day
        # This allows the server to match Jan trades to Account A and Feb trades to Account B (Reset)
        date_to_use = parsed.farming_date or datetime.now()
        parts.append(date_to_use.strftime('%d%m%y'))
        
        return "_".join(parts)
    
    def process_deals(self, deals: List[Dict]) -> Tuple[Dict[str, AggregatedTrade], List[Dict]]:
        """
        Process a list of deals and aggregate by account/phase.
        
        Args:
            deals: List of MT5 deal dictionaries
            
        Returns:
            Tuple of (aggregations dict, unmatched deals list)
        """
        self.reset()
        
        for deal in deals:
            self.add_deal(deal)
        
        return self.aggregations, self.unmatched_deals
    
    def get_summary(self) -> Dict:
        """Get a summary of the aggregation."""
        return {
            "total_aggregations": len(self.aggregations),
            "total_unmatched": len(self.unmatched_deals),
            "by_phase": self._summarize_by_phase(),
            "by_account": self._summarize_by_account(),
            "parse_log": self.parse_log
        }
    
    def _summarize_by_phase(self) -> Dict[str, Dict]:
        """Summarize aggregations by phase."""
        summary = {}
        for key, agg in self.aggregations.items():
            phase_name = agg.phase.name
            if phase_name not in summary:
                summary[phase_name] = {"count": 0, "total_net_profit": 0.0}
            summary[phase_name]["count"] += 1
            summary[phase_name]["total_net_profit"] += agg.net_profit
        return summary
    
    def _summarize_by_account(self) -> Dict[str, Dict]:
        """Summarize aggregations by account."""
        summary = {}
        for key, agg in self.aggregations.items():
            account = agg.account_number
            if account not in summary:
                summary[account] = {"phases": {}, "total_net_profit": 0.0}
            
            phase_key = f"{agg.phase_code}{agg.trade_number or ''}"
            summary[account]["phases"][phase_key] = agg.net_profit
            summary[account]["total_net_profit"] += agg.net_profit
        
        return summary
    
    def to_dashboard_format(self) -> List[Dict]:
        """
        Convert aggregations to dashboard-compatible format.
        
        Returns list of dicts with:
        - account_number: Account identifier
        - phase: Phase code (CH, FD, DD, FA)
        - trade_number: Trade number (1-4) or None
        - farming_date: Date if farming phase
        - net_profit: Total net profit for this combination
        - deal_count: Number of deals
        """
        result = []
        for key, agg in self.aggregations.items():
            result.append(agg.to_dict())
        return result
```

##### `MT5DealAggregator.__init__`

```python
def __init__(self)
```
> Initialize the aggregator.

**What it does, step by step:**

1. Assigns <code>self.parser</code> = <code>MT5CommentParser()</code>.
2. Declares <code>self.aggregations: Dict[str, AggregatedTrade]</code> = <code>{}</code>.
3. Declares <code>self.unmatched_deals: List[Dict]</code> = <code>[]</code>.
4. Declares <code>self.parse_log: List[str]</code> = <code>[]</code>.

```python
def __init__(self):
        """Initialize the aggregator."""
        self.parser = MT5CommentParser()
        self.aggregations: Dict[str, AggregatedTrade] = {}
        self.unmatched_deals: List[Dict] = []
        self.parse_log: List[str] = []
```

##### `MT5DealAggregator.reset`

```python
def reset(self)
```
> Reset aggregation state.

**What it does, step by step:**

1. Assigns <code>self.aggregations</code> = <code>{}</code>.
2. Assigns <code>self.unmatched_deals</code> = <code>[]</code>.
3. Assigns <code>self.parse_log</code> = <code>[]</code>.

```python
def reset(self):
        """Reset aggregation state."""
        self.aggregations = {}
        self.unmatched_deals = []
        self.parse_log = []
```

##### `MT5DealAggregator.add_deal`

```python
def add_deal(self, deal: Dict) -> Optional[str]
```
> Add a single deal to the aggregation.  Args:     deal: MT5 deal dictionary with fields like:           - comment: Order comment           - profit: Deal profit           - commission: Commission           - swap: Swap charges           - fee: Additional fees           - type: Deal type (BUY, SELL, BALANCE, etc.)           - entry: Entry type (IN, OUT, INOUT)            Returns:     Aggregation key if matched, None if unmatched

**What it does, step by step:**

1. Assigns <code>deal_type</code> = <code>str(deal.get('type', '')).upper()</code>.
2. <b>if</b> <code>deal_type in ['BALANCE', 'CREDIT', '2', '3', 'CHARGE', 'CORRECTION'...</code>: branches conditionally.
3. Assigns <code>comment</code> = <code>deal.get('comment', '')</code>.
4. Assigns <code>parsed</code> = <code>self.parser.parse(comment)</code>.
5. <b>if</b> <code>not parsed.is_valid or not parsed.account_number</code>: branches conditionally.
6. Assigns <code>deal_time_str</code> = <code>deal.get('time', '')</code>.
7. Assigns <code>deal_date</code> = <code>None</code>.
8. <b>try</b> block with 1 <b>except</b> clause.
9. <b>if</b> <code>not parsed.farming_date and deal_date</code>: branches conditionally.
10. Assigns <code>key</code> = <code>self._build_key(parsed)</code>.
11. <b>if</b> <code>key not in self.aggregations</code>: branches conditionally.
12. Assigns <code>agg</code> = <code>self.aggregations[key]</code>.
13. Updates <code>agg.total_profit</code> in place (Add).
14. Updates <code>agg.total_commission</code> in place (Add).
15. <i>... and 7 more statement(s) in the body.</i>

```python
def add_deal(self, deal: Dict) -> Optional[str]:
        """
        Add a single deal to the aggregation.
        
        Args:
            deal: MT5 deal dictionary with fields like:
                  - comment: Order comment
                  - profit: Deal profit
                  - commission: Commission
                  - swap: Swap charges
                  - fee: Additional fees
                  - type: Deal type (BUY, SELL, BALANCE, etc.)
                  - entry: Entry type (IN, OUT, INOUT)
                  
        Returns:
            Aggregation key if matched, None if unmatched
        """
        # Skip balance/credit operations
        deal_type = str(deal.get('type', '')).upper()
        if deal_type in ['BALANCE', 'CREDIT', '2', '3', 'CHARGE', 'CORRECTION', 'BONUS']:
            return None
        
        # Parse the comment
        comment = deal.get('comment', '')
        parsed = self.parser.parse(comment)
        
        if not parsed.is_valid or not parsed.account_number:
            self.unmatched_deals.append(deal)
            self.parse_log.append(f"⚠️ Unmatched: {comment or '(empty)'}")
            return None
        
        # Get deal date for clustering
        deal_time_str = deal.get('time', '')
        deal_date = None
        try:
            if deal_time_str:
                # Handle ISO format string (YYYY-MM-DDTHH:MM:SS)
                if isinstance(deal_time_str, str):
                    if 'T' in deal_time_str:
                        deal_date = datetime.fromisoformat(deal_time_str).date()
                    else:
                        # Fallback parsing if just YYYY-MM-DD
                        deal_date = datetime.strptime(deal_time_str.split()[0], '%Y-%m-%d').date()
                # Handle timestamp
                elif isinstance(deal_time_str, (int, float)):
                    deal_date = datetime.fromtimestamp(deal_time_str).date()
        except:
            pass # Keep deal_date as None if parsing fails

        # For Farming (FA), if no date in comment, use deal date
        # For Reset Accounts (CH/FD), we also want to separate by date to distinguish resets
        # So we update parsed.farming_date if it's currently None, using the deal date
        
        # Override/Set farming_date for grouping if not present in comment
        if not parsed.farming_date and deal_date:
            # Always populate farming_date (used as grouping date for all phases now)
            parsed.farming_date = datetime(deal_date.year, deal_date.month, deal_date.day)

        # Build aggregation key
        key = self._build_key(parsed)
        
        # Create or update aggregation
        if key not in self.aggregations:
            self.aggregations[key] = AggregatedTrade(
                account_number=parsed.account_number,
                phase=parsed.phase,
                phase_code=parsed.phase_code,
                trade_number=parsed.trade_number,
                farming_date=parsed.farming_date
            )
        
        agg = self.aggregations[key]
        agg.total_profit += deal.get('profit', 0) or 0
        agg.total_commission += deal.get('commission', 0) or 0
        agg.total_swap += deal.get('swap', 0) or 0
        agg.total_fee += deal.get('fee', 0) or 0
        agg.deal_count += 1
        agg.deals.append(deal)

        # Track earliest/latest deal times for timestamp notes
        deal_time = deal.get('time')
        if deal_time:
            if agg.earliest_deal_time is None or str(deal_time) < agg.earliest_deal_time:
                agg.earliest_deal_time = str(deal_time)
            if agg.latest_deal_time is None or str(deal_time) > agg.latest_deal_time:
                agg.latest_deal_time = str(deal_time)

        return key
```

##### `MT5DealAggregator._build_key`

```python
def _build_key(self, parsed: ParsedComment) -> str
```
> Build a unique key for an aggregation. Now includes DATE for ALL phases to support FundedNext resets.

**What it does, step by step:**

1. Assigns <code>parts</code> = <code>[parsed.account_number, parsed.phase_code]</code>.
2. <b>if</b> <code>parsed.trade_number is not None</code>: branches conditionally.
3. Assigns <code>date_to_use</code> = <code>parsed.farming_date or datetime.now()</code>.
4. Calls <code>parts.append(...)</code> for its side effect.
5. <b>return</b> <code>'_'.join(parts)</code>.

```python
def _build_key(self, parsed: ParsedComment) -> str:
        """
        Build a unique key for an aggregation.
        Now includes DATE for ALL phases to support FundedNext resets.
        """
        parts = [parsed.account_number, parsed.phase_code]
        
        if parsed.trade_number is not None:
            parts.append(str(parsed.trade_number))
        
        # Always append date to separate trades by day
        # This allows the server to match Jan trades to Account A and Feb trades to Account B (Reset)
        date_to_use = parsed.farming_date or datetime.now()
        parts.append(date_to_use.strftime('%d%m%y'))
        
        return "_".join(parts)
```

##### `MT5DealAggregator.process_deals`

```python
def process_deals(self, deals: List[Dict]) -> Tuple[Dict[str, AggregatedTrade], List[Dict]]
```
> Process a list of deals and aggregate by account/phase.  Args:     deals: List of MT5 deal dictionaries      Returns:     Tuple of (aggregations dict, unmatched deals list)

**What it does, step by step:**

1. Calls <code>self.reset(...)</code> for its side effect.
2. <b>for</b> <code>deal</code> in <code>deals</code>: iterates.
3. <b>return</b> <code>(self.aggregations, self.unmatched_deals)</code>.

```python
def process_deals(self, deals: List[Dict]) -> Tuple[Dict[str, AggregatedTrade], List[Dict]]:
        """
        Process a list of deals and aggregate by account/phase.
        
        Args:
            deals: List of MT5 deal dictionaries
            
        Returns:
            Tuple of (aggregations dict, unmatched deals list)
        """
        self.reset()
        
        for deal in deals:
            self.add_deal(deal)
        
        return self.aggregations, self.unmatched_deals
```

##### `MT5DealAggregator.get_summary`

```python
def get_summary(self) -> Dict
```
> Get a summary of the aggregation.

**What it does, step by step:**

1. <b>return</b> <code>{'total_aggregations': len(self.aggregations), 'total_unmatched': l...</code>.

```python
def get_summary(self) -> Dict:
        """Get a summary of the aggregation."""
        return {
            "total_aggregations": len(self.aggregations),
            "total_unmatched": len(self.unmatched_deals),
            "by_phase": self._summarize_by_phase(),
            "by_account": self._summarize_by_account(),
            "parse_log": self.parse_log
        }
```

##### `MT5DealAggregator._summarize_by_phase`

```python
def _summarize_by_phase(self) -> Dict[str, Dict]
```
> Summarize aggregations by phase.

**What it does, step by step:**

1. Assigns <code>summary</code> = <code>{}</code>.
2. <b>for</b> <code>(key, agg)</code> in <code>self.aggregations.items()</code>: iterates.
3. <b>return</b> <code>summary</code>.

```python
def _summarize_by_phase(self) -> Dict[str, Dict]:
        """Summarize aggregations by phase."""
        summary = {}
        for key, agg in self.aggregations.items():
            phase_name = agg.phase.name
            if phase_name not in summary:
                summary[phase_name] = {"count": 0, "total_net_profit": 0.0}
            summary[phase_name]["count"] += 1
            summary[phase_name]["total_net_profit"] += agg.net_profit
        return summary
```

##### `MT5DealAggregator._summarize_by_account`

```python
def _summarize_by_account(self) -> Dict[str, Dict]
```
> Summarize aggregations by account.

**What it does, step by step:**

1. Assigns <code>summary</code> = <code>{}</code>.
2. <b>for</b> <code>(key, agg)</code> in <code>self.aggregations.items()</code>: iterates.
3. <b>return</b> <code>summary</code>.

```python
def _summarize_by_account(self) -> Dict[str, Dict]:
        """Summarize aggregations by account."""
        summary = {}
        for key, agg in self.aggregations.items():
            account = agg.account_number
            if account not in summary:
                summary[account] = {"phases": {}, "total_net_profit": 0.0}
            
            phase_key = f"{agg.phase_code}{agg.trade_number or ''}"
            summary[account]["phases"][phase_key] = agg.net_profit
            summary[account]["total_net_profit"] += agg.net_profit
        
        return summary
```

##### `MT5DealAggregator.to_dashboard_format`

```python
def to_dashboard_format(self) -> List[Dict]
```
> Convert aggregations to dashboard-compatible format.  Returns list of dicts with: - account_number: Account identifier - phase: Phase code (CH, FD, DD, FA) - trade_number: Trade number (1-4) or None - farming_date: Date if farming phase - net_profit: Total net profit for this combination - deal_count: Number of deals

**What it does, step by step:**

1. Assigns <code>result</code> = <code>[]</code>.
2. <b>for</b> <code>(key, agg)</code> in <code>self.aggregations.items()</code>: iterates.
3. <b>return</b> <code>result</code>.

```python
def to_dashboard_format(self) -> List[Dict]:
        """
        Convert aggregations to dashboard-compatible format.
        
        Returns list of dicts with:
        - account_number: Account identifier
        - phase: Phase code (CH, FD, DD, FA)
        - trade_number: Trade number (1-4) or None
        - farming_date: Date if farming phase
        - net_profit: Total net profit for this combination
        - deal_count: Number of deals
        """
        result = []
        for key, agg in self.aggregations.items():
            result.append(agg.to_dict())
        return result
```

**Functions**

#### `get_account_signature`

```python
def get_account_signature(account: str) -> str
```
> Generate account signature from first 4 + last 4/5 characters. Used for matching truncated account numbers.  Handles truncated format with '...' like: FNFT...59574  Examples:     MFFUEVSTP326057008 -> mffu7008 (full account)     FNFT...59574 -> fnft59574 (truncated - use last 5)     MFFU7008 -> mffu7008 (short account)

**What it does, step by step:**

1. <b>if</b> <code>not account</code>: branches conditionally.
2. Assigns <code>account</code> = <code>account.strip()</code>.
3. <b>if</b> <code>'...' in account</code>: branches conditionally.
4. <b>if</b> <code>len(account) &lt;= 8</code>: branches conditionally.
5. <b>return</b> <code>(account[:4] + account[-4:]).lower()</code>.

```python
def get_account_signature(account: str) -> str:
    """
    Generate account signature from first 4 + last 4/5 characters.
    Used for matching truncated account numbers.
    
    Handles truncated format with '...' like: FNFT...59574
    
    Examples:
        MFFUEVSTP326057008 -> mffu7008 (full account)
        FNFT...59574 -> fnft59574 (truncated - use last 5)
        MFFU7008 -> mffu7008 (short account)
    """
    if not account:
        return ""
    account = account.strip()
    
    # Handle truncated format: PREFIX...SUFFIX
    if '...' in account:
        parts = account.split('...')
        if len(parts) == 2:
            prefix = parts[0][:4] if len(parts[0]) >= 4 else parts[0]
            suffix = parts[1]  # Keep full suffix (usually 5 digits)
            return (prefix + suffix).lower()
    
    # Standard format: first 4 + last 4
    if len(account) <= 8:
        return account.lower()
    return (account[:4] + account[-4:]).lower()
```

#### `parse_mt5_comment`

```python
def parse_mt5_comment(comment: str) -> Dict
```
> Convenience function to parse a single MT5 comment.  Args:     comment: MT5 order comment string      Returns:     Dictionary with parsed data:     - account_number: Tradovate account number     - phase: Phase code (CH, FD, DD, FA)     - trade_number: Trade number (1-4) or None for farming     - farming_date: Date if farming phase with date suffix     - is_valid: Whether the comment was successfully parsed

**What it does, step by step:**

1. Assigns <code>parser</code> = <code>MT5CommentParser()</code>.
2. Assigns <code>result</code> = <code>parser.parse(comment)</code>.
3. <b>return</b> <code>result.to_dict()</code>.

```python
def parse_mt5_comment(comment: str) -> Dict:
    """
    Convenience function to parse a single MT5 comment.
    
    Args:
        comment: MT5 order comment string
        
    Returns:
        Dictionary with parsed data:
        - account_number: Tradovate account number
        - phase: Phase code (CH, FD, DD, FA)
        - trade_number: Trade number (1-4) or None for farming
        - farming_date: Date if farming phase with date suffix
        - is_valid: Whether the comment was successfully parsed
    """
    parser = MT5CommentParser()
    result = parser.parse(comment)
    return result.to_dict()
```

#### `aggregate_deals_by_comment`

```python
def aggregate_deals_by_comment(deals: List[Dict]) -> Tuple[List[Dict], List[Dict], List[str]]
```
> Convenience function to aggregate deals by parsed comments.  Args:     deals: List of MT5 deal dictionaries      Returns:     Tuple of (aggregated_data, unmatched_deals, log_messages)

**What it does, step by step:**

1. Assigns <code>aggregator</code> = <code>MT5DealAggregator()</code>.
2. Calls <code>aggregator.process_deals(...)</code> for its side effect.
3. <b>return</b> <code>(aggregator.to_dashboard_format(), aggregator.unmatched_deals, aggr...</code>.

```python
def aggregate_deals_by_comment(deals: List[Dict]) -> Tuple[List[Dict], List[Dict], List[str]]:
    """
    Convenience function to aggregate deals by parsed comments.
    
    Args:
        deals: List of MT5 deal dictionaries
        
    Returns:
        Tuple of (aggregated_data, unmatched_deals, log_messages)
    """
    aggregator = MT5DealAggregator()
    aggregator.process_deals(deals)
    
    return (
        aggregator.to_dashboard_format(),
        aggregator.unmatched_deals,
        aggregator.parse_log
    )
```

#### `aggregate_deals_by_position`

```python
def aggregate_deals_by_position(deals: List[Any]) -> Tuple[List[Dict], List[Dict], List[str]]
```
> Aggregate deals by position_id first, then by comment/phase.  Also handles "Farming" cluster logic: - If Phase is FARMING (FA) and no date in comment, uses Trade Date (Time).  Args:     deals: List of MT5 deal objects or dicts      Returns:     Tuple of (aggregated_data, unmatched_positions, log_messages)

**What it does, step by step:**

1. Assigns <code>parser</code> = <code>MT5CommentParser()</code>.
2. Assigns <code>log_messages</code> = <code>[]</code>.
3. Assigns <code>positions</code> = <code>{}</code>.
4. <b>for</b> <code>deal</code> in <code>deals</code>: iterates.
5. Calls <code>log_messages.append(...)</code> for its side effect.
6. Assigns <code>position_data</code> = <code>[]</code>.
7. Assigns <code>unmatched</code> = <code>[]</code>.
8. <b>for</b> <code>(pid, deal_list)</code> in <code>positions.items()</code>: iterates.
9. Calls <code>log_messages.append(...)</code> for its side effect.
10. Assigns <code>aggregated</code> = <code>{}</code>.
11. <b>for</b> <code>pos</code> in <code>position_data</code>: iterates.
12. <b>for</b> <code>(key, agg)</code> in <code>aggregated.items()</code>: iterates.
13. <b>return</b> <code>(list(aggregated.values()), unmatched, log_messages)</code>.

```python
def aggregate_deals_by_position(deals: List[Any]) -> Tuple[List[Dict], List[Dict], List[str]]:
    """
    Aggregate deals by position_id first, then by comment/phase.
    
    Also handles "Farming" cluster logic:
    - If Phase is FARMING (FA) and no date in comment, uses Trade Date (Time).
    
    Args:
        deals: List of MT5 deal objects or dicts
        
    Returns:
        Tuple of (aggregated_data, unmatched_positions, log_messages)
    """
    parser = MT5CommentParser()
    log_messages = []
    
    # Step 1: Group deals by position_id
    positions = {}
    for deal in deals:
        # Handle both MT5 deal objects and dicts
        if hasattr(deal, '_asdict'):
            d = deal._asdict()
        elif hasattr(deal, 'position_id'):
            d = {
                'position_id': deal.position_id,
                'ticket': deal.ticket,
                'comment': deal.comment,
                'profit': deal.profit,
                'commission': getattr(deal, 'commission', 0),
                'swap': getattr(deal, 'swap', 0),
                'fee': getattr(deal, 'fee', 0),
                'entry': deal.entry,
                'type': deal.type,
                'volume': getattr(deal, 'volume', 0),
                'symbol': getattr(deal, 'symbol', ''),
                'time': getattr(deal, 'time', 0),
            }
        else:
            d = deal
        
        # Skip balance / credit / internal-transfer operations regardless of
        # whether the broker assigned a position_id to them. Some brokers tag
        # "internal transfer" balance ops with a real position_id which would
        # otherwise leak their amount into a hedge aggregate.
        d_type_str = str(d.get('type', '')).upper()
        if d_type_str in ('BALANCE', 'CREDIT', '2', '3', 'CHARGE', 'CORRECTION', 'BONUS'):
            continue
        d_comment_str = str(d.get('comment', '') or '').strip().lower()
        if 'internal transfer' in d_comment_str:
            continue

        pid = d.get('position_id', 0)
        if pid == 0:
            continue  # Skip balance/credit operations

        if pid not in positions:
            positions[pid] = []
        positions[pid].append(d)
    
    log_messages.append(f"Found {len(positions)} positions from {len(deals)} deals")
    
    # Step 2: For each position, find entry deal with comment and sum profits
    position_data = []
    unmatched = []
    
    for pid, deal_list in positions.items():
        # Find entry deal (entry=0/IN) with valid comment, and detect exit deals.
        # 'entry' can be integer (0=IN, 1=OUT, 2=INOUT, 3=OUT_BY) or string ("IN"/"OUT"/"INOUT"/"OUT_BY")
        entry_deal = None
        has_exit_deal = False
        exit_time = 0
        
        total_profit = 0.0
        total_commission = 0.0
        total_swap = 0.0
        total_fee = 0.0
        
        for d in deal_list:
            entry_val = d.get('entry', '')
            # Normalise to string for comparison
            entry_str = str(entry_val).upper() if entry_val != '' else ''
            is_entry = entry_val == 0 or entry_str == 'IN'
            is_exit  = entry_val in (1, 2, 3) or entry_str in ('OUT', 'INOUT', 'OUT_BY')

            if is_entry and entry_deal is None:
                entry_deal = d
            if is_exit:
                has_exit_deal = True
            
            # Track latest time (exit time)
            t = d.get('time_raw', d.get('time', 0))
            if isinstance(t, str):
                try:
                    t = datetime.fromisoformat(t).timestamp()
                except (ValueError, AttributeError):
                    t = 0
            
            if isinstance(t, (int, float)) and t > exit_time:
                exit_time = t
                
            total_profit += d.get('profit', 0) or 0
            total_commission += d.get('commission', 0) or 0
            total_swap += d.get('swap', 0) or 0
            total_fee += d.get('fee', 0) or 0

        # Keep open positions in aggregation. Caller-side push logic decides whether
        # zero-value FA rows should be sent (e.g., only when active positions exist).
        if not has_exit_deal:
            log_messages.append(f"ℹ️ Open position {pid} (no exit deal yet)")
        
        # If no entry deal found, try to find any deal with a valid comment
        if not entry_deal:
            for d in deal_list:
                comment = d.get('comment', '')
                if comment and ('CH' in comment or 'FD' in comment or 'FA' in comment or 'DD' in comment):
                    entry_deal = d
                    break
        
        if not entry_deal:
            entry_deal = deal_list[0]  # Fallback to first deal
        
        comment = entry_deal.get('comment', '')
        parsed = parser.parse(comment)
        
        if not parsed.is_valid or not parsed.account_number:
            unmatched.append({
                'position_id': pid,
                'comment': comment,
                'total_profit': total_profit,
                'deal_count': len(deal_list)
            })
            continue
            
        # --- FARMING DATE INFERENCE ---
        # If Phase is FA but no farming_date, use the exit time date
        if parsed.phase_code == 'FA' and not parsed.farming_date:
            if exit_time > 0:
                parsed.farming_date = datetime.fromtimestamp(exit_time) 
        # -----------------------------
        
        position_data.append({
            'position_id': pid,
            'account_number': parsed.account_number,
            'phase': parsed.phase.value if parsed.phase else None,
            'phase_name': parsed.phase.name if parsed.phase else None,
            'phase_code': parsed.phase_code,
            'trade_number': parsed.trade_number,
            'farming_date': parsed.farming_date.isoformat() if parsed.farming_date else None,
            'timestamp': exit_time, # Store timestamp for sorting
            'total_profit': round(total_profit, 2),
            'total_commission': round(total_commission, 2),
            'total_swap': round(total_swap, 2),
            'total_fee': round(total_fee, 2),
            'net_profit': round(total_profit + total_commission + total_swap + total_fee, 2),
            'deal_count': len(deal_list),
            'has_open_position': not has_exit_deal,
            'account_signature': get_account_signature(parsed.account_number),
            'raw_comment': comment
        })
    
    log_messages.append(f"Matched {len(position_data)} positions, {len(unmatched)} unmatched")
    
    # Step 3: Aggregate by account + phase (in case multiple positions have same account/phase)
    # ALSO group by DATE for Farming if not already specific
    aggregated = {}
    
    for pos in position_data:
        key = f"{pos['account_number']}_{pos['phase_code']}{pos['trade_number'] or ''}"
        
        # For Farming, always append Date to key to separate days
        if pos['phase_code'] == 'FA' and pos.get('farming_date'):
            # Convert ISO string back to date for key or use string slice
            # ISO format: YYYY-MM-DDTHH:MM:SS
            date_str = pos['farming_date'][:10] # YYYY-MM-DD
            key += f"_{date_str}"
        elif pos.get('farming_date'):
            # Some other phases might have dates too (rare)
            date_str = pos['farming_date'][:10].replace('-', '')
            key += f"_{date_str}"
        
        if key not in aggregated:
            aggregated[key] = {
                'account_number': pos['account_number'],
                'phase': pos['phase'],
                'phase_name': pos['phase_name'],
                'phase_code': pos['phase_code'],
                'trade_number': pos['trade_number'],
                'farming_date': pos['farming_date'],
                'total_profit': 0.0,
                'total_commission': 0.0,
                'total_swap': 0.0,
                'total_fee': 0.0,
                'net_profit': 0.0,
                'deal_count': 0,
                'position_count': 0,
                'has_open_position': False,
                'account_signature': pos['account_signature'],
                'key': key,
                'timestamp': pos['timestamp'] # Keep one timestamp
            }
        
        agg = aggregated[key]
        agg['total_profit'] += pos['total_profit']
        agg['total_commission'] += pos['total_commission']
        agg['total_swap'] += pos['total_swap']
        agg['total_fee'] += pos['total_fee']
        agg['net_profit'] += pos['net_profit']
        agg['deal_count'] += pos['deal_count']
        agg['position_count'] += 1
        agg['has_open_position'] = agg['has_open_position'] or bool(pos.get('has_open_position'))
        
        # Update timestamp to latest in group (usually irrelevant for same day)
        if pos['timestamp'] > agg['timestamp']:
            agg['timestamp'] = pos['timestamp']
    
    # Round final values
    for key, agg in aggregated.items():
        agg['total_profit'] = round(agg['total_profit'], 2)
        agg['total_commission'] = round(agg['total_commission'], 2)
        agg['total_swap'] = round(agg['total_swap'], 2)
        agg['total_fee'] = round(agg['total_fee'], 2)
        agg['net_profit'] = round(agg['net_profit'], 2)
    
    return (
        list(aggregated.values()),
        unmatched,
        log_messages
    )
```

---

### `trader_companion/trade_limit_manager.py`

_388 loc · 2 classes · 4 functions · 5 imports_

**Module docstring**

> Trade Limit Manager for Combine-Based Trading Manages trade limits based on the number of combines purchased and active MT5 trades

**Imports**

```python
import sys
import os
import logging
import time
from typing import Dict, List, Optional, Tuple
```

**Classes**

#### `class TradeLimit`

> Represents trade limit information for a combine

```python
class TradeLimit:
    """Represents trade limit information for a combine"""
    def __init__(self, combine_id: str, max_trades: int, account_name: str = ""):
        self.combine_id = combine_id
        self.max_trades = max_trades
        self.account_name = account_name
        self.active_trades = 0
        self.last_check = 0
        
    def can_place_trade(self) -> bool:
        """Check if a new trade can be placed"""
        return self.active_trades < self.max_trades
    
    def remaining_trades(self) -> int:
        """Get number of remaining trade slots"""
        return max(0, self.max_trades - self.active_trades)
```

##### `TradeLimit.__init__`

```python
def __init__(self, combine_id: str, max_trades: int, account_name: str='')
```
**What it does, step by step:**

1. Assigns <code>self.combine_id</code> = <code>combine_id</code>.
2. Assigns <code>self.max_trades</code> = <code>max_trades</code>.
3. Assigns <code>self.account_name</code> = <code>account_name</code>.
4. Assigns <code>self.active_trades</code> = <code>0</code>.
5. Assigns <code>self.last_check</code> = <code>0</code>.

```python
def __init__(self, combine_id: str, max_trades: int, account_name: str = ""):
        self.combine_id = combine_id
        self.max_trades = max_trades
        self.account_name = account_name
        self.active_trades = 0
        self.last_check = 0
```

##### `TradeLimit.can_place_trade`

```python
def can_place_trade(self) -> bool
```
> Check if a new trade can be placed

**What it does, step by step:**

1. <b>return</b> <code>self.active_trades &lt; self.max_trades</code>.

```python
def can_place_trade(self) -> bool:
        """Check if a new trade can be placed"""
        return self.active_trades < self.max_trades
```

##### `TradeLimit.remaining_trades`

```python
def remaining_trades(self) -> int
```
> Get number of remaining trade slots

**What it does, step by step:**

1. <b>return</b> <code>max(0, self.max_trades - self.active_trades)</code>.

```python
def remaining_trades(self) -> int:
        """Get number of remaining trade slots"""
        return max(0, self.max_trades - self.active_trades)
```

#### `class TradeLimitManager`

> Manages trade limits across multiple combines

```python
class TradeLimitManager:
    """Manages trade limits across multiple combines"""
    
    def __init__(self, max_trades: int = 5):
        self.combines: Dict[str, TradeLimit] = {}
        self.mt5 = None
        self.last_mt5_check = 0
        self.check_interval = 5  # Check MT5 every 5 seconds
        self.max_trades = max_trades  # Store the max trades limit
        
        # Default combine configurations
        self.default_combines = {
            "5_combine": 5,
            "10_combine": 10,
            "15_combine": 15,
            "20_combine": 20
        }
        
        # Add a default combine with the specified max trades
        self.add_combine("default", max_trades, "Default Account")
        
        self._initialize_mt5()
        
    def _initialize_mt5(self):
        """Initialize MT5 connection - MT5 API will be set by the main application"""
        # MT5 API instance will be set by the application through set_mt5_api() method
        self.mt5 = None
    
    def add_combine(self, combine_id: str, max_trades: int, account_name: str = "") -> bool:
        """Add a new combine with specified trade limit"""
        try:
            self.combines[combine_id] = TradeLimit(combine_id, max_trades, account_name)
            logging.info(f"✅ Added combine {combine_id} with {max_trades} trade limit")
            return True
        except Exception as e:
            logging.error(f"❌ Failed to add combine {combine_id}: {e}")
            return False
    
    def remove_combine(self, combine_id: str) -> bool:
        """Remove a combine"""
        try:
            if combine_id in self.combines:
                del self.combines[combine_id]
                logging.info(f"✅ Removed combine {combine_id}")
                return True
            else:
                logging.warning(f"⚠️ Combine {combine_id} not found")
                return False
        except Exception as e:
            logging.error(f"❌ Failed to remove combine {combine_id}: {e}")
            return False
    
    def set_mt5_api(self, mt5_api):
        """Set the MT5 API instance from the main application"""
        self.mt5 = mt5_api
        if mt5_api:
            logging.info("✅ MT5 API set for trade limit checking")
        
    def get_active_trades_from_mt5(self) -> int:
        """Get number of active trades from MT5 terminal"""
        if not self.mt5:
            return 0
        
        try:
            # Initialize MT5 if not already done
            if not self.mt5.initialize():
                logging.error("❌ Failed to initialize MT5 for trade checking")
                return 0
            
            # Get all open positions
            positions = self.mt5.positions_get()
            if positions is None:
                positions = []
            
            active_count = len(positions)
            logging.info(f"📊 MT5 active trades: {active_count}")
            
            # Get detailed position info
            if active_count > 0:
                logging.info("📋 Active positions:")
                for i, pos in enumerate(positions):
                    symbol = pos.symbol
                    volume = pos.volume
                    position_type = "BUY" if pos.type == 0 else "SELL"
                    profit = pos.profit
                    logging.info(f"   {i+1}. {symbol} {position_type} {volume} lots (P&L: {profit:.2f})")
            
            # Shutdown MT5 connection
            self.mt5.shutdown()
            
            return active_count
            
        except Exception as e:
            logging.error(f"❌ Error checking MT5 active trades: {e}")
            try:
                self.mt5.shutdown()
            except:
                pass
            return 0
    
    def update_active_trades_all_combines(self) -> bool:
        """Update active trade counts for all combines from MT5"""
        current_time = time.time()
        
        # Only check if enough time has passed
        if current_time - self.last_mt5_check < self.check_interval:
            return True
        
        try:
            total_active = self.get_active_trades_from_mt5()
            
            # Update all combines with current active trade count
            for combine_id, combine in self.combines.items():
                combine.active_trades = total_active
                combine.last_check = current_time
                logging.info(f"📊 {combine_id}: {combine.active_trades}/{combine.max_trades} trades active")
            
            self.last_mt5_check = current_time
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to update active trades: {e}")
            return False
    
    def can_place_trade(self, combine_id: str = None) -> Tuple[bool, str]:
        """
        Check if a new trade can be placed
        Returns: (can_place, reason)
        """
        # Update active trades from MT5
        self.update_active_trades_all_combines()
        
        # Use default combine if none specified
        if not combine_id:
            combine_id = "default"
        
        if combine_id in self.combines:
            # Check specific combine
            combine = self.combines[combine_id]
            if combine.can_place_trade():
                remaining = combine.remaining_trades()
                return True, f"✅ Can place trade. {remaining} slots remaining for {combine_id}"
            else:
                error_message = f"❌ Trade limit reached for {combine_id} ({combine.active_trades}/{combine.max_trades})"
                
                # Show popup alert for trade limit exceeded
                popup_message = (f"🚨 TRADE LIMIT EXCEEDED 🚨\n\n"
                               f"Account: {combine_id}\n"
                               f"Active Trades: {combine.active_trades}\n"
                               f"Maximum Allowed: {combine.max_trades}\n\n"
                               f"You have reached your combine purchase limit!\n"
                               f"Close existing trades or purchase more combines to continue trading.")
                
                show_trade_limit_alert(popup_message, "Trade Limit Exceeded")
                
                return False, error_message
        
        elif self.combines:
            # Check if any combine allows trading
            available_combines = []
            for cid, combine in self.combines.items():
                if combine.can_place_trade():
                    available_combines.append((cid, combine.remaining_trades()))
            
            if available_combines:
                total_remaining = sum(remaining for _, remaining in available_combines)
                combine_names = ", ".join(f"{cid}({remaining})" for cid, remaining in available_combines)
                return True, f"✅ Can place trade. Available combines: {combine_names}"
            else:
                active_info = ", ".join(f"{cid}({c.active_trades}/{c.max_trades})" 
                                      for cid, c in self.combines.items())
                error_message = f"❌ All trade limits reached. Active: {active_info}"
                
                # Show popup alert for all limits exceeded
                popup_message = (f"🚨 ALL TRADE LIMITS EXCEEDED 🚨\n\n"
                               f"All your combines have reached their maximum trades:\n"
                               f"{active_info}\n\n"
                               f"Please close existing trades or purchase more combines to continue trading.")
                
                show_trade_limit_alert(popup_message, "All Trade Limits Exceeded")
                
                return False, error_message
        
        else:
            error_message = "❌ No combines configured"
            show_trade_limit_alert("No trading combines configured! Please set up your combine limits.", "Configuration Error")
            return False, error_message
    
    def get_current_trade_count(self) -> int:
        """Get the current number of active trades from MT5"""
        try:
            return self.get_active_trades_from_mt5()
        except Exception as e:
            logging.error(f"Failed to get current trade count: {e}")
            return 0
    
    def get_trade_summary(self) -> Dict:
        """Get comprehensive trade limit summary"""
        self.update_active_trades_all_combines()
        
        summary = {
            "total_combines": len(self.combines),
            "total_max_trades": sum(c.max_trades for c in self.combines.values()),
            "total_active_trades": sum(c.active_trades for c in self.combines.values()),
            "total_remaining": sum(c.remaining_trades() for c in self.combines.values()),
            "mt5_active_trades": self.get_active_trades_from_mt5() if self.mt5 else 0,
            "combines": {}
        }
        
        for combine_id, combine in self.combines.items():
            summary["combines"][combine_id] = {
                "max_trades": combine.max_trades,
                "active_trades": combine.active_trades,
                "remaining": combine.remaining_trades(),
                "can_trade": combine.can_place_trade(),
                "account_name": combine.account_name
            }
        
        return summary
    
    def print_trade_status(self):
        """Print detailed trade status"""
        summary = self.get_trade_summary()
        
        print("\n" + "="*60)
        print("📊 TRADE LIMIT STATUS")
        print("="*60)
        
        print(f"🎯 Total Combines: {summary['total_combines']}")
        print(f"📈 Total Trade Capacity: {summary['total_max_trades']}")
        print(f"⚡ Active Trades (MT5): {summary['mt5_active_trades']}")
        print(f"🟢 Available Slots: {summary['total_remaining']}")
        
        if summary['combines']:
            print(f"\n📋 COMBINE DETAILS:")
            for combine_id, info in summary['combines'].items():
                status = "🟢 Available" if info['can_trade'] else "🔴 Full"
                account_info = f" ({info['account_name']})" if info['account_name'] else ""
                print(f"   {combine_id}{account_info}: {info['active_trades']}/{info['max_trades']} {status}")
        
        can_trade, reason = self.can_place_trade()
        print(f"\n🎯 TRADE STATUS: {reason}")
        print("="*60)
    
    def load_combines_from_config(self, config_file: str = "combine_config.txt") -> bool:
        """Load combine configuration from file"""
        try:
            if not os.path.exists(config_file):
                # Create default config file
                self.create_default_config(config_file)
            
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split(',')
                        if len(parts) >= 2:
                            combine_id = parts[0].strip()
                            max_trades = int(parts[1].strip())
                            account_name = parts[2].strip() if len(parts) > 2 else ""
                            self.add_combine(combine_id, max_trades, account_name)
            
            logging.info(f"✅ Loaded combines from {config_file}")
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to load combines from {config_file}: {e}")
            return False
    
    def create_default_config(self, config_file: str = "combine_config.txt"):
        """Create default combine configuration file"""
        try:
            with open(config_file, 'w') as f:
                f.write("# Combine Configuration File\n")
                f.write("# Format: combine_id, max_trades, account_name (optional)\n")
                f.write("# Example: 5_combine, 5, Main Account\n\n")
                
                f.write("# Default configurations (modify as needed)\n")
                f.write("5_combine, 5, Primary\n")
                f.write("# 10_combine, 10, Secondary\n")
                f.write("# 15_combine, 15, Advanced\n")
                f.write("# 20_combine, 20, Professional\n")
            
            logging.info(f"✅ Created default config file: {config_file}")
            
        except Exception as e:
            logging.error(f"❌ Failed to create default config: {e}")
```

##### `TradeLimitManager.__init__`

```python
def __init__(self, max_trades: int=5)
```
**What it does, step by step:**

1. Declares <code>self.combines: Dict[str, TradeLimit]</code> = <code>{}</code>.
2. Assigns <code>self.mt5</code> = <code>None</code>.
3. Assigns <code>self.last_mt5_check</code> = <code>0</code>.
4. Assigns <code>self.check_interval</code> = <code>5</code>.
5. Assigns <code>self.max_trades</code> = <code>max_trades</code>.
6. Assigns <code>self.default_combines</code> = <code>{'5_combine': 5, '10_combine': 10, '15_combine': 15, '20_...</code>.
7. Calls <code>self.add_combine(...)</code> for its side effect.
8. Calls <code>self._initialize_mt5(...)</code> for its side effect.

```python
def __init__(self, max_trades: int = 5):
        self.combines: Dict[str, TradeLimit] = {}
        self.mt5 = None
        self.last_mt5_check = 0
        self.check_interval = 5  # Check MT5 every 5 seconds
        self.max_trades = max_trades  # Store the max trades limit
        
        # Default combine configurations
        self.default_combines = {
            "5_combine": 5,
            "10_combine": 10,
            "15_combine": 15,
            "20_combine": 20
        }
        
        # Add a default combine with the specified max trades
        self.add_combine("default", max_trades, "Default Account")
        
        self._initialize_mt5()
```

##### `TradeLimitManager._initialize_mt5`

```python
def _initialize_mt5(self)
```
> Initialize MT5 connection - MT5 API will be set by the main application

**What it does, step by step:**

1. Assigns <code>self.mt5</code> = <code>None</code>.

```python
def _initialize_mt5(self):
        """Initialize MT5 connection - MT5 API will be set by the main application"""
        # MT5 API instance will be set by the application through set_mt5_api() method
        self.mt5 = None
```

##### `TradeLimitManager.add_combine`

```python
def add_combine(self, combine_id: str, max_trades: int, account_name: str='') -> bool
```
> Add a new combine with specified trade limit

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def add_combine(self, combine_id: str, max_trades: int, account_name: str = "") -> bool:
        """Add a new combine with specified trade limit"""
        try:
            self.combines[combine_id] = TradeLimit(combine_id, max_trades, account_name)
            logging.info(f"✅ Added combine {combine_id} with {max_trades} trade limit")
            return True
        except Exception as e:
            logging.error(f"❌ Failed to add combine {combine_id}: {e}")
            return False
```

##### `TradeLimitManager.remove_combine`

```python
def remove_combine(self, combine_id: str) -> bool
```
> Remove a combine

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def remove_combine(self, combine_id: str) -> bool:
        """Remove a combine"""
        try:
            if combine_id in self.combines:
                del self.combines[combine_id]
                logging.info(f"✅ Removed combine {combine_id}")
                return True
            else:
                logging.warning(f"⚠️ Combine {combine_id} not found")
                return False
        except Exception as e:
            logging.error(f"❌ Failed to remove combine {combine_id}: {e}")
            return False
```

##### `TradeLimitManager.set_mt5_api`

```python
def set_mt5_api(self, mt5_api)
```
> Set the MT5 API instance from the main application

**What it does, step by step:**

1. Assigns <code>self.mt5</code> = <code>mt5_api</code>.
2. <b>if</b> <code>mt5_api</code>: branches conditionally.

```python
def set_mt5_api(self, mt5_api):
        """Set the MT5 API instance from the main application"""
        self.mt5 = mt5_api
        if mt5_api:
            logging.info("✅ MT5 API set for trade limit checking")
```

##### `TradeLimitManager.get_active_trades_from_mt5`

```python
def get_active_trades_from_mt5(self) -> int
```
> Get number of active trades from MT5 terminal

**What it does, step by step:**

1. <b>if</b> <code>not self.mt5</code>: branches conditionally.
2. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_active_trades_from_mt5(self) -> int:
        """Get number of active trades from MT5 terminal"""
        if not self.mt5:
            return 0
        
        try:
            # Initialize MT5 if not already done
            if not self.mt5.initialize():
                logging.error("❌ Failed to initialize MT5 for trade checking")
                return 0
            
            # Get all open positions
            positions = self.mt5.positions_get()
            if positions is None:
                positions = []
            
            active_count = len(positions)
            logging.info(f"📊 MT5 active trades: {active_count}")
            
            # Get detailed position info
            if active_count > 0:
                logging.info("📋 Active positions:")
                for i, pos in enumerate(positions):
                    symbol = pos.symbol
                    volume = pos.volume
                    position_type = "BUY" if pos.type == 0 else "SELL"
                    profit = pos.profit
                    logging.info(f"   {i+1}. {symbol} {position_type} {volume} lots (P&L: {profit:.2f})")
            
            # Shutdown MT5 connection
            self.mt5.shutdown()
            
            return active_count
            
        except Exception as e:
            logging.error(f"❌ Error checking MT5 active trades: {e}")
            try:
                self.mt5.shutdown()
            except:
                pass
            return 0
```

##### `TradeLimitManager.update_active_trades_all_combines`

```python
def update_active_trades_all_combines(self) -> bool
```
> Update active trade counts for all combines from MT5

**What it does, step by step:**

1. Assigns <code>current_time</code> = <code>time.time()</code>.
2. <b>if</b> <code>current_time - self.last_mt5_check &lt; self.check_interval</code>: branches conditionally.
3. <b>try</b> block with 1 <b>except</b> clause.

```python
def update_active_trades_all_combines(self) -> bool:
        """Update active trade counts for all combines from MT5"""
        current_time = time.time()
        
        # Only check if enough time has passed
        if current_time - self.last_mt5_check < self.check_interval:
            return True
        
        try:
            total_active = self.get_active_trades_from_mt5()
            
            # Update all combines with current active trade count
            for combine_id, combine in self.combines.items():
                combine.active_trades = total_active
                combine.last_check = current_time
                logging.info(f"📊 {combine_id}: {combine.active_trades}/{combine.max_trades} trades active")
            
            self.last_mt5_check = current_time
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to update active trades: {e}")
            return False
```

##### `TradeLimitManager.can_place_trade`

```python
def can_place_trade(self, combine_id: str=None) -> Tuple[bool, str]
```
> Check if a new trade can be placed Returns: (can_place, reason)

**What it does, step by step:**

1. Calls <code>self.update_active_trades_all_combines(...)</code> for its side effect.
2. <b>if</b> <code>not combine_id</code>: branches conditionally.
3. <b>if</b> <code>combine_id in self.combines</code>: branches conditionally (with an <b>else</b>/elif arm).

```python
def can_place_trade(self, combine_id: str = None) -> Tuple[bool, str]:
        """
        Check if a new trade can be placed
        Returns: (can_place, reason)
        """
        # Update active trades from MT5
        self.update_active_trades_all_combines()
        
        # Use default combine if none specified
        if not combine_id:
            combine_id = "default"
        
        if combine_id in self.combines:
            # Check specific combine
            combine = self.combines[combine_id]
            if combine.can_place_trade():
                remaining = combine.remaining_trades()
                return True, f"✅ Can place trade. {remaining} slots remaining for {combine_id}"
            else:
                error_message = f"❌ Trade limit reached for {combine_id} ({combine.active_trades}/{combine.max_trades})"
                
                # Show popup alert for trade limit exceeded
                popup_message = (f"🚨 TRADE LIMIT EXCEEDED 🚨\n\n"
                               f"Account: {combine_id}\n"
                               f"Active Trades: {combine.active_trades}\n"
                               f"Maximum Allowed: {combine.max_trades}\n\n"
                               f"You have reached your combine purchase limit!\n"
                               f"Close existing trades or purchase more combines to continue trading.")
                
                show_trade_limit_alert(popup_message, "Trade Limit Exceeded")
                
                return False, error_message
        
        elif self.combines:
            # Check if any combine allows trading
            available_combines = []
            for cid, combine in self.combines.items():
                if combine.can_place_trade():
                    available_combines.append((cid, combine.remaining_trades()))
            
            if available_combines:
                total_remaining = sum(remaining for _, remaining in available_combines)
                combine_names = ", ".join(f"{cid}({remaining})" for cid, remaining in available_combines)
                return True, f"✅ Can place trade. Available combines: {combine_names}"
            else:
                active_info = ", ".join(f"{cid}({c.active_trades}/{c.max_trades})" 
                                      for cid, c in self.combines.items())
                error_message = f"❌ All trade limits reached. Active: {active_info}"
                
                # Show popup alert for all limits exceeded
                popup_message = (f"🚨 ALL TRADE LIMITS EXCEEDED 🚨\n\n"
                               f"All your combines have reached their maximum trades:\n"
                               f"{active_info}\n\n"
                               f"Please close existing trades or purchase more combines to continue trading.")
                
                show_trade_limit_alert(popup_message, "All Trade Limits Exceeded")
                
                return False, error_message
        
        else:
            error_message = "❌ No combines configured"
            show_trade_limit_alert("No trading combines configured! Please set up your combine limits.", "Configuration Error")
            return False, error_message
```

##### `TradeLimitManager.get_current_trade_count`

```python
def get_current_trade_count(self) -> int
```
> Get the current number of active trades from MT5

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_current_trade_count(self) -> int:
        """Get the current number of active trades from MT5"""
        try:
            return self.get_active_trades_from_mt5()
        except Exception as e:
            logging.error(f"Failed to get current trade count: {e}")
            return 0
```

##### `TradeLimitManager.get_trade_summary`

```python
def get_trade_summary(self) -> Dict
```
> Get comprehensive trade limit summary

**What it does, step by step:**

1. Calls <code>self.update_active_trades_all_combines(...)</code> for its side effect.
2. Assigns <code>summary</code> = <code>{'total_combines': len(self.combines), 'total_max_trades'...</code>.
3. <b>for</b> <code>(combine_id, combine)</code> in <code>self.combines.items()</code>: iterates.
4. <b>return</b> <code>summary</code>.

```python
def get_trade_summary(self) -> Dict:
        """Get comprehensive trade limit summary"""
        self.update_active_trades_all_combines()
        
        summary = {
            "total_combines": len(self.combines),
            "total_max_trades": sum(c.max_trades for c in self.combines.values()),
            "total_active_trades": sum(c.active_trades for c in self.combines.values()),
            "total_remaining": sum(c.remaining_trades() for c in self.combines.values()),
            "mt5_active_trades": self.get_active_trades_from_mt5() if self.mt5 else 0,
            "combines": {}
        }
        
        for combine_id, combine in self.combines.items():
            summary["combines"][combine_id] = {
                "max_trades": combine.max_trades,
                "active_trades": combine.active_trades,
                "remaining": combine.remaining_trades(),
                "can_trade": combine.can_place_trade(),
                "account_name": combine.account_name
            }
        
        return summary
```

##### `TradeLimitManager.print_trade_status`

```python
def print_trade_status(self)
```
> Print detailed trade status

**What it does, step by step:**

1. Assigns <code>summary</code> = <code>self.get_trade_summary()</code>.
2. Calls <code>print(...)</code> for its side effect.
3. Calls <code>print(...)</code> for its side effect.
4. Calls <code>print(...)</code> for its side effect.
5. Calls <code>print(...)</code> for its side effect.
6. Calls <code>print(...)</code> for its side effect.
7. Calls <code>print(...)</code> for its side effect.
8. Calls <code>print(...)</code> for its side effect.
9. <b>if</b> <code>summary['combines']</code>: branches conditionally.
10. Assigns <code>(can_trade, reason)</code> = <code>self.can_place_trade()</code>.
11. Calls <code>print(...)</code> for its side effect.
12. Calls <code>print(...)</code> for its side effect.

```python
def print_trade_status(self):
        """Print detailed trade status"""
        summary = self.get_trade_summary()
        
        print("\n" + "="*60)
        print("📊 TRADE LIMIT STATUS")
        print("="*60)
        
        print(f"🎯 Total Combines: {summary['total_combines']}")
        print(f"📈 Total Trade Capacity: {summary['total_max_trades']}")
        print(f"⚡ Active Trades (MT5): {summary['mt5_active_trades']}")
        print(f"🟢 Available Slots: {summary['total_remaining']}")
        
        if summary['combines']:
            print(f"\n📋 COMBINE DETAILS:")
            for combine_id, info in summary['combines'].items():
                status = "🟢 Available" if info['can_trade'] else "🔴 Full"
                account_info = f" ({info['account_name']})" if info['account_name'] else ""
                print(f"   {combine_id}{account_info}: {info['active_trades']}/{info['max_trades']} {status}")
        
        can_trade, reason = self.can_place_trade()
        print(f"\n🎯 TRADE STATUS: {reason}")
        print("="*60)
```

##### `TradeLimitManager.load_combines_from_config`

```python
def load_combines_from_config(self, config_file: str='combine_config.txt') -> bool
```
> Load combine configuration from file

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def load_combines_from_config(self, config_file: str = "combine_config.txt") -> bool:
        """Load combine configuration from file"""
        try:
            if not os.path.exists(config_file):
                # Create default config file
                self.create_default_config(config_file)
            
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split(',')
                        if len(parts) >= 2:
                            combine_id = parts[0].strip()
                            max_trades = int(parts[1].strip())
                            account_name = parts[2].strip() if len(parts) > 2 else ""
                            self.add_combine(combine_id, max_trades, account_name)
            
            logging.info(f"✅ Loaded combines from {config_file}")
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to load combines from {config_file}: {e}")
            return False
```

##### `TradeLimitManager.create_default_config`

```python
def create_default_config(self, config_file: str='combine_config.txt')
```
> Create default combine configuration file

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def create_default_config(self, config_file: str = "combine_config.txt"):
        """Create default combine configuration file"""
        try:
            with open(config_file, 'w') as f:
                f.write("# Combine Configuration File\n")
                f.write("# Format: combine_id, max_trades, account_name (optional)\n")
                f.write("# Example: 5_combine, 5, Main Account\n\n")
                
                f.write("# Default configurations (modify as needed)\n")
                f.write("5_combine, 5, Primary\n")
                f.write("# 10_combine, 10, Secondary\n")
                f.write("# 15_combine, 15, Advanced\n")
                f.write("# 20_combine, 20, Professional\n")
            
            logging.info(f"✅ Created default config file: {config_file}")
            
        except Exception as e:
            logging.error(f"❌ Failed to create default config: {e}")
```

**Functions**

#### `show_trade_limit_alert`

```python
def show_trade_limit_alert(message: str, title: str='Trade Limit Exceeded')
```
> Show a popup alert when trade limits are exceeded

**What it does, step by step:**

1. <b>if</b> <code>POPUP_AVAILABLE</code>: branches conditionally (with an <b>else</b>/elif arm).

```python
def show_trade_limit_alert(message: str, title: str = "Trade Limit Exceeded"):
    """
    Show a popup alert when trade limits are exceeded
    """
    if POPUP_AVAILABLE:
        try:
            # Create a temporary root window (hidden)
            root = tk.Tk()
            root.withdraw()  # Hide the main window
            
            # Show the error message
            messagebox.showerror(title, message)
            
            # Destroy the root window
            root.destroy()
            
        except Exception as e:
            logging.error(f"Failed to show popup alert: {e}")
            print(f"⚠️ Popup alert failed: {message}")
    else:
        # Fallback to console output
        print(f"🚨 {title}: {message}")
```

#### `check_trade_limit`

```python
def check_trade_limit(combine_id: str=None) -> Tuple[bool, str]
```
> Quick function to check if a trade can be placed Returns: (can_place, reason)

**What it does, step by step:**

1. <b>return</b> <code>trade_limit_manager.can_place_trade(combine_id)</code>.

```python
def check_trade_limit(combine_id: str = None) -> Tuple[bool, str]:
    """
    Quick function to check if a trade can be placed
    Returns: (can_place, reason)
    """
    return trade_limit_manager.can_place_trade(combine_id)
```

#### `get_trade_summary`

```python
def get_trade_summary() -> Dict
```
> Get current trade limit summary

**What it does, step by step:**

1. <b>return</b> <code>trade_limit_manager.get_trade_summary()</code>.

```python
def get_trade_summary() -> Dict:
    """Get current trade limit summary"""
    return trade_limit_manager.get_trade_summary()
```

#### `initialize_trade_limits`

```python
def initialize_trade_limits(config_file: str='combine_config.txt') -> bool
```
> Initialize trade limits from configuration

**What it does, step by step:**

1. <b>return</b> <code>trade_limit_manager.load_combines_from_config(config_file)</code>.

```python
def initialize_trade_limits(config_file: str = "combine_config.txt") -> bool:
    """Initialize trade limits from configuration"""
    return trade_limit_manager.load_combines_from_config(config_file)
```

---

### `trader_companion/hedge_protector.py`

> File not present in this checkout — skipped.
