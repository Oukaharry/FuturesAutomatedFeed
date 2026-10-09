"""Nightly trade attribution: what the ledger says about wins, losses and leaks.

Pure aggregation over trade_ledger rows — no model, no side effects except the
Slack post in post_trade_attribution_report(). Sample-size guards keep noise
out: breakdown lines need MIN_BREAKDOWN_N resolved trades, red flags need
MIN_FLAG_N.
"""

from collections import defaultdict
from datetime import datetime, timedelta

MIN_BREAKDOWN_N = 10
MIN_FLAG_N = 30
FLAG_WIN_RATE = 0.40

_WIN_OUTCOMES = ('tp',)
_LOSS_OUTCOMES = ('sl', 'breach')

# signal_source values that mean the ML signal was NOT the trade's source
_NON_ML_SOURCES = ('', 'none', 'random', 'fallback', 'manual')


def _signal_compliance(row):
    """'ml' | 'against_ml' | 'no_ml' for one ledger row.

    against_ml: a signal existed and the trade went the other way (or the
    companion recorded an explicit override). no_ml: no usable signal backed
    the entry (none/random/fallback/manual).
    """
    source = str(row.get('signal_source') or '').strip().lower()
    sig = str(row.get('signal_direction') or '').strip().lower()
    side = str(row.get('side') or '').strip().lower()
    if source.startswith('override'):
        return 'against_ml'
    if not sig or source in _NON_ML_SOURCES:
        return 'no_ml'
    if sig in ('buy', 'sell') and side and sig != side:
        return 'against_ml'
    return 'ml'


_trader_cache: dict = {}


def _trader_for_client(client_id):
    """(trader, admin) responsible for a client, from the hierarchy."""
    key = str(client_id or '').strip()
    if not key:
        return ('?', '?')
    if key not in _trader_cache:
        trader = admin = '?'
        try:
            from config.hierarchy import get_client_profile
            profile = get_client_profile(key) or {}
            trader = profile.get('trader') or '?'
            admin = profile.get('admin') or '?'
        except Exception:
            pass
        _trader_cache[key] = (trader, admin)
    return _trader_cache[key]


def build_ml_compliance(rows, offender_limit=200):
    """Which trades were not taken via the ML signal, and who took them."""
    rows = [r for r in rows or [] if isinstance(r, dict)]
    buckets = {'ml': [], 'against_ml': [], 'no_ml': []}
    for row in rows:
        buckets[_signal_compliance(row)].append(row)

    offenders = []
    by_trader = defaultdict(lambda: {'n': 0, 'against': 0, 'no_signal': 0,
                                     'net': 0.0, 'clients': set()})
    for kind in ('against_ml', 'no_ml'):
        for row in buckets[kind]:
            client = str(row.get('client_id') or '?')
            trader, admin = _trader_for_client(client)
            entry = by_trader[trader]
            entry['n'] += 1
            entry['against' if kind == 'against_ml' else 'no_signal'] += 1
            entry['clients'].add(client)
            try:
                entry['net'] += float(row.get('net_pnl'))
            except (TypeError, ValueError):
                pass
            offenders.append({
                'entry_date': row.get('entry_date'),
                'entry_time': row.get('entry_time'),
                'trader': trader, 'admin': admin, 'client': client,
                'account': row.get('account'), 'prop_firm': row.get('prop_firm'),
                'side': row.get('side'),
                'signal_direction': row.get('signal_direction'),
                'signal_source': row.get('signal_source'),
                'kind': 'against signal' if kind == 'against_ml' else 'no signal',
                'outcome': row.get('outcome'), 'net_pnl': row.get('net_pnl'),
            })
    offenders.sort(key=lambda r: str(r.get('entry_time') or r.get('entry_date') or ''),
                   reverse=True)

    traders = [
        dict(trader=t, n=e['n'], against=e['against'], no_signal=e['no_signal'],
             net=round(e['net'], 2), clients=sorted(e['clients']))
        for t, e in by_trader.items()]
    traders.sort(key=lambda e: -e['n'])

    return {
        'summary': {kind: _stats_dict(group) for kind, group in buckets.items()},
        'non_ml_total': len(buckets['against_ml']) + len(buckets['no_ml']),
        'by_trader': traders,
        'offenders': offenders[:offender_limit],
    }


def _effective_outcome(row):
    """Outcome for stats. A farming breach is the planned end of a milking
    cycle, not a lost trade — it would otherwise poison the farming win rate
    (farming TPs are smaller than SLs, so W/L must skew heavily to wins)."""
    outcome = str(row.get('outcome') or '').strip().lower()
    if outcome == 'breach' and 'farm' in str(row.get('phase_key') or '').lower():
        return 'cycle_end'
    return outcome


def _stats(rows):
    """(n, wins, win_rate, net_pnl, pending) over ledger rows."""
    wins = losses = pending = 0
    net = 0.0
    for row in rows:
        outcome = _effective_outcome(row)
        if outcome in _WIN_OUTCOMES:
            wins += 1
        elif outcome in _LOSS_OUTCOMES:
            losses += 1
        else:
            if outcome != 'cycle_end':
                pending += 1
            continue
        try:
            net += float(row.get('net_pnl'))
        except (TypeError, ValueError):
            pass
    n = wins + losses
    win_rate = (wins / n) if n else 0.0
    return n, wins, win_rate, net, pending


def _fmt_line(label, rows):
    n, wins, win_rate, net, _pending = _stats(rows)
    if n < MIN_BREAKDOWN_N:
        return None
    return f"• {label}: {wins}W/{n - wins}L ({win_rate:.0%})  net ${net:,.0f}"


def _group(rows, key_fn):
    groups = defaultdict(list)
    for row in rows:
        key = key_fn(row)
        if key:
            groups[key].append(row)
    return groups


def _entry_hour(row):
    ts = str(row.get('entry_time') or '')
    try:
        return f"{int(ts[11:13]):02d}:00 EAT"
    except (ValueError, IndexError):
        return None


def _entry_weekday(row):
    try:
        return datetime.strptime(str(row.get('entry_date'))[:10], '%Y-%m-%d').strftime('%A')
    except (TypeError, ValueError):
        return None


def _phase_bucket(row):
    phase = str(row.get('phase_key') or '').lower()
    if not phase:
        return None
    if 'challenge' in phase or 'evaluation' in phase:
        return 'Challenge'
    if 'funded' in phase or 'payout' in phase:
        return 'Funded'
    return phase


def _section(title, groups):
    lines = []
    for label in sorted(groups):
        line = _fmt_line(label, groups[label])
        if line:
            lines.append(line)
    if not lines:
        return []
    return [f"*{title}*"] + lines + [""]


def build_attribution_report(rows, today=None):
    """Slack text for the nightly attribution report, or None without data."""
    rows = [r for r in rows or [] if isinstance(r, dict)]
    if not rows:
        return None
    today = today or datetime.now().date()
    yesterday = (today - timedelta(days=1)).strftime('%Y-%m-%d')
    n, wins, win_rate, net, pending = _stats(rows)
    lines = [
        f"📒 *Trade Attribution — last 30 days* ({len(rows)} trades recorded)",
        f"Resolved: {wins}W/{n - wins}L ({win_rate:.0%})  net ${net:,.0f}"
        f"{f'  ·  {pending} pending' if pending else ''}",
        "",
    ]

    y_rows = [r for r in rows if str(r.get('entry_date')) == yesterday]
    if y_rows:
        yn, ywins, ywr, ynet, ypending = _stats(y_rows)
        lines.append(
            f"*Yesterday ({yesterday})*: {len(y_rows)} trades — "
            f"{ywins}W/{yn - ywins}L ({ywr:.0%} of resolved)  net ${ynet:,.0f}"
            f"{f'  ·  {ypending} pending' if ypending else ''}")
        lines.append("")

    lines += _section("By prop firm", _group(rows, lambda r: str(r.get('prop_firm') or '').strip() or None))
    lines += _section("By phase", _group(rows, _phase_bucket))
    lines += _section("By entry hour", _group(rows, _entry_hour))
    lines += _section("By weekday", _group(rows, _entry_weekday))
    lines += _section("By signal source", _group(rows, lambda r: str(r.get('signal_source') or '').strip() or None))
    lines += _section("By model", _group(rows, lambda r: str(r.get('signal_model') or '').strip() or None))

    compliance = build_ml_compliance(rows)
    if compliance['non_ml_total']:
        ml_s = compliance['summary']['ml']
        lines.append("*ML compliance*")
        if ml_s['n']:
            lines.append(f"• Followed ML: {ml_s['wins']}W/{ml_s['losses']}L "
                         f"({ml_s['win_rate']:.0%})  net ${ml_s['net']:,.0f}")
        lines.append(f"• NOT taken via ML: {compliance['non_ml_total']} trade(s)")
        for t in compliance['by_trader'][:8]:
            lines.append(
                f"   🚨 {t['trader']}: {t['n']} "
                f"({t['against']} against signal, {t['no_signal']} no signal) "
                f"net ${t['net']:,.0f} — clients: {', '.join(t['clients'][:5])}")
        lines.append("")

    flags = []
    for title, groups in (
        ("firm", _group(rows, lambda r: str(r.get('prop_firm') or '').strip() or None)),
        ("hour", _group(rows, _entry_hour)),
        ("weekday", _group(rows, _entry_weekday)),
        ("model", _group(rows, lambda r: str(r.get('signal_model') or '').strip() or None)),
    ):
        for label, group_rows in groups.items():
            gn, gwins, gwr, gnet, _p = _stats(group_rows)
            if gn >= MIN_FLAG_N and gwr <= FLAG_WIN_RATE:
                flags.append(
                    f"🚩 {title} `{label}`: {gwins}W/{gn - gwins}L ({gwr:.0%}) "
                    f"net ${gnet:,.0f} — losing systematically")
    if flags:
        lines += ["*Flags (n≥%d, win rate ≤%d%%)*" % (MIN_FLAG_N, FLAG_WIN_RATE * 100)] + flags

    return "\n".join(lines).strip()


def _stats_dict(rows):
    n, wins, win_rate, net, pending = _stats(rows)
    return {
        'n': n, 'wins': wins, 'losses': n - wins,
        'win_rate': round(win_rate, 4), 'net': round(net, 2), 'pending': pending,
    }


_BREAKDOWN_SECTIONS = (
    ('prop_firm', lambda r: str(r.get('prop_firm') or '').strip() or None),
    ('phase', _phase_bucket),
    ('entry_hour', _entry_hour),
    ('weekday', _entry_weekday),
    ('signal_source', lambda r: str(r.get('signal_source') or '').strip() or None),
    ('signal_model', lambda r: str(r.get('signal_model') or '').strip() or None),
)

_RECENT_FIELDS = (
    'entry_date', 'entry_time', 'client_id', 'account', 'prop_firm', 'phase_key',
    'platform', 'symbol', 'side', 'signal_direction', 'signal_confidence',
    'signal_model', 'signal_source', 'outcome', 'net_pnl',
)


def build_attribution_data(rows, today=None, recent_limit=100):
    """Structured attribution payload for the super-admin page."""
    rows = [r for r in rows or [] if isinstance(r, dict)]
    today = today or datetime.now().date()
    yesterday = (today - timedelta(days=1)).strftime('%Y-%m-%d')

    breakdowns = {}
    for section, key_fn in _BREAKDOWN_SECTIONS:
        groups = _group(rows, key_fn)
        entries = [dict(label=label, **_stats_dict(g)) for label, g in groups.items()]
        entries.sort(key=lambda e: (-e['n'], e['label']))
        breakdowns[section] = entries

    flags = []
    for section in ('prop_firm', 'entry_hour', 'weekday', 'signal_model'):
        for entry in breakdowns[section]:
            if entry['n'] >= MIN_FLAG_N and entry['win_rate'] <= FLAG_WIN_RATE:
                flags.append(dict(section=section, **entry))

    recent = []
    for row in sorted(rows, key=lambda r: str(r.get('entry_time') or r.get('entry_date') or ''),
                      reverse=True)[:recent_limit]:
        recent.append({f: row.get(f) for f in _RECENT_FIELDS})

    return {
        'overall': _stats_dict(rows),
        'total_rows': len(rows),
        'yesterday': dict(date=yesterday,
                          **_stats_dict([r for r in rows if str(r.get('entry_date')) == yesterday])),
        'breakdowns': breakdowns,
        'flags': flags,
        'recent': recent,
        'ml_compliance': build_ml_compliance(rows),
        'min_breakdown_n': MIN_BREAKDOWN_N,
        'min_flag_n': MIN_FLAG_N,
        'flag_win_rate': FLAG_WIN_RATE,
    }


def post_trade_attribution_report():
    """Build the report from the ledger and post it to Slack."""
    import logging
    try:
        from dashboard.scheduler import QUALITY_SLACK_PAUSED
        if QUALITY_SLACK_PAUSED:
            logging.info("Trade attribution report suppressed — quality bot is paused.")
            return False
    except Exception:
        pass
    try:
        from dashboard.database import get_trade_ledger_rows
        rows = get_trade_ledger_rows(days=30)
    except Exception as exc:
        logging.error(f"Trade attribution: ledger query failed: {exc}")
        return False
    text = build_attribution_report(rows)
    if not text:
        logging.info("Trade attribution: no ledger rows yet — nothing to post")
        return False
    try:
        from dashboard.scheduler import send_slack_message
        return bool(send_slack_message(text))
    except Exception as exc:
        logging.error(f"Trade attribution: Slack post failed: {exc}")
        return False
