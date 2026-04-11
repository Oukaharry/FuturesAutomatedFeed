import sys, os, json, sqlite3, csv, re, gzip
from collections import defaultdict
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard', 'dashboard.db')
RECOVERY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recovered_eval_data_v3.json')
RECOVER_FROM = '2026-03-26'; RECOVER_TO = '2026-04-03'
OUT_DIR = '/home/ballerquotes/MT5Dashboard'
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
PREFIX_TO_FIRM = {
    'MFFU': 'My Funded Futures', 'FNFT': 'FundedNext', 'TDFY': 'Tradeify',
    'V2': 'Topstep', '50KTC': 'Topstep', 'TDF': 'TradeDay', 'ELTD': 'TradeDay',
    'FTDF': 'TradeDay', 'AFAD': 'Alpha Futures', 'APEX': 'Apex',
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

def get_conn():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; return conn

def empty(v):
    if v is None: return True
    s = str(v).strip()
    return s in ('', '-', 'None', 'nan', 'null')

def acc_tail(a):
    if not a: return ''
    m = re.search(r'(\d{4,})$', str(a).strip())
    return m.group(1) if m else str(a).strip().upper()

def infer_firm(a):
    if not a: return None
    u = str(a).upper()
    for p in sorted(PREFIX_TO_FIRM, key=len, reverse=True):
        if p in u: return PREFIX_TO_FIRM[p]
    return None

def infer_size(a):
    if not a: return None
    u = str(a).upper()
    for p, s in SIZE_PATTERNS.items():
        if p in u: return s
    return None

def open_log(p):
    try:
        if p.endswith('.gz'): return gzip.open(p, 'rt', encoding='utf-8', errors='replace')
        return open(p, 'r', encoding='utf-8', errors='replace')
    except FileNotFoundError:
        return None

# ============================================================
# PHASE A: Load data_history snapshots, build per-row best data
# ============================================================
def load_best_history(client_id):
    """For each eval row position AND each account number, find the best historical data."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT version, created_at, evaluations FROM data_history "
        "WHERE client_id = ? ORDER BY version ASC", (client_id,)).fetchall()
    conn.close()
    # by_pos[idx] = best eval dict (latest version)
    # by_acc[tail] = best eval dict (latest version)
    by_pos = {}
    by_acc = {}
    n_versions = 0
    for row in rows:
        try:
            evals = json.loads(row['evaluations'])
        except Exception:
            continue
        n_versions += 1
        for idx, ev in enumerate(evals):
            # Always overwrite with latest version (rows are ASC order)
            by_pos[idx] = dict(ev)
            for fld in ('Account #', 'Account #.1', 'Account Number'):
                v = str(ev.get(fld, '')).strip()
                if v and v not in ('-', ''):
                    by_acc[v.upper()] = dict(ev)
                    t = acc_tail(v)
                    if t: by_acc[t] = dict(ev)
    return by_pos, by_acc, n_versions

# ============================================================
# PHASE B: Mine logs for field values for this client
# ============================================================
def mine_logs(client_name):
    """Extract field updates from logs: Matched session, trade summaries, etc."""
    field_updates = {}  # (row, field) -> value
    nl = client_name.lower()
    parts = nl.split()
    pats = [nl]
    if len(parts) >= 2:
        pats.extend([parts[0] + '%20' + parts[1], parts[0] + '+' + parts[1]])

    # Pattern: Matched session (Start ...) -> Column: [field] | Row: N | New Value: $X
    RE_MSESS = re.compile(
        r'Matched session \(Start .+?\) -> Column: \[(.+?)\] \| Row: (\d+) \| New Value: \$([\-\d.]+)')
    # Pattern: [Accumulated] -> Eval #N [field] = $value
    RE_ACCUM = re.compile(
        r'\[Accumulated\].*?Eval\s*#(\d+)\s+\[(.+?)\]\s*=\s*\$([\-\d.,]+)')
    # Farm: Row N | Hedge Day M: $value (date)
    RE_FARM = re.compile(
        r'Row\s*(\d+)\s*\|\s*Hedge Day\s*(\d+):\s*\$([\-\d.,]+)\s*\((\d{4}-\d{2}-\d{2})\)')
    # Phase line from trade summary
    RE_PHASE = re.compile(
        r'Phase\s+(\S+)\s*->\s*\[(.+?)\]\s*\(Row\s*#(\d+)\)')
    RE_PROFIT = re.compile(r'- Profit:\s*\$([\-\d.,]+)')
    RE_SRC = re.compile(r'- Source ID\(s\):\s*(.+)')
    # Dashboard Account line
    RE_DACCT = re.compile(r'Dashboard Account:\s*(\S+)')
    # Firm line
    RE_DFIRM = re.compile(r'^\s+.*?([A-Z][a-zA-Z ]+(?:Futures|Next|step|ify|Day|Apex))\s*\(\d+ trades?\)')
    # Push for client
    RE_PUSH = re.compile(r'Push for (.+?):\s*(\d+) deals.*?balance=([\-\d.]+).*?(\d+) evaluations')
    # Short account number (prop firm customer IDs like MFFU-09008, V2-6807, TDF-97386)
    RE_SHORT_ACCT = re.compile(
        r'\b((?:50KTC|FTDF|ELTD|MFFU|FNFT|TDFY|TDF|AFAD|APEX|V2)-[A-Z0-9]+)\b',
        re.IGNORECASE)
    # Long Tradovate/MT5 account number
    RE_LONG_ACCT = re.compile(
        r'\b((?:MFFUEVSTP|MFFUEVSCL|MFFUSFSCL|MFFUSFFLX|MFFUEVFLX|FTPROPLUS)[0-9]+)\b',
        re.IGNORECASE)

    ctx_in = False
    ctx_firm = None
    ctx_acct = None
    ctx_short_acct = None
    last_phase_row = None
    n_matched = 0
    row_acct_map = {}   # row_num (2-based) -> short Account Number
    long_to_short = {}  # long acct upper/tail -> short Account Number

    for lp in LOG_FILES:
        fh = open_log(lp)
        if not fh: continue
        with fh:
            for raw in fh:
                ll = raw.lower()
                is_cl = any(p in ll for p in pats)
                if is_cl: ctx_in = True
                if not is_cl and not ctx_in: continue
                # End context block
                if ctx_in and not is_cl and '=====' in raw:
                    ctx_in = False; ctx_firm = None; ctx_acct = None; ctx_short_acct = None; continue
                if ctx_in and not is_cl and 'Push for ' in raw and not is_cl:
                    ctx_in = False; ctx_firm = None; ctx_acct = None; ctx_short_acct = None; continue
                line = raw.strip()
                if not line: continue

                # Matched session
                m = RE_MSESS.search(line)
                if m:
                    rn_ms = int(m.group(2))
                    field_updates[(rn_ms, m.group(1))] = m.group(3)
                    n_matched += 1
                    # Capture short account number from same line or context
                    sa_ms = RE_SHORT_ACCT.search(line)
                    if sa_ms and rn_ms not in row_acct_map:
                        row_acct_map[rn_ms] = sa_ms.group(1)
                    elif ctx_short_acct and rn_ms not in row_acct_map:
                        row_acct_map[rn_ms] = ctx_short_acct
                    continue

                # Accumulated
                m = RE_ACCUM.search(line)
                if m:
                    field_updates[(int(m.group(1)), m.group(2))] = m.group(3)
                    n_matched += 1; continue

                # Farm day
                m = RE_FARM.search(line)
                if m:
                    field_updates[(int(m.group(1)), 'Hedge Day %s' % m.group(2))] = m.group(3)
                    n_matched += 1; continue

                # Trade summary context
                m = RE_DFIRM.search(line)
                if m: ctx_firm = m.group(1).strip(); continue
                m = RE_DACCT.search(line)
                if m:
                    ctx_acct = m.group(1)
                    if RE_SHORT_ACCT.search(m.group(1)):
                        ctx_short_acct = m.group(1)
                    continue
                m = RE_PHASE.search(line)
                if m:
                    r = int(m.group(3))
                    field_updates[(r, m.group(2))] = None  # placeholder for profit
                    last_phase_row = (r, m.group(2))
                    if ctx_short_acct and r not in row_acct_map:
                        row_acct_map[r] = ctx_short_acct
                    continue
                m = RE_PROFIT.search(line)
                if m and last_phase_row:
                    field_updates[last_phase_row] = m.group(1)
                    last_phase_row = None; continue

                # Extract long-to-short account mapping from any line in context
                la = RE_LONG_ACCT.search(line)
                sa = RE_SHORT_ACCT.search(line)
                if la and sa:
                    long_to_short[la.group(1).upper()] = sa.group(1)
                    lt = acc_tail(la.group(1))
                    if lt: long_to_short[lt] = sa.group(1)
                elif sa:
                    # Track most recent short account seen in context
                    ctx_short_acct = sa.group(1)

    return field_updates, n_matched, row_acct_map, long_to_short

# ============================================================
# MAIN EXPORT
# ============================================================
def export(client_id):
    conn = get_conn()
    row = conn.execute("SELECT evaluations FROM clients_data WHERE client_id = ?", (client_id,)).fetchone()
    conn.close()
    if not row:
        print('ERROR: "%s" not found.' % client_id)
        conn = get_conn()
        for m in conn.execute("SELECT client_id FROM clients_data WHERE client_id LIKE ?",
                              ('%' + client_id + '%',)).fetchall():
            print('  - %s' % m['client_id'])
        conn.close(); return

    evals = json.loads(row['evaluations'] or '[]')
    print('\n[1/5] Loaded %d eval rows from DB' % len(evals))

    # Load v3 recovery overlay
    hedge_updates = []; farm_updates = []
    if os.path.exists(RECOVERY_PATH):
        with open(RECOVERY_PATH) as f: recovery = json.load(f)
        cr = recovery.get('clients', {}).get(client_id, {})
        hedge_updates = [h for h in cr.get('hedge_updates', []) if RECOVER_FROM <= h.get('timestamp','') < RECOVER_TO]
        farm_updates  = [f for f in cr.get('farm_updates',  []) if RECOVER_FROM <= f.get('timestamp','') < RECOVER_TO]
        print('[2/5] V3 recovery: %d hedge + %d farm updates' % (len(hedge_updates), len(farm_updates)))
    else:
        print('[2/5] No v3 recovery file found (skipping)')

    # Build v3 overlay map
    v3_fields = {}
    for hu in sorted(hedge_updates, key=lambda x: x.get('timestamp','')):
        rn = hu.get('row')
        if rn is None: continue
        v3_fields.setdefault(rn, {})[hu['field']] = hu['value']
    for fu in sorted(farm_updates, key=lambda x: x.get('timestamp','')):
        rn = fu.get('row')
        if rn is None: continue
        v3_fields.setdefault(rn, {})[fu['field']] = fu['value']

    # Load data_history
    hist_pos, hist_acc, n_ver = load_best_history(client_id)
    print('[3/5] data_history: %d versions, %d positions, %d account keys' % (n_ver, len(hist_pos), len(hist_acc)))

    # Mine logs
    log_fields, n_log, row_acct_map, long_to_short = mine_logs(client_id)
    print('[4/5] Log mining: %d field values, %d row-acct mappings, %d long-to-short mappings' % (n_log, len(row_acct_map), len(long_to_short)))

    # MERGE: For each eval row, layer sources
    filled = 0
    merged_evals = []
    for i, ev in enumerate(evals):
        rn = i + 1  # 1-based row (v3 uses this)
        rn2 = i + 2  # 2-based row (log Matched session uses this)
        merged = dict(ev)
        for k in ['_notes', '_recovered', '_rec', '_edited_timestamp']:
            merged.pop(k, None)

        # --- SOURCE 1: data_history by position ---
        if i in hist_pos:
            hev = hist_pos[i]
            for fld in hev:
                if fld.startswith('_'): continue
                if empty(merged.get(fld)) and not empty(hev.get(fld)):
                    merged[fld] = hev[fld]; filled += 1

        # --- SOURCE 1b: data_history by account key ---
        for afld in ('Account #', 'Account #.1', 'Account Number'):
            av = str(merged.get(afld, '')).strip().upper()
            if av and av != '-' and av in hist_acc:
                hev = hist_acc[av]
                for fld in hev:
                    if fld.startswith('_'): continue
                    if empty(merged.get(fld)) and not empty(hev.get(fld)):
                        merged[fld] = hev[fld]; filled += 1
            t = acc_tail(av)
            if t and t in hist_acc:
                hev = hist_acc[t]
                for fld in hev:
                    if fld.startswith('_'): continue
                    if empty(merged.get(fld)) and not empty(hev.get(fld)):
                        merged[fld] = hev[fld]; filled += 1

        # --- SOURCE 2: v3 recovery overlay ---
        if rn in v3_fields:
            merged.update(v3_fields[rn]); filled += 1

        # --- SOURCE 3: log field updates ---
        for (r, fn), val in log_fields.items():
            if r == rn2 and val is not None and empty(merged.get(fn)):
                merged[fn] = val; filled += 1

        # --- SOURCE 4: inference from Account Number / Account # ---
        all_accts = []
        for afld in ('Account #', 'Account #.1', 'Account Number'):
            av = str(merged.get(afld, '')).strip()
            if av and av != '-': all_accts.append(av)

        if empty(merged.get('Prop Firm')):
            for a in all_accts:
                f = infer_firm(a)
                if f: merged['Prop Firm'] = f; filled += 1; break

        if empty(merged.get('Account Size')):
            for a in all_accts:
                s = infer_size(a)
                if s: merged['Account Size'] = s; filled += 1; break
            if empty(merged.get('Account Size')) and not empty(merged.get('Prop Firm')):
                merged['Account Size'] = '$50,000'; filled += 1

        if empty(merged.get('Fee')):
            firm = merged.get('Prop Firm', '')
            size = merged.get('Account Size', '')
            if (firm, size) in FEE_LOOKUP:
                merged['Fee'] = FEE_LOOKUP[(firm, size)]; filled += 1

        # Infer Account # from Account Number via history lookup
        if empty(merged.get('Account #')):
            an = str(merged.get('Account Number', '')).strip()
            if an and an != '-':
                t = acc_tail(an)
                if t and t in hist_acc:
                    ha = hist_acc[t].get('Account #', '')
                    if ha and str(ha).strip() not in ('', '-'):
                        merged['Account #'] = ha; filled += 1

        # --- SOURCE 5: Account Number from log mining ---
        if empty(merged.get('Account Number')):
            if rn2 in row_acct_map:
                merged['Account Number'] = row_acct_map[rn2]; filled += 1
            else:
                for afld in ('Account #', 'Account #.1'):
                    av = str(merged.get(afld, '')).strip()
                    if av and av not in ('-', ''):
                        if av.upper() in long_to_short:
                            merged['Account Number'] = long_to_short[av.upper()]; filled += 1; break
                        t = acc_tail(av)
                        if t and t in long_to_short:
                            merged['Account Number'] = long_to_short[t]; filled += 1; break

        # If still no Date Purchased/Started, try to infer from pushes timestamps
        if empty(merged.get('Status P1')):
            merged['Status P1'] = 'In Progress'

        merged_evals.append(merged)

    print('[5/5] Merge complete: filled %d field values' % filled)

    # Report gap analysis
    gaps = 0
    for idx, ev in enumerate(merged_evals):
        miss = [k for k in ['Prop Firm', 'Account Size', 'Fee', 'Date Purchased', 'Date Started', 'Account #', 'Account Number']
                if empty(ev.get(k))]
        if miss:
            gaps += 1
            ac = ev.get('Account Number', '') or ev.get('Account #', '') or 'Row %d' % (idx + 2)
            if gaps <= 20:
                print('  Gap Row %d (%s): %s' % (idx + 2, ac, ', '.join(miss)))
    if gaps > 20: print('  ... and %d more rows with gaps' % (gaps - 20))
    if gaps == 0: print('  All critical fields filled!')

    # Build column order
    INFO_COLS = ['Prop Firm', 'Account Size', 'Date Purchased', 'Fee']
    EVAL_COLS = ['Date Started', 'Date Ended', 'Status P1', 'Account #',
                 'Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3',
                 'Hedge Result 4', 'Hedge Result 5', 'Hedge Net']
    FUNDED_COLS = ['Activation Fee', 'Account #.1', 'Date Started.1', 'Date Ended.1', 'Status',
                   'Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1',
                   'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6',
                   'Hedge Result 7', 'Hedge Net.1',
                   'Payout 1', 'Date 1', 'Payout 2', 'Date 2', 'Payout 3', 'Date 3',
                   'Payout 4', 'Date 4', 'Payout 5', 'Date 5', 'Payout 6', 'Date 6']
    FARM_COLS = []
    for d in range(1, 51):
        FARM_COLS += ['Prop Day %d' % d, 'Prop Progress %d' % d, 'Hedge Day %d' % d]
    FARM_COLS += ['Farming Net', 'Account Number']
    KNOWN = INFO_COLS + EVAL_COLS + FUNDED_COLS + FARM_COLS
    all_keys = set()
    for ev in merged_evals: all_keys.update(k for k in ev if not k.startswith('_'))
    extra = sorted(k for k in all_keys if k not in KNOWN)
    final = KNOWN + extra
    pop = [c for c in final if any(not empty(ev.get(c)) for ev in merged_evals)]

    slug = client_id.replace(' ', '_')
    outpath = os.path.join(OUT_DIR, '_recovery_%s.csv' % slug)
    with open(outpath, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=pop, extrasaction='ignore')
        w.writeheader()
        for ev in merged_evals:
            if not any(ev.get(c) for c in ['Prop Firm', 'Account #', 'Account #.1', 'Account Number']):
                continue
            w.writerow({c: ev.get(c, '') for c in pop})

    n_written = sum(1 for ev in merged_evals
                    if any(ev.get(c) for c in ['Prop Firm','Account #','Account #.1','Account Number']))
    print('\n  Client:        %s' % client_id)
    print('  DB rows:       %d' % len(evals))
    print('  Written:       %d' % n_written)
    print('  History vers:  %d' % n_ver)
    print('  Log fields:    %d' % n_log)
    print('  Columns:       %d' % len(pop))
    print('\n  Saved -> %s' % outpath)
    print('  Download: https://www.pythonanywhere.com/user/ballerquotes/files/home/ballerquotes/MT5Dashboard/_recovery_%s.csv' % slug)

if len(sys.argv) < 2:
    print('Usage: python _export_client_csv.py "Client Name"')
else:
    export(sys.argv[1])
