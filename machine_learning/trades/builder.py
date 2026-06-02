"""Build round-trip trades from MT5 deal dicts (same rules as trade_history_analysis)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, List, Optional

from machine_learning.trades.models import Trade

_INTERNAL_TYPES = frozenset({
    "BALANCE", "CREDIT", "2", "2.0", "3", "3.0",
    "CHARGE", "CORRECTION", "BONUS",
    "DEAL_TYPE_BALANCE", "DEAL_TYPE_CREDIT",
})


def parse_deal_dt(deal: dict) -> Optional[datetime]:
    raw = deal.get("time_raw")
    if raw is None or raw == "":
        raw = deal.get("time") or deal.get("open_time")
    if raw is None or raw == "":
        return None
    try:
        n = float(raw)
        if n > 10_000_000_000:
            n = n / 1000.0
        if n > 1_000_000_000:
            return datetime.fromtimestamp(n)
    except (TypeError, ValueError):
        pass
    try:
        s = str(raw).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def deal_pnl(deal: dict) -> float:
    return (
        float(deal.get("profit") or 0)
        + float(deal.get("swap") or 0)
        + float(deal.get("commission") or 0)
        + float(deal.get("fee") or 0)
    )


def is_internal_deal(deal: dict) -> bool:
    if not isinstance(deal, dict):
        return True
    raw_type = str(deal.get("type", "")).strip().upper()
    raw_entry = str(deal.get("entry", "")).strip().upper()
    try:
        if int(float(raw_type)) in (2, 3):
            return True
    except (TypeError, ValueError):
        pass
    if raw_type in _INTERNAL_TYPES or raw_entry in _INTERNAL_TYPES:
        return True
    if "BALANCE" in raw_type or "CREDIT" in raw_type:
        return True
    return False


def normalize_direction(raw: Any) -> str:
    s = str(raw or "").strip().upper()
    if s in ("BUY", "0", "0.0"):
        return "BUY"
    if s in ("SELL", "1", "1.0"):
        return "SELL"
    if "BUY" in s:
        return "BUY"
    if "SELL" in s:
        return "SELL"
    return s or "?"


def filter_trade_deals(deals: List[dict]) -> List[dict]:
    out = []
    for d in deals or []:
        if not isinstance(d, dict) or is_internal_deal(d):
            continue
        if not parse_deal_dt(d):
            continue
        out.append(d)
    return out


def build_trades(client_id: str, deals: List[dict]) -> List[Trade]:
    """Group deals by position_id into round-trip trades."""
    by_pos: dict = defaultdict(list)
    orphans: List[dict] = []

    for d in deals:
        pos_id = d.get("position_id")
        if pos_id in (None, "", 0, "0"):
            orphans.append(d)
            continue
        by_pos[pos_id].append(d)

    trades: List[Trade] = []

    for pos_id, pos_deals in by_pos.items():
        pos_deals.sort(key=lambda x: parse_deal_dt(x) or datetime.min)
        first, last = pos_deals[0], pos_deals[-1]
        entry_dt = parse_deal_dt(first)
        exit_dt = parse_deal_dt(last)
        if not entry_dt or not exit_dt:
            continue
        net = sum(deal_pnl(d) for d in pos_deals)
        trades.append(
            Trade(
                client_id=client_id,
                position_id=pos_id,
                symbol=str(first.get("symbol") or ""),
                direction=normalize_direction(first.get("type")),
                volume=float(first.get("volume") or 0),
                entry_dt=entry_dt,
                exit_dt=exit_dt,
                net_pnl=round(net, 2),
                deal_count=len(pos_deals),
            )
        )

    if len(trades) < max(3, len(deals) * 0.15):
        out_deals = [
            d for d in orphans
            if str(d.get("entry", "")).upper() in ("OUT", "1", "1.0", "OUT_BY", "3")
        ]
        if not out_deals:
            out_deals = [d for d in orphans if abs(deal_pnl(d)) > 0.001]
        seen = {t.position_id for t in trades}
        for d in out_deals:
            ticket = d.get("ticket") or d.get("order")
            if ticket in seen:
                continue
            dt = parse_deal_dt(d)
            if not dt:
                continue
            trades.append(
                Trade(
                    client_id=client_id,
                    position_id=ticket,
                    symbol=str(d.get("symbol") or ""),
                    direction=normalize_direction(d.get("type")),
                    volume=float(d.get("volume") or 0),
                    entry_dt=dt,
                    exit_dt=dt,
                    net_pnl=round(deal_pnl(d), 2),
                    deal_count=1,
                )
            )

    trades.sort(key=lambda t: t.exit_dt)
    return trades
