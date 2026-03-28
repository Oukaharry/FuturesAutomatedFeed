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
APP_VERSION = "2.0.1"
"""
MT5 Trader Companion App
A desktop application for traders to push their MT5 data to the Trading Dashboard.
"""
import sys
import os
import json
import requests
import time
from datetime import datetime
import threading
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
except ImportError:
    try:
        from tradovate import TradovateAccount
        TRADOVATE_AVAILABLE = True
    except ImportError:
        TRADOVATE_AVAILABLE = False
        TradovateAccount = None

try:
    from trader_companion.topstepx import TopStepXAccount
    TOPSTEPX_AVAILABLE = True
except ImportError:
    try:
        from topstepx import TopStepXAccount
        TOPSTEPX_AVAILABLE = True
    except ImportError:
        TOPSTEPX_AVAILABLE = False
        TopStepXAccount = None

try:
    from trader_companion.trade_limit_manager import TradeLimitManager
except ImportError:
    try:
        from trade_limit_manager import TradeLimitManager
    except ImportError:
        TradeLimitManager = None

try:
    from trader_companion.signals.rsi import get_rsi_signal
    SIGNALS_AVAILABLE = True
except ImportError:
    try:
        from signals.rsi import get_rsi_signal
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
        
        # FNFT Specific Logic: Only push current day's trades (Midnight to Now)
        # This prevents fetching history from previous failed challenges on the same account number (Resets).
        is_fnft = False
        try:
            srv = str(self.server).upper() if self.server else ""
            cmp = str(getattr(self, 'company', '')).upper()
            if 'FUNDEDNEXT' in srv or 'FNFT' in srv or 'FUNDEDNEXT' in cmp or 'FNFT' in cmp:
                is_fnft = True
        except Exception:
            pass

        if is_fnft and days < 60:
            # Override small day values for FNFT to capture session-based history
            # We no longer hard-limit to "today" because the server side will handle resets.
            days = 60
            from_timestamp = time.time() - (days * 24 * 3600)

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
        deals = self.get_deals(days=30)
        
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
            
            # Update the evaluation
            evaluations[eval_idx][field_name] = f"${total_profit:.2f}"
            match_log.append(f"✓ {account_suffix}_{stage}{stage_num} -> [{field_name}] = ${total_profit:.2f} ({len(group_deals)} deals)")
        
        return evaluations, match_log


class TraderCompanionApp:
    """GUI Application for the Trader Companion."""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"Trader Companion v{APP_VERSION}")
        self.root.geometry("770x850")
        self.root.minsize(720, 650)
        self.root.configure(bg='#0a0e1a')
        self.root.resizable(True, True)
        
        # Set Window Icon
        try:
            if hasattr(sys, '_MEIPASS'):
                icon_path = os.path.join(sys._MEIPASS, 'logo.png')
            else:
                icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logo.png')
            
            if os.path.exists(icon_path):
                icon = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, icon)
        except Exception as e:
            print(f"Error loading icon: {e}")
        
        # Create canvas for scrolling
        self.main_canvas = tk.Canvas(self.root, bg='#0a0e1a', highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.main_canvas.yview)
        self.scrollable_frame = ttk.Frame(self.main_canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))
        )
        
        self.main_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw",
                                        tags="inner_frame")
        self.main_canvas.configure(yscrollcommand=scrollbar.set)
        
        self.main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Keep inner frame width = canvas width so content stretches fully
        def _resize_inner(event):
            self.main_canvas.itemconfig("inner_frame", width=event.width)
        self.main_canvas.bind("<Configure>", _resize_inner)
        
        # Enable mousewheel scrolling
        def _on_mousewheel(event):
            self.main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.main_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        self.pusher = MT5DataPusher()
        self.auto_push_enabled = False
        self.auto_push_thread = None
        self.client_info = None  # Stores looked-up hierarchy info

        # Auto-trade scheduler state
        self.auto_trade_enabled = False
        self.auto_trade_thread = None
        self._auto_trade_stop = threading.Event()
        self._auto_trade_scheduled_dt = None  # the randomized datetime
        
        self.setup_ui()
        self.load_config()
        
    def setup_ui(self):
        """Setup the user interface with tabbed modern layout."""
        style = ttk.Style()
        style.theme_use('clam')

        # ── Modern Dark Palette ──
        BG       = '#0a0e1a'   # deep navy
        CARD     = '#111827'   # card surface
        BORDER   = '#1e293b'   # subtle border
        FG       = '#e2e8f0'   # primary text
        FG_DIM   = '#94a3b8'   # muted text
        ACCENT   = '#f59e0b'   # amber gold
        ACCENT2  = '#3b82f6'   # blue
        GREEN    = '#22c55e'
        RED      = '#ef4444'

        # ── Global Styles ──
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=FG, font=('Segoe UI', 10))
        style.configure('TLabelframe', background=CARD, foreground=ACCENT, borderwidth=2, relief='groove')
        style.configure('TLabelframe.Label', background=CARD, foreground=ACCENT, font=('Segoe UI', 11, 'bold'))
        style.configure('TButton', font=('Segoe UI', 10, 'bold'), padding=6)
        style.configure('Header.TLabel', font=('Segoe UI', 18, 'bold'), foreground=ACCENT)
        style.configure('Status.TLabel', font=('Segoe UI', 10), foreground=GREEN)
        style.configure('Error.TLabel', font=('Segoe UI', 10), foreground=RED)
        style.configure('Dim.TLabel', background=BG, foreground=FG_DIM, font=('Segoe UI', 9, 'italic'))
        style.configure('CardBG.TFrame', background=CARD)
        style.configure('CardBG.TLabel', background=CARD, foreground=FG, font=('Segoe UI', 10))
        style.configure('CardDim.TLabel', background=CARD, foreground=FG_DIM, font=('Segoe UI', 9, 'italic'))
        style.configure('SectionHead.TLabel', background=CARD, foreground=ACCENT, font=('Segoe UI', 11, 'bold'))

        # Notebook tab styling
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=BORDER, foreground=FG_DIM,
                        font=('Segoe UI', 10, 'bold'), padding=[18, 8])
        style.map('TNotebook.Tab',
                  background=[('selected', CARD), ('!selected', BORDER)],
                  foreground=[('selected', ACCENT), ('!selected', FG_DIM)])

        # Entry styling
        style.configure('TEntry', fieldbackground='#1e293b', foreground=FG, insertcolor=FG)
        style.configure('TCombobox', fieldbackground='#1e293b', foreground=FG)
        style.map('TCombobox', fieldbackground=[('readonly', '#1e293b')],
                  foreground=[('readonly', FG)])

        # Buy / Sell button styles
        style.configure("Buy.TButton", foreground="white", background=GREEN, font=('Segoe UI', 12, 'bold'), padding=10)
        style.configure("Sell.TButton", foreground="white", background=RED, font=('Segoe UI', 12, 'bold'), padding=10)
        style.map("Buy.TButton", background=[("active", "#16a34a")])
        style.map("Sell.TButton", background=[("active", "#dc2626")])

        style.configure("AutoPush.TButton", foreground="black", background=ACCENT2)
        style.map("AutoPush.TButton", background=[("active", "#2563eb")])

        # ── Main container ──
        main_frame = ttk.Frame(self.scrollable_frame, padding=12)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ── Header ──
        header_canvas = tk.Canvas(main_frame, height=70, bg=BG, highlightthickness=0)
        header_canvas.pack(fill=tk.X, pady=(0, 10))

        def _draw_header(canvas, width=None):
            w = width or canvas.winfo_width() or 700
            canvas.delete('all')
            # Gradient
            steps = 40
            for i in range(steps):
                ratio = i / steps
                r = int(30 * (1 - ratio) + 10 * ratio)
                g = int(58 * (1 - ratio) + 14 * ratio)
                b = int(138 * (1 - ratio) + 26 * ratio)
                color = f'#{r:02x}{g:02x}{b:02x}'
                y0 = i * (70 / steps)
                y1 = y0 + (70 / steps) + 1
                canvas.create_rectangle(0, y0, w, y1, fill=color, outline=color)
            cx = w // 2
            title_size = max(14, min(22, w // 30))
            canvas.create_text(cx, 28, text="Trader Companion 2.0",
                               font=('Segoe UI', title_size, 'bold'), fill='#f59e0b')
            canvas.create_text(cx, 55, text="Data Manager  •  Trading Engine",
                               font=('Segoe UI', 10), fill='#94a3b8')

        _draw_header(header_canvas, 700)
        header_canvas.bind('<Configure>', lambda e: _draw_header(header_canvas, e.width))

        # ━━━━━━━━━━━━━━━━━━  NOTEBOOK (TABS)  ━━━━━━━━━━━━━━━━━━
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.X, pady=(0, 6))

        # ── Tab 1: Dashboard ──
        tab_dash = ttk.Frame(self.notebook, style='TFrame')
        self.notebook.add(tab_dash, text='  📊  Dashboard  ')

        # ── Tab 2: Trading Engine ──
        tab_trade = ttk.Frame(self.notebook, style='TFrame')
        self.notebook.add(tab_trade, text='  ⚡  Trading Engine  ')

        # ── Tab 3: Tools & Settings ──
        tab_tools = ttk.Frame(self.notebook, style='TFrame')
        self.notebook.add(tab_tools, text='  🛠  Tools & Settings  ')

        # ═══════════════════════════════════════════════════════════
        #  TAB 1 — DASHBOARD
        # ═══════════════════════════════════════════════════════════

        # -- Connection Target card --
        conn_frame = ttk.LabelFrame(tab_dash, text="🌐  Connection Target", padding=8)
        conn_frame.pack(fill=tk.X, padx=6, pady=(6, 3))

        conn_row = ttk.Frame(conn_frame, style='CardBG.TFrame')
        conn_row.pack(fill=tk.X)
        ttk.Label(conn_row, text="Target:", style='CardBG.TLabel').pack(side=tk.LEFT, padx=(0, 8))

        self.target_var = tk.StringVar()
        self.url_keys = ["TradeOpps (Production)", "Localhost (Development)"]
        self.url_values = {
            "TradeOpps (Production)": "https://www.tradeopss.com",
            "Localhost (Development)": "http://127.0.0.1:5001"
        }
        self.url_selector = ttk.Combobox(conn_row, textvariable=self.target_var,
                                         state="readonly", width=32)
        self.url_selector['values'] = self.url_keys
        self.url_selector.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.url_selector.current(0)

        # Hidden entry for backward compat
        self.url_entry = ttk.Entry(tab_dash)
        self.url_entry.insert(0, self.url_values["TradeOpps (Production)"])

        def on_target_change(event):
            selection = self.target_var.get()
            if "Localhost" in selection:
                password = simpledialog.askstring("Developer Access",
                    "Enter password for local development:", show='*')
                if password == "tradeopss@123":
                    self.url_entry.delete(0, tk.END)
                    self.url_entry.insert(0, self.url_values[selection])
                    self.log(f"Switched to Localhost")
                    self.status_var.set("Target: Localhost (Dev)")
                else:
                    messagebox.showerror("Access Denied", "Incorrect password.")
                    self.url_selector.current(0)
                    self.url_entry.delete(0, tk.END)
                    self.url_entry.insert(0, self.url_values["TradeOpps (Production)"])
            else:
                self.url_entry.delete(0, tk.END)
                self.url_entry.insert(0, self.url_values[selection])
                self.log(f"Switched to Production")
                self.status_var.set("Target: Production")

        self.url_selector.bind("<<ComboboxSelected>>", on_target_change)

        # -- Client Identification card --
        id_frame = ttk.LabelFrame(tab_dash, text="👤  Client Identification", padding=8)
        id_frame.pack(fill=tk.X, padx=6, pady=3)

        email_frame = ttk.Frame(id_frame, style='CardBG.TFrame')
        email_frame.pack(fill=tk.X, pady=2)
        ttk.Label(email_frame, text="Client Email:", width=14, style='CardBG.TLabel').pack(side=tk.LEFT)
        self.client_email_entry = ttk.Entry(email_frame, width=36)
        self.client_email_entry.pack(side=tk.LEFT, padx=5)
        self.lookup_btn = ttk.Button(email_frame, text="🔍 Lookup", command=self.lookup_client)
        self.lookup_btn.pack(side=tk.LEFT, padx=5)

        self.hierarchy_var = tk.StringVar(value="Enter email and click Lookup")
        self.hierarchy_label = ttk.Label(id_frame, textvariable=self.hierarchy_var,
                                         style='CardDim.TLabel')
        self.hierarchy_label.pack(fill=tk.X, pady=(4, 0))

        # -- Push Actions card --
        push_frame = ttk.LabelFrame(tab_dash, text="📤  Data Push", padding=8)
        push_frame.pack(fill=tk.X, padx=6, pady=3)

        btn_row = ttk.Frame(push_frame, style='CardBG.TFrame')
        btn_row.pack(fill=tk.X)

        self.push_btn = ttk.Button(btn_row, text="📤  Push Data", command=self.push_data)
        self.push_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.auto_btn = ttk.Button(btn_row, text="🔄  Auto-Push",
                                   command=self.toggle_auto_push, style="AutoPush.TButton")
        self.auto_btn.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(btn_row, text="�  Push Hedging Review", command=self.push_hedging_review).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(btn_row, text="�💾  Save Config", command=self.save_config).pack(side=tk.RIGHT)

        # -- Import Data card --
        import_frame = ttk.LabelFrame(tab_dash, text="📋  Import Data", padding=8)
        import_frame.pack(fill=tk.X, padx=6, pady=3)

        source_row = ttk.Frame(import_frame, style='CardBG.TFrame')
        source_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(source_row, text="Source:", width=14, style='CardBG.TLabel').pack(side=tk.LEFT)
        self.import_source = tk.StringVar(value="sheet")
        ttk.Radiobutton(source_row, text="Google Sheets", variable=self.import_source,
                        value="sheet", command=self._toggle_import_source).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Radiobutton(source_row, text="CSV File", variable=self.import_source,
                        value="csv", command=self._toggle_import_source).pack(side=tk.LEFT)

        self.sheet_input_frame = ttk.Frame(import_frame, style='CardBG.TFrame')
        self.sheet_input_frame.pack(fill=tk.X, pady=2)
        ttk.Label(self.sheet_input_frame, text="Sheet URL:", width=14, style='CardBG.TLabel').pack(side=tk.LEFT)
        self.sheet_url_entry = ttk.Entry(self.sheet_input_frame, width=46)
        self.sheet_url_entry.pack(side=tk.LEFT, padx=5)

        self.csv_input_frame = ttk.Frame(import_frame, style='CardBG.TFrame')
        ttk.Label(self.csv_input_frame, text="CSV File:", width=14, style='CardBG.TLabel').pack(side=tk.LEFT)
        self.csv_path_var = tk.StringVar()
        self.csv_path_entry = ttk.Entry(self.csv_input_frame, textvariable=self.csv_path_var,
                                        width=36, state='readonly')
        self.csv_path_entry.pack(side=tk.LEFT, padx=5)
        ttk.Button(self.csv_input_frame, text="Browse…", command=self._browse_csv).pack(side=tk.LEFT, padx=2)

        self.import_btn = ttk.Button(import_frame, text="📥  Import Sheet Data", command=self._do_import)
        self.import_btn.pack(pady=(4, 1))

        self.import_hint = ttk.Label(import_frame, text="Sheet must be publicly shared",
                                      style='CardDim.TLabel')
        self.import_hint.pack(pady=(0, 0))

        # ═══════════════════════════════════════════════════════════
        #  TAB 2 — TRADING ENGINE
        # ═══════════════════════════════════════════════════════════
        self._build_trading_engine_ui(tab_trade)

        # ═══════════════════════════════════════════════════════════
        #  TAB 3 — TOOLS & SETTINGS
        # ═══════════════════════════════════════════════════════════

        # ═══════════════════════════════════════════════════════════
        #  STATUS LOG (always visible, below tabs)
        # ═══════════════════════════════════════════════════════════

        log_frame = ttk.LabelFrame(main_frame, text="📝  Status Log", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 2))

        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, bg='#0a0e1a', fg='#22c55e',
                                                   font=('Consolas', 9), insertbackground='white',
                                                   relief='flat', borderwidth=0)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Status bar
        self.status_var = tk.StringVar(value="Ready — enter your email to get started")
        self.status_label = ttk.Label(main_frame, textvariable=self.status_var, style='Status.TLabel')
        self.status_label.pack(fill=tk.X, pady=(2, 0))

        # State for smart auto-push
        self.last_deal_ticket = 0
        self.last_deal_count = 0
        self.auto_push_thread = None

    def log(self, message, level="INFO"):
        """Add a message to the log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = "#00ff00" if level == "INFO" else "#ff6b6b" if level == "ERROR" else "#ffcc00"
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
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
        
        try:
            # Use public endpoint - no API key needed
            response = requests.post(
                f"{dashboard_url}/api/client/auth",
                json={"email": email},
                headers={"Content-Type": "application/json"},
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    self.client_info = data.get("identity", {})
                    client = self.client_info.get("client", "Unknown")
                    trader = self.client_info.get("trader", "Unknown")
                    admin = self.client_info.get("admin", "Unknown")
                    category = self.client_info.get("category", "Unknown")
                    
                    self.hierarchy_var.set(f"✅ {client} → Trader: {trader} → Admin: {admin} | Category: {category}")
                    self.hierarchy_label.configure(foreground='#16a34a')
                    self.log(f"✅ Client found: {client} → {trader} → {admin}")
                else:
                    error_msg = data.get("message", "Client not found")
                    self.hierarchy_var.set(f"❌ {error_msg}")
                    self.hierarchy_label.configure(foreground='#dc2626')
                    self.client_info = None
                    self.log(f"❌ Lookup failed: {error_msg}", "ERROR")
            else:
                error_msg = f"API Error: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message", error_msg)
                except:
                    pass
                self.hierarchy_var.set(f"❌ {error_msg}")
                self.hierarchy_label.configure(foreground='#dc2626')
                self.client_info = None
                self.log(f"❌ Lookup failed: {error_msg}", "ERROR")
                
        except requests.exceptions.Timeout:
            self.hierarchy_var.set("❌ Connection timeout")
            self.hierarchy_label.configure(foreground='#dc2626')
            self.log("❌ Connection timeout", "ERROR")
        except requests.exceptions.ConnectionError:
            self.hierarchy_var.set("❌ Cannot connect to server")
            self.hierarchy_label.configure(foreground='#dc2626')
            self.log("❌ Cannot connect to server", "ERROR")
        except Exception as e:
            self.hierarchy_var.set(f"❌ Error: {str(e)}")
            self.hierarchy_label.configure(foreground='#dc2626')
            self.log(f"❌ Error: {e}", "ERROR")
        
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
        
        self.log(f"Pushing data for {client_name}...")
        self.status_var.set("Pushing data...")
        
        # Get MT5 data - Limit to 30 days for better coverage (especially Farming)
        account = self.pusher.get_account_info() or {}

        # Log rebalance data for verification
        if account:
            b = account.get('balance', 0)
            d = account.get('total_deposits', 0)
            w = account.get('total_withdrawals', 0)
            self.log(f"📊 Rebalance Data Check:")
            self.log(f"   - Balance: ${b}")
            self.log(f"   - Total Deposits: ${d}")
            self.log(f"   - Total Withdrawals: ${w}")

        positions = self.pusher.get_positions()
        # Fetch recent deals (30 days) for regular trading stats
        raw_deals = self.pusher.get_deals(days=30)
        if raw_deals is None:
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
        
        # Full history for aggregated results to capture all farming trades
        aggregated_result = self.pusher.get_deals_grouped_by_phase(days=365)
        aggregated_by_comment = aggregated_result.get('aggregated', [])
        comment_summary = aggregated_result.get('summary', {})
        
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
                data = response.json()
                if data.get("status") == "success":
                    self.log(f"✅ {data.get('message', 'Data pushed successfully')}")
                    if aggregated_by_comment:
                        self.log(f"   ✓ Synced {len(aggregated_by_comment)} hedge result groups from history")
                    self.status_var.set("Ready - Data pushed!")
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
        self.log(f"📊 Pushing Hedging Review for {client_name}...")
        self.status_var.set("Pushing hedging review...")

        account = self.pusher.get_account_info() or {}
        if not account:
            self.log("⚠️ No account info available from MT5", "ERROR")
            self.status_var.set("Push failed - no MT5 data")
            return

        deposits = float(account.get('total_deposits', 0) or 0)
        withdrawals = float(account.get('total_withdrawals', 0) or 0)
        balance = float(account.get('balance', 0) or 0)

        self.log(f"   Deposits: ${deposits:,.2f}")
        self.log(f"   Withdrawals: ${withdrawals:,.2f}")
        self.log(f"   Balance: ${balance:,.2f}")

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
                data = response.json()
                if data.get("status") == "success":
                    hr = data.get("hedging_review", {})
                    self.log(f"✅ Hedging Review updated for {client_name}")
                    self.log(f"   Actual Hedging Results: ${hr.get('actual_hedging_results', 0):,.2f}")
                    self.log(f"   Discrepancy: ${hr.get('discrepancy', 0):,.2f}")
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

        except Exception as e:
            self.log(f"❌ Push error: {e}", "ERROR")
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
        
        self.log(f"Pushing MT5 data only for {client_name}...")
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
        
        self.log("="*60)
        self.log("📊 REBALANCE DATA DEBUG TRACE")
        self.log("="*60)
        self.log(f"✓ Account Balance: ${balance:.2f}")
        self.log(f"✓ Total Deposits: ${deposits:.2f}")
        self.log(f"✓ Total Withdrawals: ${withdrawals:.2f}")
        self.log(f"✓ Current Equity: ${account.get('equity', 0):.2f}")
        self.log(f"✓ Profit: ${account.get('profit', 0):.2f}")
        self.log(f"✓ Actual Hedging Results: ${actual_hedging:.2f} ({trade_count} closed trades)")
        self.log(f"✓ Deals fetched: {len(deals) if deals else 0}")
        
        payload = {
            "email": email,
            "account": account,
            "positions": [],
            "deals": deals or [],  # Include deals for actual hedging calculation
            "statistics": {},  # Let server recalculate with MT5 data
            # NOTE: Do NOT include "evaluations" key - server will preserve existing data
            "dropdown_options": {}
        }
        
        self.log(f"\n📤 Sending payload with:")
        self.log(f"   - Balance: ${balance:.2f}")
        self.log(f"   - Deposits: ${deposits:.2f}")
        self.log(f"   - Withdrawals: ${withdrawals:.2f}")
        self.log(f"   - Email: {email}")
        
        try:
            response = requests.post(
                f"{dashboard_url}/api/client/push",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=120
            )
            
            self.log(f"\n📡 Server response: HTTP {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                self.log(f"✓ Response data: {data.get('status', 'unknown')}")
                
                if data.get("status") == "success":
                    self.log(f"\n✅ REBALANCE DATA PUSHED SUCCESSFULLY!")
                    self.log(f"   Balance: ${balance:.2f}")
                    self.log(f"   Deposits: ${deposits:.2f}")
                    self.log(f"   Withdrawals: ${withdrawals:.2f}")
                    self.log(f"   Message: {data.get('message', 'OK')}")
                    self.log("="*60)
                    self.status_var.set("Rebalance data pushed successfully!")
                    
                    # Suggest checking dashboard
                    self.log("\n💡 TIP: Refresh your dashboard to see updated Live Hedging Review")
                else:
                    self.log(f"❌ Push failed: {data.get('message', 'Unknown error')}", "ERROR")
                    self.log("="*60, "ERROR")
                    self.status_var.set("Push failed")
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message", error_msg)
                    self.log(f"❌ Server error response: {error_data}", "ERROR")
                except:
                    self.log(f"❌ Server response text: {response.text[:200]}", "ERROR")
                self.log(f"❌ Push failed: {error_msg}", "ERROR")
                self.log("="*60, "ERROR")
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
            self.sheet_input_frame.pack(fill=tk.X, pady=2)
            self.import_btn.config(text="📥 Import Sheet Data")
            self.import_hint.config(text="Sheet must be public")
        else:
            self.sheet_input_frame.pack_forget()
            self.csv_input_frame.pack(fill=tk.X, pady=2)
            self.import_btn.config(text="📥 Import CSV File")
            self.import_hint.config(text="Use a CSV exported from the dashboard")

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
        self.root.update_idletasks()

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
                self.log(f"❌ CSV import failed: {error_msg}", "ERROR")
                self.status_var.set("Import failed")
                messagebox.showerror("Error", error_msg)
                return

            data = response.json()
            if data.get("status") != "success":
                error_msg = data.get("message", "Import failed")
                self.log(f"❌ {error_msg}", "ERROR")
                self.status_var.set("Import failed")
                messagebox.showerror("Error", error_msg)
                return

            updated = data.get('updated', 0)
            added = data.get('added', 0)
            total = data.get('total_rows', 0)
            self.log(f"   ✅ CSV import complete!")
            self.log(f"   {updated} rows updated, {added} rows added ({total} total evaluations)")
            self.status_var.set(f"Imported {updated + added} rows from CSV")
            messagebox.showinfo("Success",
                f"CSV import complete!\n\n"
                f"• {updated} rows updated\n"
                f"• {added} rows added\n"
                f"• {total} total evaluations")
            self.lookup_client()

        except requests.exceptions.Timeout:
            self.log("❌ Connection timeout during CSV import", "ERROR")
            self.status_var.set("Timeout")
            messagebox.showerror("Timeout", "Connection timed out. Please try again.")
        except requests.exceptions.ConnectionError:
            self.log("❌ Could not connect to dashboard server", "ERROR")
            self.status_var.set("Connection failed")
            messagebox.showerror("Error", "Could not connect to dashboard server. Check the URL and try again.")
        except Exception as e:
            self.log(f"❌ CSV import error: {e}", "ERROR")
            self.status_var.set("Import failed")
            messagebox.showerror("Error", str(e))

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
                self.log(f"❌ Migration failed: {error_msg}", "ERROR")
                self.status_var.set("Migration failed")
                messagebox.showerror("Error", error_msg)
                return
            
            data = response.json()
            if data.get("status") != "success":
                error_msg = data.get("message", "Migration failed")
                self.log(f"❌ {error_msg}", "ERROR")
                self.status_var.set("Migration failed")
                messagebox.showerror("Error", error_msg)
                return
            
            records = data.get("records_imported", 0)
            self.log(f"   ✅ Successfully imported {records} records")
            self.log(f"   Dashboard data fully replaced.")
            self.status_var.set(f"Imported {records} records")
            messagebox.showinfo("Success", f"Successfully imported {records} records.\nDashboard data has been updated.")
            self.lookup_client()
                
        except requests.exceptions.Timeout:
            self.log("❌ Connection timeout - server is still processing the sheet", "ERROR")
            self.status_var.set("Timeout")
            messagebox.showerror("Timeout", "Connection timed out. The sheet may be too large or the server is busy. Please try again.")
        except requests.exceptions.ConnectionError:
            self.log("❌ Could not connect to dashboard server", "ERROR")
            self.status_var.set("Connection failed")
            messagebox.showerror("Error", "Could not connect to dashboard server. Check the URL and try again.")
        except Exception as e:
            self.log(f"❌ Migration error: {e}", "ERROR")
            self.status_var.set("Migration failed")
            messagebox.showerror("Error", str(e))
    
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
        style = ttk.Style()
        if self.auto_push_enabled:
            self.auto_push_enabled = False
            self.auto_btn.configure(text="🔄 Start Auto-Push")
            style.configure("AutoPush.TButton", background="#3b82f6") # Reset
            self.log("Auto-push stopped")
        else:
            if not self.client_info:
                messagebox.showerror("Error", "Please lookup the client first")
                return
            
            # Initialize state
            self.last_deal_count = 0
            self.last_deal_ticket = 0
            
            self.auto_push_enabled = True
            self.auto_btn.config(text="⏹ Stop Auto-Push (Smart)")
            style.configure("AutoPush.TButton", background="lightblue") 

            self.log("Smart Auto-push started (Checking for new trades...)")
            self.auto_push_thread = threading.Thread(target=self.auto_push_loop, daemon=True)
            self.auto_push_thread.start()

    def check_and_push_update(self):
        """Check if new trades exist and push update if so."""
        if not self.auto_push_enabled: return
        
        try:
            # Silent check to avoid spamming log
            # Use pusher to get deals (consistent with push_data)
            deals = self.pusher.get_deals(days=30)
            
            if not deals:
                return

            current_count = len(deals)
            last_deal = deals[-1]
            current_ticket = last_deal.get('ticket')
            
            # Logic: If count changed OR last ticket changed
            # Also push immediately if this is the first check (last_deal_count == 0)
            if self.last_deal_count == 0:
                 self.last_deal_count = current_count
                 self.last_deal_ticket = current_ticket
                 self.log(f"Auto-push active. Initial scan: {current_count} deals.")
                 # Don't push immediately on toggle unless needed? 
                 # Usually users toggle it ON to verify it works, so let's push once.
                 self.push_data()
                 return

            if current_count > self.last_deal_count or current_ticket != self.last_deal_ticket:
                self.log(f"⚡ New trade detected! (Ticket: {current_ticket}) Pushing update...")
                
                # Update state
                self.last_deal_count = current_count
                self.last_deal_ticket = current_ticket
                
                # Perform the push
                self.push_data()
            else:
                # No change
                pass
                
        except Exception as e:
            print(f"Auto-push check error: {e}")

    def auto_push_loop(self):
        """Background loop for smart auto-pushing."""
        while self.auto_push_enabled:
            # Schedule check on main thread
            self.root.after(0, self.check_and_push_update)
            
            # Check frequently (every 10s)
            for _ in range(10):
                if not self.auto_push_enabled:
                    break
                time.sleep(1)

    # ============ Trading Engine ============

    def _build_trading_engine_ui(self, parent):
        """Build the Trading Engine tab with active trades list."""
        self.trading_api = None
        self.tradovate_account = None
        self.topstepx_account = None
        self.prop_firm_mgr = PropFirmManager() if PROP_FIRM_AVAILABLE else None
        self._auto_trading_stop = threading.Event()
        self._auto_trading_thread = None
        self._direction_locks = {}
        self._active_trade_rows = []  # List of dicts tracking each trade row

        # ── MT5 Connection card ──
        mt5_frame = ttk.LabelFrame(parent, text="🔗  MT5 Connection", padding=8)
        mt5_frame.pack(fill=tk.X, padx=6, pady=(6, 3))

        mt5_top = ttk.Frame(mt5_frame, style='CardBG.TFrame')
        mt5_top.pack(fill=tk.X, pady=1)
        ttk.Label(mt5_top, text="Login:", width=10, style='CardBG.TLabel').pack(side=tk.LEFT)
        self.mt5_login = ttk.Entry(mt5_top, width=16)
        self.mt5_login.pack(side=tk.LEFT, padx=3)
        ttk.Label(mt5_top, text="Pass:", style='CardBG.TLabel').pack(side=tk.LEFT, padx=(6, 0))
        self.mt5_password = ttk.Entry(mt5_top, width=16, show="*")
        self.mt5_password.pack(side=tk.LEFT, padx=3)
        ttk.Label(mt5_top, text="Server:", style='CardBG.TLabel').pack(side=tk.LEFT, padx=(6, 0))
        self.mt5_server = ttk.Entry(mt5_top, width=20)
        self.mt5_server.pack(side=tk.LEFT, padx=3)

        mt5_btn_row = ttk.Frame(mt5_frame, style='CardBG.TFrame')
        mt5_btn_row.pack(fill=tk.X, pady=(3, 0))
        self.mt5_btn = ttk.Button(mt5_btn_row, text="Connect MT5", command=self.toggle_mt5_connection)
        self.mt5_btn.pack(side=tk.LEFT)

        if not TRADING_ENGINE_AVAILABLE:
            ttk.Label(mt5_frame,
                text="Trading engine modules not loaded — broker trading unavailable. MT5 data push still works.",
                foreground='#f59e0b', font=('Segoe UI', 9, 'italic'), background='#111827',
                wraplength=500).pack(pady=(6, 0))
            return

        # ── Broker Connection card (compact) ──
        broker_frame = ttk.LabelFrame(parent, text="🏦  Broker Connection", padding=8)
        broker_frame.pack(fill=tk.X, padx=6, pady=3)

        bk_row = ttk.Frame(broker_frame, style='CardBG.TFrame')
        bk_row.pack(fill=tk.X, pady=1)
        ttk.Label(bk_row, text="Platform:", style='CardBG.TLabel').pack(side=tk.LEFT)
        self.broker_var = tk.StringVar(value="Tradovate")
        platforms = ["Tradovate"]
        if TOPSTEPX_AVAILABLE:
            platforms.append("TopStepX")
        ttk.Combobox(bk_row, textvariable=self.broker_var, values=platforms,
                     state='readonly', width=14).pack(side=tk.LEFT, padx=4)
        ttk.Label(bk_row, text="User:", style='CardBG.TLabel').pack(side=tk.LEFT, padx=(4, 0))
        self.broker_user = ttk.Entry(bk_row, width=14)
        self.broker_user.pack(side=tk.LEFT, padx=3)
        ttk.Label(bk_row, text="Pass:", style='CardBG.TLabel').pack(side=tk.LEFT)
        self.broker_pass = ttk.Entry(bk_row, width=14, show="*")
        self.broker_pass.pack(side=tk.LEFT, padx=3)

        bk_row2 = ttk.Frame(broker_frame, style='CardBG.TFrame')
        bk_row2.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(bk_row2, text="Mode:", style='CardBG.TLabel').pack(side=tk.LEFT)
        self.trading_mode_var = tk.StringVar(value="Simulation")
        ttk.Combobox(bk_row2, textvariable=self.trading_mode_var,
                     values=["Simulation", "Live"], state='readonly', width=14).pack(side=tk.LEFT, padx=4)
        self.broker_connect_btn = ttk.Button(bk_row2, text="Connect Broker", command=self._connect_broker)
        self.broker_connect_btn.pack(side=tk.LEFT, padx=(10, 0))
        self.broker_status_var = tk.StringVar(value="Not Connected")
        ttk.Label(bk_row2, textvariable=self.broker_status_var,
                  foreground='#94a3b8', font=('Segoe UI', 9), background='#111827').pack(side=tk.LEFT, padx=6)

        # ── Hedge Mode / Direction (compact inline) ──
        opts_frame = ttk.Frame(parent, style='TFrame')
        opts_frame.pack(fill=tk.X, padx=6, pady=(4, 2))
        self.hedge_mode_var = tk.StringVar(value="Hedging")
        ttk.Radiobutton(opts_frame, text="Hedging (Broker+MT5)", variable=self.hedge_mode_var,
                        value="Hedging").pack(side=tk.LEFT, padx=(0, 8))
        ttk.Radiobutton(opts_frame, text="Broker Only", variable=self.hedge_mode_var,
                        value="BrokerOnly").pack(side=tk.LEFT, padx=(0, 16))
        self.direction_var = tk.StringVar(value="All Trades")
        ttk.Label(opts_frame, text="Direction:").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Combobox(opts_frame, textvariable=self.direction_var,
                     values=["All Trades", "Buy Only", "Sell Only"],
                     state='readonly', width=12).pack(side=tk.LEFT)

        # ── Auto-Trade Scheduler Card ──
        auto_frame = ttk.LabelFrame(parent, text="⏰  Auto-Trade Scheduler", padding=8)
        auto_frame.pack(fill=tk.X, padx=6, pady=(4, 3))

        auto_row1 = ttk.Frame(auto_frame, style='CardBG.TFrame')
        auto_row1.pack(fill=tk.X, pady=(0, 4))

        self.auto_trade_btn = tk.Button(
            auto_row1, text="▶  Start Auto-Trade", bg='#3b82f6', fg='white',
            activebackground='#2563eb', activeforeground='white',
            font=('Segoe UI', 9, 'bold'), relief='flat', padx=12, pady=3,
            command=self._toggle_auto_trade)
        self.auto_trade_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.auto_trade_status_var = tk.StringVar(value="Auto-trade off")
        ttk.Label(auto_row1, textvariable=self.auto_trade_status_var,
                  foreground='#94a3b8', font=('Segoe UI', 9),
                  background='#111827').pack(side=tk.LEFT, padx=4)

        auto_row2 = ttk.Frame(auto_frame, style='CardBG.TFrame')
        auto_row2.pack(fill=tk.X)
        self.auto_trade_countdown_var = tk.StringVar(value="")
        ttk.Label(auto_row2, textvariable=self.auto_trade_countdown_var,
                  foreground='#fbbf24', font=('Consolas', 9),
                  background='#111827').pack(side=tk.LEFT)

        # Per-firm direction display (populated when auto-trade starts)
        self.auto_trade_firms_var = tk.StringVar(value="")
        ttk.Label(auto_frame, textvariable=self.auto_trade_firms_var,
                  foreground='#e2e8f0', font=('Consolas', 9),
                  background='#111827', justify='left').pack(fill=tk.X, pady=(2, 0))

        # ── Active Trades list card ──
        trades_frame = ttk.LabelFrame(parent, text="📋  Active Trades", padding=8)
        trades_frame.pack(fill=tk.X, padx=6, pady=(4, 3))

        # Top bar with Load button
        trades_top = ttk.Frame(trades_frame, style='CardBG.TFrame')
        trades_top.pack(fill=tk.X, pady=(0, 4))
        self.load_trades_btn = ttk.Button(trades_top, text="🔄  Load Trades from Dashboard",
                                          command=self._load_active_trades)
        self.load_trades_btn.pack(side=tk.LEFT)
        self.trades_count_var = tk.StringVar(value="No trades loaded")
        ttk.Label(trades_top, textvariable=self.trades_count_var,
                  foreground='#94a3b8', font=('Segoe UI', 9), background='#111827').pack(side=tk.LEFT, padx=10)

        # Column headers
        hdr = ttk.Frame(trades_frame, style='CardBG.TFrame')
        hdr.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(hdr, text="Prop Firm", width=14, style='SectionHead.TLabel',
                  font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=2)
        ttk.Label(hdr, text="Account", width=10, style='SectionHead.TLabel',
                  font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=2)
        ttk.Label(hdr, text="Size", width=8, style='SectionHead.TLabel',
                  font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=2)
        ttk.Label(hdr, text="Current Phase", width=14, style='SectionHead.TLabel',
                  font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=2)
        ttk.Label(hdr, text="Next Phase", width=14, style='SectionHead.TLabel',
                  font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=2)
        ttk.Label(hdr, text="Action", width=16, style='SectionHead.TLabel',
                  font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=2)

        # Scrollable trade rows container
        trades_canvas = tk.Canvas(trades_frame, bg='#111827', highlightthickness=0, height=300)
        trades_scrollbar = ttk.Scrollbar(trades_frame, orient="vertical", command=trades_canvas.yview)
        self._trades_inner = ttk.Frame(trades_canvas, style='CardBG.TFrame')
        self._trades_inner.bind("<Configure>",
            lambda e: trades_canvas.configure(scrollregion=trades_canvas.bbox("all")))
        trades_canvas.create_window((0, 0), window=self._trades_inner, anchor="nw")
        trades_canvas.configure(yscrollcommand=trades_scrollbar.set)
        trades_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        trades_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Mouse wheel for trade list
        def _on_trades_wheel(event):
            trades_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        trades_canvas.bind_all("<MouseWheel>", _on_trades_wheel)

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
        "Funded Next": "FundedNext",
        "TopStep": "TopStep",
        "TradeDay": "TradeDay",
        "Tradeify": "Tradeify",
        "Alpha Futures": "AlphaFutures",
        "Apex": "Apex",
    }

    _FAILED_STATUSES = {"fail", "failed", "breach", "delete", "deleted", "closed", "sl", "ended", "lost"}

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
        """Check if an evaluation is active (not failed/ended/deleted)."""
        p1 = (ev.get("Status P1", "") or "").strip().lower()
        funded = (ev.get("Status", "") or "").strip().lower()

        # If challenge failed and no funded account, it's dead
        if p1 in self._FAILED_STATUSES and not (ev.get("Account #.1", "") or "").strip():
            return False
        # If funded failed/completed
        if funded in self._FAILED_STATUSES or funded == "complete":
            return False
        # Must have at least one account number
        if not (ev.get("Account #", "") or "").strip() and not (ev.get("Account #.1", "") or "").strip():
            return False
        return True

    def _load_active_trades(self):
        """Fetch evaluations from dashboard and populate the active trades list."""
        email = self.client_email_entry.get().strip()
        dashboard_url = self.url_entry.get().strip().rstrip('/')

        if not email:
            messagebox.showerror("Error", "Go to Dashboard tab, enter client email and click Lookup first.")
            return

        self.log("Loading active trades from dashboard...")
        self.load_trades_btn.config(state='disabled')
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

                # Filter active evals (exclude completed/farming-done)
                active_evals = []
                for ev in evaluations:
                    if not self._is_eval_active(ev) or ev.get("_deleted"):
                        continue
                    prop_firm_name = ev.get("Prop Firm", "Unknown")
                    firm_code = self._FIRM_MAP.get(prop_firm_name, "MFFU_Flex")
                    current_display, phase_key = self._detect_eval_phase(ev)
                    next_display = self._get_next_phase(firm_code, current_display)
                    if "complete" in next_display.lower():
                        continue  # Skip evaluations that have no next phase
                    active_evals.append(ev)

                self.root.after(0, lambda ae=active_evals: self._populate_trade_rows(ae))

            except Exception as e:
                self.root.after(0, lambda: self.log(f"Load trades failed: {e}", "ERROR"))
                self.root.after(0, lambda: self.trades_count_var.set("Load failed"))
            finally:
                self.root.after(0, lambda: self.load_trades_btn.config(state='normal'))

        threading.Thread(target=_do_load, daemon=True).start()

    def _populate_trade_rows(self, evaluations):
        """Clear and rebuild the active trade rows."""
        # Clear existing rows
        for child in self._trades_inner.winfo_children():
            child.destroy()
        self._active_trade_rows.clear()

        if not evaluations:
            ttk.Label(self._trades_inner, text="No active trades found",
                      foreground='#94a3b8', font=('Segoe UI', 10, 'italic'),
                      background='#111827').pack(pady=20)
            self.trades_count_var.set("0 active trades")
            return

        for idx, ev in enumerate(evaluations):
            prop_firm_name = ev.get("Prop Firm", "Unknown")
            firm_code = self._FIRM_MAP.get(prop_firm_name, "MFFU_Flex")
            acct_num = (ev.get("Account #.1", "") or ev.get("Account #", "") or "—").strip()
            acct_size = ev.get("Account Size", "—") or "—"
            current_display, phase_key = self._detect_eval_phase(ev)
            next_display = self._get_next_phase(firm_code, current_display)

            # Alternating row color
            row_bg = '#0f1729' if idx % 2 == 0 else '#111827'

            row_frame = tk.Frame(self._trades_inner, bg=row_bg)
            row_frame.pack(fill=tk.X, pady=1)

            tk.Label(row_frame, text=prop_firm_name[:16], width=14, anchor='w',
                     bg=row_bg, fg='#e2e8f0', font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=2)
            tk.Label(row_frame, text=acct_num[:12], width=10, anchor='w',
                     bg=row_bg, fg='#cbd5e1', font=('Consolas', 9)).pack(side=tk.LEFT, padx=2)
            tk.Label(row_frame, text=acct_size[:10], width=8, anchor='w',
                     bg=row_bg, fg='#94a3b8', font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=2)
            tk.Label(row_frame, text=current_display, width=14, anchor='w',
                     bg=row_bg, fg='#fbbf24', font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=2)
            tk.Label(row_frame, text=next_display, width=14, anchor='w',
                     bg=row_bg, fg='#38bdf8', font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=2)

            # BUY / SELL buttons
            btn_frame = tk.Frame(row_frame, bg=row_bg)
            btn_frame.pack(side=tk.LEFT, padx=4)

            row_data = {
                "frame": row_frame,
                "eval": ev,
                "firm_code": firm_code,
                "phase_key": phase_key,
                "acct_size": acct_size,
                "acct_num": acct_num,
                "current_phase": current_display,
            }

            buy_btn = tk.Button(btn_frame, text="▲ BUY", bg='#16a34a', fg='white',
                                activebackground='#15803d', activeforeground='white',
                                font=('Segoe UI', 8, 'bold'), relief='flat', padx=6, pady=1,
                                command=lambda rd=row_data: self._execute_row_trade("buy", rd))
            buy_btn.pack(side=tk.LEFT, padx=(0, 4))

            sell_btn = tk.Button(btn_frame, text="▼ SELL", bg='#dc2626', fg='white',
                                 activebackground='#b91c1c', activeforeground='white',
                                 font=('Segoe UI', 8, 'bold'), relief='flat', padx=6, pady=1,
                                 command=lambda rd=row_data: self._execute_row_trade("sell", rd))
            sell_btn.pack(side=tk.LEFT)

            row_data["buy_btn"] = buy_btn
            row_data["sell_btn"] = sell_btn
            self._active_trade_rows.append(row_data)

        count = len(self._active_trade_rows)
        self.trades_count_var.set(f"{count} active trade{'s' if count != 1 else ''}")
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
        broker_account = self.tradovate_account if platform == "Tradovate" else self.topstepx_account

        if not broker_account:
            messagebox.showerror("Error", f"Connect to {platform} first")
            return

        mt5_api = None
        if hedging:
            mt5_api = self._get_mt5_trading_api()
            if not mt5_api:
                messagebox.showerror("Error", "Connect MT5 for hedging mode")
                return

        trado_sym = config.get("tradovate_symbol", "") or config.get("topstepx_symbol", "")
        trado_qty = int(config.get("tradovate_qty", 2) or config.get("topstepx_qty", 2))
        trado_tp = int(config.get("tradovate_tp_ticks", 151) or config.get("topstepx_tp_ticks", 151))
        trado_sl = int(config.get("tradovate_sl_ticks", 200) or config.get("topstepx_sl_ticks", 200))
        mt5_sym = config.get("mt5_symbol", "NAS100")
        mt5_vol = float(config.get("mt5_volume", 2.8))
        mt5_tp = int(config.get("mt5_tp_points", 46))
        mt5_sl = int(config.get("mt5_sl_points", 42))

        hedge_text = f" + MT5 {('SELL' if side == 'buy' else 'BUY')} {mt5_vol} {mt5_sym}" if hedging else ""
        confirm = messagebox.askyesno("Confirm Trade",
            f"{side.upper()} {trado_qty} {trado_sym} on {platform}\n"
            f"{hedge_text}\n\n"
            f"Account: {acct_num}  |  {firm_code}\n"
            f"Phase: {row_data['current_phase']}  |  Size: {acct_size}\n"
            f"TP: {trado_tp} ticks  |  SL: {trado_sl} ticks\n\n"
            f"Proceed?")
        if not confirm:
            return

        # Disable buttons immediately
        row_data["buy_btn"].config(state='disabled', text="...")
        row_data["sell_btn"].config(state='disabled', text="...")

        self.log(f"Executing {side.upper()} for {acct_num} ({firm_code} {row_data['current_phase']})...")

        def _do_trade():
            try:
                # 1. Broker order
                if platform == "Tradovate":
                    if side == "buy":
                        broker_account.buy_market(trado_sym, trado_qty, tp=trado_tp, sl=trado_sl)
                    else:
                        broker_account.sell_market(trado_sym, trado_qty, tp=trado_tp, sl=trado_sl)
                elif platform == "TopStepX":
                    if side == "buy":
                        broker_account.place_buy_order(trado_sym, trado_qty)
                    else:
                        broker_account.place_sell_order(trado_sym, trado_qty)

                self.log(f"✅ {platform} {side.upper()} {trado_qty} {trado_sym} — Acct {acct_num}")

                # 2. MT5 hedge (opposite direction)
                if hedging and mt5_api:
                    hedge_side = "sell" if side == "buy" else "buy"
                    comment = f"{acct_num}_{phase_key}"
                    if hedge_side == "buy":
                        mt5_api.buy_market(mt5_sym, mt5_vol, sl=mt5_sl, tp=mt5_tp, comment=comment)
                    else:
                        mt5_api.sell_market(mt5_sym, mt5_vol, sl=mt5_sl, tp=mt5_tp, comment=comment)
                    self.log(f"✅ MT5 Hedge {hedge_side.upper()} {mt5_vol} {mt5_sym}")

                self.log(f"✅ Trade complete for {acct_num}")

                # Remove row from list
                def _remove():
                    row_data["frame"].destroy()
                    if row_data in self._active_trade_rows:
                        self._active_trade_rows.remove(row_data)
                    remaining = len(self._active_trade_rows)
                    self.trades_count_var.set(
                        f"{remaining} active trade{'s' if remaining != 1 else ''}"
                        if remaining > 0 else "All trades complete ✓")

                self.root.after(0, _remove)

            except Exception as e:
                self.log(f"❌ Trade failed for {acct_num}: {e}", "ERROR")
                self.root.after(0, lambda: messagebox.showerror("Trade Error", str(e)))
                # Re-enable buttons on failure
                self.root.after(0, lambda: row_data["buy_btn"].config(state='normal', text="▲ BUY"))
                self.root.after(0, lambda: row_data["sell_btn"].config(state='normal', text="▼ SELL"))

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

        # Validation: need broker connected
        platform = self.broker_var.get()
        broker_account = self.tradovate_account if platform == "Tradovate" else self.topstepx_account
        if not broker_account:
            self.log(f"⚠ Connect to {platform} first before enabling auto-trade", "WARN")
            return

        # Validation: hedging mode needs MT5
        if self.hedge_mode_var.get() == "Hedging":
            mt5_api = self._get_mt5_trading_api()
            if not mt5_api:
                self.log("⚠ Connect MT5 first for hedging mode auto-trade", "WARN")
                return

        EAT = timezone(timedelta(hours=3))  # East Africa Time (UTC+3)
        now_eat = datetime.now(EAT)

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

        # Randomize direction per prop firm
        firms_in_rows = set()
        for rd in self._active_trade_rows:
            firm_name = rd["eval"].get("Prop Firm", rd["firm_code"])
            firms_in_rows.add(firm_name)
        self._auto_trade_firm_sides = {}
        for firm in sorted(firms_in_rows):
            self._auto_trade_firm_sides[firm] = random.choice(["buy", "sell"])

        # Build display string
        dir_lines = []
        for firm, s in self._auto_trade_firm_sides.items():
            arrow = "▲" if s == "buy" else "▼"
            dir_lines.append(f"  {arrow} {s.upper():4s}  {firm}")
        self.auto_trade_firms_var.set("\n".join(dir_lines))

        time_str = scheduled_eat.strftime("%I:%M %p EAT")
        self.auto_trade_btn.config(text="⏹  Stop Auto-Trade", bg='#dc2626',
                                   activebackground='#b91c1c')
        self.auto_trade_status_var.set(f"Scheduled at {time_str} — random dirs per firm")
        self.log(f"⏰ Auto-trade scheduled at {time_str} (+{offset_minutes}min random offset)")
        for firm, s in self._auto_trade_firm_sides.items():
            self.log(f"   {'▲' if s == 'buy' else '▼'} {firm} → {s.upper()}")

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
        self.auto_trade_btn.config(text="▶  Start Auto-Trade", bg='#3b82f6',
                                   activebackground='#2563eb')
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
        """Execute trades for ALL loaded rows without confirmation dialogs."""
        firm_sides = getattr(self, '_auto_trade_firm_sides', {})
        rows = list(self._active_trade_rows)  # snapshot

        if not rows:
            self.log("⚠ No trades to execute — list is empty")
            self._stop_auto_trade()
            return

        self.log(f"🚀 Auto-executing {len(rows)} accounts (random direction per firm)...")

        hedging = self.hedge_mode_var.get() == "Hedging"
        platform = self.broker_var.get()
        broker_account = self.tradovate_account if platform == "Tradovate" else self.topstepx_account
        mt5_api = self._get_mt5_trading_api() if hedging else None

        def _do_auto_trades():
            success_count = 0
            fail_count = 0
            for row_data in rows:
                if self._auto_trade_stop.is_set():
                    self.root.after(0, lambda: self.log("⏹ Auto-trade stopped mid-execution"))
                    break

                firm_code = row_data["firm_code"]
                phase_key = row_data["phase_key"]
                acct_size = row_data["acct_size"]
                acct_num = row_data["acct_num"]
                firm_name = row_data["eval"].get("Prop Firm", firm_code)
                side = firm_sides.get(firm_name, random.choice(["buy", "sell"]))

                config = None
                if self.prop_firm_mgr:
                    config = self.prop_firm_mgr.get_strategy_config(
                        firm_code, phase_key, acct_size)
                if not config:
                    self.root.after(0, lambda an=acct_num: self.log(
                        f"❌ No blueprint for {an} — skipped", "ERROR"))
                    fail_count += 1
                    continue

                trado_sym = config.get("tradovate_symbol", "") or config.get("topstepx_symbol", "")
                trado_qty = int(config.get("tradovate_qty", 2) or config.get("topstepx_qty", 2))
                trado_tp = int(config.get("tradovate_tp_ticks", 151) or config.get("topstepx_tp_ticks", 151))
                trado_sl = int(config.get("tradovate_sl_ticks", 200) or config.get("topstepx_sl_ticks", 200))
                mt5_sym = config.get("mt5_symbol", "NAS100")
                mt5_vol = float(config.get("mt5_volume", 2.8))
                mt5_tp = int(config.get("mt5_tp_points", 46))
                mt5_sl = int(config.get("mt5_sl_points", 42))

                try:
                    # 1. Broker order
                    if platform == "Tradovate":
                        if side == "buy":
                            broker_account.buy_market(trado_sym, trado_qty, tp=trado_tp, sl=trado_sl)
                        else:
                            broker_account.sell_market(trado_sym, trado_qty, tp=trado_tp, sl=trado_sl)
                    elif platform == "TopStepX":
                        if side == "buy":
                            broker_account.place_buy_order(trado_sym, trado_qty)
                        else:
                            broker_account.place_sell_order(trado_sym, trado_qty)

                    self.root.after(0, lambda an=acct_num, fc=firm_code, sd=side:
                        self.log(f"✅ {platform} {sd.upper()} {trado_qty} {trado_sym} — {an} ({fc})"))

                    # 2. MT5 hedge (opposite direction)
                    if hedging and mt5_api:
                        hedge_side = "sell" if side == "buy" else "buy"
                        comment = f"{acct_num}_{phase_key}"
                        if hedge_side == "buy":
                            mt5_api.buy_market(mt5_sym, mt5_vol, sl=mt5_sl, tp=mt5_tp, comment=comment)
                        else:
                            mt5_api.sell_market(mt5_sym, mt5_vol, sl=mt5_sl, tp=mt5_tp, comment=comment)
                        self.root.after(0, lambda an=acct_num:
                            self.log(f"✅ MT5 hedge placed for {an}"))

                    success_count += 1

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

                    # Small delay between accounts to avoid overwhelming the broker
                    time.sleep(2)

                except Exception as e:
                    fail_count += 1
                    self.root.after(0, lambda an=acct_num, err=str(e):
                        self.log(f"❌ Auto-trade failed for {an}: {err}", "ERROR"))

            # Final summary
            self.root.after(0, lambda s=success_count, f=fail_count:
                self.log(f"🏁 Auto-trade complete: {s} succeeded, {f} failed"))
            self.root.after(0, self._stop_auto_trade)

        threading.Thread(target=_do_auto_trades, daemon=True).start()

    def _on_prop_firm_change(self, event=None):
        """Update phase and size options when prop firm changes (compat stub)."""
        pass

    def _update_account_sizes(self):
        """Update account size (compat stub)."""
        pass

    def _connect_broker(self):
        """Connect to the selected broker platform."""
        platform = self.broker_var.get()
        user = self.broker_user.get().strip()
        pwd = self.broker_pass.get().strip()
        mode = self.trading_mode_var.get()

        if not user or not pwd:
            messagebox.showerror("Error", "Enter broker username and password")
            return

        self.log(f"Connecting to {platform}...")
        self.broker_status_var.set("Connecting...")

        def _do_connect():
            try:
                if platform == "Tradovate" and TRADOVATE_AVAILABLE:
                    self.tradovate_account = TradovateAccount(user, pwd, trading_mode=mode)
                    self.tradovate_account.login()
                    self.root.after(0, lambda: self.broker_status_var.set("✅ Tradovate Connected"))
                    self.root.after(0, lambda: self.broker_connect_btn.config(text="Disconnect Broker"))
                    self.log(f"Tradovate connected ({mode})")
                elif platform == "TopStepX" and TOPSTEPX_AVAILABLE:
                    self.topstepx_account = TopStepXAccount(user, pwd)
                    self.topstepx_account.login()
                    self.root.after(0, lambda: self.broker_status_var.set("✅ TopStepX Connected"))
                    self.root.after(0, lambda: self.broker_connect_btn.config(text="Disconnect Broker"))
                    self.log(f"TopStepX connected")
                else:
                    self.root.after(0, lambda: self.broker_status_var.set("❌ Platform unavailable"))
                    self.log(f"{platform} module not available", "ERROR")
            except Exception as e:
                self.root.after(0, lambda: self.broker_status_var.set(f"❌ Failed"))
                self.log(f"Broker connection failed: {e}", "ERROR")

        threading.Thread(target=_do_connect, daemon=True).start()

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
            config["broker_user"] = self.broker_user.get()
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
                    if config.get('broker_user'):
                        self.broker_user.delete(0, tk.END)
                        self.broker_user.insert(0, config['broker_user'])
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
        print("MT5 Trader Companion - Console Mode")
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
