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
APP_VERSION = "1.6.4"
RELEASE_DISABLE_STATUS_POLL = True
RELEASE_DISABLE_AUTO_STATUS_UPDATES = True
RELEASE_DISABLE_PROP_DASHBOARD_ACCESS = True
RELEASE_DISABLE_PUSH_BILLING = True
"""
Tradeopss AI
A desktop application for traders to push their MT5 data to the Trading Dashboard.
"""
import sys
import os
import json
import gzip as _gzip
import requests
import time
from datetime import datetime, timedelta, timezone

# ── Kenya / East Africa Time (UTC+3) ───────────────────────────────────
# Every day-of-week and trading-day decision is computed in Kenya time,
# never in the host machine's local clock.  A Windows install whose
# timezone is not set to Kenya (or a cloud VPS in another region) would
# otherwise roll past midnight in Kenya while the code still thinks the
# date is yesterday — which is what caused the auto-trade gate to
# classify the current day as "future" and refuse trades.
#
# Kenya does not observe DST, so a fixed UTC+3 offset is correct
# year-round.  We try zoneinfo first (more discoverable in logs) and
# fall back to a fixed offset if tzdata is missing on the host.
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    KENYA_TZ = ZoneInfo("Africa/Nairobi")
except Exception:  # pragma: no cover — bare Python without tzdata
    KENYA_TZ = timezone(timedelta(hours=3), name="EAT")


def kenya_now():
    """Current datetime in Kenya / EAT (UTC+3)."""
    return datetime.now(KENYA_TZ)


def kenya_today():
    """Today's calendar date in Kenya / EAT (UTC+3)."""
    return kenya_now().date()


# ── MT5 trade-comment helper ─────────────────────────────────────────
# `MqlTradeRequest.comment` in MetaTrader 5 is a 32-byte char[] — only
# 31 usable characters.  When the comment is longer, mt5.order_send
# returns None and mt5.last_error() reports (-2, 'Invalid "comment"
# argument') with no other diagnostic.  The raw form we used to build
# — f"{acct_num}_{phase_key}" — overflows for any account whose
# identifier is >14 chars (every FundedNext / TopstepX account is),
# so the helper below produces a comment that fits while still being
# readable in MT5 history (the account-number tail + a short phase
# tag are enough to correlate a hedge back to its prop row).

import re as _re  # local alias to avoid colliding with the `re` import
                  # used further down the file


def _normalize_acct_for_comment(acct_num: str, platform: str | None = None) -> str:
    """Broker-specific normalisation of the account number used in MT5
    comments — mirrors the TradeAccountConnector's per-broker logic.

    The connector normalises account numbers inside each broker module
    *before* the comment is built, and there are two distinct rules:

    1. **TopStepX** — ``src/topstepx.py:871-880`` and ``:917-933``.
       Raw text like ``"50KTC-V2-342449-32181797"`` reduces to
       ``"V2-...1797"`` (literal ``V2-`` + ellipsis + last 4 chars
       of the trailing segment).  The format is identical for every
       TopStepX phase (challenge / funded / double-dip / farming) —
       phase information only enters at the trailing ``_XXn`` suffix.

    2. **Tradovate / prop-firm accounts** — ``src/tradovate.py:1302-1305``.
       Any account 9+ chars long becomes ``<first 4>...<last 5>``,
       which is what produces the ``MFFU...32064``, ``FNFT...24940``,
       ``FTDF...00742``, ``TDFY...85097`` strings visible in the
       MT5 comment column.

    Rule 1 is checked first because its dash-shape would also satisfy
    rule 2 — but the connector specifically uses the ``V2-...`` form
    for TopStepX.  If neither rule matches (already shortened or too
    short), the value passes through verbatim.

    When ``platform == "TopStepX"`` we additionally guarantee a
    ``V2-...`` prefix even when the raw input has no ``V2-`` marker
    (e.g. dashes stripped upstream, or only the trailing account ID
    was passed in).  Without this, an edge-case input like
    ``"32877781"`` would slip through as ``32877781_FD1`` instead of
    the connector-compatible ``V2-...7781_FD1``.
    """
    raw = str(acct_num or "")

    # Rule 1 — TopStepX: "50KTC-V2-342449-32181797" -> "V2-...1797"
    if "V2-" in raw and "-" in raw:
        parts = raw.split("-")
        if len(parts) >= 4:
            last = parts[-1]
            if len(last) >= 4:
                return f"V2-...{last[-4:]}"

    # Force the V2-... form for any TopStepX account whose raw shape
    # doesn't include a V2- segment (dashes stripped upstream, only the
    # account ID was passed, etc.).  Falls back to the last 4 chars
    # of whatever we got.
    if platform == "TopStepX":
        if raw.startswith("V2-..."):
            return raw  # already normalised, idempotent
        # Take the last 4 chars of the *alphanumeric* tail — strip any
        # leading separators / spaces so "32877781" or "...77781" both
        # produce "V2-...7781".
        tail = ''.join(ch for ch in raw if ch.isalnum())
        if len(tail) >= 4:
            return f"V2-...{tail[-4:]}"
        # Less than 4 alnum chars — keep whatever we have.  Better to
        # ship a debuggable identifier than to invent digits.
        return f"V2-...{tail}"

    # Rule 2 — generic Tradovate-style 4+5 truncation, only if the
    # account is long enough to need it AND doesn't already look
    # shortened (no existing ellipsis).
    if len(raw) >= 9 and "..." not in raw:
        return f"{raw[:4]}...{raw[-5:]}"

    return raw


def short_mt5_comment(
    acct_num: str,
    phase_key: str,
    platform: str | None = None,
    limit: int = 31,
) -> str:
    """Build an MT5 trade comment matching the TradeAccountConnector format.

    Wire format:  ``"<account_number><phase_abbr>"``

    Two halves glued together, no separator (``phase_abbr`` already
    starts with an underscore).

    Part 1 — ``account_number``: each broker emits its own shape, and
    the connector normalises it before the comment is built (TopStepX
    gets the ``V2-...XXXX`` form, Tradovate/prop accounts get the
    ``<first 4>...<last 5>`` form).  See
    ``_normalize_acct_for_comment``.

    ``platform`` should be set to ``"TopStepX"`` for any TopStepX
    trade so the comment is guaranteed to start with ``V2-`` even if
    the raw account string lost its ``V2-`` marker upstream — this
    keeps every TopStep phase (CH, FD, DD, FA) on the same prefix.

    Part 2 — ``phase_abbr``: the connector's universal vocabulary, so
    its parser (``_(CH|FD|DD)\\d+$`` / ``_FA`` / ``_UNK`` at
    ``src/mt5.py:2253``) can round-trip the comment back to the
    account number.

        challenge_trade1..4         -> _CH1.._CH4
        funded_trade1..4            -> _FD1.._FD4
        funded_trade_doubledip_1..4 -> _DD1.._DD4
        farming                     -> _FA
        anything else / empty       -> _UNK

    MT5's ``MqlTradeRequest.comment`` is a 32-byte ``char[]``
    (31 usable chars).  If the combined form overflows, the LEFT
    characters of the account number are trimmed — the firm prefix
    repeats across many accounts; the suffix is what identifies a
    single account.  ``phase_abbr`` is preserved intact so the
    connector's parser still works against the trimmed comment.
    """
    raw_acct = _normalize_acct_for_comment(acct_num, platform=platform)

    pk = str(phase_key or "").strip().lower()
    if pk.startswith("funded_trade_doubledip_"):
        n = pk[len("funded_trade_doubledip_"):]
        phase_abbr = f"_DD{n}" if n.isdigit() else "_DD1"
    elif pk.startswith("challenge_trade"):
        n = pk[len("challenge_trade"):]
        phase_abbr = f"_CH{n}" if n.isdigit() else "_CH1"
    elif pk.startswith("funded_trade"):
        n = pk[len("funded_trade"):]
        phase_abbr = f"_FD{n}" if n.isdigit() else "_FD1"
    elif pk == "farming":
        # Connector's writer also supports "_FA_DDMMYY", but its own
        # reverse parser only recognises the bare "_FA" form, so we
        # use that for round-trip correctness.
        phase_abbr = "_FA"
    elif pk == "":
        phase_abbr = ""
    else:
        phase_abbr = "_UNK"

    candidate = f"{raw_acct}{phase_abbr}"
    if len(candidate) <= limit:
        return candidate

    # Too long — trim account from the LEFT, keep phase_abbr intact so
    # the connector's parser still strips it cleanly.
    max_acct = max(limit - len(phase_abbr), 4)
    return f"{raw_acct[-max_acct:]}{phase_abbr}"[:limit]


import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from typing import Dict
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
        FundedNextCDPAccount, ensure_chrome_debug, shutdown_debug_chrome_spawned)
    CDP_SCRAPERS_AVAILABLE = True
except Exception:
    try:
        from prop_firm_scrapers import (
            TradeifyAccount, LucidTradingAccount, TopStepAccount, MFFUAccount,
            FundedNextCDPAccount, ensure_chrome_debug, shutdown_debug_chrome_spawned)
        CDP_SCRAPERS_AVAILABLE = True
    except Exception:
        CDP_SCRAPERS_AVAILABLE = False
        TradeifyAccount = LucidTradingAccount = TopStepAccount = MFFUAccount = None
        FundedNextCDPAccount = None
        ensure_chrome_debug = None
        shutdown_debug_chrome_spawned = None

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


def _gzip_post(url, payload, timeout=120, **kwargs):
    """
    POST JSON payload compressed with gzip.
    Sends Content-Encoding: gzip so the server can decompress it.
    Falls back to normal JSON POST if compression somehow fails.
    """
    # Always tag pushes with the Trader Companion version (server may persist it per-client).
    try:
        if isinstance(payload, dict) and ('/api/client/push' in url or '/api/client/push_hedging_review' in url):
            payload.setdefault('companion_version', APP_VERSION)
    except Exception:
        pass
    try:
        raw = json.dumps(payload).encode('utf-8')
        compressed = _gzip.compress(raw, compresslevel=6)
        headers = kwargs.pop('headers', {})
        headers['Content-Type'] = 'application/json'
        headers['Content-Encoding'] = 'gzip'
        # Redundant tagging so server can record version even if payload is transformed upstream.
        if '/api/client/push' in url or '/api/client/push_hedging_review' in url:
            headers.setdefault('X-Companion-Version', APP_VERSION)
        return requests.post(url, data=compressed, headers=headers, timeout=timeout, **kwargs)
    except Exception:
        # Fallback: plain JSON
        h = kwargs.pop('headers', {}) or {}
        h.setdefault('Content-Type', 'application/json')
        if '/api/client/push' in url or '/api/client/push_hedging_review' in url:
            h.setdefault('X-Companion-Version', APP_VERSION)
        return requests.post(url, json=payload, headers=h, timeout=timeout, **kwargs)


def _to_topstepx_symbol(sym):
    """Convert Tradovate-style futures symbol to TopStepX-style.

    Tradovate uses a single-digit year (e.g. NQM6 = NQ June 2026).
    TopStepX expects a two-digit year (e.g. NQM26).

    Recognized month codes: F G H J K M N Q U V X Z
    Returns the input unchanged if it doesn't look like a futures symbol.
    """
    if not sym:
        return sym
    s = str(sym).strip().upper()
    m = re.match(r"^([A-Z]+)([FGHJKMNQUVXZ])(\d{1,2})$", s)
    if not m:
        return s
    root, month, year = m.group(1), m.group(2), m.group(3)
    if len(year) == 2:
        return s  # Already in TSX format
    # Expand single-digit year using current decade, rolling forward if needed
    from datetime import datetime as _dt
    cur_year = _dt.now().year
    decade = (cur_year // 10) * 10
    candidate = decade + int(year)
    if candidate < cur_year - 1:
        candidate += 10
    return f"{root}{month}{str(candidate % 100).zfill(2)}"


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
    
    def get_account_info(self, include_balance_history=False):
        """Get account information, optionally including full-history deposits/withdrawals."""
        if not self.connected:
            return None
        
        account = mt5.account_info()
        if not account:
            return None
        
        total_deposits = 0.0
        total_withdrawals = 0.0
        if include_balance_history:
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
        
        # Merge in deep-history farming deals for correct hedge day calculation.
        # 365 days can undercount long-lived farming accounts and push to wrong Hedge Day slot.
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
        def _normalize_fa_day(_agg):
            """Return canonical YYYY-MM-DD farming day key using timestamps first, then fallback date text."""
            for _k in ("close_time", "open_time"):
                _tv = _agg.get(_k)
                if _tv:
                    _s = str(_tv).replace('T', ' ')
                    if len(_s) >= 10:
                        return _s[:10]
            _fd = str(_agg.get('farming_date') or '').strip()
            if not _fd:
                return ''
            # Supports DD/MM from comments, and ISO-like values from parser output.
            try:
                if '/' in _fd:
                    _d, _m = _fd.split('/')[:2]
                    _d = int(_d)
                    _m = int(_m)
                    _y = datetime.now().year
                    return f"{_y:04d}-{_m:02d}-{_d:02d}"
                if '-' in _fd and len(_fd) >= 10:
                    return _fd[:10]
            except Exception:
                pass
            return _fd

        _fa_by_key = {}   # (account_number, normalized_day_key) -> merged dict
        _non_fa = []
        for _agg in aggregated:
            if _agg.get('phase_code') == 'FA':
                _date_key = _normalize_fa_day(_agg)
                _key = (_agg.get('account_number', ''), _date_key)
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
        _fa_per_account = {}   # account_number -> sorted list of (normalized_day_key, entry)
        for (acct, day_key), entry in _fa_by_key.items():
            _fa_per_account.setdefault(acct, []).append((day_key, entry))

        _fa_to_push = []   # only latest per account, tagged with _fa_slot
        for acct, date_entries in _fa_per_account.items():
            date_entries.sort(key=lambda x: x[0])          # chronological order by normalized day
            total_days = len(date_entries)                  # count = hedge day slot
            latest_day_key, latest_entry = date_entries[-1]
            tagged = dict(latest_entry)
            tagged['_fa_slot'] = total_days                 # pre-computed slot number
            _fa_to_push.append(tagged)
            match_log.append(
                f"   📅 {acct}: {total_days} FA day(s) in MT5 history "
                f"→ will push as Hedge Day {total_days} ({latest_day_key})"
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
                    # Slot number is pre-computed from MT5 history count (distinct FA trading days).
                    # Re-pushes on the same day should keep writing to the same Hedge Day slot.
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


class TradeOpssAIApp:
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
        "TopStep RTP":      "#EA580C",   # amber-orange — child of Topstep, distinct from standard red
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
        self.root.bind("<Control-m>", self._test_min_equity)
        self.root.protocol("WM_DELETE_WINDOW", self._on_app_closing)

        # Set Window Icon + section logo
        self._section_logo = None  # small logo for section headers
        try:
            if hasattr(sys, '_MEIPASS'):
                _base = sys._MEIPASS
            else:
                _base = os.path.dirname(os.path.abspath(__file__))
            from PIL import Image as PILImage, ImageTk
            png_path = os.path.join(_base, 'logo.png')
            if os.path.exists(png_path):
                _pil_icon = PILImage.open(png_path).convert('RGBA')
                bbox = _pil_icon.getbbox()
                if bbox:
                    _pil_icon = _pil_icon.crop(bbox)
                w, h = _pil_icon.size
                s = max(w, h)
                # Dark background so logo is visible in taskbar
                _sq = PILImage.new('RGBA', (s, s), (6, 14, 26, 255))
                _sq.paste(_pil_icon, ((s - w) // 2, (s - h) // 2), _pil_icon)
                # Taskbar icon (64x64)
                _taskbar = _sq.resize((64, 64), PILImage.LANCZOS)
                self._app_icon = ImageTk.PhotoImage(_taskbar)
                self.root.iconphoto(True, self._app_icon)
                self.root.after(200, lambda: self.root.iconphoto(True, self._app_icon))
                # Small logo for section headers (18x18)
                _small = _sq.resize((18, 18), PILImage.LANCZOS)
                self._section_logo = ImageTk.PhotoImage(_small)
            else:
                ico_path = os.path.join(_base, 'logo.ico')
                if os.path.exists(ico_path):
                    self.root.iconbitmap(ico_path)
                    self.root.after(200, lambda: self.root.iconbitmap(ico_path))
        except Exception:
            pass

        self.pusher = MT5DataPusher()
        self.auto_push_enabled = False
        self.auto_push_thread = None
        self._push_lock = threading.Lock()
        self._push_in_progress = False
        self._push_pending = False
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
        self._firm_billing_summary = {}   # {firm_name: {total_fees, total_payouts, records: [...]}}
        self.push_billing_btn = None
        self._status_poll_active = False   # real-time status polling flag
        self._last_known_statuses = {}     # {acct_display: last_computed_status} for change detection
        self._cached_acct_mappings = {}    # {firm_name: {acct_key: info}} cached on connect

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
            if self._section_logo:
                lbl = ctk.CTkLabel(hdr, text="", image=self._section_logo,
                                   width=18, height=18)
                lbl.pack(side="left", padx=(0, 6))
            elif icon:
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

        if not RELEASE_DISABLE_PUSH_BILLING:
            # Separator before Push Billing
            ctk.CTkFrame(toolbar, width=1, fg_color=self.C_BORDER).pack(side="left", fill="y", pady=6)

            self.push_billing_btn = self._ctk_button(toolbar, text="💰 Push Billing",
                                                      command=self._push_billing_data,
                                                      fg="#f59e0b", hover="#d97706", width=110)
            self.push_billing_btn.pack(side="left", padx=(8, 4), pady=5)

        self._ctk_button(toolbar, text="Save Config", command=self.save_config,
                         fg=self.C_BG_THIRD, hover=self.C_BORDER, width=90).pack(side="right", padx=(0, 8), pady=5)

        self._ctk_button(toolbar, text="✕ Close All", command=self._close_all_trades,
                         fg="#DC2626", hover="#B91C1C", width=90).pack(side="right", padx=(0, 4), pady=5)

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

        self.mt5_free_margin_var = tk.StringVar(value="")
        ctk.CTkLabel(trades_bezel, textvariable=self.mt5_free_margin_var,
                     font=("Consolas", 9), text_color="#38bdf8").pack(side="right", padx=(0, 8))

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
                            
                            # Auto-fetch hedge accounts to populate MT5 credentials
                            def _fetch_hedge_creds(cl=client, url=dashboard_url):
                                try:
                                    r2 = requests.get(
                                        f"{url}/api/data?client_id={cl}",
                                        timeout=15
                                    )
                                    if r2.status_code == 200:
                                        d2 = r2.json()
                                        hedge_accounts = d2.get('hedge_accounts') or []
                                        if hedge_accounts:
                                            ha = hedge_accounts[0]
                                            ha_login = str(ha.get('login', '')).strip()
                                            ha_pass = str(ha.get('password', '')).strip()
                                            ha_server = str(ha.get('server', '')).strip()
                                            def _fill_creds(l=ha_login, p=ha_pass, s=ha_server):
                                                if l:
                                                    self.mt5_login.delete(0, 'end')
                                                    self.mt5_login.insert(0, l)
                                                if p:
                                                    self.mt5_password.delete(0, 'end')
                                                    self.mt5_password.insert(0, p)
                                                if s:
                                                    self.mt5_server.delete(0, 'end')
                                                    self.mt5_server.insert(0, s)
                                                if l or s:
                                                    self.log(f"🔑 MT5 credentials auto-filled from hedge accounts (Login: {l}, Server: {s})")
                                            self.root.after(0, _fill_creds)
                                except Exception:
                                    pass
                            threading.Thread(target=_fetch_hedge_creds, daemon=True).start()
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
            self.mt5_btn.configure(text="Connect MT5")
            self.log(msg)
        else:
            login = self.mt5_login.get().strip()
            password = self.mt5_password.get()
            server = self.mt5_server.get().strip()

            success, msg = self.pusher.connect_mt5(login, password, server)
            if success:
                self.mt5_btn.configure(text="Disconnect MT5")
            self.log(msg, "INFO" if success else "ERROR")

    def _auto_connect_mt5(self):
        """Auto-connect to MT5 once credentials are present (e.g. right after the
        dashboard auto-fills them). No-op if already connected or the login/pass/
        server fields aren't all filled yet. The connect call is blocking, so it
        runs off the UI thread; on success the button flips to 'Disconnect MT5'."""
        try:
            if getattr(self.pusher, "connected", False):
                # Already connected — just make sure the button reflects it.
                try:
                    self.mt5_btn.configure(text="Disconnect MT5")
                except Exception:
                    pass
                return
            login = self.mt5_login.get().strip()
            password = self.mt5_password.get()
            server = self.mt5_server.get().strip()
        except Exception:
            return

        if not (login and password and server):
            return  # nothing to connect with yet

        # Guard against stacking multiple in-flight auto-connect attempts.
        if getattr(self, "_mt5_autoconnect_inflight", False):
            return
        self._mt5_autoconnect_inflight = True
        try:
            self.mt5_btn.configure(text="Connecting...", state="disabled")
        except Exception:
            pass

        def _worker(lg=login, pw=password, sv=server):
            try:
                success, msg = self.pusher.connect_mt5(lg, pw, sv)
            except Exception as e:
                success, msg = False, f"MT5 auto-connect error: {e}"

            def _apply():
                self._mt5_autoconnect_inflight = False
                try:
                    self.mt5_btn.configure(
                        state="normal",
                        text="Disconnect MT5" if success else "Connect MT5",
                    )
                except Exception:
                    pass
                self.log(("✅ " if success else "⚠ ") + msg, "INFO" if success else "ERROR")

            self.root.after(0, _apply)

        threading.Thread(target=_worker, daemon=True).start()

    def _push_billing_data(self):
        """Push only firm billing (actual fees & payouts) to the dashboard."""
        if RELEASE_DISABLE_PUSH_BILLING:
            self.log("ℹ Push Billing is disabled in this release", "WARN")
            return

        if not self._firm_billing_summary:
            self.log("⚠ No billing data collected yet — connect to prop firm dashboards first", "WARN")
            return

        dashboard_url = self.url_entry.get().strip().rstrip('/')
        email = self.client_email_entry.get().strip()

        if not self.client_info:
            messagebox.showerror("Error", "Please lookup the client first")
            return

        def _do_push():
            try:
                if self.push_billing_btn:
                    self.root.after(0, lambda: self.push_billing_btn.configure(state="disabled"))
                self.log("💰 Pushing billing data to dashboard...")

                # Match billing records to individual evaluations so
                # per-account Fee, Date Purchased, and Date Started get pushed
                import re as _re
                all_evals = [rd.get("eval") for rd in self._active_trade_rows if rd.get("eval")]
                filled_count = 0

                # Build a combined lookup from all firms' billing records
                billing_by_acct = {}
                for firm_name, summary in self._firm_billing_summary.items():
                    for rec in summary.get("records", []):
                        acct_no = (rec.get("account_no") or "").strip()
                        amount = rec.get("amount", 0)
                        bill_date = rec.get("date", "")
                        if acct_no and amount > 0:
                            billing_by_acct[acct_no] = {
                                "amount": amount,
                                "date": bill_date,
                                "firm": firm_name,
                            }

                if all_evals and billing_by_acct:
                    for ev in all_evals:
                        acct_challenge = (ev.get("Account #") or "").strip()
                        acct_funded = (ev.get("Account #.1") or "").strip()
                        existing_fee = (ev.get("Fee") or "").strip()
                        fee_filled = False
                        if existing_fee:
                            try:
                                fee_filled = float(existing_fee.replace("$", "").replace(",", "")) > 0
                            except ValueError:
                                fee_filled = existing_fee not in ("", "$0", "$0.00", "0")

                        matched = None
                        for acct_key in [acct_challenge, acct_funded]:
                            if not acct_key:
                                continue
                            if acct_key in billing_by_acct:
                                matched = billing_by_acct[acct_key]
                                break
                            for bill_acct, bill_info in billing_by_acct.items():
                                if bill_acct in acct_key or acct_key in bill_acct:
                                    matched = bill_info
                                    break
                            if matched:
                                break

                        if matched:
                            billing_fee = f"${matched['amount']:.2f}"
                            ev["Fee"] = billing_fee
                            if not (ev.get("Date Purchased") or "").strip() and matched["date"]:
                                ev["Date Purchased"] = matched["date"]
                            if not (ev.get("Date Started") or "").strip() and matched["date"]:
                                ev["Date Started"] = matched["date"]
                            filled_count += 1

                    self.root.after(0, lambda c=filled_count:
                        self.log(f"💰 Matched billing to {c} evaluation(s)"))

                payload = {
                    "email": email,
                    "firm_billing": self._firm_billing_summary,
                }
                if all_evals and filled_count > 0:
                    payload["evaluations"] = all_evals

                response = requests.post(
                    f"{dashboard_url}/api/client/push",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=30
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        firms = list(self._firm_billing_summary.keys())
                        total_fees = sum(f["total_fees"] for f in self._firm_billing_summary.values())
                        total_payouts = sum(f["total_payouts"] for f in self._firm_billing_summary.values())
                        self.root.after(0, lambda: self.log(
                            f"✅ Billing pushed — {len(firms)} firm(s): "
                            f"Fees ${total_fees:,.2f} | Payouts ${total_payouts:,.2f}"))
                    else:
                        self.root.after(0, lambda: self.log(
                            f"❌ Billing push failed: {data.get('message', 'Unknown error')}", "ERROR"))
                else:
                    self.root.after(0, lambda: self.log(
                        f"❌ Billing push HTTP {response.status_code}", "ERROR"))
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.log(f"❌ Billing push error: {err}", "ERROR"))
            finally:
                if self.push_billing_btn:
                    self.root.after(0, lambda: self.push_billing_btn.configure(state="normal"))

        threading.Thread(target=_do_push, daemon=True).start()

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

        # Prevent overlapping push workers. If a push is already running,
        # queue exactly one follow-up run so the latest state still gets sent.
        with self._push_lock:
            if self._push_in_progress:
                if not self._push_pending:
                    self._push_pending = True
                    self.log("⏳ Push already running — queued one follow-up push")
                return
            self._push_in_progress = True
        
        # Guard checks passed — disable the button and run everything in a background thread
        # so the UI stays responsive during MT5 calls and the HTTP round-trip.
        if hasattr(self, 'push_btn_live') and self.push_btn_live:
            try:
                self.push_btn_live.configure(state="disabled")
            except Exception:
                pass
        self.log(f"📤 Pushing {client_name}...")
        self.status_var.set("Pushing data...")

        def _do_push():
            should_run_follow_up = False
            try:
                self._push_data_worker(dashboard_url, email, client_name)
            finally:
                with self._push_lock:
                    self._push_in_progress = False
                    should_run_follow_up = self._push_pending
                    self._push_pending = False

                if should_run_follow_up:
                    try:
                        self.root.after(0, lambda: self.log("🔁 Running queued push"))
                        self.root.after(0, self.push_data)
                    except Exception:
                        pass
                elif hasattr(self, 'push_btn_live') and self.push_btn_live:
                    try:
                        self.root.after(0, lambda: self.push_btn_live.configure(state="normal"))
                    except Exception:
                        pass

        threading.Thread(target=_do_push, daemon=True).start()

    # Per-login cache for the 365-day farming history:
    #   { login_key: (fetched_at_epoch, [deals]) }
    # TTL is 5 minutes — auto-push fires frequently so we avoid re-scanning MT5 history
    # on every tick.  Only the last-24h slice is always fetched fresh.
    _FA_HISTORY_CACHE_TTL = 300  # seconds

    # Tradovate MNQ farming history cache: { firm_name: (fetched_at_epoch, mnq_data) }
    # Fetching fills + balance logs is slow; reuse within the same TTL window.
    _TRADOVATE_FARMING_CACHE_TTL = 300  # seconds

    def _push_data_worker(self, dashboard_url, email, client_name):
        """Heavy push work — runs on a background thread."""
        def _log(msg, level="INFO"):
            self.root.after(0, lambda m=msg, lv=level: self.log(m, lv))
        def _status(msg):
            self.root.after(0, lambda m=msg: self.status_var.set(m))

        account = self.pusher.get_account_info(include_balance_history=False)
        if not account:
            _log("⚠️ MT5 account info returned empty — pushing with no account data", "ERROR")
            account = {}
        
        # Log detailed MT5 account information
        if account:
            login = account.get('login', 'N/A')
            company = account.get('company', 'Unknown')
            server = account.get('server', 'Unknown')
            balance = account.get('balance', 0)
            equity = account.get('equity', 0)
            deposits = account.get('total_deposits', 0)
            withdrawals = account.get('total_withdrawals', 0)
            _log(f"💼 MT5 ACCOUNT INFO:")
            _log(f"   Login: {login} | Company: {company} | Server: {server}")
            _log(f"   Balance: ${balance:,.2f} | Equity: ${equity:,.2f}")
            _log(f"   Deposits: ${deposits:,.2f} | Withdrawals: ${withdrawals:,.2f}")
        
        positions = self.pusher.get_positions()
        if positions is None:
            _log("⚠️ MT5 positions returned None — sending empty list")
            positions = []

        # Always fetch the last 24 h fresh (fast — small result set).
        _today_cutoff = time.time() - 86400
        raw_deals = self.pusher.get_deals(days=1) or []

        # For farming aggregation we need long-range history for accurate Hedge Day slots.
        # Cache it per MT5 login with a 5-minute TTL so repeated auto-push calls are fast.
        _fa_history_days = 365
        _login_key = str(account.get('login', 'unknown'))
        if not hasattr(self, '_fa_history_cache'):
            self._fa_history_cache = {}

        _cached = self._fa_history_cache.get(_login_key)
        _now = time.time()

        if _cached and (_now - _cached[0]) < self._FA_HISTORY_CACHE_TTL:
            _log(f"📦 Using cached FA history ({int(_now - _cached[0])}s old)")
            _cached_deals = _cached[1]
        else:
            _log(f"📅 Fetching {_fa_history_days}-day FA history (cache miss or expired)")
            _full = self.pusher.get_deals(days=_fa_history_days) or []
            # Store only the deals older than today's cutoff to keep cache lean.
            # Strip internal transfers up-front so they can NEVER resurface from
            # the cache — guarantees the latest live MT5 state always wins and
            # no stale balance op leaks into hedge aggregates on subsequent pushes.
            _cached_deals = []
            for _d in _full:
                if _d.get('time_raw', 0) >= _today_cutoff:
                    continue
                _dt = str(_d.get('type', '')).upper()
                if _dt in ('BALANCE', 'CREDIT', '2', '3', 'CHARGE', 'CORRECTION', 'BONUS'):
                    _cl = str(_d.get('comment', '') or '').strip().lower()
                    if ('internal transfer' in _cl) or (not _cl):
                        continue
                _cached_deals.append(_d)
            self._fa_history_cache[_login_key] = (_now, _cached_deals)

        # Merge: fresh last-24h + cached history gives the full aggregation input.
        _raw_deal_ids = {d.get('ticket') for d in raw_deals}
        all_history_deals = list(raw_deals) + [d for d in _cached_deals if d.get('ticket') not in _raw_deal_ids]

        # Derive last-trading-day deals — already fetched above as raw_deals.
        # Fall back to the most-recent day if there were no deals in the last 24 h.
        if not raw_deals and all_history_deals:
            _max_ts = max(d.get('time_raw', 0) for d in all_history_deals)
            _day_start = _max_ts - 86400
            raw_deals = [d for d in all_history_deals if d.get('time_raw', 0) >= _day_start]

        # Mark history-only FA deals so the filter can skip re-parsing them.
        # Non-FA deals (CH, FD, DD) should only use last-trading-day data.
        # FA deals need the full 90-day history to correctly compute hedge day slots.
        _last_trading_day_ids = {d.get('ticket') for d in raw_deals}
        aggregation_raw_deals = []
        for _d in all_history_deals:
            c_up = str(_d.get('comment', '')).upper()
            is_fa = '_FA' in c_up
            is_history_only = _d.get('ticket') not in _raw_deal_ids
            d_type = str(_d.get('type', '')).upper()
            is_balance_op = d_type in ['BALANCE', 'CREDIT', '2', '3', 'CHARGE', 'CORRECTION', 'BONUS']
            _comment_lower = str(_d.get('comment', '') or '').strip().lower()
            is_internal_transfer = (
                'internal transfer' in _comment_lower
                or (is_balance_op and not _comment_lower)
            )

            if is_internal_transfer:
                # Internal transfers / unattributed balance ops never contribute to
                # hedge results; drop them so they cannot inflate eval values.
                continue

            if is_balance_op:
                # Keep other balance ops (deposits with comments, charges, bonuses, etc.)
                aggregation_raw_deals.append(_d)
            elif is_fa:
                # FA: only push last-trading-day deals (what to push).
                # Full history is used separately for day COUNT only (fa_day_keys_by_account below).
                if _d.get('ticket') in _last_trading_day_ids:
                    aggregation_raw_deals.append(_d)
            else:
                # CH / FD / DD: only last trading day — avoids stale/replaced deals from old resets
                if _d.get('ticket') in _last_trading_day_ids:
                    aggregation_raw_deals.append(_d)
        
        _fa_count = sum(1 for d in aggregation_raw_deals if '_FA' in str(d.get('comment', '')).upper())
        _other_count = len(aggregation_raw_deals) - _fa_count
        _log(f"📂 Deal scope: {_other_count} CH/FD/DD (last trading day) + {_fa_count} FA (last trading day only; slot# from {_fa_history_days}-day history)")

        # Pre-compute full FA trading-day counts per account from full history,
        # then use this count as the authoritative Hedge Day slot index.
        fa_day_keys_by_account = {}
        for _d in all_history_deals:
            _comment = str(_d.get('comment', '') or '')
            if '_FA' not in _comment.upper():
                continue

            _parsed = self.pusher.parse_deal_comment_v2(_comment)
            if not _parsed:
                continue
            # parse_deal_comment_v2 may return either a ParsedComment-like object
            # or a plain dict (parse_mt5_comment convenience path).
            _parsed_is_dict = isinstance(_parsed, dict)
            _is_valid = (_parsed.get('is_valid') if _parsed_is_dict else getattr(_parsed, 'is_valid', True))
            if _is_valid is False:
                continue

            _account_key = str(
                (_parsed.get('account_number') if _parsed_is_dict else getattr(_parsed, 'account_number', '')) or ''
            ).strip()
            if not _account_key:
                continue

            _day_key = ''
            _parsed_date = (_parsed.get('farming_date') if _parsed_is_dict else getattr(_parsed, 'farming_date', None))
            if _parsed_date:
                try:
                    if hasattr(_parsed_date, 'strftime'):
                        _day_key = _parsed_date.strftime('%Y-%m-%d')
                    else:
                        _day_key = str(_parsed_date)[:10]
                except Exception:
                    _day_key = str(_parsed_date)[:10]

            if not _day_key:
                _ts = _d.get('time_raw', 0)
                if isinstance(_ts, (int, float)) and _ts > 0:
                    try:
                        _day_key = datetime.fromtimestamp(_ts).strftime('%Y-%m-%d')
                    except Exception:
                        _day_key = ''

            if _day_key:
                fa_day_keys_by_account.setdefault(_account_key, set()).add(_day_key)

        fa_day_count_by_account = {
            acc: len(days)
            for acc, days in fa_day_keys_by_account.items()
            if days
        }

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

        if is_fnft:
            _24h_ago = time.time() - 86400
            if raw_deals:
                before_count = len(raw_deals)
                raw_deals = [
                    d for d in raw_deals
                    if '_CH' not in str(d.get('comment', '')).upper()
                    or d.get('time_raw', 0) >= _24h_ago
                ]
                dropped = before_count - len(raw_deals)
                if dropped:
                    _log(f"🔻 Filtered {dropped} old FNFT challenge deal(s) (>24h)")
            if aggregation_raw_deals:
                aggregation_raw_deals = [
                    d for d in aggregation_raw_deals
                    if '_CH' not in str(d.get('comment', '')).upper()
                    or d.get('time_raw', 0) >= _24h_ago
                ]
        
        # Filter deals: keep balance ops and trades with valid comments.
        # FA-history-only deals are pre-validated (added because comment has _FA) - skip re-parse.
        def _filter_valid_push_deals(source_deals, skip_fa_reparse=False):
            filtered = []
            for deal in source_deals or []:
                d_type = str(deal.get('type', '')).upper()
                if d_type in ['BALANCE', 'CREDIT', '2', '3', 'CHARGE', 'CORRECTION', 'BONUS']:
                    # Drop internal transfers — they are NOT real P&L and must
                    # never reach statistics or the dashboard. Catches both:
                    #   - explicit "internal transfer" comment (any sign)
                    #   - empty-comment balance ops (legacy untagged transfers)
                    _bal_comment_l = str(deal.get('comment', '') or '').strip().lower()
                    if ('internal transfer' in _bal_comment_l) or (not _bal_comment_l):
                        continue
                    filtered.append(deal)
                    continue

                if skip_fa_reparse and deal.get('_fa_history_only'):
                    filtered.append(deal)
                    continue

                # Also skip re-parsing for any FA-tagged deal when skip_fa_reparse=True.
                # All FA deals were pre-validated by the _FA comment check in the build loop.
                if skip_fa_reparse and '_FA' in str(deal.get('comment', '')).upper():
                    filtered.append(deal)
                    continue

                comment = deal.get('comment', '')
                parsed = self.pusher.parse_deal_comment_v2(comment)

                is_valid = False
                if parsed:
                    if hasattr(parsed, 'is_valid'):
                        is_valid = parsed.is_valid
                    else:
                        is_valid = True

                if is_valid:
                    filtered.append(deal)
            return filtered
        deals = _filter_valid_push_deals(raw_deals)
        aggregation_deals = _filter_valid_push_deals(aggregation_raw_deals, skip_fa_reparse=True)

        if len(deals) < len(raw_deals):
            _log(f"Filtered {len(raw_deals) - len(deals)} deals with invalid comments")

        statistics = self.pusher.calculate_statistics(deals)
        
        # Aggregate hedge results locally, including farming history for correct FA sloting.
        aggregated_by_comment = []
        comment_summary = {}
        latest_fa_aggregates = []
        if COMMENT_PARSER_AVAILABLE and aggregation_deals:
            aggregated_by_comment, _unmatched, _agg_log = aggregate_deals_by_position(aggregation_deals)

            # Keep open-position aggregates strictly on the current trading day.
            # This prevents stale multi-day open entries from re-triggering FA pushes.
            # "Today" is always Kenya time — see KENYA_TZ at the top of this file.
            _today_local = kenya_today()

            def _is_current_trading_day_open(agg):
                ts = agg.get('timestamp')
                if isinstance(ts, (int, float)) and ts > 0:
                    try:
                        return datetime.fromtimestamp(ts).date() == _today_local
                    except Exception:
                        pass

                farming_date = str(agg.get('farming_date') or '').strip()
                if len(farming_date) >= 10:
                    try:
                        return datetime.fromisoformat(farming_date.replace('Z', '+00:00')).date() == _today_local
                    except Exception:
                        try:
                            return datetime.strptime(farming_date[:10], '%Y-%m-%d').date() == _today_local
                        except Exception:
                            pass
                return False

            if aggregated_by_comment:
                _fresh_open_aggregates = []
                _dropped_stale_open = 0
                for agg in aggregated_by_comment:
                    if bool(agg.get('has_open_position')) and not _is_current_trading_day_open(agg):
                        _dropped_stale_open += 1
                        continue
                    _fresh_open_aggregates.append(agg)

                if _dropped_stale_open:
                    _log(f"🧹 Suppressed {_dropped_stale_open} stale open trade group(s) from prior trading days")
                aggregated_by_comment = _fresh_open_aggregates

            def _normalize_fa_day(agg):
                timestamp = agg.get('timestamp')
                if isinstance(timestamp, (int, float)) and timestamp > 0:
                    try:
                        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
                    except Exception:
                        pass
                farming_date = str(agg.get('farming_date') or '').strip()
                if len(farming_date) >= 10:
                    return farming_date[:10]
                return farming_date

            fa_by_account_day = {}
            non_fa_aggregates = []
            for agg in aggregated_by_comment:
                if agg.get('phase_code') != 'FA':
                    non_fa_aggregates.append(agg)
                    continue

                day_key = _normalize_fa_day(agg)
                account_key = str(agg.get('account_number') or '')
                merge_key = (account_key, day_key)
                existing = fa_by_account_day.get(merge_key)
                if not existing:
                    fa_by_account_day[merge_key] = dict(agg)
                    continue

                existing['net_profit'] = round(existing.get('net_profit', 0) + agg.get('net_profit', 0), 2)
                existing['deal_count'] = existing.get('deal_count', 0) + agg.get('deal_count', 0)
                if agg.get('timestamp', 0) > existing.get('timestamp', 0):
                    existing['timestamp'] = agg.get('timestamp', 0)
                    existing['farming_date'] = agg.get('farming_date')

            latest_fa_aggregates = []
            fa_accounts = {}
            for (account_key, day_key), agg in fa_by_account_day.items():
                fa_accounts.setdefault(account_key, []).append((day_key, agg))

            for account_key, entries in fa_accounts.items():
                entries.sort(key=lambda item: item[0])
                total_slots = fa_day_count_by_account.get(account_key, len(entries))
                # Push only the LATEST farming day, labelled as Hedge Day <total_slots>.
                # total_slots is derived from the full 90-day history so the slot number
                # is always correct even though we only send one entry per account.
                latest_day_key, latest_agg = entries[-1]
                tagged = dict(latest_agg)
                tagged['trade_number'] = total_slots
                tagged['_fa_slot'] = total_slots
                tagged['field_name'] = f"Hedge Day {total_slots}"
                latest_fa_aggregates.append(tagged)
                _log(f"📅 {account_key}: {total_slots} FA day(s) → pushing as Hedge Day {total_slots}")

            aggregated_by_comment = non_fa_aggregates + latest_fa_aggregates

            # Guard against false FA zero pushes when there are no active positions.
            # We still keep zero FA rows when positions are active (user-visible signal that a trade is running).
            has_active_positions = bool(positions)
            if not has_active_positions and aggregated_by_comment:
                filtered_aggregates = []
                dropped_fa_zeros = 0
                for agg in aggregated_by_comment:
                    is_fa = agg.get('phase_code') == 'FA'
                    net_profit = float(agg.get('net_profit', 0) or 0)
                    deal_count = int(agg.get('deal_count', 0) or 0)
                    has_open_position = bool(agg.get('has_open_position'))
                    if is_fa and abs(net_profit) < 1e-9 and deal_count <= 1 and not has_open_position:
                        dropped_fa_zeros += 1
                        continue
                    filtered_aggregates.append(agg)
                if dropped_fa_zeros:
                    _log(f"🧹 Suppressed {dropped_fa_zeros} stale FA zero row(s) (no open FA trade)")
                aggregated_by_comment = filtered_aggregates

            by_phase = {}
            for agg in aggregated_by_comment:
                phase_name = agg.get('phase_name', 'UNKNOWN')
                if phase_name not in by_phase:
                    by_phase[phase_name] = {'count': 0, 'total_net_profit': 0.0}
                by_phase[phase_name]['count'] += 1
                by_phase[phase_name]['total_net_profit'] += agg.get('net_profit', 0)
            comment_summary = {'by_phase': by_phase}

        # Collect Tradovate MNQ daily P&L for Prop Day values.
        # ONLY runs if at least one Tradovate account is actively connected.
        # Cache-miss fetches are done in a background thread so they never add
        # to push wall-time — the result is available for the NEXT push.
        tradovate_farming_days = []
        if not hasattr(self, '_tradovate_farming_cache'):
            self._tradovate_farming_cache = {}
        _tv_now = time.time()

        # Find all connected Tradovate accounts (account object must be present).
        _connected_tv = [
            (firm_name, conn.get("account"))
            for firm_name, conn in self._broker_connections.items()
            if conn.get("account") and hasattr(conn.get("account"), 'get_mnq_daily_pnl')
        ]

        if not _connected_tv:
            if latest_fa_aggregates:
                _log("⚠️ Tradovate not connected — Prop Day values will not be updated", "WARN")
        else:
            for firm_name, tv_account in _connected_tv:
                _tv_cached = self._tradovate_farming_cache.get(firm_name)
                if _tv_cached and (_tv_now - _tv_cached[0]) < self._TRADOVATE_FARMING_CACHE_TTL:
                    # Cache hit — instant, no API call.
                    mnq_data = _tv_cached[1]
                    if mnq_data:
                        total_days = sum(len(a.get('mnq_daily_pnl', [])) for a in mnq_data)
                        _log(f"🌾 {firm_name}: {total_days} Prop Day(s) ready (cached)")
                    tradovate_farming_days.extend(mnq_data)
                else:
                    # Cache miss — use whatever we have now (empty on first push),
                    # and refresh asynchronously so the NEXT push benefits.
                    existing = (_tv_cached[1] if _tv_cached else []) or []
                    if existing:
                        total_days = sum(len(a.get('mnq_daily_pnl', [])) for a in existing)
                        _log(f"🌾 {firm_name}: {total_days} Prop Day(s) from stale cache (refreshing in background)")
                        tradovate_farming_days.extend(existing)
                    else:
                        _log(f"🌾 {firm_name}: fetching Tradovate history in background (available next push)")

                    def _refresh_tv_cache(fn=firm_name, acc=tv_account):
                        try:
                            data = acc.get_mnq_daily_pnl() or []
                            self._tradovate_farming_cache[fn] = (time.time(), data)
                        except Exception as _e:
                            pass  # silently swallow; no-op on next push miss
                    threading.Thread(target=_refresh_tv_cache, daemon=True).start()

            # Cross-check: log Prop Day coverage vs Hedge Day coverage.
            if latest_fa_aggregates and tradovate_farming_days:
                for fa_agg in latest_fa_aggregates:
                    acc_key = str(fa_agg.get('account_number') or '')
                    hedge_slot = fa_agg.get('_fa_slot', '?')
                    acc_digits = [d for d in re.findall(r'\d+', acc_key.upper()) if len(d) >= 4]
                    for tv_data in tradovate_farming_days:
                        tv_name = (tv_data.get('account_name') or '').upper()
                        if acc_key.upper() in tv_name or any(d in tv_name for d in acc_digits):
                            prop_count = len(tv_data.get('mnq_daily_pnl', []))
                            _log(f"📊 {acc_key}: Hedge Day {hedge_slot} ↔ {prop_count} Prop Day(s)")
                            break

        # Pre-push diagnostic: log what we're about to send
        pos_count = len(positions) if positions else 0
        deal_count = len(deals) if deals else 0
        agg_count = len(aggregated_by_comment) if aggregated_by_comment else 0
        bal = account.get('balance', 0)
        _log(f"📦 Payload: Bal=${bal:,.0f} | {deal_count} deals | {pos_count} pos | {agg_count} hedge groups")
        
        # Detailed per-row logging of what's being pushed
        if aggregated_by_comment:
            _log(f"\n📋 INDIVIDUAL ROWS BEING PUSHED:")
            _log(f"{'='*80}")
            
            # Group by account for summary
            by_account = {}
            by_phase = {}
            
            for i, agg in enumerate(aggregated_by_comment):
                account_num = agg.get('account_number', 'Unknown')
                phase_code = agg.get('phase_code', 'UNKNOWN')
                phase_name = agg.get('phase_name', 'Unknown')
                trade_num = agg.get('trade_number', 0)
                net_profit = agg.get('net_profit', 0)
                deal_cnt = agg.get('deal_count', 1)
                field_name = agg.get('field_name', '?')
                
                # Track per account
                if account_num not in by_account:
                    by_account[account_num] = {'rows': [], 'total_profit': 0, 'total_deals': 0}
                by_account[account_num]['rows'].append({
                    'phase': f"{phase_code}{trade_num}",
                    'profit': net_profit,
                    'deals': deal_cnt,
                    'field': field_name
                })
                by_account[account_num]['total_profit'] += net_profit
                by_account[account_num]['total_deals'] += deal_cnt
                
                # Track per phase
                if phase_code not in by_phase:
                    by_phase[phase_code] = {'count': 0, 'total_profit': 0}
                by_phase[phase_code]['count'] += 1
                by_phase[phase_code]['total_profit'] += net_profit
                
                # Log individual row
                farming_date = agg.get('farming_date', '')
                date_str = f" ({farming_date})" if farming_date else ""
                _log(f"   [{i+1:2d}] {account_num}_{phase_code}{trade_num} → {field_name:20s} = ${net_profit:>10.2f}  ({deal_cnt} deal{'s' if deal_cnt != 1 else ''}){date_str}")
            
            _log(f"{'='*80}")
            _log(f"\n📊 SUMMARY BY ACCOUNT:")
            for account_num in sorted(by_account.keys()):
                data = by_account[account_num]
                row_count = len(data['rows'])
                total_p = data['total_profit']
                total_d = data['total_deals']
                phases = ', '.join(r['phase'] for r in data['rows'])
                _log(f"   {account_num:20s} | {row_count:2d} row(s) | Phases: {phases:30s} | Total: ${total_p:>10.2f} ({total_d} deals)")
            
            _log(f"\n📈 SUMMARY BY PHASE:")
            for phase_code in sorted(by_phase.keys()):
                data = by_phase[phase_code]
                phase_names = {'CH': 'Challenge', 'FD': 'Funded', 'DD': 'DoubleDip', 'FA': 'Farming'}
                phase_name = phase_names.get(phase_code, phase_code)
                _log(f"   {phase_name:15s} ({phase_code}) | {data['count']:2d} group(s) | Total: ${data['total_profit']:>10.2f}")
        
        payload = {
            "email": email,
            "account": account,
            "positions": positions,
            "deals": deals,
            "statistics": statistics,
            "evaluations": [],
            "aggregated_by_comment": aggregated_by_comment,
            "prefer_client_aggregation": True,
            "comment_summary": comment_summary,
            "dropdown_options": {},
            "firm_billing": self._firm_billing_summary if self._firm_billing_summary else None,
        }

        # Only include Tradovate prop day data if we actually have it.
        # Omitting the key entirely means the server will never touch existing Prop Day values.
        if tradovate_farming_days:
            payload["tradovate_farming_days"] = tradovate_farming_days
        
        try:
            # Use public endpoint - no API key needed
            response = _gzip_post(
                f"{dashboard_url}/api/client/push",
                payload,
                timeout=120
            )
            
            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError:
                    _log("❌ Server returned invalid JSON (not JSON response)", "ERROR")
                    _status("Push failed - bad response")
                    return
                if data.get("status") == "success":
                    bal = account.get('balance', 0)
                    dep = account.get('total_deposits', 0)
                    hedge_log = data.get("hedge_match_log", [])
                    hedge_updates = data.get("hedge_updates", 0)
                    _log(f"\n✅ PUSH SUCCESSFUL → Bal: ${bal:,.0f} | Dep: ${dep:,.0f} | {len(deals)} deals | {pos_count} pos | {agg_count} hedge groups")
                    
                    # Log detailed response from server showing what was processed
                    _log(f"\n📥 SERVER PROCESSING LOG ({len(hedge_log)} entries):")
                    _log(f"{'='*80}")
                    for i, entry in enumerate(hedge_log, 1):
                        # Highlight different types of entries
                        if entry.startswith("✅"):
                            _log(f"   {entry}", "INFO")
                        elif entry.startswith("⚠️") or entry.startswith("❌"):
                            _log(f"   {entry}", "WARN")
                        elif entry.startswith("📊") or entry.startswith("📅") or entry.startswith("🌾"):
                            _log(f"   {entry}", "INFO")
                        else:
                            _log(f"   {entry}", "INFO")
                    _log(f"{'='*80}")
                    
                    if hedge_updates:
                        _log(f"\n✨ CONFIRMED: {hedge_updates} hedge cell(s) updated and saved on dashboard")
                    elif agg_count:
                        _log("\n⚠️ Server acknowledged push but returned 0 hedge updates. Check account-number matching and active dashboard row filters.", "WARN")
                    else:
                        _log("\n📭 No hedge aggregates in this push (MT5 data only)")
                    
                    _status("Ready - Data pushed!")
                    try:
                        self.root.after(0, lambda hu=hedge_updates: self._stat_push_var.set(f"Push: ✔ {hu}"))
                    except Exception:
                        pass
                else:
                    _log(f"❌ {data.get('message', 'Push failed')}", "ERROR")
                    _status("Push failed")
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_msg = response.json().get("message", error_msg)
                except Exception:
                    pass
                _log(f"❌ Push failed: {error_msg}", "ERROR")
                _status("Push failed")

        except requests.exceptions.Timeout:
            _log("❌ Push timeout — server did not respond within 120s", "ERROR")
            _status("Push failed - timeout")
        except requests.exceptions.ConnectionError:
            _log("❌ Push failed — cannot connect to server", "ERROR")
            _status("Push failed - no connection")
        except Exception as e:
            _log(f"❌ Push error: {e}", "ERROR")
            _status("Push failed")

        # Run hedging review in the background — uses account data already in hand, no second MT5 call.
        try:
            threading.Thread(
                target=self._push_hedging_review_worker,
                args=(dashboard_url, email, account),
                daemon=True
            ).start()
        except Exception as hr_err:
            _log(f"⚠️ Hedging review thread failed to start: {hr_err}", "ERROR")

    def push_hedging_review(self):
        """Push hedging review data — called from toolbar button (fetches own account info)."""
        dashboard_url = self.url_entry.get().strip().rstrip('/')
        email = self.client_email_entry.get().strip()

        if not self.client_info:
            messagebox.showerror("Error", "Please lookup the client first by entering email and clicking 'Lookup'")
            return

        if not self.pusher.connected:
            messagebox.showerror("Error", "Please connect to MT5 first")
            return

        self.status_var.set("Pushing hedging review...")
        account = self.pusher.get_account_info(include_balance_history=True)
        if not account:
            self.log("⚠️ Hedging review skipped — MT5 account info is empty", "ERROR")
            self.status_var.set("Hedging review skipped")
            return

        threading.Thread(
            target=self._push_hedging_review_worker,
            args=(dashboard_url, email, account),
            daemon=True
        ).start()

    def _push_hedging_review_worker(self, dashboard_url, email, account):
        """Send hedging review payload — refreshes account totals in the background if needed."""
        def _log(msg, level="INFO"):
            self.root.after(0, lambda m=msg, lv=level: self.log(m, lv))
        def _status(msg):
            self.root.after(0, lambda m=msg: self.status_var.set(m))

        if self.pusher.connected:
            try:
                account = self.pusher.get_account_info(include_balance_history=True) or account
            except Exception:
                pass

        deposits = float(account.get('total_deposits', 0) or 0)
        withdrawals = float(account.get('total_withdrawals', 0) or 0)
        balance = float(account.get('balance', 0) or 0)

        _log(f"📊 HR payload: Dep=${deposits:,.0f} | Wth=${withdrawals:,.0f} | Bal=${balance:,.0f}")

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
                    _log("❌ Hedging review: server returned invalid JSON", "ERROR")
                    _status("HR failed - bad response")
                    return
                if data.get("status") == "success":
                    hr = data.get("hedging_review") or {}
                    actual = hr.get('actual_hedging_results', 0)
                    disc = hr.get('discrepancy', 0)
                    _log(f"✅ Hedging Review → Dep: ${deposits:,.0f} | Wth: ${withdrawals:,.0f} | Actual: ${actual:,.2f} | Disc: ${disc:,.2f}")
                    _status("Ready - Hedging review pushed!")
                else:
                    _log(f"❌ {data.get('message', 'Push failed')}", "ERROR")
                    _status("Push failed")
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_msg = response.json().get("message", error_msg)
                except Exception:
                    pass
                _log(f"❌ Push failed: {error_msg}", "ERROR")
                _status("Push failed")

        except requests.exceptions.Timeout:
            _log("❌ Hedging review timeout", "ERROR")
            _status("HR timeout")
        except requests.exceptions.ConnectionError:
            _log("❌ Hedging review — cannot connect", "ERROR")
            _status("HR connection failed")
        except Exception as e:
            _log(f"❌ Hedging review error: {e}", "ERROR")
            _status("Push failed")

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
            response = _gzip_post(
                f"{dashboard_url}/api/client/push",
                payload,
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
            response = _gzip_post(
                f"{dashboard_url}/api/client/push",
                payload,
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
            self.log("   Please ensure mt5_comment_parser.py is in the TradeOpssAI folder")
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
            response = _gzip_post(
                f"{dashboard_url}/api/client/push",
                payload,
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
        "TopStep RTP": "TopStep RTP",
        "TopStep_RTP": "TopStep RTP",
        "TradeDay": "TradeDay",
        "Tradeify": "Tradeify",
        "Alpha Futures": "AlphaFutures",
        "Apex": "Apex",
        "Top One Futures": "Top One Futures",
    }

    def _resolve_firm_code(self, prop_firm_name, default="MFFU_Flex"):
        """Resolve a dashboard 'Prop Firm' label to a blueprint firm code.

        Robust against the casing/format the dashboard actually emits
        (e.g. dropdown value is 'Topstep', not 'TopStep'; RTP may arrive as
        'TopStep RTP' / 'TopStep_RTP' / 'TopstepRTP' / 'topstep rtp').

        Critically, a TopStep-family label NEVER silently collapses to the
        MFFU_Flex fallback: an RTP account always resolves to the
        'TopStep RTP' blueprint and a plain TopStep account to 'TopStep'.
        """
        name = (str(prop_firm_name).strip() if prop_firm_name is not None else "")
        if not name:
            return default

        # 1. Exact map hit.
        if name in self._FIRM_MAP:
            return self._FIRM_MAP[name]

        # 2. Case/format-insensitive match against the map keys.
        norm = name.lower().replace("_", " ").replace("-", " ").strip()
        for k, v in self._FIRM_MAP.items():
            if k.lower().replace("_", " ").replace("-", " ").strip() == norm:
                return v

        # 3. Direct blueprint key (exact, then case-insensitive).
        bps = getattr(self.prop_firm_mgr, "firm_blueprints", {}) if self.prop_firm_mgr else {}
        if name in bps:
            return name
        for bk in bps:
            if bk.lower() == name.lower():
                return bk

        # 4. TopStep family — distinguish RTP by substring so it can never
        #    fall through to the generic default. 'topsteprtp' (no spaces)
        #    contains both tokens, so RTP is detected before plain TopStep.
        compact = norm.replace(" ", "")
        if "topstep" in compact:
            return "TopStep RTP" if "rtp" in compact else "TopStep"
        if "rtp" in compact:               # bare 'RTP' label → TopStep RTP
            return "TopStep RTP"

        # 5. Other known families by substring (defensive).
        if "mffu" in norm or "my funded futures" in norm:
            return "MFFU_Flex"
        if "fundednext" in compact or "funded next" in norm:
            return "Funded Next"

        return default

    _FAILED_STATUSES = {"fail", "failed", "breach", "delete", "deleted", "closed", "sl", "ended", "lost"}

    # Keywords for substring matching (catches "Fail", "Failed", "Breached", etc.)
    _INACTIVE_KEYWORDS = ("fail", "breach", "delete", "closed", "sl", "ended", "lost")

    # ── Funded-phase starting balance map ─────────────────────────────
    # Some prop firms reset the funded balance to a value that differs from
    # the challenge "Account Size".  Without this, current-profit math is wrong
    # by tens of thousands of dollars and TP/SL adjustment goes haywire
    # (e.g. MFFU funded balance starts at $0 — using $50K as start makes the
    # adjuster think we are -$50K down and inflates TP ~15× to "recover").
    #
    # Convention:
    #   - "ZERO"      → funded balance literally starts at $0
    #   - "ACCOUNT_SIZE" (default) → starts at the challenge size (e.g. $50K)
    _FUNDED_START_BALANCE_MODE: Dict[str, str] = {
        "MFFU":             "ZERO",
        "MFFU_Flex":        "ZERO",
        "TopStep":          "ZERO",  # TopStep funded accounts also start at $0
        "TopStep RTP":      "ZERO",  # Same TopStep account family — funded starts at $0
        "Funded Next":      "ACCOUNT_SIZE",
        "FundingTicks":     "ACCOUNT_SIZE",
        "TradeDay":         "ACCOUNT_SIZE",
        "Tradeify":         "ACCOUNT_SIZE",
        "AlphaFutures":     "ACCOUNT_SIZE",
        "Apex":             "ACCOUNT_SIZE",
        "Lucid":            "ACCOUNT_SIZE",
        "Top One Futures":  "ACCOUNT_SIZE",
    }

    def _resolve_starting_balance(self, ev, current_phase, acct_size):
        """Return the firm-correct starting balance for profit math.

        For Funded / Payout phases on firms whose funded balance starts at $0
        (MFFU family), this returns 0 instead of the challenge size.  All other
        firms / phases fall back to the challenge size parsed from acct_size.
        """
        # Parse acct_size as the default
        start_str = str(acct_size or '').replace("$", "").replace(",", "").strip().lower()
        if start_str.endswith("k"):
            try:
                default_start = float(start_str[:-1]) * 1000
            except ValueError:
                default_start = 50000.0
        elif start_str.replace(".", "").isdigit():
            default_start = float(start_str)
        else:
            default_start = 50000.0

        # Only Funded / Payout / Double Dip phases differ from challenge size
        funded_phases = ("Funded", "Payout 1", "Payout 2", "Payout 3", "Payout 4", "Double Dip")
        if current_phase not in funded_phases:
            return default_start

        firm_raw = (ev or {}).get("Prop Firm", "") if isinstance(ev, dict) else ""
        canonical = self._FIRM_MAP.get(firm_raw, firm_raw)
        mode = self._FUNDED_START_BALANCE_MODE.get(canonical, "ACCOUNT_SIZE")
        if mode == "ZERO":
            return 0.0
        return default_start

    def _detect_eval_phase(self, ev):
        """Determine current phase display name and blueprint key for an evaluation."""
        challenge_status = (ev.get("Status P1", "") or "").strip().lower()
        funded_status = (ev.get("Status", "") or "").strip().lower()
        has_funded_acct = bool((ev.get("Account #.1", "") or "").strip())

        # Check if farming data exists — must have BOTH the farming marker
        # AND actual Hedge Day cell data for THIS account (not just sheet columns)
        has_farming_marker = bool((ev.get("Prop Day 1", "") or "").strip())
        has_hedge_day_data = False
        if has_farming_marker:
            for i in range(1, 35):
                val = (ev.get(f"Hedge Day {i}", "") or "").strip()
                if val and val not in ("—", "-"):
                    has_hedge_day_data = True
                    break

        if has_farming_marker and has_hedge_day_data:
            return "Farming", "farming"
        elif has_funded_acct and funded_status not in self._FAILED_STATUSES:
            return "Funded", "funded_trade1"
        else:
            return "Challenge", "challenge_trade1"

    def _resolve_phase_key_from_day(self, ev, firm_code, current_phase):
        """Use the day placeholder cell index to determine the correct blueprint key.

        The day placeholder position (0-based) maps directly to the trade order
        in _PHASE_TRADE_ORDER.  E.g. cell index 2 → third trade in the sequence.

        Scans all field sets if the detected phase has no day placeholder,
        and corrects the phase accordingly.

        Returns (resolved_phase_key, day_index, day_name) or (None, None, None)
        if no day placeholder is found.
        """
        day_idx, day_name, is_today, matched_phase = self._find_tradeable_day_cell(ev, current_phase)
        if day_idx is None:
            return None, None, None

        # If day was found in a different phase's fields, correct the phase
        effective_phase = matched_phase if matched_phase else current_phase
        if matched_phase and matched_phase != current_phase:
            self.log(f"📅 Phase correction: detected '{current_phase}' but day "
                     f"placeholder found in '{matched_phase}' fields")

        if not self.prop_firm_mgr:
            return None, day_idx, day_name

        # Normalize phase for _PHASE_TRADE_ORDER lookup
        phase_map = {"Challenge": "Challenge", "Funded": "Funded",
                     "Farming": "Farming", "Double Dip": "Double Dip",
                     "Payout 1": "Funded", "Payout 2": "Funded",
                     "Payout 3": "Funded", "Payout 4": "Funded"}
        phase_group = phase_map.get(effective_phase, effective_phase)

        firm_orders = self.prop_firm_mgr._PHASE_TRADE_ORDER.get(firm_code, {})
        trade_keys = firm_orders.get(phase_group, [])

        if not trade_keys:
            return None, day_idx, day_name

        # Clamp day index to available trade keys
        key_idx = min(day_idx, len(trade_keys) - 1)
        resolved_key = trade_keys[key_idx]
        return resolved_key, day_idx, day_name

    # Day-name abbreviations that traders use as placeholders
    _DAY_ABBREVS = {
        "mon": 0, "monday": 0,
        "tue": 1, "tues": 1, "tuesday": 1,
        "wed": 2, "weds": 2, "wednesday": 2,
        "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
        "fri": 4, "friday": 4,
        "sat": 5, "saturday": 5,
        "sun": 6, "sunday": 6,
    }

    @classmethod
    def _parse_day_token(cls, value):
        """Extract a weekday number (0=Mon..6=Sun) from a cell value.

        Lenient parsing that handles surrounding punctuation, extra text,
        and embedded day names (e.g. ``"MONDAY ✓"``, ``"Mon-04/27"``,
        ``"Mon - waiting"``).  Returns the weekday number or ``None``.
        """
        if value is None:
            return None
        try:
            s = str(value).strip().lower()
        except Exception:
            return None
        if not s:
            return None
        # Whole-string match first
        if s in cls._DAY_ABBREVS:
            return cls._DAY_ABBREVS[s]
        # Tokenise on common separators (whitespace, hyphen, slash, comma, colon)
        import re as _re
        for tok in _re.split(r"[\s\-/,:;\.]+", s):
            tok = tok.strip()
            if tok in cls._DAY_ABBREVS:
                return cls._DAY_ABBREVS[tok]
        return None

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

    # All possible field sets for day placeholder scanning (phase → fields)
    _ALL_PHASE_FIELD_SETS = [
        ("Challenge",  [f"Hedge Result {i}" for i in range(1, 6)]),
        ("Funded",     [f"Hedge Result {i}.1" for i in range(1, 8)]),
        ("Farming",    [f"Hedge Day {i}" for i in range(1, 35)]),
    ]

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
            elif self._parse_day_token(val_str) is not None:
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
        """Find the next cell to trade based on day-name placeholders.

        A cell with a day-name placeholder (MON / TUE / WED / ...) means the
        trader has queued a trade for that cell and it has not yet been
        executed.  We treat the presence of a placeholder as the primary
        signal — the weekday-vs-today comparison is only used to **prefer**
        one cell over another when multiple placeholders exist, never to
        reject a placeholder outright.

        Preference order, highest first:
          1. cell whose day name == today's weekday  (today's trade)
          2. cell whose day name is a previous weekday this week
             (most-recent past first — "missed day, do it now")
          3. cell whose day name is a future weekday this week
             (closest future first — covers stale placeholders from a
             previous week that look future-of-this-week)

        Why rule 3 exists: a placeholder cell only shows a weekday name,
        not an absolute date.  ``WEDNESDAY`` on a Monday could mean either
        "next Wednesday, prepared in advance" or "last Wednesday, never
        traded".  Refusing to trade rule-3 cells used to be the source of
        the auto-trade bug where stale placeholders looked like future
        ones.  Picking the most-imminent future day mirrors the trader's
        usual intent: take the next queued trade.

        Scans the detected phase's fields first.  If nothing found, falls
        back to scanning ALL other phase field sets so a misdetected
        phase doesn't block trading.

        Returns (stage_index, day_name, is_today, matched_phase) or
        (None, None, False, None) when no day-name placeholder exists.
        """
        # Kenya time (EAT, UTC+3) — independent of the host clock.
        today_weekday = kenya_today().weekday()  # 0=Mon .. 6=Sun

        # Build ordered list: detected phase first, then all others as fallback
        primary_fields = self._get_phase_fields(current_phase)
        search_order = [(current_phase, primary_fields)]
        for phase_name, field_list in self._ALL_PHASE_FIELD_SETS:
            if field_list != primary_fields:
                search_order.append((phase_name, field_list))

        for phase_name, fields in search_order:
            best_past = None     # (index, name, day_num) — most-recent past
            best_future = None   # (index, name, day_num) — earliest future

            for i, f in enumerate(fields):
                val = ev.get(f, None)
                if val is None:
                    continue
                day_num = self._parse_day_token(val)
                if day_num is None:
                    continue  # not a day placeholder

                if day_num == today_weekday:
                    # Today's cell — return immediately, highest priority.
                    return i, str(val).strip().upper(), True, phase_name
                elif day_num < today_weekday:
                    # Past weekday — prefer the MOST recent one.
                    if best_past is None or day_num > best_past[2]:
                        best_past = (i, str(val).strip().upper(), day_num)
                else:
                    # Future weekday — prefer the EARLIEST upcoming one.
                    if best_future is None or day_num < best_future[2]:
                        best_future = (i, str(val).strip().upper(), day_num)

            # Within this phase, prefer past over future.  Only fall through
            # to the next phase if NEITHER kind of placeholder was found.
            if best_past is not None:
                return best_past[0], best_past[1], False, phase_name
            if best_future is not None:
                return best_future[0], best_future[1], False, phase_name

        return None, None, False, None

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
        fields = self._get_phase_fields(current_phase)
        stages = prediction.get("stages", []) if prediction else []

        # ── Primary gate: day placeholder ──
        day_idx, day_name, is_today, matched_phase = self._find_tradeable_day_cell(ev, current_phase)

        if day_idx is None:
            # No day placeholder for today or any missed day → don't trade
            # Check if there's a future day placeholder across ALL field sets
            future_days = []
            # Kenya time, not host local time.
            today_wd = kenya_today().weekday()
            all_fields = []
            for _, flist in self._ALL_PHASE_FIELD_SETS:
                all_fields.extend(flist)
            for i, f in enumerate(all_fields):
                val = ev.get(f, None)
                if val is None:
                    continue
                dn = self._parse_day_token(val)
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
                    # Firm-aware starting balance.  Critical for MFFU funded
                    # accounts which start at $0 — using $50K here would make
                    # the TP adjuster think we are -$50K down and inflate TP.
                    starting = self._resolve_starting_balance(ev, current_phase, acct_size)
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

    def _find_day_field_name(self, ev, current_phase):
        """Return the eval field key holding the next tradeable day-name
        placeholder, or None if there isn't one.

        Used so that after a trade lands we can clear the exact cell whose
        MON/TUE/WED placeholder triggered the trade. Mirrors the cell-finder
        logic in _resolve_phase_key_from_day so we always target the same cell.
        """
        try:
            day_idx, _day_name, _is_today, matched_phase = self._find_tradeable_day_cell(ev, current_phase)
            if day_idx is None:
                return None
            effective_phase = matched_phase or current_phase
            phase_to_fields = {ph: flist for ph, flist in self._ALL_PHASE_FIELD_SETS}
            if effective_phase == "Challenge":
                fields = phase_to_fields.get("Challenge", [])
            elif effective_phase in ("Funded", "Payout 1", "Payout 2", "Payout 3", "Payout 4", "Double Dip"):
                fields = phase_to_fields.get("Funded", [])
            elif effective_phase == "Farming":
                fields = phase_to_fields.get("Farming", [])
            else:
                fields = []
            if 0 <= day_idx < len(fields):
                return fields[day_idx]
        except Exception:
            pass
        return None

    def _mark_day_cell_traded_on_dashboard(self, acct_num, field_name):
        """Replace the day-name placeholder cell with "$0.00" on the dashboard.

        Called after a Tradovate or TopStepX order lands. Writing "$0.00" rather
        than blanking the cell is deliberate: the cell-finder treats a real
        value (non-empty, non-day-token) as a completed trade, so the next scan
        will skip this cell and the trade cannot be re-fired.

        The cell is only overwritten when it still holds a day-name token —
        never when it already contains a real P&L result. Best-effort: never
        raises so a push failure can't block the trade flow.
        """
        if not field_name or not acct_num:
            return False
        try:
            email = self.client_email_entry.get().strip()
            dashboard_url = self.url_entry.get().strip().rstrip('/')
            if not email or not dashboard_url:
                return False

            r = requests.post(
                f"{dashboard_url}/api/client/data",
                json={"email": email},
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if r.status_code != 200:
                return False
            data = r.json()
            evaluations = data.get("evaluations", []) or []

            acct_lower = str(acct_num).strip().lower()
            touched = 0
            for ev in evaluations:
                if ev.get("_deleted"):
                    continue
                a1 = (ev.get("Account #.1") or "").strip().lower()
                a0 = (ev.get("Account #") or "").strip().lower()
                if acct_lower not in (a1, a0):
                    continue
                cur = str(ev.get(field_name, "") or "").strip()
                # Only mark cells that still hold a day-name token. Skip empty
                # cells and skip cells that already contain a real value.
                if self._parse_day_token(cur) is None:
                    continue
                ev[field_name] = "$0.00"
                touched += 1

            if touched == 0:
                return False

            payload = {
                "email": email,
                "evaluations": evaluations,
                "statistics": {},
                "dropdown_options": {},
                "force_fields": [field_name],
            }
            resp = requests.post(
                f"{dashboard_url}/api/client/push",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            ok = resp.status_code == 200
            try:
                ok = ok and resp.json().get("status") == "success"
            except Exception:
                pass
            if ok:
                self.root.after(0, lambda an=acct_num, f=field_name:
                    self.log(f"🗓 Day cell marked $0.00 on dashboard: {an} / {f}"))
            else:
                self.root.after(0, lambda an=acct_num, f=field_name:
                    self.log(f"⚠ Day-cell mark push rejected: {an} / {f}", "WARN"))
            return ok
        except Exception as e:
            try:
                self.root.after(0, lambda err=str(e):
                    self.log(f"⚠ Day-cell mark error: {err}", "WARN"))
            except Exception:
                pass
            return False

    def _refresh_eval_for_account(self, acct_num):
        """Fetch fresh eval data from dashboard for a specific account.

        Returns the updated eval dict, or None if fetch fails.
        When duplicate rows exist for the same account, prefers the active one.
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
            best = None
            for ev in data.get("evaluations", []):
                if ev.get("_deleted"):
                    continue
                acct1 = (ev.get("Account #.1", "") or ev.get("Account #", "") or "").strip()
                acct0 = (ev.get("Account #", "") or "").strip()
                if acct_num in (acct1, acct0):
                    is_active = ev.get("_is_active", self._is_eval_active(ev))
                    if is_active:
                        return ev  # Active match — return immediately
                    if best is None:
                        best = ev  # Keep first inactive as fallback
            return best
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

                # Status poll can be slow and touches Tradovate; defer so trade rows render first
                if not RELEASE_DISABLE_STATUS_POLL:
                    def _delayed_poll():
                        def _run():
                            try:
                                self._poll_tradovate_balances()
                            except Exception:
                                pass
                        threading.Thread(target=_run, daemon=True).start()
                    self.root.after(600, _delayed_poll)

                # Auto-launch browsers for prop firms that need dashboard monitoring
                active_firms = list(dict.fromkeys(
                    f for f in (
                        (str(ev.get("Prop Firm")).strip() if ev.get("Prop Firm") is not None else "")
                        for ev in active_evals
                    ) if f
                ))
                if not RELEASE_DISABLE_PROP_DASHBOARD_ACCESS:
                    self.root.after(2000, lambda af=active_firms: self._auto_launch_propfirm_browsers(af))

                # Auto-fill MT5 credentials from TradeOps dashboard.
                # Prefer Hedge Accounts Configuration rows (what users actually edit in the UI),
                # then fall back to legacy mt5_credentials if present.
                mt5_login = ""
                mt5_pass = ""
                mt5_server = ""

                hedge_accounts = data.get("hedge_accounts") or []
                client_name = ((data.get("identity") or {}).get("client") or "").strip().lower()
                chosen_hedge = None
                for hedge in hedge_accounts:
                    if str(hedge.get("platform") or "").strip().upper() != "MT5":
                        continue
                    if not ((hedge.get("login") or "").strip() and (hedge.get("password") or "").strip() and (hedge.get("server") or "").strip()):
                        continue
                    hedge_name = str(hedge.get("name") or "").strip().lower()
                    if client_name and hedge_name == client_name:
                        chosen_hedge = hedge
                        break
                    if chosen_hedge is None:
                        chosen_hedge = hedge

                if chosen_hedge:
                    mt5_login = (chosen_hedge.get("login") or "").strip()
                    mt5_pass = (chosen_hedge.get("password") or "").strip()
                    mt5_server = (chosen_hedge.get("server") or "").strip()
                else:
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
                        self.log("🔗 MT5 credentials auto-filled from TradeOps dashboard")
                        # Now that creds are loaded, connect automatically so the
                        # button shows "Disconnect MT5" without a manual click.
                        self._auto_connect_mt5()
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
        # JSON often has "Prop Firm": null — ev.get("Prop Firm", "Unknown") is still None;
        # normalize so bias + row rendering never crash mid-loop.
        firms_seen = set()
        for ev in evaluations:
            pf = ev.get("Prop Firm")
            nm = str(pf).strip() if pf is not None else ""
            firms_seen.add(nm or "Unknown")
        firm_bias = self._get_daily_bias(firms_seen)
        # Store for auto-trade compatibility
        self._auto_trade_firm_sides = firm_bias

        # Log bias
        bias_parts = []
        for f, s in sorted(firm_bias.items()):
            arrow = "▲" if s == "buy" else "▼"
            bias_parts.append(f"{arrow} {f}: {s.upper()}")
        self.log(f"Direction bias: {', '.join(bias_parts)}")
        self.log(f"Rendering {len(evaluations)} active trade row(s)…")

        for idx, ev in enumerate(evaluations):
            try:
                pf_raw = ev.get("Prop Firm")
                prop_firm_name = (str(pf_raw).strip() if pf_raw is not None else "") or "Unknown"
                firm_code = self._resolve_firm_code(prop_firm_name)
                acct_num = (ev.get("Account #.1", "") or ev.get("Account #", "") or "—").strip()
                sz_raw = ev.get("Account Size", "—")
                acct_size = (str(sz_raw).strip() if sz_raw is not None else "") or "—"
                current_display, phase_key = self._detect_eval_phase(ev)
                current_display = str(current_display or "Challenge")

                # Resolve phase_key from day placeholder (primary source of truth)
                resolved_key, _di, _dn = self._resolve_phase_key_from_day(ev, firm_code, current_display)
                if resolved_key:
                    phase_key = resolved_key

                next_display = self._get_next_phase(firm_code, current_display)
                next_display = str(next_display or "—")

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
            except Exception as row_err:
                acct_guess = (ev.get("Account #.1") or ev.get("Account #") or "?")
                self.log(f"⚠ Skipped active row (render error) acct={acct_guess}: {row_err}", "WARN")

        count = len(self._active_trade_rows)
        self.trades_count_var.set(f"[ {count} ]")
        # Update stats strip
        try:
            self._stat_queue_var.set(f"Queue: {count}")
        except Exception:
            pass
        self.log(f"Loaded {count} active trades from dashboard")
        # Ensure scrollable area expands after many rows (CTk canvas scrollregion)
        try:
            canvas = getattr(self._trades_scroll, "_parent_canvas", None)
            if canvas:
                self.root.update_idletasks()
                canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            pass

        if self.hedge_mode_var.get() == "Hedging":
            self.root.after(400, self._refresh_mt5_margin_after_scan)

    def _get_mt5_free_margin(self):
        """Free margin from the connected MT5 account (pusher or trading API)."""
        try:
            if getattr(self, "pusher", None) and self.pusher.connected:
                info = self.pusher.get_account_info()
                if info is not None and info.get("margin_free") is not None:
                    return float(info["margin_free"])
        except Exception:
            pass
        try:
            self._ensure_mt5_for_signals()
            if getattr(self, "pusher", None) and self.pusher.connected:
                info = self.pusher.get_account_info()
                if info is not None and info.get("margin_free") is not None:
                    return float(info["margin_free"])
        except Exception:
            pass
        api = self._get_mt5_trading_api()
        if api and MT5_AVAILABLE:
            try:
                import MetaTrader5 as _mt5
                acc = _mt5.account_info()
                if acc is not None:
                    return float(acc.margin_free)
            except Exception:
                pass
        return None

    def _estimate_mt5_order_margin(self, symbol, volume, side):
        """Margin required for one MT5 market order (via order_calc_margin)."""
        if not MT5_AVAILABLE:
            return None
        sym = str(symbol or "").strip()
        if not sym:
            return None
        try:
            import MetaTrader5 as _mt5
            if not _mt5.symbol_select(sym, True):
                return None
            tick = _mt5.symbol_info_tick(sym)
            if tick is None:
                return None
            is_buy = str(side).lower() == "buy"
            order_type = _mt5.ORDER_TYPE_BUY if is_buy else _mt5.ORDER_TYPE_SELL
            price = tick.ask if is_buy else tick.bid
            m = _mt5.order_calc_margin(order_type, sym, float(volume), price)
            if m is None or m <= 0:
                return None
            return float(m)
        except Exception:
            return None

    def _row_hedge_margin_estimate(self, row_data, prop_side):
        """Estimate MT5 hedge margin for one active-trade row."""
        if not self.prop_firm_mgr:
            return None
        config = self.prop_firm_mgr.get_strategy_config(
            row_data["firm_code"], row_data["phase_key"], row_data["acct_size"])
        if not config:
            return None
        mt5_sym = config.get("mt5_symbol", "NAS100")
        mt5_vol = float(config.get("mt5_volume", 2.8) or 0)
        if mt5_vol <= 0:
            return None
        hedge_side = "sell" if str(prop_side).lower() == "buy" else "buy"
        return self._estimate_mt5_order_margin(mt5_sym, mt5_vol, hedge_side)

    def _refresh_mt5_margin_after_scan(self):
        """After SCAN: show MT5 free margin and estimated hedge margin for queued rows."""
        if self.hedge_mode_var.get() != "Hedging":
            self.mt5_free_margin_var.set("")
            return
        login = self.mt5_login.get().strip()
        pwd = self.mt5_password.get().strip()
        server = self.mt5_server.get().strip()
        if login and pwd and server and not getattr(self.pusher, "connected", False):
            try:
                self.pusher.connect_mt5(login, pwd, server)
            except Exception:
                pass
        free = self._get_mt5_free_margin()
        rows = list(self._active_trade_rows)
        firm_sides = getattr(self, "_auto_trade_firm_sides", {}) or {}
        est_total = 0.0
        est_count = 0
        for rd in rows:
            firm = (rd.get("eval") or {}).get("Prop Firm", rd.get("firm_code", ""))
            side = firm_sides.get(firm, "buy")
            m = self._row_hedge_margin_estimate(rd, side)
            if m is not None:
                est_total += m
                est_count += 1
        if free is None:
            self.mt5_free_margin_var.set("MT5 free: not connected")
            self.log("⚠ MT5 free margin unavailable — connect MT5 to size hedges", "WARN")
            return
        label = f"MT5 free: ${free:,.0f}"
        if est_count:
            label += f"  ·  est. ${est_total:,.0f} ({est_count} hedges)"
            if est_total > free:
                label += "  ⚠ short"
        self.mt5_free_margin_var.set(label)
        self.log(f"💰 MT5 free margin ${free:,.2f}" +
                 (f", est. ${est_total:,.2f} for {est_count} hedge(s)" if est_count else ""))

    def _cap_rows_by_mt5_margin(self, rows_by_firm, firm_sides):
        """
        Drop rows that would exceed MT5 free margin (hedging only).
        Returns (updated rows_by_firm, affordable_count, skipped_count, free_margin, required_total).
        """
        if self.hedge_mode_var.get() != "Hedging":
            total = sum(len(v) for v in rows_by_firm.values())
            return rows_by_firm, total, 0, None, 0.0

        free = self._get_mt5_free_margin()
        if free is None:
            total = sum(len(v) for v in rows_by_firm.values())
            self.log("⚠ MT5 free margin unknown — not capping auto-trade count", "WARN")
            return rows_by_firm, total, 0, None, 0.0

        budget = max(0.0, free * 0.95)
        used = 0.0
        required_total = 0.0
        affordable = 0
        skipped = 0
        kept_ids = set()

        for rd in self._active_trade_rows:
            firm = (rd.get("eval") or {}).get("Prop Firm", rd.get("firm_code", ""))
            if firm not in rows_by_firm or rd not in rows_by_firm[firm]:
                continue
            side = firm_sides.get(firm, "buy")
            need = self._row_hedge_margin_estimate(rd, side)
            if need is None:
                kept_ids.add(id(rd))
                affordable += 1
                continue
            required_total += need
            if used + need <= budget:
                used += need
                kept_ids.add(id(rd))
                affordable += 1
            else:
                skipped += 1
                self.log(
                    f"   💰 {rd.get('acct_num', '?')} ({firm}) — skipped (need ${need:,.0f} margin, "
                    f"${max(0.0, budget - used):,.0f} left)",
                    "WARN",
                )
                try:
                    rd["buy_btn"].configure(state="disabled", text="N/A")
                    rd["sell_btn"].configure(state="disabled", text="N/A")
                except Exception:
                    pass

        if skipped:
            new_map = {}
            for firm, firm_rows in rows_by_firm.items():
                kept = [r for r in firm_rows if id(r) in kept_ids]
                if kept:
                    new_map[firm] = kept
            rows_by_firm = new_map

        return rows_by_firm, affordable, skipped, free, required_total

    def _eval_has_payout(self, ev):
        """Check if any hedge result field contains 'payout' text."""
        if not ev:
            return False
        for key, val in ev.items():
            if "hedge result" in key.lower() and isinstance(val, str) and "payout" in val.lower():
                return True
        return False

    def _execute_row_trade(self, side, row_data):
        """Execute a trade for a specific row, then remove the row."""
        # Check for payout — skip account if any hedge result has payout text
        ev = row_data.get("eval", {})
        if self._eval_has_payout(ev):
            acct_num = row_data.get("acct_num", "?")
            messagebox.showwarning("Payout Pending",
                f"Account {acct_num} has a PAYOUT pending.\n"
                f"Request payout first before continuing.")
            return

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

        # ── Resolve phase_key from day placeholder (primary source of truth) ──
        fresh_ev = self._refresh_eval_for_account(acct_num)
        if fresh_ev:
            ev = fresh_ev
            row_data["eval"] = fresh_ev
        resolved_key, day_idx, day_name = self._resolve_phase_key_from_day(
            ev, firm_code, row_data["current_phase"])
        if resolved_key is None:
            messagebox.showwarning("No Day Placeholder",
                f"Account {acct_num}: No day placeholder found.\n"
                f"Enter a day name (MON/TUE/etc.) in the next cell to enable trading.")
            return
        if resolved_key != phase_key:
            self.log(f"📅 {acct_num}: Day cell {day_idx + 1} ({day_name}) → "
                     f"blueprint {resolved_key} (was {phase_key})")
            phase_key = resolved_key

        # Capture the exact eval field holding the day placeholder so we can
        # clear it on the dashboard after the broker leg fills.
        day_field = self._find_day_field_name(ev, row_data["current_phase"])

        # Get trade config from blueprint
        config = None
        if self.prop_firm_mgr:
            config = self.prop_firm_mgr.get_strategy_config(firm_code, phase_key, acct_size)
        if not config:
            messagebox.showerror("Error", f"No blueprint config for {firm_code} / {phase_key} / {acct_size}")
            return

        hedging = self.hedge_mode_var.get() == "Hedging"
        prop_firm_name = row_data["eval"].get("Prop Firm", firm_code) if row_data.get("eval") else firm_code
        # Platform follows the resolved blueprint code, not a substring of the
        # free-text dashboard label (so e.g. TopStep RTP routes to TopStepX).
        platform = self._platform_for_firm(firm_code or prop_firm_name)
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

        # ── Farming: cap MT5 TP based on hard-stop proximity ──
        ev = row_data.get("eval", {})
        _is_farming_sym = "MNQ" in (config.get("tradovate_symbol", "") or config.get("topstepx_symbol", "")).upper()
        if _is_farming_sym and self.prop_firm_mgr:
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
        # TP/SL comes directly from the stage blueprint (selected by day placeholder)

        trado_tp = int(config.get("tradovate_tp_ticks", 151) or config.get("topstepx_tp_ticks", 151))
        trado_sl = int(config.get("tradovate_sl_ticks", 200) or config.get("topstepx_sl_ticks", 200))
        mt5_sym = config.get("mt5_symbol", "NAS100")
        mt5_vol = float(config.get("mt5_volume", 2.8))
        mt5_tp = int(config.get("mt5_tp_points", 46))
        mt5_sl = int(config.get("mt5_sl_points", 42))

        # ── Reference-ported TP→SL adjustment pipeline ──
        config = self._apply_tp_sl_adjustments(
            config, broker_account=broker_account, platform=platform,
            firm_code=firm_code, current_phase=row_data["current_phase"],
            phase_key=phase_key, acct_size=acct_size, row_eval=ev,
            acct_num=acct_num, is_farming=_is_farming_sym)
        trado_tp = int(config.get("tradovate_tp_ticks", trado_tp) or trado_tp)
        trado_sl = int(config.get("tradovate_sl_ticks", trado_sl) or trado_sl)
        mt5_tp = int(config.get("mt5_tp_points", mt5_tp) or mt5_tp)
        mt5_sl = int(config.get("mt5_sl_points", mt5_sl) or mt5_sl)

        # Confirm: phase + prop TP/SL (ticks), then MT5 TP/SL (points) when hedging
        trade_phase = (row_data.get("current_phase") or "").strip() or "Unknown"
        phase_bits = [trade_phase]
        if phase_key:
            phase_bits.append(phase_key.replace("_", " "))
        if day_name:
            phase_bits.append(day_name)
        phase_line = "\nPhase:     " + "  ·  ".join(phase_bits)
        tp_sl_lines = (
            phase_line
            + f"\n{platform}:  TP {trado_tp} ticks  |  SL {trado_sl} ticks"
            + (f"\nMT5:       TP {mt5_tp} pts    |  SL {mt5_sl} pts" if hedging else "")
        )

        confirm = messagebox.askyesno(
            "Confirm Trade",
            f"{side.upper()} {trado_qty} {trado_sym} on {platform}"
            f"{tp_sl_lines}\n\nProceed?",
        )
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
                # 0. PRE-FLIGHT: if hedging is on, verify MT5 is ready BEFORE
                # touching the broker leg.  Otherwise a bad MT5 state (e.g.
                # AutoTrading toggle off) leaves the broker side filled and
                # the hedge missing — exactly the state we want to avoid.
                if hedging and mt5_api:
                    is_healthy, health_msg = mt5_api.check_connection_health()
                    if not is_healthy:
                        raise Exception(
                            f"MT5 not ready — broker order skipped to avoid "
                            f"an unhedged position. {health_msg}"
                        )

                # PRE-FLIGHT SNAPSHOT: log expected account + active account + equity/balance
                try:
                    active_acct = broker_account.get_active_account() if hasattr(broker_account, "get_active_account") else None
                except Exception:
                    active_acct = None
                try:
                    stats = broker_account.get_account_stats() if hasattr(broker_account, "get_account_stats") else {}
                except Exception:
                    stats = {}
                bal = (stats or {}).get("Balance", "N/A")
                self.log(f"🧾 Pre-flight {platform}: expected={acct_num} active={active_acct or '?'} equity={bal}")
                if hedging and mt5_api:
                    try:
                        mt5_info = mt5_api.get_account_info() if hasattr(mt5_api, "get_account_info") else None
                        if isinstance(mt5_info, dict):
                            self.log(f"🧾 Pre-flight MT5: login={mt5_info.get('login','?')} equity=${mt5_info.get('equity','?')}")
                    except Exception:
                        pass

                # 1. Broker order
                if platform == "Tradovate":
                    if side == "buy":
                        order_result = broker_account.buy_market(trado_sym, trado_qty, tp=trado_tp, sl=trado_sl, expected_account=acct_num)
                    else:
                        order_result = broker_account.sell_market(trado_sym, trado_qty, tp=trado_tp, sl=trado_sl, expected_account=acct_num)
                elif platform == "TopStepX":
                    # Account is already selected upstream — don't re-open the slow
                    # dropdown here. place_*_order verifies the selector still matches
                    # acct_num (expected_account) and only switches if it drifted,
                    # so we stay fast while never firing on the wrong account.
                    # TopStepX uses two-digit year futures codes (NQM26, MNQM26)
                    _tsx_sym = _to_topstepx_symbol(trado_sym)
                    # Convert ticks to dollars for TopStepX: dollars = ticks * tick_value * quantity
                    _tsx_tick_val = self.prop_firm_mgr.get_tick_value(_tsx_sym) if self.prop_firm_mgr else 0.5
                    _tsx_tp_dollars = trado_tp * _tsx_tick_val * trado_qty
                    _tsx_sl_dollars = trado_sl * _tsx_tick_val * trado_qty
                    if side == "buy":
                        order_result = broker_account.place_buy_order(_tsx_sym, trado_qty, tp_dollars=_tsx_tp_dollars, sl_dollars=_tsx_sl_dollars, expected_account=acct_num)
                    else:
                        order_result = broker_account.place_sell_order(_tsx_sym, trado_qty, tp_dollars=_tsx_tp_dollars, sl_dollars=_tsx_sl_dollars, expected_account=acct_num)

                # Some broker implementations return a status dict instead of raising.
                # Normalize failures so UI/logs don't report false fills.
                if isinstance(order_result, dict) and order_result.get("success") is False:
                    raise Exception(order_result.get("message") or "Broker reported unsuccessful order")

                self.log(f"✅ {platform} filled {side.upper()} {trado_qty} {trado_sym} | TP:{trado_tp}t SL:{trado_sl}t | {acct_num}")

                # Mark the day-name cell as traded ($0.00) on the dashboard now
                # that the broker leg has filled. Triggered by Tradovate/TopStepX
                # fill only — independent of whether the MT5 hedge succeeds.
                # $0.00 makes the cell-finder skip it on the next scan, so the
                # same trade can't fire twice.
                if day_field:
                    try:
                        self._mark_day_cell_traded_on_dashboard(acct_num, day_field)
                    except Exception:
                        pass

                # 2. MT5 hedge (opposite direction)
                if hedging and mt5_api:
                    hedge_side = "sell" if side == "buy" else "buy"
                    # Pass platform so TopStepX trades always produce a
                    # comment starting with "V2-..." regardless of phase
                    # or the raw account-string shape.
                    comment = short_mt5_comment(acct_num, phase_key, platform=platform)
                    if hedge_side == "buy":
                        mt5_api.buy_market(mt5_sym, mt5_vol, sl=mt5_sl, tp=mt5_tp, comment=comment)
                    else:
                        mt5_api.sell_market(mt5_sym, mt5_vol, sl=mt5_sl, tp=mt5_tp, comment=comment)
                    self.log(f"✅ MT5 hedge {hedge_side.upper()} {mt5_vol} {mt5_sym} TP:{mt5_tp} SL:{mt5_sl} comment:{comment}")

                # ── Auto-status: set "In Progress" when trade goes out ──
                _ev = row_data.get("eval")
                if _ev:
                    _has_funded = bool((_ev.get("Account #.1") or "").strip())
                    _sf = "Status" if _has_funded else "Status P1"
                    _cur = (_ev.get(_sf) or "").strip().lower()
                    if not _cur or _cur in ("not started", "in progress", ""):
                        _ev[_sf] = "In Progress"
                        self.log(f"🔄 Auto-status: {acct_num} → {_sf}='In Progress'")

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

    def _apply_tp_sl_adjustments(self, config, *, broker_account, platform,
                                 firm_code, current_phase, phase_key,
                                 acct_size, row_eval, acct_num, is_farming):
        """Reference-ported TP→SL adjustment pipeline (TradeAccountConnector).

        Mirrors the connector's _compute_trade_adjustments routing exactly:

          • Funded / Double Dip (phase_key.startswith("funded_trade")):
            ONLY calculate_funded_sl — trade 1 = fixed $2,000 SL, trade 2+ =
            balance − flat lock level (TopStep $0, MFFU $100, others
            $50,000). Deliberately NO TP-by-stage / midnight / TMDL.
          • Challenge / Farming (else): TP-by-stage → SL midnight-floor →
            SL TMDL cap (calculate_adjusted_tp is skipped for farming
            symbols, which use adjust_farming_tp_sl upstream).

        The reference methods key off `tradovate_*`; mirror the broker-
        namespaced TopStepX keys so TopStepX blueprints adjust identically.
        """
        if not self.prop_firm_mgr:
            return config
        config = config.copy()
        if not config.get("tradovate_tp_ticks") and config.get("topstepx_tp_ticks"):
            config["tradovate_tp_ticks"] = config["topstepx_tp_ticks"]
        if not config.get("tradovate_sl_ticks") and config.get("topstepx_sl_ticks"):
            config["tradovate_sl_ticks"] = config["topstepx_sl_ticks"]
        if not config.get("tradovate_qty") and config.get("topstepx_qty"):
            config["tradovate_qty"] = config["topstepx_qty"]

        sym = config.get("tradovate_symbol", "") or config.get("topstepx_symbol", "")
        tick_value = self.prop_firm_mgr.get_tick_value(sym) if sym else 5.0

        # phase_key is funded_trade{n} or funded_trade_doubledip_{n} for the
        # funded/double-dip phases (challenge_trade*/farming are excluded).
        is_funded = (phase_key or "").startswith("funded_trade")

        if is_funded:
            # FUNDED / DOUBLE DIP: Tradovate SL + MT5 TP only via the funded
            # SL rule. Deliberately NO calculate_adjusted_tp / midnight-floor
            # / TMDL cap — those would move Tradovate TP and scale MT5 SL,
            # which funded trades must not do.
            try:
                import re as _re
                balance = None
                if broker_account:
                    _stats = broker_account.get_account_stats()
                    _bal_str = _stats.get("Balance", "") if isinstance(_stats, dict) else ""
                    if _bal_str and _bal_str not in ("N/A", "Error", ""):
                        balance = float(str(_bal_str).replace("$", "").replace(",", ""))
                if balance is None:
                    self.log(f"⚠ Funded SL {acct_num}: balance unavailable — keeping blueprint SL/TP")
                else:
                    _m = _re.search(r'(\d+)$', phase_key or "")
                    trade_index = int(_m.group(1)) if _m else 1
                    # Flat lock level: distance the funded SL measures from
                    # (TopStep $0, MFFU $100, others $50,000).
                    threshold = self.prop_firm_mgr.get_lock_level(firm_code)
                    config = self.prop_firm_mgr.calculate_funded_sl(
                        config, balance, threshold, trade_index, tick_value)
            except Exception as _fe:
                self.log(f"⚠ Funded SL failed for {acct_num}: {_fe}")
        else:
            # CHALLENGE / FARMING.
            # 1) TP by stage profit (skipped for farming symbols upstream)
            if broker_account and not is_farming:
                try:
                    current_profit = self._get_current_phase_profit(
                        row_eval, current_phase,
                        broker_account=broker_account, acct_size=acct_size)
                    size_key = self.prop_firm_mgr.convert_account_size_to_key(acct_size)
                    stage_start = self.prop_firm_mgr.get_stage_start_target(
                        firm_code, current_phase, phase_key, size_key)
                    # Only apply when stage_start is trustworthy — falling back
                    # to 0 would attribute the whole account balance to this
                    # stage and collapse TP to the floor.
                    if stage_start is not None:
                        stage_profit_so_far = current_profit - stage_start
                        config = self.prop_firm_mgr.calculate_adjusted_tp(
                            config, stage_profit_so_far, tick_value)
                except Exception as _te:
                    self.log(f"⚠ TP adjust failed for {acct_num}: {_te}")

            # 2/3) SL midnight floor + TMDL cap. Runs for any broker that
            # exposes get_min_equity() — Tradovate (live API) or TopStepX
            # (static formula + persisted SOD), matching the connector.
            if broker_account and hasattr(broker_account, 'get_min_equity'):
                try:
                    min_eq = broker_account.get_min_equity()
                    if isinstance(min_eq, dict):
                        live_net_liq = min_eq.get('net_liq')
                        net_liq_sod = min_eq.get('net_liq_sod', 0)
                        live_min_equity = min_eq.get('min_equity', 0)
                        tmdl = min_eq.get('trailing_max_drawdown_limit', 50000)
                        if live_net_liq is None:
                            live_net_liq = net_liq_sod
                        if net_liq_sod and net_liq_sod > 0:
                            config = self.prop_firm_mgr.calculate_adjusted_sl_midnight_floor(
                                config, live_net_liq, net_liq_sod, tick_value)
                        if tmdl is not None and live_min_equity is not None:
                            config = self.prop_firm_mgr.calculate_adjusted_sl_tmdl_cap(
                                config, live_net_liq, live_min_equity, tmdl, tick_value)
                except Exception:
                    pass

        for _r in (config.get('_adj_reasons') or []):
            self.log(f"📐 {acct_num}: {_r}")
        return config

    # ── Auto-Trade Scheduler Logic ──

    def _toggle_auto_trade(self):
        """Toggle the auto-trade scheduler on/off."""
        if self.auto_trade_enabled:
            self._stop_auto_trade()
        else:
            self._start_auto_trade()

    # ── Hedge Protector ──────────────────────────────────────────────

    def _test_min_equity(self, event=None):
        """Test: dump min equity data from cached prop firm mappings and Tradovate API."""
        self.log("🔍 Testing min equity sources...")
        # 1. Cached prop firm mappings
        if self._cached_acct_mappings:
            for firm_name, mapping in self._cached_acct_mappings.items():
                self.log(f"  --- {firm_name} (cached mapping) ---")
                for key, info in mapping.items():
                    me = info.get("min_equity")
                    pt = info.get("profit_target")
                    bal = info.get("balance")
                    start = info.get("starting_balance")
                    self.log(f"    {key}: bal=${bal}, start=${start}, min_eq=${me}, target=${pt}")
        else:
            self.log("  ⚠ No cached account mappings (connect prop firm dashboards first)")
        # 2. Tradovate API fallback
        found = False
        for firm_name, conn in self._broker_connections.items():
            acct = conn.get("account")
            if not acct or not hasattr(acct, 'get_min_equity'):
                continue
            found = True
            self.log(f"  --- {firm_name} (Tradovate API) ---")
            try:
                result = acct.get_min_equity()
                if result:
                    self.log(f"    Net Liq:           ${result['net_liq']:,.2f}")
                    self.log(f"    Min Equity:        ${result['min_equity']:,.2f}")
                    self.log(f"    Drawdown Remaining:${result['drawdown_remaining']:,.2f}")
                    self.log(f"    Max Net Liq:       ${result.get('max_net_liq', 0):,.2f}")
                    self.log(f"    Trailing Max DD:   ${result['trailing_max_drawdown']:,.2f}")
                    self.log(f"    Trailing DD Limit: ${result['trailing_max_drawdown_limit']:,.2f}")
                    self.log(f"    Mode:              {result.get('trailing_mode', '?')}")
                else:
                    self.log(f"    ❌ get_min_equity returned None")
            except Exception as e:
                self.log(f"    ❌ Error: {e}", "ERROR")
        if not found:
            self.log("  ⚠ No connected Tradovate brokers")
        self.log("🔍 Min equity test complete.")

    # ── Close All Trades ────────────────────────────────────────────

    def _close_all_trades(self):
        """Liquidate all positions across every connected broker and MT5."""
        # Confirm first
        connected = [f for f, c in self._broker_connections.items() if c.get("account")]
        if not connected:
            self.log("⚠ No brokers connected — nothing to close")
            return

        if not messagebox.askyesno(
            "Close ALL Trades",
            f"This will LIQUIDATE all open positions on:\n\n"
            f"  • {len(connected)} broker(s): {', '.join(connected)}\n"
            f"  • MT5 (all open positions)\n\n"
            f"Are you sure?",
            icon="warning",
        ):
            return

        self.log("🔴 CLOSING ALL TRADES across all platforms...")
        self._add_activity("🔴 Close All triggered — liquidating everything", "error")

        def _do_close_all():
            closed_tv = 0
            closed_mt5 = 0
            errors = []

            # 1. Liquidate every connected Tradovate / TopStepX account
            for firm_name, conn in self._broker_connections.items():
                acct = conn.get("account")
                if not acct:
                    continue
                try:
                    if hasattr(acct, 'liquidate_position_api'):
                        # Tradovate — liquidate all accounts under this login
                        accounts = acct._api_fetch("/account/list")
                        if accounts and isinstance(accounts, list):
                            for a in accounts:
                                aid = a['id']
                                aname = a.get('name', '?')
                                # Check if positions exist first
                                positions = acct.get_positions_api(account_id=aid)
                                open_pos = [p for p in positions if p.get('netPos', 0) != 0]
                                if not open_pos:
                                    self.root.after(0, lambda fn=firm_name, n=aname:
                                        self.log(f"  ⏭ {fn} — {n} (already flat)"))
                                    # Still cancel any orphaned bracket orders
                                    try:
                                        cancelled = acct.cancel_all_orders_api(account_id=aid)
                                        if cancelled > 0:
                                            self.root.after(0, lambda fn=firm_name, n=aname, c=cancelled:
                                                self.log(f"  🧹 {fn} — {n} cancelled {c} orphaned order(s)"))
                                    except Exception:
                                        pass
                                    continue
                                self.root.after(0, lambda fn=firm_name, n=aname, cnt=len(open_pos):
                                    self.log(f"  🔄 {fn} — {n} closing {cnt} position(s)..."))
                                result = acct.liquidate_position_api(account_id=aid)
                                if result:
                                    closed_tv += 1
                                    self.root.after(0, lambda fn=firm_name, n=aname:
                                        self.log(f"  ✅ {fn} — {n} liquidated"))
                                else:
                                    errors.append(f"{firm_name}/{aname}: liquidate returned None")
                                    self.root.after(0, lambda fn=firm_name, n=aname:
                                        self.log(f"  ❌ {fn} — {n} liquidation FAILED", "ERROR"))
                                # Cancel remaining bracket orders (stop/limit)
                                try:
                                    cancelled = acct.cancel_all_orders_api(account_id=aid)
                                    if cancelled > 0:
                                        self.root.after(0, lambda fn=firm_name, n=aname, c=cancelled:
                                            self.log(f"  🧹 {fn} — {n} cancelled {c} pending order(s)"))
                                except Exception:
                                    pass
                        else:
                            self.root.after(0, lambda fn=firm_name:
                                self.log(f"  ❌ {fn} — could not fetch account list", "ERROR"))
                            errors.append(f"{firm_name}: account list fetch failed")
                    elif hasattr(acct, 'close_all_positions'):
                        # TopStepX
                        acct.close_all_positions()
                        closed_tv += 1
                        self.root.after(0, lambda fn=firm_name:
                            self.log(f"  ✅ {fn} positions closed"))
                except Exception as e:
                    errors.append(f"{firm_name}: {e}")
                    self.root.after(0, lambda fn=firm_name, err=str(e):
                        self.log(f"  ❌ {fn} close failed: {err}", "ERROR"))

            # 2. Close all MT5 positions
            #
            # Connect MT5 FIRST. Without this, mt5.positions_get() runs against an
            # uninitialised module and returns None, the `if positions:` branch
            # is skipped silently, and Close All appears to ignore MT5. The
            # _get_mt5_trading_api() call is what triggers mt5.initialize() +
            # login via MT5API.connect(), so calling it up front ensures the
            # module is ready before we query.
            try:
                if not MT5_AVAILABLE:
                    raise RuntimeError("MetaTrader5 module is not available")

                mt5_api = self._get_mt5_trading_api()
                if mt5_api is None:
                    raise RuntimeError(
                        "MT5 is not connected — enter MT5 credentials and "
                        "connect MT5 first, then retry Close All"
                    )

                positions = mt5.positions_get()
                if positions is None:
                    # Module is connected but the query itself failed.
                    last_err = mt5.last_error() if hasattr(mt5, "last_error") else "?"
                    raise RuntimeError(f"mt5.positions_get() returned None (last_error={last_err})")

                if not positions:
                    self.root.after(0, lambda:
                        self.log("  ⏭ MT5 — no open positions (already flat)"))
                else:
                    self.root.after(0, lambda n=len(positions):
                        self.log(f"  🔄 MT5 — closing {n} position(s)..."))
                    for pos in positions:
                        try:
                            mt5_api.close_trade(pos.ticket)
                            closed_mt5 += 1
                            self.root.after(0, lambda t=pos.ticket, s=pos.symbol:
                                self.log(f"  ✅ MT5 #{t} {s} closed"))
                        except Exception as e:
                            errors.append(f"MT5 #{pos.ticket}: {e}")
                            self.root.after(0, lambda t=pos.ticket, err=str(e):
                                self.log(f"  ❌ MT5 #{t} close failed: {err}", "ERROR"))
            except Exception as e:
                errors.append(f"MT5: {e}")
                self.root.after(0, lambda err=str(e):
                    self.log(f"  ❌ MT5 close skipped: {err}", "ERROR"))

            # Summary
            summary = f"🔴 Close All done — Brokers: {closed_tv}, MT5: {closed_mt5}"
            if errors:
                summary += f", Errors: {len(errors)}"
            self.root.after(0, lambda s=summary: self.log(s))
            self.root.after(0, lambda s=summary: self._add_activity(s, "error"))

        threading.Thread(target=_do_close_all, daemon=True, name="CloseAll").start()

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
        default_platform = self.broker_var.get()
        mt5_api = self._get_mt5_trading_api() if hedging else None
        if hedging and not mt5_api:
            messagebox.showerror(
                "MT5 Not Connected",
                "Connect MT5 first, or switch to 'Broker Only' mode to skip MT5 hedging."
            )
            self.log("❌ Auto-trade aborted — MT5 not connected (Hedging mode requires MT5)")
            self._stop_auto_trade()
            return

        # Group rows by firm so each firm's Chrome runs in its own thread
        rows_by_firm = defaultdict(list)
        for row_data in rows:
            firm_name = row_data["eval"].get("Prop Firm", row_data["firm_code"])
            rows_by_firm[firm_name].append(row_data)

        # ── PAYOUT CHECK: skip accounts with payout pending ──
        payout_skipped = []
        for firm_name, firm_rows in list(rows_by_firm.items()):
            clean = []
            for rd in firm_rows:
                if self._eval_has_payout(rd.get("eval", {})):
                    payout_skipped.append(rd)
                    self.log(f"   💰 {rd['acct_num']}  ({firm_name} / {rd['current_phase']}) — PAYOUT pending, skipped")
                else:
                    clean.append(rd)
            rows_by_firm[firm_name] = clean
        if payout_skipped:
            self.log(f"💰 {len(payout_skipped)} account(s) skipped — payout pending (request payout first)")

        # ── PRE-VALIDATE: check which accounts actually exist on each Tradovate ──
        skipped_rows = []
        not_connected_firms = []
        if default_platform == "Tradovate":
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

        margin_skipped = 0
        if hedging and mt5_api:
            rows_by_firm, affordable_n, margin_skipped, free_m, required_m = self._cap_rows_by_mt5_margin(
                rows_by_firm, firm_sides)
            if margin_skipped > 0 and free_m is not None:
                total_queued = affordable_n + margin_skipped
                messagebox.showwarning(
                    "Free Margin Limited",
                    f"Free margin is not enough for all hedges.\n\n"
                    f"MT5 free margin: ${free_m:,.0f}\n"
                    f"Estimated for {total_queued} trade(s): ${required_m:,.0f}\n\n"
                    f"Only taking {affordable_n} trade(s).",
                )
                self.log(
                    f"💰 Free margin limited: taking {affordable_n} of {total_queued} hedge(s), "
                    f"{margin_skipped} skipped")
            if not rows_by_firm:
                free_txt = f"${free_m:,.0f}" if free_m is not None else "unknown"
                messagebox.showerror(
                    "Insufficient Margin",
                    f"MT5 free margin ({free_txt}) is not enough to open any hedges.",
                )
                self.log("❌ Auto-trade aborted — insufficient MT5 free margin", "ERROR")
                self._stop_auto_trade()
                return
            self.root.after(0, self._refresh_mt5_margin_after_scan)

        total_success = threading.Lock()
        counters = {"success": 0, "fail": 0, "skipped": len(skipped_rows) + margin_skipped}

        def _execute_firm_trades(firm_name, firm_rows):
            """Execute all trades for one firm sequentially on its own Chrome."""
            # Platform follows the resolved blueprint code (first row's
            # firm_code), not a substring of the dashboard label.
            _fc = firm_rows[0].get("firm_code") if firm_rows else None
            platform = self._platform_for_firm(_fc or firm_name, default=default_platform)
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

                # ── Resolve phase_key from day placeholder (primary source of truth) ──
                auto_ev = row_data.get("eval", {})
                fresh_auto_ev = self._refresh_eval_for_account(acct_num)
                if fresh_auto_ev:
                    auto_ev = fresh_auto_ev
                    row_data["eval"] = fresh_auto_ev
                resolved_key, day_idx, day_name = self._resolve_phase_key_from_day(
                    auto_ev, firm_code, row_data.get("current_phase", ""))
                if resolved_key is None:
                    # Build a precise diagnostic.  resolved_key can be None for
                    # three different reasons; the message tells the user which
                    # one fired so they can act on it.  "Today" is Kenya time
                    # (EAT, UTC+3) — independent of the host clock — so the
                    # diagnostic matches the same definition the cell-finder
                    # is using.
                    _today = kenya_today()
                    today_wd = _today.weekday()
                    today_name = _today.strftime("%A").upper()
                    current_phase_str = row_data.get("current_phase", "?") or "?"

                    # Re-run the cell finder so we can tell which sub-case we hit
                    # without having to change the resolver's return signature.
                    _di, _dn, _is_today, _matched_phase = (
                        self._find_tradeable_day_cell(
                            auto_ev, current_phase_str,
                        )
                    )

                    # Collect every day-named placeholder for the log line so
                    # the user can see what the scanner actually saw.
                    placeholders: list[str] = []
                    for _ph, _flist in self._ALL_PHASE_FIELD_SETS:
                        for _f in _flist:
                            _v = auto_ev.get(_f, None)
                            _dn2 = self._parse_day_token(_v)
                            if _dn2 is None:
                                continue
                            if _dn2 == today_wd:
                                _tag = "today"
                            elif _dn2 < today_wd:
                                _tag = "past"
                            else:
                                _tag = "future"
                            placeholders.append(
                                f"{_f}={str(_v).strip()}({_tag})"
                            )

                    if _di is None:
                        diag = (
                            "no day-name placeholder anywhere in any phase"
                            if not placeholders
                            else f"cell finder still rejected every candidate "
                                 f"[{', '.join(placeholders[:3])}]"
                        )
                    else:
                        # A cell WAS found — None came from the phase-mapping
                        # step (firm has no trade order for the matched phase,
                        # or prop_firm_mgr is missing).
                        eff_phase = _matched_phase or current_phase_str
                        if self.prop_firm_mgr is None:
                            diag = (
                                f"prop_firm_mgr is None — cell "
                                f"{_di + 1} ({_dn}) found in phase "
                                f"'{eff_phase}' but no manager to map it"
                            )
                        else:
                            firm_orders = (
                                self.prop_firm_mgr._PHASE_TRADE_ORDER.get(
                                    firm_code, {}
                                )
                            )
                            available = list(firm_orders.keys())
                            diag = (
                                f"cell {_di + 1} ({_dn}) found in phase "
                                f"'{eff_phase}' but firm '{firm_code}' has "
                                f"no trade order for that phase "
                                f"(has: {available})"
                            )

                    _an, _diag = acct_num, diag
                    _ph_in = current_phase_str
                    _fc_in = firm_code
                    self.root.after(0, lambda an=_an, d=_diag,
                                    twd=today_wd, tname=today_name,
                                    ph=_ph_in, fc=_fc_in,
                                    pl=placeholders:
                        self.log(
                            f"⛔ {an}: trade rejected — {d}. "
                            f"[today={tname} (wd={twd}), "
                            f"current_phase='{ph}', firm='{fc}', "
                            f"cells={pl}]",
                            "ERROR",
                        )
                    )
                    with total_success:
                        counters["fail"] += 1
                    continue
                if resolved_key != phase_key:
                    _an, _di, _dn, _rk, _pk = acct_num, day_idx, day_name, resolved_key, phase_key
                    self.root.after(0, lambda an=_an, di=_di, dn=_dn, rk=_rk, pk=_pk:
                        self.log(f"📅 {an}: Day cell {di + 1} ({dn}) → blueprint {rk} (was {pk})"))
                    phase_key = resolved_key

                # Capture the exact eval field holding the day placeholder so
                # we can clear it after the broker leg fills.
                day_field = self._find_day_field_name(auto_ev, row_data.get("current_phase", ""))

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

                # Log resolved blueprint up-front so the user can verify the
                # correct trade is being placed (catches farming/challenge mix-ups).
                _bp_tp = config.get("tradovate_tp_ticks", config.get("topstepx_tp_ticks", "?"))
                _bp_sl = config.get("tradovate_sl_ticks", config.get("topstepx_sl_ticks", "?"))
                _an, _fc, _pk, _sz = acct_num, firm_code, phase_key, acct_size
                _bs, _bq, _bt, _bsl = trado_sym, trado_qty, _bp_tp, _bp_sl
                self.root.after(0, lambda an=_an, fc=_fc, pk=_pk, sz=_sz, bs=_bs, bq=_bq, bt=_bt, bsl=_bsl:
                    self.log(f"📋 {an}: blueprint {fc}/{pk}/{sz} → "
                             f"{bs} qty={bq} TP={bt}t SL={bsl}t"))

                # ── Farming: cap MT5 TP based on hard-stop proximity ──
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
                # TP/SL comes directly from the stage blueprint (selected by day placeholder)

                trado_tp = int(config.get("tradovate_tp_ticks", 151) or config.get("topstepx_tp_ticks", 151))
                trado_sl = int(config.get("tradovate_sl_ticks", 200) or config.get("topstepx_sl_ticks", 200))
                mt5_sym = config.get("mt5_symbol", "NAS100")
                mt5_vol = float(config.get("mt5_volume", 2.8))
                mt5_tp = int(config.get("mt5_tp_points", 46))
                mt5_sl = int(config.get("mt5_sl_points", 42))

                # ── Reference-ported TP→SL adjustment pipeline ──
                config = self._apply_tp_sl_adjustments(
                    config, broker_account=broker_account, platform=platform,
                    firm_code=firm_code, current_phase=row_data.get("current_phase", ""),
                    phase_key=phase_key, acct_size=acct_size, row_eval=auto_ev,
                    acct_num=acct_num, is_farming=_is_farming_sym_auto)
                trado_tp = int(config.get("tradovate_tp_ticks", trado_tp) or trado_tp)
                trado_sl = int(config.get("tradovate_sl_ticks", trado_sl) or trado_sl)
                mt5_tp = int(config.get("mt5_tp_points", mt5_tp) or mt5_tp)
                mt5_sl = int(config.get("mt5_sl_points", mt5_sl) or mt5_sl)

                try:
                    # 1. Broker order — uses this firm's own Chrome instance
                    # 0. PRE-FLIGHT: verify MT5 is ready BEFORE firing the
                    # broker leg whenever hedging is on, so we never leave a
                    # broker position uncovered because the MT5 terminal had
                    # AutoTrading off or the connection dropped.
                    if hedging and mt5_api:
                        is_healthy, health_msg = mt5_api.check_connection_health()
                        if not is_healthy:
                            raise Exception(
                                f"MT5 not ready — broker order skipped to "
                                f"avoid an unhedged position. {health_msg}"
                            )

                    # PRE-FLIGHT SNAPSHOT: log expected account + active account + equity/balance
                    try:
                        active_acct = broker_account.get_active_account() if hasattr(broker_account, "get_active_account") else None
                    except Exception:
                        active_acct = None
                    try:
                        stats = broker_account.get_account_stats() if hasattr(broker_account, "get_account_stats") else {}
                    except Exception:
                        stats = {}
                    bal = (stats or {}).get("Balance", "N/A")
                    self.root.after(0, lambda p=platform, an=acct_num, aa=(active_acct or "?"), b=bal:
                        self.log(f"🧾 Pre-flight {p}: expected={an} active={aa} equity={b}"))
                    if hedging and mt5_api:
                        try:
                            mt5_info = mt5_api.get_account_info() if hasattr(mt5_api, "get_account_info") else None
                            if isinstance(mt5_info, dict):
                                self.root.after(0, lambda mi=mt5_info:
                                    self.log(f"🧾 Pre-flight MT5: login={mi.get('login','?')} equity=${mi.get('equity','?')}"))
                        except Exception:
                            pass

                    if platform == "Tradovate":
                        if side == "buy":
                            order_result = broker_account.buy_market(trado_sym, trado_qty, tp=trado_tp, sl=trado_sl, expected_account=acct_num)
                        else:
                            order_result = broker_account.sell_market(trado_sym, trado_qty, tp=trado_tp, sl=trado_sl, expected_account=acct_num)
                    elif platform == "TopStepX":
                        # Account is already selected upstream — don't re-open the slow
                        # dropdown here. place_*_order verifies the selector still matches
                        # acct_num (expected_account) and only switches if it drifted,
                        # so we stay fast while never firing on the wrong account.
                        # TopStepX uses two-digit year futures codes (NQM26, MNQM26)
                        _tsx_sym = _to_topstepx_symbol(trado_sym)
                        _tsx_tick_val = self.prop_firm_mgr.get_tick_value(_tsx_sym) if self.prop_firm_mgr else 0.5
                        _tsx_tp_dollars = trado_tp * _tsx_tick_val * trado_qty
                        _tsx_sl_dollars = trado_sl * _tsx_tick_val * trado_qty
                        if side == "buy":
                            order_result = broker_account.place_buy_order(
                                _tsx_sym,
                                trado_qty,
                                tp_dollars=_tsx_tp_dollars,
                                sl_dollars=_tsx_sl_dollars,
                                expected_account=acct_num,
                            )
                        else:
                            order_result = broker_account.place_sell_order(
                                _tsx_sym,
                                trado_qty,
                                tp_dollars=_tsx_tp_dollars,
                                sl_dollars=_tsx_sl_dollars,
                                expected_account=acct_num,
                            )

                    # TopStepX returns status dicts on both success and failure.
                    # Convert broker-declared failures to exceptions so counters/logs are accurate.
                    if isinstance(order_result, dict) and order_result.get("success") is False:
                        raise Exception(order_result.get("message") or "Broker reported unsuccessful order")

                    self.root.after(0, lambda an=acct_num, fc=firm_code, sd=side, sym=trado_sym, qty=trado_qty:
                        self.log(f"✅ {platform} {sd.upper()} {qty} {sym} → {an} ({fc})"))

                    # Mark the day-name cell as traded ($0.00) on the dashboard
                    # now that the broker leg has filled. Triggered by
                    # Tradovate/TopStepX fill only — independent of whether the
                    # MT5 hedge succeeds. $0.00 makes the cell-finder skip it on
                    # the next scan, so the same trade can't fire twice.
                    if day_field:
                        try:
                            self._mark_day_cell_traded_on_dashboard(acct_num, day_field)
                        except Exception:
                            pass

                    # 2. MT5 hedge (opposite direction)
                    if hedging and mt5_api:
                        hedge_side = "sell" if side == "buy" else "buy"
                        # Pass platform so TopStepX trades always produce
                        # a "V2-..." comment regardless of phase or the
                        # raw account-string shape.
                        comment = short_mt5_comment(acct_num, phase_key, platform=platform)
                        if hedge_side == "buy":
                            mt5_api.buy_market(mt5_sym, mt5_vol, sl=mt5_sl, tp=mt5_tp, comment=comment)
                        else:
                            mt5_api.sell_market(mt5_sym, mt5_vol, sl=mt5_sl, tp=mt5_tp, comment=comment)
                        self.root.after(0, lambda an=acct_num, hs=hedge_side, vol=mt5_vol, sym=mt5_sym, cmt=comment:
                            self.log(f"✅ MT5 hedge {hs.upper()} {vol} {sym} comment:{cmt} → {an}"))

                    with total_success:
                        counters["success"] += 1

                    # ── Auto-status: set "In Progress" when trades go out ──
                    if not RELEASE_DISABLE_AUTO_STATUS_UPDATES:
                        _ev = row_data.get("eval")
                        if _ev:
                            _has_funded = bool((row_data.get("eval", {}).get("Account #.1") or "").strip())
                            _sf = "Status" if _has_funded else "Status P1"
                            _cur = (_ev.get(_sf) or "").strip().lower()
                            # Only set In Progress if status is empty, Not Started, or already In Progress
                            if not _cur or _cur in ("not started", "in progress", ""):
                                _ev[_sf] = "In Progress"
                                self.root.after(0, lambda an=acct_num, sf=_sf:
                                    self.log(f"🔄 Auto-status: {an} → {_sf}='In Progress'"))

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
                    "lucid": ["lucid trading"],
                    "lucid trading": ["lucid"],
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

                # History button — shows full Tradovate trade history for this account
                hist_btn = ctk.CTkButton(row, text="📊 History", width=78, height=24,
                                         fg_color="#1A2332", hover_color="#2A3342",
                                         border_width=1, border_color="#3B4B5E",
                                         font=("Consolas", 9), text_color="#60A5FA",
                                         corner_radius=4,
                                         command=lambda f=firm: self._show_trade_history(f))
                hist_btn.pack(side="right", padx=(4, 0))

                # Dashboard button — show for all firms (use _BROWSER_MONITORED_FIRMS with case-insensitive + alias match)
                _dash_cfg = self._BROWSER_MONITORED_FIRMS.get(firm)
                if not _dash_cfg:
                    # Case-insensitive lookup
                    for _bk, _bv in self._BROWSER_MONITORED_FIRMS.items():
                        if _bk.lower() == firm.lower():
                            _dash_cfg = _bv
                            break
                if _dash_cfg and not RELEASE_DISABLE_PROP_DASHBOARD_ACCESS:
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

        # Platform follows the resolved blueprint, not just a substring of
        # the firm label (so TopStep RTP connects via TopStepX).
        platform = self._platform_for_firm(firm_name)

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
                # Release build: no status polling side-effects
                if not RELEASE_DISABLE_STATUS_POLL:
                    self.root.after(0, self._start_status_polling)

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

    def _show_trade_history(self, firm_name):
        """Show a popup window with full Tradovate trade history for the given firm."""
        conn = self._broker_connections.get(firm_name)
        if not conn or not conn.get("account"):
            self.log(f"⚠ {firm_name} is not connected — connect first", "WARN")
            return

        account = conn["account"]
        if not hasattr(account, 'get_trade_history'):
            self.log(f"⚠ {firm_name} account does not support trade history", "WARN")
            return

        self.log(f"📊 Loading trade history for {firm_name}...")

        def _fetch_and_show():
            try:
                data = account.get_trade_history()
                if not data:
                    self.root.after(0, lambda: self.log(f"⚠ No history data for {firm_name}", "WARN"))
                    return
                self.root.after(0, lambda d=data: self._build_history_window(firm_name, d))
            except Exception as e:
                self.root.after(0, lambda: self.log(f"❌ History fetch failed: {e}", "ERROR"))

        threading.Thread(target=_fetch_and_show, daemon=True).start()

    def _build_history_window(self, firm_name, data):
        """Build and display the trade history popup window.
        data is a list of account dicts (one per account under this login)."""
        if isinstance(data, dict):
            data = [data]  # backwards compat — single account

        win = tk.Toplevel(self.root)
        acct_count = len(data)
        win.title(f"📊 Trade History — {firm_name} ({acct_count} account{'s' if acct_count > 1 else ''})")
        win.geometry("800x660")
        win.configure(bg="#0A0E17")
        win.attributes("-topmost", True)
        win.after(500, lambda: win.attributes("-topmost", False))

        # ── Account selector tabs (if multiple accounts) ──────
        if acct_count > 1:
            tab_frame = tk.Frame(win, bg="#0A0E17")
            tab_frame.pack(fill="x", padx=8, pady=(6, 0))
            tk.Label(tab_frame, text=f"{acct_count} accounts found",
                     bg="#0A0E17", fg="#64748B", font=("Consolas", 9)).pack(side="left", padx=(4, 12))

        # Content container — will be cleared/rebuilt on account switch
        content = tk.Frame(win, bg="#0A0E17")
        content.pack(fill="both", expand=True)

        def _show_account(acct_data):
            # Clear existing content
            for w in content.winfo_children():
                w.destroy()
            self._render_account_history(content, acct_data)

        # Build tab buttons (if multiple)
        if acct_count > 1:
            for i, acct in enumerate(data):
                aname = acct.get('account_name', f'Account {i+1}')
                bal = acct.get('balance', 0)
                btn_text = f"{aname}  ${bal:,.0f}"
                btn = tk.Button(tab_frame, text=btn_text, bg="#1A2332", fg="#60A5FA",
                                activebackground="#2A3342", activeforeground="#93C5FD",
                                font=("Consolas", 9), bd=0, padx=8, pady=2,
                                command=lambda d=acct: _show_account(d))
                btn.pack(side="left", padx=2)

        # Show first account by default
        _show_account(data[0])

        total_fills = sum(len(a.get('fills', [])) for a in data)
        total_days = sum(len(a.get('daily_pnl', [])) for a in data)
        self.log(f"📊 Trade history loaded for {firm_name}: {acct_count} account(s), {total_days} days, {total_fills} fills")

    def _render_account_history(self, parent, data):
        """Render a single account's history into the given parent frame."""
        acct_name = data.get('account_name', '?')
        env = data.get('environment', '?').upper()
        balance = data.get('balance', 0)
        balance_sod = data.get('balance_sod', 0)
        realized = data.get('realized_pnl', 0)
        open_pnl = data.get('open_pnl', 0)
        dd_max = data.get('trailing_max_drawdown', 0)
        dd_limit = data.get('trailing_max_drawdown_limit', 0)
        dd_mode = data.get('drawdown_mode', '?')

        # ── Header ────────────────────────────────────────────
        hdr = tk.Frame(parent, bg="#0F1520", height=80)
        hdr.pack(fill="x", padx=8, pady=(8, 4))
        hdr.pack_propagate(False)

        tk.Label(hdr, text=f"{acct_name}  [{env}]",
                 bg="#0F1520", fg="#E2E8F0", font=("Consolas", 12, "bold"),
                 anchor="w").place(x=12, y=6)

        bal_color = "#22C55E" if realized >= 0 else "#EF4444"
        tk.Label(hdr, text=f"Balance: ${balance:,.2f}   SOD: ${balance_sod:,.2f}   "
                            f"P&L: ${realized:+,.2f}   Open: ${open_pnl:+,.2f}",
                 bg="#0F1520", fg=bal_color, font=("Consolas", 10),
                 anchor="w").place(x=12, y=32)

        if dd_max:
            dd_used = dd_limit - balance if dd_limit < 999_999_000 else 0
            tk.Label(hdr, text=f"Drawdown: ${dd_max:,.0f} trailing ({dd_mode})   "
                                f"Limit: ${dd_limit:,.0f}" + (f"   Used: ${dd_used:,.2f}" if dd_used else ""),
                     bg="#0F1520", fg="#94A3B8", font=("Consolas", 9),
                     anchor="w").place(x=12, y=54)

        # ── Daily P&L Table ───────────────────────────────────
        tk.Label(parent, text="Daily P&L", bg="#0A0E17", fg="#60A5FA",
                 font=("Consolas", 10, "bold"), anchor="w").pack(fill="x", padx=12, pady=(8, 0))

        daily_frame = tk.Frame(parent, bg="#0A0E17")
        daily_frame.pack(fill="both", expand=True, padx=8, pady=(2, 4))

        # Canvas + scrollbar for the daily P&L
        canvas = tk.Canvas(daily_frame, bg="#0A0E17", highlightthickness=0)
        scrollbar = tk.Scrollbar(daily_frame, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg="#0A0E17")

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Table header
        cols = [("Date", 90), ("Trades", 50), ("Gross P&L", 90), ("Fees", 80),
                ("Net P&L", 90), ("Balance", 100)]
        hdr_row = tk.Frame(scroll_frame, bg="#151D2B")
        hdr_row.pack(fill="x", pady=(0, 1))
        for col_name, col_w in cols:
            tk.Label(hdr_row, text=col_name, width=col_w // 8, bg="#151D2B", fg="#64748B",
                     font=("Consolas", 9, "bold"), anchor="center").pack(side="left", padx=1)

        # Table rows
        daily_pnl = data.get('daily_pnl', [])
        total_gross = total_fees = total_net = 0
        for i, day in enumerate(daily_pnl):
            bg = "#0D1320" if i % 2 == 0 else "#0A0E17"
            r = tk.Frame(scroll_frame, bg=bg)
            r.pack(fill="x")

            date_str = day['date']
            trades = day['trades']
            gross = day['gross_pnl']
            fees = day['fees']
            net = day['net_pnl']
            bal = day['balance_eod']

            total_gross += gross
            total_fees += fees
            total_net += net

            net_color = "#22C55E" if net > 0 else "#EF4444" if net < 0 else "#4A5568"
            gross_color = "#22C55E" if gross > 0 else "#EF4444" if gross < 0 else "#4A5568"

            tk.Label(r, text=date_str, width=11, bg=bg, fg="#CBD5E1",
                     font=("Consolas", 9), anchor="center").pack(side="left", padx=1)
            tk.Label(r, text=str(trades) if trades else "--", width=6, bg=bg,
                     fg="#CBD5E1" if trades else "#334155",
                     font=("Consolas", 9), anchor="center").pack(side="left", padx=1)
            tk.Label(r, text=f"${gross:+,.2f}" if gross else "--", width=11, bg=bg,
                     fg=gross_color, font=("Consolas", 9), anchor="center").pack(side="left", padx=1)
            tk.Label(r, text=f"${fees:+,.2f}" if fees else "--", width=10, bg=bg,
                     fg="#94A3B8" if fees else "#334155",
                     font=("Consolas", 9), anchor="center").pack(side="left", padx=1)
            tk.Label(r, text=f"${net:+,.2f}" if net else "--", width=11, bg=bg,
                     fg=net_color, font=("Consolas", 9, "bold"), anchor="center").pack(side="left", padx=1)
            tk.Label(r, text=f"${bal:,.2f}", width=12, bg=bg, fg="#E2E8F0",
                     font=("Consolas", 9), anchor="center").pack(side="left", padx=1)

        # Totals row
        tot_bg = "#1A2332"
        tot_row = tk.Frame(scroll_frame, bg=tot_bg)
        tot_row.pack(fill="x", pady=(2, 0))
        tk.Label(tot_row, text="TOTAL", width=11, bg=tot_bg, fg="#E2E8F0",
                 font=("Consolas", 9, "bold"), anchor="center").pack(side="left", padx=1)
        tk.Label(tot_row, text="", width=6, bg=tot_bg).pack(side="left", padx=1)
        tk.Label(tot_row, text=f"${total_gross:+,.2f}", width=11, bg=tot_bg,
                 fg="#22C55E" if total_gross >= 0 else "#EF4444",
                 font=("Consolas", 9, "bold"), anchor="center").pack(side="left", padx=1)
        tk.Label(tot_row, text=f"${total_fees:+,.2f}", width=10, bg=tot_bg, fg="#94A3B8",
                 font=("Consolas", 9, "bold"), anchor="center").pack(side="left", padx=1)
        tk.Label(tot_row, text=f"${total_net:+,.2f}", width=11, bg=tot_bg,
                 fg="#22C55E" if total_net >= 0 else "#EF4444",
                 font=("Consolas", 9, "bold"), anchor="center").pack(side="left", padx=1)
        tk.Label(tot_row, text="", width=12, bg=tot_bg).pack(side="left", padx=1)

        # ── Fills Section ─────────────────────────────────────
        fills = data.get('fills', [])
        if fills:
            tk.Label(parent, text=f"Trade Fills ({len(fills)})", bg="#0A0E17", fg="#60A5FA",
                     font=("Consolas", 10, "bold"), anchor="w").pack(fill="x", padx=12, pady=(8, 0))

            fills_frame = tk.Frame(parent, bg="#0A0E17")
            fills_frame.pack(fill="both", expand=True, padx=8, pady=(2, 8))

            f_canvas = tk.Canvas(fills_frame, bg="#0A0E17", highlightthickness=0, height=150)
            f_scroll = tk.Scrollbar(fills_frame, orient="vertical", command=f_canvas.yview)
            f_inner = tk.Frame(f_canvas, bg="#0A0E17")
            f_inner.bind("<Configure>", lambda e: f_canvas.configure(scrollregion=f_canvas.bbox("all")))
            f_canvas.create_window((0, 0), window=f_inner, anchor="nw")
            f_canvas.configure(yscrollcommand=f_scroll.set)
            f_canvas.pack(side="left", fill="both", expand=True)
            f_scroll.pack(side="right", fill="y")

            # Fills header
            fhdr = tk.Frame(f_inner, bg="#151D2B")
            fhdr.pack(fill="x", pady=(0, 1))
            for col_name, col_w in [("Date", 80), ("Time", 65), ("Side", 40),
                                     ("Qty", 35), ("Contract", 70), ("Price", 80)]:
                tk.Label(fhdr, text=col_name, width=col_w // 7, bg="#151D2B", fg="#64748B",
                         font=("Consolas", 9, "bold"), anchor="center").pack(side="left", padx=1)

            for i, fill in enumerate(fills):
                bg = "#0D1320" if i % 2 == 0 else "#0A0E17"
                fr = tk.Frame(f_inner, bg=bg)
                fr.pack(fill="x")
                action_color = "#22C55E" if fill['action'] == 'Buy' else "#EF4444"
                tk.Label(fr, text=fill['date'], width=11, bg=bg, fg="#CBD5E1",
                         font=("Consolas", 9), anchor="center").pack(side="left", padx=1)
                tk.Label(fr, text=fill['time'], width=9, bg=bg, fg="#94A3B8",
                         font=("Consolas", 9), anchor="center").pack(side="left", padx=1)
                tk.Label(fr, text=fill['action'], width=5, bg=bg, fg=action_color,
                         font=("Consolas", 9, "bold"), anchor="center").pack(side="left", padx=1)
                tk.Label(fr, text=str(fill['qty']), width=5, bg=bg, fg="#CBD5E1",
                         font=("Consolas", 9), anchor="center").pack(side="left", padx=1)
                tk.Label(fr, text=fill['contract'], width=10, bg=bg, fg="#60A5FA",
                         font=("Consolas", 9), anchor="center").pack(side="left", padx=1)
                tk.Label(fr, text=f"{fill['price']:,.2f}", width=11, bg=bg, fg="#E2E8F0",
                         font=("Consolas", 9), anchor="center").pack(side="left", padx=1)

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
        "Lucid":             {"class_available": "CDP_SCRAPERS_AVAILABLE", "account_class": "LucidTradingAccount",
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
        if RELEASE_DISABLE_PROP_DASHBOARD_ACCESS:
            return

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
        if RELEASE_DISABLE_PROP_DASHBOARD_ACCESS:
            self.log("ℹ Prop firm dashboard access is disabled in this release", "WARN")
            return

        cfg = self._BROWSER_MONITORED_FIRMS.get(firm_name)
        if not cfg:
            # Case-insensitive fallback
            for _bk, _bv in self._BROWSER_MONITORED_FIRMS.items():
                if _bk.lower() == firm_name.lower():
                    cfg = _bv
                    break
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
                        acct_mapping = self._autofill_challenge_fees(firm_name, acct)
                        self._cached_acct_mappings[firm_name] = acct_mapping or {}
                        self._auto_detect_breached_accounts(firm_name, acct, acct_mapping=acct_mapping)
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
                acct_mapping = self._autofill_challenge_fees(firm_name, acct)
                self._cached_acct_mappings[firm_name] = acct_mapping or {}
                self._auto_detect_breached_accounts(firm_name, acct, acct_mapping=acct_mapping)
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
                self._cached_acct_mappings[firm_name] = acct_mapping or {}
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

            # Build lookup: account_no -> {amount, date, package}
            # First entry wins for billing_by_acct (preserves original fee under login key).
            # Last entry wins for billing_by_login (latest fee maps to current Tradovate account).
            # This handles resets: e.g. FundedNext login 946645337 has $139.04 (new) + $142.13 (reset).
            # The $139.04 stays under "946645337", while $142.13 maps to the active Tradovate account.
            billing_by_acct = {}
            billing_by_size = {}
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
                    # First entry wins — keeps oldest fee under the raw account_no key
                    if acct_no not in billing_by_acct:
                        billing_by_acct[acct_no] = info
                    # Extract numeric size from package string (e.g. "50000" from "Futures Legacy Challenge 50000 USD")
                    import re as _re
                    size_match = _re.search(r'(\d{4,})', pkg.replace(",", ""))
                    if size_match:
                        size_key = int(size_match.group(1))
                        if size_key not in billing_by_size:
                            billing_by_size[size_key] = dict(info)
                    # Last entry wins — latest fee maps to current active Tradovate account
                    billing_by_login[login_id] = dict(info)

            # Resolve billing login IDs to Tradovate account names via account mapping
            # This enriches billing_by_acct so matching by FNFT/TDFY/LFE account name works.
            # billing_by_login has the LATEST entry per login → maps to current active Tradovate account.
            for login_id, bill_info in billing_by_login.items():
                if login_id in acct_mapping:
                    tv_name = acct_mapping[login_id].get("tradovate_account_name")
                    if tv_name and tv_name not in billing_by_acct:
                        enriched = dict(bill_info)
                        enriched["tradovate_account_name"] = tv_name
                        billing_by_acct[tv_name] = enriched
                    if tv_name:
                        self.root.after(0, lambda lid=login_id, tv=tv_name, amt=bill_info["amount"]:
                            self.log(f"   🔗 Mapped billing login {lid} → {tv} (${amt:.2f})"))

            # Log challenge fees per account
            for acct_key, info in billing_by_acct.items():
                self.root.after(0, lambda a=acct_key, t=info["amount"]:
                    self.log(f"   💳 {a}: ${t:.2f}"))

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
                        changes.append(f"DatePurchased={matched['date']}")
                    # Also set Date Started from billing date when empty
                    existing_start = (ev.get("Date Started") or "").strip()
                    if not existing_start and matched["date"]:
                        ev["Date Started"] = matched["date"]
                        changes.append(f"DateStarted={matched['date']}")
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
                # Still compute per-firm summary even when no evals updated
                total_fees, total_payouts, records = self._compute_firm_billing(
                    firm_name, account, billing)
                self._firm_billing_summary[firm_name] = {
                    "total_fees": total_fees, "total_payouts": total_payouts, "records": records}
                self.root.after(0, lambda f=firm_name, tf=total_fees, tp=total_payouts:
                    self.log(f"📊 {f} Summary — Total Fees: ${tf:.2f} | Total Payouts: ${tp:.2f}"))
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
                "dropdown_options": {},
                "firm_billing": self._firm_billing_summary,
                "force_fields": ["Fee", "Date Purchased", "Date Started"],
            }

            try:
                response = _gzip_post(
                    f"{dashboard_url}/api/client/push",
                    payload,
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

            # ── Per-firm totals: aggregate challenge fees + payouts ──
            total_fees, total_payouts, records = self._compute_firm_billing(
                firm_name, account, billing)
            self._firm_billing_summary[firm_name] = {
                "total_fees": total_fees, "total_payouts": total_payouts, "records": records}

            self.root.after(0, lambda f=firm_name, tf=total_fees, tp=total_payouts:
                self.log(f"📊 {f} Summary — Total Fees: ${tf:.2f} | Total Payouts: ${tp:.2f}"))

            return acct_mapping

        except Exception as e:
            self.root.after(0, lambda err=str(e):
                self.log(f"⚠ {firm_name} billing auto-fill failed: {err}", "WARN"))
            return acct_mapping

    def _compute_firm_billing(self, firm_name, account, billing):
        """Compute per-firm total fees and payouts from scraped billing + payout data.
        Returns (total_fees, total_payouts, records)."""
        total_fees = sum(
            e.get("paid_amount_numeric", 0.0)
            for e in billing
            if (e.get("status") or "").strip().upper() == "APPROVED"
               and e.get("paid_amount_numeric", 0) > 0
        )
        records = []
        for e in billing:
            if (e.get("status") or "").strip().upper() == "APPROVED" and e.get("paid_amount_numeric", 0) > 0:
                records.append({
                    "account_no": e.get("account_no", ""),
                    "amount": e.get("paid_amount_numeric", 0),
                    "date": e.get("date", ""),
                    "package": e.get("funding_package", ""),
                    "type": e.get("transition_type", ""),
                })
        total_payouts = 0.0
        try:
            if hasattr(account, 'get_payouts'):
                payouts = account.get_payouts()
                for p in (payouts or []):
                    for key in ("amount", "payout_amount", "netAmount", "total", "value"):
                        val = p.get(key)
                        if val is not None:
                            try:
                                total_payouts += abs(float(str(val).replace("$", "").replace(",", "")))
                            except (ValueError, TypeError):
                                pass
                            break
        except Exception:
            pass
        return total_fees, total_payouts, records

    # ── Real-time status polling ───────────────────────────────────────
    def _start_status_polling(self):
        """Start the 10-second real-time status polling loop.
        Uses Tradovate broker API to fetch live balances for all accounts."""
        if RELEASE_DISABLE_STATUS_POLL:
            self._status_poll_active = False
            return

        if self._status_poll_active:
            return  # already running
        self._status_poll_active = True
        self.root.after(0, lambda: self.log("🔄 Status polling started (every 5 min)"))
        # Run FIRST poll immediately, then schedule repeating every 5 min
        def _first_poll():
            try:
                self._poll_tradovate_balances()
            except Exception as e:
                self.root.after(0, lambda err=str(e):
                    self.log(f"⚠ First status poll error: {err}", "WARN"))
        threading.Thread(target=_first_poll, daemon=True).start()
        self.root.after(300_000, self._poll_account_status)

    def _poll_account_status(self):
        """Self-rescheduling timer — fetches Tradovate balances and updates P1 status."""
        if RELEASE_DISABLE_STATUS_POLL:
            return

        if not self._status_poll_active:
            return

        def _poll_all():
            try:
                self._poll_tradovate_balances()
            except Exception as e:
                self.root.after(0, lambda err=str(e):
                    self.log(f"⚠ Status poll error: {err}", "WARN"))

        threading.Thread(target=_poll_all, daemon=True).start()
        self.root.after(300_000, self._poll_account_status)

    def _poll_tradovate_balances(self):
        """Fetch live balances from Tradovate broker API and update P1/Status on evaluations."""
        if RELEASE_DISABLE_STATUS_POLL:
            return

        # ── 1. Gather all Tradovate account balances from broker connections ──
        tv_balances = {}  # {account_name: netLiq}
        for firm_name, conn in list(self._broker_connections.items()):
            tv_account = conn.get("account")
            if not tv_account:
                continue
            # Support both TradovateAccount (_api_fetch) and DOM-based stats
            if not hasattr(tv_account, '_api_fetch'):
                continue
            try:
                # First check if browser/driver is alive
                try:
                    _ = tv_account.driver.title
                except Exception:
                    self.root.after(0, lambda fn=firm_name:
                        self.log(f"⚠ Status poll: {fn} browser not accessible", "WARN"))
                    continue

                raw = tv_account._api_fetch("/account/list")
                if not raw or not isinstance(raw, list):
                    continue
                for acct in raw:
                    aid = acct.get('id')
                    aname = acct.get('name', '')
                    if not aid or not aname:
                        continue
                    snapshot = tv_account._api_fetch(
                        "/cashBalance/getCashBalanceSnapshot", "POST",
                        {"accountId": aid})
                    if snapshot and isinstance(snapshot, dict):
                        net_liq = snapshot.get('netLiq')
                        if net_liq is not None:
                            tv_balances[aname] = float(net_liq)
            except Exception as e:
                self.root.after(0, lambda fn=firm_name, err=str(e):
                    self.log(f"⚠ Status poll: API error for {fn}: {err}", "WARN"))

        if not tv_balances:
            self.root.after(0, lambda: self.log("⚠ Status poll: no Tradovate balances fetched", "WARN"))
            return

        # Log Tradovate accounts on first poll only
        if not hasattr(self, '_poll_logged_tv_accounts'):
            self._poll_logged_tv_accounts = True
            self.root.after(0, lambda n=len(tv_balances), names=list(tv_balances.keys()):
                self.log(f"📊 Status poll: {n} Tradovate account(s): {names}"))

        # Build case-insensitive lookup
        tv_lower = {k.lower(): (k, v) for k, v in tv_balances.items()}

        # ── 2. Fetch evaluations from dashboard ──
        email = self.client_email_entry.get().strip()
        dashboard_url = self.url_entry.get().strip().rstrip('/')
        if not email or not dashboard_url:
            return

        try:
            r = requests.post(
                f"{dashboard_url}/api/client/data",
                json={"email": email},
                headers={"Content-Type": "application/json"},
                timeout=15)
            if r.status_code != 200:
                self.root.after(0, lambda s=r.status_code:
                    self.log(f"⚠ Status poll: dashboard returned HTTP {s}", "WARN"))
                return
            all_evals = r.json().get("evaluations", [])
        except Exception as e:
            # Only log dashboard connection errors once to avoid spam
            if not getattr(self, '_poll_dashboard_err_logged', False):
                self._poll_dashboard_err_logged = True
                self.root.after(0, lambda err=str(e):
                    self.log(f"⚠ Status poll: dashboard not reachable (will retry silently)", "WARN"))
            return

        # Dashboard is reachable — reset error flag
        self._poll_dashboard_err_logged = False

        if not all_evals:
            return

        # ── 3. Match evaluations to Tradovate balances and compute status ──
        any_changed = False
        for ev in all_evals:
            if not ev or ev.get("_deleted"):
                continue

            acct_challenge = (ev.get("Account #") or "").strip()
            acct_funded = (ev.get("Account #.1") or "").strip()
            current_p1 = (ev.get("Status P1") or "").strip().lower()
            current_status = (ev.get("Status") or "").strip().lower()

            # Determine which account and field to check
            has_funded = bool(acct_funded)
            if has_funded:
                acct_key = acct_funded
                status_field = "Status"
                current_check = current_status
            else:
                acct_key = acct_challenge
                status_field = "Status P1"
                current_check = current_p1

            if not acct_key:
                continue

            # Skip accounts already passed or failed
            if "pass" in current_check or any(kw in current_check for kw in ("fail", "breach", "delete", "closed", "ended", "lost")):
                continue

            # ── Find matching Tradovate balance ──
            acct_key_lower = acct_key.lower()
            match = tv_lower.get(acct_key_lower)
            if not match:
                # Try partial match (account name might be substring)
                for tv_name_lower, tv_pair in tv_lower.items():
                    if tv_name_lower in acct_key_lower or acct_key_lower in tv_name_lower:
                        match = tv_pair
                        break
            if not match:
                # Account not found on any connected Tradovate — mark as Failed
                miss_key = f"_miss_logged_{acct_key}"
                if not self._last_known_statuses.get(miss_key):
                    self._last_known_statuses[miss_key] = True
                    self.root.after(0, lambda a=acct_key, tvk=list(tv_balances.keys()):
                        self.log(f"   ⚠ No match for '{a}' in Tradovate accounts {tvk} → marking Fail"))
                if current_check not in ("fail", "failed", "breach", "delete", "deleted", "closed", "ended", "lost"):
                    ev[status_field] = "Fail"
                    any_changed = True
                    self.root.after(0, lambda a=acct_key, sf=status_field:
                        self.log(f"   ❌ {a}: {sf}='Fail' — not found on Tradovate"))
                continue

            tv_name_orig, bal = match

            # ── Get starting balance from Account Size ──
            size_str = (ev.get("Account Size") or "").replace("$", "").replace(",", "").strip().lower()
            if size_str.endswith("k"):
                start = float(size_str[:-1]) * 1000
            elif size_str.replace(".", "").isdigit():
                start = float(size_str)
            else:
                start = 50000.0

            # ── Get live targets from cached mapping if available ──
            canonical_firm = self._FIRM_MAP.get(ev.get("Prop Firm", ""), ev.get("Prop Firm", ""))
            phase = "Funded" if has_funded else "Challenge"
            live_target = None
            live_min_eq = None
            for _fn, mapping in self._cached_acct_mappings.items():
                for _mk, info in mapping.items():
                    tv_name = info.get("tradovate_account_name", "")
                    if tv_name and (tv_name.lower() in acct_key_lower or acct_key_lower in tv_name.lower()):
                        live_target = info.get("profit_target")
                        live_min_eq = info.get("min_equity")
                        if info.get("starting_balance"):
                            try:
                                start = float(info["starting_balance"])
                            except (ValueError, TypeError):
                                pass
                        break
                if live_target is not None:
                    break

            # ── Compute status ──
            # Use profit targets and min equity from _PROFIT_TARGETS table.
            # Only mark Failed if balance <= minimum equity limit.
            # Only mark Pass if balance >= start + profit target.
            # Otherwise In Progress (if balance moved) or skip.
            computed = None
            try:
                # Get profit target and min equity for this firm/phase
                pt_target = None
                pt_min_eq = None

                # First try live targets from cached prop firm mapping
                if live_target is not None:
                    pt_target = float(live_target)
                if live_min_eq is not None:
                    pt_min_eq = float(live_min_eq)

                # Fallback to hardcoded profit targets table
                if pt_target is None and self.prop_firm_mgr:
                    targets = self.prop_firm_mgr._PROFIT_TARGETS.get(canonical_firm, {})
                    phase_key = "Challenge" if phase == "Challenge" else "Funded"
                    t = targets.get(phase_key)
                    if t is not None:
                        pt_target = float(t)

                # Determine status
                if pt_min_eq is not None and bal <= pt_min_eq:
                    computed = "Fail"
                elif pt_target is not None and bal >= (start + pt_target):
                    computed = "Pass"
                elif abs(bal - start) > 0.50:
                    computed = "In Progress"
                # else: balance hasn't moved, skip
            except (ValueError, TypeError):
                continue

            if not computed:
                continue

            # Set the status on the eval
            if computed.lower() != current_check:
                ev[status_field] = computed
                any_changed = True
                self.root.after(0, lambda a=acct_key, c=computed, b=bal, s=start:
                    self.log(f"   📝 {a}: {c} (bal=${b:,.2f}, start=${s:,.0f})"))

        # ── 4. Always push all evals so dashboard stays in sync ──
        if not any_changed:
            return

        payload = {
            "email": email,
            "evaluations": all_evals,
            "statistics": {},
            "dropdown_options": {},
            "force_fields": ["Status P1", "Status"],
        }
        try:
            resp = requests.post(
                f"{dashboard_url}/api/client/push",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30)
            if resp.status_code == 200:
                rj = resp.json()
                if rj.get("status") == "success":
                    self.root.after(0, lambda: self.log(f"✅ Status poll: synced to dashboard"))
                else:
                    self.root.after(0, lambda m=rj.get('message', '?'):
                        self.log(f"⚠ Status poll push rejected: {m}", "WARN"))
            else:
                self.root.after(0, lambda s=resp.status_code, t=resp.text[:200]:
                    self.log(f"⚠ Status poll push HTTP {s}: {t}", "WARN"))
        except Exception as e:
            self.root.after(0, lambda err=str(e):
                self.log(f"⚠ Status poll push error: {err}", "WARN"))

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

                # ── Determine account status: Fail / Pass / In Progress ──
                breached = matched_info.get("breached")
                acct_display = acct_challenge or acct_funded
                changes = []

                # Detect current phase for this eval
                has_funded_acct = bool(acct_funded)
                if has_funded_acct:
                    phase_for_status = "Funded"
                    status_field = "Status"
                    current_status_check = current_status
                else:
                    phase_for_status = "Challenge"
                    status_field = "Status P1"
                    current_status_check = current_status_p1

                # Skip if already marked with a terminal status
                if any(kw in current_status_check for kw in self._INACTIVE_KEYWORDS):
                    self.root.after(0, lambda: self.log(f"🔍 Status check: already inactive, skipping"))
                    continue

                if breached and breached != 0:
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

                    ev[status_field] = "Fail"
                    changes.append(f"{status_field}='Fail'")
                    breached_count += 1
                    self.root.after(0, lambda a=acct_display, c=", ".join(changes):
                        self.log(f"   🚫 BREACHED: {a} → {c}"))
                elif self.prop_firm_mgr:
                    # ── Balance-based auto-status: Pass / In Progress / Fail ──
                    # Prefer live profit_target / min_equity from dashboard API
                    acct_balance = matched_info.get("balance")
                    acct_starting = matched_info.get("starting_balance") or matched_info.get("initial_balance")
                    live_target = matched_info.get("profit_target")
                    live_min_eq = matched_info.get("min_equity")
                    if acct_balance is not None:
                        try:
                            bal = float(acct_balance)
                            start = float(acct_starting) if acct_starting else 50000.0

                            if live_min_eq is not None or live_target is not None:
                                # ── Use live values from prop firm dashboard ──
                                min_eq = float(live_min_eq) if live_min_eq is not None else None
                                target = float(live_target) if live_target is not None else None

                                if min_eq is not None and bal < min_eq:
                                    computed = "Fail"
                                elif target is not None and bal >= (start + target):
                                    computed = "Pass"
                                elif abs(bal - start) > 0.50:
                                    # Balance differs from starting → a trade was placed
                                    computed = "In Progress"
                                elif min_eq is not None and target is not None:
                                    computed = "In Progress"
                                else:
                                    computed = self.prop_firm_mgr.compute_account_status(
                                        canonical_firm, phase_for_status, bal, start,
                                        breached=False)
                            else:
                                # ── No live data — fall back to hardcoded targets ──
                                computed = self.prop_firm_mgr.compute_account_status(
                                    canonical_firm, phase_for_status, bal, start,
                                    breached=False)

                            # If balance is exactly the starting balance, keep "Not Started"
                            if computed == "In Progress" and abs(bal - start) < 0.50:
                                if current_status_check in ("not started", ""):
                                    computed = None  # no change — no trade placed yet

                            # Only update if status actually changed
                            last_key = f"{acct_display}_{status_field}"
                            last_known = self._last_known_statuses.get(last_key)
                            if computed and computed.lower() != current_status_check and computed != last_known:
                                self._last_known_statuses[last_key] = computed
                                if computed == "Pass":
                                    ev[status_field] = "Pass"
                                    changes.append(f"{status_field}='Pass'")
                                    self.root.after(0, lambda a=acct_display, b=bal, s=start:
                                        self.log(f"   ✅ PASS: {a} — balance=${b:,.2f} (start=${s:,.0f})"))
                                elif computed == "In Progress":
                                    ev[status_field] = "In Progress"
                                    changes.append(f"{status_field}='In Progress'")
                                    self.root.after(0, lambda a=acct_display, b=bal, s=start:
                                        self.log(f"   🔄 IN PROGRESS: {a} — balance=${b:,.2f} (start=${s:,.0f})"))
                                elif computed == "Fail":
                                    ev[status_field] = "Fail"
                                    changes.append(f"{status_field}='Fail'")
                                    breached_count += 1
                                    self.root.after(0, lambda a=acct_display, b=bal, s=start:
                                        self.log(f"   🚫 FAIL: {a} — balance=${b:,.2f} (start=${s:,.0f})"))
                        except (ValueError, TypeError) as _e:
                            self.root.after(0, lambda a=acct_display, b=acct_balance, err=str(_e):
                                self.log(f"⚠ {a}: couldn't parse balance '{b}': {err}", "WARN"))

                if changes:
                    updated_evals.append(ev)

            status_updates = len(updated_evals)
            if not status_updates:
                self.root.after(0, lambda:
                    self.log(f"🌐 {firm_name}: No status changes detected"))
                return

            self.root.after(0, lambda c=status_updates, b=breached_count:
                self.log(f"🌐 {firm_name}: {c} status update(s) ({b} breached) — pushing to dashboard..."))

            # Push to dashboard
            email = self.client_email_entry.get().strip()
            dashboard_url = self.url_entry.get().strip().rstrip('/')
            if not email or not dashboard_url:
                return

            payload = {
                "email": email,
                "evaluations": all_evals,
                "statistics": {},
                "dropdown_options": {},
                "force_fields": ["Status P1", "Status"],
            }

            try:
                response = _gzip_post(
                    f"{dashboard_url}/api/client/push",
                    payload,
                    timeout=30
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        self.root.after(0, lambda c=status_updates, b=breached_count:
                            self.log(f"✅ Auto-status: {c} update(s) ({b} failed) → synced to dashboard"))
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

    def _platform_for_firm(self, firm_name, default=None):
        """Resolve the trading platform (TopStepX / Tradovate) for a prop firm.

        Routing follows the BLUEPRINT, not a substring of the free-text
        dashboard label, so firms like 'TopStep RTP' (or any label that
        does not literally contain 'topstep') still route to the platform
        their blueprint is keyed for. Order of resolution:

          1. Literal 'topstep' in the name  → TopStepX (fast path).
          2. Resolve a blueprint code via _FIRM_MAP (case/format-insensitive),
             a direct firm_blueprints key, or a fuzzy contains match.
          3. Mapped code in the TopStep family → TopStepX.
          4. Inspect the blueprint's key namespace: any topstepx_* field →
             TopStepX, any tradovate_* field → Tradovate.
          5. Fall back to the configured default broker.
        """
        if default is None:
            default = self.broker_var.get()
        name = (firm_name or "").strip()
        if not name:
            return default

        # 1. Literal heuristic — fast path, preserves prior behaviour.
        if "topstep" in name.lower():
            return "TopStepX"

        # 2. Resolve to a blueprint firm code.
        norm = name.lower().replace("_", " ").replace("-", " ").strip()
        fc = self._FIRM_MAP.get(name)
        if not fc:
            for k, v in self._FIRM_MAP.items():
                if k.lower().replace("_", " ").replace("-", " ").strip() == norm:
                    fc = v
                    break

        bp = None
        blueprints = getattr(self.prop_firm_mgr, "firm_blueprints", {}) if self.prop_firm_mgr else {}
        if fc and fc in blueprints:
            bp = blueprints[fc]
        elif name in blueprints:
            fc, bp = name, blueprints[name]
        else:
            for bk, bv in blueprints.items():
                bkn = bk.lower().replace("_", " ").replace("-", " ").strip()
                if bkn == norm or (len(norm) >= 3 and (norm in bkn or bkn in norm)):
                    fc, bp = bk, bv
                    break

        # 3. Mapped code clearly a TopStep family → TopStepX.
        if fc and fc.lower().startswith("topstep"):
            return "TopStepX"

        # 4. Inspect the blueprint's key namespace.
        if bp:
            for stage in bp.get("strategy_configs", {}).values():
                for size_cfg in stage.values():
                    keys = list(size_cfg.keys())
                    if any(k.startswith("topstepx_") for k in keys):
                        return "TopStepX"
                    if any(k.startswith("tradovate_") for k in keys):
                        return "Tradovate"

        # 5. Fall back to the configured default broker.
        return default

    def _get_broker_for_firm(self, firm_name):
        """Get the connected broker account for a specific prop firm."""
        conn = self._broker_connections.get(firm_name)
        if conn and conn.get("account"):
            return conn["account"]
        # If the firm has a row in broker connections but isn't connected, do NOT
        # fall back — it means the user chose not to connect this firm.
        if conn is not None:
            return None
        # Legacy fallback: only for setups without multi-firm broker panel.
        # Platform follows the resolved blueprint, not just a label substring.
        platform = self._platform_for_firm(firm_name)
        if platform == "TopStepX":
            return self.topstepx_account if self.topstepx_account else None
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
        # Assign in a deterministic order so balancing is reproducible
        for firm in sorted(firms):
            if firm not in firm_bias:
                # Diversify: pick the direction held by FEWER existing firms.
                # This prevents every firm from coincidentally landing on BUY.
                buys = sum(1 for d in firm_bias.values() if d == "buy")
                sells = sum(1 for d in firm_bias.values() if d == "sell")
                if buys > sells:
                    firm_bias[firm] = "sell"
                elif sells > buys:
                    firm_bias[firm] = "buy"
                else:
                    # Tie (or first firm) — random
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

        return {f: firm_bias.get(f, "buy") for f in firms}

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
        if not MT5_AVAILABLE:
            self.root.after(0, lambda: self.log("⚠ MetaTrader5 import unavailable — using random direction", "WARN"))
            return random.choice(["buy", "sell"])
        mt5_mod = mt5
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
                
    def _shutdown_broker_and_scraper_browsers(self):
        """Close Selenium broker sessions and CDP scrapers; quit CDP Chrome if we spawned it."""
        for _firm, conn in list(getattr(self, "_broker_connections", {}).items()):
            if not isinstance(conn, dict):
                continue
            acct = conn.get("account")
            if not acct:
                continue
            closer = getattr(acct, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass
            conn["account"] = None

        for _firm, acct in list(getattr(self, "_propfirm_browsers", {}).items()):
            if not acct:
                continue
            closer = getattr(acct, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass
            try:
                self._propfirm_browsers[_firm] = None
            except Exception:
                pass

        self.tradovate_account = None
        self.topstepx_account = None

        if shutdown_debug_chrome_spawned:
            try:
                shutdown_debug_chrome_spawned()
            except Exception:
                pass

    def _on_app_closing(self):
        try:
            self._status_poll_active = False
        except Exception:
            pass
        try:
            self._shutdown_broker_and_scraper_browsers()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        """Run the application."""
        self.root.mainloop()


def main():
    """Main entry point."""
    if GUI_AVAILABLE:
        app = TradeOpssAIApp()
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
