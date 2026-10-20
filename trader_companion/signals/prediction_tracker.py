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
MIN_LIVE_GATE_SAMPLES = 15        # do not alter live signals before this evidence
TRADE_ENTRY_KEEP_DAYS = 21        # how long a trade entry waits for its outcome
DECISION_BUCKET_SEC = 1800        # trades of one plan inside this window = one decision

_records: Dict[str, List[Dict[str, Any]]] = {}
_entries: Dict[str, Dict[str, Dict[str, Any]]] = {}
_entries_loaded: set = set()
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
           vote_score_input: Optional[float] = None,
           trend_direction: Optional[str] = None) -> bool:
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
            "trend_direction": (trend_direction or "").strip().lower() or None,
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
    cutoff = pred_ts + MAX_EVAL_WINDOW_MIN * 60
    if int(bars[0][0]) > cutoff:
        rec["expired"] = True
        rec["expired_at"] = time.time()
        return False
    horizon_bar = next((r for r in bars
                        if pred_ts + horizon_sec <= int(r[0]) <= cutoff), None)
    if horizon_bar is None:
        return False
    entry = rec["price"]
    sign = 1.0 if rec["lean"] == "buy" else -1.0
    tp_level = entry + sign * rec["tp_points"]
    sl_level = entry - sign * rec["sl_points"]

    # Move over the horizon (closest bar at/after pred_ts + horizon)
    move = float(horizon_bar[4]) - entry

    # TP/SL first-touch walk + MFE/MAE (within the capped window)
    outcome = "none"
    outcome_min = None
    mfe = 0.0   # max favorable excursion (signed by lean)
    mae = 0.0   # max adverse excursion
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
                   if not r.get("verified") and not r.get("expired")
                   and time.time() - r["ts"] >= r["horizon_min"] * 60]
        if not pending:
            return 0
        if rates is None:
            rates = _fetch_m1_since(symbol, int(min(r["ts"] for r in pending)) - 60)
        if rates is None or len(rates) == 0:
            return 0
        n = 0
        changed = False
        for rec in pending:
            if _verify_one(rec, rates):
                n += 1
                changed = True
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
            elif rec.get("expired"):
                changed = True
        if changed:
            _save(symbol)
        return n


def ingest_simulation(symbol: str, *, entry_ts: int, price: float, lean: str,
                      tp_points: float, sl_points: float,
                      outcome: str, outcome_min: Optional[int],
                      mfe_points: float, mae_points: float) -> None:
    """Add a paper-trade simulation outcome directly as verified training data.

    Simulated samples are tagged ``simulated=True`` — they may inform regime
    analysis, but are excluded from the live confidence gate.
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


def trade_edge_score(won: bool, tp_points: float, sl_points: float) -> float:
    """Direction-skill credit in [0, 1] for one real trade; 0.5 = coin flip.

    A raw win rate is not directional accuracy: a 3:1 setup loses 75% of the
    time on a coin flip, a 0.5:1 setup wins 67%. Each result is compared with
    its own random-walk baseline p = sl / (tp + sl) and scaled so a coin flip
    scores 0.5 on average whatever the TP/SL geometry.
    """
    total = float(tp_points) + float(sl_points)
    p = float(sl_points) / total if total > 0 else 0.5
    m = max(p, 1.0 - p)
    score = 0.5 + 0.5 * ((1.0 if won else 0.0) - p) / m
    return round(min(1.0, max(0.0, score)), 4)


def _entries_path(symbol: str) -> str:
    return os.path.join(os.path.dirname(_journal_path(symbol)),
                        f"ml_trade_entries_{symbol.lower()}.json")


def _load_entries(symbol: str) -> Dict[str, Dict[str, Any]]:
    key = symbol.lower()
    if key in _entries_loaded:
        return _entries.setdefault(key, {})
    _entries_loaded.add(key)
    data: Dict[str, Dict[str, Any]] = {}
    try:
        with open(_entries_path(symbol), "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data = loaded
    except Exception:
        pass
    _entries[key] = data
    return data


def _save_entries(symbol: str) -> None:
    key = symbol.lower()
    entries = _entries.get(key, {})
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - TRADE_ENTRY_KEEP_DAYS * 86400))
    for k in [k for k, e in entries.items() if str(e.get("entry_date") or "") < cutoff]:
        del entries[k]
    path = _entries_path(symbol)
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(entries, f)
        os.replace(temp_path, path)
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass


def _trade_key(account: Any, entry_date: Any) -> str:
    return f"{str(account or '').strip().lower()}|{str(entry_date or '').strip()}"


def record_trade_entry(symbol: str, *, account: str, entry_date: str, side: str,
                       entry_ts: float, confidence: Optional[float],
                       p_up: Optional[float], tp_points: float, sl_points: float,
                       trend_direction: Optional[str] = None,
                       signal_direction: Optional[str] = None,
                       signal_source: Optional[str] = None) -> bool:
    """Remember a real trade's decision so its dashboard outcome can teach the model.

    Only trades that actually followed the local ML signal are kept: a side
    forced by a lock or a random fallback says nothing about the model.
    """
    side = str(side or "").lower()
    if side not in ("buy", "sell"):
        return False
    if str(signal_source or "") != "local_ml" or str(signal_direction or "").lower() != side:
        return False
    try:
        tp_points, sl_points = float(tp_points), float(sl_points)
    except (TypeError, ValueError):
        return False
    if tp_points <= 0 or sl_points <= 0 or not account or not entry_date:
        return False
    key = _trade_key(account, entry_date)
    with _lock:
        entries = _load_entries(symbol)
        existing = entries.get(key)
        if existing and int(existing.get("entry_ts") or 0) == int(entry_ts):
            return False  # a retried ledger push re-sends the same entry
        entries[key] = {
            "entry_date": str(entry_date), "entry_ts": float(entry_ts), "side": side,
            "confidence": float(confidence) if confidence is not None else 0.6,
            "p_up": float(p_up) if p_up is not None else (0.6 if side == "buy" else 0.4),
            "tp_points": tp_points, "sl_points": sl_points,
            "trend_direction": (trend_direction or "").strip().lower() or None,
        }
        _save_entries(symbol)
    return True


def ingest_trade_outcome(symbol: str, *, account: str, entry_date: str, outcome: str,
                         net_pnl: Optional[float] = None) -> bool:
    """Learn from a real trade result reported by the dashboard (tp / sl / breach).

    Becomes a verified live sample, so the trend-vs-reversal blend weights adapt
    to what the real accounts actually earned. Returns True when a new sample
    was added.
    """
    outcome = str(outcome or "").strip().lower()
    if outcome not in ("tp", "sl", "breach"):
        return False
    key = _trade_key(account, entry_date)
    won = outcome == "tp"
    with _lock:
        entry = _load_entries(symbol).get(key)
        if not entry or entry.get("learned"):
            return False
        side = entry["side"]
        tp, sl = float(entry["tp_points"]), float(entry["sl_points"])
        # Accounts on one plan trade the same signal at nearly the same time:
        # count one decision, not one per account.
        decision_key = (f"{entry['entry_date']}|{side}|{round(tp, 2)}|{round(sl, 2)}|"
                        f"{int(entry['entry_ts']) // DECISION_BUCKET_SEC}")
        _load(symbol)
        recs = _records.setdefault(symbol.lower(), [])
        entry["learned"] = True
        if any(r.get("decision_key") == decision_key for r in recs[-500:]):
            _save_entries(symbol)
            return False
        sign = 1.0 if side == "buy" else -1.0
        signed = tp if won else -sl
        recs.append({
            "ts": time.time(), "bar_time": int(entry["entry_ts"]), "symbol": symbol.lower(),
            "price": 0.0, "p_up": entry["p_up"], "confidence": entry["confidence"],
            "lean": side, "direction": side, "tp_points": tp, "sl_points": sl,
            "horizon_min": DEFAULT_HORIZON_MIN, "verified": True, "verified_at": time.time(),
            "simulated": False, "source": "trade", "decision_key": decision_key,
            "trend_direction": entry.get("trend_direction"),
            "outcome": "tp" if won else "sl", "breach": outcome == "breach",
            "correct": won, "edge_score": trade_edge_score(won, tp, sl),
            "signed_move": signed, "move_points": signed * sign, "net_pnl": net_pnl,
            # Lower bounds only: the real excursions are not reported.
            "mfe_points": tp if won else 0.0, "mae_points": 0.0 if won else sl,
        })
        del recs[:-MAX_RECORDS]
        _save(symbol)
        _save_entries(symbol)
    return True


def get_trade_stats(symbol: str = "ustech", window: int = 100) -> Dict[str, Any]:
    """Real-trade scorecard: win rate vs the random-walk expectation (the edge)."""
    with _lock:
        _load(symbol)
        trades = [r for r in _records.get(symbol.lower(), [])
                  if r.get("source") == "trade" and r.get("verified")][-window:]
    n = len(trades)
    if not n:
        return {"n": 0}
    wins = sum(1 for r in trades if r.get("correct"))
    expected = sum(r["sl_points"] / (r["sl_points"] + r["tp_points"]) for r in trades) / n
    return {
        "n": n, "wins": wins, "losses": n - wins,
        "breaches": sum(1 for r in trades if r.get("breach")),
        "win_rate": round(wins / n, 3), "expected_win_rate": round(expected, 3),
        "edge": round(wins / n - expected, 3),
        "avg_score": round(sum(r.get("edge_score", 0.5) for r in trades) / n, 3),
    }


def get_stats(symbol: str = "ustech", window: int = STATS_WINDOW,
              live_only: bool = False) -> Dict[str, Any]:
    """Rolling stats over the most recent verified predictions."""
    key = symbol.lower()
    with _lock:
        _load(symbol)
        # Real trade results are edge-scored in get_trade_stats; their raw win
        # rate depends on TP/SL geometry, so it must not skew direction accuracy.
        verified = [r for r in _records.get(key, [])
                    if r.get("verified") and r.get("source") != "trade"]
    live = [r for r in verified if not r.get("simulated")]
    sim = [r for r in verified if r.get("simulated")]
    # Simulations can help reports, but must not control live trading behavior.
    if live_only:
        pool = live
    elif len(live) >= 10:
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


# Default blend when the journal has not split trend vs reversal yet.
DEFAULT_W_TREND = 0.65
DEFAULT_W_REVERSAL = 0.35
REGIME_MIN_SAMPLES = 5


def get_regime_blend_weights(symbol: str = "ustech",
                             window: int = STATS_WINDOW) -> Dict[str, Any]:
    """Learning equation — adaptive weights for trend vs reversal legs.

    Uses Laplace-smoothed accuracy of verified predictions that were
    *aligned* with the prevailing trend vs those that were *counter-trend*.
    When the two legs disagree at decision time, the historically stronger
    regime receives extra weight until the blend converges.
    """
    key = symbol.lower()
    with _lock:
        _load(symbol)
        verified = [r for r in _records.get(key, []) if r.get("verified")]
    live = [r for r in verified if not r.get("simulated")]
    sim = [r for r in verified if r.get("simulated")]
    pool = live if len(live) >= 10 else live + sim
    recent = pool[-window:]

    aligned = [r for r in recent
               if r.get("trend_direction") in ("buy", "sell")
               and r.get("lean") == r["trend_direction"]]
    reversal = [r for r in recent
                if r.get("trend_direction") in ("buy", "sell")
                and r.get("lean") in ("buy", "sell")
                and r["lean"] != r["trend_direction"]]

    n_a, n_r = len(aligned), len(reversal)
    correct_a = sum(_accuracy_credit(r) for r in aligned)
    correct_r = sum(_accuracy_credit(r) for r in reversal)

    # Beta(2,2) Laplace smoothing — stable with small samples
    trend_acc = (correct_a + 2) / (n_a + 4) if n_a else 0.5
    reversal_acc = (correct_r + 2) / (n_r + 4) if n_r else 0.5

    if n_a + n_r < REGIME_MIN_SAMPLES:
        w_trend = DEFAULT_W_TREND
        w_reversal = DEFAULT_W_REVERSAL
        source = "default"
    else:
        total = trend_acc + reversal_acc
        w_trend = trend_acc / total if total > 0 else DEFAULT_W_TREND
        w_reversal = 1.0 - w_trend
        source = "learned"

    return {
        "w_trend": round(w_trend, 4),
        "w_reversal": round(w_reversal, 4),
        "trend_acc": round(trend_acc, 3),
        "reversal_acc": round(reversal_acc, 3),
        "n_trend": n_a,
        "n_reversal": n_r,
        "n_trade_outcomes": sum(1 for r in recent if r.get("source") == "trade"),
        "source": source,
    }


def _accuracy_credit(rec: Dict[str, Any]) -> float:
    """1/0 for a verified prediction; the edge score for a real trade result."""
    if rec.get("source") == "trade" and rec.get("edge_score") is not None:
        return float(rec["edge_score"])
    return 1.0 if rec.get("correct") else 0.0


def effective_confidence_threshold(base: float, symbol: str = "ustech") -> float:
    """Adaptive gate — the feedback loop from verified outcomes to behavior.

    Poor recent live accuracy → demand MORE confidence before acting.
    Strong live accuracy → relax slightly toward the base. Simulations are
    deliberately excluded from this live-trading control.
    """
    s = get_stats(symbol, live_only=True)
    n = s.get("n_verified", 0)
    acc = s.get("accuracy")
    if n < MIN_LIVE_GATE_SAMPLES or acc is None:
        return base
    if acc < 0.45:
        return min(base + 0.10, 0.80)
    if acc < 0.55:
        return min(base + 0.05, 0.80)
    if acc > 0.65:
        return max(base - 0.03, 0.55)
    return base
