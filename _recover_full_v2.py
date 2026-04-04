"""
Fast deep log extraction - skips GET noise, only processes meaningful lines.
Run: python3 /home/ballerquotes/MT5Dashboard/_recover_full_v2.py
"""
import re, gzip, json
from collections import defaultdict

# Must contain one of these substrings to be worth parsing (pre-filter before regex)
KEEP_KEYWORDS = (
    'Push for ',
    'Saved daily watermark',
    'Stats calculated',
    'FINAL DATA TO SAVE',
    '[FA SELECT]',
    'update_data',
    'Using ', 'Preserving ',
    '- Current balance',
    '- Total deposits',
    '- Total withdrawals',
    '- Actual hedging',
)

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
DATE_START = '2026-03-26'
DATE_END   = '2026-04-03'

RE_TS        = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+: (.*)')
RE_WM        = re.compile(r'Saved daily watermark for (.+?) on (\d{4}-\d{2}-\d{2}): \$([-\d.]+) \((\w+)\)')
RE_PUSH      = re.compile(r'Push for (.+?): (\d+) deals, balance=([-\d.]+), (\d+) evaluations')
RE_NEW_EVAL  = re.compile(r'Using (\d+) NEW evaluations from push')
RE_PRES_EVAL = re.compile(r'Preserving (\d+) EXISTING evaluations')
RE_FINAL_HDR = re.compile(r'FINAL DATA TO SAVE for (.+?):')
RE_STAT_BAL  = re.compile(r'- Current balance: \$([-\d.]+)')
RE_STAT_DEP  = re.compile(r'- Total deposits: \$([-\d.]+)')
RE_STAT_WDR  = re.compile(r'- Total withdrawals: \$([-\d.]+)')
RE_STAT_HDG  = re.compile(r'- Actual hedging: \$([-\d.]+)')
RE_FA_REUSE  = re.compile(r'\[FA SELECT\].*Reusing Hedge Day (\d+) for date (\d{4}-\d{2}-\d{2})')
RE_FA_NEW    = re.compile(r'\[FA SELECT\].*Using empty slot Hedge Day (\d+) for date (\d{4}-\d{2}-\d{2})')
RE_UPDATE    = re.compile(r'\[REQUEST\] POST /api/update_data -> (\d{3})')

STAT_PATTERNS = [
    (RE_STAT_BAL, 'current_balance'),
    (RE_STAT_DEP, 'total_deposits'),
    (RE_STAT_WDR, 'total_withdrawals'),
    (RE_STAT_HDG, 'actual_hedging'),
]

def open_log(p):
    try:
        return gzip.open(p, 'rt', encoding='utf-8', errors='replace') if p.endswith('.gz') \
               else open(p, 'r', encoding='utf-8', errors='replace')
    except FileNotFoundError:
        return None

watermarks     = defaultdict(dict)
pushes         = defaultdict(lambda: defaultdict(list))
stats_store    = defaultdict(dict)
hedge_days     = defaultdict(lambda: defaultdict(list))
update_by_date = defaultdict(lambda: {'total': 0, 'ok': 0})

ctx_client = None
ctx_date   = None
ctx_stats  = {}
in_stats   = False

for log_path in LOG_FILES:
    fh = open_log(log_path)
    if fh is None:
        print(f'  [skip] {log_path}')
        continue
    kept = 0
    with fh as f:
        for raw in f:
            # ── FAST PRE-FILTERS (no strip, no regex) ─────────────────────
            if raw[:10] < DATE_START or raw[:10] > DATE_END:
                continue
            if not any(kw in raw for kw in KEEP_KEYWORDS):
                continue

            line = raw.strip()
            if not line:
                continue
            kept += 1

            m = RE_TS.match(line)
            if not m:
                # Continuation/indented stat sub-line
                if in_stats and ctx_client and ctx_date:
                    for pat, key in STAT_PATTERNS:
                        m2 = pat.search(line)
                        if m2:
                            ctx_stats[key] = float(m2.group(1))
                            break
                continue

            ts, msg = m.group(1), m.group(2)
            date = ts[:10]

            # Flush accumulated stats on any new timestamped line
            if in_stats and ctx_stats and ctx_client and ctx_date:
                stats_store[ctx_client][ctx_date] = dict(ctx_stats)
                ctx_stats = {}
                in_stats = False

            # ── Route by cheap substring check first ───────────────────────

            if 'watermark' in msg:
                m2 = RE_WM.search(msg)
                if m2:
                    cid, wdate, amount, source = m2.groups()
                    watermarks[cid][wdate] = {
                        'net_profit_complete': float(amount),
                        'source': source,
                        'created_at': ts,
                    }
                    continue

            if 'Push for' in msg:
                m2 = RE_PUSH.search(msg)
                if m2:
                    cid, deals, balance, evals = m2.groups()
                    ctx_client, ctx_date = cid, date
                    pushes[cid][date].append({
                        'timestamp': ts,
                        'deals': int(deals),
                        'balance': float(balance),
                        'eval_count': int(evals),
                    })
                    continue

            if 'NEW evaluations' in msg:
                m2 = RE_NEW_EVAL.search(msg)
                if m2 and ctx_client and pushes[ctx_client][date]:
                    pushes[ctx_client][date][-1]['new_evals'] = int(m2.group(1))
                continue

            if 'EXISTING evaluations' in msg:
                m2 = RE_PRES_EVAL.search(msg)
                if m2 and ctx_client and pushes[ctx_client][date]:
                    pushes[ctx_client][date][-1]['preserved_evals'] = int(m2.group(1))
                continue

            if 'Stats calculated' in msg:
                in_stats = True
                ctx_stats = {'logged_at': ts}
                continue

            if in_stats and ctx_client and ctx_date:
                for pat, key in STAT_PATTERNS:
                    m2 = pat.search(msg)
                    if m2:
                        ctx_stats[key] = float(m2.group(1))
                        break

            if 'FINAL DATA TO SAVE' in msg:
                m2 = RE_FINAL_HDR.search(msg)
                if m2:
                    ctx_client, ctx_date = m2.group(1), date
                continue

            if '[FA SELECT]' in msg:
                m2 = RE_FA_REUSE.search(msg)
                if m2:
                    hedge_days[ctx_client or 'unknown'][date].append(
                        {'hedge_day': int(m2.group(1)), 'for_date': m2.group(2), 'action': 'reuse', 'ts': ts})
                    continue
                m2 = RE_FA_NEW.search(msg)
                if m2:
                    hedge_days[ctx_client or 'unknown'][date].append(
                        {'hedge_day': int(m2.group(1)), 'for_date': m2.group(2), 'action': 'new_slot', 'ts': ts})
                continue

            if 'update_data' in msg:
                m2 = RE_UPDATE.search(msg)
                if m2:
                    update_by_date[date]['total'] += 1
                    if int(m2.group(1)) == 200:
                        update_by_date[date]['ok'] += 1

    print(f'  [ok] {log_path}: {kept} meaningful lines')

# Flush trailing stats block
if in_stats and ctx_stats and ctx_client and ctx_date:
    stats_store[ctx_client][ctx_date] = dict(ctx_stats)

# ── Build output ─────────────────────────────────────────────────────────────
all_clients = sorted(set(list(watermarks) + list(pushes) + list(stats_store)))
all_dates   = sorted(set(
    d for cid in all_clients
    for d in list(watermarks.get(cid, {})) + list(pushes.get(cid, {})) + list(stats_store.get(cid, {}))
))

output = {
    'meta': {
        'date_range': f'{DATE_START} to {DATE_END}',
        'clients_with_data': len(all_clients),
        'dates_with_data': len(all_dates),
        'update_data_call_totals': {d: dict(v) for d, v in sorted(update_by_date.items())},
    },
    'by_date': {},
    'by_client': {},
}

for date in all_dates:
    de = {
        'update_data_calls': update_by_date.get(date, {}).get('total', 0),
        'update_data_ok':    update_by_date.get(date, {}).get('ok', 0),
        'clients': {},
    }
    for cid in all_clients:
        wm = watermarks.get(cid, {}).get(date)
        ps = pushes.get(cid, {}).get(date, [])
        st = stats_store.get(cid, {}).get(date)
        hd = hedge_days.get(cid, {}).get(date, [])
        if not any([wm, ps, st, hd]):
            continue
        de['clients'][cid] = {
            'push_count': len(ps),
            'last_push': ps[-1] if ps else None,
            'all_pushes': ps,
            'watermark': wm,
            'stats': st,
            'hedge_day_assignments': hd,
        }
    output['by_date'][date] = de

for cid in all_clients:
    client_dates = sorted(set(
        list(watermarks.get(cid, {})) + list(pushes.get(cid, {})) + list(stats_store.get(cid, {}))
    ))
    daily = {}
    for date in client_dates:
        wm = watermarks.get(cid, {}).get(date)
        ps = pushes.get(cid, {}).get(date, [])
        st = stats_store.get(cid, {}).get(date)
        hd = hedge_days.get(cid, {}).get(date, [])
        lp = ps[-1] if ps else None
        daily[date] = {
            'push_count':           len(ps),
            'last_balance':         lp['balance']              if lp else None,
            'last_deals':           lp['deals']                if lp else None,
            'last_eval_count':      lp['eval_count']           if lp else None,
            'new_evals':            lp.get('new_evals')        if lp else None,
            'preserved_evals':      lp.get('preserved_evals')  if lp else None,
            'all_pushes':           ps,
            'watermark_net_profit': wm['net_profit_complete']  if wm else None,
            'watermark_source':     wm['source']               if wm else None,
            'watermark_created_at': wm['created_at']           if wm else None,
            'stats':                st,
            'hedge_day_assignments': hd,
        }
    output['by_client'][cid] = {
        'active_dates': client_dates,
        'total_push_count': sum(len(pushes.get(cid, {}).get(d, [])) for d in client_dates),
        'daily': daily,
    }

# ── Write ────────────────────────────────────────────────────────────────────
out_path = '/home/ballerquotes/MT5Dashboard/recovered_full_v2.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2)

# ── Print summary ────────────────────────────────────────────────────────────
print(f'\n{"="*70}')
print(f'SUMMARY')
print(f'{"="*70}')
print(f'Clients with any data: {len(all_clients)}')
print(f'Dates covered:         {", ".join(all_dates)}')

print(f'\n{"─"*70}')
print(f'UPDATE_DATA CALLS BY DATE')
print(f'{"─"*70}')
print(f'{"Date":<14} {"Total":>8} {"200 OK":>8}')
for d in sorted(update_by_date):
    r = update_by_date[d]
    print(f'{d:<14} {r["total"]:>8} {r["ok"]:>8}')

print(f'\n{"─"*70}')
print(f'PER-CLIENT SUMMARY (pushes + watermarks)')
print(f'{"─"*70}')
print(f'{"Client":<30} {"Dates active":<38} {"Total pushes":>12}')
for cid in all_clients:
    c = output["by_client"][cid]
    dates_str = ', '.join(c['active_dates'])
    print(f'{cid:<30} {dates_str:<38} {c["total_push_count"]:>12}')

print(f'\n{"─"*70}')
print(f'WATERMARKS RECOVERED')
print(f'{"─"*70}')
print(f'{"Client":<30} {"Date":<12} {"Net Profit":>12} {"Source":<8} Created At')
for cid in all_clients:
    for date, wm in sorted(watermarks.get(cid, {}).items()):
        print(f'{cid:<30} {date:<12} {wm["net_profit_complete"]:>12.2f} {wm["source"]:<8} {wm["created_at"]}')

print(f'\n{"─"*70}')
print(f'LAST PUSH PER CLIENT PER DATE (evaluation view)')
print(f'{"─"*70}')
print(f'{"Client":<30} {"Date":<12} {"Balance":>12} {"Deals":>6} {"Evals":>6} {"NewEv":>6} {"PreEv":>6}')
for cid in all_clients:
    for date, info in sorted(output['by_client'][cid]['daily'].items()):
        if info['last_balance'] is not None:
            print(f'{cid:<30} {date:<12} {info["last_balance"]:>12.2f} '
                  f'{info["last_deals"] or 0:>6} {info["last_eval_count"] or 0:>6} '
                  f'{str(info["new_evals"] or "-"):>6} {str(info["preserved_evals"] or "-"):>6}')

print(f'\nJSON → {out_path}')
print('Done.')
