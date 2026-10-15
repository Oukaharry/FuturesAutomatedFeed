"""One purchase Slack per client + prop firm, even when the fails trickle in."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import dashboard.app as dapp

EAT = timezone(timedelta(hours=3))
TUESDAY_NOON = datetime(2026, 10, 13, 12, 0, tzinfo=EAT)


class _Queue:
    """In-memory stand-in for the DB-backed per-client purchase queue."""

    def __init__(self):
        self.pending = []
        self.sent_accounts = set()
        self.sent_batches = set()

    def install(self, monkeypatch):
        db = 'dashboard.database.'
        monkeypatch.setattr(db + 'claim_breach_alert_pending', self._claim)
        monkeypatch.setattr(db + 'requeue_breach_alert_pending', self._requeue)
        monkeypatch.setattr(db + 'get_breach_alert_pending', lambda c: list(self.pending))
        monkeypatch.setattr(db + 'get_breach_alert_sent_accounts', lambda c: set(self.sent_accounts))
        monkeypatch.setattr(db + 'get_breach_alert_sent_batches', lambda c: set(self.sent_batches))
        monkeypatch.setattr(db + 'mark_breach_alert_accounts_sent',
                            lambda c, keys: self.sent_accounts.update(keys))
        monkeypatch.setattr(db + 'mark_breach_alert_batch_sent',
                            lambda c, k: self.sent_batches.add(k))
        monkeypatch.setattr(db + 'get_client_recent_ledger_firms', lambda c, days=30: {'Tradeify'})
        monkeypatch.setattr(db + 'record_daily_event', lambda *a, **k: None)

    def _claim(self, client_id):
        taken, self.pending = self.pending, []
        return taken

    def _requeue(self, client_id, items):
        seen = {b['account'].lower() for b in self.pending}
        for b in items:
            if b['account'].lower() not in seen:
                self.pending.append(b)
                seen.add(b['account'].lower())
        return len(items)


def _rows(*accounts, status='Fail'):
    return [{'Prop Firm': 'Tradeify', 'Account #': a, 'Status P1': status} for a in accounts]


def _breach(account):
    return {'account': account, 'prop_firm': 'Tradeify', 'phase': 'Challenge'}


def _run(queue, evaluations, now, sent):
    with patch.object(dapp, '_kenya_now', lambda: now), \
         patch.object(dapp, 'BREACH_SLACK_NOTIFICATIONS_PAUSED', False), \
         patch.object(dapp, '_admin_slack_route_for_client',
                      return_value=('Admin', 'U1', 'C1')), \
         patch.object(dapp, '_send_admin_breach_alert',
                      side_effect=lambda c, b: sent.append(list(b)) or 1):
        return dapp._flush_batched_breach_alerts('Harry', evaluations)


def test_five_fails_arriving_minutes_apart_become_one_purchase(monkeypatch):
    queue = _Queue()
    queue.install(monkeypatch)
    sent = []
    accounts = ['T1', 'T2', 'T3', 'T4', 'T5']

    # Fails land one at a time over four minutes; each minute flush runs.
    for i, acct in enumerate(accounts):
        now = TUESDAY_NOON + timedelta(minutes=i)
        with patch.object(dapp, '_kenya_now', lambda n=now: n):
            dapp._queue_breach_alerts('Harry', [_breach(acct)])
        _run(queue, _rows(*accounts[:i + 1]), now, sent)
    assert sent == []  # still settling — nothing split off early
    assert sorted(b['account'] for b in queue.pending) == accounts

    # Settle window elapsed since the last fail → exactly one Slack for all five.
    _run(queue, _rows(*accounts),
         TUESDAY_NOON + timedelta(minutes=4, seconds=dapp.PURCHASE_BATCH_SETTLE_SEC + 1), sent)
    assert len(sent) == 1
    assert sorted(b['account'] for b in sent[0]) == accounts
    assert queue.pending == []


def test_batch_waits_while_a_sibling_still_has_an_open_trade(monkeypatch):
    queue = _Queue()
    queue.install(monkeypatch)
    sent = []
    with patch.object(dapp, '_kenya_now', lambda: TUESDAY_NOON):
        dapp._queue_breach_alerts('Harry', [_breach('T1'), _breach('T2')])
    rows = _rows('T1', 'T2') + [
        {'Prop Firm': 'Tradeify', 'Account #': 'T3', 'Status P1': 'In Progress',
         '_open_position': True}]

    later = TUESDAY_NOON + timedelta(seconds=dapp.PURCHASE_BATCH_SETTLE_SEC + 60)
    _run(queue, rows, later, sent)
    assert sent == []
    assert sorted(b['account'] for b in queue.pending) == ['T1', 'T2']

    # T3 closes flat (position flag clears) — the two fails go out together.
    rows[2]['_open_position'] = False
    _run(queue, rows, later + timedelta(minutes=1), sent)
    assert len(sent) == 1 and sorted(b['account'] for b in sent[0]) == ['T1', 'T2']


def test_session_end_releases_a_settling_batch(monkeypatch):
    queue = _Queue()
    queue.install(monkeypatch)
    sent = []
    evening = TUESDAY_NOON.replace(hour=19, minute=59)
    with patch.object(dapp, '_kenya_now', lambda: evening):
        dapp._queue_breach_alerts('Harry', [_breach('T1')])
    _run(queue, _rows('T1'), evening, sent)
    assert sent == []

    _run(queue, _rows('T1'), evening.replace(hour=20, minute=0), sent)
    assert len(sent) == 1 and sent[0][0]['account'] == 'T1'


def test_stale_open_flag_cannot_hold_past_the_max_hold_cap(monkeypatch):
    queue = _Queue()
    queue.install(monkeypatch)
    sent = []
    morning = TUESDAY_NOON.replace(hour=9)
    with patch.object(dapp, '_kenya_now', lambda: morning):
        dapp._queue_breach_alerts('Harry', [_breach('T1')])
    stuck = _rows('T1') + [
        {'Prop Firm': 'Tradeify', 'Account #': 'T3', 'Status P1': 'In Progress',
         '_open_position': True}]

    _run(queue, stuck, morning + timedelta(hours=1), sent)
    assert sent == []
    _run(queue, stuck, morning + timedelta(seconds=dapp.PURCHASE_BATCH_MAX_HOLD_SEC), sent)
    assert len(sent) == 1
