import pandas as pd
import requests
import io
import logging
from datetime import datetime

SHEET_ID = "10eGsivGm5GOaH0orB2AAbjpXzDwDkYY1gIZgux9nIjI"
STATS_GID = "839895136"
WATERLOG_GID = "520289647"

def get_sheet_csv(gid):
    try:
        url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.content.decode('utf-8')
    except Exception as e:
        logging.error(f"Error fetching sheet CSV (gid={gid}): {e}")
        return None

def fetch_waterlog_data():
    """
    Fetches and computes the Profitability Waterlog table.

    Sheet structure (gid=206426091):
      Col A/B : Daily log — Timestamp, Value (net profit that day)
      Col D/E : Bi-weekly period table — From, To (pre-defined date ranges)
      Col F   : Low  = MIN(daily Value) for readings within [From, To]
      Col G   : High = MAX(daily Value) for readings within [From, To]
      Col H   : Profit Split = MAX(0, (Low_i − MAX(Low_1..Low_{i-1})) × 50%)
                i.e. 50% of any new high-water mark reached by the Low column.
                (Original sheet divides by 4; we use 50% as configured.)
    """
    csv_content = get_sheet_csv(WATERLOG_GID)
    if not csv_content:
        return None

    try:
        df = pd.read_csv(io.StringIO(csv_content))

        def _parse_currency(val):
            try:
                return float(str(val).replace(',', '').replace('$', '').strip())
            except Exception:
                return 0.0

        def _parse_date(val):
            """Return a date object or None."""
            if pd.isna(val) or str(val).strip() in ('', 'nan'):
                return None
            try:
                return pd.to_datetime(str(val).strip(), errors='coerce').date()
            except Exception:
                return None

        # ── 1. Build daily series: list of (date, value) from col A/B ──────────
        daily_readings = []  # list of (date, float)
        for _, row in df.iterrows():
            ts = _parse_date(row.get('Timestamp', ''))
            val = _parse_currency(row.get('Value', ''))
            if ts is not None:
                daily_readings.append((ts, val))

        # ── 2. Parse bi-weekly periods from col D/E ───────────────────────────
        # 'From ' sometimes has a trailing space in CSV exports
        from_col = 'From ' if 'From ' in df.columns else 'From'
        to_col   = 'To'

        periods = []  # list of (from_date, to_date)
        for _, row in df.iterrows():
            fd = _parse_date(row.get(from_col, ''))
            td = _parse_date(row.get(to_col, ''))
            if fd is not None and td is not None:
                periods.append((fd, td))

        # ── 3. For each period compute Low and High from daily data ───────────
        def _fmt_date(d):
            return f"{d.month}/{d.day}/{d.year}"

        def _fmt_currency(v):
            return f"${v:,.2f}" if v else '$0.00'

        result = []
        hwm_low = 0.0  # high-water mark on the Low column (across all periods)

        for (from_date, to_date) in periods:
            # Readings that fall within [from_date, to_date] inclusive
            in_range = [v for (d, v) in daily_readings if from_date <= d <= to_date]

            if in_range:
                period_low  = min(in_range)
                period_high = max(in_range)
            else:
                period_low  = 0.0
                period_high = 0.0

            # Profit Split: 50% of increment above previous high-water mark on Low
            # Only applies when current Low is positive and beats the running maximum
            if period_low > hwm_low:
                profit_split = (period_low - hwm_low) / 4
                hwm_low = period_low
            else:
                profit_split = 0.0

            result.append({
                'from_date':    _fmt_date(from_date),
                'to_date':      _fmt_date(to_date),
                'low':          _fmt_currency(period_low),
                'high':         _fmt_currency(period_high),
                'profit_split': f"${profit_split:,.0f}" if profit_split > 0 else '$0',
            })

        return result

    except Exception as e:
        logging.error(f"Error computing Waterlog data: {e}")
        return None


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
