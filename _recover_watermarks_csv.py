"""
Extract structured data from Apache error log files.
Outputs two CSV files matching actual dashboard table schemas:
  - recovered_daily_watermarks.csv  → matches daily_watermarks table
  - recovered_push_events.csv       → push summary per client per date

Run on PythonAnywhere bash:
  python3 /home/ballerquotes/MT5Dashboard/_recover_watermarks_csv.py
"""

import re
import gzip
import csv
import json
import sys
from datetime import datetime
from collections import defaultdict

LOG_FILES = [
    '/var/log/www.tradeopss.com.error.log',
    '/var/log/www.tradeopss.com.error.log.1',
    '/var/log/www.tradeopss.com.error.log.2',
    '/var/log/www.tradeopss.com.error.log.3.gz',
    '/var/log/www.tradeopss.com.error.log.4.gz',
    '/var/log/www.tradeopss.com.error.log.5.gz',
    '/var/log/www.tradeopss.com.error.log.6.gz',
    '/var/log/www.tradeopss.com.error.log.7.gz',
    '/var/log/www.tradeopss.com.error.log.8.gz',
]

DATE_RANGE_START = '2026-03-26'
DATE_RANGE_END   = '2026-04-03'

# Regex patterns
RE_WATERMARK = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+: Saved daily watermark for (.+?) on (\d{4}-\d{2}-\d{2}): \$([-\d.]+) \((\w+)\)'
)
RE_PUSH = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+: .?Push for (.+?): (\d+) deals, balance=([-\d.]+), (\d+) evaluations'
)
RE_STATS = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+: Stats calculated.*?Current balance: \$([-\d.,]+)'
)
RE_HEDGE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+: \[FA.*?\] .*?Hedge Day (\d+).*?for date (\d{4}-\d{2}-\d{2})'
)
RE_UPDATE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+: \[REQUEST\] POST /api/update_data -> (\d{3})'
)

def open_log(path):
    try:
        if path.endswith('.gz'):
            return gzip.open(path, 'rt', encoding='utf-8', errors='replace')
        else:
            return open(path, 'r', encoding='utf-8', errors='replace')
    except FileNotFoundError:
        return None

def in_range(date_str):
    return DATE_RANGE_START <= date_str[:10] <= DATE_RANGE_END

# ── collect all matches ──────────────────────────────────────────────────────

watermarks = {}          # (client_id, date) -> latest row
push_events = []
update_events = []
stats_events = []

total_lines = 0
for log_path in LOG_FILES:
    fh = open_log(log_path)
    if fh is None:
        print(f'  [skip] {log_path} (not found)')
        continue
    count = 0
    with fh as f:
        for line in f:
            line = line.strip()
            # Quick pre-filter: must start with a date in our range
            if not line or not line[:10].startswith('2026-0'):
                continue
            if not in_range(line):
                continue
            count += 1

            m = RE_WATERMARK.match(line)
            if m:
                created_at, client_id, date, amount, source = m.groups()
                key = (client_id, date)
                # Keep LAST save of the day (overwrite earlier duplicates like dashboard does)
                watermarks[key] = {
                    'client_id': client_id,
                    'date': date,
                    'net_profit_complete': float(amount),
                    'source': source,
                    'created_at': created_at,
                }
                continue

            m = RE_PUSH.match(line)
            if m:
                ts, client_id, deals, balance, evals = m.groups()
                push_events.append({
                    'timestamp': ts,
                    'date': ts[:10],
                    'client_id': client_id,
                    'deals': int(deals),
                    'balance': float(balance),
                    'evaluations': int(evals),
                })
                continue

            m = RE_UPDATE.match(line)
            if m:
                ts, status = m.groups()
                update_events.append({'timestamp': ts, 'date': ts[:10], 'status': int(status)})
                continue

    total_lines += count
    print(f'  [ok] {log_path}: {count} lines in range')

print(f'\nTotal lines scanned in date range: {total_lines}')

# ── Write daily_watermarks CSV ───────────────────────────────────────────────

wm_rows = sorted(watermarks.values(), key=lambda r: (r['date'], r['client_id']))

wm_path = '/home/ballerquotes/MT5Dashboard/recovered_daily_watermarks.csv'
with open(wm_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=['client_id', 'date', 'net_profit_complete', 'source', 'created_at'])
    writer.writeheader()
    writer.writerows(wm_rows)

print(f'\n=== DAILY WATERMARKS ({len(wm_rows)} rows) → {wm_path} ===')
print(f'{"client_id":<30} {"date":<12} {"net_profit_complete":>20} {"source":<8} {"created_at"}')
print('-' * 90)
for r in wm_rows:
    print(f'{r["client_id"]:<30} {r["date"]:<12} {r["net_profit_complete"]:>20.2f} {r["source"]:<8} {r["created_at"]}')

# ── Write push_events CSV ────────────────────────────────────────────────────

push_path = '/home/ballerquotes/MT5Dashboard/recovered_push_events.csv'
with open(push_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=['timestamp', 'date', 'client_id', 'deals', 'balance', 'evaluations'])
    writer.writeheader()
    writer.writerows(push_events)

print(f'\n=== PUSH EVENTS ({len(push_events)} rows) → {push_path} ===')
if push_events:
    print(f'{"timestamp":<22} {"client_id":<30} {"deals":>6} {"balance":>12} {"evals":>6}')
    print('-' * 82)
    for r in push_events:
        print(f'{r["timestamp"]:<22} {r["client_id"]:<30} {r["deals"]:>6} {r["balance"]:>12.2f} {r["evaluations"]:>6}')
else:
    print('  (none found)')

# ── update_data call summary ─────────────────────────────────────────────────

by_date = defaultdict(lambda: {'total': 0, '200': 0, 'other': 0})
for e in update_events:
    by_date[e['date']]['total'] += 1
    if e['status'] == 200:
        by_date[e['date']]['200'] += 1
    else:
        by_date[e['date']]['other'] += 1

print(f'\n=== /api/update_data CALLS BY DATE ===')
print(f'{"date":<12} {"total":>7} {"200 OK":>8} {"other":>7}')
print('-' * 38)
for d in sorted(by_date):
    r = by_date[d]
    print(f'{d:<12} {r["total"]:>7} {r["200"]:>8} {r["other"]:>7}')

# ── JSON output (combined) ───────────────────────────────────────────────────

json_path = '/home/ballerquotes/MT5Dashboard/recovered_structured.json'
with open(json_path, 'w', encoding='utf-8') as f:
    json.dump({
        'daily_watermarks': wm_rows,
        'push_events': push_events,
        'update_data_by_date': {d: dict(v) for d, v in by_date.items()},
    }, f, indent=2)

print(f'\nCombined JSON → {json_path}')
print('\nDone.')
