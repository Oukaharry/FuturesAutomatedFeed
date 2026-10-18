"""Is the ML direction signal actually earning its keep? Weekly / monthly scorecard.

Pure aggregation over trade_ledger rows (same input as trade_attribution).

Why win rate alone is not enough: ~99% of trades take the ML direction, so
there is no control group, and TP/SL distances differ per setup — a 0.8:1
setup "should" hit TP far more often than a 3:1 one even on a coin flip.
Each trade is therefore compared to its own random-walk baseline:

    p_random(TP) = sl_ticks / (tp_ticks + sl_ticks)

and the headline metric is EDGE = actual TP rate − mean p_random. Edge > 0
means the direction call beats a coin flip; edge ≈ 0 means the ML adds
nothing; edge < 0 means it is picking the wrong side.

Calibration (win rate by confidence bucket) answers a second question: does
higher model confidence translate into more wins? Flat calibration means the
confidence number carries no information.

Sample-size caveat: every account trades the same signal at the same time, so
`decisions` (distinct signal timestamps) — not `trades` — is the honest N.
"""

from collections import defaultdict
from datetime import datetime

from dashboard.trade_attribution import _effective_outcome

MIN_EDGE_N = 30          # resolved trades before an edge figure is shown
MIN_CALIB_N = 20         # resolved trades per confidence bucket
HIGH_RR = 1.5            # tp/sl at or above this = "needs direction skill"
CONF_BUCKETS = ((0.0, 0.60, '<0.60'), (0.60, 0.70, '0.60-0.70'),
                (0.70, 0.80, '0.70-0.80'), (0.80, 1.01, '≥0.80'))


def _ml_rows(rows):
    return [r for r in rows or []
            if isinstance(r, dict)
            and str(r.get('signal_source') or '').strip().lower() == 'local_ml']


def _period_key(entry_date, period):
    try:
        d = datetime.strptime(str(entry_date)[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None
    if period == 'month':
        return d.strftime('%Y-%m')
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _num(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _resolved(rows):
    """(wins, losses) per row list — breach counts as a loss outside farming."""
    out = []
    for r in rows:
        oc = _effective_outcome(r)
        if oc == 'tp':
            out.append((r, True))
        elif oc in ('sl', 'breach'):
            out.append((r, False))
    return out


def _edge(resolved):
    """actual TP% minus random-walk TP% over resolved rows with known TP/SL."""
    usable = []
    for r, won in resolved:
        tp, sl = _num(r.get('tp_ticks')), _num(r.get('sl_ticks'))
        if tp and sl and tp > 0 and sl > 0:
            usable.append((won, sl / (tp + sl)))
    if len(usable) < MIN_EDGE_N:
        return {'n': len(usable), 'actual_tp_pct': None,
                'random_tp_pct': None, 'edge_pts': None}
    actual = sum(1 for w, _ in usable if w) / len(usable)
    random_ = sum(p for _, p in usable) / len(usable)
    return {'n': len(usable),
            'actual_tp_pct': round(actual * 100, 1),
            'random_tp_pct': round(random_ * 100, 1),
            'edge_pts': round((actual - random_) * 100, 1)}


def _wr(resolved):
    n = len(resolved)
    wins = sum(1 for _, w in resolved if w)
    return {'n': n, 'wins': wins, 'losses': n - wins,
            'win_rate': round(wins / n, 4) if n else None}


def _calibration(resolved):
    buckets = []
    for lo, hi, label in CONF_BUCKETS:
        grp = [(r, w) for r, w in resolved
               if (c := _num(r.get('signal_confidence'))) is not None and lo <= c < hi]
        stats = _wr(grp)
        stats['label'] = label
        stats['enough'] = stats['n'] >= MIN_CALIB_N
        buckets.append(stats)
    # slope = win rate of the most confident usable bucket minus the least
    usable = [b for b in buckets if b['enough']]
    slope = (round(usable[-1]['win_rate'] - usable[0]['win_rate'], 4)
             if len(usable) >= 2 else None)
    return {'buckets': buckets, 'slope': slope}


def _bucket_stats(rows):
    resolved = _resolved(rows)
    net = 0.0
    for r, _ in resolved:
        v = _num(r.get('net_pnl'))
        if v is not None:
            net += v
    decisions = {str(r.get('signal_published_at') or r.get('entry_time') or '')[:16]
                 for r in rows}
    by_side = {}
    for side in ('buy', 'sell'):
        by_side[side] = _wr([(r, w) for r, w in resolved
                             if str(r.get('side') or '').lower() == side])
    high = [(r, w) for r, w in resolved
            if (t := _num(r.get('tp_ticks'))) and (s := _num(r.get('sl_ticks')))
            and s > 0 and t / s >= HIGH_RR]
    low = [(r, w) for r, w in resolved
           if (t := _num(r.get('tp_ticks'))) and (s := _num(r.get('sl_ticks')))
           and s > 0 and t / s < HIGH_RR]
    overall = _wr(resolved)
    return {
        'trades': len(rows),
        'decisions': len(decisions),
        'pending': len(rows) - overall['n'],
        'pending_pct': round(100.0 * (len(rows) - overall['n']) / len(rows), 1) if rows else 0.0,
        'clients': len({str(r.get('client_id') or '') for r in rows}),
        **overall,
        'net': round(net, 2),
        'edge': _edge(resolved),
        'high_rr': {**_wr(high), **{'edge': _edge(high)}},
        'low_rr': {**_wr(low), **{'edge': _edge(low)}},
        'by_side': by_side,
        'calibration': _calibration(resolved),
    }


def _verdict(stats):
    """One-line plain-English reading of a period, or None when too thin."""
    edge = stats['edge']
    if edge['edge_pts'] is None:
        return None
    parts = []
    e = edge['edge_pts']
    if e >= 5:
        parts.append(f"beats coin flip by {e:+.1f} pts")
    elif e <= -5:
        parts.append(f"WORSE than coin flip by {e:+.1f} pts")
    else:
        parts.append(f"≈ coin flip ({e:+.1f} pts)")
    hr = stats['high_rr']['edge']
    if hr['edge_pts'] is not None:
        parts.append(f"high-RR setups {hr['edge_pts']:+.1f} pts (n={hr['n']})")
    slope = stats['calibration']['slope']
    if slope is not None:
        parts.append("confidence is informative" if slope >= 0.08
                     else "confidence carries no information")
    if stats['pending_pct'] >= 40:
        parts.append(f"{stats['pending_pct']:.0f}% outcomes still unrecorded — treat as provisional")
    return "; ".join(parts)


def build_ml_effectiveness(rows, period='week'):
    """Scorecard series for 'week' or 'month' buckets, newest last."""
    period = 'month' if str(period).lower().startswith('m') else 'week'
    ml = _ml_rows(rows)
    groups = defaultdict(list)
    for r in ml:
        key = _period_key(r.get('entry_date'), period)
        if key:
            groups[key].append(r)
    series = []
    for key in sorted(groups):
        stats = _bucket_stats(groups[key])
        stats['period'] = key
        stats['verdict'] = _verdict(stats)
        series.append(stats)
    overall = _bucket_stats(ml) if ml else None
    if overall:
        overall['verdict'] = _verdict(overall)
    return {
        'period': period,
        'series': series,
        'overall': overall,
        'thresholds': {'min_edge_n': MIN_EDGE_N, 'min_calib_n': MIN_CALIB_N,
                       'high_rr': HIGH_RR},
    }


def build_ml_effectiveness_lines(rows):
    """Slack lines: this week vs last week edge, for the nightly report."""
    data = build_ml_effectiveness(rows, 'week')
    series = data['series'][-2:]
    if not series:
        return []
    lines = ["*ML edge vs coin flip (weekly)*"]
    for s in series:
        e = s['edge']
        if e['edge_pts'] is None:
            lines.append(f"• {s['period']}: {s['trades']} trades / {s['decisions']} signals — "
                         f"too few resolved (n={e['n']}) to score")
            continue
        wr = f"{s['win_rate']:.0%}" if s['win_rate'] is not None else '—'
        lines.append(
            f"• {s['period']}: {s['wins']}W/{s['losses']}L ({wr}) · "
            f"TP {e['actual_tp_pct']:.0f}% vs random {e['random_tp_pct']:.0f}% → "
            f"edge {e['edge_pts']:+.1f} pts · {s['decisions']} signals · "
            f"{s['pending_pct']:.0f}% pending")
    v = series[-1].get('verdict')
    if v:
        lines.append(f"  ↳ {v}")
    lines.append("")
    return lines
