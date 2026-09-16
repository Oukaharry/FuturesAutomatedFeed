"""Evaluation status helpers.

Hit TP1–10 / Hit SL1–10 are in-progress markers, not terminal failures.
Only Fail, Breach, Closed, Deleted (and Completed on funded) end a phase.
"""
from __future__ import annotations

import re

_HIT_TP_SL_RE = re.compile(r'^hit\s+(?:tp|sl)\d+$', re.IGNORECASE)

# Funded hedge columns. Slots 6 and 7 carry no ".1" suffix. Slots 8+ are
# overflow columns rendered after the farming block, so every trade in an
# account's lifetime keeps its own cell without shifting existing columns.
FUNDED_OVERFLOW_FIRST = 8
FUNDED_OVERFLOW_LAST = 30

P1_HEDGE_COLS = [f'Hedge Result {i}' for i in range(1, 6)]
FUNDED_OVERFLOW_COLS = [
    f'Hedge Result {i}'
    for i in range(FUNDED_OVERFLOW_FIRST, FUNDED_OVERFLOW_LAST + 1)
]
FUNDED_HEDGE_COLS = (
    [f'Hedge Result {i}.1' for i in range(1, 6)]
    + ['Hedge Result 6', 'Hedge Result 7']
    + FUNDED_OVERFLOW_COLS
)


def is_hit_tp_sl_status(status: str) -> bool:
    return bool(_HIT_TP_SL_RE.match(str(status or '').strip()))


def is_terminal_eval_status(status: str, *, include_complete: bool = False) -> bool:
    s = str(status or '').strip().lower()
    if not s or s in ('-', 'not started', 'in progress'):
        return False
    if is_hit_tp_sl_status(s):
        return False
    if 'delete' in s:
        return True
    if 'fail' in s:
        return True
    if 'breach' in s:
        return True
    if 'closed' in s:
        return True
    if include_complete and 'complete' in s:
        return True
    return False


def is_eval_phase_failed(status: str) -> bool:
    return is_terminal_eval_status(status, include_complete=False)


def is_funded_phase_ended(status: str) -> bool:
    return is_terminal_eval_status(status, include_complete=True)
