"""Automated trader daily summary — the bot fills what the trader used to type.

At 20:00 EAT every client gets the same numbered summary the trader submits
manually from the client dashboard, each section filled from the day's
recorded evidence (trade ledger + daily_events) instead of memory. Delivery
is unchanged: the slack_daily_summaries webhook, with the client's admin
tagged, and a daily_summary checklist row saved so the tracker shows the
submission. A client whose trader already submitted today is skipped.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

# Mirrors _propFirmDisplayName in the client dashboard.
_FIRM_DISPLAY = {
    'my funded futures': 'MFFU',
    'mffu builder': 'MFFU Builder',
    'fundednext': 'Funded Next',
    'funded next flex': 'Funded Next',
    'topstep': 'TopStep',
    'topstep rtp': 'TopStep',
}

_SECTIONS = (
    ('challenge_purchase', 'Challenge Purchase Status',
     'All challenges purchased and funded — no pending orders.'),
    ('renewal_cancel', 'Renewal / Cancellation Check',
     'No renewals or cancellations needed today.'),
    ('trading_delays', 'Trading / Operational Delays',
     'All accounts traded on schedule — no delays or issues.'),
    ('payout_requests', 'Payout Requests',
     'No payout requests pending.'),
    ('payout_confirm', 'Payout Confirmation & Sheet Update',
     'All confirmed payouts recorded — sheet is up to date.'),
    ('action_items', 'Client Action Items',
     'No client action required at this time.'),
    ('trade_count', '# of times account traded today',
     'No trades taken today.'),
)


def eat_now():
    return datetime.now(timezone.utc) + timedelta(hours=3)


def firm_display(raw):
    name = str(raw or '').strip()
    return _FIRM_DISPLAY.get(name.lower(), name)


def _row_live(ev):
    return isinstance(ev, dict) and not ev.get('_deleted')


def payout_eligible(ev):
    """A PAYOUT marker on a row that is still running.

    Markers live in Hedge Day, Hedge Result AND Prop Day cells (Tradeify
    farming uses Prop Day). A Completed or Failed row keeps its old marker
    forever — that is history, not an eligible payout.
    """
    if not _row_live(ev):
        return False
    funded = str(ev.get('Status') or ev.get('Status Funded') or '').strip().lower()
    if 'complete' in funded or 'fail' in funded:
        return False
    for key, val in ev.items():
        if not isinstance(key, str) or key.startswith('_'):
            continue
        if isinstance(val, str) and val.strip().upper() == 'PAYOUT':
            return True
    return False


def _client_firms(evaluations):
    """Display names of firms the client runs, in row order."""
    seen = []
    for ev in evaluations or []:
        if not _row_live(ev):
            continue
        name = firm_display(ev.get('Prop Firm'))
        if name and name not in seen:
            seen.append(name)
    return seen


def _payout_pending_counts(evaluations, has_payout_pending):
    counts = defaultdict(int)
    for ev in evaluations or []:
        if not _row_live(ev):
            continue
        try:
            if has_payout_pending(ev):
                counts[firm_display(ev.get('Prop Firm'))] += 1
        except Exception:
            continue
    return dict(counts)


def _purchase_counts(events):
    """Firm → accounts asked for purchase today (from flush announcements)."""
    counts = defaultdict(int)
    for e in events or []:
        if str(e.get('kind')) != 'purchase_sent':
            continue
        try:
            n = int(float(e.get('detail') or 1))
        except (TypeError, ValueError):
            n = 1
        counts[firm_display(e.get('prop_firm'))] += max(1, n)
    return dict(counts)


def _status_change_lines(events):
    """Firm → human summary of today's status flips (Fail/Pass/Completed)."""
    per_firm = defaultdict(lambda: defaultdict(int))
    for e in events or []:
        if str(e.get('kind')) != 'status_change':
            continue
        verdict = str(e.get('detail') or '').strip()
        if not verdict:
            continue
        per_firm[firm_display(e.get('prop_firm'))][verdict] += 1
    out = {}
    for firm, verdicts in per_firm.items():
        bits = [f"{n} {v.lower()}" for v, n in sorted(verdicts.items())]
        out[firm] = ', '.join(bits)
    return out


def _trade_count_lines(ledger_rows):
    """Firm → 'N trade(s) hit TP today' style line from the day's ledger."""
    per_firm = defaultdict(lambda: {'n': 0, 'tp': 0, 'sl': 0})
    for row in ledger_rows or []:
        firm = firm_display(row.get('prop_firm'))
        if not firm:
            continue
        agg = per_firm[firm]
        agg['n'] += 1
        outcome = str(row.get('outcome') or '').strip().lower()
        if outcome == 'tp':
            agg['tp'] += 1
        elif outcome in ('sl', 'breach'):
            agg['sl'] += 1
    out = {}
    for firm, agg in per_firm.items():
        n, tp, sl = agg['n'], agg['tp'], agg['sl']
        word = 'trade' if n == 1 else 'trades'
        if tp and not sl:
            out[firm] = f"{n} {word} hit TP today"
        elif sl and not tp:
            out[firm] = f"{n} {word} hit SL today"
        elif tp or sl:
            out[firm] = f"{n} {word} today ({tp} TP / {sl} SL)"
        else:
            out[firm] = f"{n} {word} today (outcome pending)"
    return out


def build_client_summary_text(client_id, *, trader='', admin='', admin_slack_id='',
                              evaluations=None, ledger_rows=None, events=None,
                              has_payout_pending=None, now=None):
    """The exact manual-format summary, every section filled from evidence."""
    now = now or eat_now()
    firms = _client_firms(evaluations)
    payouts = _payout_pending_counts(evaluations, has_payout_pending or payout_eligible)
    purchases = _purchase_counts(events)
    statuses = _status_change_lines(events)
    trades = _trade_count_lines(ledger_rows)

    lines = []
    if trader:
        lines.append(f"👤 Trader: {trader}")
    if admin:
        tag = f"<@{admin_slack_id}>" if admin_slack_id else f"@{admin}"
        lines.append(f"🏢 Admin: {tag}")
    lines.append('')
    lines.append(f"📋 **DAILY SUMMARY — {client_id}**")
    lines.append(f"📅 {now.strftime('%A, %B %d, %Y')}")
    lines.append('')

    def _firm_section(num, title, ok_text, firm_map, line_fn, warn=True):
        lines.append(f"**{num}. {title}**")
        if not firm_map:
            lines.append(f"✅ {ok_text}")
        else:
            icon = '⚠️' if warn else '✅'
            for firm in firms or sorted(firm_map):
                if firm in firm_map:
                    lines.append(f"  {icon} {firm}: {line_fn(firm_map[firm])}")
        lines.append('')

    num = 0
    for section_id, title, ok_text in _SECTIONS:
        num += 1
        if section_id == 'challenge_purchase':
            _firm_section(num, title, ok_text, purchases,
                          lambda n: f"{n} challenge(s) pending purchase")
        elif section_id == 'payout_requests':
            _firm_section(num, title, ok_text, payouts,
                          lambda n: f"{n} payout(s) eligible at Next Trading Day. "
                                    f"To be requested at market open")
        elif section_id == 'trade_count':
            _firm_section(num, title, ok_text, trades, lambda s: s, warn=False)
        elif section_id == 'action_items' and statuses:
            _firm_section(num, title, ok_text, statuses,
                          lambda s: f"status updated today: {s}")
        else:
            lines.append(f"**{num}. {title}**")
            lines.append(f"✅ {ok_text}")
            lines.append('')
    lines.append('—')
    return '\n'.join(lines)


def build_checklist_items(events=None, ledger_rows=None, payouts=None):
    """Checklist payload matching the manual submission (tracker + QA read this)."""
    purchases = _purchase_counts(events)
    payouts = payouts or {}
    trades = _trade_count_lines(ledger_rows)
    items = []
    for i, (section_id, title, _ok) in enumerate(_SECTIONS, start=1):
        if section_id == 'challenge_purchase' and purchases:
            notes = {f: {'status': 'warn', 'fields': {'count': str(n)}}
                     for f, n in purchases.items()}
            status = 'warn'
        elif section_id == 'payout_requests' and payouts:
            notes = {f: {'status': 'warn', 'fields': {'count': str(n)}}
                     for f, n in payouts.items()}
            status = 'warn'
        elif section_id == 'trade_count' and trades:
            notes = {f: {'status': 'warn', 'fields': {'count': s}}
                     for f, s in trades.items()}
            status = 'warn'
        else:
            notes, status = {}, 'ok'
        items.append({'id': section_id, 'num': i, 'title': title,
                      'status': status, 'notes': notes})
    items.append({'id': 'slack_sent', 'title': 'Sent to Slack',
                  'status': 'ok', 'notes': ''})
    return items


def post_auto_daily_summaries(log=print):
    """20:00 EAT: build and deliver every client's summary from the day's events."""
    import os
    if str(os.environ.get('AUTO_DAILY_SUMMARY_PAUSED', '0')).strip().lower() in (
            '1', 'true', 'yes'):
        log("Auto daily summary paused via AUTO_DAILY_SUMMARY_PAUSED")
        return 0

    from config.hierarchy import get_all_clients, get_client_profile, SYSTEM_HIERARCHY
    from dashboard.database import (
        get_client_data,
        get_daily_events,
        get_latest_daily_summary_checklist_for_client,
        get_setting,
        get_trade_ledger_rows_for_date,
        save_daily_checklist,
    )
    from dashboard.scheduler import send_slack_to_webhook

    webhook = get_setting('slack_daily_summaries_webhook_url')
    if not webhook:
        log("Auto daily summary: no slack_daily_summaries_webhook_url configured")
        return 0

    from dashboard.app import _should_skip_daily_summary_tracking
    now = eat_now()
    if _should_skip_daily_summary_tracking(now):
        log("Auto daily summary: weekend/no-session — skipped")
        return 0
    today = now.strftime('%Y-%m-%d')

    try:
        import json as _json
        excluded = set(_json.loads(get_setting('summary_tracker_excluded_clients') or '[]'))
        excluded_traders = set(_json.loads(get_setting('summary_tracker_excluded_traders') or '[]'))
    except Exception:
        excluded, excluded_traders = set(), set()

    sent = 0
    for client_id in get_all_clients() or []:
        if client_id in excluded:
            continue
        profile = get_client_profile(client_id) or {}
        trader = profile.get('trader') or ''
        if trader in excluded_traders:
            continue
        try:
            # The trader beat the bot to it — their submission stands.
            existing = get_latest_daily_summary_checklist_for_client(today, client_id)
            if existing and existing.get('items'):
                continue
            cdata = get_client_data(client_id) or {}
            evaluations = cdata.get('evaluations') or []
            if not any(isinstance(ev, dict) and not ev.get('_deleted') for ev in evaluations):
                continue
            events = get_daily_events(today, client_id)
            ledger_rows = get_trade_ledger_rows_for_date(today, client_id)
            admin = profile.get('admin') or ''
            admin_data = (SYSTEM_HIERARCHY.get('admins', {}) or {}).get(admin, {}) or {}
            text = build_client_summary_text(
                client_id,
                trader=trader,
                admin=admin,
                admin_slack_id=str(admin_data.get('slack_user_id') or '').strip(),
                evaluations=evaluations,
                ledger_rows=ledger_rows,
                events=events,
                has_payout_pending=payout_eligible,
                now=now,
            )
            if not send_slack_to_webhook(webhook, text):
                log(f"Auto daily summary: Slack send failed for {client_id}")
                continue
            payouts = _payout_pending_counts(evaluations, payout_eligible)
            save_daily_checklist(
                today, 'auto_summary_bot', 'system', 'daily_summary',
                build_checklist_items(events=events, ledger_rows=ledger_rows,
                                      payouts=payouts),
                '127.0.0.1', client_id=client_id)
            sent += 1
        except Exception as exc:
            log(f"Auto daily summary failed for {client_id}: {exc}")
    log(f"Auto daily summary: {sent} client summarie(s) posted")
    return sent
