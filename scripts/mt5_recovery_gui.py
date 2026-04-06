"""
MT5 Data Recovery Tool — GUI with two modes:

Mode 1 (Single Account): Search for a specific account number + phase.
Mode 2 (Recover All):    Fetch ALL deals from MT5, parse every comment,
                          group by prop firm account + phase + date. Displays
                          every account found as a browsable grouped table so
                          you can fill the dashboard manually.

Usage:
    python scripts/mt5_recovery_gui.py

Requires: MetaTrader5, customtkinter
"""

import sys
import os
import re
import csv
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta
from collections import defaultdict, OrderedDict
import customtkinter as ctk

# ═══════════════════════════════════════════════════════════════
# MT5 Logic (same as debug_mt5_positions.py)
# ═══════════════════════════════════════════════════════════════

def parse_comment(comment):
    if not comment:
        return None
    c = str(comment).strip()
    phase_match = re.search(r'_(CH|FD|DD|FA)(\d+)?', c, re.IGNORECASE)
    if not phase_match:
        return None
    phase = phase_match.group(1).upper()
    number = int(phase_match.group(2)) if phase_match.group(2) else 1
    account_match = re.search(r'([A-Z0-9]+)_(CH|FD|DD|FA)', c, re.IGNORECASE)
    if not account_match:
        return None
    return {
        'account_number': account_match.group(1).upper(),
        'phase': phase,
        'number': number,
    }


def phase_to_field(phase, number, is_mffu=False):
    """Map phase code + number to dashboard field name.
    is_mffu: True for MFFU prefix — FD uses +1 offset (FD0→HR1.1, FD1→HR2.1)
             False for all other firms — FD uses no offset (FD1→HR1.1, FD2→HR2.1)
    """
    if phase == 'CH':
        if 1 <= number <= 5:
            return f"Hedge Result {number}"
    elif phase == 'FD':
        if is_mffu:
            # MFFU: FD0→HR1.1, FD1→HR2.1, FD2→HR3.1 ...
            return f"Hedge Result {number + 1}.1"
        else:
            # Others: FD1→HR1.1, FD2→HR2.1, FD3→HR3.1 ...
            return f"Hedge Result {max(1, number)}.1"
    elif phase == 'DD':
        # DD1→HR1.1, DD2→HR2.1, DD3→HR3.1, DD4→HR4.1
        return f"Hedge Result {number}.1"
    elif phase == 'FA':
        return f"Hedge Day {number}" if number >= 1 else "Hedge Day 1"
    return f"{phase}{number}"


PREFIX_TO_FIRM = {
    'MFFU': 'My Funded Futures', 'FNFT': 'FundedNext', 'TDFY': 'Tradeify',
    'V2': 'Topstep', '50KTC': 'Topstep', 'TDF': 'TradeDay', 'ELTD': 'TradeDay',
    'FTDF': 'TradeDay', 'AFAD': 'Alpha Futures', 'APEX': 'Apex',
    'TPOF': 'Top One Futures',
}


def parse_full_comment(comment):
    """
    Parse MT5 comment to extract prefix, account, phase, number.
    E.g. MFFU...60076_FD1 -> ('MFFU', '60076', 'FD', 1)
         V2-...4610_CH2  -> ('V2', '4610', 'CH', 2)
         FNFT...G8326_FA -> ('FNFT', 'G8326', 'FA', 1)
    """
    if not comment:
        return None
    c = str(comment).strip()
    m = re.search(r'^([A-Z0-9\-]+)[^A-Z0-9]+([A-Z0-9]+)_(CH|FD|DD|FA)(\d+)?$', c, re.IGNORECASE)
    if m:
        prefix = m.group(1).upper().rstrip('-')
        return {
            'prefix': prefix,
            'firm': PREFIX_TO_FIRM.get(prefix, prefix),
            'account_number': m.group(2).upper(),
            'phase': m.group(3).upper(),
            'number': int(m.group(4)) if m.group(4) else 1,
        }
    # Fallback: at least try to get phase + account
    parsed = parse_comment(comment)
    if parsed:
        # Guess prefix from start of comment
        c_upper = c.upper()
        prefix = None
        for k in sorted(PREFIX_TO_FIRM, key=len, reverse=True):
            if c_upper.startswith(k) or k in c_upper:
                prefix = k; break
        parsed['prefix'] = prefix or '??'
        parsed['firm'] = PREFIX_TO_FIRM.get(prefix, prefix or '??')
        return parsed
    return None


DEAL_TYPE_MAP = {
    0: "BUY", 1: "SELL", 2: "BALANCE", 3: "CREDIT", 4: "CHARGE",
    5: "CORRECTION", 6: "BONUS", 7: "COMMISSION", 8: "DAILY_COMM",
    9: "MONTHLY_COMM", 10: "DAILY_AGT", 11: "MONTHLY_AGT", 12: "INTEREST",
}

ENTRY_MAP = {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}


def fetch_mt5_data(mt5_login, mt5_password, mt5_server, account_number,
                   phase_filter, days_back, progress_cb=None):
    """
    Connect to MT5, fetch deals, filter by account+phase.
    Returns dict with keys: matched, daily, phase_summary, open_positions,
                            other_accounts, account_info, error
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return {'error': 'MetaTrader5 package not installed.\nRun: pip install MetaTrader5'}

    if progress_cb:
        progress_cb('Initializing MT5...')
    if not mt5.initialize():
        return {'error': f'MT5 initialize() failed: {mt5.last_error()}'}

    if progress_cb:
        progress_cb(f'Logging in to {mt5_login} @ {mt5_server}...')
    if not mt5.login(int(mt5_login), password=mt5_password, server=mt5_server):
        err = mt5.last_error()
        mt5.shutdown()
        return {'error': f'MT5 login failed: {err}'}

    acct = mt5.account_info()
    account_info = {}
    if acct:
        # Compute total deposits/withdrawals from all-time BALANCE deals (type=2)
        total_deposits = 0.0
        total_withdrawals = 0.0
        try:
            import time as _t
            bal_deals = mt5.history_deals_get(0, _t.time() + 86400)
            if bal_deals:
                for _bd in bal_deals:
                    if _bd.type == 2:           # DEAL_TYPE_BALANCE
                        if _bd.profit > 0:
                            total_deposits += _bd.profit
                        else:
                            total_withdrawals += _bd.profit
        except Exception:
            pass
        account_info = {
            'name':               acct.name,
            'balance':            acct.balance,
            'equity':             acct.equity,
            'login':              acct.login,
            'currency':           getattr(acct, 'currency', ''),
            'leverage':           getattr(acct, 'leverage', 0),
            'total_deposits':     total_deposits,
            'total_withdrawals':  total_withdrawals,
        }

    # Fetch deals
    if progress_cb:
        progress_cb(f'Fetching {days_back} days of deal history...')
    import time
    from_ts = time.time() - (days_back * 86400)
    to_ts = time.time() + 86400
    deals = mt5.history_deals_get(from_ts, to_ts)

    # Fetch open positions
    if progress_cb:
        progress_cb('Checking open positions...')
    positions = mt5.positions_get()
    mt5.shutdown()

    if deals is None or len(deals) == 0:
        return {'error': 'No deals returned from MT5.',
                'account_info': account_info}

    # Filter
    if progress_cb:
        progress_cb(f'Filtering {len(deals)} deals...')
    account_upper = account_number.upper()
    matched = []
    other_accounts = set()

    for deal in deals:
        d = deal._asdict()
        comment = d.get('comment', '')
        parsed = parse_comment(comment)
        if parsed:
            extracted = parsed['account_number'].upper()
            # Match exact OR suffix (MT5 comments often truncate leading digits,
            # e.g. dashboard account '17879' appears as '7879' in the comment)
            account_match = (
                extracted == account_upper
                or (len(extracted) >= 4 and account_upper.endswith(extracted))
                or (len(account_upper) >= 4 and extracted.endswith(account_upper))
            )
            if account_match:
                if phase_filter and phase_filter != 'ALL' and parsed['phase'] != phase_filter:
                    continue
                d['_parsed'] = parsed
                matched.append(d)
            else:
                other_accounts.add(parsed['account_number'])

    if not matched:
        return {
            'error': f"No deals found for account '{account_number}'.",
            'account_info': account_info,
            'other_accounts': sorted(other_accounts),
            'total_deals': len(deals),
        }

    # Resolve profit from closing deals
    matched.sort(key=lambda d: d['time'])
    position_ids = {d['position_id'] for d in matched}
    position_profit = defaultdict(float)
    for deal in deals:
        d2 = deal._asdict()
        if d2.get('position_id') in position_ids and int(d2.get('entry', -1)) == 1:
            position_profit[d2['position_id']] += (
                d2.get('profit', 0) + d2.get('commission', 0) + d2.get('swap', 0)
            )
    for d in matched:
        d['_profit'] = position_profit.get(d['position_id'], 0.0)

    # Group by date
    daily = defaultdict(list)
    for d in matched:
        dt = datetime.fromtimestamp(d['time'])
        daily[dt.strftime('%Y-%m-%d')].append(d)

    sorted_dates = sorted(daily.keys())
    date_to_hd = {dk: i for i, dk in enumerate(sorted_dates, start=1)}

    # Phase summary
    phase_summary = defaultdict(lambda: {'count': 0, 'profit': 0.0, 'days': set()})
    for d in matched:
        p = d['_parsed']
        key = f"{p['phase']}{p['number']}"
        phase_summary[key]['count'] += 1
        phase_summary[key]['profit'] += d['_profit']
        phase_summary[key]['days'].add(datetime.fromtimestamp(d['time']).strftime('%Y-%m-%d'))

    # Open positions
    open_matched = []
    if positions:
        for pos in positions:
            p = pos._asdict()
            parsed = parse_comment(p.get('comment', ''))
            if parsed:
                extracted = parsed['account_number'].upper()
                open_acct_match = (
                    extracted == account_upper
                    or (len(extracted) >= 4 and account_upper.endswith(extracted))
                    or (len(account_upper) >= 4 and extracted.endswith(account_upper))
                )
                if open_acct_match:
                    if phase_filter and phase_filter != 'ALL' and parsed['phase'] != phase_filter:
                        continue
                    p['_parsed'] = parsed
                    open_matched.append(p)

    return {
        'matched': matched,
        'daily': dict(daily),
        'sorted_dates': sorted_dates,
        'date_to_hd': date_to_hd,
        'phase_summary': dict(phase_summary),
        'open_positions': open_matched,
        'other_accounts': sorted(other_accounts),
        'account_info': account_info,
        'total_deals': len(deals),
        'error': None,
    }


def fetch_all_deals_from_mt5(mt5_login, mt5_password, mt5_server,
                              from_date_str, to_date_str=None, progress_cb=None):
    """
    Fetch ALL deals from MT5 between from_date and to_date.
    Parse every comment, group by firm -> account -> phase.
    No account filter needed — we reconstruct everything from comments.

    Returns dict:
      accounts_data: { firm: { account: { 'prefix', 'phases': { phase_key: {
                         'field', 'deals', 'net_pl', 'dates', 'daily' } } } } }
      flat_rows:     sorted list for treeview display
      account_info:  MT5 account metadata
      total_deals:   number of raw deals fetched
      parsed_deals:  number of deals with parseable comments
      error:         None or error string
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return {'error': 'MetaTrader5 package not installed.\nRun: pip install MetaTrader5'}

    if progress_cb: progress_cb('Initializing MT5...')
    if not mt5.initialize():
        return {'error': f'MT5 initialize() failed: {mt5.last_error()}'}

    if progress_cb: progress_cb(f'Logging in to {mt5_login} @ {mt5_server}...')
    if not mt5.login(int(mt5_login), password=mt5_password, server=mt5_server):
        err = mt5.last_error(); mt5.shutdown()
        return {'error': f'MT5 login failed: {err}'}

    acct = mt5.account_info()
    account_info = {}
    if acct:
        account_info = {'name': acct.name, 'balance': acct.balance,
                        'equity': acct.equity, 'login': acct.login}

    # Parse date range
    try:
        from_dt = datetime.strptime(from_date_str.strip(), '%Y-%m-%d')
    except Exception:
        from_dt = datetime(2026, 3, 15)
    if to_date_str and to_date_str.strip():
        try:
            to_dt = datetime.strptime(to_date_str.strip(), '%Y-%m-%d') + timedelta(days=1)
        except Exception:
            to_dt = datetime.now() + timedelta(days=1)
    else:
        to_dt = datetime.now() + timedelta(days=1)

    import time as _time
    from_ts = from_dt.timestamp()
    to_ts = to_dt.timestamp()

    if progress_cb: progress_cb(f'Fetching deals from {from_dt.date()} to {to_dt.date()}...')
    deals = mt5.history_deals_get(from_ts, to_ts)
    mt5.shutdown()

    if deals is None or len(deals) == 0:
        return {'error': 'No deals returned from MT5.', 'account_info': account_info}

    total_deals = len(deals)
    if progress_cb: progress_cb(f'Parsing {total_deals} deals...')

    # Build position_profit map (closing-side profit includes commission+swap)
    position_profit = defaultdict(float)
    for deal in deals:
        d = deal._asdict()
        if int(d.get('entry', -1)) == 1:  # OUT = closing leg
            position_profit[d['position_id']] += (
                d.get('profit', 0) + d.get('commission', 0) + d.get('swap', 0))

    # Parse and group all deals
    # accounts_data[firm][account_number] = { 'prefix', 'phases': { phase_key: {...} } }
    accounts_data = {}
    parsed_deals = 0
    unparseable = []

    for deal in deals:
        d = deal._asdict()
        comment = d.get('comment', '')
        parsed = parse_full_comment(comment)
        if not parsed:
            if comment and comment.strip():
                unparseable.append(comment)
            continue

        firm = parsed['firm']
        account = parsed['account_number']
        phase = parsed['phase']
        number = parsed['number']
        phase_key = f"{phase}{number}" if not (phase == 'FA') else 'FA'

        # Determine dashboard field
        if phase == 'FA':
            # Field will be assigned by date order later
            field_label = 'Hedge Day (by date)'
        else:
            is_mffu = parsed.get('prefix', '') == 'MFFU'
            field_label = phase_to_field(phase, number, is_mffu=is_mffu)

        if firm not in accounts_data:
            accounts_data[firm] = {}
        if account not in accounts_data[firm]:
            accounts_data[firm][account] = {'prefix': parsed['prefix'], 'phases': {}}
        if phase_key not in accounts_data[firm][account]['phases']:
            accounts_data[firm][account]['phases'][phase_key] = {
                'field': field_label,
                'phase': phase,
                'number': number,
                'deals': [],
                'daily': defaultdict(list),
            }

        # Attach profit
        d['_profit'] = (d.get('profit', 0) + d.get('commission', 0) + d.get('swap', 0)
                        if int(d.get('entry', -1)) == 1
                        else position_profit.get(d['position_id'], 0.0))
        d['_parsed'] = parsed

        dt = datetime.fromtimestamp(d['time'])
        date_key = dt.strftime('%Y-%m-%d')
        accounts_data[firm][account]['phases'][phase_key]['deals'].append(d)
        accounts_data[firm][account]['phases'][phase_key]['daily'][date_key].append(d)
        parsed_deals += 1

    # Post-process: compute net_pl, date ranges, hedge day numbers for FA
    for firm in accounts_data:
        for account in accounts_data[firm]:
            for phase_key, ph in accounts_data[firm][account]['phases'].items():
                ph['deals'].sort(key=lambda x: x['time'])
                ph['net_pl'] = sum(d['_profit'] for d in ph['deals'])
                sorted_dates = sorted(ph['daily'].keys())
                ph['sorted_dates'] = sorted_dates
                ph['date_range'] = (sorted_dates[0], sorted_dates[-1]) if sorted_dates else ('', '')
                ph['deal_count'] = len(ph['deals'])
                # For FA: assign Hedge Day N by sorted date order
                if ph['phase'] == 'FA':
                    ph['date_to_hd'] = {dk: i for i, dk in enumerate(sorted_dates, 1)}
                    ph['field'] = f"Hedge Day 1 … {len(sorted_dates)}" if len(sorted_dates) > 1 else "Hedge Day 1"
                else:
                    ph['date_to_hd'] = {}

    # Build flat rows for treeview
    flat_rows = []
    for firm in sorted(accounts_data.keys()):
        for account in sorted(accounts_data[firm].keys()):
            acct_info = accounts_data[firm][account]
            total_acct_pl = sum(ph['net_pl'] for ph in acct_info['phases'].values())
            total_acct_deals = sum(ph['deal_count'] for ph in acct_info['phases'].values())
            flat_rows.append({
                'level': 'account',
                'firm': firm,
                'account': account,
                'prefix': acct_info['prefix'],
                'phase_key': '',
                'field': '',
                'deal_count': total_acct_deals,
                'net_pl': total_acct_pl,
                'date_range': '',
            })
            for phase_key in sorted(acct_info['phases'].keys()):
                ph = acct_info['phases'][phase_key]
                dr = ph['date_range']
                date_str = f"{dr[0]} → {dr[1]}" if dr[0] != dr[1] else dr[0]
                flat_rows.append({
                    'level': 'phase',
                    'firm': firm,
                    'account': account,
                    'prefix': acct_info['prefix'],
                    'phase_key': phase_key,
                    'field': ph['field'],
                    'deal_count': ph['deal_count'],
                    'net_pl': ph['net_pl'],
                    'date_range': date_str,
                    'sorted_dates': ph.get('sorted_dates', []),
                    'date_to_hd': ph.get('date_to_hd', {}),
                    'deals': ph['deals'],
                    'daily': ph['daily'],
                })

    if progress_cb: progress_cb(f'Done. {parsed_deals} deals across {len(flat_rows)} sessions.')
    return {
        'accounts_data': accounts_data,
        'flat_rows': flat_rows,
        'account_info': account_info,
        'total_deals': total_deals,
        'parsed_deals': parsed_deals,
        'unparseable_count': len(set(unparseable)),
        'error': None,
    }


# ═══════════════════════════════════════════════════════════════
# Tooltip helper
# ═══════════════════════════════════════════════════════════════

class Tooltip:
    """Hover tooltip for any widget.  Shows a small dark popup with help text."""
    PAD = 6
    DELAY = 400  # ms before popup appears

    def __init__(self, widget, text, bg='#1e2235', fg='#cbd5e1'):
        self._widget = widget
        self._text   = text
        self._bg     = bg
        self._fg     = fg
        self._win    = None
        self._after  = None
        widget.bind('<Enter>',    self._schedule, add='+')
        widget.bind('<Leave>',    self._cancel,   add='+')
        widget.bind('<Button>',   self._cancel,   add='+')
        widget.bind('<Destroy>',  self._cancel,   add='+')

    def _schedule(self, event=None):
        self._cancel()
        self._after = self._widget.after(self.DELAY, self._show)

    def _cancel(self, event=None):
        if self._after:
            self._widget.after_cancel(self._after)
            self._after = None
        if self._win:
            self._win.destroy()
            self._win = None

    def _show(self):
        if self._win:
            return
        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._win = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f'+{x}+{y}')
        tw.configure(bg='#3a4460')
        outer = tk.Frame(tw, bg='#3a4460', padx=1, pady=1)
        outer.pack()
        inner = tk.Frame(outer, bg=self._bg)
        inner.pack()
        tk.Label(inner, text=self._text, justify='left',
                 bg=self._bg, fg=self._fg,
                 font=('Segoe UI', 9), wraplength=360,
                 padx=self.PAD + 4, pady=self.PAD).pack()


def tip(widget, text):
    """Attach a tooltip to widget and return the widget (for chaining)."""
    Tooltip(widget, text)
    return widget


# ═══════════════════════════════════════════════════════════════
# GUI
# ═══════════════════════════════════════════════════════════════

class MT5RecoveryApp:
    # ── palette ──────────────────────────────────────────────
    BG        = '#0f1117'
    BG2       = '#1a1d27'
    BG3       = '#242837'
    ACCENT    = '#4f8ef7'
    ACCENT2   = '#3ecf8e'
    FG        = '#e2e8f0'
    FG2       = '#94a3b8'
    GOOD      = '#3ecf8e'
    BAD       = '#f87171'
    WARN      = '#fb923c'
    SEL       = '#2d3a55'

    def __init__(self, root):
        self.root = root
        self.root.title("MT5 Data Recovery Tool")
        self.root.geometry("1320x820")
        self.root.minsize(1000, 640)
        self.result_data   = None
        self._recon_all_rows = []
        self._recon_data   = None

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # ── ttk treeview styling (CTK has no native Treeview) ──
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('T.Treeview',
                        background=self.BG3, foreground=self.FG,
                        fieldbackground=self.BG3, font=('Consolas', 9), rowheight=26)
        style.configure('T.Treeview.Heading',
                        background=self.BG2, foreground=self.ACCENT,
                        font=('Segoe UI', 9, 'bold'), relief='flat')
        style.map('T.Treeview',
                  background=[('selected', self.SEL)],
                  foreground=[('selected', '#ffffff')])
        style.configure('Vertical.TScrollbar',
                        background=self.BG2, troughcolor=self.BG,
                        bordercolor=self.BG, arrowcolor=self.FG2)
        style.configure('Horizontal.TScrollbar',
                        background=self.BG2, troughcolor=self.BG,
                        bordercolor=self.BG, arrowcolor=self.FG2)

        self._build_ui()

    # ══════════════════════════════════════════════════════════
    def _build_ui(self):
        self.root.configure(bg=self.BG)

        # ── top header bar ────────────────────────────────────
        header = tk.Frame(self.root, bg=self.BG2, height=52)
        header.pack(fill='x', side='top')
        header.pack_propagate(False)
        tk.Label(header, text="  MT5 Data Recovery Tool",
                 bg=self.BG2, fg=self.ACCENT,
                 font=('Segoe UI', 16, 'bold')).pack(side='left', padx=8, pady=10)

        # Help toggle button on right of header
        self._help_open = tk.BooleanVar(value=False)
        help_btn = ctk.CTkButton(
            header, text='📖  How to use',
            fg_color='#1e2235', hover_color='#2d3a55',
            text_color=self.FG2, font=('Segoe UI', 9),
            corner_radius=6, height=28, width=120,
            command=self._toggle_help)
        help_btn.pack(side='right', padx=12, pady=10)

        # ── collapsible instructions panel ───────────────────
        self._help_frame = tk.Frame(self.root, bg='#1e2235', bd=0)
        # (packed/unpacked by _toggle_help — hidden by default)

        INSTRUCTIONS = (
            "QUICK START\n"
            "──────────────────────────────────────────────────────\n"
            "FETCH DEALS (single account)\n"
            "  1. Enter your HEDGE account MT5 Login, Password and Server.\n"
            "  2. Enter the dashboard Account # — the number shown in the\n"
            "     client's MT5 comment, e.g. '7879' or '17879'.\n"
            "  3. Choose a Phase filter (ALL / FA / CH / FD / DD) or leave ALL.\n"
            "  4. Set Days Back — how far into history to pull (default 365).\n"
            "  5. Click  🔍 FETCH DEALS  — results appear in the tabs below.\n"
            "\n"
            "RECONSTRUCT ALL (every account at once)\n"
            "  1. Fill in MT5 Login / Password / Server (same as above).\n"
            "  2. Set From Date and To Date for the period to scan.\n"
            "  3. Click  ⚡ RECONSTRUCT ALL  — every parseable MT5 comment is\n"
            "     decoded and grouped by Firm → Account → Phase → Hedge Day.\n"
            "  4. Click any row in the table to see individual deal detail below.\n"
            "  5. Use the Filter box to search by firm name, account, or phase.\n"
            "\n"
            "TABS (after Fetch Deals)\n"
            "  Summary        — totals: balance, equity, matched deals, P/L\n"
            "  Phase Breakdown— deals grouped by phase code → dashboard field\n"
            "  Hedge Days     — one row per trading day with P/L\n"
            "  All Deals      — every individual deal with ticket, price, profit\n"
            "  Open Positions — currently open trades on this MT5 account\n"
            "  Reconstruct All— multi-account recovery view\n"
            "\n"
            "EXPORT\n"
            "  💾 EXPORT CSV saves all matched deals to a CSV file you can open\n"
            "  in Excel and use to fill the dashboard manually.\n"
            "\n"
            "NOTES\n"
            "  • MT5 Login is the numeric hedge account ID (e.g. 123456).\n"
            "  • Server name must match exactly what MT5 shows (case-sensitive).\n"
            "  • Account # is the client account fragment in the MT5 comment\n"
            "    (the part after ... and before _CH/_FD/_FA/_DD).\n"
            "  • Phase codes: CH=Challenge  FD=Funded  FA=Farming  DD=Daily Draw\n"
            "  • Hover over any field label for a quick tip."
        )

        tip_frame = tk.Frame(self._help_frame, bg='#1e2235')
        tip_frame.pack(fill='both', expand=True, padx=16, pady=10)
        tk.Text(tip_frame, wrap='word', bg='#1e2235', fg='#cbd5e1',
                font=('Consolas', 9), relief='flat', padx=8, pady=6,
                height=22, state='normal',
                selectbackground=self.SEL).pack(fill='both', expand=True)
        # insert text then lock
        txt_w = tip_frame.winfo_children()[0]
        txt_w.insert('1.0', INSTRUCTIONS)
        txt_w.configure(state='disabled')

        # ── credential card ───────────────────────────────────
        cred = tk.Frame(self.root, bg=self.BG2, bd=0)
        cred.pack(fill='x', padx=14, pady=(10, 0))

        def lbl(parent, text, col=None, row=None, **kw):
            w = tk.Label(parent, text=text, bg=self.BG2, fg=self.FG2,
                         font=('Segoe UI', 9), **kw)
            if col is not None:
                w.grid(row=row, column=col, sticky='e', padx=(10, 4), pady=4)
            return w

        def ent(parent, var, w=15, show=''):
            e = ctk.CTkEntry(parent, textvariable=var, width=w*8,
                             fg_color=self.BG3, border_color=self.BG3,
                             text_color=self.FG, font=('Consolas', 11),
                             show=show, corner_radius=6, height=32)
            return e

        # Row 0 – credentials
        tip(lbl(cred, 'MT5 Login', col=0, row=0),
            'The numeric login ID of your HEDGE MT5 account.\nExample: 123456')
        self.mt5_login_var = tk.StringVar()
        tip(ent(cred, self.mt5_login_var, 12),
            'Numeric MT5 account login (hedge account, not client account).'
            ).grid(row=0, column=1, padx=(0,8), pady=4, sticky='w')

        tip(lbl(cred, 'Password', col=2, row=0),
            'The MT5 account password (investor or full access).')
        self.mt5_pass_var = tk.StringVar()
        self.pass_entry = ctk.CTkEntry(cred, textvariable=self.mt5_pass_var, width=140,
                                        fg_color=self.BG3, border_color=self.BG3,
                                        text_color=self.FG, font=('Consolas', 11),
                                        show='●', corner_radius=6, height=32)
        tip(self.pass_entry, 'MT5 account password. Tick "Show" to reveal.')
        self.pass_entry.grid(row=0, column=3, padx=(0,4), pady=4, sticky='w')

        self.show_pass_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(cred, text='Show', variable=self.show_pass_var,
                        command=self._toggle_password,
                        fg_color=self.ACCENT, text_color=self.FG2,
                        font=('Segoe UI', 9), width=60, height=20,
                        checkbox_width=16, checkbox_height=16
                        ).grid(row=0, column=4, padx=(2,12), sticky='w')

        tip(lbl(cred, 'Server', col=5, row=0),
            'The MT5 broker server name — must match exactly what MT5 shows.\nExample: PlexyTrade-Server01')
        self.mt5_server_var = tk.StringVar(value='PlexyTrade-Server01')
        tip(ent(cred, self.mt5_server_var, 22),
            'Broker server name (case-sensitive). Find it in MT5 → File → Login.'
            ).grid(row=0, column=6, padx=(0,8), pady=4, sticky='w')

        # Fetch + Export buttons (right side of row 0)
        self.fetch_btn = ctk.CTkButton(
                cred, text='🔍  FETCH DEALS',
                fg_color=self.ACCENT, hover_color='#3a7bd5',
                text_color='#ffffff', font=('Segoe UI', 11, 'bold'),
                corner_radius=8, height=36, width=170,
                command=self._on_fetch)
        tip(self.fetch_btn,
            'Connect to MT5 and pull all deals for the specified Account # and Phase.\n'
            'Results appear in the tabs below.')
        self.fetch_btn.grid(row=0, column=7, padx=(16,4), pady=4)

        self.export_btn = ctk.CTkButton(cred, text='💾  EXPORT CSV',
                                         fg_color=self.BG3, hover_color=self.BG,
                                         text_color=self.FG2, font=('Segoe UI', 9, 'bold'),
                                         corner_radius=8, height=28, width=140,
                                         state='disabled', command=self._on_export)
        tip(self.export_btn, 'Save all matched deals to a CSV file for manual dashboard entry.')
        self.export_btn.grid(row=1, column=7, padx=(16,4), pady=2)

        # Row 1 – account / phase / days
        tip(lbl(cred, 'Account #', col=0, row=1),
            'The client account number as it appears in the MT5 comment.\n'
            'E.g. if the comment is  FNFT...7879_CH2  enter  7879.\n'
            'Partial matches work — entering 17879 will also find 7879.')
        self.account_var = tk.StringVar()
        tip(ent(cred, self.account_var, 12),
            'Client account fragment from MT5 comment (before _CH / _FD / _FA / _DD).'
            ).grid(row=1, column=1, padx=(0,8), pady=4, sticky='w')

        tip(lbl(cred, 'Phase', col=2, row=1),
            'Filter deals by phase code:\n'
            '  ALL — return every phase\n'
            '  FA  — Farming (maps to Hedge Day columns)\n'
            '  CH  — Challenge (Hedge Result 1-5)\n'
            '  FD  — Funded (Hedge Result 1.1-5.1)\n'
            '  DD  — Daily Drawdown (Hedge Result 1.1-4.1)')
        self.phase_var = tk.StringVar(value='ALL')
        phase_cb = ctk.CTkComboBox(cred, variable=self.phase_var,
                         values=['ALL', 'FA', 'CH', 'FD', 'DD'],
                         fg_color=self.BG3, border_color=self.BG3,
                         button_color=self.ACCENT, dropdown_fg_color=self.BG2,
                         text_color=self.FG, font=('Segoe UI', 10),
                         width=120, height=32, state='readonly')
        tip(phase_cb, 'FA=Farming  CH=Challenge  FD=Funded  DD=Daily Drawdown\nALL returns every phase.')
        phase_cb.grid(row=1, column=3, padx=(0,8), pady=4, sticky='w')

        tip(lbl(cred, 'Days Back', col=5, row=1),
            'How many calendar days of MT5 history to fetch.\n'
            'Default 365 = one year.  Increase for older deals.')
        self.days_var = tk.StringVar(value='365')
        tip(ent(cred, self.days_var, 6),
            'Number of days to look back in MT5 history (default: 365).'
            ).grid(row=1, column=6, padx=(0,8), pady=4, sticky='w')

        # ── thin divider ──────────────────────────────────────
        div = tk.Frame(self.root, bg=self.BG3, height=1)
        div.pack(fill='x', padx=14, pady=(8, 0))

        # ── reconstruct row ───────────────────────────────────
        rrow = tk.Frame(self.root, bg=self.BG2)
        rrow.pack(fill='x', padx=14, pady=(4, 0))

        tip(tk.Label(rrow, text='From Date', bg=self.BG2, fg=self.FG2, font=('Segoe UI', 9)),
            'Start date for Reconstruct All scan (YYYY-MM-DD).\n'
            'Only used by the ⚡ RECONSTRUCT ALL button.').pack(side='left', padx=(8,4))
        self.from_date_var = tk.StringVar(value='2026-03-15')
        tip(ctk.CTkEntry(rrow, textvariable=self.from_date_var, width=110,
                     fg_color=self.BG3, border_color=self.BG3,
                     text_color=self.FG, font=('Consolas', 11),
                     corner_radius=6, height=30),
            'Start date — format: YYYY-MM-DD').pack(side='left', padx=(0,12))

        tip(tk.Label(rrow, text='To Date', bg=self.BG2, fg=self.FG2, font=('Segoe UI', 9)),
            'End date for Reconstruct All scan (YYYY-MM-DD).\n'
            'Defaults to today.').pack(side='left', padx=(0,4))
        self.to_date_var = tk.StringVar(value=datetime.now().strftime('%Y-%m-%d'))
        tip(ctk.CTkEntry(rrow, textvariable=self.to_date_var, width=110,
                     fg_color=self.BG3, border_color=self.BG3,
                     text_color=self.FG, font=('Consolas', 11),
                     corner_radius=6, height=30),
            'End date — format: YYYY-MM-DD').pack(side='left', padx=(0,12))

        tip(tk.Label(rrow, text='(Uses same Login / Password / Server above — no Account # needed)',
                 bg=self.BG2, fg=self.FG2, font=('Segoe UI', 9)),
            'Reconstruct All ignores the Account # field — it parses every comment on the MT5 account.'
            ).pack(side='left', padx=4)

        self.recon_btn = ctk.CTkButton(rrow, text='⚡  RECONSTRUCT ALL',
                                        fg_color=self.ACCENT2, hover_color='#2db87a',
                                        text_color='#0f1117', font=('Segoe UI', 11, 'bold'),
                                        corner_radius=8, height=36, width=190,
                                        command=self._on_reconstruct_all)
        tip(self.recon_btn,
            'Fetch ALL deals between From Date and To Date.\n'
            'Parses every MT5 comment and groups results by\n'
            'Prop Firm → Account → Phase → Hedge Day.\n'
            'No Account # needed — finds everything automatically.')
        self.recon_btn.pack(side='right', padx=(0,8), pady=4)

        # ── status strip ──────────────────────────────────────
        self.status_var = tk.StringVar(
            value='Ready.  Use FETCH DEALS for one account, or RECONSTRUCT ALL for everything.')
        stat = tk.Frame(self.root, bg=self.BG, height=24)
        stat.pack(fill='x', padx=0, pady=(4,0))
        tk.Label(stat, textvariable=self.status_var,
                 bg=self.BG, fg=self.WARN,
                 font=('Segoe UI', 9, 'italic'), anchor='w').pack(fill='x', padx=16)

        # ── notebook tabs ─────────────────────────────────────
        self._build_results_panel()

    # ══════════════════════════════════════════════════════════
    def _build_results_panel(self):
        nb_frame = tk.Frame(self.root, bg=self.BG)
        nb_frame.pack(fill='both', expand=True, padx=14, pady=(6, 10))

        self.notebook = ttk.Notebook(nb_frame)
        style = ttk.Style()
        style.configure('TNotebook', background=self.BG, borderwidth=0)
        style.configure('TNotebook.Tab',
                        background=self.BG2, foreground=self.FG2,
                        font=('Segoe UI', 9, 'bold'), padding=[14, 5])
        style.map('TNotebook.Tab',
                  background=[('selected', self.BG3)],
                  foreground=[('selected', self.FG)])
        self.notebook.pack(fill='both', expand=True)

        # Tab 1 – Summary
        f1 = tk.Frame(self.notebook, bg=self.BG3)
        self.notebook.add(f1, text='  Summary  ')
        self.summary_text = tk.Text(f1, wrap='word', bg=self.BG3, fg=self.FG,
                                     font=('Consolas', 10), insertbackground=self.FG,
                                     state='disabled', relief='flat', padx=14, pady=10,
                                     selectbackground=self.SEL)
        self.summary_text.pack(fill='both', expand=True)

        # Tab 2 – Phase Breakdown
        f2 = tk.Frame(self.notebook, bg=self.BG3)
        self.notebook.add(f2, text='  Phase Breakdown  ')
        self._build_tree(f2, 'phase_tree',
                         ('phase','field','deals','days','net_pl'),
                         ('Phase','Dashboard Field','Deals','Days','Net P/L'),
                         (80,220,70,70,110))

        # Tab 3 – Hedge Days
        f3 = tk.Frame(self.notebook, bg=self.BG3)
        self.notebook.add(f3, text='  Hedge Days  ')
        self._build_tree(f3, 'daily_tree',
                         ('hd','date','deals','net_pl'),
                         ('Hedge Day','Date','Deals','Net P/L'),
                         (120,140,70,130))

        # Tab 4 – All Deals
        f4 = tk.Frame(self.notebook, bg=self.BG3)
        self.notebook.add(f4, text='  All Deals  ')
        self._build_tree(f4, 'deals_tree',
                         ('hd','time','ticket','symbol','dir','entry','vol','price','profit','comment'),
                         ('Hedge Day','Time','Ticket','Symbol','Dir','Entry','Volume','Price','Profit','Comment'),
                         (100,155,100,90,55,55,70,115,95,260))

        # Tab 5 – Open Positions
        f5 = tk.Frame(self.notebook, bg=self.BG3)
        self.notebook.add(f5, text='  Open Positions  ')
        self._build_tree(f5, 'open_tree',
                         ('symbol','type','vol','price','profit','swap','comment'),
                         ('Symbol','Type','Volume','Open Price','Profit','Swap','Comment'),
                         (110,65,85,130,110,90,310))

        # Tab 6 – Reconstruct All
        f6 = tk.Frame(self.notebook, bg=self.BG3)
        self.notebook.add(f6, text='  ⚡  Reconstruct All  ')
        self._build_reconstruct_tab(f6)

        # Tab 7 – Push to Dashboard
        f7 = tk.Frame(self.notebook, bg=self.BG3)
        self.notebook.add(f7, text='  🚀  Push to Dashboard  ')
        self._build_push_tab(f7)

    # ══════════════════════════════════════════════════════════
    def _build_reconstruct_tab(self, parent):
        # Vertical split: full-width tree on top, deal detail below
        vpane = tk.PanedWindow(parent, orient='vertical',
                               bg=self.BG, sashwidth=6, sashrelief='flat', sashpad=0)
        vpane.pack(fill='both', expand=True)

        # ── TOP: toolbar + full-width treeview ────────────────
        top = tk.Frame(vpane, bg=self.BG3)
        vpane.add(top, minsize=400, stretch='always')

        # toolbar
        tb = tk.Frame(top, bg=self.BG2, height=40)
        tb.pack(fill='x')
        tb.pack_propagate(False)

        tk.Label(tb, text='Filter:', bg=self.BG2, fg=self.FG2,
                 font=('Segoe UI', 9)).pack(side='left', padx=(12, 4), pady=8)
        self.recon_filter_var = tk.StringVar()
        fe = ctk.CTkEntry(tb, textvariable=self.recon_filter_var, width=200,
                          fg_color=self.BG3, border_color=self.BG3,
                          text_color=self.FG, font=('Consolas', 10),
                          corner_radius=6, height=28)
        fe.pack(side='left', padx=(0, 12), pady=6)
        fe.bind('<KeyRelease>', self._on_recon_filter)

        self.recon_count_var = tk.StringVar(value='')
        tk.Label(tb, textvariable=self.recon_count_var,
                 bg=self.BG2, fg=self.FG2, font=('Segoe UI', 9)).pack(side='right', padx=14)

        self.recon_export_btn = ctk.CTkButton(
            tb, text='💾  Export CSV',
            fg_color=self.BG3, hover_color=self.BG,
            text_color=self.FG2, font=('Segoe UI', 9, 'bold'),
            corner_radius=6, height=28, width=130, state='disabled',
            command=self._on_export_recon)
        self.recon_export_btn.pack(side='right', padx=(0, 8), pady=6)

        # full-width treeview — columns stretch to fill
        style = ttk.Style()
        style.configure('Recon.Treeview',
                        background=self.BG3, foreground=self.FG,
                        fieldbackground=self.BG3, font=('Consolas', 10), rowheight=30)
        style.configure('Recon.Treeview.Heading',
                        background='#1e2235', foreground=self.ACCENT,
                        font=('Segoe UI', 10, 'bold'), relief='flat', padding=(8, 6))
        style.map('Recon.Treeview',
                  background=[('selected', '#2d3a55')],
                  foreground=[('selected', '#ffffff')])

        cols     = ('firm', 'account', 'phase', 'field', 'deals', 'net_pl', 'date_range', 'comment')
        headings = ('Firm', 'Account', 'Phase', 'Dashboard Field', 'Deals', 'Net P/L', 'Date Range', 'Sample Comment')
        widths   = (160, 110, 80, 250, 70, 120, 200, 400)
        stretches= (False, False, False, True, False, False, False, True)

        tc = tk.Frame(top, bg=self.BG3)
        tc.pack(fill='both', expand=True, padx=4, pady=4)

        self.recon_tree = ttk.Treeview(tc, columns=cols, show='headings',
                                        style='Recon.Treeview', selectmode='browse')
        for col, heading, width, stretch in zip(cols, headings, widths, stretches):
            self.recon_tree.heading(col, text=heading,
                                     command=lambda c=col: self._recon_sort(c))
            anchor = 'e' if col in ('deals', 'net_pl') else 'w'
            if stretch:
                self.recon_tree.column(col, width=width, anchor=anchor, minwidth=100, stretch=True)
            else:
                self.recon_tree.column(col, width=width, anchor=anchor, minwidth=40, stretch=False)

        vsb = ttk.Scrollbar(tc, orient='vertical',   command=self.recon_tree.yview)
        hsb = ttk.Scrollbar(tc, orient='horizontal',  command=self.recon_tree.xview)
        self.recon_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.recon_tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        tc.grid_rowconfigure(0, weight=1)
        tc.grid_columnconfigure(0, weight=1)

        # row colour tags
        self.recon_tree.tag_configure('firm_row',
                                       font=('Segoe UI', 11, 'bold'),
                                       foreground='#e2e8f0',
                                       background='#1e2235')
        self.recon_tree.tag_configure('acct_row',
                                       font=('Segoe UI', 10, 'bold'),
                                       foreground=self.ACCENT,
                                       background='#1a2030')
        self.recon_tree.tag_configure('pos',  foreground=self.GOOD)
        self.recon_tree.tag_configure('neg',  foreground=self.BAD)
        self.recon_tree.tag_configure('zero', foreground=self.FG2)
        self.recon_tree.bind('<<TreeviewSelect>>', self._on_recon_select)

        # ── BOTTOM: deal detail panel ─────────────────────────
        bottom = tk.Frame(vpane, bg=self.BG2)
        vpane.add(bottom, minsize=140, stretch='never')

        hdr = tk.Frame(bottom, bg='#1e2235', height=32)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)
        tk.Label(hdr, text='  Deal Detail', bg='#1e2235', fg=self.ACCENT,
                 font=('Segoe UI', 10, 'bold')).pack(side='left', pady=6)

        dw = tk.Frame(bottom, bg=self.BG3)
        dw.pack(fill='both', expand=True)

        self.recon_detail = tk.Text(dw, wrap='none', bg=self.BG3, fg=self.FG,
                                     font=('Consolas', 10), insertbackground=self.FG,
                                     state='disabled', relief='flat', padx=14, pady=8,
                                     selectbackground=self.SEL)
        dvsb = ttk.Scrollbar(dw, orient='vertical',   command=self.recon_detail.yview)
        dhsb = ttk.Scrollbar(dw, orient='horizontal',  command=self.recon_detail.xview)
        self.recon_detail.configure(yscrollcommand=dvsb.set, xscrollcommand=dhsb.set)
        self.recon_detail.grid(row=0, column=0, sticky='nsew')
        dvsb.grid(row=0, column=1, sticky='ns')
        dhsb.grid(row=1, column=0, sticky='ew')
        dw.grid_rowconfigure(0, weight=1)
        dw.grid_columnconfigure(0, weight=1)

    # ══════════════════════════════════════════════════════════
    def _build_tree(self, parent, attr_name, cols, headings, widths):
        c = tk.Frame(parent, bg=self.BG3)
        c.pack(fill='both', expand=True)
        tree = ttk.Treeview(c, columns=cols, show='headings', style='T.Treeview')
        for col, heading, width in zip(cols, headings, widths):
            tree.heading(col, text=heading)
            anchor = 'e' if col in ('deals','days','net_pl','vol','price','profit','swap') else 'w'
            tree.column(col, width=width, anchor=anchor, minwidth=40)
        vsb = ttk.Scrollbar(c, orient='vertical',   command=tree.yview)
        hsb = ttk.Scrollbar(c, orient='horizontal',  command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        c.grid_rowconfigure(0, weight=1)
        c.grid_columnconfigure(0, weight=1)
        setattr(self, attr_name, tree)



    def _toggle_help(self):
        if self._help_open.get():
            self._help_frame.pack_forget()
            self._help_open.set(False)
        else:
            # Insert after header (before cred card)
            self._help_frame.pack(fill='x', after=self.root.winfo_children()[0])
            self._help_open.set(True)

    def _toggle_password(self):
        self.pass_entry.configure(show='' if self.show_pass_var.get() else '●')

    def _on_reconstruct_all(self):
        mt5_login = self.mt5_login_var.get().strip()
        mt5_pass = self.mt5_pass_var.get().strip()
        mt5_server = self.mt5_server_var.get().strip()
        from_date = self.from_date_var.get().strip()
        to_date = self.to_date_var.get().strip()

        if not mt5_login or not mt5_pass or not mt5_server:
            messagebox.showwarning("Missing Input", "Enter MT5 Login, Password, and Server first.")
            return

        self.recon_btn.configure(state='disabled', text='Fetching...')
        self.recon_export_btn.configure(state='disabled')

        def run():
            result = fetch_all_deals_from_mt5(
                mt5_login, mt5_pass, mt5_server, from_date, to_date,
                progress_cb=lambda msg: self.root.after(0, lambda: self.status_var.set(msg))
            )
            self.root.after(0, lambda: self._display_reconstruct_results(result))

        threading.Thread(target=run, daemon=True).start()

    def _display_reconstruct_results(self, result):
        self.recon_btn.configure(state='normal', text='⚡  RECONSTRUCT ALL')
        self._recon_data = result

        error = result.get('error')
        if error:
            self.status_var.set(f'Reconstruct error: {error}')
            messagebox.showerror('Reconstruct Error', error)
            return

        flat_rows = result.get('flat_rows', [])
        total = result.get('total_deals', 0)
        parsed = result.get('parsed_deals', 0)
        unparseable = result.get('unparseable_count', 0)
        acct = result.get('account_info', {})

        # Store all phase-level rows for filter/sort
        self._recon_all_rows = [r for r in flat_rows if r['level'] == 'phase']
        self._recon_populate_tree(self._recon_all_rows)

        self.recon_export_btn.configure(state='normal')
        n_accts = len(set(r['account'] for r in self._recon_all_rows))
        n_firms = len(set(r['firm'] for r in self._recon_all_rows))
        msg = (f"Reconstruct: {total} raw deals | {parsed} parsed | "
               f"{n_firms} firms | {n_accts} accounts | "
               f"{len(self._recon_all_rows)} sessions | {unparseable} unparseable comment types")
        self.status_var.set(msg)
        self.recon_count_var.set(f"{len(self._recon_all_rows)} sessions")
        self.notebook.select(5)  # Reconstruct All is tab index 5

    def _recon_populate_tree(self, rows):
        """Populate the reconstruct treeview from a list of phase rows."""
        self.recon_tree.delete(*self.recon_tree.get_children())

        # Group by firm then account for display
        from collections import OrderedDict
        grouped = OrderedDict()
        for row in rows:
            firm = row['firm']
            acct = row['account']
            grouped.setdefault(firm, OrderedDict()).setdefault(acct, []).append(row)

        for firm, accts in grouped.items():
            firm_total_deals = sum(r['deal_count'] for rows_list in accts.values() for r in rows_list)
            firm_total_pl = sum(r['net_pl'] for rows_list in accts.values() for r in rows_list)

            firm_iid = self.recon_tree.insert('', 'end', values=(
                firm, f"({len(accts)} accounts)", '', '',
                firm_total_deals, f"${firm_total_pl:+,.2f}", '', ''),
                tags=('firm_row',), open=True)

            for acct, phase_rows in accts.items():
                acct_pl = sum(r['net_pl'] for r in phase_rows)
                acct_deals = sum(r['deal_count'] for r in phase_rows)
                acct_iid = self.recon_tree.insert(firm_iid, 'end', values=(
                    '', acct, f"({len(phase_rows)} phases)", '',
                    acct_deals, f"${acct_pl:+,.2f}", '', ''),
                    tags=('acct_row',), open=True)

                for row in sorted(phase_rows, key=lambda x: x['phase_key']):
                    pl = row['net_pl']
                    tag = 'pos' if pl > 0.01 else ('neg' if pl < -0.01 else 'zero')
                    idx = self._recon_all_rows.index(row) if row in self._recon_all_rows else -1
                    # grab first raw comment as sample
                    sample_comment = ''
                    if row.get('deals'):
                        sample_comment = row['deals'][0].get('comment', '')
                    self.recon_tree.insert(acct_iid, 'end', iid=str(idx), values=(
                        '', '', row['phase_key'], row['field'],
                        row['deal_count'], f"${pl:+,.2f}", row['date_range'],
                        sample_comment),
                        tags=(tag,), open=True)

    def _on_recon_filter(self, event=None):
        q = self.recon_filter_var.get().strip().upper()
        if not q:
            filtered = self._recon_all_rows
        else:
            filtered = [r for r in self._recon_all_rows
                        if q in r['firm'].upper() or q in r['account'].upper()
                        or q in r['phase_key'].upper() or q in r['field'].upper()]
        self._recon_populate_tree(filtered)
        self.recon_count_var.set(f"{len(filtered)} sessions")

    def _recon_sort(self, col):
        """Sort reconstruct tree by column."""
        col_map = {'firm': 'firm', 'account': 'account', 'phase': 'phase_key',
                   'field': 'field', 'deals': 'deal_count', 'net_pl': 'net_pl', 'date_range': 'date_range'}
        key = col_map.get(col, col)
        reverse = getattr(self, '_recon_sort_rev', {}).get(col, False)
        self._recon_all_rows.sort(key=lambda r: r.get(key, ''), reverse=reverse)
        if not hasattr(self, '_recon_sort_rev'): self._recon_sort_rev = {}
        self._recon_sort_rev[col] = not reverse
        self._recon_populate_tree(self._recon_all_rows)

    def _on_recon_select(self, event=None):
        sel = self.recon_tree.selection()
        if not sel:
            return
        iid = sel[0]
        try:
            idx = int(iid)
        except ValueError:
            return  # firm or account header row
        if idx < 0 or idx >= len(self._recon_all_rows):
            return

        row = self._recon_all_rows[idx]
        deals = row.get('deals', [])
        daily = row.get('daily', {})
        sorted_dates = row.get('sorted_dates', [])
        date_to_hd = row.get('date_to_hd', {})
        phase = row.get('phase_key', '')
        field = row.get('field', '')

        lines = []
        lines.append(f"{'='*60}")
        lines.append(f"Firm:       {row['firm']}")
        lines.append(f"Account:    {row['account']}")
        lines.append(f"Phase:      {phase}  →  Dashboard Field: {field}")
        lines.append(f"Date Range: {row['date_range']}")
        lines.append(f"Deals:      {row['deal_count']}   Net P/L: ${row['net_pl']:+,.2f}")
        lines.append(f"{'='*60}")

        if row.get('date_to_hd'):
            # FA phase — show per hedge day breakdown
            lines.append(f"\nHEDGE DAY BREAKDOWN (Farming):")
            lines.append(f"  {'Day':<10} {'Date':<14} {'Deals':>6} {'Net P/L':>12}")
            lines.append(f"  {'-'*44}")
            for date in sorted_dates:
                hd = date_to_hd.get(date, '?')
                day_deals = daily.get(date, [])
                day_pl = sum(d['_profit'] for d in day_deals)
                lines.append(f"  Hedge Day {hd:<2}  {date:<14} {len(day_deals):>6} ${day_pl:>+10,.2f}")
        else:
            # CH/FD — show per-date breakdown
            lines.append(f"\nDATE BREAKDOWN:")
            lines.append(f"  {'Date':<14} {'Deals':>6} {'Net P/L':>12}")
            lines.append(f"  {'-'*34}")
            for date in sorted_dates:
                day_deals = daily.get(date, [])
                day_pl = sum(d['_profit'] for d in day_deals)
                lines.append(f"  {date:<14} {len(day_deals):>6} ${day_pl:>+10,.2f}")

        lines.append(f"\nALL DEALS:")
        lines.append(f"  {'Date':<12} {'Time':<10} {'Ticket':<12} {'Symbol':<10} {'Dir':<5} {'Entry':<6} {'Vol':>6} {'Profit':>12}  Comment")
        lines.append(f"  {'-'*105}")
        for d in deals:
            ts_full = datetime.fromtimestamp(d['time'])
            date_str = ts_full.strftime('%Y-%m-%d')
            time_str = ts_full.strftime('%H:%M:%S')
            direction = DEAL_TYPE_MAP.get(d.get('type', -1), str(d.get('type')))
            entry = ENTRY_MAP.get(d.get('entry', -1), str(d.get('entry')))
            raw_comment = d.get('comment', '')
            lines.append(f"  {date_str:<12} {time_str:<10} {str(d.get('ticket','')):<12} "
                         f"{str(d.get('symbol','')):<10} {direction:<5} {entry:<6} "
                         f"{d.get('volume',0):>6.2f} ${d['_profit']:>+10,.2f}  {raw_comment}")

        self.recon_detail.configure(state='normal')
        self.recon_detail.delete('1.0', 'end')
        self.recon_detail.insert('end', '\n'.join(lines))
        self.recon_detail.configure(state='disabled')

    def _on_export_recon(self):
        if not self._recon_all_rows:
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.csv',
            filetypes=[('CSV Files', '*.csv'), ('All Files', '*.*')],
            initialfile=f"mt5_reconstruct_{self.from_date_var.get()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        if not path:
            return

        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Firm', 'Account', 'Phase', 'Dashboard Field',
                             'Date', 'Hedge Day', 'Time', 'Ticket', 'Symbol',
                             'Direction', 'Entry', 'Volume', 'Price',
                             'Profit', 'Commission', 'Swap', 'Net P/L', 'Comment'])
            for row in self._recon_all_rows:
                for d in row.get('deals', []):
                    ts = datetime.fromtimestamp(d['time'])
                    date_key = ts.strftime('%Y-%m-%d')
                    hd = row['date_to_hd'].get(date_key, '') if row.get('date_to_hd') else ''
                    writer.writerow([
                        row['firm'], row['account'], row['phase_key'], row['field'],
                        date_key, f"Hedge Day {hd}" if hd else row['phase_key'],
                        ts.strftime('%H:%M:%S'), d.get('ticket', ''), d.get('symbol', ''),
                        DEAL_TYPE_MAP.get(d.get('type', -1), ''),
                        ENTRY_MAP.get(d.get('entry', -1), ''),
                        d.get('volume', 0), d.get('price', 0),
                        d.get('profit', 0), d.get('commission', 0), d.get('swap', 0),
                        d['_profit'], d.get('comment', ''),
                    ])

        n = sum(r['deal_count'] for r in self._recon_all_rows)
        self.status_var.set(f"Exported {n} deals to {os.path.basename(path)}")
        messagebox.showinfo("Export Complete", f"Saved to:\n{path}")

    def _on_fetch(self):
        mt5_login = self.mt5_login_var.get().strip()
        mt5_pass = self.mt5_pass_var.get().strip()
        mt5_server = self.mt5_server_var.get().strip()
        account = self.account_var.get().strip()
        phase = self.phase_var.get()
        days_str = self.days_var.get().strip()

        if not mt5_login or not mt5_pass or not mt5_server:
            messagebox.showwarning("Missing Input", "Enter MT5 Login, Password, and Server.")
            return
        if not account:
            messagebox.showwarning("Missing Input", "Enter the Account Number to search for.")
            return
        try:
            days = int(days_str)
        except ValueError:
            messagebox.showwarning("Invalid Input", "Days Back must be a number.")
            return

        # Disable fetch button during operation
        self.fetch_btn.configure(state='disabled', text='Fetching...')
        self.export_btn.configure(state='disabled')

        def run():
            result = fetch_mt5_data(
                mt5_login, mt5_pass, mt5_server, account,
                phase if phase != 'ALL' else None, days,
                progress_cb=lambda msg: self.root.after(0, lambda: self.status_var.set(msg))
            )
            self.root.after(0, lambda: self._display_results(result))

        threading.Thread(target=run, daemon=True).start()

    def _display_results(self, result):
        self.fetch_btn.configure(state='normal', text='🔍  FETCH DEALS')
        self.result_data = result

        # Clear all
        self._clear_tree(self.phase_tree)
        self._clear_tree(self.daily_tree)
        self._clear_tree(self.deals_tree)
        self._clear_tree(self.open_tree)
        self.summary_text.configure(state='normal')
        self.summary_text.delete('1.0', 'end')

        error = result.get('error')
        acct = result.get('account_info', {})

        if error and not result.get('matched'):
            self.status_var.set(f"Error: {error}")
            self.summary_text.insert('end', f"ERROR: {error}\n\n")
            if acct:
                self.summary_text.insert('end', f"MT5 Account: {acct.get('name', '')} | "
                                                  f"Balance: ${acct.get('balance', 0):,.2f} | "
                                                  f"Equity: ${acct.get('equity', 0):,.2f}\n\n")
            other = result.get('other_accounts', [])
            if other:
                self.summary_text.insert('end', f"Other accounts found on this MT5:\n  {', '.join(other)}\n")
                self.summary_text.insert('end', f"\nTotal deals on MT5: {result.get('total_deals', 0)}\n")
            self.summary_text.configure(state='disabled')
            return

        matched = result['matched']
        daily = result['daily']
        sorted_dates = result['sorted_dates']
        date_to_hd = result['date_to_hd']
        phase_summary = result['phase_summary']
        open_pos = result.get('open_positions', [])

        # Status
        self.status_var.set(f"Found {len(matched)} deals across {len(sorted_dates)} trading days.")
        self.export_btn.configure(state='normal')

        # ── Summary tab ─────────────────────────────────────────
        lines = []
        if acct:
            lines.append(f"MT5 Account : {acct.get('name', '')} (Login: {acct.get('login', '')})")
            lines.append(f"Balance     : ${acct.get('balance', 0):,.2f}")
            lines.append(f"Equity      : ${acct.get('equity', 0):,.2f}")
            lines.append("")

        lines.append(f"Search Account : {self.account_var.get().strip()}")
        lines.append(f"Phase Filter   : {self.phase_var.get()}")
        lines.append(f"Matched Deals  : {len(matched)}")
        lines.append(f"Trading Days   : {len(sorted_dates)}")
        if sorted_dates:
            lines.append(f"Date Range     : {sorted_dates[0]} → {sorted_dates[-1]}")
        lines.append("")

        total_profit = sum(d['_profit'] for d in matched)
        lines.append(f"Total Net P/L  : ${total_profit:+,.2f}")
        lines.append("")

        if open_pos:
            lines.append(f"Open Positions : {len(open_pos)}")
            open_pl = sum(p.get('profit', 0) for p in open_pos)
            lines.append(f"Open P/L       : ${open_pl:+,.2f}")

        self.summary_text.insert('end', '\n'.join(lines))
        self.summary_text.configure(state='disabled')

        # ── Phase Breakdown tab ─────────────────────────────────
        total_deals = 0
        total_pl = 0.0
        is_mffu = any(str(d.get('comment', '')).upper().startswith('MFFU') for d in matched)
        for key in sorted(phase_summary.keys()):
            info = phase_summary[key]
            parsed_phase = key[:2]
            parsed_num = int(key[2:]) if key[2:] else 1
            field = phase_to_field(parsed_phase, parsed_num, is_mffu=is_mffu)
            total_deals += info['count']
            total_pl += info['profit']
            self.phase_tree.insert('', 'end', values=(
                key, field, info['count'], len(info['days']), f"${info['profit']:+,.2f}"))
        # Total row
        self.phase_tree.insert('', 'end', values=(
            'TOTAL', '', total_deals, len(sorted_dates), f"${total_pl:+,.2f}"),
            tags=('total',))
        self.phase_tree.tag_configure('total', font=('Consolas', 9, 'bold'))

        # ── Hedge Days tab ──────────────────────────────────────
        for day_num, date_key in enumerate(sorted_dates, start=1):
            day_deals = daily[date_key]
            day_profit = sum(d['_profit'] for d in day_deals)
            self.daily_tree.insert('', 'end', values=(
                f"Hedge Day {day_num}", date_key, len(day_deals), f"${day_profit:+,.2f}"))

        # ── All Deals tab ───────────────────────────────────────
        for d in matched:
            ts = datetime.fromtimestamp(d['time']).strftime('%Y-%m-%d %H:%M:%S')
            date_key = datetime.fromtimestamp(d['time']).strftime('%Y-%m-%d')
            hd = f"Hedge Day {date_to_hd.get(date_key, '?')}"
            direction = DEAL_TYPE_MAP.get(d.get('type', -1), f"TYPE_{d.get('type', -1)}")
            entry = ENTRY_MAP.get(d.get('entry', -1), f"E_{d.get('entry', -1)}")
            self.deals_tree.insert('', 'end', values=(
                hd, ts, d.get('ticket', ''), d.get('symbol', ''),
                direction, entry, f"{d.get('volume', 0):.2f}",
                f"{d.get('price', 0):.5f}", f"${d['_profit']:+,.2f}",
                d.get('comment', '')))

        # ── Open Positions tab ──────────────────────────────────
        for p in open_pos:
            ptype = "BUY" if p.get('type', 0) == 0 else "SELL"
            self.open_tree.insert('', 'end', values=(
                p.get('symbol', ''), ptype, f"{p.get('volume', 0):.2f}",
                f"{p.get('price_open', 0):.5f}", f"${p.get('profit', 0):+,.2f}",
                f"${p.get('swap', 0):+,.2f}", p.get('comment', '')))

        # Switch to summary tab
        self.notebook.select(0)

    def _clear_tree(self, tree):
        for item in tree.get_children():
            tree.delete(item)

    def _on_export(self):
        if not self.result_data or not self.result_data.get('matched'):
            return

        path = filedialog.asksaveasfilename(
            defaultextension='.csv',
            filetypes=[('CSV Files', '*.csv'), ('All Files', '*.*')],
            initialfile=f"mt5_recovery_{self.account_var.get().strip()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        if not path:
            return

        matched = self.result_data['matched']
        date_to_hd = self.result_data['date_to_hd']

        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Hedge Day', 'Date', 'Time', 'Ticket', 'Symbol', 'Direction',
                             'Entry', 'Volume', 'Price', 'Profit', 'Commission', 'Swap',
                             'Phase', 'Phase Number', 'Dashboard Field', 'Comment'])
            for d in matched:
                ts = datetime.fromtimestamp(d['time'])
                date_key = ts.strftime('%Y-%m-%d')
                hd_num = date_to_hd.get(date_key, 0)
                p = d['_parsed']
                is_mffu = str(d.get('comment', '')).upper().startswith('MFFU')
                field = phase_to_field(p['phase'], p['number'], is_mffu=is_mffu)
                writer.writerow([
                    f"Hedge Day {hd_num}", date_key, ts.strftime('%H:%M:%S'),
                    d.get('ticket', ''), d.get('symbol', ''),
                    DEAL_TYPE_MAP.get(d.get('type', -1), ''),
                    ENTRY_MAP.get(d.get('entry', -1), ''),
                    d.get('volume', 0), d.get('price', 0),
                    d['_profit'], d.get('commission', 0), d.get('swap', 0),
                    p['phase'], p['number'], field, d.get('comment', ''),
                ])

        self.status_var.set(f"Exported {len(matched)} deals to {os.path.basename(path)}")
        messagebox.showinfo("Export Complete", f"Saved to:\n{path}")

    # ══════════════════════════════════════════════════════════
    def _build_push_tab(self, parent):
        """Tab 7 — Push recovered deals to the live dashboard (mirrors trader companion)."""
        self._push_client_info = None   # stores /auth identity response

        # ── Row 1: Dashboard URL ──────────────────────────────
        r1 = tk.Frame(parent, bg=self.BG2)
        r1.pack(fill='x', padx=12, pady=(10, 4))
        tk.Label(r1, text='Dashboard URL', bg=self.BG2, fg=self.FG2,
                 font=('Segoe UI', 9)).pack(side='left', padx=(8, 4))
        self.push_url_var = tk.StringVar(value='https://www.tradeopss.com')
        url_e = ctk.CTkEntry(r1, textvariable=self.push_url_var, width=340,
                             fg_color=self.BG3, border_color=self.BG3,
                             text_color=self.FG, font=('Consolas', 10),
                             corner_radius=6, height=30)
        Tooltip(url_e,
                'Dashboard base URL.\n'
                'Use http://localhost:5000 for local testing,\n'
                'or https://www.tradeopss.com for production.\n'
                'No trailing slash.')
        url_e.pack(side='left', padx=(0, 8))

        # ── Row 2: Email + Lookup button + Push button ────────
        r2 = tk.Frame(parent, bg=self.BG2)
        r2.pack(fill='x', padx=12, pady=(0, 4))
        tk.Label(r2, text='Client Email', bg=self.BG2, fg=self.FG2,
                 font=('Segoe UI', 9)).pack(side='left', padx=(8, 4))
        self.push_email_var = tk.StringVar()
        email_e = ctk.CTkEntry(r2, textvariable=self.push_email_var, width=260,
                               fg_color=self.BG3, border_color=self.BG3,
                               text_color=self.FG, font=('Consolas', 10),
                               corner_radius=6, height=30)
        Tooltip(email_e,
                'The client\'s email registered on the dashboard.\n'
                'Used to find which evaluation rows belong to them.\n'
                'You must click "Lookup Client" before pushing.')
        email_e.pack(side='left', padx=(0, 8))

        lookup_btn = ctk.CTkButton(
            r2, text='🔍  Lookup Client',
            fg_color='#0f4c75', hover_color='#1b6ca8',
            text_color='#ffffff', font=('Segoe UI', 10, 'bold'),
            corner_radius=8, height=32, width=150,
            command=self._on_push_lookup)
        Tooltip(lookup_btn,
                'Verify the client email exists on the dashboard.\n'
                'This retrieves their hierarchy (Client → Trader → Admin).\n'
                'The Push button is enabled only after a successful lookup.')
        lookup_btn.pack(side='left', padx=(0, 12))

        self.push_btn = ctk.CTkButton(
            r2, text='🚀  PUSH TO DASHBOARD',
            fg_color='#555555', hover_color='#555555',
            text_color='#aaaaaa', font=('Segoe UI', 11, 'bold'),
            corner_radius=8, height=32, width=210,
            state='disabled',
            command=self._on_push_to_dashboard)
        Tooltip(self.push_btn,
                'Push all fetched deals to the dashboard.\n\n'
                'Steps:\n'
                '  1. Run FETCH DEALS to load MT5 data for the account.\n'
                '  2. Enter client email and click Lookup Client.\n'
                '  3. Click this button.\n\n'
                'What gets pushed:\n'
                '  • Hedge Result fields for CH / FD / DD phases\n'
                '  • Hedge Day fields for FA (Farming) — latest day only\n'
                '  • Open / Close timestamps stored as companion notes\n'
                '  • Auto-runs Hedging Review push after success')
        self.push_btn.pack(side='left', padx=(0, 8))

        # ── Hierarchy / status label ──────────────────────────
        self.push_hierarchy_var = tk.StringVar(
            value='Enter client email and click Lookup Client to begin.')
        self.push_hierarchy_lbl = tk.Label(
            parent, textvariable=self.push_hierarchy_var,
            bg=self.BG2, fg=self.FG2, font=('Segoe UI', 9, 'italic'),
            anchor='w', padx=16, pady=4)
        self.push_hierarchy_lbl.pack(fill='x')

        # ── Divider ───────────────────────────────────────────
        tk.Frame(parent, bg=self.BG3, height=1).pack(fill='x', padx=12, pady=(2, 0))

        # ── Push log ──────────────────────────────────────────
        log_hdr = tk.Frame(parent, bg='#1e2235', height=30)
        log_hdr.pack(fill='x', padx=12, pady=(4, 0))
        log_hdr.pack_propagate(False)
        tk.Label(log_hdr, text='  Push Log', bg='#1e2235', fg=self.ACCENT,
                 font=('Segoe UI', 9, 'bold')).pack(side='left', pady=5)
        ctk.CTkButton(log_hdr, text='Clear', fg_color='#1e2235', hover_color=self.BG3,
                      text_color=self.FG2, font=('Segoe UI', 8), corner_radius=4,
                      height=22, width=50,
                      command=lambda: self._push_log('', clear=True)
                      ).pack(side='right', padx=8, pady=4)

        log_wrap = tk.Frame(parent, bg=self.BG3)
        log_wrap.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        self.push_log_text = tk.Text(
            log_wrap, wrap='word', bg=self.BG3, fg=self.FG,
            font=('Consolas', 9), relief='flat', padx=10, pady=8,
            state='disabled', selectbackground=self.SEL,
            insertbackground=self.FG)
        self.push_log_text.tag_configure('ok',   foreground=self.GOOD)
        self.push_log_text.tag_configure('warn', foreground=self.WARN)
        self.push_log_text.tag_configure('err',  foreground=self.BAD)
        self.push_log_text.tag_configure('info', foreground=self.FG2)
        vsb = ttk.Scrollbar(log_wrap, orient='vertical', command=self.push_log_text.yview)
        self.push_log_text.configure(yscrollcommand=vsb.set)
        self.push_log_text.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

    # ── Lookup ────────────────────────────────────────────────
    def _on_push_lookup(self):
        """POST /api/client/auth — mirrors companion's lookup_client."""
        import requests as _req
        url   = self.push_url_var.get().strip().rstrip('/')
        email = self.push_email_var.get().strip()
        if not url:
            messagebox.showwarning('Missing', 'Enter the Dashboard URL.'); return
        if not email:
            messagebox.showwarning('Missing', 'Enter the client email.'); return

        self.push_hierarchy_var.set('Looking up client…')
        self.push_hierarchy_lbl.configure(fg=self.FG2)
        self._push_client_info = None
        # Disable push button while looking up
        self.push_btn.configure(state='disabled', fg_color='#555555',
                                hover_color='#555555', text_color='#aaaaaa')
        self._push_log(f'🔍 Looking up: {email} @ {url}')

        def _run():
            try:
                resp = _req.post(
                    f'{url}/api/client/auth',
                    json={'email': email},
                    headers={'Content-Type': 'application/json'},
                    timeout=30)
                self.root.after(0, lambda: self._handle_lookup_response(resp))
            except _req.exceptions.Timeout:
                self.root.after(0, lambda: self._lookup_fail('Connection timeout'))
            except _req.exceptions.ConnectionError:
                self.root.after(0, lambda: self._lookup_fail('Cannot connect to server'))
            except Exception as ex:
                self.root.after(0, lambda: self._lookup_fail(str(ex)))

        threading.Thread(target=_run, daemon=True).start()

    def _handle_lookup_response(self, resp):
        try:
            data = resp.json()
        except Exception:
            self._lookup_fail(f'HTTP {resp.status_code} — invalid JSON'); return

        if resp.status_code == 200 and data.get('status') == 'success':
            self._push_client_info = data.get('identity', {})
            client   = self._push_client_info.get('client', '?')
            trader   = self._push_client_info.get('trader', '?')
            admin    = self._push_client_info.get('admin', '?')
            category = self._push_client_info.get('category', '')
            label = f'✅  {client}  →  Trader: {trader}  →  Admin: {admin}'
            if category:
                label += f'  |  Category: {category}'
            self.push_hierarchy_var.set(label)
            self.push_hierarchy_lbl.configure(fg='#16a34a')
            # Enable push button
            self.push_btn.configure(state='normal', fg_color='#7c3aed',
                                    hover_color='#6d28d9', text_color='#ffffff')
            self._push_log(f'✅ Client found: {client} → {trader} → {admin}')
        else:
            msg = data.get('message', f'HTTP {resp.status_code}')
            self._lookup_fail(msg)

    def _lookup_fail(self, msg):
        self._push_client_info = None
        self.push_hierarchy_var.set(f'❌  {msg}')
        self.push_hierarchy_lbl.configure(fg=self.BAD)
        self._push_log(f'❌ Lookup failed: {msg}', 'err')

    # ── Push ─────────────────────────────────────────────────
    def _on_push_to_dashboard(self):
        """Build payload from fetched deals and POST to /api/client/push.
        Mirrors push_data() in trader_app.py exactly."""
        import requests as _req
        from collections import defaultdict as _ddict

        url   = self.push_url_var.get().strip().rstrip('/')
        email = self.push_email_var.get().strip()

        if not self._push_client_info:
            messagebox.showerror('Not Looked Up',
                'Please look up the client first.\n'
                'Enter their email and click "Lookup Client".')
            return
        if not self.result_data or not self.result_data.get('matched'):
            messagebox.showwarning('No Data',
                'Run FETCH DEALS first to load deals for an account.')
            return

        matched   = self.result_data['matched']
        acct_info = self.result_data.get('account_info', {})
        client_name = self._push_client_info.get('client', '')

        self.push_btn.configure(state='disabled', text='Pushing…')
        self._push_log('', clear=True)
        self._push_log(f'Dashboard : {url}')
        self._push_log(f'Client    : {email}  ({client_name})')

        # ── Statistics (mirrors calculate_statistics) ─────────────────────
        # Only OUT trades with BUY/SELL type; deduplicate by position_id
        seen_pos = set()
        unique_out = []
        for d in matched:
            if d.get('type') in [0, 1] and d.get('entry') == 1:
                if d['position_id'] not in seen_pos:
                    seen_pos.add(d['position_id'])
                    unique_out.append(d)
        profits  = [d['_profit'] for d in unique_out]
        winning  = [p for p in profits if p > 0]
        losing   = [p for p in profits if p < 0]
        statistics = {
            'total_trades':   len(unique_out),
            'winning_trades': len(winning),
            'losing_trades':  len(losing),
            'win_rate':       round(len(winning) / len(unique_out) * 100, 2) if unique_out else 0,
            'total_profit':   round(sum(profits), 2),
            'average_win':    round(sum(winning) / len(winning), 2) if winning else 0,
            'average_loss':   round(sum(losing) / len(losing), 2) if losing else 0,
            'profit_factor':  round(abs(sum(winning) / sum(losing)), 2)
                              if losing and sum(losing) != 0 else 0,
            'largest_win':    round(max(winning), 2) if winning else 0,
            'largest_loss':   round(min(losing), 2) if losing else 0,
        }

        # ── Aggregate by (account, phase, number) — position dedup ───────
        # One entry per position_id (take the matched deal that has _parsed comment)
        seen_pid = {}
        for d in matched:
            pid = d.get('position_id')
            if pid not in seen_pid:
                seen_pid[pid] = d
        all_unique = list(seen_pid.values())

        # Non-FA groups: keyed by (account, phase, number)
        non_fa = _ddict(lambda: {
            'net_profit': 0.0, 'deal_count': 0,
            'open_time': None, 'close_time': None,
            'account_number': '', 'phase_code': '',
            'trade_number': None, 'farming_date': None,
        })
        # FA groups: keyed by (account, date_str) — same-day merge
        fa_by_day = _ddict(lambda: {
            'net_profit': 0.0, 'deal_count': 0,
            'open_time': None, 'close_time': None,
            'account_number': '', 'phase_code': 'FA',
            'trade_number': 1, 'farming_date': None,
        })

        for d in all_unique:
            p      = d['_parsed']
            phase  = p['phase']
            num    = p['number']
            acct   = p['account_number']
            dt_str = datetime.fromtimestamp(d['time']).strftime('%Y-%m-%d')
            dt_iso = datetime.fromtimestamp(d['time']).isoformat()
            profit = d['_profit']

            if phase == 'FA':
                g = fa_by_day[(acct, dt_str)]
                g['account_number'] = acct
                g['farming_date']   = dt_str
                g['net_profit']    += profit
                g['deal_count']    += 1
                if not g['open_time'] or dt_iso < g['open_time']:
                    g['open_time'] = dt_iso
                if not g['close_time'] or dt_iso > g['close_time']:
                    g['close_time'] = dt_iso
            else:
                g = non_fa[(acct, phase, num)]
                g['account_number'] = acct
                g['phase_code']     = phase
                g['trade_number']   = num
                g['net_profit']    += profit
                g['deal_count']    += 1
                if not g['open_time'] or dt_iso < g['open_time']:
                    g['open_time'] = dt_iso
                if not g['close_time'] or dt_iso > g['close_time']:
                    g['close_time'] = dt_iso

        # FA: group by account, sort chronologically, _fa_slot = total days,
        # push ONLY the latest date per account (companion behaviour).
        fa_per_account = _ddict(list)
        for (acct, dt_str), entry in fa_by_day.items():
            fa_per_account[acct].append((dt_str, dict(entry)))

        fa_to_push = []
        for acct, date_entries in fa_per_account.items():
            date_entries.sort(key=lambda x: x[0])   # chronological
            total_days = len(date_entries)           # count IS the hedge day slot
            latest_date, latest_entry = date_entries[-1]
            latest_entry['_fa_slot']    = total_days
            latest_entry['trade_number'] = total_days
            fa_to_push.append(latest_entry)
            self._push_log(
                f'   📅 {acct}: {total_days} FA day(s) in history '
                f'→ push as Hedge Day {total_days} ({latest_date})')

        aggregated = list(non_fa.values()) + fa_to_push

        # ── Deals payload (string types/entry matching companion) ─────────
        deals_payload = []
        for d in matched:
            deals_payload.append({
                'ticket':      d.get('ticket', ''),
                'order':       d.get('order', ''),
                'position_id': d.get('position_id', ''),
                'symbol':      d.get('symbol', ''),
                'type':        DEAL_TYPE_MAP.get(d.get('type', -1), str(d.get('type', ''))),
                'entry':       ENTRY_MAP.get(d.get('entry', -1), str(d.get('entry', ''))),
                'volume':      d.get('volume', 0),
                'price':       d.get('price', 0),
                'profit':      d.get('profit', 0),
                'commission':  d.get('commission', 0),
                'swap':        d.get('swap', 0),
                'time':        datetime.fromtimestamp(d['time']).isoformat(),
                'time_raw':    d['time'],
                'comment':     d.get('comment', ''),
            })

        payload = {
            'email':                  email,
            'account':                acct_info,
            'positions':              [],
            'deals':                  deals_payload,
            'statistics':             statistics,
            'evaluations':            [],
            'aggregated_by_comment':  aggregated,
            'comment_summary':        {},
            'dropdown_options':       {},
        }

        bal = acct_info.get('balance', 0)
        dep = acct_info.get('total_deposits', 0)
        self._push_log(
            f'📦 Payload: Bal=${bal:,.0f} | Dep=${dep:,.0f} | '
            f'{len(deals_payload)} deals | {len(aggregated)} hedge groups '
            f'(CH/FD/DD: {len(non_fa)}, FA: {len(fa_to_push)})')

        def _run():
            try:
                resp = _req.post(
                    f'{url}/api/client/push',
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=120)
                self.root.after(
                    0, lambda: self._handle_push_response(resp, url, email, acct_info))
            except _req.exceptions.Timeout:
                self.root.after(0, lambda: self._push_done(
                    False, 'Timeout — server did not respond within 120s'))
            except _req.exceptions.ConnectionError:
                self.root.after(0, lambda: self._push_done(False, 'Cannot connect to server'))
            except Exception as ex:
                self.root.after(0, lambda: self._push_done(False, str(ex)))

        threading.Thread(target=_run, daemon=True).start()

    def _handle_push_response(self, resp, url, email, acct_info):
        try:
            data = resp.json()
        except Exception:
            self._push_done(False, f'HTTP {resp.status_code} — invalid JSON response')
            return

        if resp.status_code == 200 and data.get('status') == 'success':
            hedge_updates = data.get('hedge_updates', 0)
            for entry in data.get('hedge_match_log', []):
                self._push_log(f'  {entry}')
            if hedge_updates:
                self._push_log(f'📊 {hedge_updates} hedge cell(s) updated on dashboard')
            self._push_done(True, f'{hedge_updates} hedge cell(s) updated.')
            # Auto-trigger hedging review — same as companion does after push_data()
            self._push_hedging_review_auto(url, email, acct_info)
        else:
            msg = data.get('message', f'HTTP {resp.status_code}')
            for entry in data.get('hedge_match_log', []):
                self._push_log(f'  {entry}')
            self._push_done(False, msg)

    def _push_hedging_review_auto(self, url, email, acct_info):
        """POST /api/client/push_hedging_review — auto-called after successful push."""
        import requests as _req
        deposits    = float(acct_info.get('total_deposits', 0) or 0)
        withdrawals = float(acct_info.get('total_withdrawals', 0) or 0)
        balance     = float(acct_info.get('balance', 0) or 0)
        payload = {
            'email':              email,
            'total_deposits':     deposits,
            'total_withdrawals':  withdrawals,
            'current_balance':    balance,
        }
        self._push_log(
            f'📊 Hedging Review → Dep=${deposits:,.0f} | '
            f'Wth=${withdrawals:,.0f} | Bal=${balance:,.0f}')

        def _run():
            try:
                resp = _req.post(
                    f'{url}/api/client/push_hedging_review',
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=30)
                self.root.after(0, lambda: self._handle_hr_response(resp, balance))
            except _req.exceptions.Timeout:
                self.root.after(0, lambda: self._push_log(
                    '⚠️ Hedging review timeout', 'warn'))
            except _req.exceptions.ConnectionError:
                self.root.after(0, lambda: self._push_log(
                    '⚠️ Hedging review — cannot connect', 'warn'))
            except Exception as ex:
                self.root.after(0, lambda: self._push_log(
                    f'⚠️ Hedging review error: {ex}', 'warn'))

        threading.Thread(target=_run, daemon=True).start()

    def _handle_hr_response(self, resp, balance):
        try:
            data = resp.json()
        except Exception:
            self._push_log(
                f'⚠️ Hedging review: HTTP {resp.status_code} — invalid JSON', 'warn')
            return
        if resp.status_code == 200 and data.get('status') == 'success':
            hr     = data.get('hedging_review') or {}
            actual = hr.get('actual_hedging_results', 0)
            disc   = hr.get('discrepancy', 0)
            self._push_log(
                f'✅ Hedging Review → Actual: ${actual:,.2f} | '
                f'Disc: ${disc:,.2f} | Bal: ${balance:,.0f}')
        else:
            msg = data.get('message', f'HTTP {resp.status_code}')
            self._push_log(f'⚠️ Hedging review failed: {msg}', 'warn')

    def _push_log(self, msg, tag='info', clear=False):
        """Append a colour-coded line to the push log."""
        self.push_log_text.configure(state='normal')
        if clear:
            self.push_log_text.delete('1.0', 'end')
            self.push_log_text.configure(state='disabled')
            return
        if msg.startswith('✅'):
            tag = 'ok'
        elif msg.startswith('⚠') or msg.startswith('⏭') or msg.startswith('SKIP'):
            tag = 'warn'
        elif msg.startswith('❌'):
            tag = 'err'
        self.push_log_text.insert('end', msg + '\n', tag)
        self.push_log_text.see('end')
        self.push_log_text.configure(state='disabled')

    def _push_done(self, success, msg):
        self.push_btn.configure(
            state='normal', text='🚀  PUSH TO DASHBOARD',
            fg_color='#7c3aed', hover_color='#6d28d9', text_color='#ffffff')
        if success:
            self._push_log(f'✅ Push complete — {msg}')
        else:
            self._push_log(f'❌ Push failed — {msg}', 'err')






def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    app = MT5RecoveryApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
