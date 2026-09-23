"""Challenge CH1 / funded FT1 / FT2 must be taken before breach auto-Fail is valid."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "trader_companion"))

from prop_firm_manager import PropFirmManager  # noqa: E402


def _parse_day(v):
    s = str(v or "").strip().upper()
    days = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4}
    return days.get(s)


def _cell(v, default=""):
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def _cell_account(v):
    s = _cell(v)
    return s if s and s not in ("—", "-") else ""


def _on_funded_leg(ev):
    ch = _cell_account(ev.get("Account #"))
    fu = _cell_account(ev.get("Account #.1"))
    return bool(ch and fu) or (bool(fu) and not ch)


def _has_taken_challenge_trade1(ev):
    if _on_funded_leg(ev):
        return False
    hr1 = _cell(ev.get("Hedge Result 1"))
    if hr1 and hr1 not in ("—", "-") and _parse_day(hr1) is None:
        return True
    for i in range(2, 8):
        val = _cell(ev.get(f"Hedge Result {i}"))
        if val and val not in ("—", "-"):
            return True
    return False


def _has_taken_funded_trade1(ev):
    if not _on_funded_leg(ev):
        return False
    hr1 = _cell(ev.get("Hedge Result 1.1"))
    if hr1 and hr1 not in ("—", "-") and _parse_day(hr1) is None:
        return True
    for i in range(2, 8):
        val = _cell(ev.get(f"Hedge Result {i}.1"))
        if val and val not in ("—", "-"):
            return True
    return False


def _has_taken_funded_trade2(ev):
    if not _on_funded_leg(ev):
        return False
    hr2 = _cell(ev.get("Hedge Result 2.1"))
    if hr2 and hr2 not in ("—", "-") and _parse_day(hr2) is None:
        return True
    for i in range(3, 8):
        val = _cell(ev.get(f"Hedge Result {i}.1"))
        if val and val not in ("—", "-"):
            return True
    return False


def _blown_for_ev(mgr, ev, firm, balance, has_trades=True):
    on_funded = _on_funded_leg(ev)
    phase = "Funded" if on_funded else "Challenge"
    after_ch1 = _has_taken_challenge_trade1(ev) if not on_funded else False
    after_ft1 = _has_taken_funded_trade1(ev) if on_funded else False
    after_ft2 = _has_taken_funded_trade2(ev) if on_funded else False
    floor = mgr.get_breach_floor(
        firm, phase,
        after_funded_trade1=after_ft1,
        after_funded_trade2=after_ft2,
    )
    return mgr.evaluate_breach_blown(
        on_funded=on_funded,
        after_ch1=after_ch1,
        after_ft1=after_ft1,
        after_ft2=after_ft2,
        floor=floor,
        balance=balance,
        has_trades=has_trades,
    )


def test_challenge_breach_requires_ch1_and_trades():
    mgr = PropFirmManager()
    ev_pre = {
        "Account #": "11111",
        "Hedge Result 1": "MON",
        "Prop Firm": "Tradeify",
    }
    assert _has_taken_challenge_trade1(ev_pre) is False
    assert _blown_for_ev(mgr, ev_pre, "Tradeify", 47000.0) is False

    ev_ch1 = {**ev_pre, "Hedge Result 1": "$0.00"}
    assert _has_taken_challenge_trade1(ev_ch1) is True
    assert _blown_for_ev(mgr, ev_ch1, "Tradeify", 47000.0) is True
    assert _blown_for_ev(mgr, ev_ch1, "Tradeify", 48000.0) is False
    assert _blown_for_ev(mgr, ev_ch1, "Tradeify", 47000.0, has_trades=False) is False


def test_ft1_breach_requires_hr11_not_placeholder():
    mgr = PropFirmManager()
    ev = {
        "Account #": "11111",
        "Account #.1": "22222",
        "Hedge Result 1.1": "WED",
        "Prop Firm": "Tradeify",
    }
    assert _has_taken_funded_trade1(ev) is False
    assert _blown_for_ev(mgr, ev, "Tradeify", 47000.0) is False

    ev_ft1 = {**ev, "Hedge Result 1.1": "$0.00"}
    assert _has_taken_funded_trade1(ev_ft1) is True
    assert _blown_for_ev(mgr, ev_ft1, "Tradeify", 47000.0) is True
    assert _blown_for_ev(mgr, ev_ft1, "Tradeify", 48000.0) is False


def test_ft2_breach_requires_hr21_uses_at_or_below_ceiling():
    mgr = PropFirmManager()
    ev_ft1_only = {
        "Account #": "11111",
        "Account #.1": "22222",
        "Hedge Result 1.1": "$2,000.00",
        "Hedge Result 2.1": "THU",
        "Prop Firm": "Tradeify",
    }
    assert _has_taken_funded_trade2(ev_ft1_only) is False
    # FT1 tier: below 48k fails
    assert _blown_for_ev(mgr, ev_ft1_only, "Tradeify", 47999.0) is True
    assert _blown_for_ev(mgr, ev_ft1_only, "Tradeify", 50100.0) is False

    ev_ft2 = {**ev_ft1_only, "Hedge Result 2.1": "$0.00"}
    assert _has_taken_funded_trade2(ev_ft2) is True
    assert _blown_for_ev(mgr, ev_ft2, "Tradeify", 50100.0) is True
    assert _blown_for_ev(mgr, ev_ft2, "Tradeify", 50101.0) is False
    assert _blown_for_ev(mgr, ev_ft2, "Tradeify", 47999.0) is True


def test_ft2_mffu_and_topstep_ceilings_after_ft2():
    mgr = PropFirmManager()
    base = {
        "Account #": "11111",
        "Account #.1": "22222",
        "Hedge Result 1.1": "$1.00",
        "Hedge Result 2.1": "$0.00",
    }
    assert _blown_for_ev(mgr, {**base, "Prop Firm": "MFFU_Flex"}, "MFFU_Flex", 100.0)
    assert not _blown_for_ev(mgr, {**base, "Prop Firm": "MFFU_Flex"}, "MFFU_Flex", 100.01)
    assert _blown_for_ev(mgr, {**base, "Prop Firm": "Topstep"}, "TopStep", 0.0)
    assert not _blown_for_ev(mgr, {**base, "Prop Firm": "Topstep"}, "TopStep", 0.01)


def test_pre_ft1_funded_no_breach_even_below_48k():
    mgr = PropFirmManager()
    ev = {
        "Account #.1": "22222",
        "Hedge Result 1.1": "FRI",
        "Prop Firm": "Tradeify",
    }
    assert _has_taken_funded_trade1(ev) is False
    assert _blown_for_ev(mgr, ev, "Tradeify", 47000.0) is False
