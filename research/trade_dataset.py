"""Load MT5 deal history and active positions from clients_data."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from research.mt5_time import deal_instant_utc, infer_utc_correction_sec, timing_for_client
from trader_companion.mt5_comment_parser import MT5CommentParser


def _timestamp_from_deal(deal: dict, *, correction_sec: int = 0) -> Optional[pd.Timestamp]:
    return deal_instant_utc(deal, correction_sec=correction_sec)


def _parse_close_time(value: Any) -> Optional[datetime]:
    """Legacy helper — returns naive UTC wall time for sorting."""
    fake = {"time": value} if not isinstance(value, dict) else value
    ts = deal_instant_utc(fake, correction_sec=0)
    if ts is None:
        return None
    return ts.to_pydatetime().replace(tzinfo=None)


def _normalize_side(raw: Any) -> str:
    s = str(raw or "").strip().upper()
    if s in ("BUY", "0", "0.0"):
        return "BUY"
    if s in ("SELL", "1", "1.0"):
        return "SELL"
    if "BUY" in s:
        return "BUY"
    if "SELL" in s:
        return "SELL"
    return "?"


def load_clients_positions(client_id: Optional[str] = None) -> Dict[str, List[dict]]:
    """Return {client_id: [position dicts]} from clients_data.positions."""
    import json as _json

    from dashboard.database import get_direct_connection

    out: Dict[str, List[dict]] = {}
    with get_direct_connection() as conn:
        if client_id:
            row = conn.execute(
                "SELECT client_id, positions FROM clients_data WHERE client_id = ?",
                (client_id,),
            ).fetchone()
            rows = [row] if row else []
        else:
            rows = conn.execute("SELECT client_id, positions FROM clients_data").fetchall()
        for row in rows:
            cid = row["client_id"]
            raw = row["positions"]
            pos = _json.loads(raw) if isinstance(raw, str) else (raw or [])
            out[cid] = pos if isinstance(pos, list) else []
    return out


def load_active_positions_df(client_id: Optional[str] = None) -> pd.DataFrame:
    """
    Flatten all open MT5 positions (active trades) with parsed prop account + phase.
    Uses real sl/tp from the live position snapshot.
    Applies the same per-client MT5→EAT timestamp correction as closed round-trips.
    """
    parser = MT5CommentParser()
    rows: List[dict] = []
    now_utc = datetime.utcnow()

    positions_map = load_clients_positions(client_id)
    deals_map = load_clients_deals(client_id)
    identity_map = load_clients_identity(client_id)

    for cid, positions in positions_map.items():
        corr = _utc_correction_for_client(
            cid, deals_map.get(cid, []), identity_map.get(cid, {})
        )
        for p in positions or []:
            if not isinstance(p, dict):
                continue
            comment = str(p.get("comment") or "")
            parsed = parser.parse(comment)
            entry_ts = _timestamp_from_deal(p, correction_sec=corr)
            entry_dt = (
                entry_ts.to_pydatetime().replace(tzinfo=None) if entry_ts is not None else now_utc
            )
            open_px = float(p.get("price_open") or p.get("price_current") or 0)
            sl = float(p.get("sl") or 0)
            tp = float(p.get("tp") or 0)
            side = _normalize_side(p.get("type"))

            rows.append(
                {
                    "client_id": cid,
                    "ticket": p.get("ticket"),
                    "symbol": p.get("symbol", ""),
                    "side": side,
                    "volume": float(p.get("volume") or 0),
                    "open_price": open_px,
                    "close_price": float(p.get("price_current") or open_px),
                    "sl": sl,
                    "tp": tp,
                    "profit": float(p.get("profit") or 0),
                    "comment": comment,
                    "account_number": parsed.account_number if parsed.is_valid else None,
                    "phase_code": parsed.phase_code if parsed.is_valid else "UNK",
                    "phase_name": parsed.phase.name if parsed.phase else None,
                    "trade_number": parsed.trade_number,
                    "entry_time": entry_dt,
                    "close_time": entry_dt,
                    "trade_date": entry_dt.date().isoformat(),
                    "parse_valid": parsed.is_valid,
                    "is_active": True,
                    "net_pnl": float(p.get("profit") or 0),
                }
            )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _position_sl_tp_map(positions: List[dict]) -> Dict[int, dict]:
    m: Dict[int, dict] = {}
    for p in positions or []:
        if not isinstance(p, dict):
            continue
        tid = p.get("ticket") or p.get("position_id")
        if tid is None:
            continue
        try:
            m[int(tid)] = {
                "sl": float(p.get("sl") or 0),
                "tp": float(p.get("tp") or 0),
                "comment": p.get("comment") or "",
                "price_open": float(p.get("price_open") or 0),
            }
        except (TypeError, ValueError):
            continue
    return m


def enrich_round_trips_with_positions(df: pd.DataFrame, positions_by_client: Dict[str, List[dict]]) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if "position_comment" not in out.columns:
        out["position_comment"] = ""
    for i, row in out.iterrows():
        cid = row.get("client_id", "")
        pid = row.get("position_id")
        pos_map = _position_sl_tp_map(positions_by_client.get(cid, []))
        snap = pos_map.get(int(pid)) if pid is not None else None
        if snap:
            if not row.get("sl") and snap.get("sl"):
                out.at[i, "sl"] = snap["sl"]
            if not row.get("tp") and snap.get("tp"):
                out.at[i, "tp"] = snap["tp"]
            if (not row.get("comment") or row.get("phase_code") == "UNK") and snap.get("comment"):
                out.at[i, "position_comment"] = snap["comment"]
    return out


def load_clients_deals(client_id: Optional[str] = None) -> Dict[str, List[dict]]:
    import json as _json

    from dashboard.database import get_direct_connection

    out: Dict[str, List[dict]] = {}
    with get_direct_connection() as conn:
        if client_id:
            row = conn.execute(
                "SELECT client_id, deals FROM clients_data WHERE client_id = ?",
                (client_id,),
            ).fetchone()
            rows = [row] if row else []
        else:
            rows = conn.execute("SELECT client_id, deals FROM clients_data").fetchall()
        for row in rows:
            cid = row["client_id"]
            raw = row["deals"]
            deals = _json.loads(raw) if isinstance(raw, str) else (raw or [])
            out[cid] = deals
    return out


def load_clients_identity(client_id: Optional[str] = None) -> Dict[str, dict]:
    import json as _json

    from dashboard.database import get_direct_connection

    out: Dict[str, dict] = {}
    with get_direct_connection() as conn:
        if client_id:
            row = conn.execute(
                "SELECT client_id, identity FROM clients_data WHERE client_id = ?",
                (client_id,),
            ).fetchone()
            rows = [row] if row else []
        else:
            rows = conn.execute("SELECT client_id, identity FROM clients_data").fetchall()
        for row in rows:
            cid = row["client_id"]
            raw = row["identity"]
            ident = _json.loads(raw) if isinstance(raw, str) else (raw or {})
            out[cid] = ident if isinstance(ident, dict) else {}
    return out


def client_utc_correction_map(client_id: Optional[str] = None) -> Dict[str, int]:
    """Per-client deal timestamp correction (seconds) for EAT entry-hour bucketing."""
    deals_map = load_clients_deals(client_id)
    identity_map = load_clients_identity(client_id)
    out: Dict[str, int] = {}
    for cid, deals in deals_map.items():
        out[cid] = _utc_correction_for_client(cid, deals or [], identity_map.get(cid, {}))
    return out


def _utc_correction_for_client(client_id: str, deals: List[dict], identity: dict) -> int:
    """
    Per-client seconds added to MT5 ``time_raw`` when building round-trip times.

    Prefer companion ``mt5_timing`` when present, else dual-field inference. When a
    non-zero correction buckets many entries outside 02:00–17:00 EAT, fall back to 0
    (Plexy wall-clock digits = EAT) — inferred offsets are often wrong on mixed ISO/raw.
    """
    timing = timing_for_client(identity)
    correction: Optional[int] = None
    if timing.get("utc_correction_sec") is not None:
        try:
            correction = int(timing["utc_correction_sec"])
        except (TypeError, ValueError):
            correction = None
    if correction is None:
        correction, _ = infer_utc_correction_sec(deals)

    if correction != 0 and deals:
        off_corr = _entry_off_hours_rate(deals, client_id, correction)
        off_zero = _entry_off_hours_rate(deals, client_id, 0)
        if off_zero + 0.03 < off_corr:
            return 0
    return int(correction)


def _deal_time_raw(deal: dict, *, correction_sec: int = 0) -> float:
    ts = _timestamp_from_deal(deal, correction_sec=correction_sec)
    return float(ts.timestamp()) if ts is not None else 0.0


def deals_to_round_trips(
    deals: List[dict],
    client_id: str = "",
    *,
    utc_correction_sec: int = 0,
) -> pd.DataFrame:
    if not deals:
        return pd.DataFrame()

    parser = MT5CommentParser()
    positions: Dict[int, List[dict]] = {}

    for deal in deals:
        d_type = str(deal.get("type", "")).upper()
        if d_type in ("BALANCE", "CREDIT", "2", "3", "CHARGE", "CORRECTION", "BONUS"):
            continue
        if "internal transfer" in str(deal.get("comment") or "").lower():
            continue
        pid = deal.get("position_id") or 0
        if not pid:
            continue
        positions.setdefault(int(pid), []).append(deal)

    rows: List[dict] = []
    for pid, deal_list in positions.items():
        entry_deal = None
        has_exit = False
        exit_time = 0.0
        total_profit = total_commission = total_swap = total_fee = 0.0

        for d in deal_list:
            entry_val = d.get("entry", "")
            entry_str = str(entry_val).upper() if entry_val != "" else ""
            is_entry = entry_val == 0 or entry_str == "IN"
            is_exit = entry_val in (1, 2, 3) or entry_str in ("OUT", "INOUT", "OUT_BY")
            if is_entry and entry_deal is None:
                entry_deal = d
            if is_exit:
                has_exit = True
            t = _deal_time_raw(d, correction_sec=utc_correction_sec)
            if t > exit_time:
                exit_time = t
            total_profit += float(d.get("profit") or 0)
            total_commission += float(d.get("commission") or 0)
            total_swap += float(d.get("swap") or 0)
            total_fee += float(d.get("fee") or 0)

        if not has_exit:
            continue

        if not entry_deal:
            for d in deal_list:
                c = d.get("comment") or ""
                if c and any(x in c for x in ("CH", "FD", "FA", "DD")):
                    entry_deal = d
                    break
        if not entry_deal:
            entry_deal = deal_list[0]

        exit_deal = None
        for d in deal_list:
            entry_val = d.get("entry", "")
            entry_str = str(entry_val).upper() if entry_val != "" else ""
            is_exit = entry_val in (1, 2, 3) or entry_str in ("OUT", "INOUT", "OUT_BY")
            if is_exit:
                if exit_deal is None or _deal_time_raw(d, correction_sec=utc_correction_sec) >= _deal_time_raw(
                    exit_deal, correction_sec=utc_correction_sec
                ):
                    exit_deal = d
        if exit_deal is None:
            exit_deal = deal_list[-1]

        comment = entry_deal.get("comment") or ""
        parsed = parser.parse(comment)
        entry_ts = _timestamp_from_deal(entry_deal, correction_sec=utc_correction_sec)
        entry_dt = (
            entry_ts.to_pydatetime().replace(tzinfo=None) if entry_ts is not None else None
        )
        exit_ts = (
            pd.Timestamp(exit_time, unit="s", tz="UTC") + pd.Timedelta(seconds=int(utc_correction_sec))
            if exit_time
            else _timestamp_from_deal(exit_deal, correction_sec=utc_correction_sec)
        )
        close_dt = (
            exit_ts.tz_convert("UTC").to_pydatetime().replace(tzinfo=None)
            if exit_ts is not None
            else None
        )
        side = _normalize_side(entry_deal.get("type"))
        open_px = float(entry_deal.get("price") or 0)
        close_px = float(exit_deal.get("price") or 0)
        sl_px = float(entry_deal.get("sl") or exit_deal.get("sl") or 0)
        tp_px = float(entry_deal.get("tp") or exit_deal.get("tp") or 0)

        rows.append(
            {
                "client_id": client_id,
                "position_id": pid,
                "symbol": entry_deal.get("symbol", ""),
                "side": side,
                "volume": float(entry_deal.get("volume") or 0),
                "open_price": open_px,
                "close_price": close_px,
                "sl": sl_px,
                "tp": tp_px,
                "net_pnl": round(total_profit + total_commission + total_swap + total_fee, 2),
                "comment": comment,
                "account_number": parsed.account_number if parsed.is_valid else None,
                "phase_code": parsed.phase_code if parsed.is_valid else None,
                "phase_name": parsed.phase.name if parsed.phase else None,
                "trade_number": parsed.trade_number,
                "entry_time": entry_dt,
                "close_time": close_dt,
                "trade_date": entry_dt.date().isoformat() if entry_dt else "",
                "deal_count": len(deal_list),
                "parse_valid": parsed.is_valid,
                "is_active": False,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("close_time").reset_index(drop=True)


_ENTRY_OFF_MARGIN = 0.03
_MIN_RT_FOR_OFF_CHECK = 10


def _entry_off_hours_rate(deals: List[dict], client_id: str, correction_sec: int) -> float:
    """Share of closed round-trips with entry outside 02:00–17:00 EAT (prop entry window)."""
    from research.eat_time import entry_times_to_eat
    from research.market_signals import EAT_ENTRY_END_HOUR, EAT_ENTRY_START_HOUR

    rt = deals_to_round_trips(deals, client_id=client_id, utc_correction_sec=correction_sec)
    if len(rt) < _MIN_RT_FOR_OFF_CHECK:
        return 1.0
    corr_series = pd.Series(int(correction_sec), index=rt.index, dtype=int)
    hours = entry_times_to_eat(rt["entry_time"], corr_series).dt.hour
    bad = ((hours < EAT_ENTRY_START_HOUR) | (hours > EAT_ENTRY_END_HOUR)).sum()
    return float(bad) / len(hours)


def load_all_round_trips(
    client_id: Optional[str] = None,
    *,
    attach_positions: bool = True,
) -> pd.DataFrame:
    parts: List[pd.DataFrame] = []
    deals_map = load_clients_deals(client_id)
    identity_map = load_clients_identity(client_id)
    pos_map = load_clients_positions(client_id) if attach_positions else {}
    for cid, deals in deals_map.items():
        if not deals:
            continue
        corr = _utc_correction_for_client(cid, deals, identity_map.get(cid, {}))
        rt = deals_to_round_trips(deals, client_id=cid, utc_correction_sec=corr)
        if not rt.empty:
            if attach_positions:
                rt = enrich_round_trips_with_positions(rt, {cid: pos_map.get(cid, [])})
            parts.append(rt)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def coverage_report(clients_deals: Optional[Dict[str, List[dict]]] = None) -> pd.DataFrame:
    from dashboard.database import get_all_clients

    if clients_deals is None:
        all_rows = get_all_clients()
        clients_deals = {cid: (row.get("deals") or []) for cid, row in all_rows.items()}
        last_updated_map = {cid: row.get("last_updated") for cid, row in all_rows.items()}
    else:
        last_updated_map = {}

    rows = []
    for cid, deals in clients_deals.items():
        if isinstance(deals, str):
            deals = json.loads(deals)
        n_deals = len(deals)
        last_up = last_updated_map.get(cid)
        ident = load_clients_identity(cid).get(cid, {})
        corr = _utc_correction_for_client(cid, deals, ident) if n_deals else 0
        rt = (
            deals_to_round_trips(deals, client_id=cid, utc_correction_sec=corr)
            if n_deals
            else pd.DataFrame()
        )
        n_rt = len(rt)
        valid = int(rt["parse_valid"].sum()) if n_rt and "parse_valid" in rt.columns else 0
        pnl = float(rt["net_pnl"].sum()) if n_rt else 0.0
        first = rt["close_time"].min() if n_rt and rt["close_time"].notna().any() else None
        last = rt["close_time"].max() if n_rt and rt["close_time"].notna().any() else None
        rows.append(
            {
                "client_id": cid,
                "raw_deals": n_deals,
                "round_trips": n_rt,
                "parsed_comments": valid,
                "parse_rate_pct": round(100 * valid / n_rt, 1) if n_rt else 0,
                "total_net_pnl": round(pnl, 2),
                "first_close": first,
                "last_close": last,
                "last_updated": last_up,
            }
        )
    return pd.DataFrame(rows).sort_values("round_trips", ascending=False)
