"""Dashboard vanish breach: account gone after CH1/FT1/FT2 means prop breach."""


def _parse_day(v):
    s = str(v or "").strip().upper()
    return {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4}.get(s)


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


def _has_ch1(ev):
    if _on_funded_leg(ev):
        return False
    hr1 = _cell(ev.get("Hedge Result 1"))
    return bool(hr1 and hr1 not in ("—", "-") and _parse_day(hr1) is None)


def _has_ft1(ev):
    if not _on_funded_leg(ev):
        return False
    hr1 = _cell(ev.get("Hedge Result 1.1"))
    if hr1 and hr1 not in ("—", "-") and _parse_day(hr1) is None:
        return True
    return any(
        _cell(ev.get(f"Hedge Result {i}.1")) not in ("", "—", "-")
        for i in range(2, 8)
    )


def _present_accounts(evals):
    out = set()
    for ev in evals or []:
        if ev.get("_deleted"):
            continue
        for f in ("Account #", "Account #.1"):
            a = _cell_account(ev.get(f))
            if a:
                out.add(a.lower())
    return out


class _VanishModel:
    """Mirrors TradeOpssAIApp dashboard vanish registry (minimal)."""

    TIER_RANK = {"ch1": 1, "ft1": 2, "ft2": 3}

    def __init__(self):
        self.registry = {}

    def sync(self, evaluations):
        for ev in evaluations or []:
            if ev.get("_deleted"):
                continue
            if not _on_funded_leg(ev):
                ch = _cell_account(ev.get("Account #"))
                if ch and _has_ch1(ev):
                    self._reg(ch, ev, False, "ch1")
            fu = _cell_account(ev.get("Account #.1"))
            if fu and _has_ft1(ev):
                self._reg(fu, ev, True, "ft1")

    def _reg(self, account, ev, on_funded, tier):
        key = account.lower()
        self.registry[key] = {
            "ev_snapshot": dict(ev),
            "on_funded": on_funded,
            "tier": tier,
            "row_key": "|".join(
                x for x in (
                    _cell_account(ev.get("Account #")).lower(),
                    _cell_account(ev.get("Account #.1")).lower(),
                ) if x
            ),
        }

    def apply_vanish(self, evaluations):
        present = _present_accounts(evaluations)
        failures = []
        for key, meta in list(self.registry.items()):
            if key in present:
                continue
            ev = dict(meta["ev_snapshot"])
            field = "Status" if meta["on_funded"] else "Status P1"
            ev[field] = "Fail"
            evaluations.append(ev)
            failures.append(key)
            for rk in meta["row_key"].split("|"):
                self.registry.pop(rk, None)
        return failures


def test_no_vanish_breach_without_ch1_marker():
    m = _VanishModel()
    ev = {"Account #": "10001", "Hedge Result 1": "MON", "Prop Firm": "Tradeify"}
    m.sync([ev])
    assert "10001" not in m.registry
    m.apply_vanish([])
    assert not any(e.get("Status P1") == "Fail" for e in [])


def test_ch1_account_vanish_marks_fail():
    m = _VanishModel()
    ev = {
        "Account #": "10001",
        "Hedge Result 1": "$0.00",
        "Prop Firm": "Tradeify",
        "Status P1": "In Progress",
    }
    m.sync([ev])
    assert "10001" in m.registry
    evals = []
    failed = m.apply_vanish(evals)
    assert failed == ["10001"]
    assert len(evals) == 1
    assert evals[0]["Status P1"] == "Fail"


def test_ft1_funded_account_vanish_marks_funded_status():
    m = _VanishModel()
    ev = {
        "Account #": "10001",
        "Account #.1": "20002",
        "Hedge Result 1.1": "$500.00",
        "Prop Firm": "Tradeify",
        "Status": "In Progress",
    }
    m.sync([ev])
    assert "20002" in m.registry
    evals = []
    m.apply_vanish(evals)
    assert evals[0]["Status"] == "Fail"


def test_still_on_dashboard_no_vanish_fail():
    m = _VanishModel()
    ev = {
        "Account #.1": "20002",
        "Hedge Result 1.1": "$500.00",
        "Prop Firm": "Tradeify",
    }
    m.sync([ev])
    evals = [ev]
    failed = m.apply_vanish(evals)
    assert failed == []
    assert ev.get("Status") != "Fail"
