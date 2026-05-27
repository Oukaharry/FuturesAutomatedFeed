from typing import Any
from flask import Flask, render_template, jsonify, request, redirect, url_for, g
from flask_compress import Compress
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import threading
import json
import os
import sys
import logging
import time
import errno
import signal

# Add project root to sys.path to import config and dashboard modules properly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from functools import wraps
import secrets
import hashlib
import re
from datetime import datetime, timedelta
from dashboard.financial_overview import calculate_propfirm_overview, get_payouts_history, get_portfolio_growth_data, get_payouts_growth_data, get_cumulative_deposits, get_cumulative_trading_profit, get_cumulative_fees_data, get_cumulative_hedge_data, get_cumulative_farming_data, calculate_trader_stats, parse_date, get_cached_clients_dataset, calculate_all_financials, get_client_performance_stats

from config.hierarchy import (
    SYSTEM_HIERARCHY, add_admin, add_trader, add_client, 
    update_admin_details, update_trader_details, update_client_details, update_client_category,
    get_client_by_email, get_user_by_email, get_client_profile,
    remove_admin, remove_trader, remove_client,
    move_client, move_trader,
    rename_admin, rename_trader, rename_client,
    reassign_client_trader, save_hierarchy
)

# Import database module for secure storage
from dashboard.database import (
    init_database, check_and_repair_database,
    get_connection,
    validate_api_key, generate_api_key, list_api_keys, revoke_api_key,
    verify_admin_password, set_admin_password, admin_password_exists, copy_admin_password_row,
    save_client_data, get_client_data, get_all_clients, get_clients_count, update_client_field, delete_client_data,
    log_action, get_audit_log,
    create_session, validate_session, delete_session,
    delete_other_sessions_for_user, list_sessions_public_for_user,
    create_user, verify_user_password, verify_client_login, update_user_password,
    delete_user_credential, update_user_email, rename_user_credential, rename_client_in_db,
    get_user, list_users, deactivate_user, reset_user_password, user_exists,
    record_login_attempt, is_account_locked,
    find_user_by_identifier, verify_user_by_identifier,
    # History management
    save_client_data_with_history, get_data_history, get_data_version,
    rollback_to_version, compare_versions, get_latest_version,
    # KYC link management
    add_kyc_link, remove_kyc_link, get_kyc_linked_clients, get_kyc_primary_for,
    get_all_kyc_accounts, get_all_kyc_links, is_kyc_primary
)
from dashboard.notes_service import (
    get_client_notes, save_client_note, delete_client_note
)
from dashboard.utils.trade_matcher import UnifiedTradeMatcher

# Firms hidden from BEF admin (normalised: lowercase, no spaces)
BEF_HIDDEN_FIRMS = {'lucid', 'apex', 'tradeday', 'toponefutures'}

# Admin tracker: max simultaneous active evaluation rows per normalized prop firm key.
ADMIN_PROP_MAX_ACTIVE_ACCOUNTS = {
    'mffu': 3,
    'tradeday': 3,
    'alphafutures': 3,
    'apex': 10,
}
ADMIN_PROP_MAX_ACTIVE_DEFAULT = 5
ADMIN_PROP_DISPLAY_NAME = {
    'mffu': 'My Funded Futures',
    'tradeday': 'TradeDay',
    'alphafutures': 'Alpha Futures',
    'apex': 'Apex Trader Funding',
    'toponefutures': 'Top One Futures',
}

# QA-gated: trader daily summary item 4 — any prop firm with payouts-eligible count >= 1 (super_admin resolve)
QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE = 'Daily summary: payouts eligible >=1-QA'
# Older scan key; still honored when reading qa_resolutions so existing clears keep working.
QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE_LEGACY = 'MFF payouts eligible >1-QA'

# Omitted from client-sheet "Data Quality Issues" and trader dashboard aggregates; still stored on scans,
# listed on admin tracker (synthetic rows), and surfaced in quality QA modals / super-admin APIs.
_QUALITY_CHECKS_HIDDEN_FROM_TRADER_CLIENT_VIEWS = frozenset({
    QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE,
    QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE_LEGACY,
    'No evaluations',
})


def _issues_for_trader_client_quality_views(issues):
    skip = _QUALITY_CHECKS_HIDDEN_FROM_TRADER_CLIENT_VIEWS | {'Scan error'}
    return [i for i in (issues or []) if i.get('check') not in skip]


_QUALITY_SEVERITY_WEIGHT = {'critical': 20, 'high': 10, 'medium': 5, 'low': 2, 'warning': 3, 'info': 0}


def _trader_ranking_health_metrics(issues):
    """(total_issues, health_score) for trader leaderboards and scorecards — excludes payout QA and scan errors."""
    vis = _issues_for_trader_client_quality_views(issues)
    if not vis:
        return 0, 100.0
    deduction = sum(_QUALITY_SEVERITY_WEIGHT.get(i.get('severity', 'low'), 2) for i in vis)
    return len(vis), max(0.0, round(100.0 - deduction, 1))


def _quality_scan_row_for_trader_client_quality_api(scan_row):
    """Recompute issues, total_issues, and health_score for trader-facing quality UIs."""
    out = dict(scan_row)
    out['issues'] = _issues_for_trader_client_quality_views(scan_row.get('issues'))
    out['total_issues'], out['health_score'] = _trader_ranking_health_metrics(scan_row.get('issues'))
    return out


def _sync_quality_issue_tracking(scan_date: str, results: list):
    """Record scan-day baseline + resolutions for trader clearance speed rankings."""
    if not scan_date or not results:
        return
    try:
        from dashboard.database import (
            record_quality_scan_anchor,
            upsert_quality_issue_baseline,
            mark_quality_issue_resolved,
        )
        record_quality_scan_anchor(scan_date, datetime.utcnow().isoformat())
        resolved_at = datetime.utcnow().isoformat()
        for r in results:
            client_id = r.get('client_id')
            if not client_id:
                continue
            total_issues, _ = _trader_ranking_health_metrics(r.get('issues'))
            trader = str(r.get('trader') or '')
            # Record resolution before baseline upsert so had_issues=1 from morning is preserved.
            if total_issues == 0:
                mark_quality_issue_resolved(scan_date, client_id, resolved_at)
            upsert_quality_issue_baseline(scan_date, client_id, trader, total_issues > 0)
    except Exception as e:
        logging.warning('Quality issue tracking sync failed: %s', e)


def _trader_leaderboard_sort_key(trader: str, stats: dict, clear_mins: int) -> tuple:
    """
    0 = finished clearance race (fastest time first)
    1 = clean at scan (not in race)
    2 = still fixing
    """
    name = (trader or '').lower()
    if clear_mins >= 99999:
        return (2, int(stats.get('issues', 99999)), name)
    if clear_mins < 0:
        avg = stats.get('health_sum', 0) / max(stats.get('clients', 1), 1)
        return (1, -avg, name)
    return (0, int(clear_mins), name)


def _trader_clearance_sort_key(trader_entry: dict) -> tuple:
    """Sort traders for Daily Summary Tracker cards (same tiers as leaderboard)."""
    if trader_entry.get('clearance_not_in_race'):
        mins = -1
    elif trader_entry.get('clearance_unresolved') or trader_entry.get('clearance_minutes') is None:
        mins = 99999
    else:
        mins = int(trader_entry.get('clearance_minutes'))
    stats = {
        'issues': trader_entry.get('open_issues', 0),
        'health_sum': trader_entry.get('avg_health', 100) * max(trader_entry.get('clients_scanned', 1), 1),
        'clients': trader_entry.get('clients_scanned', 1),
    }
    return _trader_leaderboard_sort_key(trader_entry.get('trader', ''), stats, int(mins))


def _trader_health_title(avg: float) -> str:
    if avg >= 95:
        return '👑 Legendary'
    if avg >= 90:
        return '⭐ Elite'
    if avg >= 80:
        return '💪 Solid'
    if avg >= 70:
        return '⚡ Warming Up'
    if avg >= 50:
        return '🔧 Needs Work'
    return '🚨 SOS'


def _trader_health_bar(avg: float) -> str:
    bar_filled = max(0, min(10, round(avg / 10)))
    return '🟩' * bar_filled + '⬛' * (10 - bar_filled)


def _trader_leaderboard_entry_lines(trader: str, clear_mins: int, stats: dict, medal: str) -> tuple:
    """Title + green health bar lines for Slack / daily summary leaderboard."""
    avg = round(stats.get('health_sum', 0) / max(stats.get('clients', 1), 1), 1)
    issues = int(stats.get('issues', 0) or 0)
    clients = int(stats.get('clients', 0) or 0)
    title = _trader_health_title(avg)
    line1 = f"{medal} **{trader}** — {title}"
    line2 = f"   {_trader_health_bar(avg)} **{avg}%** · {clients} clients · {issues} issues"
    return line1, line2


def _trader_tracker_subtitle(clear_mins: int, stats: dict) -> str:
    """Short subtitle for Daily Summary Tracker cards (no 'still fixing')."""
    avg = round(stats.get('health_sum', 0) / max(stats.get('clients', 1), 1), 1)
    issues = int(stats.get('issues', 0) or 0)
    parts = [f'{avg}% health', f'{issues} issue{"s" if issues != 1 else ""}']
    if clear_mins > 0:
        parts.append(f'cleared {_format_clearance_minutes(clear_mins)}')
    return ' · '.join(parts)


def _format_clearance_minutes(minutes: int) -> str:
    if minutes is None or minutes >= 99999:
        return ''
    if minutes < 60:
        return f'{minutes}m'
    hours, rem = divmod(minutes, 60)
    return f'{hours}h {rem}m' if rem else f'{hours}h'


# Super Admin financial aggregates: excluded client names (not tied to Daily Summary tracker lists)
_SUPER_ADMIN_STATS_EXCLUDED_KEY = 'super_admin_stats_excluded_clients'


def _get_super_admin_stats_excluded_set():
    from dashboard.database import get_setting
    try:
        raw = json.loads(get_setting(_SUPER_ADMIN_STATS_EXCLUDED_KEY) or '[]')
    except (TypeError, ValueError):
        return set[Any]()
    return {str(x).strip() for x in raw if x is not None and str(x).strip()}


def _client_excluded_from_super_admin_stats(client_id, display_name, excluded):
    if not excluded:
        return False
    for nm in (client_id, display_name):
        if nm and str(nm).strip() in excluded:
            return True
    return False


def _norm_prop_firm_max_out_key(raw):
    """Normalize Prop Firm strings for admin max-out / prop slot counts."""
    s = str(raw or '').strip().lower().replace(' ', '').replace('_', '')
    if not s:
        return ''
    if 'myfunded' in s or s.startswith('mffu') or 'mffu' in s:
        return 'mffu'
    if s in ('toponefutures', 'topone', 'tpo'):
        return 'toponefutures'
    if s in ('tradeday', 'trade-day'):
        return 'tradeday'
    if s in ('topsteprtp', 'topstep-rtp') or 'topsteprtp' in s:
        return 'topstep'
    if 'topstep' in s:
        return 'topstep'
    if 'apex' in s:
        return 'apex'
    if s == 'alphafutures' or ('alpha' in s and 'future' in s):
        return 'alphafutures'
    return s


def _admin_prop_max_active_expected(pf_key):
    return ADMIN_PROP_MAX_ACTIVE_ACCOUNTS.get(pf_key, ADMIN_PROP_MAX_ACTIVE_DEFAULT)


def _admin_prop_display_name(pf_key):
    return ADMIN_PROP_DISPLAY_NAME.get(pf_key, pf_key)


_QUALITY_MAX_OUT_EXCLUSIONS_KEY = 'quality_max_out_exclusions'

# Prop firms that can appear in max-out checks beyond ADMIN_PROP_* (normalized keys).
_MAX_OUT_EXTRA_PROP_KEYS = frozenset[str]({
    'fundednext', 'topstep', 'lucid', 'tradeify', 'fundednextplus',
})


def _prop_firm_dropdown_options_max_out():
    """{key, label} for max-out exclusion UI (keys match _norm_prop_firm_max_out_key output)."""
    keys = set(ADMIN_PROP_MAX_ACTIVE_ACCOUNTS.keys()) | set(ADMIN_PROP_DISPLAY_NAME.keys()) | set(_MAX_OUT_EXTRA_PROP_KEYS)
    opts = []
    for k in sorted(keys):
        label = ADMIN_PROP_DISPLAY_NAME.get(k)
        if not label:
            label = k[:1].upper() + k[1:] if k else k
        opts.append({'key': k, 'label': label})
    return opts


def _load_max_out_exclusions():
    """Saved triplets (admin, client_id, prop_firm_key) — skip max-out flags for that combo."""
    from dashboard.database import get_setting
    try:
        raw = json.loads(get_setting(_QUALITY_MAX_OUT_EXCLUSIONS_KEY) or '[]')
    except (TypeError, ValueError):
        raw = []
    out = []
    for i, x in enumerate(raw):
        if not isinstance(x, dict):
            continue
        admin = str(x.get('admin') or '').strip()
        cid = str(x.get('client_id') or '').strip()
        pfk = _norm_prop_firm_max_out_key(x.get('prop_firm_key') or x.get('prop_firm') or '')
        if not admin or not cid or not pfk:
            continue
        eid = str(x.get('id') or '').strip() or f'maxout-ex-{i}'
        out.append({'id': eid, 'admin': admin, 'client_id': cid, 'prop_firm_key': pfk})
    return out


def _max_out_triplet_excluded(admin_name, client_id, pf_key, exclusion_list):
    a = str(admin_name or '').strip().lower()
    cid = str(client_id or '').strip()
    pk = str(pf_key or '').strip().lower()
    if not exclusion_list:
        return False
    for ex in exclusion_list:
        if str(ex.get('admin') or '').strip().lower() == a and ex.get('client_id') == cid and ex.get('prop_firm_key') == pk:
            return True
    return False


def _max_out_row_is_live_numeric_account(ev):
    """True if this row's account id looks like funded/live (digits-only), not eval (prefix + suffix).

    Eval rows typically store firm-prefixed ids (e.g. MFFU80594). Live funded broker accounts are numeric only.
    When a trader is live on one account they are not running multiple eval slots; skip underfilled max-out in that case.

    Handles JSON numeric types (e.g. 1838060 stored as float) and comma-formatted strings.
    Funded-phase Account # in the UI is stored as Account #.1; eval Account # may be empty for live rows.
    """
    if not isinstance(ev, dict):
        return False
    _PLACEHOLDER_ACCOUNTS = {'', 'none', '-', '—', '–', 'n/a', 'na', 'tbd', 'pending'}

    def _clean_raw(val):
        s = str(val or '').strip()
        return '' if not s or s.lower() in _PLACEHOLDER_ACCOUNTS else s

    def _is_numeric_live_id(val):
        """True when value is a whole-number broker id (not prefix+suffix eval text)."""
        if val is None or val == '':
            return False
        if isinstance(val, bool):
            return False
        if isinstance(val, int):
            return val > 0
        if isinstance(val, float):
            return val.is_integer() and val > 0
        s = _clean_raw(val).replace(',', '').replace(' ', '')
        if not s:
            return False
        if s.isdigit():
            return True
        try:
            f = float(s)
            return f.is_integer() and f > 0
        except (ValueError, TypeError):
            return False

    a0_raw = ev.get('Account #')
    a1_raw = ev.get('Account #.1')
    an_raw = ev.get('Account Number')

    a0 = _clean_raw(a0_raw)
    a1 = _clean_raw(a1_raw)

    if _is_numeric_live_id(a1_raw):
        return True
    if _is_numeric_live_id(a0_raw) and not a1:
        return True
    if _is_numeric_live_id(an_raw) and not a1:
        return True
    return False


# Start Midnight Watermark Scheduler
try:
    from dashboard.scheduler import start_scheduler
    start_scheduler()
except ImportError:
    logging.warning("Could not start Watermark Scheduler (ImportError).")
except Exception as e:
    logging.error(f"Failed to start Watermark Scheduler: {e}")

from logging.handlers import RotatingFileHandler

# Initialize logging to file - WITH AUTO-FLUSH AND FSYNC
class UnbufferedFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.stream.flush()

# Path for the rolling 1-hour recent log
_RECENT_LOG_PATH = 'dashboard/server_recent.log'
_RECENT_LOG_RE = re.compile(r'^\[((?:\d{4}-\d{2}-\d{2} )?\d{2}:\d{2}:\d{2}(?:,\d+)?)\]')


def _parse_recent_log_timestamp(ts_text):
    """Parse either full datetime or time-only log stamps."""
    # Full timestamp variants.
    for fmt in ('%Y-%m-%d %H:%M:%S,%f', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(ts_text, fmt)
        except ValueError:
            pass

    # Time-only variants (new concise format): assume today, with a safe
    # midnight rollover fallback when a future time appears.
    for fmt in ('%H:%M:%S,%f', '%H:%M:%S'):
        try:
            t = datetime.strptime(ts_text, fmt).time()
            now = datetime.now()
            parsed = datetime.combine(now.date(), t)
            if parsed - now > timedelta(minutes=5):
                parsed -= timedelta(days=1)
            return parsed
        except ValueError:
            pass
    return None


class TraderStyleFormatter(logging.Formatter):
    """Compact log format to match Trader Companion readability."""

    def format(self, record):
        stamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')
        msg = record.getMessage()
        if record.levelno >= logging.WARNING:
            msg = f"[{record.levelname}] {msg}"
        return f"[{stamp}] {msg}"

def _purge_recent_log(log_path=_RECENT_LOG_PATH, hours=1):
    """Trim log_path in-place, keeping only entries from the last `hours` hours."""
    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        with open(log_path, 'r', encoding='utf-8', errors='replace') as fh:
            lines = fh.readlines()
        kept = []
        for line in lines:
            m = _RECENT_LOG_RE.match(line)
            if m:
                ts = _parse_recent_log_timestamp(m.group(1))
                if ts is None:
                    kept.append(line)  # unparseable timestamp → keep
                elif ts >= cutoff:
                    kept.append(line)
                # else: drop — older than the window
            else:
                # Continuation / blank lines: keep only if we have recent content
                if kept:
                    kept.append(line)
        with open(log_path, 'w', encoding='utf-8') as fh:
            fh.writelines(kept)
    except (FileNotFoundError, IOError):
        pass

def _start_recent_log_purger(log_path=_RECENT_LOG_PATH, interval_minutes=5):
    """Daemon thread: prune entries older than 1 hour from the recent log every 5 minutes."""
    def _worker():
        while True:
            time.sleep(interval_minutes * 60)
            _purge_recent_log(log_path)
    t = threading.Thread(target=_worker, daemon=True, name='recent-log-purger')
    t.start()

_LOG_LEVEL_NAME = str(os.getenv('DASHBOARD_LOG_LEVEL', 'INFO')).upper()
_LOG_LEVEL = getattr(logging, _LOG_LEVEL_NAME, logging.INFO)


logging.basicConfig(
    level=_LOG_LEVEL,
    force=True,  # Py3.8+ Override previous configs
    handlers=[
        logging.StreamHandler(),
        # Full log: rotating — max 10 MB, keep 3 backups (30 MB total max)
        RotatingFileHandler('dashboard/server.log', mode='a', encoding='utf-8',
                            maxBytes=10*1024*1024, backupCount=3),
        # Recent log: cleared on restart, background thread keeps it to last 1 hour only
        UnbufferedFileHandler(_RECENT_LOG_PATH, mode='w', encoding='utf-8'),
    ]
)

# Use concise, trader-app-like log lines across console and files.
_trader_style_formatter = TraderStyleFormatter()
for _h in logging.getLogger().handlers:
    _h.setFormatter(_trader_style_formatter)

# Start the background thread that prunes server_recent.log every 5 minutes
_start_recent_log_purger()

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))
# Allow up to 10 MB request bodies (default Flask is unlimited; uWSGI chokes on huge uncompressed pushes)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

# ── Suppress SIGPIPE (benign client disconnect errors) ──────────────────────
# When a client closes the connection during a large response, the server's
# write() call raises OSError: [Errno 32] Broken pipe. This is normal and
# expected on slow/unstable networks. Log as debug, not error.
import signal
if hasattr(signal, 'SIGPIPE'):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # Restore default handler to avoid zombie processes

# ── Gzip compression ────────────────────────────────────────────────────────
# Compress large JSON/HTML responses before sending to client.
# Reduces 300-600 KB payloads to ~30-60 KB, preventing uWSGI read timeouts.
app.config['COMPRESS_REGISTER'] = True
app.config['COMPRESS_MIMETYPES'] = [
    'application/json',
    'text/html',
    'text/css',
    'application/javascript',
    'text/plain',
]
app.config['COMPRESS_LEVEL'] = 6       # zlib level 1-9 (6 = good balance)
app.config['COMPRESS_MIN_SIZE'] = 1000 # only compress responses > 1KB
Compress(app)

# ============ Request Duration Logging ============
@app.before_request
def _log_request_start():
    g._request_start = time.monotonic()

# ── Auto-decompress gzip-encoded incoming request bodies ───────────────────
# Trader Companion sends MT5 deal payloads with Content-Encoding: gzip.
# uWSGI does not decompress these automatically, so we do it here before
# Flask's request.json parser runs.
@app.before_request
def _decompress_request_body():
    if request.headers.get('Content-Encoding') == 'gzip':
        import gzip as _gzip
        import io as _io
        try:
            # Read directly from wsgi.input BEFORE Werkzeug wraps it into a
            # LimitedStream or caches it — calling request.get_data() here would
            # cache the compressed bytes and the JSON parser would see garbage.
            raw_stream = request.environ.get('wsgi.input')
            content_length = request.environ.get('CONTENT_LENGTH')
            try:
                compressed_size = int(content_length) if content_length else 0
            except (TypeError, ValueError):
                compressed_size = 0

            if raw_stream and compressed_size > 0:
                compressed = raw_stream.read(compressed_size)
            else:
                compressed = raw_stream.read() if raw_stream else b''
            decompressed = _gzip.decompress(compressed)
            request.environ['wsgi.input'] = _io.BytesIO(decompressed)
            request.environ['CONTENT_LENGTH'] = str(len(decompressed))
            request.environ.pop('HTTP_CONTENT_ENCODING', None)
        except Exception as e:
            logging.warning(f'[DECOMPRESS] Failed to decompress gzip request: {e}')

@app.after_request
def _log_request_end(response):
    try:
        duration_ms = (time.monotonic() - getattr(g, '_request_start', time.monotonic())) * 1000
        logging.info('[REQ] %s %s -> %s (%.1fms)', request.method, request.path, response.status_code, duration_ms)
    except OSError as e:
        # Client disconnected during response write (SIGPIPE / broken pipe)
        # This is benign and not a server error — suppress as debug log
        if e.errno == errno.EPIPE:
            logging.debug('[REQ_BROKEN_PIPE] Client disconnect on %s %s', request.method, request.path)
        else:
            raise
    return response

# ============ Rate Limiting ============
# Note: For local development, use higher limits. 
# For production, consider: ["200 per day", "50 per hour"]
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["10000 per day", "2000 per hour"],
    storage_uri="memory://"
)

# In-memory cache for Google Sheet Stats-tab fetches.
# Avoids a blocking external HTTP call on every push (TTL = 5 minutes per sheet URL).
_stats_tab_cache = {}   # {sheet_url: (fetched_at_epoch, push_xlsx_notes)}
_STATS_TAB_TTL = 300    # seconds
_stats_tab_cache_refreshing = set()

# Initialize connection pool and log startup state
# Note: before_first_request was removed in Flask 2.4+. Call init directly at startup.
def _init_database_pool():
    """Initialize database connection pool on app startup."""
    try:
        from dashboard.database import _init_pool
        _init_pool()
        logging.info("[STARTUP] Database connection pool initialized")
    except Exception as e:
        logging.error(f"[STARTUP ERROR] Failed to initialize DB pool: {e}")
        raise

# Initialize on module load (runs before first request)
_init_database_pool()

# Initialize Hierarchy from Config
hierarchy = SYSTEM_HIERARCHY


def get_account_signature(account_number):
    """
    Extract account signature for matching: first 4 + last 4/5 digits.
    This handles truncated account numbers in MT5 comments.
    
    Handles truncated format with '...' like: FNFT...59574
    
    Examples:
        MFFUEVSTP326057008 -> mffu7008 (full account)
        FNFT...59574 -> fnft59574 (truncated - keep last 5)
        12345678 -> 12345678
    """
    if not account_number:
        return None
    
    account_str = str(account_number).strip()
    
    # Handle truncated format: PREFIX...SUFFIX
    if '...' in account_str:
        parts = account_str.split('...')
        if len(parts) == 2:
            prefix = parts[0][:4] if len(parts[0]) >= 4 else parts[0]
            suffix = parts[1]  # Keep full suffix (usually 5 digits)
            return (prefix + suffix).lower()
    
    # Standard format: first 4 + last 4
    if len(account_str) < 8:
        return account_str.lower()
    
    # First 4 + last 4
    return (account_str[:4] + account_str[-4:]).lower()


def get_last_n_digits(account: str, n: int = 5) -> str:
    """
    Extract last N digits from account number.
    Prioritizes digits at the end of the string to avoid prefix contamination.
    """
    import re
    if not account:
        return ""
    
    # Try to extract the final sequence of digits
    match = re.search(r'(\d+)$', str(account).strip())
    if match:
        digits = match.group(1)
        # For Topstep (V2-) or short accounts, ensure we don't demand more digits than exist
        if len(digits) < n:
            return digits
        return digits[-n:]
    
    # Fallback: extract all digits
    digits = ''.join(c for c in str(account) if c.isdigit())
    return digits[-n:] if len(digits) >= n else digits


def match_account_to_evaluation(account_number, evaluations, phase_code):
    """
    Find ALL matching evaluations for an account number based on phase.
    
    For Challenge (CH): Match against 'Account #' column
    For Funded/DoubleDip (FD, DD): Match against 'Account #.1' column
    For Farming (FA): Match against 'Account #.1' (funded); if blank, fall back to 'Account #' (challenge)
    
    Returns: List of (eval_index, matched_account)
    """
    import logging
    matches = []
    if not account_number:
        logging.debug(f"[MATCH] No account_number provided.")
        return matches

    target_sig = get_account_signature(account_number)
    target_last5 = get_last_n_digits(account_number, 5)
    logging.debug(f"[MATCH] Target account: {account_number} | Signature: {target_sig} | Last5: {target_last5}")
    if not target_sig and not target_last5:
        logging.debug(f"[MATCH] No signature or last5 for target account.")
        return matches

    def get_prefix(acc_str):
        import re
        s = str(acc_str).strip().upper()
        if '...' in s:
            s = s.split('...')[0]
        if '-' in s:
            return s.split('-')[0]
        m = re.match(r'^([A-Z]+)', s)
        if m:
            return m.group(1)
        return None

    target_prefix = get_prefix(account_number)

    # Combine funded and evaluation accounts for matching.
    # For FA (farming) phase: prefer Account #.1 (funded account number), but if that
    # column is blank for a row, fall back to Account # (challenge account number) so
    # that accounts with no separate funded account number can still be matched.
    #
    # Treat dash/placeholder strings as EMPTY so the matcher cannot write hedge
    # results into rows whose user blanked out the account column to "—" / "-" / "–".
    _PLACEHOLDER_ACCOUNTS = {'', 'none', '-', '—', '–', 'n/a', 'na', 'tbd', 'pending'}

    def _is_real_account(s):
        return bool(s) and s.strip().lower() not in _PLACEHOLDER_ACCOUNTS

    combined_accounts = []
    for idx, ev in enumerate(evaluations):
        funded_account = str(ev.get('account') or '').strip()
        if _is_real_account(funded_account):
            combined_accounts.append({'idx': idx, 'account': funded_account, 'source': 'funded'})

        if phase_code == 'FA':
            # Prefer funded account number; fall back to challenge account number if blank
            funded_acct = str(ev.get('Account #.1') or '').strip()
            challenge_acct = str(ev.get('Account #') or '').strip()
            if _is_real_account(funded_acct):
                combined_accounts.append({'idx': idx, 'account': funded_acct, 'source': 'Account #.1'})
            elif _is_real_account(challenge_acct):
                combined_accounts.append({'idx': idx, 'account': challenge_acct, 'source': 'Account # (FA fallback)'})
        else:
            for col_name in ['Account #.1', 'Account #']:
                eval_account = str(ev.get(col_name) or '').strip()
                if _is_real_account(eval_account):
                    combined_accounts.append({'idx': idx, 'account': eval_account, 'source': col_name})

    is_topstep = str(account_number).upper().startswith('V2')
    seen_row_indices = set()
    for entry in combined_accounts:
        idx = entry['idx']
        eval_account = entry['account']
        source = entry['source']
        if idx in seen_row_indices:
            continue
        eval_sig = get_account_signature(eval_account)
        eval_prefix = get_prefix(eval_account)
        has_letters = any(c.isalpha() for c in str(eval_account).upper())
        
        # Check for strict prefix mismatch
        prefix_mismatch = False
        if target_prefix and has_letters:
            if eval_prefix and target_prefix != eval_prefix:
                # If they are totally different prefixes, mismatch
                # But allow partials like MFFU vs MFFUEV
                 if not (target_prefix.startswith(str(eval_prefix)) or str(eval_prefix).startswith(target_prefix)):
                      # Also check if target_prefix is inside eval_account (e.g. V2 inside EXPRESS-V2)
                      if target_prefix not in eval_account.upper():
                           prefix_mismatch = True

        # eval_last5 = get_last_n_digits(eval_account, 5)
        # logging.debug(f"[MATCH] Comparing to DB account: {eval_account} (source: {source}) | Signature: {eval_sig} | Last5: {eval_last5}")
        if eval_sig == target_sig:
            matches.append((idx, eval_account))
            seen_row_indices.add(idx)
            logging.debug(f"[MATCH] Signature match: {account_number} == {eval_account}")
            continue
        
        # Strict prefix check applies to partial matches below
        if prefix_mismatch:
             logging.debug(f"[MATCH] Rejected partial match due to prefix mismatch: {target_prefix} vs {eval_account}")
             continue

        if target_last5 and len(target_last5) >= 4:
            eval_last5 = get_last_n_digits(eval_account, 5)
            if eval_last5 == target_last5:
                matches.append((idx, eval_account))
                seen_row_indices.add(idx)
                logging.debug(f"[MATCH] Last5 exact match: {target_last5} == {eval_last5}")
                continue
            if len(eval_last5) != len(target_last5) and eval_last5 and target_last5:
                if eval_last5.endswith(target_last5) or target_last5.endswith(eval_last5):
                    matches.append((idx, eval_account))
                    seen_row_indices.add(idx)
                    logging.debug(f"[MATCH] Last5 suffix match: {target_last5} <-> {eval_last5}")
                    continue
            if len(target_last5) >= 4 and len(eval_last5) >= 4:
                if target_last5[-4:] == eval_last5[-4:]:
                    matches.append((idx, eval_account))
                    seen_row_indices.add(idx)
                    logging.debug(f"[MATCH] Last4 match: {target_last5[-4:]} == {eval_last5[-4:]}")
                    continue
        if is_topstep:
            target_last4 = get_last_n_digits(account_number, 4)
            eval_last4 = get_last_n_digits(eval_account, 4)
            if target_last4 and len(target_last4) == 4 and target_last4 == eval_last4:
                matches.append((idx, eval_account))
                seen_row_indices.add(idx)
                logging.debug(f"[MATCH] Topstep relaxed 4-digit match: {target_last4} == {eval_last4}")
                continue
    if not matches:
        logging.debug(f"[MATCH] No match found for {account_number} in any DB account.")
    return matches


def parse_sheet_date(date_str):
    """
    Parse date string from Google Sheet into datetime object.
    Supports formats: DD/MM/YYYY, YYYY-MM-DD, MM/DD/YYYY, etc.
    """
    if not date_str:
        return None
    
    date_str = str(date_str).strip()
    if not date_str:
        return None
        
    formats = [
        '%m/%d/%Y', '%d/%m/%Y', '%Y-%m-%d', 
        '%m/%d/%y', '%d/%m/%y', 
        '%d-%m-%Y', '%Y/%m/%d', '%d.%m.%Y'
    ]
    
    for fmt in formats:
        try:
            val = datetime.strptime(date_str, fmt)
            # FORCE TO UTC or STRIP TIMEZONE? 
            # MT5 timestamps are usually UTC or server time (which we convert to timestamps).
            # If sheet dates are parsed as naive 00:00:00, and we compare to 
            # trade times which might be later in the day, that's fine.
            # But if a trade happens at 23:00 on Feb 18 (UTC), and sheet says Feb 18...
            # The trade timestamp (TS) > Date Purchased TS.
            # But if timezone is involved, eg. Sheet date is parsed as local time?
            # datetime.strptime creates NAIVE datetime.
            
            # If there's a 1-day difference being observed, it's likely a timezone shift display issue?
            # Or the dashboard is displaying dates differently?
            # Or maybe pandas parsing?
            
            # User says: "one day difference between the dates on the sheets and the dates on the dashboard"
            # If Sheet says Feb 18, Dashboard says Feb 17? Or Feb 19?
            
            # If date_str is "2/18/26", datetime is 2026-02-18 00:00:00
            
            # FIX: Use simple parsing - keep naive dates as imported
            # If date_str is "2/18/26", datetime is 2026-02-18 00:00:00
            
            return val
        except ValueError:
            continue
            
    return None


def filter_matches_by_date(matches, evaluations, trade_timestamp, phase_code=None, trade_number=None):
    """
    Filter matches to find the best matching evaluation.
    
    Universal logic for ALL prop firms:
        - When multiple rows match the same account, always prefer the LATEST row
          (highest eval_index = most recently added to the dashboard).
        - Date filtering is used as a secondary signal but never overrides the
          "latest row wins" rule.
    
    Args:
        matches: List of (eval_index, matched_account)
        evaluations: List of evaluation dicts
        trade_timestamp: Timestamp of the trade (float or int)
        phase_code: (Optional) Phase code to help determine target field for placeholder check
        trade_number: (Optional) Trade number for target field check
    """
    if not matches:
        return None
    
    # Universal: always prefer the latest row (highest eval_index)
    if not trade_timestamp:
        return max(matches, key=lambda m: m[0])

    # Convert trade timestamp to datetime
    try:
        val = float(trade_timestamp)
        trade_date = datetime.fromtimestamp(val)
    except (ValueError, TypeError):
         # If not a float, try isoformat string if present
        try:
             trade_date = datetime.fromisoformat(str(trade_timestamp).replace('Z', '+00:00'))
        except ValueError:
             return max(matches, key=lambda m: m[0])
        
    valid_matches = []
    
    # "give it a 2 day window from the date started"
    # Allow trades to be slightly BEFORE date started (e.g. timezone diffs)
    BUFFER_SECONDS = 2 * 24 * 3600 # 2 days

    for eval_idx, matched_acc in matches:
        ev = evaluations[eval_idx]
        # "Date Purchased" is typically at index 2, but we address by name
        date_purchased_str = ev.get('Date Started', '') or ev.get('Date Purchased', '')
        date_purchased = parse_sheet_date(date_purchased_str)
        
        if not date_purchased:
            # If no date purchased, keep as fallback
            valid_matches.append({
                'match': (eval_idx, matched_acc),
                'delta': float('inf'),
                'valid_date': False,
                'start_date': 'None'
            })
            continue
            
        # Reset time to midnight for comparison
        dp_date = date_purchased.replace(hour=0, minute=0, second=0, microsecond=0)
        td_date = trade_date.replace(hour=0, minute=0, second=0, microsecond=0)
        
        raw_delta_seconds = (td_date - dp_date).total_seconds()
        
        # Check if Trade Date is within valid window relative to Start Date
        # Valid: Trade >= Start - 2 days
        if raw_delta_seconds >= -BUFFER_SECONDS:
            valid_matches.append({
                'match': (eval_idx, matched_acc),
                'delta': raw_delta_seconds,
                'valid_date': True,
                'start_date': dp_date.strftime('%Y-%m-%d')
            })
            
    if not valid_matches:
        # Fallback if no valid dates found — prefer latest row (highest eval_index)
        # Prefer the latest row (highest eval_index = most recently added account)
        return max(matches, key=lambda m: m[0])
        
    # When multiple valid matches exist, prefer the latest row (highest eval_index).
    # This ensures data always goes to the most recently added account on the dashboard.
    dated_valid = [m for m in valid_matches if m['valid_date']]
    if dated_valid:
        match_result = max(dated_valid, key=lambda m: m['match'][0])['match']
    else:
        match_result = max(valid_matches, key=lambda m: m['match'][0])['match']
    return match_result


def normalize_account_size(value):
    """
    Normalize account size values to standard format: $X,XXX
    
    Handles:
        - "50k", "50K" → "$50,000"
        - "100000", "100,000" → "$100,000"
        - "$50,000" → "$50,000" (already correct)
        - "5000" → "$5,000"
    """
    import re
    if not value:
        return value
    
    val = str(value).strip().upper()
    
    # Already in correct format
    if re.match(r'^\$[\d,]+$', val):
        return value
    
    # Handle "50k" or "50K" format
    match = re.match(r'^[\$]?(\d+\.?\d*)K$', val, re.IGNORECASE)
    if match:
        num = float(match.group(1)) * 1000
        return f"${num:,.0f}"
    
    # Handle plain numbers like "50000" or "50,000"
    val_clean = re.sub(r'[\$,\s]', '', val)
    try:
        num = float(val_clean)
        return f"${num:,.0f}"
    except:
        pass
    
    # Return original if can't parse
    return value


def normalize_evaluations(evaluations):
    """Normalize field values in evaluations list."""
    if not evaluations:
        return evaluations
    
    for ev in evaluations:
        if 'Account Size' in ev and ev['Account Size']:
            ev['Account Size'] = normalize_account_size(ev['Account Size'])
    
    return evaluations


# Fields edited on the dashboard (or filled by billing) that sheet/trader pushes
# must not blindly overwrite — except when the caller sets force_fields.
DASHBOARD_OWNED_EVAL_KEYS = frozenset({
    'Payout 1', 'Date 1', 'Payout 2', 'Date 2', 'Payout 3', 'Date 3',
    'Payout 4', 'Date 4', 'Payout 5', 'Date 5', 'Payout 6', 'Date 6',
    'Fee', 'Activation Fee',
    'Status', 'Status Funded', 'Status P1',
    'Date Started', 'Date Ended', 'Date Started.1', 'Date Ended.1',
    'Date Purchased',
    'Account Number', 'Prop Firm', 'Account Size',
    'Account #', 'Account #.1',
})


def _evaluation_row_merge_key(ev):
    """Stable identity for matching a pushed row to the same row in the DB.

    Index-based merge breaks when row order changes, when only a subset of rows
    is pushed (active trades / billing), or when new rows are inserted — which
    caused Activation Fee and other dashboard-owned fields to attach to the
    wrong evaluation or appear to "not persist".
    """
    if not isinstance(ev, dict):
        return None
    firm = (ev.get('Prop Firm') or '').strip().lower().replace(' ', '').replace('_', '')
    a0 = (ev.get('Account #') or '').strip().lower()
    a1 = (ev.get('Account #.1') or '').strip().lower()
    sz = (ev.get('Account Size') or '').strip().lower()
    accts = tuple(sorted(a for a in (a0, a1) if a))
    if not firm and not accts:
        return None
    return (firm, accts, sz)


def _apply_dashboard_owned_merge(merged, base_row, incoming_row, force_fields):
    """Preserve dashboard-owned fields from base_row onto merged (mutates merged)."""
    for key in DASHBOARD_OWNED_EVAL_KEYS:
        if key in force_fields:
            if key in incoming_row:
                merged[key] = incoming_row[key]
            continue
        existing_val = base_row.get(key)
        if existing_val and str(existing_val).strip() not in ('', '-'):
            if key in ('Fee', 'Activation Fee'):
                try:
                    numeric = float(str(existing_val).replace('$', '').replace(',', '').strip())
                    if numeric == 0:
                        continue
                except (ValueError, TypeError):
                    pass
            merged[key] = existing_val


def merge_evaluation_push_with_existing(existing_evals, incoming_evals, force_fields=None):
    """Merge incoming evaluation rows into the full stored list by row identity.

    - Patches rows that match (firm + account numbers + size); never drops
      existing rows when the push only contains a subset (e.g. active trades).
    - Appends rows that have no match (new accounts from the sheet/trader).
    """
    if not incoming_evals:
        return list(existing_evals) if existing_evals else []

    force_fields = set(force_fields or [])
    existing_evals = existing_evals or []
    incoming_evals = incoming_evals or []

    key_to_idx = {}
    for i, ex in enumerate(existing_evals):
        if not isinstance(ex, dict):
            continue
        mk = _evaluation_row_merge_key(ex)
        if mk and mk not in key_to_idx:
            key_to_idx[mk] = i

    out = []
    for ex in existing_evals:
        out.append(dict(ex) if isinstance(ex, dict) else ex)

    appended = []

    for i, ev_in in enumerate(incoming_evals):
        if not isinstance(ev_in, dict):
            continue
        mk = _evaluation_row_merge_key(ev_in)
        idx = key_to_idx.get(mk) if mk else None
        if idx is None and mk is None and i < len(out):
            idx = i
        if idx is not None and idx < len(out):
            base_snapshot = existing_evals[idx] if isinstance(existing_evals[idx], dict) else {}
            merged = dict(out[idx])
            merged.update(ev_in)
            _apply_dashboard_owned_merge(merged, base_snapshot, ev_in, force_fields)
            out[idx] = merged
        else:
            merged = dict(ev_in)
            _apply_dashboard_owned_merge(merged, {}, ev_in, force_fields)
            appended.append(merged)

    out.extend(appended)
    return out


def recalculate_hedge_nets(evaluations):
    """Recalculate Hedge Net and Hedge Net.1 for every evaluation row.

    Uses the same formulas as the Google Sheet import in data_processor.py
    so that values stay correct whenever hedge results or statuses change.
    """
    def _num(val):
        if val is None or str(val).strip() in ('', '-'):
            return 0.0
        try:
            return float(str(val).replace('$', '').replace(',', '').strip())
        except (ValueError, TypeError):
            return 0.0

    def _is_blank(val):
        return val is None or str(val).strip() in ('', '-')

    for ev in (evaluations or []):
        # --- Hedge Net (Phase 1) ---
        # =IF(OR(ISBLANK(HR1), Status P1<>"Fail"), "", -Fee + HR1+HR2+HR3+HR4+HR5)
        status_p1 = str(ev.get('Status P1', '')).strip()
        if _is_blank(ev.get('Hedge Result 1')) or status_p1 != 'Fail':
            ev['Hedge Net'] = ''
        else:
            fee = _num(ev.get('Fee'))
            hr_sum = sum(_num(ev.get(f'Hedge Result {i}')) for i in range(1, 6))
            ev['Hedge Net'] = -fee + hr_sum

        # --- Hedge Net.1 (Funded) ---
        status = str(ev.get('Status') or ev.get('Status Funded', '')).strip()
        sum_phase1 = sum(_num(ev.get(f'Hedge Result {i}')) for i in range(1, 6))
        sum_funded = sum(_num(ev.get(c)) for c in [
            'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
            'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7',
        ])
        fee = _num(ev.get('Fee'))
        activation_fee = _num(ev.get('Activation Fee'))

        if status == 'Completed':
            sum_payouts = sum(_num(ev.get(f'Payout {i}')) for i in range(1, 7))
            sum_days = sum(_num(ev.get(f'Hedge Day {i}')) for i in range(1, 51))
            ev['Hedge Net.1'] = sum_payouts + sum_funded + sum_phase1 - fee - activation_fee + sum_days
        elif status == 'Fail':
            ev['Hedge Net.1'] = sum_funded + sum_phase1 - fee - activation_fee
        else:
            ev['Hedge Net.1'] = ''

    return evaluations


# Dashboard merge: keep MT5 / historical hedging_review fields from DB while refreshing sheet-derived totals.
_MT5_HEDGING_REVIEW_PRESERVE_KEYS = (
    'actual_hedging_results',
    'total_deposits',
    'total_withdrawals',
    'current_balance',
    'historical_accounts',
    'historical_deposits',
    'historical_withdrawals',
    'historical_balance',
    'current_mt5_prior_activity',
)


def merge_statistics_hedging_review_preserve_mt5(existing_hr, merged_statistics):
    """Mutates merged_statistics: refresh sheet_* from calculate_statistics, preserve MT5 snapshot."""
    existing_hr = existing_hr or {}
    fresh_hr = merged_statistics.get('hedging_review') or {}
    merged_hr = dict(fresh_hr)
    for key in _MT5_HEDGING_REVIEW_PRESERVE_KEYS:
        if key in existing_hr and existing_hr.get(key) is not None:
            merged_hr[key] = existing_hr[key]
    try:
        sheet_hedge = float(merged_hr.get('sheet_hedging_results', 0) or 0)
    except (TypeError, ValueError):
        sheet_hedge = 0.0
    try:
        actual_hedge = float(merged_hr.get('actual_hedging_results', 0) or 0)
    except (TypeError, ValueError):
        actual_hedge = 0.0
    merged_hr['discrepancy'] = round(actual_hedge - sheet_hedge, 2)
    disc = merged_hr['discrepancy']
    for section_key in ('profitability_completed', 'cashflow_inprogress'):
        sec = merged_statistics.get(section_key, {})
        sec['net_profit'] = round(
            float(sec.get('payouts', 0) or 0)
            + float(sec.get('hedging_results', 0) or 0)
            + float(sec.get('farming_results', 0) or 0)
            + float(disc)
            - float(sec.get('challenge_fees', 0) or 0),
            2,
        )
    merged_statistics['hedging_review'] = merged_hr


def _changed_fields_touch_hedge(user_changed):
    """True if user explicitly edited any hedge result or hedge day column."""
    if not user_changed:
        return False
    for fields in user_changed.values():
        for f in fields or []:
            if not isinstance(f, str):
                continue
            if f.startswith('Hedge Result') or f.startswith('Hedge Day'):
                return True
    return False


def _dashboard_log_hedge_edit(client_id, user_changed, evaluations):
    """Structured log when hedge-related cells were saved (debug MT5 vs sheet drift)."""
    if not user_changed:
        return
    hedge_cols = {f'Hedge Result {i}' for i in range(1, 6)}
    hedge_cols.update({
        'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
        'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7',
    })
    hedge_cols.update(f'Hedge Day {i}' for i in range(1, 51))
    touched = False
    for idx_str, fields in user_changed.items():
        try:
            idx = int(idx_str)
        except (TypeError, ValueError):
            continue
        fs = fields or []
        if not fs:
            continue
        inter = set(fs) & hedge_cols
        if not inter:
            continue
        touched = True
        ev = evaluations[idx] if 0 <= idx < len(evaluations) else {}
        if not isinstance(ev, dict):
            ev = {}
        app.logger.info(
            "[HEDGE_SAVE] client=%s row=%s fields=%s HR1=%r HNet=%r HNet1=%r StatusP1=%r Status=%r",
            client_id,
            idx,
            sorted(inter),
            ev.get('Hedge Result 1'),
            ev.get('Hedge Net'),
            ev.get('Hedge Net.1'),
            ev.get('Status P1'),
            ev.get('Status') or ev.get('Status Funded'),
        )
    if touched:
        app.logger.info("[HEDGE_SAVE] client=%s rows_touched_done", client_id)


def _match_tradovate_farming(tradovate_farming_days, fa_account_key):
    """Find Tradovate MNQ daily P&L matching a farming account.

    Args:
        tradovate_farming_days: List of {account_name, account_id, mnq_daily_pnl: [{date, net_pnl}]}
        fa_account_key: Account key from MT5 comment, e.g. 'FNFT-85625'

    Returns:
        Sorted list of {date, net_pnl} dicts, or None if no match.
    """
    if not tradovate_farming_days or not fa_account_key:
        return None

    fa_key_upper = fa_account_key.upper()
    # Extract digits (4+ chars) from the FA key for fallback matching
    digits = [d for d in re.findall(r'\d+', fa_key_upper) if len(d) >= 4]

    for tv_data in tradovate_farming_days:
        tv_name = (tv_data.get('account_name') or '').upper()
        if not tv_name:
            continue

        # Direct substring match (either direction)
        if fa_key_upper in tv_name or tv_name in fa_key_upper:
            return tv_data.get('mnq_daily_pnl', [])

        # Digit-based match: significant digit sequences from the FA key
        for d in digits:
            if d in tv_name:
                return tv_data.get('mnq_daily_pnl', [])

    return None


def get_field_name_for_phase(phase_code, trade_number, farming_date, evaluations, eval_idx, account_number=None):
    """
    Determine the correct field name to update based on phase.
    
    Phase mappings:
    - CH1-5: Hedge Result 1-5 (Challenge)
    - FD (MFFU with FD0): FD0→Hedge Result 1, FD1→Hedge Result 2, etc.
    - FD (Other starting FD1): FD1→Hedge Result 1, FD2→Hedge Result 2, etc.
    - DD1-4: Additional funded hedge results
    - FA: Hedge Day N (based on date or next available slot)
    """
    if phase_code == 'CH':
        # Challenge: CH1 → Hedge Result 1, CH2 → Hedge Result 2, etc.
        if trade_number is not None and 1 <= trade_number <= 5:
            return f"Hedge Result {trade_number}"
    
    elif phase_code == 'FD':
        # Funded: FD1→HR1.1, FD2→HR2.1, etc.
        # Some sources send FD0; treat FD0 the same as FD1 (map to HR1.1).
        if trade_number is not None:
            if trade_number == 0:
                return "Hedge Result 1.1"
            return f"Hedge Result {trade_number}.1"
    
    elif phase_code == 'DD':
        # Double Dip: DD1 maps to Hedge Result 1.1, DD2->2.1 etc
        if trade_number is not None:
             return f"Hedge Result {trade_number}.1"
    
    elif phase_code == 'FA':
        ev = evaluations[eval_idx] if (eval_idx is not None and evaluations and eval_idx < len(evaluations)) else {}
        incoming_date = str(farming_date or '').strip()

        logging.info(f"[FA SELECT] eval_idx={eval_idx} incoming_date={incoming_date}")

        # Reuse same slot if same date already exists
        for day_num in range(1, 51):
            date_key = f"_Hedge Day {day_num} Date"
            saved_date = str(ev.get(date_key, '')).strip()
            if saved_date and incoming_date and saved_date == incoming_date:
                logging.info(f"[FA SELECT] Reusing Hedge Day {day_num} for date {incoming_date}")
                return f"Hedge Day {day_num}"

        # Otherwise use first empty slot
        for day_num in range(1, 51):
            value_key = f"Hedge Day {day_num}"
            date_key = f"_Hedge Day {day_num} Date"

            existing_value = ev.get(value_key)
            existing_date = ev.get(date_key)

            is_empty_value = existing_value in (None, '', 0, '0', '$0', '$0.00')
            is_empty_date = existing_date in (None, '')

            if is_empty_value and is_empty_date:
                logging.info(f"[FA SELECT] Using empty slot Hedge Day {day_num} for date {incoming_date}")
                return value_key

        logging.warning(f"[FA SELECT] No empty slot found, defaulting to Hedge Day 1")
        return "Hedge Day 1"
    
    return None


def update_evaluations_from_aggregated_data(evaluations, aggregated_data=None, raw_deals=None, tradovate_farming_days=None):
    """
    Update evaluation hedge result fields from aggregated MT5 comment data OR raw deals.
    
    If 'raw_deals' is provided, performs server-side aggregation (Session Matching).
    Otherwise, uses client-provided 'aggregated_data'.
    
    Args:
        evaluations: List of evaluation records
        aggregated_data: List of aggregated trade data (from client)
        raw_deals: List of raw MT5 deal objects (from client)
        tradovate_farming_days: List of Tradovate MNQ daily P&L per account (for Prop Day values)
    
    Returns:
        Tuple of (updated_evaluations, match_log)
    """
    aggregated_data = aggregated_data or []
    tradovate_farming_days = tradovate_farming_days or []
    
    # -------------------------------------------------------------------------
    # SERVER-SIDE SESSION MATCHING LOGIC
    # -------------------------------------------------------------------------
    if raw_deals:
        import datetime
        
        match_log = ["🔄 Using SERVER-SIDE Session Matching (ignoring client aggregation)"]
        
        # Helper: Parse simple comment patterns
        def parse_comment(c):
            if not c: return None, None
            # Standard Pattern: PRE...12345_CH1
            m = re.search(r'_(CH|FD|DD|FA)(\d+)?', c, re.IGNORECASE)
            if m:
                return m.group(1).upper(), int(m.group(2)) if m.group(2) else None
            return None, None

        def parse_full_comment_structure(c):
            # Returns (PropPrefix, AccountNum, PhaseStr, PhaseNum)
            # Example: MFFU...60076_FD1 -> ('MFFU', '60076', 'FD', 1)
            # Example: V2-...4610_CH2 -> ('V2-', '4610', 'CH', 2)
            # Example: FNFT...G8326_CH1 -> ('FNFT', 'G8326', 'CH', 1)
            if not c: return None, None, None, None
            
            # Regex for "PREFIX...ALPHANUM_PHASE"
            # Support prefixes with digits and dashes (e.g. V2-)
            # 1. Prefix: Letters, Digits, Dashes, min length 2
            # 2. Filler: non-alphanumeric chars (dots, spaces, etc)
            # 3. Account: Alphanumeric (Letters + Digits)
            # 4. Underscore + Phase Code + Num
            m = re.search(r'^([A-Z0-9\-]+)[^A-Z0-9]+([A-Z0-9]+)_(CH|FD|DD|FA)(\d+)?$', c.strip(), re.IGNORECASE)
            if m:
                return m.group(1).upper(), m.group(2).upper(), m.group(3).upper(), int(m.group(4)) if m.group(4) else 1
            return None, None, None, None
            
        def get_ts(d):
            t = d.get('time')
            if isinstance(t, (int, float)): return t
            if isinstance(t, str):
                try:
                    return datetime.datetime.fromisoformat(t).timestamp()
                except:
                    pass
            return 0

        # Helper: Parse simple comment patterns to extract identifying account number
        def extract_account_from_comment(c):
            if not c: return None
            
            # Known prefixes logic - moved to TOP priority
            known_prefixes = ['MFFU', 'AFAD', 'V2', 'FNFT', 'TDFY', 'ELTD', 'TDF']
            c_upper = c.upper()
            found_prefix = None
            for kp in known_prefixes:
                if kp in c_upper:
                    found_prefix = kp
                    break
            
            # If we see a known prefix, we want to capture that + the number (or alphanumeric code)
            if found_prefix:
                # Try to find the number/alphanum pattern specific to the prefix logic
                # For FNFT, account numbers can start with G?
                # Generally look for the part after dots and before _PHASE
                
                # Check for Structure: PREFIX...ACCOUNT_PHASE
                # Grab whatever is between ... and _
                # Use regex to find alphanumeric chars immediately preceding _PHASE
                m_phase = re.search(r'([A-Z0-9]+)_(CH|FD|DD|FA)', c, re.IGNORECASE)
                if m_phase:
                     # This captures G8326 from ...G8326_CH1
                     # But we want to prepend prefix if not present?
                     extracted = m_phase.group(1)
                     # If extracted matches digits, or starts with G, etc.
                     # If found_prefix is already in extracted (e.g. FNFT12345), return extracted
                     if found_prefix in extracted.upper():
                         return extracted
                     # Else return PREFIX-ACCOUNT
                     return f"{found_prefix}-{extracted}"

                # Fallback: Just first number sequence if phase not found (shouldn't happen for valid comments)
                num_match = re.search(r'(\d+)', c)
                if num_match:
                    return f"{found_prefix}-{num_match.group(1)}"
            
            # Look for alphanumeric string of length 4+ (including letters) before phase
            # This covers alphanumeric accounts like "MFFU12345"
            m = re.search(r'([A-Za-z0-9]{3,})_(CH|FD|DD|FA)', c, re.IGNORECASE)
            if m:
                val = m.group(1)
                # If it's just digits, fine
                if val.isdigit():
                    return val
                
                # If it has letters, it might contain the prefix already in the group
                # e.g. MFFU12345
                return val

            # Fallback: Just look for digits before phase
            m = re.search(r'(\d+)_(CH|FD|DD|FA)', c, re.IGNORECASE)
            if m:
                 return m.group(1)
            return None

        # 1. Group by Account Number (from login or comment)
        # Note: raw_deals usually come from a single login, but might contain history for that login.
        
        # --- NEW: Group Deals by Position ID FIRST ---
        # The user requested "extract data from positions not deals".
        # We synthesize "Position Objects" from raw deals by grouping on 'position_id'.
        # This ensures that Exit deals (often comment-less) are linked to Entry deals (with comments).
        
        position_map = {}
        non_position_deals = []
        
        # Initial pass to group
        for d in raw_deals:
            pos_id = d.get('position_id')
            # Check if it's a trade deal (not balance/credit) and has valid position_id
            # Balance ops usually have position_id=0 or are distinct types
            d_type = str(d.get('type', '')).upper()
            is_balance = d_type in ['BALANCE', 'CREDIT', '2', '3', 'CHARGE', 'CORRECTION', 'BONUS']
            
            if not is_balance and pos_id and pos_id > 0:
                if pos_id not in position_map:
                    position_map[pos_id] = []
                position_map[pos_id].append(d)
            else:
                non_position_deals.append(d)
                
        # Synthesize Positions
        synthesized_deals = []
        
        # Add non-position deals — but skip internal transfers.
        # Internal transfers are BALANCE-type deals with NO comment (no
        # Tradovate account number).  Positive balance resets (also no comment
        # but profit > 0) are kept because they drive session splitting.
        for _npd in non_position_deals:
            _npd_type = str(_npd.get('type', '')).upper()
            _npd_comment = str(_npd.get('comment', '')).strip()
            _npd_comment_l = _npd_comment.lower()
            _npd_profit = float(_npd.get('profit', 0))
            # Internal transfers can be tagged either way:
            #   - no comment + non-positive profit (legacy heuristic), OR
            #   - explicit 'internal transfer' comment regardless of sign.
            if _npd_type in ('BALANCE', '2'):
                if 'internal transfer' in _npd_comment_l:
                    continue
                if not _npd_comment and _npd_profit <= 0:
                    continue
            synthesized_deals.append(_npd)
        
        for pos_id, p_deals in position_map.items():
            # Create a single 'deal' representing the whole position
            
            # 1. Find best comment (from entry usually)
            # Sort by time to find entry
            p_deals.sort(key=get_ts)
            
            common_comment = ""
            for pd in p_deals:
                c = pd.get('comment', '')
                if c and not common_comment:
                    common_comment = c
                # Prefer comments that match our parser pattern
                if parse_comment(c)[0]: 
                    common_comment = c
                    break
            
            # 2. Sum Profits
            total_profit = sum(float(pd.get('profit', 0)) + float(pd.get('commission', 0)) + float(pd.get('swap', 0)) for pd in p_deals)
            
            # 3. Create Synthesized Object
            # Use Entry Time as the time for this position
            entry_time = get_ts(p_deals[0])
            
            syn_deal = {
                'time': entry_time,
                'profit': total_profit, # Net result of position
                'comment': common_comment,
                'type': 'POSITION',
                'position_id': pos_id,
                'deal_count': len(p_deals)
            }
            
            # --- FILTER UNKNOWN FORMATS ---
            # If we cannot extract an account number OR a valid phase from the comment,
            # this position is likely "Unknown" and should be ignored as per user request.
            # We use likelyhood check: if extraction returns None, it's unknown format.
            ac_check = extract_account_from_comment(common_comment)
            ph_check, _ = parse_comment(common_comment)
            
            if not ac_check and not ph_check:
                 # logging.debug(f"[FILTER] Skipping position {pos_id} due to unrecognized comment format: '{common_comment}'")
                 continue
            
            synthesized_deals.append(syn_deal)
            
        # Replace raw_deals with our improved list
        raw_deals = synthesized_deals
        match_log.append(f"🔄 Grouped {len(position_map)} positions from raw deals for accurate P&L tracking")
        
        # --- NEW DATE FILTERING LOGIC ---
        # The user requested to only process trades from "today" (active day)
        # OR if no trades today, process trades from the "last active day".
        if raw_deals:
            # Helper to extract YYYY-MM-DD from timestamp (assuming timestamp is seconds)
            # syn_deal['time'] is already a timestamp float/int
            def get_date_str(ts):
                try:
                    if isinstance(ts, str):
                        # Try parsing ISO string
                        dt = datetime.datetime.fromisoformat(ts)
                        return dt.strftime('%Y-%m-%d')
                    return datetime.datetime.fromtimestamp(float(ts)).strftime('%Y-%m-%d')
                except Exception as e:
                    logging.warning(f"Failed to parse timestamp {ts}: {e}")
                    return "1970-01-01"
            
            # Count FA deals for logging
            fa_count = sum(1 for d in raw_deals if parse_comment(d.get('comment', ''))[0] == 'FA')
            if fa_count:
                match_log.append(f"🌾 Found {fa_count} farming deals in data")

            # --- PRE-COMPUTE FARMING DAILY PROFITS PER ACCOUNT (before date filter) ---
            # Scan ALL FA deals to build: {account_num: {date_str: total_profit}}
            # This lets us know how many farming days exist for each account
            # and which Hedge Day slot each date maps to.
            fa_account_days = {}
            for _d in raw_deals:
                _phase, _num = parse_comment(_d.get('comment', ''))
                if _phase != 'FA':
                    continue
                _acc = extract_account_from_comment(_d.get('comment', ''))
                if not _acc:
                    continue
                _ts = get_ts(_d)
                _date = datetime.datetime.fromtimestamp(_ts).strftime('%Y-%m-%d')
                _profit = float(_d.get('profit', 0)) + float(_d.get('commission', 0)) + float(_d.get('swap', 0))
                if _acc not in fa_account_days:
                    fa_account_days[_acc] = {}
                fa_account_days[_acc][_date] = fa_account_days[_acc].get(_date, 0.0) + _profit

            if fa_account_days:
                for _acc, _days in fa_account_days.items():
                    logging.info(f"[FA PRE-COMPUTE] account={_acc} farming_days={len(_days)} dates={sorted(_days.keys())}")
                match_log.append(f"🌾 Pre-computed farming: {len(fa_account_days)} account(s), {sum(len(d) for d in fa_account_days.values())} total farming day(s)")

            # Track which evals have already had their Hedge Days written by FA pre-compute
            fa_evals_written = set()
            
            # Identify all unique dates in the data for logging
            unique_dates = sorted(list({get_date_str(d['time']) for d in raw_deals})) if raw_deals else []
            
            # Date filtering is now handled CLIENT-SIDE (push from 23rd of last month,
            # FNFT challenge 24h filter). Server processes ALL deals received.
            if unique_dates:
                match_log.append(f"📅 Processing deals across {len(unique_dates)} date(s): {unique_dates[0]} to {unique_dates[-1]}")
                logging.info(f"   [DATES] Processing all {len(raw_deals)} deals across {len(unique_dates)} date(s)")
            

        # --------------------------------
        
        # ---------------------------------------------
        
        # Let's assume passed 'aggregated_data' logic was doing groupings.
        # We will iterate raw_deals, extracting (Phase, TradeNum) from comment.
        # And Group by Time Gaps (> 7 days) -> New Session.
        
        raw_deals.sort(key=get_ts)
        
        # Group into sessions by Time Gap (24h) OR Phase Change
        sessions = []
        
        # Helper to init session
        def new_session_dict(start_t, acc_guess=None):
            return {
                'deals': [], 
                'start': start_t, 
                'end': start_t, 
                'account_guess': acc_guess,
                'phase_guess': None,
                'phase_num': None
            }
        
        # Initialize with first deal info
        first_deal = raw_deals[0]
        start_ts = get_ts(first_deal)
        
        if len(raw_deals) > 0:
             logging.info(f"[DEBUG] First 20 Raw Comments: {[d.get('comment') for d in raw_deals[:20]]}")

        # Extract initial account guess
        first_acc_guess = None
        for d in raw_deals:
             guess = extract_account_from_comment(d.get('comment', ''))
             if guess:
                 first_acc_guess = guess
                 break
        
        current_session = new_session_dict(start_ts, first_acc_guess)
        last_ts = start_ts
        
        # Initial phase guess
        p_init, n_init = parse_comment(first_deal.get('comment', ''))
        if p_init:
            current_session['phase_guess'] = p_init
            current_session['phase_num'] = n_init
        
        for d in raw_deals:
            ts = get_ts(d)
            p, n = parse_comment(d.get('comment', ''))
            
            # Check for Phase Change
            is_phase_change = False
            if p and current_session['phase_guess']:
                if p != current_session['phase_guess'] or n != current_session['phase_num']:
                    is_phase_change = True

            # Check for Account Change
            is_account_change = False
            current_account_guess = extract_account_from_comment(d.get('comment', ''))
            
            # Only trigger change if we had a guess and the new guess is DEFINITELY different
            if current_account_guess and current_session['account_guess']:
                if current_account_guess != current_session['account_guess']:
                    is_account_change = True
                    logging.debug(f"[SPLIT] Account changed from {current_session['account_guess']} to {current_account_guess}")

            # Check Time Gap (36 hours) - lowered from 7 days
            time_gap = (ts - last_ts) > (36 * 3600)
            
            # Balance Reset
            is_balance_reset = str(d.get('type', '')).upper() == 'BALANCE' and float(d.get('profit', 0)) > 0
            
            # Split Session Logic (Phase, Time, Balance, Account)
            should_split = (time_gap or is_balance_reset or is_phase_change or is_account_change)
            
            if should_split and current_session['deals']:
                sessions.append(current_session)
                
                # Determine next account guess for the new session
                next_acc_guess = current_account_guess if current_account_guess else current_session['account_guess']
                
                # Create new session
                current_session = new_session_dict(ts, next_acc_guess)
                
                if p:
                    current_session['phase_guess'] = p
                    current_session['phase_num'] = n
            
            current_session['deals'].append(d)
            current_session['end'] = max(current_session['end'], ts)
            last_ts = ts
            
            # Update tracking
            if p and not current_session['phase_guess']:
                current_session['phase_guess'] = p
                current_session['phase_num'] = n
                
            # If we don't have an account guess yet (or it's None), see if this comment has one
            if current_account_guess and not current_session['account_guess']:
                current_session['account_guess'] = current_account_guess
        
        if current_session['deals']:
            sessions.append(current_session)
        
        match_log.append(f"   Found {len(sessions)} distinct sessions based on Phase/Time gaps")
        
        # --- NEW: Summary Aggregation Structure ---
        # { PropFirm: { AccountNumber: { PhaseKey: { profit: 0.0, trades: 0 } } } }
        trade_summary = {}
        # ------------------------------------------



        # Now match each session to an Evaluation
        updates_made = 0
        
        for session in sessions:
            if not session['account_guess']:
                logging.warning(f"Session without account guess skipped. Deals: {len(session['deals'])}")
                continue # Can't match without account number

            logging.info(f"[DEBUG] Processing Session: AccountGuess={session['account_guess']}, Deals={len(session['deals'])}")
                
            # Aggregate stats for session — exclude internal transfers.
            # Internal transfers are BALANCE-type deals with no comment (no
            # Tradovate account number).  Real trades always have comments.
            def _is_internal_transfer(d):
                dt = str(d.get('type', '')).upper()
                comment = str(d.get('comment', '')).strip()
                comment_l = comment.lower()
                if dt not in ('BALANCE', 'CREDIT', '2', '3', 'CHARGE', 'CORRECTION', 'BONUS'):
                    return False
                # Either no comment (legacy) or an explicit "internal transfer" tag.
                return (not comment) or ('internal transfer' in comment_l)
            trade_deals_only = [d for d in session['deals'] if not _is_internal_transfer(d)]
            session_profit = sum(float(d.get('profit', 0)) + float(d.get('commission', 0)) + float(d.get('swap', 0)) for d in trade_deals_only)
            
            # Determine Phase/TradeNum from MOST frequent in session
            # (To handle noise)
            phases = {}
            full_comment_info = None
            
            for d in session['deals']:
                # Try full structure parse first
                prefix, acc_part, p, n = parse_full_comment_structure(d.get('comment', ''))
                if prefix and acc_part:
                    full_comment_info = (prefix, acc_part, p, n)
                
                # Fallback to simple parse for counting
                p_simple, n_simple = parse_comment(d.get('comment', ''))
                if p_simple:
                    key = (p_simple, n_simple)
                    phases[key] = phases.get(key, 0) + 1
            
            if not phases:
                continue
                
            best_phase, best_num = max(phases.items(), key=lambda x: x[1])[0]
            logging.info(
                f"[SESSION] account_guess={session['account_guess']} "
                f"best_phase={best_phase} best_num={best_num} "
                f"start={datetime.datetime.fromtimestamp(session['start'])} "
                f"end={datetime.datetime.fromtimestamp(session['end'])} "
                f"profit={session_profit}"
            )
            
            # If we found a full comment structure, prefer that for matching
            if full_comment_info:
                 target_prefix, target_acc_part, target_phase, target_num = full_comment_info
                 # Use the derived phase/num from the full comment if available, or fallback to frequency
                 if target_phase: 
                     best_phase = target_phase
                 if target_num:
                     best_num = target_num
                 
                 acc_num = target_acc_part # Use extracted regex digits as the account number to match
                 
                 # NEW: If acc_num is purely digits, but we found a PREFIX, try to append it?
                 # Or better: Check if appending prefix helps match against verbose DB accounts?
                 # e.g. TDFY-72031 might be better search key than 72031 if DB is verbose?
                 # But our matching logic 's_acc in ac1' works better with SHORTER s_acc.
                 # So keeps '72031'.
            else:
                 acc_num = session['account_guess']

            start_date_ts = session['start']
            
            # Find candidate evaluations
            # Check match against BOTH Account # and Account #.1
            
            def normalize_acc(a): return str(a).strip().upper()
            
            # Strip prefix from s_acc if we are relying on substring matching?
            # If s_acc is "TDFY-72031", and DB has "TDFYSL...72031", "TDFY-72031" is NOT in it.
            # But "72031" IS in it.
            # So we should probably strip known prefixes from s_acc before matching loop if we want flexible matching.
            
            s_acc_raw = normalize_acc(acc_num)
            
            # Preserve the comment prefix (e.g. 'V2-', 'MFFU', 'FNFT') for firm validation
            # even when acc_num itself has no hyphen (full_comment_info strips prefix from acc_part)
            comment_prefix = None
            if full_comment_info and full_comment_info[0]:
                comment_prefix = full_comment_info[0].rstrip('-').upper()
            
            # If s_acc contains a hyphen, try splitting
            if '-' in s_acc_raw:
                # Keep full for strict check, but try short version for loose check?
                s_acc_short = s_acc_raw.split('-')[-1]
            else:
                s_acc_short = s_acc_raw
            
            # Use the SHORTER version for candidate finding to maximize hits
            s_search = s_acc_short
            
            candidates = []
            
            # Determines if we have a strict structural match up front
            matches_full_strict = (full_comment_info is not None)

            for e in evaluations:
                is_match = False
                ac1 = normalize_acc(e.get('Account #', ''))
                ac2 = normalize_acc(e.get('Account #.1', ''))
                
                # Strip Top Step prefixes (50KTC- for challenge, EXPRESS- for funded) before matching
                for _ts_prefix in ['50KTC-', 'EXPRESS-']:
                    if ac1.startswith(_ts_prefix): ac1 = ac1[len(_ts_prefix):]
                    if ac2.startswith(_ts_prefix): ac2 = ac2[len(_ts_prefix):]
                
                # Use ENDING digits matching only — never substring containment
                s = s_search
                
                # Extract trailing digits for comparison
                import re as _re
                s_digits = _re.search(r'(\d+)$', s)
                s_trail = s_digits.group(1) if s_digits else s
                
                # Check ac1
                if ac1:
                    ac1_digits = _re.search(r'(\d+)$', ac1)
                    ac1_trail = ac1_digits.group(1) if ac1_digits else ac1
                    if s == ac1:
                        is_match = True
                    elif ac1_trail.endswith(s_trail) or s_trail.endswith(ac1_trail):
                        is_match = True
                
                # Check ac2
                if not is_match and ac2:
                    ac2_digits = _re.search(r'(\d+)$', ac2)
                    ac2_trail = ac2_digits.group(1) if ac2_digits else ac2
                    if s == ac2:
                        is_match = True
                    elif ac2_trail.endswith(s_trail) or s_trail.endswith(ac2_trail):
                        is_match = True
                
                # STRICT PREFIX CHECK — use comment_prefix (from full_comment_info) OR s_acc_raw hyphen prefix
                prefix_part = comment_prefix  # e.g. 'V2' from V2-1128_CH2
                if not prefix_part and '-' in s_acc_raw:
                    prefix_part = s_acc_raw.split('-')[0]
                
                try:
                    if is_match and prefix_part:
                        pf_val = str(e.get('Prop Firm', '')).upper()
                        
                        # Only proceed if we have a valid Prop Firm string to check against
                        if pf_val and prefix_part not in pf_val and pf_val not in prefix_part:
                            mapping = {
                                'MFFU': ['MYFUNDED', 'MFFU', 'MY FUNDED'],
                                'AFAD': ['ALPHA', 'AFAD'],
                                'V2': ['TOPSTEP', 'TOP STEP', 'V2'],
                                'FNFT': ['FUNDEDNEXT', 'FUNDED NEXT', 'FNFT'],
                                'TDFY': ['TRADEIFY', 'TDFY'],
                                'ELTD': ['TRADEDAY', 'ELTD'],
                                'TDF': ['TRADEDAY', 'TDF', 'TRADEIFY'],
                                'FTDF': ['TRADEDAY', 'TDF', 'TRADEIFY'],
                                'TPOF': ['TOPONEFUTURES', 'TOP ONE', 'TPOF']
                            }
                            if prefix_part in mapping:
                                valid_keywords = mapping[prefix_part]
                                if not any(k in pf_val for k in valid_keywords):
                                    is_match = False
                except Exception as ex:
                    logging.error(f"Error in Strict Prefix Check for {s_acc_raw} prefix={prefix_part}: {ex}")

                if matches_full_strict and is_match:
                     pass

                if is_match:
                    candidates.append(e)

            if not candidates:
                match_log.append(f"⚠️ No evaluation found for session {acc_num} (Start: {str(datetime.datetime.fromtimestamp(start_date_ts))})")
                continue

            # Filter by Date Purchased
            # We want Evaluation.DatePurchased <= Session.Start
            # And closest to it
            valid_candidates = []
            
            # STRICT MATCH OVERRIDE: If we have a perfectly parsed comment (Structure: PREFIX...ACC_PHASE),
            # and we found matching accounts, we TRUST the account number match primarily.
            # Skip date filtering for ALL firms with a structural match — latest row always wins.
            skip_date_filter = matches_full_strict

            for e in candidates:
                if skip_date_filter:
                     # Trust the account match implicitly (all matches are suffix-based)
                     valid_candidates.append((e, 0))
                     continue

                dp_str = str(e.get('Date Started', '')) or str(e.get('Date Purchased', ''))
                try:
                    # Try common formats
                    dp_dt = None
                    for fmt in ["%m/%d/%y", "%Y-%m-%d", "%m/%d/%Y"]:
                        try:
                            dp_dt = datetime.datetime.strptime(dp_str, fmt)
                            break
                        except: pass
                    
                    if dp_dt:
                        diff = start_date_ts - dp_dt.timestamp()
                        # Allow session to start slightly before purchase? (Maybe same day timezone diff?)
                        # Allow -24h slack.
                        # BUFFER: If strict comment match, assume it's correct even if dates are weird?
                        # But typically we still want the LATEST one if duplications exist.
                        # Let's keep date logic but maybe relax it for strict matches?
                        if diff > -86400 * 2: # 48 hours buffer
                            valid_candidates.append((e, diff))
                    else:
                        # If no date found, but we have a STRICT digit match?
                        # Keep it as a candidate with high drift (unless only one candidate)
                         valid_candidates.append((e, float('inf')))
                except:
                    pass
            
            # Decision Time
            if not valid_candidates:
                # If we had a strict comment match, and no valid dates, maybe just pick the best text match?
                if matches_full_strict and candidates:
                     # Always prefer the latest row (highest eval_index)
                     best_eval = max(candidates, key=lambda e: evaluations.index(e))
                     match_log.append(f"⚠️ Date mismatch but strict ID match for {acc_num}, using latest row.")
                else:
                     match_log.append(f"⚠️ No valid date match for {acc_num}")
                     continue
            else:
                # Always prefer the latest row (highest eval_index = most recently added)
                # regardless of date proximity — the bigger the row number, the more recent the account
                best_eval = max(
                    [vc[0] for vc in valid_candidates],
                    key=lambda e: evaluations.index(e)
                )
                drift = next(vc[1] for vc in valid_candidates if vc[0] is best_eval)
                    
                logging.info(
                    f"[MATCHED EVAL] eval_idx={evaluations.index(best_eval)} "
                    f"account={acc_num} phase={best_phase} num={best_num} drift={drift}"
                )
            
            # Determined Field Name
            field_name = "Hedge Result" # Default
            
            # Use parsed phase/num from strict match if available
            if matches_full_strict: 
                 _, _, best_phase, best_num = full_comment_info
            
            if best_phase == 'CH':
                # CH1 -> Hedge Result 1
                # CH2 -> Hedge Result 2
                if best_num and best_num > 1:
                     field_name = f"Hedge Result {best_num}"
                else:
                     field_name = "Hedge Result 1" # Default to 'Hedge Result 1' to match sheet headers

            elif best_phase == 'FD':
                 # FD1 -> Hedge Result 1.1? Or just Hedge Result?
                 # User provided logic: "last part is the cell to put the data in" (CH2 -> HR2)
                 # Wait, for FD, existing logic says "Hedge Result 1.1" usually.
                 # Let's check get_field_name_for_phase implementation again if possible, or replicate:
                 if best_num is not None:
                      # MFFU logic: FD0->1.1, FD1->2.1? Or FD1->1.1?
                      # Standard implementation elsewhere:
                      # FD -> 1.1 usually means "Funded Account 1"
                      # Let's assume matches 1:1 if possible?
                      # Logic in get_field_name_for_phase (read earlier):
                      # "MFFU accounts: FD0->HR1.1, FD1->HR2.1"
                      # "Other: FD0/1 -> HR1.1"
                      
                      # Re-implement simplified version here:
                      normalized_prefix = (target_prefix or '').upper()
                      if 'MFFU' in normalized_prefix:
                           # MFFU Logic
                           # FD0 -> 1.1 ?? Wait, previous code said FD0->1.1, FD1->2.1
                           # Let's safer assume user wants mapped to *.1
                           # Map FD1 -> Hedge Result 1.1
                           # FD2 -> Hedge Result 2.1
                           if best_num == 0: field_name = "Hedge Result 1.1" # FD0 match
                           else: field_name = f"Hedge Result {best_num}.1"
                      else:
                           # Standard FD
                           field_name = f"Hedge Result {best_num}.1"

            elif best_phase == 'DD':
                 field_name = f"Hedge Result {best_num}.1"

            elif best_phase == 'FA':
                # --- FARMING: Count farming days from MT5 history, only update the LAST one ---
                # fa_account_days has ALL farming dates per account from full MT5 history.
                # Count distinct dates to know which Hedge Day slot the latest trade belongs to.
                # e.g. 5 farming days total → only write Hedge Day 5 with the latest day's profit.
                best_eval_idx = evaluations.index(best_eval)
                row_num = best_eval_idx + 2

                # --- Active account check: skip inactive evals for farming ---
                _s_p1 = str(best_eval.get('Status P1', '')).lower()
                _s_funded = str(best_eval.get('Status', '') or best_eval.get('Status Funded', '')).lower()
                _inactive_kw = ('fail', 'breach', 'sl', 'closed', 'delete')
                _is_inactive = (
                    any(kw in _s_p1 for kw in _inactive_kw) or
                    any(kw in _s_funded for kw in (*_inactive_kw, 'complete'))
                )
                if _is_inactive:
                    match_log.append(f"   ⏩ Skipping FA for inactive eval row {row_num} (P1='{_s_p1}', Funded='{_s_funded}')")
                    logging.info(f"[FA SKIP] eval_idx={best_eval_idx} inactive — P1='{_s_p1}' Funded='{_s_funded}'")
                    continue

                # Only write once per eval
                if best_eval_idx in fa_evals_written:
                    continue
                fa_evals_written.add(best_eval_idx)

                # Get this account's farming data from the pre-computed map
                # Pre-compute keys have prefix (e.g. "FNFT-76770"), but acc_num may be just digits ("76770")
                # Try exact match first, then substring fallback
                account_days = fa_account_days.get(acc_num, {})
                if not account_days:
                    # Substring match: find key where acc_num appears in it or it appears in acc_num
                    for _fa_key, _fa_days in fa_account_days.items():
                        if acc_num in _fa_key or _fa_key in acc_num:
                            account_days = _fa_days
                            logging.info(f"[FA WRITE] Matched acc_num={acc_num} to pre-computed key={_fa_key}")
                            break
                if not account_days:
                    logging.warning(f"[FA WRITE] No pre-computed farming data for account {acc_num} (eval_idx={best_eval_idx})")
                    continue

                # Sort dates chronologically — position = Hedge Day number
                sorted_dates = sorted(account_days.keys())
                total_farming_days = len(sorted_dates)
                last_date = sorted_dates[-1]
                last_profit = account_days[last_date]
                slot = total_farming_days  # e.g. 5 dates → Hedge Day 5

                if slot > 50:
                    logging.warning(f"[FA WRITE] eval_idx={best_eval_idx} has {slot} farming days, capping at 50")
                    slot = 50

                field_name = f'Hedge Day {slot}'

                best_eval[field_name] = f'{last_profit:.2f}'
                best_eval[f'_{field_name} Date'] = last_date
                updates_made += 1

                match_log.append(f"✅ 🌾 Row {row_num} | {field_name}: ${last_profit:.2f} ({last_date}) [day {slot} of {total_farming_days}]")
                logging.info(
                    f"[FA WRITE] row={row_num} account={acc_num} "
                    f"total_farming_days={total_farming_days} → {field_name}=${last_profit:.2f} date={last_date}"
                )

                # --- Write Prop Day values from Tradovate MNQ daily P&L ---
                if tradovate_farming_days:
                    tv_mnq_days = _match_tradovate_farming(tradovate_farming_days, acc_num)
                    if tv_mnq_days:
                        prop_days_written = 0
                        for day_idx, tv_day in enumerate(tv_mnq_days):
                            prop_slot = day_idx + 1
                            if prop_slot > 50:
                                break
                            best_eval[f'Prop Day {prop_slot}'] = f"{tv_day['net_pnl']:.2f}"
                            prop_days_written += 1
                        if prop_days_written:
                            match_log.append(
                                f"   ✅ 💰 Row {row_num} | Prop Days 1-{prop_days_written}: "
                                f"Tradovate MNQ P&L written"
                            )
                            logging.info(
                                f"[FA PROP DAY] row={row_num} account={acc_num} "
                                f"wrote {prop_days_written} Prop Day value(s) from Tradovate MNQ"
                            )
                    else:
                        logging.info(f"[FA PROP DAY] No matching Tradovate MNQ data for account {acc_num}")

                # --- Also add to trade_summary for logging ---
                try:
                    p_firm = best_eval.get('Prop Firm') or 'Unknown Firm'
                    report_acc = best_eval.get('Account #') or best_eval.get('Account #.1') or acc_num
                    phase_label = f"FA{best_num or ''}"
                    if p_firm not in trade_summary: trade_summary[p_firm] = {}
                    if report_acc not in trade_summary[p_firm]: trade_summary[p_firm][report_acc] = {}
                    if phase_label not in trade_summary[p_firm][report_acc]:
                        trade_summary[p_firm][report_acc][phase_label] = {
                            'profit': 0.0, 'trades': 0, 'source_accounts': set(),
                            'comments': set(), 'target_field': field_name,
                            'detailed_trades': [], 'row_index': row_num
                        }
                    sn = trade_summary[p_firm][report_acc][phase_label]
                    # Use the pre-computed last-date profit (what was actually written),
                    # NOT the session profit (which may come from the earliest session)
                    sn['profit'] = float(last_profit)
                    sn['trades'] = total_farming_days
                    sn['source_accounts'].add(str(acc_num))
                    sn['target_field'] = field_name
                    # Find the actual trade timestamp for the last farming date
                    _last_ts_str = last_date
                    for _fd in reversed(raw_deals):
                        _fp, _ = parse_comment(_fd.get('comment', ''))
                        if _fp == 'FA':
                            _fa_acc = extract_account_from_comment(_fd.get('comment', ''))
                            if _fa_acc and (acc_num in _fa_acc or _fa_acc in acc_num):
                                _fts = get_ts(_fd)
                                _fdate = datetime.datetime.fromtimestamp(_fts).strftime('%Y-%m-%d') if _fts > 0 else ''
                                if _fdate == last_date:
                                    _last_ts_str = datetime.datetime.fromtimestamp(_fts).strftime('%Y-%m-%d %H:%M:%S')
                                    break
                    sn['detailed_trades'] = [f"[{_last_ts_str}] [{session['deals'][0].get('comment', '')}] {acc_num} -> ${last_profit:.2f}"]
                except Exception as e:
                    logging.error(f"Error accumulating FA stats: {e}")

                continue  # Skip normal write logic — FA is handled above

            
            # Update Logic: ACCUMULATE profit for this push
            # Since we are processing all history in this push, we should sum up sessions for the same eval/field.
            # But be careful not to sum with existing OLD values from DB if we are replacing them?
            # Actually, update_evaluations... is called on the existing 'evaluations' list from DB.
            # If we just add, we might double count if we run this multiple times?
            # No, 'evaluations' object is transient for this request (loaded from DB/Sheet).
            # The 'session_profit' is from the NEW deals being pushed.
            # Users usually push ALL history.
            # So we should probably clear the field first if it's the first time we touch it IN THIS REQUEST?
            # Or just assume we are recalculating from scratch for these deals.
            
            # For robustness: valid numeric check (handle $ formatting)
            try:
                raw_val = str(best_eval.get(field_name, 0) or 0)
                clean_val = raw_val.replace('$', '').replace(',', '').strip()
                current_val = float(clean_val) if clean_val else 0.0
            except:
                current_val = 0.0
                
            # SPECIAL CASE: FundedNext (or others) where multiple evals share account?
            # The user said: "one account number belongs to several prop firm evaluations, this only happens for funded next"
            # "The rest should just push directly" 
            # If we touch the same field multiple times in this loop (multiple sessions for same eval), we MUST accumulate.
            # If the eval field already has value from previous pushes (DB), and we are pushing partial data?
            # Usually pushes contain full history.
            # Let's assume we accumulate.
            
            # However, if this is the FIRST time we are updating this specific field IN THIS BATCH,
            # and we want to overwrite old DB data with new calculation?
            # The 'evaluations' list comes from DB.
            # If we want to replace the old 'Hedge Result' with the new value from this push,
            # We should probably track which fields we've updated.
            
            # Key to track uniqueness: (Eval Index, Field Name)
            update_key = (candidates.index(best_eval) if best_eval in candidates else -1, field_name)
            
            # This is tricky because we don't have unique IDs easily accessible here without strict indexing
            # Let's rely on the object identity `id(best_eval)`
            
            eval_id = id(best_eval)
            
            # Simple aggregation logic: If it's the first time we see this field for this eval in THIS REQUEST,
            # we overwrite it (assuming full push). Subsequent sessions add to it.
            if '_updated_fields' not in best_eval:
                best_eval['_updated_fields'] = set()
            
            if field_name not in best_eval['_updated_fields']:
                new_val = session_profit
                best_eval['_updated_fields'].add(field_name)
            else:
                new_val = current_val + session_profit
            
            # Store clean numeric value (dashboard JS adds $ at display time)
            best_eval[field_name] = f"{new_val:.2f}"

            updates_made += 1
            if 'Match Log' not in best_eval:
                 best_eval['Match Log'] = []
            best_eval['Match Log'].append(f"Matched matched session (start {datetime.datetime.fromtimestamp(start_date_ts)}) -> {field_name}: ${float(session_profit):.2f} (Total: ${float(new_val):.2f})")
            
            # Add explicit cell confirmation log
            current_row_idx = evaluations.index(best_eval) + 2
            match_log.append(f"✅ Matched session (Start {datetime.datetime.fromtimestamp(start_date_ts)}) -> Column: [{field_name}] | Row: {current_row_idx} | New Value: ${new_val:.2f}")

            # --- AGGREGATE SUMMARY STATS ---
            try:
                # 1. Prop Firm
                # Uses col "Prop Firm" if exists, or guess from prefix
                p_firm = best_eval.get('Prop Firm') 
                if not p_firm:
                     # Try to guess from account number prefix or comments
                     guesser = normalize_acc(acc_num)
                     # Also check comments in session for clues if account number is ambiguous
                     session_comments = " ".join([d.get('comment', '') for d in session['deals'][:5]])
                     
                     if 'MFF' in guesser or 'MFF' in session_comments.upper(): p_firm = 'My Funded Futures'
                     elif 'V2' in guesser or 'V2' in session_comments.upper(): p_firm = 'Topstep'
                     elif 'FN' in guesser or 'FNFT' in session_comments.upper(): p_firm = 'FundedNext'
                     elif 'AF' in guesser or 'AFAD' in session_comments.upper(): p_firm = 'Alpha Futures'
                     else: p_firm = 'Unknown Firm'
                
                # 2. Account Number (Use the one from the evaluation record if possible for consistency)
                # "Account #" for Challenge or "Account #.1" for Funded
                # Or just use the Evaluation Index/Name to be clearer? 
                # User asked for "Account Number"
                report_acc = best_eval.get('Account #') or best_eval.get('Account #.1') or acc_num
                
                # 3. Phase Key (e.g. CH1, FD1)
                phase_label = f"{best_phase}{best_num or ''}"
                
                # InitDicts
                if p_firm not in trade_summary: trade_summary[p_firm] = {}
                if report_acc not in trade_summary[p_firm]: trade_summary[p_firm][report_acc] = {}
                if phase_label not in trade_summary[p_firm][report_acc]: 
                     trade_summary[p_firm][report_acc][phase_label] = {
                         'profit': 0.0, 
                         'trades': 0,
                         'source_accounts': set(), # The raw account number from mt5/comment
                         'comments': set(),        # Sample comments used for classification
                         'target_field': field_name,
                         'detailed_trades': [],    # List of specific trade details
                         'row_index': -1           # Will be set below
                     }
                
                # Add
                summary_node = trade_summary[p_firm][report_acc][phase_label]
                
                # Find row index (Add 2 because Sheet usually has headers, Python list is 0-indexed)
                try:
                    row_idx = evaluations.index(best_eval) + 2
                    summary_node['row_index'] = row_idx
                except:
                    summary_node['row_index'] = '??'

                summary_node['profit'] += float(session_profit)
                
                # Count only actual trade deals (exclude internal transfers)
                _session_trade_deals = [d for d in session['deals'] if not _is_internal_transfer(d)]
                summary_node['trades'] += len(_session_trade_deals)
                summary_node['source_accounts'].add(str(acc_num))
                
                # Add detailed trade info (only real trades)
                for d in _session_trade_deals:
                    t_profit = float(d.get('profit', 0))
                    t_comment = d.get('comment', '')
                    t_acc = extract_account_from_comment(t_comment) or "N/A"
                    
                    # Format timestamp
                    t_ts = get_ts(d)
                    t_time_str = "Unknown Time"
                    if t_ts > 0:
                        t_time_str = datetime.datetime.fromtimestamp(t_ts).strftime('%Y-%m-%d %H:%M:%S')

                    # Add to list (limit size if needed, but user asked for detail)
                    summary_node['detailed_trades'].append(f"[{t_time_str}] [{t_comment}] {t_acc} -> ${t_profit:.2f}")

                # Add sample comments (limit to 3 unique ones per phase to avoid spam)
                current_comments = [d.get('comment', '') for d in session['deals'] if d.get('comment')]
                for c in current_comments:
                    if len(summary_node['comments']) < 3:
                        summary_node['comments'].add(c)
                
            except Exception as e:
                logging.error(f"Error accumulating stats: {e}")
            # -------------------------------



        # CLEANUP: Remove temporary tracking fields before returning
        for ev in evaluations:
            if '_updated_fields' in ev:
                del ev['_updated_fields']
            if 'Match Log' in ev:
                del ev['Match Log']

        # --- LOG SUMMARY ---
        # "Group for me all trades under a specific propfirm, like topstep 2 trades etc, break it even further interms of the account number and phases"
        logging.info("="*30)
        logging.info(" TRADE PROCESSING SUMMARY")
        logging.info("="*30)
        
        # Sort firms
        sorted_firms = sorted(trade_summary.keys())
        for firm in sorted_firms:
             firm_data = trade_summary[firm]
             # Total trades for firm
             total_firm_trades = 0
             for acc_data in firm_data.values():
                 for stats in acc_data.values():
                     total_firm_trades += stats['trades']
                     
             logging.info(f"📂 {firm} ({total_firm_trades} trades)")
             
             sorted_accs = sorted(firm_data.keys(), key=lambda x: str(x))
             for acc in sorted_accs:
                  acc_data = firm_data[acc]
                  # Total trades for account
                  total_acc_trades = sum(item['trades'] for item in acc_data.values())
                  logging.info(f"   └── 👤 Dashboard Account: {acc} ({total_acc_trades} trades)")
                  
                  sorted_phases = sorted(acc_data.keys())
                  for phase in sorted_phases:
                       stats = acc_data[phase]
                       profit_str = f"${stats['profit']:,.2f}"
                       trades_count = stats['trades']
                       target_field = stats.get('target_field', 'Unknown')
                       
                       # Format comments and source accounts
                       sources_str = ", ".join(sorted(list(stats['source_accounts'])))
                       
                       row_idx = stats.get('row_index', '??')
                       
                       logging.info(f"       └── 🏷️  Phase {phase} -> [{target_field}] (Row #{row_idx})")
                       logging.info(f"           - Profit: {profit_str}")
                       logging.info(f"           - Trades: {trades_count}")
                       
                       # Detailed Trade Listing
                       count = 0
                       for t_detail in stats.get('detailed_trades', []):
                           logging.info(f"             - {t_detail}")
                           count += 1
                           if count > 50: # Safety limit
                               logging.info(f"             ... and {trades_count - 50} more")
                               break
                       
                       logging.info(f"           - Source ID(s): {sources_str}")
        logging.info("="*30)
        # -------------------

        # Return the computed sessions so they can be saved as 'aggregated_by_comment'
        return evaluations, match_log, sessions

    # -------------------------------------------------------------------------
    # LEGACY CLIENT-SIDE AGGREGATION LOGIC (Fallback)
    # -------------------------------------------------------------------------

    """
    Update evaluation hedge result fields from aggregated MT5 comment data.
    
    Args:
        evaluations: List of evaluation records
        aggregated_data: List of aggregated trade data with account_number, phase_code, etc.
    
    Returns:
        Tuple of (updated_evaluations, match_log)
    """
    if not evaluations or not aggregated_data:
        # If no server-side matching occurred (raw_deals was None), just return None for sessions
        return evaluations, ["No evaluations or aggregated data to process"], None
    
    match_log = []
    updates_made = 0
    
    match_log.append(f"📊 Processing {len(aggregated_data)} aggregated trade groups")
    match_log.append(f"   Against {len(evaluations)} evaluation records")
    
    # Sort aggregated data to ensure farming days are processed chronologically
    # Sort by account, then by timestamp (or farming_date)
    def sort_key(x):
        # Ensure consistent string type for comparison to avoid TypeError between float/str
        ts = x.get('timestamp') or x.get('farming_date') or ''
        return (
            str(x.get('account_number', '')),
            str(ts)
        )
    
    try:
        aggregated_data.sort(key=sort_key)
    except Exception as e:
        match_log.append(f"⚠️ Warning: Sorting failed ({str(e)}), processing unsorted.")
    
    # --- FNFT FILTERING LOGIC ---
    # For FundedNext accounts:
    # 1. Only process the active (latest) phase.
    # 2. Within that phase, only process the LATEST DAY (ignore prior history for same phase).
    
    # Map: account_sig -> (max_timestamp, (phase_code, trade_number))
    fnft_latest_phase_map = {} 
    
    # 1. Identify latest phase AND latest timestamp for that phase
    for agg in aggregated_data:
        acc = str(agg.get('account_number', '')).upper()
        if 'FNFT' in acc or 'FUNDEDNEXT' in acc:
            sig = get_account_signature(acc)
            ts = agg.get('timestamp') or 0
            
            # Update global max timestamp for account (determines active phase)
            curr_max_ts, curr_combo = fnft_latest_phase_map.get(sig, (0, None))
            
            if ts >= curr_max_ts:
                p_code = agg.get('phase_code')
                t_num = agg.get('trade_number')
                fnft_latest_phase_map[sig] = (ts, (p_code, t_num))

    # 2. Filter loop
    filtered_data = []
    for agg in aggregated_data:
        acc = str(agg.get('account_number', '')).upper()
        if 'FNFT' in acc or 'FUNDEDNEXT' in acc:
            sig = get_account_signature(acc)
            max_ts_global, latest_combo = fnft_latest_phase_map.get(sig, (0, None))
            
            this_combo = (agg.get('phase_code'), agg.get('trade_number'))
            this_ts = agg.get('timestamp') or 0
            this_phase_code = agg.get('phase_code', '')
            
            # Check 1: Is this the active phase?
            if latest_combo and this_combo != latest_combo:
                 match_log.append(f"⏩ FNFT: Skipping {acc} old phase {this_combo} (Active: {latest_combo})")
                 continue
            
            # Check 2: Age Check applied ONLY to Challenge (CH) phase
            # "only checking the current days trades will check this"
            if this_phase_code == 'CH':
                # Strictly filter to the "Current Day" (represented by max_ts_global).
                # We discard any data older than 18 hours from the latest timestamp.
                # This ensures we don't sum up "Old Reset" results (e.g. from 2 days ago)
                # with "New Reset" results (Today).
                AGE_THRESHOLD = 18 * 3600 # 18 hours (Current session only)
                time_diff = max_ts_global - this_ts
                
                if time_diff > AGE_THRESHOLD:
                     match_log.append(f"⏩ FNFT: Skipping {acc} old Challenge history {this_combo} (Age: {time_diff/3600:.1f}h)")
                     continue
            else:
                 # Pass through FA/FD/DD to allow standard logic as requested
                 pass

        filtered_data.append(agg)
        
    aggregated_data = filtered_data
    # ----------------------------

    # Track next available slot for Farming (FA) phase per evaluation
    # This ensures we overwrite from Day 1 sequentially instead of appending
    fa_slot_tracker = {}
    
    # Track accumulated values for standard phases (CH, FD, DD) because client now sends daily chunks
    # Key: (eval_idx, field_name) -> value
    accumulation_tracker = {}

    for agg in aggregated_data:
        account_number = agg.get('account_number', '')
        phase_code = agg.get('phase_code', '')
        trade_number = agg.get('trade_number')
        farming_date = agg.get('farming_date')
        net_profit = agg.get('net_profit', 0)
        deal_count = agg.get('deal_count', 0)
        
        if account_number and str(account_number).lower().startswith("unknown"):
             continue

        # Find matching evaluation
        matches = match_account_to_evaluation(account_number, evaluations, phase_code)
        
        # Use date filtering to pick the best match
        # Try to get timestamp from agg if available, otherwise it will fallback to first match
        trade_timestamp = agg.get('timestamp') 
        match = filter_matches_by_date(
            matches, 
            evaluations, 
            trade_timestamp, 
            phase_code=phase_code, 
            trade_number=trade_number
        )
        
        if not match:
            sig = get_account_signature(account_number)
            match_log.append(f"⚠️ No match: {account_number} ({sig}) _{phase_code}{trade_number or ''} = ${net_profit:.2f}")
            continue

        eval_idx, matched_account = match
        logging.info(f"MATCHED: MT5 Account {account_number} -> Dashboard Account {matched_account}")

        # Defense-in-depth: refuse to write into a row whose target account
        # column is blank or a placeholder ("—", "-", "n/a", etc.).  Catches
        # cases where a stale lookup or fuzzy match returns a row the user
        # has since wiped clean.
        _placeholders = {'', 'none', '-', '—', '–', 'n/a', 'na', 'tbd', 'pending'}
        _matched_norm = str(matched_account or '').strip().lower()
        if _matched_norm in _placeholders:
            match_log.append(
                f"🛑 Skipped write to row #{eval_idx}: target account is placeholder "
                f"'{matched_account}' (deal {account_number} _{phase_code}{trade_number or ''} = ${net_profit:.2f})"
            )
            continue
        # Also verify the actual eval row still has a real value in BOTH the
        # challenge and funded account columns being placeholders would mean
        # a wiped row that should never receive writes.
        _ev_check = evaluations[eval_idx] if 0 <= eval_idx < len(evaluations) else None
        if _ev_check is not None:
            _ch = str(_ev_check.get('Account #') or '').strip().lower()
            _fd = str(_ev_check.get('Account #.1') or '').strip().lower()
            if (_ch in _placeholders) and (_fd in _placeholders):
                match_log.append(
                    f"🛑 Skipped wiped row #{eval_idx}: both Account # cols are blank/placeholder "
                    f"(deal {account_number} _{phase_code}{trade_number or ''} = ${net_profit:.2f})"
                )
                continue
        
        # Determine field to update
        field_name = None
        
        if phase_code == 'FA':
            client_field_name = str(agg.get('field_name') or '').strip()
            client_slot = agg.get('_fa_slot')

            if client_field_name.startswith('Hedge Day '):
                field_name = client_field_name
            elif isinstance(client_slot, (int, float)) and client_slot > 0:
                field_name = f"Hedge Day {int(client_slot)}"
            else:
                # Fallback for older clients that do not send a pre-computed Hedge Day.
                current_slot = fa_slot_tracker.get(eval_idx, 1)
                field_name = f"Hedge Day {current_slot}"
                fa_slot_tracker[eval_idx] = current_slot + 1
        else:
            field_name = get_field_name_for_phase(phase_code, trade_number, farming_date, evaluations, eval_idx, account_number)
        
        if not field_name:
            match_log.append(f"⚠️ Unknown field for {phase_code}{trade_number or ''}")
            continue
        
        # Determine whether to Accumulate (CH, FD, DD) or Overwrite (FA)
        # UPDATE: FNFT Challenge (CH) should NOT accumulate if we are strictly enforcing "Current Day" in client.
        # However, checking 'is_fnft' here is tricky without context.
        # But wait - if we are now only sending today's data, accumulation of *just today's* trades is correct if they came in multiple chunks.
        # But we do NOT want to read the OLD value from DB and add to it.
        # The logic below `accumulation_tracker[key] = current_val + float(net_profit)` only sums up what is in `aggregated_data` (the current request/payload).
        # It does NOT pull from evaluations[eval_idx][field_name] first.
        # So it is effectively a "Fresh Sum of Payload".
        # This is correct behavior for "Current Day Only" payload.
        
        should_accumulate = phase_code in ['CH', 'FD', 'DD']

        # ── Honor manual user clears ──
        # If the user explicitly blanked this field on the dashboard, refuse to
        # repopulate it from re-aggregated MT5 history.  The clear is lifted
        # automatically when the user types a new value back into the cell
        # (see /api/update_data handler).
        _ev_for_clear = evaluations[eval_idx] if 0 <= eval_idx < len(evaluations) else None
        if _ev_for_clear is not None:
            _cleared_set = set(_ev_for_clear.get('_cleared_fields') or [])
            if field_name in _cleared_set:
                match_log.append(
                    f"🚫 Skipped manually-cleared cell: Eval #{eval_idx} [{field_name}] "
                    f"(would have been ${net_profit:.2f} from {account_number})"
                )
                continue

        if should_accumulate:
            # Add to accumulator (sums up multiple entries in SAME payload)
            key = (eval_idx, field_name)
            current_val = accumulation_tracker.get(key, 0.0)
            accumulation_tracker[key] = current_val + float(net_profit)
            
            # Log individual contribution
            # sig = get_account_signature(account_number)
            # match_log.append(f"   + {account_number} ({sig}) → [{field_name}] += ${net_profit:.2f}")
        else:
            # Direct overwrite (Farming)
            evaluations[eval_idx][field_name] = net_profit
            updates_made += 1
            sig = get_account_signature(account_number)
            match_log.append(f"✅ {account_number} ({sig}) _{phase_code}{trade_number or ''} → [{field_name}] = ${net_profit:.2f}")
            match_log.append(f"   Matched to: {matched_account}")
            
    # Apply accumulated updates
    for (eval_idx, field_name), total_profit in accumulation_tracker.items():
        evaluations[eval_idx][field_name] = total_profit
        updates_made += 1
        # Log the final total update
        # We can't easily show which account number triggered it if multiple did, but usually it's one.
        match_log.append(f"✅ [Accumulated] → Eval #{eval_idx} [{field_name}] = ${total_profit:.2f}")
    
    match_log.append(f"\n📈 Total updates: {updates_made}/{len(aggregated_data)}")
    return evaluations, match_log, None

# Initialize admin password if not exists
def init_admin_password():
    """Initialize default admin password only if not already set."""
    if not admin_password_exists('super_admin'):
        admin_password = os.getenv('ADMIN_PASSWORD', 'BallerAdmin@123')
        set_admin_password('super_admin', admin_password)
        print("super_admin password initialized")
    # BEF Admin - separate credentials, restricted to BEF clients only
    if not admin_password_exists('bef_admin'):
        bef_password = os.getenv('BEF_ADMIN_PASSWORD', 'BEFAdmin@123')
        set_admin_password('bef_admin', bef_password)
        print("bef_admin password initialized")
    # Kwok admin: set explicitly on startup so the password is predictable for demos.
    # Override via KWOK_ADMIN_PASSWORD env var.
    kwok_password = os.getenv('KWOK_ADMIN_PASSWORD', '123@kwok_admin')
    set_admin_password('kwok_admin', kwok_password)
    print("kwok_admin password set/updated")

# Run initialization
init_database()

init_admin_password()

def provision_hierarchy_passwords():
    """Auto-create or reset user_credentials with default password for hierarchy users."""
    default_pw = 'Test@123'
    created = 0
    reset = 0

    def ensure_password(name, utype, email=None, parent_admin=None, parent_trader=None):
        nonlocal created, reset
        if not user_exists(name, utype):
            if create_user(name, default_pw, utype, email, parent_admin, parent_trader):
                created += 1
        else:
            # Reset password for users who have never logged in (still have old random pw)
            existing = get_user(name, utype)
            if existing and not existing.get('last_login'):
                if update_user_password(name, utype, default_pw):
                    reset += 1

    for admin_name, admin_data in hierarchy.get('admins', {}).items():
        ensure_password(admin_name, 'admin', admin_data.get('email'))
        for trader_name, trader_data in admin_data.get('traders', {}).items():
            ensure_password(trader_name, 'trader', trader_data.get('email'), admin_name)
            for client in trader_data.get('clients', []):
                c_name = client.get('name') if isinstance(client, dict) else client
                c_email = client.get('email', '') if isinstance(client, dict) else ''
                ensure_password(c_name, 'client', c_email, admin_name, trader_name)
    if created or reset:
        print(f"[AUTH] Provisioned {created} new, reset {reset} existing users to default password")

# Check DB integrity before provisioning (catches corrupt DB on startup)
try:
    _db_ok, _db_msg = check_and_repair_database()
    if not _db_ok:
        print(f"[STARTUP] WARNING: DB integrity check/repair failed: {_db_msg}")
    else:
        print(f"[STARTUP] {_db_msg}")
except Exception as _db_exc:
    print(f"[STARTUP] WARNING: DB check raised: {_db_exc}")

# Run password provisioning in background thread so it doesn't block WSGI startup
def _bg_provision():
    try:
        provision_hierarchy_passwords()
    except Exception as _prov_exc:
        print(f"[STARTUP] WARNING: provision_hierarchy_passwords failed: {_prov_exc}")

threading.Thread(target=_bg_provision, daemon=True).start()
print("[STARTUP] Background provisioning thread started, continuing module load...")

# ============ Authentication Decorators ============

def require_api_key(f):
    """Decorator to require valid API key for endpoint access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        client_ip = get_remote_address()
        
        if not api_key:
            log_action('API_ACCESS_DENIED', 'unknown', 'no_key', client_ip, 'Missing API key', False)
            return jsonify({"status": "error", "message": "API key required"}), 401
        
        try:
            user_info = validate_api_key(api_key)
        except Exception:
            app.logger.exception('[AUTH] validate_api_key raised — DB may be corrupt')
            return jsonify({"status": "error", "message": "Service temporarily unavailable"}), 503
        if not user_info:
            log_action('API_ACCESS_DENIED', 'unknown', api_key[:12], client_ip, 'Invalid API key', False)
            return jsonify({"status": "error", "message": "Invalid API key"}), 403
        
        # Reject read-only keys from full-access endpoints
        if user_info.get('scope') == 'readonly':
            log_action('API_ACCESS_DENIED', 'unknown', api_key[:12], client_ip, 'Readonly key on full-access endpoint', False)
            return jsonify({"status": "error", "message": "This API key is read-only and cannot access this endpoint"}), 403
        
        # Add user info to request context
        request.api_user = user_info
        log_action('API_ACCESS', 'trader', user_info.get('trader', 'unknown'), client_ip, f"Endpoint: {request.endpoint}")
        return f(*args, **kwargs)
    return decorated_function

def require_admin_password(f):
    """Decorator to require admin password for endpoint access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_ip = get_remote_address()
        
        # Check for password in request body or headers
        admin_password = None
        if request.is_json:
            admin_password = request.json.get('admin_password')
        if not admin_password:
            admin_password = request.headers.get('X-Admin-Password')
        
        if not admin_password:
            log_action('ADMIN_ACCESS_DENIED', 'admin', 'unknown', client_ip, 'Missing password', False)
            return jsonify({"status": "error", "message": "Admin password required"}), 401
        
        if not verify_admin_password('super_admin', admin_password):
            log_action('ADMIN_ACCESS_DENIED', 'admin', 'super_admin', client_ip, 'Invalid password', False)
            return jsonify({"status": "error", "message": "Invalid admin password"}), 403
        
        log_action('ADMIN_ACCESS', 'admin', 'super_admin', client_ip, f"Endpoint: {request.endpoint}")
        return f(*args, **kwargs)
    return decorated_function

def require_role(*allowed_roles):
    """Decorator to require specific roles via session authentication."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            session_token = request.cookies.get('session_token')
            
            if not session_token:
                return jsonify({"status": "error", "message": "Authentication required"}), 401
            
            session_info = validate_session(session_token)
            if not session_info:
                return jsonify({"status": "error", "message": "Invalid or expired session"}), 401
            
            user_type = session_info.get('user_type')
            if user_type not in allowed_roles:
                log_action('ACCESS_DENIED', user_type, session_info.get('user_identifier'), 
                          get_remote_address(), f"Required roles: {allowed_roles}", False)
                return jsonify({"status": "error", "message": "Access denied. Insufficient permissions."}), 403
            
            request.session_user = session_info
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_session(f):
    """Decorator to require valid session for web access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = request.cookies.get('session_token')

        if not session_token:
            return redirect(url_for('index'))

        try:
            session_info = validate_session(session_token)
        except Exception:
            app.logger.exception('[AUTH] validate_session raised — DB may be corrupt, redirecting to login')
            return redirect(url_for('index'))

        if not session_info:
            return redirect(url_for('index'))

        request.session_user = session_info
        return f(*args, **kwargs)
    return decorated_function

# ============ Web Routes ============

@app.context_processor
def inject_home_url():
    """Inject home_url into every template so the logo can link to the user's home page."""
    try:
        session_token = request.cookies.get('session_token')
        if session_token:
            session_info = validate_session(session_token)
            if session_info:
                user_type = session_info.get('user_type', '')
                user_id = session_info.get('user_identifier', '')
                if user_type == 'super_admin':
                    return {'home_url': '/super_admin'}
                elif user_type == 'bef_admin':
                    return {'home_url': '/bef_admin'}
                elif user_type == 'kwok_admin':
                    return {'home_url': '/kwok_admin'}
                elif user_type == 'admin':
                    return {'home_url': f'/admin/{user_id}'}
                elif user_type == 'trader':
                    return {'home_url': f'/trader/{user_id}'}
                elif user_type == 'client':
                    return {'home_url': f'/dashboard/{user_id}'}
    except Exception:
        pass
    return {'home_url': '/'}

# ============ Maintenance Mode ============
# Set to True to show maintenance page to clients only
MAINTENANCE_MODE = False
MAINTENANCE_EXEMPT = {'super_admin', 'bef_admin', 'kwok_admin', 'admin', 'trader'}

@app.route('/maintenance')
def maintenance_page():
    session_token = request.cookies.get('session_token')
    if session_token:
        try:
            session_info = validate_session(session_token)
            if session_info and session_info.get('user_type') in MAINTENANCE_EXEMPT:
                user_type = session_info.get('user_type')
                user_id = session_info.get('user_identifier')
                if user_type == 'super_admin':
                    return redirect('/super_admin')
                elif user_type == 'bef_admin':
                    return redirect('/bef_admin')
                elif user_type == 'kwok_admin':
                    return redirect('/kwok_admin')
                elif user_type == 'admin':
                    return redirect(f'/admin/{user_id}')
                elif user_type == 'trader':
                    return redirect(f'/trader/{user_id}')
        except Exception:
            pass
    return render_template('maintenance.html')

@app.route('/')
def index():
    # Check if already logged in
    session_token = request.cookies.get('session_token')
    if session_token:
        session_info = validate_session(session_token)
        if session_info:
            # Redirect to appropriate dashboard
            user_type = session_info.get('user_type')
            user_id = session_info.get('user_identifier')
            if user_type == 'super_admin':
                return redirect('/super_admin')
            elif user_type == 'bef_admin':
                return redirect('/bef_admin')
            elif user_type == 'kwok_admin':
                return redirect('/kwok_admin')
            elif user_type == 'admin':
                return redirect(f'/admin/{user_id}')
            elif user_type == 'trader':
                return redirect(f'/trader/{user_id}')
            elif user_type == 'client':
                if MAINTENANCE_MODE:
                    return redirect('/maintenance')
                return redirect(f'/dashboard/{user_id}')
    return render_template('login.html')

@app.route('/super_admin')
@require_session
def super_admin():
    if request.session_user.get('user_type') != 'super_admin':
        return redirect('/')
    return render_template('super_admin.html', is_bef_admin=False, is_kwok_admin=False)

@app.route('/bef_admin')
@require_session
def bef_admin():
    if request.session_user.get('user_type') != 'bef_admin':
        return redirect('/')
    return render_template(
        'super_admin.html', user_role='bef_admin', is_bef_admin=True, is_kwok_admin=False)

@app.route('/showcase_admin')
def showcase_admin_legacy_redirect():
    """Old URL/bookmarks from the previous role name."""
    return redirect('/kwok_admin', code=308)


@app.route('/kwok_admin')
@require_session
def kwok_admin():
    if request.session_user.get('user_type') != 'kwok_admin':
        return redirect('/')
    return render_template(
        'super_admin.html', user_role='kwok_admin', is_bef_admin=False, is_kwok_admin=True)

@app.route('/quality_dashboard')
@require_session
def quality_dashboard():
    if request.session_user.get('user_type') not in ('super_admin',):
        return redirect('/')
    return render_template('quality_dashboard.html')

@app.route('/admin/<admin_name>')
@require_session
def admin_dashboard(admin_name):
    session_user = request.session_user
    # Allow super_admin, bef_admin, and kwok_admin to access admin dashboards
    if session_user.get('user_type') in ('super_admin', 'bef_admin', 'kwok_admin'):
        ut = session_user.get('user_type')
        return render_template('admin_dashboard.html', admin_name=admin_name,
                               is_bef_admin=(ut == 'bef_admin'),
                               is_kwok_admin=(ut == 'kwok_admin'))
    # Check if user is the correct admin
    if session_user.get('user_type') != 'admin' or session_user.get('user_identifier') != admin_name:
        return redirect('/')
    return render_template('admin_dashboard.html', admin_name=admin_name)

@app.route('/financial_overview')
@require_session
def financial_overview():
    session_user = request.session_user
    if session_user.get('user_type') not in ('super_admin', 'bef_admin', 'kwok_admin'):
         return redirect('/')
    
    profile_filter = request.args.get('profile', 'ALL')
    # BEF admin always sees only BEF profile
    if session_user.get('user_type') == 'bef_admin':
        profile_filter = 'BEF'
    # Kwok admin: consolidated view only (no BEF / Private slice in UI or via ?profile=)
    if session_user.get('user_type') == 'kwok_admin':
        profile_filter = 'ALL'
    
    # Date filtering
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    start_date = None
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        except:
            pass
            
    end_date = None
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        except:
            pass
    
    # NEW: Use optimized single-pass aggregator
    all_data = calculate_all_financials(profile_filter=profile_filter, start_date=start_date, end_date=end_date)
    
    overview_data = all_data['overview']
    global_stats = all_data.get('global_stats', {})

    # Card totals from cashflow_inprogress (same source as BEF admin dashboard)
    perf_clients = get_client_performance_stats(profile_filter, start_date=start_date, end_date=end_date)
    card_totals = {
        'payouts': round(sum(c.get('payouts', 0) for c in perf_clients), 2),
        'deposits': round(sum(c.get('deposits', 0) for c in perf_clients), 2),
        'fees': round(sum(c.get('fees', 0) for c in perf_clients), 2),
        'net_profit': round(sum(c.get('net_profit', 0) for c in perf_clients), 2),
        'hedge': round(sum(c.get('hedge_profit', 0) for c in perf_clients), 2),
        'active': sum(c.get('active', 0) for c in perf_clients),
        'passed': sum(c.get('passed', 0) for c in perf_clients),
        'failed': sum(c.get('failed', 0) for c in perf_clients),
    }
    t_ended = sum(c.get('ended', 0) for c in perf_clients)
    t_duration = sum(c.get('total_duration_days', 0) for c in perf_clients)
    card_totals['ev'] = round(card_totals['net_profit'] / t_ended, 2) if t_ended > 0 else 0.0
    card_totals['ev_day'] = round(card_totals['net_profit'] / t_duration, 2) if t_duration > 0 else 0.0

    # Hide restricted firms from BEF admin only (Kwok admin sees full firm set for demos)
    if session_user.get('user_type') == 'bef_admin':
        overview_data = {k: v for k, v in overview_data.items()
                         if k.lower().replace(' ', '') not in BEF_HIDDEN_FIRMS}

    growth_dates, growth_values = all_data['growth']
    payouts_dates, payouts_values = all_data['payouts']
    net_profit_dates, net_profit_values = all_data['net_profit']
    deposits_dates, deposits_values = all_data['deposits']
    fees_dates, fees_values = all_data['fees']
    hedge_dates, hedge_values = all_data['hedge']
    farming_dates, farming_values = all_data['farming']
    
    return render_template('financial_overview.html', 
                           overview=overview_data,
                           global_stats=global_stats,
                           card_totals=card_totals,
                           selected_profile=profile_filter,
                           start_date=start_date_str,
                           end_date=end_date_str,
                           is_bef_admin=(session_user.get('user_type') == 'bef_admin'),
                           is_kwok_admin=(session_user.get('user_type') == 'kwok_admin'),
                           growth_dates=growth_dates,
                           growth_values=growth_values,
                           payouts_dates=payouts_dates,
                           payouts_values=payouts_values,
                           net_profit_dates=net_profit_dates,
                           net_profit_values=net_profit_values,
                           deposits_dates=deposits_dates,
                           deposits_values=deposits_values,
                           fees_dates=fees_dates,
                           fees_values=fees_values,
                           hedge_dates=hedge_dates,
                           hedge_values=hedge_values,
                           farming_dates=farming_dates,
                           farming_values=farming_values)

@app.route('/payout_history')
@require_session
def payout_history():
    session_user = request.session_user
    if session_user.get('user_type') not in ('super_admin', 'bef_admin', 'kwok_admin'):
         return redirect('/')

    # Filter dates
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    start_date = None
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        except:
            pass
            
    end_date = None
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        except:
            pass

    prop_firm_filter = request.args.get('prop_firm')
    profile_filter = request.args.get('profile', 'ALL')
    
    # BEF admin always sees only BEF profile
    if session_user.get('user_type') == 'bef_admin':
        profile_filter = 'BEF'
    if session_user.get('user_type') == 'kwok_admin':
        profile_filter = 'ALL'
    # We need overview data just to get the list of prop firms for the dropdown
    overview_data = calculate_propfirm_overview()
    sorted_prop_firms = sorted(overview_data.keys())
    
    # Hide restricted firms from BEF admin
    if session_user.get('user_type') == 'bef_admin':
        sorted_prop_firms = [f for f in sorted_prop_firms if f.lower().replace(' ', '') not in BEF_HIDDEN_FIRMS]
    
    payouts_list = get_payouts_history(start_date, end_date, prop_firm_filter, profile_filter=profile_filter)
    
    # Filter payout entries for BEF admin
    if session_user.get('user_type') == 'bef_admin':
        payouts_list = [p for p in payouts_list if p.get('prop_firm', '').lower().replace(' ', '') not in BEF_HIDDEN_FIRMS]
    
    return render_template('payout_history.html', 
                           payouts=payouts_list,
                           start_date=start_date_str,
                           end_date=end_date_str,
                           selected_prop_firm=prop_firm_filter,
                           selected_profile=profile_filter,
                           is_bef_admin=(session_user.get('user_type') == 'bef_admin'),
                           is_kwok_admin=(session_user.get('user_type') == 'kwok_admin'),
                           prop_firms=sorted_prop_firms)

@app.route('/client_performance')
@require_session
def client_performance():
    session_user = request.session_user
    if session_user.get('user_type') == 'kwok_admin':
        return redirect('/kwok_admin')
    if session_user.get('user_type') not in ('super_admin', 'bef_admin'):
         return redirect('/')
    ut = session_user.get('user_type')
    return render_template('client_performance.html', is_bef_admin=(ut == 'bef_admin'),
                           is_kwok_admin=False)

@app.route('/trader_performance')
@require_session
def trader_performance():
    session_user = request.session_user
    if session_user.get('user_type') == 'kwok_admin':
        return redirect('/kwok_admin')
    if session_user.get('user_type') not in ('super_admin', 'bef_admin'):
         return redirect('/')
         
    profile_filter = request.args.get('profile', 'ALL')
    # BEF admin always sees only BEF profile
    if session_user.get('user_type') == 'bef_admin':
        profile_filter = 'BEF'
    traders_data = calculate_trader_stats(profile_filter=profile_filter)
    ut = session_user.get('user_type')
    return render_template('trader_performance.html', traders=traders_data, selected_profile=profile_filter,
                           is_bef_admin=(ut == 'bef_admin'), is_kwok_admin=(ut == 'kwok_admin'))


@app.route('/trader/<trader_name>')
@require_session
def trader_dashboard(trader_name):
    session_user = request.session_user
    # Resolve trader email + parent admin for admin actions (reset/delete)
    try:
        from config.hierarchy import reload_hierarchy
        reload_hierarchy()
    except Exception:
        pass
    trader_email = ''
    trader_admin = ''
    try:
        trader_email = (SYSTEM_HIERARCHY.get('traders', {}) or {}).get(trader_name, {}).get('email', '') or ''
        for admin_name, admin_data in (SYSTEM_HIERARCHY.get('admins', {}) or {}).items():
            traders = (admin_data or {}).get('traders', {}) or {}
            if trader_name in traders:
                trader_admin = admin_name
                trader_email = trader_email or (traders.get(trader_name, {}) or {}).get('email', '') or ''
                break
    except Exception:
        trader_email = trader_email or ''
        trader_admin = trader_admin or ''
    # Allow super_admin, bef_admin, and kwok_admin to access trader dashboards
    if session_user.get('user_type') in ('super_admin', 'bef_admin', 'kwok_admin'):
        ut = session_user.get('user_type')
        return render_template('trader_dashboard.html', trader_name=trader_name,
                               trader_email=trader_email, trader_admin=trader_admin,
                               is_super_admin=(ut == 'super_admin'),
                               is_bef_admin=(ut == 'bef_admin'),
                               is_kwok_admin=(ut == 'kwok_admin'))
    # Allow admin to access traders under them
    if session_user.get('user_type') == 'admin':
        return render_template('trader_dashboard.html', trader_name=trader_name,
                               trader_email=trader_email, trader_admin=trader_admin,
                               is_super_admin=False)
    # Check if user is the correct trader
    if session_user.get('user_type') != 'trader' or session_user.get('user_identifier') != trader_name:
        return redirect('/')
    return render_template('trader_dashboard.html', trader_name=trader_name,
                           trader_email=trader_email, trader_admin=trader_admin,
                           is_super_admin=False)

@app.route('/dashboard/<client_id>')
@require_session
def client_dashboard(client_id):
    session_user = request.session_user
    user_type = session_user.get('user_type')
    
    # Get client email and active status for dashboard
    client_email = ''
    is_active = True
    client_data = get_client_data(client_id)
    if client_data and client_data.get('identity'):
        client_email = client_data['identity'].get('email', '')
        is_active = client_data['identity'].get('active_status', 'active') != 'inactive'
    
    # Look up the client's parent trader and admin for display in reports
    _profile = get_client_profile(client_id) or {}
    client_trader_name = _profile.get('trader', '')
    client_admin_name = _profile.get('admin', '')
    # Look up admin's Slack member ID for direct tagging
    _admin_data = SYSTEM_HIERARCHY.get('admins', {}).get(client_admin_name, {})
    client_admin_slack_id = _admin_data.get('slack_user_id', '')

    # Allow super_admin, bef_admin, kwok_admin, admin, and trader to access client dashboards
    if user_type in ['super_admin', 'bef_admin', 'kwok_admin', 'admin', 'trader']:
        # BEF admin can only access BEF-category clients
        if user_type == 'bef_admin' and not can_access_client('bef_admin', None, client_id):
            return redirect('/bef_admin')
        can_edit = user_type != 'kwok_admin'
        return render_template('index.html', client_id=client_id, user_type=user_type, 
                               can_edit_hedging=can_edit, client_email=client_email, is_active=is_active,
                               client_trader_name=client_trader_name, client_admin_name=client_admin_name,
                               client_admin_slack_id=client_admin_slack_id)
    # Client access: allow own dashboard OR primary KYC can view linked accounts
    if user_type == 'client':
        own_name = session_user.get('user_identifier')
        if client_id == own_name:
            return render_template('index.html', client_id=client_id, user_type=user_type, 
                                   can_edit_hedging=True, client_email=client_email, is_active=is_active,
                                   client_trader_name=client_trader_name, client_admin_name=client_admin_name,
                                   client_admin_slack_id=client_admin_slack_id)
        # Only primary KYC clients can view linked accounts
        if is_kyc_primary(own_name) and client_id in get_all_kyc_accounts(own_name):
            return render_template('index.html', client_id=client_id, user_type=user_type, 
                                   can_edit_hedging=True, client_email=client_email, is_active=is_active,
                                   client_trader_name=client_trader_name, client_admin_name=client_admin_name,
                                   client_admin_slack_id=client_admin_slack_id)
    return redirect('/')

# ============ Hierarchy API with Role-Based Access Control ============

def _normalized_client_key(value):
    return ' '.join(str(value or '').replace('\u00A0', ' ').split()).strip().lower()


def _find_client_in_hierarchy(client_name):
    """Return (admin, trader, client_obj) for a client, matching normalized names."""
    target = _normalized_client_key(client_name)
    if not target:
        return None

    for admin_name, admin_data in (SYSTEM_HIERARCHY.get('admins', {}) or {}).items():
        for trader_name, trader_data in ((admin_data or {}).get('traders', {}) or {}).items():
            for client in (trader_data or {}).get('clients', []) or []:
                name = client.get('name') if isinstance(client, dict) else client
                if _normalized_client_key(name) == target:
                    return admin_name, trader_name, client
    return None


def _client_identity_details(client_name):
    """Best-effort email/category lookup for hierarchy repair rows."""
    details = {'email': '', 'category': ''}
    try:
        user = get_user(client_name, 'client') or {}
        details['email'] = (user.get('email') or '').strip()
    except Exception:
        pass

    try:
        data = get_client_data(client_name) or {}
        identity = data.get('identity') if isinstance(data, dict) else {}
        if isinstance(identity, dict):
            details['email'] = details['email'] or (identity.get('email') or '').strip()
            details['category'] = (
                identity.get('category') or identity.get('profile') or ''
            ).strip()
    except Exception:
        pass
    return details


def _ensure_client_database_membership(client_name, admin_name, trader_name, email='', category=''):
    """Keep hierarchy clients represented in auth and clients_data."""
    name = ' '.join(str(client_name or '').split()).strip()
    if not name:
        return

    email = (email or '').strip()
    category = (category or '').strip()
    identity = {}
    existing = None
    try:
        existing = get_client_data(name)
        if isinstance(existing, dict) and isinstance(existing.get('identity'), dict):
            identity = dict(existing.get('identity') or {})
    except Exception:
        identity = {}

    desired = {
        'name': identity.get('name') or name,
        'client': identity.get('client') or name,
        'email': email or identity.get('email', ''),
        'category': category or identity.get('category', ''),
        'profile': category or identity.get('profile') or identity.get('category', ''),
        'source': category or identity.get('source') or 'Private',
        'admin': admin_name,
        'trader': trader_name,
        'active_status': identity.get('active_status') or 'active',
    }
    next_identity = {**identity, **desired}
    if not existing or any(identity.get(k) != v for k, v in desired.items()):
        update_client_field(name, 'identity', next_identity)

    try:
        user = get_user(name, 'client')
        if user:
            needs_credential_update = (
                (email and (user.get('email') or '') != email)
                or (user.get('parent_admin') or '') != admin_name
                or (user.get('parent_trader') or '') != trader_name
            )
            if not needs_credential_update:
                return
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''UPDATE user_credentials
                       SET email = COALESCE(NULLIF(?, ''), email),
                           parent_admin = ?,
                           parent_trader = ?,
                           updated_at = ?
                       WHERE username = ? AND user_type = 'client' ''',
                    (email, admin_name, trader_name, datetime.now().isoformat(), name)
                )
                conn.commit()
        else:
            create_user(name, 'Test@123', 'client', email, admin_name, trader_name)
    except Exception as exc:
        print(f"[hierarchy_sync] client credential sync failed for {name}: {exc}")


def _remove_client_from_hierarchy_anywhere(client_name, admin_name='', trader_name=''):
    """Remove a client from hierarchy, using exact parent first then normalized global search."""
    target = _normalized_client_key(client_name)
    if not target:
        return False

    removed = False
    admins = SYSTEM_HIERARCHY.get('admins', {}) or {}

    def _remove_from_trader(a_name, t_name):
        nonlocal removed
        trader_data = ((admins.get(a_name) or {}).get('traders', {}) or {}).get(t_name)
        if not trader_data:
            return
        clients = trader_data.get('clients', []) or []
        kept = []
        for client in clients:
            name = client.get('name') if isinstance(client, dict) else client
            if _normalized_client_key(name) == target:
                removed = True
                continue
            kept.append(client)
        trader_data['clients'] = kept

    if admin_name and trader_name:
        _remove_from_trader(admin_name, trader_name)

    if not removed:
        for a_name, a_data in admins.items():
            for t_name in ((a_data or {}).get('traders', {}) or {}).keys():
                _remove_from_trader(a_name, t_name)

    if removed:
        save_hierarchy(SYSTEM_HIERARCHY)
    return removed


def _delete_kyc_links_for_client(client_name):
    """Remove KYC relationships so deleted clients are not re-created by sync."""
    name = ' '.join(str(client_name or '').split()).strip()
    if not name:
        return 0
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM kyc_links WHERE primary_client = ? OR linked_client = ?',
                (name, name)
            )
            deleted = cursor.rowcount or 0
            conn.commit()
            return deleted
    except Exception as exc:
        print(f"[delete_user] KYC link cleanup failed for {name}: {exc}")
        return 0


def _delete_client_everywhere(client_name, admin_name='', trader_name=''):
    """Delete a client from hierarchy, KYC links, auth credentials, and data tables."""
    name = ' '.join(str(client_name or '').split()).strip()
    if not name:
        return False

    removed_hierarchy = _remove_client_from_hierarchy_anywhere(name, admin_name, trader_name)
    deleted_kyc = _delete_kyc_links_for_client(name)
    deleted_credentials = delete_user_credential(name, 'client')
    delete_client_data(name)

    return bool(removed_hierarchy or deleted_kyc or deleted_credentials)


def sync_kyc_links_into_hierarchy():
    """
    Ensure KYC-linked accounts are real hierarchy clients too.

    KYC links grant dashboard access, but trader/admin dashboards and user
    management are sourced from hierarchy.json. If a linked account is missing
    there, attach it to the same admin/trader as its primary account.
    """
    try:
        links = get_all_kyc_links() or []
    except Exception:
        return False

    changed = False
    for link in links:
        primary = ' '.join(str(link.get('primary_client') or '').split()).strip()
        linked = ' '.join(str(link.get('linked_client') or '').split()).strip()
        if not primary or not linked or _normalized_client_key(primary) == _normalized_client_key(linked):
            continue
        linked_details = _client_identity_details(linked)
        linked_location = _find_client_in_hierarchy(linked)
        if linked_location:
            link_admin, link_trader, linked_client = linked_location
            linked_category = linked_details.get('category', '')
            if isinstance(linked_client, dict):
                if linked_details.get('email') and not (linked_client.get('email') or '').strip():
                    linked_client['email'] = linked_details['email']
                    changed = True
                if linked_details.get('category') and not (linked_client.get('category') or '').strip():
                    linked_client['category'] = linked_details['category']
                    changed = True
                linked_category = linked_client.get('category') or linked_category
            _ensure_client_database_membership(
                linked,
                link_admin,
                link_trader,
                linked_details.get('email') or (linked_client.get('email') if isinstance(linked_client, dict) else ''),
                linked_category,
            )
            continue

        primary_location = _find_client_in_hierarchy(primary)
        if not primary_location:
            continue

        admin_name, trader_name, primary_client = primary_location
        admin_data = (SYSTEM_HIERARCHY.get('admins', {}) or {}).get(admin_name, {})
        trader_data = (admin_data.get('traders', {}) or {}).get(trader_name)
        if not trader_data:
            continue

        primary_category = ''
        if isinstance(primary_client, dict):
            primary_category = (primary_client.get('category') or primary_client.get('profile') or '').strip()
        trader_data.setdefault('clients', []).append({
            'name': linked,
            'email': linked_details.get('email', ''),
            'category': linked_details.get('category') or primary_category,
        })
        _ensure_client_database_membership(
            linked,
            admin_name,
            trader_name,
            linked_details.get('email', ''),
            linked_details.get('category') or primary_category,
        )
        changed = True

    if changed:
        save_hierarchy(SYSTEM_HIERARCHY)
    return changed


def get_filtered_hierarchy(user_type, user_identifier):
    """
    Returns hierarchy filtered based on user role:
    - super_admin: sees everything
    - admin: sees only their traders and clients
    - trader: sees only their clients
    - client: sees only themselves
    """
    full_hierarchy = hierarchy
    
    if user_type == 'super_admin':
        return full_hierarchy

    if user_type == 'kwok_admin':
        # Full client list for demos, without exposing super-admin hierarchy editing UI
        return full_hierarchy
    
    if user_type == 'bef_admin':
        # BEF admin sees full hierarchy but filtered to only BEF-category clients
        filtered_admins = {}
        for admin_name, admin_data in full_hierarchy.get('admins', {}).items():
            filtered_traders = {}
            for trader_name, trader_data in admin_data.get('traders', {}).items():
                bef_clients = [
                    c for c in trader_data.get('clients', [])
                    if (c.get('category') or '').upper() == 'BEF'
                ]
                if bef_clients:
                    filtered_traders[trader_name] = {
                        'email': trader_data.get('email', ''),
                        'clients': bef_clients
                    }
            if filtered_traders:
                filtered_admins[admin_name] = {
                    'email': admin_data.get('email', ''),
                    'traders': filtered_traders
                }
        return {'admins': filtered_admins}
    
    if user_type == 'admin':
        # Admin sees only their own data (case-insensitive match)
        admin_name = user_identifier
        admin_name_lower = admin_name.strip().lower()
        for key in full_hierarchy.get('admins', {}):
            if key.strip().lower() == admin_name_lower:
                return {
                    'admins': {
                        key: full_hierarchy['admins'][key]
                    }
                }
        return {'admins': {}}
    
    if user_type == 'trader':
        # Trader sees only their clients — collect from ALL admins
        trader_name = user_identifier.strip()
        trader_name_lower = trader_name.lower()
        merged_admins = {}
        for admin_name, admin_data in full_hierarchy.get('admins', {}).items():
            traders = admin_data.get('traders', {})
            for t_key in traders:
                if t_key.strip().lower() == trader_name_lower:
                    if admin_name not in merged_admins:
                        merged_admins[admin_name] = {
                            'email': '',
                            'traders': {}
                        }
                    merged_admins[admin_name]['traders'][t_key] = traders[t_key]
        return {'admins': merged_admins} if merged_admins else {'admins': {}}
    
    if user_type == 'client':
        # Client sees only themselves (case-insensitive match)
        client_name = user_identifier
        client_name_lower = client_name.strip().lower()
        for admin_name, admin_data in full_hierarchy.get('admins', {}).items():
            for trader_name, trader_data in admin_data.get('traders', {}).items():
                for client in trader_data.get('clients', []):
                    cname = (client.get('name') or '').strip().lower()
                    cemail = (client.get('email') or '').strip().lower()
                    if cname == client_name_lower or cemail == client_name_lower:
                        return {
                            'admins': {
                                admin_name: {
                                    'email': '',
                                    'traders': {
                                        trader_name: {
                                            'email': '',
                                            'clients': [client]
                                        }
                                    }
                                }
                            }
                        }
        return {'admins': {}}
    
    return {'admins': {}}

@app.route('/api/hierarchy')
def get_hierarchy():
    """Returns hierarchy filtered by user's role."""
    session_token = request.cookies.get('session_token')
    
    if not session_token:
        # Check for simple API key header for scripts
        api_key = request.headers.get('X-API-Key')
        if not api_key:
             return jsonify({"status": "error", "message": "Authentication required"}), 401
    
    user_type = 'super_admin' # Fallback for trusted scripts
    user_identifier = 'baller'
    
    if session_token:
        session_info = validate_session(session_token)
        if not session_info:
            return jsonify({"status": "error", "message": "Invalid session"}), 401
        
        user_type = session_info.get('user_type')
        user_identifier = session_info.get('user_identifier')
    
    # Reload hierarchy to get latest changes from file
    from config.hierarchy import reload_hierarchy
    reload_hierarchy()
    sync_kyc_links_into_hierarchy()
    
    filtered = get_filtered_hierarchy(user_type, user_identifier)
    
    # Enrich client objects with active_status — single bulk query instead of N+1
    from dashboard.database import get_all_client_identities
    import copy
    all_identities = get_all_client_identities()
    enriched = copy.deepcopy(filtered)
    for admin_data in enriched.get('admins', {}).values():
        for trader_data in admin_data.get('traders', {}).values():
            for client in trader_data.get('clients', []):
                cname = client.get('name', '')
                identity = all_identities.get(cname, {})
                client['active_status'] = identity.get('active_status', 'active')
                # Default split % is always 50; per-period overrides live in split_pct_overrides.
                # Ignore any legacy identity.split_pct that may have been populated from sheet imports.
                client['split_pct'] = 50
                # Hierarchy email is the source of truth (preserves original case).
                # Only fall back to DB identity email if hierarchy has none.
                if not client.get('email'):
                    client['email'] = identity.get('email', '')
    # Debug logging for empty hierarchy results
    if not enriched.get('admins') or all(
        not admin_data.get('traders', {}) for admin_data in enriched.get('admins', {}).values()
    ):
        logging.warning(f"[HIERARCHY] Empty result for user_type={user_type} user_identifier='{user_identifier}' — available trader keys: {[t for a in hierarchy.get('admins', {}).values() for t in a.get('traders', {}).keys()]}")
    
    # Shuffle client order daily so traders start with different clients each day
    import random
    from datetime import date as _date_cls
    today_seed = _date_cls.today().toordinal()
    for admin_data in enriched.get('admins', {}).values():
        for trader_name, trader_data in admin_data.get('traders', {}).items():
            clients = trader_data.get('clients', [])
            if len(clients) > 1:
                # Seed with today's date + trader name for per-trader unique order
                rng = random.Random(today_seed + hash(trader_name))
                rng.shuffle(clients)
    
    return jsonify(enriched)

from dashboard.financial_overview import calculate_all_financials

@app.route('/api/super_admin/totals')
def get_super_admin_totals():
    """Get aggregated totals across all clients for super admin dashboard."""
    session_token = request.cookies.get('session_token')
    
    if not session_token:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    
    # Check session
    # ... (auth check logic is fine, keeping it implicitly via context if needed or re-implementing if I replace the whole function body)
    # The snippet below replaces the body.
    
    session_info = validate_session(session_token)
    if not session_info or session_info.get('user_type') not in ('super_admin', 'bef_admin', 'kwok_admin'):
        return jsonify({"status": "error", "message": "Admin access required"}), 403
    
    profile_filter = request.args.get('profile', 'ALL').upper()
    
    # BEF admin always sees only BEF profile data
    if session_info.get('user_type') == 'bef_admin':
        profile_filter = 'BEF'
    if session_info.get('user_type') == 'kwok_admin':
        profile_filter = 'ALL'

    # Derive ALL totals from per-client stats (fast — uses precomputed cashflow_inprogress)
    clients = get_client_performance_stats(profile_filter)
    excluded_sa = _get_super_admin_stats_excluded_set()
    clients = [c for c in clients if str(c.get('client_id') or '').strip() not in excluded_sa]

    t_pay = sum(c.get('payouts', 0) for c in clients)
    t_dep = sum(c.get('deposits', 0) for c in clients)
    t_fees = sum(c.get('fees', 0) for c in clients)
    t_net = sum(c.get('net_profit', 0) for c in clients)
    t_hedge = sum(c.get('hedge_profit', 0) for c in clients)
    t_farming = sum(c.get('farming_profit', 0) for c in clients)
    t_active = sum(c.get('active', 0) for c in clients)
    t_passed = sum(c.get('passed', 0) for c in clients)
    t_failed = sum(c.get('failed', 0) for c in clients)
    t_ended = sum(c.get('ended', 0) for c in clients)
    t_duration = sum(c.get('total_duration_days', 0) for c in clients)

    ev = t_net / t_ended if t_ended > 0 else 0.0
    ev_day = t_net / t_duration if t_duration > 0 else 0.0

    response_data = {
        "status": "success",
        "totals": {
            "total_payouts": round(t_pay, 2),
            "total_deposits": round(t_dep, 2),
            "total_fees": round(t_fees, 2),
            "total_net_profit": round(t_net, 2),
            "active_accounts": t_active,
            "completed_accounts": t_passed,
            "failed_accounts": t_failed,
            "total_hedge": round(t_hedge, 2),
            "total_farming": round(t_farming, 2),
            "expected_value": round(ev, 2),
            "ev_per_day": round(ev_day, 2)
        },
        "clients": clients
    }

    return jsonify(response_data)

@app.route('/api/super_admin/profit_splits')
@require_session
def get_profit_splits():
    """Return per-client current profit split (in progress) for the super admin dashboard."""
    session_user = request.session_user
    if session_user.get('user_type') not in ('super_admin', 'bef_admin', 'kwok_admin'):
        return jsonify({"status": "error", "message": "Admin access required"}), 403

    profile_filter = request.args.get('profile', 'ALL').upper()
    if session_user.get('user_type') == 'bef_admin':
        profile_filter = 'BEF'
    if session_user.get('user_type') == 'kwok_admin':
        profile_filter = 'ALL'

    from dashboard.watermark_service import compute_waterlog_from_db, compute_waterlog_daily_fallback
    from dashboard.financial_overview import _get_cached_clients, get_client_profile
    from utils.data_processor import parse_currency
    from concurrent.futures import ThreadPoolExecutor

    clients_data = _get_cached_clients()
    excluded_sa = _get_super_admin_stats_excluded_set()
    results = []

    def _money_to_float(v):
        """Parse currency/stat fields the same way as quality-scan helpers."""
        try:
            if v is None:
                return 0.0
            s = str(v).replace("$", "").replace(",", "").strip()
            if s == "":
                return 0.0
            return float(s)
        except (TypeError, ValueError):
            return 0.0

    # Net profit in progress for Profit Split must match index.html Stats card /
    # window._statsNetProfit (lines ~5000–5005):
    #   payouts + hedging_results + farming_results + hedging_review.discrepancy
    #   - challenge_fees
    # Recomputing from evaluations alone omits MT5↔sheet discrepancy and will
    # disagree with the client's Profit Split tab.
    # Mirror the sheet (Evaluations tab) formulas exactly:
    #   Hedging Results = SUM(J:N) + SUM(U:AA)
    #                   = P1 hedges (HR 1..5) + ALL funded hedges (HR 1.1..5.1 + HR 6..7)
    #   Farming Results = SUM(AM:AM, AO:AO, AQ:AQ, ... DA:DA)
    #                   = Hedge Day 1..N only (no HR 6/7, no Farming Net override)
    _P1_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
    _FUNDED_COLS = [
        'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 'Hedge Result 5.1',
        'Hedge Result 6', 'Hedge Result 7',
    ]
    _HEDGE_DAY_COLS = [f'Hedge Day {i}' for i in range(1, 51)]

    def _live_in_progress_net(evaluations):
        cf_pay = cf_fees = cf_hedge = cf_farm = 0.0
        for ev in (evaluations or []):
            if not ev or ev.get('_deleted'):
                continue
            sp1 = str(ev.get('Status P1', '') or '').lower()
            sf = str(ev.get('Status') or ev.get('Status Funded', '') or '').lower()
            if 'deleted' in sp1 or 'deleted' in sf:
                continue
            p1 = round(sum(parse_currency(ev.get(c)) for c in _P1_COLS), 2)
            fd = round(sum(parse_currency(ev.get(c)) for c in _FUNDED_COLS), 2)
            h_days = round(sum(parse_currency(ev.get(c)) for c in _HEDGE_DAY_COLS), 2)
            fee = parse_currency(ev.get('Fee'))
            act = parse_currency(ev.get('Activation Fee'))
            payouts = round(sum(parse_currency(ev.get(f'Payout {i}')) for i in range(1, 7)), 2)
            row_hedge = round(p1 + fd, 2)
            row_farm = h_days  # pure sum of Hedge Day cols — matches sheet
            cf_pay = round(cf_pay + payouts, 2)
            cf_fees = round(cf_fees + fee + act, 2)
            cf_hedge = round(cf_hedge + row_hedge, 2)
            cf_farm = round(cf_farm + row_farm, 2)
        return round(cf_pay + cf_hedge + cf_farm - cf_fees, 2)

    def _compute_one(client_id, data):
        try:
            identity = data.get('identity', {})
            display_name = (identity.get('name') or client_id).strip()
            # Profile filter
            source = get_client_profile(client_id, identity)
            if profile_filter != 'ALL' and source != profile_filter:
                return None

            if _client_excluded_from_super_admin_stats(client_id, display_name, excluded_sa):
                return None

            # Mirror the client dashboard's Profit Split card EXACTLY so the super
            # admin "Client Breakdown" matches #split-profit-amount per client.
            #
            # Client dashboard (index.html):
            #   latestNet = window._statsNetProfit from cashflow_inprogress + discrepancy
            #   baseline  = net at end of the most recent *completed* period whose
            #               profit_split > 0 (months with $0 split do not move baseline).
            #   split_amt = 0 if latestNet <= 0 else max(0, (latestNet - baseline) * split_pct / 100)
            stats = data.get('statistics') if isinstance(data.get('statistics'), dict) else {}
            cf = stats.get('cashflow_inprogress') if isinstance(stats.get('cashflow_inprogress'), dict) else {}
            hr = stats.get('hedging_review') if isinstance(stats.get('hedging_review'), dict) else {}
            if cf:
                latest_net = round(
                    _money_to_float(cf.get("payouts"))
                    + _money_to_float(cf.get("hedging_results"))
                    + _money_to_float(cf.get("farming_results"))
                    + _money_to_float(hr.get("discrepancy"))
                    - _money_to_float(cf.get("challenge_fees")),
                    2,
                )
            else:
                latest_net = _live_in_progress_net(data.get('evaluations') or [])

            # Watermark DB rows are keyed by dashboard client_id, not display name.
            wl = compute_waterlog_from_db(client_id) or compute_waterlog_daily_fallback(client_id)
            baseline = 0.0
            split_pct = 50
            if wl and wl.get('periods'):
                periods = wl['periods']
                try:
                    split_pct = int(periods[-1].get('split_pct', 50) or 50)
                except (TypeError, ValueError):
                    split_pct = 50
                completed = periods[:-1]
                for p in reversed(completed):
                    ps_raw = str(p.get('profit_split', '$0')).replace('$', '').replace(',', '').strip()
                    try:
                        psv = float(ps_raw)
                    except ValueError:
                        psv = 0.0
                    if psv <= 0:
                        continue
                    low_raw = str(p.get('low', '$0')).replace('$', '').replace(',', '').strip()
                    try:
                        baseline = float(low_raw)
                    except ValueError:
                        baseline = 0.0
                    break
                if baseline == 0.0 and not completed:
                    lsn = wl.get('last_split_net_profit')
                    if lsn is not None:
                        try:
                            baseline = float(lsn)
                        except (TypeError, ValueError):
                            baseline = 0.0

            if latest_net <= 0:
                split_amt = 0.0
            elif latest_net > baseline:
                split_amt = (latest_net - baseline) * split_pct / 100.0
            else:
                split_amt = 0.0

            return {
                'client_id': display_name,
                'net_profit': round(latest_net, 2),
                'profit_split_inprogress': round(split_amt, 2),
                'split_pct': split_pct,
            }
        except Exception as _exc:
            import traceback
            print(f"[profit_splits] error for {client_id}: {_exc}\n{traceback.format_exc()}")
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_compute_one, cid, d) for cid, d in clients_data.items()]
        for f in futures:
            r = f.result()
            if r is not None:
                results.append(r)

    total = round(sum(r['profit_split_inprogress'] for r in results), 2)
    results.sort(key=lambda x: x['profit_split_inprogress'], reverse=True)
    return jsonify({'status': 'success', 'clients': results, 'total': total})


@app.route('/api/super_admin/stats_exclusions', methods=['GET'])
@require_role('super_admin')
def api_super_admin_stats_exclusions_get():
    """List all clients with trader/admin and current Super Admin exclusion set."""
    from dashboard.database import get_setting, get_all_clients

    try:
        excluded = json.loads(get_setting(_SUPER_ADMIN_STATS_EXCLUDED_KEY) or '[]')
    except (TypeError, ValueError):
        excluded = []
    if not isinstance(excluded, list):
        excluded = []

    rows = []
    seen = set()
    h = SYSTEM_HIERARCHY or {}
    if h.get('admins'):
        for admin_name, admin_data in h['admins'].items():
            for trader_name, trader_data in admin_data.get('traders', {}).items():
                for client in trader_data.get('clients', []):
                    cname = (client.get('name') or '').strip()
                    if not cname or cname in seen:
                        continue
                    seen.add(cname)
                    rows.append({
                        'client_id': cname,
                        'trader': trader_name or '-',
                        'admin': admin_name or '-',
                    })

    for cid, data in (get_all_clients() or {}).items():
        if not data:
            continue
        identity = data.get('identity') or {}
        display = (identity.get('name') or cid or '').strip()
        if not display or display in seen:
            continue
        seen.add(display)
        rows.append({'client_id': display, 'trader': '-', 'admin': '-'})

    rows.sort(key=lambda r: r['client_id'].lower())
    return jsonify({'status': 'success', 'clients': rows, 'excluded': excluded})


@app.route('/api/super_admin/stats_exclusions', methods=['POST'])
@require_role('super_admin')
def api_super_admin_stats_exclusions_post():
    """Replace Super Admin stats exclusion list (checked clients in Data Quality UI)."""
    from dashboard.database import set_setting

    body = request.get_json(silent=True) or {}
    ex = body.get('excluded')
    if not isinstance(ex, list):
        return jsonify({'status': 'error', 'message': 'excluded must be a list'}), 400

    clean = sorted({str(x).strip() for x in ex if x is not None and str(x).strip()})
    user_id = request.session_user.get('user_identifier', '')
    set_setting(_SUPER_ADMIN_STATS_EXCLUDED_KEY, json.dumps(clean), updated_by=user_id)
    try:
        from dashboard.financial_overview import clear_financial_overview_cache
        clear_financial_overview_cache()
    except Exception:
        pass
    log_action(
        'SUPER_ADMIN_STATS_EXCLUSIONS',
        'super_admin',
        user_id,
        get_remote_address(),
        f'{len(clean)} excluded client(s)',
    )
    return jsonify({'status': 'success', 'excluded': clean})


@app.route('/api/client_payouts/<client_id>')
@require_session
def get_client_payouts_detail(client_id):
    """Return individual payout records for a client (used by breakdown modal expand)."""
    session_user = request.session_user
    if session_user.get('user_type') not in ('super_admin', 'bef_admin', 'kwok_admin'):
        return jsonify({"status": "error"}), 403

    from dashboard.financial_overview import parse_currency, parse_date
    data = get_client_data(client_id)
    if not data:
        return jsonify({"payouts": []})

    evaluations = data.get('evaluations', [])
    records = []
    for ev in evaluations:
        if not isinstance(ev, dict):
            continue
        prop_firm = str(ev.get('Prop Firm') or 'Unknown').strip() or 'Unknown'
        account = str(ev.get('Account #') or ev.get('Account #.1') or '-').strip()
        for i in range(1, 10):
            amt = parse_currency(ev.get(f'Payout {i}'))
            if amt != 0:
                pdate = str(ev.get(f'Date {i}') or '-').strip()
                d_obj = parse_date(pdate)
                records.append({
                    "prop_firm": prop_firm,
                    "account": account,
                    "amount": round(amt, 2),
                    "date": pdate,
                    "_sort": d_obj.isoformat() if d_obj else "0000-00-00"
                })

    records.sort(key=lambda r: r['_sort'])
    # Add running total
    running = 0.0
    for r in records:
        running += r['amount']
        r['running_total'] = round(running, 2)
        del r['_sort']

    return jsonify({"payouts": records})

@app.route('/api/super_admin/recalculate_stats', methods=['POST'])
@require_session
def recalculate_all_stats():
    """Recalculate and save statistics for all clients from stored evaluations."""
    if request.session_user.get('user_type') != 'super_admin':
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    from utils.data_processor import calculate_statistics
    all_clients = get_all_clients()
    results = []
    for client_id, client_data in all_clients.items():
        try:
            evals = client_data.get('evaluations', [])
            evals = recalculate_hedge_nets(evals)
            existing_mt5 = client_data.get('account')
            existing_hr = client_data.get('statistics', {}).get('hedging_review', {})
            existing_hist = existing_hr.get('historical_accounts')
            old_fees = client_data.get('statistics', {}).get('profitability_completed', {}).get('challenge_fees', 0)
            new_stats = calculate_statistics(evals, mt5_account=existing_mt5, historical_accounts=existing_hist)
            # ALWAYS preserve hedging_review MT5-derived fields
            new_hr = new_stats.setdefault('hedging_review', {})
            new_hr['total_deposits'] = existing_hr.get('total_deposits', 0)
            new_hr['total_withdrawals'] = existing_hr.get('total_withdrawals', 0)
            new_hr['current_balance'] = existing_hr.get('current_balance', 0)
            new_hr['actual_hedging_results'] = existing_hr.get('actual_hedging_results', 0)
            # Preserve historical account fields
            if existing_hist:
                new_hr['historical_accounts'] = existing_hist
                new_hr['historical_deposits'] = existing_hr.get('historical_deposits', 0)
                new_hr['historical_withdrawals'] = existing_hr.get('historical_withdrawals', 0)
                new_hr['historical_balance'] = existing_hr.get('historical_balance', 0)
            # Recalculate discrepancy + net_profit with preserved MT5 values
            new_hr['discrepancy'] = round(new_hr['actual_hedging_results'] - new_hr.get('sheet_hedging_results', 0), 2)
            # Recalculate net_profit with discrepancy (match frontend formula)
            disc = new_hr['discrepancy']
            for sk in ["profitability_completed", "cashflow_inprogress"]:
                sec = new_stats[sk]
                sec["net_profit"] = round(sec["payouts"] + sec["hedging_results"] + sec["farming_results"] + disc - sec["challenge_fees"], 2)
            new_fees = new_stats.get('profitability_completed', {}).get('challenge_fees', 0)
            save_client_data(client_id, {'evaluations': evals, 'statistics': new_stats})
            results.append({"client_id": client_id, "old_fees": old_fees, "new_fees": new_fees, "changed": abs(float(new_fees) - float(old_fees)) > 0.01})
        except Exception as e:
            results.append({"client_id": client_id, "error": str(e)})
    return jsonify({"status": "success", "recalculated": len(results), "results": results})

@app.route('/api/super_admin/cleanup_database', methods=['POST'])
@require_session
def api_cleanup_database():
    """Run database cleanup: prune old history, audit log, expired sessions."""
    if request.session_user.get('user_type') != 'super_admin':
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    from dashboard.database import cleanup_database
    results = cleanup_database()
    return jsonify({"status": "success", "cleaned": results})

@app.route('/api/client/update_source', methods=['POST'])
@require_session
def update_client_source():
    """Update client source (BEF/Private)."""
    session_user = request.session_user
    if session_user.get('user_type') != 'super_admin':
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
        
    data = request.get_json(silent=True) or {}
    client_id = data.get('client_id')
    source = data.get('source')
    allowed = ['BEF', 'Private']

    if not client_id or source not in allowed:
        return jsonify({"status": "error", "message": "Invalid data"}), 400
    
    # Update Database
    client_data = get_client_data(client_id)
    if not client_data:
        return jsonify({"status": "error", "message": "Client not found"}), 404
        
    identity = client_data.get('identity', {}) or {}
    # Update all relevant fields for consistency
    identity['profile'] = source
    identity['category'] = source
    identity['source'] = source
    update_client_field(client_id, 'identity', identity)

    # clear cache
    from dashboard.financial_overview import clear_financial_cache
    clear_financial_cache()
    
    # Also update Hierarchy.json if possible
    try:
        from config.hierarchy import get_client_profile, update_client_category
        profile = get_client_profile(client_id)
        if profile:
            update_client_category(profile['admin'], profile['trader'], client_id, source)
    except Exception as e:
        log_action('UPDATE_CLIENT_SOURCE', 'super_admin', client_id, get_remote_address(), str(e), success=False)
    
    log_action('UPDATE_CLIENT_SOURCE', 'super_admin', client_id, get_remote_address(), f"To: {source}")
    return jsonify({"status": "success"})

@app.route('/api/client/lookup', methods=['POST'])
@require_api_key
def api_client_lookup():
    """Look up client hierarchy info by email."""
    email = request.json.get('email', '').strip()
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    client = get_client_by_email(email)
    if client:
        return jsonify({
            "status": "success",
            "client": client['client'],
            "trader": client['trader'],
            "admin": client['admin'],
            "email": client['email']
        })
    
    return jsonify({"status": "error", "message": "Email not found in system"}), 404


@app.route('/api/check_email', methods=['GET', 'POST', 'OPTIONS'], strict_slashes=False)
def api_check_email():
    """
    Check whether an email (or username) exists in the system.

    Accepts both GET (?email=...) and POST (JSON body: {"email": "..."}).
    Requires X-API-Key header (accepts both 'full' and 'readonly' scoped keys).

    Response (200):
        {"exists": true,  "user_type": "client", "username": "John Doe"}
        {"exists": false}
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({"status": "ok"})
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key'
        return response, 200

    # Manual key validation — accepts both 'full' and 'readonly' scope
    api_key = request.headers.get('X-API-Key')
    client_ip = get_remote_address()
    if not api_key:
        return jsonify({"status": "error", "message": "API key required"}), 401
    user_info = validate_api_key(api_key)
    if not user_info:
        log_action('API_ACCESS_DENIED', 'unknown', api_key[:12], client_ip, 'Invalid API key on check_email', False)
        return jsonify({"status": "error", "message": "Invalid API key"}), 403
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        email = data.get('email', '').strip()
    else:
        email = request.args.get('email', '').strip()

    if not email:
        return jsonify({"status": "error", "message": "email parameter required"}), 400

    from dashboard.database import find_user_by_identifier
    from config.hierarchy import reload_hierarchy

    def _find_client_email(search_email):
        """Check both user_credentials (DB) and hierarchy.json for a client with this email."""
        search_email_lower = search_email.lower()
        # 1. Check DB
        user = find_user_by_identifier(search_email)
        if user and user.get('user_type') == 'client':
            return {'username': user.get('username'), 'source': 'db'}
        # 2. Check hierarchy.json
        h = reload_hierarchy()
        for admin_data in h.get('admins', {}).values():
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    if (client.get('email') or '').lower() == search_email_lower:
                        return {'username': client.get('name', ''), 'source': 'hierarchy'}
        return None

    found = _find_client_email(email)
    if found:
        return jsonify({
            "exists": True,
            "user_type": "client",
            "username": found['username']
        })

    return jsonify({"exists": False})


@app.route('/api/list_emails', methods=['GET', 'POST', 'OPTIONS'], strict_slashes=False)
def api_list_emails():
    """
    GET  — Return all emails registered in the system (each entry includes exists: true).
    POST — Bulk check: pass {"emails": ["a@b.com", ...]} and get back exists true/false per email.

    Requires X-API-Key header (accepts both 'full' and 'readonly' scoped keys).

    GET query params:
        ?user_type=client|trader|admin   — filter by role (default: all)
        ?active_only=true                — only include active accounts (default: true)

    GET response:
        {"count": 2, "emails": [
            {"email": "john@example.com", "username": "John", "user_type": "client", "exists": true},
            ...
        ]}

    POST response:
        {"results": [
            {"email": "john@example.com", "exists": true,  "user_type": "client", "username": "John"},
            {"email": "unknown@x.com",    "exists": false}
        ]}
    """
    if request.method == 'OPTIONS':
        response = jsonify({"status": "ok"})
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key'
        return response, 200

    # Validate key — accepts readonly and full scopes
    api_key = request.headers.get('X-API-Key')
    client_ip = get_remote_address()
    if not api_key:
        return jsonify({"status": "error", "message": "API key required"}), 401
    user_info = validate_api_key(api_key)
    if not user_info:
        log_action('API_ACCESS_DENIED', 'unknown', api_key[:12], client_ip, 'Invalid API key on list_emails', False)
        return jsonify({"status": "error", "message": "Invalid API key"}), 403

    from dashboard.database import list_users, find_user_by_identifier
    from config.hierarchy import reload_hierarchy

    def _all_hierarchy_clients():
        """Return all clients from hierarchy.json as a list of {email, username} dicts."""
        results = []
        h = reload_hierarchy()
        for admin_data in h.get('admins', {}).values():
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    email = (client.get('email') or '').strip()
                    if email:
                        results.append({'email': email, 'username': client.get('name', '')})
        return results

    def _find_client_email(search_email):
        search_email_lower = search_email.lower()
        user = find_user_by_identifier(search_email)
        if user and user.get('user_type') == 'client':
            return {'username': user.get('username')}
        h = reload_hierarchy()
        for admin_data in h.get('admins', {}).values():
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    if (client.get('email') or '').lower() == search_email_lower:
                        return {'username': client.get('name', '')}
        return None

    # ── POST: bulk existence check ──────────────────────────────────────────
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        emails_to_check = data.get('emails', [])
        if not isinstance(emails_to_check, list):
            return jsonify({"status": "error", "message": "'emails' must be a list"}), 400

        results = []
        for email in emails_to_check:
            email = str(email).strip()
            if not email:
                continue
            found = _find_client_email(email)
            if found:
                results.append({
                    "email": email,
                    "exists": True,
                    "user_type": "client",
                    "username": found['username']
                })
            else:
                results.append({"email": email, "exists": False})

        log_action('API_ACCESS', 'reader', user_info.get('trader', 'unknown'), client_ip,
                   f"bulk_check_emails: {len(results)} checked")
        return jsonify({"results": results})

    # ── GET: return all client emails (DB + hierarchy.json) ─────────────────
    active_only = request.args.get('active_only', 'true').lower() != 'false'

    # Collect from DB
    seen_emails = set()
    results = []
    for u in list_users(user_type='client'):
        if active_only and not u.get('is_active'):
            continue
        email = (u.get('email') or '').strip()
        if email:
            seen_emails.add(email.lower())
            results.append({'email': email, 'username': u.get('username'), 'user_type': 'client', 'exists': True})

    # Also collect from hierarchy.json (clients not in DB)
    for c in _all_hierarchy_clients():
        if c['email'].lower() not in seen_emails:
            seen_emails.add(c['email'].lower())
            results.append({'email': c['email'], 'username': c['username'], 'user_type': 'client', 'exists': True})

    log_action('API_ACCESS', 'reader', user_info.get('trader', 'unknown'), client_ip,
               f"list_emails: {len(results)} returned")
    return jsonify({"count": len(results), "emails": results})


# ============ PUBLIC CLIENT API (No API Key Required) ============

@app.route('/api/client/auth', methods=['POST'])
@limiter.limit("30 per minute")
def api_client_auth():
    """
    Public endpoint - authenticate client by email only.
    Returns client hierarchy info if email exists in system.
    No API key required - just the client email.
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"status": "error", "message": "Invalid JSON or Content-Type"}), 400
            
        email = data.get('email', '').strip().lower()
        
        if not email:
            return jsonify({"status": "error", "message": "Email required"}), 400
        
        client = get_client_by_email(email)
        
        # Safe logging
        try:
            remote_addr = get_remote_address()
        except:
            remote_addr = "0.0.0.0"

        if client:
            try:
                log_action('CLIENT_AUTH', 'client', email, remote_addr, 'Email verified')
            except Exception as e:
                print(f"Log action error: {e}", file=sys.stderr)
                
            return jsonify({
                "status": "success",
                "identity": {
                    "admin": client['admin'],
                    "trader": client['trader'],
                    "client": client['client'],
                    "email": client['email'],
                    "category": client.get('category', '')
                }
            })
        
        try:
            log_action('CLIENT_AUTH_FAILED', 'client', email, remote_addr, 'Email not found', False)
        except:
            pass
            
        return jsonify({"status": "error", "message": "Email not registered in the system"}), 404
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/client/data', methods=['POST'])
@limiter.limit("30 per minute")
def api_client_data():
    """
    Public endpoint - fetch client evaluations by email.
    Used by Trader Companion to load active trades list.
    """
    from dashboard.database import get_client_data

    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"status": "error", "message": "Invalid JSON"}), 400

        email = (data.get('email') or '').strip().lower()
        if not email:
            return jsonify({"status": "error", "message": "Email required"}), 400

        client_info = get_client_by_email(email)
        if not client_info:
            return jsonify({"status": "error", "message": "Email not registered"}), 404

        client_id = client_info['client']
        client_data = get_client_data(client_id)
        if not client_data:
            return jsonify({"status": "error", "message": "No data found for client"}), 404

        # Mark each evaluation with is_active using the same logic as data_processor
        evaluations = client_data.get("evaluations", [])
        for ev in evaluations:
            status_p1 = (ev.get("Status P1") or "").strip()
            status_funded = (ev.get("Status") or "").strip()
            is_p1_fail = status_p1 == "Fail"
            is_funded_fail = status_funded == "Fail"
            is_funded_completed = status_funded == "Completed"
            is_funded_ended = is_funded_fail or is_funded_completed
            ev["_is_active"] = not is_p1_fail and not is_funded_ended

        return jsonify({
            "status": "success",
            "evaluations": evaluations,
            "prop_accounts": client_data.get("prop_accounts", []),
            "hedge_accounts": client_data.get("hedge_accounts", []),
            "mt5_credentials": client_data.get("mt5_credentials", {}),
            "identity": {
                "client": client_info['client'],
                "trader": client_info['trader'],
                "admin": client_info['admin'],
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


_INTERNAL_DEAL_TYPES_INT = {2, 3}  # BALANCE=2, CREDIT=3
_INTERNAL_DEAL_TYPES_STR = {
    'BALANCE', '2', '2.0',
    'CREDIT',  '3', '3.0',
    'DEAL_TYPE_BALANCE', 'DEAL_TYPE_CREDIT',
}


def _drop_balance_deals(deals):
    """
    Remove internal-transfer style MT5 deals (BALANCE/CREDIT) from a pushed deal list.

    Requirement: these internal transfers should "not exist" for the dashboard:
    they should not be stored, displayed, or used in server-side calculations.
    """
    if not deals:
        return [], 0
    if not isinstance(deals, list):
        return deals, 0

    def _is_internal(d):
        if not isinstance(d, dict):
            return False

        raw_type = d.get('type', '')
        raw_entry = d.get('entry', '')

        # Numeric check (raw MT5 / DataFrame): catches 2, 2.0, 3, 3.0, etc.
        try:
            if int(float(raw_type)) in _INTERNAL_DEAL_TYPES_INT:
                return True
        except (ValueError, TypeError):
            pass

        # String check (JSON payloads / serialized exports)
        str_type = str(raw_type).strip().upper()
        str_entry = str(raw_entry).strip().upper()

        return (
            str_type in _INTERNAL_DEAL_TYPES_STR
            or str_entry in _INTERNAL_DEAL_TYPES_STR
            or ('BALANCE' in str_type)
            or ('CREDIT' in str_type)
        )

    filtered = [d for d in deals if not _is_internal(d)]
    dropped = len(deals) - len(filtered)
    return filtered, dropped


@app.route('/api/client/push', methods=['POST'])
@limiter.limit("60 per minute")
def api_client_push():
    """
    Public endpoint - push data using client email only (no API key).
    Automatically looks up hierarchy from email.
    Recalculates statistics using MT5 deals/account data if provided.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    # Look up client by email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered in the system"}), 404
    
    admin_id = client_info['admin']
    trader_id = client_info['trader']
    client_id = client_info['client']

    # Trader Companion version (for audit/visibility; not trusted for auth)
    companion_version = (
        str(data.get('companion_version') or data.get('version') or request.headers.get('X-Companion-Version') or '').strip()
    )
    
    # Get MT5 data from push
    mt5_deals_raw = data.get("deals", [])
    mt5_deals, dropped_internal = _drop_balance_deals(mt5_deals_raw)
    if dropped_internal:
        app.logger.info(f"🚫 Dropped {dropped_internal} internal transfer deal(s) (BALANCE/CREDIT) from push payload")
    mt5_account = data.get("account", {})
    
    # Get existing data to merge evaluations if needed
    existing_data = get_client_data(client_id) or {}
    
    # Only use new evaluations if explicitly provided and not empty
    # If "evaluations" key is missing or None, preserve existing data
    if "evaluations" in data and data["evaluations"]:
        incoming_evals = data["evaluations"]
        existing_evals_push = existing_data.get('evaluations', [])
        force_fields = set(data.get('force_fields', []))
        evaluations = merge_evaluation_push_with_existing(
            existing_evals_push, incoming_evals, force_fields)
        app.logger.info(
            f"   Merged {len(incoming_evals)} incoming evaluation row(s) "
            f"into {len(evaluations)} total (was {len(existing_evals_push)} in DB)")
    else:
        evaluations = existing_data.get("evaluations", [])
        app.logger.info(f"   Preserving {len(evaluations)} EXISTING evaluations")
    
    # Normalize Account Size values to standard format
    evaluations = normalize_evaluations(evaluations)
    
    # Check for aggregated comment data (from Push by Comment feature) OR raw deals
    aggregated_by_comment = data.get("aggregated_by_comment", [])
    prefer_client_aggregation = bool(data.get("prefer_client_aggregation"))
    comment_summary = data.get("comment_summary", {})
    tradovate_farming_days = data.get("tradovate_farming_days", [])
    hedge_match_log = []
    
    if aggregated_by_comment or mt5_deals:
        app.logger.info(f"📋 Received {len(aggregated_by_comment)} aggregated groups, {len(mt5_deals)} raw deals")
        if prefer_client_aggregation:
            app.logger.info("⚡ Preferring client-side aggregation for hedge matching")
        if tradovate_farming_days:
            app.logger.info(f"🌾 Received Tradovate farming data for {len(tradovate_farming_days)} account(s)")
        
        # Update evaluations with hedge results from aggregated data OR raw deals
        if evaluations:
            app.logger.info(f"🔄 Matching hedge results to evaluations...")
            evaluations, hedge_match_log, generated_sessions = update_evaluations_from_aggregated_data(
                evaluations, aggregated_data=aggregated_by_comment,
                raw_deals=None if prefer_client_aggregation else mt5_deals,
                tradovate_farming_days=tradovate_farming_days)
            
            # If server-side aggregation occurred, use THAT instead of the client's.
            if generated_sessions:
                aggregated_by_comment = generated_sessions
                app.logger.info(f"✅ Replaced client aggregation with {len(generated_sessions)} server-side sessions")

            if hedge_match_log:
                app.logger.info(f"📌 Hedge matching produced {len(hedge_match_log)} log entries")
                if app.logger.isEnabledFor(logging.DEBUG):
                    for log_line in hedge_match_log:
                        app.logger.debug(f"   {log_line}")
    
    # Debug logging
    acct_balance = mt5_account.get('balance', 0) if mt5_account else 0
    app.logger.info(f"📥 Push for {client_id}: {len(mt5_deals)} deals, balance={acct_balance}, {len(evaluations)} evaluations")
    
    # Log detailed MT5 account info
    if mt5_account:
        app.logger.info(f"💰 MT5 Account Details:")
        app.logger.info(f"   - balance: ${mt5_account.get('balance', 0):.2f}")
        app.logger.info(f"   - total_deposits: ${mt5_account.get('total_deposits', 0):.2f}")
        app.logger.info(f"   - total_withdrawals: ${mt5_account.get('total_withdrawals', 0):.2f}")
        app.logger.info(f"   - equity: ${mt5_account.get('equity', 0):.2f}")
        app.logger.info(f"   - account_number: {mt5_account.get('account_number', 'N/A')}")
    
    # Log deal types and counts to debug
    if mt5_deals:
        deal_types = {}
        for d in mt5_deals:
            dtype = str(d.get('type', 'unknown'))
            deal_types[dtype] = deal_types.get(dtype, 0) + 1
        app.logger.info(f"🔄 Deal types: {deal_types}")
    
    # Log evaluation hedging/payout data summary
    app.logger.info(f"📋 Evaluation Rows Summary:")
    for i, ev in enumerate(evaluations):
        prop_firm = ev.get('Prop Firm', 'Unknown')
        status_p1 = ev.get('Status P1', '')
        status_fd = ev.get('Status') or ev.get('Status Funded', '')
        
        # Collect hedge results
        hedge_results = []
        for j in range(1, 8):
            key = f'Hedge Result {j}' if j < 6 else f'Hedge Result {j-5}.1' if j == 6 else f'Hedge Result {j-5}.1'
            val = ev.get(key, '')
            if val and str(val).strip() not in ('', '-', '$0'):
                hedge_results.append(f"{key}={val}")
        
        # Collect payouts
        payouts = []
        for j in range(1, 10):
            key = f'Payout {j}'
            val = ev.get(key, '')
            if val and str(val).strip() not in ('', '-', '$0'):
                payouts.append(f"{key}={val}")
        
        hedge_net = ev.get('Hedge Net', '')
        hedge_net_1 = ev.get('Hedge Net.1', '')
        fee = ev.get('Fee', '')
        act_fee = ev.get('Activation Fee', '')
        
        row_info = f"   [{i}] {prop_firm} | P1:{status_p1} FD:{status_fd}"
        if hedge_results:
            row_info += f" | Hedges: {', '.join(hedge_results)}"
        if payouts:
            row_info += f" | Payouts: {', '.join(payouts)}"
        if hedge_net and str(hedge_net).strip() not in ('', '-'):
            row_info += f" | Hedge Net={hedge_net}"
        if hedge_net_1 and str(hedge_net_1).strip() not in ('', '-'):
            row_info += f" | Hedge Net.1={hedge_net_1}"
        if fee and str(fee).strip() not in ('', '-', '$0'):
            row_info += f" | Fee={fee}"
        if act_fee and str(act_fee).strip() not in ('', '-', '$0'):
            row_info += f" | Activation={act_fee}"
        
        app.logger.info(row_info)
    
    # Log deal types to debug
    if mt5_deals:
        deal_types = [str(d.get('type', 'unknown')) for d in mt5_deals[:5]]
        app.logger.info(f"   Sample deal types: {deal_types}")
    
    # ALWAYS recalculate statistics when we have evaluations or MT5 data
    # This ensures discrepancy is only calculated when we have actual MT5 data
    statistics = data.get("statistics", {})
    push_sheet_url = existing_data.get('sheet_url') or (existing_data.get('identity') or {}).get('sheet_url')

    # Recalculate Hedge Net / Hedge Net.1 before stats so formulas stay current
    evaluations = recalculate_hedge_nets(evaluations)

    if evaluations or mt5_deals or mt5_account:
        try:
            from utils.data_processor import calculate_statistics
            
            # Log what we're passing to calculate_statistics
            app.logger.info(f"🔧 Calling calculate_statistics with:")
            app.logger.info(f"   - mt5_account type: {type(mt5_account)}, has data: {bool(mt5_account)}")
            if mt5_account:
                app.logger.info(f"   - mt5_account.balance: {mt5_account.get('balance', 'N/A')}")
                app.logger.info(f"   - mt5_account.total_deposits: {mt5_account.get('total_deposits', 'N/A')}")
                app.logger.info(f"   - mt5_account.total_withdrawals: {mt5_account.get('total_withdrawals', 'N/A')}")
            
            # Pass MT5 data - if empty, discrepancy will be 0
            mt5_acc_param = mt5_account if mt5_account else None
            mt5_deals_param = mt5_deals if mt5_deals else None
            
            # Fetch Stats tab values from Google Sheet so the SUMIF stats
            # use formula-precision values instead of CSV-rounded values.
            # Cached per sheet_url with a 5-minute TTL to avoid blocking on every push.
            push_xlsx_notes = None
            if push_sheet_url:
                import time as _time
                _now = _time.time()
                _cached = _stats_tab_cache.get(push_sheet_url)
                if _cached and (_now - _cached[0]) < _STATS_TAB_TTL:
                    push_xlsx_notes = _cached[1]
                    app.logger.info(f"📊 Stats tab served from cache (age {int(_now - _cached[0])}s)")
                else:
                    # Never block the push on a live sheet fetch. Use cache if present,
                    # and refresh in the background for the next request.
                    if _cached:
                        push_xlsx_notes = _cached[1]
                        app.logger.info("📊 Stats tab using stale cache while refreshing in background")
                    else:
                        app.logger.info("📊 Stats tab cache miss - skipping live fetch for this push")

                    if push_sheet_url not in _stats_tab_cache_refreshing:
                        _stats_tab_cache_refreshing.add(push_sheet_url)

                        def _refresh_stats_tab_cache(sheet_url=push_sheet_url):
                            try:
                                from utils.data_processor import fetch_evaluations as _fe
                                _result = _fe(sheet_url)
                                if isinstance(_result, tuple) and len(_result) == 2:
                                    _, _notes = _result
                                    _stats_tab_cache[sheet_url] = (_time.time(), _notes)
                                    if _notes and '__stats_tab__' in _notes:
                                        app.logger.info("📊 Stats tab fetched in background and cached")
                            except Exception as _e:
                                app.logger.warning(f"Stats tab background fetch failed (non-critical): {_e}")
                            finally:
                                _stats_tab_cache_refreshing.discard(sheet_url)

                        threading.Thread(target=_refresh_stats_tab_cache, daemon=True).start()
            
            statistics = calculate_statistics(evaluations, mt5_deals_param, mt5_acc_param, xlsx_notes=push_xlsx_notes,
                                              historical_accounts=existing_data.get('statistics', {}).get('hedging_review', {}).get('historical_accounts'))
            
            # Preserve historical MT5 accounts from existing data
            existing_hr = existing_data.get('statistics', {}).get('hedging_review', {})
            if 'historical_accounts' in existing_hr:
                statistics.setdefault('hedging_review', {})['historical_accounts'] = existing_hr['historical_accounts']
                statistics['hedging_review']['historical_deposits'] = existing_hr.get('historical_deposits', 0)
                statistics['hedging_review']['historical_withdrawals'] = existing_hr.get('historical_withdrawals', 0)
                statistics['hedging_review']['historical_balance'] = existing_hr.get('historical_balance', 0)
            
            # ALWAYS preserve hedging_review MT5-derived fields from existing data.
            # Only manual edits via /api/hedging_review or /api/client/push_hedging_review can set MT5 fields.
            # Push Data should never overwrite live hedging review values.
            app.logger.info(f"📌 Preserving hedging review MT5 values — push data never overwrites")
            new_hr = statistics.get('hedging_review', {})
            # Preserve MT5-derived fields from existing manual/push edits
            new_hr['total_deposits'] = existing_hr.get('total_deposits', 0)
            new_hr['total_withdrawals'] = existing_hr.get('total_withdrawals', 0)
            new_hr['current_balance'] = existing_hr.get('current_balance', 0)
            new_hr['actual_hedging_results'] = existing_hr.get('actual_hedging_results', 0)
            # Preserve historical account fields
            if existing_hr.get('historical_accounts'):
                new_hr['historical_accounts'] = existing_hr['historical_accounts']
                new_hr['historical_deposits'] = existing_hr.get('historical_deposits', 0)
                new_hr['historical_withdrawals'] = existing_hr.get('historical_withdrawals', 0)
                new_hr['historical_balance'] = existing_hr.get('historical_balance', 0)
            # Recalculate discrepancy with preserved MT5 values + fresh sheet values
            new_hr['discrepancy'] = round(new_hr['actual_hedging_results'] - new_hr.get('sheet_hedging_results', 0), 2)
            statistics['hedging_review'] = new_hr
            # Recalculate net_profit with the corrected discrepancy
            disc = new_hr['discrepancy']
            for section_key in ["profitability_completed", "cashflow_inprogress"]:
                sec = statistics[section_key]
                sec["net_profit"] = round(sec["payouts"] + sec["hedging_results"] + sec["farming_results"] - sec["challenge_fees"] + disc, 2)
            
            # Log the hedging review results
            hr = statistics.get('hedging_review', {})
            app.logger.info(f"Stats calculated:")
            app.logger.info(f"   - Current balance: ${hr.get('current_balance', 0):.2f}")
            app.logger.info(f"   - Total deposits: ${hr.get('total_deposits', 0):.2f}")
            app.logger.info(f"   - Total withdrawals: ${hr.get('total_withdrawals', 0):.2f}")
            app.logger.info(f"   - Actual hedging: ${hr.get('actual_hedging_results', 0):.2f}")
            
            # Debug info
            if '_debug_deal_count' in hr:
                app.logger.info(f"   - Debug: {hr.get('_debug_deal_count')} deals processed, types seen: {hr.get('_debug_deal_types', [])}")
        except Exception as e:
            app.logger.error(f"Error recalculating stats: {e}")
            import traceback
            app.logger.error(traceback.format_exc())
            # Keep the provided statistics if recalc fails

    # Merge incoming account onto existing instead of replacing.
    # The lightweight push sends total_deposits/total_withdrawals as 0 (deal-history
    # walk is skipped for speed); the follow-up /api/client/push_hedging_review call
    # fills them in. If we let the zeros overwrite, any push where the HR follow-up
    # fails (MT5 disconnect, history_deals_get timeout, network error) leaves the
    # panel showing $0 until the next successful HR push.
    incoming_acct = mt5_account or {}
    existing_acct = existing_data.get("account") or {}
    merged_acct = dict(existing_acct)
    merged_acct.update(incoming_acct)
    for _preserve_key in ("total_deposits", "total_withdrawals"):
        if not incoming_acct.get(_preserve_key):
            merged_acct[_preserve_key] = existing_acct.get(_preserve_key, 0)

    # Prepare client data
    client_data = {
        "deals": mt5_deals,
        "positions": data.get("positions", []),
        "account": merged_acct,
        "evaluations": evaluations,
        "statistics": statistics,
        "dropdown_options": data.get("dropdown_options", {}),
        "identity": {
            "admin": admin_id,
            "trader": trader_id,
            "client": client_id,
            "email": client_info.get('email', email),
            "sheet_url": push_sheet_url
        },
        # Store aggregated comment data if provided (from Push by Comment feature).
        # IMPORTANT: a fresh MT5 push (signaled by mt5_deals OR mt5_account being
        # present in the payload, OR an explicit aggregated_by_comment key in the
        # request body) ALWAYS overwrites the persisted aggregates — even if the
        # new value is an empty list.  This prevents stale rows (e.g. old internal
        # transfers, deleted positions) from resurrecting from cache when the
        # latest live MT5 state no longer contains them.
        "aggregated_by_comment": (
            aggregated_by_comment
            if (aggregated_by_comment or mt5_deals or mt5_account or ("aggregated_by_comment" in data))
            else existing_data.get("aggregated_by_comment", [])
        ),
        "comment_summary": (
            comment_summary
            if (comment_summary or mt5_deals or mt5_account or ("comment_summary" in data))
            else existing_data.get("comment_summary", {})
        ),
    }

    # Persist last Companion version seen for this client (if supplied)
    if companion_version:
        try:
            from datetime import datetime as _dt
            client_data.setdefault("identity", {})
            client_data["identity"]["companion_version"] = companion_version
            client_data["identity"]["companion_version_updated_at"] = _dt.utcnow().isoformat(timespec="seconds") + "Z"
        except Exception:
            pass
    
    # Merge firm_billing: new push data wins per-firm, but preserve firms not in this push
    existing_firm_billing = existing_data.get("firm_billing") or {}
    pushed_firm_billing = data.get("firm_billing")
    if pushed_firm_billing:
        merged_billing = dict(existing_firm_billing)
        merged_billing.update(pushed_firm_billing)
        client_data["firm_billing"] = merged_billing
        app.logger.info(f"   - firm_billing: {list(merged_billing.keys())} (pushed: {list(pushed_firm_billing.keys())})")
    elif existing_firm_billing:
        client_data["firm_billing"] = existing_firm_billing

    # Final verification before save
    hr_final = statistics.get('hedging_review', {})
    app.logger.info(f"✅ SAVING DATA for {client_id}:")
    app.logger.info(f"📊 Statistics Section:")
    app.logger.info(f"   - hedging_review.total_deposits: ${hr_final.get('total_deposits', 0):.2f}")
    app.logger.info(f"   - hedging_review.total_withdrawals: ${hr_final.get('total_withdrawals', 0):.2f}")
    app.logger.info(f"   - hedging_review.current_balance: ${hr_final.get('current_balance', 0):.2f}")
    app.logger.info(f"   - hedging_review.actual_hedging_results: ${hr_final.get('actual_hedging_results', 0):.2f}")
    app.logger.info(f"   - hedging_review.sheet_hedging_results: ${hr_final.get('sheet_hedging_results', 0):.2f}")
    app.logger.info(f"   - hedging_review.discrepancy: ${hr_final.get('discrepancy', 0):.2f}")
    app.logger.info(f"   - account.total_deposits: ${mt5_account.get('total_deposits', 0) if mt5_account else 0:.2f}")
    app.logger.info(f"   - account.balance: ${mt5_account.get('balance', 0) if mt5_account else 0:.2f}")
    
    # Log final evaluation state
    app.logger.info(f"📋 Final Evaluation Rows Being Saved:")
    for i, ev in enumerate(evaluations[:5]):  # Show first 5
        prop_firm = ev.get('Prop Firm', 'Unknown')
        hedges = sum(1 for j in range(1, 8) if ev.get(f'Hedge Result {j}', '') and str(ev.get(f'Hedge Result {j}', '')).strip() not in ('', '-'))
        payouts = sum(1 for j in range(1, 10) if ev.get(f'Payout {j}', '') and str(ev.get(f'Payout {j}', '')).strip() not in ('', '-', '$0'))
        app.logger.info(f"   [{i}] {prop_firm}: {hedges} hedge cells, {payouts} payout cells")
    
    if len(evaluations) > 5:
        app.logger.info(f"   ... and {len(evaluations) - 5} more rows")
    
    if aggregated_by_comment:
        app.logger.info(f"   - aggregated_by_comment: {len(aggregated_by_comment)} groups")
    
    app.logger.info(f"💾 Saving to database...")
    
    # Determine change source for history tracking
    change_source = 'trader_app'
    if aggregated_by_comment:
        change_source = 'mt5_push_with_comments'
    elif mt5_account or mt5_deals:
        change_source = 'mt5_push'
    
    # Save to database WITH history tracking
    success, version = save_client_data_with_history(
        client_id, 
        client_data,
        action='DATA_PUSH',
        changed_by=email,
        changed_by_type='client',
        ip_address=get_remote_address(),
        change_source=change_source,
        change_description=f"Data push from trader app with {len(evaluations)} evaluations"
    )
    
    app.logger.info(f"✅ SAVED to database successfully (v{version})")
    app.logger.info(f"🔄 Updated Statistics:")
    stats_complete = statistics.get('profitability_completed', {})
    stats_inprogress = statistics.get('cashflow_inprogress', {})
    app.logger.info(f"   - Profitability Completed: P/L=${stats_complete.get('net_profit', 0):.2f}")
    app.logger.info(f"   - Cashflow In Progress: P/L=${stats_inprogress.get('net_profit', 0):.2f}")
    app.logger.info(f"   - Evaluations saved: {len(evaluations)} rows")
    
    # Update Hierarchy (in case new)
    add_admin(admin_id)
    add_trader(admin_id, trader_id)
    add_client(admin_id, trader_id, client_id)
    
    log_action('CLIENT_DATA_PUSH', 'client', email, get_remote_address(), f"Data pushed for {client_id} (v{version})")
    
    response_data = {
        "status": "success", 
        "message": f"Data updated for {client_id}",
        "version": version,
        "identity": {
            "admin": admin_id,
            "trader": trader_id,
            "client": client_id
        }
    }
    
    # Include hedge match log if we processed aggregated data
    if hedge_match_log:
        response_data["hedge_match_log"] = hedge_match_log
        response_data["hedge_updates"] = len([l for l in hedge_match_log if l.startswith("✅")])
    
    return jsonify(response_data)


@app.route('/api/client/migrate_sheet', methods=['POST'])
@limiter.limit("10 per minute")
def api_migrate_sheet():
    """
    Public endpoint - migrate data from Google Sheets using client email.
    Fetches data from Google Sheet and pushes it to the dashboard.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    sheet_url = data.get('sheet_url', '').strip()
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    if not sheet_url:
        return jsonify({"status": "error", "message": "Google Sheet URL required"}), 400
    
    # Look up client by email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered in the system"}), 404
    
    admin_id = client_info['admin']
    trader_id = client_info['trader']
    client_id = client_info['client']
    
    # Fetch data from Google Sheets
    try:
        # Import the data processor
        from utils.data_processor import fetch_evaluations, calculate_statistics, fetch_waterlog_history
        from dashboard.watermark_service import bulk_save_history
        import concurrent.futures

        try:
            from utils.sheet_helper import fetch_waterlog_data, fetch_waterlog_periods_from_sheet
        except ImportError:
            try:
                from dashboard.utils.sheet_helper import fetch_waterlog_data, fetch_waterlog_periods_from_sheet
            except ImportError:
                fetch_waterlog_data = None
                fetch_waterlog_periods_from_sheet = None
        try:
            from dashboard.watermark_service import save_waterlog_periods
        except ImportError:
            from watermark_service import save_waterlog_periods

        # Fetch evaluations, waterlog history and waterlog data in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_eval = executor.submit(fetch_evaluations, sheet_url)
            future_wl_hist = executor.submit(fetch_waterlog_history, sheet_url)
            future_wl_data = executor.submit(fetch_waterlog_data, sheet_url, client_id) if fetch_waterlog_data else None

            eval_result = future_eval.result()
            waterlog_history = future_wl_hist.result()
            wl_full = future_wl_data.result() if future_wl_data else None

        if isinstance(eval_result, tuple):
            evaluations, xlsx_notes = eval_result
        else:
            evaluations = eval_result
            xlsx_notes = {}
        if not evaluations:
            return jsonify({"status": "error", "message": "Could not fetch data from sheet. Make sure it's shared as 'Anyone with the link'. (Evaluations Tab)"}), 400
        
        # Save daily waterlog history
        waterlog_count = 0
        if waterlog_history:
            bulk_save_history(client_id, waterlog_history)
            waterlog_count = len(waterlog_history)

        # Save the bi-weekly period schedule WITH Low/High values
        if wl_full:
            from datetime import datetime as _wldt
            import re as _re

            def _parse_currency_str(s):
                try:
                    return float(_re.sub(r'[^0-9.\-]', '', str(s))) if s else None
                except Exception:
                    return None

            def _to_iso(date_str):
                """Convert M/D/YYYY to YYYY-MM-DD."""
                try:
                    return _wldt.strptime(date_str.strip(), '%m/%d/%Y').strftime('%Y-%m-%d')
                except Exception:
                    return None

            wl_periods = []
            wl_values  = {}
            for row in wl_full:
                fd = _to_iso(row.get('from_date', ''))
                td = _to_iso(row.get('to_date', ''))
                if fd and td:
                    wl_periods.append((fd, td))
                    low  = _parse_currency_str(row.get('low'))
                    high = _parse_currency_str(row.get('high'))
                    if low is not None or high is not None:
                        wl_values[fd] = {
                            'low':       low,
                            'high':      high,
                            'split_pct': row.get('split_pct', 50),
                        }

            if wl_periods:
                save_waterlog_periods(client_id, wl_periods, period_values=wl_values)
        elif fetch_waterlog_periods_from_sheet:
            # Fallback: save dates only (no Low/High)
            wl_periods = fetch_waterlog_periods_from_sheet(sheet_url)
            if wl_periods:
                save_waterlog_periods(client_id, wl_periods)
        
        # Get existing data to preserve MT5 account, historical accounts, and deletions
        existing_import_data = get_client_data(client_id) or {}
        existing_mt5 = existing_import_data.get('account') or None
        existing_hist = existing_import_data.get('statistics', {}).get('hedging_review', {}).get('historical_accounts')
        
        # Preserve _deleted flags: build fingerprints of previously deleted rows
        existing_evals = existing_import_data.get('evaluations', [])
        deleted_fingerprints = set()
        for ev in existing_evals:
            if isinstance(ev, dict) and ev.get('_deleted'):
                acct = str(ev.get('Account #') or ev.get('Account #.1') or '').strip()
                firm = str(ev.get('Prop Firm') or '').strip()
                size = str(ev.get('Account Size') or '').strip()
                if acct:
                    deleted_fingerprints.add((acct, firm, size))
        
        # Re-apply _deleted to matching incoming rows
        if deleted_fingerprints:
            for ev in evaluations:
                if isinstance(ev, dict):
                    acct = str(ev.get('Account #') or ev.get('Account #.1') or '').strip()
                    firm = str(ev.get('Prop Firm') or '').strip()
                    size = str(ev.get('Account Size') or '').strip()
                    if acct and (acct, firm, size) in deleted_fingerprints:
                        ev['_deleted'] = True
        
        # Calculate statistics including existing MT5 data and historical accounts
        statistics = calculate_statistics(evaluations, None, existing_mt5 if existing_mt5 else None, xlsx_notes=xlsx_notes,
                                          historical_accounts=existing_hist)
        
        # Preserve historical accounts in the new statistics
        if existing_hist:
            existing_hr = existing_import_data.get('statistics', {}).get('hedging_review', {})
            statistics.setdefault('hedging_review', {})['historical_accounts'] = existing_hist
            statistics['hedging_review']['historical_deposits'] = existing_hr.get('historical_deposits', 0)
            statistics['hedging_review']['historical_withdrawals'] = existing_hr.get('historical_withdrawals', 0)
            statistics['hedging_review']['historical_balance'] = existing_hr.get('historical_balance', 0)
        
        # Prepare client data
        client_data = {
            "deals": existing_import_data.get('deals', []),
            "positions": existing_import_data.get('positions', []),
            "account": existing_mt5 or {},
            "evaluations": evaluations,
            "statistics": statistics,
            "dropdown_options": {},
            "identity": {
                "admin": admin_id,
                "trader": trader_id,
                "client": client_id,
                "email": client_info.get('email', email),
                "sheet_url": sheet_url
            },
            "sheet_url": sheet_url,
            "migrated_at": datetime.now().isoformat(),
            # Preserve manually-entered fields that are not sourced from the sheet
            "prop_accounts": existing_import_data.get('prop_accounts', []),
            "vps_accounts": existing_import_data.get('vps_accounts', []),
            "hedge_accounts": existing_import_data.get('hedge_accounts', []),
            "payment_info": existing_import_data.get('payment_info', []),
            "payment_address": existing_import_data.get('payment_address', {}),
            "mt5_credentials": existing_import_data.get('mt5_credentials', {}),
        }
        
        # Save to database WITH history tracking - full overwrite (import replaces all existing data)
        success, version = save_client_data_with_history(
            client_id, 
            client_data,
            action='SHEET_IMPORT',
            changed_by=email,
            changed_by_type='client',
            ip_address=get_remote_address(),
            change_source='sheet_migration',
            change_description=f"Imported {len(evaluations)} records from Google Sheets",
            overwrite=True
        )
        
        # Save cell comments as notes (for Prop Progress display)
        notes_saved = 0
        if xlsx_notes:
            for row_idx, col_notes in xlsx_notes.items():
                if isinstance(row_idx, int) and isinstance(col_notes, dict):
                    for col_key, content in col_notes.items():
                        if content and str(content).strip():
                            save_client_note(client_id, row_idx, col_key, str(content).strip(), 'sheet_import')
                            notes_saved += 1

        # Update Hierarchy
        add_admin(admin_id)
        add_trader(admin_id, trader_id)
        add_client(admin_id, trader_id, client_id)
        
        log_action('SHEET_MIGRATION', 'client', email, get_remote_address(), 
                   f"Migrated {len(evaluations)} records + {waterlog_count} waterlog entries + {notes_saved} notes from Google Sheets for {client_id} (v{version})")
        
        # Return statistics for verification
        return jsonify({
            "status": "success", 
            "message": f"Successfully migrated {len(evaluations)} records and {waterlog_count} waterlog entries",
            "records_imported": len(evaluations),
            "version": version,
            "statistics": statistics,  # Include stats for client-side verification
            "identity": {
                "admin": admin_id,
                "trader": trader_id,
                "client": client_id
            }
        })
        
    except Exception as e:
        log_action('SHEET_MIGRATION_FAILED', 'client', email, get_remote_address(), str(e), False)
        return jsonify({"status": "error", "message": f"Migration failed: {str(e)}"}), 500


@app.route('/api/client/watermark_history/<client_id>')
@require_session
def api_get_watermark_history(client_id):
    """
    Get daily watermark history for a client.
    Restricted: Clients can only see their own waterlog history.
    """
    session_user = request.session_user
    user_type = session_user.get('user_type')
    user_id = session_user.get('user_identifier')
    
    # Handle URL encoding spaces if necessary (Flask usually decodes)
    # Check authorization
    is_authorized = False
    if user_type in ['super_admin', 'admin', 'trader', 'kwok_admin']:
        is_authorized = True
    elif user_type == 'bef_admin':
        is_authorized = can_access_client('bef_admin', None, client_id)
    elif user_type == 'client':
        # Check specific client ownership
        if user_id == client_id:
            is_authorized = True
        else:
            # Check if email matches (some systems use email as identifier)
            # Or if user_id is the email and client_id is the name?
            # 'client_id' in URL is the NAME (e.g. Jiang Quang Huang)
            # 'user_identifier' in session for client is usually the EMAIL.
            # We need to resolve email -> client_id
            client_by_email = get_client_by_email(user_id)
            if client_by_email and client_by_email['client'] == client_id:
                is_authorized = True
    
    if not is_authorized:
        return jsonify({"status": "error", "message": "Unauthorized access to client waterlog"}), 403

    try:
        from dashboard.watermark_service import get_watermark_history, get_lower_watermark, save_daily_profit
        from dashboard.database import get_client_data

        # --- Always snapshot today's live net profit so the Low Watermark is current ---
        today_str = __import__('datetime').datetime.now().strftime('%Y-%m-%d')
        try:
            client_data = get_client_data(client_id)
            if client_data:
                # Pull net profit directly from stored statistics
                # (already includes discrepancy from the last data push)
                stored_stats = client_data.get('statistics', {})
                live_net = None
                if isinstance(stored_stats, dict):
                    live_net = stored_stats.get('cashflow_inprogress', {}).get('net_profit')
                    if live_net is None:
                        live_net = stored_stats.get('profitability_completed', {}).get('net_profit')
                if live_net is not None:
                    save_daily_profit(client_id, live_net, today_str, source='live')
        except Exception as snap_err:
            logging.warning(f"Live watermark snapshot failed for {client_id}: {snap_err}")

        # Get history for the requested period (14 days)
        history = get_watermark_history(client_id, days=14)

        # Low watermark among previous days only (exclude today so live value is shown separately)
        prev_history = [h for h in history if h['date'] < today_str]
        low_watermark = min(prev_history, key=lambda x: x['profit']) if prev_history else None

        # Today's live entry
        today_entry = next((h for h in history if h['date'] == today_str), None)

        return jsonify({
            "status": "success",
            "history": history,
            "low_watermark": low_watermark,
            "today": today_entry
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/login', methods=['POST'])
@limiter.limit("10 per minute")
def api_login():
    email = request.json.get('email')
    client_ip = get_remote_address()
    
    if not email: 
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    client = get_client_by_email(email)
    if client:
        log_action('CLIENT_LOGIN', 'client', email, client_ip, 'Successful login')
        return jsonify({"status": "success", "redirect": f"/dashboard/{client['client']}"})
    
    log_action('CLIENT_LOGIN_FAILED', 'client', email, client_ip, 'Email not found', False)
    return jsonify({"status": "error", "message": "Email not found"}), 404

@app.route('/api/admin_login', methods=['POST'])
@limiter.limit("5 per minute")
def api_admin_login():
    """Secure admin login with session creation."""
    password = request.json.get('password')
    client_ip = get_remote_address()
    
    if not password:
        return jsonify({"status": "error", "message": "Password required"}), 400
    
    if verify_admin_password('super_admin', password):
        session_token = create_session('admin', 'super_admin', client_ip)
        log_action('ADMIN_LOGIN', 'admin', 'super_admin', client_ip, 'Successful login')
        
        response = jsonify({"status": "success", "redirect": "/super_admin"})
        response.set_cookie('session_token', session_token, httponly=True, secure=not app.debug, samesite='Strict')
        return response

@app.route('/logout')
def logout():
    """Logout via GET request - clears session and redirects to login."""
    session_token = request.cookies.get('session_token')
    if session_token:
        delete_session(session_token)
        log_action('LOGOUT', 'user', 'session', get_remote_address())
    
    response = redirect('/')
    response.delete_cookie('session_token')
    return response

@app.route('/api/logout', methods=['POST'])
def api_logout():
    """Logout and invalidate session (API endpoint)."""
    session_token = request.cookies.get('session_token')
    if session_token:
        delete_session(session_token)
    
    response = jsonify({"status": "success"})
    response.delete_cookie('session_token')
    return response

@app.route('/api/auth/my_sessions', methods=['GET'])
@require_session
def api_my_sessions():
    """List active login sessions for the current user (no secrets exposed)."""
    session_user = request.session_user
    token = request.cookies.get('session_token') or ''
    rows = list_sessions_public_for_user(
        session_user.get('user_type', ''),
        session_user.get('user_identifier', ''),
        token,
    )
    return jsonify({"status": "success", "sessions": rows, "count": len(rows)})


@app.route('/api/auth/revoke_other_sessions', methods=['POST'])
@require_session
@limiter.limit("10 per hour")
def api_revoke_other_sessions():
    """Invalidate every session except the current browser (sign out other devices)."""
    session_user = request.session_user
    token = request.cookies.get('session_token') or ''
    if not token:
        return jsonify({"status": "error", "message": "No session cookie"}), 400
    n = delete_other_sessions_for_user(
        session_user.get('user_type', ''),
        session_user.get('user_identifier', ''),
        token,
    )
    log_action(
        'REVOKE_OTHER_SESSIONS',
        session_user.get('user_type', ''),
        session_user.get('user_identifier', ''),
        get_remote_address(),
        f"revoked={n}",
    )
    return jsonify({"status": "success", "revoked": n})

# ============ Unified Authentication Endpoint ============

@app.route('/api/auth/check-admin', methods=['POST'])
@limiter.limit("20 per minute")
def check_admin_identifier():
    """Returns whether the given identifier requires a password (all users do)."""
    data = request.json or {}
    identifier = data.get('identifier', '').strip()
    if not identifier:
        return jsonify({"requires_password": False})
    user = find_user_by_identifier(identifier)
    if not user and '@' in identifier:
        user = get_user_by_email(identifier)
    # All recognised users require a password
    requires_password = bool(user)
    return jsonify({"requires_password": requires_password})

@app.route('/api/auth/login', methods=['POST'])
@limiter.limit("10 per minute")
def unified_login():
    """
    Unified login endpoint - auto-detects user type from email/username.
    All user types require email + password. Default password: Test@123
    """
    data = request.json
    identifier = data.get('identifier', '').strip()
    password = data.get('password', '')
    remember = data.get('remember', False)
    client_ip = get_remote_address()

    # Session durations:
    # - Default: 24h
    # - Remember: 7 days (requested)
    DEFAULT_SESSION_HOURS = 24
    REMEMBER_SESSION_DAYS = 7
    session_hours_valid = (REMEMBER_SESSION_DAYS * 24) if remember else DEFAULT_SESSION_HOURS
    cookie_max_age = (REMEMBER_SESSION_DAYS * 24 * 60 * 60) if remember else (DEFAULT_SESSION_HOURS * 60 * 60)
    
    if not identifier:
        return jsonify({"status": "error", "message": "Email is required"}), 400
    
    # Find user by identifier (email or username)
    user = find_user_by_identifier(identifier)
    
    # If not found in DB, check hierarchy (for email-only logins)
    # This allows users defined in hierarchy.json but not yet in user_credentials to login
    if not user and '@' in identifier:
        hierarchy_user = get_user_by_email(identifier)
        if hierarchy_user:
            user = hierarchy_user
    
    if not user:
        log_action('LOGIN_FAILED', 'unknown', identifier, client_ip, 'User not found', False)
        return jsonify({"status": "error", "message": "Email not found in system"}), 403
    
    user_type = user.get('user_type')
    username = user.get('username', identifier).strip()
    
    # Check account lockout
    if is_account_locked(username, user_type):
        log_action('LOGIN_LOCKED', user_type, username, client_ip, 'Account locked', False)
        return jsonify({"status": "error", "message": "Account locked. Too many failed attempts. Try again in 15 minutes."}), 429
    
    # Handle Super Admin login - REQUIRES PASSWORD
    if user_type == 'super_admin':
        if not password:
            return jsonify({"status": "error", "message": "Password is required for Super Admin"}), 400
        
        if verify_admin_password('super_admin', password):
            session_token = create_session('super_admin', 'super_admin', client_ip, hours_valid=session_hours_valid)
            record_login_attempt('super_admin', 'super_admin', client_ip, True)
            log_action('LOGIN_SUCCESS', 'super_admin', 'super_admin', client_ip)

            response = jsonify({
                "status": "success",
                "user_type": "super_admin",
                "redirect": "/super_admin",
                "must_change_password": False
            })
            response.set_cookie('session_token', session_token, httponly=True, secure=not app.debug, samesite='Lax', max_age=cookie_max_age)
            return response
        
        record_login_attempt('super_admin', 'super_admin', client_ip, False)
        log_action('LOGIN_FAILED', 'super_admin', 'super_admin', client_ip, 'Invalid password', False)
        return jsonify({"status": "error", "message": "Invalid password"}), 403
    
    # Handle BEF Admin login - REQUIRES PASSWORD (same flow as super_admin)
    if user_type == 'bef_admin':
        if not password:
            return jsonify({"status": "error", "message": "Password is required for BEF Admin"}), 400
        
        if verify_admin_password('bef_admin', password):
            session_token = create_session('bef_admin', 'bef_admin', client_ip, hours_valid=session_hours_valid)
            record_login_attempt('bef_admin', 'bef_admin', client_ip, True)
            log_action('LOGIN_SUCCESS', 'bef_admin', 'bef_admin', client_ip)

            response = jsonify({
                "status": "success",
                "user_type": "bef_admin",
                "redirect": "/bef_admin",
                "must_change_password": False
            })
            response.set_cookie('session_token', session_token, httponly=True, secure=not app.debug, samesite='Lax', max_age=cookie_max_age)
            return response
        
        record_login_attempt('bef_admin', 'bef_admin', client_ip, False)
        log_action('LOGIN_FAILED', 'bef_admin', 'bef_admin', client_ip, 'Invalid password', False)
        return jsonify({"status": "error", "message": "Invalid password"}), 403

    # Kwok admin — separate password, full read-only client access
    if user_type == 'kwok_admin':
        if not password:
            return jsonify({"status": "error", "message": "Password is required for Kwok Admin"}), 400

        if verify_admin_password('kwok_admin', password):
            session_token = create_session('kwok_admin', 'kwok_admin', client_ip, hours_valid=session_hours_valid)
            record_login_attempt('kwok_admin', 'kwok_admin', client_ip, True)
            log_action('LOGIN_SUCCESS', 'kwok_admin', 'kwok_admin', client_ip)
            response = jsonify({
                "status": "success",
                "user_type": "kwok_admin",
                "redirect": "/kwok_admin",
                "must_change_password": False
            })
            response.set_cookie('session_token', session_token, httponly=True, secure=not app.debug, samesite='Lax', max_age=cookie_max_age)
            return response

        record_login_attempt('kwok_admin', 'kwok_admin', client_ip, False)
        log_action('LOGIN_FAILED', 'kwok_admin', 'kwok_admin', client_ip, 'Invalid password', False)
        return jsonify({"status": "error", "message": "Invalid password"}), 403
    
    # Handle Admin/Trader/Client login - PASSWORD REQUIRED
    if not password:
        return jsonify({"status": "error", "message": "Password is required"}), 400

    # Auto-provision credentials if user exists in hierarchy but not in user_credentials DB
    if not find_user_by_identifier(username) and not find_user_by_identifier(user.get('email', '')):
        default_pw = 'Test@123'
        create_user(username, default_pw, user_type,
                    user.get('email'), user.get('parent_admin'), user.get('parent_trader'))

    # Verify password
    verified = verify_user_password(username, user_type, password)
    if not verified:
        record_login_attempt(username, user_type, client_ip, False)
        log_action('LOGIN_FAILED', user_type, username, client_ip, 'Invalid password', False)
        return jsonify({"status": "error", "message": "Invalid password"}), 403

    record_login_attempt(username, user_type, client_ip, True)
    log_action('LOGIN_SUCCESS', user_type, username, client_ip)
    
    # Determine redirect URL based on user type
    redirect_map = {
        'admin': f'/admin/{username}',
        'trader': f'/trader/{username}',
        'client': '/maintenance' if MAINTENANCE_MODE else f'/dashboard/{username}'
    }
    redirect_url = redirect_map.get(user_type, '/')
    
    must_change = verified.get('must_change_password', False)
    
    session_token = create_session(user_type, username, client_ip, hours_valid=session_hours_valid)
    response = jsonify({
        "status": "success",
        "user_type": user_type,
        "redirect": redirect_url,
        "must_change_password": must_change
    })
    response.set_cookie('session_token', session_token, httponly=True, secure=not app.debug, samesite='Lax', max_age=cookie_max_age)
    return response

# ============ User Management Endpoints (Admin only) ============

@app.route('/api/admin/create_user', methods=['POST'])
@require_role('super_admin')
@limiter.limit("20 per hour")
def api_create_user():
    """Create a new user account."""
    data = request.json
    username = data.get('username')
    user_type = data.get('user_type')  # admin, trader, or client
    email = data.get('email')
    
    # Auto-generate password if not provided
    password = data.get('password')
    if not password:
        password = 'Test@123'
    
    parent_admin = data.get('parent_admin')
    parent_trader = data.get('parent_trader')
    
    if not username or not user_type:
        return jsonify({"status": "error", "message": "Username and user_type required"}), 400
    
    if user_type not in ['admin', 'trader', 'client']:
        return jsonify({"status": "error", "message": "Invalid user type"}), 400
    
    # Check if user already exists in DB
    user_db_exists = user_exists(username, user_type)
    
    # Check if user exists in Hierarchy
    hierarchy_exists = False
    if user_type == 'admin':
        if username in hierarchy.get('admins', {}):
            hierarchy_exists = True
    elif user_type == 'trader':
        for adm in hierarchy.get('admins', {}).values():
            if username in adm.get('traders', {}):
                hierarchy_exists = True
                break
    elif user_type == 'client':
        for adm in hierarchy.get('admins', {}).values():
            for tr in adm.get('traders', {}).values():
                clients = tr.get('clients', [])
                for cl in clients:
                    c_name = cl.get('name') if isinstance(cl, dict) else cl
                    if c_name == username:
                        hierarchy_exists = True
                        break
                if hierarchy_exists: break
            if hierarchy_exists: break

    if user_db_exists and hierarchy_exists:
        return jsonify({"status": "error", "message": f"{user_type.title()} '{username}' already exists"}), 400
    
    # Create user in database (auth) if not exists
    if not user_db_exists:
        if not create_user(username, password, user_type, email, parent_admin, parent_trader):
            return jsonify({"status": "error", "message": "Failed to create user"}), 500

    # Update Hierarchy (for display) - even if they existed in DB but not hierarchy
    try:
        if user_type == 'admin':
            if not hierarchy_exists:
                add_admin(username, email)
        elif user_type == 'trader':
            if not hierarchy_exists:
                # Map parent_user to parent_admin for simple logic if needed, 
                # but request.json usually sends 'parent_user' which we need to grab
                p_admin = data.get('parent_user') or parent_admin
                if p_admin:
                    add_trader(p_admin, username, email)
        elif user_type == 'client':
            if not hierarchy_exists:
                p_trader = data.get('parent_user') or parent_trader
                # We need to find the admin for this trader to call add_client(admin, trader, client)
                # Search hierarchy for the trader
                found_admin = None
                if hierarchy.get('admins'):
                    for adm, a_data in hierarchy['admins'].items():
                        if p_trader in a_data.get('traders', {}):
                            found_admin = adm
                            break
                if found_admin and p_trader:
                    add_client(found_admin, p_trader, username, email)
    except Exception as e:
        print(f"Hierarchy update failed: {e}")
        # Continue, as user was created in DB

    log_action('CREATE_USER', 'admin', username, get_remote_address(), f"Type: {user_type}")
    return jsonify({"status": "success", "message": f"{user_type.title()} '{username}' created successfully"})

def can_manage_user(manager_type, manager_identifier, target_username, target_user_type):
    """Check if a user can manage (reset password, deactivate) another user."""
    if manager_type == 'super_admin':
        return True  # Super admin can manage everyone
    
    if manager_type == 'admin':
        # Admin can manage traders and clients under them
        admin_data = hierarchy.get('admins', {}).get(manager_identifier, {})
        
        if target_user_type == 'trader':
            # Check if trader is under this admin
            return target_username in admin_data.get('traders', {})
        
        if target_user_type == 'client':
            # Check if client is under any of this admin's traders
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    if client.get('name') == target_username or client.get('email') == target_username:
                        return True
            return False
        
        return False  # Admin cannot manage other admins
    
    if manager_type == 'trader':
        # Trader can only manage their clients
        if target_user_type != 'client':
            return False
        
        for admin_data in hierarchy.get('admins', {}).values():
            trader_data = admin_data.get('traders', {}).get(manager_identifier, {})
            for client in trader_data.get('clients', []):
                if client.get('name') == target_username or client.get('email') == target_username:
                    return True
        return False
    
    return False

@app.route('/api/admin/list_users', methods=['GET'])
@require_admin_password
def api_list_users():
    """List all users."""
    user_type = request.args.get('type')
    users = list_users(user_type)
    return jsonify({"status": "success", "users": users})

@app.route('/api/user/reset_password', methods=['POST'])
@require_role('super_admin', 'admin', 'trader')
def api_reset_password_rbac():
    """Reset a user's password with role-based access control."""
    session_user = request.session_user
    manager_type = session_user.get('user_type')
    manager_id = session_user.get('user_identifier')
    
    data = request.json
    username = data.get('username')
    user_type = data.get('user_type')
    email = data.get('email')
    
    if not username or not user_type:
        return jsonify({"status": "error", "message": "Username and user_type required"}), 400
    
    # Check if user has permission to reset this user's password
    if not can_manage_user(manager_type, manager_id, username, user_type):
        log_action('RESET_PASSWORD_DENIED', manager_type, manager_id, get_remote_address(), 
                   f"Attempted to reset: {username} ({user_type})", False)
        return jsonify({"status": "error", "message": "Access denied. You can only manage users under your hierarchy."}), 403
    
    temp_password = reset_user_password(username, user_type)
    if temp_password:
        log_action('RESET_PASSWORD', manager_type, username, get_remote_address(), f"By: {manager_id}")
        
        email_sent = False
        if email:
            # Import email sender lazily so we don't touch stdlib email modules
            # unless we actually need to send an email (avoids Windows watchdog reload loops).
            try:
                from dashboard.email_service import send_password_reset_with_temp
                email_sent = send_password_reset_with_temp(email, username, temp_password)
            except Exception as e:
                app.logger.warning(f"[RESET_PASSWORD] Email send failed for {username}: {e}")
        
        return jsonify({
            "status": "success", 
            "message": f"Password reset for {username}",
            "temporary_password": temp_password,
            "email_sent": email_sent,
            "all_sessions_invalidated": True,
        })
    
    return jsonify({"status": "error", "message": "User not found"}), 404

@app.route('/api/admin/reset_password', methods=['POST'])
@require_admin_password
def api_reset_password():
    """Reset a user's password (legacy - uses password header)."""
    data = request.json
    username = data.get('username')
    user_type = data.get('user_type')
    email = data.get('email')  # Optional - for email notification
    
    if not username or not user_type:
        return jsonify({"status": "error", "message": "Username and user_type required"}), 400
    
    temp_password = reset_user_password(username, user_type)
    if temp_password:
        log_action('RESET_PASSWORD', 'admin', username, get_remote_address(), f"Type: {user_type}")
        
        # Send email notification if email provided
        email_sent = False
        if email:
            try:
                from dashboard.email_service import send_password_reset_with_temp
                email_sent = send_password_reset_with_temp(email, username, temp_password)
            except Exception as e:
                app.logger.warning(f"[RESET_PASSWORD] Email send failed for {username}: {e}")
        
        return jsonify({
            "status": "success", 
            "message": f"Password reset for {username}",
            "temporary_password": temp_password,
            "email_sent": email_sent,
            "all_sessions_invalidated": True,
        })
    
    return jsonify({"status": "error", "message": "User not found"}), 404

@app.route('/api/admin/set_password', methods=['POST'])
@require_role('super_admin')
def api_set_password():
    """Super admin sets a specific password for any user."""
    data = request.json
    username = data.get('username')
    user_type = data.get('user_type')
    new_password = data.get('new_password')

    if not username or not user_type or not new_password:
        return jsonify({"status": "error", "message": "username, user_type and new_password required"}), 400
    if len(new_password) < 6:
        return jsonify({"status": "error", "message": "Password must be at least 6 characters"}), 400

    # Auto-provision if the user has no credentials row yet
    if not user_exists(username, user_type):
        create_user(username, new_password, user_type)
        log_action('SET_PASSWORD', 'super_admin', username, get_remote_address(), f"Created + set ({user_type})")
        return jsonify({"status": "success", "message": f"Credentials created for {username} with provided password"})

    if update_user_password(username, user_type, new_password):
        log_action('SET_PASSWORD', 'super_admin', username, get_remote_address(), f"Type: {user_type}")
        return jsonify({"status": "success", "message": f"Password set for {username}"})

    return jsonify({"status": "error", "message": "Failed to set password"}), 500

@app.route('/api/admin/deactivate_user', methods=['POST'])
@require_admin_password
def api_deactivate_user():
    """Deactivate a user account."""
    data = request.json
    username = data.get('username')
    user_type = data.get('user_type')
    
    if not username or not user_type:
        return jsonify({"status": "error", "message": "Username and user_type required"}), 400
    
    if deactivate_user(username, user_type):
        log_action('DEACTIVATE_USER', 'admin', username, get_remote_address(), f"Type: {user_type}")
        return jsonify({"status": "success", "message": f"User '{username}' deactivated"})
    
    return jsonify({"status": "error", "message": "User not found"}), 404

# ============ Change Password Endpoint ============

@app.route('/change-password')
@require_session
def change_password_page():
    """Page to change password."""
    session_user = request.session_user
    user_type = session_user.get('user_type')
    username = session_user.get('user_identifier')
    must_change = False
    if user_type not in ('super_admin', 'bef_admin', 'kwok_admin'):
        user_record = find_user_by_identifier(username)
        must_change = bool(user_record and user_record.get('must_change_password'))
    return render_template('change_password.html', must_change_password=must_change)

@app.route('/api/auth/change_password', methods=['POST'])
@require_session
@limiter.limit("5 per hour")
def api_change_password():
    """Change user's own password."""
    data = request.json
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    skip_current = data.get('skip_current', False)
    
    if not new_password:
        return jsonify({"status": "error", "message": "New password required"}), 400
    
    if not skip_current and not current_password:
        return jsonify({"status": "error", "message": "Current and new password required"}), 400
    
    if len(new_password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters"}), 400
    
    session_user = request.session_user
    user_type = session_user.get('user_type')
    username = session_user.get('user_identifier')
    
    # If skip_current requested, verify user actually has must_change_password set
    if skip_current and user_type not in ('super_admin', 'bef_admin', 'kwok_admin'):
        user_record = find_user_by_identifier(username)
        if not user_record or not user_record.get('must_change_password'):
            return jsonify({"status": "error", "message": "Current password is required"}), 400
    
    # Verify current password (unless must_change_password skip)
    if user_type == 'super_admin':
        if not skip_current and not verify_admin_password('super_admin', current_password):
            return jsonify({"status": "error", "message": "Current password is incorrect"}), 403
        if set_admin_password('super_admin', new_password):
            log_action('CHANGE_PASSWORD', 'super_admin', 'super_admin', get_remote_address())
            return jsonify({"status": "success", "message": "Password changed successfully"})
    elif user_type == 'bef_admin':
        if not skip_current and not verify_admin_password('bef_admin', current_password):
            return jsonify({"status": "error", "message": "Current password is incorrect"}), 403
        if set_admin_password('bef_admin', new_password):
            log_action('CHANGE_PASSWORD', 'bef_admin', 'bef_admin', get_remote_address())
            return jsonify({"status": "success", "message": "Password changed successfully"})
    elif user_type == 'kwok_admin':
        if not skip_current and not verify_admin_password('kwok_admin', current_password):
            return jsonify({"status": "error", "message": "Current password is incorrect"}), 403
        if set_admin_password('kwok_admin', new_password):
            log_action('CHANGE_PASSWORD', 'kwok_admin', 'kwok_admin', get_remote_address())
            return jsonify({"status": "success", "message": "Password changed successfully"})
    else:
        if not skip_current:
            user_info = verify_user_password(username, user_type, current_password)
            if not user_info:
                return jsonify({"status": "error", "message": "Current password is incorrect"}), 403
        if update_user_password(username, user_type, new_password):
            log_action('CHANGE_PASSWORD', user_type, username, get_remote_address())
            return jsonify({"status": "success", "message": "Password changed successfully"})
    
    return jsonify({"status": "error", "message": "Failed to change password"}), 500

# ============ KYC Link Management Endpoints ============

@app.route('/api/kyc/link', methods=['POST'])
@require_role('super_admin')
def api_kyc_link():
    """Link a secondary client to a primary client as a KYC account."""
    data = request.json
    primary = data.get('primary_client', '').strip()
    linked = data.get('linked_client', '').strip()
    if not primary or not linked:
        return jsonify({"status": "error", "message": "primary_client and linked_client required"}), 400
    if primary == linked:
        return jsonify({"status": "error", "message": "Cannot link a client to themselves"}), 400
    # Prevent linking a client that is already a primary of other links
    existing_links = get_kyc_linked_clients(linked)
    if existing_links:
        return jsonify({"status": "error", "message": f"'{linked}' is already a primary account with linked KYCs. Unlink those first."}), 400
    if add_kyc_link(primary, linked, request.session_user.get('user_identifier', 'super_admin')):
        sync_kyc_links_into_hierarchy()
        log_action('KYC_LINK', 'super_admin', primary, get_remote_address(), f"Linked: {linked}")
        return jsonify({"status": "success", "message": f"'{linked}' linked to '{primary}' as KYC"})
    return jsonify({"status": "error", "message": "Link already exists or failed"}), 400

@app.route('/api/kyc/unlink', methods=['POST'])
@require_role('super_admin')
def api_kyc_unlink():
    """Remove a KYC link."""
    data = request.json
    primary = data.get('primary_client', '').strip()
    linked = data.get('linked_client', '').strip()
    if not primary or not linked:
        return jsonify({"status": "error", "message": "primary_client and linked_client required"}), 400
    if remove_kyc_link(primary, linked):
        log_action('KYC_UNLINK', 'super_admin', primary, get_remote_address(), f"Unlinked: {linked}")
        return jsonify({"status": "success", "message": f"'{linked}' unlinked from '{primary}'"})
    return jsonify({"status": "error", "message": "Link not found"}), 404

@app.route('/api/kyc/links', methods=['GET'])
@require_role('super_admin', 'bef_admin', 'kwok_admin')
def api_kyc_list_all():
    """List all KYC links (super admin view)."""
    return jsonify({"status": "success", "links": get_all_kyc_links()})

@app.route('/api/kyc/accounts', methods=['GET'])
@require_session
def api_kyc_accounts():
    """Get all KYC-linked accounts for the current user or a specified client."""
    session_user = request.session_user
    user_type = session_user.get('user_type')
    client_id = request.args.get('client_id', session_user.get('user_identifier', ''))
    
    # Admins/super_admins can query any client; clients can only query themselves
    if user_type == 'client' and client_id != session_user.get('user_identifier'):
        return jsonify({"status": "error", "message": "Access denied"}), 403
    
    # Only primary KYC clients see linked accounts; linked clients see only themselves
    if is_kyc_primary(client_id):
        accounts = get_all_kyc_accounts(client_id)
    else:
        accounts = [client_id]
    # Enrich with basic client info
    is_bef = user_type == 'bef_admin'
    from dashboard.financial_overview import get_client_profile as _gcp
    result = []
    for name in accounts:
        cdata = get_client_data(name)
        if not cdata:
            if is_bef:
                identity = {}
                if _gcp(name, identity) != 'BEF':
                    continue
            result.append({"name": name, "eval_count": 0, "is_current": name == client_id})
            continue
        if is_bef:
            # BEF admin: only show clients whose profile/category is BEF (with hierarchy fallback)
            identity = cdata.get('identity') or {}
            if _gcp(name, identity) != 'BEF':
                continue
        evals = [ev for ev in cdata.get('evaluations', []) if isinstance(ev, dict)]
        if is_bef:
            # Exclude hidden prop firms from eval count
            evals = [ev for ev in evals
                     if str(ev.get('Prop Firm') or '').strip().lower().replace(' ', '') not in BEF_HIDDEN_FIRMS]
        result.append({"name": name, "eval_count": len(evals), "is_current": name == client_id})
    return jsonify({"status": "success", "accounts": result, "has_kyc_links": len(result) > 1, "is_primary": is_kyc_primary(client_id)})

@app.route('/api/kyc/portfolio', methods=['GET'])
@require_session
def api_kyc_portfolio():
    """Get combined portfolio stats across all KYC-linked accounts.
    Reads directly from stored statistics (same as client Stats tab) for consistency.
    """
    session_user = request.session_user
    user_type = session_user.get('user_type')
    user_id = session_user.get('user_identifier', '')
    client_id = request.args.get('client_id', '')
    
    is_bef = user_type == 'bef_admin'

    # Determine which client to query
    if user_type in ('super_admin', 'bef_admin', 'kwok_admin', 'admin', 'trader'):
        if not client_id:
            return jsonify({"status": "error", "message": "client_id required"}), 400
    elif user_type == 'client':
        client_id = client_id or user_id
        if client_id != user_id:
            return jsonify({"status": "error", "message": "Access denied"}), 403
    else:
        return jsonify({"status": "error", "message": "Access denied"}), 403
    
    if not is_kyc_primary(client_id):
        return jsonify({"status": "error", "message": "Not a primary KYC account"}), 403
    
    from_date = request.args.get('from', '')
    to_date = request.args.get('to', '')
    
    accounts = get_all_kyc_accounts(client_id)
    from dashboard.financial_overview import parse_currency, get_client_profile as _gcp
    
    def parse_date_safe(val):
        if not val or not isinstance(val, str):
            return None
        clean = val.strip()
        if not clean or clean in ('-', 'n/a', 'null', ''):
            return None
        for fmt in ('%m/%d/%y', '%m/%d/%Y', '%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d',
                    '%m-%d-%Y', '%m-%d-%y', '%d-%m-%Y', '%d-%m-%y',
                    '%b %d, %Y', '%B %d, %Y', '%d %b %Y', '%d %B %Y'):
            try:
                return datetime.strptime(clean, fmt).date()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(clean.replace('Z', '+00:00')).date()
        except Exception:
            return None

    filter_from = parse_date_safe(from_date) if from_date else None
    filter_to = parse_date_safe(to_date) if to_date else None
    has_date_filter = bool(filter_from or filter_to)

    def date_in_period(date_str):
        if not has_date_filter:
            return True
        d = parse_date_safe(date_str)
        if not d:
            return True
        if filter_from and d < filter_from:
            return False
        if filter_to and d > filter_to:
            return False
        return True

    def eval_in_period(ev):
        if not has_date_filter:
            return True
        d = parse_date_safe(ev.get('Date Purchased')) or parse_date_safe(ev.get('Date Started'))
        if not d:
            return False
        if filter_from and d < filter_from:
            return False
        if filter_to and d > filter_to:
            return False
        return True

    def format_display_date(date_str):
        if not date_str or not isinstance(date_str, str):
            return date_str or '-'
        d = parse_date_safe(date_str)
        if not d:
            return date_str
        return f"{d.strftime('%b')} {d.day}, {d.year}"

    totals = {
        "total_payouts": 0.0, "total_deposits": 0.0, "total_fees": 0.0,
        "total_net_profit": 0.0, "total_hedge": 0.0, "total_farming": 0.0,
        "active_accounts": 0, "passed_accounts": 0, "failed_accounts": 0,
        "total_evaluations": 0
    }
    per_account = []
    all_payouts = []
    by_prop_firm = {}

    for name in accounts:
        cdata = get_client_data(name)
        if not cdata:
            if is_bef:
                if _gcp(name, {}) != 'BEF':
                    continue
            per_account.append({"name": name, "eval_count": 0, "payouts": 0, "fees": 0, "hedge": 0, "farming": 0, "net": 0, "active": 0, "passed": 0, "failed": 0})
            continue
        # BEF admin: skip clients whose profile is not BEF (with hierarchy fallback)
        if is_bef:
            identity = cdata.get('identity') or {}
            if _gcp(name, identity) != 'BEF':
                continue

        all_evals = [ev for ev in cdata.get('evaluations', []) if isinstance(ev, dict)]

        # BEF admin: exclude hidden prop firms (Lucid, Apex, TradeDay, TopOneFutures)
        if is_bef:
            all_evals = [ev for ev in all_evals
                         if str(ev.get('Prop Firm') or '').strip().lower().replace(' ', '') not in BEF_HIDDEN_FIRMS]

        if not has_date_filter and not is_bef:
            # ── No date filter: use stored statistics (consistent with Stats tab) ──
            stats = cdata.get('statistics', {}) or {}
            cashflow = stats.get('cashflow_inprogress', {})
            et = stats.get('eval_totals', {})

            s_payouts = cashflow.get('payouts', 0.0) or 0.0
            s_fees = cashflow.get('challenge_fees', 0.0) or 0.0
            s_hedge = cashflow.get('hedging_results', 0.0) or 0.0
            s_farming = cashflow.get('farming_results', 0.0) or 0.0
            s_net = s_payouts + s_hedge + s_farming - s_fees
            s_active = et.get('total_running', 0) or 0
            s_passed = et.get('total_passed', 0) or 0
            s_failed = et.get('total_failed', 0) or 0
            s_evals = len(all_evals)

            # If stored eval_totals seem incomplete, recount from raw evaluations
            if s_evals > 0 and (s_active + s_passed + s_failed) == 0:
                for ev in all_evals:
                    sp1 = str(ev.get('Status P1') or '').strip().lower()
                    sf = str(ev.get('Status') or '').strip().lower()
                    if sp1 == 'fail' or sf in ('fail', 'failed', 'breached', 'blown'):
                        s_failed += 1
                    elif sf in ('completed', 'passed', 'funded'):
                        s_passed += 1
                    else:
                        s_active += 1

            acc_stats = {
                "name": name, "eval_count": s_evals,
                "payouts": round(s_payouts, 2), "fees": round(s_fees, 2),
                "hedge": round(s_hedge, 2), "farming": round(s_farming, 2),
                "net": round(s_net, 2),
                "active": s_active, "passed": s_passed, "failed": s_failed
            }
        else:
            # ── Date filter active: recalculate from evaluations in period ──
            period_evals = [ev for ev in all_evals if eval_in_period(ev)]
            acc_stats = {"name": name, "eval_count": len(period_evals),
                         "payouts": 0.0, "fees": 0.0, "hedge": 0.0, "farming": 0.0,
                         "net": 0.0, "active": 0, "passed": 0, "failed": 0}

            for ev in period_evals:
                status = str(ev.get('Status') or '').lower()
                if any(s in status for s in ['passed', 'funded']):
                    acc_stats["passed"] += 1
                elif any(s in status for s in ['failed', 'breached', 'blown', 'fail']):
                    acc_stats["failed"] += 1
                elif any(s in status for s in ['active', 'phase', 'running', 'ongoing', 'trading', 'challenge']):
                    acc_stats["active"] += 1

                acc_stats["fees"] += parse_currency(ev.get('Fee')) + parse_currency(ev.get('Activation Fee'))

                # Only count hedge/farming for rows with a populated status
                ev_status_p1 = str(ev.get('Status P1') or '').strip()
                ev_status_funded = str(ev.get('Status') or '').strip()
                if ev_status_p1:
                    for col in ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']:
                        acc_stats["hedge"] += parse_currency(ev.get(col))
                if ev_status_funded:
                    for col in ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1',
                                'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']:
                        acc_stats["hedge"] += parse_currency(ev.get(col))
                    for di in range(1, 51):
                        acc_stats["farming"] += parse_currency(ev.get(f'Hedge Day {di}'))

            # Payouts from ALL evals filtered by individual payout date
            for ev in all_evals:
                for i in range(1, 10):
                    pval = parse_currency(ev.get(f'Payout {i}'))
                    if pval != 0:
                        pdate = str(ev.get(f'Date {i}') or '-').strip()
                        if date_in_period(pdate):
                            acc_stats["payouts"] += pval

            acc_stats["net"] = round(acc_stats["payouts"] - acc_stats["fees"] + acc_stats["hedge"] + acc_stats["farming"], 2)
            acc_stats["payouts"] = round(acc_stats["payouts"], 2)
            acc_stats["fees"] = round(acc_stats["fees"], 2)
            acc_stats["hedge"] = round(acc_stats["hedge"], 2)
            acc_stats["farming"] = round(acc_stats["farming"], 2)

        # Accumulate totals
        totals["total_payouts"] += acc_stats["payouts"]
        totals["total_fees"] += acc_stats["fees"]
        totals["total_hedge"] += acc_stats["hedge"]
        totals["total_farming"] += acc_stats["farming"]
        totals["total_net_profit"] += acc_stats["net"]
        totals["active_accounts"] += acc_stats["active"]
        totals["passed_accounts"] += acc_stats["passed"]
        totals["failed_accounts"] += acc_stats["failed"]
        totals["total_evaluations"] += acc_stats["eval_count"]

        per_account.append(acc_stats)

        # Collect individual payout records and prop firm breakdown from evals
        for ev in all_evals:
            prop_firm = str(ev.get('Prop Firm') or 'Unknown').strip() or 'Unknown'
            account_num = str(ev.get('Account #') or ev.get('Account #.1') or '-').strip()

            for i in range(1, 10):
                pval = parse_currency(ev.get(f'Payout {i}'))
                if pval != 0:
                    pdate = str(ev.get(f'Date {i}') or '-').strip()
                    if date_in_period(pdate):
                        raw_date = parse_date_safe(pdate)
                        all_payouts.append({
                            "client": name, "prop_firm": prop_firm, "account": account_num,
                            "payout_num": i, "amount": round(pval, 2), "date": format_display_date(pdate),
                            "_sort_date": raw_date.isoformat() if raw_date else "0000-00-00"
                        })

            if prop_firm not in by_prop_firm:
                by_prop_firm[prop_firm] = {"evals": 0, "payouts": 0.0, "fees": 0.0, "hedge": 0.0, "farming": 0.0, "net": 0.0, "active": 0, "passed": 0, "failed": 0}
            pf = by_prop_firm[prop_firm]
            pf["evals"] += 1

            status = str(ev.get('Status') or '').lower()
            status_p1_raw = str(ev.get('Status P1') or '').strip()
            status_funded_raw = str(ev.get('Status') or '').strip()
            fee = parse_currency(ev.get('Fee'))
            act_fee = parse_currency(ev.get('Activation Fee'))
            pf["fees"] += (fee + act_fee)

            # Only count hedge/farming for rows with a populated status
            if status_p1_raw:
                for col in ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']:
                    pf["hedge"] += parse_currency(ev.get(col))
            if status_funded_raw:
                for col in ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1',
                            'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']:
                    pf["hedge"] += parse_currency(ev.get(col))
                for di in range(1, 51):
                    pf["farming"] += parse_currency(ev.get(f'Hedge Day {di}'))

            for j in range(1, 10):
                pf["payouts"] += parse_currency(ev.get(f'Payout {j}'))

            if any(s in status for s in ['passed', 'funded']):
                pf["passed"] += 1
            elif any(s in status for s in ['failed', 'breached', 'blown', 'fail']):
                pf["failed"] += 1
            elif any(s in status for s in ['active', 'phase', 'running', 'ongoing', 'trading', 'challenge']):
                pf["active"] += 1

    # Round totals
    for k in ["total_payouts", "total_fees", "total_hedge", "total_farming", "total_net_profit"]:
        totals[k] = round(totals[k], 2)

    # Round prop firm breakdown
    prop_firm_list = []
    for pf_name, pf in by_prop_firm.items():
        pf["net"] = round(pf["payouts"] - pf["fees"] + pf["hedge"] + pf["farming"], 2)
        pf["payouts"] = round(pf["payouts"], 2)
        pf["fees"] = round(pf["fees"], 2)
        pf["hedge"] = round(pf["hedge"], 2)
        pf["farming"] = round(pf["farming"], 2)
        prop_firm_list.append({"name": pf_name, **pf})
    prop_firm_list.sort(key=lambda x: x["payouts"], reverse=True)

    all_payouts.sort(key=lambda x: x.get("_sort_date", "0000-00-00"), reverse=True)
    for p in all_payouts:
        p.pop("_sort_date", None)

    return jsonify({
        "status": "success",
        "primary": client_id,
        "totals": totals,
        "accounts": per_account,
        "payouts": all_payouts,
        "by_prop_firm": prop_firm_list,
        "period": {"from": from_date, "to": to_date}
    })

# ============ Admin/Trader/Client Management ============

@app.route('/api/add_admin', methods=['POST'])
def api_add_admin():
    name = request.json.get('name')
    email = request.json.get('email', '')
    if not name: return jsonify({"status": "error", "message": "Name required"}), 400
    
    if add_admin(name, email):
        log_action('ADD_ADMIN', 'system', name, get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Admin exists"}), 400

@app.route('/api/delete_user', methods=['POST'])
@require_role('super_admin')
def api_delete_user():
    data = request.json
    user_type = data.get('type')
    name = data.get('name')
    admin = data.get('admin')
    trader = data.get('trader')
    
    if not user_type or not name:
        return jsonify({"status": "error", "message": "Missing arguments"}), 400
        
    result = False
    if user_type == 'admin':
        result = remove_admin(name)
        delete_user_credential(name, 'admin')
            
    elif user_type == 'trader':
        if not admin: return jsonify({"status": "error", "message": "Admin parent required"}), 400
        result = remove_trader(admin, name)
        delete_user_credential(name, 'trader')
            
    elif user_type == 'client':
        result = _delete_client_everywhere(name, admin or '', trader or '')
    
    if result:
        log_action(f'DELETE_{user_type.upper()}', user_type, name, get_remote_address())
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "error", "message": "Delete failed (not found)"}), 400

@app.route('/api/update_admin', methods=['POST'])
def api_update_admin():
    name = request.json.get('name')
    email = request.json.get('email')
    slack_user_id = request.json.get('slack_user_id', None)
    new_name = request.json.get('new_name', '').strip()
    if not name: return jsonify({"status": "error", "message": "Name required"}), 400
    
    # Rename if new_name provided and different
    if new_name and new_name != name:
        if not rename_admin(name, new_name, email):
            return jsonify({"status": "error", "message": "Rename failed (name taken or not found)"}), 400
        rename_user_credential(name, new_name, 'admin')
        log_action('RENAME_ADMIN', 'admin', f'{name} -> {new_name}', get_remote_address())
        return jsonify({"status": "success"})
    
    if update_admin_details(name, email, slack_user_id=slack_user_id):
        update_user_email(name, 'admin', email)
        log_action('UPDATE_ADMIN', 'admin', name, get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Admin not found"}), 400

@app.route('/api/update_trader', methods=['POST'])
def api_update_trader():
    admin = request.json.get('admin')
    name = request.json.get('name')
    email = request.json.get('email')
    new_name = request.json.get('new_name', '').strip()
    if not admin or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    # Rename if new_name provided and different
    if new_name and new_name != name:
        if not rename_trader(admin, name, new_name, email):
            return jsonify({"status": "error", "message": "Rename failed (name taken or not found)"}), 400
        rename_user_credential(name, new_name, 'trader')
        log_action('RENAME_TRADER', 'trader', f'{name} -> {new_name}', get_remote_address(), f"Admin: {admin}")
        return jsonify({"status": "success"})
    
    if update_trader_details(admin, name, email):
        update_user_email(name, 'trader', email)
        log_action('UPDATE_TRADER', 'admin', name, get_remote_address(), f"Admin: {admin}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Trader not found"}), 400

@app.route('/api/update_client', methods=['POST'])
def api_update_client():
    admin = request.json.get('admin')
    trader = request.json.get('trader')
    name = request.json.get('name')
    email = request.json.get('email', '')
    category = request.json.get('category', '')
    new_name = request.json.get('new_name', '').strip()
    
    if not admin or not trader or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    # Rename if new_name provided and different
    if new_name and new_name != name:
        if not rename_client(admin, trader, name, new_name, email, category or None):
            return jsonify({"status": "error", "message": "Rename failed (not found)"}), 400
        rename_client_in_db(name, new_name)
        rename_user_credential(name, new_name, 'client')
        log_action('RENAME_CLIENT', 'client', f'{name} -> {new_name}', get_remote_address(), f"Trader: {trader}")
        return jsonify({"status": "success"})
    
    if category:
        update_client_category(admin, trader, name, category)
        # Also sync category into the DB identity blob so financial overview reads it
        try:
            client_data = get_client_data(name)
            if client_data:
                identity = client_data.get('identity', {})
                identity['profile'] = category
                identity['category'] = category
                update_client_field(name, 'identity', identity)
        except Exception as e:
            print(f"Error syncing category to DB identity: {e}")

    # Save active_status if provided
    active_status = request.json.get('active_status')
    if active_status:
        try:
            client_data = get_client_data(name)
            if client_data:
                identity = client_data.get('identity', {})
                identity['active_status'] = active_status
                update_client_field(name, 'identity', identity)
        except Exception as e:
            print(f"Error updating active_status: {e}")

    # Save split_pct (profit split percentage) if provided
    split_pct = request.json.get('split_pct')
    if split_pct is not None:
        try:
            split_pct_val = int(split_pct)
            if 0 <= split_pct_val <= 100:
                cd = get_client_data(name)
                if cd:
                    identity = cd.get('identity', {})
                    identity['split_pct'] = split_pct_val
                    update_client_field(name, 'identity', identity)
        except (ValueError, TypeError) as e:
            print(f"Error updating split_pct: {e}")
        
    if update_client_details(admin, trader, name, email):
        update_user_email(name, 'client', email)
        log_action('UPDATE_CLIENT', 'trader', name, get_remote_address(), f"Trader: {trader}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Client not found"}), 400

@app.route('/api/add_trader', methods=['POST'])
def api_add_trader():
    admin = request.json.get('admin')
    name = request.json.get('name')
    email = request.json.get('email', '')
    if not admin or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    if add_trader(admin, name, email):
        # Also ensure record exists in database
        try:
            # We don't have a "trader" table in database, user_credentials holds trader logins.
            if not user_exists(name, 'trader'):
                 temp_pass = "trader123" 
                 create_user(name, temp_pass, 'trader', email)
        except Exception as e:
            print(f"Error creating trader DB user: {e}")

        log_action('ADD_TRADER', 'admin', name, get_remote_address(), f"Admin: {admin}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Invalid request or Trader exists"}), 400

@app.route('/api/add_client', methods=['POST'])
def api_add_client():
    admin = request.json.get('admin')
    trader = request.json.get('trader')
    name = request.json.get('name')
    email = request.json.get('email', '')
    category = request.json.get('category', '')
    
    if not admin or not trader or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    if add_client(admin, trader, name, email, category):
        # IMPORTANT: Initialize database record for new client
        try:
            if not get_client_data(name): 
                initial_data = {
                    "identity": {
                        "name": name,
                        "email": email,
                        "category": category,
                        "profile": category,
                        "source": category or "Private",
                        "admin": admin,
                        "trader": trader,
                        "client": name
                    }
                }
                save_client_data(name, initial_data)
                
            # Create user credential for client portal access
            if email and not user_exists(name, 'client') and not find_user_by_identifier(email):
                 temp_pass = "client123"
                 create_user(name, temp_pass, 'client', email)
                 
        except Exception as e:
             print(f"Error creating client DB record: {e}")
             
        log_action('ADD_CLIENT', 'trader', name, get_remote_address(), f"Trader: {trader}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Invalid request or Client exists"}), 400

@app.route('/api/move_user', methods=['POST'])
def api_move_user():
    data = request.json
    user_type = data.get('type')
    name = data.get('name')
    
    if user_type == 'trader':
        old_admin = data.get('old_admin')
        new_admin = data.get('new_admin')
        if not all([name, old_admin, new_admin]): 
            return jsonify({"status": "error", "message": "Missing fields"}), 400
            
        if move_trader(name, old_admin, new_admin):
            try:
                # Update DB using raw SQL since no helper exposes raw update
                # We need to manually get a connection from the pool/manager
                # get_connection is imported from dashboard.database
                with get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("UPDATE user_credentials SET parent_admin = ? WHERE username = ? AND user_type = 'trader'", (new_admin, name))
                    # Also update all clients of this trader to point to new admin
                    cursor.execute("UPDATE user_credentials SET parent_admin = ? WHERE parent_trader = ? AND user_type = 'client'", (new_admin, name))
                    conn.commit()
            except Exception as e:
                print(f"DB update failed: {e}")
                
            log_action('MOVE_TRADER', 'super_admin', name, get_remote_address(), f"{old_admin} -> {new_admin}")
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error", "message": "Move failed (invalid target or user not found)"}), 400
            
    elif user_type == 'client':
        old_trader = data.get('old_trader')
        old_admin = data.get('old_admin')
        new_trader = data.get('new_trader') # The target trader
        new_admin = data.get('new_admin')   # The admin of the target trader (required for consistency)
        
        if not all([name, old_trader, old_admin, new_trader, new_admin]): 
             return jsonify({"status": "error", "message": "Missing fields"}), 400
             
        # Signature: move_client(client_name, old_admin, old_trader, new_admin, new_trader)
        if move_client(name, old_admin, old_trader, new_admin, new_trader):
            try:
                with get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE user_credentials SET parent_trader = ?, parent_admin = ? WHERE username = ? AND user_type = 'client'", 
                        (new_trader, new_admin, name)
                    )
                    conn.commit()
            except Exception as e:
                print(f"DB update failed: {e}")
                
            log_action('MOVE_CLIENT', 'super_admin', name, get_remote_address(), f"{old_trader} -> {new_trader}")
            return jsonify({"status": "success"})
        else:
             return jsonify({"status": "error", "message": "Move failed (duplicate name?)"}), 400

    return jsonify({"status": "error", "message": "Invalid type"}), 400

@app.route('/api/update_client_profile', methods=['POST'])
@require_session
def api_update_client_profile():
    session_user = request.session_user
    if session_user.get('user_type') not in ['admin', 'super_admin']:
         return jsonify({"status": "error", "message": "Access denied"}), 403

    data = request.json
    admin = data.get('admin')
    trader = data.get('trader')
    name = data.get('name')
    category = data.get('category')
    active_status = data.get('active_status', 'active')
    
    if not admin or not trader or not name or category is None:
         return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    from config.hierarchy import update_client_category
    
    if update_client_category(admin, trader, name, category):
        client_id = name
        
        try:
             client_data = get_client_data(client_id)
             if client_data:
                 identity = client_data.get('identity', {})
                 identity['profile'] = category 
                 identity['category'] = category
                 identity['active_status'] = active_status
                 update_client_field(client_id, 'identity', identity)
        except Exception as e:
             print(f"Error updating DB identity profile: {e}")

        log_action('UPDATE_CLIENT_PROFILE', session_user.get('user_type'), name, get_remote_address(), f"To: {category}, Status: {active_status}")
        return jsonify({"status": "success"})
    
    return jsonify({"status": "error", "message": "Client not found"}), 404


@app.route('/api/assign_client_trader', methods=['POST'])
@require_session
def api_assign_client_trader():
    """
    Reassign a client to a new trader and persist to:
    - hierarchy JSON (reassign_client_trader — auto-creates lane if needed)
    - user_credentials (parent_trader/parent_admin)
    - clients_data.identity (admin/trader fields, if record exists)
    """
    session_user = request.session_user
    if session_user.get('user_type') not in ('super_admin', 'bef_admin'):
        return jsonify({"status": "error", "message": "Access denied"}), 403

    data = request.json or {}
    client_name = (data.get('client_name') or '').strip()
    target_admin = (data.get('admin') or '').strip()
    new_trader = (data.get('new_trader') or '').strip()

    if not client_name or not target_admin or not new_trader:
        return jsonify({"status": "error", "message": "Missing fields"}), 400

    # Get current location before reassigning (for logging)
    from config.hierarchy import reload_hierarchy, get_client_profile
    reload_hierarchy()
    current = get_client_profile(client_name)
    if not current:
        return jsonify({"status": "error", "message": "Client not found in hierarchy"}), 404

    old_admin = (current.get('admin') or '').strip()
    old_trader = (current.get('trader') or '').strip()

    # Persist in hierarchy (auto-creates trader lane, handles idempotent same-assignment)
    if not reassign_client_trader(client_name, target_admin, new_trader):
        return jsonify({"status": "error", "message": "Reassignment failed"}), 400

    # Skip DB/identity updates if nothing actually changed
    if old_admin == target_admin and old_trader == new_trader:
        return jsonify({"status": "success", "message": "No change"})

    # Persist in DB
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE user_credentials SET parent_trader = ?, parent_admin = ? WHERE username = ? AND user_type = 'client'",
                (new_trader, target_admin, client_name)
            )
            conn.commit()
    except Exception as e:
        print(f"[assign_client_trader] DB update failed (user_credentials): {e}")

    # Update client identity record (if it exists)
    try:
        client_data = get_client_data(client_name)
        if client_data:
            identity = client_data.get('identity', {}) if isinstance(client_data, dict) else {}
            if not isinstance(identity, dict):
                identity = {}
            identity['admin'] = target_admin
            identity['trader'] = new_trader
            update_client_field(client_name, 'identity', identity)
    except Exception as e:
        print(f"[assign_client_trader] identity update failed: {e}")

    log_action(
        'ASSIGN_CLIENT_TRADER',
        session_user.get('user_type'),
        client_name,
        get_remote_address(),
        f"{old_admin}/{old_trader} -> {target_admin}/{new_trader}"
    )
    return jsonify({"status": "success"})


@app.route('/api/remove_admin', methods=['POST'])
def api_remove_admin():
    name = request.json.get('name')
    if not name: return jsonify({"status": "error", "message": "Name required"}), 400
    
    if remove_admin(name):
        log_action('REMOVE_ADMIN', 'system', name, get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Admin not found"}), 400

@app.route('/api/remove_trader', methods=['POST'])
def api_remove_trader():
    admin = request.json.get('admin')
    name = request.json.get('name')
    if not admin or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    if remove_trader(admin, name):
        log_action('REMOVE_TRADER', 'admin', name, get_remote_address(), f"Admin: {admin}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Trader not found"}), 400

@app.route('/api/remove_client', methods=['POST'])
def api_remove_client():
    admin = request.json.get('admin')
    trader = request.json.get('trader')
    name = request.json.get('name')
    if not admin or not trader or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    # Save a final snapshot before deletion so data can be recovered
    client_data = get_client_data(name)
    if client_data:
        from dashboard.database import save_data_snapshot
        save_data_snapshot(
            name, client_data,
            action='CLIENT_DELETED',
            changed_by='system',
            changed_by_type='admin',
            ip_address=get_remote_address(),
            change_source='client_removal',
            change_description=f"Final snapshot before client removal (Trader: {trader}, Admin: {admin})"
        )
    
    if _delete_client_everywhere(name, admin, trader):
        log_action('REMOVE_CLIENT', 'trader', name, get_remote_address(), f"Trader: {trader}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Client not found"}), 400

@app.route('/api/client/delete_evaluation', methods=['POST'])
@limiter.limit("30 per minute")
def api_delete_evaluation():
    """
    Delete an evaluation row with history tracking.
    Only super_admin users can delete evaluation rows.
    The data is removed from current view but can be recovered from version history.
    """
    # Require super_admin for all deletes
    session_token = request.cookies.get('session_token')
    if not session_token:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    session_info = validate_session(session_token)
    if not session_info:
        return jsonify({"status": "error", "message": "Invalid or expired session"}), 401
    if session_info.get('user_type') != 'super_admin':
        log_action('DELETE_DENIED', session_info.get('user_type'), session_info.get('user_identifier'),
                   get_remote_address(), 'Attempted evaluation delete without super_admin role', False)
        return jsonify({"status": "error", "message": "Only super admins can delete evaluations"}), 403

    data = request.json
    email = data.get('email', '').strip().lower()
    evaluation_index = data.get('index')
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    if evaluation_index is None:
        return jsonify({"status": "error", "message": "Evaluation index required"}), 400
    
    # Look up client by email
    from config.hierarchy import get_client_by_email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered"}), 404
    
    client_id = client_info['client']
    
    # Get current client data
    client_data = get_client_data(client_id)
    if not client_data:
        return jsonify({"status": "error", "message": "Client data not found"}), 404
    
    evaluations = client_data.get('evaluations', [])
    
    if evaluation_index < 0 or evaluation_index >= len(evaluations):
        return jsonify({"status": "error", "message": "Invalid evaluation index"}), 400
    
    # Get details of what we're deleting for the log
    deleted_eval = evaluations[evaluation_index]
    deleted_info = f"Row {evaluation_index + 1}: {deleted_eval.get('Prop Firm', 'Unknown')} - {deleted_eval.get('Account Size', 'Unknown')}"
    
    # Remove the evaluation
    evaluations.pop(evaluation_index)
    evaluations = recalculate_hedge_nets(evaluations)
    client_data['evaluations'] = evaluations
    
    # Recalculate statistics with existing MT5 + historical accounts
    from utils.data_processor import calculate_statistics
    existing_mt5 = client_data.get('account') or None
    existing_hr_del = client_data.get('statistics', {}).get('hedging_review', {})
    existing_hist = existing_hr_del.get('historical_accounts')
    new_stats = calculate_statistics(evaluations, None, existing_mt5 if existing_mt5 else None,
                                     historical_accounts=existing_hist)
    # ALWAYS preserve hedging_review MT5-derived fields
    new_hr = new_stats.setdefault('hedging_review', {})
    new_hr['total_deposits'] = existing_hr_del.get('total_deposits', 0)
    new_hr['total_withdrawals'] = existing_hr_del.get('total_withdrawals', 0)
    new_hr['current_balance'] = existing_hr_del.get('current_balance', 0)
    new_hr['actual_hedging_results'] = existing_hr_del.get('actual_hedging_results', 0)
    if existing_hist:
        new_hr['historical_accounts'] = existing_hist
        new_hr['historical_deposits'] = existing_hr_del.get('historical_deposits', 0)
        new_hr['historical_withdrawals'] = existing_hr_del.get('historical_withdrawals', 0)
        new_hr['historical_balance'] = existing_hr_del.get('historical_balance', 0)
    new_hr['discrepancy'] = round(new_hr['actual_hedging_results'] - new_hr.get('sheet_hedging_results', 0), 2)
    # Recalculate net_profit with discrepancy (match frontend formula)
    disc = new_hr['discrepancy']
    for sk in ["profitability_completed", "cashflow_inprogress"]:
        sec = new_stats[sk]
        sec["net_profit"] = round(sec["payouts"] + sec["hedging_results"] + sec["farming_results"] + disc - sec["challenge_fees"], 2)
    client_data['statistics'] = new_stats
    
    # Save with history tracking - the previous version contains the deleted row
    success, version = save_client_data_with_history(
        client_id,
        client_data,
        action='DELETE_EVALUATION',
        changed_by=email,
        changed_by_type='client',
        ip_address=get_remote_address(),
        change_source='dashboard_delete',
        change_description=f"Deleted evaluation: {deleted_info}"
    )
    
    log_action('DELETE_EVALUATION', 'client', email, get_remote_address(), 
               f"Deleted {deleted_info} from {client_id} (v{version})")
    
    return jsonify({
        "status": "success",
        "message": f"Evaluation deleted. Use Version History to recover if needed.",
        "version": version,
        "deleted": deleted_info
    })

@app.route('/api/move_client', methods=['POST'])
def api_move_client():
    data = request.json
    if move_client(data['client_name'], data['old_admin'], data['old_trader'], data['new_admin'], data['new_trader']):
        log_action('MOVE_CLIENT', 'admin', data['client_name'], get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Move failed"}), 400

@app.route('/api/move_trader', methods=['POST'])
def api_move_trader():
    data = request.json
    if move_trader(data['trader_name'], data['old_admin'], data['new_admin']):
        log_action('MOVE_TRADER', 'admin', data['trader_name'], get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Move failed"}), 400

@app.route('/super_admin/clients')
@require_session
def client_management():
    if request.session_user.get('user_type') not in ('super_admin', 'bef_admin'):
        return redirect('/')
    return render_template('client_management.html')

# ============ Data API with Role-Based Access Control ============

def can_access_client(user_type, user_identifier, target_client):
    """Check if user has permission to access a client's data."""
    if user_type == 'super_admin':
        return True

    if user_type == 'kwok_admin':
        return True
    
    if user_type == 'bef_admin':
        # BEF admin can only access clients with category == 'BEF'
        for admin_data in hierarchy.get('admins', {}).values():
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    if (client.get('name') == target_client or client.get('email') == target_client):
                        return (client.get('category') or '').upper() == 'BEF'
        return False
    
    if user_type == 'client':
        # Client can always access own data
        if user_identifier == target_client:
            return True
        # Only primary KYC clients can access linked accounts' data
        if is_kyc_primary(user_identifier):
            kyc_group = get_all_kyc_accounts(user_identifier)
            return target_client in kyc_group
        return False
    
    # For admins and traders, check hierarchy
    for admin_name, admin_data in hierarchy.get('admins', {}).items():
        for trader_name, trader_data in admin_data.get('traders', {}).items():
            for client in trader_data.get('clients', []):
                client_name = client.get('name', '')
                client_email = client.get('email', '')
                
                if client_name == target_client or client_email == target_client:
                    if user_type == 'admin' and user_identifier == admin_name:
                        return True
                    if user_type == 'trader' and user_identifier == trader_name:
                        return True
    
    return False

def get_accessible_clients(user_type, user_identifier):
    """Get list of client names this user can access."""
    clients = []
    
    if user_type == 'super_admin':
        # Super admin can access all clients
        for admin_data in hierarchy.get('admins', {}).values():
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    clients.append(client.get('name'))
        return clients

    if user_type == 'kwok_admin':
        return get_accessible_clients('super_admin', user_identifier)
    
    if user_type == 'bef_admin':
        # BEF admin can access only BEF-category clients
        for admin_data in hierarchy.get('admins', {}).values():
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    if (client.get('category') or '').upper() == 'BEF':
                        clients.append(client.get('name'))
        return clients
    
    if user_type == 'admin':
        # Admin can access all clients under their traders
        admin_data = hierarchy.get('admins', {}).get(user_identifier, {})
        for trader_data in admin_data.get('traders', {}).values():
            for client in trader_data.get('clients', []):
                clients.append(client.get('name'))
        return clients
    
    if user_type == 'trader':
        # Trader can access only their clients
        for admin_data in hierarchy.get('admins', {}).values():
            trader_data = admin_data.get('traders', {}).get(user_identifier, {})
            for client in trader_data.get('clients', []):
                clients.append(client.get('name'))
        return clients
    
    if user_type == 'client':
        # Client can only access themselves
        return [user_identifier]
    
    return []

@app.route('/api/hedging_review/<client_id>', methods=['POST'])
@require_session
def update_hedging_review(client_id):
    """Update hedging review values manually - only for traders, admins, and super_admins."""
    session_user = request.session_user
    user_type = session_user.get('user_type')
    user_identifier = session_user.get('user_identifier')
    
    # Allow all authenticated users to edit their own hedging review
    # Traders/admins/super_admins can edit any client they have access to
    
    # Check if user can access this client
    if not can_access_client(user_type, user_identifier, client_id):
        log_action('HEDGING_EDIT_DENIED', user_type, user_identifier, get_remote_address(), 
                   f"No access to client: {client_id}", False)
        return jsonify({"status": "error", "message": "Access denied to this client"}), 403
    
    data = request.json
    
    # Get existing client data
    client_data = get_client_data(client_id)
    if not client_data:
        return jsonify({"status": "error", "message": "Client data not found"}), 404
    
    # Update hedging review in statistics
    if 'statistics' not in client_data:
        client_data['statistics'] = {}
    if 'hedging_review' not in client_data['statistics']:
        client_data['statistics']['hedging_review'] = {}
    
    hr = client_data['statistics']['hedging_review']
    hr['total_deposits'] = float(data.get('total_deposits', hr.get('total_deposits', 0)))
    hr['total_withdrawals'] = float(data.get('total_withdrawals', hr.get('total_withdrawals', 0)))
    hr['current_balance'] = float(data.get('current_balance', hr.get('current_balance', 0)))

    # Auto-negate withdrawals if entered as positive
    if hr['total_withdrawals'] > 0:
        hr['total_withdrawals'] = -hr['total_withdrawals']

    # Recalculate: actual = balance - (deposits + withdrawals), withdrawals are negative
    net_deposits = hr['total_deposits'] + hr['total_withdrawals']
    hr['actual_hedging_results'] = round(hr['current_balance'] - net_deposits, 2)
    sheet_hr = hr.get('sheet_hedging_results', 0)
    hr['discrepancy'] = round(hr['actual_hedging_results'] - sheet_hr, 2)
    
    # Also store in account for consistency with MT5 push
    if 'account' not in client_data:
        client_data['account'] = {}
    client_data['account']['balance'] = hr['current_balance']
    client_data['account']['total_deposits'] = hr['total_deposits']
    client_data['account']['total_withdrawals'] = hr['total_withdrawals']
    
    # Save updated data
    save_client_data(client_id, client_data)
    
    log_action('HEDGING_EDIT', user_type, user_identifier, get_remote_address(), 
               f"Updated hedging review for {client_id}: deposits={hr['total_deposits']}, withdrawals={hr['total_withdrawals']}, balance={hr['current_balance']}")
    
    return jsonify({
        "status": "success", 
        "message": "Hedging review updated",
        "hedging_review": hr
    })

@app.route('/api/client/push_hedging_review', methods=['POST'])
@limiter.limit("30 per minute")
def api_push_hedging_review():
    """
    Public endpoint - push Live Hedging Review data using client email.
    Updates deposits, withdrawals, balance and recalculates actual hedging results.
    Used by the Trader Companion app.
    """
    data = request.json
    email = data.get('email', '').strip().lower()

    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400

    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered in the system"}), 404

    client_id = client_info['client']
    client_data = get_client_data(client_id)
    if not client_data:
        return jsonify({"status": "error", "message": "Client data not found"}), 404

    if 'statistics' not in client_data:
        client_data['statistics'] = {}
    if 'hedging_review' not in client_data['statistics']:
        client_data['statistics']['hedging_review'] = {}

    hr = client_data['statistics']['hedging_review']
    hr['total_deposits'] = float(data.get('total_deposits', hr.get('total_deposits', 0)))
    hr['total_withdrawals'] = float(data.get('total_withdrawals', hr.get('total_withdrawals', 0)))
    hr['current_balance'] = float(data.get('current_balance', hr.get('current_balance', 0)))

    # Auto-negate withdrawals if entered as positive
    if hr['total_withdrawals'] > 0:
        hr['total_withdrawals'] = -hr['total_withdrawals']

    # Recalculate actual hedging results: balance - (deposits + withdrawals)
    # Withdrawals are negative, so deposits + withdrawals = net deposits
    net_deposits = hr['total_deposits'] + hr['total_withdrawals']
    hr['actual_hedging_results'] = round(hr['current_balance'] - net_deposits, 2)

    # Recalculate discrepancy
    sheet_hr = hr.get('sheet_hedging_results', 0)
    hr['discrepancy'] = round(hr['actual_hedging_results'] - sheet_hr, 2)

    # Also store in account for consistency
    if 'account' not in client_data:
        client_data['account'] = {}
    client_data['account']['balance'] = hr['current_balance']
    client_data['account']['total_deposits'] = hr['total_deposits']
    client_data['account']['total_withdrawals'] = hr['total_withdrawals']

    save_client_data(client_id, client_data)

    app.logger.info(f"✅ SAVED Hedging Review for {client_id}:")
    app.logger.info(f"   - total_deposits: ${hr['total_deposits']:.2f}")
    app.logger.info(f"   - total_withdrawals: ${hr['total_withdrawals']:.2f}")
    app.logger.info(f"   - current_balance: ${hr['current_balance']:.2f}")
    app.logger.info(f"   - actual_hedging_results: ${hr['actual_hedging_results']:.2f}")
    app.logger.info(f"   - sheet_hedging_results: ${hr.get('sheet_hedging_results', 0):.2f}")
    app.logger.info(f"   - discrepancy: ${hr['discrepancy']:.2f}")

    log_action('PUSH_HEDGING_REVIEW', 'companion', email, get_remote_address(),
               f"Hedging review for {client_id}: deposits={hr['total_deposits']}, withdrawals={hr['total_withdrawals']}, balance={hr['current_balance']}, actual={hr['actual_hedging_results']}")

    return jsonify({
        "status": "success",
        "message": f"Hedging review updated for {client_id}",
        "hedging_review": hr
    })

@app.route('/api/client/check_mt5_auto_populate/<client_id>', methods=['GET'])
@require_session
def check_mt5_auto_populate(client_id):
    """
    On dashboard load, check if MT5 values need auto-population.
    Returns status and suggestion for initialization.
    """
    session_user = request.session_user
    user_type = session_user.get('user_type')
    user_identifier = session_user.get('user_identifier')
    
    # Only allow client to check their own data or authorized users
    if user_type == 'client' and client_id != user_identifier:
        return jsonify({"status": "error", "message": "Access denied"}), 403
    
    # Check if user can access this client
    if user_type in ['trader', 'admin', 'bef_admin', 'super_admin', 'kwok_admin']:
        if not can_access_client(user_type, user_identifier, client_id):
            return jsonify({"status": "error", "message": "Access denied"}), 403
    
    client_data = get_client_data(client_id)
    if not client_data:
        return jsonify({
            "status": "needs_init",
            "message": "Client data not initialized",
            "needs_mt5": True
        })
    
    # Check if hedging_review MT5 values are empty/zero
    hr = client_data.get('statistics', {}).get('hedging_review', {})
    account = client_data.get('account', {})
    hedge_accounts = client_data.get('hedge_accounts') or []
    prop_accounts = client_data.get('prop_accounts') or []
    
    deposits = float(hr.get('total_deposits', 0))
    withdrawals = float(hr.get('total_withdrawals', 0))
    balance = float(hr.get('current_balance', 0))
    equity = float(account.get('equity', 0))
    
    # Check if values are truly empty (all zero or missing)
    has_mt5_values = (deposits != 0) or (withdrawals != 0) or (balance != 0) or (equity != 0)

    # Setup credentials:
    # - The legacy banner logic was: if hedge creds missing, check prop creds;
    #   if prop creds exist, do NOT prompt; otherwise prompt to set up MT5.
    has_hedge_creds = any(
        isinstance(h, dict)
        and (str(h.get('login', '') or '').strip() or str(h.get('password', '') or '').strip())
        for h in hedge_accounts
    )
    has_prop_creds = any(_prop_account_has_credentials(p) for p in prop_accounts if isinstance(p, dict))
    
    # Need MT5 setup only when MT5 values are missing AND there are no usable
    # hedge creds AND no usable prop creds. If prop creds exist, bypass prompt.
    needs_mt5 = (not has_mt5_values) and (not has_hedge_creds) and (not has_prop_creds)

    if needs_mt5:
        if not has_mt5_values:
            app.logger.info(f"⚠️  MT5 auto-populate: {client_id} has zero MT5 values")
        app.logger.info(
            f"⚠️  MT5 auto-populate: {client_id} missing hedge + prop account credentials (setup required)"
        )
        return jsonify({
            "status": "needs_init",
            "message": "MT5 values need initialization",
            "needs_mt5": True,
            "current_values": {
                "deposits": deposits,
                "withdrawals": withdrawals,
                "balance": balance
            },
            "needs_hedge_creds": (not has_hedge_creds),
            "needs_prop_creds": (not has_prop_creds),
        })
    else:
        app.logger.info(f"✅ MT5 auto-populate: {client_id} already has MT5 values")
        return jsonify({
            "status": "ok",
            "message": "MT5 values already initialized",
            "needs_mt5": False,
            "current_values": {
                "deposits": deposits,
                "withdrawals": withdrawals,
                "balance": balance,
                "equity": equity
            }
        })

@app.route('/api/historical_mt5/<client_id>', methods=['POST'])
@require_session
def manage_historical_mt5(client_id):
    """Manage historical MT5 accounts - add/delete. Only for traders, admins, and super_admins."""
    session_user = request.session_user
    user_type = session_user.get('user_type')
    user_identifier = session_user.get('user_identifier')
    
    # Only allow traders, admins, and super_admins to edit
    if user_type not in ['trader', 'admin', 'super_admin']:
        log_action('HISTORICAL_MT5_DENIED', user_type, user_identifier, get_remote_address(), 
                   f"Client tried to edit historical MT5 for: {client_id}", False)
        return jsonify({"status": "error", "message": "Only traders, admins, and super admins can manage historical MT5 accounts"}), 403
    
    # Check if user can access this client
    if not can_access_client(user_type, user_identifier, client_id):
        log_action('HISTORICAL_MT5_DENIED', user_type, user_identifier, get_remote_address(), 
                   f"No access to client: {client_id}", False)
        return jsonify({"status": "error", "message": "Access denied to this client"}), 403
    
    data = request.json
    action = data.get('action')  # 'add' or 'delete'
    
    # Get existing client data
    client_data = get_client_data(client_id)
    if not client_data:
        return jsonify({"status": "error", "message": "Client data not found"}), 404
    
    # Save snapshot BEFORE making changes (for recovery)
    from dashboard.database import save_data_snapshot
    save_data_snapshot(
        client_id, client_data,
        action='BEFORE_HISTORICAL_MT5_' + action.upper(),
        changed_by=user_identifier,
        changed_by_type=user_type,
        ip_address=get_remote_address(),
        change_source='historical_mt5_management',
        change_description=f"Snapshot before {action} historical MT5 account"
    )
    
    # Ensure hedging_review structure exists
    if 'statistics' not in client_data:
        client_data['statistics'] = {}
    if 'hedging_review' not in client_data['statistics']:
        client_data['statistics']['hedging_review'] = {}
    
    hr = client_data['statistics']['hedging_review']
    
    # Initialize historical_accounts array if not exists
    if 'historical_accounts' not in hr:
        hr['historical_accounts'] = []
    
    if action == 'add':
        account = data.get('account', {})
        hr['historical_accounts'].append({
            'name': account.get('name', 'MT5 Account'),
            'deposits': float(account.get('deposits', 0)),
            'withdrawals': float(account.get('withdrawals', 0)),
            'final_balance': float(account.get('final_balance', 0)),
            'date_added': account.get('date_added', '')
        })
        
        log_action('HISTORICAL_MT5_ADD', user_type, user_identifier, get_remote_address(), 
                   f"Added historical MT5 for {client_id}: {account.get('name')}")
        
    elif action == 'delete':
        index = data.get('index')
        if index is not None and 0 <= index < len(hr['historical_accounts']):
            deleted = hr['historical_accounts'].pop(index)
            log_action('HISTORICAL_MT5_DELETE', user_type, user_identifier, get_remote_address(), 
                       f"Deleted historical MT5 for {client_id}: {deleted.get('name')}")
        else:
            return jsonify({"status": "error", "message": "Invalid index"}), 400
    
    elif action == 'set_prior_activity':
        target = data.get('target')  # 'current' or integer index for historical
        prior_profit = float(data.get('prior_activity_profit', 0))
        if target == 'current':
            hr['current_mt5_prior_activity'] = prior_profit
            log_action('PRIOR_ACTIVITY_SET', user_type, user_identifier, get_remote_address(),
                       f"Set current MT5 prior activity for {client_id}: {prior_profit}")
        elif isinstance(target, int) and 0 <= target < len(hr['historical_accounts']):
            hr['historical_accounts'][target]['prior_activity_profit'] = prior_profit
            log_action('PRIOR_ACTIVITY_SET', user_type, user_identifier, get_remote_address(),
                       f"Set historical MT5 #{target} prior activity for {client_id}: {prior_profit}")
        else:
            return jsonify({"status": "error", "message": "Invalid target"}), 400
    
    else:
        return jsonify({"status": "error", "message": "Invalid action"}), 400
    
    # Recalculate totals including historical accounts
    hist_deposits = sum(acc.get('deposits', 0) for acc in hr['historical_accounts'])
    hist_withdrawals = sum(acc.get('withdrawals', 0) for acc in hr['historical_accounts'])
    hist_balance = sum(acc.get('final_balance', 0) for acc in hr['historical_accounts'])
    
    # Store historical totals for data_processor to use
    hr['historical_deposits'] = hist_deposits
    hr['historical_withdrawals'] = hist_withdrawals
    hr['historical_balance'] = hist_balance
    
    # Save updated data WITH history tracking
    email = client_data.get('identity', {}).get('email', '')
    success, version = save_client_data_with_history(
        client_id, client_data,
        action='HISTORICAL_MT5_' + action.upper(),
        changed_by=user_identifier,
        changed_by_type=user_type,
        ip_address=get_remote_address(),
        change_source='historical_mt5_management',
        change_description=f"{action.capitalize()} historical MT5 account"
    )
    
    return jsonify({
        "status": "success", 
        "message": f"Historical MT5 {action}ed successfully",
        "historical_accounts": hr['historical_accounts'],
        "historical_totals": {
            "deposits": hist_deposits,
            "withdrawals": hist_withdrawals,
            "balance": hist_balance
        }
    })

@app.route('/api/data')
@limiter.limit("180 per minute")  # 10,800/hour: allows ~30s polling on 120+ concurrent clients
def get_data():
    """Get client data - requires authentication and role-based access."""
    client_id = request.args.get('client_id')
    
    # Check authentication
    session_token = request.cookies.get('session_token')
    if not session_token:
        # Also check API Key for trader apps
        api_key = request.headers.get('X-API-Key')
        if not api_key:
             return jsonify({"status": "error", "message": "Authentication required"}), 401
        
        # Validate API Key
        key_info = validate_api_key(api_key)
        if not key_info:
             return jsonify({"status": "error", "message": "Invalid API Key"}), 401
        
        user_type = 'api'
        user_identifier = key_info.get('owner') 
    else:
        session_info = validate_session(session_token)
        if not session_info:
            return jsonify({"status": "error", "message": "Invalid session"}), 401
    
        user_type = session_info.get('user_type')
        user_identifier = session_info.get('user_identifier')
    
    if client_id:
        # Check if user can access this client's data
        if not can_access_client(user_type, user_identifier, client_id):
            log_action('ACCESS_DENIED', user_type, user_identifier, get_remote_address(), f"Tried to access: {client_id}", False)
            return jsonify({"status": "error", "message": "Access denied"}), 403
        
        data = get_client_data(client_id)
        if data is None:
            return jsonify({"status": "error", "message": f"No data found for client '{client_id}'. The client may not exist or has no saved data yet."}), 404

        if data:
            # Inject Visual Notes
            if 'evaluations' in data:
                try:
                    notes = get_client_notes(client_id)
                    # notes is { row_index: { col: text } }
                    for i, ev in enumerate(data['evaluations']):
                        if i in notes:
                            ev['_notes'] = notes[i]
                except Exception as e:
                    logging.error(f"Error injecting notes: {e}")

            # Historical MT5 values are shown separately in the MT5 Accounts Overview table.
            # The hedging_review values (deposits, withdrawals, balance, discrepancy) are
            # served as-is from data_processor.py — single source of truth.
            
            data['status'] = 'success'
            # Include current version so frontend can detect stale refreshes
            try:
                from dashboard.database import get_next_version
                data['_version'] = get_next_version(client_id) - 1
            except Exception:
                pass
            # Include last activity info for dashboard display
            try:
                from dashboard.database import get_client_activity
                data['_activity'] = get_client_activity(client_id)
            except Exception:
                pass
            return jsonify(data)
    
    # If no client specified, return empty
    return jsonify({
        "status": "success",
        "deals": [], "positions": [], "account": {}, 
        "evaluations": [], "statistics": {}, "dropdown_options": {}, 
        "last_updated": "Never"
    })


@app.route('/api/dashboard/recalculate_statistics', methods=['POST'])
@limiter.limit("30 per minute")
def api_dashboard_recalculate_statistics():
    """
    Recalculate Hedge Net / Hedge Net.1 and statistics from stored evaluations and persist.
    Used after a full dashboard page load so DB matches formulas (separate from trader /api/client/push).
    Uses save_client_data (no extra history snapshot) like super_admin batch recalc.
    """
    session_token = request.cookies.get('session_token')
    if not session_token:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    session_info = validate_session(session_token)
    if not session_info:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    user_type = session_info.get('user_type')
    user_identifier = session_info.get('user_identifier')
    payload = request.get_json() or {}
    client_id = payload.get('client_id')
    if not client_id:
        return jsonify({"status": "error", "message": "client_id required"}), 400
    if not can_access_client(user_type, user_identifier, client_id):
        return jsonify({"status": "error", "message": "Access denied"}), 403

    try:
        from utils.data_processor import calculate_statistics
        max_attempts = 6
        for attempt in range(max_attempts):
            client_data = get_client_data(client_id)
            if not client_data:
                return jsonify({"status": "error", "message": "No data found"}), 404

            ts_marker = client_data.get('last_updated')
            evals = recalculate_hedge_nets(list(client_data.get('evaluations') or []))
            existing_mt5 = client_data.get('account')
            existing_hr = client_data.get('statistics', {}).get('hedging_review', {}) or {}
            existing_hist = existing_hr.get('historical_accounts')

            new_stats = calculate_statistics(
                evals, mt5_account=existing_mt5, historical_accounts=existing_hist
            )
            merge_statistics_hedging_review_preserve_mt5(existing_hr, new_stats)

            verify = get_client_data(client_id)
            if verify.get('last_updated') != ts_marker:
                app.logger.warning(
                    "[HEDGE_RECALC] client=%s attempt=%s stale_read mid_calc last_updated shifted, retrying",
                    client_id,
                    attempt + 1,
                )
                continue

            pre_save = get_client_data(client_id)
            if pre_save.get('last_updated') != ts_marker:
                app.logger.warning(
                    "[HEDGE_RECALC] client=%s attempt=%s stale_read pre_save, retrying",
                    client_id,
                    attempt + 1,
                )
                continue

            save_client_data(client_id, {'statistics': new_stats})
            mh = new_stats.get('hedging_review', {})
            app.logger.info(
                "[HEDGE_RECALC] client=%s ok sheet_hedge=%s discrepancy=%s cf_net=%s attempt=%s",
                client_id,
                mh.get('sheet_hedging_results'),
                mh.get('discrepancy'),
                new_stats.get('cashflow_inprogress', {}).get('net_profit'),
                attempt + 1,
            )
            try:
                from dashboard.financial_overview import clear_financial_cache
                clear_financial_cache()
            except Exception:
                pass
            return jsonify({"status": "success"})

        app.logger.error(
            "[HEDGE_RECALC] client=%s failed after %s attempts (concurrent saves)",
            client_id,
            max_attempts,
        )
        return jsonify({
            "status": "error",
            "message": "Data changed during recalculation; refresh the page.",
        }), 409
    except Exception as e:
        app.logger.exception("recalculate_statistics on dashboard load failed")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/client/export_csv')
def export_client_csv():
    """Export client evaluation data as CSV download."""
    import csv
    import io

    client_id = request.args.get('client_id')
    if not client_id:
        return jsonify({"status": "error", "message": "client_id required"}), 400

    # Auth check
    session_token = request.cookies.get('session_token')
    api_key = request.headers.get('X-API-Key')
    if session_token:
        session_info = validate_session(session_token)
        if not session_info:
            return jsonify({"status": "error", "message": "Invalid session"}), 401
        user_type = session_info.get('user_type')
        user_identifier = session_info.get('user_identifier')
    elif api_key:
        key_info = validate_api_key(api_key)
        if not key_info:
            return jsonify({"status": "error", "message": "Invalid API key"}), 401
        user_type = 'api'
        user_identifier = key_info.get('owner')
    else:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    if not can_access_client(user_type, user_identifier, client_id):
        return jsonify({"status": "error", "message": "Access denied"}), 403

    data = get_client_data(client_id)
    if not data:
        return jsonify({"status": "error", "message": "No data found"}), 404

    evaluations = data.get('evaluations', [])
    if not evaluations:
        return jsonify({"status": "error", "message": "No evaluation data"}), 404

    # Dashboard column order — matches the HTML template
    DASHBOARD_COLUMN_ORDER = [
        'Prop Firm', 'Account Size', 'Date Purchased', 'Fee',
        'Date Started', 'Date Ended', 'Status P1', 'Account #',
        'Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
        'Hedge Result 4', 'Hedge Result 5', 'Hedge Net',
        'Account #.1', 'Activation Fee', 'Date Started.1', 'Date Ended.1', 'Status',
        'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
        'Hedge Result 4.1', 'Hedge Result 5.1',
        'Hedge Result 6', 'Hedge Result 7', 'Hedge Net.1',
        'Payout 1', 'Date 1', 'Payout 2', 'Date 2',
        'Payout 3', 'Date 3', 'Payout 4', 'Date 4',
    ] + [f'Prop Day {i}' for i in range(1, 35)] \
      + [f'Prop Progress {i}' for i in range(1, 35)] \
      + [f'Hedge Day {i}' for i in range(1, 35)]

    # Build column list: dashboard order first, then extras (skip Account Number)
    all_keys = set()
    for ev in evaluations:
        all_keys.update(k for k in ev if not k.startswith('_') and k != 'Account Number')
    seen = set()
    columns = []
    for col in DASHBOARD_COLUMN_ORDER:
        if col in all_keys and col not in seen:
            seen.add(col)
            columns.append(col)
    for ev in evaluations:
        for key in ev:
            if key not in seen and not key.startswith('_') and key != 'Account Number':
                seen.add(key)
                columns.append(key)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for ev in evaluations:
        writer.writerow([ev.get(col, '') for col in columns])

    # Add statistics summary rows
    stats = data.get('statistics', {})
    if stats:
        writer.writerow([])  # blank separator
        writer.writerow(['--- Statistics ---'])
        for key, val in stats.items():
            if isinstance(val, dict):
                for k2, v2 in val.items():
                    writer.writerow([f'{key}.{k2}', v2])
            else:
                writer.writerow([key, val])

    csv_content = output.getvalue()
    output.close()

    from flask import Response
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', client_id)
    resp = Response(csv_content, mimetype='text/csv')
    resp.headers['Content-Disposition'] = f'attachment; filename={safe_name}_evaluations.csv'
    log_action('CSV_EXPORT', user_type, user_identifier, get_remote_address(), f"Exported CSV for {client_id}")
    return resp

# ============ Quality Scan System ============

def _parse_date_str(val):
    """Try to parse a date string from evaluation data. Returns YYYY-MM-DD or None."""
    if not val:
        return None
    val = str(val).strip().rstrip('.')
    if not val or len(val) < 3:
        return None
    # Skip obvious non-dates
    if val[0].isalpha() and '/' not in val and '-' not in val:
        return None

    # Normalize: replace dots with slashes, collapse double slashes
    normalized = val.replace('.', '/').replace('//', '/')
    # Strip leading non-digit chars (e.g. "V10/17/25")
    while normalized and not normalized[0].isdigit():
        normalized = normalized[1:]
    if not normalized:
        return None

    # Try standard formats
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%m-%d-%Y', '%m-%d-%y',
                '%b %d, %Y', '%B %d, %Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(normalized, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue

    # Handle M/D (no year) — infer year
    parts = normalized.split('/')
    if len(parts) == 2:
        try:
            month = int(parts[0])
            day = int(parts[1])
            if 1 <= month <= 12 and 1 <= day <= 31:
                now = datetime.now()
                candidate = datetime(now.year, month, day)
                # If the date is in the future, assume previous year
                if candidate > now:
                    candidate = datetime(now.year - 1, month, day)
                return candidate.strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            pass

    return None


def _get_row_dates(ev):
    """Extract all parseable dates from an evaluation row."""
    fields = ['Date Purchased', 'Date Started', 'Date Ended',
              'Date Started.1', 'Date Ended.1',
              'Date 1', 'Date 2', 'Date 3', 'Date 4']
    dates = []
    for f in fields:
        d = _parse_date_str(ev.get(f, ''))
        if d:
            dates.append(d)
    # Also check farming progress columns (Prop Day N, Hedge Day N)
    for key, val in ev.items():
        k = str(key)
        if ('Prop Day' in k or 'Hedge Day' in k) and not k.startswith('_'):
            d = _parse_date_str(val)
            if d:
                dates.append(d)
    return sorted(set(dates))


def _estimate_issue_date(ev, issue_check, fallback):
    """Estimate when an issue occurred based on row dates and issue type."""
    dates = _get_row_dates(ev)
    if not dates:
        return fallback
    dp = _parse_date_str(ev.get('Date Purchased', ''))
    ds = _parse_date_str(ev.get('Date Started', ''))
    # Setup/entry issues → earliest date (purchase/start)
    if issue_check in (
        'Status blank', 'Empty Fee', 'Empty Account Size', 'Missing Date Started', 'Missing Date Purchased',
        'Phase 1: missing Date Started',
    ):
        return dp or ds or dates[0]
    # End-of-life issues → latest known date
    if issue_check in ('Missing Date Ended', 'Phase 1: missing Date Ended'):
        return ds or dates[-1]
    # Active account issues → start date
    if issue_check == 'Empty Account #':
        return ds or dp or dates[0]
    # Funded issues → latest date
    if issue_check == 'Empty Activation Fee':
        return dates[-1]
    if issue_check == 'Funded phase: missing Date Ended':
        ds1 = _parse_date_str(ev.get('Date Started.1', ''))
        return ds1 or (dates[-1] if dates else fallback)
    if issue_check == 'Funded phase: missing Date Started':
        de1 = _parse_date_str(ev.get('Date Ended.1', ''))
        return de1 or (dates[-1] if dates else fallback)
    # Current/ongoing issues → latest date
    if issue_check in ('No current day value', 'Downtime detected', 'Negative Hedge Net, no note', 'Negative Hedge Net-QA'):
        return dates[-1]
    if issue_check == QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE:
        return fallback
    return dates[-1]


# ── Weekday markers in Hedge Result / Hedge Day / Prop Day (quality scan) ──
# Match whole tokens only (avoids "mon" inside "money"). Longer spellings first in the alternation.
_WEEKDAY_TOKEN_TO_ABBR = {
    'monday': 'mon', 'mon': 'mon',
    'tuesday': 'tue', 'tues': 'tue', 'tue': 'tue',
    'wednesday': 'wed', 'weds': 'wed', 'wed': 'wed',
    'thursday': 'thu', 'thurs': 'thu', 'thu': 'thu',
    'friday': 'fri', 'fri': 'fri',
    'saturday': 'sat', 'sat': 'sat',
    'sunday': 'sun', 'sun': 'sun',
}
_WEEKDAY_RE = re.compile(
    r'\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|'
    r'tues|weds|thurs|mon|tue|wed|thu|fri|sat|sun)\b',
    re.I,
)


def _allowed_trading_day_abbrs(ref_dt):
    """Which single-day markers are valid for *today* (Chicago-style trading week).

    Mon–Thu: today and tomorrow (e.g. Tue → tue, wed).
    Fri: fri and mon (next session Monday).
    Sat–Sun: mon only (prep for Monday; no other weekday markers).
    """
    wd = ref_dt.weekday()
    order = ('mon', 'tue', 'wed', 'thu', 'fri')
    if wd >= 5:
        return frozenset({'mon'})
    if wd == 4:
        return frozenset({'fri', 'mon'})
    return frozenset({order[wd], order[wd + 1]})


def _should_skip_daily_summary_tracking(eat_dt):
    """Skip daily-summary submission tracker when there is no session to track.

    True on Sat/Sun (no trading) and on Mon before the new week is underway —
    e.g. the 02:30 EAT bot run after Sunday (yesterday was non-trading), so the
    Slack message matches the clean weekend post instead of flagging missing sends.
    """
    if eat_dt.weekday() in (5, 6):
        return True
    yesterday = eat_dt - timedelta(days=1)
    return yesterday.weekday() in (5, 6)


DAILY_SUMMARY_TRACKER_SKIP_MSG = (
    "🛑 _No trading session to track (weekend or day after a non-trading day). "
    "Daily summary submission tracking resumes on the next trading day._"
)


def _weekday_abbrs_in_text(raw):
    """Return {'mon','tue',...} for weekday tokens in *raw* (empty if none)."""
    s = str(raw or '').strip().lower()
    if not s or s in ('-', '—', '–'):
        return frozenset()
    out = set()
    for m in _WEEKDAY_RE.finditer(s):
        tok = m.group(0).lower()
        ab = _WEEKDAY_TOKEN_TO_ABBR.get(tok)
        if ab:
            out.add(ab)
    return frozenset(out)


def _hedge_cell_currency_only(raw):
    """True when the cell is numeric P&L style (digits) with no weekday letters."""
    s = str(raw or '').strip()
    if not s or s in ('-', '—', '–'):
        return False
    low = s.lower()
    if _WEEKDAY_RE.search(low):
        return False
    probe = low.replace('$', '').replace('€', '').replace('£', '').strip()
    if not probe:
        return False
    return bool(re.search(r'\d', probe))


def _row_all_day_slots_blank_or_currency(ev, day_cols):
    """Every day-tracked cell is empty/dash or currency-only (no weekday text)."""
    for col in day_cols:
        s = str(ev.get(col) or '').strip()
        if not s or s in ('-', '—', '–'):
            continue
        if _hedge_cell_currency_only(ev.get(col)):
            continue
        return False
    return True


def _row_has_nonzero_currency_in_day_cols(ev, day_cols, parse_nonzero_fn):
    """At least one day column parses as non-zero money (PnL-only row heuristic)."""
    for col in day_cols:
        if _hedge_cell_currency_only(ev.get(col)) and abs(parse_nonzero_fn(ev.get(col))) > 1e-9:
            return True
    return False


def _prop_account_has_credentials(pa) -> bool:
    """True if a prop_accounts row has portal login/password or Tradovate user/pass (Prop Firm tab)."""
    if not isinstance(pa, dict):
        return False
    for key in ('login', 'password', 'tradovate_username', 'tradovate_password'):
        if str(pa.get(key, '') or '').strip():
            return True
    return False


def _eval_row_needs_hedge_or_prop_tabs(ev):
    """True when this row is past bare sheet onboarding (Hedge/Prop *tabs* should exist)."""
    if not isinstance(ev, dict) or ev.get('_deleted'):
        return False
    prop_firm = str(ev.get('Prop Firm', '') or '').strip()
    acct_size = str(ev.get('Account Size', '') or '').strip()
    if not (prop_firm or acct_size):
        return False
    if prop_firm.lower() in ('funding ticks', 'fundingticks'):
        return False
    status_p1 = str(ev.get('Status P1', '') or '').strip().lower()
    status_p2 = str(ev.get('Status', '') or ev.get('Status Funded', '') or '').strip().lower()
    if 'delete' in status_p1 or 'delete' in status_p2:
        return False
    _inactive_p1 = ('fail', 'breach', 'delete', 'closed', 'sl')
    _inactive_p2 = ('fail', 'breach', 'delete', 'closed', 'sl', 'complete', 'completed')
    if any(t in status_p1 for t in _inactive_p1) or any(t in status_p2 for t in _inactive_p2):
        return False
    if _max_out_row_is_live_numeric_account(ev):
        return True
    if str(ev.get('Account #', '') or '').strip() or str(ev.get('Account #.1', '') or '').strip():
        return True

    def _pnz(v):
        try:
            s = str(v).replace('$', '').replace(',', '').strip()
            if s in ('', '-', None):
                return 0.0
            return float(s)
        except (ValueError, TypeError):
            return 0.0

    for k, v in ev.items():
        if isinstance(k, str) and k.startswith('Hedge Result') and not k.startswith('_'):
            if abs(_pnz(v)) > 1e-9:
                return True
    if status_p1 and 'not started' not in status_p1:
        return True
    if status_p2 and 'not started' not in status_p2:
        return True
    return False


def _daily_summary_payout_eligible_triggers_from_items(items):
    """Daily summary item 4 (payout_requests) in Notes mode: each prop firm with count >= 1."""
    triggers = []
    if not isinstance(items, list):
        return triggers
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get('id') != 'payout_requests':
            continue
        if it.get('status') != 'warn':
            continue
        notes = it.get('notes')
        if not isinstance(notes, dict):
            continue
        for firm_name, nv in notes.items():
            if not isinstance(firm_name, str) or not firm_name.strip():
                continue
            if not isinstance(nv, dict):
                continue
            fields = nv.get('fields')
            if not isinstance(fields, dict):
                continue
            raw = fields.get('count', '')
            s = str(raw).strip().replace(',', '').replace('$', '')
            if not s:
                continue
            m = re.match(r'^[-+]?\d*\.?\d+', s)
            if not m:
                continue
            try:
                n = float(m.group(0))
            except (ValueError, TypeError):
                continue
            if n >= 1.0:
                triggers.append({'firm': firm_name.strip(), 'count': n})
    return triggers


def _daily_summary_payout_qa_resolved_union(client_id: str, row_index: int) -> bool:
    from dashboard.database import is_qa_resolved
    return (
        is_qa_resolved(QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE, client_id, row_index)
        or is_qa_resolved(QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE_LEGACY, client_id, row_index)
    )


def _get_daily_summary_payout_qa_resolved_set():
    from dashboard.database import get_qa_resolved_set
    return get_qa_resolved_set(QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE) | get_qa_resolved_set(
        QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE_LEGACY
    )


def run_quality_scan(target_client=None):
    """
    Automated quality scan: checks every client's data for SOP violations.
    Returns list of per-client scan results with issues and health scores.
    If target_client is given, only scan that one client.
    """
    from config.hierarchy import get_all_clients as hierarchy_get_all_clients, get_client_profile
    from dashboard.database import (
        get_client_data,
        get_client_activity,
        get_latest_daily_summary_checklist_for_client,
    )

    all_clients = [target_client] if target_client else hierarchy_get_all_clients()
    results = []
    # The server runs UTC, but the ops workflow (and Slack bot schedule) is keyed to Kenyan time.
    # Use Kenyan "now" for day-marker / downtime logic so missing trading days are flagged
    # as soon as we cross midnight EAT, not midnight UTC.
    now = datetime.now()
    today_weekday = now.weekday()  # 0=Mon, 6=Sun (UTC)
    scan_date_str = now.strftime('%Y-%m-%d')  # persisted scan date remains UTC
    try:
        from datetime import timezone as _tz, timedelta as _td
        now_eat = datetime.now(_tz.utc).astimezone(_tz(_td(hours=3)))
    except Exception:
        now_eat = now

    for client_name in all_clients:
        profile = get_client_profile(client_name)
        trader = profile.get('trader', '') if profile else ''
        admin = profile.get('admin', '') if profile else ''
        try:
            data = get_client_data(client_name)

            issues = []

            if not data:
                issues.append({'check': 'No data', 'severity': 'critical', 'detail': 'No saved client data',
                               'estimated_date': scan_date_str})
                results.append({
                    'client_id': client_name, 'trader': trader, 'admin': admin,
                    'total_issues': len(issues), 'issues': issues, 'health_score': 0.0
                })
                continue

            # Skip inactive clients — their stats are still calculated but no quality checks
            identity = data.get('identity', {})
            if isinstance(identity, dict) and identity.get('active_status') == 'inactive':
                results.append({
                    'client_id': client_name, 'trader': trader, 'admin': admin,
                    'total_issues': 0, 'issues': [], 'health_score': 100.0,
                    'skipped': True, 'skip_reason': 'inactive'
                })
                continue

            evaluations = data.get('evaluations', [])

            # Inject cell notes so checks like "Negative Hedge Net, no note" can see them
            try:
                notes = get_client_notes(client_name)
                for i, ev in enumerate(evaluations):
                    if i in notes:
                        ev['_notes'] = notes[i]
            except Exception:
                pass

            if not evaluations:
                issues.append({'check': 'No evaluations', 'severity': 'warning', 'detail': 'No evaluation rows found',
                               'estimated_date': scan_date_str})

            # Activity tracking
            activity = get_client_activity(client_name) or {}
            last_push = activity.get('last_push_at')
            if last_push:
                try:
                    push_dt = datetime.fromisoformat(last_push)
                    hours_since_push = (now - push_dt).total_seconds() / 3600
                    # Flag if >24h since last push on a weekday (Mon-Fri)
                    if hours_since_push > 24 and today_weekday < 5:
                        issues.append({'check': 'No recent MT5 push', 'severity': 'high',
                                       'detail': f'Last push {hours_since_push:.0f}h ago',
                                       'estimated_date': push_dt.strftime('%Y-%m-%d')})
                except (ValueError, TypeError):
                    pass

            # MT5 Profit vs Hedging Results (as displayed in the Stats UI)
            #
            # IMPORTANT: this check must compare the same numbers users see on the dashboard:
            # - MT5 table "Profit" uses current+historical MT5 combined, minus prior activity.
            # - Stats "Hedging Results" uses (hedging_results + farming_results + discrepancy).
            try:
                stats = data.get('statistics', {}) if isinstance(data, dict) else {}
                hr = stats.get('hedging_review', {}) if isinstance(stats, dict) else {}
                cf = stats.get('cashflow_inprogress', {}) if isinstance(stats, dict) else {}
                acct = data.get('account', {}) if isinstance(data, dict) else {}
                if isinstance(hr, dict) and isinstance(cf, dict) and isinstance(acct, dict):
                    def _to_float(v):
                        try:
                            if v is None:
                                return 0.0
                            s = str(v).replace('$', '').replace(',', '').strip()
                            if s == '':
                                return 0.0
                            return float(s)
                        except (ValueError, TypeError):
                            return 0.0

                    # Compute the SAME MT5 Profit value shown in the MT5 Accounts Overview table.
                    # UI source of truth for "Current MT5" is data.account.*
                    mt5_dep = _to_float(acct.get('total_deposits', hr.get('total_deposits')))
                    mt5_wd = _to_float(acct.get('total_withdrawals', hr.get('total_withdrawals')))
                    mt5_bal = _to_float(acct.get('balance', hr.get('current_balance')))
                    hist = hr.get('historical_accounts') or []
                    hist_dep = hist_wd = hist_bal = 0.0
                    prior_activity = _to_float(hr.get('current_mt5_prior_activity'))
                    if isinstance(hist, list):
                        for a in hist:
                            if not isinstance(a, dict):
                                continue
                            hist_dep += _to_float(a.get('deposits'))
                            hist_wd += _to_float(a.get('withdrawals'))
                            hist_bal += _to_float(a.get('final_balance'))
                            prior_activity += _to_float(a.get('prior_activity_profit'))
                    combined_dep = mt5_dep + hist_dep
                    combined_wd = mt5_wd + hist_wd
                    combined_bal = mt5_bal + hist_bal
                    mt5_profit_combined = round(combined_bal - (combined_dep + combined_wd) - prior_activity, 2)

                    # Also compute Current MT5-only profit (yellow row in UI), excluding historical accounts.
                    # This avoids false positives when historical MT5 totals are present but the current MT5
                    # profit matches the sheet hedging results shown in Stats.
                    current_prior = _to_float(hr.get('current_mt5_prior_activity'))
                    mt5_profit_current = round(mt5_bal - (mt5_dep + mt5_wd) - current_prior, 2)

                    # Compute the SAME Hedging Results number shown in the Stats panel.
                    hedge_total_display = round(
                        _to_float(cf.get('hedging_results')) + _to_float(cf.get('farming_results')) + _to_float(hr.get('discrepancy')),
                        2
                    )

                    # Only evaluate this check when there's meaningful MT5 context or a recent push.
                    has_mt5_context = bool(last_push) or (abs(mt5_dep) > 1e-9) or (abs(mt5_wd) > 1e-9) or (abs(mt5_bal) > 1e-9) or (abs(hist_dep) > 1e-9) or (abs(hist_wd) > 1e-9) or (abs(hist_bal) > 1e-9)
                    if has_mt5_context:
                        # Prefer current-only profit if it matches within tolerance, otherwise fall back to combined.
                        chosen_profit = mt5_profit_combined
                        if (abs(hist_dep) > 1e-9) or (abs(hist_wd) > 1e-9) or (abs(hist_bal) > 1e-9):
                            if abs(mt5_profit_current - hedge_total_display) < 1.0:
                                chosen_profit = mt5_profit_current

                        diff = round(chosen_profit - hedge_total_display, 2)
                        # Tolerance to avoid noise from rounding / tiny differences.
                        if abs(diff) >= 1.0:
                            issues.append({
                                'check': 'Hedging Results mismatch',
                                'severity': 'high',
                                'detail': f"Sheet hedge total differs from MT5 profit (HR={hedge_total_display:.2f}, MT5={chosen_profit:.2f})",
                                'estimated_date': scan_date_str
                            })
            except Exception:
                pass

            # Check each evaluation row
            total_checks = 0
            for idx, ev in enumerate(evaluations):
                row_label = f'Row {idx + 1}'
                # Skip internal/deleted rows
                if ev.get('_deleted'):
                    continue

                status_p1 = str(ev.get('Status P1', '') or '').strip().lower()
                status_p2 = str(ev.get('Status', '') or ev.get('Status Funded', '') or '').strip().lower()

                # Skip rows marked as deleted via status text — superadmin review rows, not real issues
                if 'delete' in status_p1 or 'delete' in status_p2:
                    continue
                # Match the dashboard's "Active Only" filter semantics:
                # treat rows as inactive if either phase status indicates a terminal/closed state.
                _inactive_tokens_p1 = ('fail', 'breach', 'closed', 'sl')
                _inactive_tokens_p2 = ('fail', 'breach', 'closed', 'sl', 'complete', 'completed')
                is_active = (not any(t in status_p1 for t in _inactive_tokens_p1)) and (not any(t in status_p2 for t in _inactive_tokens_p2))

                prop_firm = str(ev.get('Prop Firm', '') or '').strip()
                acct_size = str(ev.get('Account Size', '') or '').strip()
                has_data = bool(prop_firm or acct_size)
                total_checks += 1

                if not has_data:
                    continue

                # Skip defunct prop firms — no point flagging issues on closed firms
                if prop_firm.lower() in ('funding ticks', 'fundingticks'):
                    continue

                # Quality scan gating for newly added rows:
                # - If a new row has no hedge values yet, we suppress "early" flags
                #   (ex: empty account number / missing weekday) so it isn't flagged
                #   while the user is still populating fees + initial status.
                # - We still flag missing `Fee` and any Status P1 value that is not
                #   exactly "not started".
                # - If a hedge value exists, we allow the normal flagging flow.
                # Only treat "new row" gating/flags as relevant for active rows.
                # Inactive rows (failed/closed/completed) should never be flagged as "new".
                is_new_row = bool(ev.get('_row_added_at')) and is_active
                fee_raw = str(ev.get('Fee', '') or '').strip()
                acct_num_local = str(ev.get('Account #', '') or '').strip()
                acct_num2_local = str(ev.get('Account #.1', '') or '').strip()
                has_account_num_local = bool(acct_num_local or acct_num2_local)

                def _parse_nonzero(v):
                    try:
                        s = str(v).replace('$', '').replace(',', '').strip()
                        if s in ('', '-', None):
                            return 0.0
                        return float(s)
                    except (ValueError, TypeError):
                        return 0.0

                _hedge_result_cols = [
                    k for k in ev.keys()
                    if isinstance(k, str) and k.startswith('Hedge Result') and not k.startswith('_')
                ]
                # Funded-phase hedge result columns use a ".1" suffix in the sheet export
                # (e.g. "Hedge Result 1.1"). Keep these separate so we can reason about
                # "Funded = not started" without being confused by eval-phase hedge values.
                _funded_hedge_result_cols = [k for k in _hedge_result_cols if k.endswith('.1')]

                fee_num = _parse_nonzero(ev.get('Fee', ''))
                fee_present = fee_num > 0.0

                has_hedge_value_local = any(
                    abs(_parse_nonzero(ev.get(c))) > 1e-9 for c in _hedge_result_cols
                )
                has_funded_hedge_value_local = any(
                    abs(_parse_nonzero(ev.get(c))) > 1e-9 for c in _funded_hedge_result_cols
                )

                # Live funded broker rows (digits-only Account #.1 / funded id): traders are not in eval workflow;
                # skip sheet SOP flags except weekday-of-day tracking (and any client/global issues like downtime).
                is_live_funded_numeric_row = _max_out_row_is_live_numeric_account(ev)

                new_row_strict_mode = is_new_row and not has_hedge_value_local and not is_live_funded_numeric_row

                # If the row is explicitly "not started" but hedge values already exist, flag.
                #
                # Important nuance:
                # - If Funded status is "not started", only flag when *funded-phase* hedge
                #   cells contain numeric values. If funded never began, those cells remain
                #   blank or text-only and should not be flagged.
                is_not_started_p1 = ('not started' in status_p1)
                is_not_started_p2 = ('not started' in status_p2)

                def _suppress_not_started_hedge_mismatch():
                    for c in _hedge_result_cols:
                        raw = str(ev.get(c) or '').strip()
                        if raw and 'see note' in raw.lower():
                            return True
                    _cn = ev.get('_notes') or {}
                    if isinstance(_cn, dict) and any(str(v or '').strip() for v in _cn.values()):
                        return True
                    if str(ev.get('Notes', '') or '').strip():
                        return True
                    return False

                if (
                    not is_live_funded_numeric_row
                    and (
                        (is_not_started_p1 and has_hedge_value_local)
                        or (is_not_started_p2 and has_funded_hedge_value_local)
                    )
                    and not _suppress_not_started_hedge_mismatch()
                ):
                    issues.append({
                        'check': 'Not Started but hedge values present',
                        'severity': 'high',
                        'row': idx,
                        'detail': f'{row_label}: Status not started but hedge values exist',
                        'estimated_date': _estimate_issue_date(ev, 'Not Started but hedge values present', scan_date_str),
                    })

                # Detect "double dip" — MFF/TopStep accounts with an activation fee
                # These are reset at funded stage so eval-phase fields are intentionally blank
                _dd_firms = ('my funded futures', 'mff', 'topstep', 'top step', 'topstepx')
                activation_fee = str(ev.get('Activation Fee', '') or '').strip()
                is_double_dip = (
                    prop_firm.lower() in _dd_firms
                    and bool(activation_fee)
                )

                def _norm_marker_text(v: str) -> str:
                    v = (v or '').strip().lower()
                    v = v.replace('\u00a0', ' ')
                    v = re.sub(r'[^a-z0-9]+', ' ', v)
                    return re.sub(r'\s+', ' ', v).strip()

                _marker_sources = (
                    ev.get('Account #', ''),
                    ev.get('Account #.1', ''),
                    ev.get('Notes', ''),
                    ev.get('Note', ''),
                    ev.get('Status', ''),
                    ev.get('Status Funded', ''),
                )
                _marker_text = _norm_marker_text(' '.join(str(s or '') for s in _marker_sources))
                is_back_to_funded_marker = ('back to funded' in _marker_text)
                # Eval Fee may be blank when returning to funded (activation fee only).
                is_empty_fee_exempt = is_double_dip or (
                    is_back_to_funded_marker and bool(activation_fee)
                )

                # Status blank on non-empty row
                if not is_live_funded_numeric_row and not status_p1 and has_data and not is_double_dip:
                    issues.append({'check': 'Status blank', 'severity': 'medium', 'row': idx,
                                   'detail': f'{row_label}: Has data but no Status P1',
                                   'estimated_date': _estimate_issue_date(ev, 'Status blank', scan_date_str)})

                # Empty Fee
                fee_raw = str(ev.get('Fee', '') or '').strip()
                fee_num = _parse_nonzero(ev.get('Fee', ''))
                # Treat "0", "0.00", etc. as missing fee — challenge fees must be > 0.00
                _notes = ev.get('_notes') or {}
                _fee_note = ''
                if isinstance(_notes, dict):
                    for _k, _v in _notes.items():
                        if str(_k or '').strip().lower() == 'fee' and str(_v or '').strip():
                            _fee_note = str(_v).strip()
                            break
                # If the Fee cell has a note, treat it as an explicit override/explanation
                # and do not flag "Empty Fee" even when Fee is 0.00.
                if (
                    not is_live_funded_numeric_row
                    and (not fee_raw or fee_num <= 0.0)
                    and has_data
                    and not is_empty_fee_exempt
                    and not _fee_note
                ):
                    issues.append({'check': 'Empty Fee', 'severity': 'low', 'row': idx,
                                   'detail': f'{row_label}: Fee not filled in',
                                   'estimated_date': _estimate_issue_date(ev, 'Empty Fee', scan_date_str)})

                # New-row strict rule:
                # If it's a brand new row and there's NO hedge value yet, we only
                # allow the scan to flag:
                #   1) missing/zero Fee (handled above),
                #   2) missing Date Purchased, or
                #   3) Status P1 not being exactly "not started".
                # Everything else (empty account #, missing weekday, etc.) is suppressed
                # until hedge values arrive.
                if new_row_strict_mode and not is_live_funded_numeric_row:
                    dp_raw = str(ev.get('Date Purchased', '') or '').strip()
                    if not dp_raw:
                        issues.append({
                            'check': 'Missing Date Purchased',
                            'severity': 'medium',
                            'row': idx,
                            'detail': f'{row_label}: New row missing Date Purchased',
                            'estimated_date': _estimate_issue_date(ev, 'Missing Date Purchased', scan_date_str),
                        })
                    # Special case: some clients do not hedge.
                    # They may put a weekday into Hedge Result 1 to indicate the prop account should be traded,
                    # while Status P1 is "hit tp1/2/3". Treat this as valid and suppress the "not started" flag.
                    _hr1 = str(ev.get('Hedge Result 1', '') or '').strip().lower()
                    _weekday_tokens = ('mon', 'monday', 'tue', 'tues', 'tuesday', 'wed', 'weds', 'wednesday',
                                       'thu', 'thurs', 'thursday', 'fri', 'friday')
                    _has_weekday_marker = any(tok in _hr1 for tok in _weekday_tokens)
                    _is_hit_tp = status_p1.startswith('hit tp') or status_p1.replace(' ', '').startswith('hittp')
                    _nonhedge_ok = _is_hit_tp and _has_weekday_marker

                    # Additional special case:
                    # Some rows are marked "pass" (or other non-"not started") even though no numeric hedge values exist yet,
                    # but a weekday marker is placed in funded/farming hedge columns as a workflow cue.
                    # If any funded hedge result or farming hedge day cell contains a weekday token, suppress the flag.
                    _weekday_ok = False
                    try:
                        _funded_cols = (
                            'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
                            'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7',
                        )
                        _farming_cols = tuple(f'Hedge Day {i}' for i in range(1, 51))
                        for _c in (_funded_cols + _farming_cols):
                            _v = str(ev.get(_c, '') or '').strip().lower()
                            if _v and any(tok in _v for tok in _weekday_tokens):
                                _weekday_ok = True
                                break
                    except Exception:
                        _weekday_ok = False

                    # Farming-phase weekday in Prop Day cells, eval + funded both "pass", hedges still empty:
                    # treat as intentional workflow state — do not flag "not started".
                    _pass_propday_weekday_ok = False
                    if status_p1 == 'pass' and status_p2 == 'pass' and not has_hedge_value_local:
                        try:
                            for _i in range(1, 51):
                                _c = f'Prop Day {_i}'
                                _v = str(ev.get(_c, '') or '').strip().lower()
                                if _v and any(tok in _v for tok in _weekday_tokens):
                                    _pass_propday_weekday_ok = True
                                    break
                        except Exception:
                            _pass_propday_weekday_ok = False

                    if (
                        fee_present
                        and status_p1
                        and status_p1 != 'not started'
                        and not _nonhedge_ok
                        and not _weekday_ok
                        and not _pass_propday_weekday_ok
                    ):
                        issues.append({
                            'check': 'New row: Status P1 not started',
                            'severity': 'medium',
                            'row': idx,
                            'detail': f'{row_label}: Fee present; Status P1 should be not started',
                            'estimated_date': _estimate_issue_date(ev, 'New row: Status P1 not started', scan_date_str),
                        })

                # Empty Account Size
                if not is_live_funded_numeric_row and not new_row_strict_mode and not acct_size and prop_firm and not is_double_dip:
                    issues.append({'check': 'Empty Account Size', 'severity': 'low', 'row': idx,
                                   'detail': f'{row_label}: Account Size blank',
                                   'estimated_date': _estimate_issue_date(ev, 'Empty Account Size', scan_date_str)})

                # Empty Account #
                acct_num = str(ev.get('Account #', '') or '').strip()
                acct_num2 = str(ev.get('Account #.1', '') or '').strip()
                if not is_live_funded_numeric_row and not new_row_strict_mode and is_active and not acct_num and not acct_num2:
                    # Treat as "new/uninitialized" and suppress the flag when:
                    # - Status is "not started", and
                    # - there are no numeric hedge results yet (blank or text markers like weekdays).
                    if status_p1 == 'not started' and not has_hedge_value_local:
                        pass
                    # For double dips, only the funded-phase account # matters
                    elif not is_double_dip or not acct_num2:
                        issues.append({'check': 'Empty Account #', 'severity': 'medium', 'row': idx,
                                       'detail': f'{row_label}: Active but no account number',
                                       'estimated_date': _estimate_issue_date(ev, 'Empty Account #', scan_date_str)})

                # Empty Activation Fee on funded rows
                activation = str(ev.get('Activation Fee', '') or '').strip()
                if not is_live_funded_numeric_row and not new_row_strict_mode and status_p2 in ('funded', 'live', 'payout') and not activation:
                    issues.append({'check': 'Empty Activation Fee', 'severity': 'medium', 'row': idx,
                                   'detail': f'{row_label}: Funded but no activation fee',
                                   'estimated_date': _estimate_issue_date(ev, 'Empty Activation Fee', scan_date_str)})

                # Phase 1 terminal outcome (Pass / Fail): require both start and end dates.
                # Strict: Date Purchased does NOT count as start (purchase date can differ from first trade date).
                p1_started = str(ev.get('Date Started', '') or '').strip()
                p1_ended = str(ev.get('Date Ended', '') or '').strip()
                # Back-to-funded rows (see is_back_to_funded_marker above): skip eval date requirements.
                if (
                    not is_live_funded_numeric_row
                    and not new_row_strict_mode
                    and status_p1 in ('pass', 'fail')
                    and not p1_started
                    and not is_back_to_funded_marker
                ):
                    issues.append({
                        'check': 'Phase 1: missing Date Started',
                        'severity': 'medium',
                        'row': idx,
                        'detail': f'{row_label}: Status P1 \"{status_p1}\" missing Date Started',
                        'estimated_date': _estimate_issue_date(ev, 'Phase 1: missing Date Started', scan_date_str),
                    })
                if (
                    not is_live_funded_numeric_row
                    and not new_row_strict_mode
                    and status_p1 in ('pass', 'fail')
                    and not p1_ended
                    and not is_back_to_funded_marker
                ):
                    issues.append({
                        'check': 'Phase 1: missing Date Ended',
                        'severity': 'medium',
                        'row': idx,
                        'detail': f'{row_label}: Status P1 \"{status_p1}\" missing Date Ended',
                        'estimated_date': _estimate_issue_date(ev, 'Phase 1: missing Date Ended', scan_date_str),
                    })

                # Funded-phase terminal outcome (Pass / Fail): funded "Date Ended" column must be set (Date Ended.1).
                status_funded_raw = str(ev.get('Status', '') or ev.get('Status Funded', '') or '').strip()
                _sf_lower = status_funded_raw.lower()
                _sf_first = ''
                if _sf_lower:
                    _sf_first = re.split(r'[\s\-–—:;]+', _sf_lower, maxsplit=1)[0].strip().rstrip('.,')
                funded_started = str(ev.get('Date Started.1', '') or '').strip()
                funded_ended = str(ev.get('Date Ended.1', '') or '').strip()
                if (
                    not is_live_funded_numeric_row
                    and not new_row_strict_mode
                    and _sf_first in ('pass', 'fail')
                    and not funded_started
                ):
                    issues.append({
                        'check': 'Funded phase: missing Date Started',
                        'severity': 'medium',
                        'row': idx,
                        'detail': f'{row_label}: Funded status \"{status_funded_raw}\" missing funded Date Started',
                        'estimated_date': _estimate_issue_date(ev, 'Funded phase: missing Date Started', scan_date_str),
                    })
                if (
                    not is_live_funded_numeric_row
                    and not new_row_strict_mode
                    and _sf_first in ('pass', 'fail')
                    and not funded_ended
                ):
                    issues.append({
                        'check': 'Funded phase: missing Date Ended',
                        'severity': 'medium',
                        'row': idx,
                        'detail': f'{row_label}: Funded status \"{status_funded_raw}\" missing funded Date Ended',
                        'estimated_date': _estimate_issue_date(ev, 'Funded phase: missing Date Ended', scan_date_str),
                    })

                # Alpha Futures always charges an activation fee when an account
                # actually starts trading the funded account — so only flag a
                # missing Activation Fee when the row has BOTH reached funded
                # stage AND logged at least one non-zero hedge result in the
                # funded phase. Accounts that got a funded account # but never
                # traded (or were abandoned before any HR) are excluded so we
                # don't drown the dashboard in false positives.
                if (
                    not is_live_funded_numeric_row
                    and (not new_row_strict_mode)
                    and prop_firm.lower().replace(' ', '') in ('alphafutures',)
                    and not activation
                ):
                    _funded_hr_cols = (
                        'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
                        'Hedge Result 4.1', 'Hedge Result 5.1',
                        'Hedge Result 6', 'Hedge Result 7',
                    )
                    _has_funded_hr = any(
                        re.search(r'[1-9]', str(ev.get(_c, '') or ''))
                        for _c in _funded_hr_cols
                    )
                    _funded_marker = bool(
                        status_p1 == 'pass'
                        or acct_num2
                        or str(ev.get('Date Started.1', '') or '').strip()
                        or str(ev.get('Date Ended.1', '') or '').strip()
                        or status_p2
                    )
                    if _funded_marker and _has_funded_hr:
                        issues.append({'check': 'Alpha Futures: missing Activation Fee', 'severity': 'high', 'row': idx,
                                       'detail': f'{row_label}: Alpha Futures funded account missing Activation Fee',
                                       'estimated_date': _estimate_issue_date(ev, 'Alpha Futures: missing Activation Fee', scan_date_str)})

                # Same idea as new_row_strict_mode for weekday: if challenge is paid, P1 is still
                # "not started", no account #s yet, and no hedge numbers, do not require a day marker
                # even when _row_added_at is missing (older rows / imports).
                _suppress_no_current_day_eval_onboarding = (
                    is_active
                    and not is_live_funded_numeric_row
                    and not has_hedge_value_local
                    and not has_funded_hedge_value_local
                    and is_not_started_p1
                    and not has_account_num_local
                    and fee_present
                )

                # Active account: Hedge Result / Hedge Day / Prop Day markers must match the
                # trading calendar (Mon–Thu: today + next weekday; Fri: fri + mon; Sat–Sun: mon only).
                # Any other weekday token → Downtime detected. Whole-token match avoids "mon" in "money".
                # Rows that only hold P&L numbers in those columns (no weekday letters) skip the
                # "must show current day" rule when at least one such cell is non-zero currency.
                _inactive_p1 = any(k in status_p1 for k in ('fail', 'breach', 'delete', 'closed', 'sl'))
                _inactive_p2 = any(k in status_p2 for k in ('fail', 'breach', 'delete', 'closed', 'sl', 'complete'))
                _day_columns = [
                    k for k in ev.keys()
                    if isinstance(k, str)
                    and (k.startswith('Hedge Result') or k.startswith('Hedge Day') or k.startswith('Prop Day'))
                    and not k.startswith('_')
                ]
                if (not new_row_strict_mode or has_account_num_local) and not _inactive_p1 and not _inactive_p2 and status_p1:
                    # Downtime/current-day markers should follow Kenyan day boundaries (midnight EAT).
                    _allowed_abbrs = _allowed_trading_day_abbrs(now_eat)
                    _allowed_human = '/'.join(sorted(_allowed_abbrs))
                    _cell_notes = ev.get('_notes') or {}
                    if not isinstance(_cell_notes, dict):
                        _cell_notes = {}
                    # Live funded (digits-only) rows must show an allowed weekday unless Status P1 has a cell note
                    # explaining why not; other cell notes do not waive the day requirement for live rows.
                    _is_live_day_row = is_live_funded_numeric_row
                    _live_status_p1_note = bool(
                        _is_live_day_row and str(_cell_notes.get('Status P1') or '').strip()
                    )
                    stale_detail_parts = []
                    has_allowed_markers = bool(_live_status_p1_note)
                    for col in _day_columns:
                        if not _is_live_day_row:
                            note_val = _cell_notes.get(col)
                            if note_val and str(note_val).strip():
                                has_allowed_markers = True
                                continue
                        raw_cell = ev.get(col)
                        if _hedge_cell_currency_only(raw_cell):
                            continue
                        ab = _weekday_abbrs_in_text(raw_cell)
                        if not ab:
                            continue
                        disallowed = ab - _allowed_abbrs
                        if disallowed:
                            bad = ', '.join(sorted(disallowed))
                            stale_detail_parts.append(f'{col}={str(raw_cell).strip()!r} ({bad})')
                        if ab <= _allowed_abbrs:
                            has_allowed_markers = True
                    if stale_detail_parts:
                        prevw = ', '.join(stale_detail_parts[:5])
                        if len(stale_detail_parts) > 5:
                            prevw += f' (+{len(stale_detail_parts) - 5} more)'
                        issues.append({
                            'check': 'Downtime detected',
                            'severity': 'high',
                            'row': idx,
                            'detail': f'{row_label}: Stale day marker found; allowed: {_allowed_human}',
                            'estimated_date': _estimate_issue_date(ev, 'Downtime detected', scan_date_str),
                        })
                    elif (
                        not has_allowed_markers
                        and not (
                            (not _is_live_day_row)
                            and _row_all_day_slots_blank_or_currency(ev, _day_columns)
                            and _row_has_nonzero_currency_in_day_cols(ev, _day_columns, _parse_nonzero)
                        )
                        and not _suppress_no_current_day_eval_onboarding
                    ):
                        if _is_live_day_row:
                            _nd_msg = f'{row_label}: Missing allowed day marker ({_allowed_human}); add marker or Status P1 note'
                        else:
                            _nd_msg = f'{row_label}: Missing allowed day marker ({_allowed_human}); add marker or cell note'
                        issues.append({
                            'check': 'No current day value',
                            'severity': 'medium',
                            'row': idx,
                            'detail': _nd_msg,
                            'estimated_date': _estimate_issue_date(ev, 'No current day value', scan_date_str),
                        })

                # Negative Hedge Net without note
                def _parse_num(v):
                    try: return float(str(v).replace('$', '').replace(',', '').strip())
                    except (ValueError, TypeError): return None

                hedge_net = _parse_num(ev.get('Hedge Net', ''))
                if (
                    not is_live_funded_numeric_row
                    and not new_row_strict_mode
                    and hedge_net is not None
                    and hedge_net < 0
                ):
                    dp_str = _parse_date_str(ev.get('Date Purchased', '') or '')
                    is_post_cutoff = bool(dp_str and dp_str >= '2026-04-29')
                    if is_post_cutoff:
                        # QA-gated negative hedge net: notes do NOT clear this. Only super_admin can resolve.
                        try:
                            from dashboard.database import is_qa_resolved
                            if not is_qa_resolved('Negative Hedge Net-QA', client_name, idx):
                                issues.append({
                                    'check': 'Negative Hedge Net-QA',
                                    'severity': 'high',
                                    'row': idx,
                                    'detail': f'{row_label}: Hedge Net=${hedge_net:.2f}; needs QA resolution',
                                    'estimated_date': _estimate_issue_date(ev, 'Negative Hedge Net-QA', scan_date_str)
                                })
                        except Exception:
                            issues.append({
                                'check': 'Negative Hedge Net-QA',
                                'severity': 'high',
                                'row': idx,
                                'detail': f'{row_label}: Hedge Net=${hedge_net:.2f}; needs QA resolution',
                                'estimated_date': _estimate_issue_date(ev, 'Negative Hedge Net-QA', scan_date_str)
                            })
                    else:
                        # Legacy behavior (pre-cutoff): notes clear the issue.
                        cell_notes = ev.get('_notes', {}) or {}
                        has_any_note = isinstance(cell_notes, dict) and any(v for v in cell_notes.values() if v and str(v).strip())
                        notes_col = str(ev.get('Notes', '') or '').strip()
                        has_note = has_any_note or bool(notes_col)
                        if not has_note:
                            issues.append({'check': 'Negative Hedge Net, no note', 'severity': 'high', 'row': idx,
                                           'detail': f'{row_label}: Hedge Net=${hedge_net:.2f} with no explanation',
                                           'estimated_date': _estimate_issue_date(ev, 'Negative Hedge Net, no note', scan_date_str)})

                # Comma used as a decimal separator in Hedge Result / Hedge Day cells.
                # We only care about European-style "1000,67" or "1,000,00" where
                # a comma stands in for the decimal point — those silently break
                # currency parsing (",67" gets stripped as a thousands separator
                # and the .67 is lost).  Normal US thousand separators like
                # "1,000.67" are LEGIT and must not be flagged, so a cell that
                # contains a '.' is always accepted.
                _comma_cols = []
                for _col in ev.keys():
                    if not isinstance(_col, str):
                        continue
                    if not (_col.startswith('Hedge Result') or _col.startswith('Hedge Day')):
                        continue
                    _val = str(ev.get(_col) or '').strip()
                    if not _val or ',' not in _val:
                        continue
                    _probe = _val.replace('$', '').strip()
                    if '.' in _probe:
                        # '.' present → commas are thousand separators (US style). Legit.
                        continue
                    # Flag only when the cell ends with exactly ",NN" (two digits) —
                    # i.e. the comma is acting as the decimal point.
                    if re.search(r',\d{2}\s*$', _probe):
                        _comma_cols.append(f'{_col}="{_val}"')
                if _comma_cols:
                    _preview = '; '.join(_comma_cols[:3])
                    _suffix = '' if len(_comma_cols) <= 3 else f' (+{len(_comma_cols) - 3} more)'
                    if not new_row_strict_mode and not is_live_funded_numeric_row:
                        issues.append({'check': 'Comma in hedge value', 'severity': 'low', 'row': idx,
                                       'detail': f'{row_label}: Comma decimal in hedge value; use dot decimals',
                                       'estimated_date': _estimate_issue_date(ev, 'Comma in hedge value', scan_date_str)})

            # Trader daily summary item 4 (any prop firm): payouts eligible at next trading day count >= 1 — QA-gated
            try:
                _cl_row = get_latest_daily_summary_checklist_for_client(scan_date_str, client_name)
                if _cl_row:
                    _payout_triggers = _daily_summary_payout_eligible_triggers_from_items(_cl_row.get('items'))
                    if _payout_triggers:
                        _qa_day_key = int(scan_date_str.replace('-', ''))
                        if not _daily_summary_payout_qa_resolved_union(client_name, _qa_day_key):
                            _sub_at = str(_cl_row.get('submitted_at') or '').strip()
                            _by = str(_cl_row.get('user_identifier') or '').strip()
                            _lines = [
                                'Daily summary · Item 4 — Payout requests (Notes)',
                                '',
                                'Eligible count at next trading day (QA flags each firm at >= 1):',
                            ]
                            for t in _payout_triggers[:12]:
                                _lines.append(f"  • {t['firm']}: {t['count']:g}")
                            if len(_payout_triggers) > 12:
                                _lines.append(f"  • … +{len(_payout_triggers) - 12} more firm(s)")
                            _lines.extend([
                                '',
                                f"Checklist submitted: {_sub_at or 'unknown time'}",
                            ])
                            if _by:
                                _lines.append(f"Trader / user: {_by}")
                            _lines.extend([
                                '',
                                'Super-admin QA resolution required.',
                            ])
                            issues.append({
                                'check': QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE,
                                'severity': 'high',
                                'detail': '\n'.join(_lines),
                                'estimated_date': scan_date_str,
                                'row': _qa_day_key,
                                'submitted_at': _sub_at,
                            })
            except Exception:
                pass

            # ── Hedge account or Prop Firm account: at least one must be filled ──
            # If the client has evaluations with data, they need either hedge account
            # credentials OR prop firm account credentials entered.
            hedge_accounts = data.get('hedge_accounts') or []
            prop_accounts  = data.get('prop_accounts')  or []
            _hedge_filled = any(
                str(hacc.get('login', '') or '').strip() or str(hacc.get('password', '') or '').strip()
                for hacc in hedge_accounts
                if isinstance(hacc, dict)
            )
            _prop_filled = any(_prop_account_has_credentials(pa) for pa in prop_accounts if isinstance(pa, dict))
            if total_checks > 0 and not _hedge_filled and not _prop_filled:
                issues.append({
                    'check': 'Hedge account or Prop Firm missing',
                    'severity': 'high',
                    'tab': 'hedge',
                    'detail': 'Hedge account credentials missing; fill Hedge Accounts tab',
                    'estimated_date': scan_date_str,
                })
                issues.append({
                    'check': 'Hedge account or Prop Firm missing',
                    'severity': 'high',
                    'tab': 'prop',
                    'detail': 'Prop firm credentials missing; fill Prop Firm Accounts tab',
                    'estimated_date': scan_date_str,
                })

            # Calculate health score (100 - deductions)
            severity_weight = {'critical': 20, 'high': 10, 'medium': 5, 'low': 2, 'warning': 3, 'info': 0}
            deduction = sum(severity_weight.get(i.get('severity', 'low'), 2) for i in issues)
            health_score = max(0.0, 100.0 - deduction)

            results.append({
                'client_id': client_name,
                'trader': trader,
                'admin': admin,
                'total_issues': len(issues),
                'issues': issues,
                'health_score': round(health_score, 1)
            })
        except Exception as exc:
            import traceback
            traceback.print_exc()
            results.append({
                'client_id': client_name, 'trader': trader, 'admin': admin,
                'total_issues': 1, 'issues': [{'check': 'Scan error', 'severity': 'critical',
                    'detail': 'Scan failed; check server logs', 'estimated_date': scan_date_str}],
                'health_score': 0.0
            })

    return results


@app.route('/api/quality/discrepancies', methods=['GET'])
@require_role('super_admin')
def api_quality_discrepancies():
    """Return all clients sorted by absolute discrepancy (highest first)."""
    from dashboard.database import get_connection
    with get_connection() as conn:
        cursor = conn.cursor()
        # Quote "identity" — it is a reserved keyword in PostgreSQL 10+
        cursor.execute('SELECT client_id, "identity", account, statistics FROM clients_data')
        rows = cursor.fetchall()

    results = []
    for row in rows:
        cid = row['client_id']
        try:
            raw_id = row['identity']
            identity = (json.loads(raw_id) if isinstance(raw_id, str) else raw_id) or {}
        except Exception:
            identity = {}
        try:
            raw_acct = row['account']
            acct = (json.loads(raw_acct) if isinstance(raw_acct, str) else raw_acct) or {}
        except Exception:
            acct = {}
        try:
            raw_st = row['statistics']
            stats = (json.loads(raw_st) if isinstance(raw_st, str) else raw_st) or {}
        except Exception:
            stats = {}
        hr = stats.get('hedging_review', {}) or {}
        cashflow = stats.get('cashflow_inprogress', {}) or {}

        # Dashboard JS reads MT5 data from data.account (the account column):
        #   const mt5Dep = parseFloat(mt5Acc.total_deposits) || 0;
        #   const mt5With = parseFloat(mt5Acc.total_withdrawals) || 0;
        #   const mt5Bal = parseFloat(mt5Acc.balance) || 0;
        mt5_dep = float(acct.get('total_deposits') or 0)
        mt5_with = float(acct.get('total_withdrawals') or 0)
        mt5_bal = float(acct.get('balance') or 0)

        # Historical accounts from hedging_review
        hist_accts = hr.get('historical_accounts') or []
        hist_dep = sum(float(a.get('deposits') or 0) for a in hist_accts)
        hist_with = sum(float(a.get('withdrawals') or 0) for a in hist_accts)
        hist_bal = sum(float(a.get('final_balance') or 0) for a in hist_accts)

        combined_dep = mt5_dep + hist_dep
        combined_with = mt5_with + hist_with
        combined_bal = mt5_bal + hist_bal

        # Prior activity
        total_prior = float(hr.get('current_mt5_prior_activity') or 0)
        for a in hist_accts:
            total_prior += float(a.get('prior_activity_profit') or 0)

        # Skip clients with no MT5 data (same guard as JS: mt5Dep !== 0 || mt5Bal !== 0)
        if mt5_dep == 0 and mt5_bal == 0:
            continue

        # liveActualHedging = combinedBal - (combinedDep + combinedWith) - totalPriorActivity
        actual = combined_bal - (combined_dep + combined_with) - total_prior

        # sheet = cashflow_inprogress.hedging_results + farming_results
        sheet = float(cashflow.get('hedging_results') or 0) + float(cashflow.get('farming_results') or 0)
        disc = actual - sheet

        name = identity.get('name') or identity.get('display_name') or identity.get('client') or cid
        if disc == 0 and actual == 0 and sheet == 0:
            continue
        try:
            results.append({
                'client_id': cid,
                'name': name,
                'discrepancy': round(float(disc), 2),
                'actual': round(float(actual), 2),
                'sheet': round(float(sheet), 2),
            })
        except (TypeError, ValueError):
            continue

    results.sort(key=lambda r: abs(r['discrepancy']), reverse=True)
    return jsonify({'status': 'success', 'clients': results})


@app.route('/api/quality/deleted_rows', methods=['GET'])
@require_role('super_admin')
def api_quality_deleted_rows():
    """Return all evaluation rows across all clients where Status P1 == 'Deleted'."""
    from config.hierarchy import get_all_clients as _get_all_clients, get_client_profile
    from dashboard.database import get_client_data

    all_clients = _get_all_clients()
    rows = []
    for client_name in all_clients:
        try:
            data = get_client_data(client_name)
            if not data:
                continue
            profile = get_client_profile(client_name)
            trader = profile.get('trader', '') if profile else ''
            evaluations = data.get('evaluations', [])
            for idx, ev in enumerate(evaluations):
                status_p1 = str(ev.get('Status P1', '') or '').strip()
                if status_p1.lower() == 'deleted':
                    rows.append({
                        'client': client_name,
                        'trader': trader,
                        'row': idx,
                        'account': ev.get('Account #') or ev.get('Account #.1') or '',
                        'prop_firm': ev.get('Prop Firm', ''),
                        'date_started': ev.get('Date Started') or ev.get('Date Purchased') or '',
                    })
        except Exception as e:
            logging.warning(f'deleted_rows scan error for {client_name}: {e}')
            continue

    return jsonify({'status': 'success', 'rows': rows, 'total': len(rows)})


@app.route('/api/quality/negative_hedge_net_qa', methods=['GET'])
@require_role('super_admin', 'bef_admin')
def api_quality_negative_hedge_net_qa():
    """List unresolved Negative Hedge Net-QA issues across the portfolio."""
    from dashboard.database import get_quality_scan_results, get_qa_resolved_set
    date = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
    scan = get_quality_scan_results(date) or []
    resolved = get_qa_resolved_set('Negative Hedge Net-QA')

    items = []
    for r in scan:
        cid = r.get('client_id')
        trader = r.get('trader', '')
        admin = r.get('admin', '')
        for iss in (r.get('issues') or []):
            if iss.get('check') != 'Negative Hedge Net-QA':
                continue
            row = iss.get('row')
            if row is None:
                continue
            try:
                row_i = int(row)
            except Exception:
                continue
            if (cid, row_i) in resolved:
                continue
            items.append({
                'client_id': cid,
                'trader': trader,
                'admin': admin,
                'row': row_i,
                'detail': iss.get('detail', ''),
                'estimated_date': iss.get('estimated_date', ''),
                'severity': iss.get('severity', 'high'),
            })

    items.sort(key=lambda x: (str(x.get('estimated_date') or ''), str(x.get('client_id') or '')), reverse=True)
    return jsonify({'status': 'success', 'date': date, 'items': items, 'total': len(items)})


@app.route('/api/quality/daily_summary_payout_qa', methods=['GET'])
@app.route('/api/quality/mff_payout_summary_qa', methods=['GET'])
@require_role('super_admin', 'bef_admin')
def api_quality_daily_summary_payout_qa():
    """List unresolved daily-summary item-4 (payout eligible >=1) QA items across the portfolio."""
    from dashboard.database import get_quality_scan_results
    date = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
    scan = get_quality_scan_results(date) or []
    resolved = _get_daily_summary_payout_qa_resolved_set()

    items = []
    for r in scan:
        cid = r.get('client_id')
        trader = r.get('trader', '')
        admin = r.get('admin', '')
        for iss in (r.get('issues') or []):
            if iss.get('check') != QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE:
                continue
            row = iss.get('row')
            if row is None:
                continue
            try:
                row_i = int(row)
            except Exception:
                continue
            if (cid, row_i) in resolved:
                continue
            items.append({
                'client_id': cid,
                'trader': trader,
                'admin': admin,
                'row': row_i,
                'detail': iss.get('detail', ''),
                'estimated_date': iss.get('estimated_date', ''),
                'submitted_at': iss.get('submitted_at', ''),
                'severity': iss.get('severity', 'high'),
            })

    items.sort(key=lambda x: (str(x.get('estimated_date') or ''), str(x.get('client_id') or '')), reverse=True)
    return jsonify({'status': 'success', 'date': date, 'items': items, 'total': len(items)})


@app.route('/api/quality/qa_resolve', methods=['POST'])
@require_role('super_admin', 'bef_admin')
def api_quality_qa_resolve():
    """Resolve a QA-gated issue. Daily-summary payout-eligible check is super_admin only; other checks allow BEF."""
    from dashboard.database import mark_qa_resolved
    data = request.get_json(force=True) or {}
    check_name = (data.get('check') or '').strip()
    client_id = (data.get('client_id') or '').strip()
    row = data.get('row')
    notes = (data.get('notes') or '').strip()
    if not check_name or not client_id or row is None:
        return jsonify({'status': 'error', 'message': 'check, client_id, row required'}), 400
    try:
        row_i = int(row)
    except Exception:
        return jsonify({'status': 'error', 'message': 'row must be an integer'}), 400
    check_store = (
        QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE
        if check_name == QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE_LEGACY
        else check_name
    )
    if check_store == QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE:
        if request.session_user.get('user_type') != 'super_admin':
            return jsonify({'status': 'error', 'message': 'Only super_admin can resolve this check'}), 403
    user = request.session_user.get('user_identifier', '')
    mark_qa_resolved(check_store, client_id, row_i, user, notes=notes)
    try:
        log_action('QA_RESOLVE', request.session_user.get('user_type'), user, get_remote_address(),
                   f'{check_store} resolved for {client_id} row {row_i}')
    except Exception:
        pass
    return jsonify({'status': 'success'})


@app.route('/api/quality/scan', methods=['POST'])
@require_role('super_admin')
def api_run_quality_scan():
    """Run quality scan on all clients. Super admin only."""
    # Step 1: run the scan (reads client data only)
    try:
        results = run_quality_scan()
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f'Scan failed: {str(e)}'}), 500

    scan_date = datetime.now().strftime('%Y-%m-%d')

    # Step 2: persist results — non-fatal if the DB is in a bad state
    save_warning = None
    try:
        from dashboard.database import save_quality_scan_results
        save_quality_scan_results(scan_date, results)
        _sync_quality_issue_tracking(scan_date, results)
    except Exception as e:
        save_warning = str(e)
        logging.warning(f'Quality scan results could not be saved: {e}')

    # Compute display stats after filtering out infrastructure scan errors
    severity_weight = {'critical': 20, 'high': 10, 'medium': 5, 'low': 2, 'warning': 3, 'info': 0}
    for r in results:
        r['issues'] = [i for i in r.get('issues', []) if i.get('check') != 'Scan error']
        r['total_issues'] = len(r['issues'])
        deduction = sum(severity_weight.get(i.get('severity', 'low'), 2) for i in r['issues'])
        r['health_score'] = max(0.0, round(100.0 - deduction, 1))

    total_issues = sum(r['total_issues'] for r in results)
    clients_with_issues = sum(1 for r in results if r['total_issues'] > 0)
    avg_health = sum(r['health_score'] for r in results) / len(results) if results else 0

    try:
        log_action('QUALITY_SCAN', 'super_admin', request.session_user.get('user_identifier'),
                   get_remote_address(), f'Scanned {len(results)} clients, {total_issues} total issues')
    except Exception:
        pass

    resp = {
        'status': 'success',
        'scan_date': scan_date,
        'total_clients': len(results),
        'clients_with_issues': clients_with_issues,
        'total_issues': total_issues,
        'avg_health_score': round(avg_health, 1),
        'results': results
    }
    if save_warning:
        resp['save_warning'] = f'Results not persisted ({save_warning}). Run DB Repair to fix.'
    return jsonify(resp)





@app.route('/api/quality/client/<client_id>', methods=['GET'])
@require_role('admin', 'trader', 'super_admin')
def api_quality_client(client_id):
    """Get quality issues for a single client. Loads saved results; ?rescan=1 triggers a live re-scan."""
    user_type = request.session_user.get('user_type')
    user_identifier = request.session_user.get('user_identifier')
    if not can_access_client(user_type, user_identifier, client_id):
        return jsonify({"status": "error", "message": "Access denied"}), 403
    empty = {"client_id": client_id, "issues": [], "health_score": 100.0}

    # If rescan=1, run a live scan for this client and update the stored results
    if request.args.get('rescan') == '1':
        try:
            results = run_quality_scan(target_client=client_id)
            if results:
                r = results[0]
                # Persist the updated result into today's scan row for this client
                try:
                    from dashboard.database import get_connection
                    scan_date = datetime.now().strftime('%Y-%m-%d')
                    with get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute('DELETE FROM quality_scan_results WHERE scan_date = ? AND client_id = ?',
                                       (scan_date, client_id))
                        cursor.execute('''INSERT INTO quality_scan_results
                                          (scan_date, client_id, trader, admin, total_issues, issues, health_score)
                                          VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                       (scan_date, r['client_id'], r.get('trader'), r.get('admin'),
                                        r['total_issues'], json.dumps(r['issues']), r['health_score']))
                        conn.commit()
                    _sync_quality_issue_tracking(scan_date, [r])
                except Exception:
                    pass  # Non-fatal — still return live results
                return jsonify({"status": "success", "data": _quality_scan_row_for_trader_client_quality_api(r)})
        except Exception as e:
            return jsonify({"status": "error", "message": f"Scan failed: {str(e)}"}), 500

    # Try loading from saved scan results first (faster, no DB corruption risk)
    try:
        from dashboard.database import get_quality_scan_results
        saved = get_quality_scan_results()  # latest scan
        if saved:
            for r in saved:
                if r.get('client_id') == client_id:
                    return jsonify({
                        "status": "success",
                        "data": _quality_scan_row_for_trader_client_quality_api(r),
                    })
    except Exception:
        pass
    # No saved results — only super admins should trigger a live scan
    if user_type == 'super_admin':
        try:
            results = run_quality_scan(target_client=client_id)
            if results:
                return jsonify({
                    "status": "success",
                    "data": _quality_scan_row_for_trader_client_quality_api(results[0]),
                })
        except Exception as e:
            return jsonify({"status": "error", "message": f"Scan failed: {str(e)}"}), 500
    return jsonify({"status": "success", "data": empty})


@app.route('/api/quality/results')
@require_role('super_admin', 'bef_admin')
def api_quality_results():
    """Get quality scan results. Supports ?date=, ?start=&end= for ranges. Super admin only."""
    try:
        from dashboard.database import get_quality_scan_results, get_weekly_scan_results
        scan_date = request.args.get('date')
        start_date = request.args.get('start')
        end_date = request.args.get('end')

        if start_date and end_date:
            # Date range query
            try:
                s = datetime.strptime(start_date, '%Y-%m-%d')
                e = datetime.strptime(end_date, '%Y-%m-%d')
                days = (e - s).days + 1
                results = get_weekly_scan_results(end_date, days)
            except ValueError:
                return jsonify({'status': 'error', 'message': 'Invalid date format. Use YYYY-MM-DD'}), 400
        else:
            results = get_quality_scan_results(scan_date)
        if not results:
            return jsonify({'status': 'success', 'results': [], 'total_clients': 0,
                            'clients_with_issues': 0, 'total_issues': 0, 'avg_health_score': 0,
                            'scan_dates': [],
                            'message': 'No scan results for this date range.'})

        # Collect unique scan dates
        scan_dates = sorted(set(r['scan_date'] for r in results))

        # Filter out scan errors and recalculate health scores BEFORE deduplication
        severity_weight = {'critical': 20, 'high': 10, 'medium': 5, 'low': 2, 'warning': 3, 'info': 0}
        for r in results:
            r['issues'] = [i for i in r.get('issues', []) if i.get('check') != 'Scan error']
            r['total_issues'] = len(r['issues'])
            deduction = sum(severity_weight.get(i.get('severity', 'low'), 2) for i in r['issues'])
            r['health_score'] = max(0.0, round(100.0 - deduction, 1))

        # For multi-day ranges, deduplicate: keep only the LATEST scan per client
        client_latest = {}
        for r in results:
            cid = r['client_id']
            if cid not in client_latest or r['scan_date'] > client_latest[cid]['scan_date']:
                client_latest[cid] = r
        deduped = list(client_latest.values())

        total_issues = sum(r['total_issues'] for r in deduped)
        clients_with_issues = sum(1 for r in deduped if r['total_issues'] > 0)
        avg_health = sum(r['health_score'] for r in deduped) / len(deduped) if deduped else 0

        return jsonify({
            'status': 'success',
            'scan_date': scan_dates[-1] if scan_dates else None,
            'scan_dates': scan_dates,
            'total_clients': len(deduped),
            'clients_with_issues': clients_with_issues,
            'total_issues': total_issues,
            'avg_health_score': round(avg_health, 1),
            'results': results  # Full results (all days) for the issues table
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f'Failed to load results: {str(e)}'}), 500


def compute_admin_tracker_payload(admin_name: str, date: str):
    """Compute admin-tracker payload (shared by UI + Slack summaries)."""
    from config.hierarchy import get_all_clients as hierarchy_get_all_clients, get_client_profile
    from dashboard.database import (
        get_quality_scan_results,
        get_client_data,
        get_daily_checklists,
        get_summary_status_for_date,
        get_setting,
    )
    from dashboard.notes_service import get_client_notes
    import json as _json

    # Exclusions mirror the Daily Summary Tracker rules
    excluded_traders = set(_json.loads(get_setting('summary_tracker_excluded_traders') or '[]'))
    excluded_clients = set(_json.loads(get_setting('summary_tracker_excluded_clients') or '[]'))
    _mffu_skip_admins = {'joy ndua', 'marion nyika'}
    max_out_exclusions = _load_max_out_exclusions()

    # Build admin client roster from hierarchy profiles
    clients = []
    for client_id in hierarchy_get_all_clients():
        p = get_client_profile(client_id) or {}
        if str(p.get('admin') or '').strip().lower() != str(admin_name or '').strip().lower():
            continue
        trader = str(p.get('trader') or '').strip()
        category = str(p.get('category') or p.get('profile') or '').strip() or 'PRIVATE'
        active_status = str(p.get('active_status') or 'active').strip().lower()
        clients.append({
            'client_id': client_id,
            'trader': trader,
            'category': category,
            'active_status': active_status,
        })
    clients.sort(key=lambda c: (c.get('active_status') != 'active', (c.get('trader') or ''), c['client_id']))

    # Load latest quality scan issues (used for fee/downtime derivations)
    scan_results = get_quality_scan_results() or []
    scan_by_client = {r.get('client_id'): r for r in scan_results if r.get('client_id')}

    admin_issues = []

    def _add_issue(issue_type, client_id, trader, severity, detail, extra=None):
        rec = {
            'type': issue_type,
            'client_id': client_id,
            'trader': trader or '',
            'severity': severity or 'medium',
            'detail': detail or '',
        }
        if extra and isinstance(extra, dict):
            rec.update(extra)
        admin_issues.append(rec)

    _inactive_tokens_p1 = ('fail', 'breach', 'closed', 'sl')
    _inactive_tokens_p2 = ('fail', 'breach', 'closed', 'sl', 'complete', 'completed')
    def _is_row_active(ev):
        sp1 = str(ev.get('Status P1', '') or '').strip().lower()
        sp2 = str(ev.get('Status', '') or ev.get('Status Funded', '') or '').strip().lower()
        if 'delete' in sp1 or 'delete' in sp2:
            return False
        return (not any(t in sp1 for t in _inactive_tokens_p1)) and (not any(t in sp2 for t in _inactive_tokens_p2))

    fee_issue_checks = {'Empty Fee', 'Empty Activation Fee', 'Alpha Futures: missing Activation Fee'}
    for c in clients:
        cid = c['client_id']
        trader = c.get('trader') or ''
        active_status = c.get('active_status', 'active')
        if active_status == 'inactive':
            continue
        if cid in excluded_clients or (trader and trader in excluded_traders):
            continue

        r = scan_by_client.get(cid) or {}
        for iss in (r.get('issues') or []):
            if iss.get('check') == 'No evaluations':
                _add_issue(
                    'no_evaluations',
                    cid,
                    trader,
                    iss.get('severity') or 'warning',
                    iss.get('detail') or 'No evaluation rows found',
                    extra={'estimated_date': iss.get('estimated_date')}
                )
        for iss in (r.get('issues') or []):
            if iss.get('check') in fee_issue_checks:
                _add_issue(
                    'challenge_fees',
                    cid,
                    trader,
                    iss.get('severity') or 'medium',
                    f"{iss.get('check')}: {iss.get('detail') or ''}",
                    extra={'row': iss.get('row'), 'estimated_date': iss.get('estimated_date')}
                )
        for iss in (r.get('issues') or []):
            if iss.get('check') == 'Downtime detected':
                _add_issue(
                    'downtime',
                    cid,
                    trader,
                    iss.get('severity') or 'high',
                    iss.get('detail') or 'Downtime detected',
                    extra={'row': iss.get('row'), 'estimated_date': iss.get('estimated_date')}
                )
        for iss in (r.get('issues') or []):
            if iss.get('check') == QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE:
                _add_issue(
                    'daily_summary_payout_qa',
                    cid,
                    trader,
                    iss.get('severity') or 'high',
                    iss.get('detail') or QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE,
                    extra={
                        'row': iss.get('row'),
                        'estimated_date': iss.get('estimated_date'),
                        'submitted_at': iss.get('submitted_at'),
                    },
                )

        # Prop firm max-out counts
        try:
            cdata = get_client_data(cid) or {}
            identity = cdata.get('identity', {}) if isinstance(cdata, dict) else {}
            if isinstance(identity, dict) and str(identity.get('active_status') or '').lower() == 'inactive':
                continue
            evals = [ev for ev in (cdata.get('evaluations') or []) if isinstance(ev, dict) and not ev.get('_deleted')]

            # Inject cell notes so we can suppress "excess accounts" when the extra rows are explained via notes.
            try:
                notes_by_row = get_client_notes(cid) or {}
                for _i, _ev in enumerate(evals):
                    if _i in notes_by_row:
                        _ev['_notes'] = notes_by_row[_i]
            except Exception:
                pass

            pf_rows = {}  # pf_key -> list[{idx, has_note}]
            for idx, ev in enumerate(evals):
                if not _is_row_active(ev):
                    continue
                pf_key = _norm_prop_firm_max_out_key(ev.get('Prop Firm'))
                if not pf_key:
                    continue
                # Exception: for these two admins, do not flag any MFFU max-out / excess-account issues.
                if pf_key == 'mffu' and str(admin_name or '').strip().lower() in _mffu_skip_admins:
                    continue
                # Excess-account suppression requires a note STRICTLY on the Status P1 cell.
                has_note = False
                cell_notes = ev.get('_notes') or {}
                if isinstance(cell_notes, dict):
                    sp1_note = cell_notes.get('Status P1')
                    if sp1_note is not None and str(sp1_note).strip():
                        has_note = True
                pf_rows.setdefault(pf_key, []).append({'idx': idx, 'has_note': has_note})

            for pf_key, rows in sorted(pf_rows.items()):
                if _max_out_triplet_excluded(admin_name, cid, pf_key, max_out_exclusions):
                    continue
                count = len(rows)
                expected = _admin_prop_max_active_expected(pf_key)
                if count == 0:
                    continue
                if count != expected:
                    human = _admin_prop_display_name(pf_key)
                    if count < expected:
                        skip_underfilled = (
                            count == 1
                            and _max_out_row_is_live_numeric_account(evals[rows[0]['idx']])
                        )
                        if not skip_underfilled:
                            _add_issue(
                                'max_out',
                                cid,
                                trader,
                                'medium',
                                f"{human}: {expected - count} needed (expected {expected}, has {count})",
                                extra={'prop_firm': human, 'expected': expected, 'count': count}
                            )
                    else:
                        excess = count - expected
                        noted = sum(1 for r in rows if r.get('has_note'))
                        if noted < excess:
                            missing_notes = excess - noted
                            _add_issue(
                                'max_out',
                                cid,
                                trader,
                                'medium',
                                f"{human}: too many accounts (expected {expected}, has {count}) — {missing_notes} excess row(s) missing note",
                                extra={'prop_firm': human, 'expected': expected, 'count': count, 'excess': excess, 'excess_missing_notes': missing_notes}
                            )
        except Exception:
            pass

    # Admin summary sign-off (only required after trader submitted)
    trader_submissions = get_summary_status_for_date(date) or []
    trader_sent_map = {}
    for s in trader_submissions:
        cid = (s.get('client_id') or '').strip()
        if not cid:
            continue
        if cid not in trader_sent_map:
            trader_sent_map[cid] = {
                'submitted_at': s.get('submitted_at'),
                # `get_summary_status_for_date` uses `submitted_by`; keep backward compatibility.
                'user_identifier': s.get('user_identifier') or s.get('submitted_by'),
            }
    trader_submitted_clients = set(trader_sent_map.keys())

    admin_checklists = get_daily_checklists(date, admin_name) or []
    def _is_admin_signed(checklist_row):
        try:
            if checklist_row.get('checklist_type') != 'admin_daily_summary':
                return False
            items = checklist_row.get('items') or []
            if not isinstance(items, list):
                return False
            for it in items:
                if isinstance(it, dict) and it.get('id') == 'sent_to_client' and bool(it.get('checked')):
                    return True
            return False
        except Exception:
            return False

    admin_signed_clients = {
        (c.get('client_id') or '').strip()
        for c in admin_checklists
        if c.get('client_id') and _is_admin_signed(c)
    }

    required_clients = sorted([
        (c.get('client_id') or '').strip()
        for c in clients
        if c.get('active_status') == 'active'
        and (c.get('client_id') or '').strip() in {str(x or '').strip() for x in trader_submitted_clients}
        and ((c.get('client_id') or '').strip() not in {str(x or '').strip() for x in excluded_clients})
        and ((c.get('trader') or '') not in excluded_traders)
    ])
    pending_clients = sorted([cid for cid in required_clients if cid not in admin_signed_clients])

    severity_weight = {'critical': 20, 'high': 10, 'medium': 5, 'low': 2, 'warning': 3, 'info': 0}
    deduction = sum(severity_weight.get(i.get('severity', 'low'), 2) for i in admin_issues)
    health_score = max(0.0, round(100.0 - deduction, 1))

    # Backward/forward compatibility: different UIs may read `issues` or `admin_issues`.
    # Keep `issues` as canonical, but include both keys.
    return {
        'admin': admin_name,
        'date': date,
        'clients': clients,
        'issues': admin_issues,
        'admin_issues': admin_issues,
        'total_clients': len([c for c in clients if c.get('active_status') == 'active']),
        'total_issues': len(admin_issues),
        'health_score': health_score,
        'summary_signoff': {
            'required_total': len(required_clients),
            'signed_total': sum(1 for cid in required_clients if cid in admin_signed_clients),
            'pending_total': len(pending_clients),
            'pending_clients': pending_clients,
            'signed_clients': sorted([cid for cid in required_clients if cid in admin_signed_clients]),
            'trader_sent': trader_sent_map,
        }
    }


@app.route('/api/admin/tracker')
@require_role('admin', 'super_admin', 'bef_admin', 'kwok_admin')
def api_admin_tracker():
    """Admin tracking dashboard: aggregate admin-owned issues derived from client state and quality scan."""
    try:
        from config.hierarchy import get_all_clients as hierarchy_get_all_clients, get_client_profile
        from dashboard.database import (
            get_quality_scan_results,
            get_client_data,
            get_daily_checklists,
            get_summary_status_for_date,
            get_setting,
        )
        import json as _json

        def _compute_admin_tracker_payload(admin_name: str, date: str):
            # Exclusions mirror the Daily Summary Tracker rules
            excluded_traders = set(_json.loads(get_setting('summary_tracker_excluded_traders') or '[]'))
            excluded_clients = set(_json.loads(get_setting('summary_tracker_excluded_clients') or '[]'))
            max_out_exclusions = _load_max_out_exclusions()

            # Build admin client roster from hierarchy profiles
            clients = []
            for raw_client_id in hierarchy_get_all_clients():
                client_id = str(raw_client_id or '').strip()
                if not client_id:
                    continue
                p = get_client_profile(raw_client_id) or {}
                if str(p.get('admin') or '').strip().lower() != admin_name.lower():
                    continue
                trader = str(p.get('trader') or '').strip()
                category = str(p.get('category') or p.get('profile') or '').strip() or 'PRIVATE'
                active_status = str(p.get('active_status') or 'active').strip().lower()
                clients.append({
                    'client_id': client_id,
                    'trader': trader,
                    'category': category,
                    'active_status': active_status,
                })
            clients.sort(key=lambda c: (c.get('active_status') != 'active', (c.get('trader') or ''), c['client_id']))

            # Load latest quality scan issues (used for fee/downtime derivations)
            scan_results = get_quality_scan_results() or []
            scan_by_client = {r.get('client_id'): r for r in scan_results if r.get('client_id')}

            admin_issues = []

            def _add_issue(issue_type, client_id, trader, severity, detail, extra=None):
                rec = {
                    'type': issue_type,
                    'client_id': client_id,
                    'trader': trader or '',
                    'severity': severity or 'medium',
                    'detail': detail or '',
                }
                if extra and isinstance(extra, dict):
                    rec.update(extra)
                admin_issues.append(rec)

            _inactive_tokens_p1 = ('fail', 'breach', 'closed', 'sl')
            _inactive_tokens_p2 = ('fail', 'breach', 'closed', 'sl', 'complete', 'completed')
            def _is_row_active(ev):
                sp1 = str(ev.get('Status P1', '') or '').strip().lower()
                sp2 = str(ev.get('Status', '') or ev.get('Status Funded', '') or '').strip().lower()
                if 'delete' in sp1 or 'delete' in sp2:
                    return False
                return (not any(t in sp1 for t in _inactive_tokens_p1)) and (not any(t in sp2 for t in _inactive_tokens_p2))

            fee_issue_checks = {'Empty Fee', 'Empty Activation Fee', 'Alpha Futures: missing Activation Fee'}
            for c in clients:
                cid = c['client_id']
                trader = c.get('trader') or ''
                active_status = c.get('active_status', 'active')
                if active_status == 'inactive':
                    continue
                if cid in excluded_clients or (trader and trader in excluded_traders):
                    continue

                r = scan_by_client.get(cid) or {}
                for iss in (r.get('issues') or []):
                    if iss.get('check') == 'No evaluations':
                        _add_issue(
                            'no_evaluations',
                            cid,
                            trader,
                            iss.get('severity') or 'warning',
                            iss.get('detail') or 'No evaluation rows found',
                            extra={'estimated_date': iss.get('estimated_date')}
                        )
                for iss in (r.get('issues') or []):
                    if iss.get('check') in fee_issue_checks:
                        _add_issue(
                            'challenge_fees',
                            cid,
                            trader,
                            iss.get('severity') or 'medium',
                            f"{iss.get('check')}: {iss.get('detail') or ''}",
                            extra={'row': iss.get('row'), 'estimated_date': iss.get('estimated_date')}
                        )
                for iss in (r.get('issues') or []):
                    if iss.get('check') == 'Downtime detected':
                        _add_issue(
                            'downtime',
                            cid,
                            trader,
                            iss.get('severity') or 'high',
                            iss.get('detail') or 'Downtime detected',
                            extra={'row': iss.get('row'), 'estimated_date': iss.get('estimated_date')}
                        )
                for iss in (r.get('issues') or []):
                    if iss.get('check') == QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE:
                        _add_issue(
                            'daily_summary_payout_qa',
                            cid,
                            trader,
                            iss.get('severity') or 'high',
                            iss.get('detail') or QA_CHECK_DAILY_SUMMARY_PAYOUT_ELIGIBLE,
                            extra={
                                'row': iss.get('row'),
                                'estimated_date': iss.get('estimated_date'),
                                'submitted_at': iss.get('submitted_at'),
                            },
                        )

                # Prop firm max-out counts
                try:
                    cdata = get_client_data(cid) or {}
                    identity = cdata.get('identity', {}) if isinstance(cdata, dict) else {}
                    if isinstance(identity, dict) and str(identity.get('active_status') or '').lower() == 'inactive':
                        continue
                    evals = [ev for ev in (cdata.get('evaluations') or []) if isinstance(ev, dict) and not ev.get('_deleted')]

                    # Inject cell notes so we can suppress "excess accounts" when the extra rows are explained via notes.
                    # (Matches how run_quality_scan injects notes.)
                    try:
                        notes_by_row = get_client_notes(cid) or {}
                        for _i, _ev in enumerate(evals):
                            if _i in notes_by_row:
                                _ev['_notes'] = notes_by_row[_i]
                    except Exception:
                        pass

                    pf_rows = {}  # pf_key -> list[{idx, has_note}]
                    for idx, ev in enumerate(evals):
                        if not _is_row_active(ev):
                            continue
                        pf_key = _norm_prop_firm_max_out_key(ev.get('Prop Firm'))
                        if not pf_key:
                            continue
                        # Excess-account suppression requires a note STRICTLY on the Status P1 cell.
                        # Notes on other cells are not accepted for this purpose.
                        has_note = False
                        cell_notes = ev.get('_notes') or {}
                        if isinstance(cell_notes, dict):
                            sp1_note = cell_notes.get('Status P1')
                            if sp1_note is not None and str(sp1_note).strip():
                                has_note = True
                        pf_rows.setdefault(pf_key, []).append({'idx': idx, 'has_note': has_note})

                    for pf_key, rows in sorted(pf_rows.items()):
                        if _max_out_triplet_excluded(admin_name, cid, pf_key, max_out_exclusions):
                            continue
                        count = len(rows)
                        expected = _admin_prop_max_active_expected(pf_key)
                        if count == 0:
                            continue
                        if count != expected:
                            human = _admin_prop_display_name(pf_key)
                            if count < expected:
                                skip_underfilled = (
                                    count == 1
                                    and _max_out_row_is_live_numeric_account(evals[rows[0]['idx']])
                                )
                                if not skip_underfilled:
                                    _add_issue(
                                        'max_out',
                                        cid,
                                        trader,
                                        'medium',
                                        f"{human}: {expected - count} needed (expected {expected}, has {count})",
                                        extra={'prop_firm': human, 'expected': expected, 'count': count}
                                    )
                            else:
                                # Excess accounts are allowed ONLY when the extra rows have notes.
                                # If N accounts exceed the required count, we require at least N rows
                                # to have a note (cell note or Notes column). Otherwise, flag.
                                excess = count - expected
                                noted = sum(1 for r in rows if r.get('has_note'))
                                if noted < excess:
                                    missing_notes = excess - noted
                                    _add_issue(
                                        'max_out',
                                        cid,
                                        trader,
                                        'medium',
                                        f"{human}: too many accounts (expected {expected}, has {count}) — {missing_notes} excess row(s) missing note",
                                        extra={'prop_firm': human, 'expected': expected, 'count': count, 'excess': excess, 'excess_missing_notes': missing_notes}
                                    )
                except Exception:
                    pass

            # Admin summary sign-off (only required after a summary has been sent "upstream")
            # In your workflow: trader sends summary → admin reviews → admin confirms accurate & sent to client.
            trader_submissions = get_summary_status_for_date(date) or []
            trader_sent_map = {}
            for s in trader_submissions:
                cid = s.get('client_id')
                if not cid:
                    continue
                # Keep the most recent submission per client (get_summary_status_for_date is newest-first already)
                if cid not in trader_sent_map:
                    trader_sent_map[cid] = {
                        'submitted_at': s.get('submitted_at'),
                        'user_identifier': s.get('user_identifier'),
                    }
            trader_submitted_clients = set(trader_sent_map.keys())

            admin_checklists = get_daily_checklists(date, admin_name) or []
            def _is_admin_signed(checklist_row):
                try:
                    if checklist_row.get('checklist_type') != 'admin_daily_summary':
                        return False
                    items = checklist_row.get('items') or []
                    if not isinstance(items, list):
                        return False
                    for it in items:
                        if isinstance(it, dict) and it.get('id') == 'sent_to_client' and bool(it.get('checked')):
                            return True
                    return False
                except Exception:
                    return False

            admin_signed_clients = {
                c.get('client_id')
                for c in admin_checklists
                if c.get('client_id') and _is_admin_signed(c)
            }

            required_clients = []
            pending_clients = []
            for c in clients:
                cid = c['client_id']
                trader = c.get('trader') or ''
                if c.get('active_status') == 'inactive':
                    continue
                if cid in excluded_clients or (trader and trader in excluded_traders):
                    continue
                if cid not in trader_submitted_clients:
                    continue
                required_clients.append(cid)
                if cid not in admin_signed_clients:
                    pending_clients.append(cid)
                    _add_issue(
                        'summary_signoff',
                        cid,
                        trader,
                        'medium',
                        'Daily summary not signed off (confirm sent to client)',
                        extra={'date': date}
                    )

            sev_rank = {'critical': 0, 'high': 1, 'medium': 2, 'warning': 3, 'low': 4, 'info': 5}
            admin_issues.sort(key=lambda i: (sev_rank.get(i.get('severity', 'medium'), 9), i.get('type', ''), i.get('client_id', '')))

            return {
                'admin': admin_name,
                'date': date,
                'clients': clients,
                'admin_issues': admin_issues,
                'summary_signoff': {
                    'required_total': len(required_clients),
                    'signed_total': sum(1 for cid in required_clients if cid in admin_signed_clients),
                    'pending_total': len(pending_clients),
                    'pending_clients': pending_clients,
                    'signed_clients': sorted([cid for cid in required_clients if cid in admin_signed_clients]),
                    'trader_sent': trader_sent_map,
                }
            }

        session_user = request.session_user
        if session_user.get('user_type') in ('super_admin', 'bef_admin', 'kwok_admin'):
            admin_name = (request.args.get('admin') or '').strip()
        else:
            admin_name = (session_user.get('user_identifier') or '').strip()
        if not admin_name:
            return jsonify({'status': 'error', 'message': 'Admin name required'}), 400
        date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))

        payload = compute_admin_tracker_payload(admin_name, date)
        return jsonify({'status': 'success', **payload})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f'Failed to load admin tracker: {str(e)}'}), 500


@app.route('/api/quality/admin_tracker')
@require_role('super_admin', 'bef_admin')
def api_quality_admin_tracker():
    """Super-admin view of admin tracker issues across admins (quality dashboard source of truth)."""
    try:
        from config.hierarchy import get_all_clients as hierarchy_get_all_clients, get_client_profile
        admins = set()
        for cid in hierarchy_get_all_clients():
            p = get_client_profile(cid) or {}
            a = str(p.get('admin') or '').strip()
            if a:
                admins.add(a)
        admin = (request.args.get('admin') or '').strip()
        date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))

        # Reuse the existing admin tracker endpoint logic by calling the local view function's helper through a request-style call:
        # We simply invoke /api/admin/tracker-style computation by issuing internal HTTP is overkill; instead, we call api_admin_tracker
        # is not possible cleanly. So we request per-admin via the public function by recreating minimal request args is not safe.
        # Pragmatic: call /api/admin/tracker endpoint from frontend for a single admin; for all admins, loop here with the same logic
        # by delegating to the endpoint itself is avoided. Instead, we reuse the DB-backed quality + client data directly by
        # calling the /api/admin/tracker route through WSGI is out of scope.

        # Implementation: make N calls by recomputing via querystring by temporarily setting request args is unsafe.
        # Therefore, we implement a small loop by calling the public endpoint over HTTP is also not allowed here.
        # So: return the list of admins + let the quality dashboard fetch each admin in parallel.
        # This keeps server logic correct and avoids duplicating the computation again.
        result_admins = sorted(admins)
        if admin:
            if admin not in admins:
                return jsonify({'status': 'error', 'message': 'Unknown admin'}), 404
            return jsonify({'status': 'success', 'admins': result_admins, 'admin': admin, 'date': date})
        return jsonify({'status': 'success', 'admins': result_admins, 'date': date})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f'Failed to load admin tracker index: {str(e)}'}), 500

@app.route('/api/quality/admin_issues')
@require_role('admin', 'super_admin')
def api_admin_issues():
    """Return latest quality scan results filtered for a specific admin's traders/clients. Admin role only."""
    try:
        from dashboard.database import get_quality_scan_results
        session_user = request.session_user
        if session_user.get('user_type') == 'super_admin':
            admin_name = request.args.get('admin', '')
        else:
            admin_name = session_user.get('user_identifier', '')
        if not admin_name:
            return jsonify({'status': 'error', 'message': 'Admin name required'}), 400
        results = get_quality_scan_results()  # latest scan
        # Filter for this admin only
        filtered = [r for r in results if (r.get('admin') or '').lower() == admin_name.lower()]
        # Strip scan errors, recalculate health
        severity_weight = {'critical': 20, 'high': 10, 'medium': 5, 'low': 2, 'warning': 3, 'info': 0}
        for r in filtered:
            r['issues'] = [i for i in r.get('issues', []) if i.get('check') != 'Scan error']
            r['total_issues'] = len(r['issues'])
            deduction = sum(severity_weight.get(i.get('severity', 'low'), 2) for i in r['issues'])
            r['health_score'] = max(0.0, round(100.0 - deduction, 1))
        total_issues = sum(r['total_issues'] for r in filtered)
        return jsonify({
            'status': 'success',
            'admin': admin_name,
            'total_clients': len(filtered),
            'clients_with_issues': sum(1 for r in filtered if r['total_issues'] > 0),
            'total_issues': total_issues,
            'results': filtered
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f'Failed to load admin issues: {str(e)}'}), 500


@app.route('/api/quality/scan_dates')
@require_role('super_admin', 'bef_admin')
def api_quality_scan_dates():
    """Get list of all dates that have scan results."""
    try:
        from dashboard.database import get_connection
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT scan_date FROM quality_scan_results ORDER BY scan_date DESC')
            dates = [row['scan_date'] for row in cursor.fetchall()]
        return jsonify({'status': 'success', 'dates': dates})
    except Exception as e:
        return jsonify({'status': 'success', 'dates': []})


@app.route('/api/quality/summary_status')
@require_role('super_admin', 'bef_admin')
def api_summary_status():
    """Get daily summary submission status for all clients, grouped by trader."""
    from config.hierarchy import get_all_clients as hierarchy_get_all_clients, get_client_profile
    from dashboard.database import get_summary_status_for_date, get_setting, get_client_data
    import json as _json

    # Use UTC date as default — server runs UTC, so midnight UTC = 3 AM Kenyan.
    # This means the tracker naturally flips ~55 min after the 2:05 AM Slack send.
    from datetime import timezone, timedelta as _td
    _kenyan_tz = timezone(_td(hours=3))
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    submissions = get_summary_status_for_date(date)

    # Convert timestamps from UTC to Kenyan time (UTC+3)
    for s in submissions:
        ts = s.get('submitted_at', '')
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                s['submitted_at'] = dt.astimezone(_kenyan_tz).isoformat()
            except Exception:
                pass

    sent_map = {s['client_id']: s for s in submissions}
    all_clients = hierarchy_get_all_clients()

    # Load exclusion settings
    excluded_traders = set(_json.loads(get_setting('summary_tracker_excluded_traders') or '[]'))
    excluded_clients = set(_json.loads(get_setting('summary_tracker_excluded_clients') or '[]'))

    traders = {}  # trader -> {sent: [...], not_sent: [...]}
    tracked_count = 0
    for client_name in all_clients:
        profile = get_client_profile(client_name)
        trader = (profile.get('trader', '') if profile else '') or 'Unassigned'

        # Skip excluded traders entirely
        if trader in excluded_traders:
            continue

        # Skip excluded clients
        if client_name in excluded_clients:
            continue

        # Skip inactive clients by default
        try:
            cdata = get_client_data(client_name)
            if cdata and isinstance(cdata.get('identity'), dict):
                if cdata['identity'].get('active_status') == 'inactive':
                    continue
        except Exception:
            pass

        tracked_count += 1
        if trader not in traders:
            traders[trader] = {'sent': [], 'not_sent': []}
        if client_name in sent_map:
            s = sent_map[client_name]
            traders[trader]['sent'].append({
                'client_id': client_name,
                'submitted_by': s['submitted_by'],
                'submitted_at': s['submitted_at']
            })
        else:
            traders[trader]['not_sent'].append(client_name)
    # Issue-clearance speed (from morning scan baseline → all clients at 0 issues)
    from dashboard.database import get_trader_issue_resolution_minutes, get_quality_scan_results
    scan_date = date
    scan_by_trader = {}
    for row in get_quality_scan_results(scan_date) or []:
        t = (row.get('trader') or '') or 'Unassigned'
        ti, hs = _trader_ranking_health_metrics(row.get('issues'))
        if t not in scan_by_trader:
            scan_by_trader[t] = {
                'open_issues': 0, 'clients_with_issues': 0, 'health_sum': 0.0, 'clients_scanned': 0,
            }
        scan_by_trader[t]['health_sum'] += hs
        scan_by_trader[t]['clients_scanned'] += 1
        if ti > 0:
            scan_by_trader[t]['open_issues'] += ti
            scan_by_trader[t]['clients_with_issues'] += 1

    total_sent = sum(len(d['sent']) for d in traders.values())
    result = []
    for trader, data in traders.items():
        raw_mins = get_trader_issue_resolution_minutes(scan_date, trader)
        unresolved = raw_mins >= 99999
        not_in_race = raw_mins < 0
        st = scan_by_trader.get(trader, {})
        avg_health = round(st.get('health_sum', 0) / max(st.get('clients_scanned', 1), 1), 1)
        lb_stats = {
            'issues': st.get('open_issues', 0),
            'health_sum': st.get('health_sum', 0),
            'clients': max(st.get('clients_scanned', 1), 1),
        }
        result.append({
            'trader': trader,
            'total': len(data['sent']) + len(data['not_sent']),
            'sent_count': len(data['sent']),
            'sent': data['sent'],
            'not_sent': data['not_sent'],
            'clearance_minutes': None if unresolved or not_in_race else raw_mins,
            'clearance_unresolved': unresolved,
            'clearance_not_in_race': not_in_race,
            'avg_health': avg_health,
            'clearance_label': _trader_tracker_subtitle(raw_mins, lb_stats),
            'open_issues': st.get('open_issues', 0),
            'clients_with_issues': st.get('clients_with_issues', 0),
            'clients_scanned': st.get('clients_scanned', 0),
        })
    result.sort(key=_trader_clearance_sort_key)
    for idx, row in enumerate(result, 1):
        row['clearance_rank'] = idx
    return jsonify({
        'status': 'success', 'date': date,
        'total_clients': tracked_count, 'total_sent': total_sent,
        'total_not_sent': tracked_count - total_sent,
        'excluded_traders': sorted(excluded_traders),
        'excluded_clients': sorted(excluded_clients),
        'traders': result
    })


def _resolve_trader_for_session(session_user, requested):
    """Resolve which trader a request is asking about and whether the session is allowed.

    Returns (trader_name, error_response_or_None). If the second element is not None,
    the caller should return it directly.
    """
    user_type = session_user.get('user_type')
    user_id = (session_user.get('user_identifier') or '').strip()
    requested = (requested or '').strip()

    if user_type == 'trader':
        # Traders can only query their own data
        if requested and requested != user_id:
            return None, (jsonify({'status': 'error', 'message': 'Access denied'}), 403)
        return user_id, None

    trader_name = requested or user_id
    if not trader_name:
        return None, (jsonify({'status': 'error', 'message': 'Trader required'}), 400)

    if user_type == 'admin':
        admin_data = hierarchy.get('admins', {}).get(user_id, {}) or {}
        if trader_name not in (admin_data.get('traders') or {}):
            return None, (jsonify({'status': 'error', 'message': 'Access denied'}), 403)

    # super_admin / bef_admin: allow any trader
    return trader_name, None


def _clients_for_trader(trader_name):
    """Return the list of client names managed by the given trader across all admins."""
    names = []
    seen = set()
    for admin_data in hierarchy.get('admins', {}).values():
        tdata = (admin_data.get('traders') or {}).get(trader_name)
        if not tdata:
            continue
        for c in tdata.get('clients', []) or []:
            nm = c.get('name') if isinstance(c, dict) else c
            if nm and nm not in seen:
                seen.add(nm)
                names.append(nm)
    return names


@app.route('/api/quality/trader_issues')
@require_role('trader', 'admin', 'super_admin', 'bef_admin', 'kwok_admin')
def api_trader_issues():
    """Latest quality scan issues filtered to a single trader's clients.

    Traders see only themselves; admins see their own traders; super_admin /
    bef_admin can pass ?trader=<name>. Clients with no scan record are
    returned with total_issues=0 so the UI can show "all clear" rows too.
    """
    try:
        from dashboard.database import get_quality_scan_results, get_connection
        import json as _json
        trader_name, err = _resolve_trader_for_session(request.session_user, request.args.get('trader'))
        if err is not None:
            return err

        trader_clients = set(_clients_for_trader(trader_name))
        # Optional: rescan=1 to force live recompute (keeps trader portal in sync with client dashboard).
        # This is intentionally opt-in because it can be expensive across many clients.
        do_rescan = request.args.get('rescan') == '1'
        scan_date_today = datetime.now().strftime('%Y-%m-%d')

        if do_rescan and trader_clients:
            # Cap rescans for safety (super_admin can rescan larger sets).
            ut = (request.session_user or {}).get('user_type') or ''
            max_clients = 60 if ut in ('super_admin', 'bef_admin', 'kwok_admin') else 25
            # Deterministic order to avoid "random" partial refreshes.
            to_scan = sorted(list(trader_clients))[:max_clients]
            live_results = None
            # Fallback path: scan per client (run_quality_scan supports target_client)
            if not live_results:
                live_results = []
                for cid in to_scan:
                    try:
                        rlist = run_quality_scan(target_client=cid) or []
                        if rlist:
                            live_results.append(rlist[0])
                    except Exception:
                        continue

            # Persist into today's scan rows (best effort)
            try:
                with get_connection() as conn:
                    cursor = conn.cursor()
                    for r in live_results:
                        try:
                            cursor.execute('DELETE FROM quality_scan_results WHERE scan_date = ? AND client_id = ?',
                                           (scan_date_today, r['client_id']))
                            cursor.execute('''INSERT INTO quality_scan_results
                                              (scan_date, client_id, trader, admin, total_issues, issues, health_score)
                                              VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                           (scan_date_today, r['client_id'], r.get('trader'), r.get('admin'),
                                            r.get('total_issues', 0), _json.dumps(r.get('issues') or []), r.get('health_score', 100.0)))
                        except Exception:
                            continue
                    conn.commit()
                if live_results:
                    _sync_quality_issue_tracking(scan_date_today, live_results)
            except Exception:
                pass

        results = get_quality_scan_results() or []
        filtered = [
            _quality_scan_row_for_trader_client_quality_api(r)
            for r in results
            if r.get('client_id') in trader_clients
        ]

        scanned_ids = {r['client_id'] for r in filtered}
        for nm in sorted(trader_clients - scanned_ids):
            filtered.append({
                'client_id': nm, 'trader': trader_name,
                'issues': [], 'total_issues': 0, 'health_score': 100.0,
                'scan_date': None,
            })

        filtered.sort(key=lambda r: (-r.get('total_issues', 0), r.get('client_id') or ''))
        total_issues = sum(r.get('total_issues', 0) for r in filtered)
        clients_with_issues = sum(1 for r in filtered if r.get('total_issues', 0) > 0)

        return jsonify({
            'status': 'success',
            'trader': trader_name,
            'total_clients': len(filtered),
            'clients_with_issues': clients_with_issues,
            'total_issues': total_issues,
            'results': filtered,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f'Failed to load trader issues: {str(e)}'}), 500


@app.route('/api/quality/trader_summary_status')
@require_role('trader', 'admin', 'super_admin', 'bef_admin', 'kwok_admin')
def api_trader_summary_status():
    """Daily summary submission status filtered to a single trader's clients."""
    try:
        from dashboard.database import get_summary_status_for_date, get_setting, get_client_data
        import json as _json
        from datetime import timezone, timedelta as _td

        trader_name, err = _resolve_trader_for_session(request.session_user, request.args.get('trader'))
        if err is not None:
            return err

        date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        submissions = get_summary_status_for_date(date) or []

        _kenyan_tz = timezone(_td(hours=3))
        for s in submissions:
            ts = s.get('submitted_at', '')
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    s['submitted_at'] = dt.astimezone(_kenyan_tz).isoformat()
                except Exception:
                    pass

        sent_map = {s['client_id']: s for s in submissions}

        excluded_traders = set(_json.loads(get_setting('summary_tracker_excluded_traders') or '[]'))
        excluded_clients = set(_json.loads(get_setting('summary_tracker_excluded_clients') or '[]'))

        clients_payload = []
        for nm in _clients_for_trader(trader_name):
            if nm in excluded_clients:
                continue
            try:
                cdata = get_client_data(nm)
                if cdata and isinstance(cdata.get('identity'), dict):
                    if cdata['identity'].get('active_status') == 'inactive':
                        continue
            except Exception:
                pass
            if nm in sent_map:
                s = sent_map[nm]
                clients_payload.append({
                    'client_id': nm,
                    'sent': True,
                    'submitted_by': s.get('submitted_by'),
                    'submitted_at': s.get('submitted_at'),
                })
            else:
                clients_payload.append({'client_id': nm, 'sent': False})

        clients_payload.sort(key=lambda c: (c['sent'], c['client_id'].lower()))

        total_sent = sum(1 for c in clients_payload if c['sent'])
        return jsonify({
            'status': 'success',
            'trader': trader_name,
            'date': date,
            'total_clients': len(clients_payload),
            'total_sent': total_sent,
            'total_not_sent': len(clients_payload) - total_sent,
            'trader_excluded': trader_name in excluded_traders,
            'clients': clients_payload,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f'Failed to load trader summaries: {str(e)}'}), 500


@app.route('/api/quality/summary_tracker_exclude', methods=['POST'])
@require_role('super_admin')
def api_summary_tracker_exclude():
    """Toggle trader/client exclusion for the Daily Summary Tracker and related quality views."""
    from dashboard.database import get_setting, set_setting
    import json as _json

    data = request.get_json(force=True)
    exclude_type = data.get('type')  # 'trader' or 'client'
    name = (data.get('name') or '').strip()
    action = data.get('action', 'toggle')  # 'add', 'remove', or 'toggle'

    if exclude_type not in ('trader', 'client') or not name:
        return jsonify({'status': 'error', 'message': 'Invalid type or name'}), 400

    key = f'summary_tracker_excluded_{"traders" if exclude_type == "trader" else "clients"}'
    current = set(_json.loads(get_setting(key) or '[]'))

    if action == 'add':
        current.add(name)
    elif action == 'remove':
        current.discard(name)
    else:  # toggle
        if name in current:
            current.discard(name)
        else:
            current.add(name)

    user_id = request.session_user.get('user_identifier', '')
    set_setting(key, _json.dumps(sorted(current)), updated_by=user_id)

    log_action('SUMMARY_TRACKER_EXCLUDE', 'super_admin', user_id,
               get_remote_address(), f'{action} {exclude_type}: {name}')

    return jsonify({'status': 'success', 'excluded': sorted(current)})


@app.route('/api/quality/max_out_exclusions', methods=['GET', 'POST', 'DELETE'])
@require_role('super_admin')
def api_quality_max_out_exclusions():
    """Manage admin+client+prop-firm triplets excluded from Admin Tracker max-out checks."""
    from dashboard.database import get_setting, set_setting
    import uuid as _uuid

    if request.method == 'GET':
        exclusions = list(_load_max_out_exclusions())
        for ex in exclusions:
            ex['prop_firm_label'] = _admin_prop_display_name(ex['prop_firm_key'])
        admins = sorted(SYSTEM_HIERARCHY.get('admins', {}).keys(), key=lambda s: str(s).lower())
        client_rows = []
        for admin in SYSTEM_HIERARCHY.get('admins', {}):
            ad = SYSTEM_HIERARCHY['admins'][admin]
            for trader_name, trader_data in (ad.get('traders') or {}).items():
                for client in trader_data.get('clients') or []:
                    if not isinstance(client, dict):
                        continue
                    nm = (client.get('name') or '').strip()
                    if nm:
                        client_rows.append({
                            'client_id': nm,
                            'admin': admin,
                            'trader': trader_name,
                        })
        client_rows.sort(key=lambda r: (str(r['admin']).lower(), str(r['client_id']).lower()))
        return jsonify({
            'status': 'success',
            'exclusions': exclusions,
            'admins': admins,
            'clients': client_rows,
            'prop_firms': _prop_firm_dropdown_options_max_out(),
        })

    data = request.get_json(silent=True) or {}
    user_id = request.session_user.get('user_identifier', '')

    if request.method == 'POST':
        admin = (data.get('admin') or '').strip()
        cid = (data.get('client_id') or '').strip()
        pf_raw = (data.get('prop_firm_key') or data.get('prop_firm') or '').strip()
        pfk = _norm_prop_firm_max_out_key(pf_raw)
        if not admin or not cid or not pfk:
            return jsonify({'status': 'error', 'message': 'admin, client_id, and prop_firm_key are required'}), 400
        profile = get_client_profile(cid) or {}
        if str(profile.get('admin') or '').strip().lower() != admin.lower():
            return jsonify({'status': 'error', 'message': 'Selected client is not assigned to the selected admin'}), 400
        cur = _load_max_out_exclusions()
        if _max_out_triplet_excluded(admin, cid, pfk, cur):
            return jsonify({'status': 'error', 'message': 'This exclusion already exists'}), 400
        cur.append({
            'id': str(_uuid.uuid4()),
            'admin': admin,
            'client_id': cid,
            'prop_firm_key': pfk,
        })
        set_setting(_QUALITY_MAX_OUT_EXCLUSIONS_KEY, json.dumps(cur), updated_by=user_id)
        log_action(
            'MAX_OUT_EXCLUSION_ADD',
            'super_admin',
            user_id,
            get_remote_address(),
            f'admin={admin} client={cid} prop_firm_key={pfk}',
        )
        for ex in cur:
            ex['prop_firm_label'] = _admin_prop_display_name(ex['prop_firm_key'])
        return jsonify({'status': 'success', 'exclusions': cur})

    eid = (data.get('id') or '').strip()
    if not eid:
        return jsonify({'status': 'error', 'message': 'id required'}), 400
    cur = _load_max_out_exclusions()
    new_list = [x for x in cur if str(x.get('id')) != eid]
    if len(new_list) == len(cur):
        return jsonify({'status': 'error', 'message': 'Exclusion not found'}), 404
    set_setting(_QUALITY_MAX_OUT_EXCLUSIONS_KEY, json.dumps(new_list), updated_by=user_id)
    log_action(
        'MAX_OUT_EXCLUSION_REMOVE',
        'super_admin',
        user_id,
        get_remote_address(),
        f'id={eid}',
    )
    for ex in new_list:
        ex['prop_firm_label'] = _admin_prop_display_name(ex['prop_firm_key'])
    return jsonify({'status': 'success', 'exclusions': new_list})


@app.route('/api/quality/trade_count_toggle', methods=['POST'])
@require_session
def api_trade_count_toggle():
    """Toggle a client for trade-count tracking in the daily summary (off by default)."""
    from dashboard.database import get_setting, set_setting
    import json as _json

    data = request.get_json(force=True)
    client_name = (data.get('client') or '').strip()
    action = data.get('action', 'toggle')  # 'add', 'remove', or 'toggle'

    if not client_name:
        return jsonify({'status': 'error', 'message': 'Client name required'}), 400

    key = 'trade_count_enabled_clients'
    current = set(_json.loads(get_setting(key) or '[]'))

    if action == 'add':
        current.add(client_name)
    elif action == 'remove':
        current.discard(client_name)
    else:
        if client_name in current:
            current.discard(client_name)
        else:
            current.add(client_name)

    user_id = request.session_user.get('user_identifier', '')
    user_type = request.session_user.get('user_type', '')
    set_setting(key, _json.dumps(sorted(current)), updated_by=user_id)

    log_action('TRADE_COUNT_TOGGLE', user_type, user_id,
               get_remote_address(), f'{action} client: {client_name}')

    return jsonify({'status': 'success', 'enabled_clients': sorted(current)})


@app.route('/api/quality/trade_count_clients')
@require_session
def api_trade_count_clients():
    """Return list of clients with trade-count tracking enabled."""
    from dashboard.database import get_setting
    import json as _json
    enabled = sorted(set(_json.loads(get_setting('trade_count_enabled_clients') or '[]')))
    return jsonify({'status': 'success', 'enabled_clients': enabled})


@app.route('/api/admin/repair_db', methods=['POST'])
@app.route('/api/admin/db_repair', methods=['POST'])
@require_role('super_admin')
def api_repair_database():
    """Attempt to repair a corrupted SQLite database. Super admin only."""
    from dashboard.database import check_and_repair_database
    ok, message = check_and_repair_database()
    log_action('DB_REPAIR', 'super_admin', request.session_user.get('user_identifier'),
               get_remote_address(), message)
    if ok:
        return jsonify({'status': 'success', 'message': message})
    return jsonify({'status': 'error', 'message': message}), 500


# ============ Daily Checklists ============

@app.route('/api/checklist/submit', methods=['POST'])
@require_session
def api_submit_checklist():
    """Submit a daily checklist (per client)."""
    from dashboard.database import save_daily_checklist
    session_user = request.session_user
    user_type = session_user.get('user_type')
    user_identifier = session_user.get('user_identifier')

    data = request.json
    checklist_type = data.get('checklist_type', 'daily_summary')
    client_id = data.get('client_id', '')
    items = data.get('items', [])

    if not items:
        return jsonify({'status': 'error', 'message': 'No items provided'}), 400

    today = datetime.now().strftime('%Y-%m-%d')
    save_daily_checklist(today, user_identifier, user_type, checklist_type, items,
                         get_remote_address(), client_id=client_id)

    log_action('CHECKLIST_SUBMIT', user_type, user_identifier, get_remote_address(),
               f"{checklist_type} for {client_id}: {len(items)} sections")

    return jsonify({'status': 'success', 'message': 'Daily summary saved'})


@app.route('/api/checklist/status')
@require_session
def api_checklist_status():
    """Get checklist status for today (or specified date)."""
    from dashboard.database import get_daily_checklists
    session_user = request.session_user
    user_identifier = session_user.get('user_identifier')
    user_type = session_user.get('user_type')

    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    client_id = request.args.get('client_id', '')

    if user_type in ('super_admin', 'bef_admin'):
        checklists = get_daily_checklists(date)
    else:
        checklists = get_daily_checklists(date, user_identifier)

    # Filter by client_id if requested
    if client_id:
        checklists = [c for c in checklists if c.get('client_id', '') == client_id]

    return jsonify({'status': 'success', 'date': date, 'checklists': checklists})


@app.route('/api/admin/summary_signoff', methods=['POST'])
@require_role('admin', 'super_admin', 'bef_admin', 'kwok_admin')
def api_admin_summary_signoff():
    """Admin sign-off: confirm trader summary reviewed + sent to client (persisted like trader tracking)."""
    from dashboard.database import save_daily_checklist, get_daily_checklists
    session_user = request.session_user
    user_type = session_user.get('user_type')
    session_id = (session_user.get('user_identifier') or '').strip()

    data = request.get_json(silent=True) or {}
    client_id = (data.get('client_id') or '').strip()
    admin_name = (data.get('admin') or '').strip()
    checked = bool(data.get('checked', False))
    date = (data.get('date') or '').strip()

    if not client_id:
        return jsonify({'status': 'error', 'message': 'client_id required'}), 400

    # Admin users can only sign off as themselves.
    # Super admin / BEF / kwok can sign off on behalf of a specific admin dashboard.
    if user_type == 'admin':
        effective_admin = session_id
    else:
        effective_admin = admin_name
    if not effective_admin:
        return jsonify({'status': 'error', 'message': 'Admin name required'}), 400
    if not date:
        date = datetime.now().strftime('%Y-%m-%d')
    else:
        # Defensive: if invalid format, fall back to server date
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except Exception:
            date = datetime.now().strftime('%Y-%m-%d')

    # Once an admin signs off "checked", keep it locked and read-only (cannot be unticked).
    already_signed = False
    try:
        existing = get_daily_checklists(date, effective_admin) or []
        for row in existing:
            if row.get('checklist_type') != 'admin_daily_summary':
                continue
            if (row.get('client_id') or '').strip() != client_id:
                continue
            items0 = row.get('items') or []
            if isinstance(items0, list):
                for it in items0:
                    if isinstance(it, dict) and it.get('id') == 'sent_to_client' and bool(it.get('checked')):
                        already_signed = True
                        break
            if already_signed:
                break
    except Exception:
        already_signed = False

    effective_checked = True if already_signed else checked
    items = [{
        'id': 'sent_to_client',
        'title': 'Sent summary to client (approved)',
        'checked': bool(effective_checked),
        'status': 'ok' if effective_checked else 'pending',
        'notes': ''
    }]

    # Persist under the effective admin identity so the tracker reads it back correctly.
    save_daily_checklist(date, effective_admin, 'admin', 'admin_daily_summary', items,
                         get_remote_address(), client_id=client_id)

    try:
        log_action('ADMIN_SUMMARY_SIGNOFF', 'admin', effective_admin, get_remote_address(),
                   f'{("checked" if checked else "unchecked")} {client_id}')
    except Exception:
        pass

    return jsonify({'status': 'success', 'checked': bool(effective_checked), 'locked': bool(already_signed or effective_checked)})

@app.route('/api/quality/scorecard')
@require_role('super_admin', 'bef_admin')
def api_weekly_scorecard():
    """Generate weekly scorecard aggregating quality scan data per trader."""
    from dashboard.database import get_weekly_scan_results, get_daily_checklists
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    days = int(request.args.get('days', 7))
    results = get_weekly_scan_results(end_date, days)
    if not results:
        return jsonify({'status': 'success', 'scorecard': {}, 'message': 'No scan data for this period.'})

    # Per-trader aggregates: health / issue counts exclude payout QA (admin-owned); full issues stay in DB.
    for r in results:
        r['issues'] = [i for i in r.get('issues', []) if i.get('check') != 'Scan error']
        r['total_issues'], r['health_score'] = _trader_ranking_health_metrics(r.get('issues'))

    start_date = (datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=days - 1)).strftime('%Y-%m-%d')

    # Aggregate by trader
    traders = {}
    scan_dates = set()
    for r in results:
        t = r.get('trader', 'Unknown')
        sd = r['scan_date']
        scan_dates.add(sd)
        if t not in traders:
            traders[t] = {'clients': set(), 'daily': {}, 'total_issues': 0, 'total_health': 0, 'scan_count': 0}
        traders[t]['clients'].add(r['client_id'])
        traders[t]['total_issues'] += r['total_issues']
        traders[t]['total_health'] += r['health_score']
        traders[t]['scan_count'] += 1
        if sd not in traders[t]['daily']:
            traders[t]['daily'][sd] = {'issues': 0, 'health_sum': 0, 'count': 0}
        traders[t]['daily'][sd]['issues'] += r['total_issues']
        traders[t]['daily'][sd]['health_sum'] += r['health_score']
        traders[t]['daily'][sd]['count'] += 1

    # Build scorecard
    scorecard = {}
    for t, data in traders.items():
        avg_health = round(data['total_health'] / data['scan_count'], 1) if data['scan_count'] else 0
        # Health trend: compare first half vs second half
        sorted_dates = sorted(data['daily'].keys())
        mid = len(sorted_dates) // 2
        first_half = sorted_dates[:mid] if mid > 0 else sorted_dates
        second_half = sorted_dates[mid:] if mid > 0 else sorted_dates
        fh_health = sum(data['daily'][d]['health_sum'] / data['daily'][d]['count'] for d in first_half) / len(first_half) if first_half else 0
        sh_health = sum(data['daily'][d]['health_sum'] / data['daily'][d]['count'] for d in second_half) / len(second_half) if second_half else 0
        trend = 'improving' if sh_health > fh_health + 2 else ('declining' if sh_health < fh_health - 2 else 'stable')

        daily_breakdown = {}
        for d in sorted_dates:
            dd = data['daily'][d]
            daily_breakdown[d] = {
                'issues': dd['issues'],
                'avg_health': round(dd['health_sum'] / dd['count'], 1),
                'clients_scanned': dd['count']
            }

        # Grade based on avg health
        grade = 'A' if avg_health >= 90 else 'B' if avg_health >= 75 else 'C' if avg_health >= 60 else 'D' if avg_health >= 40 else 'F'

        scorecard[t] = {
            'total_clients': len(data['clients']),
            'total_issues': data['total_issues'],
            'avg_health': avg_health,
            'grade': grade,
            'trend': trend,
            'scans_in_period': len(sorted_dates),
            'daily': daily_breakdown
        }

    # Checklist completion for the period
    checklist_summary = {}
    current = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    while current <= end_dt:
        d = current.strftime('%Y-%m-%d')
        cls = get_daily_checklists(d)
        for cl in cls:
            uid = cl['user_identifier']
            if uid not in checklist_summary:
                checklist_summary[uid] = {'completed': 0, 'total_days': 0}
            checklist_summary[uid]['completed'] += 1
        current += timedelta(days=1)
    for uid in checklist_summary:
        checklist_summary[uid]['total_days'] = days

    return jsonify({
        'status': 'success',
        'period': {'start': start_date, 'end': end_date, 'days': days},
        'scan_dates': sorted(scan_dates),
        'scorecard': scorecard,
        'checklist_completion': checklist_summary
    })

@app.route('/api/quality/daily_summary')
@require_role('super_admin', 'bef_admin')
def api_daily_summary():
    """Generate a text summary of today's dashboard state for Discord/team sharing."""
    from dashboard.database import get_quality_scan_results, get_daily_checklists
    from config.hierarchy import get_all_clients, get_client_profile
    from config.hierarchy import SYSTEM_HIERARCHY

    # UTC date — server runs UTC; midnight UTC = 3 AM Kenyan, so the day
    # flips after the automated 2:05 AM Kenyan Slack send.
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    scan_results = get_quality_scan_results(date)
    checklists = get_daily_checklists(date)

    # Apply Daily Summary Tracker exclusions to the generated report as well
    # (so preview matches what the Slack bot posts).
    try:
        from dashboard.database import get_setting
        import json as _json_ex
        excluded_traders = set(_json_ex.loads(get_setting('summary_tracker_excluded_traders') or '[]'))
        excluded_clients = set(_json_ex.loads(get_setting('summary_tracker_excluded_clients') or '[]'))
    except Exception:
        excluded_traders = set()
        excluded_clients = set()

    # Leaderboard / portfolio health: exclude payout QA from scores; keep full (non–scan-error) issues for top-issues + downtime.
    for r in scan_results:
        r['issues'] = [i for i in r.get('issues', []) if i.get('check') != 'Scan error']
        r['total_issues'], r['health_score'] = _trader_ranking_health_metrics(r.get('issues'))

    all_clients = get_all_clients()
    # Filter portfolio list to excluded traders/clients for the report header.
    filtered_clients = []
    for client_name in all_clients:
        if client_name in excluded_clients:
            continue
        prof = get_client_profile(client_name) or {}
        trader = (prof.get('trader') or '') or 'Unassigned'
        if trader in excluded_traders:
            continue
        filtered_clients.append(client_name)
    total_clients = len(filtered_clients)

    # Filter scan_results so top issues + leaderboard align with exclusions
    if excluded_traders or excluded_clients:
        scan_results = [
            r for r in (scan_results or [])
            if (r.get('client_id') not in excluded_clients)
            and ((r.get('trader') or 'Unassigned') not in excluded_traders)
        ]

    # Count active vs issues from scan
    clients_healthy = sum(1 for r in scan_results if r['health_score'] >= 90)
    clients_warning = sum(1 for r in scan_results if 70 <= r['health_score'] < 90)
    clients_critical = sum(1 for r in scan_results if r['health_score'] < 70)
    total_issues = sum(r['total_issues'] for r in scan_results)
    avg_health = round(sum(r['health_score'] for r in scan_results) / len(scan_results), 1) if scan_results else 0

    # Top issues by frequency
    issue_counts = {}
    for r in scan_results:
        for iss in r['issues']:
            key = iss['check']
            issue_counts[key] = issue_counts.get(key, 0) + 1
    top_issues = sorted(issue_counts.items(), key=lambda x: -x[1])[:5]

    # Trader breakdown
    trader_stats = {}
    for r in scan_results:
        t = r.get('trader', 'Unknown')
        if t not in trader_stats:
            trader_stats[t] = {'clients': 0, 'issues': 0, 'health_sum': 0}
        trader_stats[t]['clients'] += 1
        trader_stats[t]['issues'] += r['total_issues']
        trader_stats[t]['health_sum'] += r['health_score']

    # Checklist status
    checklist_count = len(checklists)

    # Build the text summary
    weekday = datetime.strptime(date, '%Y-%m-%d').strftime('%A')
    lines = []
    lines.append(f"📊 **Daily Quality Summary — {weekday}, {date}**")
    lines.append("")
    lines.append(f"🏢 **Portfolio:** {total_clients} total clients")
    if scan_results:
        lines.append(f"💚 Healthy (90%+): {clients_healthy}  |  🟡 Warning: {clients_warning}  |  🔴 Critical: {clients_critical}")
        lines.append(f"📈 Avg Health Score: **{avg_health}%**  |  Total Issues: **{total_issues}**")
    else:
        lines.append("⚠️ No quality scan run today yet.")
    lines.append("")

    if top_issues:
        lines.append("🔍 **Top Issues:**")
        for check, count in top_issues:
            lines.append(f"  • {check}: {count} occurrences")
        lines.append("")

    # Collect downtime data (will be rendered at the bottom)
    downtime_clients = []
    for r in scan_results:
        for iss in r['issues']:
            if iss['check'] == 'Downtime detected':
                downtime_clients.append((r.get('trader', 'Unknown'), r['client_id'], iss['detail']))

    if trader_stats:
        from dashboard.database import get_trader_issue_resolution_minutes
        # Gamified Trader Health Leaderboard — fastest issue clearance first
        ranked = sorted(
            trader_stats.items(),
            key=lambda it: _trader_leaderboard_sort_key(
                it[0], it[1], get_trader_issue_resolution_minutes(date, it[0]),
            ),
        )
        lines.append("🏆 **TRADER HEALTH LEADERBOARD**")
        lines.append("_Green bar = average client health for that trader._")
        lines.append("")
        total_traders = len(ranked)
        for rank, (t, s) in enumerate(ranked, 1):
            clear_mins = get_trader_issue_resolution_minutes(date, t)
            if rank == 1:
                medal = '🥇'
            elif rank == 2:
                medal = '🥈'
            elif rank == 3:
                medal = '🥉'
            else:
                medal = f'`#{rank}`'
            line1, line2 = _trader_leaderboard_entry_lines(t, clear_mins, s, medal)
            lines.append(line1)
            lines.append(line2)
        lines.append("")

    lines.append(f"📋 Checklists submitted today: **{checklist_count}**")
    lines.append("")

    # ── Daily Summary Submission Tracker ──
    try:
        from dashboard.database import get_summary_status_for_date, get_setting, get_client_data
        from config.hierarchy import get_client_profile as _gcp
        from datetime import timezone, timedelta as _td
        import json as _json_mod

        _kenyan_tz = timezone(_td(hours=3))
        submissions = get_summary_status_for_date(date)
        # Convert timestamps to Kenyan time
        for s in submissions:
            ts = s.get('submitted_at', '')
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    s['submitted_at'] = dt.astimezone(_kenyan_tz).isoformat()
                except Exception:
                    pass

        sent_map = {s['client_id']: s for s in submissions}
        excluded_traders = set(_json_mod.loads(get_setting('summary_tracker_excluded_traders') or '[]'))
        excluded_clients = set(_json_mod.loads(get_setting('summary_tracker_excluded_clients') or '[]'))

        # Build per-trader summary submission data
        tracker_traders = {}  # trader -> {sent: [{client_id, time}], total: int}
        tracked_total = 0
        for client_name in all_clients:
            profile = _gcp(client_name)
            trader = (profile.get('trader', '') if profile else '') or 'Unassigned'
            if trader in excluded_traders or client_name in excluded_clients:
                continue
            try:
                cdata = get_client_data(client_name)
                if cdata and isinstance(cdata.get('identity'), dict):
                    if cdata['identity'].get('active_status') == 'inactive':
                        continue
            except Exception:
                pass
            tracked_total += 1
            if trader not in tracker_traders:
                tracker_traders[trader] = {'sent': [], 'not_sent': [], 'total': 0}
            tracker_traders[trader]['total'] += 1
            if client_name in sent_map:
                ts = sent_map[client_name].get('submitted_at', '')
                tracker_traders[trader]['sent'].append(ts)
            else:
                tracker_traders[trader]['not_sent'].append(client_name)

        # Split: 100% complete → ranked; everyone else → incomplete
        tracker_complete = []
        tracker_incomplete = []
        for t, d in tracker_traders.items():
            sent_count = len(d['sent'])
            if sent_count == d['total']:
                minutes_list = []
                for ts in d['sent']:
                    try:
                        dt = datetime.fromisoformat(ts)
                        minutes_list.append(dt.hour * 60 + dt.minute)
                    except Exception:
                        pass
                avg_minutes = round(sum(minutes_list) / len(minutes_list)) if minutes_list else 1440
                avg_hh = avg_minutes // 60
                avg_mm = avg_minutes % 60
                avg_time_str = f"{avg_hh:02d}:{avg_mm:02d}"
                tracker_complete.append((t, sent_count, d['total'], avg_minutes, avg_time_str))
            else:
                tracker_incomplete.append((t, sent_count, d['total'], d['not_sent']))

        tracker_complete.sort(key=lambda x: x[3])
        tracker_incomplete.sort(key=lambda x: x[0])
        total_sent_summary = sum(x[1] for x in tracker_complete) + sum(x[1] for x in tracker_incomplete)

        lines.append("📬 **DAILY SUMMARY SUBMISSION BY MIDNIGHT (KENYAN TIME)**")
        from datetime import timezone as _tz2, timedelta as _td2
        _eat_now = datetime.now(_tz2(_td2(hours=3)))
        if _should_skip_daily_summary_tracking(_eat_now):
            lines.append(DAILY_SUMMARY_TRACKER_SKIP_MSG)
            lines.append("")
        else:
            pct = round(total_sent_summary / tracked_total * 100) if tracked_total else 0
            lines.append(f"✅ {total_sent_summary}/{tracked_total} sent ({pct}%)")
            lines.append("")
            if tracker_complete:
                lines.append("🏆 **Complete — ranked by earliest avg submission time:**")
                lines.append("_All your clients' summaries must be submitted to qualify. The earlier you submit, the higher you rank. 🥇 goes to the fastest!_")
                for rank, (t, sent, total, _avg_m, avg_t) in enumerate(tracker_complete, 1):
                    if rank == 1:
                        medal = '🥇'
                    elif rank == 2:
                        medal = '🥈'
                    elif rank == 3:
                        medal = '🥉'
                    else:
                        medal = f'`#{rank}`'
                    lines.append(f"{medal} **{t}** — {sent}/{total} ✅ · avg {avg_t}")
                lines.append("")
            if tracker_incomplete:
                lines.append("❌ **Incomplete — missing clients:**")
                for t, sent, total, missing in tracker_incomplete:
                    lines.append(f"⚠️ **{t}** — {sent}/{total} sent")
                    lines.append(f"   ⛔ {', '.join(missing)}")
                lines.append("")
            lines.append("👁️ _We track everything — every submission, every miss, every second._")
            lines.append("")
    except Exception as e:
        import traceback
        traceback.print_exc()

    # ── Admin Team Rankings (generated summary only; not sent by bot) ──
    try:
        admins_map = SYSTEM_HIERARCHY.get('admins', {}) if isinstance(SYSTEM_HIERARCHY, dict) else {}
        admin_names = sorted([a for a in admins_map.keys() if str(a).strip()])
        if admin_names:
            # Each admin is treated as its own team (so team count ~= admin count).
            # Use friendly placeholder team names for now.
            placeholder_team_names = [
                'Team Atlas', 'Team Orion', 'Team Pegasus', 'Team Phoenix',
                'Team Nova', 'Team Aurora', 'Team Titan', 'Team Comet',
            ]
            admin_to_team = {}
            for idx, a in enumerate(admin_names):
                admin_to_team[a] = (
                    placeholder_team_names[idx]
                    if idx < len(placeholder_team_names)
                    else f'Team {idx + 1}'
                )

            # Build per-admin roster + score using existing admin-tracker logic.
            admin_rows = {}
            for a in admin_names:
                payload = compute_admin_tracker_payload(a, date) or {}
                score = float(payload.get('health_score') or 0.0)

                roster = {}  # trader -> [clients]
                active_clients = []
                for client_id in all_clients:
                    prof = get_client_profile(client_id) or {}
                    if str(prof.get('admin') or '').strip().lower() != str(a or '').strip().lower():
                        continue
                    trader = (str(prof.get('trader') or '').strip() or 'Unassigned')
                    if client_id in excluded_clients or trader in excluded_traders:
                        continue
                    try:
                        from dashboard.database import get_client_data as _gcd
                        cdata = _gcd(client_id) or {}
                        if isinstance(cdata.get('identity'), dict) and str(cdata['identity'].get('active_status') or '').lower() == 'inactive':
                            continue
                    except Exception:
                        pass
                    active_clients.append(client_id)
                    roster.setdefault(trader, []).append(client_id)

                for t in roster:
                    roster[t].sort()
                admin_rows[a] = {'score': round(score, 1), 'clients': len(active_clients), 'roster': roster}

            ranked_teams = []
            for a in admin_names:
                ranked_teams.append((admin_to_team.get(a, a), a, admin_rows[a]['score']))
            ranked_teams.sort(key=lambda x: (-x[2], x[0].lower()))

            lines.append("🏅 **ADMIN TEAMS (internal preview — not posted by bot)**")
            lines.append("_Admins are grouped into teams for friendly competition. Team score is a weighted average of admin health scores (weighted by active client count)._")
            lines.append("")
            for rank, (team, admin, score) in enumerate(ranked_teams, 1):
                if rank == 1:
                    medal = '🥇'
                elif rank == 2:
                    medal = '🥈'
                elif rank == 3:
                    medal = '🥉'
                else:
                    medal = f'`#{rank}`'
                arow = admin_rows.get(admin) or {}
                team_clients = int(arow.get('clients') or 0)
                lines.append(f"{medal} **{team}** (Admin: **{admin}**) — **{score}%** · {team_clients} clients")
                # List clients grouped by trader; cap to keep messages readable.
                shown = 0
                cap = 20
                for trader, cids in sorted((arow.get('roster') or {}).items(), key=lambda it: it[0].lower()):
                    if shown >= cap:
                        break
                    take = cids[: max(0, cap - shown)]
                    shown += len(take)
                    suffix = f" (+{len(cids) - len(take)} more)" if len(take) < len(cids) else ""
                    lines.append(f"     - {trader}: {', '.join(take)}{suffix}")
                total_listed = sum(len(v) for v in (arow.get('roster') or {}).values())
                if total_listed > shown:
                    lines.append(f"     - … (+{total_listed - shown} more clients)")
                lines.append("")
    except Exception:
        # Never block summary generation if team aggregation fails.
        pass

    # ── Downtime Alert (bottom of message for maximum visibility) ──
    if downtime_clients:
        lines.append("🚨🚨🚨 **DOWNTIME ALERT — ZERO TOLERANCE** 🚨🚨🚨")
        lines.append(f"⚠️ **{len(downtime_clients)} account(s) have stale trading days. This means the account was NOT traded on those days.**")
        lines.append("")
        for trader, client, detail in sorted(downtime_clients):
            acct = ''
            if '[' in detail and ']' in detail:
                acct = detail.split('[')[1].split(']')[0]
            stale_part = detail.split('Stale day(s) found: ')[-1].split(' —')[0] if 'Stale day(s) found: ' in detail else detail
            acct_tag = f" · {acct}" if acct and acct != 'no acct#' else ''
            lines.append(f"  🔴 **{client}** ({trader}{acct_tag}) — {stale_part}")
        lines.append("")
        lines.append("‼️ **Downtime is unacceptable. Every trading day must be accounted for. Traders responsible for these accounts must explain immediately.**")
        lines.append("")
        lines.append("━" * 30)
        lines.append("")

    # Admin tracker in daily summary export — disabled until admins are briefed; set flag True to restore.
    _include_admin_tracker_in_daily_summary = False
    if _include_admin_tracker_in_daily_summary:
        lines.append("—")

        # ── Admin Tracker Summary (issues + sign-offs) ──
        try:
            admins_map = SYSTEM_HIERARCHY.get('admins', {}) if isinstance(SYSTEM_HIERARCHY, dict) else {}
            admin_names = sorted([a for a in admins_map.keys() if str(a).strip()])
            if admin_names:
                lines.append("")
                lines.append("🏢 **ADMIN TRACKER (issues + sign-offs)**")
                lines.append("_Based on admin-owned checks: fees, prop-firm max-out, downtime, and missing client sign-offs after trader submits._")
                lines.append("")

                admin_rows = []
                total_admin_issues = 0
                total_required_signoffs = 0
                total_signed_signoffs = 0

                for a in admin_names:
                    payload = compute_admin_tracker_payload(a, date) or {}
                    issues = payload.get('issues') or payload.get('admin_issues') or []
                    sign = payload.get('summary_signoff') or {}
                    required = int(sign.get('required_total') or 0)
                    signed = int(sign.get('signed_total') or 0)
                    pending = int(sign.get('pending_total') or 0)

                    total_admin_issues += len(issues)
                    total_required_signoffs += required
                    total_signed_signoffs += signed

                    admin_rows.append({
                        'admin': a,
                        'health': float(payload.get('health_score') or 0.0),
                        'clients': int(payload.get('total_clients') or 0),
                        'issues': len(issues),
                        'sign_required': required,
                        'sign_signed': signed,
                        'pending_signoffs': pending,
                        'pending_clients': (sign.get('pending_clients') or []),
                    })

                admin_rows.sort(key=lambda r: (r['health'], r['clients']), reverse=True)
                avg_admin_health = round(sum(r['health'] for r in admin_rows) / len(admin_rows), 1) if admin_rows else 0.0

                lines.append(f"🏢 **Admins tracked:** {len(admin_rows)}")
                lines.append(f"📈 Avg Admin Health Score: **{avg_admin_health}%**  |  Total Admin Issues: **{total_admin_issues}**")
                if total_required_signoffs:
                    pct = round((total_signed_signoffs / total_required_signoffs) * 100)
                    lines.append(f"✅ Admin sign-offs: **{total_signed_signoffs}/{total_required_signoffs}** ({pct}%)")
                else:
                    lines.append("✅ Admin sign-offs: **0/0** (no trader submissions yet)")
                lines.append("")

                lines.append("🏆 **ADMIN HEALTH LEADERBOARD**")
                lines.append("_Ranked by admin health score (highest first)._")
                lines.append("")
                for rank, r in enumerate(admin_rows, 1):
                    if rank == 1:
                        medal = '🥇'
                    elif rank == 2:
                        medal = '🥈'
                    elif rank == 3:
                        medal = '🥉'
                    else:
                        medal = f'`#{rank}`'
                    bar_filled = round(r['health'] / 10)
                    bar_empty = 10 - bar_filled
                    bar = '🟩' * bar_filled + '⬛' * bar_empty
                    sign_extra = ""
                    if int(r.get('sign_required') or 0) > 0:
                        sign_extra = f" · sign-offs {int(r.get('sign_signed') or 0)}/{int(r.get('sign_required') or 0)}"
                    extra = f" · {r['pending_signoffs']} pending sign-offs" if r['pending_signoffs'] else ""
                    lines.append(f"{medal} **{r['admin']}**")
                    lines.append(f"   {bar} **{r['health']}%** · {r['clients']} clients · {r['issues']} issues{sign_extra}{extra}")

                # Admin completion leaderboard (only admins who signed off ALL required clients)
                try:
                    from datetime import timezone as _tz_admin, timedelta as _td_admin
                    _kenyan_tz_admin = _tz_admin(_td_admin(hours=3))
                    admin_complete = []
                    for r in admin_rows:
                        req = int(r.get('sign_required') or 0)
                        sgn = int(r.get('sign_signed') or 0)
                        if req <= 0 or sgn != req:
                            continue
                        # Build client_id -> submitted_at for checked sign-offs
                        ts_by_client = {}
                        try:
                            cls = get_daily_checklists(date, r.get('admin')) or []
                            for row in cls:
                                if row.get('checklist_type') != 'admin_daily_summary':
                                    continue
                                cid = (row.get('client_id') or '').strip()
                                if not cid:
                                    continue
                                items = row.get('items') or []
                                ok = False
                                if isinstance(items, list):
                                    for it in items:
                                        if isinstance(it, dict) and it.get('id') == 'sent_to_client' and bool(it.get('checked')):
                                            ok = True
                                            break
                                if not ok:
                                    continue
                                ts_by_client[cid] = row.get('submitted_at') or ''
                        except Exception:
                            ts_by_client = {}

                        minutes_list = []
                        for cid, ts in ts_by_client.items():
                            if not ts:
                                continue
                            try:
                                dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
                                if dt.tzinfo is None:
                                    dt = dt.replace(tzinfo=_tz_admin.utc)
                                dt = dt.astimezone(_kenyan_tz_admin)
                                minutes_list.append(dt.hour * 60 + dt.minute)
                            except Exception:
                                pass
                        avg_minutes = round(sum(minutes_list) / len(minutes_list)) if minutes_list else 1440
                        avg_hh = avg_minutes // 60
                        avg_mm = avg_minutes % 60
                        avg_time_str = f"{avg_hh:02d}:{avg_mm:02d}"
                        admin_complete.append((r.get('admin') or '', sgn, req, avg_minutes, avg_time_str))

                    admin_complete.sort(key=lambda x: x[3])
                    if admin_complete:
                        lines.append("")
                        lines.append("🏆 **Complete — ranked by earliest avg sign-off time:**")
                        lines.append("_All required client summaries must be signed off to qualify. The earlier you finish, the higher you rank. 🥇 goes to the fastest!_")
                        for rank, (a, sgn, req, _avg_m, avg_t) in enumerate(admin_complete, 1):
                            if rank == 1:
                                medal = '🥇'
                            elif rank == 2:
                                medal = '🥈'
                            elif rank == 3:
                                medal = '🥉'
                            else:
                                medal = f'`#{rank}`'
                            lines.append(f"{medal} **{a}** — {sgn}/{req} ✅ · avg {avg_t}")
                except Exception:
                    pass

                incomplete = [r for r in admin_rows if r['pending_signoffs'] > 0]
                if incomplete:
                    lines.append("")
                    lines.append("📬 **ADMIN DAILY SUMMARY SIGN-OFF (after trader submits)**")
                    lines.append("❌ **Incomplete — pending client sign-offs:**")
                    for r in sorted(incomplete, key=lambda x: (-x['pending_signoffs'], x['admin'])):
                        req = int(r.get('sign_required') or 0)
                        sgn = int(r.get('sign_signed') or 0)
                        badge = f"{sgn}/{req}" if req else "0/0"
                        lines.append(f"⚠️ **{r['admin']}** — {badge} · {r['pending_signoffs']} pending")
                        missing = r.get('pending_clients') or []
                        if len(missing) > 25:
                            shown = ", ".join(missing[:25]) + f", +{len(missing) - 25} more"
                        else:
                            shown = ", ".join(missing)
                        lines.append(f"   ⛔ {shown}")
                    lines.append("")
        except Exception:
            import traceback
            traceback.print_exc()

    summary_text = "\n".join(lines)

    fmt = request.args.get('format', 'json')
    if fmt == 'text':
        return summary_text, 200, {'Content-Type': 'text/plain; charset=utf-8'}

    return jsonify({
        'status': 'success',
        'date': date,
        'summary': summary_text,
        'stats': {
            'total_clients': total_clients,
            'scanned': len(scan_results),
            'healthy': clients_healthy,
            'warning': clients_warning,
            'critical': clients_critical,
            'total_issues': total_issues,
            'avg_health': avg_health,
            'checklists_submitted': checklist_count
        }
    })


@app.route('/api/settings/slack_webhook', methods=['GET'])
@require_role('super_admin')
def api_get_slack_webhook():
    """Get the current Slack webhook URL (masked). Super admin only."""
    from dashboard.database import get_setting
    url = get_setting('slack_webhook_url')
    if url:
        # Mask the URL for display — show first 40 chars + last 6
        masked = url[:40] + '...' + url[-6:] if len(url) > 50 else url
        return jsonify({'status': 'success', 'configured': True, 'masked_url': masked})
    return jsonify({'status': 'success', 'configured': False, 'masked_url': ''})


@app.route('/api/settings/slack_webhook', methods=['POST'])
@require_role('super_admin')
def api_set_slack_webhook():
    """Set the Slack webhook URL. Super admin only."""
    from dashboard.database import set_setting
    data = request.get_json(force=True)
    url = (data.get('url') or '').strip()
    user = request.session_user.get('user_identifier', '')

    if url and not url.startswith('https://hooks.slack.com/'):
        return jsonify({'status': 'error', 'message': 'Invalid Slack webhook URL. Must start with https://hooks.slack.com/'}), 400

    set_setting('slack_webhook_url', url, updated_by=user)
    action = 'configured' if url else 'removed'
    log_action('SLACK_WEBHOOK', 'super_admin', user, get_remote_address(), f'Slack webhook {action}')
    return jsonify({'status': 'success', 'message': f'Slack webhook {action} successfully.'})


@app.route('/api/quality/send_slack', methods=['POST'])
@require_role('super_admin')
def api_send_slack_summary():
    """Manually post the daily quality summary to Slack. Super admin only.
    Accepts optional JSON body: { "test_webhook": "https://hooks.slack.com/..." }
    to override the target (e.g. send to a DM or test channel instead of main).
    """
    from dashboard.scheduler import send_slack_message, send_slack_to_webhook, _build_daily_summary_text, _get_slack_webhook_url

    data = request.get_json(silent=True) or {}
    test_webhook = (data.get('test_webhook') or '').strip()

    # Validate test webhook if provided
    if test_webhook and not test_webhook.startswith('https://hooks.slack.com/'):
        return jsonify({'status': 'error', 'message': 'Invalid webhook URL — must start with https://hooks.slack.com/'}), 400

    if not test_webhook and not _get_slack_webhook_url():
        return jsonify({'status': 'error', 'message': 'Slack webhook not configured. Paste your webhook URL in the Settings section below.'}), 400
    try:
        text = _build_daily_summary_text()
        if test_webhook:
            text = "🧪 *[TEST MODE — DM only]*\n\n" + text
            ok = send_slack_to_webhook(test_webhook, text)
        else:
            ok = send_slack_message(text)
        if ok:
            dest = 'test webhook (DM)' if test_webhook else 'main channel'
            log_action('SLACK_SUMMARY', 'super_admin', request.session_user.get('user_identifier'),
                       get_remote_address(), f'Manual Slack summary posted to {dest}')
            return jsonify({'status': 'success', 'message': f'Summary posted to {dest}.'})
        else:
            return jsonify({'status': 'error', 'message': 'Slack post failed — check webhook URL and logs.'}), 502
    except Exception as e:
        logging.error(f"Manual Slack post error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Daily Summaries Slack ─────────────────────────────────────────

@app.route('/api/settings/slack_daily_webhook', methods=['GET'])
@require_role('super_admin')
def api_get_slack_daily_webhook():
    """Get the Daily Summaries Slack webhook URL (masked)."""
    from dashboard.database import get_setting
    url = get_setting('slack_daily_summaries_webhook_url')
    if url:
        masked = url[:40] + '...' + url[-6:] if len(url) > 50 else url
        return jsonify({'status': 'success', 'configured': True, 'masked_url': masked})
    return jsonify({'status': 'success', 'configured': False, 'masked_url': ''})


@app.route('/api/settings/slack_daily_webhook', methods=['POST'])
@require_role('super_admin')
def api_set_slack_daily_webhook():
    """Set the Daily Summaries Slack webhook URL. Super admin only."""
    from dashboard.database import set_setting
    data = request.get_json(force=True)
    url = (data.get('url') or '').strip()
    user = request.session_user.get('user_identifier', '')
    if url and not url.startswith('https://hooks.slack.com/'):
        return jsonify({'status': 'error', 'message': 'Invalid Slack webhook URL.'}), 400
    set_setting('slack_daily_summaries_webhook_url', url, updated_by=user)
    action = 'configured' if url else 'removed'
    log_action('SLACK_DAILY_WEBHOOK', 'super_admin', user, get_remote_address(), f'Daily summaries Slack webhook {action}')
    return jsonify({'status': 'success', 'message': f'Daily summaries Slack webhook {action}.'})


@app.route('/api/checklist/send_slack', methods=['POST'])
@require_session
def api_send_checklist_slack():
    """Send a daily summary to Slack."""
    from dashboard.database import get_daily_checklists, get_setting, save_daily_checklist
    from dashboard.scheduler import send_slack_to_webhook
    session_user = request.session_user
    user_type = session_user.get('user_type')
    user_identifier = session_user.get('user_identifier', '')

    if user_type == 'client':
        return jsonify({'status': 'error', 'message': 'Not authorized'}), 403

    data = request.get_json(force=True)
    summary_text = (data.get('text') or '').strip()
    client_id = (data.get('client_id') or '').strip()

    if not summary_text:
        return jsonify({'status': 'error', 'message': 'No summary text provided.'}), 400

    webhook_url = get_setting('slack_daily_summaries_webhook_url')
    if not webhook_url:
        return jsonify({'status': 'error', 'message': 'No Slack webhook configured. Ask a super admin to set one up in the Quality Dashboard.'}), 400

    try:
        ok = send_slack_to_webhook(webhook_url, summary_text)
        if ok:
            if client_id:
                today = datetime.now().strftime('%Y-%m-%d')
                # Do not replace a full daily_summary payload: the quality scan reads
                # checklist items (e.g. payout_requests). Slack used to overwrite the row
                # with only slack_sent, which wiped section 4 and broke payout-eligible QA.
                slack_marker = {
                    'id': 'slack_sent',
                    'title': 'Sent to Slack',
                    'status': 'ok',
                    'notes': '',
                }
                items_to_save = [slack_marker]
                try:
                    for row in get_daily_checklists(today, user_identifier) or []:
                        if row.get('checklist_type') != 'daily_summary':
                            continue
                        if (row.get('client_id') or '').strip() != client_id:
                            continue
                        prev = row.get('items') or []
                        if not isinstance(prev, list) or not prev:
                            break
                        base = [
                            it for it in prev
                            if not (isinstance(it, dict) and it.get('id') == 'slack_sent')
                        ]
                        if any(isinstance(it, dict) and it.get('id') for it in base):
                            items_to_save = base + [slack_marker]
                        break
                except Exception:
                    pass
                save_daily_checklist(
                    today,
                    user_identifier,
                    user_type,
                    'daily_summary',
                    items_to_save,
                    get_remote_address(),
                    client_id=client_id,
                )
            log_action('SLACK_DAILY_SUMMARY', user_type, user_identifier,
                       get_remote_address(), f'Daily summary sent to Slack for {client_id}')
            return jsonify({'status': 'success', 'message': 'Summary sent to Slack!'})
        else:
            return jsonify({'status': 'error', 'message': 'Slack post failed — check webhook URL.'}), 502
    except Exception as e:
        logging.error(f"Daily summary Slack post error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/client/import_csv', methods=['POST'])
@require_role('super_admin')
def import_client_csv():
    """Import CSV data back into a client's evaluations. Super admin only."""
    import csv
    import io
    from dashboard.database import get_client_data, save_client_data_with_history

    session_user = request.session_user
    user_identifier = session_user.get('user_identifier')

    client_id = request.form.get('client_id')
    if not client_id:
        return jsonify({"status": "error", "message": "client_id required"}), 400

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({"status": "error", "message": "CSV file required"}), 400

    if not file.filename.lower().endswith('.csv'):
        return jsonify({"status": "error", "message": "File must be a .csv"}), 400

    # Read and parse CSV
    try:
        content = file.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))
        rows = []
        for row in reader:
            # Stop at statistics separator
            first_val = list(row.values())[0] if row else ''
            if first_val and first_val.strip().startswith('--- '):
                break
            # Skip empty rows
            if all(not v.strip() for v in row.values()):
                continue
            rows.append(dict(row))
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to parse CSV: {str(e)}"}), 400

    if not rows:
        return jsonify({"status": "error", "message": "CSV contains no data rows"}), 400

    # Load existing data
    existing_data = get_client_data(client_id)
    if not existing_data:
        return jsonify({"status": "error", "message": f"No existing data for client {client_id}"}), 404

    existing_evals = existing_data.get('evaluations', [])

    # Build index of existing evaluations by Account # for matching
    existing_by_account = {}
    for idx, ev in enumerate(existing_evals):
        acct = (ev.get('Account #') or '').strip()
        if acct:
            existing_by_account[acct] = idx

    # Merge: update matched rows, append new ones
    updated_count = 0
    added_count = 0
    merged_evals = list(existing_evals)  # copy

    for csv_row in rows:
        acct = (csv_row.get('Account #') or '').strip()
        # Clean out internal keys
        clean_row = {k: v for k, v in csv_row.items() if not k.startswith('_')}

        if acct and acct in existing_by_account:
            # Update existing evaluation
            idx = existing_by_account[acct]
            for key, val in clean_row.items():
                if val.strip():  # only overwrite non-empty values
                    merged_evals[idx][key] = val
            updated_count += 1
        else:
            # New row - append
            merged_evals.append(clean_row)
            added_count += 1

    # Save with history
    existing_data['evaluations'] = merged_evals
    save_client_data_with_history(
        client_id, existing_data,
        changed_by=user_identifier,
        change_source='csv_import',
        change_description=f"CSV import: {updated_count} updated, {added_count} added"
    )

    log_action('CSV_IMPORT', 'super_admin', user_identifier, get_remote_address(),
               f"Imported CSV for {client_id}: {updated_count} updated, {added_count} added from {len(rows)} rows")

    return jsonify({
        'status': 'success',
        'message': f'Import complete: {updated_count} rows updated, {added_count} rows added',
        'updated': updated_count,
        'added': added_count,
        'total_rows': len(merged_evals)
    })

@app.route('/api/client/import_csv_companion', methods=['POST'])
@limiter.limit("10 per minute")
def import_csv_companion():
    """Import CSV data via companion app. Auth via email (same as sheet migration)."""
    import csv
    import io
    from dashboard.database import get_client_data, save_client_data_with_history

    email = (request.form.get('email') or '').strip().lower()
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400

    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered in the system"}), 404

    client_id = client_info['client']

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({"status": "error", "message": "CSV file required"}), 400

    if not file.filename.lower().endswith('.csv'):
        return jsonify({"status": "error", "message": "File must be a .csv"}), 400

    try:
        content = file.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))
        rows = []
        for row in reader:
            first_val = list(row.values())[0] if row else ''
            if first_val and first_val.strip().startswith('--- '):
                break
            if all(not v.strip() for v in row.values()):
                continue
            rows.append(dict(row))
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to parse CSV: {str(e)}"}), 400

    if not rows:
        return jsonify({"status": "error", "message": "CSV contains no data rows"}), 400

    existing_data = get_client_data(client_id)
    if not existing_data:
        return jsonify({"status": "error", "message": f"No existing data for client {client_id}"}), 404

    old_count = len(existing_data.get('evaluations', []))

    # Full replacement: CSV becomes the new evaluations list
    new_evals = []
    for csv_row in rows:
        clean_row = {k: v for k, v in csv_row.items() if not k.startswith('_')}
        new_evals.append(clean_row)

    existing_data['evaluations'] = new_evals
    save_client_data_with_history(
        client_id, existing_data,
        changed_by=email,
        change_source='csv_import',
        change_description=f"CSV import via companion: replaced {old_count} evals with {len(new_evals)} from CSV"
    )

    log_action('CSV_IMPORT', 'companion', email, get_remote_address(),
               f"Imported CSV for {client_id}: replaced {old_count} with {len(new_evals)} evals")

    return jsonify({
        'status': 'success',
        'message': f'Import complete: {len(new_evals)} rows imported (replaced {old_count})',
        'imported': len(new_evals),
        'previous': old_count,
        'total_rows': len(new_evals)
    })

@app.route('/api/notes', methods=['POST'])
@require_session
def update_note():
    """Update or Delete a cell note."""
    try:
        session_user = request.session_user
        user_type = session_user.get('user_type')
        user_identifier = session_user.get('user_identifier')
        
        data = request.json
        client_id = data.get('client_id')
        row_index = data.get('row_index')
        column_key = data.get('column_key')
        content = data.get('content')

        if not client_id or row_index is None or not column_key:
            return jsonify({"status": "error", "message": "Missing required fields"}), 400

        # Ensure user has access
        if not can_access_client(user_type, user_identifier, client_id):
            log_action('ACCESS_DENIED', user_type, user_identifier, get_remote_address(), f"Note access denied: {client_id}", False)
            return jsonify({"status": "error", "message": "Access denied"}), 403

        if user_type in ('client', 'kwok_admin'):
            return jsonify({"status": "error", "message": "Read-only account"}), 403

        if content:
            save_client_note(client_id, row_index, column_key, content, user_identifier)
            action = 'UPDATE_NOTE'
        else:
            # Empty content means delete
            delete_client_note(client_id, row_index, column_key)
            action = 'DELETE_NOTE'
            
        log_action(action, user_type, user_identifier, get_remote_address(), f"Note on {client_id} row {row_index} col {column_key}", True)
        return jsonify({"status": "success"})
    except Exception as e:
        logging.error(f"Error updating note: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/notes/delete', methods=['POST'])
@require_session
def delete_note():
    data = request.json or {}
    client_id = data.get('client_id')
    row_index = data.get('row_index')
    column_key = data.get('column_key')

    session_user = request.session_user
    user_type = session_user.get('user_type')
    user_identifier = session_user.get('user_identifier')

    if not client_id or row_index is None or not column_key:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    if not can_access_client(user_type, user_identifier, client_id):
        return jsonify({"status": "error", "message": "Access denied"}), 403

    if user_type in ('client', 'kwok_admin'):
        return jsonify({"status": "error", "message": "Read-only account"}), 403

    if delete_client_note(client_id, row_index, column_key):
        log_action('DELETE_NOTE', user_type, user_identifier, get_remote_address(),
                   f"Note on {client_id} row {row_index} col {column_key}", True)
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Database error"}), 500

@app.route('/api/update_data', methods=['POST'])
@limiter.limit("60 per minute")
def update_data():
    """Update client data - supports both session and API key authentication."""
    try:
        data = request.json
        identity = data.get('identity', {})
        
        # Try session authentication first (for dashboard UI)
        session_token = request.cookies.get('session_token')
        api_key = request.headers.get('X-API-Key')
        
        if session_token:
            session_info = validate_session(session_token)
            if session_info:
                user_type = session_info.get('user_type')
                user_identifier = session_info.get('user_identifier')
                
                # Get client_id from request data
                client_id = identity.get('client') or data.get('client_id')
                
                if not client_id:
                    return jsonify({"status": "error", "message": "Client ID required"}), 400
                
                # Check if user can access this client's data
                if not can_access_client(user_type, user_identifier, client_id):
                    log_action('UPDATE_DENIED', user_type, user_identifier, get_remote_address(), 
                              f"Tried to update: {client_id}", False)
                    return jsonify({"status": "error", "message": "Access denied"}), 403

                if user_type == 'kwok_admin':
                    return jsonify({"status": "error", "message": "View-only account"}), 403
                
                # Get existing data to preserve fields not being updated
                existing_data = get_client_data(client_id) or {}
                
                # Get evaluations and normalize Account Size values
                evaluations = data.get("evaluations", existing_data.get("evaluations", []))

                evaluations = normalize_evaluations(evaluations)
                
                # Deep-merge evaluations: preserve push-sourced fields (Hedge Results, deals, etc.)
                # that the stale frontend may not have received yet.
                existing_evals = existing_data.get("evaluations", [])
                
                # --- SAFETY: Prevent stale frontend from wiping evaluations ---
                action_type = data.get('action_type', 'UPDATE')
                
                if action_type == 'CREATE':
                    # Evaluations-tab "Add Account" only — hedge/prop/VPS saves must
                    # use UPDATE so we never append a phantom evaluation row.
                    if len(evaluations) > len(existing_evals):
                        now_iso = datetime.utcnow().isoformat()
                        new_rows = evaluations[len(existing_evals):]
                        for _r in new_rows:
                            if isinstance(_r, dict) and '_row_added_at' not in _r:
                                _r['_row_added_at'] = now_iso
                        evaluations = normalize_evaluations(existing_evals) + new_rows
                    elif data.get('create_evaluation'):
                        evaluations = normalize_evaluations(existing_evals)
                        new_row = {
                            "Prop Firm": "My Funded Futures",
                            "Account Size": "$100,000",
                            "Date Purchased": "",
                            "Fee": "0"
                        }
                        new_row['_row_added_at'] = datetime.utcnow().isoformat()
                        evaluations.append(new_row)
                    else:
                        evaluations = normalize_evaluations(existing_evals)
                    existing_evals = existing_data.get("evaluations", [])
                elif action_type not in ('DELETE', 'ROLLBACK'):
                    # General safety check: block saves that would drop eval count
                    # by more than 50% (accidental wipe protection)
                    if (len(existing_evals) >= 10
                            and len(evaluations) < len(existing_evals) * 0.5):
                        log_action('WIPE_BLOCKED', user_type, user_identifier,
                                   get_remote_address(),
                                   f'{client_id}: incoming {len(evaluations)} evals vs '
                                   f'existing {len(existing_evals)} — blocked to prevent data loss',
                                   False)
                        return jsonify({
                            "status": "error",
                            "message": f"Safety check: your page has {len(evaluations)} evaluations "
                                       f"but the database has {len(existing_evals)}. "
                                       f"Please refresh the page and try again."
                        }), 409
                PUSH_SOURCED_KEYS = {
                    'Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
                    'Hedge Result 4', 'Hedge Result 5',
                    'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
                    'Hedge Result 4.1', 'Hedge Result 5.1',
                    'Hedge Result 6', 'Hedge Result 7',
                }
                # Include farming Hedge Day / Prop Day fields (push-sourced)
                for _i in range(1, 51):
                    PUSH_SOURCED_KEYS.add(f'Hedge Day {_i}')
                    PUSH_SOURCED_KEYS.add(f'Prop Day {_i}')
                # Payout/date fields that should only be overwritten by explicit user edits
                # (prevents a stale browser tab from reverting dashboard-entered payouts)
                PAYOUT_KEYS = {
                    'Payout 1', 'Date 1', 'Payout 2', 'Date 2', 'Payout 3', 'Date 3',
                    'Payout 4', 'Date 4', 'Payout 5', 'Date 5', 'Payout 6', 'Date 6',
                }
                PROTECTED_KEYS = PUSH_SOURCED_KEYS | PAYOUT_KEYS

                # Fields the user explicitly touched in this edit session
                # (sent by frontend so we can distinguish intentional clears from stale data)
                raw_changed = data.get('_changedFields', {})
                user_changed = {}  # { int(eval_index): set(field_names) }
                for idx_str, fields in raw_changed.items():
                    try:
                        user_changed[int(idx_str)] = set(fields) if isinstance(fields, list) else set()
                    except (ValueError, TypeError):
                        pass

                for idx in sorted(user_changed.keys()):
                    flds = user_changed.get(idx) or set()
                    if idx >= len(evaluations):
                        app.logger.warning(
                            "[HEDGE_SAVE] client=%s _changedFields row=%s out of range (len=%s)",
                            client_id, idx, len(evaluations),
                        )
                        continue
                    ev_pay = evaluations[idx]
                    if isinstance(ev_pay, dict):
                        for fk in sorted(flds):
                            if fk.startswith('Hedge Result') or fk.startswith('Hedge Day'):
                                app.logger.info(
                                    "[HEDGE_SAVE] incoming_payload client=%s row=%s %s=%r",
                                    client_id, idx, fk, ev_pay.get(fk),
                                )

                def _has_non_blank_value(v):
                    """Treat numeric 0 as a real value so protected fields are not blanked."""
                    if v is None:
                        return False
                    if isinstance(v, str):
                        return v.strip() not in ('', '-')
                    return True

                for i, ev in enumerate(evaluations):
                    explicitly_changed = user_changed.get(i, set())

                    if i < len(existing_evals):
                        existing_ev = existing_evals[i]
                        
                        # Preserve DB-only internal keys the frontend doesn't send
                        for k, v in existing_ev.items():
                            if k.startswith('_') and k not in ev:
                                ev[k] = v
                        
                        for key in PROTECTED_KEYS:
                            # If the user explicitly cleared this field, respect the clear
                            if key in explicitly_changed:
                                continue
                            existing_val = existing_ev.get(key)
                            incoming_val = ev.get(key)
                            # Keep the existing (push-sourced) value when the frontend sends empty/missing
                            if _has_non_blank_value(existing_val) and not _has_non_blank_value(incoming_val):
                                ev[key] = existing_val

                    # ── Track manual clears so MT5 push aggregator cannot resurrect them ──
                    # When the user explicitly blanks a push-sourced field, record it in
                    # `_cleared_fields`.  When they later type a real value back in,
                    # remove the entry so push writes resume.
                    cleared = set(ev.get('_cleared_fields') or [])
                    for key in explicitly_changed:
                        if key not in PUSH_SOURCED_KEYS:
                            continue
                        if _has_non_blank_value(ev.get(key)):
                            cleared.discard(key)   # user typed a value back → resume push writes
                        else:
                            cleared.add(key)       # user blanked the cell → freeze it
                    if cleared:
                        ev['_cleared_fields'] = sorted(cleared)
                    elif '_cleared_fields' in ev:
                        # remove empty list to keep payload lean
                        ev.pop('_cleared_fields', None)

                # Recalculate Hedge Net / Hedge Net.1 from current hedge results & statuses
                evaluations = recalculate_hedge_nets(evaluations)
                _dashboard_log_hedge_edit(client_id, user_changed, evaluations)

                # Recalculate statistics so they reflect latest evaluation changes
                from utils.data_processor import calculate_statistics
                existing_mt5 = existing_data.get('account') or data.get('account')
                existing_hr_stats = existing_data.get('statistics', {}).get('hedging_review', {})
                existing_hist = existing_hr_stats.get('historical_accounts')

                merged_statistics = calculate_statistics(
                    evaluations, mt5_account=existing_mt5,
                    historical_accounts=existing_hist
                )

                existing_hr_for_merge = existing_data.get('statistics', {}).get('hedging_review', {})
                merge_statistics_hedging_review_preserve_mt5(existing_hr_for_merge, merged_statistics)
                merged_hr = merged_statistics.get('hedging_review', {})
                app.logger.info(
                    "[HEDGE_SAVE] client=%s cashflow_hedge=%s cashflow_farm=%s sheet_hedge_total=%s actual_mt5=%s discrepancy=%s cf_net=%s",
                    client_id,
                    merged_statistics.get('cashflow_inprogress', {}).get('hedging_results'),
                    merged_statistics.get('cashflow_inprogress', {}).get('farming_results'),
                    merged_hr.get('sheet_hedging_results'),
                    merged_hr.get('actual_hedging_results'),
                    merged_hr.get('discrepancy'),
                    merged_statistics.get('cashflow_inprogress', {}).get('net_profit'),
                )

                client_data = {
                    "deals": _drop_balance_deals(data.get("deals", existing_data.get("deals", [])))[0],
                    "positions": data.get("positions", existing_data.get("positions", [])),
                    "account": data.get("account", existing_data.get("account", {})),
                    "hedge_accounts": data.get("hedge_accounts", existing_data.get("hedge_accounts", [])),
                    "prop_accounts": data.get("prop_accounts", existing_data.get("prop_accounts", [])),
                    "vps_accounts": data.get("vps_accounts", existing_data.get("vps_accounts", [])),
                    "payment_info": data.get("payment_info", existing_data.get("payment_info", [])),
                    "payment_address": data.get("payment_address", existing_data.get("payment_address", {})),
                    "mt5_credentials": data.get("mt5_credentials", existing_data.get("mt5_credentials", {})),
                    "firm_billing": existing_data.get("firm_billing", {}),
                    "evaluations": evaluations,
                    "statistics": merged_statistics,
                    "dropdown_options": data.get("dropdown_options", existing_data.get("dropdown_options", {})),
                    # Persist match log when updating from dashboard
                    "aggregated_by_comment": existing_data.get("aggregated_by_comment", []),
                    "comment_summary": existing_data.get("comment_summary", {}),
                    "identity": data.get("identity", existing_data.get("identity", {}))
                }
                
                # Ensure client ID is in identity
                if 'client' not in client_data['identity']:
                    client_data['identity']['client'] = client_id
                
                # Allow custom action/description from frontend
                action_type = data.get('action_type', 'UPDATE')
                description = data.get('change_description', f'Manual edit from dashboard by {user_type}')

                # Clients are view+edit only — block add/delete of evaluations
                if user_type == 'client' and action_type in ('CREATE', 'DELETE'):
                    return jsonify({"status": "error", "message": "Clients cannot add or delete evaluations"}), 403

                # Only super_admin can delete evaluations
                if action_type == 'DELETE' and user_type != 'super_admin':
                    log_action('DELETE_DENIED', user_type, user_identifier, get_remote_address(),
                               f'Attempted DELETE on {client_id} without super_admin role', False)
                    return jsonify({"status": "error", "message": "Only super admins can delete evaluations"}), 403

                # Save with history tracking
                success, version = save_client_data_with_history(
                    client_id,
                    client_data,
                    action=action_type,
                    changed_by=user_identifier,
                    changed_by_type=user_type,
                    ip_address=get_remote_address(),
                    change_source='dashboard_edit',
                    change_description=description
                )
                
                if success:
                    if _changed_fields_touch_hedge(user_changed):
                        try:
                            from dashboard.financial_overview import clear_financial_cache
                            clear_financial_cache()
                        except Exception:
                            pass
                    log_action('DATA_UPDATE', user_type, user_identifier, get_remote_address(), 
                              f"Client: {client_id} (v{version})")
                    payload = {
                        "status": "success",
                        "message": "Data updated",
                        "version": version,
                        "_version": version,
                        "statistics": merged_statistics,
                        "evaluations": evaluations,
                    }
                    saved_row = get_client_data(client_id)
                    if saved_row:
                        payload["last_updated"] = saved_row.get('last_updated')
                    return jsonify(payload)
                else:
                    return jsonify({"status": "error", "message": "Failed to save data"}), 500
        
        # Fall back to API key authentication
        if api_key:
            user_info = validate_api_key(api_key)
            if user_info:
                return update_data_with_api_key(data, identity, user_info)
            else:
                return jsonify({"status": "error", "message": "Invalid API key"}), 403
        
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    except Exception as e:
        print(f"Error in update_data: {e}")
        return jsonify({"status": "error", "message": f"Server error: {str(e)}"}), 500


def update_data_with_api_key(data, identity, user_info):
    """Handle update with API key authentication (for external API calls)."""
    # Use authenticated user info if no identity provided
    if not identity:
        identity = {
            'admin': user_info.get('admin'),
            'trader': user_info.get('trader'),
            'client': user_info.get('client')
        }
    
    admin_id = identity.get('admin', 'Admin1')
    trader_id = identity.get('trader', 'Trader1')
    client_id = identity.get('client', 'Client1')
    email = identity.get('email', '')
    
    # Get existing data to prevent overwriting evaluations with empty list
    existing_data = get_client_data(client_id) or {}
    
    # Smart merge for evaluations:
    # Only overwrite if incoming evaluations list is NOT empty
    incoming_evals = data.get("evaluations")
    if incoming_evals and len(incoming_evals) > 0:
        evaluations = incoming_evals
    else:
        # If incoming is empty or missing, preserve existing
        evaluations = existing_data.get("evaluations", [])
        
    evaluations = normalize_evaluations(evaluations)
    
    # Smart merge for statistics (preserve hedging_review if present in existing)
    incoming_stats = data.get("statistics", {})
    existing_stats = existing_data.get("statistics", {})
    
    # Start with existing stats, update with incoming
    # This preserves keys like 'hedging_review' that the trader app doesn't send
    statistics = existing_stats.copy()
    statistics.update(incoming_stats)
    
    # Always preserve hedging_review from DB — only /api/client/push and
    # /api/hedging_review are authoritative sources for this data.
    existing_hr = existing_stats.get('hedging_review')
    if existing_hr:
        statistics['hedging_review'] = existing_hr
    
    # Smart merge for dropdown_options (preserve if incoming is empty)
    incoming_options = data.get("dropdown_options", {})
    if not incoming_options:
        dropdown_options = existing_data.get("dropdown_options", {})
    else:
        dropdown_options = incoming_options

    # Merge account onto existing — never wipe MT5 totals when the API caller
    # omits the field or sends zeros. Same rationale as /api/client/push.
    incoming_acct = data.get("account") or {}
    existing_acct = existing_data.get("account") or {}
    merged_acct = dict(existing_acct)
    merged_acct.update(incoming_acct)
    for _preserve_key in ("total_deposits", "total_withdrawals"):
        if not incoming_acct.get(_preserve_key):
            merged_acct[_preserve_key] = existing_acct.get(_preserve_key, 0)

    # Prepare client data
    client_data = {
        "deals": _drop_balance_deals(data.get("deals", []))[0],
        "positions": data.get("positions", []),
        "account": merged_acct,
        "evaluations": evaluations,
        "statistics": statistics,
        "dropdown_options": dropdown_options,
        "aggregated_by_comment": existing_data.get("aggregated_by_comment", []),
        "comment_summary": existing_data.get("comment_summary", {}),
        "identity": identity
    }
    
    # Save to database WITH history tracking
    success, version = save_client_data_with_history(
        client_id,
        client_data,
        action='UPDATE',
        changed_by=email or trader_id,
        changed_by_type='api',
        ip_address=get_remote_address(),
        change_source='api_push',
        change_description='Update via API'
    )
    
    # Update Hierarchy
    add_admin(admin_id)
    add_trader(admin_id, trader_id)
    add_client(admin_id, trader_id, client_id)
    
    log_action('DATA_UPDATE', 'trader', trader_id, get_remote_address(), f"Client: {client_id} (v{version})")
    return jsonify({"status": "success", "message": "Data updated", "version": version})

# ============ API Key Management (Admin only) ============

@app.route('/api/admin/generate_key', methods=['POST'])
@require_admin_password
@limiter.limit("10 per hour")
def api_generate_key():
    """Generate a new API key for a trader."""
    trader_info = request.json.get('trader_info', {})
    admin = trader_info.get('admin')
    trader = trader_info.get('trader')
    client = trader_info.get('client', '')
    
    if not admin or not trader:
        return jsonify({"status": "error", "message": "Admin and trader required"}), 400
    
    # Generate hashed API key
    api_key = generate_api_key(admin, trader, client)
    
    if api_key:
        log_action('GENERATE_API_KEY', 'admin', trader, get_remote_address())
        return jsonify({
            "status": "success",
            "api_key": api_key,  # Only time the full key is visible
            "trader_info": {"admin": admin, "trader": trader, "client": client}
        })
    
    return jsonify({"status": "error", "message": "Failed to generate key"}), 500

@app.route('/api/admin/list_keys', methods=['GET'])
@require_admin_password
def api_list_keys():
    """List all API keys (showing only prefix)."""
    keys = list_api_keys()
    log_action('LIST_API_KEYS', 'admin', 'super_admin', get_remote_address())
    return jsonify({"status": "success", "keys": keys})

@app.route('/api/admin/revoke_key', methods=['POST'])
@require_admin_password
def api_revoke_key():
    """Revoke an API key."""
    key_prefix = request.json.get('key_prefix')
    
    if not key_prefix:
        return jsonify({"status": "error", "message": "Key prefix required"}), 400
    
    if revoke_api_key(key_prefix):
        log_action('REVOKE_API_KEY', 'admin', key_prefix, get_remote_address())
        return jsonify({"status": "success", "message": "API key revoked"})
    
    return jsonify({"status": "error", "message": "API key not found"}), 404

# ============ Audit Log (Admin only) ============

@app.route('/api/admin/audit_log', methods=['GET'])
@require_admin_password
def api_audit_log():
    """Get audit log entries."""
    limit = request.args.get('limit', 100, type=int)
    action_filter = request.args.get('action', None)
    
    logs = get_audit_log(limit, action_filter)
    return jsonify({"status": "success", "logs": logs})

# ============ Trader Push Endpoints ============

@app.route('/api/trader/push_account', methods=['POST'])
@require_api_key
@limiter.limit("30 per minute")
def push_account_data():
    """Endpoint for traders to push account information."""
    data = request.json
    client_id = data.get('client_id') or request.api_user.get('client', 'Client1')
    
    update_client_field(client_id, 'account', data.get('account', {}))
    log_action('PUSH_ACCOUNT', 'trader', request.api_user.get('trader'), get_remote_address(), f"Client: {client_id}")
    
    return jsonify({"status": "success", "message": "Account data updated"})

@app.route('/api/trader/push_positions', methods=['POST'])
@require_api_key
@limiter.limit("30 per minute")
def push_positions():
    """Endpoint for traders to push current positions."""
    data = request.json
    client_id = data.get('client_id') or request.api_user.get('client', 'Client1')
    
    update_client_field(client_id, 'positions', data.get('positions', []))
    log_action('PUSH_POSITIONS', 'trader', request.api_user.get('trader'), get_remote_address(), f"Client: {client_id}")
    
    return jsonify({"status": "success", "message": "Positions updated"})

@app.route('/api/trader/push_deals', methods=['POST'])
@require_api_key
@limiter.limit("30 per minute")
def push_deals():
    """Endpoint for traders to push deal history."""
    data = request.json
    client_id = data.get('client_id') or request.api_user.get('client', 'Client1')
    
    deals_raw = data.get('deals', [])
    deals, dropped_internal = _drop_balance_deals(deals_raw)
    if dropped_internal:
        app.logger.info(f"🚫 Dropped {dropped_internal} internal transfer deal(s) (BALANCE/CREDIT) from /api/trader/push_deals")
    update_client_field(client_id, 'deals', deals)
    log_action('PUSH_DEALS', 'trader', request.api_user.get('trader'), get_remote_address(), f"Client: {client_id}")
    
    return jsonify({"status": "success", "message": "Deals updated"})

@app.route('/api/trader/push_evaluations', methods=['POST'])
@require_api_key
@limiter.limit("30 per minute")
def push_evaluations():
    """Endpoint for traders to push evaluation data."""
    data = request.json
    client_id = data.get('client_id') or request.api_user.get('client', 'Client1')
    
    new_evals = data.get('evaluations', [])
    
    # Preserve _deleted flags from existing data
    existing_data = get_client_data(client_id) or {}
    existing_evals = existing_data.get('evaluations', [])
    deleted_fingerprints = set()
    for ev in existing_evals:
        if isinstance(ev, dict) and ev.get('_deleted'):
            acct = str(ev.get('Account #') or ev.get('Account #.1') or '').strip()
            firm = str(ev.get('Prop Firm') or '').strip()
            size = str(ev.get('Account Size') or '').strip()
            if acct:
                deleted_fingerprints.add((acct, firm, size))
    
    if deleted_fingerprints:
        for ev in new_evals:
            if isinstance(ev, dict):
                acct = str(ev.get('Account #') or ev.get('Account #.1') or '').strip()
                firm = str(ev.get('Prop Firm') or '').strip()
                size = str(ev.get('Account Size') or '').strip()
                if acct and (acct, firm, size) in deleted_fingerprints:
                    ev['_deleted'] = True

    force_fields = set((data.get('force_fields') or []) if isinstance(data, dict) else [])
    merged_evals = merge_evaluation_push_with_existing(
        existing_evals, new_evals, force_fields)

    update_client_field(client_id, 'evaluations', merged_evals)
    log_action('PUSH_EVALUATIONS', 'trader', request.api_user.get('trader'), get_remote_address(), f"Client: {client_id}")
    
    return jsonify({"status": "success", "message": "Evaluations updated"})

# ============ Data History & Version Control ============

@app.route('/api/client/history', methods=['POST'])
@limiter.limit("30 per minute")
def api_get_client_history():
    """
    Get the change history for a client's data.
    Requires client email for authentication.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    limit = data.get('limit', 50)
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    # Look up client by email
    from config.hierarchy import get_client_by_email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered"}), 404
    
    client_id = client_info['client']
    history = get_data_history(client_id, limit)
    
    return jsonify({
        "status": "success",
        "client_id": client_id,
        "history": history,
        "total_versions": len(history)
    })

@app.route('/api/client/version', methods=['POST'])
@limiter.limit("30 per minute")
def api_get_client_version():
    """
    Get a specific version of client data.
    Useful for viewing what the data looked like at a previous point.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    version = data.get('version')
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    if version is None:
        return jsonify({"status": "error", "message": "Version number required"}), 400
    
    # Look up client by email
    from config.hierarchy import get_client_by_email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered"}), 404
    
    client_id = client_info['client']
    version_data = get_data_version(client_id, int(version))
    
    if not version_data:
        return jsonify({"status": "error", "message": f"Version {version} not found"}), 404
    
    return jsonify({
        "status": "success",
        "client_id": client_id,
        "version_info": {
            "version": version_data['version'],
            "action": version_data['action'],
            "changed_by": version_data['changed_by'],
            "change_source": version_data['change_source'],
            "change_description": version_data['change_description'],
            "created_at": version_data['created_at']
        },
        "data": version_data['data']
    })

@app.route('/api/client/rollback', methods=['POST'])
@limiter.limit("5 per hour")
def api_rollback_client_data():
    """
    Rollback client data to a specific previous version.
    Creates a new version marking this as a rollback.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    version = data.get('version') or data.get('rollback_version')  # support both field names
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    if version is None:
        return jsonify({"status": "error", "message": "Version number required"}), 400
    
    # Look up client by email
    from config.hierarchy import get_client_by_email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered"}), 404
    
    client_id = client_info['client']
    
    # Check if version exists
    version_data = get_data_version(client_id, int(version))
    if not version_data:
        return jsonify({"status": "error", "message": f"Version {version} not found"}), 404
    
    # Perform rollback
    success, new_version = rollback_to_version(
        client_id, 
        int(version),
        rolled_back_by=email,
        rolled_back_by_type='client',
        ip_address=get_remote_address()
    )
    
    if success:
        log_action('DATA_ROLLBACK', 'client', email, get_remote_address(), 
                   f"Rolled back {client_id} to version {version} (new version: {new_version})")
        
        return jsonify({
            "status": "success",
            "message": f"Data rolled back to version {version}",
            "client_id": client_id,
            "rolled_back_to_version": version,
            "new_version": new_version,
            "rolled_back_from_date": version_data['created_at']
        })
    else:
        return jsonify({"status": "error", "message": "Failed to rollback data"}), 500

@app.route('/api/client/compare_versions', methods=['POST'])
@limiter.limit("30 per minute")
def api_compare_versions():
    """
    Compare two versions of client data to see what changed.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    version1 = data.get('version1')
    version2 = data.get('version2')
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    if version1 is None or version2 is None:
        return jsonify({"status": "error", "message": "Both version1 and version2 required"}), 400
    
    # Look up client by email
    from config.hierarchy import get_client_by_email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered"}), 404
    
    client_id = client_info['client']
    
    comparison = compare_versions(client_id, int(version1), int(version2))
    
    if not comparison:
        return jsonify({"status": "error", "message": "One or both versions not found"}), 404
    
    return jsonify({
        "status": "success",
        "client_id": client_id,
        "comparison": comparison
    })

@app.route('/api/admin/all_history', methods=['GET'])
@require_admin_password
def api_get_all_history():
    """
    Admin endpoint to get all history across all clients.
    """
    from dashboard.database import get_connection
    
    limit = request.args.get('limit', 100, type=int)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, client_id, version, action, changed_by, changed_by_type,
                   change_source, change_description, created_at
            FROM data_history 
            ORDER BY created_at DESC
            LIMIT ?
        ''', (limit,))
        history = [dict(row) for row in cursor.fetchall()]
    
    return jsonify({
        "status": "success",
        "history": history,
        "total_entries": len(history)
    })

# ============ Health Check ============

@app.route('/health', methods=['GET'])
@app.route('/api/health', methods=['GET'])
def health_check():
    """Simple health check endpoint."""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "clients_count": get_clients_count()
    })

# ============ Change Password Endpoint ============

@app.route('/api/admin/change_password', methods=['POST'])
@require_admin_password
@limiter.limit("3 per hour")
def change_admin_password():
    """Change admin password."""
    new_password = request.json.get('new_password')
    
    if not new_password or len(new_password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters"}), 400
    
    if set_admin_password('super_admin', new_password):
        log_action('CHANGE_PASSWORD', 'admin', 'super_admin', get_remote_address())
        return jsonify({"status": "success", "message": "Password changed successfully"})
    
    return jsonify({"status": "error", "message": "Failed to change password"}), 500

# ============ Sheet Data Endpoints ============
try:
    from dashboard.utils.sheet_helper import fetch_stats_data, fetch_waterlog_data
except ImportError:
    # Fallback if utils package structure is wacky
    try:
        from utils.sheet_helper import fetch_stats_data, fetch_waterlog_data
    except ImportError:
        logging.error("Could not import sheet_helper")

@app.route('/api/sheet/stats')
@require_session
def get_stats_sheet_data():
    """Fetches stats data directly from the Google Sheet."""
    try:
        data = fetch_stats_data()
        if data:
            return jsonify({"status": "success", "data": data})
        return jsonify({"status": "error", "message": "Failed to fetch stats data"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/sheet/waterlog')
@require_session
def get_waterlog_sheet_data():
    """Returns the Profit Share History table.

    Priority:
      1. Compute from DB (waterlog_periods + daily_watermarks) — offline.
      2. If no period schedule exists, derive a minimal row from daily_watermarks only
         (avoids Google when sheet export fails).
      3. Last resort: live Google Sheet CSV export.

    Query params:
      ?client_id=<id>   — required to identify whose schedule/daily data to use
      ?sheet_url=<url>  — fallback sheet URL for pre-import clients
    """
    try:
        from dashboard.watermark_service import compute_waterlog_from_db, compute_waterlog_daily_fallback
    except ImportError:
        from watermark_service import compute_waterlog_from_db, compute_waterlog_daily_fallback

    try:
        client_id_param = request.args.get('client_id')
        sheet_url = request.args.get('sheet_url') or None

        db_waterlog = None
        # ── 1. Try fully-offline DB computation ──────────────────────────────
        if client_id_param:
            db_waterlog = compute_waterlog_from_db(client_id_param)
            if db_waterlog is not None:
                return jsonify({"status": "success", "data": db_waterlog})

            daily_fb = compute_waterlog_daily_fallback(client_id_param)
            if daily_fb is not None:
                return jsonify({"status": "success", "data": daily_fb})

        # ── 3. Live Google Sheet CSV (pre-import clients or missing daily rows) ──
        if client_id_param:
            client_data = get_client_data(client_id_param)
            if client_data:
                sheet_url = client_data.get('sheet_url') or sheet_url

        data = fetch_waterlog_data(sheet_url=sheet_url, client_id=client_id_param)
        if data:
            return jsonify({"status": "success", "data": data})

        msg = "Failed to fetch waterlog data"
        if client_id_param and db_waterlog is None:
            if not sheet_url:
                msg = (
                    "No profit-share schedule or daily snapshots in the database for this client "
                    "and no Google Sheet URL is on file. Re-import from Sheets or add a sheet URL."
                )
            else:
                msg = (
                    "Could not load the Profitability Waterlog from Google (timeout, rate limit, or "
                    "sheet access) and there are no daily snapshots to fall back on. "
                    "Try again later or re-import the client."
                )
        return jsonify({"status": "error", "message": msg}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/client/profit_split_override', methods=['POST'])
@require_session
def api_save_profit_split_override():
    """Save a manual profit split override for a specific period. Admin only."""
    session_user = request.session_user
    if session_user.get('user_type') not in ('admin', 'super_admin'):
        return jsonify({"status": "error", "message": "Admin access required"}), 403

    data = request.get_json(silent=True) or {}
    client_id = data.get('client_id')
    from_date = data.get('from_date')
    amount = data.get('amount')

    if not client_id or not from_date or amount is None:
        return jsonify({"status": "error", "message": "client_id, from_date, and amount are required"}), 400

    try:
        amount = float(str(amount).replace('$', '').replace(',', ''))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid amount"}), 400

    try:
        from dashboard.watermark_service import save_profit_split_override
    except ImportError:
        from watermark_service import save_profit_split_override

    if save_profit_split_override(client_id, from_date, amount):
        return jsonify({"status": "success", "message": "Profit split override saved"})
    return jsonify({"status": "error", "message": "Failed to save override"}), 500


@app.route('/api/client/split_pct_override', methods=['POST'])
@require_session
def api_save_split_pct_override():
    """Save a per-period split percentage override. Admin only."""
    session_user = request.session_user
    if session_user.get('user_type') not in ('admin', 'super_admin'):
        return jsonify({"status": "error", "message": "Admin access required"}), 403

    data = request.get_json(silent=True) or {}
    client_id = data.get('client_id')
    from_date = data.get('from_date')
    pct = data.get('pct')

    if not client_id or not from_date or pct is None:
        return jsonify({"status": "error", "message": "client_id, from_date, and pct are required"}), 400

    try:
        pct = float(str(pct).replace('%', '').strip())
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid percentage"}), 400

    if pct < 0 or pct > 100:
        return jsonify({"status": "error", "message": "Percentage must be between 0 and 100"}), 400

    try:
        from dashboard.watermark_service import save_split_pct_override
    except ImportError:
        from watermark_service import save_split_pct_override

    if save_split_pct_override(client_id, from_date, pct):
        return jsonify({"status": "success", "message": "Split percentage override saved"})
    return jsonify({"status": "error", "message": "Failed to save override"}), 500


@app.route('/api/client/net_profit_override', methods=['POST'])
@require_session
def api_save_net_profit_override():
    """Save a manual net profit override for a specific period. Admin only."""
    session_user = request.session_user
    if session_user.get('user_type') not in ('admin', 'super_admin'):
        return jsonify({"status": "error", "message": "Admin access required"}), 403

    data = request.get_json(silent=True) or {}
    client_id = data.get('client_id')
    from_date = data.get('from_date')
    amount = data.get('amount')

    if not client_id or not from_date or amount is None:
        return jsonify({"status": "error", "message": "client_id, from_date, and amount are required"}), 400

    try:
        amount = float(str(amount).replace('$', '').replace(',', ''))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid amount"}), 400

    try:
        from dashboard.watermark_service import save_net_profit_override
    except ImportError:
        from watermark_service import save_net_profit_override

    if save_net_profit_override(client_id, from_date, amount):
        return jsonify({"status": "success", "message": "Net profit override saved"})
    return jsonify({"status": "error", "message": "Failed to save override"}), 500

# ============ Global Error Handlers ============

@app.errorhandler(404)
def not_found(e):
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify({"status": "error", "message": "Not found"}), 404
    return "Page not found", 404

@app.errorhandler(500)
def internal_server_error(e):
    """Show maintenance page on any 500 Internal Server Error."""
    import logging
    logging.error(f"500 error: {e}")
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify({"status": "error", "message": "Internal server error"}), 500
    return render_template('500.html'), 500

@app.errorhandler(Exception)
def unhandled_exception(e):
    """Catch-all for any unhandled exception — skip HTTP exceptions (404, 403, etc.)."""
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    import logging
    logging.exception(f"Unhandled exception: {e}")
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
    return render_template('500.html'), 500

# ============ Main Entry Point ============

def run_dashboard():
    print(f"\n{'='*60}")
    print("SECURE DASHBOARD API SERVER STARTING")
    print(f"{'='*60}")
    print(f"Database: PostgreSQL (Alembic-managed schema)")
    print(f"Rate Limiting: Enabled")
    print(f"Password Hashing: PBKDF2-SHA256 (100,000 iterations)")
    print(f"API Keys: Hashed with SHA-256")
    print(f"Audit Logging: Enabled")
    print(f"\nClients in database: {get_clients_count()}")
    print(f"{'='*60}\n")
    app.run(host='0.0.0.0', port=5001, debug=True)

if __name__ == '__main__':
    run_dashboard()
