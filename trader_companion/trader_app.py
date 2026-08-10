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
    sys.path.insert(0, os.path.join(sys._MEIPASS, 'connectors'))
    # Add DLL search directory for bundled .pyd files (MetaTrader5 _core etc.)
    _mt5_dir = os.path.join(sys._MEIPASS, 'MetaTrader5')
    if os.path.isdir(_mt5_dir):
        os.add_dll_directory(sys._MEIPASS)
        os.add_dll_directory(_mt5_dir)
    os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ.get('PATH', '')
APP_VERSION = "1.11.6"  # Alpha Futures NQ-only blueprint cleanup + challenge consistency retune
RELEASE_DISABLE_STATUS_POLL = True
RELEASE_DISABLE_AUTO_STATUS_UPDATES = True
RELEASE_DISABLE_PROP_DASHBOARD_ACCESS = True
RELEASE_DISABLE_PUSH_BILLING = True
# M1 push feeds the dashboard's m1_bars table — the source of the dashboard
# market bias shown in the AI monitor. Disabling it makes bias=none.
RELEASE_DISABLE_M1_DASHBOARD_PUSH = False
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
        payoutN_trade1..2 (Apex)    -> _FD1.._FD2
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
    elif pk.startswith("payout") and "_trade" in pk:
        # Apex per-payout funded trades (payoutN_tradeM) round-trip as funded
        # legs so the connector's _FD\d+ parser still recognises them.
        n = pk.split("_trade")[-1].strip()
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
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional
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
    try:
        from trader_companion.signals.price_data import copy_rates_from_pos_cached
        mt5.copy_rates_from_pos = copy_rates_from_pos_cached
    except ImportError:
        try:
            from signals.price_data import copy_rates_from_pos_cached
            mt5.copy_rates_from_pos = copy_rates_from_pos_cached
        except ImportError:
            pass
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

# Structured/file logging so adjustment + account-selection diagnostics land in
# mt5_trading.log (the companion debug log) — not just the in-app GUI feed.
import logging
try:
    from trader_companion.audit_log import audit, ensure_mt5_trading_log_handler
except Exception:
    try:
        from audit_log import audit, ensure_mt5_trading_log_handler  # type: ignore
    except Exception:
        def audit(event, **fields):  # type: ignore
            try:
                logging.getLogger("AUDIT").info("[AUDIT] %s %s", event, fields)
            except Exception:
                pass
        def ensure_mt5_trading_log_handler(*_a, **_k):  # type: ignore
            return None
try:
    ensure_mt5_trading_log_handler()
except Exception:
    pass

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

try:
    from connectors.alphatrader_connector import AlphaTraderConnector
    ALPHATRADER_AVAILABLE = True
except Exception as _at_err:
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'connectors'))
        from alphatrader_connector import AlphaTraderConnector
        ALPHATRADER_AVAILABLE = True
        _at_err = None
    except Exception as _at_err2:
        ALPHATRADER_AVAILABLE = False
        AlphaTraderConnector = None
        _at_err = _at_err2
_ALPHATRADER_IMPORT_ERROR = str(_at_err) if not ALPHATRADER_AVAILABLE and '_at_err' in dir() and _at_err else None

try:
    from connectors.blackarrow_connector import BlackArrowConnector
    BLACKARROW_AVAILABLE = True
except Exception as _ba_err:
    try:
        from blackarrow_connector import BlackArrowConnector
        BLACKARROW_AVAILABLE = True
        _ba_err = None
    except Exception as _ba_err2:
        BLACKARROW_AVAILABLE = False
        BlackArrowConnector = None
        _ba_err = _ba_err2
_BLACKARROW_IMPORT_ERROR = str(_ba_err) if not BLACKARROW_AVAILABLE and '_ba_err' in dir() and _ba_err else None

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
    from trader_companion.signals.sma import get_sma_signal
    from trader_companion.signals.ema import get_ema_signal
    from trader_companion.signals.dmi import get_dmi_signal
    from trader_companion.signals.mfi import get_mfi_signal
    from trader_companion.signals.roc import get_roc_signal
    from trader_companion.signals.sar import get_sar_signal
    from trader_companion.signals.tsi import get_tsi_signal
    from trader_companion.signals.wr import get_wr_signal
    from trader_companion.signals.donchian_channel import get_donchian_channel_signal
    from trader_companion.signals.price_channel import get_price_channel_signal
    from trader_companion.signals.keltner_channel import get_keltner_channel_signal
    from trader_companion.signals.vortex import get_vortex_signal
    from trader_companion.signals.cmo import get_cmo_signal
    from trader_companion.signals.coppock_curve import get_coppock_curve_signal
    from trader_companion.signals.ultimate_oscillator import get_ultimate_oscillator_signal
    from trader_companion.signals.elder_ray import get_elder_ray_signal
    from trader_companion.signals.gator_oscillator import get_gator_oscillator_signal
    from trader_companion.signals.fractal import get_fractal_signal
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
        from signals.sma import get_sma_signal
        from signals.ema import get_ema_signal
        from signals.dmi import get_dmi_signal
        from signals.mfi import get_mfi_signal
        from signals.roc import get_roc_signal
        from signals.sar import get_sar_signal
        from signals.tsi import get_tsi_signal
        from signals.wr import get_wr_signal
        from signals.donchian_channel import get_donchian_channel_signal
        from signals.price_channel import get_price_channel_signal
        from signals.keltner_channel import get_keltner_channel_signal
        from signals.vortex import get_vortex_signal
        from signals.cmo import get_cmo_signal
        from signals.coppock_curve import get_coppock_curve_signal
        from signals.ultimate_oscillator import get_ultimate_oscillator_signal
        from signals.elder_ray import get_elder_ray_signal
        from signals.gator_oscillator import get_gator_oscillator_signal
        from signals.fractal import get_fractal_signal
        SIGNALS_AVAILABLE = True
    except ImportError:
        SIGNALS_AVAILABLE = False
        get_rsi_signal = None

# ML + deep-learning direction engine (gradient boosting + neural net).
# Optional: requires scikit-learn; the AI degrades gracefully without it.
try:
    from trader_companion.signals import ml_direction as ml_direction_engine
    ML_DIRECTION_AVAILABLE = ml_direction_engine.SKLEARN_AVAILABLE
except ImportError:
    try:
        from signals import ml_direction as ml_direction_engine
        ML_DIRECTION_AVAILABLE = ml_direction_engine.SKLEARN_AVAILABLE
    except ImportError:
        ml_direction_engine = None
        ML_DIRECTION_AVAILABLE = False

# Automatic indicator-parameter optimizer (backtests voter settings on
# recent bars at startup and applies the best ones to the live vote).
try:
    from trader_companion.signals import indicator_optimizer
    INDICATOR_OPT_AVAILABLE = True
except ImportError:
    try:
        from signals import indicator_optimizer
        INDICATOR_OPT_AVAILABLE = True
    except ImportError:
        indicator_optimizer = None
        INDICATOR_OPT_AVAILABLE = False

# Self-learning prediction journal (verifies ML predictions vs the real
# market move + TP/SL simulation; feeds the adaptive confidence gate).
try:
    from trader_companion.signals import prediction_tracker
    PREDICTION_TRACKER_AVAILABLE = True
except ImportError:
    try:
        from signals import prediction_tracker
        PREDICTION_TRACKER_AVAILABLE = True
    except ImportError:
        prediction_tracker = None
        PREDICTION_TRACKER_AVAILABLE = False

# Tomorrow trade paper simulator (day-placeholder → blueprint TP/SL replay).
try:
    from trader_companion.signals import trade_simulator
    TRADE_SIMULATOR_AVAILABLE = True
except ImportError:
    try:
        from signals import trade_simulator
        TRADE_SIMULATOR_AVAILABLE = True
    except ImportError:
        trade_simulator = None
        TRADE_SIMULATOR_AVAILABLE = False

try:
    from trader_companion.signals import strategy_tester_chart
    STRATEGY_TESTER_AVAILABLE = True
except ImportError:
    try:
        from signals import strategy_tester_chart
        STRATEGY_TESTER_AVAILABLE = True
    except ImportError:
        strategy_tester_chart = None
        STRATEGY_TESTER_AVAILABLE = False

try:
    from trader_companion.signals import trade_learning_journal
    TRADE_LEARNING_AVAILABLE = True
except ImportError:
    try:
        from signals import trade_learning_journal
        TRADE_LEARNING_AVAILABLE = True
    except ImportError:
        trade_learning_journal = None
        TRADE_LEARNING_AVAILABLE = False

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

    Tradovate uses a single-digit year (e.g. NQU6 = NQ Sep 2026).
    TopStepX expects a two-digit year (e.g. NQU26).

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


# mt5.initialize() must never run concurrently: two racing calls (UI auto-connect,
# signal threads, margin worker) make one launch terminal64.exe while the other
# attaches mid-startup → (-10003, "IPC initialize failed, Pipe server didn't
# answer in 60 sec"). All initialize/login paths take this lock first.
_MT5_INIT_LOCK = threading.Lock()


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

        with _MT5_INIT_LOCK:
            return self._connect_mt5_locked(login, password, server, terminal_path)

    def _connect_mt5_locked(self, login=None, password=None, server=None, terminal_path=None):
        # Another thread may have finished connecting while we waited on the lock.
        if self.connected and mt5.terminal_info():
            return True, "Already connected to MT5"

        init_params = {}
        if terminal_path:
            init_params['path'] = terminal_path

        ok = mt5.initialize(**init_params)
        if not ok:
            error = mt5.last_error()
            # -10003 IPC timeout usually means the terminal is mid-startup or the
            # previous IPC pipe went stale — shut down and retry once.
            try:
                mt5.shutdown()
            except Exception:
                pass
            time.sleep(2)
            ok = mt5.initialize(**init_params)
            if not ok:
                error = mt5.last_error()
                return False, (
                    f"MT5 initialization failed: {error}\n"
                    "Tips: start the MT5 terminal manually and let it load fully, "
                    "kill any stuck terminal64.exe in Task Manager, and run MT5 "
                    "and this app at the same privilege level (both normal or both admin).")

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
        try:
            from trader_companion.mt5_market_feed import stop_mt5_market_feed
            stop_mt5_market_feed()
        except Exception:
            pass
        try:
            from trader_companion.m1_bars_sync import stop_m1_dashboard_sync
            stop_m1_dashboard_sync()
        except Exception:
            pass
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
                "time": datetime.fromtimestamp(pos.time, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                "time_raw": int(pos.time),
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
                "time": datetime.fromtimestamp(deal.time, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                "time_raw": int(deal.time),
                "time_msc": int(getattr(deal, "time_msc", 0) or 0),
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

    ML_MODE_PASSWORD = "tradeopss@123"

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
        "Funded Futures Family": "#7C3AED",
        "LucidMaxx":        "#8B5CF6",
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
                if CTK_AVAILABLE:
                    # CTkLabel needs CTkImage (scales correctly on HighDPI)
                    self._section_logo = ctk.CTkImage(
                        light_image=_small, dark_image=_small, size=(18, 18))
                else:
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
        self._auto_push_first_run = True
        self._push_lock = threading.Lock()
        self._push_in_progress = False
        self._push_pending = False
        self.client_info = None
        self._hedge_account_profile = {}

        # Auto-trade scheduler state
        self.auto_trade_enabled = False
        self.auto_trade_thread = None
        self._auto_trade_stop = threading.Event()
        self._auto_trade_batch_event = threading.Event()
        self._auto_trade_scheduled_dt = None
        self._auto_trade_waiting_gate = False

        # AI decision monitor — real-time trace of every AI decision
        self._ai_events = deque(maxlen=500)
        self._ai_monitor_win = None
        self._ai_monitor_text = None
        self._trade_learning_win = None
        self._strategy_tester_win = None
        self._stester_play_after = None
        # Diagnostics auto-run every 60s app-wide (monitor open or not)
        self._start_ai_diagnostics_loop()

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
                    msg = f"Server error ({response.status_code})"
                    try:
                        api_msg = response.json().get("message")
                        if api_msg:
                            msg = api_msg
                    except Exception:
                        pass
                    self.root.after(0, lambda m=msg: self._login_fail(m))
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

        # ── Row 0: Compact toolbar (Auto-Push + Auto-Trade) ──
        toolbar = ctk.CTkFrame(self._live_view, fg_color=self.C_BG_SEC, corner_radius=8,
                               border_width=1, border_color=self.C_BORDER, height=38)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        toolbar.pack_propagate(False)

        self.push_btn_live = None  # manual push removed; auto-sync only
        self.auto_btn_live = self._ctk_button(toolbar, text="▶ Auto-Push",
                                              command=self.toggle_auto_push,
                                              fg=self.C_ACCENT, hover=self.C_ACCENT_HV, width=100)
        self.auto_btn_live.pack(side="left", padx=(8, 4), pady=5)
        self.auto_push_status_var = tk.StringVar(value="Sync: off — press Auto-Push to start")
        ctk.CTkLabel(
            toolbar,
            textvariable=self.auto_push_status_var,
            font=("Segoe UI", 10),
            text_color=self.C_TEXT_DIM,
        ).pack(side="left", padx=(10, 8), pady=5)

        # Separator
        ctk.CTkFrame(toolbar, width=1, fg_color=self.C_BORDER).pack(side="left", fill="y", pady=6)

        self.auto_trade_btn = self._ctk_button(toolbar, text="▶ Auto-Trade",
                                               command=self._toggle_auto_trade,
                                               fg=self.C_ACCENT, hover=self.C_ACCENT_HV, width=110)
        self.auto_trade_btn.pack(side="left", padx=(8, 4), pady=5)

        self.auto_trade_immediate_var = tk.BooleanVar(value=False)
        self.ml_mode_var = tk.BooleanVar(value=False)
        # Off = classic funded SL (balance − lock). On = split payout day for
        # Tradeify only ($2k + profit cushion on trade 2+, per-leg signals).
        self.funded_split_payout_var = tk.BooleanVar(value=False)
        if CTK_AVAILABLE:
            ctk.CTkCheckBox(toolbar, text="Now", variable=self.auto_trade_immediate_var,
                            font=("Segoe UI", 9), text_color=self.C_TEXT_DIM,
                            fg_color=self.C_ACCENT, border_color=self.C_BORDER,
                            hover_color=self.C_ACCENT_HV, width=40,
                            checkbox_width=16, checkbox_height=16).pack(side="left", padx=(0, 6), pady=5)
            ctk.CTkCheckBox(toolbar, text="ML Signals", variable=self.ml_mode_var,
                            command=self._toggle_ml_mode,
                            font=("Segoe UI", 9), text_color="#f59e0b",
                            fg_color=self.C_ACCENT, border_color=self.C_BORDER,
                            hover_color=self.C_ACCENT_HV, width=90,
                            checkbox_width=16, checkbox_height=16).pack(side="left", padx=(0, 6), pady=5)
            ctk.CTkCheckBox(toolbar, text="Split (Tradeify)", variable=self.funded_split_payout_var,
                            font=("Segoe UI", 9), text_color="#a78bfa",
                            fg_color=self.C_ACCENT, border_color=self.C_BORDER,
                            hover_color=self.C_ACCENT_HV, width=95,
                            checkbox_width=16, checkbox_height=16).pack(side="left", padx=(0, 6), pady=5)
            ctk.CTkLabel(toolbar, text="🎲 random/firm",
                         font=("Segoe UI", 9), text_color=self.C_TEXT_DIM).pack(side="left", padx=(0, 6), pady=5)

        self.ai_monitor_btn = self._ctk_button(toolbar, text="🧠 AI Monitor",
                                               command=self._open_ai_monitor,
                                               fg="#1e293b", hover="#334155", width=100)
        self.ai_monitor_btn.pack(side="right", padx=(4, 8), pady=5)

        self.trade_history_btn = self._ctk_button(toolbar, text="📜 Trade History",
                                                  command=self._open_trade_learning_history,
                                                  fg="#1e293b", hover="#334155", width=110)
        self.trade_history_btn.pack(side="right", padx=(4, 0), pady=5)

        self.strategy_tester_btn = self._ctk_button(
            toolbar, text="📈 Strategy Tester",
            command=self._open_strategy_tester,
            fg="#1e293b", hover="#334155", width=120)
        self.strategy_tester_btn.pack(side="right", padx=(4, 0), pady=5)

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

        self._signal_strength_var = tk.StringVar(value="Signal: —")
        ctk.CTkLabel(trades_bezel, textvariable=self._signal_strength_var,
                     font=("Consolas", 9, "bold"), text_color="#A78BFA").pack(
            side="left", padx=(0, 12))

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
                         ("PHASE", 88), ("NEXT", 100), ("SIGNAL", 72)]:
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
                    self._restart_m1_sync_for_target()
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
                self._restart_m1_sync_for_target()

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
        """Add a message to the log, live activity display, and mt5_trading.log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        try:
            from trader_companion.audit_log import log_gui
            log_gui(message, level)
        except Exception:
            try:
                from audit_log import log_gui  # type: ignore
                log_gui(message, level)
            except Exception:
                pass
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
                                            def _fill_creds(l=ha_login, p=ha_pass, s=ha_server, profile=ha):
                                                self._hedge_account_profile = dict(profile or {})
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
                            self.root.after(400, self._auto_connect_mt5)
                            # Auto-push is OFF by default — user starts it
                            # with the toolbar Auto-Push toggle.
                            self.root.after(2000, lambda: self._update_auto_push_status(
                                "Sync: off — press Auto-Push to start"))
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
                            reason = "account inactive" if data.get("status") == "inactive" else "client lookup failed"
                            self.stop_auto_push(reason)
                            self.log(f"❌ Lookup failed: {msg}", "ERROR")
                        self.root.after(0, _on_not_found)
                else:
                    error_msg = f"API Error: {response.status_code}"
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("message", error_msg)
                        inactive = error_data.get("status") == "inactive"
                    except:
                        inactive = False
                    def _on_error(msg=error_msg, inactive=inactive):
                        self.hierarchy_var.set(f"❌ {msg}")
                        if CTK_AVAILABLE:
                            self.hierarchy_label.configure(text_color='#dc2626')
                        else:
                            self.hierarchy_label.configure(foreground='#dc2626')
                        self.client_info = None
                        self.stop_auto_push("account inactive" if inactive else "client lookup failed")
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
        
    def _start_m1_feed_after_mt5_connect(self) -> None:
        """Start local M1 poller (signal cache) + dashboard Postgres sync."""
        try:
            from trader_companion.mt5_market_feed import (
                start_mt5_market_feed,
                format_market_feed_status_for_user,
            )

            started = start_mt5_market_feed(["USTECH", "ustech"])
            line = format_market_feed_status_for_user()
            level = "INFO" if started else "WARN"
            self.log(f"📡 {line}", level)
            print(f"[MT5Feed] {line}")
        except Exception as exc:
            self.log(f"📡 M1 feed failed: {exc}", "WARN")
            print(f"[MT5Feed] failed: {exc}")

        # NOTE: ML training is deliberately NOT started here — it kicks off
        # together with the indicator vote once ALL brokers (Tradovate /
        # TopStepX) are connected and the accounts are ready to trade
        # (see _check_all_brokers_ready).

        # Indicator-parameter optimization DOES run at startup: it only
        # calibrates voter settings against recent bars (no signals fired),
        # so the vote uses the best-performing parameters by trading time.
        if INDICATOR_OPT_AVAILABLE and indicator_optimizer is not None:
            try:
                indicator_optimizer.ensure_optimized_async("ustech", log_fn=self._opt_log)
            except Exception:
                pass

        self._start_m1_dashboard_sync()

    def _restart_m1_sync_for_target(self) -> None:
        """Point M1 bar sync at the newly selected dashboard URL (localhost vs production)."""
        try:
            from trader_companion.m1_bars_sync import stop_m1_dashboard_sync

            stop_m1_dashboard_sync()
        except Exception:
            pass
        self._start_m1_dashboard_sync()

    def _start_m1_dashboard_sync(self) -> None:
        """Push shared Plexy USTECH M1 OHLC to dashboard (gap + backfill + live)."""
        if RELEASE_DISABLE_M1_DASHBOARD_PUSH:
            self.log("📊 M1 dashboard push disabled — bars stay local (feed/indicators/ML unaffected)", "INFO")
            return
        try:
            url = self.url_entry.get().strip().rstrip("/")
            email = self.client_email_entry.get().strip().lower()
            if not url or not email:
                return

            from trader_companion.m1_bars_sync import is_plexy_trade_mt5, start_m1_dashboard_sync

            if not is_plexy_trade_mt5():
                self.log(
                    "📊 M1 DB sync skipped — PlexyTrade only (shared USTECH market feed)",
                    "INFO",
                )
                return

            def _sync_log(msg, level="INFO"):
                try:
                    self.root.after(0, lambda m=msg, lv=level: self.log(f"📊 M1 DB: {m}", lv))
                except Exception:
                    pass

            start_m1_dashboard_sync(url, email, "ustech", log_fn=_sync_log, force=True)
            self.log("📊 M1 shared Plexy USTECH sync started (gap + backfill + live)", "INFO")
        except Exception as exc:
            self.log(f"📊 M1 dashboard sync failed: {exc}", "WARN")

    def _log_market_feed_status(self, delay_ms: int = 2500) -> None:
        """Log M1 feed cache status after first poll cycle."""
        def _emit():
            try:
                from trader_companion.mt5_market_feed import format_market_feed_status_for_user
                line = format_market_feed_status_for_user()
            except Exception as exc:
                line = f"M1 feed: {exc}"
            level = "INFO" if "active" in line else "WARN"
            self.log(f"📡 {line}", level)

        try:
            self.root.after(delay_ms, _emit)
        except Exception:
            _emit()

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
                self._start_m1_feed_after_mt5_connect()
                self._log_market_feed_status()
            self.log(msg, "INFO" if success else "ERROR")

    def _auto_connect_mt5(self):
        """Auto-connect to MT5 once credentials are present (e.g. right after the
        dashboard auto-fills them). Runs on the UI thread so MT5 + M1 feed share one thread."""
        try:
            if getattr(self.pusher, "connected", False):
                # Already connected — just make sure the button reflects it.
                try:
                    self.mt5_btn.configure(text="Disconnect MT5")
                except Exception:
                    pass
                self._start_m1_feed_after_mt5_connect()
                self._log_market_feed_status()
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

        def _connect_on_ui(lg=login, pw=password, sv=server):
            try:
                success, msg = self.pusher.connect_mt5(lg, pw, sv)
            except Exception as e:
                success, msg = False, f"MT5 auto-connect error: {e}"
            self._mt5_autoconnect_inflight = False
            try:
                self.mt5_btn.configure(
                    state="normal",
                    text="Disconnect MT5" if success else "Connect MT5",
                )
            except Exception:
                pass
            self.log(("✅ " if success else "⚠ ") + msg, "INFO" if success else "ERROR")
            if success:
                self._start_m1_feed_after_mt5_connect()
                self._log_market_feed_status()

        self.root.after(0, _connect_on_ui)

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
                        acct_challenge = self._cell(ev.get("Account #"))
                        acct_funded = self._cell(ev.get("Account #.1"))
                        existing_fee = self._cell(ev.get("Fee"))
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
                            if not self._cell(ev.get("Date Purchased")) and matched["date"]:
                                ev["Date Purchased"] = matched["date"]
                            if not self._cell(ev.get("Date Started")) and matched["date"]:
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

    def push_data(self, full_prop_refresh=False):
        """Push data to dashboard - NO API KEY REQUIRED (auto-sync only in v1.6.6+).

        full_prop_refresh=True on the first auto-sync run re-scrapes prop firm billing
        and blocks on Tradovate prop-day fetch; later runs use cached billing.
        """
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
        
        self.log(f"📤 Auto-sync {client_name}...")
        self._update_auto_push_status("Sync: pushing…")
        self.status_var.set("Pushing data...")

        def _do_push():
            should_run_follow_up = False
            try:
                self._push_data_worker(dashboard_url, email, client_name, full_prop_refresh)
            finally:
                with self._push_lock:
                    self._push_in_progress = False
                    should_run_follow_up = self._push_pending
                    self._push_pending = False

                if should_run_follow_up:
                    try:
                        self.root.after(0, lambda: self.log("🔁 Running queued push"))
                        self.root.after(0, lambda: self.push_data(full_prop_refresh=full_prop_refresh))
                    except Exception:
                        pass
                else:
                    self.root.after(0, lambda: self._update_auto_push_status("Sync: active"))

        threading.Thread(target=_do_push, daemon=True).start()

    def _update_auto_push_status(self, text: str) -> None:
        try:
            if hasattr(self, "auto_push_status_var"):
                self.auto_push_status_var.set(text)
        except Exception:
            pass

    def _update_auto_push_button(self) -> None:
        """Sync the toolbar Auto-Push toggle with the current state."""
        btn = getattr(self, "auto_btn_live", None)
        if not btn:
            return
        try:
            if self.auto_push_enabled:
                btn.configure(text="⏹ Stop Push")
                if CTK_AVAILABLE:
                    btn.configure(fg_color='#dc2626', hover_color='#b91c1c')
            else:
                btn.configure(text="▶ Auto-Push")
                if CTK_AVAILABLE:
                    btn.configure(fg_color=self.C_ACCENT, hover_color=self.C_ACCENT_HV)
        except Exception:
            pass

    def toggle_auto_push(self):
        """Manual toolbar toggle for the background auto-sync."""
        if self.auto_push_enabled:
            self.stop_auto_push("manual toggle")
        else:
            if not self.client_info:
                messagebox.showerror("Error", "Please lookup the client first")
                return
            self.start_auto_push()

    def start_auto_push(self) -> None:
        """Start background auto-sync (manual: toolbar Auto-Push toggle only)."""
        if self.auto_push_enabled:
            return
        if not self.client_info:
            self._update_auto_push_status("Sync: waiting for client lookup")
            return

        self.last_deal_count = 0
        self.last_deal_ticket = 0
        self._auto_push_first_run = True
        self.auto_push_enabled = True
        self.log(
            "🔄 Auto-sync started — dashboard updates on new trades "
            "(MT5 TimeCurrent vs Nairobi timezone on each push)"
        )
        self._update_auto_push_status("Sync: active (watching trades)")
        self._update_auto_push_button()
        self.auto_push_thread = threading.Thread(target=self.auto_push_loop, daemon=True)
        self.auto_push_thread.start()

    def stop_auto_push(self, reason: str = "") -> None:
        """Stop background auto-sync."""
        if not self.auto_push_enabled:
            return
        self.auto_push_enabled = False
        msg = "Auto-sync stopped"
        if reason:
            msg += f" ({reason})"
        self.log(msg)
        self._update_auto_push_status("Sync: stopped")
        self._update_auto_push_button()

    # Per-login cache for the 365-day farming history:
    #   { login_key: (fetched_at_epoch, [deals]) }
    # TTL is 5 minutes — auto-push fires frequently so we avoid re-scanning MT5 history
    # on every tick.  Only the last-24h slice is always fetched fresh.
    _FA_HISTORY_CACHE_TTL = 300  # seconds
    # Stats tab trade history only — not used for hedge results / hedge days.
    TRADE_HISTORY_DAYS = 3650  # ~10y; max MT5 history depth for display

    # Tradovate MNQ farming history cache: { firm_name: (fetched_at_epoch, mnq_data) }
    # Fetching fills + balance logs is slow; reuse within the same TTL window.
    _TRADOVATE_FARMING_CACHE_TTL = 300  # seconds

    def _refresh_prop_billing_sync(self, _log):
        """Manual Push: synchronously re-scrape billing (fees & payouts) from every
        connected prop firm dashboard so firm_billing and the per-eval Fee/Date are
        fresh for the push that follows. Runs on the push worker's background thread.

        If no prop firm dashboard browser is connected, we push anyway and log a clear
        warning that billing was not refreshed (per configured behaviour)."""
        browsers = dict(getattr(self, "_propfirm_browsers", {}) or {})
        if not browsers:
            _log("⚠️ No prop firm dashboard connected — billing NOT refreshed "
                 "(pushing MT5 + cached prop data only)", "WARN")
            return

        if not hasattr(self, "_cached_acct_mappings"):
            self._cached_acct_mappings = {}

        for firm_name, account in browsers.items():
            try:
                _log(f"🔄 Refreshing {firm_name} billing for push...")
                acct_mapping = self._autofill_challenge_fees(firm_name, account)
                self._cached_acct_mappings[firm_name] = acct_mapping or {}
            except Exception as e:
                _log(f"⚠️ {firm_name}: billing refresh failed: {e}", "WARN")

    def _push_data_worker(self, dashboard_url, email, client_name, full_prop_refresh=False):
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

        # Stats tab trade history ONLY — dedicated full MT5 fetch, separate from hedge pipeline.
        _log(f"📜 Fetching trade history ({self.TRADE_HISTORY_DAYS}-day window) for Stats tab…")
        trade_history_raw = self.pusher.get_deals(days=self.TRADE_HISTORY_DAYS) or []
        trade_history_deals = []
        for deal in trade_history_raw:
            d_type = str(deal.get('type', '')).upper()
            if d_type in ['BALANCE', 'CREDIT', '2', '3', 'CHARGE', 'CORRECTION', 'BONUS']:
                _bal_comment_l = str(deal.get('comment', '') or '').strip().lower()
                if ('internal transfer' in _bal_comment_l) or (not _bal_comment_l):
                    continue
            trade_history_deals.append(deal)
        if trade_history_deals:
            _ts_vals = [d.get('time_raw') or 0 for d in trade_history_deals if d.get('time_raw')]
            if _ts_vals:
                _oldest = datetime.fromtimestamp(min(_ts_vals)).strftime('%Y-%m-%d')
                _newest = datetime.fromtimestamp(max(_ts_vals)).strftime('%Y-%m-%d')
                _log(f"📜 Trade history: {len(trade_history_deals)} deal(s), {_oldest} → {_newest} (hedge unchanged)")
            else:
                _log(f"📜 Trade history: {len(trade_history_deals)} deal(s) (hedge unchanged)")
        else:
            _log("📜 Trade history: 0 deals returned from MT5")

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

        # Manual Push: synchronously re-scrape prop firm billing (fees & payouts) so
        # firm_billing and eval Fee/Date are fresh in THIS push. Auto-push skips this
        # and reuses whatever was scraped when the dashboard browser last connected.
        if full_prop_refresh:
            self._refresh_prop_billing_sync(_log)

        # Collect Tradovate MNQ daily P&L for Prop Day values.
        # ONLY runs if at least one Tradovate account is actively connected.
        # Cache-miss fetches are done in a background thread so they never add
        # to push wall-time — the result is available for the NEXT push.
        # On a manual push (full_prop_refresh) we block on the fetch instead so the
        # prop days land in the same payload.
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
                elif full_prop_refresh:
                    # Manual push — block on the fetch so prop days land in THIS payload.
                    _log(f"🌾 {firm_name}: fetching Tradovate prop-day history (manual push — blocking)...")
                    try:
                        data = tv_account.get_mnq_daily_pnl() or []
                        self._tradovate_farming_cache[firm_name] = (time.time(), data)
                        if data:
                            total_days = sum(len(a.get('mnq_daily_pnl', [])) for a in data)
                            _log(f"🌾 {firm_name}: {total_days} Prop Day(s) fetched")
                        tradovate_farming_days.extend(data)
                    except Exception as _e:
                        _log(f"⚠️ {firm_name}: prop-day fetch failed: {_e}", "WARN")
                else:
                    # Auto-push cache miss — use whatever we have now (empty on first push),
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
            "deals": [],  # intentionally empty — hedge/stats use aggregated_by_comment + statistics below
            "trade_history_deals": trade_history_deals,
            "statistics": statistics,
            "evaluations": [],
            "aggregated_by_comment": aggregated_by_comment,
            "prefer_client_aggregation": True,
            "comment_summary": comment_summary,
            "dropdown_options": {},
            "firm_billing": self._firm_billing_summary if self._firm_billing_summary else None,
        }
        try:
            from research.mt5_time import capture_push_timing_context

            _mt5_mod = mt5 if (MT5_AVAILABLE and self.pusher.connected) else None
            payload["mt5_timing"] = capture_push_timing_context(
                account=account,
                sample_deals=trade_history_deals,
                mt5=_mt5_mod,
            )
            _probe = (payload["mt5_timing"].get("timecurrent_probe") or {})
            if _probe.get("mt5_server_minus_nairobi_hours") is not None:
                _log(
                    f"🕐 MT5 TimeCurrent vs Nairobi: {_probe.get('mt5_server_minus_nairobi_hours'):+.1f}h "
                    f"(correction {_probe.get('utc_correction_sec', 0) / 3600:+.1f}h, "
                    f"tick age {_probe.get('tick_freshness_sec', '?')}s)",
                )
        except Exception as _tz_exc:
            _log(f"⚠️ mt5_timing snapshot skipped: {_tz_exc}", "WARNING")

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
                    _log(f"\n✅ PUSH SUCCESSFUL → Bal: ${bal:,.0f} | Dep: ${dep:,.0f} | {len(trade_history_deals)} history deals | {pos_count} pos | {agg_count} hedge groups")
                    
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
                    if data.get("status") in ("inactive", "blocked"):
                        self.root.after(0, lambda m=data.get("message", "Sync disabled"): self.stop_auto_push(m))
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    body = response.json()
                    error_msg = body.get("message", error_msg)
                    if body.get("status") in ("inactive", "blocked") or response.status_code == 403:
                        self.root.after(0, lambda m=error_msg: self.stop_auto_push(m))
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

            # First check — initialize state and push once (full billing refresh first time)
            if self.last_deal_count == 0:
                self.last_deal_count = current_count
                self.last_deal_ticket = current_ticket
                self.log(f"🔍 Auto-sync scan: {current_count} deals, last ticket: {current_ticket}")
                full = bool(getattr(self, "_auto_push_first_run", False))
                self._auto_push_first_run = False
                self.push_data(full_prop_refresh=full)
                return

            if current_count > self.last_deal_count or current_ticket != self.last_deal_ticket:
                self.log(
                    f"⚡ New trade — auto-sync "
                    f"(deals {self.last_deal_count}→{current_count}, ticket {current_ticket})"
                )

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
        "Funded Next Flex": "Funded Next Flex",
        "FundedNextFlex": "Funded Next Flex",
        "TopStep": "TopStep",
        "TopStep RTP": "TopStep RTP",
        "TopStep_RTP": "TopStep RTP",
        "TradeDay": "TradeDay",
        "Tradeify": "Tradeify",
        "Alpha Futures": "AlphaFutures",
        "Apex": "Apex",
        "Top One Futures": "Top One Futures",
        "Funded Futures Family": "Funded Futures Family",
        "FFF": "Funded Futures Family",
        "Lucid": "Lucid",
        "LucidMaxx": "LucidMaxx",
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
        if "fundednextflex" in compact or "funded next flex" in norm:
            return "Funded Next Flex"
        if "fundednext" in compact or "funded next" in norm:
            return "Funded Next"
        if "funded futures family" in norm or "fundedfuturesfamily" in compact or compact == "fff":
            return "Funded Futures Family"
        if "lucidmaxx" in compact or "lucid maxx" in norm:
            return "LucidMaxx"

        return default

    _DETECTED_PROP_FIRM_LABEL = {
        "MFFU": "My Funded Futures",
        "Funded Next": "FundedNext",
        "TopStep": "Topstep",
        "Trade Day": "TradeDay",
        "Tradeify": "Tradeify",
        "FundingTicks": "Funding Ticks",
        "Lucid": "Lucid",
        "LucidMaxx": "LucidMaxx",
        "AlphaFutures": "Alpha Futures",
        "Funded Futures Family": "Funded Futures Family",
        "Apex": "Apex",
        "Top One Futures": "Top One Futures",
    }

    def _sync_prop_firm_from_account(self, ev):
        """Align dashboard Prop Firm with account prefix when they disagree."""
        if not self.prop_firm_mgr or not isinstance(ev, dict):
            return
        acct = self._cell(ev.get("Account #.1") or ev.get("Account #"))
        if len(acct) < 4:
            return
        detected = self.prop_firm_mgr.detect_prop_firm(acct)
        if not detected:
            return
        label = self._DETECTED_PROP_FIRM_LABEL.get(detected, detected)
        cur_code = self._resolve_firm_code(ev.get("Prop Firm", ""))
        new_code = self._resolve_firm_code(label)

        # Funded Next account prefixes cannot distinguish standard vs Flex.
        # If the row is explicitly set to Flex, never downgrade it to standard.
        if cur_code == "Funded Next Flex" and new_code == "Funded Next":
            return

        if cur_code != new_code:
            ev["Prop Firm"] = label

    _FAILED_STATUSES = {"fail", "failed", "breach", "delete", "deleted", "closed", "sl", "ended", "lost"}

    # Keywords for substring matching (catches "Fail", "Failed", "Breached", etc.)
    _INACTIVE_KEYWORDS = ("fail", "breach", "delete", "closed", "ended", "lost")

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
        "LucidMaxx":        "ACCOUNT_SIZE",
        "Top One Futures":  "ACCOUNT_SIZE",
        "Funded Futures Family": "ACCOUNT_SIZE",
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
        challenge_status = self._cell(ev.get("Status P1")).lower()
        funded_status = self._cell(ev.get("Status")).lower()
        has_funded_acct = bool(self._cell(ev.get("Account #.1")))
        passed_funded = self._has_passed_to_funded(ev)

        # Check if farming data exists — must have BOTH the farming marker
        # AND actual Hedge Day cell data for THIS account (not just sheet columns)
        has_farming_marker = bool(self._cell(ev.get("Prop Day 1")))
        has_hedge_day_data = False
        if has_farming_marker:
            for i in range(1, 35):
                val = self._cell(ev.get(f"Hedge Day {i}"))
                if val and val not in ("—", "-"):
                    has_hedge_day_data = True
                    break

        if has_farming_marker and has_hedge_day_data:
            return "Farming", "farming"
        # Both Account # + Account #.1 → eval passed; never trade challenge leg.
        if passed_funded:
            return "Funded", "funded_trade1"
        elif has_funded_acct and funded_status not in self._FAILED_STATUSES:
            return "Funded", "funded_trade1"
        else:
            return "Challenge", "challenge_trade1"

    @staticmethod
    def _phase_badge_label(current_phase: str, phase_key: str) -> str:
        """Short label for the Phase column (CH1 / FD2 / FA / DD1...)."""
        pk = str(phase_key or "").strip().lower()
        if pk.startswith("challenge_trade"):
            suf = pk.replace("challenge_trade", "").strip() or "1"
            return f"CH{suf}"
        if pk.startswith("funded_trade_doubledip_"):
            suf = pk.replace("funded_trade_doubledip_", "").strip() or "1"
            return f"DD{suf}"
        if pk.startswith("payout") and "_trade" in pk:
            # e.g. payout2_trade1 -> P2-1
            payout_n = pk.replace("payout", "").split("_trade")[0] or "1"
            trade_n = pk.split("_trade")[-1].strip() or "1"
            return f"P{payout_n}-{trade_n}"
        if pk.startswith("funded_trade"):
            suf = pk.replace("funded_trade", "").strip() or "1"
            return f"FD{suf}"
        if pk == "farming":
            return "FA"
        # Fallback: first 3 letters of detected phase
        cp = str(current_phase or "").strip().upper()
        return (cp[:3] or "PH")

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

        # Dual-account rows always resolve to funded blueprints — never CH*.
        if self._has_passed_to_funded(ev) and matched_phase == "Challenge":
            matched_phase = "Funded"

        # If day was found in a different phase's fields, correct the phase
        effective_phase = matched_phase if matched_phase else current_phase
        if self._has_passed_to_funded(ev):
            effective_phase = "Funded" if effective_phase == "Challenge" else effective_phase
        if matched_phase and matched_phase != current_phase:
            _acct = self._primary_trade_account(ev)
            self._ai_trace("WARN", f"{_acct}: phase correction — detected "
                                   f"'{current_phase}' but placeholder found in "
                                   f"'{matched_phase}' columns")
            self.log(f"📅 Phase correction: detected '{current_phase}' but day "
                     f"placeholder found in '{matched_phase}' fields")

        if not self.prop_firm_mgr:
            return None, day_idx, day_name

        # Normalize phase for _PHASE_TRADE_ORDER lookup
        phase_map = {"Challenge": "Challenge", "Funded": "Funded",
                     "Farming": "Farming", "Double Dip": "Double Dip",
                     "Min Trading Days": "Min Trading Days",
                     "Funded Phase": "Funded Phase",
                     "Residual Phase": "Residual Phase", "Residual": "Residual Phase",
                     "Payout 1": "Funded", "Payout 2": "Funded",
                     "Payout 3": "Funded", "Payout 4": "Funded"}
        firm_orders = self.prop_firm_mgr._PHASE_TRADE_ORDER.get(firm_code, {})
        # Prefer the firm's own phase key (e.g. Apex per-payout groups); only
        # collapse Payout→Funded for firms without per-payout trade orders.
        if effective_phase in firm_orders:
            phase_group = effective_phase
        else:
            phase_group = phase_map.get(effective_phase, effective_phase)
        trade_keys = firm_orders.get(phase_group, [])

        if not trade_keys:
            return None, day_idx, day_name

        # Clamp day index to available trade keys.
        # If the trader placed a weekday placeholder in a cell beyond the
        # configured number of trades for this firm/phase (e.g. Hedge Result 3
        # when the firm only has CH1/CH2), we must not "invent" CH3 — instead
        # we clamp to the last configured key and log a clear warning so the
        # dashboard can be corrected.
        if day_idx >= len(trade_keys):
            try:
                self.log(
                    f"⚠ Phase cell overflow: firm={firm_code} phase={phase_group} "
                    f"placeholder_cell={day_idx + 1} ({day_name}) but only {len(trade_keys)} "
                    f"trade(s) configured — using {trade_keys[-1]}",
                    "WARN",
                )
            except Exception:
                pass
        key_idx = min(day_idx, len(trade_keys) - 1)
        resolved_key = trade_keys[key_idx]
        _acct = self._primary_trade_account(ev)
        self._ai_trace("BLUEPRINT",
                       f"{_acct}: day cell {day_idx + 1} ({day_name}) in "
                       f"'{effective_phase}' [{firm_code}] → blueprint {resolved_key}")
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

    def _has_passed_to_funded(self, ev) -> bool:
        """True when the row has both challenge and funded account numbers."""
        ch = self._cell(ev.get("Account #"))
        fu = self._cell(ev.get("Account #.1"))
        return bool(ch and fu)

    def _primary_trade_account(self, ev) -> str:
        """Account number to trade — funded leg when challenge is already passed."""
        ch = self._cell(ev.get("Account #"))
        fu = self._cell(ev.get("Account #.1"))
        if self._has_passed_to_funded(ev):
            return fu
        return fu or ch or "—"

    def _phase_field_sets_for_scan(self, ev):
        """Which hedge columns to inspect for today's day placeholder at SCAN."""
        if self._on_funded_leg(ev):
            phase_display, _ = self._detect_eval_phase(ev)
            names = ("Funded",) if phase_display != "Farming" else ("Funded", "Farming")
            return [(n, flist) for n, flist in self._ALL_PHASE_FIELD_SETS if n in names]
        return self._ALL_PHASE_FIELD_SETS

    def _is_superseded_challenge_row(self, ev, all_evals) -> bool:
        """Skip a challenge-only row when the same Account # graduated elsewhere.

        Example: row A has eval + funded (passed); row B still lists only the
        old eval account — row B must not appear in Active Trades.
        """
        ch = self._cell(ev.get("Account #"))
        fu = self._cell(ev.get("Account #.1"))
        if not ch or fu:
            return False
        for other in all_evals:
            if other is ev or other.get("_deleted"):
                continue
            if (self._cell(other.get("Account #")) == ch
                    and self._cell(other.get("Account #.1"))):
                return True
        return False

    @staticmethod
    def _cell(value, default=""):
        """Sheet/JSON cell → stripped string (values may be int/float from DB import)."""
        if value is None:
            return default
        s = str(value).strip()
        return s if s else default

    @staticmethod
    def _acct_suffix(acct: str, n: int = 5) -> str:
        s = str(acct or "").strip()
        return s[-n:] if len(s) >= n else s

    def _is_funded_only_row(self, ev) -> bool:
        """Row lists only Account #.1 (funded leg) — no challenge number."""
        ch = self._cell(ev.get("Account #"))
        fu = self._cell(ev.get("Account #.1"))
        return bool(fu) and not ch

    def _on_funded_leg(self, ev) -> bool:
        """Eval is on the funded stage (dual-account row or funded-only row)."""
        return self._has_passed_to_funded(ev) or self._is_funded_only_row(ev)

    def _funded_leg_exhausted(self, ev) -> bool:
        """Funded hedge track finished — dollar results, no day placeholders left."""
        if not self._cell(ev.get("Account #.1")):
            return False
        fields = [f"Hedge Result {i}.1" for i in range(1, 8)]
        placeholders = 0
        results = 0
        for f in fields:
            val = self._cell(ev.get(f))
            if not val or val in ("—", "-"):
                continue
            if self._parse_day_token(val) is not None:
                placeholders += 1
            else:
                try:
                    float(val.replace("$", "").replace(",", ""))
                    results += 1
                except ValueError:
                    pass
        return results >= 2 and placeholders == 0

    def _build_lifecycle_registry(self, all_evals):
        """Challenge → funded pairs and funded suffixes from graduated rows."""
        graduated_ch = set()
        funded_suffixes = set()
        for ev in all_evals:
            if ev.get("_deleted"):
                continue
            ch = self._cell(ev.get("Account #"))
            fu = self._cell(ev.get("Account #.1"))
            if ch and fu:
                graduated_ch.add(ch)
                graduated_ch.add(self._acct_suffix(ch))
                funded_suffixes.add(fu)
                funded_suffixes.add(self._acct_suffix(fu))
        return graduated_ch, funded_suffixes

    def _is_superseded_lifecycle_row(self, ev, all_evals) -> bool:
        """Skip duplicate lifecycle legs (challenge row after funded account exists).

        When an eval passes, the prop firm issues a new funded account number.
        The dashboard may still have a stale challenge-only row OR a completed
        funded row — only the current, tradeable leg should appear once.
        """
        ch = self._cell(ev.get("Account #"))
        fu = self._cell(ev.get("Account #.1"))

        if self._on_funded_leg(ev) and self._funded_leg_exhausted(ev):
            return True

        if self._is_superseded_challenge_row(ev, all_evals):
            return True

        graduated_ch, funded_suffixes = self._build_lifecycle_registry(all_evals)

        # Challenge-only row whose Account # already graduated on another row
        if ch and not fu:
            if ch in graduated_ch or self._acct_suffix(ch) in graduated_ch:
                return True
            # Funded number mistakenly listed alone in Account # column
            if ch in funded_suffixes or self._acct_suffix(ch) in funded_suffixes:
                return True

        return False

    def _dedupe_active_by_primary_account(self, active_evals):
        """One active row per tradeable account number."""
        seen = set()
        out = []
        for ev in active_evals:
            primary = self._primary_trade_account(ev)
            key = self._acct_suffix(primary, 8)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(ev)
        return out

    def _scan_day_placeholders(self, ev, phase_sets, target_weekday=None):
        """Return whether a placeholder is tradeable today or missed earlier.

        Rows with no day placeholder at all are not active.  Future-only queued
        placeholders remain inactive until the scheduled weekday arrives.  A
        prior weekday placeholder counts as active because it represents a missed
        trade that still needs to be caught up.
        """
        found_any = False
        for _phase, fields in phase_sets:
            for f in fields:
                val = ev.get(f)
                if val is None:
                    continue
                day_num = self._parse_day_token(val)
                if day_num is None:
                    continue
                found_any = True
                if target_weekday is None:
                    continue
                bucket = self._classify_day_placeholder(day_num, target_weekday)
                if bucket in ("today", "past"):
                    return True, True
        if target_weekday is not None:
            return False, found_any
        return found_any, found_any

    def _funded_leg_tradeable(self, ev, weekday: int) -> bool:
        """Funded-stage rows: only Account #.1 columns, must have today's slot."""
        if self._funded_leg_exhausted(ev):
            return False
        funded_st = self._cell(ev.get("Status")).lower()
        if funded_st and any(kw in funded_st for kw in (
                "complete", "completed", "paid", "payout", "closed",
                *self._INACTIVE_KEYWORDS)):
            return False
        phase_sets = self._phase_field_sets_for_scan(ev)
        today_ok, _found = self._scan_day_placeholders(ev, phase_sets, weekday)
        return bool(today_ok)

    def _passed_funded_row_tradeable(self, ev, weekday: int) -> bool:
        """Alias — dual-account rows use the funded-leg rules."""
        return self._funded_leg_tradeable(ev, weekday)

    def _has_placeholder_for_weekday(self, ev, weekday: int) -> bool:
        """True when an eval is still tradeable for this calendar weekday (Kenya EAT).

        A row is active only when it has a placeholder for today or for an
        earlier missed weekday.  Future-only placeholders are queued for later and
        therefore do not count as active on the current day.  A row with no day
        placeholders at all is not tradeable and must be filtered out.
        """
        passed_funded = self._has_passed_to_funded(ev)
        if passed_funded or self._is_funded_only_row(ev):
            return self._funded_leg_tradeable(ev, weekday)

        phase_sets = self._phase_field_sets_for_scan(ev)
        today_scoped, found_any_scoped = self._scan_day_placeholders(
            ev, phase_sets, weekday)
        if today_scoped:
            return True
        if not found_any_scoped:
            return False
        return False

    def _classify_day_placeholder(self, day_num: int, today_weekday: int) -> str:
        """Classify a weekday placeholder as today / past / future.

        Uses trading-week logic so Friday→Monday wraps to the next trading day,
        and weekend placeholders are treated as queued for the next session.
        """
        if today_weekday >= 5:
            return "future"
        if day_num == today_weekday:
            return "today"
        if today_weekday == 4 and day_num == 0:
            return "future"
        if day_num < today_weekday:
            return "past"
        return "future"

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

        passed_funded = self._has_passed_to_funded(ev)
        if passed_funded and current_phase == "Challenge":
            current_phase = "Funded"

        # Build ordered list: detected phase first, then all others as fallback
        primary_fields = self._get_phase_fields(current_phase)
        search_order = [(current_phase, primary_fields)]
        has_funded_acct = bool(self._cell(ev.get("Account #.1")))
        for phase_name, field_list in self._ALL_PHASE_FIELD_SETS:
            if field_list == primary_fields:
                continue
            # GUARD: eval passed (both account columns) must NEVER use Challenge
            # columns — stale day placeholders there would pick CH* blueprints.
            if phase_name == "Challenge" and (
                    passed_funded or (has_funded_acct and current_phase != "Challenge")):
                stale = [f for f in field_list
                         if self._parse_day_token(ev.get(f)) is not None]
                if stale and not passed_funded:
                    acct = self._primary_trade_account(ev)
                    msg = (f"⚠ {acct}: stale challenge placeholder in '{stale[0]}' "
                           f"IGNORED — account is funded; challenge columns are "
                           f"no longer tradeable (would have used wrong TP/SL)")
                    self._ai_trace("WARN", msg)
                    try:
                        self.root.after(0, lambda m=msg: self.log(m, "WARN"))
                    except Exception:
                        pass
                continue
            search_order.append((phase_name, field_list))

        def _pick_from_fields(fields, report_phase):
            best_past = None
            best_future = None
            for i, f in enumerate(fields):
                val = ev.get(f, None)
                if val is None:
                    continue
                day_num = self._parse_day_token(val)
                if day_num is None:
                    continue
                bucket = self._classify_day_placeholder(day_num, today_weekday)
                if bucket == "today":
                    return i, str(val).strip().upper(), True, report_phase
                if bucket == "past":
                    if best_past is None or day_num > best_past[2]:
                        best_past = (i, str(val).strip().upper(), day_num)
                else:
                    if best_future is None or day_num < best_future[2]:
                        best_future = (i, str(val).strip().upper(), day_num)
            if best_past is not None:
                return best_past[0], best_past[1], False, report_phase
            if best_future is not None:
                return best_future[0], best_future[1], False, report_phase
            return None

        for phase_name, fields in search_order:
            hit = _pick_from_fields(fields, phase_name)
            if hit is not None:
                return hit

        return None, None, False, None

    def _find_day_cell_for_weekday(self, ev, current_phase, target_weekday: int):
        """Find a day-name placeholder matching a specific weekday (0=Mon..6=Sun).

        Used to locate TOMORROW's queued trade from dashboard cells.
        Returns (stage_index, day_name, matched_phase) or (None, None, None).
        """
        primary_fields = self._get_phase_fields(current_phase)
        search_order = [(current_phase, primary_fields)]
        passed_funded = self._has_passed_to_funded(ev)
        if passed_funded and current_phase == "Challenge":
            current_phase = "Funded"
            primary_fields = self._get_phase_fields(current_phase)
            search_order = [(current_phase, primary_fields)]
        has_funded_acct = bool(self._cell(ev.get("Account #.1")))
        for phase_name, field_list in self._ALL_PHASE_FIELD_SETS:
            if field_list == primary_fields:
                continue
            if phase_name == "Challenge" and (
                    passed_funded or (has_funded_acct and current_phase != "Challenge")):
                continue
            search_order.append((phase_name, field_list))

        for phase_name, fields in search_order:
            for i, f in enumerate(fields):
                val = ev.get(f, None)
                if val is None:
                    continue
                day_num = self._parse_day_token(val)
                if day_num is not None and day_num == target_weekday:
                    return i, str(val).strip().upper(), phase_name
        return None, None, None

    def _resolve_phase_key_for_weekday(self, ev, firm_code, current_phase, target_weekday: int):
        """Map a weekday placeholder cell to its blueprint key (e.g. tomorrow)."""
        day_idx, day_name, matched_phase = self._find_day_cell_for_weekday(
            ev, current_phase, target_weekday)
        if day_idx is None:
            return None, None, None
        effective_phase = matched_phase if matched_phase else current_phase
        if not self.prop_firm_mgr:
            return None, day_idx, day_name
        phase_map = {"Challenge": "Challenge", "Funded": "Funded",
                     "Farming": "Farming", "Double Dip": "Double Dip",
                     "Min Trading Days": "Min Trading Days",
                     "Funded Phase": "Funded Phase",
                     "Residual Phase": "Residual Phase", "Residual": "Residual Phase",
                     "Payout 1": "Funded", "Payout 2": "Funded",
                     "Payout 3": "Funded", "Payout 4": "Funded"}
        firm_orders = self.prop_firm_mgr._PHASE_TRADE_ORDER.get(firm_code, {})
        if effective_phase in firm_orders:
            phase_group = effective_phase
        else:
            phase_group = phase_map.get(effective_phase, effective_phase)
        trade_keys = firm_orders.get(phase_group, [])
        if not trade_keys:
            return None, day_idx, day_name
        key_idx = min(day_idx, len(trade_keys) - 1)
        return trade_keys[key_idx], day_idx, day_name

    def _is_queued_for_calendar_tomorrow(self, ev, current_phase):
        """Locate the cell whose day name is calendar tomorrow (e.g. FRIDAY).

        Scans for tomorrow's weekday directly — does NOT use
        ``_find_tradeable_day_cell`` because that prefers missed past days
        (MON on WED) over future FRIDAY placeholders.
        """
        from datetime import timedelta
        tomorrow_wd = (kenya_today() + timedelta(days=1)).weekday()
        day_idx, day_name, matched_phase = self._find_day_cell_for_weekday(
            ev, current_phase, tomorrow_wd)
        if day_idx is None:
            return None
        return day_idx, day_name, matched_phase

    def _collect_tomorrow_trade_plans(self):
        """Build simulation plans from rows queued for calendar tomorrow.

        Uses the same day-cell + blueprint resolution as the BLUEPRINT traces
        at SCAN time, so FRIDAY placeholders seen there appear here too.
        """
        if not TRADE_SIMULATOR_AVAILABLE:
            return []
        from datetime import timedelta
        twd = (kenya_today() + timedelta(days=1)).weekday()
        wd_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        plans = []
        seen = set()
        rows = getattr(self, "_active_trade_rows", None) or []
        for rd in rows:
            firm_code = rd.get("firm_code", "")
            current_phase = rd.get("current_phase", "")
            acct_num = (rd.get("acct_num") or "?").strip()
            acct_size = (rd.get("acct_size") or "50k").strip()
            if acct_size in ("—", "-", "", "N/A"):
                acct_size = "50k"

            # Fresh eval — dashboard may have updated since SCAN
            ev = rd.get("eval") or {}
            try:
                fresh = self._refresh_eval_for_account(acct_num)
                if fresh:
                    ev = fresh
                    rd["eval"] = fresh
            except Exception:
                pass

            queued = self._is_queued_for_calendar_tomorrow(ev, current_phase)
            if queued is None:
                continue
            day_idx, day_name, matched = queued

            # Blueprint for THIS weekday cell (not the catch-up cell tradeable finder prefers)
            phase_key, _, _ = self._resolve_phase_key_for_weekday(
                ev, firm_code, current_phase, twd)
            if not phase_key or not self.prop_firm_mgr:
                continue
            config = self.prop_firm_mgr.get_strategy_config(
                firm_code, phase_key, acct_size)
            if not config:
                continue
            sym = (config.get("tradovate_symbol", "")
                   or config.get("topstepx_symbol", "")).upper()
            tp_ticks = int(config.get("tradovate_tp_ticks", 0)
                           or config.get("topstepx_tp_ticks", 0) or 0)
            sl_ticks = int(config.get("tradovate_sl_ticks", 0)
                           or config.get("topstepx_sl_ticks", 0) or 0)
            if not tp_ticks or not sl_ticks:
                continue
            plan_id = trade_simulator.make_plan_id(acct_num, phase_key, firm_code)
            if plan_id in seen:
                continue
            seen.add(plan_id)
            tp_pts = trade_simulator.ticks_to_points(tp_ticks)
            sl_pts = trade_simulator.ticks_to_points(sl_ticks)
            plans.append({
                "plan_id": plan_id,
                "acct_num": acct_num,
                "firm_code": firm_code,
                "phase_key": phase_key,
                "phase_display": matched or current_phase,
                "acct_size": acct_size,
                "day_name": day_name or wd_names[twd],
                "day_idx": day_idx,
                "tp_ticks": tp_ticks,
                "sl_ticks": sl_ticks,
                "tp_points": tp_pts,
                "sl_points": sl_pts,
                "expected_min": trade_simulator.expected_duration_min(tp_pts, sl_pts),
                "is_farming": "MNQ" in sym,
                "mt5_symbol": self._resolve_mt5_hedge_symbol(config),
            })
        return plans

    def _announce_tomorrow_plans(self, plans, error: str = ""):
        """Update monitor + log with queued tomorrow plans (even without MT5)."""
        from datetime import timedelta
        wd_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        twd = (kenya_today() + timedelta(days=1)).weekday()
        tname = wd_names[twd]
        if not plans:
            return
        summary = ", ".join(
            f"{p['acct_num'][-8:]}:{p['phase_key']}(TP{p['tp_ticks']}t)"
            for p in plans[:8])
        if len(plans) > 8:
            summary += f" +{len(plans) - 8} more"
        msg = f"TOMORROW {tname}: {len(plans)} plan(s) queued — {summary}"
        if error:
            msg += f" | {error}"
        self._ai_trace("SIM", msg)
        try:
            if getattr(self, "_ai_status_vars", None):
                self._ai_status_vars["tomorrow"].set(msg[:120])
        except Exception:
            pass
        try:
            self.root.after(0, lambda m=msg: self.log(f"📋 {m}"))
        except Exception:
            pass

    def _run_tomorrow_simulation(self):
        """Paper-trade tomorrow's queued plans on today's bars (learning loop).

        Runs even when no live trades were taken — uses day placeholders to
        know which blueprint TP/SL to simulate, replays entries every 15 min,
        ranks plans by TP hit rate and speed (small moves = fast trades).
        """
        if not TRADE_SIMULATOR_AVAILABLE:
            return
        try:
            plans = self._collect_tomorrow_trade_plans()
            if not plans:
                brief = trade_simulator.get_last_brief()
                if brief.get("plans"):
                    return
                from datetime import timedelta
                twd = (kenya_today() + timedelta(days=1)).weekday()
                wd_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
                self._ai_trace(
                    "SIM",
                    f"no plans for calendar tomorrow ({wd_names[twd]}) — "
                    f"enter {wd_names[twd]} in the next Hedge Result cell on each row")
                return

            # Always announce queued plans immediately (even if replay is throttled)
            self._announce_tomorrow_plans(plans)

            # Continuous batch sim: open all tomorrow plans, walk TP/SL on M1, next batch when all close
            def _sim_dir(_plan):
                if ML_DIRECTION_AVAILABLE and ml_direction_engine is not None:
                    try:
                        ml = ml_direction_engine.get_ml_direction("ustech", 5, auto_train=False)
                        lean = (ml or {}).get("lean")
                        if lean in ("buy", "sell"):
                            return lean
                    except Exception:
                        pass
                return None

            batch_brief = trade_simulator.step_batch_engine(
                plans, "ustech",
                log_fn=lambda m: self._ai_trace("SIM", m),
                direction_fn=_sim_dir,
            )
            if batch_brief.get("error"):
                self._announce_tomorrow_plans(
                    plans, error=batch_brief.get("error", "connect MT5 for batch sim"))
            elif batch_brief.get("n_batches"):
                acc = batch_brief.get("accuracy", 0)
                bmsg = (f"batch #{batch_brief.get('batch_num')} "
                        f"{batch_brief.get('open_count', 0)} open / "
                        f"{batch_brief.get('closed_count', 0)} closed sim | "
                        f"accuracy {acc:.0%}")
                try:
                    if getattr(self, "_ai_status_vars", None):
                        self._ai_status_vars["tomorrow"].set(bmsg[:120])
                except Exception:
                    pass

            replay_due = (time.time() - getattr(self, "_last_sim_ts", 0) >= 300
                          or not getattr(self, "_last_sim_ts", 0))
            if not replay_due:
                return
            self._last_sim_ts = time.time()

            brief = trade_simulator.run_simulation(
                plans, "ustech",
                log_fn=lambda m: self._ai_trace("SIM", m))
            if brief.get("error"):
                self._announce_tomorrow_plans(
                    plans, error=brief.get("error", "connect MT5 to replay bars"))
                return
            top = brief.get("top")
            if top:
                msg = (f"TOMORROW {brief.get('tomorrow')}: best "
                       f"{top.get('acct_num')} {top.get('phase_key')} "
                       f"TP={top['tp_ticks']}t SL={top['sl_ticks']}t "
                       f"score={top['score']} enter ~{top.get('best_slot')} "
                       f"{str(top.get('best_direction', '')).upper()} "
                       f"(avg {top.get('avg_tp_min')}min to TP)")
                self._ai_trace("SIM", msg)
                try:
                    if getattr(self, "_ai_status_vars", None):
                        self._ai_status_vars["tomorrow"].set(msg[:120])
                except Exception:
                    pass
                # Store per-row sim scores for button unlock hints
                for rd in getattr(self, "_active_trade_rows", []) or []:
                    for p in brief.get("plans", []):
                        if (p.get("acct_num") == rd.get("acct_num")
                                and p.get("firm_code") == rd.get("firm_code")):
                            rd["sim_score"] = p.get("score")
                            rd["sim_tp_rate"] = p.get("tp_rate")
                            rd["sim_best_slot"] = p.get("best_slot")
                            rd["sim_phase_key"] = p.get("phase_key")
                            break
        except Exception as e:
            self._ai_trace("WARN", f"tomorrow simulation failed: {e}")

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

    def _get_current_phase_profit(self, ev, current_phase, broker_account=None, acct_size=None, live_equity=None, acct_num=None):
        """Get the current P/L for the active phase.

        Priority:
        1. Live broker equity (equity - starting balance) — most accurate
        2. Eval hedge result fields — fallback when broker not available

        ``live_equity`` lets the caller supply an ACCOUNT-SCOPED equity (read by
        account_id via the API) so the stage-profit/TP math is computed from the
        trade's own account instead of whatever account happens to be active in
        the broker UI. When None we fall back to the DOM-scraped active account.
        """
        # ── 1. Try live broker equity ──
        equity = None
        equity_src = None
        if live_equity is not None:
            try:
                equity = float(live_equity)
                equity_src = "account-scoped API netLiq"
            except (ValueError, TypeError):
                equity = None
        if equity is None and broker_account and acct_size:
            try:
                stats = broker_account.get_account_stats()
                balance_str = stats.get("Balance", "N/A")
                if balance_str and balance_str != "N/A":
                    cleaned = balance_str.replace("$", "").replace(",", "").strip()
                    equity = float(cleaned)
                    equity_src = "active-UI get_account_stats() [FALLBACK — not account-scoped]"
            except Exception:
                equity = None
        if equity is not None and acct_size:
            # Firm-aware starting balance.  Critical for MFFU funded
            # accounts which start at $0 — using $50K here would make
            # the TP adjuster think we are -$50K down and inflate TP.
            starting = self._resolve_starting_balance(ev, current_phase, acct_size)
            live_profit = equity - starting
            audit("trader.phase_profit.live", acct_num=str(acct_num or ""),
                  phase=str(current_phase), equity=equity, starting=starting,
                  live_profit=live_profit, source=equity_src)
            if abs(live_profit) > 0.01:
                return live_profit

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
        p1 = self._cell(ev.get("Status P1")).lower()
        funded = self._cell(ev.get("Status")).lower()
        has_funded_acct = bool(self._cell(ev.get("Account #.1")))
        has_challenge_acct = bool(self._cell(ev.get("Account #")))

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

        # Only keep rows whose day placeholders include today's weekday (Kenya).
        # Prevents MON/THU placeholders from appearing in Active Trades on FRI.
        if not self._has_placeholder_for_weekday(ev, kenya_today().weekday()):
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
            if self._has_passed_to_funded(ev) and effective_phase == "Challenge":
                effective_phase = "Funded"
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
                a1 = self._cell(ev.get("Account #.1")).lower()
                a0 = self._cell(ev.get("Account #")).lower()
                if acct_lower not in (a1, a0):
                    continue
                cur = self._cell(ev.get(field_name))
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
                acct1 = self._cell(ev.get("Account #.1"))
                acct0 = self._cell(ev.get("Account #"))
                primary = self._primary_trade_account(ev)
                if acct_num == primary:
                    pass
                elif not self._has_passed_to_funded(ev) and acct_num in (acct1, acct0):
                    pass
                else:
                    continue
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
                r = None
                for attempt in range(3):
                    r = requests.post(
                        f"{dashboard_url}/api/client/data",
                        json={"email": email},
                        headers={"Content-Type": "application/json"},
                        timeout=15
                    )
                    if r.status_code != 429:
                        break
                    time.sleep(3 if attempt == 0 else 5)
                if r.status_code != 200:
                    msg = "Unknown error"
                    try:
                        msg = r.json().get("message", msg)
                    except Exception:
                        msg = r.text[:200] if r.text else f"HTTP {r.status_code}"
                    full_msg = f"HTTP {r.status_code}: {msg}"
                    self.root.after(0, lambda m=full_msg: self.log(f"Failed to load trades: {m}", "ERROR"))
                    self.root.after(0, lambda: self.trades_count_var.set("Load failed"))
                    return
                data = r.json()
                evaluations = data.get("evaluations", [])

                # Filter using dashboard's _is_active flag (source of truth)
                # Falls back to local _is_eval_active() if flag missing
                active_evals = []
                skipped_count = 0
                skipped_day = 0
                skipped_super = 0
                skipped_dual = 0
                skipped_funded_done = 0
                skipped_lifecycle = 0
                today_wd = kenya_today().weekday()
                wd_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
                for ev in evaluations:
                    if ev.get("_deleted"):
                        skipped_count += 1
                        continue

                    # Lifecycle dedup — same eval at challenge vs funded stage
                    if self._is_superseded_lifecycle_row(ev, evaluations):
                        skipped_lifecycle += 1
                        continue

                    # Status gate (fail/completed) — dashboard flag or local fallback
                    if "_is_active" in ev:
                        is_active = ev["_is_active"]
                    else:
                        is_active = self._is_eval_active(ev)

                    # Dashboard _is_active ignores weekday + funded completion nuance
                    if is_active and self._on_funded_leg(ev):
                        if not self._funded_leg_tradeable(ev, today_wd):
                            skipped_funded_done += 1
                            continue

                    if not is_active:
                        skipped_count += 1
                        continue

                    # Must have at least one account number
                    if not self._cell(ev.get("Account #")) and not self._cell(ev.get("Account #.1")):
                        skipped_count += 1
                        continue

                    # Dual-account rows must have a funded account to trade
                    if self._has_passed_to_funded(ev) and not self._cell(ev.get("Account #.1")):
                        skipped_dual += 1
                        continue

                    # Day placeholder gate — always applied at SCAN (even when
                    # dashboard _is_active is true; that flag ignores weekdays).
                    if not self._has_placeholder_for_weekday(ev, today_wd):
                        skipped_day += 1
                        continue

                    self._sync_prop_firm_from_account(ev)
                    active_evals.append(ev)

                active_evals = self._dedupe_active_by_primary_account(active_evals)

                self.root.after(0, lambda t=len(evaluations), a=len(active_evals),
                                s=skipped_count, d=skipped_day, g=skipped_super,
                                u=skipped_dual, fd=skipped_funded_done, lc=skipped_lifecycle,
                                w=wd_names[today_wd]:
                    self.log(
                        f"📊 {t} total evaluations → {a} active for {w} today, "
                        f"{s} filtered (failed/completed/deleted)"
                        + (f", {d} skipped (no {w} placeholder)" if d else "")
                        + (f", {g} skipped (eval passed → funded elsewhere)" if g else "")
                        + (f", {u} skipped (dual row missing funded acct)" if u else "")
                        + (f", {fd} skipped (funded leg done / no {w} in funded cols)" if fd else "")
                        + (f", {lc} skipped (lifecycle duplicate / funded complete)" if lc else "")))

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
                    if self._cell(hedge.get("platform")).upper() != "MT5":
                        continue
                    if not (self._cell(hedge.get("login")) and self._cell(hedge.get("password")) and self._cell(hedge.get("server"))):
                        continue
                    hedge_name = self._cell(hedge.get("name")).lower()
                    if client_name and hedge_name == client_name:
                        chosen_hedge = hedge
                        break
                    if chosen_hedge is None:
                        chosen_hedge = hedge

                if chosen_hedge:
                    mt5_login = self._cell(chosen_hedge.get("login"))
                    mt5_pass = self._cell(chosen_hedge.get("password"))
                    mt5_server = self._cell(chosen_hedge.get("server"))
                    self._hedge_account_profile = dict(chosen_hedge)
                else:
                    self._hedge_account_profile = {}
                    mt5_creds = data.get("mt5_credentials") or {}
                    mt5_login = self._cell(mt5_creds.get("login"))
                    mt5_pass = self._cell(mt5_creds.get("password"))
                    mt5_server = self._cell(mt5_creds.get("server"))

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

        # Default: random BUY/SELL per prop firm (daily bias). ML mode is opt-in
        # (password) and replaces bias with AI (ML/DL + indicator vote).
        firms_seen = set()
        for ev in evaluations:
            pf = ev.get("Prop Firm")
            nm = str(pf).strip() if pf is not None else ""
            firms_seen.add(nm or "Unknown")
        self._active_trade_firms = firms_seen

        if self._ml_mode_enabled():
            last_sig = getattr(self, "_last_ai_signal", None) or "buy"
            firm_bias = {f: last_sig for f in firms_seen}
            self._auto_trade_firm_sides = firm_bias
            self._ai_warmup_done = False
            self.log(f"🧠 ML mode: {last_sig.upper()} (last AI signal) — training starts "
                     f"once all brokers are connected")
        else:
            firm_bias = self._get_daily_bias(firms_seen)
            self._auto_trade_firm_sides = firm_bias
            self._ai_warmup_done = True  # skip ML warm-up in random mode
            bias_parts = []
            for f, s in sorted(firm_bias.items()):
                arrow = "▲" if s == "buy" else "▼"
                bias_parts.append(f"{arrow} {f}: {s.upper()}")
            self.log(f"🎲 Direction bias (random per firm): {', '.join(bias_parts)}")
        self.log(f"Rendering {len(evaluations)} active trade row(s)…")

        for idx, ev in enumerate(evaluations):
            try:
                pf_raw = ev.get("Prop Firm")
                prop_firm_name = (str(pf_raw).strip() if pf_raw is not None else "") or "Unknown"
                firm_code = self._resolve_firm_code(prop_firm_name)
                acct_num = self._primary_trade_account(ev)
                if self._has_passed_to_funded(ev):
                    ch = self._cell(ev.get("Account #"))
                    fu = acct_num
                    self.log(
                        f"   📌 Lifecycle row → funded {fu[-8:] if len(fu) > 8 else fu} only "
                        f"(eval {ch[-8:] if len(ch) > 8 else ch} is prior stage — ignored)")
                sz_raw = ev.get("Account Size", "—")
                acct_size = (str(sz_raw).strip() if sz_raw is not None else "") or "—"
                current_display, phase_key = self._detect_eval_phase(ev)
                current_display = str(current_display or "Challenge")

                # Resolve phase_key from day placeholder (primary source of truth)
                resolved_key, _di, _dn = self._resolve_phase_key_from_day(ev, firm_code, current_display)
                if resolved_key:
                    phase_key = resolved_key

                phase_badge = self._phase_badge_label(current_display, phase_key)

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
                    ctk.CTkLabel(phase_pill, text=phase_badge,
                                 font=("Consolas", 8, "bold"),
                                 text_color=glow_fg).pack(padx=8, pady=1)

                    # Next phase with arrow
                    ctk.CTkLabel(row_frame, text=f"→ {next_display}", width=100,
                                 font=("Consolas", 9), text_color="#00D4FF",
                                 anchor="w").pack(side="left", padx=(8, 0))

                    # Signal strength guide (BUY/SELL % — advisory, not a lock)
                    strength_lbl = ctk.CTkLabel(
                        row_frame, text="—", width=72,
                        font=("Consolas", 9, "bold"), text_color="#64748B", anchor="w")
                    strength_lbl.pack(side="left", padx=(8, 0))

                    # BUY / SELL action buttons — bias-aware highlight
                    btn_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
                    btn_frame.pack(side="right", padx=8)

                    row_data = {
                        "frame": row_frame, "eval": ev, "firm_code": firm_code,
                        "phase_key": phase_key, "acct_size": acct_size,
                        "acct_num": acct_num, "current_phase": current_display,
                        "strength_lbl": strength_lbl,
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
                    tk.Label(row_frame, text=phase_badge, width=14, anchor='w',
                             bg=row_bg, fg='#fbbf24', font=('Consolas', 9, 'bold')).pack(side="left", padx=2)
                    tk.Label(row_frame, text=f"→ {next_display}", width=14, anchor='w',
                             bg=row_bg, fg='#00D4FF', font=('Consolas', 9)).pack(side="left", padx=2)

                    strength_lbl = tk.Label(row_frame, text="—", width=9, anchor='w',
                                            bg=row_bg, fg='#64748B',
                                            font=('Consolas', 9, 'bold'))
                    strength_lbl.pack(side="left", padx=2)

                    btn_frame = tk.Frame(row_frame, bg=row_bg)
                    btn_frame.pack(side="left", padx=4)

                    row_data = {
                        "frame": row_frame, "eval": ev, "firm_code": firm_code,
                        "phase_key": phase_key, "acct_size": acct_size,
                        "acct_num": acct_num, "current_phase": current_display,
                        "strength_lbl": strength_lbl,
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
        if self._ml_mode_enabled():
            self._refresh_setup_locks_async()
        # Paper-simulate tomorrow's queued trades on today's bars
        if TRADE_SIMULATOR_AVAILABLE:
            threading.Thread(target=self._run_tomorrow_simulation,
                             name="tomorrow-sim", daemon=True).start()
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
        mt5_sym = self._resolve_mt5_hedge_symbol(config)
        mt5_vol = float(config.get("mt5_volume", 2.8) or 0)
        if mt5_vol <= 0:
            return None
        hedge_side = "sell" if str(prop_side).lower() == "buy" else "buy"
        return self._estimate_mt5_order_margin(mt5_sym, mt5_vol, hedge_side)

    def _refresh_mt5_margin_after_scan(self):
        """After SCAN: show MT5 free margin and estimated hedge margin for queued rows.

        MT5 connect + per-row order_calc_margin are slow IPC calls, so all the
        heavy work runs on a background thread — the Tk main loop must never
        block (it froze the app right after scan when run inline).
        """
        if self.hedge_mode_var.get() != "Hedging":
            self.mt5_free_margin_var.set("")
            return
        if getattr(self, "_margin_refresh_running", False):
            return
        self._margin_refresh_running = True
        self.mt5_free_margin_var.set("MT5 free: checking…")

        login = self.mt5_login.get().strip()
        pwd = self.mt5_password.get().strip()
        server = self.mt5_server.get().strip()
        rows = list(self._active_trade_rows)
        firm_sides = dict(getattr(self, "_auto_trade_firm_sides", {}) or {})

        def _worker():
            try:
                if login and pwd and server and not getattr(self.pusher, "connected", False):
                    try:
                        self.pusher.connect_mt5(login, pwd, server)
                    except Exception:
                        pass
                free = self._get_mt5_free_margin()
                est_total = 0.0
                est_count = 0
                for rd in rows:
                    firm = (rd.get("eval") or {}).get("Prop Firm", rd.get("firm_code", ""))
                    side = firm_sides.get(firm, "buy")
                    m = self._row_hedge_margin_estimate(rd, side)
                    if m is not None:
                        est_total += m
                        est_count += 1

                def _apply(free=free, est_total=est_total, est_count=est_count):
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
                self.root.after(0, _apply)
            finally:
                self._margin_refresh_running = False

        threading.Thread(target=_worker, name="mt5-margin-refresh", daemon=True).start()

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

        hedging = self.hedge_mode_var.get() == "Hedging"
        prop_firm_name = row_data["eval"].get("Prop Firm", firm_code) if row_data.get("eval") else firm_code
        # Platform follows the resolved blueprint code, not a substring of the
        # free-text dashboard label (so e.g. TopStep RTP routes to TopStepX).
        platform = self._platform_for_firm(firm_code or prop_firm_name)
        broker_account = self._get_broker_for_firm(prop_firm_name)

        if not broker_account:
            messagebox.showerror("Error", f"Connect broker for {prop_firm_name} first")
            return

        # ── AlphaTrader: switch to the correct account BEFORE any balance reads ──
        # get_account_size_label(), get_account_stats() and get_min_equity() all
        # scrape the CURRENTLY VISIBLE account in the UI header. The actual switch
        # inside place_order() is too late — the adjustments would use the wrong
        # account's balance. Switch here so every subsequent read is on-target.
        if platform == "AlphaTrader" and acct_num and hasattr(broker_account, 'switch_account'):
            try:
                active_now = broker_account.get_active_account() if hasattr(broker_account, 'get_active_account') else None
                _acct_str = str(acct_num)
                _active_str = str(active_now or "")
                if _acct_str.upper() not in _active_str.upper():
                    self.log(f"🔀 AlphaTrader: pre-adjustment account switch {_active_str!r} → {_acct_str!r}")
                    switched = broker_account.switch_account(_acct_str)
                    if not switched:
                        self.log(f"⚠ AlphaTrader: account switch to '{_acct_str}' may have failed — proceeding anyway")
                else:
                    self.log(f"✅ AlphaTrader: already on correct account {_active_str!r}")
            except Exception as _sw_err:
                self.log(f"⚠ AlphaTrader: pre-adjustment switch failed ({_sw_err}) — balance reads may use wrong account")

        # For AlphaTrader, auto-detect the account size from the live balance when
        # the eval row doesn't have a size (or has "—"), so the right blueprint
        # config (qty / TP / SL) is used rather than falling back to 50k defaults.
        if platform == "AlphaTrader" and acct_size in ("—", "-", "", "N/A"):
            try:
                detected = broker_account.get_account_size_label("AlphaFutures")
                if detected:
                    acct_size = detected
                    self.log(f"📐 AlphaTrader {acct_num}: account size auto-detected → {acct_size}")
            except Exception as _sz_err:
                self.log(f"⚠ AlphaTrader size detection failed for {acct_num}: {_sz_err}")

        # Get trade config from blueprint
        config = None
        if self.prop_firm_mgr:
            config = self.prop_firm_mgr.get_strategy_config(firm_code, phase_key, acct_size)
        if not config:
            messagebox.showerror("Error", f"No blueprint config for {firm_code} / {phase_key} / {acct_size}")
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
        mt5_sym = self._resolve_mt5_hedge_symbol(config)
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

        # ── Full-cushion dynamic SL ────────────────────────────────────────
        # When sl_mode == "full_cushion" the SL is sized to consume the entire
        # remaining drawdown buffer between current balance and the MLL floor.
        #   SL_ticks = (current_balance - drawdown_floor) / (qty × tick_value)
        # tick_value for NQ minis = $5; for MNQ micros = $0.50.
        # Falls back to the blueprint's tradovate_sl_ticks if balance can't be read.
        if config.get("sl_mode") == "full_cushion" and broker_account:
            try:
                _stats = broker_account.get_account_stats() if hasattr(broker_account, "get_account_stats") else {}
                _bal_str = (_stats or {}).get("Balance", "")
                _mll_str = (_stats or {}).get("MLL", "")
                _sod_str = (_stats or {}).get("SODBalance", (_stats or {}).get("SOD Balance", ""))
                _bal = float(_bal_str.replace("$", "").replace(",", "")) if _bal_str and _bal_str not in ("N/A", "Error", "") else None
                _floor = None
                if _mll_str and _mll_str not in ("N/A", "Error", ""):
                    _floor = float(_mll_str.replace("$", "").replace(",", ""))
                elif _sod_str and _sod_str not in ("N/A", "Error", ""):
                    _sod = float(_sod_str.replace("$", "").replace(",", ""))
                    _floor = _sod * (1.0 - 0.04)  # 4% EOD trailing drawdown
                if _bal is not None and _floor is not None and _bal > _floor:
                    _cushion = _bal - _floor
                    _sym_upper = trado_sym.upper()
                    _tick_val = 0.50 if "MNQ" in _sym_upper or "MES" in _sym_upper or "MGC" in _sym_upper else 5.0
                    _dynamic_sl = int(_cushion / (trado_qty * _tick_val))
                    if _dynamic_sl > 0:
                        self.log(
                            f"📐 Full-cushion SL: balance=${_bal:,.2f} floor=${_floor:,.2f} "
                            f"cushion=${_cushion:,.2f} → SL={_dynamic_sl} ticks "
                            f"(was {trado_sl})"
                        )
                        trado_sl = _dynamic_sl
            except Exception as _fc_err:
                self.log(f"⚠ full_cushion SL calc failed, using blueprint fallback ({trado_sl}t): {_fc_err}")

        # Confirm: phase + prop TP/SL (ticks), then MT5 TP/SL (points) when hedging
        trade_phase = (row_data.get("current_phase") or "").strip() or "Unknown"
        phase_bits = [trade_phase]
        if phase_key:
            phase_bits.append(phase_key.replace("_", " "))
        if day_name:
            phase_bits.append(day_name)
        phase_line = "\nPhase:     " + "  ·  ".join(phase_bits)

        _adj_reasons = config.get("_adj_reasons") or []
        _adj_line = ""
        if _adj_reasons:
            _adj_line = "\n⚠ Auto-adjusted:" + "".join(f"\n   • {r}" for r in _adj_reasons)

        tp_sl_lines = (
            phase_line
            + f"\n{platform}:  Qty {trado_qty}  |  TP {trado_tp} ticks  |  SL {trado_sl} ticks"
            + (f"\nMT5:       TP {mt5_tp} pts    |  SL {mt5_sl} pts" if hedging else "")
            + _adj_line
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
                    # TopStepX uses two-digit year futures codes (NQU26, MNQU26)
                    _tsx_sym = _to_topstepx_symbol(trado_sym)
                    # Convert ticks to dollars for TopStepX: dollars = ticks * tick_value * quantity
                    _tsx_tick_val = self.prop_firm_mgr.get_tick_value(_tsx_sym) if self.prop_firm_mgr else 0.5
                    _tsx_tp_dollars = trado_tp * _tsx_tick_val * trado_qty
                    _tsx_sl_dollars = trado_sl * _tsx_tick_val * trado_qty
                    if side == "buy":
                        order_result = broker_account.place_buy_order(_tsx_sym, trado_qty, tp_dollars=_tsx_tp_dollars, sl_dollars=_tsx_sl_dollars, expected_account=acct_num)
                    else:
                        order_result = broker_account.place_sell_order(_tsx_sym, trado_qty, tp_dollars=_tsx_tp_dollars, sl_dollars=_tsx_sl_dollars, expected_account=acct_num)
                elif platform == "AlphaTrader":
                    # Alpha Trader (futures.alphatrader.com) — ticks passed directly.
                    # Pass expected_account so the connector verifies / switches
                    # to the correct account before placing.
                    order_result = broker_account.place_order(
                        trado_sym, side=side, qty=trado_qty,
                        tp_ticks=trado_tp, sl_ticks=trado_sl,
                        expected_account=acct_num,
                    )
                elif platform == "BlackArrow":
                    # BlackArrow (web.blackarrowtrading.com) — ticks passed directly
                    order_result = broker_account.place_order(
                        trado_sym, side=side, qty=trado_qty,
                        tp_ticks=trado_tp, sl_ticks=trado_sl,
                    )

                # Some broker implementations return a status dict instead of raising.
                # AlphaTrader/BlackArrow return False (bool) on failure — catch that too.
                # Normalize all failure modes so MT5 is never hedged against a missing fill.
                if isinstance(order_result, dict) and order_result.get("success") is False:
                    raise Exception(order_result.get("message") or "Broker reported unsuccessful order")
                if order_result is False:
                    raise Exception(f"{platform} order failed — check broker window for details")

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
                    _has_funded = bool(self._cell(_ev.get("Account #.1")))
                    _sf = "Status" if _has_funded else "Status P1"
                    _cur = self._cell(_ev.get(_sf)).lower()
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

          • Funded / Double Dip / Apex payout (funded phase keys):
            ONLY calculate_funded_sl — trade 1 = fixed $2,000 SL; trade 2+ uses
            classic (balance − lock) by default, or split ($2k + cushion) when
            Split (Tradeify) is on — Tradeify accounts only.
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

        # Funded / double-dip / Apex payout keys use the funded SL rule only.
        is_funded = self._is_funded_phase_key(phase_key)

        # Snapshot blueprint values BEFORE adjustment, for diff logging.
        _before_tp = config.get("tradovate_tp_ticks")
        _before_sl = config.get("tradovate_sl_ticks")

        # ── ACCOUNT-SCOPED LIVE READS ──────────────────────────────────────
        # Previously the adjustment read live numbers from get_account_stats()
        # (the *active* UI account) and get_min_equity() (always accounts[0]).
        # On a multi-account Tradovate login that meant TP/SL could be adjusted
        # from the WRONG account's balance/drawdown. We now resolve THIS trade's
        # own account_id and pull one account-scoped min-equity snapshot that
        # every branch below reuses. TopStepX (no _resolve_api_account_id) keeps
        # its previous behaviour via the legacy fallbacks.
        target_account_id = None
        resolved_name = None
        active_ui = None
        account_min_eq = None
        if broker_account is not None:
            try:
                if hasattr(broker_account, 'get_active_account'):
                    active_ui = broker_account.get_active_account()
            except Exception:
                active_ui = None
            if hasattr(broker_account, '_resolve_api_account_id'):
                try:
                    target_account_id, resolved_name = broker_account._resolve_api_account_id(acct_num)
                except Exception as _re_err:
                    self.log(f"⚠ Adjust {acct_num}: could not resolve account_id ({_re_err}) — using active-account reads")
                if hasattr(broker_account, 'get_min_equity'):
                    try:
                        account_min_eq = broker_account.get_min_equity(account_id=target_account_id)
                    except Exception as _me_err:
                        self.log(f"⚠ Adjust {acct_num}: get_min_equity(account_id={target_account_id}) failed — {_me_err}")

        scoped = isinstance(account_min_eq, dict)
        scoped_net_liq = float(account_min_eq['net_liq']) if (scoped and account_min_eq.get('net_liq') is not None) else None
        # Cross-check: does the resolved/active account match the trade target?
        _acct_match = None
        try:
            if active_ui and acct_num:
                _au, _an = str(active_ui), str(acct_num)
                _acct_match = (_an in _au) or (_au in _an) or _au.endswith(_an[-5:]) or _an.endswith(_au[-5:])
        except Exception:
            _acct_match = None
        self.log(
            f"🎯 Adjust scope {acct_num} [{'funded' if is_funded else 'challenge/farming'}]: "
            f"target_id={target_account_id} resolved='{resolved_name}' active_ui='{active_ui or '?'}' "
            f"match={_acct_match} scoped_reads={scoped}")
        if scoped:
            self.log(
                f"📊 Live[{acct_num}] id={target_account_id}: netLiq=${account_min_eq.get('net_liq')} "
                f"SOD=${account_min_eq.get('net_liq_sod')} minEq=${account_min_eq.get('min_equity')} "
                f"TMDL=${account_min_eq.get('trailing_max_drawdown_limit')} "
                f"TMD=${account_min_eq.get('trailing_max_drawdown')} mode={account_min_eq.get('trailing_mode')}")
        audit("trader.adjust.scope", acct_num=str(acct_num or ""), firm=str(firm_code or ""),
              phase_key=str(phase_key or ""), phase=str(current_phase or ""),
              is_funded=bool(is_funded), is_farming=bool(is_farming),
              target_account_id=target_account_id, resolved_name=str(resolved_name or ""),
              active_ui=str(active_ui or ""), account_matches_target=_acct_match,
              scoped_reads=scoped, live_net_liq=scoped_net_liq,
              net_liq_sod=(account_min_eq.get('net_liq_sod') if scoped else None),
              min_equity=(account_min_eq.get('min_equity') if scoped else None),
              tmdl=(account_min_eq.get('trailing_max_drawdown_limit') if scoped else None),
              before_tp=_before_tp, before_sl=_before_sl, tick_value=tick_value, symbol=str(sym or ""))
        if _acct_match is False:
            self.log(f"⚠ Adjust {acct_num}: active UI account '{active_ui}' ≠ trade target '{acct_num}' — "
                     f"adjustments are account-scoped via API id={target_account_id}, "
                     f"order will switch to target before firing", "WARN")

        if is_funded:
            # FUNDED / DOUBLE DIP: Tradovate SL + MT5 TP only via the funded
            # SL rule. Deliberately NO calculate_adjusted_tp / midnight-floor
            # / TMDL cap — those would move Tradovate TP and scale MT5 SL,
            # which funded trades must not do.
            try:
                import re as _re
                balance = None
                bal_src = None
                if scoped_net_liq is not None:
                    balance = scoped_net_liq
                    bal_src = f"account-scoped API netLiq (id={target_account_id})"
                elif broker_account:
                    _stats = broker_account.get_account_stats()
                    _bal_str = _stats.get("Balance", "") if isinstance(_stats, dict) else ""
                    if _bal_str and _bal_str not in ("N/A", "Error", ""):
                        balance = float(str(_bal_str).replace("$", "").replace(",", ""))
                        bal_src = "active-UI get_account_stats() [FALLBACK — not account-scoped]"
                if balance is None:
                    self.log(f"⚠ Funded SL {acct_num}: balance unavailable — keeping blueprint SL/TP")
                    audit("trader.adjust.funded_sl", acct_num=str(acct_num or ""),
                          status="no_balance", target_account_id=target_account_id)
                else:
                    trade_index = self._phase_trade_index(phase_key)
                    # Flat lock level for profit-cushion math on trade 2+
                    threshold = self.prop_firm_mgr.get_lock_level(firm_code)
                    sl_mode = self._funded_sl_mode(firm_code)
                    self.log(f"🧮 Funded SL {acct_num}: balance=${balance:,.2f} via {bal_src} | "
                             f"trade_index={trade_index} lock_level=${threshold} "
                             f"mode={sl_mode} tick_value={tick_value}")
                    config = self.prop_firm_mgr.calculate_funded_sl(
                        config, balance, threshold, trade_index, tick_value,
                        sl_mode=sl_mode)
                    audit("trader.adjust.funded_sl", acct_num=str(acct_num or ""),
                          status="applied", balance=balance, balance_source=bal_src,
                          trade_index=trade_index, lock_level=threshold,
                          target_account_id=target_account_id,
                          sl_after=config.get("tradovate_sl_ticks"))
            except Exception as _fe:
                self.log(f"⚠ Funded SL failed for {acct_num}: {_fe}")
                audit("trader.adjust.funded_sl", acct_num=str(acct_num or ""),
                      status="error", error=str(_fe))
        else:
            # CHALLENGE / FARMING.
            # 1) TP by stage profit (skipped for farming symbols upstream)
            if broker_account and not is_farming:
                try:
                    # Respect the per-config opt-out flag.  The5ers (and any other
                    # firm with a strict consistency rule) set disable_tp_adjustment=True
                    # in their blueprint so the dynamic TP raise can never push a single
                    # trade over the 40% consistency ceiling.
                    if config.get("disable_tp_adjustment"):
                        self.log(
                            f"⏭ TP-by-stage {acct_num}: skipped — "
                            f"disable_tp_adjustment=True in blueprint ({firm_code}/{phase_key})"
                        )
                        audit("trader.adjust.tp_by_stage", acct_num=str(acct_num or ""),
                              status="disabled_by_blueprint", firm=str(firm_code or ""),
                              phase_key=str(phase_key or ""))
                    else:
                        current_profit = self._get_current_phase_profit(
                            row_eval, current_phase,
                            broker_account=broker_account, acct_size=acct_size,
                            live_equity=scoped_net_liq, acct_num=acct_num)
                        size_key = self.prop_firm_mgr.convert_account_size_to_key(acct_size)
                        stage_start = self.prop_firm_mgr.get_stage_start_target(
                            firm_code, current_phase, phase_key, size_key)
                        # Only apply when stage_start is trustworthy — falling back
                        # to 0 would attribute the whole account balance to this
                        # stage and collapse TP to the floor.
                        if stage_start is not None:
                            stage_profit_so_far = current_profit - stage_start
                            target_profit_dollars = None
                            if firm_code == "Funded Next Flex" and phase_key == "funded_trade2":
                                target_profit_dollars = self.prop_firm_mgr._PROFIT_TARGETS.get("Funded Next Flex", {}).get("Funded", 3050.0)
                            self.log(f"🧮 TP-by-stage {acct_num}: equity_scoped={'yes' if scoped_net_liq is not None else 'NO(fallback)'} "
                                     f"current_profit=${current_profit:,.2f} stage_start=${stage_start:,.2f} "
                                     f"stage_profit_so_far=${stage_profit_so_far:,.2f} size_key={size_key} tick_value={tick_value} "
                                     f"target_profit_dollars={target_profit_dollars}")
                            config = self.prop_firm_mgr.calculate_adjusted_tp(
                                config,
                                stage_profit_so_far,
                                tick_value,
                                target_profit_dollars=target_profit_dollars,
                            )
                            audit("trader.adjust.tp_by_stage", acct_num=str(acct_num or ""),
                                  status="applied", target_account_id=target_account_id,
                                  scoped_equity=(scoped_net_liq is not None),
                                  current_profit=current_profit, stage_start=stage_start,
                                  stage_profit_so_far=stage_profit_so_far, size_key=str(size_key),
                                  target_profit_dollars=target_profit_dollars,
                                  tp_before=_before_tp, tp_after=config.get("tradovate_tp_ticks"))
                        else:
                            self.log(f"⚠ TP-by-stage {acct_num}: stage_start unavailable ({firm_code}/{phase_key}) — TP unchanged")
                            audit("trader.adjust.tp_by_stage", acct_num=str(acct_num or ""),
                                  status="no_stage_start", firm=str(firm_code or ""), phase_key=str(phase_key or ""))
                except Exception as _te:
                    self.log(f"⚠ TP adjust failed for {acct_num}: {_te}")
                    audit("trader.adjust.tp_by_stage", acct_num=str(acct_num or ""),
                          status="error", error=str(_te))

            # 2/3) SL midnight floor + TMDL cap. Reuses the account-scoped
            # snapshot when available (Tradovate); otherwise falls back to the
            # legacy get_min_equity() for brokers without account resolution.
            min_eq = account_min_eq
            if min_eq is None and broker_account and hasattr(broker_account, 'get_min_equity'):
                try:
                    min_eq = broker_account.get_min_equity()
                    if isinstance(min_eq, dict):
                        self.log(f"⚠ SL floor/TMDL {acct_num}: using LEGACY get_min_equity() "
                                 f"(not account-scoped) — netLiq=${min_eq.get('net_liq')}", "WARN")
                except Exception as _sle:
                    self.log(f"⚠ SL floor/TMDL {acct_num}: get_min_equity failed — {_sle}")
                    min_eq = None
            if isinstance(min_eq, dict):
                try:
                    live_net_liq = min_eq.get('net_liq')
                    net_liq_sod = min_eq.get('net_liq_sod', 0)
                    live_min_equity = min_eq.get('min_equity', 0)
                    tmdl = min_eq.get('trailing_max_drawdown_limit', 50000)
                    if live_net_liq is None:
                        live_net_liq = net_liq_sod
                    _sl_pre = config.get("tradovate_sl_ticks")
                    if net_liq_sod and net_liq_sod > 0:
                        config = self.prop_firm_mgr.calculate_adjusted_sl_midnight_floor(
                            config, live_net_liq, net_liq_sod, tick_value)
                    if tmdl is not None and live_min_equity is not None:
                        config = self.prop_firm_mgr.calculate_adjusted_sl_tmdl_cap(
                            config, live_net_liq, live_min_equity, tmdl, tick_value)
                    self.log(f"🧮 SL floor/TMDL {acct_num}: netLiq=${live_net_liq} SOD=${net_liq_sod} "
                             f"minEq=${live_min_equity} TMDL=${tmdl} → SL {_sl_pre}→{config.get('tradovate_sl_ticks')} ticks")
                    audit("trader.adjust.sl_floor_tmdl", acct_num=str(acct_num or ""),
                          status="applied", scoped_reads=scoped, target_account_id=target_account_id,
                          net_liq=live_net_liq, net_liq_sod=net_liq_sod, min_equity=live_min_equity,
                          tmdl=tmdl, sl_before=_sl_pre, sl_after=config.get("tradovate_sl_ticks"))
                except Exception as _sle2:
                    self.log(f"⚠ SL floor/TMDL failed for {acct_num}: {_sle2}")
                    audit("trader.adjust.sl_floor_tmdl", acct_num=str(acct_num or ""),
                          status="error", error=str(_sle2))

        for _r in (config.get('_adj_reasons') or []):
            self.log(f"📐 {acct_num}: {_r}")
        # Final before→after summary for quick log scanning.
        self.log(f"📐 Adjust result {acct_num} [{'funded' if is_funded else 'challenge/farming'}]: "
                 f"TP {_before_tp}→{config.get('tradovate_tp_ticks')} ticks | "
                 f"SL {_before_sl}→{config.get('tradovate_sl_ticks')} ticks")
        audit("trader.adjust.result", acct_num=str(acct_num or ""), is_funded=bool(is_funded),
              target_account_id=target_account_id, scoped_reads=scoped,
              tp_before=_before_tp, tp_after=config.get("tradovate_tp_ticks"),
              sl_before=_before_sl, sl_after=config.get("tradovate_sl_ticks"),
              reasons=list(config.get('_adj_reasons') or []))
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
                    elif hasattr(acct, 'flatten_all'):
                        # AlphaTrader — cancel all orders and flatten
                        acct.flatten_all()
                        closed_tv += 1
                        self.root.after(0, lambda fn=firm_name:
                            self.log(f"  ✅ {fn} positions flattened"))
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

        # Validation: ML signal mode needs MT5 for price data
        use_signal = self._ml_mode_enabled()
        if use_signal and not self._ensure_mt5_for_signals():
            self.log("⚠ Connect MT5 first — ML signals need price data", "WARN")
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
        self._auto_trade_side_lock_logged = set()

        self._auto_trade_use_signal = use_signal
        firms_in_rows = set()
        for rd in self._active_trade_rows:
            pf = (rd.get("eval") or {}).get("Prop Firm", "Unknown")
            firms_in_rows.add(str(pf).strip() or "Unknown")

        if use_signal:
            existing_firm_sides = getattr(self, "_auto_trade_firm_sides", {}) or {}
            self._auto_trade_firm_sides = dict(existing_firm_sides) if existing_firm_sides else {}
            self.auto_trade_firms_var.set("  🧠  ML signals at execution")
            mode_label = "ML signals + gate"
        else:
            self._auto_trade_firm_sides = self._get_daily_bias(firms_in_rows)
            dir_lines = []
            for firm, s in self._auto_trade_firm_sides.items():
                arrow = "▲" if s == "buy" else "▼"
                dir_lines.append(f"  {arrow} {s.upper():4s}  {firm}")
            self.auto_trade_firms_var.set("\n".join(dir_lines))
            mode_label = "random dirs per firm"
        time_str = scheduled_eat.strftime("%I:%M %p EAT")
        self.auto_trade_btn.configure(text="⏹  Stop Auto-Trade")
        if CTK_AVAILABLE:
            self.auto_trade_btn.configure(fg_color='#dc2626', hover_color='#b91c1c')
        if immediate:
            self.auto_trade_status_var.set(
                f"Starting soon — {mode_label}")
            self.log(f"⚡ Auto-trade starting immediately — {mode_label}")
        else:
            self.auto_trade_status_var.set(f"Scheduled at {time_str} — {mode_label}")
            self.log(f"⏰ Auto-trade scheduled at {time_str} (+{offset_minutes}min random offset)")
        if use_signal:
            self.log("   🧠 Directions from ML at execution (+ phase-aware entry gate)")
            if self._split_payout_mode_enabled():
                self.log(
                    "   ⏳ Split (Tradeify) ON — per-leg signals + cushion SL on "
                    "Tradeify only; other firms use classic funded rules")
            else:
                self.log(
                    "   ⏳ Classic funded — ≥68% + ⚡VOL or ≥72% · "
                    "Challenge ≥58% (~1h)")
        else:
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
        self.auto_trade_btn.configure(text="▶  Start Auto-Trade")
        if CTK_AVAILABLE:
            self.auto_trade_btn.configure(fg_color=self.C_ACCENT, hover_color=self.C_ACCENT_HV)
        self.auto_trade_status_var.set("Auto-trade off")
        self.auto_trade_countdown_var.set("")
        self.auto_trade_firms_var.set("")
        self._auto_trade_firm_sides = {}
        self._auto_trade_waiting_gate = False
        self._auto_trade_side_lock_logged = set()
        self.log("⏹ Auto-trade cancelled")

    def _tick_auto_trade_countdown(self):
        """Update the countdown label every second."""
        if not self.auto_trade_enabled or not self._auto_trade_scheduled_dt:
            return
        if getattr(self, "_auto_trade_waiting_gate", False):
            return  # wait loop owns the countdown label
        from datetime import datetime, timedelta, timezone
        EAT = timezone(timedelta(hours=3))
        now = datetime.now(EAT)
        remaining = self._auto_trade_scheduled_dt - now
        if remaining.total_seconds() <= 0:
            queued = len(getattr(self, "_active_trade_rows", []) or [])
            if queued:
                self.auto_trade_countdown_var.set(
                    f"{queued} trade{'s' if queued != 1 else ''} remaining")
            else:
                self.auto_trade_countdown_var.set("Executing now...")
            return
        hours, rem = divmod(int(remaining.total_seconds()), 3600)
        minutes, seconds = divmod(rem, 60)
        self.auto_trade_countdown_var.set(f"Starts in {hours}h {minutes}m {seconds}s")
        self.root.after(1000, self._tick_auto_trade_countdown)

    def _complete_auto_trade(self):
        """Natural completion when every queued trade has been taken."""
        self.auto_trade_enabled = False
        self._auto_trade_scheduled_dt = None
        self._auto_trade_waiting_gate = False
        self.auto_trade_btn.configure(text="▶  Start Auto-Trade")
        if CTK_AVAILABLE:
            self.auto_trade_btn.configure(fg_color=self.C_ACCENT, hover_color=self.C_ACCENT_HV)
        self.auto_trade_status_var.set("All trades complete ✓")
        self.auto_trade_countdown_var.set("")
        self.auto_trade_firms_var.set("")
        self._auto_trade_firm_sides = {}
        self._auto_trade_side_lock_logged = set()
        self.log("✅ Auto-trade finished — all queued trades taken")

    def _build_acct_to_firm_lookup(self):
        """Map account tokens (full, normalized, suffix) → prop firm display name."""
        lookup = {}
        for rd in (getattr(self, "_active_trade_rows", []) or []):
            acct = str(rd.get("acct_num") or "").strip()
            firm = (rd.get("eval") or {}).get("Prop Firm", rd.get("firm_code", ""))
            if not acct or not firm:
                continue
            lookup[acct.lower()] = firm
            norm = _normalize_acct_for_comment(acct)
            if norm:
                lookup[norm.lower()] = firm
            m = re.search(r"(\d{5,})$", acct)
            if m:
                lookup[m.group(1)] = firm
        for firm_name, mapping in (getattr(self, "_cached_acct_mappings", {}) or {}).items():
            for key, info in (mapping or {}).items():
                acct = str((info or {}).get("account") or key or "").strip()
                if not acct:
                    acct = str(key or "").strip()
                if not acct:
                    continue
                lookup[acct.lower()] = firm_name
                norm = _normalize_acct_for_comment(acct)
                if norm:
                    lookup[norm.lower()] = firm_name
                m = re.search(r"(\d{5,})$", acct)
                if m:
                    lookup[m.group(1)] = firm_name
        return lookup

    def _firm_for_acct_token(self, token, lookup):
        if not token or not lookup:
            return None
        t = str(token).strip().lower()
        if t in lookup:
            return lookup[t]
        for key, firm in lookup.items():
            if len(key) >= 5 and (t.endswith(key) or key.endswith(t)):
                return firm
        return None

    def _detect_open_prop_sides_by_firm(self):
        """Prop-firm direction from open broker legs (MT5 hedge is inverted).

        Result is cached for a few seconds: the gate poll calls this from a
        background thread, and the execute path re-calls it on the UI thread —
        without the cache each call repeats slow broker REST requests and can
        freeze the window.
        """
        now = time.time()
        cached = getattr(self, "_open_prop_sides_cache", None)
        if cached and (now - cached[0]) < 5.0:
            return dict(cached[1])
        out = {}
        lookup = self._build_acct_to_firm_lookup()

        if MT5_AVAILABLE and COMMENT_PARSER_AVAILABLE:
            try:
                import MetaTrader5 as mt5
                if mt5.terminal_info():
                    parser = MT5CommentParser()
                    for pos in (mt5.positions_get() or []):
                        comment = getattr(pos, "comment", "") or ""
                        parsed = parser.parse(comment)
                        if not parsed.is_valid:
                            continue
                        acct = parsed.account_number or ""
                        firm = self._firm_for_acct_token(acct, lookup)
                        if not firm:
                            continue
                        hedge = "buy" if pos.type == 0 else "sell"
                        prop = "sell" if hedge == "buy" else "buy"
                        if firm in out and out[firm] != prop:
                            self.log(
                                f"⚠ {firm}: mixed MT5 hedge directions — using {prop.upper()}",
                                "WARN")
                        out[firm] = prop
            except Exception:
                pass

        for firm_name, conn in (self._broker_connections or {}).items():
            broker = conn.get("account")
            if not broker or not hasattr(broker, "get_positions_api"):
                continue
            try:
                positions = broker.get_positions_api() or []
                for p in positions:
                    net = p.get("netPos", 0)
                    if net == 0:
                        continue
                    prop = "buy" if net > 0 else "sell"
                    if firm_name in out and out[firm_name] != prop:
                        self.log(
                            f"⚠ {firm_name}: mixed broker directions — using {prop.upper()}",
                            "WARN")
                    out[firm_name] = prop
            except Exception:
                pass
        self._open_prop_sides_cache = (now, dict(out))
        return out

    def _sync_auto_trade_firm_sides(self):
        """Merge session sides with open positions — no opposite trades on same firm."""
        sides = dict(getattr(self, "_auto_trade_firm_sides", {}) or {})
        open_sides = self._detect_open_prop_sides_by_firm()
        logged = getattr(self, "_auto_trade_side_lock_logged", None) or set()
        for firm, side in open_sides.items():
            prev = sides.get(firm)
            log_key = (firm, side)
            if log_key not in logged:
                if prev and prev != side:
                    self.log(
                        f"🔒 {firm}: open {side.upper()} position — only {side.upper()} "
                        f"signals allowed (session had {prev.upper()})")
                else:
                    self.log(
                        f"🔒 {firm}: open {side.upper()} position — direction locked")
                logged.add(log_key)
            sides[firm] = side
        self._auto_trade_side_lock_logged = logged
        self._auto_trade_firm_sides = sides
        return sides

    def _run_auto_trade_batch_and_wait(self):
        """Dispatch one execute batch on the UI thread and block until it finishes."""
        self._auto_trade_batch_event.clear()
        self.root.after(0, lambda: self._auto_execute_all_trades(stop_when_done=False))
        self._auto_trade_batch_event.wait(timeout=7200)

    def _finish_auto_trade_batch(self, stop_when_done=False):
        self._auto_trade_batch_event.set()
        if stop_when_done:
            self.root.after(0, self._complete_auto_trade)

    def _auto_trade_loop(self):
        """Background thread: schedule, then keep scanning until all rows are traded."""
        from datetime import datetime, timedelta, timezone
        EAT = timezone(timedelta(hours=3))

        while self.auto_trade_enabled and not self._auto_trade_stop.is_set():
            now = datetime.now(EAT)
            if now >= self._auto_trade_scheduled_dt:
                break
            self._auto_trade_stop.wait(timeout=1)

        if not self.auto_trade_enabled or self._auto_trade_stop.is_set():
            return

        use_signal = getattr(self, "_auto_trade_use_signal", False)
        self._sync_auto_trade_firm_sides()

        while (self.auto_trade_enabled and not self._auto_trade_stop.is_set()
               and self._active_trade_rows):
            self._sync_auto_trade_firm_sides()
            remaining = len(self._active_trade_rows)
            self.root.after(0, lambda n=remaining: self.auto_trade_status_var.set(
                f"Auto-trade active — {n} trade{'s' if n != 1 else ''} remaining"))

            if use_signal:
                if not self._auto_wait_for_gate_once():
                    break
            else:
                self.root.after(0, lambda n=remaining: self.auto_trade_countdown_var.set(
                    f"Executing batch — {n} remaining"))

            if (not self.auto_trade_enabled or self._auto_trade_stop.is_set()
                    or not self._active_trade_rows):
                break

            self._run_auto_trade_batch_and_wait()

            if self._active_trade_rows and self.auto_trade_enabled:
                left = len(self._active_trade_rows)
                self.log(
                    f"🔄 {left} trade(s) still queued — resuming signal watch…")
                self._ai_trace("SIGNAL", f"auto-trade continuing — {left} rows left")
                if self._auto_trade_stop.wait(timeout=10):
                    break

        if self.auto_trade_enabled and not self._auto_trade_stop.is_set():
            self.root.after(0, self._complete_auto_trade)

    def _auto_trade_update_waiting_ui(self, gate_msg, dominant, volatile, consensus,
                                     rows_remaining=0):
        """Status line while auto-trade polls for entry conditions."""
        self._auto_trade_waiting_gate = True
        vol_tag = "⚡VOL ok" if volatile else "waiting ⚡VOL"
        cons_tag = "★ consensus" if consensus else "⏳ diverge"
        short = str(gate_msg or "")[:72]
        rem = rows_remaining or len(getattr(self, "_active_trade_rows", []) or [])
        try:
            self.auto_trade_status_var.set(
                f"Waiting for gate — {rem} left · {short}")
            self.auto_trade_countdown_var.set(
                f"{dominant}% · {vol_tag} · {cons_tag} · Stop to cancel")
        except Exception:
            pass

    def _auto_wait_for_gate_once(self):
        """Poll phase-aware gate until at least one pending row can enter. Returns False if stopped."""
        if not self.auto_trade_enabled or self._auto_trade_stop.is_set():
            return False

        rows = list(getattr(self, "_active_trade_rows", []) or [])
        if not rows:
            return False

        tiers = sorted({
            self._signal_tier_for_phase(
                rd.get("phase_key"), rd.get("current_phase"),
                firm_code=rd.get("firm_code"))
            for rd in rows
        } or {"funded"})
        prof0 = self._get_signal_gate_profile(
            self._permissive_signal_tier_from_rows(rows))
        align_win = prof0.get("bar_align_window_sec")

        self.root.after(0, lambda: self.auto_trade_countdown_var.set(
            "Aligning to M5 bar close…"))
        self._ai_trace("SIGNAL", "auto-trade: waiting for M5 bar close before gate check")
        self._align_signal_to_bar_close(
            stop_event=self._auto_trade_stop, align_window_sec=align_win)
        if self._auto_trade_stop.is_set() or not self.auto_trade_enabled:
            return False

        self.log(
            f"⏳ Auto-trade waiting for phase-aware gate "
            f"(tiers: {', '.join(tiers)} — challenge ≥58% within 1h, "
            f"funded ≥68% intentional)…")
        self._ai_trace("SIGNAL", "auto-trade: polling phase-aware gate until conditions met")
        gate_started = time.time()
        last_logged = ""

        while self.auto_trade_enabled and not self._auto_trade_stop.is_set():
            if not self._active_trade_rows:
                self._auto_trade_waiting_gate = False
                return False
            elapsed = int(time.time() - gate_started)
            allowed, lean, dom, volatile, gate_msg = self._auto_batch_gate_allowed(
                elapsed_sec=elapsed)
            sig = getattr(self, "_signal_strength_state", None) or {}
            consensus = bool(sig.get("consensus"))
            rem = len(self._active_trade_rows)
            self.root.after(0, lambda m=gate_msg, d=dom, v=volatile, c=consensus, r=rem:
                            self._auto_trade_update_waiting_ui(m, d, v, c, r))
            if allowed:
                self._auto_trade_waiting_gate = False
                self.root.after(0, lambda: self.auto_trade_countdown_var.set(
                    "Gate passed — executing…"))
                self.log(f"✅ Auto-trade gate passed — {gate_msg}")
                self._ai_trace("SIGNAL", f"auto-trade gate OK — {gate_msg}")
                return True
            if gate_msg != last_logged:
                last_logged = gate_msg
                self.log(f"   ⏳ Gate ({elapsed // 60}m): {gate_msg}")
                self._ai_trace("SIGNAL", f"auto-trade waiting — {gate_msg}")
            self._align_signal_to_bar_close(
                stop_event=self._auto_trade_stop, align_window_sec=align_win)
            if self._auto_trade_stop.wait(timeout=self.AUTO_TRADE_GATE_POLL_SEC):
                break

        self._auto_trade_waiting_gate = False
        return False

    # ── Entry staggering (risk spreading) ──────────────────────────────
    # Never fire all trades at the exact same second: each firm thread
    # starts with its own offset, and accounts within a firm are spaced
    # by a random gap. All waits are stop-aware (Stop button interrupts).
    AUTO_TRADE_FIRM_STAGGER_BASE_SEC = 15   # firm i starts ~i*15s after firm 0
    AUTO_TRADE_FIRM_STAGGER_JITTER_SEC = 10  # plus 0-10s random jitter
    AUTO_TRADE_ACCOUNT_SPACING_SEC = (20, 60)  # random gap between accounts in a firm
    AUTO_TRADE_MIN_SIGNAL_PCT = 68            # default funded blend floor (challenge uses profile)
    BLEND_MIN_MARGIN_DIVERGE = 15             # min margin when trend/reversal disagree
    AUTO_TRADE_REQUIRE_VOLATILE = True        # funded default; challenge profile skips
    AUTO_TRADE_REQUIRE_CONSENSUS = True       # block diverge — trend + reversal must agree
    AUTO_TRADE_REQUIRE_READY = True           # funded default; challenge uses lighter ML agree
    AUTO_TRADE_GATE_POLL_SEC = 8              # re-check interval while waiting for gate
    # Firms that honor the Split payout toolbar option (others stay classic).
    SPLIT_PAYOUT_FIRM_CODES = frozenset({"Tradeify"})
    # Phase-aware entry: challenge = small TP, fire within ~1h; funded = intentional but bounded
    SIGNAL_GATE_PROFILES = {
        "challenge": {
            "min_blend_pct": 58,
            "min_blend_relaxed": 54,
            "require_volatile": False,
            "require_consensus": True,
            "require_ready": False,
            "require_ml_agree": True,
            "require_setup_fit": False,
            "setup_fit_slack": 1.40,
            "max_wait_sec": 3600,
            "bar_align_window_sec": 45,
            "min_decision_pct": 55,
            "min_diverge_margin": 12,
            "min_diverge_dominant": 52,
            "volatile_bypass_blend": 0,
        },
        "funded": {
            "min_blend_pct": 68,
            "min_blend_relaxed": 64,
            "require_volatile": True,
            "require_consensus": True,
            "require_ready": False,
            "require_ml_agree": True,
            "require_setup_fit": True,
            "setup_fit_slack": 1.0,
            "max_wait_sec": 5400,
            "bar_align_window_sec": 90,
            "min_decision_pct": 60,
            "min_diverge_margin": 15,
            "min_diverge_dominant": 55,
            "volatile_bypass_blend": 72,
        },
        # First leg of a split payout day (e.g. Apex 2×$2,500 toward $5k)
        "funded_split": {
            "min_blend_pct": 62,
            "min_blend_relaxed": 58,
            "require_volatile": False,
            "require_consensus": True,
            "require_ready": False,
            "require_ml_agree": True,
            "require_setup_fit": True,
            "setup_fit_slack": 1.25,
            "max_wait_sec": 3600,
            "bar_align_window_sec": 60,
            "min_decision_pct": 58,
            "min_diverge_margin": 13,
            "min_diverge_dominant": 54,
            "volatile_bypass_blend": 66,
        },
        # Second+ leg same day — SL widens to $2k + profit already banked
        "funded_followup": {
            "min_blend_pct": 60,
            "min_blend_relaxed": 56,
            "require_volatile": False,
            "require_consensus": True,
            "require_ready": False,
            "require_ml_agree": True,
            "require_setup_fit": False,
            "setup_fit_slack": 1.70,
            "max_wait_sec": 3600,
            "bar_align_window_sec": 45,
            "min_decision_pct": 56,
            "min_diverge_margin": 12,
            "min_diverge_dominant": 53,
            "volatile_bypass_blend": 0,
        },
        # Single-shot large funded target (e.g. one trade for full $5k)
        "funded_large": {
            "min_blend_pct": 70,
            "min_blend_relaxed": 66,
            "require_volatile": True,
            "require_consensus": True,
            "require_ready": False,
            "require_ml_agree": True,
            "require_setup_fit": True,
            "setup_fit_slack": 0.95,
            "max_wait_sec": 5400,
            "bar_align_window_sec": 90,
            "min_decision_pct": 62,
            "min_diverge_margin": 16,
            "min_diverge_dominant": 56,
            "volatile_bypass_blend": 74,
        },
        "farming": {
            "min_blend_pct": 52,
            "min_blend_relaxed": 50,
            "require_volatile": False,
            "require_consensus": False,
            "require_ready": False,
            "require_ml_agree": False,
            "require_setup_fit": False,
            "setup_fit_slack": 1.50,
            "max_wait_sec": 3600,
            "bar_align_window_sec": 45,
            "min_decision_pct": 52,
            "min_diverge_margin": 10,
            "min_diverge_dominant": 50,
            "volatile_bypass_blend": 0,
        },
    }

    # Signal timing: if the current M5 bar closes within this window, wait
    # for the close (+ buffer) before computing the signal so the decision
    # uses CONFIRMED bars instead of a half-formed candle that can flip.
    SIGNAL_BAR_ALIGN_WINDOW_SEC = 90
    SIGNAL_BAR_CLOSE_BUFFER_SEC = 2.0

    def _is_funded_phase_key(self, phase_key=None):
        """True for funded / double-dip / Apex payout trade keys."""
        pk = (phase_key or "").lower().strip()
        if pk.startswith("funded_trade"):
            return True
        return pk.startswith("payout") and "_trade" in pk

    def _phase_trade_index(self, phase_key=None):
        """1-based trade index from phase_key suffix (payout1_trade2 → 2)."""
        pk = (phase_key or "").lower().strip()
        if pk.startswith("payout") and "_trade" in pk:
            suf = pk.split("_trade")[-1].strip()
            return int(suf) if suf.isdigit() else 1
        m = re.search(r"(\d+)$", pk)
        return int(m.group(1)) if m else 1

    def _config_tp_dollars(self, config):
        """Blueprint Tradovate TP in dollars (None if unknown)."""
        if not config:
            return None
        sym = (config.get("tradovate_symbol", "")
               or config.get("topstepx_symbol", ""))
        qty = int(config.get("tradovate_qty", 0)
                   or config.get("topstepx_qty", 0) or 0)
        tp = int(config.get("tradovate_tp_ticks", 0)
                 or config.get("topstepx_tp_ticks", 0) or 0)
        if qty <= 0 or tp <= 0:
            return None
        tick_val = 5.0
        if self.prop_firm_mgr and sym:
            try:
                tick_val = self.prop_firm_mgr.get_tick_value(sym)
            except Exception:
                pass
        return qty * tp * tick_val

    def _signal_tier_for_phase(self, phase_key=None, current_phase=None,
                               config=None, firm_code=None):
        """Map blueprint phase → signal strictness tier."""
        pk = (phase_key or "").lower().strip()
        cp = (current_phase or "").lower().strip()
        if pk == "farming" or "farming" in cp or "min trading days" in cp:
            return "farming"
        if pk.startswith("challenge") or cp in (
                "challenge", "challenge phase", "evaluation", "eval"):
            return "challenge"
        is_funded = (
            self._is_funded_phase_key(pk)
            or pk.startswith("funded")
            or "funded" in cp
            or "residual" in cp
            or pk.startswith("double_dip")
            or "double dip" in cp
        )
        if not is_funded:
            return "funded"

        if not self._split_payout_applies(firm_code):
            return "funded"

        trade_idx = self._phase_trade_index(pk)
        tp_d = self._config_tp_dollars(config)

        # Second leg same payout day: wider SL ($2k + banked profit) — faster gate
        if trade_idx >= 2:
            return "funded_followup"
        # Split payout (2× ~$2.5k) vs one-shot ~$5k
        if tp_d is not None:
            if tp_d >= 4000:
                return "funded_large"
            if tp_d <= 3200:
                return "funded_split"
        return "funded"

    def _get_signal_gate_profile(self, tier=None, elapsed_sec=0):
        """Per-phase gate thresholds; relax slightly after max_wait_sec."""
        tier = tier or "funded"
        base = dict(self.SIGNAL_GATE_PROFILES.get(
            tier, self.SIGNAL_GATE_PROFILES["funded"]))
        if elapsed_sec >= int(base.get("max_wait_sec") or 99999):
            base["min_blend_pct"] = base.get(
                "min_blend_relaxed", base["min_blend_pct"])
            base["require_volatile"] = False
            base["require_ready"] = False
            if tier == "funded":
                base["require_setup_fit"] = False
            elif tier in ("funded_large", "funded_split"):
                base["min_blend_pct"] = base.get(
                    "min_blend_relaxed", base["min_blend_pct"])
                base["require_volatile"] = False
            base["relaxed"] = True
        return base

    def _signal_tier_rank(self, tier, firm_code=None):
        """Lower rank = more permissive (fires earlier)."""
        if self._split_payout_applies(firm_code):
            order = {
                "farming": 0,
                "funded_followup": 1,
                "funded_split": 2,
                "challenge": 3,
                "funded": 4,
                "funded_large": 5,
            }
            return order.get(tier, 4)
        order = {"farming": 0, "challenge": 1, "funded": 2}
        return order.get(tier, 2)

    def _permissive_signal_tier_from_rows(self, rows):
        """Most permissive tier among loaded rows (fires earliest)."""
        best = "funded"
        best_rank = 99
        for rd in rows or []:
            fc = rd.get("firm_code")
            config = None
            if self.prop_firm_mgr:
                try:
                    config = self.prop_firm_mgr.get_strategy_config(
                        fc, rd.get("phase_key"), rd.get("acct_size"))
                except Exception:
                    config = None
            tier = self._signal_tier_for_phase(
                rd.get("phase_key"), rd.get("current_phase"),
                config=config, firm_code=fc)
            rank = self._signal_tier_rank(tier, fc)
            if rank < best_rank:
                best, best_rank = tier, rank
        return best

    def _align_signal_to_bar_close(self, timeframe_sec=300, stop_event=None,
                                   align_window_sec=None):
        """Wait (bounded) for the M5 bar close when it is imminent.

        Returns True if we waited. Far from the close, returns immediately —
        the bounded window keeps scheduled trades on time (max ~92s delay).
        """
        window = (align_window_sec if align_window_sec is not None
                  else self.SIGNAL_BAR_ALIGN_WINDOW_SEC)
        remaining = timeframe_sec - (time.time() % timeframe_sec)
        if remaining > window:
            return False
        wait = remaining + self.SIGNAL_BAR_CLOSE_BUFFER_SEC
        self._ai_trace("SIGNAL", f"timing: M5 bar closes in {remaining:.0f}s — "
                                 f"waiting for the close so the signal uses confirmed bars")
        if stop_event is not None:
            stop_event.wait(wait)
        else:
            time.sleep(wait)
        return True

    def _auto_execute_all_trades(self, stop_when_done=True):
        """Execute trades for ALL loaded rows, parallel across prop firms.

        Each prop firm has its own Chrome instance opened during initialization.
        Trades for different firms run in parallel threads (one thread per firm),
        while trades for the same firm run sequentially within that thread.
        Entries are deliberately staggered (per-firm offset + per-account gap)
        so positions open at different times and risk is spread.

        When stop_when_done is False the outer auto-trade loop keeps running
        until every row is taken (or the user clicks Stop).
        """
        firm_sides = dict(getattr(self, '_auto_trade_firm_sides', {}) or {})
        use_signal = getattr(self, '_auto_trade_use_signal', False)
        rows = list(self._active_trade_rows)  # snapshot

        if not rows:
            self.log("⚠ No trades to execute — list is empty")
            self._finish_auto_trade_batch(stop_when_done=stop_when_done)
            if stop_when_done:
                self._stop_auto_trade()
            return

        self._sync_auto_trade_firm_sides()
        firm_sides = dict(getattr(self, '_auto_trade_firm_sides', {}) or {})

        self.log(f"🚀 Auto-executing {len(rows)} accounts (parallel per firm)...")

        sig = self._compute_signal_strength(max_age_sec=0) if use_signal else {}
        if use_signal and sig.get("ready"):
            self.log(f"📊 Signal: {sig['label']} — highly recommended "
                     f"{str(sig.get('recommended', '')).upper()}")
        elif use_signal:
            self.log(f"📊 Signal: {sig.get('label', '—')} ({sig.get('detail', '')})")

        if use_signal:
            allowed, lean, dom, volatile, gate_msg = self._auto_batch_gate_allowed()
            if not allowed:
                self.log(f"⛔ Auto-trade gate: {gate_msg}", "WARN")
                self._ai_trace("WARN", f"auto-trade blocked at execute — {gate_msg}")
                self._finish_auto_trade_batch(stop_when_done=stop_when_done)
                return
            self.log(f"✅ Auto-trade gate passed — {gate_msg}")
        else:
            self.log("🎲 Auto-trade using daily random direction per prop firm")

        hedging = self.hedge_mode_var.get() == "Hedging"
        default_platform = self.broker_var.get()
        mt5_api = self._get_mt5_trading_api() if hedging else None
        if hedging and not mt5_api:
            messagebox.showerror(
                "MT5 Not Connected",
                "Connect MT5 first, or switch to 'Broker Only' mode to skip MT5 hedging."
            )
            self.log("❌ Auto-trade aborted — MT5 not connected (Hedging mode requires MT5)")
            self._finish_auto_trade_batch(stop_when_done=stop_when_done)
            if stop_when_done:
                self._stop_auto_trade()
            return

        # Group rows by firm so each firm's Chrome runs in its own thread
        rows_by_firm = defaultdict(list)
        for row_data in rows:
            firm_name = row_data["eval"].get("Prop Firm", row_data["firm_code"])
            rows_by_firm[firm_name].append(row_data)

        # Seed any missing firm-side directions from the current UI signal so
        # the entry direction used by auto-trade matches what the user sees.
        if use_signal and not firm_sides and getattr(self, '_last_ai_signal', None) in ('buy', 'sell'):
            firm_sides = {firm_name: self._last_ai_signal for firm_name in rows_by_firm}

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
                self.log("⚠ No valid accounts remain — will retry when queue changes")
                self._finish_auto_trade_batch(stop_when_done=stop_when_done)
                if stop_when_done:
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
                self._finish_auto_trade_batch(stop_when_done=stop_when_done)
                if stop_when_done:
                    self._stop_auto_trade()
                return
            self.root.after(0, self._refresh_mt5_margin_after_scan)

        total_success = threading.Lock()
        counters = {"success": 0, "fail": 0, "skipped": len(skipped_rows) + margin_skipped}

        def _execute_firm_trades(firm_name, firm_rows, stagger_offset=0.0):
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

            firm_locks = self._sync_auto_trade_firm_sides()
            locked_side = firm_locks.get(firm_name)

            # ── Stagger this firm's start so firms never fire together ──
            if stagger_offset > 0:
                self.root.after(0, lambda fn=firm_name, d=stagger_offset: self.log(
                    f"⏳ {fn}: staggered start in {d:.0f}s (risk spreading)"))
                if self._auto_trade_stop.wait(timeout=stagger_offset):
                    return  # auto-trade stopped during the wait

            for row_idx, row_data in enumerate(firm_rows):
                if self._auto_trade_stop.is_set():
                    break

                # ── Space accounts within the firm (risk spreading) ──
                if row_idx > 0:
                    gap = random.uniform(*self.AUTO_TRADE_ACCOUNT_SPACING_SEC)
                    self.root.after(0, lambda fn=firm_name, g=gap: self.log(
                        f"⏳ {fn}: next account in {g:.0f}s (risk spreading)"))
                    if self._auto_trade_stop.wait(timeout=gap):
                        break

                firm_code = row_data["firm_code"]
                phase_key = row_data["phase_key"]
                acct_size = row_data["acct_size"]
                acct_num = row_data["acct_num"]

                # For AlphaTrader, auto-detect account size from live balance when
                # eval row doesn't have a size value.
                if platform == "AlphaTrader" and acct_size in ("—", "-", "", "N/A"):
                    try:
                        detected = broker_account.get_account_size_label("AlphaFutures")
                        if detected:
                            acct_size = detected
                    except Exception:
                        pass

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

                # Direction: ML signals (opt-in) or daily random bias per firm.
                # Open positions lock the firm to one prop direction only.
                if use_signal:
                    if locked_side in ("buy", "sell"):
                        firm_sides[firm_name] = locked_side
                    elif firm_name not in firm_sides:
                        config_tmp = None
                        if self.prop_firm_mgr:
                            config_tmp = self.prop_firm_mgr.get_strategy_config(
                                firm_code, phase_key, acct_size)
                        mt5_sym = self._resolve_mt5_hedge_symbol(config_tmp or {})
                        self._align_signal_to_bar_close(stop_event=self._auto_trade_stop)
                        if self._auto_trade_stop.is_set():
                            break
                        sig = self._get_signal_direction(mt5_sym)
                        req = firm_locks.get(firm_name)
                        if req and sig in ("buy", "sell") and sig != req:
                            self._ai_trace(
                                "WARN",
                                f"{firm_name}: signal {sig.upper()} ≠ locked {req.upper()} — skipped")
                            self.root.after(0, lambda fn=firm_name, s=sig, r=req: self.log(
                                f"⛔ {fn}: signal {s.upper()} but firm locked "
                                f"{r.upper()} — batch skipped for this firm", "WARN"))
                            with total_success:
                                counters["skipped"] += len(firm_rows) - row_idx
                            break
                        if sig in ("buy", "sell"):
                            firm_sides[firm_name] = sig
                            self._ai_trace("SIGNAL", f"{firm_name}: AI direction locked → {sig.upper()}")
                            self.root.after(0, lambda fn=firm_name, s=sig, sym=mt5_sym:
                                self.log(f"   📊 {fn} ({sym}) → signal: {s.upper()}"))
                    side = firm_sides.get(firm_name)
                    if side not in ("buy", "sell"):
                        self._ai_trace("WARN", f"{acct_num}: NO ML signal — trade skipped")
                        self.root.after(0, lambda an=acct_num: self.log(
                            f"⛔ {an}: no ML signal — trade skipped", "WARN"))
                        with total_success:
                            counters["fail"] += 1
                        continue
                else:
                    if locked_side in ("buy", "sell"):
                        side = locked_side
                    else:
                        side = firm_sides.get(firm_name, random.choice(["buy", "sell"]))
                        firm_sides[firm_name] = side

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

                if use_signal:
                    _cp = row_data.get("current_phase", "")
                    allowed, _lean, _dom, _vol, gate_msg = self._auto_trade_entry_allowed(
                        phase_key=phase_key, config=config, current_phase=_cp,
                        firm_code=firm_code)
                    if not allowed:
                        self._ai_trace("WARN", f"{acct_num}: auto-trade skipped — {gate_msg}")
                        self.root.after(0, lambda an=acct_num, gm=gate_msg: self.log(
                            f"⛔ {an}: auto gate — {gm}", "WARN"))
                        with total_success:
                            counters["skipped"] += 1
                        continue

                # Phase distance advisory — tier-aware; funded can block via gate above
                _st = getattr(self, "_signal_strength_state", {}) or {}
                _tier = self._signal_tier_for_phase(
                    phase_key, row_data.get("current_phase"), config=config,
                    firm_code=firm_code)
                fit_ok, fit_detail = self._phase_setup_fit(
                    config, _st.get("capacity"), tier=_tier)
                if not fit_ok:
                    self._ai_trace("WARN",
                        f"{acct_num}: phase {phase_key} TP/SL may not fit "
                        f"current reach ({fit_detail})")
                    self.root.after(0, lambda an=acct_num, d=fit_detail: self.log(
                        f"⚠ {an}: phase TP/SL tight for setup — {d}", "WARN"))

                trado_sym = config.get("tradovate_symbol", "") or config.get("topstepx_symbol", "")
                trado_qty = int(config.get("tradovate_qty", 2) or config.get("topstepx_qty", 2))

                # Log resolved blueprint up-front so the user can verify the
                # correct trade is being placed (catches farming/challenge mix-ups).
                _bp_tp = config.get("tradovate_tp_ticks", config.get("topstepx_tp_ticks", "?"))
                _bp_sl = config.get("tradovate_sl_ticks", config.get("topstepx_sl_ticks", "?"))
                _an, _fc, _pk, _sz = acct_num, firm_code, phase_key, acct_size
                _bs, _bq, _bt, _bsl = trado_sym, trado_qty, _bp_tp, _bp_sl
                self._ai_trace("BLUEPRINT",
                               f"{acct_num}: EXECUTING with {firm_code}/{phase_key}/{acct_size} "
                               f"→ {trado_sym} qty={trado_qty} TP={_bp_tp}t SL={_bp_sl}t")
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
                mt5_sym = self._resolve_mt5_hedge_symbol(config)
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
                    elif platform == "AlphaTrader":
                        order_result = broker_account.place_order(
                            trado_sym, side=side, qty=trado_qty,
                            tp_ticks=trado_tp, sl_ticks=trado_sl,
                            expected_account=acct_num,
                        )
                    elif platform == "BlackArrow":
                        order_result = broker_account.place_order(
                            trado_sym, side=side, qty=trado_qty,
                            tp_ticks=trado_tp, sl_ticks=trado_sl,
                        )
                    elif platform == "TopStepX":
                        # Account is already selected upstream — don't re-open the slow
                        # dropdown here. place_*_order verifies the selector still matches
                        # acct_num (expected_account) and only switches if it drifted,
                        # so we stay fast while never firing on the wrong account.
                        # TopStepX uses two-digit year futures codes (NQU26, MNQU26)
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
                    if order_result is False:
                        raise Exception(f"{platform} order failed — check broker window for details")

                    self._ai_trace("TRADE",
                                   f"{acct_num}: {platform} {side.upper()} {trado_qty} {trado_sym} "
                                   f"FILLED (TP={trado_tp}t SL={trado_sl}t)")
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
                        self._ai_trace("TRADE",
                                       f"{acct_num}: MT5 hedge {hedge_side.upper()} {mt5_vol} {mt5_sym} "
                                       f"(TP={mt5_tp}pts SL={mt5_sl}pts)")
                        self.root.after(0, lambda an=acct_num, hs=hedge_side, vol=mt5_vol, sym=mt5_sym, cmt=comment:
                            self.log(f"✅ MT5 hedge {hs.upper()} {vol} {sym} comment:{cmt} → {an}"))

                    with total_success:
                        counters["success"] += 1

                    self._auto_trade_firm_sides[firm_name] = side
                    self._auto_trade_side_lock_logged.add((firm_name, side))

                    # ── Auto-status: set "In Progress" when trades go out ──
                    if not RELEASE_DISABLE_AUTO_STATUS_UPDATES:
                        _ev = row_data.get("eval")
                        if _ev:
                            _has_funded = bool(self._cell(row_data.get("eval", {}).get("Account #.1")))
                            _sf = "Status" if _has_funded else "Status P1"
                            _cur = self._cell(_ev.get(_sf)).lower()
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

                except Exception as e:
                    with total_success:
                        counters["fail"] += 1
                    self._ai_trace("WARN", f"{acct_num}: trade FAILED — {e}")
                    self.root.after(0, lambda an=acct_num, err=str(e):
                        self.log(f"❌ Auto-trade failed for {an}: {err}", "ERROR"))

        def _dispatch_parallel():
            num_firms = len(rows_by_firm)
            self.root.after(0, lambda n=num_firms: self.log(
                f"⚡ Dispatching trades across {n} firm(s) — staggered entries (risk spreading)..."))
            with ThreadPoolExecutor(max_workers=num_firms) as executor:
                futures = {
                    executor.submit(
                        _execute_firm_trades, firm, firm_rows,
                        idx * self.AUTO_TRADE_FIRM_STAGGER_BASE_SEC
                        + random.uniform(0, self.AUTO_TRADE_FIRM_STAGGER_JITTER_SEC),
                    ): firm
                    for idx, (firm, firm_rows) in enumerate(rows_by_firm.items())
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
                self.log(f"🏁 Auto-trade batch: {s} succeeded, {f} failed, {sk} skipped"))
            self._finish_auto_trade_batch(stop_when_done=stop_when_done)

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
        missing_creds = []  # list of firm names that have no dashboard creds
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
                    "funded next flex": ["fundednextflex", "funded next", "fundednext"],
                    "fundednextflex": ["funded next flex", "funded next", "fundednext"],
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
            creds_from_dashboard = bool(pre_user and pre_pass)

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
            else:
                # Don't hang / silently wait: record missing creds so UI + logs are explicit.
                missing_creds.append(firm)
                try:
                    # Mark status as missing creds (unless already connected)
                    if not existing_account:
                        status_var.set("❌")
                        if hasattr(conn_btn, "configure"):
                            conn_btn.configure(text="Missing", fg_color="#450A0A")
                        if hasattr(status_lbl, "configure"):
                            status_lbl.configure(text_color="#F87171")
                except Exception:
                    pass

            self._broker_connections[firm] = {
                "user_entry": user_entry,
                "pass_entry": pass_entry,
                "connect_btn": conn_btn,
                "status_var": status_var,
                "status_lbl": status_lbl,
                "row_frame": row,
                "account": existing_account,
                "creds_source": "dashboard" if creds_from_dashboard else "missing",
            }

        if missing_creds:
            # Explicit log line per firm so it's impossible to miss.
            for _f in missing_creds:
                self.log(f"❌ Could not find Tradovate credentials for {_f}", "ERROR")

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
                elif platform == "AlphaTrader":
                    if not ALPHATRADER_AVAILABLE:
                        err = _ALPHATRADER_IMPORT_ERROR or 'unknown reason'
                        self.root.after(0, lambda: conn["status_var"].set("❌"))
                        self.log(f"AlphaTrader import failed: {err}", "ERROR")
                        self.root.after(0, lambda: conn["connect_btn"].configure(text="Connect"))
                        return
                    account = AlphaTraderConnector(email=user, password=pwd)
                    account.connect()
                elif platform == "BlackArrow":
                    if not BLACKARROW_AVAILABLE:
                        err = _BLACKARROW_IMPORT_ERROR or 'unknown reason'
                        self.root.after(0, lambda: conn["status_var"].set("❌"))
                        self.log(f"BlackArrow import failed: {err}", "ERROR")
                        self.root.after(0, lambda: conn["connect_btn"].configure(text="Connect"))
                        return
                    # Gather account IDs from active evals for this firm
                    _ba_acct_ids = [
                        str(rd["eval"].get("Account #") or rd["eval"].get("Account #.1") or "").strip()
                        for rd in getattr(self, "_active_trade_rows", [])
                        if isinstance(rd.get("eval"), dict) and str(rd["eval"].get("Prop Firm") or "").strip() == firm_name
                    ]
                    _ba_acct_id = next((a for a in _ba_acct_ids if a), "")
                    account = BlackArrowConnector(email=user, password=pwd, account_id=_ba_acct_id)
                    account.connect()
                    self.log("⚠ BlackArrow: if a 2FA code is requested, enter it manually in the browser window.")
                else:
                    self.root.after(0, lambda: conn["status_var"].set("❌"))
                    self.log(f"Unknown platform: {platform}", "ERROR")
                    self.root.after(0, lambda: conn["connect_btn"].configure(text="Connect"))
                    return

                conn["account"] = account
                # Also keep legacy references for backward compatibility
                if platform == "Tradovate":
                    self.tradovate_account = account
                elif platform == "TopStepX":
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
                    # AI warm-up (ML training + indicator vote) starts only
                    # when ALL populated brokers are connected & ready.
                    self._check_all_brokers_ready()
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

    def _check_all_brokers_ready(self):
        """Fire the AI warm-up once EVERY populated broker row is connected.

        ML training and the indicator vote are intentionally deferred until
        all Tradovate/TopStepX accounts are ready to trade, so the AI spends
        its compute when it matters and the first signal reflects market
        conditions at trading time, not at app start. Runs once per trade
        load (re-armed each time Active Trades are rendered).
        """
        if getattr(self, "_ai_warmup_done", False):
            return
        if not self._ml_mode_enabled():
            return
        conns = self._broker_connections or {}
        if not conns:
            return
        try:
            populated = [f for f, c in conns.items()
                         if c["user_entry"].get().strip() and c["pass_entry"].get().strip()]
        except Exception:
            return
        if not populated:
            return
        not_ready = [f for f in populated if not conns[f].get("account")]
        if not_ready:
            self._ai_trace("DIAG", f"AI warm-up waiting — {len(not_ready)} broker(s) "
                                   f"not connected yet: {', '.join(sorted(not_ready))}")
            return
        self._ai_warmup_done = True
        self._on_all_brokers_ready(populated)

    def _on_all_brokers_ready(self, firms):
        """All accounts are ready to trade — NOW start ML training + vote."""
        self.log(f"🧠 All {len(firms)} broker(s) connected & ready — starting ML "
                 f"training + indicator vote")
        self._ai_trace("ML", f"all {len(firms)} broker(s) ready to trade — "
                             f"ML/DL training + indicator vote starting now")
        if ML_DIRECTION_AVAILABLE and ml_direction_engine is not None:
            try:
                ml_direction_engine.ensure_trained_async("ustech", log_fn=self._ml_log)
            except Exception:
                pass
        target_firms = getattr(self, "_active_trade_firms", None) or set(firms)
        self._refresh_ai_direction_async(target_firms)

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
            elif not user or not pwd:
                # If a firm row exists but has missing creds, log it explicitly once.
                if (conn.get("creds_source") == "missing") and not conn.get("account"):
                    self.log(f"❌ Auto-connect skipped: missing Tradovate credentials for {firm}", "ERROR")

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
        "Funded Next Flex":  {"class_available": "CDP_SCRAPERS_AVAILABLE", "account_class": "FundedNextCDPAccount",
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
        "LucidMaxx":         {"class_available": "CDP_SCRAPERS_AVAILABLE", "account_class": "LucidTradingAccount",
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

                acct_challenge = self._cell(ev.get("Account #"))
                acct_funded = self._cell(ev.get("Account #.1"))
                existing_fee = self._cell(ev.get("Fee"))
                existing_date = self._cell(ev.get("Date Purchased"))

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
                    ev_size_str = self._cell(ev.get("Account Size"))
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
                    existing_start = self._cell(ev.get("Date Started"))
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
                    # ── Defensive orphan-bracket sweep ──
                    # cancel_all_orders_api() only cancels working orders when the
                    # account is flat. In this app every working order on a flat
                    # account is an orphaned TP/SL leg left over after the position
                    # closed — if not cleaned up it later triggers as a random naked
                    # trade. This is the safety net behind the OCO bracket linking.
                    try:
                        if hasattr(tv_account, 'cancel_all_orders_api'):
                            cancelled = tv_account.cancel_all_orders_api(account_id=aid)
                            if cancelled:
                                self.root.after(0, lambda n=aname, c=cancelled:
                                    self.log(f"🧹 Status poll: cancelled {c} orphaned order(s) on flat account {n}"))
                    except Exception:
                        pass
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

            acct_challenge = self._cell(ev.get("Account #"))
            acct_funded = self._cell(ev.get("Account #.1"))
            current_p1 = self._cell(ev.get("Status P1")).lower()
            current_status = self._cell(ev.get("Status")).lower()

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
                        "funded next flex": ["fundednextflex", "funded next", "fundednext"],
                        "fundednextflex": ["funded next flex", "funded next", "fundednext"],
                        "my funded futures": ["mffu"],
                        "mffu": ["my funded futures"],
                    }
                    ev_aliases = _FIRM_ALIASES.get(ev_firm.lower(), [])
                    firm_match = firm_name.lower() in ev_aliases or canonical_firm.lower() in ev_aliases
                if not firm_match:
                    continue

                acct_challenge = self._cell(ev.get("Account #"))
                acct_funded = self._cell(ev.get("Account #.1"))
                current_status_p1 = self._cell(ev.get("Status P1")).lower()
                current_status = self._cell(ev.get("Status")).lower()

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
                    ev_size_str = self._cell(ev.get("Account Size"))
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
        _name_stripped = name.lower().replace("%", "").replace(" ", "")
        if "blackarrow" in name.lower() or "the5ers" in _name_stripped or "5ers" in _name_stripped:
            return "BlackArrow"
        if "alphafutures" in name.lower() or "alpha futures" in name.lower():
            return "AlphaTrader"

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

    def _resolve_mt5_hedge_symbol(self, config=None):
        """Dashboard hedge account + broker/server override, then blueprint default."""
        try:
            from trader_companion.mt5_symbol_policy import resolve_hedge_mt5_symbol
        except ImportError:
            from mt5_symbol_policy import resolve_hedge_mt5_symbol
        server = ""
        try:
            server = self.mt5_server.get().strip()
        except Exception:
            pass
        return resolve_hedge_mt5_symbol(
            config=config or {},
            hedge_account=getattr(self, "_hedge_account_profile", None) or {},
            server=server,
        )

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
                # Same lock as pusher.connect_mt5 — concurrent mt5.initialize()
                # calls cause -10003 IPC pipe timeouts.
                with _MT5_INIT_LOCK:
                    connected = self.trading_api.connect()
                if connected:
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
        elif mt5.terminal_info():
            try:
                from trader_companion.mt5_market_feed import start_mt5_market_feed
                start_mt5_market_feed()
            except Exception:
                pass
            return True
        return False

    # ============ Daily Bias Persistence ============

    def _ml_mode_enabled(self):
        """True when the user unlocked ML signal mode (password-gated checkbox)."""
        var = getattr(self, "ml_mode_var", None)
        return bool(var and var.get())

    def _split_payout_mode_enabled(self):
        """True when the Split (Tradeify) toolbar checkbox is checked."""
        var = getattr(self, "funded_split_payout_var", None)
        return bool(var and var.get())

    def _split_payout_applies(self, firm_code=None):
        """Split payout SL + signal tiers — Tradeify only, when checkbox is on."""
        if not self._split_payout_mode_enabled():
            return False
        fc = self._resolve_firm_code(firm_code, default="") if firm_code else ""
        return fc in self.SPLIT_PAYOUT_FIRM_CODES

    def _funded_sl_mode(self, firm_code=None):
        """PropFirmManager sl_mode string for calculate_funded_sl."""
        if not self.prop_firm_mgr:
            return "classic"
        if self._split_payout_applies(firm_code):
            return self.prop_firm_mgr.FUNDED_SL_MODE_SPLIT
        return self.prop_firm_mgr.FUNDED_SL_MODE_CLASSIC

    def _toggle_ml_mode(self):
        """Enable ML signals only after password; default is random per firm."""
        if self._ml_mode_enabled():
            pwd = simpledialog.askstring(
                "ML Signals",
                "Enter password to enable ML signals:",
                show="*",
            )
            if pwd != self.ML_MODE_PASSWORD:
                self.ml_mode_var.set(False)
                messagebox.showerror("Access Denied", "Incorrect password.")
                return
            self.log("🧠 ML signal mode enabled — AI drives direction + auto-trade gate")
            self._ai_warmup_done = False
            self._check_all_brokers_ready()
            firms = getattr(self, "_active_trade_firms", None) or set()
            if firms:
                self._refresh_ai_direction_async(firms)
            self._refresh_setup_locks_async()
        else:
            self.log("🎲 Random mode — daily BUY/SELL per prop firm (default)")
            firms = set()
            for rd in self._active_trade_rows:
                pf = (rd.get("eval") or {}).get("Prop Firm", "Unknown")
                firms.add(str(pf).strip() or "Unknown")
            if firms:
                bias = self._get_daily_bias(firms)
                self._auto_trade_firm_sides = bias
                for rd in self._active_trade_rows:
                    pf = (rd.get("eval") or {}).get("Prop Firm", "Unknown")
                    self._style_direction_buttons(rd, bias.get(pf, "buy"))
                parts = []
                for f, s in sorted(bias.items()):
                    arrow = "▲" if s == "buy" else "▼"
                    parts.append(f"{arrow} {f}: {s.upper()}")
                self.log(f"Direction bias: {', '.join(parts)}")

    def _get_daily_bias(self, firms):
        """Get or create today's direction bias per prop firm.

        Persisted to trader_bias.json so it survives app restarts.
        Resets automatically on a new calendar day (EAT).
        """
        from datetime import datetime, timedelta, timezone
        EAT = timezone(timedelta(hours=3))
        today_str = datetime.now(EAT).strftime("%Y-%m-%d")

        bias_path = os.path.join(os.path.dirname(__file__), "trader_bias.json")
        saved = {}
        if os.path.exists(bias_path):
            try:
                with open(bias_path, "r") as f:
                    saved = json.load(f)
            except Exception:
                saved = {}

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
                with open(bias_path, "w") as f:
                    json.dump(saved, f, indent=2)
            except Exception:
                pass

        return {f: firm_bias[f] for f in firms}

    def _refresh_ai_direction_async(self, firms):
        """Compute the AI (ML/DL) direction in the background and restyle rows.

        Replaces the old daily coin-flip bias: the suggested BUY/SELL on every
        Active Trades row comes from _get_signal_direction (local ML/DL
        ensemble → indicator vote), never from random.
        """
        def _worker():
            try:
                sig = self._get_signal_direction("ustech")
            except Exception:
                return
            if sig not in ("buy", "sell"):
                return

            def _apply(s=sig, fs=set(firms)):
                self._last_ai_signal = s
                self._auto_trade_firm_sides = {f: s for f in fs}
                for rd in list(self._active_trade_rows):
                    self._style_direction_buttons(rd, s)
            self.root.after(0, _apply)

        threading.Thread(target=_worker, name="ai-direction", daemon=True).start()

    def _style_direction_buttons(self, row_data, bias):
        """Re-color a row's BUY/SELL buttons to highlight the AI direction."""
        buy_btn = row_data.get("buy_btn")
        sell_btn = row_data.get("sell_btn")
        if not buy_btn or not sell_btn:
            return
        try:
            if CTK_AVAILABLE:
                if bias == "buy":
                    buy_btn.configure(fg_color="#052E16", border_color="#16A34A",
                                      text_color="#4ADE80", hover_color="#14532D")
                    sell_btn.configure(fg_color="#0A0F1A", border_color="#1A1A2E",
                                       text_color="#2A3040", hover_color="#0A0F1A")
                else:
                    buy_btn.configure(fg_color="#0A0F1A", border_color="#1A1A2E",
                                      text_color="#2A3040", hover_color="#0A0F1A")
                    sell_btn.configure(fg_color="#2D0A0A", border_color="#DC2626",
                                       text_color="#F87171", hover_color="#450A0A")
            else:
                buy_btn.configure(bg='#052E16' if bias == 'buy' else '#0A0F1A',
                                  fg='#4ADE80' if bias == 'buy' else '#2A3040')
                sell_btn.configure(bg='#2D0A0A' if bias == 'sell' else '#0A0F1A',
                                   fg='#F87171' if bias == 'sell' else '#2A3040')
        except Exception:
            pass

    # ============ Indicator-Based Signal ============

    # Signal functions mapped by name → (callable, buy_values, sell_values)
    # buy_values/sell_values are the return strings that map to buy/sell
    _SIGNAL_INDICATORS = None  # populated lazily

    @staticmethod
    def _price_vs_ma_signal(get_ma_value):
        """Wrap a raw moving-average function into a buy/sell signal.

        SMA/EMA modules return the MA *value*, not a direction — the classic
        trend rule is applied here: close above MA = buy, below = sell.
        """
        def _sig(symbol, timeframe, period=21):
            try:
                ma = get_ma_value(symbol, timeframe, period)
                if ma is None:
                    return None
                rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 1)
                if rates is None or len(rates) == 0:
                    return None
                close = float(rates[-1][4])
                ma = float(ma)
                if close > ma:
                    return "buy"
                if close < ma:
                    return "sell"
            except Exception:
                pass
            return None
        return _sig

    @classmethod
    def _get_indicator_map(cls):
        """Build indicator map lazily (needs imports to be resolved)."""
        if cls._SIGNAL_INDICATORS is not None:
            return cls._SIGNAL_INDICATORS
        indicators = {}
        # name → (callable(symbol, timeframe), buy return values, sell return values)
        candidates = [
            ("RSI", lambda: get_rsi_signal, {"buy"}, {"sell"}),
            ("MACD", lambda: get_macd_signal, {"buy"}, {"sell"}),
            ("Stochastic", lambda: get_stochastic_signal, {"buy"}, {"sell"}),
            ("CCI", lambda: get_cci_signal, {"buy"}, {"sell"}),
            ("Supertrend", lambda: get_supertrend_signal, {"bullish"}, {"bearish"}),
            ("Momentum", lambda: get_momentum_signal, {"bullish"}, {"bearish"}),
            ("BollingerBands", lambda: get_bb_signal, {"lower"}, {"upper"}),
            ("SMA", lambda: cls._price_vs_ma_signal(get_sma_signal), {"buy"}, {"sell"}),
            ("EMA", lambda: cls._price_vs_ma_signal(get_ema_signal), {"buy"}, {"sell"}),
            ("DMI", lambda: get_dmi_signal, {"bullish"}, {"bearish"}),
            ("MFI", lambda: get_mfi_signal, {"buy"}, {"sell"}),
            ("ROC", lambda: get_roc_signal, {"bullish"}, {"bearish"}),
            ("ParabolicSAR", lambda: get_sar_signal, {"buy"}, {"sell"}),
            ("TSI", lambda: get_tsi_signal, {"bullish"}, {"bearish"}),
            ("WilliamsR", lambda: get_wr_signal, {"buy"}, {"sell"}),
            ("Donchian", lambda: get_donchian_channel_signal, {"buy"}, {"sell"}),
            ("PriceChannel", lambda: get_price_channel_signal, {"buy"}, {"sell"}),
            ("Keltner", lambda: get_keltner_channel_signal, {"buy"}, {"sell"}),
            ("Vortex", lambda: get_vortex_signal, {"buy"}, {"sell"}),
            ("CMO", lambda: get_cmo_signal, {"buy"}, {"sell"}),
            ("Coppock", lambda: get_coppock_curve_signal, {"buy"}, {"sell"}),
            ("UltimateOsc", lambda: get_ultimate_oscillator_signal, {"buy"}, {"sell"}),
            ("ElderRay", lambda: get_elder_ray_signal, {"buy"}, {"sell"}),
            ("Gator", lambda: get_gator_oscillator_signal, {"buy"}, {"sell"}),
            ("Fractal", lambda: get_fractal_signal, {"buy"}, {"sell"}),
        ]
        for name, resolve, buy_vals, sell_vals in candidates:
            try:
                func = resolve()
                if func is None:
                    continue
                indicators[name] = (func, buy_vals, sell_vals)
            except Exception:
                pass
        cls._SIGNAL_INDICATORS = indicators
        return indicators

    # ── Setup readiness & phase distance fit ──────────────────────────
    #
    # Signal strength guides manual trades (ML + vote + trend). Buttons are
    # never locked — strength % is shown in the Active Trades header and on
    # each row. Phase TP/SL fit is advisory only.

    SETUP_TICK_POINT = 0.25        # USTECH/NQ: 1 tick = 0.25 index points
    SETUP_MFE_ATR_MULT = 3.0       # est. favorable reach when no live stats yet
    SETUP_MAE_ATR_MULT = 1.2       # est. adverse noise when no live stats yet
    SETUP_MIN_VERIFIED = 10        # live MFE/MAE needs this many verified preds
    SETUP_STATE_TTL_SEC = 55       # readiness cache (refreshed by the 60s loop)

    def _estimate_move_capacity(self, mt5_symbol="ustech"):
        """How far the market can realistically travel right now.

        mfe_est — typical favorable excursion (how far price runs our way),
        mae_est — typical adverse excursion (how far it goes against us
        first). Taken from the prediction journal's verified MFE/MAE once
        enough live evidence exists, otherwise estimated from M5 ATR.
        """
        atr = None
        try:
            sym = mt5_symbol
            for cand in (mt5_symbol, mt5_symbol.upper(), mt5_symbol.lower()):
                if mt5.symbol_info(cand) is not None:
                    sym = cand
                    break
            rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 60)
            if rates is not None and len(rates) >= 20:
                if time.time() - int(rates[-1][0]) < 300:
                    rates = rates[:-1]  # closed bars only
                trs = []
                for i in range(1, len(rates)):
                    h, l = float(rates[i][2]), float(rates[i][3])
                    pc = float(rates[i - 1][4])
                    trs.append(max(h - l, abs(h - pc), abs(l - pc)))
                atr = sum(trs[-14:]) / min(14, len(trs))
        except Exception:
            atr = None
        mfe_est = mae_est = None
        source = "no data"
        if PREDICTION_TRACKER_AVAILABLE:
            try:
                s = prediction_tracker.get_stats("ustech")
                if s.get("n_verified", 0) >= self.SETUP_MIN_VERIFIED:
                    mfe_est = float(s["avg_mfe"])
                    mae_est = float(s["avg_mae"])
                    source = f"live-verified x{s['n_verified']}"
            except Exception:
                pass
        if mfe_est is None and atr is not None:
            mfe_est = atr * self.SETUP_MFE_ATR_MULT
            mae_est = atr * self.SETUP_MAE_ATR_MULT
            source = f"ATR estimate (ATR {atr:.1f}pts)"
        return {"atr": atr, "mfe_est": mfe_est, "mae_est": mae_est,
                "source": source}

    def _phase_setup_fit(self, config, capacity, tier=None, slack=None):
        """Does the CURRENT setup support this phase's TP/SL distances?

        TP must be within the market's typical favorable reach, and the SL
        must sit beyond the typical adverse noise (otherwise we'd be stopped
        out before the move). Farming legs (micro MNQ feeders) are exempt —
        their far TP is strategic, not setup-driven. Returns (ok, detail).
        """
        if slack is None and tier:
            prof = self._get_signal_gate_profile(tier)
            slack = float(prof.get("setup_fit_slack") or 1.0)
        slack = float(slack or 1.0)
        try:
            sym = (config.get("tradovate_symbol", "")
                   or config.get("topstepx_symbol", "")).upper()
            if "MNQ" in sym:
                return True, "farming leg — distance gate not applied"
            tp_ticks = int(config.get("tradovate_tp_ticks", 0)
                           or config.get("topstepx_tp_ticks", 0) or 0)
            sl_ticks = int(config.get("tradovate_sl_ticks", 0)
                           or config.get("topstepx_sl_ticks", 0) or 0)
        except Exception:
            return True, "no TP/SL in blueprint — gate not applied"
        if not tp_ticks or not sl_ticks:
            return True, "no TP/SL in blueprint — gate not applied"
        if not capacity or capacity.get("mfe_est") is None:
            return False, "no market-reach data yet (no ATR / verified stats)"
        tp_pts = tp_ticks * self.SETUP_TICK_POINT
        sl_pts = sl_ticks * self.SETUP_TICK_POINT
        tp_ok = tp_pts <= capacity["mfe_est"] * slack
        sl_ok = sl_pts >= capacity["mae_est"] / max(slack, 1.0)
        detail = (f"TP {tp_pts:.1f}pts vs reach {capacity['mfe_est']:.1f}pts "
                  f"{'OK' if tp_ok else 'TOO FAR'} | "
                  f"SL {sl_pts:.1f}pts vs noise {capacity['mae_est']:.1f}pts "
                  f"{'OK' if sl_ok else 'TOO TIGHT'} [{capacity['source']}]"
                  + (f" slack×{slack:.2f}" if slack != 1.0 else ""))
        return tp_ok and sl_ok, detail

    def _leg_raw_to_pct(self, buy_raw: float, sell_raw: float):
        total = buy_raw + sell_raw
        if total <= 0:
            return 50, 50
        return (
            int(min(100, round(buy_raw / total * 100))),
            int(min(100, round(sell_raw / total * 100))),
        )

    def _compute_trend_reversal_legs(self, trend, ml, vote, volatile):
        """Separate trend-following vs counter-trend (reversal) raw scores."""
        ml_conf = float(ml.get("confidence") or 0.5) if ml.get("ready") else 0.0
        ml_lean = (ml.get("lean") or "").lower()
        p = float(ml.get("probability") or 0.5)
        gate = float(ml.get("confidence_threshold") or 0.6)
        tf = ml.get("tick_features") or {}
        mom = float(tf.get("momentum_pts") or 0.0)

        t_buy = t_sell = r_buy = r_sell = 0.0
        vote_b = vote_s = cast = 0
        if vote:
            vote_b = int(vote.get("buy") or 0)
            vote_s = int(vote.get("sell") or 0)
            cast = vote_b + vote_s

        if trend == "buy":
            t_buy += 35.0
            if ml.get("ready") and ml_lean == "buy":
                t_buy += min(50.0, (ml_conf / max(gate, 0.01)) * 42.0)
            if cast:
                t_buy += vote_b / cast * 28.0
            if volatile and ml_lean == "buy":
                t_buy += 12.0 + min(6.0, float(tf.get("volatile_score") or 0) * 8.0)

            if ml.get("ready") and ml_lean == "sell":
                r_sell += min(55.0, (ml_conf / max(gate, 0.01)) * 48.0)
            elif ml.get("ready"):
                r_sell += (1.0 - p) * 32.0
            if cast:
                r_sell += vote_s / cast * 28.0
            if mom < -0.5:
                r_sell += min(20.0, abs(mom) * 0.65)
        elif trend == "sell":
            t_sell += 35.0
            if ml.get("ready") and ml_lean == "sell":
                t_sell += min(50.0, (ml_conf / max(gate, 0.01)) * 42.0)
            if cast:
                t_sell += vote_s / cast * 28.0
            if volatile and ml_lean == "sell":
                t_sell += 12.0 + min(6.0, float(tf.get("volatile_score") or 0) * 8.0)

            if ml.get("ready") and ml_lean == "buy":
                r_buy += min(55.0, (ml_conf / max(gate, 0.01)) * 48.0)
            elif ml.get("ready"):
                r_buy += p * 32.0
            if cast:
                r_buy += vote_b / cast * 28.0
            if mom > 0.5:
                r_buy += min(20.0, abs(mom) * 0.65)
        else:
            if ml.get("ready"):
                t_buy += p * 50.0
                t_sell += (1.0 - p) * 50.0
            if cast:
                t_buy += vote_b / cast * 30.0
                t_sell += vote_s / cast * 30.0

        t_buy_pct, t_sell_pct = self._leg_raw_to_pct(t_buy, t_sell)
        r_buy_pct, r_sell_pct = (
            self._leg_raw_to_pct(r_buy, r_sell) if trend else (50, 50)
        )
        return {
            "trend_buy_raw": t_buy, "trend_sell_raw": t_sell,
            "rev_buy_raw": r_buy, "rev_sell_raw": r_sell,
            "trend_buy_pct": t_buy_pct, "trend_sell_pct": t_sell_pct,
            "rev_buy_pct": r_buy_pct, "rev_sell_pct": r_sell_pct,
        }

    def _compute_trend_reversal_blend(self, symbol="ustech", max_age_sec=None):
        """Learning-weighted blend of trend leg + reversal leg → decision."""
        if max_age_sec is None:
            max_age_sec = self.SETUP_STATE_TTL_SEC
        cache_key = f"_blend_state_{symbol}"
        cached = getattr(self, cache_key, None)
        if cached and time.time() - cached["ts"] < max_age_sec:
            return cached

        capacity = self._estimate_move_capacity(symbol)
        trend = None
        try:
            trend = self._get_trend_direction(symbol)
        except Exception:
            trend = None

        ml: Dict[str, Any] = {}
        if ML_DIRECTION_AVAILABLE and ml_direction_engine is not None:
            try:
                ml = ml_direction_engine.get_ml_direction(
                    symbol, auto_train=False, trend_direction=trend) or {}
            except Exception:
                ml = {}

        vote = None
        try:
            vote = self._compute_indicator_votes(symbol)
        except Exception:
            vote = None

        volatile = bool(ml.get("volatile_regime"))
        legs = self._compute_trend_reversal_legs(trend, ml, vote, volatile)

        weights = {"w_trend": 0.65, "w_reversal": 0.35,
                   "trend_acc": 0.5, "reversal_acc": 0.5, "source": "default"}
        if prediction_tracker is not None:
            try:
                weights = prediction_tracker.get_regime_blend_weights(symbol)
            except Exception:
                pass

        w_t = float(weights.get("w_trend") or 0.65)
        w_r = float(weights.get("w_reversal") or 0.35)
        t_dom = ("buy" if legs["trend_buy_pct"] >= legs["trend_sell_pct"]
                 else "sell")
        r_dom = ("buy" if legs["rev_buy_pct"] >= legs["rev_sell_pct"]
                 else "sell")
        consensus = (not trend) or (t_dom == r_dom)

        if trend and not consensus:
            t_acc = float(weights.get("trend_acc") or 0.5)
            r_acc = float(weights.get("reversal_acc") or 0.5)
            if t_acc > r_acc:
                w_t *= 1.0 + 0.18 * (t_acc - r_acc)
            elif r_acc > t_acc:
                w_r *= 1.0 + 0.18 * (r_acc - t_acc)
            s = w_t + w_r
            w_t, w_r = w_t / s, w_r / s
        elif consensus and trend:
            w_t = min(0.82, w_t * 1.10)
            w_r = min(0.82, w_r * 1.10)
            s = w_t + w_r
            w_t, w_r = w_t / s, w_r / s

        if trend:
            buy_raw = w_t * legs["trend_buy_raw"] + w_r * legs["rev_buy_raw"]
            sell_raw = w_t * legs["trend_sell_raw"] + w_r * legs["rev_sell_raw"]
        else:
            buy_raw = legs["trend_buy_raw"]
            sell_raw = legs["trend_sell_raw"]
            w_t, w_r = 1.0, 0.0

        buy_pct, sell_pct = self._leg_raw_to_pct(buy_raw, sell_raw)
        margin = abs(buy_pct - sell_pct)
        lean = "buy" if buy_pct >= sell_pct else "sell"
        dominant = max(buy_pct, sell_pct)

        rows = getattr(self, "_active_trade_rows", None) or []
        tier = self._permissive_signal_tier_from_rows(rows)
        prof = self._get_signal_gate_profile(tier)
        min_dec = int(prof.get("min_decision_pct") or 60)
        div_margin = int(prof.get("min_diverge_margin") or self.BLEND_MIN_MARGIN_DIVERGE)
        div_dom = int(prof.get("min_diverge_dominant") or 55)

        decision = None
        if consensus and dominant >= min_dec:
            decision = lean
        elif margin >= div_margin and dominant >= div_dom:
            decision = lean

        parts = []
        if trend:
            parts.append(f"trend B{legs['trend_buy_pct']}/S{legs['trend_sell_pct']}")
            parts.append(f"rev B{legs['rev_buy_pct']}/S{legs['rev_sell_pct']}")
        else:
            parts.append("no trend")
        parts.append(
            f"learn wT={w_t:.0%}({weights.get('trend_acc', 0.5):.0%}) "
            f"wR={w_r:.0%}({weights.get('reversal_acc', 0.5):.0%}) "
            f"[{weights.get('source', '?')}]")
        if ml.get("ready"):
            parts.append(f"ML {str(ml.get('lean', '')).upper()} {float(ml.get('confidence') or 0):.0%}")
        if volatile:
            parts.append("VOLATILE")

        if trend:
            label = (f"blend B{buy_pct}/S{sell_pct} | "
                     f"trend B{legs['trend_buy_pct']}/S{legs['trend_sell_pct']} · "
                     f"rev B{legs['rev_buy_pct']}/S{legs['rev_sell_pct']}")
            if consensus:
                label += " ★consensus"
            else:
                label += " ⏳diverge"
        else:
            label = f"BUY {buy_pct}% · SELL {sell_pct}%"

        ml_dir = ml.get("direction") if ml.get("ready") else None
        vote_dir = (vote or {}).get("direction")
        ready = bool(
            decision
            and consensus
            and ml_dir in ("buy", "sell")
            and ml_dir == decision
            and (not trend or vote_dir == decision or vote_dir is None)
        )

        state = {
            "ts": time.time(),
            "buy_pct": buy_pct,
            "sell_pct": sell_pct,
            "lean": decision or lean,
            "decision": decision,
            "consensus": consensus,
            "blend_margin": margin,
            "ready": ready,
            "recommended": decision,
            "label": label,
            "detail": " · ".join(parts),
            "capacity": capacity,
            "ml": ml,
            "vote": vote,
            "trend": trend,
            "volatile_regime": volatile,
            "legs": legs,
            "weights": weights,
            "w_trend": w_t,
            "w_reversal": w_r,
            "signal_tier": tier,
        }
        if ready:
            state["label"] += " ★"
        setattr(self, cache_key, state)
        return state

    def _evaluate_setup_readiness(self, max_age_sec=None):
        """Highly recommended = learning blend consensus + ML confident."""
        if max_age_sec is None:
            max_age_sec = self.SETUP_STATE_TTL_SEC
        st = getattr(self, "_setup_state", None)
        if st and time.time() - st["ts"] < max_age_sec:
            return st
        state = {"ts": time.time(), "ready": False, "direction": None,
                 "capacity": None, "why": []}
        self._setup_state = state
        why = state["why"]
        try:
            if not (MT5_AVAILABLE and mt5.terminal_info()):
                why.append("MT5 not connected")
                return state
        except Exception:
            why.append("MT5 not connected")
            return state

        sig = self._compute_trend_reversal_blend("ustech", max_age_sec)
        state["capacity"] = sig.get("capacity")
        state["ts"] = sig["ts"]
        if not sig.get("ready"):
            if not sig.get("consensus"):
                why.append("trend and reversal diverge — blend waiting for consensus")
            elif not sig.get("decision"):
                why.append("blend has no clear direction yet")
            else:
                why.append(sig.get("detail") or "setup not ready")
            return state
        state["ready"] = True
        state["direction"] = sig["decision"]
        why.append(sig.get("detail") or "blend consensus")
        return state

    def _compute_signal_strength(self, max_age_sec=None):
        """Trend + reversal legs blended by learning weights → BUY/SELL %."""
        sig = self._compute_trend_reversal_blend("ustech", max_age_sec)
        self._signal_strength_state = sig
        self._setup_state = {
            "ts": sig["ts"],
            "ready": sig.get("ready"),
            "direction": sig.get("recommended"),
            "capacity": sig.get("capacity"),
            "why": [sig.get("detail", "")] + (
                ["highly recommended"] if sig.get("ready") else []),
        }
        return sig

    def _auto_trade_entry_allowed(self, phase_key=None, config=None,
                                  current_phase=None, elapsed_sec=0,
                                  firm_code=None):
        """Phase-aware auto gate: challenge fires on smaller moves; funded needs intent."""
        sig = self._compute_signal_strength(max_age_sec=0)
        buy_pct = int(sig.get("buy_pct") or 50)
        sell_pct = int(sig.get("sell_pct") or 50)
        lean = sig.get("decision") or sig.get("lean") or (
            "buy" if buy_pct >= sell_pct else "sell")
        dominant = max(buy_pct, sell_pct)
        ml = sig.get("ml") or {}
        volatile = bool(sig.get("volatile_regime") or ml.get("volatile_regime"))
        consensus = bool(sig.get("consensus"))
        margin = int(sig.get("blend_margin") or 0)
        legs = sig.get("legs") or {}

        tier = self._signal_tier_for_phase(
            phase_key, current_phase, config=config, firm_code=firm_code)
        prof = self._get_signal_gate_profile(tier, elapsed_sec=elapsed_sec)
        min_blend = int(prof.get("min_blend_pct") or self.AUTO_TRADE_MIN_SIGNAL_PCT)
        tier_tag = tier + ("*" if prof.get("relaxed") else "")

        if prof.get("require_consensus", self.AUTO_TRADE_REQUIRE_CONSENSUS) and not consensus:
            return False, lean, dominant, volatile, (
                f"[{tier_tag}] trend/reversal diverge — need consensus "
                f"(trend B{legs.get('trend_buy_pct', '?')}/S{legs.get('trend_sell_pct', '?')} "
                f"vs rev B{legs.get('rev_buy_pct', '?')}/S{legs.get('rev_sell_pct', '?')}, "
                f"margin {margin}%)")

        if dominant < min_blend:
            return False, lean, dominant, volatile, (
                f"[{tier_tag}] blend {dominant}% below {min_blend}% "
                f"(B{buy_pct}/S{sell_pct})")

        if not sig.get("decision"):
            return False, lean, dominant, volatile, (
                f"[{tier_tag}] no blend decision yet (B{buy_pct}/S{sell_pct})")

        vol_bypass = int(prof.get("volatile_bypass_blend") or 0)
        need_vol = bool(prof.get("require_volatile", self.AUTO_TRADE_REQUIRE_VOLATILE))
        if need_vol and not volatile and not (vol_bypass and dominant >= vol_bypass):
            return False, lean, dominant, volatile, (
                f"[{tier_tag}] waiting for ⚡VOL or ≥{vol_bypass}% blend "
                f"(B{buy_pct}/S{sell_pct})")

        ml_dir = (ml.get("direction") or ml.get("lean") or "").lower()
        if prof.get("require_ml_agree") and ml.get("ready"):
            if ml_dir not in ("buy", "sell") or ml_dir != lean:
                return False, lean, dominant, volatile, (
                    f"[{tier_tag}] ML {ml_dir or 'neutral'} ≠ blend {lean.upper()} "
                    f"(B{buy_pct}/S{sell_pct})")

        if prof.get("require_ready", self.AUTO_TRADE_REQUIRE_READY) and not sig.get("ready"):
            return False, lean, dominant, volatile, (
                f"[{tier_tag}] waiting for ★ highly recommended "
                f"(blend {lean.upper()} B{buy_pct}/S{sell_pct}, ML {ml_dir or 'neutral'})")

        if prof.get("require_setup_fit") and config:
            cap = sig.get("capacity")
            fit_ok, fit_detail = self._phase_setup_fit(
                config, cap, tier=tier)
            if not fit_ok:
                return False, lean, dominant, volatile, (
                    f"[{tier_tag}] TP/SL reach — {fit_detail}")

        w = sig.get("weights") or {}
        vol_note = "⚡VOL" if volatile else "calm tape OK" if tier == "challenge" else "no-VOL bypass"
        return True, lean, dominant, volatile, (
            f"[{tier_tag}] entry OK — {lean.upper()} {dominant}% consensus "
            f"wT={float(sig.get('w_trend') or 0):.0%} wR={float(sig.get('w_reversal') or 0):.0%} "
            f"+ {vol_note} | trend acc {w.get('trend_acc', '?')} rev {w.get('reversal_acc', '?')}")

    def _auto_batch_gate_allowed(self, elapsed_sec=0):
        """True when at least one loaded row passes its phase-specific gate."""
        rows = list(getattr(self, "_active_trade_rows", []) or [])
        locks = self._sync_auto_trade_firm_sides()
        if not rows:
            return self._auto_trade_entry_allowed(elapsed_sec=elapsed_sec)

        best = None
        direction_blocked = None
        for rd in rows:
            pk = rd.get("phase_key")
            cp = rd.get("current_phase", "")
            firm = (rd.get("eval") or {}).get("Prop Firm", rd.get("firm_code", ""))
            config = None
            if self.prop_firm_mgr:
                try:
                    config = self.prop_firm_mgr.get_strategy_config(
                        rd["firm_code"], pk, rd["acct_size"])
                except Exception:
                    config = None
            result = self._auto_trade_entry_allowed(
                phase_key=pk, config=config, current_phase=cp,
                elapsed_sec=elapsed_sec, firm_code=rd.get("firm_code"))
            if not result[0]:
                if best is None or result[2] > best[2]:
                    best = result
                continue
            lean = result[1]
            req = locks.get(firm)
            if req and lean and req != lean:
                direction_blocked = (
                    f"{firm} locked {req.upper()} — signal is {lean.upper()} "
                    f"({result[2]}%)")
                if best is None or result[2] > best[2]:
                    best = (False, lean, result[2], result[3],
                            direction_blocked)
                continue
            return result
        if direction_blocked and best and not best[0]:
            return best
        return best if best is not None else self._auto_trade_entry_allowed(
            elapsed_sec=elapsed_sec)

    def _update_signal_strength_ui(self):
        """Update strength labels and button highlights — never disable buttons."""
        sig = getattr(self, "_signal_strength_state", None) or {}
        buy_pct = sig.get("buy_pct", 50)
        sell_pct = sig.get("sell_pct", 50)
        lean = sig.get("lean")
        ready = sig.get("ready")

        try:
            hdr = f"Signal: {sig.get('label', '—')}"
            if sig.get("volatile_regime"):
                hdr += " ⚡VOL"
            if sig.get("detail"):
                hdr += f"  ({sig['detail'][:60]})"
            if hasattr(self, "_signal_strength_var"):
                self._signal_strength_var.set(hdr[:140])
        except Exception:
            pass

        try:
            if getattr(self, "_ai_status_vars", None):
                short = sig.get("label", "—")
                if sig.get("detail"):
                    short += f" — {sig['detail'][:80]}"
                self._ai_status_vars["setup"].set(short[:120])
        except Exception:
            pass

        rows = getattr(self, "_active_trade_rows", None) or []
        capacity = sig.get("capacity")
        for rd in rows:
            try:
                buy_btn, sell_btn = rd.get("buy_btn"), rd.get("sell_btn")
                if not buy_btn or not sell_btn:
                    continue
                if str(buy_btn.cget("text")) == "N/A":
                    continue

                # Always enabled — user chooses direction
                if CTK_AVAILABLE:
                    buy_btn.configure(state="normal", text="▲ BUY")
                    sell_btn.configure(state="normal", text="▼ SELL")
                else:
                    buy_btn.configure(state="normal", text="▲ BUY")
                    sell_btn.configure(state="normal", text="▼ SELL")

                # Highlight stronger side
                if lean == "buy" or (ready and sig.get("recommended") == "buy"):
                    if CTK_AVAILABLE:
                        buy_btn.configure(fg_color="#052E16", border_color="#16A34A",
                                          text_color="#4ADE80")
                        sell_btn.configure(fg_color="#0A0F1A", border_color="#1A1A2E",
                                           text_color="#2A3040")
                    else:
                        buy_btn.configure(bg="#052E16", fg="#4ADE80")
                        sell_btn.configure(bg="#0A0F1A", fg="#2A3040")
                elif lean == "sell" or (ready and sig.get("recommended") == "sell"):
                    if CTK_AVAILABLE:
                        sell_btn.configure(fg_color="#2D0A0A", border_color="#DC2626",
                                           text_color="#F87171")
                        buy_btn.configure(fg_color="#0A0F1A", border_color="#1A1A2E",
                                          text_color="#2A3040")
                    else:
                        sell_btn.configure(bg="#2D0A0A", fg="#F87171")
                        buy_btn.configure(bg="#0A0F1A", fg="#2A3040")

                lbl = rd.get("strength_lbl")
                if lbl:
                    legs = sig.get("legs") or {}
                    if legs and sig.get("trend"):
                        row_txt = (f"T{legs.get('trend_buy_pct', '?')}/{legs.get('trend_sell_pct', '?')} "
                                   f"R{legs.get('rev_buy_pct', '?')}/{legs.get('rev_sell_pct', '?')} "
                                   f"→ B{buy_pct} S{sell_pct}")
                    else:
                        row_txt = f"B{buy_pct} S{sell_pct}"
                    fit_tag = ""
                    if self.prop_firm_mgr:
                        cfg = self.prop_firm_mgr.get_strategy_config(
                            rd["firm_code"], rd["phase_key"], rd["acct_size"])
                        if cfg and capacity:
                            tier = self._signal_tier_for_phase(
                                rd["phase_key"], rd.get("current_phase"),
                                config=cfg, firm_code=rd.get("firm_code"))
                            ok, _ = self._phase_setup_fit(cfg, capacity, tier=tier)
                            fit_tag = " ✓" if ok else " ⚠"
                    row_txt += fit_tag
                    if ready:
                        row_txt = f"★ {row_txt}"
                    color = "#4ADE80" if lean == "buy" else "#F87171" if lean == "sell" else "#94A3B8"
                    if CTK_AVAILABLE:
                        lbl.configure(text=row_txt, text_color=color)
                    else:
                        lbl.configure(text=row_txt, fg=color)
            except Exception:
                continue

    def _update_trade_button_locks(self):
        """Legacy name — strength display only, no locks."""
        self._update_signal_strength_ui()

    def _refresh_setup_locks_bg(self):
        """Background: compute signal strength, refresh UI labels."""
        if not self._ml_mode_enabled():
            return
        try:
            sig = self._compute_signal_strength(max_age_sec=0)
            key = (sig.get("buy_pct"), sig.get("sell_pct"), sig.get("ready"),
                   sig.get("ml", {}).get("probability"))
            if key != getattr(self, "_setup_last_announced", None):
                self._setup_last_announced = key
                star = " ★ highly recommended" if sig.get("ready") else ""
                vol = ""
                ml = sig.get("ml") or {}
                if ml.get("volatile_regime"):
                    vol = " | VOLATILE entry window"
                msg = (f"signal strength — {sig.get('label')}{star} "
                       f"({sig.get('detail')}){vol}")
                self._ai_trace("SIGNAL", msg)
        except Exception:
            pass
        try:
            self.root.after(0, self._update_signal_strength_ui)
        except Exception:
            pass

    def _publish_ml_score_60s(self):
        """Re-score ML/DL ensemble from live ticks (called every 60s)."""
        if not self._ml_mode_enabled():
            return
        if not ML_DIRECTION_AVAILABLE or ml_direction_engine is None:
            return
        try:
            trend = self._get_trend_direction("ustech")
            ml = ml_direction_engine.get_ml_direction(
                "ustech", auto_train=False, trend_direction=trend)
            if not ml.get("ready"):
                self._ai_trace("ML", f"60s score: not ready ({ml.get('reason')})")
                return
            tf = ml.get("tick_features") or {}
            w = ml.get("ensemble_weights") or {}
            vol_tag = "VOLATILE ★ entry window" if ml.get("volatile_regime") else "calm"
            trend_tag = ""
            if trend in ("buy", "sell"):
                tag = "aligned" if ml.get("aligned_with_trend") else (
                    "reversal" if ml.get("counter_trend") else "")
                trend_tag = f"trend={trend.upper()}" + (f" ML-{tag}" if tag else "")
            blend = self._compute_trend_reversal_blend("ustech", max_age_sec=0)
            legs = blend.get("legs") or {}
            blend_note = ""
            if legs and trend:
                blend_note = (f" | legs trend B{legs.get('trend_buy_pct')}/"
                              f"S{legs.get('trend_sell_pct')} rev "
                              f"B{legs.get('rev_buy_pct')}/S{legs.get('rev_sell_pct')} "
                              f"→ blend B{blend.get('buy_pct')}/S{blend.get('sell_pct')}")
            self._ai_trace(
                "ML",
                f"60s tick-score: GBM={ml.get('gbm_probability')} "
                f"DL={ml.get('dl_probability')} ET={ml.get('et_probability')} "
                f"→ ens={ml.get('probability')} conf={ml.get('confidence')} "
                f"(gate {ml.get('confidence_threshold')}) | {vol_tag} | "
                f"ticks={tf.get('tick_count', 0)} "
                f"mom={float(tf.get('momentum_pts') or 0):+.1f}pts "
                f"vol={float(tf.get('volatile_score') or 0):.2f} "
                f"weights DL={float(w.get('dl', 0)):.0%}"
                + (f" | {trend_tag}" if trend_tag else "")
                + blend_note)
        except Exception as e:
            self._ai_trace("WARN", f"60s ML score failed: {e}")

    def _refresh_setup_locks_async(self):
        threading.Thread(target=self._refresh_setup_locks_bg,
                         name="setup-locks", daemon=True).start()

    # ── Indicator vote — co-decider alongside the ML/DL ensemble ──────

    def _get_trend_direction(self, mt5_symbol, timeframe=None):
        """Prevailing trend from CLOSED bars — we time the trend, never reversals.

        Uses EMA21/50 on M5 (+ M15 confirm), M1 for the live leg, and a
        10-bar M5 slope so a clear downtrend is not hidden when M15 lags.
        Returns "buy", "sell", or None (only when genuinely flat / no data).
        """
        if not MT5_AVAILABLE:
            return None

        sym = mt5_symbol
        for cand in (mt5_symbol, mt5_symbol.upper(), mt5_symbol.lower()):
            try:
                if mt5.symbol_info(cand) is not None:
                    sym = cand
                    break
            except Exception:
                pass

        def _ema_last(values, period):
            k = 2.0 / (period + 1.0)
            ema = values[0]
            for v in values[1:]:
                ema = v * k + ema * (1.0 - k)
            return ema

        def _closed_closes(tf, tf_sec, count=80):
            try:
                rates = mt5.copy_rates_from_pos(sym, tf, 0, count)
                if rates is None or len(rates) < 12:
                    return None
                if time.time() - int(rates[-1][0]) < tf_sec:
                    rates = rates[:-1]
                if len(rates) < 12:
                    return None
                return [float(r[4]) for r in rates]
            except Exception:
                return None

        def _tf_trend(closes):
            if not closes or len(closes) < 55:
                return None
            ema21 = _ema_last(closes, 21)
            ema50 = _ema_last(closes, 50)
            close = closes[-1]
            if ema21 > ema50 and close > ema50:
                return "buy"
            if ema21 < ema50 and close < ema50:
                return "sell"
            return None

        def _slope_trend(closes, lookback=10, min_pts=12.0):
            """Direction of the recent move in points (USTECH-scale)."""
            if not closes or len(closes) <= lookback:
                return None
            delta = closes[-1] - closes[-1 - lookback]
            if delta >= min_pts:
                return "buy"
            if delta <= -min_pts:
                return "sell"
            return None

        c5 = _closed_closes(mt5.TIMEFRAME_M5, 300)
        c15 = _closed_closes(mt5.TIMEFRAME_M15, 900)
        c1 = _closed_closes(mt5.TIMEFRAME_M1, 60, count=40)

        t5 = _tf_trend(c5)
        t15 = _tf_trend(c15)
        t1 = _tf_trend(c1)
        slope5 = _slope_trend(c5, lookback=10, min_pts=12.0)
        slope1 = _slope_trend(c1, lookback=15, min_pts=6.0) if c1 else None

        if t5 and t15 and t5 == t15:
            return t5
        if t5 and t1 and t5 == t1:
            return t5
        if slope5 and slope1 and slope5 == slope1:
            return slope5
        if t5:
            return t5
        if slope5:
            return slope5
        if t1 and slope1 and t1 == slope1:
            return t1
        if t15 and not t5:
            return t15
        return None

    def _momentum_tiebreak(self, mt5_symbol, timeframe):
        """Deterministic data-driven tie-break: direction of the last 8-bar move.

        Returns "buy"/"sell" from real price data, or None if no data (or the
        move is exactly flat). NEVER random.
        """
        try:
            rates = mt5.copy_rates_from_pos(mt5_symbol, timeframe, 0, 9)
            if rates is not None and len(rates) >= 2:
                first = float(rates[0][4])
                last = float(rates[-1][4])
                if last > first:
                    return "buy"
                if last < first:
                    return "sell"
        except Exception:
            pass
        return None

    def _compute_indicator_votes(self, mt5_symbol, timeframe=None, num_indicators=None):
        """Poll ALL available indicators and return the raw vote tally.

        Deterministic — every indicator is polled in a stable order, no random
        subset. Returns a dict:
            {"direction": "buy"/"sell"/None (None = tie or no votes),
             "buy": int, "sell": int, "strength": 0..1 (margin / votes cast),
             "detail": str, "symbol": resolved MT5 symbol, "timeframe": tf}
        or None when indicators cannot run at all (no MT5 / no indicators).
        """
        if not MT5_AVAILABLE:
            self._ai_trace("WARN", f"{mt5_symbol}: MetaTrader5 unavailable — no indicator vote")
            return None
        mt5_mod = mt5
        if timeframe is None:
            timeframe = mt5_mod.TIMEFRAME_M5

        # Ensure MT5 is connected (non-hedging clients may not have it open)
        if not mt5_mod.terminal_info():
            self._ensure_mt5_for_signals()
            if not mt5_mod.terminal_info():
                self._ai_trace("WARN", f"{mt5_symbol}: MT5 not connected — no indicator vote")
                return None

        # MT5 symbol names are case-sensitive: 'ustech' fetches NOTHING while
        # 'USTECH' works — resolve to the broker's exact name before polling.
        try:
            for _cand in (str(mt5_symbol), str(mt5_symbol).upper(),
                          str(mt5_symbol).lower(), str(mt5_symbol).capitalize()):
                if mt5_mod.symbol_info(_cand) is not None:
                    if _cand != mt5_symbol:
                        self._ai_trace("DIAG", f"symbol '{mt5_symbol}' resolved to "
                                               f"MT5 name '{_cand}'")
                    mt5_symbol = _cand
                    break
        except Exception:
            pass

        try:
            from trader_companion.mt5_market_feed import get_market_feed, start_mt5_market_feed
            feed = get_market_feed()
            feed.ensure_symbol(mt5_symbol)
            if not feed.is_running:
                start_mt5_market_feed([mt5_symbol])
        except Exception:
            pass

        indicators = self._get_indicator_map()
        if not indicators:
            self._ai_trace("WARN", f"{mt5_symbol}: no indicators available — no indicator vote")
            return None

        # Poll EVERY indicator in a stable order — intentional, reproducible.
        chosen = sorted(indicators.keys())
        if num_indicators:
            chosen = chosen[:num_indicators]

        # Optimized settings from the startup backtest (empty → defaults)
        opt_params = {}
        if INDICATOR_OPT_AVAILABLE and indicator_optimizer is not None:
            try:
                opt_params = indicator_optimizer.get_best_params(mt5_symbol) or {}
            except Exception:
                opt_params = {}

        buy_votes = 0
        sell_votes = 0
        details = []

        for name in chosen:
            func, buy_vals, sell_vals = indicators[name]
            try:
                kwargs = opt_params.get(name) or {}
                try:
                    result = func(mt5_symbol, timeframe, **kwargs)
                except TypeError:
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
            except Exception:
                details.append(f"{name}=err")

        cast = buy_votes + sell_votes
        if buy_votes > sell_votes:
            direction = "buy"
        elif sell_votes > buy_votes:
            direction = "sell"
        else:
            direction = None  # tie — caller breaks it with data
        return {
            "direction": direction,
            "buy": buy_votes,
            "sell": sell_votes,
            "strength": (abs(buy_votes - sell_votes) / cast) if cast else 0.0,
            "detail": f"{buy_votes}B/{sell_votes}S [" + ", ".join(details) + "]",
            "symbol": mt5_symbol,
            "timeframe": timeframe,
        }

    # ── AI Decision Monitor — real-time window into the AI's reasoning ──

    AI_TRACE_COLORS = {
        "SIGNAL":    "#00D4FF",  # final direction decisions
        "ML":        "#4ADE80",  # local ML/DL ensemble layer
        "INSIGHT":   "#fbbf24",  # dashboard trade-history ML (advisory)
        "VOTE":      "#a78bfa",  # indicator vote fallback
        "BLUEPRINT": "#60a5fa",  # phase/blueprint resolution (TP/SL source)
        "TRADE":     "#34d399",  # orders fired
        "WARN":      "#f87171",  # anomalies / guards
        "DIAG":      "#2dd4bf",  # on-demand diagnostics (raw indicator values)
        "OPT":       "#f472b6",  # indicator-parameter optimizer
        "LEARN":     "#fb923c",  # self-learning: verified predictions vs market
        "SIM":       "#C084FC",  # tomorrow paper-trade simulation
    }
    # AI Decision Monitor typography / layout (single place to tune readability)
    AI_MONITOR_FONT = "Segoe UI"
    AI_MONITOR_LOG_FONT = "Consolas"
    AI_MONITOR_TITLE_SIZE = 16
    AI_MONITOR_CAPTION_SIZE = 10
    AI_MONITOR_CARD_SIZE = 11
    AI_MONITOR_LOG_SIZE = 11
    AI_MONITOR_BADGE_SIZE = 10
    AI_MONITOR_BTN_SIZE = 10
    AI_MONITOR_DEFAULT_GEOMETRY = "1280x780"
    AI_MONITOR_CARD_WRAP = 360

    def _run_ai_diagnostics(self):
        """Probe every AI input LIVE and trace raw values to the monitor.

        Answers "what is the AI actually seeing right now?": MT5 connection,
        symbol resolution, bar freshness, every indicator's raw computed
        value, ML model state + prediction, and dashboard insight health.
        Runs in a background thread; results stream into the monitor as DIAG.
        Auto-runs every 60s while the monitor is open (manual runs anytime).
        """
        if getattr(self, "_ai_diag_running", False):
            return  # previous run still in flight — never overlap
        self._ai_diag_running = True

        def _worker():
            def t(msg):
                self._ai_trace("DIAG", msg)

            try:
                # Fresh ML/tick score every 60s — never reuse stale cache
                self._signal_strength_state = None
                self._setup_state = None
                self._run_ai_diagnostics_body(t)
                self._publish_ml_score_60s()
                self._verify_ml_predictions()
                self._refresh_setup_locks_bg()
                self._run_tomorrow_simulation()
            finally:
                self._ai_diag_running = False

        threading.Thread(target=_worker, name="ai-diagnostics", daemon=True).start()

    def _schedule_ai_diagnostics(self):
        """App-level loop: auto-run diagnostics every 60s.

        Runs regardless of whether the AI monitor window is open — events
        are recorded to the trace buffer and replayed when the monitor is
        opened. Quietly skips a cycle while MT5 is disconnected (nothing to
        probe) instead of spamming 'not connected' every minute.
        """
        try:
            if MT5_AVAILABLE and mt5.terminal_info():
                self._run_ai_diagnostics()
        except Exception:
            pass
        try:
            self.root.after(60_000, self._schedule_ai_diagnostics)
        except Exception:
            pass  # app shutting down

    def _start_ai_diagnostics_loop(self):
        """Start the 60s diagnostics loop exactly once."""
        if getattr(self, "_ai_diag_loop_started", False):
            return
        self._ai_diag_loop_started = True
        self.root.after(5_000, self._schedule_ai_diagnostics)

    def _verify_ml_predictions(self):
        """Self-learning pass (piggybacks on the 60s diagnostics loop).

        Checks every journaled ML prediction whose horizon has elapsed
        against the actual market: distance moved, whether the market
        followed the prediction, and a TP/SL first-touch simulation as if
        a trade had been active. Verified outcomes drive the adaptive
        confidence gate inside the ML engine.
        """
        if not PREDICTION_TRACKER_AVAILABLE:
            return
        try:
            n = prediction_tracker.verify_pending(
                "ustech", log_fn=lambda m: self._ai_trace("LEARN", m))
            if n:
                s = prediction_tracker.get_stats("ustech")
                if s.get("n_verified"):
                    eff = prediction_tracker.effective_confidence_threshold(
                        ml_direction_engine.CONFIDENCE_THRESHOLD
                        if ML_DIRECTION_AVAILABLE else 0.60, "ustech")
                    self._ai_trace(
                        "LEARN",
                        f"scorecard (last {s['n_verified']}): "
                        f"accuracy {s['accuracy']:.0%} | trade sim: "
                        f"{s['tp_hits']} TP / {s['sl_hits']} SL / "
                        f"{s['no_hit']} no-hit | avg move with lean "
                        f"{s['avg_signed_move']:+.1f}pts | MFE +{s['avg_mfe']:.1f} "
                        f"MAE -{s['avg_mae']:.1f} | adaptive gate {eff:.2f}")
        except Exception as e:
            self._ai_trace("WARN", f"prediction verification failed: {e}")

    def _run_ai_diagnostics_body(self, t):
            def _fmt(v):
                if isinstance(v, float):
                    return f"{v:.2f}"
                if isinstance(v, (tuple, list)):
                    return "(" + ", ".join(_fmt(x) for x in v) + ")"
                try:
                    import numpy as _np
                    if isinstance(v, _np.floating):
                        return f"{float(v):.2f}"
                except Exception:
                    pass
                return str(v)

            t("──── diagnostics started ────")

            # 1. MT5 connection
            if not MT5_AVAILABLE:
                t("MT5: module not installed — indicators and ML CANNOT run")
                return
            try:
                ti = mt5.terminal_info()
                if not ti:
                    t("MT5: NOT CONNECTED — connect MT5 first, then re-run")
                    return
                ai = mt5.account_info()
                t(f"MT5: connected={ti.connected} login={getattr(ai, 'login', '?')} "
                  f"server={getattr(ai, 'server', '?')}")
            except Exception as e:
                t(f"MT5: error — {e}")
                return

            # 2. Symbol resolution (case matters: 'ustech' fetches nothing)
            raw_sym = "ustech"
            resolved = None
            for cand in (raw_sym.upper(), raw_sym, raw_sym.capitalize()):
                try:
                    if mt5.symbol_info(cand) is not None:
                        resolved = cand
                        break
                except Exception:
                    pass
            if not resolved:
                t(f"symbol: could NOT resolve '{raw_sym}' on this broker — no data possible")
                return
            t(f"symbol: '{raw_sym}' → MT5 '{resolved}'")

            # 3. Bar freshness
            tf = mt5.TIMEFRAME_M5
            try:
                rates = mt5.copy_rates_from_pos(resolved, tf, 0, 2)
            except Exception as e:
                rates = None
                t(f"bars: fetch error — {e}")
            if rates is None or len(rates) == 0:
                t("bars: NO M5 data returned — indicators will all be neutral")
                return
            last = rates[-1]
            age = int(time.time() - int(last[0]))
            t(f"bars: last M5 close={float(last[4]):.2f}, bar opened {age}s ago")

            # 4. Every indicator's raw computed value (with optimized params)
            opt_params = {}
            if INDICATOR_OPT_AVAILABLE and indicator_optimizer is not None:
                try:
                    opt_params = indicator_optimizer.get_best_params(raw_sym) or {}
                    opt_at = indicator_optimizer.last_optimized_at(raw_sym)
                    if opt_at:
                        mins = int((time.time() - opt_at) / 60)
                        t(f"optimizer: settings backtested {mins}min ago — "
                          f"{len(opt_params)} indicator(s) tuned away from defaults"
                          + (f": {', '.join(sorted(opt_params))}" if opt_params else ""))
                    elif indicator_optimizer.is_optimizing(raw_sym):
                        t("optimizer: backtest running — defaults in use until it finishes")
                    else:
                        t("optimizer: no results yet — defaults in use")
                except Exception as e:
                    t(f"optimizer: error — {e}")
            indicators = self._get_indicator_map()
            if not indicators:
                t("indicators: NONE available (import failure?)")
            else:
                buy_n, sell_n, neutral_n, err_n = [], [], [], []
                for name in sorted(indicators.keys()):
                    func = indicators[name][0]
                    kw = opt_params.get(name) or {}
                    try:
                        out = func(resolved, tf, return_value=True, **kw)
                    except TypeError:
                        try:
                            out = func(resolved, tf)
                        except Exception as e:
                            err_n.append(f"{name}({e})")
                            continue
                    except Exception as e:
                        err_n.append(f"{name}({e})")
                        continue
                    sig = out[0] if isinstance(out, tuple) else out
                    sig_s = str(sig).lower() if sig is not None else "none"
                    if sig_s in ("buy", "long", "1", "1.0"):
                        buy_n.append(name)
                    elif sig_s in ("sell", "short", "-1", "-1.0"):
                        sell_n.append(name)
                    else:
                        neutral_n.append(name)
                t(f"indicators ({len(indicators)} polled): "
                  f"{len(buy_n)} BUY, {len(sell_n)} SELL, {len(neutral_n)} neutral"
                  + (f", {len(err_n)} error(s)" if err_n else ""))
                if buy_n:
                    t(f"  BUY side: {', '.join(buy_n)}")
                if sell_n:
                    t(f"  SELL side: {', '.join(sell_n)}")
                if err_n:
                    t(f"  errors: {'; '.join(err_n[:5])}")

            # 5. ML/DL ensemble state
            if ML_DIRECTION_AVAILABLE and ml_direction_engine is not None:
                try:
                    b = ml_direction_engine.get_cached_bundle(raw_sym, 5)
                    if b:
                        wf = b.get("walk_forward") or {}
                        mins = int((time.time() - b["trained_at"]) / 60)
                        t(f"ML model: trained {mins}min ago, n={b.get('n_labeled')}, "
                          f"wf_acc={wf.get('accuracy')} gated={wf.get('gated_accuracy')}")
                    else:
                        t("ML model: not trained yet — training starts once all "
                          "brokers are connected & ready to trade")
                    pred = ml_direction_engine.get_ml_direction(raw_sym, 5, auto_train=False)
                    if pred.get("ready"):
                        tf = pred.get("tick_features") or {}
                        vol = " VOLATILE★" if pred.get("volatile_regime") else ""
                        t(f"ML prediction: {str(pred.get('direction')).upper()} "
                          f"p_up={pred.get('probability')} conf={pred.get('confidence')} "
                          f"(gate {pred.get('confidence_threshold')}){vol} | "
                          f"ticks={tf.get('tick_count', 0)} "
                          f"mom={float(tf.get('momentum_pts') or 0):+.1f}pts")
                    else:
                        t(f"ML prediction: not ready ({pred.get('reason')})")
                except Exception as e:
                    t(f"ML: error — {e}")
            else:
                t("ML: scikit-learn unavailable — ensemble disabled, indicator vote only")

            # 6. Dashboard insights health
            ins = self._get_dashboard_ml_insights()
            if ins:
                mkt = ins.get("market") or {}
                port = ins.get("portfolio") or {}
                t(f"dashboard: reachable — bias={mkt.get('bias')} "
                  f"conf={mkt.get('confidence')} n_trades={port.get('n_trades')}")
            else:
                t("dashboard: insights UNAVAILABLE (check URL / email / network) — "
                  "advisory layer inactive")

            # 7. Signal strength (advisory — buttons never locked)
            try:
                cap = self._estimate_move_capacity(resolved or raw_sym)
                t(f"market reach: MFE~{cap.get('mfe_est')} MAE~{cap.get('mae_est')} "
                  f"[{cap.get('source')}]")
                sig = self._compute_signal_strength(max_age_sec=0)
                star = " ★ highly recommended" if sig.get("ready") else ""
                t(f"signal: {sig.get('label')}{star} — {sig.get('detail')}")
                rows = getattr(self, "_active_trade_rows", None) or []
                if rows and self.prop_firm_mgr:
                    for rd in rows[:8]:
                        cfg = self.prop_firm_mgr.get_strategy_config(
                            rd["firm_code"], rd["phase_key"], rd["acct_size"])
                        if not cfg:
                            continue
                        ok, det = self._phase_setup_fit(cfg, cap)
                        t(f"  {rd.get('acct_num','?')} {rd.get('phase_key','?')}: "
                          f"{'phase OK' if ok else 'phase ⚠'} — {det}")
                    if len(rows) > 8:
                        t(f"  … +{len(rows) - 8} more rows")
            except Exception as e:
                t(f"signal strength: error — {e}")

            # 8. Tomorrow paper-trade simulation
            try:
                from datetime import timedelta
                twd = (kenya_today() + timedelta(days=1)).weekday()
                wd_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
                plans = self._collect_tomorrow_trade_plans()
                t(f"tomorrow ({wd_names[twd]}): {len(plans)} queued plan(s) from day placeholders")
                if TRADE_SIMULATOR_AVAILABLE:
                    brief = trade_simulator.get_last_brief()
                    for p in (brief.get("plans") or [])[:6]:
                        t(f"  sim {p.get('acct_num','?')} {p.get('phase_key','?')} "
                          f"TP={p.get('tp_ticks')}t SL={p.get('sl_ticks')}t "
                          f"score={p.get('score')} tp={p.get('tp_rate',0):.0%} "
                          f"sl={p.get('sl_rate',0):.0%} ~{p.get('avg_tp_min')}min "
                          f"window={p.get('best_slot')}")
                    top = brief.get("top")
                    if top:
                        t(f"tomorrow best: {top.get('acct_num')} {top.get('phase_key')} "
                          f"enter {top.get('best_slot')} "
                          f"{str(top.get('best_direction','')).upper()}")
            except Exception as e:
                t(f"tomorrow sim: error — {e}")

            t("──── diagnostics complete ────")

    def _ml_log(self, message: str) -> None:
        """Route ML training progress to both the app log and the AI monitor."""
        self._ai_trace("ML", message.replace("🧠 ", ""))
        try:
            self.root.after(0, lambda m=message: self.log(m))
        except Exception:
            pass

    def _opt_log(self, message: str) -> None:
        """Route indicator-optimizer progress to the app log and AI monitor."""
        self._ai_trace("OPT", message.replace("⚙ ", ""))
        try:
            self.root.after(0, lambda m=message: self.log(m))
        except Exception:
            pass

    def _ai_monitor_category_visible(self, category: str) -> bool:
        """Respect per-category filter toggles in the monitor window."""
        filters = getattr(self, "_ai_monitor_filter_vars", None)
        if not filters:
            return True
        var = filters.get(category)
        return var.get() if var is not None else True

    def _ai_monitor_rerender(self):
        """Rebuild the log from the event buffer (after filter toggle)."""
        txt = self._ai_monitor_text
        win = self._ai_monitor_win
        if not txt or not win:
            return
        try:
            if not win.winfo_exists():
                return
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            for ts, cat, msg in list(self._ai_events):
                if self._ai_monitor_category_visible(cat):
                    self._ai_monitor_insert(txt, ts, cat, msg)
            txt.configure(state="disabled")
            if getattr(self, "_ai_autoscroll_var", None) is None or \
                    self._ai_autoscroll_var.get():
                txt.see("end")
        except Exception:
            pass

    def _ai_trace(self, category: str, message: str) -> None:
        """Record one AI decision event and stream it to the monitor window.

        Safe to call from any thread; widget updates hop to the UI thread.
        """
        ts = datetime.now().strftime("%H:%M:%S")
        self._ai_events.append((ts, category, message))

        def _append():
            self._ai_monitor_update_status(category, message)
            if not self._ai_monitor_category_visible(category):
                # Still counted in the buffer — user can toggle the filter on
                if getattr(self, "_ai_status_vars", None):
                    try:
                        self._ai_status_vars["events"].set(
                            f"{len(self._ai_events)} events")
                    except Exception:
                        pass
                return
            txt = self._ai_monitor_text
            win = self._ai_monitor_win
            if not txt or not win:
                return
            try:
                if not win.winfo_exists():
                    return
                self._ai_monitor_insert(txt, ts, category, message)
                if getattr(self, "_ai_autoscroll_var", None) is None or \
                        self._ai_autoscroll_var.get():
                    txt.see("end")
            except Exception:
                pass

        try:
            self.root.after(0, _append)
        except Exception:
            pass

    @classmethod
    def _ai_monitor_insert(cls, txt, ts, category, message):
        """Insert one formatted trace line (badge style) into the text widget."""
        badge_w = 10
        txt.configure(state="normal")
        txt.insert("end", f" {ts}  ", "dim")
        txt.insert("end", f" {category:^{badge_w}} ", f"badge_{category}")
        txt.insert("end", f"  {message}\n", f"msg_{category}")
        txt.configure(state="disabled")

    def _ai_monitor_update_status(self, category: str, message: str) -> None:
        """Refresh the status cards at the top of the monitor."""
        vars_map = getattr(self, "_ai_status_vars", None)
        if not vars_map:
            return
        try:
            short = message if len(message) <= 120 else message[:117] + "…"
            if category == "ML":
                vars_map["model"].set(short)
            elif category == "SIGNAL":
                vars_map["signal"].set(short)
                if "setup" in message.lower():
                    vars_map["setup"].set(short)
            elif category == "INSIGHT":
                vars_map["insight"].set(short)
            elif category == "LEARN":
                vars_map["learn"].set(short)
            elif category == "SIM":
                vars_map["tomorrow"].set(short)
            elif category in ("TRADE", "WARN"):
                vars_map["last_event"].set(f"[{category}] {short}")
            vars_map["events"].set(f"{len(self._ai_events)} events")
        except Exception:
            pass

    def _open_trade_learning_history(self):
        """Simulated tomorrow-trade batches with TP/SL walk and AI learning notes."""
        if self._trade_learning_win:
            try:
                if self._trade_learning_win.winfo_exists():
                    self._trade_learning_win.lift()
                    self._trade_learning_win.focus_force()
                    return
            except Exception:
                pass

        if not TRADE_SIMULATOR_AVAILABLE:
            messagebox.showwarning("Trade History", "Trade simulator not available.")
            return

        win = tk.Toplevel(self.root)
        win.title("Trade History & AI Learning")
        win.geometry("1320x760")
        win.configure(bg="#070D1A")
        win.minsize(960, 520)
        self._trade_learning_win = win

        hdr = tk.Frame(win, bg="#070D1A")
        hdr.pack(fill="x", padx=16, pady=(12, 8))
        tk.Label(hdr, text="Simulated Trade History", bg="#070D1A", fg="#F1F5F9",
                 font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Label(hdr, text="Tomorrow plans · tick TP/SL (MT5 tester style) · MT5 server time",
                 bg="#070D1A", fg="#64748B",
                 font=("Segoe UI", 10)).pack(side="left", padx=(12, 0))
        status_var = tk.StringVar(value="Starting batch simulator…")
        tk.Label(hdr, textvariable=status_var, bg="#070D1A", fg="#94A3B8",
                 font=("Consolas", 10)).pack(side="right")

        body = tk.Frame(win, bg="#0B1426")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        style = ttk.Style(win)
        style.theme_use("clam")
        style.configure("Sim.Treeview",
                        background="#0F172A", fieldbackground="#0F172A",
                        foreground="#E2E8F0", rowheight=26,
                        font=("Consolas", 11))
        style.configure("Sim.Treeview.Heading",
                        background="#1E293B", foreground="#F8FAFC",
                        font=("Segoe UI", 10, "bold"))
        style.map("Sim.Treeview", background=[("selected", "#1D4ED8")])

        cols = ("batch", "account", "phase", "symbol", "side", "entry_time", "entry_px",
                "exit_time", "exit_px", "duration", "outcome", "pnl", "ai")
        tree = ttk.Treeview(body, columns=cols, show="headings", height=18, style="Sim.Treeview")
        for c, w, t in [
            ("batch", 44, "Batch"), ("account", 88, "Account"), ("phase", 72, "Phase"),
            ("symbol", 64, "Symbol"), ("side", 44, "Side"),
            ("entry_time", 130, "Entry Time"), ("entry_px", 80, "Entry Price"),
            ("exit_time", 130, "Exit Time"), ("exit_px", 80, "Exit Price"),
            ("duration", 52, "Min"), ("outcome", 52, "Result"),
            ("pnl", 72, "Sim P/L"), ("ai", 44, "AI"),
        ]:
            tree.heading(c, text=t)
            tree.column(c, width=w, anchor="center")
        tree.column("entry_time", anchor="w")
        tree.column("exit_time", anchor="w")
        tree.column("account", anchor="w")
        vsb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        detail = tk.Text(win, bg="#0A1220", fg="#E2E8F0", font=("Consolas", 11),
                         height=9, wrap="word", relief="flat", padx=12, pady=10)
        detail.pack(fill="x", padx=16, pady=(0, 12))
        detail.insert("end", "Simulated tomorrow trades — each batch opens all queued plans at "
                            "current price, walks M1 until TP/SL, then opens the next batch.\n")
        detail.configure(state="disabled")

        row_map: dict = {}
        refresh_after: list = [None]

        def _show_detail(_evt=None):
            sel = tree.selection()
            if not sel:
                return
            row = row_map.get(sel[0])
            if not row:
                return
            detail.configure(state="normal")
            detail.delete("1.0", "end")
            detail.insert("end", f"Batch #{row.get('batch')}  {row.get('trade_id', '')}\n")
            detail.insert("end", f"{row.get('acct_num', '?')}  {row.get('phase_key', '')}  "
                                 f"{row.get('side', '').upper()} {row.get('symbol')}\n")
            detail.insert("end", f"Entry {row.get('entry_time_str')} @ {row.get('entry_price')}  "
                                 f"->  {row.get('exit_time_str', 'OPEN')} "
                                 f"@ {row.get('exit_price') if row.get('exit_price') is not None else '—'}\n")
            if row.get("outcome") and row.get("outcome") != "open":
                detail.insert("end", f"Outcome: {str(row.get('outcome')).upper()}  "
                                     f"MFE={row.get('mfe_points', '—')}  "
                                     f"MAE={row.get('mae_points', '—')} pts\n")
            if row.get("ai_lean"):
                detail.insert("end", f"Direction: {str(row.get('ai_lean')).upper()}\n")
            learn = row.get("learning")
            if learn:
                detail.insert("end", "\n── LOSS ANALYSIS ──\n", "hdr")
                detail.insert("end", f"What went wrong:\n{learn.get('what_went_wrong', '')}\n\n")
                detail.insert("end", f"What we improved next:\n{learn.get('what_improved', '')}\n\n")
                detail.insert("end", f"Did it help:\n{learn.get('did_it_help', '')}\n")
            elif row.get("won"):
                detail.insert("end", "\nTP hit — positive evidence logged to ML journal.\n")
            elif not row.get("closed"):
                tp = row.get("tp_level")
                sl = row.get("sl_level")
                detail.insert("end", f"\nStill open — watching M1 for TP @ {tp} or SL @ {sl}.\n")
            detail.configure(state="disabled")

        tree.bind("<<TreeviewSelect>>", _show_detail)
        detail.tag_configure("hdr", foreground="#FB923C", font=("Consolas", 11, "bold"))

        def _load():
            def _worker():
                plans = self._collect_tomorrow_trade_plans()
                brief = trade_simulator.step_batch_engine(
                    plans, "ustech",
                    log_fn=lambda m: self._ai_trace("SIM", m),
                )
                m1, _, _ = trade_simulator.fetch_m1_m5("ustech")
                rows = trade_simulator.get_simulated_trade_history(
                    include_open=True, m1_bars=m1)
                self.root.after(0, lambda: _populate(rows, brief))

            def _populate(rows, brief):
                for iid in tree.get_children():
                    tree.delete(iid)
                row_map.clear()
                wins = losses = open_n = 0
                for r in rows:
                    pnl = r.get("net_profit")
                    tag = "win" if r.get("won") else "loss" if r.get("lost") else "open"
                    if tag == "win":
                        wins += 1
                    elif tag == "loss":
                        losses += 1
                    else:
                        open_n += 1
                    acct = str(r.get("acct_num") or "?")
                    if len(acct) > 10:
                        acct = acct[-8:]
                    iid = tree.insert("", "end", values=(
                        r.get("batch", ""),
                        acct,
                        r.get("phase_key", ""),
                        r.get("symbol", ""),
                        r.get("side", "").upper(),
                        r.get("entry_time_str", ""),
                        r.get("entry_price", ""),
                        r.get("exit_time_str", ""),
                        r.get("exit_price") if r.get("exit_price") is not None else "—",
                        r.get("duration_min") if r.get("duration_min") is not None else "—",
                        str(r.get("outcome", "")).upper() if r.get("outcome") else "—",
                        f"{pnl:+.1f}" if pnl is not None else "—",
                        str(r.get("ai_lean") or "—").upper()[:4],
                    ), tags=(tag,))
                    row_map[iid] = r
                tree.tag_configure("win", foreground="#4ADE80")
                tree.tag_configure("loss", foreground="#F87171")
                tree.tag_configure("open", foreground="#60A5FA")
                closed = wins + losses
                acc = brief.get("accuracy", 0) if brief else 0
                batches = brief.get("n_batches", 0) if brief else 0
                cur_batch = brief.get("batch_num", 0) if brief else 0
                err = (brief or {}).get("error")
                if err:
                    status_var.set(f"{err} · {len(rows)} row(s)")
                else:
                    mode = (brief or {}).get("walk_mode", "m1")
                    ticks_n = (brief or {}).get("tick_count", 0)
                    status_var.set(
                        f"Batch #{cur_batch} · {len(rows)} sim trade(s) · "
                        f"{closed} closed ({wins}W/{losses}L) · {open_n} open · "
                        f"accuracy {acc:.0%} over {batches} batch(es) · "
                        f"{mode} ({ticks_n:,} ticks)")
                self._ai_trace("LEARN",
                               f"sim history: {len(rows)} trades, batch #{cur_batch}, "
                               f"{losses} loss(es) with notes")

            threading.Thread(target=_worker, name="sim-trade-history", daemon=True).start()

        def _schedule_refresh():
            if not win.winfo_exists():
                return
            _load()
            refresh_after[0] = win.after(30000, _schedule_refresh)

        def _on_close():
            if refresh_after[0]:
                try:
                    win.after_cancel(refresh_after[0])
                except Exception:
                    pass
            self._trade_learning_win = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", _on_close)

        tk.Button(hdr, text="  Refresh  ", command=_load,
                  bg="#1A2332", fg="#E2E8F0", relief="flat",
                  font=("Segoe UI", 10), cursor="hand2").pack(side="right", padx=(8, 0))

        def _open_chart_for_sel():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("Strategy Tester", "Select a trade first.")
                return
            row = row_map.get(sel[0])
            if row:
                self._open_strategy_tester(focus_trade_id=row.get("trade_id"))

        tk.Button(hdr, text="  📈 Chart  ", command=_open_chart_for_sel,
                  bg="#1D4ED8", fg="#F8FAFC", relief="flat",
                  font=("Segoe UI", 10), cursor="hand2").pack(side="right", padx=(8, 0))
        _load()
        refresh_after[0] = win.after(30000, _schedule_refresh)

    def _stester_stop_play(self):
        if self._stester_play_after and self._strategy_tester_win:
            try:
                self._strategy_tester_win.after_cancel(self._stester_play_after)
            except Exception:
                pass
        self._stester_play_after = None

    def _stester_update_indicator_legend(self, legend_frame, ctx, cursor_ts=None):
        """MT5-style indicator strip — blue=buy, red=sell, grey=neutral."""
        for w in legend_frame.winfo_children():
            w.destroy()
        if not ctx:
            return
        candles = ctx.get("candles") or []
        overlay = ctx.get("overlay") or {}
        ind_map = overlay.get("indicators") or {}
        ts = cursor_ts or ctx.get("entry_ts")
        bar_i = strategy_tester_chart.bar_index_for_ts(candles, int(ts or 0))

        tk.Label(legend_frame, text="Indicators @ replay:",
                 bg="#0a0a0a", fg="#9CA3AF",
                 font=("Segoe UI", 9)).pack(side="left", padx=(4, 8))

        for name in strategy_tester_chart.INDICATOR_NAMES:
            series = ind_map.get(name) or []
            sig = series[bar_i] if bar_i < len(series) else None
            bg = strategy_tester_chart.signal_color(sig)
            fg = "#FFFFFF" if sig else "#D1D5DB"
            short = name if len(name) <= 10 else name[:9] + "…"
            tk.Label(legend_frame, text=short, bg=bg, fg=fg,
                     font=("Segoe UI", 8), padx=4, pady=1).pack(
                         side="left", padx=1, pady=2)

        cons = (overlay.get("bar_signals") or [None])[bar_i] if bar_i < len(
            overlay.get("bar_signals") or []) else None
        if cons:
            tk.Label(legend_frame, text=f"  vote → {cons.upper()}",
                     bg="#0a0a0a", fg=strategy_tester_chart.signal_color(cons),
                     font=("Segoe UI", 9, "bold")).pack(side="left", padx=8)

    @staticmethod
    def _st_hex_rgb(hex_color: str):
        h = str(hex_color or "#808080").lstrip("#")
        if len(h) >= 6:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        return 128, 128, 128

    def _stester_pil_blit(self, canvas, img):
        """Single PhotoImage swap — avoids Tk canvas delete/repaint flicker."""
        from PIL import ImageTk
        photo = ImageTk.PhotoImage(img)
        iid = getattr(canvas, "_st_pil_id", None)
        try:
            if iid is not None and canvas.type(iid):
                canvas.itemconfig(iid, image=photo)
            else:
                canvas.delete("all")
                canvas._st_pil_id = canvas.create_image(0, 0, anchor="nw", image=photo)
        except Exception:
            canvas.delete("all")
            canvas._st_pil_id = canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas._st_pil_photo = photo
        canvas.configure(bg="#0a0a0a")

    def _stester_invalidate_play_cache(self, canvas):
        canvas._st_play_cache = None
        canvas._st_pil_id = None
        canvas._st_pil_photo = None

    def _st_pil_candle(self, draw, cx, bar_w, dc, y_of, is_forming,
                       vol_top, vol_h, vol_val, vol_max, cur_frac=1.0):
        bull = float(dc["c"]) >= float(dc["o"])
        if is_forming:
            col = "#60A5FA" if bull else "#F87171"
        else:
            col = "#2563EB" if bull else "#DC2626"
        rgb = self._st_hex_rgb(col)
        y_hi = y_of(float(dc["h"]))
        y_lo = y_of(float(dc["l"]))
        y_o = y_of(float(dc["o"]))
        y_c = y_of(float(dc["c"]))
        draw.line([(cx, y_hi), (cx, y_lo)], fill=rgb, width=2)
        body_top = min(y_o, y_c)
        body_h = max(5, abs(y_c - y_o))
        half = max(2, bar_w // 2)
        draw.rectangle(
            [cx - half, body_top, cx + half, body_top + body_h], fill=rgb)
        if vol_val and vol_max > 0:
            v = float(vol_val)
            if is_forming:
                v *= max(0.1, cur_frac)
            vh = int((v / vol_max) * (vol_h - 6))
            if vh > 0:
                vrgb = self._st_hex_rgb("#1D4ED8" if bull else "#991B1B")
                draw.rectangle(
                    [cx - half, vol_top + vol_h - vh, cx + half, vol_top + vol_h],
                    fill=vrgb)

    def _stester_draw_static_play(self, canvas, ctx, replay_frame, replay_active,
                                   cursor_px=None):
        """MT5-style play via PIL: closed bars accumulate; only forming bar redrawn."""
        from PIL import Image, ImageDraw

        candles = ctx.get("candles") or []
        if not candles or not replay_frame:
            return

        w = max(canvas.winfo_width(), 400)
        h = max(canvas.winfo_height(), 200)
        ml, mr, mt, mb = 78, 16, 22, 36
        vol_h = int(h * 0.14)
        ph = h - mt - mb - vol_h
        pw = w - ml - mr
        if pw < 20 or ph < 20:
            return

        cur_bar = max(0, min(int(replay_frame.get("bar_i", 0)), len(candles) - 1))
        cur_frac = float(replay_frame.get("frac", 1.0))
        _, forming = strategy_tester_chart.candles_at_frame(candles, cur_bar, cur_frac)

        sym = str(ctx.get("symbol") or "ustech").upper()
        t0_full = int(ctx.get("from_ts") or candles[0]["ts"])
        t1_full = int(ctx.get("to_ts") or candles[-1]["ts"])
        trades_list = list(ctx.get("trades") or [])
        highlight_id = ctx.get("highlight_trade_id")
        overlay = ctx.get("overlay") or {}
        ema21 = overlay.get("ema21") or []
        volumes = overlay.get("volumes") or []
        n_slots = max(1, len(candles))

        p_lo, p_hi = strategy_tester_chart.chart_price_bounds(candles, ctx)
        pr = p_hi - p_lo or 1.0
        vol_max = max(volumes) if volumes else 1.0
        vol_top = mt + ph + 4
        bar_w = max(8, int(pw / n_slots * 0.72))

        def y_of(p):
            return mt + (p_hi - float(p)) / pr * ph

        def x_bar(bi):
            return strategy_tester_chart.x_slot_for_bar(bi, n_slots, ml, pw)

        geom_key = (w, h, len(candles), t0_full, t1_full, len(trades_list))
        cache = getattr(canvas, "_st_play_cache", None)
        if cache is None or cache.get("geom_key") != geom_key:
            accum = Image.new("RGB", (w, h), self._st_hex_rgb("#0a0a0a"))
            draw = ImageDraw.Draw(accum)
            grid_rgb = self._st_hex_rgb("#1a1a1a")
            lbl_rgb = self._st_hex_rgb("#6B7280")
            for i in range(1, 4):
                y = mt + ph * i / 4
                draw.line([(ml, y), (ml + pw, y)], fill=grid_rgb, width=1)
                p = p_hi - pr * i / 4
                draw.text((ml - 40, y - 5), f"{p:.1f}", fill=lbl_rgb)
            step = max(1, len(candles) // 6)
            labeled = list(range(0, len(candles), step))
            if len(candles) - 1 not in labeled:
                labeled.append(len(candles) - 1)
            for bi in labeled:
                xb = x_bar(bi)
                draw.text(
                    (xb - 20, h - 14),
                    strategy_tester_chart.fmt_axis_time(int(candles[bi]["ts"])),
                    fill=lbl_rgb)
            for tr in trades_list:
                hl = bool(highlight_id and tr.get("trade_id") == highlight_id)
                side = str(tr.get("direction") or "").upper()
                ebi = int(tr.get("entry_bar") or 0)
                xbi = int(tr.get("exit_bar") or 0)
                ex, xx = x_bar(ebi), x_bar(xbi)
                entry_px = float(tr.get("entry_price") or 0)
                dim = not hl
                icol = self._st_hex_rgb("#22C55E" if side == "BUY" else "#F87171")
                dcol = self._st_hex_rgb("#334155")
                if ex is not None:
                    draw.line([(ex, mt), (ex, mt + ph + vol_h)],
                              fill=icol if not dim else dcol, width=2 if hl else 1)
                if tr.get("exit_ts") and xx is not None:
                    oc = str(tr.get("outcome") or "").upper()
                    ohex = "#4ADE80" if oc == "TP" else "#F87171" if oc == "SL" else "#A855F7"
                    ocol = self._st_hex_rgb(ohex)
                    draw.line([(xx, mt), (xx, mt + ph + vol_h)],
                              fill=ocol if not dim else dcol, width=2 if hl else 1)
                if ex is not None and xx is not None:
                    span_x2 = xx if tr.get("exit_ts") else ex + bar_w
                    xa, xb = min(ex, span_x2), max(ex, span_x2)
                    for price, hexc in (
                        (entry_px, "#22C55E" if side == "BUY" else "#EF4444"),
                        (tr.get("tp_level"), "#EF4444"),
                        (tr.get("sl_level"), "#EF4444"),
                    ):
                        if price is None:
                            continue
                        y = y_of(float(price))
                        draw.line([(xa, y), (xb, y)],
                                  fill=self._st_hex_rgb("#475569" if dim else hexc),
                                  width=2 if not dim else 1)
            cache = {
                "geom_key": geom_key,
                "last_closed_bar": -1,
                "accum": accum,
                "ml": ml, "pw": pw, "mt": mt, "ph": ph, "vol_h": vol_h,
                "vol_top": vol_top, "n_slots": n_slots, "bar_w": bar_w,
                "p_hi": p_hi, "pr": pr, "vol_max": vol_max,
            }
            canvas._st_play_cache = cache

        accum = cache["accum"]
        closed_upto = cur_bar - 1 if cur_frac < 1.0 else cur_bar
        if closed_upto > cache["last_closed_bar"]:
            draw_acc = ImageDraw.Draw(accum)
            for bi in range(cache["last_closed_bar"] + 1, closed_upto + 1):
                cx = x_bar(bi)
                if cx is None:
                    continue
                vol_val = volumes[bi] if bi < len(volumes) else 0
                self._st_pil_candle(
                    draw_acc, cx, cache["bar_w"], candles[bi], y_of, False,
                    cache["vol_top"], cache["vol_h"], vol_val, cache["vol_max"])
            cache["last_closed_bar"] = closed_upto

        frame = accum.copy()
        draw_f = ImageDraw.Draw(frame)
        is_forming = cur_frac < 1.0 and forming is not None
        if is_forming:
            cx = x_bar(cur_bar)
            if cx is not None:
                vol_val = volumes[cur_bar] if cur_bar < len(volumes) else 0
                self._st_pil_candle(
                    draw_f, cx, cache["bar_w"], forming, y_of, True,
                    cache["vol_top"], cache["vol_h"], vol_val, cache["vol_max"],
                    cur_frac=cur_frac)

        ema_pts = []
        for bi in range(0, cur_bar + 1):
            if bi < len(ema21) and ema21[bi] is not None:
                xb = x_bar(bi)
                if xb is not None:
                    ema_pts.extend([xb, y_of(float(ema21[bi]))])
        if len(ema_pts) >= 4:
            draw_f.line(list(zip(ema_pts[::2], ema_pts[1::2])),
                        fill=self._st_hex_rgb("#FF3333"), width=1)

        hdr = (f"{sym}  ·  {strategy_tester_chart.fmt_axis_time(t0_full)} → "
               f"{strategy_tester_chart.fmt_axis_time(t1_full)}"
               f"  ·  {len(trades_list)} trades · bar {cur_bar + 1}/{len(candles)}")
        if replay_active:
            hdr += "  ▶ REPLAY"
        draw_f.text((8, 6), hdr, fill=self._st_hex_rgb("#D1D5DB"))

        self._stester_pil_blit(canvas, frame)

    def _stester_draw_chart(self, canvas, ctx, cursor_ts=None, legend_frame=None,
                            cursor_px=None, replay_active=False, replay_frame=None):
        """MT5-style chart; during replay only closed + forming bars are drawn."""
        static_mode = bool(ctx.get("static_mode") and ctx.get("period_mode"))
        if static_mode and replay_active and replay_frame is not None:
            self._stester_draw_static_play(
                canvas, ctx, replay_frame, replay_active, cursor_px=cursor_px)
            return

        if getattr(canvas, "_st_play_cache", None) is not None:
            self._stester_invalidate_play_cache(canvas)

        canvas.delete("all")
        canvas.configure(bg="#0a0a0a")
        if replay_active:
            pass  # skip update_idletasks — causes visible flash between frames
        else:
            try:
                canvas.update_idletasks()
            except Exception:
                pass
        w = max(canvas.winfo_width(), 400)
        h = max(canvas.winfo_height(), 200)
        ml, mr, mt, mb = 78, 16, 22, 36
        vol_h = int(h * 0.14)
        ph = h - mt - mb - vol_h
        pw = w - ml - mr
        if pw < 20 or ph < 20:
            return

        candles = ctx.get("candles") or []
        ticks = ctx.get("ticks") or []
        if not candles:
            canvas.create_text(w // 2, h // 2, text="No M1 data — connect MT5",
                               fill="#9CA3AF", font=("Segoe UI", 12))
            return

        sym = str(ctx.get("symbol") or "ustech").upper()
        t0_full = ctx.get("from_ts") or candles[0]["ts"]
        t1_full = ctx.get("to_ts") or candles[-1]["ts"]
        if t1_full <= t0_full:
            t1_full = t0_full + 60

        # Chart-first replay: frame = market bar position; trade follows the chart
        forming = None
        chart_mode = replay_frame is not None
        cur_bar = 0
        cur_frac = 1.0
        if chart_mode:
            cur_bar = int(replay_frame.get("bar_i", 0))
            cur_frac = float(replay_frame.get("frac", 1.0))
            cur_bar = max(0, min(cur_bar, len(candles) - 1))
            completed, forming = strategy_tester_chart.candles_at_frame(
                candles, cur_bar, cur_frac)
            if cursor_ts is None and replay_frame.get("ts"):
                cursor_ts = int(replay_frame["ts"])
            if cursor_px is None and replay_frame.get("mid"):
                cursor_px = float(replay_frame["mid"])
        else:
            completed, forming = candles, None

        overlay = ctx.get("overlay") or {}
        ema21 = overlay.get("ema21") or []
        bar_signals = overlay.get("bar_signals") or []
        volumes = overlay.get("volumes") or []

        period_mode = bool(ctx.get("period_mode") and (ctx.get("trades") or []))
        static_mode = bool(period_mode and ctx.get("static_mode"))
        trades_list: List[Dict[str, Any]] = list(ctx.get("trades") or []) if period_mode else []
        highlight_id = ctx.get("highlight_trade_id")

        entry_bar = int(ctx.get("entry_bar") or 0)
        exit_bar = int(ctx.get("exit_bar") or max(0, len(candles) - 1))
        entry_frac = float(ctx.get("entry_frac") or 0.08)
        exit_frac = float(ctx.get("exit_frac") or 0.92)
        entry_ts = int(ctx.get("entry_ts") or 0)
        exit_ts = int(ctx.get("exit_ts") or 0)

        active_tr: Optional[Dict[str, Any]] = None
        if period_mode and chart_mode:
            active_tr = strategy_tester_chart.active_trade_at_frame(
                trades_list, cur_bar, cur_frac)
        elif not period_mode:
            active_tr = ctx if ctx.get("entry_ts") else None

        if period_mode:
            trade_live = active_tr is not None
            trade_closed = False
        elif chart_mode:
            trade_live = (cur_bar > entry_bar
                          or (cur_bar == entry_bar and cur_frac >= entry_frac))
            trade_closed = bool(exit_ts and ctx.get("exit_price") is not None and (
                cur_bar > exit_bar
                or (cur_bar == exit_bar and cur_frac >= exit_frac)))
        else:
            trade_live = True
            trade_closed = bool(exit_ts and ctx.get("exit_price") is not None)

        vis_i0 = 0
        if static_mode:
            n_slots = max(1, len(candles))
            if chart_mode:
                pass  # cur_bar already set from replay_frame
            else:
                cur_bar = len(candles) - 1
                cur_frac = 1.0
        elif chart_mode and period_mode:
            max_vis = max(48, min(120, int(pw / 7)))
            vis_i0, _, n_slots = strategy_tester_chart.visible_bar_window(
                cur_bar, len(candles), max_vis)
        else:
            n_slots = max(1, (cur_bar + 1) if chart_mode else len(candles))

        hdr = (f"{sym}  ·  {strategy_tester_chart.fmt_axis_time(int(t0_full))} → "
               f"{strategy_tester_chart.fmt_axis_time(int(t1_full))}")
        if static_mode:
            hdr += f"  ·  {len(trades_list)} trades · {len(candles)} bars"
            if highlight_id:
                hdr += f"  ·  ▶ {str(highlight_id)[-12:]}"
        elif period_mode:
            hdr += f"  ·  {len(trades_list)} trades"
            done = sum(
                1 for tr in trades_list
                if tr.get("exit_ts") and strategy_tester_chart.frame_reached(
                    cur_bar, cur_frac,
                    int(tr.get("exit_bar") or 0),
                    float(tr.get("exit_frac") or 1.0)))
            hdr += f"  ·  {done}/{len(trades_list)} closed"
        if chart_mode:
            hdr += f"  ·  bar {cur_bar + 1}/{len(candles)}"
        if replay_active:
            hdr += "  ▶ REPLAY"
        canvas.create_text(8, 6, anchor="nw", text=hdr,
                           fill="#D1D5DB", font=("Segoe UI", 10))

        p_lo, p_hi = strategy_tester_chart.chart_price_bounds(candles, ctx)
        pr = p_hi - p_lo or 1.0
        t0, t1 = int(t0_full), int(t1_full)

        vol_max = max(volumes) if volumes else 1.0
        vol_top = mt + ph + 4

        def y_of(p):
            return mt + (p_hi - float(p)) / pr * ph

        def x_bar(bi):
            if bi < vis_i0:
                return None
            return strategy_tester_chart.x_slot_for_bar(bi - vis_i0, n_slots, ml, pw)

        def x_of(ts):
            ts = int(ts or 0)
            if chart_mode and not static_mode:
                bi = strategy_tester_chart.bar_index_for_ts(candles, ts)
                bi = max(0, min(bi, cur_bar))
                return x_bar(bi)
            span = max(1, t1 - t0)
            return ml + (ts - t0) / span * pw

        for i in range(1, 4):
            y = mt + ph * i / 4
            canvas.create_line(ml, y, ml + pw, y, fill="#1a1a1a")
            p = p_hi - pr * i / 4
            canvas.create_text(ml - 4, y, text=f"{p:.1f}", anchor="e",
                               fill="#6B7280", font=("Consolas", 8))

        bar_w = max(8, int(pw / n_slots * 0.72))

        def _paint_candle(bi, dc, is_forming_bar=False):
            cx = x_bar(bi)
            if cx is None:
                return
            bull = float(dc["c"]) >= float(dc["o"])
            col = "#2563EB" if bull else "#DC2626"
            if is_forming_bar:
                col = "#60A5FA" if bull else "#F87171"
            y_hi, y_lo = y_of(float(dc["h"])), y_of(float(dc["l"]))
            y_o, y_c = y_of(float(dc["o"])), y_of(float(dc["c"]))
            canvas.create_line(cx, y_hi, cx, y_lo, fill=col, width=2)
            body_top = min(y_o, y_c)
            body_h = max(5, abs(y_c - y_o))
            canvas.create_rectangle(cx - bar_w // 2, body_top,
                                    cx + bar_w // 2, body_top + body_h,
                                    fill=col, outline="#FFFFFF" if is_forming_bar else col,
                                    width=1 if is_forming_bar else 0)
            sig = bar_signals[bi] if bi < len(bar_signals) else None
            if not is_forming_bar and sig == "buy":
                dy = y_of(float(dc["l"])) + 8
                canvas.create_polygon(cx, dy - 4, cx - 3, dy + 2, cx + 3, dy + 2,
                                      fill="#2563EB", outline="#93C5FD")
            elif not is_forming_bar and sig == "sell":
                dy = y_of(float(dc["h"])) - 8
                canvas.create_polygon(cx, dy + 4, cx - 3, dy - 2, cx + 3, dy - 2,
                                      fill="#DC2626", outline="#FCA5A5")
            if volumes and bi < len(volumes) and vol_max > 0:
                v = float(volumes[bi])
                if is_forming_bar:
                    v *= max(0.1, cur_frac)
                vh = int((v / vol_max) * (vol_h - 6))
                if vh > 0:
                    vcol = "#1D4ED8" if bull else "#991B1B"
                    canvas.create_rectangle(cx - bar_w // 2, vol_top + vol_h - vh,
                                            cx + bar_w // 2, vol_top + vol_h,
                                            fill=vcol, outline="")

        # ── Paint market (candles) first — always ──
        if static_mode:
            for bi, c in enumerate(candles):
                is_forming = (chart_mode and bi == cur_bar and cur_frac < 1.0
                              and forming is not None)
                dc = forming if is_forming else c
                _paint_candle(bi, dc, is_forming)
            if chart_mode:
                cx = x_bar(cur_bar)
                if cx is not None:
                    canvas.create_line(cx, mt, cx, mt + ph + vol_h,
                                       fill="#FBBF24", width=2)
                    if cursor_px and cursor_px > 0:
                        cy = y_of(cursor_px)
                        canvas.create_oval(cx - 5, cy - 5, cx + 5, cy + 5,
                                           fill="#FBBF24", outline="#FFF", width=2)
        elif chart_mode:
            paint_from = vis_i0 if period_mode else 0
            for bi in range(paint_from, cur_bar):
                _paint_candle(bi, candles[bi], False)
            is_forming = cur_frac < 1.0 and forming is not None
            dc = forming if is_forming else candles[cur_bar]
            _paint_candle(cur_bar, dc, is_forming)
            cx = x_bar(cur_bar)
            if cx is not None:
                canvas.create_line(cx, mt, cx, mt + ph + vol_h, fill="#FBBF24", width=2)
                if cursor_px and cursor_px > 0:
                    cy = y_of(cursor_px)
                    canvas.create_oval(cx - 5, cy - 5, cx + 5, cy + 5,
                                       fill="#FBBF24", outline="#FFF", width=2)
        else:
            for bi, c in enumerate(candles):
                _paint_candle(bi, c, False)

        # EMA21 on visible bars
        ema_pts = []
        if static_mode:
            ema_from, last_bi = 0, len(candles) - 1
        else:
            ema_from = vis_i0 if (chart_mode and period_mode) else 0
            last_bi = cur_bar if chart_mode else len(candles) - 1
        for bi in range(ema_from, last_bi + 1):
            if bi < len(ema21) and ema21[bi] is not None:
                xb = x_bar(bi)
                if xb is not None:
                    ema_pts.extend([xb, y_of(float(ema21[bi]))])
        if len(ema_pts) >= 4:
            canvas.create_line(ema_pts, fill="#FF3333", width=1, smooth=True)

        def _hline(price, label, color, dash=(4, 3), dim=False):
            if price is None:
                return
            y = y_of(float(price))
            c = color if not dim else "#475569"
            canvas.create_line(ml, y, ml + pw, y, fill=c, dash=dash, width=1)
            if label:
                canvas.create_text(ml + 2, y - 2, text=label, anchor="sw",
                                   fill=c, font=("Segoe UI", 9))

        def _draw_trade_markers(tr: Dict[str, Any], live: bool, closed: bool):
            side = str(tr.get("direction") or "").upper()
            entry_px = float(tr.get("entry_price") or 0)
            ebi = int(tr.get("entry_bar") or 0)
            xbi = int(tr.get("exit_bar") or 0)
            ef = float(tr.get("entry_frac") or 0.08)
            xf = float(tr.get("exit_frac") or 0.92)
            xt = int(tr.get("exit_ts") or 0)

            if tr.get("sl_level") is not None:
                _hline(tr.get("sl_level"), "SL" if live else "", "#EF4444", dim=not live)
            if tr.get("tp_level") is not None:
                _hline(tr.get("tp_level"), "TP" if live else "", "#EF4444", dim=not live)
            if entry_px:
                elabel = f"{side} @ {entry_px:.2f}" if live else ""
                ecol = "#22C55E" if side == "BUY" else "#EF4444"
                _hline(entry_px, elabel, ecol, dash=(6, 4), dim=not live)
                if live:
                    ex = x_bar(ebi)
                    if ex is not None:
                        ey = y_of(entry_px)
                        efill = "#2563EB" if side == "BUY" else "#DC2626"
                        canvas.create_polygon(
                            ex, ey - 8, ex - 6, ey + 4, ex + 6, ey + 4,
                            fill=efill, outline="#FFF")
                        tid = str(tr.get("trade_id") or "")[-8:]
                        canvas.create_text(
                            ex, ey - 12, text=f"ENTRY {side} {tid}",
                            fill=efill, font=("Segoe UI", 8, "bold"))
            if closed and tr.get("exit_price") is not None:
                oc = str(tr.get("outcome", "")).upper()
                xx = x_bar(xbi)
                if xx is not None:
                    xy = y_of(tr["exit_price"])
                    col = "#4ADE80" if oc == "TP" else "#F87171" if oc == "SL" else "#A855F7"
                    canvas.create_oval(xx - 6, xy - 6, xx + 6, xy + 6,
                                       fill=col, outline="#FFF")
                    canvas.create_text(xx, xy - 14, text=f"EXIT {oc}",
                                       fill=col, font=("Segoe UI", 8, "bold"))

        def _seg_hline(x1, x2, price, color, dash=(6, 4), label="", dim=False):
            if price is None or x1 is None or x2 is None:
                return
            xa, xb = min(float(x1), float(x2)), max(float(x1), float(x2))
            y = y_of(float(price))
            c = "#475569" if dim else color
            canvas.create_line(xa, y, xb, y, fill=c, dash=dash, width=2 if not dim else 1)
            if label and not dim:
                canvas.create_text(xa + 2, y - 2, text=label, anchor="sw",
                                   fill=c, font=("Segoe UI", 8))

        # Static period chart — all trades + levels at once (matplotlib-style)
        if static_mode:
            for tr in trades_list:
                hl = bool(highlight_id and tr.get("trade_id") == highlight_id)
                side = str(tr.get("direction") or "").upper()
                ebi = int(tr.get("entry_bar") or 0)
                xbi = int(tr.get("exit_bar") or 0)
                ex, xx = x_bar(ebi), x_bar(xbi)
                entry_px = float(tr.get("entry_price") or 0)
                dim = not hl
                icol = "#22C55E" if side == "BUY" else "#F87171"
                if ex is not None:
                    vcol = icol if not dim else "#334155"
                    canvas.create_line(ex, mt, ex, mt + ph + vol_h,
                                       fill=vcol, dash=(3, 4), width=2 if hl else 1)
                if tr.get("exit_ts") and xx is not None:
                    oc = str(tr.get("outcome") or "").upper()
                    ocol = "#4ADE80" if oc == "TP" else "#F87171" if oc == "SL" else "#A855F7"
                    vcol = ocol if not dim else "#334155"
                    canvas.create_line(xx, mt, xx, mt + ph + vol_h,
                                       fill=vcol, dash=(3, 4), width=2 if hl else 1)
                if ex is not None and xx is not None:
                    span_x2 = xx if tr.get("exit_ts") else ex + bar_w
                    ecol = "#22C55E" if side == "BUY" else "#EF4444"
                    elabel = f"{side} @ {entry_px:.2f}" if hl else ""
                    _seg_hline(ex, span_x2, entry_px, ecol, dash=(6, 4),
                               label=elabel, dim=dim)
                    _seg_hline(ex, span_x2, tr.get("tp_level"), "#EF4444",
                               dash=(4, 3), label="TP" if hl else "", dim=dim)
                    _seg_hline(ex, span_x2, tr.get("sl_level"), "#EF4444",
                               dash=(4, 3), label="SL" if hl else "", dim=dim)
                    if hl and entry_px:
                        ey = y_of(entry_px)
                        efill = "#2563EB" if side == "BUY" else "#DC2626"
                        canvas.create_polygon(
                            ex, ey - 8, ex - 6, ey + 4, ex + 6, ey + 4,
                            fill=efill, outline="#FFF")
                        tid = str(tr.get("trade_id") or "")[-8:]
                        canvas.create_text(
                            ex, ey - 12, text=f"ENTRY {side} {tid}",
                            fill=efill, font=("Segoe UI", 8, "bold"))
                    if hl and tr.get("exit_price") is not None and xx is not None:
                        xy = y_of(tr["exit_price"])
                        oc = str(tr.get("outcome", "")).upper()
                        col = "#4ADE80" if oc == "TP" else "#F87171" if oc == "SL" else "#A855F7"
                        canvas.create_oval(xx - 6, xy - 6, xx + 6, xy + 6,
                                           fill=col, outline="#FFF")
                        canvas.create_text(xx, xy - 14, text=f"EXIT {oc}",
                                           fill=col, font=("Segoe UI", 8, "bold"))

        # Vertical dotted lines — entry → exit span for each trade (progressive replay)
        elif period_mode and chart_mode:
            for tr in trades_list:
                side = str(tr.get("direction") or "").upper()
                ebi = int(tr.get("entry_bar") or 0)
                xbi = int(tr.get("exit_bar") or 0)
                ef = float(tr.get("entry_frac") or 0.08)
                xf = float(tr.get("exit_frac") or 0.92)
                past_in = strategy_tester_chart.frame_reached(
                    cur_bar, cur_frac, ebi, ef)
                past_out = bool(tr.get("exit_ts")) and strategy_tester_chart.frame_reached(
                    cur_bar, cur_frac, xbi, xf)
                if past_in:
                    ex = x_bar(ebi)
                    if ex is not None:
                        icol = "#22C55E" if side == "BUY" else "#F87171"
                        canvas.create_line(
                            ex, mt, ex, mt + ph + vol_h,
                            fill=icol, dash=(3, 4), width=1)
                if past_out:
                    xx = x_bar(xbi)
                    if xx is not None:
                        oc = str(tr.get("outcome") or "").upper()
                        ocol = "#4ADE80" if oc == "TP" else "#F87171" if oc == "SL" else "#A855F7"
                        canvas.create_line(
                            xx, mt, xx, mt + ph + vol_h,
                            fill=ocol, dash=(3, 4), width=1)
                if past_in and past_out:
                    x1, x2 = x_bar(ebi), x_bar(xbi)
                    if x1 is not None and x2 is not None:
                        canvas.create_line(
                            x1, mt + 2, x2, mt + 2,
                            fill="#64748B", dash=(2, 5), width=1)

        # Active / single trade TP-SL overlay
        if period_mode and active_tr and not static_mode:
            _draw_trade_markers(active_tr, live=True, closed=False)
        elif period_mode and chart_mode:
            pass
        elif not period_mode:
            side = str(ctx.get("direction") or "").upper()
            entry_px = float(ctx.get("entry_price") or 0)
            if ctx.get("sl_level") is not None:
                _hline(ctx["sl_level"], "SL" if trade_live else "", "#EF4444",
                       dim=not trade_live)
            if ctx.get("tp_level") is not None:
                _hline(ctx["tp_level"], "TP" if trade_live else "", "#EF4444",
                       dim=not trade_live)
            if entry_px:
                elabel = f"{side} 0.05 at {entry_px:.2f}" if trade_live else ""
                ecol = "#22C55E" if side == "BUY" else "#EF4444"
                _hline(entry_px, elabel, ecol, dash=(6, 4), dim=not trade_live)
                if trade_live:
                    ex = x_bar(entry_bar) if chart_mode else x_of(entry_ts)
                    if ex is not None:
                        ey = y_of(entry_px)
                        efill = "#2563EB" if side == "BUY" else "#DC2626"
                        canvas.create_polygon(
                            ex, ey - 8, ex - 6, ey + 4, ex + 6, ey + 4,
                            fill=efill, outline="#FFF")
                        canvas.create_text(ex, ey - 12, text=f"ENTRY {side}",
                                           fill=efill, font=("Segoe UI", 8, "bold"))
                elif entry_bar >= 0:
                    ex = x_bar(entry_bar) if chart_mode else x_of(entry_ts)
                    if ex is not None:
                        canvas.create_line(ex, mt, ex, mt + ph + vol_h,
                                           fill="#475569", dash=(2, 4))
                        canvas.create_text(ex, mt + 4, text="entry →",
                                           fill="#64748B", font=("Segoe UI", 8))
            if trade_closed and ctx.get("exit_price") is not None:
                oc = str(ctx.get("outcome", "")).upper()
                xx = x_bar(exit_bar) if chart_mode else x_of(exit_ts)
                if xx is not None:
                    xy = y_of(ctx["exit_price"])
                    col = "#4ADE80" if oc == "TP" else "#F87171" if oc == "SL" else "#A855F7"
                    canvas.create_oval(xx - 6, xy - 6, xx + 6, xy + 6,
                                       fill=col, outline="#FFF")
                    canvas.create_text(xx, xy - 14, text=f"EXIT {oc}",
                                       fill=col, font=("Segoe UI", 8, "bold"))

        if static_mode:
            step = max(1, len(candles) // 6)
            labeled = list(range(0, len(candles), step))
            if len(candles) - 1 not in labeled:
                labeled.append(len(candles) - 1)
            for bi in labeled:
                xb = x_bar(bi)
                if xb is None:
                    continue
                canvas.create_text(
                    xb, h - 8,
                    text=strategy_tester_chart.fmt_axis_time(int(candles[bi]["ts"])),
                    fill="#6B7280", font=("Consolas", 8))
        elif chart_mode:
            step = max(1, (cur_bar + 1 - vis_i0) // 4)
            labeled = list(range(vis_i0, cur_bar + 1, step))
            if cur_bar not in labeled:
                labeled.append(cur_bar)
            for bi in labeled:
                xb = x_bar(bi)
                if xb is None:
                    continue
                canvas.create_text(
                    xb, h - 8,
                    text=strategy_tester_chart.fmt_axis_time(int(candles[bi]["ts"])),
                    fill="#6B7280", font=("Consolas", 8))
        else:
            for frac in (0.0, 0.5, 1.0):
                ts = int(t0 + (t1 - t0) * frac)
                canvas.create_text(x_of(ts), h - 8,
                                   text=strategy_tester_chart.fmt_axis_time(ts),
                                   fill="#6B7280", font=("Consolas", 8))

        if legend_frame is not None and not replay_active:
            try:
                self._stester_update_indicator_legend(legend_frame, ctx, cursor_ts)
            except Exception:
                pass

    def _stester_draw_chart_safe(self, canvas, ctx, **kwargs):
        """Draw wrapper — surface errors instead of leaving a blank canvas."""
        try:
            self._stester_draw_chart(canvas, ctx, **kwargs)
        except Exception as exc:
            canvas.delete("all")
            canvas.configure(bg="#0a0a0a")
            w = max(canvas.winfo_width(), 400)
            h = max(canvas.winfo_height(), 200)
            canvas.create_text(
                w // 2, h // 2,
                text=f"Chart draw error:\n{exc}",
                fill="#F87171", font=("Segoe UI", 11), justify="center")

    def _open_strategy_tester(self, focus_trade_id=None):
        """Strategy Tester — tick/M1 chart replay of simulated entries."""
        if self._strategy_tester_win:
            try:
                if self._strategy_tester_win.winfo_exists():
                    self._strategy_tester_win.lift()
                    self._strategy_tester_win.focus_force()
                    if focus_trade_id and hasattr(self, "_stester_focus_trade"):
                        self._stester_focus_trade(focus_trade_id)
                    return
            except Exception:
                pass

        if not TRADE_SIMULATOR_AVAILABLE or not STRATEGY_TESTER_AVAILABLE:
            messagebox.showwarning(
                "Strategy Tester",
                "Trade simulator / chart module not available.")
            return

        win = tk.Toplevel(self.root)
        win.title("Strategy Tester — Simulated Entry Replay")
        win.geometry("1420x880")
        win.configure(bg="#070D1A")
        win.minsize(1000, 640)
        self._strategy_tester_win = win

        st: Dict[str, Any] = {
            "ctx": None,
            "period_ctx": None,
            "rows": [],
            "tick_idx": 0,
            "playing": False,
            "_play_saved_ctx": None,
            "_scrub_sync": False,
        }

        hdr = tk.Frame(win, bg="#070D1A")
        hdr.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(hdr, text="Strategy Tester", bg="#070D1A", fg="#F1F5F9",
                 font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Label(hdr, text="Historical tick replay · trader blueprints · TP/SL walk",
                 bg="#070D1A", fg="#64748B",
                 font=("Segoe UI", 10)).pack(side="left", padx=(12, 0))

        period_var = tk.StringVar(value="30d")
        period_frame = tk.Frame(hdr, bg="#070D1A")
        period_frame.pack(side="left", padx=(20, 0))
        tk.Label(period_frame, text="Period:", bg="#070D1A", fg="#94A3B8",
                 font=("Segoe UI", 10)).pack(side="left", padx=(0, 6))
        period_menu = ttk.Combobox(
            period_frame, textvariable=period_var, state="readonly", width=18,
            values=[trade_simulator.HISTORICAL_PERIOD_LABELS[k]
                    for k in ("live", "7d", "30d", "90d", "365d")])
        period_menu.pack(side="left")
        period_menu.current(2)  # default 30d

        _label_to_key = {v: k for k, v in trade_simulator.HISTORICAL_PERIOD_LABELS.items()}

        status_var = tk.StringVar(value="Choose a period and click Run Backtest…")
        tk.Label(hdr, textvariable=status_var, bg="#070D1A", fg="#94A3B8",
                 font=("Consolas", 10)).pack(side="right")

        stats_var = tk.StringVar(value="")
        stats_bar = tk.Frame(win, bg="#0F172A")
        stats_bar.pack(fill="x", padx=16, pady=(0, 4))
        tk.Label(stats_bar, textvariable=stats_var, bg="#0F172A", fg="#CBD5E1",
                 font=("Consolas", 10), anchor="w").pack(fill="x", padx=8, pady=4)

        ctrl = tk.Frame(win, bg="#0B1426")
        ctrl.pack(fill="x", padx=16, pady=(0, 6))
        tick_var = tk.IntVar(value=0)
        play_lbl = tk.StringVar(value="▶ Play chart")

        chart_frame = tk.Frame(win, bg="#0a0a0a", highlightbackground="#333333",
                               highlightthickness=1)
        chart_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        chart = tk.Canvas(chart_frame, bg="#0a0a0a", highlightthickness=0)
        chart.pack(fill="both", expand=True)

        legend_frame = tk.Frame(win, bg="#0a0a0a")
        legend_frame.pack(fill="x", padx=16, pady=(0, 6))

        lower = tk.Frame(win, bg="#0B1426")
        lower.pack(fill="both", expand=False, padx=16, pady=(0, 12))

        cols = ("batch", "account", "phase", "side", "entry_time", "entry_px",
                "outcome", "pnl")
        tree = ttk.Treeview(lower, columns=cols, show="headings", height=8)
        for c, w, t in [
            ("batch", 44, "Batch"), ("account", 88, "Account"), ("phase", 72, "Phase"),
            ("side", 44, "Side"), ("entry_time", 130, "Entry"), ("entry_px", 80, "Price"),
            ("outcome", 52, "Result"), ("pnl", 72, "P/L"),
        ]:
            tree.heading(c, text=t)
            tree.column(c, width=w, anchor="center")
        tree.column("entry_time", anchor="w")
        tree.pack(side="left", fill="both", expand=True)
        vsb = ttk.Scrollbar(lower, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="left", fill="y")

        detail = tk.Text(lower, bg="#0A1220", fg="#E2E8F0", font=("Consolas", 10),
                         width=48, height=8, wrap="word", relief="flat", padx=10, pady=8)
        detail.pack(side="right", fill="y", padx=(8, 0))
        detail.insert("end", "Run Backtest → full period replay plays every simulated trade in order.\n"
                              "Vertical dotted lines mark each entry (IN) and exit (TP/SL).\n"
                              "Click a row to jump the scrubber to that trade's entry.\n")
        detail.configure(state="disabled")

        row_map: dict = {}

        def _replay_frames(ctx):
            frames = ctx.get("replay_frames") or ctx.get("ticks") or []
            return frames if frames else []

        def _sync_scrub(idx: int):
            """Move scrubber without treating it as a user pause."""
            st["_scrub_sync"] = True
            try:
                tick_var.set(int(idx))
            finally:
                st["_scrub_sync"] = False

        def _redraw(replay_active=False):
            ctx = st.get("ctx")
            if not ctx:
                return
            cursor_ts = None
            cursor_px = None
            replay_frame = None
            frames = _replay_frames(ctx)
            idx = st.get("tick_idx", 0)
            static = bool(ctx.get("static_mode"))
            show_cursor = replay_active or (static and idx > 0)
            if frames and idx < len(frames) and (not static or show_cursor):
                replay_frame = frames[idx]
                cursor_ts = int(replay_frame["ts"])
                cursor_px = float(replay_frame.get("mid") or 0)
            self._stester_draw_chart_safe(
                chart, ctx,
                cursor_ts=cursor_ts,
                legend_frame=legend_frame,
                cursor_px=cursor_px,
                replay_active=replay_active,
                replay_frame=replay_frame)

        def _show_trade(row):
            detail.configure(state="normal")
            detail.delete("1.0", "end")
            detail.insert("end", f"Loading chart for {row.get('trade_id')}…\n")
            detail.configure(state="disabled")
            status_var.set("Fetching M1 + ticks from MT5…")

            def _worker():
                try:
                    self._ensure_mt5_for_signals()
                    ctx = strategy_tester_chart.build_trade_replay(row)
                except Exception as e:
                    ctx = {"error": str(e)}
                self.root.after(0, lambda: _apply_ctx(row, ctx))

            threading.Thread(target=_worker, name="stester-chart", daemon=True).start()

        def _apply_period_ctx(ctx, brief=None):
            if ctx.get("error"):
                status_var.set(f"Period load: {ctx['error']}")
                return
            st["period_ctx"] = ctx
            st["ctx"] = ctx
            st["tick_idx"] = 0
            n = ctx.get("n_trades") or len(ctx.get("trades") or [])
            nframes = ctx.get("frame_count", len(ctx.get("replay_frames") or []))
            nbars = len(ctx.get("candles") or [])
            _sync_scrub(0)
            scrub.configure(to=max(0, nframes - 1))
            _redraw(replay_active=False)
            mode_lbl = "static" if ctx.get("static_mode") else "replay"
            status_var.set(
                f"Chart ready · {n} trades · {nbars} M1 bars · "
                f"{nframes:,} {mode_lbl} frames · ▶ Play")
            detail.configure(state="normal")
            detail.delete("1.0", "end")
            detail.insert("end", f"Period chart — {n} trades\n\n")
            detail.insert("end", f"{strategy_tester_chart.fmt_axis_time(ctx['from_ts'])} → "
                                 f"{strategy_tester_chart.fmt_axis_time(ctx['to_ts'])}\n")
            detail.insert("end", f"{nbars} M1 bars · all entry/TP/SL levels shown\n\n")
            detail.insert("end", "Click a trade row to highlight it on the chart.\n")
            detail.insert("end", "▶ Play moves the cursor across the full chart.\n")
            if brief and brief.get("stats"):
                s = brief["stats"]
                detail.insert("end", f"\n{s.get('tp', 0)} TP · {s.get('sl')} SL · "
                                     f"win rate {s.get('win_rate', 0):.0%}\n")
            detail.configure(state="disabled")
            focus_tid = st.pop("focus_trade_id", None)
            if focus_tid:
                for iid, r in row_map.items():
                    if r.get("trade_id") == focus_tid:
                        tree.selection_set(iid)
                        tree.focus(iid)
                        _highlight_on_chart(r)
                        break

        def _load_period(rows, brief=None):
            if not rows:
                return
            status_var.set("Loading M1 chart (all trades)…")

            def _worker():
                try:
                    self._ensure_mt5_for_signals()
                    ctx = strategy_tester_chart.build_period_chart(rows)
                except Exception as e:
                    ctx = {"error": str(e)}
                self.root.after(0, lambda: _apply_period_ctx(ctx, brief))

            threading.Thread(target=_worker, name="stester-period", daemon=True).start()

        def _fill_trade_detail(row):
            detail.configure(state="normal")
            detail.delete("1.0", "end")
            detail.insert("end", f"{row.get('trade_id')}  batch #{row.get('batch')}\n")
            detail.insert("end", f"{row.get('acct_num')}  {row.get('phase_key')}  "
                                 f"{str(row.get('side', '')).upper()}\n\n")
            et = int(row.get("entry_time") or row.get("entry_ts") or 0)
            detail.insert("end", f"Entry  {strategy_tester_chart.fmt_axis_time(et)} "
                                 f"@ {row.get('entry_price')}\n")
            if row.get("exit_time") or row.get("exit_ts"):
                detail.insert("end", f"Exit   @ {row.get('exit_price')}  "
                                     f"→ {str(row.get('outcome', '')).upper()}\n")
            detail.insert("end", f"TP {row.get('tp_level')}  SL {row.get('sl_level')}\n")
            pnl = row.get("net_profit")
            if pnl is not None:
                detail.insert("end", f"P/L {pnl:+.1f} pts\n")
            detail.configure(state="disabled")

        def _highlight_on_chart(row):
            ctx = st.get("ctx") or {}
            if not (ctx.get("static_mode") and ctx.get("period_mode")):
                return False
            tid = row.get("trade_id")
            trades = ctx.get("trades") or []
            match = next((t for t in trades if t.get("trade_id") == tid), None)
            if not match:
                return False
            ctx = dict(ctx)
            ctx["highlight_trade_id"] = tid
            st["ctx"] = ctx
            frames = _replay_frames(ctx)
            ebi = int(match.get("entry_bar") or 0)
            idx = strategy_tester_chart.frame_index_for_bar(frames, ebi)
            st["tick_idx"] = idx
            _sync_scrub(idx)
            _redraw(replay_active=False)
            _fill_trade_detail(row)
            status_var.set(
                f"Highlighted {str(tid)[-12:]} · bar {ebi + 1}/{len(ctx.get('candles') or [])}")
            return True

        def _apply_ctx(row, ctx):
            if ctx.get("error"):
                status_var.set(ctx["error"])
                detail.configure(state="normal")
                detail.delete("1.0", "end")
                detail.insert("end", f"Error: {ctx['error']}\n")
                detail.configure(state="disabled")
                return
            st["ctx"] = ctx
            st["tick_idx"] = 0
            _sync_scrub(0)
            frames = _replay_frames(ctx)
            scrub.configure(to=max(0, len(frames) - 1))
            _redraw(replay_active=False)
            walk = ctx.get("walk") or {}
            detail.configure(state="normal")
            detail.delete("1.0", "end")
            detail.insert("end", f"{row.get('trade_id')}  batch #{row.get('batch')}\n")
            detail.insert("end", f"{row.get('acct_num')}  {row.get('phase_key')}  "
                                 f"{ctx.get('direction', '').upper()}\n\n")
            detail.insert("end", f"Entry  {strategy_tester_chart.fmt_axis_time(ctx['entry_ts'])} "
                                 f"@ {ctx['entry_price']:.2f}  ({ctx.get('walk_mode')} fill)\n")
            if ctx.get("exit_ts"):
                detail.insert("end", f"Exit   @ {ctx.get('exit_price')}  "
                                     f"→ {str(ctx.get('outcome', '')).upper()}\n")
            detail.insert("end", f"TP {ctx.get('tp_level')}  SL {ctx.get('sl_level')}\n")
            detail.insert("end", f"MFE {walk.get('mfe_points', '—')}  "
                                 f"MAE {walk.get('mae_points', '—')} pts\n")
            detail.insert("end", f"{ctx.get('frame_count', len(ctx.get('replay_frames') or [])):,} replay frames · "
                                 f"{ctx.get('tick_count', 0):,} raw ticks · "
                                 f"{len(ctx.get('candles') or [])} M1 bars\n")
            detail.configure(state="disabled")
            status_var.set(
                f"{ctx.get('symbol', '').upper()} · {ctx.get('walk_mode')} · "
                f"{ctx.get('tick_count', 0):,} ticks")

        def _on_select(_evt=None):
            self._stester_stop_play()
            st["playing"] = False
            play_lbl.set("▶ Play chart")
            sel = tree.selection()
            if not sel:
                return
            row = row_map.get(sel[0])
            if row and _highlight_on_chart(row):
                return
            if row:
                _show_trade(row)

        def _on_chart_configure(_e):
            if st.get("playing"):
                return
            _redraw(replay_active=False)

        tree.bind("<<TreeviewSelect>>", _on_select)
        chart.bind("<Configure>", _on_chart_configure)

        def _on_scrub(v):
            if st.get("_scrub_sync"):
                return
            self._stester_stop_play()
            st["playing"] = False
            play_lbl.set("▶ Play chart")
            frames = _replay_frames(st.get("ctx") or {})
            if not frames:
                return
            st["tick_idx"] = max(0, min(len(frames) - 1, int(float(v))))
            _redraw(replay_active=False)

        scrub = tk.Scale(ctrl, from_=0, to=0, orient="horizontal", variable=tick_var,
                         command=_on_scrub, bg="#0B1426", fg="#E2E8F0",
                         troughcolor="#1E293B", highlightthickness=0,
                         length=400, label="Chart replay")
        scrub.pack(side="left", fill="x", expand=True, padx=(8, 12))

        def _restore_after_play():
            saved = st.pop("_play_saved_ctx", None)
            if saved is not None:
                st["ctx"] = saved
                st["tick_idx"] = 0
                _sync_scrub(0)
                scrub.configure(to=max(0, len(_replay_frames(saved)) - 1))
                _redraw(replay_active=False)

        def _toggle_play():
            if st["playing"]:
                self._stester_stop_play()
                st["playing"] = False
                play_lbl.set("▶ Play chart")
                _restore_after_play()
                self._stester_invalidate_play_cache(chart)
                _redraw(replay_active=False)
                return

            pctx = st.get("period_ctx")
            cur_ctx = st.get("ctx") or {}
            use_period = bool(
                pctx and not pctx.get("error") and _replay_frames(pctx)
                and not cur_ctx.get("static_mode"))
            if use_period:
                st["_play_saved_ctx"] = st.get("ctx")
                st["ctx"] = pctx
                scrub.configure(to=max(0, len(_replay_frames(pctx)) - 1))
            ctx = st.get("ctx") or {}
            frames = _replay_frames(ctx)
            if not frames:
                status_var.set("Run Backtest first — no replay frames loaded")
                return
            st["tick_idx"] = 0
            _sync_scrub(0)
            st["playing"] = True
            st["_last_scrub_bar"] = -1
            st["_status_tick"] = 0
            self._stester_invalidate_play_cache(chart)
            play_lbl.set("⏸ Pause")

            def _step():
                if not st["playing"] or not win.winfo_exists():
                    return
                frames_l = _replay_frames(st.get("ctx") or {})
                if not frames_l:
                    return
                idx = st["tick_idx"]
                fr = frames_l[idx]
                cur_bi = int(fr.get("bar_i") or 0)
                cur_fr = float(fr.get("frac") or 0)
                _redraw(replay_active=True)
                ts = int(fr["ts"])
                px = float(fr.get("mid") or 0)
                if cur_bi != st.get("_last_scrub_bar"):
                    st["_last_scrub_bar"] = cur_bi
                    _sync_scrub(idx)
                ctx_l = st.get("ctx") or {}
                past_entry = False
                past_exit = False
                tick_n = st.get("_status_tick", 0) + 1
                st["_status_tick"] = tick_n
                update_status = (tick_n % 6 == 0 or cur_fr >= 0.99
                                 or idx >= len(frames_l) - 1)
                if ctx_l.get("period_mode"):
                    active = strategy_tester_chart.active_trade_at_frame(
                        ctx_l.get("trades") or [], cur_bi, cur_fr)
                    done = sum(
                        1 for tr in (ctx_l.get("trades") or [])
                        if tr.get("exit_ts") and strategy_tester_chart.frame_reached(
                            cur_bi, cur_fr,
                            int(tr.get("exit_bar") or 0),
                            float(tr.get("exit_frac") or 1.0)))
                    n_tr = len(ctx_l.get("trades") or [])
                    if update_status:
                        if active:
                            side = str(active.get("direction") or "").upper()
                            tid = str(active.get("trade_id") or "")[-10:]
                            status_var.set(
                                f"▶ TRADE OPEN {side} {tid} · "
                                f"{strategy_tester_chart.fmt_axis_time(ts)} @ {px:.2f} · "
                                f"{done}/{n_tr} closed")
                        else:
                            status_var.set(
                                f"▶ bar {cur_bi + 1}/{len(ctx_l.get('candles') or [])} · "
                                f"{done}/{n_tr} closed · "
                                f"{strategy_tester_chart.fmt_axis_time(ts)}")
                    past_entry = active is not None
                else:
                    et = int(ctx_l.get("entry_ts") or 0)
                    xt = int(ctx_l.get("exit_ts") or 0)
                    e_bar = int(ctx_l.get("entry_bar") or 0)
                    x_bar_i = int(ctx_l.get("exit_bar") or 0)
                    e_frac = float(ctx_l.get("entry_frac") or 0.08)
                    x_frac = float(ctx_l.get("exit_frac") or 0.92)
                    past_entry = cur_bi > e_bar or (cur_bi == e_bar and cur_fr >= e_frac)
                    past_exit = (xt and (
                        cur_bi > x_bar_i or (cur_bi == x_bar_i and cur_fr >= x_frac)))
                    if update_status:
                        if past_exit and xt:
                            status_var.set(
                                f"▶ EXIT {str(ctx_l.get('outcome', '')).upper()} @ "
                                f"{float(ctx_l.get('exit_price') or px):.2f}")
                        elif past_entry and et and not past_exit:
                            status_var.set(
                                f"▶ TRADE OPEN · {strategy_tester_chart.fmt_axis_time(ts)} "
                                f"@ {px:.2f} · watching TP/SL…")
                        elif et and abs(ts - et) < 120:
                            status_var.set(f"▶ ENTRY @ {px:.2f}")
                        else:
                            status_var.set(
                                f"▶ bar {cur_bi + 1} · "
                                f"{strategy_tester_chart.fmt_axis_time(ts)}")
                if st["tick_idx"] >= len(frames_l) - 1:
                    st["playing"] = False
                    play_lbl.set("▶ Play chart")
                    _restore_after_play()
                    self._stester_invalidate_play_cache(chart)
                    _redraw(replay_active=False)
                    status_var.set("Replay complete — click Play to watch again")
                    return
                st["tick_idx"] = min(len(frames_l) - 1, st["tick_idx"] + 1)
                delay_ms = 30 if ctx_l.get("static_mode") else (
                    50 if (past_entry and not past_exit) else 35)
                self._stester_play_after = win.after(delay_ms, _step)

            _step()

        tk.Button(ctrl, textvariable=play_lbl, command=_toggle_play,
                  bg="#1A2332", fg="#E2E8F0", relief="flat",
                  font=("Segoe UI", 10), cursor="hand2").pack(side="left", padx=(8, 4))

        def _load_trades():
            label = period_var.get()
            period_key = _label_to_key.get(label, "30d")
            days = trade_simulator.HISTORICAL_PERIODS.get(period_key, 30)
            status_var.set("Running backtest…")
            stats_var.set("")
            self._stester_stop_play()

            def _worker():
                self._ensure_mt5_for_signals()
                plans = self._collect_tomorrow_trade_plans()
                log = lambda m: self._ai_trace("SIM", m)
                if period_key == "live":
                    brief = trade_simulator.step_batch_engine(
                        plans, "ustech", log_fn=log)
                    m1, _, _ = trade_simulator.fetch_m1_m5("ustech")
                    rows = trade_simulator.get_simulated_trade_history(
                        include_open=True, m1_bars=m1)
                    if brief.get("error") and not rows:
                        self.root.after(0, lambda: _populate([], brief))
                    else:
                        self.root.after(0, lambda: _populate(rows, brief if not rows else None))
                else:
                    result = trade_simulator.run_historical_backtest(
                        plans, "ustech", days_back=days, log_fn=log)
                    if result.get("error"):
                        self.root.after(0, lambda: _populate([], result))
                    else:
                        self.root.after(0, lambda: _populate(
                            result.get("trades") or [], result))

            def _populate(rows, brief):
                st["rows"] = rows
                for iid in tree.get_children():
                    tree.delete(iid)
                row_map.clear()
                wins = losses = 0
                for r in rows:
                    acct = str(r.get("acct_num") or "?")[-8:]
                    pnl = r.get("net_profit")
                    tag = "win" if r.get("won") else "loss" if r.get("lost") else "open"
                    if tag == "win":
                        wins += 1
                    elif tag == "loss":
                        losses += 1
                    iid = tree.insert("", "end", values=(
                        r.get("batch", ""),
                        acct,
                        r.get("phase_key", ""),
                        str(r.get("side", "")).upper(),
                        r.get("entry_time_str", ""),
                        r.get("entry_price", ""),
                        str(r.get("outcome", "")).upper() if r.get("outcome") else "—",
                        f"{pnl:+.1f}" if pnl is not None else "—",
                    ), tags=(tag,))
                    row_map[iid] = r
                tree.tag_configure("win", foreground="#4ADE80")
                tree.tag_configure("loss", foreground="#F87171")
                tree.tag_configure("open", foreground="#60A5FA")

                if brief and brief.get("error"):
                    status_var.set(brief["error"])
                    stats_var.set("")
                elif brief and brief.get("stats"):
                    s = brief["stats"]
                    status_var.set(
                        f"{s.get('period_label')} · {s.get('n_trades')} trades · "
                        f"every {s.get('interval_min')}min · {s.get('walk_mode')} walk")
                    stats_var.set(
                        f"{s.get('from_str')} → {s.get('to_str')}  |  "
                        f"TP {s.get('tp')}  SL {s.get('sl')}  "
                        f"timeout {s.get('timeout')}  |  "
                        f"win rate {s.get('win_rate', 0):.0%}  |  "
                        f"Σ sim P/L {s.get('total_pnl_pts', 0):+.0f} pts  |  "
                        f"{s.get('n_plans')} plan(s)  "
                        f"(stride {s.get('stride', 1)})")
                else:
                    status_var.set(f"{len(rows)} live sim trade(s) — ▶ Play chart for period replay")

                if rows:
                    if focus_trade_id:
                        st["focus_trade_id"] = focus_trade_id
                    st["period_ctx"] = None
                    st["ctx"] = None
                    _load_period(rows, brief)
                elif focus_trade_id:
                    for iid, r in row_map.items():
                        if r.get("trade_id") == focus_trade_id:
                            tree.selection_set(iid)
                            tree.focus(iid)
                            _on_select()
                            break

            threading.Thread(target=_worker, name="stester-load", daemon=True).start()

        def _focus_trade(tid):
            for iid, r in row_map.items():
                if r.get("trade_id") == tid:
                    tree.selection_set(iid)
                    tree.focus(iid)
                    _on_select()
                    break

        self._stester_focus_trade = _focus_trade

        tk.Button(hdr, text="  Run Backtest  ", command=_load_trades,
                  bg="#1D4ED8", fg="#F8FAFC", relief="flat",
                  font=("Segoe UI", 10, "bold"), cursor="hand2").pack(side="right", padx=(8, 0))

        def _on_close():
            self._stester_stop_play()
            self._strategy_tester_win = None
            self._stester_focus_trade = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", _on_close)

    def _open_ai_monitor(self):
        """Open (or focus) the real-time AI Decision Monitor window."""
        if self._ai_monitor_win:
            try:
                if self._ai_monitor_win.winfo_exists():
                    self._ai_monitor_win.lift()
                    self._ai_monitor_win.focus_force()
                    return
            except Exception:
                pass

        BG = "#070D1A"
        PANEL = "#0B1426"
        BORDER = "#1B2A45"
        FF = self.AI_MONITOR_FONT
        LF = self.AI_MONITOR_LOG_FONT

        win = tk.Toplevel(self.root)
        win.title("AI Decision Monitor")
        win.geometry(self.AI_MONITOR_DEFAULT_GEOMETRY)
        win.configure(bg=BG)
        win.minsize(900, 520)

        # ── Header ──
        header = tk.Frame(win, bg=BG)
        header.pack(fill="x", padx=18, pady=(14, 10))
        tk.Label(header, text="🧠", bg=BG, fg="#00D4FF",
                 font=(FF, 18)).pack(side="left")
        title_block = tk.Frame(header, bg=BG)
        title_block.pack(side="left", padx=(8, 0))
        tk.Label(title_block, text="AI Decision Monitor", bg=BG, fg="#F1F5F9",
                 font=(FF, self.AI_MONITOR_TITLE_SIZE, "bold")).pack(anchor="w")
        tk.Label(title_block, text="Live reasoning · ML · indicators · trades",
                 bg=BG, fg="#64748B",
                 font=(FF, self.AI_MONITOR_BTN_SIZE)).pack(anchor="w")

        btn_bar = tk.Frame(header, bg=BG)
        btn_bar.pack(side="right")

        self._ai_autoscroll_var = tk.BooleanVar(value=True)
        tk.Checkbutton(btn_bar, text="Auto-scroll", variable=self._ai_autoscroll_var,
                       bg=BG, fg="#94A3B8", selectcolor=PANEL,
                       activebackground=BG, activeforeground="#E2E8F0",
                       font=(FF, self.AI_MONITOR_BTN_SIZE), relief="flat",
                       highlightthickness=0).pack(side="right", padx=(10, 0))

        def _font_delta(delta):
            self.AI_MONITOR_LOG_SIZE = max(9, min(16, self.AI_MONITOR_LOG_SIZE + delta))
            self.AI_MONITOR_CARD_SIZE = max(9, min(14, self.AI_MONITOR_CARD_SIZE + delta))
            self.AI_MONITOR_BADGE_SIZE = max(8, min(13, self.AI_MONITOR_BADGE_SIZE + delta))
            txt = self._ai_monitor_text
            if txt:
                txt.configure(font=(LF, self.AI_MONITOR_LOG_SIZE))
                for cat in self.AI_TRACE_COLORS:
                    txt.tag_configure(f"badge_{cat}",
                                      font=(LF, self.AI_MONITOR_BADGE_SIZE, "bold"))
            self._ai_monitor_rerender()

        tk.Button(btn_bar, text=" A− ", command=lambda: _font_delta(-1),
                  bg=PANEL, fg="#CBD5E1", activebackground=BORDER,
                  font=(FF, self.AI_MONITOR_BTN_SIZE, "bold"), relief="flat",
                  cursor="hand2").pack(side="right", padx=(6, 0))
        tk.Button(btn_bar, text=" A+ ", command=lambda: _font_delta(+1),
                  bg=PANEL, fg="#CBD5E1", activebackground=BORDER,
                  font=(FF, self.AI_MONITOR_BTN_SIZE, "bold"), relief="flat",
                  cursor="hand2").pack(side="right", padx=(6, 0))
        tk.Button(btn_bar, text="  Clear  ", command=self._clear_ai_monitor,
                  bg=PANEL, fg="#E2E8F0", activebackground=BORDER,
                  activeforeground="#FFFFFF", relief="flat",
                  font=(FF, self.AI_MONITOR_BTN_SIZE), cursor="hand2").pack(side="right", padx=(6, 0))
        tk.Button(btn_bar, text="  Run Diagnostics  ", command=self._run_ai_diagnostics,
                  bg="#0E2A26", fg="#2dd4bf", activebackground="#134E4A",
                  activeforeground="#5EEAD4", relief="flat",
                  font=(FF, self.AI_MONITOR_BTN_SIZE, "bold"), cursor="hand2").pack(
            side="right", padx=(0, 6))
        tk.Label(btn_bar, text="auto every 60s", bg=BG, fg="#4ADE80",
                 font=(FF, self.AI_MONITOR_BTN_SIZE - 1)).pack(side="right", padx=(0, 8))

        # ── Status cards (two rows — easier to read at larger font) ──
        self._ai_status_vars = {
            "model":      tk.StringVar(value="Waiting for ML model…"),
            "signal":     tk.StringVar(value="No signal yet"),
            "setup":      tk.StringVar(value="Signal strength not evaluated"),
            "learn":      tk.StringVar(value="No verified predictions yet"),
            "tomorrow":   tk.StringVar(value="No tomorrow plans queued"),
            "insight":    tk.StringVar(value="No dashboard insight yet"),
            "last_event": tk.StringVar(value="—"),
            "events":     tk.StringVar(value=f"{len(self._ai_events)} events"),
        }
        cards_outer = tk.Frame(win, bg=BG)
        cards_outer.pack(fill="x", padx=18, pady=(0, 12))

        row1_defs = [
            ("ML MODEL",       "model",    "#4ADE80"),
            ("LAST AI SIGNAL", "signal",   "#00D4FF"),
            ("SIGNAL STRENGTH", "setup",    "#A78BFA"),
            ("TOMORROW SIM",   "tomorrow", "#C084FC"),
        ]
        row2_defs = [
            ("SELF-LEARNING",      "learn",      "#FB923C"),
            ("DASHBOARD ADVISORY", "insight",    "#FBBF24"),
            ("LAST TRADE / ALERT", "last_event", "#F87171"),
        ]

        def _make_card(parent, caption, key, accent, colspan=1):
            card = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER,
                            highlightthickness=1)
            card.grid(row=parent._grid_row, column=parent._grid_col,
                      sticky="nsew", padx=(0 if parent._grid_col == 0 else 8, 0),
                      columnspan=colspan)
            parent._grid_col += colspan
            tk.Label(card, text=caption, bg=PANEL, fg=accent,
                     font=(FF, self.AI_MONITOR_CAPTION_SIZE, "bold"),
                     anchor="w").pack(fill="x", padx=12, pady=(10, 2))
            tk.Label(card, textvariable=self._ai_status_vars[key], bg=PANEL,
                     fg="#E2E8F0", font=(LF, self.AI_MONITOR_CARD_SIZE),
                     anchor="w", justify="left",
                     wraplength=self.AI_MONITOR_CARD_WRAP).pack(
                fill="x", padx=12, pady=(0, 12))

        for row_idx, defs in enumerate((row1_defs, row2_defs)):
            row_frame = tk.Frame(cards_outer, bg=BG)
            row_frame.pack(fill="x", pady=(0 if row_idx == 0 else 8, 0))
            row_frame._grid_row = 0
            row_frame._grid_col = 0
            n = len(defs)
            for i, (caption, key, accent) in enumerate(defs):
                row_frame.grid_columnconfigure(i, weight=1)
            for caption, key, accent in defs:
                _make_card(row_frame, caption, key, accent)

        # Second row: insight + last_event span wider
        cards_outer.grid_columnconfigure(0, weight=1)

        # ── Category filters (legend doubles as show/hide toggles) ──
        filter_bar = tk.Frame(win, bg=BG)
        filter_bar.pack(fill="x", padx=18, pady=(0, 8))
        tk.Label(filter_bar, text="Show:", bg=BG, fg="#64748B",
                 font=(FF, self.AI_MONITOR_BTN_SIZE)).pack(side="left", padx=(0, 8))

        self._ai_monitor_filter_vars = {}
        # DIAG off by default — it was flooding the log every 60s
        _default_on = {c: (c != "DIAG") for c in self.AI_TRACE_COLORS}

        def _on_filter_toggle():
            self._ai_monitor_rerender()

        for cat, color in self.AI_TRACE_COLORS.items():
            var = tk.BooleanVar(value=_default_on.get(cat, True))
            self._ai_monitor_filter_vars[cat] = var
            tk.Checkbutton(
                filter_bar, text=f" {cat} ", variable=var,
                command=_on_filter_toggle,
                bg=color, fg="#0A0F1A", selectcolor=color,
                activebackground=color, activeforeground="#0A0F1A",
                font=(LF, self.AI_MONITOR_BADGE_SIZE, "bold"),
                relief="flat", highlightthickness=0, padx=4, pady=2,
            ).pack(side="left", padx=(0, 6))

        tk.Label(filter_bar, textvariable=self._ai_status_vars["events"], bg=BG,
                 fg="#64748B", font=(FF, self.AI_MONITOR_BTN_SIZE)).pack(side="right")

        # ── Trace area ──
        body = tk.Frame(win, bg=BORDER, padx=1, pady=1)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        inner = tk.Frame(body, bg=PANEL)
        inner.pack(fill="both", expand=True)
        scroll = tk.Scrollbar(inner, troughcolor=PANEL, width=14)
        scroll.pack(side="right", fill="y")
        txt = tk.Text(
            inner, bg="#0A1220", fg="#E2E8F0",
            font=(LF, self.AI_MONITOR_LOG_SIZE),
            relief="flat", wrap="word", state="disabled",
            yscrollcommand=scroll.set, insertbackground="#E2E8F0",
            spacing1=4, spacing3=6, padx=14, pady=10,
            selectbackground="#1E3A5F", selectforeground="#FFFFFF",
        )
        txt.pack(side="left", fill="both", expand=True)
        scroll.config(command=txt.yview)

        txt.tag_configure("dim", foreground="#64748B",
                          font=(LF, self.AI_MONITOR_LOG_SIZE))
        for cat, color in self.AI_TRACE_COLORS.items():
            txt.tag_configure(
                f"badge_{cat}", background=color, foreground="#0A0F1A",
                font=(LF, self.AI_MONITOR_BADGE_SIZE, "bold"),
                lmargin1=4, lmargin2=4, rmargin=4,
            )
            txt.tag_configure(f"msg_{cat}", foreground="#E2E8F0",
                              font=(LF, self.AI_MONITOR_LOG_SIZE))
        txt.tag_configure("msg_WARN", foreground="#FCA5A5",
                          font=(LF, self.AI_MONITOR_LOG_SIZE))
        txt.tag_configure("msg_SIGNAL", foreground="#7DD3FC",
                          font=(LF, self.AI_MONITOR_LOG_SIZE))
        txt.tag_configure("msg_TRADE", foreground="#6EE7B7",
                          font=(LF, self.AI_MONITOR_LOG_SIZE))
        txt.tag_configure("msg_LEARN", foreground="#FDBA74",
                          font=(LF, self.AI_MONITOR_LOG_SIZE))
        txt.tag_configure("msg_ML", foreground="#86EFAC",
                          font=(LF, self.AI_MONITOR_LOG_SIZE))
        txt.tag_configure("msg_SIM", foreground="#E9D5FF",
                          font=(LF, self.AI_MONITOR_LOG_SIZE))

        self._ai_monitor_win = win
        self._ai_monitor_text = txt

        # Replay everything recorded so far (respecting filters)
        try:
            self._ai_monitor_rerender()
            for ts, cat, msg in list(self._ai_events):
                self._ai_monitor_update_status(cat, msg)
            txt.see("end")
        except Exception:
            pass

        win.after(500, self._run_ai_diagnostics)

    def _clear_ai_monitor(self):
        self._ai_events.clear()
        txt = self._ai_monitor_text
        try:
            if txt and self._ai_monitor_win and self._ai_monitor_win.winfo_exists():
                txt.configure(state="normal")
                txt.delete("1.0", "end")
                txt.configure(state="disabled")
                if getattr(self, "_ai_status_vars", None):
                    self._ai_status_vars["events"].set("0 events")
        except Exception:
            pass

    # ── Layer 2: dashboard trade-history ML insights ──────────────────

    _ML_INSIGHTS_TTL = 300  # seconds
    _ml_insights_cache = None  # {"ts": float, "data": dict}

    def _get_dashboard_ml_insights(self):
        """Fetch portfolio/trade-history ML insights from the dashboard API.

        Cached for 5 minutes (the server worker refreshes every 2–5 min).
        Returns the insights dict or None on any failure — the AI works
        without it, just with one less layer of intelligence.
        """
        now = time.time()
        cached = self.__class__._ml_insights_cache
        if cached and now - cached["ts"] < self._ML_INSIGHTS_TTL:
            return cached["data"]
        try:
            dashboard_url = self.url_entry.get().strip().rstrip('/')
            email = self.client_email_entry.get().strip().lower()
            if not dashboard_url or not email:
                return None
            resp = requests.get(
                f"{dashboard_url}/api/client/ml_insights",
                params={"email": email}, timeout=15,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data.get("status") != "success":
                return None
            self.__class__._ml_insights_cache = {"ts": now, "data": data}
            return data
        except Exception:
            return None

    # ── The AI: layered ML/DL + portfolio intelligence ─────────────────

    # Final decision = weighted BLEND of both co-deciders (the vote always
    # counts — it is never discarded, even when the ML is very confident).
    # The ML also LEARNS from the vote: every voter signal + the vote
    # consensus are training features (see ml_direction.make_features).
    ML_BLEND_WEIGHT = 0.68      # ML/DL primary; rises in volatile tape
    VOTE_BLEND_WEIGHT = 0.32
    ML_BLEND_WEIGHT_VOLATILE = 0.78
    VOTE_BLEND_WEIGHT_VOLATILE = 0.22
    BLEND_DEADZONE = 0.10
    BLEND_DEADZONE_VOLATILE = 0.07  # tighter deadzone when vol is high

    def _get_signal_direction(self, mt5_symbol, timeframe=None, num_indicators=None):
        """Decide the trade direction — the companion's own signal is FINAL.

        Two co-deciders, BOTH always counted in one blended score:
        1. Local ML/DL ensemble (gradient boosting + deep neural net), as a
           signed conviction in [-1, +1]: (p_up - 0.5) x 2. The model's
           features INCLUDE every voter signal and the vote consensus, so
           the vote also shapes the ML's own opinion.
        2. Indicator vote over ALL 25 indicators, as a signed margin in
           [-1, +1]: (buy - sell) / votes_cast.

        blend = 0.6 x ML + 0.4 x vote. |blend| >= 0.10 decides; smaller
        values fall to data-only tie-breaks (price momentum). If one side is
        unavailable the other decides alone (ML gated on confidence).

        Dashboard trade-history ML insights are DISPLAY ONLY: they annotate
        the log/monitor but play NO part in the trading decision.

        Returns "buy"/"sell", or None when no data-driven decision exists —
        there is NO random fallback anywhere; callers must skip the trade.
        """
        symbol = str(mt5_symbol or "ustech")

        # Display-only input — dashboard trade-history ML (NEVER used to decide)
        insights = self._get_dashboard_ml_insights()
        mkt = (insights or {}).get("market") or {}
        port = (insights or {}).get("portfolio") or {}
        dash_bias = str(mkt.get("bias") or "").lower()
        dash_dir = dash_bias if dash_bias in ("buy", "sell") else None
        dash_conf = float(mkt.get("confidence") or 0.0)
        self._ai_trace("INSIGHT",
                       f"dashboard trade-history ML: bias={dash_bias or 'none'} "
                       f"conf={dash_conf:.2f} n_trades={port.get('n_trades')} "
                       f"(display only — plays no part in the decision)")

        # Trend + reversal legs → learning-weighted blend (no suppression).
        trend = self._get_trend_direction(symbol, timeframe)
        blend = self._compute_trend_reversal_blend(symbol, max_age_sec=0)
        legs = blend.get("legs") or {}
        w = blend.get("weights") or {}
        if trend:
            self._ai_trace("SIGNAL",
                           f"{symbol}: trend {trend.upper()} | "
                           f"trend leg B{legs.get('trend_buy_pct')}/S{legs.get('trend_sell_pct')} · "
                           f"reversal leg B{legs.get('rev_buy_pct')}/S{legs.get('rev_sell_pct')} · "
                           f"blend B{blend.get('buy_pct')}/S{blend.get('sell_pct')} "
                           f"({'consensus' if blend.get('consensus') else 'diverge'})")
        else:
            self._ai_trace("SIGNAL", f"{symbol}: no clear trend — raw blend only "
                                     f"B{blend.get('buy_pct')}/S{blend.get('sell_pct')}")

        if prediction_tracker is not None and w.get("source") == "learned":
            self._ai_trace("LEARN",
                           f"{symbol}: regime weights wT={blend.get('w_trend', 0):.0%} "
                           f"(acc {w.get('trend_acc', 0):.0%} n={w.get('n_trend', 0)}) "
                           f"wR={blend.get('w_reversal', 0):.0%} "
                           f"(acc {w.get('reversal_acc', 0):.0%} n={w.get('n_reversal', 0)})")

        ml = blend.get("ml") or {}
        if (ml or {}).get("ready"):
            ml_dir = ml.get("direction")
            ml_conf = float(ml.get("confidence") or 0.0)
            ml_lean = str(ml.get("lean") or "").lower()
            wf0 = ml.get("walk_forward") or {}
            ct = " counter-trend" if ml.get("counter_trend") else ""
            self._ai_trace("ML",
                           f"{symbol}: ens={ml.get('probability')} conf={ml_conf:.2f} "
                           f"lean={ml_lean.upper()}{ct} dir={ml_dir} | "
                           f"wf_acc={wf0.get('accuracy')}")

        vote = blend.get("vote")
        if vote:
            vote_dir = vote.get("direction")
            tally = (vote_dir.upper() if vote_dir else "TIE")
            self._ai_trace("VOTE", f"{vote['symbol']}: {vote['detail']} → {tally}")
            self.root.after(0, lambda d=vote["detail"], t=tally:
                self.log(f"   📊 Indicator vote: {d} → {t}"))

        decision = blend.get("decision")
        if not decision:
            if not blend.get("consensus"):
                self._ai_trace("WARN",
                               f"{symbol}: trend/reversal diverge — waiting for "
                               f"learning blend to converge "
                               f"(margin {blend.get('blend_margin')}%)")
            else:
                self._ai_trace("WARN", f"{symbol}: blend has no clear direction")
            self.root.after(0, lambda: self.log(
                "   📊 AI signal: NO SIGNAL — trend/reversal blend not ready", "WARN"))
            return None

        how = (f"learn blend wT={float(blend.get('w_trend') or 0):.0%} "
               f"wR={float(blend.get('w_reversal') or 0):.0%} → "
               f"B{blend.get('buy_pct')}/S{blend.get('sell_pct')}")
        if dash_dir is None:
            note = "no dashboard bias"
        elif dash_dir == decision:
            note = f"dashboard ML agrees (conf {dash_conf:.2f}, display only)"
        else:
            note = f"dashboard ML disagrees (conf {dash_conf:.2f}, display only)"
        self._ai_trace("SIGNAL", f"{symbol}: {decision.upper()} — {how} ({note})")
        self.root.after(0, lambda d=decision, h=how, n=note:
            self.log(f"   🧠 AI signal → {d.upper()} [{h}, {n}]"))
        return decision

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
