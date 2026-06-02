"""Blueprint-style phase badges and prop-firm labels for research reports."""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

# Lazy singleton to avoid log spam on bulk enrichment
_PROP_MGR = None


def _prop_mgr():
    global _PROP_MGR
    if _PROP_MGR is None:
        from trader_companion.prop_firm_manager import PropFirmManager

        _PROP_MGR = PropFirmManager()
        _PROP_MGR.logger.disabled = True
    return _PROP_MGR


def phase_badge(phase_code: Any, trade_number: Any = None) -> str:
    """
    Blueprint phase column label: CH1, FD2, DD1, FA, UNK.
    Matches TradeOpssAIApp._phase_badge_label semantics.
    """
    code = str(phase_code or "").strip().upper()
    if not code or code in ("UNK", "NONE", "NAN", "?"):
        return "UNK"

    if code == "FA":
        return "FA"

    num = trade_number
    if num is not None and not (isinstance(num, float) and pd.isna(num)):
        try:
            n = int(num)
            if code in ("CH", "FD", "DD"):
                return f"{code}{n}"
        except (TypeError, ValueError):
            pass

    if code.startswith("CH") and len(code) > 2:
        return code
    if code.startswith("FD") and len(code) > 2:
        return code
    if code.startswith("DD") and len(code) > 2:
        return code

    if code in ("CH", "FD", "DD"):
        return f"{code}1"

    return code[:6]


def phase_stage(phase_code: Any) -> str:
    """Blueprint stage name (Evaluation / Funded / Farming)."""
    code = str(phase_code or "").strip().upper()
    if code.startswith("CH") or code == "CH":
        return "Challenge"
    if code.startswith("FD") or code == "FD":
        return "Funded"
    if code.startswith("DD") or code == "DD":
        return "Double Dip"
    if code.startswith("FA") or code == "FA":
        return "Farming"
    return "Unknown"


def detect_prop_firm_blueprint(account_number: Any, comment: Any = None) -> str:
    """UI blueprint name from Tradovate account (e.g. MFFU_Flex, TopStep)."""
    candidates = []
    for raw in (account_number, comment):
        acct = str(raw or "").strip()
        if not acct or acct.lower() in ("nan", "none", "unknown"):
            continue
        # Comment form: MFFUEVSTP326057008_CH1
        if "_" in acct:
            acct = acct.split("_", 1)[0]
        candidates.append(acct)

    mgr = _prop_mgr()
    for acct in candidates:
        firm = mgr.detect_firm_from_account(acct)
        if firm:
            return firm
    return "Unknown"


def _short_account(account_number: Any) -> str:
    acct = str(account_number or "")
    if not acct:
        return "—"
    if len(acct) <= 12:
        return acct
    return f"{acct[:4]}…{acct[-5:]}"


def enrich_trade_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Add prop_firm, phase_badge, phase_stage, account_short; sort keys."""
    if df is None or df.empty:
        return df

    out = df.copy()
    firms = []
    badges = []
    stages = []
    shorts = []

    firm_cache: dict = {}

    for _, row in out.iterrows():
        acct = row.get("account_number")
        cache_key = (acct, row.get("comment"))
        if cache_key not in firm_cache:
            firm_cache[cache_key] = detect_prop_firm_blueprint(
                acct, row.get("comment") or row.get("position_comment")
            )
        firms.append(firm_cache[cache_key])

        code = row.get("phase_code") or row.get("phase_group") or "UNK"
        tn = row.get("trade_number")
        badges.append(phase_badge(code, tn))
        stages.append(phase_stage(code))
        shorts.append(_short_account(acct))

    out["prop_firm"] = firms
    out["phase_badge"] = badges
    out["phase_stage"] = stages
    out["account_short"] = shorts

    out["_sort_firm"] = out["prop_firm"].fillna("Unknown")
    out["_sort_badge"] = out["phase_badge"].fillna("UNK")
    return out


def sort_for_report(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by prop firm → phase badge → client → entry time."""
    if df is None or df.empty:
        return df
    cols = ["_sort_firm", "_sort_badge", "client_id"]
    if "entry_time" in df.columns:
        cols.append("entry_time")
    for c in cols:
        if c not in df.columns:
            if c.startswith("_sort"):
                df[c] = df.get("prop_firm" if "firm" in c else "phase_badge", "")
    return df.sort_values(
        [c for c in cols if c in df.columns],
        ascending=[True, True, True, False],
        na_position="last",
    ).reset_index(drop=True)
