import pandas as pd
import requests
import io
import logging
from datetime import datetime

SHEET_ID = "10eGsivGm5GOaH0orB2AAbjpXzDwDkYY1gIZgux9nIjI"
STATS_GID = "839895136"
WATERLOG_GID = "520289647"
WATERLOG_TAB_NAME = "Profitability Waterlog"

def get_sheet_csv(gid, sheet_id=None):
    sid = sheet_id or SHEET_ID
    try:
        url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.content.decode('utf-8')
    except Exception as e:
        logging.error(f"Error fetching sheet CSV (gid={gid}): {e}")
        return None

def _extract_sheet_id(sheet_url):
    """Extract the spreadsheet key from a Google Sheets URL."""
    import re
    if not sheet_url:
        return None
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', sheet_url)
    return m.group(1) if m else None

def _discover_waterlog_gid(sheet_id):
    """Try to discover the Profitability Waterlog GID from the sheet's HTML."""
    import re
    try:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        content = resp.text
        safe_name = re.escape(WATERLOG_TAB_NAME)
        for m in re.finditer(safe_name, content):
            window = content[max(0, m.start() - 300):m.start()]
            candidates = re.findall(r'\\?"(\d+)\\?"(?!\s*:)', window)
            valid = [c for c in candidates if len(c) > 5]
            if valid:
                return valid[-1]
        return None
    except Exception as e:
        logging.error(f"Error discovering waterlog GID: {e}")
        return None

def fetch_waterlog_data(sheet_url=None, client_id=None):
    """
    Fetches the Profitability Waterlog table directly from the sheet.

    If sheet_url is provided the sheet ID (and GID) are resolved dynamically
    from that URL so each client sees data from their own sheet.
    Falls back to the hardcoded SHEET_ID / WATERLOG_GID when not supplied.

    Sheet structure (Profitability Waterlog tab):
      Col D/E : Bi-weekly period table — From, To
      Col F   : Low  (computed by Google Sheets from live trading data)
      Col G   : High (computed by Google Sheets from live trading data)

    Low and High are read directly from columns F/G.  Profit Split is
    recomputed using the HWM/4 formula that matches the reference sheet.
    
    If client_id is provided, loads and applies any split_pct_overrides 
    from the database, preventing the ratio-based detection from overwriting 
    admin-set split percentages.
    """
    # Load split percentage overrides if client_id provided
    spct_overrides = {}
    if client_id:
        try:
            from dashboard.watermark_service import get_split_pct_overrides
            spct_overrides = get_split_pct_overrides(client_id)
        except Exception as e:
            logging.debug(f"Could not load split_pct_overrides for {client_id}: {e}")
    
    # Resolve sheet-ID and GID
    sid = _extract_sheet_id(sheet_url) if sheet_url else None
    if sid:
        gid = _discover_waterlog_gid(sid) or WATERLOG_GID
    else:
        sid = None          # use default SHEET_ID inside get_sheet_csv
        gid = WATERLOG_GID

    csv_content = get_sheet_csv(gid, sheet_id=sid)
    if not csv_content:
        return None

    try:
        df = pd.read_csv(io.StringIO(csv_content))

        def _parse_currency(val):
            try:
                s = str(val).replace(',', '').replace('$', '').strip()
                return float(s) if s not in ('', 'nan') else 0.0
            except Exception:
                return 0.0

        def _parse_date(val):
            if pd.isna(val) or str(val).strip() in ('', 'nan'):
                return None
            try:
                d = pd.to_datetime(str(val).strip(), errors='coerce').date()
                if d is None or d.year < 2000 or d.year > 2100:
                    return None
                return d
            except Exception:
                return None

        def _fmt_date(d):
            return f"{d.month}/{d.day}/{d.year}"

        def _fmt_currency(v):
            if v < 0:
                return f"-${abs(v):,.2f}"
            return f"${v:,.2f}"

        # Column names — 'From ' sometimes has a trailing space in CSV exports
        from_col = 'From ' if 'From ' in df.columns else 'From'
        # 'Profit Split' column may carry the sheet's actual formula result
        ps_col = next((c for c in df.columns if c.strip() == 'Profit Split'), None)

        # Parse all valid rows first, then sort oldest→newest before HWM calc
        parsed_rows = []
        for _, row in df.iterrows():
            from_date = _parse_date(row.get(from_col, ''))
            to_date   = _parse_date(row.get('To', ''))
            if from_date is None or to_date is None:
                continue
            period_low  = _parse_currency(row.get('Low', 0))
            period_high = _parse_currency(row.get('High', 0))
            # Read the sheet's own Profit Split value if available
            sheet_ps    = _parse_currency(row[ps_col]) if ps_col else 0.0
            parsed_rows.append((from_date, to_date, period_low, period_high, sheet_ps))

        # CRITICAL: HWM must be computed oldest-first regardless of CSV order
        parsed_rows.sort(key=lambda x: x[0])

        result = []
        hwm_low = 0.0  # running high-water mark on the Low column

        for (from_date, to_date, period_low, period_high, sheet_ps) in parsed_rows:
            gain = period_low - hwm_low if period_low > hwm_low else 0.0

            # Determine split percentage:
            # 1. If there's an explicit override for this period, use it (admin-set)
            # 2. Otherwise, detect from the sheet's profit split value using ratio logic
            # 3. Default to 50% for all new/unspecified periods (only legacy 25% for detected historical ratios)
            fmt_from_date = _fmt_date(from_date)
            if fmt_from_date in spct_overrides:
                # Admin-set override takes priority
                split_pct = spct_overrides[fmt_from_date]
            elif gain > 0 and sheet_ps > 0:
                # Detect split % by comparing sheet value to the period gain.
                # Ratio ≈ 0.25 → 25% (/4),  ratio ≈ 0.50 → 50% (/2).
                ratio = sheet_ps / gain
                if 0.40 <= ratio <= 0.60:
                    split_pct = 50
                elif 0.15 <= ratio <= 0.35:
                    split_pct = 25
                else:
                    split_pct = 50  # default to 50% if ratio is ambiguous
            else:
                split_pct = 50  # no gain or no sheet data — default to 50%

            if gain > 0:
                profit_split = gain * split_pct / 100
                hwm_low = period_low
            else:
                profit_split = 0.0

            result.append({
                'from_date':    fmt_from_date,
                'to_date':      _fmt_date(to_date),
                'low':          _fmt_currency(period_low),
                'high':         _fmt_currency(period_high),
                'profit_split': f"${profit_split:,.0f}" if profit_split > 0 else '$0',
                'split_pct':    split_pct,
            })

        # Return newest-first for display
        result.reverse()
        return result

    except Exception as e:
        logging.error(f"Error computing Waterlog data: {e}")
        return None


def fetch_waterlog_periods_from_sheet(sheet_url=None):
    """
    Reads the bi-weekly period schedule (columns D/E: From, To) from the sheet.
    Returns list of (from_date_str, to_date_str) in 'YYYY-MM-DD' format,
    filtered to valid dates (year 2000-2100).
    Used once during import to seed the waterlog_periods DB table.
    """
    sid = _extract_sheet_id(sheet_url) if sheet_url else None
    if sid:
        gid = _discover_waterlog_gid(sid) or WATERLOG_GID
    else:
        sid = None
        gid = WATERLOG_GID

    csv_content = get_sheet_csv(gid, sheet_id=sid)
    if not csv_content:
        return []

    try:
        df = pd.read_csv(io.StringIO(csv_content))

        def _parse_date(val):
            if pd.isna(val) or str(val).strip() in ('', 'nan'):
                return None
            try:
                d = pd.to_datetime(str(val).strip(), errors='coerce').date()
                if d is None or d.year < 2000 or d.year > 2100:
                    return None
                return d
            except Exception:
                return None

        from_col = 'From ' if 'From ' in df.columns else 'From'
        periods = []
        for _, row in df.iterrows():
            fd = _parse_date(row.get(from_col, ''))
            td = _parse_date(row.get('To', ''))
            if fd and td:
                periods.append((fd.strftime('%Y-%m-%d'), td.strftime('%Y-%m-%d')))
        return periods
    except Exception as e:
        logging.error(f"Error fetching waterlog periods from sheet: {e}")
        return []


def fetch_stats_data():
    """Fetches and parses the Stats tab."""
    csv_content = get_sheet_csv(STATS_GID)
    if not csv_content:
        return None

    try:
        # Return raw rows for flexible rendering
        df = pd.read_csv(io.StringIO(csv_content), header=None)
        df = df.fillna('')
        return df.values.tolist()
    except Exception as e:
        logging.error(f"Error parsing Stats data: {e}")
        return None
