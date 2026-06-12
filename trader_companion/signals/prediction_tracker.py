"""Self-learning prediction journal for the ML/DL direction engine.

Every prediction the model makes is recorded (price, probability, lean).
Once the prediction horizon has passed, it is verified against what the
market ACTUALLY did:

  * distance moved since the prediction (points, signed by the lean)
  * was the direction correct?
  * TP/SL simulation — from the prediction price, which level would an
    active trade have hit FIRST (bar-by-bar high/low walk)?
  * MFE / MAE — max favorable / adverse excursion over the window

The rolling verified stats then feed BACK into the model's behavior via an
adaptive confidence gate: when recent live accuracy degrades the model must
be more confident before it acts; when live accuracy is strong the gate
relaxes toward its base. This is the model learning from its own scorecard
— not just from historical bars.

Storage: JSONL next to the model cache (survives restarts).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

# USTECH on Tradovate: tick = 0.25 points. Blueprint TPs are ~150-250 ticks,
# SLs ~100 ticks → defaults below mirror a typical active trade.
DEFAULT_TP_POINTS = 250 * 0.25   # 62.5 pts
DEFAULT_SL_POINTS = 100 * 0.25   # 25.0 pts
DEFAULT_HORIZON_MIN = 20         # matches ml_direction HORIZON_BARS (4 x M5)
MAX_EVAL_WINDOW_MIN = 240        # stop looking for TP/SL after 4 hours
MAX_RECORDS = 2000               # journal cap (memory + disk)
STATS_WINDOW = 40                # adaptive gate looks at the last N verified

_records: Dict[str, List[Dict[str, Any]]] = {}
_lock = threading.Lock()
_loaded: set = set()


def _journal_path(symbol: str) -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, f"ml_prediction_journal_{symbol.lower()}.jsonl")


def _load(symbol: str) -> None:
    key = symbol.lower()
    if key in _loaded:
        return
    _loaded.add(key)
    recs: List[Dict[str, Any]] = []
    try:
        path = _journal_path(symbol)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            recs.append(json.loads(line))
                        except Exception:
                            pass
    except Exception:
        pass
    _records[key] = recs[-MAX_RECORDS:]


def _save(symbol: str) -> None:
    key = symbol.lower()
    try:
        with open(_journal_path(symbol), "w", encoding="utf-8") as f:
            for r in _records.get(key, [])[-MAX_RECORDS:]:
                f.write(json.dumps(r) + "\n")
    except Exception:
        pass  # journal is best-effort


def record(symbol: str, *, bar_time: int, price: float, p_up: float,
           confidence: float, lean: str, direction: str,
           tp_points: float = DEFAULT_TP_POINTS,
           sl_points: float = DEFAULT_SL_POINTS,
           horizon_min: int = DEFAULT_HORIZON_MIN,
           vote_score_input: Optional[float] = None) -> bool:
    """Journal one prediction. Deduped per closed bar — repeat calls on the
    same bar (e.g. the 60s diagnostics probe) are ignored."""
    key = symbol.lower()
    with _lock:
        _load(symbol)
        recs = _records.setdefault(key, [])
        if any(r.get("bar_time") == bar_time for r in recs[-50:]):
            return False
        recs.append({
            "ts": time.time(),
            "bar_time": int(bar_time),
            "symbol": key,
            "price": float(price),
            "p_up": float(p_up),
            "confidence": float(confidence),
            "lean": lean,
            "direction": direction,        # may be "neutral" when gated
            "tp_points": float(tp_points),
            "sl_points": float(sl_points),
            "horizon_min": int(horizon_min),
            "vote_score_input": vote_score_input,
            "verified": False,
        })
        del recs[:-MAX_RECORDS]
        _save(symbol)
    return True


def _fetch_m1_since(symbol: str, since_epoch: int):
    if not MT5_AVAILABLE:
        return None
    try:
        for cand in (symbol, symbol.upper(), symbol.lower(), symbol.capitalize()):
            if mt5.symbol_info(cand) is not None:
                symbol = cand
                break
        need = int((time.time() - since_epoch) / 60) + 10
        return mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, min(need, 20000))
    except Exception:
        return None


def _verify_one(rec: Dict[str, Any], rates) -> bool:
    """Fill verification fields from M1 bars. Returns True when verified."""
    pred_ts = rec["ts"]
    horizon_sec = rec["horizon_min"] * 60
    if time.time() - pred_ts < horizon_sec:
        return False  # too early
    bars = [r for r in rates if int(r[0]) >= int(pred_ts)] if rates is not None else []
    if not bars:
        return False
    entry = rec["price"]
    sign = 1.0 if rec["lean"] == "buy" else -1.0
    tp_level = entry + sign * rec["tp_points"]
    sl_level = entry - sign * rec["sl_points"]

    # Move over the horizon (closest bar at/after pred_ts + horizon)
    move = None
    for r in bars:
        if int(r[0]) >= pred_ts + horizon_sec:
            move = float(r[4]) - entry
            break
    if move is None:
        move = float(bars[-1][4]) - entry  # window not fully elapsed in data

    # TP/SL first-touch walk + MFE/MAE (within the capped window)
    outcome = "none"
    outcome_min = None
    mfe = 0.0   # max favorable excursion (signed by lean)
    mae = 0.0   # max adverse excursion
    cutoff = pred_ts + MAX_EVAL_WINDOW_MIN * 60
    for r in bars:
        t, high, low = int(r[0]), float(r[2]), float(r[3])
        if t > cutoff:
            break
        fav = (high - entry) if sign > 0 else (entry - low)
        adv = (entry - low) if sign > 0 else (high - entry)
        mfe = max(mfe, fav)
        mae = max(mae, adv)
        hit_tp = high >= tp_level if sign > 0 else low <= tp_level
        hit_sl = low <= sl_level if sign > 0 else high >= sl_level
        if hit_tp or hit_sl:
            # both pierced in one bar → conservative: count the stop
            outcome = "sl" if hit_sl else "tp"
            outcome_min = int((t - pred_ts) / 60)
            break

    rec["verified"] = True
    rec["verified_at"] = time.time()
    rec["move_points"] = round(move, 2)
    rec["signed_move"] = round(sign * move, 2)   # >0 → market followed the lean
    rec["correct"] = bool(sign * move > 0)
    rec["outcome"] = outcome                      # tp / sl / none(yet)
    rec["outcome_min"] = outcome_min
    rec["mfe_points"] = round(mfe, 2)
    rec["mae_points"] = round(mae, 2)
    return True


def verify_pending(symbol: str = "ustech",
                   rates=None,
                   log_fn: Optional[Callable[[str], None]] = None) -> int:
    """Verify every prediction whose horizon has elapsed. Returns count."""
    key = symbol.lower()
    with _lock:
        _load(symbol)
        pending = [r for r in _records.get(key, [])
                   if not r.get("verified")
                   and time.time() - r["ts"] >= r["horizon_min"] * 60]
        if not pending:
            return 0
        if rates is None:
            rates = _fetch_m1_since(symbol, int(min(r["ts"] for r in pending)) - 60)
        if rates is None or len(rates) == 0:
            return 0
        n = 0
        for rec in pending:
            if _verify_one(rec, rates):
                n += 1
                if log_fn:
                    try:
                        mark = ("market FOLLOWED the prediction" if rec["correct"]
                                else "market went AGAINST the prediction")
                        oc = {"tp": f"TP hit in {rec['outcome_min']}min",
                              "sl": f"SL hit in {rec['outcome_min']}min",
                              "none": "neither TP nor SL hit"}[rec["outcome"]]
                        log_fn(f"verified {rec['lean'].upper()} p={rec['p_up']:.2f} "
                               f"@ {rec['price']:.2f} -> moved {rec['signed_move']:+.1f}pts "
                               f"in {rec['horizon_min']}min ({mark}) | trade sim: {oc} "
                               f"| MFE +{rec['mfe_points']:.1f} MAE -{rec['mae_points']:.1f}")
                    except Exception:
                        pass
        if n:
            _save(symbol)
        return n


def ingest_simulation(symbol: str, *, entry_ts: int, price: float, lean: str,
                      tp_points: float, sl_points: float,
                      outcome: str, outcome_min: Optional[int],
                      mfe_points: float, mae_points: float) -> None:
    """Add a paper-trade simulation outcome directly as verified training data.

    Simulated samples are tagged ``simulated=True`` — the adaptive gate blends
    them with live outcomes when live evidence is thin (<20 verified).
    """
    key = symbol.lower()
    sign = 1.0 if lean == "buy" else -1.0
    correct = outcome == "tp"
    signed_move = tp_points if outcome == "tp" else (-sl_points if outcome == "sl" else 0.0)
    with _lock:
        _load(symbol)
        recs = _records.setdefault(key, [])
        # dedupe — same slot/direction/levels not recorded twice
        sig = (int(entry_ts), lean, round(tp_points, 2), round(sl_points, 2))
        for r in recs[-200:]:
            if r.get("simulated") and (
                int(r.get("bar_time", 0)), r.get("lean"),
                round(float(r.get("tp_points", 0)), 2),
                round(float(r.get("sl_points", 0)), 2),
            ) == sig:
                return
        recs.append({
            "ts": float(entry_ts),
            "bar_time": int(entry_ts),
            "symbol": key,
            "price": float(price),
            "p_up": 0.6 if lean == "buy" else 0.4,
            "confidence": 0.6,
            "lean": lean,
            "direction": lean,
            "tp_points": float(tp_points),
            "sl_points": float(sl_points),
            "horizon_min": int(outcome_min or 20),
            "verified": True,
            "verified_at": time.time(),
            "simulated": True,
            "move_points": signed_move * sign,
            "signed_move": signed_move * sign,
            "correct": correct,
            "outcome": outcome,
            "outcome_min": outcome_min,
            "mfe_points": float(mfe_points),
            "mae_points": float(mae_points),
        })
        del recs[:-MAX_RECORDS]
        _save(symbol)


def get_stats(symbol: str = "ustech", window: int = STATS_WINDOW) -> Dict[str, Any]:
    """Rolling stats over the most recent verified predictions."""
    key = symbol.lower()
    with _lock:
        _load(symbol)
        verified = [r for r in _records.get(key, []) if r.get("verified")]
    live = [r for r in verified if not r.get("simulated")]
    sim = [r for r in verified if r.get("simulated")]
    # Prefer live; backfill with simulations when live evidence is thin
    if len(live) >= 10:
        pool = live
    else:
        pool = live + sim
    recent = pool[-window:]
    if not recent:
        return {"n_verified": 0}
    n = len(recent)
    n_live = sum(1 for r in recent if not r.get("simulated"))
    n_sim = n - n_live
    correct = sum(1 for r in recent if r["correct"])
    tp = sum(1 for r in recent if r["outcome"] == "tp")
    sl = sum(1 for r in recent if r["outcome"] == "sl")
    acted = [r for r in recent if r.get("direction") in ("buy", "sell")]
    return {
        "n_verified": n,
        "n_live": n_live,
        "n_simulated": n_sim,
        "n_total_verified": len(verified),
        "accuracy": round(correct / n, 3),
        "acted_accuracy": (round(sum(1 for r in acted if r["correct"]) / len(acted), 3)
                           if acted else None),
        "tp_hits": tp,
        "sl_hits": sl,
        "no_hit": n - tp - sl,
        "avg_signed_move": round(sum(r["signed_move"] for r in recent) / n, 2),
        "avg_mfe": round(sum(r["mfe_points"] for r in recent) / n, 2),
        "avg_mae": round(sum(r["mae_points"] for r in recent) / n, 2),
    }


def effective_confidence_threshold(base: float, symbol: str = "ustech") -> float:
    """Adaptive gate — the feedback loop from verified outcomes to behavior.

    Poor recent live accuracy → demand MORE confidence before acting.
    Strong live accuracy → relax slightly toward the base. Uses live
    outcomes when available; blends in paper simulations when live count
    is still building (<10 verified live samples).
    """
    s = get_stats(symbol)
    n = s.get("n_verified", 0)
    acc = s.get("accuracy")
    if n < 15 or acc is None:
        return base
    if acc < 0.45:
        return min(base + 0.10, 0.80)
    if acc < 0.55:
        return min(base + 0.05, 0.80)
    if acc > 0.65:
        return max(base - 0.03, 0.55)
    return base
