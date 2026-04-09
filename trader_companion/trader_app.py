import sys
import os

# Fix SSL certificates for PyInstaller-bundled exe (HTTPS connections to production)
if hasattr(sys, '_MEIPASS'):
    _cert = os.path.join(sys._MEIPASS, 'certifi', 'cacert.pem')
    if os.path.exists(_cert):
        os.environ['REQUESTS_CA_BUNDLE'] = _cert
        os.environ['SSL_CERT_FILE'] = _cert

# Ensure utils and bundled packages are importable when running as PyInstaller bundle
if hasattr(sys, '_MEIPASS'):
    sys.path.insert(0, sys._MEIPASS)
    sys.path.insert(0, os.path.join(sys._MEIPASS, 'utils'))
    # Add DLL search directory for bundled .pyd files (MetaTrader5 _core etc.)
    _mt5_dir = os.path.join(sys._MEIPASS, 'MetaTrader5')
    if os.path.isdir(_mt5_dir):
        os.add_dll_directory(sys._MEIPASS)
        os.add_dll_directory(_mt5_dir)
    os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ.get('PATH', '')
APP_VERSION = "1.1"
"""
Tradeopss AI
A desktop application for traders to push their MT5 data to the Trading Dashboard.
"""
import sys
import os
import json
import requests
import time
from datetime import datetime
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import re
import random

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext, simpledialog, filedialog
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False
    print("Tkinter not available - running in console mode")

try:
    import customtkinter as ctk
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except Exception as e:
    MT5_AVAILABLE = False
    import traceback
    _mt5_err = traceback.format_exc()
    print(f"MetaTrader5 import failed: {type(e).__name__}: {e}")
    print(_mt5_err)

# Import new comment parser
try:
    from trader_companion.mt5_comment_parser import (
        MT5CommentParser, MT5DealAggregator, Phase,
        parse_mt5_comment, aggregate_deals_by_comment, aggregate_deals_by_position
    )
    COMMENT_PARSER_AVAILABLE = True
except ImportError:
    try:
        from mt5_comment_parser import (
            MT5CommentParser, MT5DealAggregator, Phase,
            parse_mt5_comment, aggregate_deals_by_comment, aggregate_deals_by_position
        )
        COMMENT_PARSER_AVAILABLE = True
    except ImportError:
        COMMENT_PARSER_AVAILABLE = False
        print("MT5 Comment Parser module not found.")

# ============ Trading Engine Imports (from TradeAccountConnector) ============
try:
    from trader_companion.mt5_trading import MT5API, get_installed_mt5_terminals
    TRADING_ENGINE_AVAILABLE = True
except ImportError:
    try:
        from mt5_trading import MT5API, get_installed_mt5_terminals
        TRADING_ENGINE_AVAILABLE = True
    except ImportError:
        TRADING_ENGINE_AVAILABLE = False
        MT5API = None

try:
    from trader_companion.prop_firm_manager import PropFirmManager
    PROP_FIRM_AVAILABLE = True
except ImportError:
    try:
        from prop_firm_manager import PropFirmManager
        PROP_FIRM_AVAILABLE = True
    except ImportError:
        PROP_FIRM_AVAILABLE = False
        PropFirmManager = None

try:
    from trader_companion.tradovate import TradovateAccount
    TRADOVATE_AVAILABLE = True
except Exception as _trado_err:
    try:
        from tradovate import TradovateAccount
        TRADOVATE_AVAILABLE = True
        _trado_err = None
    except Exception as _trado_err2:
        TRADOVATE_AVAILABLE = False
        TradovateAccount = None
        _trado_err = _trado_err2
_TRADOVATE_IMPORT_ERROR = str(_trado_err) if not TRADOVATE_AVAILABLE and '_trado_err' in dir() and _trado_err else None

try:
    from trader_companion.topstepx import TopStepXAccount
    TOPSTEPX_AVAILABLE = True
except Exception as _tsx_err:
    try:
        from topstepx import TopStepXAccount
        TOPSTEPX_AVAILABLE = True
        _tsx_err = None
    except Exception as _tsx_err2:
        TOPSTEPX_AVAILABLE = False
        TopStepXAccount = None
        _tsx_err = _tsx_err2
_TOPSTEPX_IMPORT_ERROR = str(_tsx_err) if not TOPSTEPX_AVAILABLE and '_tsx_err' in dir() and _tsx_err else None

try:
    from trader_companion.fundednext import FundedNextAccount
    FUNDEDNEXT_AVAILABLE = True
except Exception as _fn_err:
    try:
        from fundednext import FundedNextAccount
        FUNDEDNEXT_AVAILABLE = True
        _fn_err = None
    except Exception as _fn_err2:
        FUNDEDNEXT_AVAILABLE = False
        FundedNextAccount = None
        _fn_err = _fn_err2
_FUNDEDNEXT_IMPORT_ERROR = str(_fn_err) if not FUNDEDNEXT_AVAILABLE and '_fn_err' in dir() and _fn_err else None

# CDP-based prop firm scrapers (Tradeify, Lucid Trading, TopStep dashboard, MFFU, FundedNext)
try:
    from trader_companion.prop_firm_scrapers import (
        TradeifyAccount, LucidTradingAccount, TopStepAccount, MFFUAccount,
        FundedNextCDPAccount, ensure_chrome_debug)
    CDP_SCRAPERS_AVAILABLE = True
except Exception:
    try:
        from prop_firm_scrapers import (
            TradeifyAccount, LucidTradingAccount, TopStepAccount, MFFUAccount,
            FundedNextCDPAccount, ensure_chrome_debug)
        CDP_SCRAPERS_AVAILABLE = True
    except Exception:
        CDP_SCRAPERS_AVAILABLE = False
        TradeifyAccount = LucidTradingAccount = TopStepAccount = MFFUAccount = None
        FundedNextCDPAccount = None
        ensure_chrome_debug = None

try:
    from trader_companion.trade_limit_manager import TradeLimitManager
except ImportError:
    try:
        from trade_limit_manager import TradeLimitManager
    except ImportError:
        TradeLimitManager = None

try:
    from trader_companion.signals.rsi import get_rsi_signal
    from trader_companion.signals.macd import get_macd_signal
    from trader_companion.signals.stochastic import get_stochastic_signal
    from trader_companion.signals.cci import get_cci_signal
    from trader_companion.signals.supertrend import get_supertrend_signal
    from trader_companion.signals.momentum import get_momentum_signal
    from trader_companion.signals.bb import get_bb_signal
    SIGNALS_AVAILABLE = True
except ImportError:
    try:
        from signals.rsi import get_rsi_signal
        from signals.macd import get_macd_signal
        from signals.stochastic import get_stochastic_signal
        from signals.cci import get_cci_signal
        from signals.supertrend import get_supertrend_signal
        from signals.momentum import get_momentum_signal
        from signals.bb import get_bb_signal
        SIGNALS_AVAILABLE = True
    except ImportError:
        SIGNALS_AVAILABLE = False
        get_rsi_signal = None

try:
    import pytz
except ImportError:
    pytz = None


class MT5DataPusher:
    """Handles MT5 data extraction and API pushing."""
    
    def __init__(self, dashboard_url="http://127.0.0.1:5001", api_key=None):
        self.dashboard_url = dashboard_url.rstrip('/')
        self.api_key = api_key
        self.connected = False
        self.login = None
        self.server = None
        
    def connect_mt5(self, login=None, password=None, server=None, terminal_path=None):
        """Connect to MT5 terminal."""
        if not MT5_AVAILABLE:
            err_detail = globals().get('_mt5_err', 'unknown')
            return False, f"MetaTrader5 module not installed.\n{err_detail}"
        
        init_params = {}
        if terminal_path:
            init_params['path'] = terminal_path
            
        if not mt5.initialize(**init_params):
            error = mt5.last_error()
            return False, f"MT5 initialization failed: {error}"
        
        if login and password and server:
            try:
                login_int = int(login)
            except ValueError:
                return False, "Login must be a number"
                
            if not mt5.login(login_int, password=password, server=server):
                error = mt5.last_error()
                return False, f"MT5 login failed: {error}"
            
            self.login = login_int
            self.server = server
        
        self.connected = True
        account = mt5.account_info()
        if account:
            # Update server info from actual account connection if not manually provided
            if not self.server:
                self.server = account.server
            # Also store company for FNFT detection
            self.company = account.company
            return True, f"Connected to account #{account.login} ({account.server})"
        return True, "Connected to MT5 (no account logged in)"
    
    def disconnect_mt5(self):
        """Disconnect from MT5."""
        if MT5_AVAILABLE:
            mt5.shutdown()
        self.connected = False
        return True, "Disconnected from MT5"
    
    def get_account_info(self):
        """Get account information including calculated deposits/withdrawals."""
        if not self.connected:
            return None
        
        account = mt5.account_info()
        if not account:
            return None
        
        # Calculate deposits/withdrawals from deal history (BALANCE type = 2)
        total_deposits = 0.0
        total_withdrawals = 0.0
        try:
            from_timestamp = 0  # From the beginning
            to_timestamp = time.time() + 86400
            deals = mt5.history_deals_get(from_timestamp, to_timestamp)
            if deals:
                for deal in deals:
                    if deal.type == 2:  # DEAL_TYPE_BALANCE
                        if deal.profit > 0:
                            total_deposits += deal.profit
                        else:
                            total_withdrawals += deal.profit
        except Exception as e:
            print(f"Error calculating deposits/withdrawals: {e}")
            
        return {
            "login": account.login,
            "server": account.server,
            "balance": account.balance,
            "equity": account.equity,
            "profit": account.profit,
            "margin": account.margin,
            "margin_free": account.margin_free,
            "margin_level": account.margin_level if account.margin > 0 else 0,
            "leverage": account.leverage,
            "currency": account.currency,
            "name": account.name,
            "company": account.company,
            "credit": getattr(account, 'credit', 0.0),
            "total_deposits": total_deposits,
            "total_withdrawals": total_withdrawals
        }
    
    def get_positions(self):
        """Get open positions."""
        if not self.connected:
            return []
        
        positions = mt5.positions_get()
        if positions is None:
            return []
        
        result = []
        for pos in positions:
            result.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "type": "BUY" if pos.type == 0 else "SELL",
                "volume": pos.volume,
                "price_open": pos.price_open,
                "price_current": pos.price_current,
                "sl": pos.sl,
                "tp": pos.tp,
                "profit": pos.profit,
                "swap": pos.swap,
                "time": datetime.fromtimestamp(pos.time).isoformat(),
                "magic": pos.magic,
                "comment": pos.comment
            })
        return result
    
    def get_deals(self, days=30):
        """Get deal history."""
        if not self.connected:
            return []
        
        from_timestamp = time.time() - (days * 24 * 3600)
        to_timestamp = time.time() + 86400

        deals = mt5.history_deals_get(from_timestamp, to_timestamp)
        if deals is None:
            return []
        
        result = []
        for deal in deals:
            result.append({
                "ticket": deal.ticket,
                "order": deal.order,
                "position_id": deal.position_id,
                "symbol": deal.symbol,
                "type": self._deal_type_to_string(deal.type),
                "entry": self._entry_to_string(deal.entry),
                "volume": deal.volume,
                "price": deal.price,
                "profit": deal.profit,
                "commission": deal.commission,
                "swap": deal.swap,
                "fee": deal.fee,
                "time": datetime.fromtimestamp(deal.time).isoformat(),
                "time_raw": deal.time,
                "magic": deal.magic,
                "comment": deal.comment
            })
        return result
    
    def _deal_type_to_string(self, deal_type):
        types = {0: "BUY", 1: "SELL", 2: "BALANCE", 3: "CREDIT", 
                 4: "CHARGE", 5: "CORRECTION", 6: "BONUS"}
        return types.get(deal_type, str(deal_type))
    
    def _entry_to_string(self, entry):
        entries = {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}
        return entries.get(entry, str(entry))
    
    def calculate_statistics(self, deals):
        """Calculate trading statistics from deals."""
        if not deals:
            return {}
        
        # Filter actual trades (not balance operations)
        trades = [d for d in deals if d.get('type') in ['BUY', 'SELL'] and d.get('entry') == 'OUT']
        
        if not trades:
            return {"total_trades": 0}
        
        profits = [t['profit'] for t in trades]
        winning = [p for p in profits if p > 0]
        losing = [p for p in profits if p < 0]
        
        return {
            "total_trades": len(trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": round(len(winning) / len(trades) * 100, 2) if trades else 0,
            "total_profit": round(sum(profits), 2),
            "average_win": round(sum(winning) / len(winning), 2) if winning else 0,
            "average_loss": round(sum(losing) / len(losing), 2) if losing else 0,
            "profit_factor": round(abs(sum(winning) / sum(losing)), 2) if losing and sum(losing) != 0 else 0,
            "largest_win": round(max(winning), 2) if winning else 0,
            "largest_loss": round(min(losing), 2) if losing else 0
        }
    
    def parse_deal_comment_v2(self, comment):
        """
        Parse MT5 deal comment using the new TradeAccountConnector format.
        
        Comment Format: {TradovateAccountNumber}{PhaseSuffix}
        
        Phase Suffixes:
        - _CH1-4: Challenge Trade 1-4
        - _FD0: Funded Base (MFFU style)
        - _FD1-4: Funded/Payout 1-4
        - _DD1-4: Double Dip 1-4
        - _FA: Farming/Consistency
        - _FA_DDMMYY: Farming with date (e.g., _FA_210126 = Jan 21, 2026)
        - _UNK: Unknown phase
        
        Returns:
            dict with parsed data or None if cannot parse
        """
        if COMMENT_PARSER_AVAILABLE:
            return parse_mt5_comment(comment)
        else:
            # Fallback to basic parsing
            return self.parse_deal_comment(comment)
    
    def aggregate_deals_by_comment_v2(self, deals):
        """
        Aggregate deals by account and phase using the new comment parser.
        
        Returns:
            Tuple of (aggregated_data, unmatched_deals, log_messages)
        """
        if COMMENT_PARSER_AVAILABLE:
            return aggregate_deals_by_comment(deals)
        else:
            # Fallback to basic aggregation
            aggregated, unmatched = self.aggregate_deals_by_account(deals)
            return [], unmatched, ["Comment parser not available, using basic aggregation"]
    
    def get_deals_grouped_by_phase(self, days=365):
        """
        Get deals grouped by account and phase based on comments.
        
        Uses position-based aggregation which:
        - Groups deals by position_id (each closed position has entry + exit deals)
        - Gets comment from entry deal (e.g., FNFT...59574_CH1)
        - Sums profit from all deals in that position (entry has profit=0, exit has actual profit)
        
        Returns:
            dict with structure:
            {
                'aggregated': [list of aggregated trade data],
                'unmatched': [list of positions without matching comments],
                'summary': {summary statistics},
                'log': [parsing log messages]
            }
        """
        deals = self.get_deals(days=days)
        if not deals:
            return {'aggregated': [], 'unmatched': [], 'summary': {}, 'log': ['No deals found']}
        
        if COMMENT_PARSER_AVAILABLE:
            # Use position-based aggregation for correct profit calculation
            # Entry deal has comment but profit=0, exit deal has profit but different comment
            aggregated, unmatched, log = aggregate_deals_by_position(deals)
            
            # Build summary
            by_phase = {}
            for agg in aggregated:
                phase_name = agg.get('phase_name', 'UNKNOWN')
                if phase_name not in by_phase:
                    by_phase[phase_name] = {'count': 0, 'total_net_profit': 0.0}
                by_phase[phase_name]['count'] += 1
                by_phase[phase_name]['total_net_profit'] += agg.get('net_profit', 0)
            
            return {
                'aggregated': aggregated,
                'unmatched': unmatched,
                'summary': {'by_phase': by_phase},
                'log': log
            }
        else:
            aggregated, unmatched = self.aggregate_deals_by_account(deals)
            return {
                'aggregated': [],
                'unmatched': unmatched,
                'summary': {},
                'log': ['Comment parser module not available']
            }
    
    def parse_deal_comment(self, comment):
        """
        Parse deal comment to extract account number and stage.
        
        Comment formats (MFFU example - middle parts abbreviated):
        - MFFU...81001 contains account ending in 81001
        - Stage is identified by _CH{n}, _FU{n}, _FA{n}_ patterns
        
        Returns:
            dict with 'account_suffix' (last 5 digits), 'stage' (CH/FU/FA), 'stage_num'
            or None if cannot parse
        """
        import re
        
        if not comment:
            return None
        
        result = {
            'account_suffix': None,
            'stage': None,
            'stage_num': None,
            'farming_date': None,
            'raw_comment': comment
        }
        
        # Extract account number - look for 5+ digit sequences
        # The account number appears at the end or within the comment
        account_matches = re.findall(r'(\d{5,})', comment)
        if account_matches:
            # Use the last match, take last 5 digits as identifier
            result['account_suffix'] = account_matches[-1][-5:]
        
        # Extract stage from comment
        # Challenge: _CH1, _CH2, etc. or CH1, CH2
        ch_match = re.search(r'_?CH(\d+)', comment, re.IGNORECASE)
        if ch_match:
            result['stage'] = 'CH'
            result['stage_num'] = int(ch_match.group(1))
            return result
        
        # Funded: _FU1, _FU2, etc. or FU1, FU2
        fu_match = re.search(r'_?FU(\d+)', comment, re.IGNORECASE)
        if fu_match:
            result['stage'] = 'FU'
            result['stage_num'] = int(fu_match.group(1))
            return result
        
        # Farming: _FA1_DD/MM or FA1_DD/MM
        fa_match = re.search(r'_?FA(\d+)_?(\d{1,2}[/\-]\d{1,2})?', comment, re.IGNORECASE)
        if fa_match:
            result['stage'] = 'FA'
            result['stage_num'] = int(fa_match.group(1))
            if fa_match.group(2):
                result['farming_date'] = fa_match.group(2)
            return result
        
        # If we found an account but no stage, return partial result
        if result['account_suffix']:
            return result
        
        return None
    
    def aggregate_deals_by_account(self, deals):
        """
        Aggregate deals by account number and stage.
        
        Returns dict: {
            'account_suffix': {
                'CH': {1: total_profit, 2: total_profit, ...},
                'FU': {1: total_profit, 2: total_profit, ...},
                'FA': {1: {'profit': total_profit, 'date': 'DD/MM'}, ...}
            }
        }
        """
        aggregated = {}
        unmatched = []
        
        for deal in deals:
            # Skip balance operations
            if deal.get('type') in ['BALANCE', 'CREDIT', '2', '3']:
                continue
            
            comment = deal.get('comment', '')
            parsed = self.parse_deal_comment(comment)
            
            if not parsed or not parsed['account_suffix']:
                unmatched.append(deal)
                continue
            
            account = parsed['account_suffix']
            stage = parsed.get('stage')
            stage_num = parsed.get('stage_num')
            
            if account not in aggregated:
                aggregated[account] = {'CH': {}, 'FU': {}, 'FA': {}}
            
            # Calculate deal P/L (profit + swap + commission)
            profit = (deal.get('profit', 0) or 0) + (deal.get('swap', 0) or 0) + (deal.get('commission', 0) or 0)
            
            if stage and stage_num:
                if stage == 'FA':
                    if stage_num not in aggregated[account]['FA']:
                        aggregated[account]['FA'][stage_num] = {'profit': 0, 'date': parsed.get('farming_date')}
                    aggregated[account]['FA'][stage_num]['profit'] += profit
                else:
                    if stage_num not in aggregated[account][stage]:
                        aggregated[account][stage][stage_num] = 0
                    aggregated[account][stage][stage_num] += profit
            else:
                # Has account but no stage - could be a general trade
                unmatched.append(deal)
        
        return aggregated, unmatched

    def push_to_dashboard(self, client_name, admin_name="", trader_name=""):
        """Push all data to the dashboard."""
        if not self.api_key:
            return False, "API key not set"
            
        print(f"--- Client {client_name} Info Start ---")
        
        account = self.get_account_info()
        positions = self.get_positions()

        # Calculate days from 23rd of last month
        from datetime import datetime as _dt
        _now = _dt.now()
        if _now.month == 1:
            _from_date = _dt(_now.year - 1, 12, 23)
        else:
            _from_date = _dt(_now.year, _now.month - 1, 23)
        _days_since_23rd = (_now - _from_date).days + 1
        deals = self.get_deals(days=_days_since_23rd)
        
        # Merge in full-history farming deals for correct hedge day calculation
        all_deals_full = self.get_deals(days=365) or []
        if deals is None:
            deals = []
        existing_ids = {d.get('ticket') or d.get('order') for d in deals}
        for d in all_deals_full:
            if '_FA' in str(d.get('comment', '')).upper():
                deal_id = d.get('ticket') or d.get('order')
                if deal_id not in existing_ids:
                    deals.append(d)
                    existing_ids.add(deal_id)
        
        statistics = self.calculate_statistics(deals)
        
        payload = {
            "identity": {
                "admin": admin_name or "Admin",
                "trader": trader_name or "Trader",
                "client": client_name
            },
            "account": account or {},
            "positions": positions,
            "deals": deals,
            "statistics": statistics,
            "evaluations": [],
            "dropdown_options": {}
        }
        
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key
        }
        
        try:
            response = requests.post(
                f"{self.dashboard_url}/api/update_data",
                json=payload,
                headers=headers,
                timeout=120
            )
            
            if response.status_code == 200:
                data = response.json()
                print(f"--- Client {client_name} Info End ---")
                if data.get('status') == 'success':
                    return True, f"Data pushed successfully for {client_name}"
                return False, data.get('message', 'Unknown error')
            else:
                print(f"--- Client {client_name} Info End (Failed) ---")
                return False, f"HTTP {response.status_code}: {response.text}"
                
        except requests.exceptions.ConnectionError:
            print(f"--- Client {client_name} Info End (Connection Error) ---")
            return False, f"Cannot connect to dashboard at {self.dashboard_url}"
        except requests.exceptions.Timeout:
            print(f"--- Client {client_name} Info End (Timeout) ---")
            return False, "Request timed out"
        except Exception as e:
            print(f"--- Client {client_name} Info End (Error) ---")
            return False, str(e)
    
    def parse_deal_comment(self, comment):
        """
        Parse MT5 deal comment to extract account number and stage info.
        
        Comment formats:
        - Challenge: {account}_CH{n}  (e.g., "12345_CH1", "67890_CH2")
        - Funded: {account}_FU{n}  (e.g., "12345_FU1", "12345_FU2")
        - Farming: {account}_FA{n}_{DD/MM}  (e.g., "12345_FA1_15/01")
        
        Returns dict with:
        - account: The account number (with middle part extracted if needed)
        - stage: 'challenge', 'funded', or 'farming'
        - stage_num: The number (1, 2, 3, etc.)
        - date: Optional date for farming (DD/MM format)
        """
        import re
        
        if not comment:
            return None
        
        comment = comment.strip()
        
        # Pattern for Challenge: {account}_CH{n}
        ch_match = re.match(r'^(.+?)_CH(\d+)$', comment, re.IGNORECASE)
        if ch_match:
            return {
                'account': ch_match.group(1),
                'stage': 'challenge',
                'stage_num': int(ch_match.group(2)),
                'date': None
            }
        
        # Pattern for Funded: {account}_FU{n}
        fu_match = re.match(r'^(.+?)_FU(\d+)$', comment, re.IGNORECASE)
        if fu_match:
            return {
                'account': fu_match.group(1),
                'stage': 'funded',
                'stage_num': int(fu_match.group(2)),
                'date': None
            }
        
        # Pattern for Double Dip: {account}_DD{n}
        dd_match = re.match(r'^(.+?)_DD(\d+)$', comment, re.IGNORECASE)
        if dd_match:
            return {
                'account': dd_match.group(1),
                'stage': 'doubledip',
                'stage_num': int(dd_match.group(2)),
                'date': None
            }
        
        # Pattern for Farming: {account}_FA{n}_{DD/MM}
        fa_match = re.match(r'^(.+?)_FA(\d+)_(\d{1,2}/\d{1,2})$', comment, re.IGNORECASE)
        if fa_match:
            return {
                'account': fa_match.group(1),
                'stage': 'farming',
                'stage_num': int(fa_match.group(2)),
                'date': fa_match.group(3)
            }
        
        return None
    
    def extract_account_core(self, account_num):
        """
        Extract the core/middle part of an account number for matching.
        This handles cases where the full account number might have prefixes/suffixes.
        
        For example:
        - "HFM-123456-USD" -> "123456"
        - "123456" -> "123456"
        - "ACC123456END" -> "123456" (extracts numeric middle)
        """
        import re
        
        if not account_num:
            return None
        
        account_str = str(account_num).strip()
        
        # First try: extract all digits as a group
        digits = re.findall(r'\d+', account_str)
        if digits:
            # Return the longest group of digits (likely the account number)
            return max(digits, key=len)
        
        return account_str
    
    def process_deals_for_evaluations(self, deals, evaluations):
        """
        Process deals and match them to evaluations based on comments.
        Uses the new TradeAccountConnector comment format.
        
        Comment Format: {TradovateAccountNumber}_{Phase}{Number}
        - CH1-4: Challenge Hedge Results 1-5
        - FD0-4: Funded Hedge Results (FD0=base, FD1-4=payouts)
        - DD1-4: Double Dip (treated like funded)
        - FA or FA_DDMMYY: Farming days
        
        Args:
            deals: List of MT5 deals with 'comment' field
            evaluations: List of evaluation records
        
        Returns:
            Tuple of (updated_evaluations, match_log)
        """
        if not deals or not evaluations:
            return evaluations, ["No deals or evaluations to process"]
        
        match_log = []
        
        # Use the new parser if available
        if COMMENT_PARSER_AVAILABLE:
            return self._process_deals_with_new_parser(deals, evaluations)
        
        match_log.append("⚠️ Using legacy parser - install mt5_comment_parser for full support")
        return self._process_deals_legacy(deals, evaluations)
    
    def _process_deals_with_new_parser(self, deals, evaluations):
        """
        Process deals using the new MT5 comment parser.
        Matches account numbers and updates the correct hedge result fields.
        """
        match_log = []
        
        # Step 1: Aggregate deals by comment using the new parser
        aggregator = MT5DealAggregator()
        aggregator.process_deals(deals)
        
        aggregated = aggregator.to_dashboard_format()
        match_log.append(f"📊 Aggregated {len(aggregated)} trade groups from {len(deals)} deals")
        match_log.append(f"   Unmatched deals: {len(aggregator.unmatched_deals)}")
        
        if not aggregated:
            match_log.append("⚠️ No valid trade groups found in deals")
            return evaluations, match_log
        
        # Step 2: Build account lookup from evaluations
        # We need to match full account numbers, not just suffixes
        eval_lookup = {}  # Maps account_number -> list of (eval_index, account_type)
        
        for idx, ev in enumerate(evaluations):
            # Challenge account (Account #) - used for CH phase
            ch_account = str(ev.get('Account #', '')).strip()
            if ch_account:
                if ch_account not in eval_lookup:
                    eval_lookup[ch_account] = []
                eval_lookup[ch_account].append((idx, 'challenge'))
                
                # Also add partial matches (last 8-10 chars for flexibility)
                for suffix_len in [8, 10, 12]:
                    if len(ch_account) >= suffix_len:
                        suffix = ch_account[-suffix_len:]
                        if suffix not in eval_lookup:
                            eval_lookup[suffix] = []
                        eval_lookup[suffix].append((idx, 'challenge'))
            
            # Funded account (Account #.1) - used for FD, DD, FA phases
            fu_account = str(ev.get('Account #.1', '')).strip()
            if fu_account:
                if fu_account not in eval_lookup:
                    eval_lookup[fu_account] = []
                eval_lookup[fu_account].append((idx, 'funded'))
                
                # Also add partial matches
                for suffix_len in [8, 10, 12]:
                    if len(fu_account) >= suffix_len:
                        suffix = fu_account[-suffix_len:]
                        if suffix not in eval_lookup:
                            eval_lookup[suffix] = []
                        eval_lookup[suffix].append((idx, 'funded'))
        
        match_log.append(f"📋 Built account lookup with {len(eval_lookup)} entries")
        
        # Sample accounts for debug
        sample_accounts = list(eval_lookup.keys())[:5]
        match_log.append(f"   Sample accounts: {sample_accounts}")
        
        # Step 3: Process each aggregated trade group
        updates_made = 0
        
        # Sort aggregated groups by date to ensure chronological order for farming days
        aggregated.sort(key=lambda x: str(x.get('farming_date') or ''))

        # --- Same-day FA aggregation + hedge-day slot calculation ---
        # Step 1: Merge trades on the same date into one entry per (account, date).
        #         sum net_profit/deal_count, earliest open_time, latest close_time.
        # Step 2: Count ALL distinct FA trading dates per account from the full MT5 history window
        #         (acts as our "3-month history scan").  That count IS the hedge day number
        #         for the latest trade — no sheet-slot scanning needed.
        # Step 3: Only push the LATEST date per account; earlier dates are already in the sheet.
        _fa_by_key = {}   # (account_number, date_str) -> merged dict
        _non_fa = []
        for _agg in aggregated:
            if _agg.get('phase_code') == 'FA':
                _date_str = str(_agg.get('farming_date') or '')
                _key = (_agg.get('account_number', ''), _date_str)
                if _key not in _fa_by_key:
                    _fa_by_key[_key] = dict(_agg)
                else:
                    _m = _fa_by_key[_key]
                    _m['net_profit'] = _m.get('net_profit', 0) + _agg.get('net_profit', 0)
                    _m['deal_count'] = _m.get('deal_count', 0) + _agg.get('deal_count', 0)
                    # Earliest open_time
                    if _agg.get('open_time') and (
                            not _m.get('open_time') or str(_agg['open_time']) < str(_m['open_time'])):
                        _m['open_time'] = _agg['open_time']
                    # Latest close_time (deduplication key)
                    if _agg.get('close_time') and (
                            not _m.get('close_time') or str(_agg['close_time']) > str(_m['close_time'])):
                        _m['close_time'] = _agg['close_time']
            else:
                _non_fa.append(_agg)

        # Group merged FA entries by account, sort chronologically.
        # The hedge day number for the latest trade = total distinct trading days in history.
        # Only keep the latest entry per account for the actual push.
        _fa_per_account = {}   # account_number -> sorted list of (date_str, entry)
        for (acct, date_str), entry in _fa_by_key.items():
            _fa_per_account.setdefault(acct, []).append((date_str, entry))

        _fa_to_push = []   # only latest per account, tagged with _fa_slot
        for acct, date_entries in _fa_per_account.items():
            date_entries.sort(key=lambda x: x[0])          # chronological order
            total_days = len(date_entries)                  # count = hedge day slot
            latest_date_str, latest_entry = date_entries[-1]
            tagged = dict(latest_entry)
            tagged['_fa_slot'] = total_days                 # pre-computed slot number
            _fa_to_push.append(tagged)
            match_log.append(
                f"   📅 {acct}: {total_days} FA day(s) in MT5 history "
                f"→ will push as Hedge Day {total_days} ({latest_date_str})"
            )

        # Rebuild aggregated: non-FA entries + one FA entry per account (latest day only)
        aggregated = _non_fa + sorted(_fa_to_push, key=lambda x: str(x.get('farming_date') or ''))
        match_log.append(f"   After FA processing: {len(_fa_to_push)} FA account(s) queued for push")

        # (legacy fallback: still used for edge-cases without a farming_date)
        account_farming_slots = {}

        # Pre-build per-account set of close_times already stored in Hedge Day Notes.
        # This is the deduplication guard: if a close_time is already recorded in
        # any "Hedge Day N Note" field, that trade has already been pushed and we skip it.
        # Maps account_number -> set of close_time signature strings
        account_pushed_close_times = {}

        def _get_pushed_close_times(account_number, phase_code):
            if account_number in account_pushed_close_times:
                return account_pushed_close_times[account_number]
            pushed = set()
            fa_matches = self._find_evaluation_match(account_number, phase_code, eval_lookup)
            for fa_idx, fa_type in (fa_matches or []):
                if fa_type != 'funded':
                    continue
                ev = evaluations[fa_idx]
                for day_num in range(1, 51):
                    note = ev.get(f'Hedge Day {day_num} Note', '')
                    if note and 'Close:' in str(note):
                        # Extract close time signature: "Open: ... | Close: 2026-01-21 16:00"
                        close_part = str(note).split('Close:')[-1].strip()
                        if close_part:
                            pushed.add(close_part)
                break  # Use first funded eval match
            account_pushed_close_times[account_number] = pushed
            return pushed

        for agg in aggregated:
            account_number = agg.get('account_number', '')
            phase_code = agg.get('phase_code', '')
            trade_number = agg.get('trade_number')
            farming_date = agg.get('farming_date')
            net_profit = agg.get('net_profit', 0)
            deal_count = agg.get('deal_count', 0)
            
            # Find matching evaluation
            eval_matches = self._find_evaluation_match(account_number, phase_code, eval_lookup)
            
            if not eval_matches:
                match_log.append(f"⚠️ No match: {account_number}_{phase_code}{trade_number or ''} = ${net_profit:.2f}")
                continue
            
            # Special handling for Farming phase to ensure sequential day filling
            forced_day_num = None
            skip_farming = False
            if phase_code == 'FA':
                close_time = agg.get('close_time')
                def _fmt_time_fa(t):
                    try:
                        return str(t)[:16].replace('T', ' ')
                    except:
                        return str(t)
                close_sig = _fmt_time_fa(close_time) if close_time else None

                # Deduplication: check if this close_time was already pushed
                if close_sig:
                    pushed_times = _get_pushed_close_times(account_number, phase_code)
                    if close_sig in pushed_times:
                        match_log.append(f"⏭️ SKIP (already pushed) {account_number}_FA close={close_sig}")
                        skip_farming = True

                if not skip_farming:
                    # Slot number was pre-computed from MT5 history count (distinct FA trading days).
                    # _fa_slot = total distinct FA dates for this account in the history window.
                    fa_slot = agg.get('_fa_slot')
                    if fa_slot:
                        forced_day_num = fa_slot
                    else:
                        # Fallback for entries without a farming_date / legacy comments
                        if trade_number and trade_number > 0:
                            forced_day_num = trade_number
                        else:
                            if account_number not in account_farming_slots:
                                account_farming_slots[account_number] = {'__next_slot': 1}
                            slot = account_farming_slots[account_number]['__next_slot']
                            account_farming_slots[account_number]['__next_slot'] += 1
                            forced_day_num = slot

            if skip_farming:
                continue

            # Determine which field to update based on phase
            # Use first match to determine field name logic
            field_name = self._get_field_name_for_phase(
                phase_code, trade_number, farming_date, evaluations, eval_matches[0][0],
                forced_day_num=forced_day_num
            )
            
            if not field_name:
                match_log.append(f"⚠️ Unknown field for {phase_code}{trade_number or ''}")
                continue
            
            # Update ALL matching evaluations
            for eval_idx, account_type in eval_matches:
                # Verify this is the right type of match
                if phase_code == 'CH' and account_type != 'challenge':
                    continue
                if phase_code in ['FD', 'DD', 'FA'] and account_type != 'funded':
                    continue
                
                # Update the field
                evaluations[eval_idx][field_name] = net_profit

                # Store open/close timestamps as a companion note
                open_time = agg.get('open_time')
                close_time = agg.get('close_time')
                def _fmt_time(t):
                    try:
                        return str(t)[:16].replace('T', ' ')
                    except:
                        return str(t)
                if open_time or close_time:
                    note = f"Open: {_fmt_time(open_time)} | Close: {_fmt_time(close_time)}"
                    evaluations[eval_idx][f'{field_name} Note'] = note
                    # Register this close_time so re-entrant pushes in the same run are also blocked
                    if phase_code == 'FA' and close_time:
                        close_sig_written = _fmt_time(close_time)
                        account_pushed_close_times.setdefault(account_number, set()).add(close_sig_written)

                updates_made += 1
                
                eval_account = evaluations[eval_idx].get('Account #' if account_type == 'challenge' else 'Account #.1', 'N/A')
                match_log.append(f"✅ {account_number}_{phase_code}{trade_number or ''} → [{field_name}] = ${net_profit:.2f} ({deal_count} deals)")
                match_log.append(f"   Matched to eval row: {eval_account} (Row {eval_idx})")
                if open_time or close_time:
                    match_log.append(f"   🕐 Open: {_fmt_time(open_time)} | Close: {_fmt_time(close_time)}")
        
        match_log.append(f"\n📈 Total updates made: {updates_made}")
        return evaluations, match_log
    
    def _find_evaluation_match(self, account_number, phase_code, eval_lookup):
        """
        Find matching evaluation(s) for an account number.
        Tries exact match first, then partial matches.
        """
        # Try exact match first
        if account_number in eval_lookup:
            return eval_lookup[account_number]
        
        # Try matching by suffix (last N characters)
        for suffix_len in [12, 10, 8]:
            if len(account_number) >= suffix_len:
                suffix = account_number[-suffix_len:]
                if suffix in eval_lookup:
                    return eval_lookup[suffix]
        
        # Try finding accounts that contain this number as substring
        for key, matches in eval_lookup.items():
            if account_number in key or key in account_number:
                return matches
        
        return []
    
    def _get_field_name_for_phase(self, phase_code, trade_number, farming_date, evaluations, eval_idx, forced_day_num=None):
        """
        Determine the correct field name to update based on phase.
        
        Phase mappings:
        - CH1-5: Hedge Result 1-5 (Challenge)
        - FD0: Hedge Result 1.1 (Funded base)
        - FD1-4: Hedge Result 2.1-5.1 (Funded payouts)
        - DD1-4: Hedge Result 6-7 or similar
        - FA: Hedge Day N (based on date ordering)
        """
        if phase_code == 'CH':
            # Challenge: CH1 → Hedge Result 1, CH2 → Hedge Result 2, etc.
            if trade_number and 1 <= trade_number <= 5:
                return f"Hedge Result {trade_number}"
        
        elif phase_code == 'FD':
            # Funded: FD0 → Hedge Result 1.1, FD1 → Hedge Result 2.1, etc.
            if trade_number is not None:
                if trade_number == 0:
                    return "Hedge Result 1.1"
                elif 1 <= trade_number <= 4:
                    return f"Hedge Result {trade_number + 1}.1"
                elif trade_number == 5:
                    return "Hedge Result 6"
                elif trade_number == 6:
                    return "Hedge Result 7"
        
        elif phase_code == 'DD':
            # Double Dip: DD1 -> Hedge Result 1.1, DD2 -> Hedge Result 2.1
            if trade_number:
                 return f"Hedge Result {trade_number}.1"
        
        elif phase_code == 'FA':
            # Farming: Use date to determine day number (using forced sequence if available)
            if forced_day_num:
                return f"Hedge Day {forced_day_num}"
                
            if farming_date:
                # Calculate which farming day this is based on the date
                # Legacy fallback if no forced sequence
                day_number = self._calculate_farming_day(farming_date, evaluations, eval_idx)
                if day_number and 1 <= day_number <= 34:
                    return f"Hedge Day {day_number}"
            elif trade_number:
                # If no date but has trade number, use that
                if 1 <= trade_number <= 34:
                    return f"Hedge Day {trade_number}"
        
        return None
    
    def _calculate_farming_day(self, farming_date_str, evaluations, eval_idx):
        """
        Calculate which farming day number to use based on the date.
        
        Farming dates in comments are DDMMYY format (e.g., 210126 = Jan 21, 2026).
        We need to figure out which day number (1-34) this corresponds to.
        
        Strategy: Look at existing farming dates in the evaluation to determine sequence,
        or use the first farming date as day 1 and count from there.
        """
        from datetime import datetime
        
        # Parse the farming date
        if isinstance(farming_date_str, str):
            try:
                farming_date = datetime.fromisoformat(farming_date_str)
            except:
                return None
        else:
            farming_date = farming_date_str
        
        if not farming_date:
            return None
        
        # Get the evaluation record to check for existing farming dates
        ev = evaluations[eval_idx] if eval_idx < len(evaluations) else {}
        
        # Find the first empty farming day slot
        for day_num in range(1, 51):
            field_name = f"Hedge Day {day_num}"
            existing_value = ev.get(field_name)
            
            # Check if this slot is empty or has no value
            if existing_value is None or existing_value == '' or existing_value == 0:
                return day_num
        
        # All slots full, return the last one
        return 50
    
    def _process_deals_legacy(self, deals, evaluations):
        """Legacy deal processing for backward compatibility."""
        match_log = []
        deal_groups = {}
        
        for deal in deals:
            comment = deal.get('comment', '')
            parsed = self.parse_deal_comment(comment)
            
            if not parsed or not parsed.get('account_suffix'):
                continue
            
            # Skip balance operations
            d_type = str(deal.get('type', '')).upper()
            if d_type in ['BALANCE', 'CREDIT', '2', '3']:
                continue
            
            # Only process closed trades (OUT)
            if deal.get('entry') != 'OUT':
                continue
            
            account_suffix = parsed['account_suffix']
            stage = parsed.get('stage')
            stage_num = parsed.get('stage_num')
            
            if not stage or not stage_num:
                continue
                
            key = (account_suffix, stage, stage_num)
            
            if key not in deal_groups:
                deal_groups[key] = []
            deal_groups[key].append(deal)
        
        match_log.append(f"Found {len(deal_groups)} unique account/stage combinations in deals")
        
        # Build account lookup from evaluations
        # Maps account_suffix (last 5 digits) -> evaluation index
        eval_lookup_ch = {}  # Challenge accounts (Account #)
        eval_lookup_fu = {}  # Funded accounts (Account #.1)
        
        for idx, ev in enumerate(evaluations):
            # Challenge account (Account #) - extract last 5 digits for matching
            ch_account = ev.get('Account #', '')
            if ch_account:
                ch_suffix = str(ch_account).strip()[-5:] if len(str(ch_account).strip()) >= 5 else str(ch_account).strip()
                if ch_suffix:
                    eval_lookup_ch[ch_suffix] = idx
            
            # Funded account (Account #.1) - extract last 5 digits for matching
            fu_account = ev.get('Account #.1', '')
            if fu_account:
                fu_suffix = str(fu_account).strip()[-5:] if len(str(fu_account).strip()) >= 5 else str(fu_account).strip()
                if fu_suffix:
                    eval_lookup_fu[fu_suffix] = idx
        
        match_log.append(f"Built lookup: {len(eval_lookup_ch)} challenge accounts, {len(eval_lookup_fu)} funded accounts")
        
        # Debug: Show some of the lookup keys
        if eval_lookup_ch:
            sample_ch = list(eval_lookup_ch.keys())[:3]
            match_log.append(f"   Sample CH accounts: {sample_ch}")
        if eval_lookup_fu:
            sample_fu = list(eval_lookup_fu.keys())[:3]
            match_log.append(f"   Sample FU accounts: {sample_fu}")
        
        # Process each deal group and update evaluations
        for (account_suffix, stage, stage_num), group_deals in deal_groups.items():
            # Calculate total profit for this group
            total_profit = sum(
                (d.get('profit', 0) or 0) + (d.get('swap', 0) or 0) + (d.get('commission', 0) or 0)
                for d in group_deals
            )
            
            # Find matching evaluation based on stage
            # CH = Challenge (Account #), FU = Funded (Account #.1), FA = Farming (Account #.1)
            eval_idx = None
            if stage == 'CH':
                eval_idx = eval_lookup_ch.get(account_suffix)
            elif stage in ['FU', 'FA']:
                eval_idx = eval_lookup_fu.get(account_suffix)
            
            if eval_idx is None:
                match_log.append(f"⚠️ No match for {account_suffix}_{stage}{stage_num}: ${total_profit:.2f} ({len(group_deals)} deals)")
                continue
            
            # Determine field name to update
            if stage == 'CH':
                # Challenge uses: Hedge Result 1, Hedge Result 2, etc.
                field_name = f"Hedge Result {stage_num}"
            elif stage == 'FU':
                # Funded uses: Hedge Result 1.1, Hedge Result 2.1, etc. (up to 7)
                field_name = f"Hedge Result {stage_num}.1"
            elif stage == 'FA':
                # Farming uses: Hedge Day {n}
                field_name = f"Hedge Day {stage_num}"
            else:
                match_log.append(f"⚠️ Unknown stage {stage} for {account_suffix}")
                continue
            
            # Update the evaluation — store clean numeric, no $ prefix
            evaluations[eval_idx][field_name] = f"{total_profit:.2f}"
            match_log.append(f"✓ {account_suffix}_{stage}{stage_num} -> [{field_name}] = ${total_profit:.2f} ({len(group_deals)} deals)")
        
        return evaluations, match_log


class TraderCompanionApp:
    """GUI Application for Tradeopss AI."""

    # ── Design System (FuturesEngine-inspired Dark Theme) ──
    C_BG        = "#0D1117"   # GitHub dark background
    C_BG_SEC    = "#161B22"   # Card / secondary surface
    C_BG_THIRD  = "#1C2333"   # Tertiary / input fields
    C_BORDER    = "#30363D"   # Subtle borders
    C_ACCENT    = "#0969DA"   # Blue accent
    C_ACCENT_HV = "#218BFF"   # Blue hover
    C_GOLD      = "#F59E0B"   # Amber gold (brand)
    C_SUCCESS   = "#1A7F37"   # Green
    C_ERROR     = "#CF222E"   # Red
    C_TEXT      = "#E6EDF3"   # Primary text
    C_TEXT_DIM  = "#8B949E"   # Muted text
    C_TEXT_DARK = "#24292F"   # Dark text (for light pill backgrounds)

    PROP_FIRM_COLORS = {
        "My Funded Futures": "#3B8ED0",
        "MFFU":             "#3B8ED0",
        "TopStep":          "#DA3633",
        "Apex":             "#E67E22",
        "Funded Next":      "#E91E63",
        "FundingTicks":     "#F1C40F",
        "TradeDay":         "#9B59B6",
        "Tradeify":         "#1ABC9C",
        "Alpha Futures":    "#2980B9",
        "Top One Futures": "#0D9488",
    }

    PHASE_BADGE = {
        "Challenge": ("#FEF3C7", "#92400E"),   # warm-yellow bg, brown text
        "Funded":    ("#D1FAE5", "#065F46"),   # green bg, dark-green text
        "Farming":   ("#DBEAFE", "#1E40AF"),   # blue bg, dark-blue text
    }

    def __init__(self):
        # ── CTk root window ──
        if CTK_AVAILABLE:
            ctk.set_appearance_mode("Dark")
            ctk.set_default_color_theme("blue")
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()
        self.root.title(f"Tradeopss AI v{APP_VERSION}")
        self.root.geometry("680x612")
        self.root.minsize(595, 527)
        if CTK_AVAILABLE:
            self.root.configure(fg_color=self.C_BG)
        else:
            self.root.configure(bg=self.C_BG)
        self.root.resizable(True, True)

        # Set Window Icon
        try:
            if hasattr(sys, '_MEIPASS'):
                _base = sys._MEIPASS
            else:
                _base = os.path.dirname(os.path.abspath(__file__))
            ico_path = os.path.join(_base, 'logo.ico')
            if os.path.exists(ico_path):
                self.root.iconbitmap(ico_path)
                self.root.after(200, lambda: self.root.iconbitmap(ico_path))
            else:
                png_path = os.path.join(_base, 'logo.png')
                if os.path.exists(png_path):
                    from PIL import Image as PILImage, ImageTk
                    _pil_icon = PILImage.open(png_path)
                    bbox = _pil_icon.getbbox()
                    if bbox:
                        _pil_icon = _pil_icon.crop(bbox)
                    w, h = _pil_icon.size
                    s = max(w, h)
                    _sq = PILImage.new('RGBA', (s, s), (0, 0, 0, 0))
                    _sq.paste(_pil_icon, ((s - w) // 2, (s - h) // 2))
                    _sq = _sq.resize((64, 64), PILImage.LANCZOS)
                    self._app_icon = ImageTk.PhotoImage(_sq)
                    self.root.iconphoto(True, self._app_icon)
                    self.root.after(200, lambda: self.root.iconphoto(True, self._app_icon))
        except Exception:
            pass

        self.pusher = MT5DataPusher()
        self.auto_push_enabled = False
        self.auto_push_thread = None
        self.client_info = None

        # Auto-trade scheduler state
        self.auto_trade_enabled = False
        self.auto_trade_thread = None
        self._auto_trade_stop = threading.Event()
        self._auto_trade_scheduled_dt = None

        # Trading engine state
        self.trading_api = None
        self.tradovate_account = None
        self.topstepx_account = None
        self._broker_connections = {}  # {firm_name: {user_entry, pass_entry, status_var, connect_btn, account, row_frame}}
        self._propfirm_browsers = {}   # {firm_name: FundedNextAccount/etc} for dashboard scraping
        self.prop_firm_mgr = PropFirmManager() if PROP_FIRM_AVAILABLE else None
        self._auto_trading_stop = threading.Event()
        self._auto_trading_thread = None
        self._direction_locks = {}
        self._active_trade_rows = []

        self._show_login_screen()
        
    # ── Login Screen ──
    def _show_login_screen(self):
        """Show a full-screen login/email verification screen — always required."""
        # Try loading saved email to pre-fill
        saved_email = ""
        config_path = os.path.join(os.path.dirname(__file__), "trader_config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    cfg = json.load(f)
                saved_email = cfg.get('client_email', '').strip()
            except Exception:
                pass

        self._login_frame = ctk.CTkFrame(self.root, fg_color=self.C_BG) if CTK_AVAILABLE else \
                            tk.Frame(self.root, bg=self.C_BG)
        self._login_frame.pack(fill="both", expand=True)

        # Center box
        center = ctk.CTkFrame(self._login_frame, fg_color=self.C_BG_SEC, corner_radius=12,
                               border_width=1, border_color=self.C_BORDER) if CTK_AVAILABLE else \
                 tk.Frame(self._login_frame, bg="#161B22")
        center.place(relx=0.5, rely=0.45, anchor="center")

        if CTK_AVAILABLE:
            ctk.CTkLabel(center, text="Client Verification",
                         font=("Segoe UI", 13),
                         text_color=self.C_TEXT).pack(pady=(30, 16))

            self._login_email = ctk.CTkEntry(center, placeholder_text="Enter Registered Email",
                                              width=300, height=40,
                                              font=("Segoe UI", 12),
                                              fg_color=self.C_BG_THIRD,
                                              border_color=self.C_BORDER,
                                              text_color=self.C_TEXT)
            self._login_email.pack(pady=(0, 16), padx=30)
            self._login_email.bind("<Return>", lambda e: self._verify_login())

            # Pre-fill saved email
            if saved_email:
                self._login_email.insert(0, saved_email)

            self._login_btn = ctk.CTkButton(center, text="VERIFY ACCESS",
                                             width=300, height=40,
                                             command=self._verify_login,
                                             fg_color=self.C_ACCENT,
                                             hover_color=self.C_ACCENT_HV,
                                             font=("Segoe UI", 12, "bold"))
            self._login_btn.pack(pady=(0, 12), padx=30)

            self._login_status = ctk.CTkLabel(center, text="",
                                               font=("Segoe UI", 11),
                                               text_color=self.C_ERROR)
            self._login_status.pack(pady=(0, 24))

    def _verify_login(self):
        """Verify the email against the dashboard API."""
        email = self._login_email.get().strip()
        if not email:
            self._login_status.configure(text="Please enter an email address.")
            return

        self._login_btn.configure(state="disabled", text="VERIFYING...")
        self._login_status.configure(text="", text_color=self.C_TEXT_DIM)
        self.root.update_idletasks()

        def _check():
            try:
                response = requests.post(
                    "https://www.tradeopss.com/api/client/auth",
                    json={"email": email},
                    headers={"Content-Type": "application/json"},
                    timeout=30
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        self.root.after(0, lambda: self._finish_login(email))
                        return
                    else:
                        msg = data.get("message", "Email not found")
                        self.root.after(0, lambda: self._login_fail(f"Access Denied: {msg}"))
                        return
                else:
                    self.root.after(0, lambda: self._login_fail(f"Server error ({response.status_code})"))
                    return
            except requests.exceptions.ConnectionError:
                self.root.after(0, lambda: self._login_fail("Cannot connect to server"))
            except Exception as e:
                self.root.after(0, lambda: self._login_fail(str(e)))

        threading.Thread(target=_check, daemon=True).start()

    def _login_fail(self, msg):
        """Show login failure message."""
        self._login_status.configure(text=msg, text_color=self.C_ERROR)
        self._login_btn.configure(state="normal", text="VERIFY ACCESS")

    def _finish_login(self, email):
        """Tear down login screen, build main UI, and auto-lookup."""
        if hasattr(self, '_login_frame'):
            self._login_frame.destroy()

        self.setup_ui()
        self.load_config()

        # Set the email and trigger lookup
        self.client_email_entry.delete(0, tk.END)
        self.client_email_entry.insert(0, email)
        self.root.after(200, self.lookup_client)
        
    # ── Helper: create a section card ──
    def _section_card(self, parent, title="", icon="", **kw):
        """Create a styled card frame with optional title strip."""
        card = ctk.CTkFrame(parent, fg_color=self.C_BG_SEC, corner_radius=8,
                            border_width=1, border_color=self.C_BORDER) if CTK_AVAILABLE else \
               tk.Frame(parent, bg='#161B22')
        if title and CTK_AVAILABLE:
            hdr = ctk.CTkFrame(card, fg_color="transparent", height=26)
            hdr.pack(fill="x", padx=10, pady=(6, 0))
            hdr.pack_propagate(False)
            if icon:
                ctk.CTkLabel(hdr, text=icon, font=("Segoe UI", 12)).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(hdr, text=title, font=("Segoe UI", 10, "bold"),
                         text_color=self.C_GOLD).pack(side="left")
        return card

    # ── Helper: styled CTk entry ──
    def _ctk_entry(self, parent, width=200, show=None, placeholder=None):
        if CTK_AVAILABLE:
            kw = dict(width=width, height=32, fg_color=self.C_BG_THIRD,
                      border_color=self.C_BORDER, text_color=self.C_TEXT,
                      font=("Segoe UI", 11))
            if show:
                kw["show"] = show
            if placeholder:
                kw["placeholder_text"] = placeholder
            return ctk.CTkEntry(parent, **kw)
        else:
            e = ttk.Entry(parent, width=width // 8)
            if show:
                e.configure(show=show)
            return e

    # ── Helper: styled CTk button ──
    def _ctk_button(self, parent, text="", command=None, fg=None, hover=None, width=140, **kw):
        fg = fg or self.C_ACCENT
        hover = hover or self.C_ACCENT_HV
        if CTK_AVAILABLE:
            return ctk.CTkButton(parent, text=text, command=command,
                                 fg_color=fg, hover_color=hover,
                                 font=("Segoe UI", 11, "bold"),
                                 corner_radius=6, height=34, width=width, **kw)
        else:
            return ttk.Button(parent, text=text, command=command)

    # ── Helper: status pill ──
    def _status_pill(self, parent, text, bg_color, text_color):
        if CTK_AVAILABLE:
            pill = ctk.CTkFrame(parent, fg_color=bg_color, corner_radius=8, height=22)
            ctk.CTkLabel(pill, text=text, font=("Segoe UI", 9, "bold"),
                         text_color=text_color).pack(padx=8, pady=2)
            return pill
        else:
            lbl = tk.Label(parent, text=text, bg=bg_color, fg=text_color,
                           font=("Segoe UI", 9, "bold"), padx=6, pady=1)
            return lbl

    def setup_ui(self):
        """Setup the modern CTk user interface — two-column single-screen layout."""
        if not CTK_AVAILABLE:
            # ── Fallback: simple ttk layout ──
            self.main_canvas = tk.Canvas(self.root, bg=self.C_BG, highlightthickness=0)
            sb = ttk.Scrollbar(self.root, orient="vertical", command=self.main_canvas.yview)
            self.scrollable_frame = ttk.Frame(self.main_canvas)
            self.scrollable_frame.bind("<Configure>",
                lambda e: self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all")))
            self.main_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
            self.main_canvas.configure(yscrollcommand=sb.set)
            self.main_canvas.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            main = self.scrollable_frame
            style = ttk.Style(); style.theme_use('clam')
            self.notebook = ttk.Notebook(main)
            self.notebook.pack(fill="both", expand=True, padx=8, pady=4)
            tab_dash  = ttk.Frame(self.notebook); self.notebook.add(tab_dash, text="Settings")
            self._build_dashboard_tab(tab_dash)
            self._build_trading_engine_ui(tab_dash)
            log_frame = ttk.LabelFrame(main, text="Status Log", padding=4)
            log_frame.pack(fill="both", expand=True, padx=8, pady=4)
            self.log_text = scrolledtext.ScrolledText(log_frame, height=6, bg='#0a0e1a',
                                                       fg='#22c55e', font=('Consolas', 9),
                                                       insertbackground='white', relief='flat')
            self.log_text.pack(fill="both", expand=True)
            self.status_var = tk.StringVar(value="Ready")
            self.status_label = ttk.Label(main, textvariable=self.status_var)
            self.status_label.pack(fill="x", padx=8, pady=(0, 4))
            self.last_deal_ticket = 0
            self.last_deal_count = 0
            self.auto_push_thread = None
            # Activity feed list (fallback)
            self._activity_items = []
            return

        # ══════════════════════════════════════════════════════════
        #  MODERN CTK LAYOUT — Two columns, single screen
        # ══════════════════════════════════════════════════════════

        # ── Outer container (no scroll — single screen) ──
        outer = ctk.CTkFrame(self.root, fg_color=self.C_BG)
        outer.pack(fill="both", expand=True)

        # ── TOP BAR — slim, compact ──
        top_bar = ctk.CTkFrame(outer, fg_color="#1A2332", height=38, corner_radius=0)
        top_bar.pack(fill="x")
        top_bar.pack_propagate(False)
        # Gold accent line
        ctk.CTkFrame(top_bar, height=3, fg_color=self.C_GOLD, corner_radius=0).pack(fill="x", side="top")
        bar_inner = ctk.CTkFrame(top_bar, fg_color="transparent")
        bar_inner.pack(fill="both", expand=True, padx=16)
        # Right side: MT5 status
        self._conn_dot = ctk.CTkFrame(bar_inner, width=8, height=8,
                                      fg_color="#EF4444", corner_radius=4)
        self._conn_dot.pack(side="right", padx=(0, 6), pady=6)
        ctk.CTkLabel(bar_inner, text="MT5", font=("Segoe UI", 9),
                     text_color=self.C_TEXT_DIM).pack(side="right", padx=(0, 4), pady=6)
        # Panel toggle button
        self._panel_btn = ctk.CTkButton(
            bar_inner, text="☰  Controls", width=110, height=28,
            fg_color=self.C_BG_THIRD, hover_color=self.C_BORDER,
            border_width=1, border_color=self.C_BORDER,
            text_color=self.C_TEXT, font=("Segoe UI", 10, "bold"),
            corner_radius=6, command=self._toggle_controls_panel)
        self._panel_btn.pack(side="right", padx=(0, 12), pady=6)

        # ── BODY — single area, swaps between Live Display and Controls ──
        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=(6, 4))
        self._body = body

        # ── VIEW 1: Live Display (default, visible) ──
        self._live_view = ctk.CTkFrame(body, fg_color="transparent")
        self._live_view.pack(fill="both", expand=True)
        self._live_view.grid_rowconfigure(0, weight=0)   # toolbar
        self._live_view.grid_rowconfigure(1, weight=3)   # active trades (main)
        self._live_view.grid_rowconfigure(2, weight=1)   # live activity + log
        self._live_view.grid_columnconfigure(0, weight=1)

        # ── Row 0: Compact toolbar (Push + Auto-Trade in one strip) ──
        toolbar = ctk.CTkFrame(self._live_view, fg_color=self.C_BG_SEC, corner_radius=8,
                               border_width=1, border_color=self.C_BORDER, height=38)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        toolbar.pack_propagate(False)

        self.push_btn_live = self._ctk_button(toolbar, text="Push Data", command=self.push_data,
                                              fg=self.C_SUCCESS, hover="#16a34a", width=90)
        self.push_btn_live.pack(side="left", padx=(8, 4), pady=5)
        self.auto_btn_live = self._ctk_button(toolbar, text="Auto-Push", command=self.toggle_auto_push,
                                              fg=self.C_ACCENT, hover=self.C_ACCENT_HV, width=90)
        self.auto_btn_live.pack(side="left", padx=(0, 8), pady=5)

        # Separator
        ctk.CTkFrame(toolbar, width=1, fg_color=self.C_BORDER).pack(side="left", fill="y", pady=6)

        self.auto_trade_btn = self._ctk_button(toolbar, text="▶ Auto-Trade",
                                               command=self._toggle_auto_trade,
                                               fg=self.C_ACCENT, hover=self.C_ACCENT_HV, width=110)
        self.auto_trade_btn.pack(side="left", padx=(8, 4), pady=5)

        self.auto_trade_immediate_var = tk.BooleanVar(value=False)
        self.auto_trade_signal_var = tk.BooleanVar(value=False)
        if CTK_AVAILABLE:
            ctk.CTkCheckBox(toolbar, text="Now", variable=self.auto_trade_immediate_var,
                            font=("Segoe UI", 9), text_color=self.C_TEXT_DIM,
                            fg_color=self.C_ACCENT, border_color=self.C_BORDER,
                            hover_color=self.C_ACCENT_HV, width=40,
                            checkbox_width=16, checkbox_height=16).pack(side="left", padx=(0, 6), pady=5)
            ctk.CTkCheckBox(toolbar, text="Actual Signal", variable=self.auto_trade_signal_var,
                            font=("Segoe UI", 9), text_color=self.C_TEXT_DIM,
                            fg_color="#f59e0b", border_color=self.C_BORDER,
                            hover_color="#d97706", width=90,
                            checkbox_width=16, checkbox_height=16).pack(side="left", padx=(0, 6), pady=5)

        self.auto_trade_status_var = tk.StringVar(value="Off")
        ctk.CTkLabel(toolbar, textvariable=self.auto_trade_status_var,
                     font=("Segoe UI", 9), text_color=self.C_TEXT_DIM).pack(side="left", padx=(0, 6))

        self.auto_trade_countdown_var = tk.StringVar(value="")
        ctk.CTkLabel(toolbar, textvariable=self.auto_trade_countdown_var,
                     font=("Consolas", 9), text_color=self.C_GOLD).pack(side="left")

        self.auto_trade_firms_var = tk.StringVar(value="")

        self._ctk_button(toolbar, text="Save Config", command=self.save_config,
                         fg=self.C_BG_THIRD, hover=self.C_BORDER, width=90).pack(side="right", padx=(0, 8), pady=5)

        # ── Row 1: Active Trades (main area — futuristic terminal) ──
        trades_card = ctk.CTkFrame(self._live_view, fg_color="#000000", corner_radius=10,
                                   border_width=1, border_color="#0F4C75")
        trades_card.grid(row=1, column=0, sticky="nsew", pady=(0, 4))

        # Terminal-style top bezel
        trades_bezel = ctk.CTkFrame(trades_card, fg_color="#030D1B", height=36, corner_radius=0)
        trades_bezel.pack(fill="x", padx=3, pady=(3, 0))
        trades_bezel.pack_propagate(False)

        # Traffic-light dots
        dot_bar = ctk.CTkFrame(trades_bezel, fg_color="transparent")
        dot_bar.pack(side="left", padx=10)
        for c in ["#EF4444", "#F59E0B", "#22C55E"]:
            ctk.CTkFrame(dot_bar, width=8, height=8, fg_color=c,
                         corner_radius=4).pack(side="left", padx=2, pady=8)

        ctk.CTkLabel(trades_bezel, text="⟐  ACTIVE TRADES",
                     font=("Consolas", 11, "bold"),
                     text_color="#00D4FF").pack(side="left", padx=(10, 0))

        self.trades_count_var = tk.StringVar(value="[ — ]")
        ctk.CTkLabel(trades_bezel, textvariable=self.trades_count_var,
                     font=("Consolas", 9), text_color="#3B6978").pack(side="left", padx=14)

        self.load_trades_btn = ctk.CTkButton(trades_bezel, text="⟳  SCAN", width=70, height=24,
                                             command=self._load_active_trades,
                                             fg_color="#0A2647", hover_color="#144272",
                                             border_width=1, border_color="#205295",
                                             font=("Consolas", 9, "bold"),
                                             text_color="#00D4FF", corner_radius=4)
        self.load_trades_btn.pack(side="right", padx=10)

        # Column headers — grid-aligned with row content
        hdr = ctk.CTkFrame(trades_card, fg_color="#060E1A", corner_radius=0, height=26)
        hdr.pack(fill="x", padx=3, pady=(1, 0))
        hdr.pack_propagate(False)
        # 3px accent spacer to match row left bar
        ctk.CTkFrame(hdr, width=3, fg_color="transparent").pack(side="left")
        for label, w in [("PROP FIRM", 110), ("ACCOUNT", 88), ("SIZE", 68),
                         ("PHASE", 88), ("NEXT", 100)]:
            ctk.CTkLabel(hdr, text=label, width=w,
                         font=("Consolas", 8, "bold"),
                         text_color="#3B6978", anchor="w").pack(side="left", padx=(8, 0))
        ctk.CTkLabel(hdr, text="ACTION",
                     font=("Consolas", 8, "bold"),
                     text_color="#3B6978").pack(side="right", padx=(0, 24))

        # Scrollable trade rows (fills remaining space)
        self._trades_scroll = ctk.CTkScrollableFrame(trades_card, fg_color="#020A14")
        self._trades_scroll.pack(fill="both", expand=True, padx=3, pady=(0, 3))
        self._trades_inner = self._trades_scroll

        # ── Row 2: Live Activity (compact bottom) ──
        display_frame = ctk.CTkFrame(self._live_view, fg_color="#000000", corner_radius=10,
                                     border_width=1, border_color="#1E293B")
        display_frame.grid(row=2, column=0, sticky="nsew")

        # Screen header — monitor bezel
        screen_top = ctk.CTkFrame(display_frame, fg_color="#0F172A", height=32, corner_radius=0)
        screen_top.pack(fill="x", padx=3, pady=(3, 0))
        screen_top.pack_propagate(False)
        dot_row = ctk.CTkFrame(screen_top, fg_color="transparent")
        dot_row.pack(side="left", padx=10)
        for c in ["#EF4444", "#F59E0B", "#22C55E"]:
            ctk.CTkFrame(dot_row, width=8, height=8, fg_color=c,
                         corner_radius=4).pack(side="left", padx=2, pady=8)
        ctk.CTkLabel(screen_top, text="LIVE  ACTIVITY", font=("Consolas", 10, "bold"),
                     text_color="#64748B").pack(side="left", padx=(10, 0))
        self._live_clock_var = tk.StringVar(value="")
        ctk.CTkLabel(screen_top, textvariable=self._live_clock_var,
                     font=("Consolas", 9), text_color="#475569").pack(side="right", padx=10)
        self._tick_live_clock()

        # Activity feed
        self._activity_scroll = ctk.CTkScrollableFrame(display_frame, fg_color="#020617",
                                                        corner_radius=0)
        self._activity_scroll.pack(fill="both", expand=True, padx=3)
        self._activity_items = []

        # Stats strip
        stats_strip = ctk.CTkFrame(display_frame, fg_color="#0F172A", height=28, corner_radius=0)
        stats_strip.pack(fill="x", padx=3, pady=(0, 3))
        stats_strip.pack_propagate(False)
        self._stat_trades_var = tk.StringVar(value="Trades: 0")
        self._stat_queue_var = tk.StringVar(value="Queue: 0")
        self._stat_push_var = tk.StringVar(value="Push: idle")
        for var in [self._stat_trades_var, self._stat_queue_var, self._stat_push_var]:
            ctk.CTkLabel(stats_strip, textvariable=var, font=("Consolas", 9),
                         text_color="#475569").pack(side="left", padx=(12, 16), pady=4)

        # Hidden log widget (still needed by self.log() method)
        self.log_text = tk.Text(self._live_view, height=0)

        # ── VIEW 2: Controls (hidden, full-screen takeover) ──
        self._controls_visible = False
        self._controls_view = ctk.CTkFrame(body, fg_color="transparent")
        # Don't pack yet — toggled on click

        self.notebook = ctk.CTkTabview(self._controls_view, fg_color=self.C_BG,
                                       segmented_button_fg_color=self.C_BG_SEC,
                                       segmented_button_selected_color=self.C_ACCENT,
                                       segmented_button_unselected_color=self.C_BG_THIRD,
                                       text_color=self.C_TEXT, corner_radius=8)
        self.notebook.pack(fill="both", expand=True)
        tab_settings = self.notebook.add("  Settings  ")

        self._build_combined_settings_tab(tab_settings)

        # ── Bottom status bar ──
        status_bar = ctk.CTkFrame(outer, fg_color=self.C_BG_SEC, height=24, corner_radius=0)
        status_bar.pack(fill="x", side="bottom")
        status_bar.pack_propagate(False)
        self.status_var = tk.StringVar(value="Ready — enter your email to get started")
        self.status_label = ctk.CTkLabel(status_bar, textvariable=self.status_var,
                                         font=("Segoe UI", 9), text_color=self.C_TEXT_DIM)
        self.status_label.pack(side="left", padx=12, pady=2)

        # State for smart auto-push
        self.last_deal_ticket = 0
        self.last_deal_count = 0
        self.auto_push_thread = None

    def _tick_live_clock(self):
        """Update the live display clock every second."""
        try:
            self._live_clock_var.set(datetime.now().strftime("%H:%M:%S"))
            self.root.after(1000, self._tick_live_clock)
        except Exception:
            pass

    def _add_activity(self, text, kind="info"):
        """Add an entry to the Live Activity display panel.
        kind: 'info', 'trade', 'push', 'error', 'queue', 'success'
        """
        COLORS = {
            "info":    "#64748B",
            "trade":   "#F59E0B",
            "push":    "#3B82F6",
            "error":   "#EF4444",
            "queue":   "#A78BFA",
            "success": "#22C55E",
        }
        ICONS = {
            "info":    "ℹ",
            "trade":   "⚡",
            "push":    "📤",
            "error":   "✖",
            "queue":   "⏳",
            "success": "✔",
        }
        if not CTK_AVAILABLE:
            return

        color = COLORS.get(kind, COLORS["info"])
        icon = ICONS.get(kind, "•")
        ts = datetime.now().strftime("%H:%M:%S")

        row = ctk.CTkFrame(self._activity_scroll, fg_color="transparent", height=22)
        row.pack(fill="x", padx=4, pady=1)
        row.pack_propagate(False)
        ctk.CTkLabel(row, text=f"{icon}", font=("Segoe UI", 10),
                     text_color=color, width=16).pack(side="left", padx=(4, 4))
        ctk.CTkLabel(row, text=ts, font=("Consolas", 9),
                     text_color="#334155").pack(side="left", padx=(0, 6))
        ctk.CTkLabel(row, text=text, font=("Segoe UI", 9),
                     text_color=color, anchor="w").pack(side="left", fill="x", expand=True)

        self._activity_items.append({"frame": row, "kind": kind})

        # Keep max 80 items
        while len(self._activity_items) > 80:
            old = self._activity_items.pop(0)
            try:
                old["frame"].destroy()
            except Exception:
                pass

        # Auto-scroll to bottom
        try:
            self._activity_scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _toggle_controls_panel(self):
        """Swap between Live Display and Controls views (full-screen takeover)."""
        if self._controls_visible:
            # Hide controls, show live display
            self._controls_view.pack_forget()
            self._live_view.pack(fill="both", expand=True)
            self._controls_visible = False
            self._panel_btn.configure(text="☰  Controls")
        else:
            # Hide live display, show controls
            self._live_view.pack_forget()
            self._controls_view.pack(fill="both", expand=True)
            self._controls_visible = True
            self._panel_btn.configure(text="◀  Back to Live")



    # ── Build Dashboard Tab ──
    def _build_combined_settings_tab(self, parent):
        """Build the combined Settings tab — Dashboard + Trading Engine in one page."""
        if CTK_AVAILABLE:
            scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
            scroll.pack(fill="both", expand=True)
            parent = scroll
        self._build_dashboard_tab(parent)
        self._build_trading_engine_ui(parent)

    def _build_dashboard_tab(self, parent):
        """Build the Dashboard section — compact layout."""

        # ── Connection Target ──
        settings = parent
        conn_card = self._section_card(settings, "CONNECTION TARGET", "🌐")
        conn_card.pack(fill="x", padx=4, pady=(4, 2))

        conn_inner = ctk.CTkFrame(conn_card, fg_color="transparent") if CTK_AVAILABLE else \
                     tk.Frame(conn_card, bg="#161B22")
        conn_inner.pack(fill="x", padx=10, pady=(2, 6))

        if CTK_AVAILABLE:
            ctk.CTkLabel(conn_inner, text="Target:", font=("Segoe UI", 11),
                         text_color=self.C_TEXT_DIM).pack(side="left", padx=(0, 8))

        self.target_var = tk.StringVar()
        self.url_keys = ["TradeOpps (Production)", "Localhost (Development)"]
        self.url_values = {
            "TradeOpps (Production)": "https://www.tradeopss.com",
            "Localhost (Development)": "http://127.0.0.1:5001"
        }

        if CTK_AVAILABLE:
            self.url_selector = ctk.CTkComboBox(conn_inner, variable=self.target_var,
                                                values=self.url_keys, state="readonly",
                                                width=280, height=32,
                                                fg_color=self.C_BG_THIRD,
                                                border_color=self.C_BORDER,
                                                button_color=self.C_ACCENT,
                                                dropdown_fg_color=self.C_BG_SEC,
                                                dropdown_hover_color=self.C_BG_THIRD,
                                                text_color=self.C_TEXT,
                                                font=("Segoe UI", 11))
            self.url_selector.pack(side="left", padx=(0, 8))
            self.url_selector.set(self.url_keys[0])
        else:
            self.url_selector = ttk.Combobox(conn_inner, textvariable=self.target_var,
                                             state="readonly", width=32)
            self.url_selector['values'] = self.url_keys
            self.url_selector.pack(side="left", fill="x", expand=True)
            self.url_selector.current(0)

        # Hidden entry for backward-compat URL storage
        self.url_entry = ttk.Entry(settings)
        self.url_entry.insert(0, self.url_values["TradeOpps (Production)"])

        def on_target_change(event=None):
            selection = self.target_var.get()
            if "Localhost" in selection:
                password = simpledialog.askstring("Developer Access",
                    "Enter password for local development:", show='*')
                if password == "tradeopss@123":
                    self.url_entry.delete(0, tk.END)
                    self.url_entry.insert(0, self.url_values[selection])
                    self.log("Switched to Localhost")
                    self.status_var.set("Target: Localhost (Dev)")
                else:
                    messagebox.showerror("Access Denied", "Incorrect password.")
                    if CTK_AVAILABLE:
                        self.url_selector.set(self.url_keys[0])
                    else:
                        self.url_selector.current(0)
                    self.url_entry.delete(0, tk.END)
                    self.url_entry.insert(0, self.url_values["TradeOpps (Production)"])
            else:
                self.url_entry.delete(0, tk.END)
                self.url_entry.insert(0, self.url_values[selection])
                self.log("Switched to Production")
                self.status_var.set("Target: Production")

        if CTK_AVAILABLE:
            self.url_selector.configure(command=lambda _: on_target_change())
        else:
            self.url_selector.bind("<<ComboboxSelected>>", on_target_change)

        # ── Client Identification (hidden entry for compat) ──
        self.client_email_entry = ctk.CTkEntry(settings, width=0, height=0) if CTK_AVAILABLE else tk.Entry(settings)
        # Don't pack — hidden, used only as data holder

        self.hierarchy_var = tk.StringVar(value="")
        self.hierarchy_label = ctk.CTkLabel(settings, textvariable=self.hierarchy_var,
                                            font=("Segoe UI", 10, "italic"),
                                            text_color=self.C_TEXT_DIM) if CTK_AVAILABLE else \
                              ttk.Label(settings, textvariable=self.hierarchy_var)
        # Don't pack — hidden

        # ── Import Data ──
        imp_card = self._section_card(settings, "IMPORT DATA", "📋")
        imp_card.pack(fill="x", padx=4, pady=2)

        imp_inner = ctk.CTkFrame(imp_card, fg_color="transparent") if CTK_AVAILABLE else \
                    tk.Frame(imp_card, bg="#161B22")
        imp_inner.pack(fill="x", padx=12, pady=(4, 4))

        self.import_source = tk.StringVar(value="sheet")
        if CTK_AVAILABLE:
            ctk.CTkRadioButton(imp_inner, text="Google Sheets", variable=self.import_source,
                               value="sheet", command=self._toggle_import_source,
                               font=("Segoe UI", 11), text_color=self.C_TEXT,
                               fg_color=self.C_ACCENT, border_color=self.C_BORDER).pack(side="left", padx=(0, 14))
            ctk.CTkRadioButton(imp_inner, text="CSV File", variable=self.import_source,
                               value="csv", command=self._toggle_import_source,
                               font=("Segoe UI", 11), text_color=self.C_TEXT,
                               fg_color=self.C_ACCENT, border_color=self.C_BORDER).pack(side="left")
        else:
            ttk.Radiobutton(imp_inner, text="Google Sheets", variable=self.import_source,
                            value="sheet", command=self._toggle_import_source).pack(side="left", padx=(0, 12))
            ttk.Radiobutton(imp_inner, text="CSV File", variable=self.import_source,
                            value="csv", command=self._toggle_import_source).pack(side="left")

        # Sheet URL row
        self.sheet_input_frame = ctk.CTkFrame(imp_card, fg_color="transparent") if CTK_AVAILABLE else \
                                 tk.Frame(imp_card, bg="#161B22")
        self.sheet_input_frame.pack(fill="x", padx=12, pady=4)
        if CTK_AVAILABLE:
            ctk.CTkLabel(self.sheet_input_frame, text="URL:", font=("Segoe UI", 11),
                         text_color=self.C_TEXT_DIM).pack(side="left", padx=(0, 6))
        self.sheet_url_entry = self._ctk_entry(self.sheet_input_frame, width=380, placeholder="Google Sheet URL...")
        self.sheet_url_entry.pack(side="left", fill="x", expand=True)

        # CSV row (hidden by default)
        self.csv_input_frame = ctk.CTkFrame(imp_card, fg_color="transparent") if CTK_AVAILABLE else \
                               tk.Frame(imp_card, bg="#161B22")
        self.csv_path_var = tk.StringVar()
        if CTK_AVAILABLE:
            ctk.CTkLabel(self.csv_input_frame, text="File:", font=("Segoe UI", 11),
                         text_color=self.C_TEXT_DIM).pack(side="left", padx=(0, 6))
            self.csv_path_entry = ctk.CTkEntry(self.csv_input_frame, textvariable=self.csv_path_var,
                                               width=280, height=32, state="disabled",
                                               fg_color=self.C_BG_THIRD, border_color=self.C_BORDER,
                                               text_color=self.C_TEXT)
        else:
            self.csv_path_entry = ttk.Entry(self.csv_input_frame, textvariable=self.csv_path_var,
                                            width=36, state='readonly')
        self.csv_path_entry.pack(side="left", padx=(0, 6))
        self._ctk_button(self.csv_input_frame, text="Browse…", command=self._browse_csv,
                         fg=self.C_BG_THIRD, hover=self.C_BORDER, width=90).pack(side="left")

        imp_btn_row = ctk.CTkFrame(imp_card, fg_color="transparent") if CTK_AVAILABLE else \
                      tk.Frame(imp_card, bg="#161B22")
        imp_btn_row.pack(fill="x", padx=12, pady=(4, 8))
        self.import_btn = self._ctk_button(imp_btn_row, text="Import Sheet Data", command=self._do_import,
                                           fg="#6366F1", hover="#4F46E5", width=180)
        self.import_btn.pack(side="left")
        self.import_hint_text = "Sheet must be publicly shared"
        if CTK_AVAILABLE:
            self.import_hint = ctk.CTkLabel(imp_btn_row, text=self.import_hint_text,
                                            font=("Segoe UI", 9, "italic"),
                                            text_color=self.C_TEXT_DIM)
        else:
            self.import_hint = ttk.Label(imp_btn_row, text=self.import_hint_text)
        self.import_hint.pack(side="left", padx=(12, 0))

    def log(self, message, level="INFO"):
        """Add a message to the log and the live activity display."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        # Feed into live display
        kind = "info"
        msg_lower = message.lower()
        if level == "ERROR" or "❌" in message or "failed" in msg_lower:
            kind = "error"
        elif "✅" in message or "success" in msg_lower:
            kind = "success"
        elif "trade" in msg_lower or "buy" in msg_lower or "sell" in msg_lower or "⚡" in message:
            kind = "trade"
        elif "push" in msg_lower or "📤" in message or "synced" in msg_lower:
            kind = "push"
        elif "queue" in msg_lower or "scheduled" in msg_lower or "⏳" in message:
            kind = "queue"
        try:
            self._add_activity(message, kind)
        except Exception:
            pass
        try:
            self.root.update_idletasks()
        except Exception:
            pass
    
    def lookup_client(self):
        """Lookup client hierarchy from email - NO API KEY REQUIRED."""
        email = self.client_email_entry.get().strip()
        dashboard_url = self.url_entry.get().strip().rstrip('/')
        
        if not email:
            messagebox.showerror("Error", "Please enter the client email")
            return
        
        self.log(f"Looking up client: {email}")
        self.hierarchy_var.set("Looking up...")
        self.root.update_idletasks()

        def _do_lookup():
            try:
                # Use public endpoint - no API key needed
                response = requests.post(
                    f"{dashboard_url}/api/client/auth",
                    json={"email": email},
                    headers={"Content-Type": "application/json"},
                    timeout=30
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        def _on_success(data=data):
                            self.client_info = data.get("identity", {})
                            client = self.client_info.get("client", "Unknown")
                            trader = self.client_info.get("trader", "Unknown")
                            admin = self.client_info.get("admin", "Unknown")
                            category = self.client_info.get("category", "Unknown")
                            
                            self.hierarchy_var.set(f"✅ {client} → Trader: {trader} → Admin: {admin} | Category: {category}")
                            if CTK_AVAILABLE:
                                self.hierarchy_label.configure(text_color='#16a34a')
                            else:
                                self.hierarchy_label.configure(foreground='#16a34a')
                            self.log(f"✅ Client found: {client} → {trader} → {admin}")
                        self.root.after(0, _on_success)
                    else:
                        error_msg = data.get("message", "Client not found")
                        def _on_not_found(msg=error_msg):
                            self.hierarchy_var.set(f"❌ {msg}")
                            if CTK_AVAILABLE:
                                self.hierarchy_label.configure(text_color='#dc2626')
                            else:
                                self.hierarchy_label.configure(foreground='#dc2626')
                            self.client_info = None
                            self.log(f"❌ Lookup failed: {msg}", "ERROR")
                        self.root.after(0, _on_not_found)
                else:
                    error_msg = f"API Error: {response.status_code}"
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("message", error_msg)
                    except:
                        pass
                    def _on_error(msg=error_msg):
                        self.hierarchy_var.set(f"❌ {msg}")
                        if CTK_AVAILABLE:
                            self.hierarchy_label.configure(text_color='#dc2626')
                        else:
                            self.hierarchy_label.configure(foreground='#dc2626')
                        self.client_info = None
                        self.log(f"❌ Lookup failed: {msg}", "ERROR")
                    self.root.after(0, _on_error)
                    
            except requests.exceptions.Timeout:
                def _on_timeout():
                    self.hierarchy_var.set("❌ Connection timeout")
                    if CTK_AVAILABLE:
                        self.hierarchy_label.configure(text_color='#dc2626')
                    else:
                        self.hierarchy_label.configure(foreground='#dc2626')
                    self.log("❌ Connection timeout", "ERROR")
                self.root.after(0, _on_timeout)
            except requests.exceptions.ConnectionError:
                def _on_conn_err():
                    self.hierarchy_var.set("❌ Cannot connect to server")
                    if CTK_AVAILABLE:
                        self.hierarchy_label.configure(text_color='#dc2626')
                    else:
                        self.hierarchy_label.configure(foreground='#dc2626')
                    self.log("❌ Cannot connect to server", "ERROR")
                self.root.after(0, _on_conn_err)
            except Exception as e:
                def _on_exc(err=str(e)):
                    self.hierarchy_var.set(f"❌ Error: {err}")
                    if CTK_AVAILABLE:
                        self.hierarchy_label.configure(text_color='#dc2626')
                    else:
                        self.hierarchy_label.configure(foreground='#dc2626')
                    self.log(f"❌ Error: {err}", "ERROR")
                self.root.after(0, _on_exc)

        threading.Thread(target=_do_lookup, daemon=True).start()
        
    def toggle_mt5_connection(self):
        """Connect or disconnect from MT5."""
        if self.pusher.connected:
            success, msg = self.pusher.disconnect_mt5()
            self.mt5_btn.configure(text="Connect to MT5")
            self.log(msg)
        else:
            login = self.mt5_login.get().strip()
            password = self.mt5_password.get()
            server = self.mt5_server.get().strip()
            
            success, msg = self.pusher.connect_mt5(login, password, server)
            if success:
                self.mt5_btn.configure(text="Disconnect MT5")
            self.log(msg, "INFO" if success else "ERROR")
            
    def push_data(self):
        """Push data to dashboard - NO API KEY REQUIRED."""
        dashboard_url = self.url_entry.get().strip().rstrip('/')
        email = self.client_email_entry.get().strip()
        
        # Use looked-up hierarchy info
        if not self.client_info:
            messagebox.showerror("Error", "Please lookup the client first by entering email and clicking 'Lookup'")
            return
        
        client_name = self.client_info.get('client', '')
        
        if not client_name:
            messagebox.showerror("Error", "Client lookup failed - no client name found")
            return
        
        self.log(f"📤 Pushing {client_name}...")
        self.status_var.set("Pushing data...")
        
        # Get MT5 data - Limit to 30 days for better coverage (especially Farming)
        account = self.pusher.get_account_info()
        if not account:
            self.log("⚠️ MT5 account info returned empty — pushing with no account data", "ERROR")
            account = {}
        positions = self.pusher.get_positions()
        if positions is None:
            self.log("⚠️ MT5 positions returned None — sending empty list")
            positions = []
        # Calculate "23rd of last month" as the from-date for deals
        from datetime import datetime as _dt
        _now = _dt.now()
        if _now.month == 1:
            _from_date = _dt(_now.year - 1, 12, 23)
        else:
            _from_date = _dt(_now.year, _now.month - 1, 23)
        _days_since_23rd = (_now - _from_date).days + 1  # +1 to include the 23rd itself
        self.log(f"📅 Fetching deals from {_from_date.strftime('%b %d')} ({_days_since_23rd} days)")

        # Fetch deals from 23rd of last month
        raw_deals = self.pusher.get_deals(days=_days_since_23rd)
        if raw_deals is None:
            self.log(f"⚠️ MT5 deals({_days_since_23rd}d) returned None — MT5 may be disconnected")
            raw_deals = []
        
        # Fetch full history (365 days) for farming deals only — needed for correct hedge day count
        all_deals_full = self.pusher.get_deals(days=365) or []
        fa_deal_ids = {d.get('ticket') or d.get('order') for d in raw_deals if '_FA' in str(d.get('comment', '')).upper()}
        for d in all_deals_full:
            comment = str(d.get('comment', '')).upper()
            if '_FA' in comment:
                deal_id = d.get('ticket') or d.get('order')
                if deal_id not in fa_deal_ids:
                    raw_deals.append(d)
                    fa_deal_ids.add(deal_id)

        # FNFT challenge filter: challenge accounts reuse the same account numbers
        # across resets, so only keep last 24h of deals with _CH in the comment.
        # Funded (_FU, _FD, _DD, _FA) deals keep the full date range.
        is_fnft = False
        try:
            srv = str(self.pusher.server or '').upper()
            cmp = str(getattr(self.pusher, 'company', '') or '').upper()
            if 'FUNDEDNEXT' in srv or 'FNFT' in srv or 'FUNDEDNEXT' in cmp or 'FNFT' in cmp:
                is_fnft = True
        except Exception:
            pass

        if is_fnft and raw_deals:
            _24h_ago = time.time() - 86400
            before_count = len(raw_deals)
            filtered = []
            for d in raw_deals:
                comment_upper = str(d.get('comment', '')).upper()
                # Challenge deals: only keep last 24h
                if '_CH' in comment_upper:
                    deal_ts = d.get('time_raw', 0)
                    if deal_ts and deal_ts >= _24h_ago:
                        filtered.append(d)
                    # else: skip old challenge deal
                else:
                    filtered.append(d)
            dropped = before_count - len(filtered)
            if dropped:
                self.log(f"🔻 Filtered {dropped} old FNFT challenge deal(s) (>24h)")
            raw_deals = filtered
        
        # Filter deals: Only keep Balance operations and Trades with valid comments
        deals = []
        if raw_deals:
            for deal in raw_deals:
                # Always keep balance/credit operations
                d_type = str(deal.get('type', '')).upper()
                if d_type in ['BALANCE', 'CREDIT', '2', '3', 'CHARGE', 'CORRECTION', 'BONUS']:
                    deals.append(deal)
                    continue
                
                # Check comment validity for trades
                comment = deal.get('comment', '')
                parsed = self.pusher.parse_deal_comment_v2(comment)
                
                is_valid = False
                if parsed:
                    # Check for .is_valid attribute (new parser) or non-None dict (fallback parser)
                    if hasattr(parsed, 'is_valid'):
                        is_valid = parsed.is_valid
                    else:
                        is_valid = True # Fallback parser returned a dict, so it found a match
                
                if is_valid:
                    deals.append(deal)
            
            if len(deals) < len(raw_deals):
                self.log(f"Filtered {len(raw_deals) - len(deals)} deals with invalid comments")

        statistics = self.pusher.calculate_statistics(deals)
        
        # Aggregate hedge results from the SAME filtered deals (respects 23rd cutoff
        # and FNFT challenge 24h filter) so hedge values match the pushed deals.
        aggregated_by_comment = []
        comment_summary = {}
        if COMMENT_PARSER_AVAILABLE and deals:
            aggregated_by_comment, _unmatched, _log = aggregate_deals_by_position(deals)
            by_phase = {}
            for agg in aggregated_by_comment:
                phase_name = agg.get('phase_name', 'UNKNOWN')
                if phase_name not in by_phase:
                    by_phase[phase_name] = {'count': 0, 'total_net_profit': 0.0}
                by_phase[phase_name]['count'] += 1
                by_phase[phase_name]['total_net_profit'] += agg.get('net_profit', 0)
            comment_summary = {'by_phase': by_phase}

        # Pre-push diagnostic: log what we're about to send
        pos_count = len(positions) if positions else 0
        deal_count = len(deals) if deals else 0
        agg_count = len(aggregated_by_comment) if aggregated_by_comment else 0
        bal = account.get('balance', 0)
        self.log(f"📦 Payload: Bal=${bal:,.0f} | {deal_count} deals | {pos_count} pos | {agg_count} hedge groups")
        
        payload = {
            "email": email,
            "account": account,
            "positions": positions,
            "deals": deals,
            "statistics": statistics,
            "evaluations": [],
            "aggregated_by_comment": aggregated_by_comment,
            "comment_summary": comment_summary,
            "dropdown_options": {}
        }
        
        try:
            # Use public endpoint - no API key needed
            response = requests.post(
                f"{dashboard_url}/api/client/push",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=120
            )
            
            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError:
                    self.log("❌ Server returned invalid JSON (not JSON response)", "ERROR")
                    self.status_var.set("Push failed - bad response")
                    return
                if data.get("status") == "success":
                    # Compact push summary
                    bal = account.get('balance', 0)
                    dep = account.get('total_deposits', 0)
                    pos_count = len(positions) if positions else 0
                    deal_count = len(deals) if deals else 0
                    agg_count = len(aggregated_by_comment) if aggregated_by_comment else 0
                    self.log(f"✅ Push OK → Bal: ${bal:,.0f} | Dep: ${dep:,.0f} | {deal_count} deals | {pos_count} pos | {agg_count} hedge groups")

                    # Surface server cell-level hedge updates
                    hedge_log = data.get("hedge_match_log", [])
                    hedge_updates = data.get("hedge_updates", 0)
                    if hedge_log:
                        for entry in hedge_log:
                            if entry.startswith("✅"):
                                self.log(f"  {entry}", "INFO")
                            elif entry.startswith("⚠") or entry.startswith("🌾"):
                                self.log(f"  {entry}", "INFO")
                        if hedge_updates:
                            self.log(f"📊 {hedge_updates} hedge cell(s) updated on dashboard")

                    self.status_var.set("Ready - Data pushed!")
                    try:
                        self._stat_push_var.set(f"Push: ✔ {hedge_updates}")
                    except Exception:
                        pass
                    # Auto-trigger hedging review after successful data push
                    try:
                        self.push_hedging_review()
                    except Exception as hr_err:
                        self.log(f"⚠️ Hedging review failed: {hr_err}", "ERROR")
                else:
                    self.log(f"❌ {data.get('message', 'Push failed')}", "ERROR")
                    self.status_var.set("Push failed")
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_msg = response.json().get("message", error_msg)
                except:
                    pass
                self.log(f"❌ Push failed: {error_msg}", "ERROR")
                self.status_var.set("Push failed")
                
        except requests.exceptions.Timeout:
            self.log("❌ Push timeout — server did not respond within 120s", "ERROR")
            self.status_var.set("Push failed - timeout")
        except requests.exceptions.ConnectionError:
            self.log("❌ Push failed — cannot connect to server", "ERROR")
            self.status_var.set("Push failed - no connection")
        except Exception as e:
            self.log(f"❌ Push error: {e}", "ERROR")
            self.status_var.set("Push failed")
    
    def push_hedging_review(self):
        """Push ONLY Live Hedging Review data (deposits, withdrawals, balance) from MT5."""
        dashboard_url = self.url_entry.get().strip().rstrip('/')
        email = self.client_email_entry.get().strip()

        if not self.client_info:
            messagebox.showerror("Error", "Please lookup the client first by entering email and clicking 'Lookup'")
            return

        if not self.pusher.connected:
            messagebox.showerror("Error", "Please connect to MT5 first")
            return

        client_name = self.client_info.get('client', '')
        self.status_var.set("Pushing hedging review...")

        account = self.pusher.get_account_info()
        if not account:
            self.log("⚠️ Hedging review skipped — MT5 account info is empty", "ERROR")
            self.status_var.set("Hedging review skipped")
            return

        deposits = float(account.get('total_deposits', 0) or 0)
        withdrawals = float(account.get('total_withdrawals', 0) or 0)
        balance = float(account.get('balance', 0) or 0)

        self.log(f"📊 HR payload: Dep=${deposits:,.0f} | Wth=${withdrawals:,.0f} | Bal=${balance:,.0f}")

        payload = {
            "email": email,
            "total_deposits": deposits,
            "total_withdrawals": withdrawals,
            "current_balance": balance
        }

        try:
            response = requests.post(
                f"{dashboard_url}/api/client/push_hedging_review",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )

            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError:
                    self.log("❌ Hedging review: server returned invalid JSON", "ERROR")
                    self.status_var.set("HR failed - bad response")
                    return
                if data.get("status") == "success":
                    hr = data.get("hedging_review") or {}
                    actual = hr.get('actual_hedging_results', 0)
                    disc = hr.get('discrepancy', 0)
                    self.log(f"📊 Hedging Review → Actual: ${actual:,.2f} | Disc: ${disc:,.2f} | Bal: ${balance:,.0f}")
                    self.status_var.set("Ready - Hedging review pushed!")
                else:
                    self.log(f"❌ {data.get('message', 'Push failed')}", "ERROR")
                    self.status_var.set("Push failed")
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_msg = response.json().get("message", error_msg)
                except:
                    pass
                self.log(f"❌ Push failed: {error_msg}", "ERROR")
                self.status_var.set("Push failed")

        except requests.exceptions.Timeout:
            self.log("❌ Hedging review timeout", "ERROR")
            self.status_var.set("HR timeout")
        except requests.exceptions.ConnectionError:
            self.log("❌ Hedging review — cannot connect", "ERROR")
            self.status_var.set("HR connection failed")
        except Exception as e:
            self.log(f"❌ Hedging review error: {e}", "ERROR")
            self.status_var.set("Push failed")

    def push_mt5_only(self):
        """Push ONLY MT5 data (deals, positions, account) to recalculate hedging review."""
        dashboard_url = self.url_entry.get().strip().rstrip('/')
        email = self.client_email_entry.get().strip()
        
        if not self.client_info:
            messagebox.showerror("Error", "Please lookup the client first by entering email and clicking 'Lookup'")
            return
        
        if not self.pusher.connected:
            messagebox.showerror("Error", "Please connect to MT5 first to push MT5 data")
            return
        
        client_name = self.client_info.get('client', '')
        
        self.log(f"📤 MT5 rebalance push for {client_name}...")
        self.status_var.set("Pushing MT5 data...")
        
        # Get MT5 data
        account = self.pusher.get_account_info() or {}
        deals = self.pusher.get_deals(days=365)  # Get 1 year of deals for hedging calculations
        
        if not account:
            self.log("⚠️ No account info available", "ERROR")
            messagebox.showerror("Error", "Could not retrieve account information from MT5.")
            return
        
        # Extract rebalance data directly from account info (MT5 provides cumulative totals)
        balance = account.get('balance', 0)
        deposits = account.get('total_deposits', 0)
        withdrawals = account.get('total_withdrawals', 0)
        
        # Calculate actual hedging results from deals (non-BALANCE trades)
        actual_hedging = 0.0
        trade_count = 0
        for deal in (deals or []):
            d_type = str(deal.get('type', '')).upper()
            if d_type not in ['BALANCE', 'CREDIT', '2', '3']:  # Skip balance and credit operations
                profit = deal.get('profit', 0) or 0
                swap = deal.get('swap', 0) or 0
                commission = deal.get('commission', 0) or 0
                actual_hedging += (profit + swap + commission)
                if deal.get('entry') == 'OUT':  # Count closed trades
                    trade_count += 1
        
        self.log(f"📊 Bal: ${balance:,.0f} | Dep: ${deposits:,.0f} | Wth: ${withdrawals:,.0f} | Hedge: ${actual_hedging:,.2f} ({trade_count} trades)")
        
        payload = {
            "email": email,
            "account": account,
            "positions": [],
            "deals": deals or [],  # Include deals for actual hedging calculation
            "statistics": {},  # Let server recalculate with MT5 data
            # NOTE: Do NOT include "evaluations" key - server will preserve existing data
            "dropdown_options": {}
        }
        
        try:
            response = requests.post(
                f"{dashboard_url}/api/client/push",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=120
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("status") == "success":
                    self.log(f"✅ Rebalance pushed — Bal: ${balance:,.0f} | Dep: ${deposits:,.0f}")
                    self.status_var.set("Rebalance data pushed!")
                else:
                    self.log(f"❌ Push failed: {data.get('message', 'Unknown error')}", "ERROR")
                    self.status_var.set("Push failed")
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_msg = response.json().get("message", error_msg)
                except:
                    pass
                self.log(f"❌ Rebalance push failed: {error_msg}", "ERROR")
                self.status_var.set("Push failed")
                
        except Exception as e:
            self.log(f"❌ Push error: {e}", "ERROR")
            self.status_var.set("Push failed")
    
    def show_deal_comments(self):
        """Debug function to show all deal comments from MT5."""
        if not self.pusher.connected:
            messagebox.showerror("Error", "Please connect to MT5 first")
            return
        
        self.log("="*60)
        self.log("🔍 MT5 DEAL COMMENTS DEBUG")
        self.log("="*60)
        
        deals = self.pusher.get_deals(days=365)
        
        if not deals:
            self.log("No deals found")
            return
        
        self.log(f"Total deals: {len(deals)}\n")
        
        # Group by unique comments
        comment_counts = {}
        for deal in deals:
            comment = deal.get('comment', '') or '(empty)'
            d_type = deal.get('type', '')
            if d_type not in ['BALANCE', 'CREDIT', '2', '3']:  # Skip balance ops
                if comment not in comment_counts:
                    comment_counts[comment] = {'count': 0, 'total_profit': 0, 'sample_deal': deal}
                comment_counts[comment]['count'] += 1
                comment_counts[comment]['total_profit'] += (deal.get('profit', 0) or 0)
        
        self.log(f"Unique comments: {len(comment_counts)}\n")
        self.log("-"*60)
        
        for comment, info in sorted(comment_counts.items()):
            parsed = self.pusher.parse_deal_comment(comment)
            
            self.log(f"\n📋 Comment: '{comment}'")
            self.log(f"   Deals: {info['count']}, Total P/L: ${info['total_profit']:.2f}")
            
            if parsed:
                self.log(f"   ✓ Parsed -> Account: {parsed['account_suffix']}")
                if parsed.get('stage'):
                    self.log(f"   ✓ Stage: {parsed['stage']}{parsed['stage_num']}")
                else:
                    self.log(f"   ⚠️ No stage pattern found (CH/FU/FA)")
            else:
                self.log(f"   ❌ Could not parse comment")
        
        self.log("\n" + "="*60)
        self.log("💡 Comment format expected:")
        self.log("   Challenge: ..._CH{n} or ...CH{n}")
        self.log("   Funded:    ..._FU{n} or ...FU{n}")
        self.log("   Farming:   ..._FA{n}_DD/MM or ...FA{n}")
        self.log("="*60)
    
    def sync_hedge_results(self):
        """
        Sync hedge results from MT5 deal comments to evaluation records.
        
        Parses deal comments to extract account number and stage:
        - Challenge: {account}_CH{n}
        - Funded: {account}_FU{n}
        - Farming: {account}_FA{n}_{DD/MM}
        
        Then updates the appropriate Hedge Result fields in evaluations.
        """
        dashboard_url = self.url_entry.get().strip().rstrip('/')
        email = self.client_email_entry.get().strip()
        
        if not self.client_info:
            messagebox.showerror("Error", "Please lookup the client first by entering email and clicking 'Lookup'")
            return
        
        if not self.pusher.connected:
            messagebox.showerror("Error", "Please connect to MT5 first")
            return
        
        client_name = self.client_info.get('client', '')
        
        self.log("="*60)
        self.log("🔗 SYNC HEDGE RESULTS FROM MT5 COMMENTS")
        self.log("="*60)
        self.status_var.set("Syncing hedge results...")
        
        # Step 1: Get current evaluations from dashboard
        self.log("\n📥 Step 1: Fetching current evaluations from dashboard...")
        try:
            response = requests.get(
                f"{dashboard_url}/api/data?client_id={client_name}",
                cookies=self.session_cookies if hasattr(self, 'session_cookies') else {},
                timeout=60
            )
            
            if response.status_code != 200:
                self.log(f"❌ Failed to fetch data: HTTP {response.status_code}", "ERROR")
                messagebox.showerror("Error", "Could not fetch current data from dashboard. Try logging in via browser first.")
                return
            
            data = response.json()
            evaluations = data.get('evaluations', [])
            
            if not evaluations:
                self.log("⚠️ No evaluations found in dashboard", "WARNING")
                messagebox.showwarning("Warning", "No evaluations found. Please import from Google Sheets first.")
                return
            
            self.log(f"   ✓ Found {len(evaluations)} evaluation records")
            
        except Exception as e:
            self.log(f"❌ Error fetching data: {e}", "ERROR")
            messagebox.showerror("Error", f"Failed to fetch data: {e}")
            return
        
        # Step 2: Get deals from MT5
        self.log("\n📊 Step 2: Fetching deals from MT5...")
        deals = self.pusher.get_deals(days=365)  # Get 1 year of deals
        
        if not deals:
            self.log("⚠️ No deals found in MT5", "WARNING")
            messagebox.showwarning("Warning", "No deals found in MT5 history.")
            return
        
        self.log(f"   ✓ Found {len(deals)} deals")
        
        # Show sample comments for debugging
        comments_with_data = [d.get('comment', '') for d in deals if d.get('comment')]
        unique_comments = list(set(comments_with_data))[:10]
        self.log(f"\n📝 Sample deal comments found:")
        for c in unique_comments:
            parsed = self.pusher.parse_deal_comment(c)
            if parsed and parsed.get('stage'):
                self.log(f"   ✓ '{c}' -> {parsed['stage']}{parsed['stage_num']}, account: {parsed['account_suffix']}")
            elif parsed and parsed.get('account_suffix'):
                self.log(f"   · '{c}' -> account: {parsed['account_suffix']} (no stage found)")
            else:
                self.log(f"   · '{c}' (not matching pattern)")
        
        # Step 3: Process deals and update evaluations
        self.log("\n🔄 Step 3: Processing deals and matching to evaluations...")
        updated_evals, match_log = self.pusher.process_deals_for_evaluations(deals, evaluations)
        
        for log_line in match_log:
            self.log(f"   {log_line}")
        
        # Step 4: Push updated evaluations back to dashboard
        self.log("\n📤 Step 4: Pushing updated evaluations to dashboard...")
        
        payload = {
            "email": email,
            "evaluations": updated_evals,
            "statistics": {},  # Let server recalculate
            "dropdown_options": {}
        }
        
        try:
            response = requests.post(
                f"{dashboard_url}/api/client/push",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=120
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    self.log(f"\n✅ HEDGE RESULTS SYNCED SUCCESSFULLY!")
                    self.log(f"   Updated {len(updated_evals)} evaluation records")
                    self.log("="*60)
                    self.status_var.set("Hedge results synced!")
                    messagebox.showinfo("Success", "Hedge results synced from MT5 comments!")
                else:
                    self.log(f"❌ Sync failed: {data.get('message', 'Unknown error')}", "ERROR")
                    self.status_var.set("Sync failed")
            else:
                self.log(f"❌ HTTP {response.status_code}", "ERROR")
                self.status_var.set("Sync failed")
                
        except Exception as e:
            self.log(f"❌ Sync error: {e}", "ERROR")
            self.status_var.set("Sync failed")
    
    def analyze_comments_v2(self):
        """
        Analyze MT5 deal comments using the new TradeAccountConnector format.
        
        Shows detailed breakdown of:
        - Comment format: {TradovateAccountNumber}{PhaseSuffix}
        - Phases: CH (Challenge), FD (Funded), DD (DoubleDip), FA (Farming)
        """
        if not self.pusher.connected:
            messagebox.showerror("Error", "Please connect to MT5 first")
            return
        
        self.log("="*70)
        self.log("🔬 MT5 COMMENT ANALYSIS (TradeAccountConnector Format)")
        self.log("="*70)
        
        if not COMMENT_PARSER_AVAILABLE:
            self.log("⚠️ Comment Parser module not available!", "ERROR")
            self.log("   Please ensure mt5_comment_parser.py is in the trader_companion folder")
            return
        
        deals = self.pusher.get_deals(days=365)
        
        if not deals:
            self.log("No deals found")
            return
        
        self.log(f"Total deals fetched: {len(deals)}\n")
        
        # Use the new parser
        parser = MT5CommentParser()
        
        # Analyze all unique comments
        comment_analysis = {}
        for deal in deals:
            comment = deal.get('comment', '') or ''
            d_type = str(deal.get('type', '')).upper()
            
            if d_type in ['BALANCE', 'CREDIT', '2', '3']:  # Skip balance and credit ops
                continue
                
            if comment not in comment_analysis:
                parsed = parser.parse(comment)
                comment_analysis[comment] = {
                    'parsed': parsed,
                    'count': 0,
                    'total_profit': 0,
                    'total_commission': 0,
                    'total_swap': 0
                }
            
            comment_analysis[comment]['count'] += 1
            comment_analysis[comment]['total_profit'] += deal.get('profit', 0) or 0
            comment_analysis[comment]['total_commission'] += deal.get('commission', 0) or 0
            comment_analysis[comment]['total_swap'] += deal.get('swap', 0) or 0
        
        self.log(f"Unique comments found: {len(comment_analysis)}\n")
        self.log("-"*70)
        
        # Group by validity
        valid_comments = []
        invalid_comments = []
        
        for comment, data in comment_analysis.items():
            parsed = data['parsed']
            if parsed.is_valid:
                valid_comments.append((comment, data))
            else:
                invalid_comments.append((comment, data))
        
        # Show valid comments first
        self.log(f"\n✅ VALID COMMENTS ({len(valid_comments)}):\n")
        
        for comment, data in sorted(valid_comments, key=lambda x: x[0]):
            parsed = data['parsed']
            net_profit = data['total_profit'] + data['total_commission'] + data['total_swap']
            
            self.log(f"📋 '{comment}'")
            self.log(f"   Account: {parsed.account_number}")
            self.log(f"   Phase: {parsed.phase.name} ({parsed.phase_code})")
            if parsed.trade_number:
                self.log(f"   Trade #: {parsed.trade_number}")
            if parsed.farming_date:
                self.log(f"   Farming Date: {parsed.farming_date.strftime('%Y-%m-%d')}")
            self.log(f"   Deals: {data['count']}, Net P/L: ${net_profit:.2f}")
            self.log("")
        
        # Show invalid comments
        if invalid_comments:
            self.log(f"\n⚠️ UNRECOGNIZED COMMENTS ({len(invalid_comments)}):\n")
            
            for comment, data in sorted(invalid_comments, key=lambda x: x[0]):
                net_profit = data['total_profit'] + data['total_commission'] + data['total_swap']
                self.log(f"❓ '{comment or '(empty)'}'")
                self.log(f"   Deals: {data['count']}, Net P/L: ${net_profit:.2f}")
                self.log("")
        
        self.log("-"*70)
        self.log("\n📖 EXPECTED COMMENT FORMATS:")
        self.log("   Challenge:    {Account}_CH{1-4}     (e.g., MFFUEVSTP326057008_CH1)")
        self.log("   Funded:       {Account}_FD{0-4}     (e.g., MFFUEVSTP326057008_FD2)")
        self.log("   Double Dip:   {Account}_DD{1-4}     (e.g., MFFUEVSTP326057008_DD1)")
        self.log("   Farming:      {Account}_FA          (e.g., MFFUEVSTP326057008_FA)")
        self.log("   Farming+Date: {Account}_FA_DDMMYY  (e.g., MFFUEVSTP326057008_FA_210126)")
        self.log("="*70)
    
    def show_aggregated_data(self):
        """
        Show aggregated deal data by account and phase.
        Uses the new comment parser to group deals.
        """
        if not self.pusher.connected:
            messagebox.showerror("Error", "Please connect to MT5 first")
            return
        
        self.log("="*70)
        self.log("📊 AGGREGATED DEAL DATA BY ACCOUNT/PHASE")
        self.log("="*70)
        
        result = self.pusher.get_deals_grouped_by_phase(days=365)
        
        aggregated = result.get('aggregated', [])
        unmatched = result.get('unmatched', [])
        summary = result.get('summary', {})
        
        self.log(f"\nTotal aggregation groups: {len(aggregated)}")
        self.log(f"Unmatched deals: {len(unmatched)}\n")
        
        if not aggregated:
            self.log("⚠️ No aggregated data available")
            self.log("   Make sure your deals have comments in the correct format")
            return
        
        # Group by account for display
        by_account = {}
        for agg in aggregated:
            account = agg.get('account_number', 'Unknown')
            if account not in by_account:
                by_account[account] = []
            by_account[account].append(agg)
        
        self.log("-"*70)
        
        for account, trades in sorted(by_account.items()):
            account_total = sum(t.get('net_profit', 0) for t in trades)
            self.log(f"\n🏦 ACCOUNT: {account}")
            self.log(f"   Total Net P/L: ${account_total:.2f}")
            self.log("")
            
            for trade in sorted(trades, key=lambda x: (x.get('phase_code', ''), x.get('trade_number', 0) or 0)):
                phase_code = trade.get('phase_code', '?')
                phase_name = trade.get('phase_name', 'Unknown')
                trade_num = trade.get('trade_number', '')
                net_profit = trade.get('net_profit', 0)
                deal_count = trade.get('deal_count', 0)
                farming_date = trade.get('farming_date', '')
                
                label = f"{phase_code}{trade_num or ''}"
                if farming_date:
                    label += f" ({farming_date})"
                
                self.log(f"   [{label}] {phase_name}: ${net_profit:.2f} ({deal_count} deals)")
        
        # Show summary
        self.log("\n" + "-"*70)
        self.log("\n📈 SUMMARY BY PHASE:")
        by_phase = summary.get('by_phase', {})
        for phase, data in sorted(by_phase.items()):
            self.log(f"   {phase}: {data.get('count', 0)} groups, Total: ${data.get('total_net_profit', 0):.2f}")
        
       
    def push_by_comment(self):
        """
        Push hedge results to dashboard by matching MT5 order comments to evaluation accounts.
        
        This uses the TradeAccountConnector comment format:
        - {TradovateAccountNumber}_CH{1-4}: Challenge Hedge Results 1-5
        - {TradovateAccountNumber}_FD{0-4}: Funded Hedge Results  
        - {TradovateAccountNumber}_DD{1-4}: Double Dip (funded hedge results)
        - {TradovateAccountNumber}_FA or _FA_DDMMYY: Farming Hedge Days
        
        The function:
        1. Aggregates MT5 deals by account/phase from comments
        2. Sends aggregated data to dashboard
        3. Dashboard matches account numbers and updates hedge results
        """
        dashboard_url = self.url_entry.get().strip().rstrip('/')
        email = self.client_email_entry.get().strip()
        
        if not self.client_info:
            messagebox.showerror("Error", "Please lookup the client first by entering email and clicking 'Lookup'")
            return
        
        if not self.pusher.connected:
            messagebox.showerror("Error", "Please connect to MT5 first")
            return
        
        if not COMMENT_PARSER_AVAILABLE:
            messagebox.showerror("Error", "Comment Parser module not available!")
            return
        
        client_name = self.client_info.get('client', '')
        
        self.log("="*70)
        self.log("📋 PUSH HEDGE RESULTS BY COMMENT")
        self.log("="*70)
        self.log("Comment Format: {Account}_{Phase}{Number}")
        self.log("  CH1-5 → Hedge Result 1-5 (Challenge)")
        self.log("  FD0-4 → Hedge Result 1.1-5.1 (Funded)")
        self.log("  DD1-4 → Additional Funded Hedge Results")
        self.log("  FA/FA_DDMMYY → Hedge Day 1-50 (Farming)")
        self.log("Account Matching: First 4 + Last 4 characters")
        self.log("="*70)
        self.status_var.set("Processing MT5 deals...")
        
        # Step 1: Get and aggregate deals from MT5
        self.log("\n📊 Step 1: Aggregating deals from MT5 by comment...")
        
        result = self.pusher.get_deals_grouped_by_phase(days=365)
        
        aggregated = result.get('aggregated', [])
        unmatched = result.get('unmatched', [])
        summary = result.get('summary', {})
        
        if not aggregated:
            self.log("⚠️ No deals with valid comments found", "WARNING")
            messagebox.showwarning("Warning", "No deals found with valid comment format.\nExpected: {Account}_CH{1-5}, {Account}_FD{0-4}, etc.")
            return
        
        self.log(f"   ✓ Found {len(aggregated)} trade groups")
        self.log(f"   ⚠️ {len(unmatched)} deals without valid comments")
        
        # Show sample groups
        for agg in aggregated[:5]:
            account = agg.get('account_number', '')
            phase = agg.get('phase_code', '')
            trade_num = agg.get('trade_number', '')
            profit = agg.get('net_profit', 0)
            sig = f"{account[:4]}...{account[-4:]}" if len(account) >= 8 else account
            self.log(f"   • {sig}_{phase}{trade_num or ''}: ${profit:.2f}")
        
        if len(aggregated) > 5:
            self.log(f"   ... and {len(aggregated) - 5} more groups")
        
        # Step 2: Get account info
        self.log("\n📊 Step 2: Getting MT5 account info...")
        account = self.pusher.get_account_info() or {}
        deals = self.pusher.get_deals(days=365)
        
        if account:
            self.log(f"   Balance: ${account.get('balance', 0):.2f}")
            self.log(f"   Deposits: ${account.get('total_deposits', 0):.2f}")
            self.log(f"   Withdrawals: ${account.get('total_withdrawals', 0):.2f}")
        
        # Step 3: Send to dashboard (dashboard will do the matching)
        self.log("\n📤 Step 3: Sending to dashboard for matching...")
        self.status_var.set("Pushing to dashboard...")
        
        # Prepare aggregated data for dashboard
        trade_data = []
        for agg in aggregated:
            trade_data.append({
                "account_number": agg.get('account_number'),
                "phase_code": agg.get('phase_code'),
                "trade_number": agg.get('trade_number'),
                "farming_date": agg.get('farming_date'),
                "net_profit": agg.get('net_profit'),
                "deal_count": agg.get('deal_count')
            })
        
        payload = {
            "email": email,
            "account": account,
            "positions": self.pusher.get_positions(),
            "deals": deals,
            "aggregated_by_comment": trade_data,  # Dashboard will match and update
            "comment_summary": {
                "total_groups": len(aggregated),
                "unmatched_deals": len(unmatched),
                "by_phase": summary.get('by_phase', {})
            },
            "statistics": {},  # Let server recalculate
            "dropdown_options": {}
        }
        
        try:
            response = requests.post(
                f"{dashboard_url}/api/client/push",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=120
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    # Show match log from dashboard
                    hedge_log = data.get("hedge_match_log", [])
                    hedge_updates = data.get("hedge_updates", 0)
                    
                    self.log(f"\n✅ DASHBOARD MATCHING RESULTS:")
                    for log_line in hedge_log:
                        self.log(f"   {log_line}")
                    
                    self.log(f"\n✅ HEDGE RESULTS PUSHED SUCCESSFULLY!")
                    self.log(f"   {hedge_updates} hedge results updated")
                    self.log("="*70)
                    self.status_var.set(f"Pushed! {hedge_updates} updates")
                    messagebox.showinfo("Success", f"Pushed {len(trade_data)} trade groups.\n{hedge_updates} hedge results updated on dashboard!")
                else:
                    self.log(f"❌ Push failed: {data.get('message', 'Unknown error')}", "ERROR")
                    self.status_var.set("Push failed")
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_msg = response.json().get("message", error_msg)
                except:
                    pass
                self.log(f"❌ Push failed: {error_msg}", "ERROR")
                self.status_var.set("Push failed")
                
        except Exception as e:
            self.log(f"❌ Push error: {e}", "ERROR")
            self.status_var.set("Push failed")

    # ── Import source toggle helpers ──

    def _toggle_import_source(self):
        """Show/hide the correct input row based on selected import source."""
        if self.import_source.get() == 'sheet':
            self.csv_input_frame.pack_forget()
            self.sheet_input_frame.pack(fill="x", pady=2)
            self.import_btn.configure(text="Import Sheet Data")
            self.import_hint.configure(text="Sheet must be publicly shared")
        else:
            self.sheet_input_frame.pack_forget()
            self.csv_input_frame.pack(fill="x", pady=2)
            self.import_btn.configure(text="Import CSV File")
            self.import_hint.configure(text="Use a CSV exported from the dashboard")

    def _browse_csv(self):
        """Open file dialog to pick a CSV file."""
        path = filedialog.askopenfilename(
            title="Select CSV File",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if path:
            self.csv_path_var.set(path)

    def _do_import(self):
        """Route to the correct import method."""
        if self.import_source.get() == 'sheet':
            self.migrate_from_sheet()
        else:
            self.import_from_csv()

    def import_from_csv(self):
        """Import evaluation data from a CSV file previously exported from the dashboard."""
        email = self.client_email_entry.get().strip()
        csv_path = self.csv_path_var.get().strip()
        dashboard_url = self.url_entry.get().strip().rstrip('/')

        if not email:
            messagebox.showerror("Error", "Please enter your client email first")
            return

        if not csv_path:
            messagebox.showerror("Error", "Please select a CSV file first")
            return

        if not os.path.isfile(csv_path):
            messagebox.showerror("Error", f"File not found:\n{csv_path}")
            return

        if not self.client_info:
            messagebox.showerror("Error", "Please lookup the client first by entering email and clicking 'Lookup'")
            return

        client_name = self.client_info.get('client', '')
        if not client_name:
            messagebox.showerror("Error", "Client lookup failed - no client name found")
            return

        # Confirm before proceeding
        if not messagebox.askyesno("Confirm CSV Import",
                f"This will import CSV data into {client_name}'s dashboard.\n\n"
                f"File: {os.path.basename(csv_path)}\n\n"
                "Existing rows matched by Account # will be updated.\n"
                "New rows will be appended.\n\nContinue?"):
            return

        self.log(f"📂 Importing CSV for {client_name}...")
        self.status_var.set("Importing CSV...")
        self.import_btn.configure(state="disabled")
        self.root.update_idletasks()

        def _do_import():
            try:
                with open(csv_path, 'rb') as f:
                    response = requests.post(
                        f"{dashboard_url}/api/client/import_csv_companion",
                        data={"email": email},
                        files={"file": (os.path.basename(csv_path), f, "text/csv")},
                        timeout=120
                    )

                if response.status_code != 200:
                    error_msg = f"HTTP {response.status_code}"
                    try:
                        error_msg = response.json().get("message", error_msg)
                    except:
                        pass
                    def _on_http_err(msg=error_msg):
                        self.log(f"❌ CSV import failed: {msg}", "ERROR")
                        self.status_var.set("Import failed")
                        self.import_btn.configure(state="normal")
                        messagebox.showerror("Error", msg)
                    self.root.after(0, _on_http_err)
                    return

                data = response.json()
                if data.get("status") != "success":
                    error_msg = data.get("message", "Import failed")
                    def _on_api_err(msg=error_msg):
                        self.log(f"❌ {msg}", "ERROR")
                        self.status_var.set("Import failed")
                        self.import_btn.configure(state="normal")
                        messagebox.showerror("Error", msg)
                    self.root.after(0, _on_api_err)
                    return

                updated = data.get('updated', 0)
                added = data.get('added', 0)
                total = data.get('total_rows', 0)
                def _on_success():
                    self.log(f"   ✅ CSV import complete!")
                    self.log(f"   {updated} rows updated, {added} rows added ({total} total evaluations)")
                    self.status_var.set(f"Imported {updated + added} rows from CSV")
                    self.import_btn.configure(state="normal")
                    messagebox.showinfo("Success",
                        f"CSV import complete!\n\n"
                        f"• {updated} rows updated\n"
                        f"• {added} rows added\n"
                        f"• {total} total evaluations")
                    self.lookup_client()
                self.root.after(0, _on_success)

            except requests.exceptions.Timeout:
                def _on_timeout():
                    self.log("❌ Connection timeout during CSV import", "ERROR")
                    self.status_var.set("Timeout")
                    self.import_btn.configure(state="normal")
                    messagebox.showerror("Timeout", "Connection timed out. Please try again.")
                self.root.after(0, _on_timeout)
            except requests.exceptions.ConnectionError:
                def _on_conn_err():
                    self.log("❌ Could not connect to dashboard server", "ERROR")
                    self.status_var.set("Connection failed")
                    self.import_btn.configure(state="normal")
                    messagebox.showerror("Error", "Could not connect to dashboard server. Check the URL and try again.")
                self.root.after(0, _on_conn_err)
            except Exception as e:
                def _on_exc(err=str(e)):
                    self.log(f"❌ CSV import error: {err}", "ERROR")
                    self.status_var.set("Import failed")
                    self.import_btn.configure(state="normal")
                    messagebox.showerror("Error", err)
                self.root.after(0, _on_exc)

        threading.Thread(target=_do_import, daemon=True).start()

    def migrate_from_sheet(self):
        """Migrate data from Google Sheets to the dashboard with verification."""
        email = self.client_email_entry.get().strip()
        sheet_url = self.sheet_url_entry.get().strip()
        dashboard_url = self.url_entry.get().strip().rstrip('/')
        
        if not email:
            messagebox.showerror("Error", "Please enter your client email first")
            return
        
        if not sheet_url:
            messagebox.showerror("Error", "Please enter the Google Sheet URL")
            return
        
        if 'docs.google.com/spreadsheets' not in sheet_url:
            messagebox.showerror("Error", "Please enter a valid Google Sheets URL")
            return
        
        self.log(f"Migrating sheet data to dashboard...")
        self.status_var.set("Migrating sheet data...")
        self.root.update_idletasks()

        def _do_migrate():
            try:
                response = requests.post(
                    f"{dashboard_url}/api/client/migrate_sheet",
                    json={"email": email, "sheet_url": sheet_url},
                    headers={"Content-Type": "application/json"},
                    timeout=180
                )
                
                if response.status_code != 200:
                    error_msg = f"HTTP {response.status_code}"
                    try:
                        error_msg = response.json().get("message", error_msg)
                    except:
                        pass
                    def _on_err(msg=error_msg):
                        self.log(f"❌ Migration failed: {msg}", "ERROR")
                        self.status_var.set("Migration failed")
                        messagebox.showerror("Error", msg)
                    self.root.after(0, _on_err)
                    return
                
                data = response.json()
                if data.get("status") != "success":
                    error_msg = data.get("message", "Migration failed")
                    def _on_api_err(msg=error_msg):
                        self.log(f"❌ {msg}", "ERROR")
                        self.status_var.set("Migration failed")
                        messagebox.showerror("Error", msg)
                    self.root.after(0, _on_api_err)
                    return
                
                records = data.get("records_imported", 0)
                def _on_success():
                    self.log(f"   ✅ Successfully imported {records} records")
                    self.log(f"   Dashboard data fully replaced.")
                    self.status_var.set(f"Imported {records} records")
                    messagebox.showinfo("Success", f"Successfully imported {records} records.\nDashboard data has been updated.")
                    self.lookup_client()
                self.root.after(0, _on_success)
                    
            except requests.exceptions.Timeout:
                def _on_timeout():
                    self.log("❌ Connection timeout - server is still processing the sheet", "ERROR")
                    self.status_var.set("Timeout")
                    messagebox.showerror("Timeout", "Connection timed out. The sheet may be too large or the server is busy. Please try again.")
                self.root.after(0, _on_timeout)
            except requests.exceptions.ConnectionError:
                def _on_conn_err():
                    self.log("❌ Could not connect to dashboard server", "ERROR")
                    self.status_var.set("Connection failed")
                    messagebox.showerror("Error", "Could not connect to dashboard server. Check the URL and try again.")
                self.root.after(0, _on_conn_err)
            except Exception as e:
                def _on_exc(err=str(e)):
                    self.log(f"❌ Migration error: {err}", "ERROR")
                    self.status_var.set("Migration failed")
                    messagebox.showerror("Error", err)
                self.root.after(0, _on_exc)

        threading.Thread(target=_do_migrate, daemon=True).start()
    
    def verify_stats(self, local_stats, dashboard_stats):
        """Compare local stats with dashboard stats and return list of discrepancies."""
        discrepancies = []
        tolerance = 0.01  # Allow $0.01 difference for rounding
        
        # Helper to compare values
        def compare(name, local_val, dash_val):
            if isinstance(local_val, (int, float)) and isinstance(dash_val, (int, float)):
                if abs(local_val - dash_val) > tolerance:
                    discrepancies.append(f"{name}: Local=${local_val:,.2f} vs Dashboard=${dash_val:,.2f}")
            elif local_val != dash_val:
                discrepancies.append(f"{name}: Local={local_val} vs Dashboard={dash_val}")
        
        # Compare profitability_completed
        local_prof = local_stats.get('profitability_completed', {})
        dash_prof = dashboard_stats.get('profitability_completed', {})
        compare("Prof.Challenge Fees", local_prof.get('challenge_fees', 0), dash_prof.get('challenge_fees', 0))
        compare("Prof.Hedging Results", local_prof.get('hedging_results', 0), dash_prof.get('hedging_results', 0))
        compare("Prof.Farming Results", local_prof.get('farming_results', 0), dash_prof.get('farming_results', 0))
        compare("Prof.Payouts", local_prof.get('payouts', 0), dash_prof.get('payouts', 0))
        compare("Prof.Net Profit", local_prof.get('net_profit', 0), dash_prof.get('net_profit', 0))
        
        # Compare cashflow_inprogress
        local_cash = local_stats.get('cashflow_inprogress', {})
        dash_cash = dashboard_stats.get('cashflow_inprogress', {})
        compare("Cash.Challenge Fees", local_cash.get('challenge_fees', 0), dash_cash.get('challenge_fees', 0))
        compare("Cash.Hedging Results", local_cash.get('hedging_results', 0), dash_cash.get('hedging_results', 0))
        compare("Cash.Farming Results", local_cash.get('farming_results', 0), dash_cash.get('farming_results', 0))
        compare("Cash.Payouts", local_cash.get('payouts', 0), dash_cash.get('payouts', 0))
        compare("Cash.Net Profit", local_cash.get('net_profit', 0), dash_cash.get('net_profit', 0))
        
        # Compare eval_totals
        local_et = local_stats.get('eval_totals', {})
        dash_et = dashboard_stats.get('eval_totals', {})
        compare("Eval.Total Running", local_et.get('total_running', 0), dash_et.get('total_running', 0))
        compare("Eval.Total Passed", local_et.get('total_passed', 0), dash_et.get('total_passed', 0))
        compare("Eval.Total Failed", local_et.get('total_failed', 0), dash_et.get('total_failed', 0))
        
        # Compare funded_totals
        local_ft = local_stats.get('funded_totals', {})
        dash_ft = dashboard_stats.get('funded_totals', {})
        compare("Funded.Not Started", local_ft.get('not_started', 0), dash_ft.get('not_started', 0))
        compare("Funded.Ongoing", local_ft.get('ongoing', 0), dash_ft.get('ongoing', 0))
        compare("Funded.Failed", local_ft.get('failed', 0), dash_ft.get('failed', 0))
        compare("Funded.Completed", local_ft.get('completed', 0), dash_ft.get('completed', 0))
        
        return discrepancies
        
    def toggle_auto_push(self):
        """Toggle automatic data pushing."""
        if self.auto_push_enabled:
            self.auto_push_enabled = False
            try:
                self.auto_btn.configure(text="Auto-Push")
            except Exception:
                pass
            try:
                self.auto_btn_live.configure(text="Auto-Push")
            except Exception:
                pass
            self.log("Auto-push stopped")
        else:
            if not self.client_info:
                messagebox.showerror("Error", "Please lookup the client first")
                return
            
            # Initialize state
            self.last_deal_count = 0
            self.last_deal_ticket = 0
            
            self.auto_push_enabled = True
            try:
                self.auto_btn.configure(text="Stop Auto-Push")
            except Exception:
                pass
            try:
                self.auto_btn_live.configure(text="Stop Auto-Push")
            except Exception:
                pass

            self.log("Smart Auto-push started (Checking for new trades...)")
            self.auto_push_thread = threading.Thread(target=self.auto_push_loop, daemon=True)
            self.auto_push_thread.start()

    def check_and_push_update(self):
        """Check if new trades exist and push update if so."""
        if not self.auto_push_enabled: return
        
        try:
            if not self.pusher.connected:
                self.log("⚠️ Auto-push: MT5 not connected — skipping check", "ERROR")
                return

            deals = self.pusher.get_deals(days=30)
            
            if not deals:
                self.log("⚠️ Auto-push: MT5 returned 0 deals — connection issue?")
                return

            current_count = len(deals)
            last_deal = deals[-1]
            current_ticket = last_deal.get('ticket')
            
            if current_ticket is None:
                self.log("⚠️ Auto-push: last deal has no ticket ID")

            # First check — initialize state and push once
            if self.last_deal_count == 0:
                 self.last_deal_count = current_count
                 self.last_deal_ticket = current_ticket
                 self.log(f"🔍 Auto-push scan: {current_count} deals, last ticket: {current_ticket}")
                 self.push_data()
                 return

            if current_count > self.last_deal_count or current_ticket != self.last_deal_ticket:
                self.log(f"⚡ New trade! Deals: {self.last_deal_count}→{current_count} | Ticket: {current_ticket}")
                
                self.last_deal_count = current_count
                self.last_deal_ticket = current_ticket
                
                self.push_data()
                
        except Exception as e:
            self.log(f"❌ Auto-push check error: {e}", "ERROR")

    def auto_push_loop(self):
        """Background loop for smart auto-pushing."""
        cycle = 0
        while self.auto_push_enabled:
            try:
                self.root.after(0, self.check_and_push_update)
            except Exception as e:
                # Thread-safe: can't call self.log from background thread directly
                try:
                    self.root.after(0, lambda err=str(e): self.log(f"❌ Auto-push loop error: {err}", "ERROR"))
                except Exception:
                    pass
            
            # Check frequently (every 10s)
            for _ in range(10):
                if not self.auto_push_enabled:
                    break
                time.sleep(1)
            
            cycle += 1
            # Heartbeat every ~60s (6 cycles of 10s)
            if cycle % 6 == 0 and self.auto_push_enabled:
                try:
                    self.root.after(0, lambda c=cycle: self.log(f"🔍 Auto-push heartbeat (cycle {c})  — watching for new trades"))
                except Exception:
                    pass

    # ============ Trading Engine ============

    def _build_trading_engine_ui(self, parent):
        """Build the Trading Engine section with CTk styled cards."""

        # ── MT5 Connection Card ──
        mt5_card = self._section_card(parent, "MT5 CONNECTION", "🔗")
        mt5_card.pack(fill="x", padx=4, pady=(4, 2))

        mt5_row = ctk.CTkFrame(mt5_card, fg_color="transparent") if CTK_AVAILABLE else \
                  tk.Frame(mt5_card, bg="#161B22")
        mt5_row.pack(fill="x", padx=10, pady=(2, 2))

        if CTK_AVAILABLE:
            ctk.CTkLabel(mt5_row, text="Login:", font=("Segoe UI", 11),
                         text_color=self.C_TEXT_DIM).pack(side="left", padx=(0, 4))
        self.mt5_login = self._ctk_entry(mt5_row, width=120)
        self.mt5_login.pack(side="left", padx=(0, 8))

        if CTK_AVAILABLE:
            ctk.CTkLabel(mt5_row, text="Pass:", font=("Segoe UI", 11),
                         text_color=self.C_TEXT_DIM).pack(side="left", padx=(0, 4))
        self.mt5_password = self._ctk_entry(mt5_row, width=120, show="*")
        self.mt5_password.pack(side="left", padx=(0, 8))

        if CTK_AVAILABLE:
            ctk.CTkLabel(mt5_row, text="Server:", font=("Segoe UI", 11),
                         text_color=self.C_TEXT_DIM).pack(side="left", padx=(0, 4))
        self.mt5_server = self._ctk_entry(mt5_row, width=160)
        self.mt5_server.pack(side="left", padx=(0, 8))

        mt5_btn_row = ctk.CTkFrame(mt5_card, fg_color="transparent") if CTK_AVAILABLE else \
                      tk.Frame(mt5_card, bg="#161B22")
        mt5_btn_row.pack(fill="x", padx=10, pady=(0, 4))
        self.mt5_btn = self._ctk_button(mt5_btn_row, text="Connect MT5",
                                        command=self.toggle_mt5_connection,
                                        fg="#24292F", hover="#000000", width=140)
        self.mt5_btn.pack(side="left")

        if not TRADING_ENGINE_AVAILABLE:
            if CTK_AVAILABLE:
                ctk.CTkLabel(mt5_card, text="Trading engine modules not loaded — broker trading unavailable.",
                             font=("Segoe UI", 9, "italic"), text_color=self.C_GOLD,
                             wraplength=500).pack(padx=12, pady=(0, 8))
            return

        # ── Broker Connections Card ──
        broker_card = self._section_card(parent, "BROKER CONNECTIONS", "🏦")
        broker_card.pack(fill="x", padx=4, pady=2)

        # Global settings row: Platform + Mode + Connect All
        bk_global = ctk.CTkFrame(broker_card, fg_color="transparent") if CTK_AVAILABLE else \
                    tk.Frame(broker_card, bg="#161B22")
        bk_global.pack(fill="x", padx=10, pady=(2, 2))

        if CTK_AVAILABLE:
            ctk.CTkLabel(bk_global, text="Platform:", font=("Segoe UI", 11),
                         text_color=self.C_TEXT_DIM).pack(side="left", padx=(0, 4))
        self.broker_var = tk.StringVar(value="Tradovate")
        platforms = ["Tradovate", "TopStepX"]
        if CTK_AVAILABLE:
            ctk.CTkComboBox(bk_global, variable=self.broker_var, values=platforms,
                            state="readonly", width=120, height=30,
                            fg_color=self.C_BG_THIRD, border_color=self.C_BORDER,
                            button_color=self.C_ACCENT, text_color=self.C_TEXT,
                            dropdown_fg_color=self.C_BG_SEC).pack(side="left", padx=(0, 12))
        else:
            ttk.Combobox(bk_global, textvariable=self.broker_var, values=platforms,
                         state='readonly', width=14).pack(side="left", padx=(0, 8))

        if CTK_AVAILABLE:
            ctk.CTkLabel(bk_global, text="Mode:", font=("Segoe UI", 11),
                         text_color=self.C_TEXT_DIM).pack(side="left", padx=(0, 4))
        self.trading_mode_var = tk.StringVar(value="Simulation")
        if CTK_AVAILABLE:
            ctk.CTkComboBox(bk_global, variable=self.trading_mode_var,
                            values=["Simulation", "Live"], state="readonly",
                            width=120, height=30, fg_color=self.C_BG_THIRD,
                            border_color=self.C_BORDER, button_color=self.C_ACCENT,
                            text_color=self.C_TEXT,
                            dropdown_fg_color=self.C_BG_SEC).pack(side="left", padx=(0, 12))
        else:
            ttk.Combobox(bk_global, textvariable=self.trading_mode_var,
                         values=["Simulation", "Live"], state='readonly', width=14).pack(side="left", padx=(0, 10))

        self.broker_connect_all_btn = self._ctk_button(bk_global, text="Connect All",
                                                        command=self._connect_all_brokers,
                                                        fg="#24292F", hover="#000000", width=100)
        self.broker_connect_all_btn.pack(side="left", padx=(0, 6))

        self.broker_status_var = tk.StringVar(value="")
        if CTK_AVAILABLE:
            ctk.CTkLabel(bk_global, textvariable=self.broker_status_var,
                         font=("Segoe UI", 9), text_color=self.C_TEXT_DIM).pack(side="left")
        else:
            ttk.Label(bk_global, textvariable=self.broker_status_var).pack(side="left")

        # Dynamic broker rows container (populated when trades load)
        self._broker_rows_frame = ctk.CTkFrame(broker_card, fg_color="transparent") if CTK_AVAILABLE else \
                                  tk.Frame(broker_card, bg="#161B22")
        self._broker_rows_frame.pack(fill="x", padx=6, pady=(0, 4))

        if CTK_AVAILABLE:
            ctk.CTkLabel(self._broker_rows_frame,
                         text="Load trades to populate prop firm connections",
                         font=("Segoe UI", 9, "italic"), text_color="#4A5568").pack(pady=4)

        # ── Hedge Mode / Direction (inline) ──
        opts_row = ctk.CTkFrame(parent, fg_color="transparent") if CTK_AVAILABLE else \
                   tk.Frame(parent)
        opts_row.pack(fill="x", padx=10, pady=(2, 2))

        self.hedge_mode_var = tk.StringVar(value="Hedging")
        if CTK_AVAILABLE:
            ctk.CTkRadioButton(opts_row, text="Hedging (Broker+MT5)", variable=self.hedge_mode_var,
                               value="Hedging", font=("Segoe UI", 11), text_color=self.C_TEXT,
                               fg_color=self.C_ACCENT, border_color=self.C_BORDER).pack(side="left", padx=(0, 12))
            ctk.CTkRadioButton(opts_row, text="Broker Only", variable=self.hedge_mode_var,
                               value="BrokerOnly", font=("Segoe UI", 11), text_color=self.C_TEXT,
                               fg_color=self.C_ACCENT, border_color=self.C_BORDER).pack(side="left", padx=(0, 20))
        else:
            ttk.Radiobutton(opts_row, text="Hedging (Broker+MT5)", variable=self.hedge_mode_var,
                            value="Hedging").pack(side="left", padx=(0, 8))
            ttk.Radiobutton(opts_row, text="Broker Only", variable=self.hedge_mode_var,
                            value="BrokerOnly").pack(side="left", padx=(0, 16))

        self.direction_var = tk.StringVar(value="All Trades")
        if CTK_AVAILABLE:
            ctk.CTkLabel(opts_row, text="Direction:", font=("Segoe UI", 11),
                         text_color=self.C_TEXT_DIM).pack(side="left", padx=(0, 4))
            ctk.CTkComboBox(opts_row, variable=self.direction_var,
                            values=["All Trades", "Buy Only", "Sell Only"],
                            state="readonly", width=130, height=32,
                            fg_color=self.C_BG_THIRD, border_color=self.C_BORDER,
                            button_color=self.C_ACCENT, text_color=self.C_TEXT,
                            dropdown_fg_color=self.C_BG_SEC).pack(side="left")
        else:
            ttk.Label(opts_row, text="Direction:").pack(side="left", padx=(0, 4))
            ttk.Combobox(opts_row, textvariable=self.direction_var,
                         values=["All Trades", "Buy Only", "Sell Only"],
                         state='readonly', width=12).pack(side="left")

        # ── Hidden vars for backward compat with save/load config ──
        self.prop_firm_var = tk.StringVar(value="MFFU_Flex")
        self.phase_var = tk.StringVar(value="challenge_trade1")
        self.acct_size_var = tk.StringVar(value="$50,000")
        self.strategy_var = tk.StringVar(value="Random Entries")

        # Dummy combos (hidden, for _on_prop_firm_change / _update_account_sizes compat)
        self.prop_firm_combo = ttk.Combobox(parent)
        self.phase_combo = ttk.Combobox(parent)
        self.acct_size_combo = ttk.Combobox(parent)

    # ── Phase detection helpers ──

    _FIRM_MAP = {
        "My Funded Futures": "MFFU_Flex",
        "MFFU": "MFFU",
        "Funding Ticks": "FundingTicks",
        "Funded Next": "Funded Next",
        "FundedNext": "Funded Next",
        "TopStep": "TopStep",
        "TradeDay": "TradeDay",
        "Tradeify": "Tradeify",
        "Alpha Futures": "AlphaFutures",
        "Apex": "Apex",
        "Top One Futures": "Top One Futures",
    }

    _FAILED_STATUSES = {"fail", "failed", "breach", "delete", "deleted", "closed", "sl", "ended", "lost"}

    # Keywords for substring matching (catches "Fail", "Failed", "Breached", etc.)
    _INACTIVE_KEYWORDS = ("fail", "breach", "delete", "closed", "sl", "ended", "lost")

    def _detect_eval_phase(self, ev):
        """Determine current phase display name and blueprint key for an evaluation."""
        challenge_status = (ev.get("Status P1", "") or "").strip().lower()
        funded_status = (ev.get("Status", "") or "").strip().lower()
        has_funded_acct = bool((ev.get("Account #.1", "") or "").strip())

        # Check if farming data exists
        has_farming = bool((ev.get("Prop Day 1", "") or "").strip())

        if has_farming:
            return "Farming", "farming"
        elif has_funded_acct and funded_status not in self._FAILED_STATUSES:
            return "Funded", "funded_trade1"
        else:
            return "Challenge", "challenge_trade1"

    # Day-name abbreviations that traders use as placeholders
    _DAY_ABBREVS = {
        "mon": 0, "monday": 0,
        "tue": 1, "tues": 1, "tuesday": 1,
        "wed": 2, "weds": 2, "wednesday": 2,
        "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
        "fri": 4, "friday": 4,
    }

    def _get_phase_fields(self, current_phase):
        """Return the ordered list of eval field names for a phase."""
        if current_phase == "Challenge":
            return [f"Hedge Result {i}" for i in range(1, 6)]
        elif current_phase in ("Funded", "Payout 1", "Payout 2", "Payout 3", "Payout 4"):
            return [f"Hedge Result {i}.1" for i in range(1, 8)]
        elif current_phase == "Double Dip":
            return [f"Hedge Result {i}.1" for i in range(1, 8)]
        elif current_phase == "Farming":
            return [f"Hedge Day {i}" for i in range(1, 35)]
        return []

    def _count_completed_trades(self, ev, current_phase):
        """Count how many trading day cells are filled for the current phase.

        A filled cell = a trade already taken.  Empty/blank = not yet traded.
        Day-name placeholders (MON, TUE, etc.) are NOT counted as completed.
        Returns (completed_count, total_fields, next_empty_index).
        next_empty_index is 0-based: the position of the first empty cell.
        """
        fields = self._get_phase_fields(current_phase)

        completed = 0
        next_empty = None
        for i, f in enumerate(fields):
            val = ev.get(f, None)
            val_str = str(val).strip() if val is not None else ""
            if val_str in ("", "—", "-"):
                # Empty cell
                if next_empty is None:
                    next_empty = i
            elif val_str.lower() in self._DAY_ABBREVS:
                # Day placeholder — not yet traded
                if next_empty is None:
                    next_empty = i
            else:
                # Has a real value (dollar amount, etc.) — completed trade
                completed += 1

        if next_empty is None:
            next_empty = len(fields)  # All filled

        return completed, len(fields), next_empty

    def _find_tradeable_day_cell(self, ev, current_phase):
        """Find the cell that should be traded today based on day placeholders.

        A cell is tradeable today if it contains today's day name OR a
        previous weekday that hasn't been filled with a result yet (i.e. the
        trader missed entering a day and it's still pending).

        A cell whose day is AFTER today = already been prepared for the next
        trading day and should NOT be traded now.

        Returns (stage_index, day_name, is_today) or (None, None, False).
        stage_index is 0-based position in the field list.
        """
        import datetime
        today_weekday = datetime.date.today().weekday()  # 0=Mon .. 4=Fri
        fields = self._get_phase_fields(current_phase)

        best_idx = None
        best_day_name = None
        best_is_today = False

        for i, f in enumerate(fields):
            val = ev.get(f, None)
            if val is None:
                continue
            val_str = str(val).strip().lower()
            day_num = self._DAY_ABBREVS.get(val_str)
            if day_num is None:
                continue  # Not a day placeholder (result value or empty)

            if day_num == today_weekday:
                # Exact match — this cell is for today
                return i, str(val).strip().upper(), True
            elif day_num < today_weekday:
                # Previous day still has a day placeholder (not yet traded)
                # Pick the latest previous day as the one to trade
                if best_idx is None or day_num > self._DAY_ABBREVS.get(best_day_name.lower(), -1):
                    best_idx = i
                    best_day_name = str(val).strip().upper()
                    best_is_today = False
            # day_num > today_weekday → future day, skip (already prepared)

        if best_idx is not None:
            return best_idx, best_day_name, best_is_today
        return None, None, False

    def _validate_stage_consistency(self, prediction, ev, current_phase, acct_num):
        """Validate whether a trade should proceed using day placeholders as
        the primary gate, with balance and cell count as advisory warnings.

        Day placeholder rule (GATE — controls trade/no-trade):
          - Cell with today's day (or a missed previous day) → TRADE
          - No matching day placeholder found → NO TRADE
          - Only future day placeholders → NO TRADE (already prepared)

        Balance + cell count (ADVISORY — warnings only, never block):
          - If balance stage or cell count disagree, log warnings
          - But trade still proceeds if day placeholder confirms

        Returns (should_trade: bool, message: str).
        """
        import datetime
        fields = self._get_phase_fields(current_phase)
        stages = prediction.get("stages", []) if prediction else []

        # ── Primary gate: day placeholder ──
        day_idx, day_name, is_today = self._find_tradeable_day_cell(ev, current_phase)

        if day_idx is None:
            # No day placeholder for today or any missed day → don't trade
            # Check if there's a future day placeholder
            future_days = []
            today_wd = datetime.date.today().weekday()
            for i, f in enumerate(fields):
                val = ev.get(f, None)
                if val is None:
                    continue
                val_str = str(val).strip().lower()
                dn = self._DAY_ABBREVS.get(val_str)
                if dn is not None and dn > today_wd:
                    future_days.append((i, str(val).strip().upper()))

            if future_days:
                next_day = future_days[0]
                msg = (f"⏭️ {acct_num}: No trade today — "
                       f"next day placeholder is {next_day[1]} in cell {next_day[0] + 1}. "
                       f"Already prepared for next trading day.")
            else:
                msg = (f"⛔ {acct_num}: No day placeholder found for today — "
                       f"trader needs to enter a day name (MON/TUE/etc.) "
                       f"in the next cell to enable trading.")
            return False, msg

        # Day placeholder found — trade is confirmed
        day_stage_idx = min(day_idx, len(stages) - 1) if stages else day_idx
        day_label = "today" if is_today else f"missed {day_name}"

        msgs = []
        msgs.append(
            f"✅ {acct_num}: Trade confirmed via {day_name} placeholder "
            f"({'today' if is_today else 'pending from earlier'}) "
            f"in cell {day_idx + 1}")

        # ── Advisory: balance check ──
        if prediction and stages:
            balance_stage_idx = 0
            current_key = prediction.get("current_phase_key", "")
            for i, (_, key, _, _) in enumerate(stages):
                if key == current_key:
                    balance_stage_idx = i
                    break

            if balance_stage_idx != day_stage_idx:
                msgs.append(
                    f"   ⚠️ Balance advisory: balance suggests stage "
                    f"{balance_stage_idx + 1} ({prediction['current_stage']}), "
                    f"but day placeholder is in cell {day_idx + 1} (stage {day_stage_idx + 1})")

        # ── Advisory: cell count check ──
        completed, total, _ = self._count_completed_trades(ev, current_phase)
        if stages:
            expected_completed = day_idx  # Cells before the day placeholder should be filled
            if completed != expected_completed:
                msgs.append(
                    f"   ⚠️ Cell count advisory: {completed} cells filled, "
                    f"expected {expected_completed} before cell {day_idx + 1}")

        return True, "\n".join(msgs)

    def _get_current_phase_profit(self, ev, current_phase, broker_account=None, acct_size=None):
        """Get the current P/L for the active phase.

        Priority:
        1. Live broker equity (equity - starting balance) — most accurate
        2. Eval hedge result fields — fallback when broker not available
        """
        # ── 1. Try live broker equity ──
        if broker_account and acct_size:
            try:
                stats = broker_account.get_account_stats()
                balance_str = stats.get("Balance", "N/A")
                if balance_str and balance_str != "N/A":
                    cleaned = balance_str.replace("$", "").replace(",", "").strip()
                    equity = float(cleaned)
                    # Parse starting balance from acct_size (e.g. "$50,000" or "50k" → 50000)
                    start_str = str(acct_size).replace("$", "").replace(",", "").strip().lower()
                    if start_str.endswith("k"):
                        starting = float(start_str[:-1]) * 1000
                    elif start_str.replace(".", "").isdigit():
                        starting = float(start_str)
                    else:
                        starting = 50000.0
                    live_profit = equity - starting
                    if abs(live_profit) > 0.01:
                        return live_profit
            except Exception:
                pass

        # ── 2. Fallback: sum eval hedge result fields ──
        total = 0.0
        fields = []
        if current_phase == "Challenge":
            fields = [f"Hedge Result {i}" for i in range(1, 6)]
        elif current_phase in ("Funded", "Payout 1", "Payout 2", "Payout 3", "Payout 4"):
            fields = [f"Hedge Result {i}.1" for i in range(1, 8)]
        elif current_phase == "Farming":
            fields = [f"Hedge Day {i}" for i in range(1, 35)]
        elif current_phase == "Double Dip":
            fields = [f"Hedge Result {i}.1" for i in range(1, 8)]

        for f in fields:
            val = ev.get(f, None)
            if val is None or val == "" or val == "—":
                continue
            try:
                cleaned = str(val).replace("$", "").replace(",", "").strip()
                total += float(cleaned)
            except (ValueError, TypeError):
                continue
        return total

    def _get_next_phase(self, firm_code, current_display):
        """Get the next phase display name from trading_phases progression."""
        if not self.prop_firm_mgr:
            return "—"
        phases = self.prop_firm_mgr.get_prop_firm_trading_phases(firm_code)
        if not phases:
            return "—"

        # Match current_display to a phase in the list
        current_idx = -1
        for i, ph in enumerate(phases):
            if current_display.lower() in ph.lower():
                current_idx = i
                break

        if current_idx < 0:
            # Not found — guess by keyword
            for i, ph in enumerate(phases):
                if "challenge" in ph.lower() and "challenge" in current_display.lower():
                    current_idx = i
                    break
                if "fund" in ph.lower() and "fund" in current_display.lower():
                    current_idx = i
                    break
                if "farm" in ph.lower() and "farm" in current_display.lower():
                    current_idx = i
                    break

        if current_idx < 0 or current_idx >= len(phases) - 1:
            return "Complete ✓"

        return phases[current_idx + 1]

    def _is_eval_active(self, ev):
        """Check if an evaluation is active (not failed/ended/deleted).
        
        Uses substring matching so 'Fail', 'Failed', 'Breached' etc. all caught.
        """
        p1 = (ev.get("Status P1", "") or "").strip().lower()
        funded = (ev.get("Status", "") or "").strip().lower()
        has_funded_acct = bool((ev.get("Account #.1", "") or "").strip())
        has_challenge_acct = bool((ev.get("Account #", "") or "").strip())

        p1_inactive = any(kw in p1 for kw in self._INACTIVE_KEYWORDS) if p1 else False
        funded_inactive = any(kw in funded for kw in (*self._INACTIVE_KEYWORDS, "complete")) if funded else False

        # If challenge failed (regardless of whether funded acct number exists)
        if p1_inactive and not has_funded_acct:
            return False
        # If funded status is failed/completed
        if funded_inactive:
            return False
        # If challenge failed AND funded also failed — both phases dead
        if p1_inactive and has_funded_acct and funded_inactive:
            return False
        # Must have at least one account number
        if not has_challenge_acct and not has_funded_acct:
            return False
        return True

    def _refresh_eval_for_account(self, acct_num):
        """Fetch fresh eval data from dashboard for a specific account.

        Returns the updated eval dict, or None if fetch fails.
        """
        try:
            email = self.client_email_entry.get().strip()
            dashboard_url = self.url_entry.get().strip().rstrip('/')
            if not email or not dashboard_url:
                return None
            r = requests.post(
                f"{dashboard_url}/api/client/data",
                json={"email": email},
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            if r.status_code != 200:
                return None
            data = r.json()
            for ev in data.get("evaluations", []):
                acct1 = (ev.get("Account #.1", "") or ev.get("Account #", "") or "").strip()
                acct0 = (ev.get("Account #", "") or "").strip()
                if acct_num in (acct1, acct0):
                    return ev
        except Exception:
            pass
        return None

    def _load_active_trades(self):
        """Fetch evaluations from dashboard and populate the active trades list."""
        email = self.client_email_entry.get().strip()
        dashboard_url = self.url_entry.get().strip().rstrip('/')

        if not email:
            messagebox.showerror("Error", "Go to Dashboard tab, enter client email and click Lookup first.")
            return

        self.log("Loading active trades from dashboard...")
        self.load_trades_btn.configure(state='disabled')
        self.trades_count_var.set("Loading...")

        def _do_load():
            try:
                r = requests.post(
                    f"{dashboard_url}/api/client/data",
                    json={"email": email},
                    headers={"Content-Type": "application/json"},
                    timeout=15
                )
                if r.status_code != 200:
                    msg = "Unknown error"
                    try:
                        msg = r.json().get("message", msg)
                    except Exception:
                        pass
                    self.root.after(0, lambda m=msg: self.log(f"Failed to load trades: {m}", "ERROR"))
                    self.root.after(0, lambda: self.trades_count_var.set("Load failed"))
                    return
                data = r.json()
                evaluations = data.get("evaluations", [])

                # Filter using dashboard's _is_active flag (source of truth)
                # Falls back to local _is_eval_active() if flag missing
                active_evals = []
                skipped_count = 0
                for ev in evaluations:
                    if ev.get("_deleted"):
                        skipped_count += 1
                        continue

                    # Use dashboard-computed flag if available, else local fallback
                    if "_is_active" in ev:
                        is_active = ev["_is_active"]
                    else:
                        is_active = self._is_eval_active(ev)

                    if not is_active:
                        skipped_count += 1
                        continue

                    # Must have at least one account number
                    if not (ev.get("Account #", "") or "").strip() and not (ev.get("Account #.1", "") or "").strip():
                        skipped_count += 1
                        continue

                    active_evals.append(ev)

                self.root.after(0, lambda t=len(evaluations), a=len(active_evals), s=skipped_count:
                    self.log(f"📊 {t} total evaluations → {a} active, {s} filtered out (failed/completed/deleted)"))

                self.root.after(0, lambda ae=active_evals: self._populate_trade_rows(ae))

                # Populate broker connection rows per prop firm
                prop_accounts = data.get("prop_accounts", [])
                self.root.after(0, lambda ae=active_evals, pa=prop_accounts: self._populate_broker_rows(ae, pa))

                # Auto-launch browsers for prop firms that need dashboard monitoring
                active_firms = list(dict.fromkeys(
                    ev.get("Prop Firm", "") for ev in active_evals if ev.get("Prop Firm")))
                self.root.after(2000, lambda af=active_firms: self._auto_launch_propfirm_browsers(af))

                # Auto-fill MT5 credentials from dashboard if available
                mt5_creds = data.get("mt5_credentials") or {}
                mt5_login = (mt5_creds.get("login") or "").strip()
                mt5_pass = (mt5_creds.get("password") or "").strip()
                mt5_server = (mt5_creds.get("server") or "").strip()
                if mt5_login and mt5_pass and mt5_server:
                    def _fill_mt5(login=mt5_login, pwd=mt5_pass, srv=mt5_server):
                        # Only fill if fields are currently empty
                        if not self.mt5_login.get().strip():
                            self.mt5_login.delete(0, tk.END)
                            self.mt5_login.insert(0, login)
                        if not self.mt5_password.get().strip():
                            self.mt5_password.delete(0, tk.END)
                            self.mt5_password.insert(0, pwd)
                        if not self.mt5_server.get().strip():
                            self.mt5_server.delete(0, tk.END)
                            self.mt5_server.insert(0, srv)
                        self.log("🔗 MT5 credentials auto-filled from dashboard")
                    self.root.after(0, _fill_mt5)

            except Exception as e:
                self.root.after(0, lambda: self.log(f"Load trades failed: {e}", "ERROR"))
                self.root.after(0, lambda: self.trades_count_var.set("Load failed"))
            finally:
                self.root.after(0, lambda: self.load_trades_btn.configure(state='normal'))

        threading.Thread(target=_do_load, daemon=True).start()

    # Futuristic phase badge palette (border_color, bg, fg)
    _PHASE_GLOW = {
        "Challenge": ("#F59E0B", "#1A1000", "#FBBF24"),
        "Funded":    ("#22C55E", "#001A0A", "#4ADE80"),
        "Farming":   ("#3B82F6", "#001030", "#60A5FA"),
    }

    def _populate_trade_rows(self, evaluations):
        """Clear and rebuild the active trade rows — futuristic terminal style."""
        for child in self._trades_inner.winfo_children():
            child.destroy()
        self._active_trade_rows.clear()

        if not evaluations:
            if CTK_AVAILABLE:
                empty = ctk.CTkFrame(self._trades_inner, fg_color="transparent")
                empty.pack(fill="both", expand=True, pady=40)
                ctk.CTkLabel(empty, text="⟐", font=("Consolas", 28),
                             text_color="#0F4C75").pack()
                ctk.CTkLabel(empty, text="NO ACTIVE TRADES DETECTED",
                             font=("Consolas", 11, "bold"),
                             text_color="#1B4965").pack(pady=(4, 2))
                ctk.CTkLabel(empty, text="Connect and verify access to populate",
                             font=("Consolas", 9),
                             text_color="#0F3460").pack()
            else:
                tk.Label(self._trades_inner, text="No active trades found",
                         fg='#94a3b8', bg='#020A14', font=('Segoe UI', 10, 'italic')).pack(pady=20)
            self.trades_count_var.set("[ 0 ]")
            return

        # Daily bias per prop firm (persisted, resets each day)
        firms_seen = set()
        for ev in evaluations:
            firms_seen.add(ev.get("Prop Firm", "Unknown"))
        firm_bias = self._get_daily_bias(firms_seen)
        # Store for auto-trade compatibility
        self._auto_trade_firm_sides = firm_bias

        # Log bias
        bias_parts = []
        for f, s in sorted(firm_bias.items()):
            arrow = "▲" if s == "buy" else "▼"
            bias_parts.append(f"{arrow} {f}: {s.upper()}")
        self.log(f"Direction bias: {', '.join(bias_parts)}")

        for idx, ev in enumerate(evaluations):
            prop_firm_name = ev.get("Prop Firm", "Unknown")
            firm_code = self._FIRM_MAP.get(prop_firm_name, "MFFU_Flex")
            acct_num = (ev.get("Account #.1", "") or ev.get("Account #", "") or "—").strip()
            acct_size = ev.get("Account Size", "—") or "—"
            current_display, phase_key = self._detect_eval_phase(ev)
            next_display = self._get_next_phase(firm_code, current_display)

            strip_color = self.PROP_FIRM_COLORS.get(prop_firm_name, "#95A5A6")
            glow_border, glow_bg, glow_fg = self._PHASE_GLOW.get(
                current_display, ("#475569", "#0A0F1A", "#94A3B8"))

            bias = firm_bias.get(prop_firm_name, "buy")

            if CTK_AVAILABLE:
                row_bg = "#050D18" if idx % 2 == 0 else "#071020"
                row_frame = ctk.CTkFrame(self._trades_inner, fg_color=row_bg,
                                         corner_radius=4, height=44,
                                         border_width=1, border_color="#0A1628")
                row_frame.pack(fill="x", pady=1, padx=1)
                row_frame.pack_propagate(False)

                # Left accent bar
                ctk.CTkFrame(row_frame, width=3, fg_color=strip_color,
                             corner_radius=0).pack(side="left", fill="y")

                # Prop firm name — aligned with header col
                ctk.CTkLabel(row_frame, text=prop_firm_name[:18], width=110,
                             font=("Consolas", 10, "bold"), text_color=strip_color,
                             anchor="w").pack(side="left", padx=(8, 0))

                # Account number
                acct_display = acct_num[-8:] if len(acct_num) > 8 else acct_num
                ctk.CTkLabel(row_frame, text=acct_display,
                             width=88, font=("Consolas", 10),
                             text_color="#6B8DAD", anchor="w").pack(side="left", padx=(8, 0))

                # Size
                ctk.CTkLabel(row_frame, text=acct_size[:10], width=68,
                             font=("Consolas", 10), text_color="#4A7C8F",
                             anchor="w").pack(side="left", padx=(8, 0))

                # Phase badge — neon pill with border glow
                phase_holder = ctk.CTkFrame(row_frame, fg_color="transparent", width=88)
                phase_holder.pack(side="left", padx=(8, 0))
                phase_holder.pack_propagate(False)
                phase_pill = ctk.CTkFrame(phase_holder, fg_color=glow_bg,
                                          corner_radius=8, border_width=1,
                                          border_color=glow_border)
                phase_pill.pack(side="left", pady=6)
                ctk.CTkLabel(phase_pill, text=current_display.upper(),
                             font=("Consolas", 8, "bold"),
                             text_color=glow_fg).pack(padx=8, pady=1)

                # Next phase with arrow
                ctk.CTkLabel(row_frame, text=f"→ {next_display}", width=100,
                             font=("Consolas", 9), text_color="#00D4FF",
                             anchor="w").pack(side="left", padx=(8, 0))

                # BUY / SELL action buttons — bias-aware
                btn_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
                btn_frame.pack(side="right", padx=8)

                row_data = {
                    "frame": row_frame, "eval": ev, "firm_code": firm_code,
                    "phase_key": phase_key, "acct_size": acct_size,
                    "acct_num": acct_num, "current_phase": current_display,
                }

                # Active button gets neon glow, opposite gets muted/grayed
                if bias == "buy":
                    buy_fg, buy_brd, buy_txt = "#052E16", "#16A34A", "#4ADE80"
                    sell_fg, sell_brd, sell_txt = "#0A0F1A", "#1A1A2E", "#2A3040"
                else:
                    buy_fg, buy_brd, buy_txt = "#0A0F1A", "#1A1A2E", "#2A3040"
                    sell_fg, sell_brd, sell_txt = "#2D0A0A", "#DC2626", "#F87171"

                buy_btn = ctk.CTkButton(btn_frame, text="▲ BUY", width=58, height=26,
                                        fg_color=buy_fg, hover_color="#14532D" if bias == "buy" else "#0A0F1A",
                                        border_width=1, border_color=buy_brd,
                                        font=("Consolas", 9, "bold"),
                                        text_color=buy_txt, corner_radius=4,
                                        command=lambda rd=row_data: self._execute_row_trade("buy", rd))
                buy_btn.pack(side="left", padx=(0, 3))

                sell_btn = ctk.CTkButton(btn_frame, text="▼ SELL", width=58, height=26,
                                         fg_color=sell_fg, hover_color="#450A0A" if bias == "sell" else "#0A0F1A",
                                         border_width=1, border_color=sell_brd,
                                         font=("Consolas", 9, "bold"),
                                         text_color=sell_txt, corner_radius=4,
                                         command=lambda rd=row_data: self._execute_row_trade("sell", rd))
                sell_btn.pack(side="left")
            else:
                # Fallback plain tk
                row_bg = '#050D18' if idx % 2 == 0 else '#071020'
                row_frame = tk.Frame(self._trades_inner, bg=row_bg)
                row_frame.pack(fill="x", pady=1)

                tk.Label(row_frame, text=prop_firm_name[:16], width=14, anchor='w',
                         bg=row_bg, fg='#e2e8f0', font=('Consolas', 9)).pack(side="left", padx=2)
                tk.Label(row_frame, text=acct_num[:12], width=10, anchor='w',
                         bg=row_bg, fg='#6B8DAD', font=('Consolas', 9)).pack(side="left", padx=2)
                tk.Label(row_frame, text=acct_size[:10], width=8, anchor='w',
                         bg=row_bg, fg='#4A7C8F', font=('Consolas', 9)).pack(side="left", padx=2)
                tk.Label(row_frame, text=current_display, width=14, anchor='w',
                         bg=row_bg, fg='#fbbf24', font=('Consolas', 9, 'bold')).pack(side="left", padx=2)
                tk.Label(row_frame, text=f"→ {next_display}", width=14, anchor='w',
                         bg=row_bg, fg='#00D4FF', font=('Consolas', 9)).pack(side="left", padx=2)

                btn_frame = tk.Frame(row_frame, bg=row_bg)
                btn_frame.pack(side="left", padx=4)

                row_data = {
                    "frame": row_frame, "eval": ev, "firm_code": firm_code,
                    "phase_key": phase_key, "acct_size": acct_size,
                    "acct_num": acct_num, "current_phase": current_display,
                }

                buy_btn = tk.Button(btn_frame, text="▲ BUY",
                                    bg='#052E16' if bias == 'buy' else '#0A0F1A',
                                    fg='#4ADE80' if bias == 'buy' else '#2A3040',
                                    font=('Consolas', 8, 'bold'), relief='flat', padx=6, pady=1,
                                    command=lambda rd=row_data: self._execute_row_trade("buy", rd))
                buy_btn.pack(side="left", padx=(0, 4))

                sell_btn = tk.Button(btn_frame, text="▼ SELL",
                                     bg='#2D0A0A' if bias == 'sell' else '#0A0F1A',
                                     fg='#F87171' if bias == 'sell' else '#2A3040',
                                     font=('Consolas', 8, 'bold'), relief='flat', padx=6, pady=1,
                                     command=lambda rd=row_data: self._execute_row_trade("sell", rd))
                sell_btn.pack(side="left")

            row_data["buy_btn"] = buy_btn
            row_data["sell_btn"] = sell_btn
            self._active_trade_rows.append(row_data)

        count = len(self._active_trade_rows)
        self.trades_count_var.set(f"[ {count} ]")
        # Update stats strip
        try:
            self._stat_queue_var.set(f"Queue: {count}")
        except Exception:
            pass
        self.log(f"Loaded {count} active trades from dashboard")

    def _execute_row_trade(self, side, row_data):
        """Execute a trade for a specific row, then remove the row."""
        # Direction filter
        direction = self.direction_var.get()
        if direction == "Buy Only" and side == "sell":
            messagebox.showwarning("Direction Lock", "Direction is set to Buy Only")
            return
        if direction == "Sell Only" and side == "buy":
            messagebox.showwarning("Direction Lock", "Direction is set to Sell Only")
            return

        firm_code = row_data["firm_code"]
        phase_key = row_data["phase_key"]
        acct_size = row_data["acct_size"]
        acct_num = row_data["acct_num"]

        # Get trade config from blueprint
        config = None
        if self.prop_firm_mgr:
            config = self.prop_firm_mgr.get_strategy_config(firm_code, phase_key, acct_size)
        if not config:
            messagebox.showerror("Error", f"No blueprint config for {firm_code} / {phase_key} / {acct_size}")
            return

        hedging = self.hedge_mode_var.get() == "Hedging"
        platform = self.broker_var.get()
        prop_firm_name = row_data["eval"].get("Prop Firm", firm_code) if row_data.get("eval") else firm_code
        broker_account = self._get_broker_for_firm(prop_firm_name)

        if not broker_account:
            messagebox.showerror("Error", f"Connect broker for {prop_firm_name} first")
            return

        mt5_api = None
        if hedging:
            mt5_api = self._get_mt5_trading_api()
            if not mt5_api:
                messagebox.showerror("Error", "Connect MT5 for hedging mode")
                return

        trado_sym = config.get("tradovate_symbol", "") or config.get("topstepx_symbol", "")
        trado_qty = int(config.get("tradovate_qty", 2) or config.get("topstepx_qty", 2))

        # ── Balance-aware TP/SL adjustment ──
        ev = row_data.get("eval", {})
        current_profit = self._get_current_phase_profit(ev, row_data["current_phase"], broker_account=broker_account, acct_size=acct_size)
        _is_farming_sym = "MNQ" in (config.get("tradovate_symbol", "") or config.get("topstepx_symbol", "")).upper()
        if _is_farming_sym and self.prop_firm_mgr:
            # Farming: cap MT5 TP based on hard-stop proximity (not balance-based shrink)
            try:
                _bal = None
                if broker_account:
                    _stats = broker_account.get_account_stats()
                    _bal_str = _stats.get("Balance", "")
                    if _bal_str and _bal_str not in ("N/A", "Error", ""):
                        _bal = float(_bal_str.replace("$", "").replace(",", ""))
                if _bal is not None:
                    orig_mt5_tp = int(config.get("mt5_tp_points", 0))
                    config = self.prop_firm_mgr.adjust_farming_tp_sl(config, _bal, firm_code)
                    new_mt5_tp = int(config.get("mt5_tp_points", 0))
                    if new_mt5_tp != orig_mt5_tp:
                        self.log(f"🌾 Farming TP cap {acct_num}: balance=${_bal:,.2f} → MT5 TP {orig_mt5_tp}→{new_mt5_tp} pts")
                    else:
                        self.log(f"🌾 Farming TP OK {acct_num}: MT5 TP {orig_mt5_tp} pts within safe range")
                else:
                    self.log(f"⚠ Farming {acct_num}: could not read balance — using blueprint TP/SL")
            except Exception as _fe:
                self.log(f"⚠ Farming TP check failed for {acct_num}: {_fe}")
        elif current_profit != 0.0 and self.prop_firm_mgr:
            orig_tp = int(config.get("tradovate_tp_ticks", 0) or config.get("topstepx_tp_ticks", 0))
            orig_sl = int(config.get("tradovate_sl_ticks", 0) or config.get("topstepx_sl_ticks", 0))
            orig_mt5_tp = int(config.get("mt5_tp_points", 0))
            orig_mt5_sl = int(config.get("mt5_sl_points", 0))
            config = self.prop_firm_mgr.adjust_tp_sl_for_balance(config, current_profit)
            new_tp = int(config.get("tradovate_tp_ticks", 0) or config.get("topstepx_tp_ticks", 0))
            new_sl = int(config.get("tradovate_sl_ticks", 0) or config.get("topstepx_sl_ticks", 0))
            new_mt5_tp = int(config.get("mt5_tp_points", 0))
            new_mt5_sl = int(config.get("mt5_sl_points", 0))
            if new_tp != orig_tp or new_sl != orig_sl:
                mt5_part = f" | MT5 TP {orig_mt5_tp}→{new_mt5_tp}, SL {orig_mt5_sl}→{new_mt5_sl} pts" if (new_mt5_tp != orig_mt5_tp or new_mt5_sl != orig_mt5_sl) else ""
                self.log(f"📊 Balance adjust {acct_num}: P/L=${current_profit:.2f} → TP {orig_tp}→{new_tp}, SL {orig_sl}→{new_sl} ticks{mt5_part}")

        trado_tp = int(config.get("tradovate_tp_ticks", 151) or config.get("topstepx_tp_ticks", 151))
        trado_sl = int(config.get("tradovate_sl_ticks", 200) or config.get("topstepx_sl_ticks", 200))
        mt5_sym = config.get("mt5_symbol", "NAS100")
        mt5_vol = float(config.get("mt5_volume", 2.8))
        mt5_tp = int(config.get("mt5_tp_points", 46))
        mt5_sl = int(config.get("mt5_sl_points", 42))

        hedge_text = f" + MT5 {('SELL' if side == 'buy' else 'BUY')} {mt5_vol} {mt5_sym}" if hedging else ""
        balance_text = f"\nBalance P/L: ${current_profit:+.2f}" if current_profit != 0.0 else ""

        # Predict current stage and next trade from balance
        stage_text = ""
        prediction = None
        if current_profit != 0.0 and self.prop_firm_mgr:
            prediction = self.prop_firm_mgr.predict_next_trade(
                firm_code, row_data["current_phase"], current_profit,
                self.prop_firm_mgr.convert_account_size_to_key(acct_size))
            if prediction.get("stages"):
                stage_text = (f"\n\n── Stage Prediction ──"
                              f"\nCurrent: {prediction['current_stage']}  (target ${prediction['current_target']:,.0f})"
                              f"\nNext Trade: {prediction['next_stage']}")
                if prediction.get("next_config"):
                    nc = prediction["next_config"]
                    ntp = int(nc.get("tradovate_tp_ticks", 0) or nc.get("topstepx_tp_ticks", 0))
                    nsl = int(nc.get("tradovate_sl_ticks", 0) or nc.get("topstepx_sl_ticks", 0))
                    stage_text += f"  (TP:{ntp} SL:{nsl})"

        # Cross-validate: refresh eval data from dashboard for live day placeholders
        fresh_ev = self._refresh_eval_for_account(acct_num)
        if fresh_ev:
            ev = fresh_ev
            row_data["eval"] = fresh_ev  # Update cached data
        if prediction and prediction.get("stages"):
            is_consistent, val_msg = self._validate_stage_consistency(
                prediction, ev, row_data["current_phase"], acct_num)
            self.log(val_msg)
            if not is_consistent:
                stage_text += "\n\n⚠️ MISMATCH: Balance stage ≠ filled day cells!"
                messagebox.showwarning("Stage Mismatch",
                    f"{val_msg}\n\nTrade blocked — balance and day cells do not agree.")
                return

        confirm = messagebox.askyesno("Confirm Trade",
            f"{side.upper()} {trado_qty} {trado_sym} on {platform}\n"
            f"{hedge_text}\n\n"
            f"Account: {acct_num}  |  {firm_code}\n"
            f"Phase: {row_data['current_phase']}  |  Size: {acct_size}{balance_text}\n"
            f"TP: {trado_tp} ticks  |  SL: {trado_sl} ticks"
            f"{stage_text}\n\nProceed?")
        if not confirm:
            return

        # Disable buttons immediately
        row_data["buy_btn"].configure(state='disabled', text="...")
        row_data["sell_btn"].configure(state='disabled', text="...")

        prop_name = ev.get("Prop Firm", firm_code) if (ev := row_data.get("eval")) else firm_code
        hedge_tag = f" ↔ MT5 {'SELL' if side == 'buy' else 'BUY'} {mt5_vol} {mt5_sym}" if hedging else ""
        self.log(f"⚡ {side.upper()} {trado_qty} {trado_sym} → {prop_name} {acct_num} [{row_data['current_phase']}]{hedge_tag}")

        def _do_trade():
            try:
                # 1. Broker order
                if platform == "Tradovate":
                    if side == "buy":
                        broker_account.buy_market(trado_sym, trado_qty, tp=trado_tp, sl=trado_sl, expected_account=acct_num)
                    else:
                        broker_account.sell_market(trado_sym, trado_qty, tp=trado_tp, sl=trado_sl, expected_account=acct_num)
                elif platform == "TopStepX":
                    if side == "buy":
                        broker_account.place_buy_order(trado_sym, trado_qty)
                    else:
                        broker_account.place_sell_order(trado_sym, trado_qty)

                self.log(f"✅ {platform} filled {side.upper()} {trado_qty} {trado_sym} | TP:{trado_tp}t SL:{trado_sl}t | {acct_num}")

                # 2. MT5 hedge (opposite direction)
                if hedging and mt5_api:
                    hedge_side = "sell" if side == "buy" else "buy"
                    comment = f"{acct_num}_{phase_key}"
                    if hedge_side == "buy":
                        mt5_api.buy_market(mt5_sym, mt5_vol, sl=mt5_sl, tp=mt5_tp, comment=comment)
                    else:
                        mt5_api.sell_market(mt5_sym, mt5_vol, sl=mt5_sl, tp=mt5_tp, comment=comment)
                    self.log(f"✅ MT5 hedge {hedge_side.upper()} {mt5_vol} {mt5_sym} TP:{mt5_tp} SL:{mt5_sl} comment:{comment}")

                # Remove row from list
                def _remove():
                    row_data["frame"].destroy()
                    if row_data in self._active_trade_rows:
                        self._active_trade_rows.remove(row_data)
                    remaining = len(self._active_trade_rows)
                    self.trades_count_var.set(
                        f"{remaining} active trade{'s' if remaining != 1 else ''}"
                        if remaining > 0 else "All trades complete ✓")
                    try:
                        self._stat_queue_var.set(f"Queue: {remaining}")
                        # Increment trade count
                        cur = self._stat_trades_var.get()
                        n = int(cur.split(":")[1].strip()) + 1 if ":" in cur else 1
                        self._stat_trades_var.set(f"Trades: {n}")
                    except Exception:
                        pass

                self.root.after(0, _remove)

            except Exception as e:
                self.log(f"❌ Trade failed for {acct_num}: {e}", "ERROR")
                self.root.after(0, lambda: messagebox.showerror("Trade Error", str(e)))
                # Re-enable buttons on failure
                self.root.after(0, lambda: row_data["buy_btn"].configure(state='normal', text="▲ BUY"))
                self.root.after(0, lambda: row_data["sell_btn"].configure(state='normal', text="▼ SELL"))

        threading.Thread(target=_do_trade, daemon=True).start()

    # ── Auto-Trade Scheduler Logic ──

    def _toggle_auto_trade(self):
        """Toggle the auto-trade scheduler on/off."""
        if self.auto_trade_enabled:
            self._stop_auto_trade()
        else:
            self._start_auto_trade()

    def _start_auto_trade(self):
        """Activate auto-trade: compute randomized start time, begin countdown."""
        from datetime import datetime, timedelta, timezone

        # Validation: need trades loaded
        if not self._active_trade_rows:
            self.log("⚠ Load trades first before enabling auto-trade", "WARN")
            return

        # Validation: need at least one broker connected
        connected_firms = [f for f, c in self._broker_connections.items() if c.get("account")]
        if not connected_firms:
            self.log("⚠ Connect at least one broker before enabling auto-trade", "WARN")
            return

        # Validation: hedging mode needs MT5
        if self.hedge_mode_var.get() == "Hedging":
            mt5_api = self._get_mt5_trading_api()
            if not mt5_api:
                self.log("⚠ Connect MT5 first for hedging mode auto-trade", "WARN")
                return

        # Validation: signal mode needs MT5 for price data
        if self.auto_trade_signal_var.get():
            if not SIGNALS_AVAILABLE:
                self.log("⚠ Signal indicators not available — install required packages", "WARN")
                return
            if not self._ensure_mt5_for_signals():
                self.log("⚠ Connect MT5 first for Actual Signal mode (indicators need price data)", "WARN")
                return

        EAT = timezone(timedelta(hours=3))  # East Africa Time (UTC+3)
        now_eat = datetime.now(EAT)

        immediate = self.auto_trade_immediate_var.get()

        if immediate:
            # Execute immediately (5-second grace period)
            scheduled_eat = now_eat + timedelta(seconds=5)
            offset_minutes = 0
        else:
            # Base time: 2:05 AM EAT today (or tomorrow if already past ~5:05 AM)
            base = now_eat.replace(hour=2, minute=5, second=0, microsecond=0)

            # Random offset: 0 to 180 minutes (3 hours)
            offset_minutes = random.randint(0, 180)
            scheduled_eat = base + timedelta(minutes=offset_minutes)

            # If the scheduled time already passed today, schedule for tomorrow
            if scheduled_eat <= now_eat:
                scheduled_eat += timedelta(days=1)

        self._auto_trade_scheduled_dt = scheduled_eat
        self.auto_trade_enabled = True
        self._auto_trade_stop.clear()

        use_signal = self.auto_trade_signal_var.get() and SIGNALS_AVAILABLE
        self._auto_trade_use_signal = use_signal

        if use_signal:
            # Direction will be determined by indicator signals at execution time
            self._auto_trade_firm_sides = {}  # filled at execution
            self.auto_trade_firms_var.set("  📊  Directions from indicator signals")
        else:
            # Daily bias per prop firm (persisted, resets each day)
            firms_in_rows = set()
            for rd in self._active_trade_rows:
                firm_name = rd["eval"].get("Prop Firm", rd["firm_code"])
                firms_in_rows.add(firm_name)
            self._auto_trade_firm_sides = self._get_daily_bias(firms_in_rows)

            # Build display string
            dir_lines = []
            for firm, s in self._auto_trade_firm_sides.items():
                arrow = "▲" if s == "buy" else "▼"
                dir_lines.append(f"  {arrow} {s.upper():4s}  {firm}")
            self.auto_trade_firms_var.set("\n".join(dir_lines))

        mode_label = "indicator signals" if use_signal else "random dirs per firm"
        time_str = scheduled_eat.strftime("%I:%M %p EAT")
        self.auto_trade_btn.configure(text="⏹  Stop Auto-Trade")
        if CTK_AVAILABLE:
            self.auto_trade_btn.configure(fg_color='#dc2626', hover_color='#b91c1c')
        if immediate:
            self.auto_trade_status_var.set(f"Executing in 5s — {mode_label}")
            self.log(f"⚡ Auto-trade starting immediately — {mode_label}")
        else:
            self.auto_trade_status_var.set(f"Scheduled at {time_str} — {mode_label}")
            self.log(f"⏰ Auto-trade scheduled at {time_str} (+{offset_minutes}min random offset)")
        if not use_signal:
            for firm, s in self._auto_trade_firm_sides.items():
                self.log(f"   {'▲' if s == 'buy' else '▼'} {firm} → {s.upper()}")
        else:
            self.log("   📊 Directions will be generated from indicators at execution time")

        # Start background countdown / executor thread
        self.auto_trade_thread = threading.Thread(
            target=self._auto_trade_loop, daemon=True)
        self.auto_trade_thread.start()

        # Start UI countdown ticker
        self._tick_auto_trade_countdown()

    def _stop_auto_trade(self):
        """Cancel auto-trade scheduler."""
        self.auto_trade_enabled = False
        self._auto_trade_stop.set()
        self._auto_trade_scheduled_dt = None
        self.auto_trade_btn.configure(text="▶  Start Auto-Trade")
        if CTK_AVAILABLE:
            self.auto_trade_btn.configure(fg_color=self.C_ACCENT, hover_color=self.C_ACCENT_HV)
        self.auto_trade_status_var.set("Auto-trade off")
        self.auto_trade_countdown_var.set("")
        self.auto_trade_firms_var.set("")
        self._auto_trade_firm_sides = {}
        self.log("⏹ Auto-trade cancelled")

    def _tick_auto_trade_countdown(self):
        """Update the countdown label every second."""
        if not self.auto_trade_enabled or not self._auto_trade_scheduled_dt:
            return
        from datetime import datetime, timedelta, timezone
        EAT = timezone(timedelta(hours=3))
        now = datetime.now(EAT)
        remaining = self._auto_trade_scheduled_dt - now
        if remaining.total_seconds() <= 0:
            self.auto_trade_countdown_var.set("Executing now...")
            return
        hours, rem = divmod(int(remaining.total_seconds()), 3600)
        minutes, seconds = divmod(rem, 60)
        self.auto_trade_countdown_var.set(f"Starts in {hours}h {minutes}m {seconds}s")
        self.root.after(1000, self._tick_auto_trade_countdown)

    def _auto_trade_loop(self):
        """Background thread: wait until scheduled time, then execute all trades."""
        from datetime import datetime, timedelta, timezone
        EAT = timezone(timedelta(hours=3))

        while self.auto_trade_enabled and not self._auto_trade_stop.is_set():
            now = datetime.now(EAT)
            if now >= self._auto_trade_scheduled_dt:
                # Time to execute
                self.root.after(0, lambda: self.auto_trade_countdown_var.set("Executing now..."))
                self.root.after(0, self._auto_execute_all_trades)
                return
            # Sleep 1 second between checks
            self._auto_trade_stop.wait(timeout=1)

    def _auto_execute_all_trades(self):
        """Execute trades for ALL loaded rows, parallel across prop firms.

        Each prop firm has its own Chrome instance opened during initialization.
        Trades for different firms run in parallel threads (one thread per firm),
        while trades for the same firm run sequentially within that thread.
        """
        firm_sides = getattr(self, '_auto_trade_firm_sides', {})
        use_signal = getattr(self, '_auto_trade_use_signal', False)
        rows = list(self._active_trade_rows)  # snapshot

        if not rows:
            self.log("⚠ No trades to execute — list is empty")
            self._stop_auto_trade()
            return

        self.log(f"🚀 Auto-executing {len(rows)} accounts (parallel per firm)...")

        hedging = self.hedge_mode_var.get() == "Hedging"
        platform = self.broker_var.get()
        mt5_api = self._get_mt5_trading_api() if hedging else None

        # Group rows by firm so each firm's Chrome runs in its own thread
        rows_by_firm = defaultdict(list)
        for row_data in rows:
            firm_name = row_data["eval"].get("Prop Firm", row_data["firm_code"])
            rows_by_firm[firm_name].append(row_data)

        # ── PRE-VALIDATE: check which accounts actually exist on each Tradovate ──
        skipped_rows = []
        not_connected_firms = []
        if platform == "Tradovate":
            self.log("🔍 Pre-validating accounts against Tradovate dropdowns...")
            validated_by_firm = {}
            for firm_name, firm_rows in list(rows_by_firm.items()):
                broker_account = self._get_broker_for_firm(firm_name)
                if not broker_account:
                    # Firm is NOT connected — skip ALL its accounts immediately
                    not_connected_firms.append(firm_name)
                    self.log(f"⛔ {firm_name} is NOT connected — skipping {len(firm_rows)} account(s)")
                    for rd in firm_rows:
                        skipped_rows.append(rd)
                        self.log(f"   ❌ {rd['acct_num']}  ({firm_name} / {rd['current_phase']}) — firm not connected")
                    rows_by_firm[firm_name] = []  # clear all rows for this firm
                    continue

                # Read all accounts from this firm's Tradovate dropdown
                import re as _re
                try:
                    trado_accounts = broker_account.get_all_accounts()
                except Exception as e:
                    self.log(f"⚠ Could not read accounts for {firm_name}: {e}")
                    trado_accounts = []

                if not trado_accounts:
                    self.log(f"⚠ No accounts listed for {firm_name} — skipping pre-filter")
                    continue

                trado_lower = [a.lower() for a in trado_accounts]

                valid_rows = []
                for rd in firm_rows:
                    acct = str(rd["acct_num"]).strip()
                    acct_lower = acct.lower()
                    digit_match = _re.search(r'(\d{5,})$', acct)
                    digit_suffix = digit_match.group(1) if digit_match else None

                    found = False
                    for ta in trado_accounts:
                        ta_lower = ta.lower()
                        if acct_lower in ta_lower or ta_lower in acct_lower:
                            found = True
                            break
                        if digit_suffix and ta.endswith(digit_suffix):
                            found = True
                            break

                    if found:
                        valid_rows.append(rd)
                    else:
                        skipped_rows.append(rd)

                rows_by_firm[firm_name] = valid_rows
                validated_by_firm[firm_name] = len(valid_rows)

            # Log skipped accounts (those not found in Tradovate dropdown)
            missing_only = [rd for rd in skipped_rows if rd["eval"].get("Prop Firm", rd["firm_code"]) not in not_connected_firms]
            if missing_only:
                self.log(f"⛔ {len(missing_only)} account(s) NOT found on Tradovate — skipped:")
                for rd in missing_only:
                    fn = rd["eval"].get("Prop Firm", rd["firm_code"])
                    self.log(f"   ❌ {rd['acct_num']}  ({fn} / {rd['current_phase']})")

            # Mark ALL skipped rows visually (unconnected + not found)
            for rd in skipped_rows:
                def _mark_skipped(rd=rd):
                    try:
                        rd["buy_btn"].configure(state='disabled', text="N/A")
                        rd["sell_btn"].configure(state='disabled', text="N/A")
                    except Exception:
                        pass
                self.root.after(0, _mark_skipped)

            # Remove empty firms
            rows_by_firm = {f: r for f, r in rows_by_firm.items() if r}

            total_valid = sum(len(r) for r in rows_by_firm.values())
            self.log(f"✅ {total_valid} account(s) validated, {len(skipped_rows)} skipped")

            if not rows_by_firm:
                self.log("⚠ No valid accounts remain — aborting auto-trade")
                self._stop_auto_trade()
                return

        total_success = threading.Lock()
        counters = {"success": 0, "fail": 0, "skipped": len(skipped_rows)}

        def _execute_firm_trades(firm_name, firm_rows):
            """Execute all trades for one firm sequentially on its own Chrome."""
            broker_account = self._get_broker_for_firm(firm_name)
            if not broker_account:
                for rd in firm_rows:
                    self.root.after(0, lambda fn=firm_name, an=rd["acct_num"]: self.log(
                        f"❌ No broker connected for {fn} — {an} skipped", "ERROR"))
                    with total_success:
                        counters["fail"] += 1
                return

            for row_data in firm_rows:
                if self._auto_trade_stop.is_set():
                    break

                firm_code = row_data["firm_code"]
                phase_key = row_data["phase_key"]
                acct_size = row_data["acct_size"]
                acct_num = row_data["acct_num"]

                # Determine direction: signal-based or random bias
                if use_signal:
                    # Lazy-compute signal once per firm
                    if firm_name not in firm_sides:
                        config_tmp = None
                        if self.prop_firm_mgr:
                            config_tmp = self.prop_firm_mgr.get_strategy_config(
                                firm_code, phase_key, acct_size)
                        mt5_sym = (config_tmp or {}).get("mt5_symbol", "NAS100")
                        sig = self._get_signal_direction(mt5_sym)
                        firm_sides[firm_name] = sig
                        self.root.after(0, lambda fn=firm_name, s=sig, sym=mt5_sym:
                            self.log(f"   📊 {fn} ({sym}) → signal: {s.upper()}"))
                side = firm_sides.get(firm_name, random.choice(["buy", "sell"]))

                config = None
                if self.prop_firm_mgr:
                    config = self.prop_firm_mgr.get_strategy_config(
                        firm_code, phase_key, acct_size)
                if not config:
                    self.root.after(0, lambda an=acct_num, fc=firm_code, pk=phase_key, sz=acct_size: self.log(
                        f"❌ No blueprint: {an} ({fc}/{pk}/{sz}) — skipped", "ERROR"))
                    with total_success:
                        counters["fail"] += 1
                    continue

                trado_sym = config.get("tradovate_symbol", "") or config.get("topstepx_symbol", "")
                trado_qty = int(config.get("tradovate_qty", 2) or config.get("topstepx_qty", 2))

                # ── Balance-aware TP/SL adjustment ──
                auto_ev = row_data.get("eval", {})
                auto_profit = self._get_current_phase_profit(auto_ev, row_data.get("current_phase", ""), broker_account=broker_account, acct_size=acct_size)
                _is_farming_sym_auto = "MNQ" in (config.get("tradovate_symbol", "") or config.get("topstepx_symbol", "")).upper()
                if _is_farming_sym_auto and self.prop_firm_mgr:
                    # Farming: cap MT5 TP based on hard-stop proximity
                    try:
                        _bal_auto = None
                        if broker_account:
                            _stats_auto = broker_account.get_account_stats()
                            _bal_str_auto = _stats_auto.get("Balance", "")
                            if _bal_str_auto and _bal_str_auto not in ("N/A", "Error", ""):
                                _bal_auto = float(_bal_str_auto.replace("$", "").replace(",", ""))
                        if _bal_auto is not None:
                            orig_mt5_tp_a = int(config.get("mt5_tp_points", 0))
                            config = self.prop_firm_mgr.adjust_farming_tp_sl(config, _bal_auto, firm_code)
                            new_mt5_tp_a = int(config.get("mt5_tp_points", 0))
                            if new_mt5_tp_a != orig_mt5_tp_a:
                                _an, _bal_v, _omt, _nmt = acct_num, _bal_auto, orig_mt5_tp_a, new_mt5_tp_a
                                self.root.after(0, lambda an=_an, bv=_bal_v, omt=_omt, nmt=_nmt:
                                    self.log(f"🌾 Farming TP cap {an}: balance=${bv:,.2f} → MT5 TP {omt}→{nmt} pts"))
                            else:
                                _an = acct_num
                                self.root.after(0, lambda an=_an, omt=orig_mt5_tp_a:
                                    self.log(f"🌾 Farming TP OK {an}: MT5 TP {omt} pts within safe range"))
                        else:
                            _an = acct_num
                            self.root.after(0, lambda an=_an:
                                self.log(f"⚠ Farming {an}: could not read balance — using blueprint TP/SL"))
                    except Exception as _fe:
                        _an, _err = acct_num, str(_fe)
                        self.root.after(0, lambda an=_an, err=_err:
                            self.log(f"⚠ Farming TP check failed for {an}: {err}"))
                elif auto_profit != 0.0 and self.prop_firm_mgr:
                    orig_tp_auto = int(config.get("tradovate_tp_ticks", 0) or config.get("topstepx_tp_ticks", 0))
                    orig_sl_auto = int(config.get("tradovate_sl_ticks", 0) or config.get("topstepx_sl_ticks", 0))
                    orig_mt5_tp_a = int(config.get("mt5_tp_points", 0))
                    orig_mt5_sl_a = int(config.get("mt5_sl_points", 0))
                    config = self.prop_firm_mgr.adjust_tp_sl_for_balance(config, auto_profit)
                    new_tp_auto = int(config.get("tradovate_tp_ticks", 0) or config.get("topstepx_tp_ticks", 0))
                    new_sl_auto = int(config.get("tradovate_sl_ticks", 0) or config.get("topstepx_sl_ticks", 0))
                    new_mt5_tp_a = int(config.get("mt5_tp_points", 0))
                    new_mt5_sl_a = int(config.get("mt5_sl_points", 0))
                    if new_tp_auto != orig_tp_auto or new_sl_auto != orig_sl_auto:
                        mt5_changed = new_mt5_tp_a != orig_mt5_tp_a or new_mt5_sl_a != orig_mt5_sl_a
                        _an, _pl = acct_num, auto_profit
                        _otp, _ntp, _osl, _nsl = orig_tp_auto, new_tp_auto, orig_sl_auto, new_sl_auto
                        _omt, _nmt, _oms, _nms, _mc = orig_mt5_tp_a, new_mt5_tp_a, orig_mt5_sl_a, new_mt5_sl_a, mt5_changed
                        self.root.after(0, lambda an=_an, pl=_pl, otp=_otp, ntp=_ntp, osl=_osl, nsl=_nsl, omt=_omt, nmt=_nmt, oms=_oms, nms=_nms, mc=_mc:
                            self.log(f"📊 Balance adjust {an}: P/L=${pl:.2f} → TP {otp}→{ntp}, SL {osl}→{nsl} ticks"
                                     f"{f' | MT5 TP {omt}→{nmt}, SL {oms}→{nms} pts' if mc else ''}"))

                    # Log stage prediction and cross-validate
                    pred = self.prop_firm_mgr.predict_next_trade(
                        firm_code, row_data.get("current_phase", ""), auto_profit,
                        self.prop_firm_mgr.convert_account_size_to_key(acct_size))
                    if pred.get("stages"):
                        _an2, _cs, _ns = acct_num, pred["current_stage"], pred["next_stage"]
                        self.root.after(0, lambda an=_an2, cs=_cs, ns=_ns:
                            self.log(f"   🎯 {an}: Stage={cs} → Next={ns}"))

                        # Cross-validate stage vs filled day cells (refresh first)
                        fresh_auto_ev = self._refresh_eval_for_account(acct_num)
                        if fresh_auto_ev:
                            auto_ev = fresh_auto_ev
                            row_data["eval"] = fresh_auto_ev
                        is_ok, val_msg = self._validate_stage_consistency(
                            pred, auto_ev, row_data.get("current_phase", ""), acct_num)
                        _vm = val_msg
                        self.root.after(0, lambda m=_vm: self.log(m))
                        if not is_ok:
                            self.root.after(0, lambda an=acct_num:
                                self.log(f"   🚫 {an}: Skipped — stage mismatch", "ERROR"))
                            with total_success:
                                counters["fail"] += 1
                            continue

                trado_tp = int(config.get("tradovate_tp_ticks", 151) or config.get("topstepx_tp_ticks", 151))
                trado_sl = int(config.get("tradovate_sl_ticks", 200) or config.get("topstepx_sl_ticks", 200))
                mt5_sym = config.get("mt5_symbol", "NAS100")
                mt5_vol = float(config.get("mt5_volume", 2.8))
                mt5_tp = int(config.get("mt5_tp_points", 46))
                mt5_sl = int(config.get("mt5_sl_points", 42))

                try:
                    # 1. Broker order — uses this firm's own Chrome instance
                    if platform == "Tradovate":
                        if side == "buy":
                            broker_account.buy_market(trado_sym, trado_qty, tp=trado_tp, sl=trado_sl, expected_account=acct_num)
                        else:
                            broker_account.sell_market(trado_sym, trado_qty, tp=trado_tp, sl=trado_sl, expected_account=acct_num)
                    elif platform == "TopStepX":
                        if side == "buy":
                            broker_account.place_buy_order(trado_sym, trado_qty)
                        else:
                            broker_account.place_sell_order(trado_sym, trado_qty)

                    self.root.after(0, lambda an=acct_num, fc=firm_code, sd=side, sym=trado_sym, qty=trado_qty:
                        self.log(f"✅ {platform} {sd.upper()} {qty} {sym} → {an} ({fc})"))

                    # 2. MT5 hedge (opposite direction)
                    if hedging and mt5_api:
                        hedge_side = "sell" if side == "buy" else "buy"
                        comment = f"{acct_num}_{phase_key}"
                        if hedge_side == "buy":
                            mt5_api.buy_market(mt5_sym, mt5_vol, sl=mt5_sl, tp=mt5_tp, comment=comment)
                        else:
                            mt5_api.sell_market(mt5_sym, mt5_vol, sl=mt5_sl, tp=mt5_tp, comment=comment)
                        self.root.after(0, lambda an=acct_num, hs=hedge_side, vol=mt5_vol, sym=mt5_sym, cmt=comment:
                            self.log(f"✅ MT5 hedge {hs.upper()} {vol} {sym} comment:{cmt} → {an}"))

                    with total_success:
                        counters["success"] += 1

                    # Remove row from UI
                    def _remove(rd=row_data):
                        rd["frame"].destroy()
                        if rd in self._active_trade_rows:
                            self._active_trade_rows.remove(rd)
                        remaining = len(self._active_trade_rows)
                        self.trades_count_var.set(
                            f"{remaining} active trade{'s' if remaining != 1 else ''}"
                            if remaining > 0 else "All trades complete ✓")
                    self.root.after(0, _remove)

                    # Small delay between trades on the same account
                    time.sleep(2)

                except Exception as e:
                    with total_success:
                        counters["fail"] += 1
                    self.root.after(0, lambda an=acct_num, err=str(e):
                        self.log(f"❌ Auto-trade failed for {an}: {err}", "ERROR"))

        def _dispatch_parallel():
            num_firms = len(rows_by_firm)
            self.root.after(0, lambda n=num_firms: self.log(
                f"⚡ Dispatching trades across {n} firm(s) in parallel..."))
            with ThreadPoolExecutor(max_workers=num_firms) as executor:
                futures = {
                    executor.submit(_execute_firm_trades, firm, firm_rows): firm
                    for firm, firm_rows in rows_by_firm.items()
                }
                for future in as_completed(futures):
                    firm = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        self.root.after(0, lambda fn=firm, err=str(e):
                            self.log(f"❌ Firm thread {fn} crashed: {err}", "ERROR"))

            # Final summary
            self.root.after(0, lambda s=counters["success"], f=counters["fail"], sk=counters["skipped"]:
                self.log(f"🏁 Auto-trade complete: {s} succeeded, {f} failed, {sk} skipped (not on Tradovate)"))
            self.root.after(0, self._stop_auto_trade)

        threading.Thread(target=_dispatch_parallel, daemon=True).start()

    def _on_prop_firm_change(self, event=None):
        """Update phase and size options when prop firm changes (compat stub)."""
        pass

    def _update_account_sizes(self):
        """Update account size (compat stub)."""
        pass

    def _populate_broker_rows(self, evaluations, prop_accounts):
        """Build one connection row per unique prop firm from active evaluations."""
        for child in self._broker_rows_frame.winfo_children():
            child.destroy()
        # Preserve any already-connected accounts
        old_connections = dict(self._broker_connections)
        self._broker_connections.clear()

        # Get unique prop firms in order
        firms = []
        seen = set()
        for ev in evaluations:
            firm = ev.get("Prop Firm", "Unknown")
            if firm not in seen:
                seen.add(firm)
                firms.append(firm)

        if not firms:
            if CTK_AVAILABLE:
                ctk.CTkLabel(self._broker_rows_frame,
                             text="No active prop firms — load trades first",
                             font=("Segoe UI", 9, "italic"), text_color="#4A5568").pack(pady=4)
            return

        # Header row
        if CTK_AVAILABLE:
            hdr = ctk.CTkFrame(self._broker_rows_frame, fg_color="transparent")
            hdr.pack(fill="x", padx=4, pady=(2, 0))
            ctk.CTkLabel(hdr, text="PROP FIRM", width=110, font=("Consolas", 8, "bold"),
                         text_color="#4A5568", anchor="w").pack(side="left", padx=(12, 0))
            ctk.CTkLabel(hdr, text="USERNAME", width=140, font=("Consolas", 8, "bold"),
                         text_color="#4A5568", anchor="w").pack(side="left", padx=(8, 0))
            ctk.CTkLabel(hdr, text="PASSWORD", width=110, font=("Consolas", 8, "bold"),
                         text_color="#4A5568", anchor="w").pack(side="left", padx=(8, 0))

        # Build lookup from prop_accounts by prop_firm name
        pa_lookup = {}
        pa_unmatched = []  # accounts with creds but no firm match yet
        for pa in (prop_accounts or []):
            pf = (pa.get("prop_firm") or "").strip()
            has_creds = bool((pa.get("tradovate_username") or "").strip() and
                             (pa.get("tradovate_password") or "").strip())
            if pf and pf not in pa_lookup:
                pa_lookup[pf] = pa
            elif has_creds and not pf:
                pa_unmatched.append(pa)

        # Log what we received for debugging
        if prop_accounts:
            self.log(f"Dashboard prop_accounts: {len(prop_accounts)} entries, "
                     f"matched firms: {list(pa_lookup.keys())}")

        auto_count = 0
        for firm in firms:
            strip_color = self.PROP_FIRM_COLORS.get(firm, "#95A5A6")
            # Try exact match first, then case-insensitive, then alias match, then unmatched pool
            pa = pa_lookup.get(firm, {})
            if not pa:
                for pf_key, pf_val in pa_lookup.items():
                    if pf_key.lower() == firm.lower():
                        pa = pf_val
                        break
            if not pa:
                # Alias matching: firm name variants that refer to the same firm
                _FIRM_ALIASES = {
                    "funded next": ["fundednext"],
                    "fundednext": ["funded next"],
                    "my funded futures": ["mffu"],
                    "mffu": ["my funded futures"],
                }
                firm_lower = firm.lower()
                aliases = _FIRM_ALIASES.get(firm_lower, [])
                for pf_key, pf_val in pa_lookup.items():
                    if pf_key.lower() in aliases:
                        pa = pf_val
                        break
            if not pa and pa_unmatched:
                pa = pa_unmatched.pop(0)
            pre_user = (pa.get("tradovate_username") or "").strip()
            pre_pass = (pa.get("tradovate_password") or "").strip()

            # Carry over existing connected account if available
            old_conn = old_connections.get(firm, {})
            existing_account = old_conn.get("account")

            if CTK_AVAILABLE:
                row = ctk.CTkFrame(self._broker_rows_frame, fg_color="#0A1220",
                                   corner_radius=4, height=36,
                                   border_width=1, border_color="#0F1A2A")
                row.pack(fill="x", padx=4, pady=1)
                row.pack_propagate(False)

                # Accent bar
                ctk.CTkFrame(row, width=3, fg_color=strip_color,
                             corner_radius=0).pack(side="left", fill="y")

                # Firm name
                ctk.CTkLabel(row, text=firm[:16], width=110,
                             font=("Consolas", 10, "bold"), text_color=strip_color,
                             anchor="w").pack(side="left", padx=(8, 0))

                # User entry
                user_entry = ctk.CTkEntry(row, width=140, height=26,
                                          fg_color=self.C_BG_THIRD, border_color=self.C_BORDER,
                                          text_color=self.C_TEXT, font=("Consolas", 10))
                user_entry.pack(side="left", padx=(8, 0))
                if pre_user:
                    user_entry.insert(0, pre_user)

                # Pass entry
                pass_entry = ctk.CTkEntry(row, width=110, height=26, show="*",
                                          fg_color=self.C_BG_THIRD, border_color=self.C_BORDER,
                                          text_color=self.C_TEXT, font=("Consolas", 10))
                pass_entry.pack(side="left", padx=(8, 0))
                if pre_pass:
                    pass_entry.insert(0, pre_pass)

                # Status indicator
                status_var = tk.StringVar(value="✅" if existing_account else "⬚")
                status_lbl = ctk.CTkLabel(row, textvariable=status_var,
                                          font=("Segoe UI", 11), width=24,
                                          text_color="#22C55E" if existing_account else "#4A5568")
                status_lbl.pack(side="right", padx=(0, 8))

                # Connect button
                btn_text = "Connected" if existing_account else "Connect"
                conn_btn = ctk.CTkButton(row, text=btn_text, width=72, height=24,
                                         fg_color="#14532D" if existing_account else "#1A2332",
                                         hover_color="#24292F",
                                         border_width=1, border_color=self.C_BORDER,
                                         font=("Consolas", 9), text_color=self.C_TEXT,
                                         corner_radius=4,
                                         command=lambda f=firm: self._connect_broker_firm(f))
                conn_btn.pack(side="right", padx=(8, 4))

                # Dashboard button — only for firms with browser-based dashboards
                if firm in self._BROWSER_MONITORED_FIRMS:
                    dash_btn = ctk.CTkButton(row, text="🌐 Dashboard", width=90, height=24,
                                             fg_color="#1A1A3E", hover_color="#2A2A5E",
                                             border_width=1, border_color="#3B3B6E",
                                             font=("Consolas", 9), text_color="#A78BFA",
                                             corner_radius=4,
                                             command=lambda f=firm: self._launch_propfirm_dashboard(f))
                    dash_btn.pack(side="right", padx=(4, 0))

                # Dashboard button — only for firms with browser-based dashboards
                if firm in self._BROWSER_MONITORED_FIRMS:
                    dash_btn = ctk.CTkButton(row, text="🌐 Dashboard", width=90, height=24,
                                             fg_color="#1A1A3E", hover_color="#2A2A5E",
                                             border_width=1, border_color="#3B3B6E",
                                             font=("Consolas", 9), text_color="#A78BFA",
                                             corner_radius=4,
                                             command=lambda f=firm: self._launch_propfirm_dashboard(f))
                    dash_btn.pack(side="right", padx=(4, 0))
            else:
                row = tk.Frame(self._broker_rows_frame, bg="#0A1220")
                row.pack(fill="x", padx=4, pady=1)
                tk.Label(row, text=firm[:16], width=14, anchor='w',
                         bg="#0A1220", fg=strip_color, font=('Consolas', 9)).pack(side="left", padx=2)
                user_entry = ttk.Entry(row, width=16)
                user_entry.pack(side="left", padx=2)
                if pre_user:
                    user_entry.insert(0, pre_user)
                pass_entry = ttk.Entry(row, width=12, show="*")
                pass_entry.pack(side="left", padx=2)
                if pre_pass:
                    pass_entry.insert(0, pre_pass)
                conn_btn = ttk.Button(row, text="Connect",
                                      command=lambda f=firm: self._connect_broker_firm(f))
                conn_btn.pack(side="left", padx=2)
                status_var = tk.StringVar(value="✅" if existing_account else "⬚")
                status_lbl = ttk.Label(row, textvariable=status_var)
                status_lbl.pack(side="left", padx=2)

            if pre_user and pre_pass:
                auto_count += 1

            self._broker_connections[firm] = {
                "user_entry": user_entry,
                "pass_entry": pass_entry,
                "connect_btn": conn_btn,
                "status_var": status_var,
                "status_lbl": status_lbl,
                "row_frame": row,
                "account": existing_account,
            }

        if auto_count:
            self.log(f"Broker credentials found for {auto_count} prop firm(s) — auto-connecting...")
            # Auto-connect all firms that have credentials from dashboard
            self.root.after(500, self._auto_connect_populated_brokers)

    def _connect_broker_firm(self, firm_name):
        """Connect a single prop firm's broker account."""
        conn = self._broker_connections.get(firm_name)
        if not conn:
            return

        platform = self.broker_var.get()
        user = conn["user_entry"].get().strip()
        pwd = conn["pass_entry"].get().strip()
        mode = self.trading_mode_var.get()

        if not user or not pwd:
            messagebox.showerror("Error", f"Enter username and password for {firm_name}")
            return

        self.log(f"Connecting {firm_name} to {platform}...")
        conn["status_var"].set("⏳")
        conn["connect_btn"].configure(text="...")

        def _do_connect():
            try:
                if platform == "Tradovate":
                    if not TRADOVATE_AVAILABLE:
                        err = _TRADOVATE_IMPORT_ERROR or 'unknown reason'
                        self.root.after(0, lambda: conn["status_var"].set("❌"))
                        self.log(f"Tradovate import failed: {err}", "ERROR")
                        self.root.after(0, lambda: conn["connect_btn"].configure(text="Connect"))
                        return
                    account = TradovateAccount(user, pwd, trading_mode=mode)
                    account.login()
                elif platform == "TopStepX":
                    if not TOPSTEPX_AVAILABLE:
                        err = _TOPSTEPX_IMPORT_ERROR or 'unknown reason'
                        self.root.after(0, lambda: conn["status_var"].set("❌"))
                        self.log(f"TopStepX import failed: {err}", "ERROR")
                        self.root.after(0, lambda: conn["connect_btn"].configure(text="Connect"))
                        return
                    account = TopStepXAccount(user, pwd)
                    account.login()
                else:
                    self.root.after(0, lambda: conn["status_var"].set("❌"))
                    self.log(f"Unknown platform: {platform}", "ERROR")
                    self.root.after(0, lambda: conn["connect_btn"].configure(text="Connect"))
                    return

                conn["account"] = account
                # Also keep legacy references for backward compatibility
                if platform == "Tradovate":
                    self.tradovate_account = account
                else:
                    self.topstepx_account = account

                def _update_ui():
                    conn["status_var"].set("✅")
                    conn["connect_btn"].configure(text="Connected", fg_color="#14532D")
                    if hasattr(conn.get("status_lbl"), "configure"):
                        conn["status_lbl"].configure(text_color="#22C55E")
                    # Update global status
                    connected = sum(1 for c in self._broker_connections.values() if c.get("account"))
                    total = len(self._broker_connections)
                    self.broker_status_var.set(f"{connected}/{total} connected")
                self.root.after(0, _update_ui)
                self.log(f"✅ {firm_name} connected to {platform} ({mode})")

            except Exception as e:
                def _fail():
                    conn["status_var"].set("❌")
                    conn["connect_btn"].configure(text="Retry", fg_color="#450A0A")
                self.root.after(0, _fail)
                self.log(f"❌ {firm_name} connection failed: {e}", "ERROR")

        threading.Thread(target=_do_connect, daemon=True).start()

    def _connect_all_brokers(self):
        """Connect all prop firms that have credentials filled in."""
        if not self._broker_connections:
            self.log("⚠ Load trades first to see prop firm connections", "WARN")
            return

        to_connect = []
        for firm, conn in self._broker_connections.items():
            user = conn["user_entry"].get().strip()
            pwd = conn["pass_entry"].get().strip()
            if user and pwd and not conn.get("account"):
                to_connect.append(firm)

        if not to_connect:
            self.log("All populated firms are already connected")
            return

        self.log(f"Connecting {len(to_connect)} broker(s)...")

        def _do_connect_all():
            for firm in to_connect:
                self.root.after(0, lambda f=firm: self._connect_broker_firm(f))
                time.sleep(3)  # stagger connections

        threading.Thread(target=_do_connect_all, daemon=True).start()

    def _auto_connect_populated_brokers(self):
        """Auto-connect all broker rows that have dashboard credentials pre-filled."""
        to_connect = []
        for firm, conn in self._broker_connections.items():
            user = conn["user_entry"].get().strip()
            pwd = conn["pass_entry"].get().strip()
            if user and pwd and not conn.get("account"):
                to_connect.append(firm)

        if not to_connect:
            return

        self.log(f"🔗 Auto-connecting {len(to_connect)} broker(s) from dashboard credentials...")

        def _do_auto():
            for firm in to_connect:
                self.root.after(0, lambda f=firm: self._connect_broker_firm(f))
                time.sleep(3)  # stagger to avoid overwhelming

        threading.Thread(target=_do_auto, daemon=True).start()

    _BROWSER_MONITORED_FIRMS = {
        "Funded Next":       {"class_available": "CDP_SCRAPERS_AVAILABLE", "account_class": "FundedNextCDPAccount",
                              "login_url": "https://app.fundednext.com", "accounts_url": "https://app.fundednext.com/accounts",
                              "cdp": True},
        "FundedNext":        {"class_available": "CDP_SCRAPERS_AVAILABLE", "account_class": "FundedNextCDPAccount",
                              "login_url": "https://app.fundednext.com", "accounts_url": "https://app.fundednext.com/accounts",
                              "cdp": True},
        # CDP-based scrapers — attach to existing Chrome tab (no Selenium needed)
        "Tradeify":          {"class_available": "CDP_SCRAPERS_AVAILABLE", "account_class": "TradeifyAccount",
                              "login_url": "https://app-f.tradeify.co", "accounts_url": "https://app-f.tradeify.co",
                              "cdp": True},
        "Lucid Trading":     {"class_available": "CDP_SCRAPERS_AVAILABLE", "account_class": "LucidTradingAccount",
                              "login_url": "https://dash.lucidtrading.com", "accounts_url": "https://dash.lucidtrading.com",
                              "cdp": True},
        "TopStep":           {"class_available": "CDP_SCRAPERS_AVAILABLE", "account_class": "TopStepAccount",
                              "login_url": "https://dashboard.topstep.com", "accounts_url": "https://dashboard.topstep.com",
                              "cdp": True},
        "MFFU":              {"class_available": "CDP_SCRAPERS_AVAILABLE", "account_class": "MFFUAccount",
                              "login_url": "https://myfundedfutures.com", "accounts_url": "https://myfundedfutures.com",
                              "cdp": True},
        "My Funded Futures": {"class_available": "CDP_SCRAPERS_AVAILABLE", "account_class": "MFFUAccount",
                              "login_url": "https://myfundedfutures.com", "accounts_url": "https://myfundedfutures.com",
                              "cdp": True},
    }

    def _auto_launch_propfirm_browsers(self, active_firms):
        """
        Detect which active prop firms have browser-based dashboards and store
        them so the UI dashboard buttons know what to launch.  Does NOT auto-open
        browsers — the user clicks the "Dashboard" button in the broker row.
        Tradovate/TopStepX auto-connect with credentials as before.
        """
        for firm in active_firms:
            cfg = self._BROWSER_MONITORED_FIRMS.get(firm)
            if not cfg:
                continue
            class_avail = globals().get(cfg["class_available"], False)
            if class_avail:
                self.log(f"🌐 {firm} has a dashboard — click the Dashboard button to connect")

    def _launch_propfirm_dashboard(self, firm_name):
        """
        Launch a Chrome browser for the prop firm's dashboard, show login dialog.
        Called when user clicks the 'Dashboard' button in a broker row.
        For CDP-based scrapers, attaches to an existing Chrome tab instead of launching new Chrome.
        """
        cfg = self._BROWSER_MONITORED_FIRMS.get(firm_name)
        if not cfg:
            self.log(f"⚠ No dashboard config for {firm_name}", "WARN")
            return

        # Skip if already connected
        if firm_name in self._propfirm_browsers and self._propfirm_browsers[firm_name]:
            try:
                if self._propfirm_browsers[firm_name].is_connected():
                    self.log(f"🌐 {firm_name} dashboard already open")
                    return
            except Exception:
                pass

        class_avail = globals().get(cfg["class_available"], False)
        if not class_avail:
            self.log(f"⚠ {firm_name} browser module not available", "WARN")
            return

        # CDP-based scrapers: launch Chrome (or reuse) → open tab → show login dialog → attach
        if cfg.get("cdp"):
            self.log(f"🌐 Attaching to {firm_name} dashboard tab (CDP)...")
            def _do_cdp_launch():
                try:
                    account_cls = globals().get(cfg["account_class"])
                    if not account_cls:
                        self.root.after(0, lambda: self.log(f"❌ {firm_name}: scraper class not found", "ERROR"))
                        return

                    login_url = cfg.get("login_url", "")

                    # Ensure Chrome debug is running and the tab is open
                    try:
                        ensure_chrome_debug(url=login_url, port=9222)
                    except FileNotFoundError as e:
                        self.root.after(0, lambda err=str(e):
                            self.log(f"❌ {err}", "ERROR"))
                        return

                    acct = account_cls(debug_port=9222)

                    # Try to attach immediately (tab may already be logged in)
                    try:
                        acct.login(open_url=login_url)
                        self._propfirm_browsers[firm_name] = acct
                        self.root.after(0, lambda:
                            self.log(f"✅ {firm_name} dashboard connected via CDP"))
                        self._autofill_challenge_fees(firm_name, acct)
                        return
                    except ConnectionError:
                        # Tab not ready yet — show login dialog
                        pass

                    # Show dialog asking user to log in, then retry
                    self.root.after(0, lambda: self._show_cdp_login_dialog(
                        firm_name, acct, cfg))

                except Exception as e:
                    self.root.after(0, lambda err=str(e):
                        self.log(f"❌ {firm_name} CDP launch failed: {err}", "ERROR"))
            threading.Thread(target=_do_cdp_launch, daemon=True).start()
            return

    def _show_propfirm_login_dialog(self, firm_name, account, cfg):
        """Show a dialog prompting the user to log in to the prop firm dashboard."""
        if CTK_AVAILABLE:
            dialog = ctk.CTkToplevel(self.root)
        else:
            dialog = tk.Toplevel(self.root)
        dialog.title(f"{firm_name} Dashboard Login")
        dialog.geometry("380x140")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)

        status_var = tk.StringVar(value=f"Please log in to {firm_name} in the browser window,\nthen click the button below.")
        if CTK_AVAILABLE:
            status_lbl = ctk.CTkLabel(dialog, textvariable=status_var, font=("Consolas", 11),
                                       wraplength=340, justify="center")
            status_lbl.pack(pady=(16, 8), padx=16)
            confirm_btn = ctk.CTkButton(dialog, text="✅ I've logged in", width=160, height=30,
                                         fg_color="#14532D", hover_color="#166534",
                                         font=("Consolas", 11), text_color="#D1FAE5",
                                         command=lambda: self._on_login_confirmed(firm_name, account, cfg, dialog, status_var, confirm_btn))
            confirm_btn.pack(pady=(4, 16))
        else:
            status_lbl = tk.Label(dialog, textvariable=status_var, font=("Consolas", 10),
                                   wraplength=340, justify="center")
            status_lbl.pack(pady=(16, 8), padx=16)
            confirm_btn = tk.Button(dialog, text="✅ I've logged in", width=20,
                                     command=lambda: self._on_login_confirmed(firm_name, account, cfg, dialog, status_var, confirm_btn))
            confirm_btn.pack(pady=(4, 16))

    def _on_login_confirmed(self, firm_name, account, cfg, dialog, status_var, confirm_btn):
        """Called when user clicks 'I've logged in' — disable button and verify in background."""
        confirm_btn.configure(state="disabled")
        status_var.set("⏳ Verifying login...")
        threading.Thread(target=self._verify_propfirm_browser,
                         args=(firm_name, account, cfg, dialog, status_var),
                         daemon=True).start()

    def _show_cdp_login_dialog(self, firm_name, acct, cfg):
        """Show dialog for CDP-based scrapers asking user to log in, then attach."""
        if CTK_AVAILABLE:
            dialog = ctk.CTkToplevel(self.root)
        else:
            dialog = tk.Toplevel(self.root)
        dialog.title(f"{firm_name} Dashboard Login")
        dialog.geometry("400x150")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)

        status_var = tk.StringVar(
            value=f"Please log in to {firm_name} in the Chrome window,\nthen click the button below.")
        if CTK_AVAILABLE:
            ctk.CTkLabel(dialog, textvariable=status_var, font=("Consolas", 11),
                         wraplength=360, justify="center").pack(pady=(16, 8), padx=16)
            confirm_btn = ctk.CTkButton(
                dialog, text="✅ I've logged in", width=160, height=30,
                fg_color="#14532D", hover_color="#166634",
                font=("Consolas", 11), text_color="#D1FAE5",
                command=lambda: self._on_cdp_login_confirmed(
                    firm_name, acct, cfg, dialog, status_var, confirm_btn))
            confirm_btn.pack(pady=(4, 16))
        else:
            tk.Label(dialog, textvariable=status_var, font=("Consolas", 10),
                     wraplength=360, justify="center").pack(pady=(16, 8), padx=16)
            confirm_btn = tk.Button(
                dialog, text="✅ I've logged in", width=20,
                command=lambda: self._on_cdp_login_confirmed(
                    firm_name, acct, cfg, dialog, status_var, confirm_btn))
            confirm_btn.pack(pady=(4, 16))

    def _on_cdp_login_confirmed(self, firm_name, acct, cfg, dialog, status_var, confirm_btn):
        """Attach CDP after user confirms they've logged in."""
        confirm_btn.configure(state="disabled")
        status_var.set("⏳ Attaching to dashboard...")

        def _attach():
            try:
                login_url = cfg.get("login_url", "")
                acct.login(open_url=login_url)
                self._propfirm_browsers[firm_name] = acct
                self.root.after(0, lambda: self.log(
                    f"✅ {firm_name} dashboard connected via CDP"))
                self._autofill_challenge_fees(firm_name, acct)
                self.root.after(0, dialog.destroy)
            except ConnectionError:
                self.root.after(0, lambda: status_var.set(
                    f"❌ Could not find {firm_name} tab.\n"
                    f"Make sure {cfg.get('login_url', '')} is open and loaded."))
                self.root.after(0, lambda: confirm_btn.configure(state="normal"))
            except Exception as e:
                self.root.after(0, lambda err=str(e): status_var.set(f"❌ {err}"))
                self.root.after(0, lambda: confirm_btn.configure(state="normal"))

        threading.Thread(target=_attach, daemon=True).start()

    def _verify_propfirm_browser(self, firm_name, account, cfg, dialog=None, status_var=None):
        """Navigate to accounts page, verify login, auto-fill fees, close dialog."""
        def _update_status(msg):
            if status_var:
                self.root.after(0, lambda m=msg: status_var.set(m))

        def _close_dialog():
            if dialog:
                self.root.after(0, lambda: dialog.destroy())

        try:
            _update_status("⏳ Navigating to accounts page...")
            account.driver.get(cfg["accounts_url"])
            time.sleep(3)

            current_url = account.driver.current_url
            if "accounts" in current_url or account.is_connected():
                account.logged_in = True
                account._login_timestamp = time.time()
                self.root.after(0, lambda:
                    self.log(f"✅ {firm_name} browser connected — monitoring active"))

                # Auto-fill challenge fees from billing history
                _update_status("⏳ Fetching billing history...")
                acct_mapping = self._autofill_challenge_fees(firm_name, account)

                # Auto-detect breached accounts and mark as failed
                _update_status("⏳ Checking breach status...")
                self._auto_detect_breached_accounts(firm_name, account, acct_mapping=acct_mapping)

                _update_status("✅ Connected!")
                time.sleep(1)
                _close_dialog()
            else:
                self.root.after(0, lambda:
                    self.log(f"⚠ {firm_name} may not be logged in (URL: {current_url}). "
                             f"You can reconnect later.", "WARN"))
                _update_status("⚠ Login not detected — try again")
                # Re-enable the button so user can retry
                if dialog:
                    self.root.after(0, lambda: [
                        w.configure(state="normal")
                        for w in dialog.winfo_children()
                        if hasattr(w, 'configure') and isinstance(w, (ctk.CTkButton if CTK_AVAILABLE else tk.Button,))
                    ])
        except Exception as e:
            self.root.after(0, lambda err=str(e):
                self.log(f"❌ {firm_name} browser verification failed: {err}", "ERROR"))
            _update_status(f"❌ Error: {str(e)[:50]}")

    def _autofill_challenge_fees(self, firm_name, account):
        """
        Scrape billing history from the prop firm dashboard and auto-fill
        the 'Fee', 'Date Purchased', and 'Account #' fields of active evaluations.
        Then push the updated evaluations to the dashboard.
        
        For FundedNext Futures accounts, also resolves the billing login ID
        to the Tradovate account name (e.g. 945576089 -> FNFTCHHARRISONOUKA85625).
        
        Returns the acct_mapping dict (or {}) so callers can reuse it for breach detection.
        """
        acct_mapping = {}
        try:
            if not hasattr(account, 'get_billing_history'):
                self.root.after(0, lambda:
                    self.log(f"🌐 {firm_name}: No get_billing_history method — skipping"))
                return acct_mapping

            self.root.after(0, lambda:
                self.log(f"🌐 {firm_name}: Scraping billing history..."))

            # Prefer API-based billing if available (richer data with login field)
            if hasattr(account, 'get_billing_via_api'):
                billing = account.get_billing_via_api()
            else:
                billing = account.get_billing_history()
            if not billing:
                self.root.after(0, lambda:
                    self.log(f"🌐 {firm_name}: No billing records found"))
                return acct_mapping

            self.root.after(0, lambda b=len(billing):
                self.log(f"🌐 {firm_name}: Found {b} billing record(s)"))

            # Get account mapping (billing login -> Tradovate account name)
            if hasattr(account, 'get_account_mapping'):
                try:
                    self.root.after(0, lambda:
                        self.log(f"🌐 {firm_name}: Fetching account mapping..."))
                    acct_mapping = account.get_account_mapping()
                    if acct_mapping:
                        self.root.after(0, lambda n=len(acct_mapping):
                            self.log(f"🌐 {firm_name}: Got {n} login→account mapping(s)"))
                except Exception as e:
                    self.root.after(0, lambda err=str(e):
                        self.log(f"⚠ {firm_name}: Account mapping failed: {err}", "WARN"))

            # Log all billing entries for visibility
            for i, entry in enumerate(billing):
                acct = entry.get("account_no", "?")
                amt = entry.get("paid_amount", "?")
                status = entry.get("status", "?")
                date = entry.get("date", "?")
                pkg = entry.get("funding_package", "?")
                self.root.after(0, lambda idx=i, a=acct, m=amt, s=status, d=date, p=pkg:
                    self.log(f"   📋 Billing #{idx+1}: Acct={a} | Amount={m} | Status={s} | Date={d} | Pkg={p}"))

            # Build lookup: account_no -> {amount, date, package} (use first approved entry per account)
            billing_by_acct = {}
            # Also build a size-based lookup for fallback when Account # is empty
            # billing funding_package contains size e.g. "Futures Legacy Challenge 50000 USD"
            billing_by_size = {}
            # Build login->billing info lookup for account mapping
            billing_by_login = {}
            for entry in billing:
                acct_no = (entry.get("account_no") or "").strip()
                status = (entry.get("status") or "").strip().upper()
                amount = entry.get("paid_amount_numeric", 0.0)
                bill_date = (entry.get("date") or "").strip()
                pkg = (entry.get("funding_package") or "").strip()
                login_id = str(entry.get("login") or acct_no).strip()
                if acct_no and amount > 0 and status == "APPROVED":
                    info = {"amount": amount, "date": bill_date, "package": pkg, "account_no": acct_no, "login": login_id}
                    if acct_no not in billing_by_acct:
                        billing_by_acct[acct_no] = info
                    # Extract numeric size from package string (e.g. "50000" from "Futures Legacy Challenge 50000 USD")
                    import re as _re
                    size_match = _re.search(r'(\d{4,})', pkg.replace(",", ""))
                    if size_match:
                        size_key = int(size_match.group(1))
                        if size_key not in billing_by_size:
                            billing_by_size[size_key] = info
                    # Index by login ID for account mapping resolution
                    if login_id and login_id not in billing_by_login:
                        billing_by_login[login_id] = info

            # Resolve billing login IDs to Tradovate account names via account mapping
            # This enriches billing_by_acct so matching by FNFT account name works
            for login_id, bill_info in billing_by_login.items():
                if login_id in acct_mapping:
                    tv_name = acct_mapping[login_id].get("tradovate_account_name")
                    if tv_name and tv_name not in billing_by_acct:
                        enriched = dict(bill_info)
                        enriched["tradovate_account_name"] = tv_name
                        billing_by_acct[tv_name] = enriched
                        self.root.after(0, lambda lid=login_id, tv=tv_name:
                            self.log(f"   🔗 Mapped billing login {lid} → {tv}"))

            if not billing_by_acct and not billing_by_size:
                self.root.after(0, lambda:
                    self.log(f"🌐 {firm_name}: No APPROVED billing entries with amount > 0"))
                return acct_mapping

            self.root.after(0, lambda n=len(billing_by_acct), s=len(billing_by_size),
                                   ak=list(billing_by_acct.keys()), sk=list(billing_by_size.keys()):
                self.log(f"🌐 {firm_name}: {n} by-acct ({ak}), {s} by-size ({sk})"))

            # Log active trade rows for debugging
            row_count = len(self._active_trade_rows)
            self.root.after(0, lambda c=row_count:
                self.log(f"🌐 {firm_name}: Checking {c} active trade row(s) for missing Fee/Date"))

            # Canonical firm name for comparison
            canonical_firm = self._FIRM_MAP.get(firm_name, firm_name)

            # Match billing to active evaluations missing Fee or Date Purchased
            updated_evals = []
            filled_count = 0
            for row_data in self._active_trade_rows:
                ev = row_data.get("eval")
                if not ev:
                    continue

                # Check if eval belongs to this prop firm (flexible matching)
                ev_firm = ev.get("Prop Firm", "")
                ev_canonical = self._FIRM_MAP.get(ev_firm, ev_firm)
                if ev_canonical != canonical_firm and ev_firm != firm_name:
                    continue

                acct_challenge = (ev.get("Account #") or "").strip()
                acct_funded = (ev.get("Account #.1") or "").strip()
                existing_fee = (ev.get("Fee") or "").strip()
                existing_date = (ev.get("Date Purchased") or "").strip()

                fee_filled = False
                if existing_fee:
                    try:
                        existing_val = float(existing_fee.replace("$", "").replace(",", ""))
                        fee_filled = existing_val > 0
                    except ValueError:
                        fee_filled = existing_fee not in ("", "$0", "$0.00", "0")
                date_filled = bool(existing_date)

                # Log each eval's current state
                self.root.after(0, lambda f=ev_firm, ac=acct_challenge, af=acct_funded,
                                       ef=existing_fee, ed=existing_date, ff=fee_filled, df=date_filled:
                    self.log(f"   🔍 Eval: Firm={f} | Acct#={ac} | Acct#.1={af} | "
                             f"Fee='{ef}' ({'✓' if ff else '✗'}) | Date='{ed}' ({'✓' if df else '✗'})"))

                # Note: we no longer skip early — fee is always updated if it differs from billing

                # Try matching by Account # or Account #.1
                matched = None
                matched_via = ""
                for acct_key, label in [(acct_challenge, "Account #"), (acct_funded, "Account #.1")]:
                    if not acct_key:
                        continue
                    # Direct match
                    if acct_key in billing_by_acct:
                        matched = billing_by_acct[acct_key]
                        matched_via = f"{label} direct: {acct_key}"
                        break
                    # Partial match: billing account_no may be a substring
                    for bill_acct, bill_info in billing_by_acct.items():
                        if bill_acct in acct_key or acct_key in bill_acct:
                            matched = bill_info
                            matched_via = f"{label} partial: eval={acct_key} ~ bill={bill_acct}"
                            break
                    if matched:
                        break

                # Fallback: match by Account Size when Account # is empty
                if not matched and billing_by_size:
                    ev_size_str = (ev.get("Account Size") or "").strip()
                    import re as _re
                    size_match = _re.search(r'(\d[\d,]*)', ev_size_str.replace(",", ""))
                    if size_match:
                        ev_size = int(size_match.group(1))
                        if ev_size in billing_by_size:
                            matched = billing_by_size[ev_size]
                            matched_via = f"Account Size fallback: ${ev_size:,} → bill acct {matched.get('account_no', '?')}"

                if matched:
                    billing_fee = f"${matched['amount']:.2f}"
                    changes = []
                    # Always overwrite fee with billing value
                    ev["Fee"] = billing_fee
                    changes.append(f"Fee={billing_fee}")
                    if not date_filled and matched["date"]:
                        ev["Date Purchased"] = matched["date"]
                        changes.append(f"Date={matched['date']}")
                    # Auto-fill Account # from account mapping when empty
                    tv_name = matched.get("tradovate_account_name")
                    if not acct_challenge and tv_name:
                        ev["Account #"] = tv_name
                        changes.append(f"Account#={tv_name}")
                    elif not acct_challenge and matched.get("login") and str(matched["login"]) in acct_mapping:
                        tv_name = acct_mapping[str(matched["login"])].get("tradovate_account_name")
                        if tv_name:
                            ev["Account #"] = tv_name
                            changes.append(f"Account#={tv_name}")
                    filled_count += 1
                    updated_evals.append(ev)
                    self.root.after(0, lambda v=matched_via, c=", ".join(changes):
                        self.log(f"   💰 Matched ({v}): {c}"))
                else:
                    acct_display = acct_challenge or acct_funded or "no-acct"
                    bill_keys = list(billing_by_acct.keys())
                    self.root.after(0, lambda a=acct_display, bk=bill_keys:
                        self.log(f"   ⚠ No billing match for {a} (billing accts: {bk})"))

            if not filled_count:
                self.root.after(0, lambda:
                    self.log(f"🌐 {firm_name}: No accounts needed Fee/Date updates"))
                return acct_mapping

            self.root.after(0, lambda c=filled_count:
                self.log(f"🌐 {firm_name}: Pushing {c} updated eval(s) to dashboard..."))

            # Push updated evaluations to dashboard
            email = self.client_email_entry.get().strip()
            dashboard_url = self.url_entry.get().strip().rstrip('/')
            if not email or not dashboard_url:
                self.root.after(0, lambda:
                    self.log(f"⚠ Cannot push fee updates — no email/dashboard URL", "WARN"))
                return acct_mapping

            # Collect ALL active evals (server expects the full set)
            all_evals = [rd.get("eval") for rd in self._active_trade_rows if rd.get("eval")]

            # Debug: log the Fee value we're about to push
            for ev_debug in all_evals:
                ev_fee = ev_debug.get("Fee", "N/A")
                ev_acct = ev_debug.get("Account #", "?")
                self.root.after(0, lambda f=ev_fee, a=ev_acct:
                    self.log(f"   📤 Pushing eval Acct={a} Fee={f}"))

            self.root.after(0, lambda n=len(all_evals):
                self.log(f"🌐 {firm_name}: Sending {n} total eval(s) in push payload"))

            payload = {
                "email": email,
                "evaluations": all_evals,
                "statistics": {},
                "dropdown_options": {}
            }

            try:
                response = requests.post(
                    f"{dashboard_url}/api/client/push",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=30
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        self.root.after(0, lambda c=filled_count:
                            self.log(f"✅ Auto-filled Fee & Date Purchased for {c} account(s) → synced to dashboard"))
                    else:
                        self.root.after(0, lambda m=data.get('message', 'Unknown'):
                            self.log(f"⚠ Fee sync response: {m}", "WARN"))
                else:
                    self.root.after(0, lambda s=response.status_code:
                        self.log(f"⚠ Fee sync failed: HTTP {s}", "WARN"))
            except Exception as e:
                self.root.after(0, lambda err=str(e):
                    self.log(f"⚠ Fee sync error: {err}", "WARN"))

            return acct_mapping

        except Exception as e:
            self.root.after(0, lambda err=str(e):
                self.log(f"⚠ {firm_name} billing auto-fill failed: {err}", "WARN"))
            return acct_mapping

    def _auto_detect_breached_accounts(self, firm_name, account, acct_mapping=None):
        """
        Check if any evaluations have been breached on FundedNext
        and auto-set their status to 'Failed' with the breach reason.

        Uses the account mapping (from get_account_mapping) which includes
        breach status from the React fiber, plus optionally the account-overview
        API for detailed breach info (breach reason, reset price etc).

        Fetches ALL evaluations from the dashboard (not just _active_trade_rows)
        since breached accounts may already be filtered out of the active rows.
        """
        try:
            if not acct_mapping:
                if hasattr(account, 'get_account_mapping'):
                    acct_mapping = account.get_account_mapping()
                if not acct_mapping:
                    return

            # Build reverse lookup: tradovate_account_name -> mapping info
            tv_to_info = {}
            for login_id, info in acct_mapping.items():
                tv_name = info.get("tradovate_account_name")
                if tv_name:
                    tv_to_info[tv_name] = info
                    tv_to_info[login_id] = info  # also index by login

            self.root.after(0, lambda keys=list(tv_to_info.keys()):
                self.log(f"🔍 Breach check: mapping keys = {keys}"))

            # Canonical firm name for comparison
            canonical_firm = self._FIRM_MAP.get(firm_name, firm_name)

            # Fetch ALL evaluations from dashboard (not just _active_trade_rows,
            # since breached accounts may have been filtered out as inactive)
            email = self.client_email_entry.get().strip()
            dashboard_url = self.url_entry.get().strip().rstrip('/')
            all_evals = []
            if email and dashboard_url:
                try:
                    r = requests.get(
                        f"{dashboard_url}/api/client/data",
                        params={"email": email},
                        timeout=15
                    )
                    if r.status_code == 200:
                        all_evals = r.json().get("evaluations", [])
                except Exception as e:
                    self.root.after(0, lambda err=str(e):
                        self.log(f"⚠ Breach check: couldn't fetch evals: {err}", "WARN"))

            if not all_evals:
                # Fallback to active trade rows
                all_evals = [rd.get("eval") for rd in self._active_trade_rows if rd.get("eval")]

            breached_count = 0
            updated_evals = []

            self.root.after(0, lambda n=len(all_evals), fn=firm_name, cf=canonical_firm:
                self.log(f"🔍 Breach check: {n} eval(s), firm_name='{fn}', canonical='{cf}'"))

            for ev in all_evals:
                if not ev:
                    continue

                # Skip deleted
                if ev.get("_deleted"):
                    continue

                # Check if eval belongs to this prop firm (with alias support)
                ev_firm = ev.get("Prop Firm", "")
                ev_canonical = self._FIRM_MAP.get(ev_firm, ev_firm)
                firm_match = (ev_canonical == canonical_firm or ev_firm == firm_name)
                if not firm_match:
                    # Check aliases: firm name variants that refer to the same firm
                    _FIRM_ALIASES = {
                        "funded next": ["fundednext"],
                        "fundednext": ["funded next"],
                        "my funded futures": ["mffu"],
                        "mffu": ["my funded futures"],
                    }
                    ev_aliases = _FIRM_ALIASES.get(ev_firm.lower(), [])
                    firm_match = firm_name.lower() in ev_aliases or canonical_firm.lower() in ev_aliases
                if not firm_match:
                    continue

                acct_challenge = (ev.get("Account #") or "").strip()
                acct_funded = (ev.get("Account #.1") or "").strip()
                current_status_p1 = (ev.get("Status P1") or "").strip().lower()
                current_status = (ev.get("Status") or "").strip().lower()

                self.root.after(0, lambda ac=acct_challenge, af=acct_funded, sp=current_status_p1, s=current_status:
                    self.log(f"🔍 Breach eval: Acct#='{ac}' Acct#.1='{af}' P1='{sp}' Status='{s}'"))

                # Skip if already marked as failed/breached
                if any(kw in current_status_p1 for kw in self._INACTIVE_KEYWORDS):
                    if not acct_funded or any(kw in current_status for kw in self._INACTIVE_KEYWORDS):
                        self.root.after(0, lambda: self.log(f"🔍 Breach check: already inactive, skipping"))
                        continue

                # Find matching account in mapping
                matched_info = None
                for acct_key in [acct_challenge, acct_funded]:
                    if not acct_key:
                        continue
                    if acct_key in tv_to_info:
                        matched_info = tv_to_info[acct_key]
                        break
                    # Partial match
                    for tv_name, info in tv_to_info.items():
                        if tv_name in acct_key or acct_key in tv_name:
                            matched_info = info
                            break
                    if matched_info:
                        break

                if not matched_info:
                    # Fallback: match by Account Size to any mapping entry
                    ev_size_str = (ev.get("Account Size") or "").strip()
                    import re as _re
                    size_match = _re.search(r'(\d[\d,]*)', ev_size_str.replace(",", ""))
                    if size_match:
                        ev_size = int(size_match.group(1))
                        for _lid, info in acct_mapping.items():
                            sb = info.get("starting_balance")
                            if sb and int(sb) == ev_size:
                                matched_info = info
                                self.root.after(0, lambda sz=ev_size:
                                    self.log(f"🔍 Breach: matched by Account Size ${sz:,}"))
                                break

                if not matched_info:
                    self.root.after(0, lambda ac=acct_challenge, af=acct_funded:
                        self.log(f"🔍 Breach check: no mapping match for Acct#='{ac}' Acct#.1='{af}'"))
                    continue

                # Check if account is breached
                breached = matched_info.get("breached")
                if not breached or breached == 0:
                    self.root.after(0, lambda b=breached:
                        self.log(f"🔍 Breach check: account not breached (breached={b})"))
                    continue

                # Account is breached — get detailed info from API if available
                breach_reason = matched_info.get("breachedby") or "Breached"
                account_id = matched_info.get("account_id")
                if account_id and hasattr(account, 'get_account_overview'):
                    try:
                        overview = account.get_account_overview(account_id)
                        if overview:
                            details = overview.get("account_details", {})
                            breach_reason = details.get("breached_by") or breach_reason
                    except Exception:
                        pass

                # Determine which status field to set
                acct_display = acct_challenge or acct_funded
                changes = []

                # If challenge phase is still active and breached
                if acct_funded:
                    # Has funded account — set funded status
                    if not any(kw in current_status for kw in self._INACTIVE_KEYWORDS):
                        ev["Status"] = f"Failed - {breach_reason}"
                        changes.append(f"Status='Failed - {breach_reason}'")
                else:
                    # Challenge only — set P1 status
                    if not any(kw in current_status_p1 for kw in self._INACTIVE_KEYWORDS):
                        ev["Status P1"] = f"Failed - {breach_reason}"
                        changes.append(f"Status P1='Failed - {breach_reason}'")

                if changes:
                    breached_count += 1
                    updated_evals.append(ev)
                    self.root.after(0, lambda a=acct_display, c=", ".join(changes):
                        self.log(f"   🚫 BREACHED: {a} → {c}"))

            if not breached_count:
                self.root.after(0, lambda:
                    self.log(f"🌐 {firm_name}: No breached accounts detected"))
                return

            self.root.after(0, lambda c=breached_count:
                self.log(f"🌐 {firm_name}: {c} breached account(s) — pushing status updates..."))

            # Push to dashboard
            email = self.client_email_entry.get().strip()
            dashboard_url = self.url_entry.get().strip().rstrip('/')
            if not email or not dashboard_url:
                return

            payload = {
                "email": email,
                "evaluations": all_evals,
                "statistics": {},
                "dropdown_options": {}
            }

            try:
                response = requests.post(
                    f"{dashboard_url}/api/client/push",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=30
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        self.root.after(0, lambda c=breached_count:
                            self.log(f"✅ Auto-failed {c} breached account(s) → synced to dashboard"))
                    else:
                        self.root.after(0, lambda m=data.get('message', 'Unknown'):
                            self.log(f"⚠ Breach sync response: {m}", "WARN"))
                else:
                    self.root.after(0, lambda s=response.status_code:
                        self.log(f"⚠ Breach sync failed: HTTP {s}", "WARN"))
            except Exception as e:
                self.root.after(0, lambda err=str(e):
                    self.log(f"⚠ Breach sync error: {err}", "WARN"))

        except Exception as e:
            self.root.after(0, lambda err=str(e):
                self.log(f"⚠ {firm_name} breach detection failed: {err}", "WARN"))

    def _get_broker_for_firm(self, firm_name):
        """Get the connected broker account for a specific prop firm."""
        conn = self._broker_connections.get(firm_name)
        if conn and conn.get("account"):
            return conn["account"]
        # If the firm has a row in broker connections but isn't connected, do NOT
        # fall back — it means the user chose not to connect this firm.
        if conn is not None:
            return None
        # Legacy fallback: only for setups without multi-firm broker panel
        platform = self.broker_var.get()
        if platform == "Tradovate" and self.tradovate_account:
            return self.tradovate_account
        if platform == "TopStepX" and self.topstepx_account:
            return self.topstepx_account
        return None

    def _get_trade_config(self):
        """Get current trade configuration from blueprint."""
        if not self.prop_firm_mgr:
            return None
        firm = self.prop_firm_var.get()
        phase = self.phase_var.get()
        size = self.acct_size_var.get()
        config = self.prop_firm_mgr.get_strategy_config(firm, phase, size)
        return config

    def _get_mt5_trading_api(self):
        """Get or create the MT5 trading API from companion's existing MT5 connection."""
        if self.trading_api and hasattr(self.trading_api, 'is_connected') and self.trading_api.is_connected():
            return self.trading_api
        # Try to create from companion's MT5 credentials
        login = self.mt5_login.get().strip()
        pwd = self.mt5_password.get().strip()
        server = self.mt5_server.get().strip()
        if login and pwd and server:
            try:
                self.trading_api = MT5API(login, pwd, server)
                if self.trading_api.connect():
                    return self.trading_api
            except Exception as e:
                self.log(f"MT5 trading API connection failed: {e}", "ERROR")
        return None

    def _ensure_mt5_for_signals(self):
        """Ensure MT5 is initialized so indicators can fetch price data.
        
        Works for both hedging and non-hedging clients:
        - If pusher already connected MT5, it's already initialized → returns True
        - Otherwise, tries to initialize from saved credentials
        
        Returns:
            bool: True if MT5 is ready for price data queries.
        """
        if not MT5_AVAILABLE:
            return False
        # Already connected via pusher?
        if self.pusher.connected:
            return True
        # Already connected via trading API?
        if mt5.terminal_info():
            return True
        # Try to connect using saved credentials
        login = self.mt5_login.get().strip()
        pwd = self.mt5_password.get().strip()
        server = self.mt5_server.get().strip()
        if login and pwd and server:
            success, msg = self.pusher.connect_mt5(login, pwd, server)
            if success:
                self.log("🔗 MT5 connected for signal data")
                return True
            self.log(f"⚠ MT5 auto-connect failed: {msg}", "WARN")
        return False

    # ============ Daily Bias Persistence ============

    def _get_daily_bias(self, firms):
        """Get or create today's direction bias per prop firm.
        Persisted to trader_bias.json so it survives app restarts.
        Resets automatically on a new calendar day (EAT)."""
        from datetime import datetime, timedelta, timezone
        EAT = timezone(timedelta(hours=3))
        today_str = datetime.now(EAT).strftime("%Y-%m-%d")

        bias_path = os.path.join(os.path.dirname(__file__), "trader_bias.json")
        saved = {}
        if os.path.exists(bias_path):
            try:
                with open(bias_path, 'r') as f:
                    saved = json.load(f)
            except Exception:
                saved = {}

        # Reset if date changed
        if saved.get("date") != today_str:
            saved = {"date": today_str, "firms": {}}

        firm_bias = saved.get("firms", {})
        changed = False
        for firm in firms:
            if firm not in firm_bias:
                firm_bias[firm] = random.choice(["buy", "sell"])
                changed = True

        if changed or saved.get("date") != today_str:
            saved["date"] = today_str
            saved["firms"] = firm_bias
            try:
                with open(bias_path, 'w') as f:
                    json.dump(saved, f, indent=2)
            except Exception:
                pass

        return {f: firm_bias[f] for f in firms}

    # ============ Indicator-Based Signal ============

    # Signal functions mapped by name → (callable, buy_values, sell_values)
    # buy_values/sell_values are the return strings that map to buy/sell
    _SIGNAL_INDICATORS = None  # populated lazily

    @classmethod
    def _get_indicator_map(cls):
        """Build indicator map lazily (needs imports to be resolved)."""
        if cls._SIGNAL_INDICATORS is not None:
            return cls._SIGNAL_INDICATORS
        indicators = {}
        try:
            indicators["RSI"] = (get_rsi_signal, {"buy"}, {"sell"})
        except Exception:
            pass
        try:
            indicators["MACD"] = (get_macd_signal, {"buy"}, {"sell"})
        except Exception:
            pass
        try:
            indicators["Stochastic"] = (get_stochastic_signal, {"buy"}, {"sell"})
        except Exception:
            pass
        try:
            indicators["CCI"] = (get_cci_signal, {"buy"}, {"sell"})
        except Exception:
            pass
        try:
            indicators["Supertrend"] = (get_supertrend_signal, {"bullish"}, {"bearish"})
        except Exception:
            pass
        try:
            indicators["Momentum"] = (get_momentum_signal, {"bullish"}, {"bearish"})
        except Exception:
            pass
        try:
            indicators["BollingerBands"] = (get_bb_signal, {"lower"}, {"upper"})
        except Exception:
            pass
        cls._SIGNAL_INDICATORS = indicators
        return indicators

    def _get_signal_direction(self, mt5_symbol, timeframe=None, num_indicators=3):
        """Generate a trade direction by polling a random subset of indicators.
        
        Picks `num_indicators` random indicators, queries each on the given
        MT5 symbol, and uses majority vote to decide buy vs sell.
        Falls back to random if no indicators produce a signal.
        """
        import MetaTrader5 as mt5_mod
        if timeframe is None:
            timeframe = mt5_mod.TIMEFRAME_M5

        # Ensure MT5 is connected (non-hedging clients may not have it open)
        if not mt5_mod.terminal_info():
            self._ensure_mt5_for_signals()
            if not mt5_mod.terminal_info():
                self.root.after(0, lambda: self.log("⚠ MT5 not connected — using random direction", "WARN"))
                return random.choice(["buy", "sell"])

        indicators = self._get_indicator_map()
        if not indicators:
            self.root.after(0, lambda: self.log("⚠ No signal indicators available — using random", "WARN"))
            return random.choice(["buy", "sell"])

        # Pick a random subset
        available = list(indicators.keys())
        pick_count = min(num_indicators, len(available))
        chosen = random.sample(available, pick_count)

        buy_votes = 0
        sell_votes = 0
        details = []

        for name in chosen:
            func, buy_vals, sell_vals = indicators[name]
            try:
                result = func(mt5_symbol, timeframe)
                if result is None:
                    details.append(f"{name}=neutral")
                    continue
                sig = result.lower() if isinstance(result, str) else str(result).lower()
                if sig in buy_vals:
                    buy_votes += 1
                    details.append(f"{name}=BUY")
                elif sig in sell_vals:
                    sell_votes += 1
                    details.append(f"{name}=SELL")
                else:
                    details.append(f"{name}={sig}")
            except Exception as e:
                details.append(f"{name}=err")

        detail_str = ", ".join(details)
        if buy_votes > sell_votes:
            direction = "buy"
        elif sell_votes > buy_votes:
            direction = "sell"
        else:
            direction = random.choice(["buy", "sell"])
            detail_str += " (tie→random)"

        self.root.after(0, lambda d=detail_str, dir=direction:
            self.log(f"   📊 Signal vote: {d} → {dir.upper()}"))
        return direction

    # ============ Version History & Rollback ============

    def save_config(self):
        """Save configuration to file."""
        config = {
            "dashboard_url": self.url_entry.get(),  # Save dynamic URL
            "client_email": self.client_email_entry.get(),
            "sheet_url": self.sheet_url_entry.get(),
            "mt5_login": self.mt5_login.get(),
            "mt5_server": self.mt5_server.get()
        }
        # Trading engine settings
        if hasattr(self, 'broker_var'):
            config["broker_platform"] = self.broker_var.get()
            config["trading_mode"] = self.trading_mode_var.get()
            config["prop_firm"] = self.prop_firm_var.get()
            config["phase"] = self.phase_var.get()
            config["account_size"] = self.acct_size_var.get()
            config["hedge_mode"] = self.hedge_mode_var.get()
            config["direction"] = self.direction_var.get()
            config["strategy"] = self.strategy_var.get()
        
        config_path = os.path.join(os.path.dirname(__file__), "trader_config.json")
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        self.log("Configuration saved")
        messagebox.showinfo("Saved", "Configuration saved successfully")
        
    def load_config(self):
        """Load configuration from file."""
        config_path = os.path.join(os.path.dirname(__file__), "trader_config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                
                # Do NOT load dashboard_url - keep hardcoded TradeOpps
                # saved_url = config.get('dashboard_url')
                # if saved_url:
                #     self.url_entry.delete(0, tk.END)
                #     self.url_entry.insert(0, saved_url)
                
                if config.get('client_email'):
                    self.client_email_entry.delete(0, tk.END)
                    self.client_email_entry.insert(0, config.get('client_email', ''))
                
                if config.get('sheet_url'):
                    self.sheet_url_entry.delete(0, tk.END)
                    self.sheet_url_entry.insert(0, config.get('sheet_url', ''))
                
                if config.get('mt5_login'):
                    self.mt5_login.delete(0, tk.END)
                    self.mt5_login.insert(0, config.get('mt5_login', ''))
                
                if config.get('mt5_server'):
                    self.mt5_server.delete(0, tk.END)
                    self.mt5_server.insert(0, config.get('mt5_server', ''))
                
                # Trading engine settings
                if hasattr(self, 'broker_var'):
                    if config.get('broker_platform'):
                        self.broker_var.set(config['broker_platform'])
                    if config.get('trading_mode'):
                        self.trading_mode_var.set(config['trading_mode'])
                    if config.get('prop_firm'):
                        self.prop_firm_var.set(config['prop_firm'])
                        self._on_prop_firm_change()
                    if config.get('phase'):
                        self.phase_var.set(config['phase'])
                    if config.get('account_size'):
                        self.acct_size_var.set(config['account_size'])
                    if config.get('hedge_mode'):
                        self.hedge_mode_var.set(config['hedge_mode'])
                    if config.get('direction'):
                        self.direction_var.set(config['direction'])
                    if config.get('strategy'):
                        self.strategy_var.set(config['strategy'])
                
                self.log("Configuration loaded")
            except Exception as e:
                self.log(f"Failed to load config: {e}", "ERROR")
                
    def run(self):
        """Run the application."""
        self.root.mainloop()


def main():
    """Main entry point."""
    if GUI_AVAILABLE:
        app = TraderCompanionApp()
        app.run()
    else:
        print("=" * 50)
        print("Tradeopss AI - Console Mode")
        print("=" * 50)
        print("\nGUI not available. Install tkinter to use the graphical interface.")
        print("\nUsage:")
        print("  1. Set your API key in the dashboard")
        print("  2. Use the MT5DataPusher class programmatically")
        print("\nExample:")
        print("  pusher = MT5DataPusher('http://localhost:5001', 'your-api-key')")
        print("  pusher.connect_mt5(login, password, server)")
        print("  pusher.push_to_dashboard('ClientName', 'AdminName', 'TraderName')")


if __name__ == "__main__":
    main()
