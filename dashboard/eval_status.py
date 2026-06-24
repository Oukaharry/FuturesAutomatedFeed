"""Evaluation status helpers.

Hit TP1–10 / Hit SL1–10 are in-progress markers, not terminal failures.
Only Fail, Breach, Closed, Deleted (and Completed on funded) end a phase.
"""
from __future__ import annotations

import re

_HIT_TP_SL_RE = re.compile(r'^hit\s+(?:tp|sl)\d+$', re.IGNORECASE)


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
