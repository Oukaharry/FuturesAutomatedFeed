"""MT5-style round-trip history correlated with AI predictions and learning notes.

For each closed trade: entry/exit time & price (like MetaTrader 5), the AI
prediction active at entry, and for losses — what went wrong, what the model
changed on the next prediction, and whether that helped subsequent accuracy.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

KENYA_TZ = timezone.utc  # display uses local formatting from epoch

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

try:
    from trader_companion.signals import prediction_tracker
except ImportError:
    try:
        from signals import prediction_tracker
    except ImportError:
        prediction_tracker = None


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _outcomes_path() -> str:
    return os.path.join(_base_dir(), "trade_outcomes_journal.jsonl")


def _fmt_ts(epoch: Optional[int]) -> str:
    if not epoch:
        return "—"
    try:
        return datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "—"


def _duration_min(entry_ts: int, exit_ts: int) -> Optional[int]:
    if not entry_ts or not exit_ts or exit_ts <= entry_ts:
        return None
    return max(1, int((exit_ts - entry_ts) / 60))


def fetch_deals(days: int = 30, deals_fn=None) -> List[Dict[str, Any]]:
    """Fetch deal dicts — prefer injected ``deals_fn`` (pusher.get_deals)."""
    if deals_fn is not None:
        try:
            return list(deals_fn(days=days) or [])
        except Exception:
            pass
    if not MT5_AVAILABLE:
        return []
    try:
        t0 = time.time() - days * 86400
        raw = mt5.history_deals_get(t0, time.time() + 3600)
        if raw is None:
            return []
        out = []
        for d in raw:
            out.append({
                "ticket": d.ticket,
                "position_id": d.position_id,
                "symbol": d.symbol,
                "type": "BUY" if d.type == 0 else "SELL" if d.type == 1 else str(d.type),
                "entry": "IN" if d.entry == 0 else "OUT" if d.entry == 1 else str(d.entry),
                "volume": float(d.volume),
                "price": float(d.price),
                "profit": float(d.profit),
                "commission": float(getattr(d, "commission", 0) or 0),
                "swap": float(getattr(d, "swap", 0) or 0),
                "time_raw": int(d.time),
                "comment": str(getattr(d, "comment", "") or ""),
            })
        return out
    except Exception:
        return []


def round_trips_from_deals(deals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build MT5-like round trips: entry time/price, exit time/price, net P/L."""
    by_pos: Dict[int, List[Dict]] = defaultdict(list)
    for d in deals:
        pid = int(d.get("position_id") or 0)
        if pid <= 0:
            continue
        t = str(d.get("type", "")).upper()
        if t in ("BALANCE", "CREDIT", "2", "3"):
            continue
        by_pos[pid].append(d)

    trips: List[Dict[str, Any]] = []
    for pid, dl in by_pos.items():
        dl.sort(key=lambda x: x.get("time_raw", 0))
        entry_deals = [d for d in dl if str(d.get("entry", "")).upper() == "IN"]
        exit_deals = [d for d in dl if str(d.get("entry", "")).upper() == "OUT"]
        if not entry_deals:
            continue
        ent = entry_deals[0]
        ex = exit_deals[-1] if exit_deals else None
        side = str(ent.get("type", "")).upper()
        if side not in ("BUY", "SELL"):
            continue
        net = sum(float(d.get("profit", 0) or 0) for d in dl)
        net += sum(float(d.get("commission", 0) or 0) for d in dl)
        net += sum(float(d.get("swap", 0) or 0) for d in dl)
        entry_ts = int(ent.get("time_raw", 0))
        exit_ts = int(ex.get("time_raw", 0)) if ex else None
        entry_px = float(ent.get("price", 0))
        exit_px = float(ex.get("price", 0)) if ex else None
        closed = ex is not None
        move = None
        if closed and entry_px and exit_px:
            move = exit_px - entry_px
            if side == "SELL":
                move = -move
        trips.append({
            "position_id": pid,
            "symbol": ent.get("symbol", ""),
            "side": side.lower(),
            "volume": float(ent.get("volume", 0)),
            "entry_time": entry_ts,
            "entry_time_str": _fmt_ts(entry_ts),
            "entry_price": round(entry_px, 2),
            "exit_time": exit_ts,
            "exit_time_str": _fmt_ts(exit_ts) if exit_ts else "OPEN",
            "exit_price": round(exit_px, 2) if exit_px is not None else None,
            "duration_min": _duration_min(entry_ts, exit_ts) if exit_ts else None,
            "net_profit": round(net, 2),
            "closed": closed,
            "signed_move": round(move, 2) if move is not None else None,
            "comment": ent.get("comment", ""),
            "won": closed and net > 0,
            "lost": closed and net < 0,
        })
    trips.sort(key=lambda t: t.get("entry_time", 0), reverse=True)
    return trips


def _load_predictions() -> List[Dict[str, Any]]:
    if prediction_tracker is None:
        return []
    try:
        prediction_tracker._load("ustech")  # noqa: SLF001
        return list(prediction_tracker._records.get("ustech", []))  # noqa: SLF001
    except Exception:
        return []


def _prediction_at_time(preds: List[Dict], entry_ts: int, window_sec: int = 900):
    """Nearest AI prediction within ``window_sec`` before entry."""
    best = None
    best_dt = window_sec + 1
    for p in preds:
        if p.get("simulated"):
            continue
        pts = int(p.get("ts") or p.get("bar_time") or 0)
        if pts > entry_ts:
            continue
        dt = entry_ts - pts
        if 0 <= dt < best_dt:
            best_dt = dt
            best = p
    return best


def _prediction_after(preds: List[Dict], exit_ts: int, limit: int = 5):
    """First verified predictions after the trade closed."""
    after = []
    for p in preds:
        if not p.get("verified"):
            continue
        pts = int(p.get("verified_at") or p.get("ts") or 0)
        if pts >= exit_ts:
            after.append(p)
    after.sort(key=lambda x: x.get("verified_at", 0))
    return after[:limit]


def _learning_for_loss(trip: Dict, pred_entry: Optional[Dict],
                       preds_after: List[Dict]) -> Dict[str, str]:
    """Human-readable learning narrative for a losing trade."""
    side = trip.get("side", "?").upper()
    move = trip.get("signed_move")
    dur = trip.get("duration_min")
    wrong_parts = []
    improve_parts = []
    help_parts = []

    if pred_entry:
        lean = str(pred_entry.get("lean", "?")).upper()
        conf = pred_entry.get("confidence")
        vote = pred_entry.get("vote_score_input")  # may be absent on old records
        wrong_parts.append(
            f"At entry the AI leaned {lean} (confidence {conf}) "
            f"while we took a {side} hedge leg.")
        if move is not None:
            wrong_parts.append(
                f"Price moved {move:+.1f} pts against the position over {dur or '?'} min.")
        if vote is not None:
            wrong_parts.append(f"Indicator vote score at entry was {vote:+.2f}.")
    else:
        wrong_parts.append(
            f"No AI journal entry matched this entry time — "
            f"loss was {trip.get('net_profit', 0):+.2f} on {side}.")

    if preds_after:
        p1 = preds_after[0]
        thr = p1.get("confidence_threshold")
        base = prediction_tracker.CONFIDENCE_THRESHOLD if prediction_tracker else 0.6
        if thr and thr > base:
            improve_parts.append(
                f"Adaptive gate tightened to {thr:.2f} (base {base:.2f}) — "
                f"model must be more confident before acting.")
        verified = [p for p in preds_after if p.get("verified")]
        if verified:
            wins = sum(1 for p in verified if p.get("correct"))
            improve_parts.append(
                f"Next {len(verified)} verified prediction(s): "
                f"{wins} followed by the market.")
        if not improve_parts:
            improve_parts.append(
                "Journal updated with this loss pattern for recency-weighted retraining.")
    else:
        improve_parts.append(
            "Waiting for the next verified predictions to measure improvement.")

    if preds_after:
        verified = [p for p in preds_after if p.get("verified")]
        if verified:
            acc = sum(1 for p in verified if p.get("correct")) / len(verified)
            if acc >= 0.6:
                help_parts.append(
                    f"Subsequent accuracy {acc:.0%} — post-loss adjustments appear to be helping.")
            elif acc >= 0.45:
                help_parts.append(
                    f"Subsequent accuracy {acc:.0%} — partial recovery, still calibrating.")
            else:
                help_parts.append(
                    f"Subsequent accuracy {acc:.0%} — gate remains strict until scorecard improves.")
        else:
            help_parts.append("Not enough verified predictions yet to score if changes helped.")
    else:
        help_parts.append("Keep the AI monitor open — learning loop verifies every 60s.")

    return {
        "what_went_wrong": " ".join(wrong_parts),
        "what_improved": " ".join(improve_parts),
        "did_it_help": " ".join(help_parts),
    }


def build_trade_history(days: int = 30, deals_fn=None) -> List[Dict[str, Any]]:
    """Full history rows for the UI — MT5 fields + AI correlation + learning."""
    deals = fetch_deals(days, deals_fn=deals_fn)
    trips = round_trips_from_deals(deals)
    preds = _load_predictions()
    rows = []
    for trip in trips:
        pred_entry = _prediction_at_time(preds, trip.get("entry_time", 0))
        preds_after = (_prediction_after(preds, trip.get("exit_time", 0))
                     if trip.get("closed") and trip.get("exit_time") else [])
        row = {**trip}
        if pred_entry:
            row["ai_lean"] = pred_entry.get("lean")
            row["ai_confidence"] = pred_entry.get("confidence")
            row["ai_p_up"] = pred_entry.get("p_up")
            row["ai_vote"] = pred_entry.get("vote_score_input")
        else:
            row["ai_lean"] = None
        if trip.get("lost"):
            row["learning"] = _learning_for_loss(trip, pred_entry, preds_after)
        else:
            row["learning"] = None
        rows.append(row)
    return rows


def save_outcome_snapshot(rows: List[Dict[str, Any]]) -> None:
    """Persist closed trade snapshots (deduped by position_id)."""
    try:
        seen = set()
        existing = []
        path = _outcomes_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            existing.append(json.loads(line))
                        except Exception:
                            pass
        for r in existing:
            seen.add(r.get("position_id"))
        with open(path, "a", encoding="utf-8") as f:
            for r in rows:
                if not r.get("closed") or r.get("position_id") in seen:
                    continue
                seen.add(r.get("position_id"))
                f.write(json.dumps({
                    "saved_at": time.time(),
                    "position_id": r["position_id"],
                    "entry_time": r.get("entry_time_str"),
                    "exit_time": r.get("exit_time_str"),
                    "entry_price": r.get("entry_price"),
                    "exit_price": r.get("exit_price"),
                    "net_profit": r.get("net_profit"),
                    "learning": r.get("learning"),
                }) + "\n")
    except Exception:
        pass
