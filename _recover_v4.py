# -*- coding: utf-8 -*-
"""
V4 Deep Recovery - data_history + log mining + inference.
Pure ASCII version for PythonAnywhere paste compatibility.
Run: python3 /home/ballerquotes/MT5Dashboard/_recover_v4.py "Chris Ream"
     python3 /home/ballerquotes/MT5Dashboard/_recover_v4.py --all
"""
import sys, os, re, json, gzip, csv, sqlite3
from collections import defaultdict

DB_PATH = '/home/ballerquotes/MT5Dashboard/dashboard/dashboard.db'
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
CORRUPTION_START = '2026-03-26'
CORRUPTION_END   = '2026-04-03'
OUTPUT_DIR = '/home/ballerquotes/MT5Dashboard'

PREFIX_TO_FIRM = {
    'MFFU': 'My Funded Futures', 'FNFT': 'FundedNext', 'TDFY': 'Tradeify',
    'V2': 'Topstep', '50KTC': 'Topstep', 'TDF': 'TradeDay', 'ELTD': 'TradeDay',
    'FTDF': 'TradeDay', 'AFAD': 'Alpha Futures', 'APEX': 'Apex',
    'TAKEPROFIT': 'Take Profit Trader',
}
SIZE_PATTERNS = {
    'SL50': '$50,000', 'SL100': '$100,000', 'SL150': '$150,000',
    '50KTC': '$50,000', '100KTC': '$100,000', '150KTC': '$150,000',
    'EVFLX': '$50,000', 'EVSTP': '$50,000', 'EVESC': '$50,000',
    'EVRPD': '$100,000', 'SFFLX': '$50,000', 'SFSTP': '$50,000',
}
FEE_LOOKUP = {
    ('My Funded Futures', '$50,000'): '$107.00',
    ('My Funded Futures', '$100,000'): '$267.00',
    ('My Funded Futures', '$150,000'): '$397.00',
    ('FundedNext', '$50,000'): '$137.99',
    ('Topstep', '$50,000'): '$109.00',
    ('Topstep', '$100,000'): '$159.00',
    ('Tradeify', '$50,000'): '$95.00',
    ('TradeDay', '$50,000'): '$95.00',
    ('Alpha Futures', '$50,000'): '$95.00',
}
CSV_COLUMNS = [
    'Prop Firm','Account Size','Date Purchased','Fee','Date Started','Date Ended',
    'Status P1','Account #',
    'Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4',
    'Hedge Result 5','Hedge Net',
    'Activation Fee','Account #.1','Date Started.1','Date Ended.1','Status',
    'Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1','Hedge Result 4.1',
    'Hedge Result 5.1','Hedge Net.1',
    'Payout 1','Date 1','Payout 2','Date 2','Payout 3','Date 3','Payout 4','Date 4',
]
for i in range(1, 31):
    CSV_COLUMNS.append('Prop Day %d' % i)
    CSV_COLUMNS.append('Hedge Day %d' % i)
CSV_COLUMNS.extend(['Farming Net', 'Account Number'])

# Emoji constants as unicode escapes (safe for heredoc paste)
E_CHECK = '\u2705'       # checkmark
E_WHEAT = '\U0001f33e'   # wheat/farm
E_FOLDER = '\U0001f4c2'  # folder
E_PERSON = '\U0001f464'  # person
E_LABEL = '\U0001f3f7'   # label
E_ARROW = '\u2192'        # right arrow
E_DBAR = '\u2550'         # double bar


def open_log(path):
    try:
        if path.endswith('.gz'):
            return gzip.open(path, 'rt', encoding='utf-8', errors='replace')
        return open(path, 'r', encoding='utf-8', errors='replace')
    except FileNotFoundError:
        return None


def infer_firm(acct):
    if not acct:
        return None
    a = str(acct).upper()
    for prefix in sorted(PREFIX_TO_FIRM.keys(), key=len, reverse=True):
        if prefix in a:
            return PREFIX_TO_FIRM[prefix]
    return None


def infer_size(acct):
    if not acct:
        return None
    a = str(acct).upper()
    for pat, size in SIZE_PATTERNS.items():
        if pat in a:
            return size
    m = re.search(r'SL(\d+)', a)
    if m:
        num = int(m.group(1))
        if num <= 50: return '$50,000'
        elif num <= 100: return '$100,000'
        elif num <= 150: return '$150,000'
    return None


def acc_tail(acct):
    if not acct:
        return ''
    m = re.search(r'(\d{4,})$', str(acct).strip())
    return m.group(1) if m else str(acct).strip().upper()


def row_keys(ev):
    keys = set()
    for f in ('Account #', 'Account #.1', 'Account Number'):
        v = str(ev.get(f, '')).strip()
        if v and v != '-':
            keys.add(v.upper())
            t = acc_tail(v)
            if t:
                keys.add(t)
    return keys


def empty(val):
    if val is None:
        return True
    s = str(val).strip()
    return s in ('', '-', 'None', 'nan')


def load_current(client_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT evaluations FROM clients_data WHERE client_id = ?", (client_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return []
    return json.loads(row['evaluations'])


def load_history(client_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT version, created_at, evaluations FROM data_history "
        "WHERE client_id = ? ORDER BY version ASC", (client_id,))
    results = []
    for row in cur.fetchall():
        try:
            results.append((row['version'], row['created_at'], json.loads(row['evaluations'])))
        except Exception:
            pass
    conn.close()
    return results


def build_index(history):
    by_acc = defaultdict(list)
    by_pos = defaultdict(list)
    for ver, ts, evals in history:
        for idx, ev in enumerate(evals):
            entry = (ver, ts, dict(ev))
            by_pos[idx].append(entry)
            for f in ('Account #', 'Account #.1', 'Account Number'):
                v = str(ev.get(f, '')).strip()
                if v and v not in ('-', ''):
                    by_acc[v.upper()].append(entry)
                    t = acc_tail(v)
                    if t and t != v.upper():
                        by_acc[t].append(entry)
    return by_acc, by_pos


def mine_logs(client_name):
    field_updates = {}
    account_maps = {}
    trade_sums = []
    pushes = []
    hday_slots = {}
    all_vals = defaultdict(set)
    watermarks = {}
    direct = {}

    nl = client_name.lower()
    parts = nl.split()
    pats = [nl]
    if len(parts) >= 2:
        pats.append(parts[0] + '%20' + parts[1])
        pats.append(parts[0] + '+' + parts[1])
        pats.append(parts[0] + '_' + parts[1])

    # Regex patterns using unicode escapes instead of literal emojis
    RE_MSESS = re.compile(
        r'Matched session \(Start (.+?)\) -> Column: \[(.+?)\] \| Row: (\d+) \| New Value: \$([\-\d.]+)')
    RE_DIRECT = re.compile(
        E_CHECK + r'\s+(\S+)\s+\((\S+)\)\s+_(\w+)\s*' + E_ARROW + r'\s*\[(.+?)\]\s*=\s*\$([\-\d.,]+)')
    RE_ACCUM = re.compile(
        r'\[Accumulated\]\s*' + E_ARROW + r'\s*Eval\s*#(\d+)\s+\[(.+?)\]\s*=\s*\$([\-\d.,]+)')
    RE_FARM = re.compile(
        E_WHEAT + r'\s*Row\s*(\d+)\s*\|\s*Hedge Day\s*(\d+):\s*\$([\-\d.,]+)\s*\((\d{4}-\d{2}-\d{2})\)')
    RE_PUSH = re.compile(
        r'Push for (.+?):\s*(\d+) deals.*?balance=([\-\d.]+).*?(\d+) evaluations')
    RE_WM = re.compile(
        r'Saved daily watermark for (.+?) on (\d{4}-\d{2}-\d{2}):\s*\$([\-\d.]+)\s*\((\w+)\)')
    RE_FIRM = re.compile(E_FOLDER + r'\s+(.+?)\s+\((\d+) trades?\)')
    RE_ACCT = re.compile(E_PERSON + r'\s+Dashboard Account:\s*(\S+)\s*\((\d+) trades?\)')
    RE_PHASE = re.compile(E_LABEL + r'\ufe0f?\s*Phase\s+(\S+)\s*->\s*\[(.+?)\]\s*\(Row\s*#(\d+)\)')
    RE_PROFIT = re.compile(r'- Profit:\s*\$([\-\d.,]+)')
    RE_SRC = re.compile(r'- Source ID\(s\):\s*(.+)')
    RE_MT5 = re.compile(r'MATCHED:\s*MT5 Account\s+(\S+)\s*->\s*Dashboard Account\s+(\S+)')
    RE_SESS = re.compile(
        r'\[SESSION\]\s+account_guess=(\S+)\s+best_phase=(\w+)\s+best_num=(\d+).*?profit=([\-\d.]+)')
    RE_LEG = re.compile(
        r'(\S+)\s*' + E_ARROW + r'\s*Row\s*(\d+)\s+\[(.+?)\]\s*=\s*\$([\-\d.,]+)')

    ctx_firm = None
    ctx_acct = None
    ctx_in = False

    for lp in LOG_FILES:
        fh = open_log(lp)
        if not fh:
            continue
        with fh:
            for raw in fh:
                ll = raw.lower()
                is_cl = any(p in ll for p in pats)
                if is_cl:
                    ctx_in = True
                if not is_cl and not ctx_in:
                    continue
                if ctx_in and not is_cl:
                    if E_DBAR * 5 in raw or ('Push for ' in raw and not is_cl):
                        ctx_in = False
                        ctx_firm = None
                        ctx_acct = None
                        continue
                line = raw.strip()
                if not line:
                    continue

                m = RE_PUSH.search(line)
                if m and nl in m.group(1).lower():
                    pushes.append({
                        'client': m.group(1), 'deals': int(m.group(2)),
                        'balance': float(m.group(3)), 'eval_count': int(m.group(4)),
                        'date': line[:10]})
                    ctx_in = True
                    continue

                m = RE_WM.search(line)
                if m and nl in m.group(1).lower():
                    watermarks[(m.group(2), m.group(4))] = float(m.group(3))
                    continue

                m = RE_MSESS.search(line)
                if m:
                    field_updates[(int(m.group(3)), m.group(2))] = m.group(4)
                    all_vals[m.group(2)].add(m.group(4))
                    continue

                m = RE_DIRECT.search(line)
                if m:
                    a = m.group(1)
                    if a not in direct: direct[a] = {}
                    direct[a][m.group(4)] = m.group(5)
                    all_vals[m.group(4)].add(m.group(5))
                    continue

                m = RE_ACCUM.search(line)
                if m:
                    field_updates[(int(m.group(1)), m.group(2))] = m.group(3)
                    all_vals[m.group(2)].add(m.group(3))
                    continue

                m = RE_FARM.search(line)
                if m:
                    hday_slots[(int(m.group(1)), int(m.group(2)))] = (m.group(3), m.group(4))
                    continue

                m = RE_SESS.search(line)
                if m:
                    a = m.group(1)
                    if a not in direct: direct[a] = {}
                    direct[a]['_sp'] = m.group(2)
                    direct[a]['_sn_%s' % m.group(3)] = m.group(4)
                    continue

                m = RE_LEG.search(line)
                if m:
                    field_updates[(int(m.group(2)), m.group(3))] = m.group(4)
                    all_vals[m.group(3)].add(m.group(4))
                    continue

                m = RE_MT5.search(line)
                if m:
                    account_maps[m.group(1)] = m.group(2)
                    continue

                m = RE_FIRM.search(line)
                if m:
                    ctx_firm = m.group(1)
                    ctx_in = True
                    continue
                m = RE_ACCT.search(line)
                if m:
                    ctx_acct = m.group(1)
                    continue
                m = RE_PHASE.search(line)
                if m:
                    trade_sums.append({
                        'firm': ctx_firm, 'acct': ctx_acct, 'phase': m.group(1),
                        'field': m.group(2), 'row': int(m.group(3))})
                    continue
                m = RE_PROFIT.search(line)
                if m and trade_sums:
                    trade_sums[-1]['profit'] = m.group(1)
                    continue
                m = RE_SRC.search(line)
                if m and trade_sums:
                    trade_sums[-1]['source_ids'] = m.group(1).strip()
                    continue

    return {
        'field_updates': field_updates, 'account_maps': account_maps,
        'trade_sums': trade_sums, 'pushes': pushes,
        'hday_slots': hday_slots, 'all_vals': all_vals,
        'watermarks': watermarks, 'direct': direct,
    }


def merge(evals, by_acc, by_pos, ld):
    fu = ld['field_updates']
    ts = ld['trade_sums']
    dm = ld['direct']
    hds = ld['hday_slots']
    filled = 0

    for idx, ev in enumerate(evals):
        rn = idx + 2
        rk = row_keys(ev)

        # Source 1: history by account
        bh = None
        bts = ''
        for k in rk:
            if k in by_acc:
                for v, t, he in by_acc[k]:
                    if not bh or t > bts:
                        bh = he
                        bts = t
        if not bh and idx in by_pos:
            for v, t, he in reversed(by_pos[idx]):
                hk = row_keys(he)
                if rk & hk or (not rk and not hk):
                    bh = he
                    bts = t
                    break
        if bh:
            for f in list(bh.keys()):
                if f.startswith('_'): continue
                if empty(ev.get(f)) and not empty(bh.get(f)):
                    ev[f] = bh[f]
                    filled += 1

        # Source 2: log field updates
        for (r, fn), val in fu.items():
            if r == rn and empty(ev.get(fn)):
                ev[fn] = val
                filled += 1

        # Source 3: direct matches
        for k in rk:
            if k in dm:
                for fn, val in dm[k].items():
                    if not fn.startswith('_') and empty(ev.get(fn)):
                        ev[fn] = val
                        filled += 1

        # Source 4: hedge day slots
        for (r, slot), (val, dt) in hds.items():
            if r == rn:
                hf = 'Hedge Day %d' % slot
                if empty(ev.get(hf)):
                    ev[hf] = val
                    filled += 1

        # Source 5: trade summaries
        for te in ts:
            if te.get('row') == rn:
                if empty(ev.get('Prop Firm')) and te.get('firm'):
                    ev['Prop Firm'] = te['firm']
                    filled += 1
                fld = te.get('field', '')
                if fld and empty(ev.get(fld)) and te.get('profit'):
                    ev[fld] = te['profit']
                    filled += 1

        # Source 6: inference
        an = str(ev.get('Account #', '') or '').strip()
        a1 = str(ev.get('Account #.1', '') or '').strip()
        ad = str(ev.get('Account Number', '') or '').strip()
        aa = [x for x in [an, a1, ad] if x and x != '-']

        if empty(ev.get('Prop Firm')):
            for a in aa:
                firm = infer_firm(a)
                if firm:
                    ev['Prop Firm'] = firm
                    filled += 1
                    break

        if empty(ev.get('Account Size')):
            for a in aa:
                sz = infer_size(a)
                if sz:
                    ev['Account Size'] = sz
                    filled += 1
                    break
            if empty(ev.get('Account Size')) and not empty(ev.get('Prop Firm')):
                ev['Account Size'] = '$50,000'
                filled += 1

        if empty(ev.get('Fee')):
            firm = ev.get('Prop Firm', '')
            size = ev.get('Account Size', '')
            if (firm, size) in FEE_LOOKUP:
                ev['Fee'] = FEE_LOOKUP[(firm, size)]
                filled += 1

        if empty(ev.get('Account #')) and ad:
            for k in rk:
                if k in by_acc:
                    for _, _, he in by_acc[k]:
                        ha = he.get('Account #', '')
                        if ha and str(ha).strip() not in ('', '-'):
                            ev['Account #'] = ha
                            filled += 1
                            break
                    if not empty(ev.get('Account #')):
                        break

        if empty(ev.get('Account Number')) and an:
            short = an
            for prefix in sorted(PREFIX_TO_FIRM.keys(), key=len, reverse=True):
                if prefix in an.upper():
                    t = acc_tail(an)
                    if t:
                        short = '%s-%s' % (prefix, t[-5:])
                    break
            ev['Account Number'] = short

        if empty(ev.get('Date Started')):
            for te in ts:
                if te.get('row') == rn and te.get('date'):
                    ev['Date Started'] = te['date']
                    filled += 1
                    break

    return evals, filled


def export_csv(client_id, evals, path):
    all_cols = set()
    for ev in evals:
        all_cols.update(k for k in ev.keys() if not k.startswith('_'))
    ordered = []
    seen = set()
    for c in CSV_COLUMNS:
        if c in all_cols:
            ordered.append(c)
            seen.add(c)
    for c in sorted(all_cols - seen):
        ordered.append(c)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(ordered)
        for ev in evals:
            w.writerow([str(ev.get(c, '') or '') for c in ordered])
    return path


def recover(client_id):
    print('')
    print('=' * 60)
    print(' V4 DEEP RECOVERY: %s' % client_id)
    print('=' * 60)

    print('\n[1/6] Loading current evaluations...')
    cur = load_current(client_id)
    print('  -> %d rows' % len(cur))

    print('\n[2/6] Loading data_history...')
    hist = load_history(client_id)
    print('  -> %d versions' % len(hist))
    if hist:
        dates = [h[1] for h in hist]
        pre = [d for d in dates if d < CORRUPTION_START]
        dur = [d for d in dates if CORRUPTION_START <= d <= CORRUPTION_END]
        post = [d for d in dates if d > CORRUPTION_END]
        print('    Pre-corruption: %d, During: %d, Post: %d' % (len(pre), len(dur), len(post)))
        if pre:
            print('    Latest pre-corruption: %s' % pre[-1])

    print('\n[3/6] Building history index...')
    by_acc, by_pos = build_index(hist)
    print('  -> %d account keys, %d positions' % (len(by_acc), len(by_pos)))

    print('\n[4/6] Mining logs...')
    ld = mine_logs(client_id)
    print('  -> %d field updates' % len(ld['field_updates']))
    print('  -> %d MT5 mappings' % len(ld['account_maps']))
    print('  -> %d trade summaries' % len(ld['trade_sums']))
    print('  -> %d push events' % len(ld['pushes']))
    print('  -> %d hedge day slots' % len(ld['hday_slots']))
    print('  -> %d direct matches' % len(ld['direct']))

    print('\n[5/6] Merging...')
    eb = sum(1 for ev in cur for k, v in ev.items() if empty(v) and not k.startswith('_'))
    merged, filled = merge(cur, by_acc, by_pos, ld)
    ea = sum(1 for ev in merged for k, v in ev.items() if empty(v) and not k.startswith('_'))
    print('  -> Filled %d values' % filled)
    print('  -> Empty cells: %d -> %d (recovered %d)' % (eb, ea, eb - ea))

    print('\n  Gap analysis:')
    gaps = 0
    for idx, ev in enumerate(merged):
        miss = []
        for key in ['Prop Firm', 'Account Size', 'Date Purchased', 'Fee',
                     'Date Started', 'Account #', 'Status P1']:
            if empty(ev.get(key)):
                miss.append(key)
        if miss:
            gaps += 1
            ac = ev.get('Account Number', '') or ev.get('Account #', '') or 'Row %d' % (idx + 2)
            if gaps <= 30:
                print('    Row %d (%s): missing %s' % (idx + 2, ac, ', '.join(miss)))
    if gaps > 30:
        print('    ... and %d more' % (gaps - 30))
    if gaps == 0:
        print('    All critical fields filled!')

    print('\n[6/6] Exporting CSV...')
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', client_id)
    out = os.path.join(OUTPUT_DIR, '_recovery_%s.csv' % safe)
    export_csv(client_id, merged, out)
    print('  -> Saved: %s' % out)
    print('  -> %d rows' % len(merged))
    return out


def list_clients():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT client_id FROM clients_data ORDER BY client_id")
    clients = [r[0] for r in cur.fetchall()]
    conn.close()
    return clients


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python3 _recover_v4.py "Client Name"')
        print('       python3 _recover_v4.py --all')
        sys.exit(1)
    if sys.argv[1] == '--all':
        cl = list_clients()
        print('Recovering all %d clients...' % len(cl))
        for c in cl:
            try:
                recover(c)
            except Exception as e:
                print('  ERROR for %s: %s' % (c, e))
    else:
        cid = ' '.join(sys.argv[1:])
        recover(cid)
