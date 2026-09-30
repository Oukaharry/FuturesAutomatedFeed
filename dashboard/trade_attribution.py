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


def _stats(rows):
    """(n, wins, win_rate, net_pnl, pending) over ledger rows."""
    wins = losses = pending = 0
    net = 0.0
    for row in rows:
        outcome = str(row.get('outcome') or '').strip().lower()
        if outcome in _WIN_OUTCOMES:
            wins += 1
        elif outcome in _LOSS_OUTCOMES:
            losses += 1
        else:
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


def post_trade_attribution_report():
    """Build the report from the ledger and post it to Slack."""
    import logging
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
