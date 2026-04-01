"""
Debug MT5 Positions — Fetch all deals for a dashboard account number from MT5.

Usage:
  1. Set ACCOUNT_NUMBER below to the dashboard account (e.g. "3066167")
  2. Set MT5_LOGIN, MT5_PASSWORD, MT5_SERVER to the hedge account credentials
  3. Optionally set DAYS_BACK to control how far back to look
  4. Run:  python scripts/debug_mt5_positions.py

The script connects to MT5, pulls all history deals, filters by the account
number found in the deal comment (same logic the app uses), and groups them
by trading day — showing the hedge day number for each day.

MT5 comments are in the format:  PREFIX...ACCOUNT_PHASE[Num]
  e.g.  FNFT...24774_FA   → account extracted = 24774, phase=FA (no number)
        FNFT...S8657_FA   → account extracted = S8657, phase=FA
        TDFY...29929_CH3  → account extracted = 29929, phase=CH, num=3
        MFFU...35109_FD2  → account extracted = 35109, phase=FD, num=2

Set ACCOUNT_NUMBER to the account portion extracted from the comment
(i.e. what appears immediately before _PHASE in the MT5 comment).
NOT the full dashboard account ID like 'FNFTCHKEVINWILLIAMS19859'.

Phase codes:
  CH = Challenge   (maps to Hedge Result 1-5)
  FD = Funded      (maps to Hedge Result 1.1-5.1, then 6+)
  FA = Farming     (maps to Hedge Day columns)  ← no trailing number in comment
"""

import sys
import os
import re
from datetime import datetime, timedelta
from collections import defaultdict

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION — Edit these before running
# ═══════════════════════════════════════════════════════════════
ACCOUNT_NUMBER = "44229"           # Account portion from MT5 comment (e.g. S8657, 24774, 35107)
MT5_LOGIN      = 21589169           # MT5 login (integer)
MT5_PASSWORD   = "9jm4iXLB1y2S$"          # MT5 password
MT5_SERVER     = "VTMarkets-Live"          # MT5 server name
DAYS_BACK      = 365         # How many days of history to fetch
PHASE_FILTER   = "FA"        # Set to "CH", "FD", "FA" to filter, or None for all

# ═══════════════════════════════════════════════════════════════


def parse_comment(comment):
    """
    Parse MT5 deal comment to extract account number, phase, and number.
    Mirrors the app's extract_account_from_comment + parse_comment logic in app.py.

    MT5 comments are like: FNFT...S8657_FA  or  TDFY...29929_CH3
    The phase number is OPTIONAL (FA deals have no trailing number).
    We extract the alphanumeric part immediately before _PHASE as the account.
    """
    if not comment:
        return None

    c = str(comment).strip()

    # Extract phase (number optional — FA has no number)
    phase_match = re.search(r'_(CH|FD|DD|FA)(\d+)?', c, re.IGNORECASE)
    if not phase_match:
        return None

    phase = phase_match.group(1).upper()
    number = int(phase_match.group(2)) if phase_match.group(2) else 1

    # Extract account: alphanumeric chars immediately before _PHASE
    # e.g. FNFT...S8657_FA → S8657 | TDFY...29929_CH3 → 29929
    account_match = re.search(r'([A-Z0-9]+)_(CH|FD|DD|FA)', c, re.IGNORECASE)
    if not account_match:
        return None

    return {
        'account_number': account_match.group(1).upper(),
        'phase': phase,
        'number': number,
    }


def phase_to_field(phase, number):
    """
    Map phase code to dashboard column name.
    Same logic as trade_matcher._get_field_name
    """
    if phase == 'CH':
        if 1 <= number <= 5:
            return f"Hedge Result {number}"
    elif phase == 'FD':
        if number == 0:
            return "Hedge Result 1.1"
        if 1 <= number <= 4:
            return f"Hedge Result {number + 1}.1"
        if number >= 5:
            return f"Hedge Result {number + 1}"
    elif phase == 'FA':
        return f"Hedge Day {number}" if number >= 1 else "Hedge Day 1"
    return f"{phase}{number}"


def format_type(deal_type):
    """Convert MT5 deal type integer to readable string."""
    type_map = {
        0: "BUY",
        1: "SELL",
        2: "BALANCE",
        3: "CREDIT",
        4: "CHARGE",
        5: "CORRECTION",
        6: "BONUS",
        7: "COMMISSION",
        8: "DAILY_COMMISSION",
        9: "MONTHLY_COMMISSION",
        10: "DAILY_AGENT",
        11: "MONTHLY_AGENT",
        12: "INTEREST",
    }
    return type_map.get(deal_type, f"TYPE_{deal_type}")


def format_entry(entry):
    """Convert MT5 deal entry integer to readable string."""
    entry_map = {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}
    return entry_map.get(entry, f"ENTRY_{entry}")


def main():
    # ── Validate config ─────────────────────────────────────
    if not ACCOUNT_NUMBER:
        print("ERROR: Set ACCOUNT_NUMBER at the top of this script.")
        sys.exit(1)
    if not MT5_LOGIN or not MT5_PASSWORD or not MT5_SERVER:
        print("ERROR: Set MT5_LOGIN, MT5_PASSWORD, MT5_SERVER at the top of this script.")
        sys.exit(1)

    # ── Import & connect MT5 ────────────────────────────────
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("ERROR: MetaTrader5 package not installed. Run: pip install MetaTrader5")
        sys.exit(1)

    print(f"Initializing MT5...")
    if not mt5.initialize():
        print(f"MT5 initialize() failed: {mt5.last_error()}")
        sys.exit(1)

    login_int = int(MT5_LOGIN)
    print(f"Logging in to account {login_int} @ {MT5_SERVER}...")
    if not mt5.login(login_int, password=MT5_PASSWORD, server=MT5_SERVER):
        print(f"MT5 login failed: {mt5.last_error()}")
        mt5.shutdown()
        sys.exit(1)

    acct = mt5.account_info()
    if acct:
        print(f"Connected: {acct.name} | Balance: {acct.balance} | Equity: {acct.equity}")
    print()

    # ── Fetch deals ─────────────────────────────────────────
    import time
    from_ts = time.time() - (DAYS_BACK * 86400)
    to_ts = time.time() + 86400  # buffer

    print(f"Fetching deals for last {DAYS_BACK} days...")
    deals = mt5.history_deals_get(from_ts, to_ts)
    mt5.shutdown()

    if deals is None or len(deals) == 0:
        print("No deals returned from MT5.")
        sys.exit(0)

    print(f"Total deals from MT5: {len(deals)}")
    print()

    # ── Filter by account number ────────────────────────────
    matched = []
    unmatched_comments = set()
    account_upper = ACCOUNT_NUMBER.upper()

    for deal in deals:
        d = deal._asdict()
        comment = d.get('comment', '')
        parsed = parse_comment(comment)

        if parsed and parsed['account_number'].upper() == account_upper:
            if PHASE_FILTER and parsed['phase'] != PHASE_FILTER:
                continue
            d['_parsed'] = parsed
            matched.append(d)
        elif comment:
            unmatched_comments.add(comment)

    print(f"Deals matching account '{ACCOUNT_NUMBER}': {len(matched)}")
    if PHASE_FILTER:
        print(f"  (filtered to phase: {PHASE_FILTER})")
    print()

    if not matched:
        print("No matching deals found.")
        if unmatched_comments:
            print(f"\nSample non-matching comments ({min(len(unmatched_comments), 20)} of {len(unmatched_comments)}):")
            for c in sorted(unmatched_comments)[:20]:
                print(f"  '{c}'")
        sys.exit(0)

    # ── Sort by time ────────────────────────────────────────
    matched.sort(key=lambda d: d['time'])

    # ── Resolve actual profit from closing (OUT) deals ──────
    # Entry (IN) deals carry profit=0; the real P/L is on the OUT deal
    # which shares the same position_id but has no account comment.
    position_ids = {d['position_id'] for d in matched}
    position_profit = defaultdict(float)
    for deal in deals:
        d2 = deal._asdict()
        if d2.get('position_id') in position_ids and int(d2.get('entry', -1)) == 1:  # OUT
            position_profit[d2['position_id']] += (
                d2.get('profit', 0) + d2.get('commission', 0) + d2.get('swap', 0)
            )
    for d in matched:
        d['_profit'] = position_profit.get(d['position_id'], 0.0)

    # ── Group by date ───────────────────────────────────────
    daily = defaultdict(list)
    for d in matched:
        ts = d['time']
        dt = datetime.fromtimestamp(ts)
        date_key = dt.strftime('%Y-%m-%d')
        daily[date_key].append(d)

    sorted_dates = sorted(daily.keys())

    # ── Summary by phase ────────────────────────────────────
    phase_summary = defaultdict(lambda: {'count': 0, 'profit': 0.0, 'days': set()})
    for d in matched:
        p = d['_parsed']
        key = f"{p['phase']}{p['number']}"
        phase_summary[key]['count'] += 1
        phase_summary[key]['profit'] += d['_profit']
        phase_summary[key]['days'].add(datetime.fromtimestamp(d['time']).strftime('%Y-%m-%d'))

    W = 90
    print()
    print("═" * W)
    print(f"  ACCOUNT : {ACCOUNT_NUMBER}")
    print(f"  MT5     : {MT5_LOGIN} @ {MT5_SERVER}")
    phase_label = f"  (phase filter: {PHASE_FILTER})" if PHASE_FILTER else ""
    print(f"  Matched : {len(matched)} deal(s) across {len(sorted_dates)} trading day(s){phase_label}")
    print("═" * W)

    # ── Phase breakdown ─────────────────────────────────────
    print()
    print("  PHASE BREAKDOWN")
    print("  " + "─" * (W - 2))
    print(f"  {'Phase':<10}  {'Dashboard Field':<22}  {'Deals':>6}  {'Days':>6}  {'Net P/L':>10}")
    print(f"  {'─'*10}  {'─'*22}  {'─'*6}  {'─'*6}  {'─'*10}")
    total_profit = 0.0
    for key in sorted(phase_summary.keys()):
        info = phase_summary[key]
        parsed_phase = key[:2]
        parsed_num = int(key[2:]) if key[2:] else 1
        field = phase_to_field(parsed_phase, parsed_num)
        total_profit += info['profit']
        print(f"  {key:<10}  {field:<22}  {info['count']:>6}  {len(info['days']):>6}  {info['profit']:>+10.2f}")
    print(f"  {'─'*10}  {'─'*22}  {'─'*6}  {'─'*6}  {'─'*10}")
    print(f"  {'TOTAL':<10}  {'':22}  {len(matched):>6}  {len(sorted_dates):>6}  {total_profit:>+10.2f}")

    # ── Daily breakdown ─────────────────────────────────────
    print()
    print("  DAILY BREAKDOWN — HEDGE DAYS")
    print("  " + "─" * (W - 2))
    print(f"  {'#':<4}  {'Date':<12}  {'Hedge Day Label':<20}  {'Deals':>5}  {'Net P/L':>10}  {'Time (UTC)':<19}  {'Symbol':<10}  {'Dir':<4}  {'Vol':>6}  {'Entry Price':>13}")
    print(f"  {'─'*4}  {'─'*12}  {'─'*20}  {'─'*5}  {'─'*10}  {'─'*19}  {'─'*10}  {'─'*4}  {'─'*6}  {'─'*13}")

    for day_num, date_key in enumerate(sorted_dates, start=1):
        day_deals = daily[date_key]
        hedge_label = f"Hedge Day {day_num}"
        day_profit = sum(d['_profit'] for d in day_deals)

        # Print one row per deal on this day (first deal on same line, extras indented)
        for i, d in enumerate(day_deals):
            ts = datetime.fromtimestamp(d['time']).strftime('%Y-%m-%d %H:%M:%S')
            direction = format_type(d.get('type', -1))
            symbol = d.get('symbol', '')
            volume = d.get('volume', 0)
            price = d.get('price', 0)

            if i == 0:
                print(
                    f"  {day_num:<4}  {date_key:<12}  {hedge_label:<20}  {len(day_deals):>5}  "
                    f"{day_profit:>+10.2f}  {ts:<19}  {symbol:<10}  {direction:<4}  {volume:>6.2f}  {price:>13.5f}"
                )
            else:
                print(
                    f"  {'':4}  {'':12}  {'':20}  {'':5}  "
                    f"{'':10}  {ts:<19}  {symbol:<10}  {direction:<4}  {volume:>6.2f}  {price:>13.5f}"
                )

        print(f"  {'─'*4}  {'─'*12}  {'─'*20}  {'─'*5}  {'─'*10}  {'─'*19}  {'─'*10}  {'─'*4}  {'─'*6}  {'─'*13}")

    # ── Detailed deal list ──────────────────────────────────
    print()
    print("  ALL MATCHED DEALS")
    print("  " + "─" * (W - 2))
    print(f"  {'Time':<20}  {'Ticket':<12}  {'Symbol':<10}  {'Dir':<4}  {'Entry':<5}  {'Vol':>6}  {'Price':>13}  {'Profit':>10}  {'Comment'}")
    print(f"  {'─'*20}  {'─'*12}  {'─'*10}  {'─'*4}  {'─'*5}  {'─'*6}  {'─'*13}  {'─'*10}  {'─'*30}")

    for d in matched:
        ts = datetime.fromtimestamp(d['time']).strftime('%Y-%m-%d %H:%M:%S')
        print(
            f"  {ts:<20}  {d.get('ticket', ''):<12}  {d.get('symbol', ''):<10}  "
            f"{format_type(d.get('type', -1)):<4}  {format_entry(d.get('entry', -1)):<5}  "
            f"{d.get('volume', 0):>6.2f}  {d.get('price', 0):>13.5f}  "
            f"{d['_profit']:>+10.2f}  "
            f"{d.get('comment', '')}"
        )

    # ── Open positions check ────────────────────────────────
    # Reconnect briefly to check open positions
    print(f"\n── Checking Open Positions ──────────────────────────")
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
        mt5.login(int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER)
        positions = mt5.positions_get()
        mt5.shutdown()

        if positions:
            open_matched = []
            for pos in positions:
                p = pos._asdict()
                parsed = parse_comment(p.get('comment', ''))
                if parsed and parsed['account_number'].upper() == account_upper:
                    if PHASE_FILTER and parsed['phase'] != PHASE_FILTER:
                        continue
                    p['_parsed'] = parsed
                    open_matched.append(p)

            if open_matched:
                print(f"  Open positions matching '{ACCOUNT_NUMBER}': {len(open_matched)}")
                print(f"  {'Symbol':<12} {'Type':<6} {'Volume':>8} {'Price':>12} {'Profit':>10} {'Swap':>8}  {'Comment'}")
                print(f"  {'─'*12} {'─'*6} {'─'*8} {'─'*12} {'─'*10} {'─'*8}  {'─'*30}")
                for p in open_matched:
                    ptype = "BUY" if p.get('type', 0) == 0 else "SELL"
                    print(
                        f"  {p.get('symbol', ''):<12} {ptype:<6} "
                        f"{p.get('volume', 0):>8.2f} {p.get('price_open', 0):>12.5f} "
                        f"{p.get('profit', 0):>10.2f} {p.get('swap', 0):>8.2f}  "
                        f"{p.get('comment', '')}"
                    )
            else:
                print(f"  No open positions matching '{ACCOUNT_NUMBER}'.")
        else:
            print("  No open positions on this MT5 account.")
    except Exception as e:
        print(f"  Could not check open positions: {e}")

    # ── Non-matching comments sample ────────────────────────
    if unmatched_comments:
        print(f"\n── Other Comments in MT5 (not matching '{ACCOUNT_NUMBER}') ──")
        # Extract unique account numbers from non-matching
        other_accounts = set()
        for c in unmatched_comments:
            parsed = parse_comment(c)
            if parsed:
                other_accounts.add(parsed['account_number'])
        if other_accounts:
            print(f"  Other account numbers found: {', '.join(sorted(other_accounts))}")
        print(f"  Sample comments ({min(len(unmatched_comments), 10)}):")
        for c in sorted(unmatched_comments)[:10]:
            print(f"    '{c}'")


if __name__ == '__main__':
    main()
