"""FT1 must be marked on dashboard before funded breach applies."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "trader_companion"))

from prop_firm_manager import PropFirmManager  # noqa: E402


class _AppStub:
    prop_firm_mgr = PropFirmManager()

    @staticmethod
    def _cell(v, default=""):
        if v is None:
            return default
        s = str(v).strip()
        return s if s else default

    @staticmethod
    def _cell_account(v):
        s = _AppStub._cell(v)
        return s if s and s not in ("—", "-") else ""

    _parse_day_token = staticmethod(lambda v: None)

    def _on_funded_leg(self, ev):
        return bool(self._cell_account(ev.get("Account #.1")))

    def _has_taken_funded_trade1(self, ev):
        if not self._on_funded_leg(ev):
            return False
        hr1 = self._cell(ev.get("Hedge Result 1.1"))
        if hr1 and hr1 not in ("—", "-") and self._parse_day_token(hr1) is None:
            return True
        for i in range(2, 8):
            val = self._cell(ev.get(f"Hedge Result {i}.1"))
            if val and val not in ("—", "-"):
                return True
        return False

    @staticmethod
    def _account_has_trades(entry):
        return bool(entry and any(d.get("trades") for d in (entry.get("daily_pnl") or [])))

    def _breach_balance_account(self, ev, on_funded):
        if on_funded:
            return self._cell_account(ev.get("Account #.1"))
        return self._cell_account(ev.get("Account #"))


def test_funded_breach_blocked_until_hr11_marked():
    app = _AppStub()
    ev = {
        "Account #.1": "99999",
        "Hedge Result 1.1": "WED",
        "Prop Firm": "Tradeify",
    }
    app._parse_day_token = staticmethod(lambda v: 3 if str(v).upper() == "WED" else None)
    assert app._has_taken_funded_trade1(ev) is False
    mgr = app.prop_firm_mgr
    assert mgr.get_breach_floor("Tradeify", "Funded", after_funded_trade1=False) is None

    ev2 = {**ev, "Hedge Result 1.1": "$0.00"}
    app._parse_day_token = staticmethod(lambda v: None)
    assert app._has_taken_funded_trade1(ev2) is True
    assert mgr.get_breach_floor("Tradeify", "Funded", after_funded_trade1=True) == 48000.0


def test_ft2_gate_requires_hr21():
    app = _AppStub()
    ev_ft1_only = {
        "Account #.1": "99999",
        "Hedge Result 1.1": "$1,200.00",
        "Hedge Result 2.1": "THU",
        "Prop Firm": "Tradeify",
    }
    app._parse_day_token = staticmethod(lambda v: 4 if str(v).upper() == "THU" else None)

    def has_ft2(ev):
        if not app._on_funded_leg(ev):
            return False
        hr2 = app._cell(ev.get("Hedge Result 2.1"))
        if hr2 and hr2 not in ("—", "-") and app._parse_day_token(hr2) is None:
            return True
        return False

    assert has_ft2(ev_ft1_only) is False
    ev_ft2 = {**ev_ft1_only, "Hedge Result 2.1": "$0.00"}
    app._parse_day_token = staticmethod(lambda v: None)
    assert has_ft2(ev_ft2) is True
    mgr = app.prop_firm_mgr
    assert mgr.get_breach_floor(
        "Tradeify", "Funded", after_funded_trade1=True, after_funded_trade2=True
    ) == 50100.0
