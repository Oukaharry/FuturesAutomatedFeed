"""Paper-trade simulator for TOMORROW's queued trades.

Reads day placeholders (MON/TUE/…) on loaded dashboard rows, resolves each
account's blueprint TP/SL, then replays entries every N minutes on TODAY's
M1 bars using those exact distances.  Runs even when no live trades were
taken — the goal is to learn timing and phase fit before tomorrow's session.

Outputs:
  * per-slot TP/SL outcomes (duration, MFE/MAE)
  * ranked tomorrow plans (best phases / accounts / entry windows)
  * journal persisted to disk for the adaptive ML gate

USTECH tick = 0.25 index points.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

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
        try:
            import prediction_tracker
        except ImportError:
            prediction_tracker = None

TICK_POINT = 0.25
DEFAULT_TP_POINTS = 250 * TICK_POINT   # 62.5 pts — typical CH blueprint
DEFAULT_SL_POINTS = 100 * TICK_POINT   # 25.0 pts
SIM_INTERVAL_MIN = 15          # replay an entry every 15 minutes
MAX_WALK_MIN = 240             # stop TP/SL walk after 4 hours
MAX_JOURNAL = 3000
# Prefer real tick history (MT5 Strategy Tester style) over M1 OHLC when available.
USE_TICK_WALK = True
MAX_TICKS_PER_FETCH = 750_000
KENYA_TZ = timezone(timedelta(hours=3))
# MT5 encodes broker server wall clock in Unix fields — format with utcfromtimestamp
# (see research/mt5_time.py). Kenya EAT is kept for calendar "tomorrow" only.
SIM_HISTORY_MAX_AGE_SEC = 3 * 86400
MT5_SYMBOL_CANDIDATES = ("ustech", "USTECH", "US100", "NAS100", "USTEC")

# Small moves → trades should resolve quickly; scale max wait from TP distance
MIN_EXPECTED_MIN = 15
MAX_EXPECTED_CAP = 120

_journal: List[Dict[str, Any]] = []
_last_brief: Dict[str, Any] = {}
_lock = threading.Lock()
_loaded = False


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _journal_path() -> str:
    return os.path.join(_base_dir(), "trade_sim_journal.jsonl")


def _load_journal() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        path = _journal_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            _journal.append(json.loads(line))
                        except Exception:
                            pass
    except Exception:
        pass
    del _journal[:-MAX_JOURNAL]


def _save_journal() -> None:
    try:
        with open(_journal_path(), "w", encoding="utf-8") as f:
            for r in _journal[-MAX_JOURNAL:]:
                f.write(json.dumps(r) + "\n")
    except Exception:
        pass


def kenya_today() -> date:
    return datetime.now(KENYA_TZ).date()


def tomorrow_weekday() -> int:
    return (kenya_today() + timedelta(days=1)).weekday()


def ticks_to_points(ticks: int) -> float:
    return float(ticks) * TICK_POINT


def expected_duration_min(tp_pts: float, sl_pts: float) -> int:
    """How long a trade *should* take given modest USTECH moves.

    Tight challenge legs resolve faster; wide payout TPs get more time but
    are capped — if TP hasn't hit by then the setup is too slow for the move.
    """
    est = int(tp_pts / 0.75 + sl_pts / 2.0)
    return max(MIN_EXPECTED_MIN, min(MAX_EXPECTED_CAP, est))


def _tick_entry_price(tick, direction: str) -> float:
    """MT5 fill: BUY at ask, SELL at bid."""
    bid = float(tick["bid"])
    ask = float(tick["ask"])
    if direction == "buy":
        return ask if ask > 0 else bid
    return bid if bid > 0 else ask


def _tick_exit_price(tick, direction: str) -> float:
    """MT5 close check: long watched on bid, short on ask."""
    bid = float(tick["bid"])
    ask = float(tick["ask"])
    if direction == "buy":
        return bid if bid > 0 else ask
    return ask if ask > 0 else bid


def _tick_sort_key(tick) -> Tuple[int, int]:
    t = int(tick["time"])
    msc = int(tick["time_msc"]) if "time_msc" in tick.dtype.names else 0
    return t, msc


def fetch_ticks(symbol: str, from_ts: int, to_ts: int):
    """MT5 tick history for [from_ts, to_ts] in server-wall time."""
    if not USE_TICK_WALK or not MT5_AVAILABLE:
        return None
    sym = _resolve_symbol(symbol)
    if not sym or to_ts <= from_ts:
        return None
    dt_from = _mt5_wall_dt(from_ts)
    dt_to = _mt5_wall_dt(to_ts + 1)
    try:
        for flag in (mt5.COPY_TICKS_ALL, mt5.COPY_TICKS_INFO):
            ticks = mt5.copy_ticks_range(sym, dt_from, dt_to, flag)
            if ticks is not None and len(ticks):
                if len(ticks) > MAX_TICKS_PER_FETCH:
                    ticks = ticks[-MAX_TICKS_PER_FETCH:]
                return ticks
    except Exception:
        pass
    return None


def entry_fill_from_ticks(ticks, entry_ts: int, direction: str,
                          fallback_price: float) -> Tuple[int, float]:
    """First tick at/after entry_ts — ask for buy, bid for sell."""
    if ticks is None or len(ticks) == 0:
        return entry_ts, fallback_price
    ordered = sorted(ticks, key=_tick_sort_key)
    for tick in ordered:
        t = int(tick["time"])
        if t < entry_ts:
            continue
        px = _tick_entry_price(tick, direction)
        if px > 0:
            return t, px
    return entry_ts, fallback_price


def walk_tp_sl_ticks(entry_ts: int, entry_price: float, direction: str,
                     tp_pts: float, sl_pts: float, ticks) -> Dict[str, Any]:
    """Tick-by-tick TP/SL (MT5 tester: bid/ask side matches position direction)."""
    sign = 1.0 if direction == "buy" else -1.0
    tp_level = entry_price + sign * tp_pts
    sl_level = entry_price - sign * sl_pts
    cutoff = entry_ts + MAX_WALK_MIN * 60
    mfe = mae = 0.0
    outcome = "none"
    outcome_min = None
    exit_ts = None
    exit_price = None
    if ticks is None or len(ticks) == 0:
        return {
            "outcome": outcome,
            "outcome_min": outcome_min,
            "exit_ts": exit_ts,
            "exit_price": None,
            "tp_level": round(tp_level, 2),
            "sl_level": round(sl_level, 2),
            "mfe_points": 0.0,
            "mae_points": 0.0,
            "walk_mode": "ticks",
        }
    last_px = entry_price
    for tick in sorted(ticks, key=_tick_sort_key):
        t = int(tick["time"])
        if t < entry_ts:
            continue
        if t > cutoff:
            break
        px = _tick_exit_price(tick, direction)
        if px <= 0:
            continue
        last_px = px
        fav = (px - entry_price) if sign > 0 else (entry_price - px)
        adv = (entry_price - px) if sign > 0 else (px - entry_price)
        mfe = max(mfe, fav)
        mae = max(mae, adv)
        hit_tp = px >= tp_level if sign > 0 else px <= tp_level
        hit_sl = px <= sl_level if sign > 0 else px >= sl_level
        if hit_tp or hit_sl:
            if hit_tp and hit_sl:
                outcome = "sl"  # same-tick ambiguity: conservative like M1 bar walk
                exit_price = sl_level
            elif hit_sl:
                outcome = "sl"
                exit_price = sl_level
            else:
                outcome = "tp"
                exit_price = tp_level
            outcome_min = max(1, int((t - entry_ts) / 60))
            exit_ts = t
            break
    if outcome == "none" and last_px != entry_price:
        # still open within window
        pass
    return {
        "outcome": outcome,
        "outcome_min": outcome_min,
        "exit_ts": exit_ts,
        "exit_price": round(exit_price, 2) if exit_price is not None else None,
        "tp_level": round(tp_level, 2),
        "sl_level": round(sl_level, 2),
        "mfe_points": round(mfe, 2),
        "mae_points": round(mae, 2),
        "walk_mode": "ticks",
    }


def walk_tp_sl(entry_ts: int, entry_price: float, direction: str,
               tp_pts: float, sl_pts: float,
               m1_bars, ticks=None, symbol: Optional[str] = None) -> Dict[str, Any]:
    """TP/SL walk — ticks when available (MT5 tester style), else M1 OHLC."""
    if USE_TICK_WALK:
        if ticks is None and symbol and MT5_AVAILABLE:
            ticks = fetch_ticks(symbol, entry_ts, entry_ts + MAX_WALK_MIN * 60)
        if ticks is not None and len(ticks):
            return walk_tp_sl_ticks(entry_ts, entry_price, direction, tp_pts, sl_pts, ticks)
    return _walk_tp_sl_m1(entry_ts, entry_price, direction, tp_pts, sl_pts, m1_bars)


def _walk_tp_sl_m1(entry_ts: int, entry_price: float, direction: str,
                   tp_pts: float, sl_pts: float,
                   m1_bars) -> Dict[str, Any]:
    """Bar-by-bar TP/SL first-touch from entry_ts forward (M1 fallback)."""
    sign = 1.0 if direction == "buy" else -1.0
    tp_level = entry_price + sign * tp_pts
    sl_level = entry_price - sign * sl_pts
    cutoff = entry_ts + MAX_WALK_MIN * 60
    mfe = mae = 0.0
    outcome = "none"
    outcome_min = None
    exit_ts = None
    exit_price = None
    bars = [r for r in m1_bars if int(r[0]) >= entry_ts]
    for r in bars:
        t, high, low = int(r[0]), float(r[2]), float(r[3])
        if t > cutoff:
            break
        fav = (high - entry_price) if sign > 0 else (entry_price - low)
        adv = (entry_price - low) if sign > 0 else (high - entry_price)
        mfe = max(mfe, fav)
        mae = max(mae, adv)
        hit_tp = high >= tp_level if sign > 0 else low <= tp_level
        hit_sl = low <= sl_level if sign > 0 else high >= sl_level
        if hit_tp or hit_sl:
            outcome = "sl" if hit_sl else "tp"
            outcome_min = max(1, int((t - entry_ts) / 60))
            exit_ts = t
            exit_price = sl_level if hit_sl else tp_level
            break
    return {
        "outcome": outcome,
        "outcome_min": outcome_min,
        "exit_ts": exit_ts,
        "exit_price": round(exit_price, 2) if exit_price is not None else None,
        "tp_level": round(tp_level, 2),
        "sl_level": round(sl_level, 2),
        "mfe_points": round(mfe, 2),
        "mae_points": round(mae, 2),
        "walk_mode": "m1",
    }


def _ema_last(closes: List[float], period: int) -> float:
    if not closes:
        return 0.0
    k = 2.0 / (period + 1.0)
    ema = closes[0]
    for v in closes[1:]:
        ema = v * k + ema * (1.0 - k)
    return ema


def trend_at_time(m5_bars, entry_ts: int) -> Optional[str]:
    """EMA21/50 trend from M5 bars closed at or before entry_ts."""
    closed = [r for r in m5_bars if int(r[0]) + 300 <= entry_ts]
    if len(closed) < 55:
        return None
    closes = [float(r[4]) for r in closed[-80:]]
    ema21 = _ema_last(closes, 21)
    ema50 = _ema_last(closes, 50)
    close = closes[-1]
    if ema21 > ema50 and close > ema50:
        return "buy"
    if ema21 < ema50 and close < ema50:
        return "sell"
    return None


def ensure_mt5() -> bool:
    """Ensure the MT5 terminal session is ready for copy_* calls."""
    if not MT5_AVAILABLE:
        return False
    try:
        if mt5.terminal_info():
            return True
        return bool(mt5.initialize())
    except Exception:
        return False


def _resolve_symbol(symbol: str) -> Optional[str]:
    if not MT5_AVAILABLE:
        return None
    ensure_mt5()
    for cand in (symbol, symbol.upper(), symbol.lower(), symbol.capitalize()):
        try:
            info = mt5.symbol_info(cand)
            if info is not None:
                try:
                    mt5.symbol_select(cand, True)
                except Exception:
                    pass
                return cand
        except Exception:
            pass
    return None


def fetch_m1_m5(symbol: str = "ustech", hours: int = 10):
    sym = _resolve_symbol(symbol)
    if not sym:
        return None, None, sym
    m1_n = min(hours * 60 + 30, 20000)
    m5_n = min(hours * 12 + 20, 5000)
    try:
        m1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, m1_n)
        m5 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, m5_n)
        return m1, m5, sym
    except Exception:
        return None, None, sym


def _session_start_ts(hours_back: int = 10, m1_bars=None) -> int:
    """Start of replay window using MT5 server clock."""
    return _mt5_now_ts(m1_bars) - hours_back * 3600


def _simulation_slots(m1_bars, interval_min: int = SIM_INTERVAL_MIN) -> List[Tuple[int, float]]:
    """(entry_ts, entry_price) every interval on today's M1 data."""
    if m1_bars is None or len(m1_bars) < interval_min + 5:
        return []
    start_ts = _session_start_ts(m1_bars=m1_bars)
    now_ts = _mt5_now_ts(m1_bars)
    slots: List[Tuple[int, float]] = []
    # align to interval boundaries
    t = start_ts - (start_ts % (interval_min * 60)) + interval_min * 60
    while t < now_ts - interval_min * 60:
        # price = close of bar at or just before t
        price = None
        for r in m1_bars:
            bt = int(r[0])
            if bt <= t:
                price = float(r[4])
            else:
                break
        if price is not None:
            slots.append((t, price))
        t += interval_min * 60
    return slots


def simulate_plan(plan: Dict[str, Any], m1_bars, m5_bars,
                  interval_min: int = SIM_INTERVAL_MIN,
                  ticks=None, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """Replay one tomorrow blueprint across today's time slots."""
    tp_pts = plan["tp_points"]
    sl_pts = plan["sl_points"]
    max_exp = plan["expected_min"]
    results = []
    for entry_ts, entry_price in _simulation_slots(m1_bars, interval_min):
        direction = trend_at_time(m5_bars, entry_ts)
        if direction is None:
            continue
        fill_ts, fill_px = entry_fill_from_ticks(
            ticks, entry_ts, direction, entry_price)
        walk = walk_tp_sl(
            fill_ts, fill_px, direction, tp_pts, sl_pts, m1_bars,
            ticks=ticks, symbol=symbol)
        slot_h = _mt5_wall_dt(entry_ts).strftime("%H:%M")
        too_slow = (walk["outcome"] == "tp" and walk["outcome_min"] is not None
                    and walk["outcome_min"] > max_exp)
        results.append({
            "plan_id": plan["plan_id"],
            "entry_ts": fill_ts,
            "slot": slot_h,
            "direction": direction,
            "entry_price": fill_px,
            "tp_points": tp_pts,
            "sl_points": sl_pts,
            "expected_min": max_exp,
            "too_slow": too_slow,
            **walk,
        })
    return results


def score_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Rank a plan's simulation — prefer TP hits that resolve quickly."""
    if not results:
        return {"score": 0.0, "n": 0, "tp_rate": 0.0, "sl_rate": 0.0,
                "avg_tp_min": None, "best_slot": None, "best_direction": None}
    n = len(results)
    tp_hits = [r for r in results if r["outcome"] == "tp"]
    sl_hits = [r for r in results if r["outcome"] == "sl"]
    tp_rate = len(tp_hits) / n
    sl_rate = len(sl_hits) / n
    slow_rate = sum(1 for r in tp_hits if r.get("too_slow")) / max(1, len(tp_hits))
    avg_tp_min = (sum(r["outcome_min"] for r in tp_hits if r["outcome_min"])
                  / len(tp_hits)) if tp_hits else None
    # score: reward TP, penalize SL and slow winners
    score = tp_rate * 2.0 - sl_rate * 1.5 - slow_rate * 0.5
    # best entry hour bucket
    by_slot: Dict[str, List[Dict]] = {}
    for r in results:
        by_slot.setdefault(r["slot"][:2], []).append(r)  # hour bucket EAT
    best_hour = None
    best_hour_score = -999.0
    for hour, rs in by_slot.items():
        hr_tp = sum(1 for x in rs if x["outcome"] == "tp") / len(rs)
        if hr_tp > best_hour_score:
            best_hour_score = hr_tp
            best_hour = hour
    # dominant direction among winning slots
    buy_tp = sum(1 for r in tp_hits if r["direction"] == "buy")
    sell_tp = sum(1 for r in tp_hits if r["direction"] == "sell")
    best_dir = "buy" if buy_tp >= sell_tp else "sell"
    return {
        "score": round(score, 3),
        "n": n,
        "tp_rate": round(tp_rate, 3),
        "sl_rate": round(sl_rate, 3),
        "slow_rate": round(slow_rate, 3),
        "avg_tp_min": round(avg_tp_min, 1) if avg_tp_min is not None else None,
        "best_slot": f"{best_hour}:00 MT5" if best_hour else None,
        "best_direction": best_dir,
    }


def run_simulation(plans: List[Dict[str, Any]], symbol: str = "ustech",
                   log_fn: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Simulate all tomorrow plans on today's bars; persist + return brief."""
    global _last_brief
    if not plans:
        brief = {"plans": [], "tomorrow_wd": tomorrow_weekday(), "ran_at": time.time()}
        with _lock:
            _last_brief = brief
        return brief

    m1, m5, sym = fetch_m1_m5(symbol)
    wd_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    twd = tomorrow_weekday()
    if m1 is None or len(m1) < 60:
        queued = [{**p, "score": None, "queued_only": True} for p in plans]
        brief = {
            "plans": queued,
            "top": queued[0] if queued else None,
            "tomorrow": wd_names[twd],
            "tomorrow_wd": twd,
            "error": "connect MT5 to replay today's bars for TP/SL scoring",
            "ran_at": time.time(),
        }
        with _lock:
            _last_brief = brief
        if log_fn:
            log_fn(f"queued {len(plans)} plan(s) for {wd_names[twd]} — "
                   f"connect MT5 to run bar replay")
        return brief

    ranked: List[Dict[str, Any]] = []
    all_records: List[Dict[str, Any]] = []
    run_ts = time.time()
    now_ts = _mt5_now_ts(m1)
    session_ticks = None
    walk_mode = "m1"
    if USE_TICK_WALK:
        session_ticks = fetch_ticks(sym, _session_start_ts(m1_bars=m1), now_ts)
        if session_ticks is not None and len(session_ticks):
            walk_mode = "ticks"

    for plan in plans:
        results = simulate_plan(plan, m1, m5, ticks=session_ticks, symbol=sym)
        stats = score_results(results)
        entry = {
            **plan,
            **stats,
            "simulated_at": run_ts,
        }
        ranked.append(entry)
        for r in results:
            all_records.append({**r, "simulated_at": run_ts, "simulated": True})

    ranked.sort(key=lambda x: x["score"], reverse=True)

    with _lock:
        _load_journal()
        _journal.extend(all_records)
        del _journal[:-MAX_JOURNAL]
        _save_journal()

    # Feed outcomes into the ML learning journal (simulated = verified immediately)
    if prediction_tracker is not None:
        for r in all_records:
            if r.get("outcome") in ("tp", "sl"):
                try:
                    prediction_tracker.ingest_simulation(
                        "ustech",
                        entry_ts=r["entry_ts"],
                        price=r["entry_price"],
                        lean=r["direction"],
                        tp_points=r["tp_points"],
                        sl_points=r["sl_points"],
                        outcome=r["outcome"],
                        outcome_min=r.get("outcome_min"),
                        mfe_points=r.get("mfe_points", 0),
                        mae_points=r.get("mae_points", 0),
                    )
                except Exception:
                    pass

    wd_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    twd = tomorrow_weekday()
    brief = {
        "ran_at": run_ts,
        "tomorrow": wd_names[twd],
        "tomorrow_wd": twd,
        "symbol": sym or symbol,
        "walk_mode": walk_mode,
        "tick_count": len(session_ticks) if session_ticks is not None else 0,
        "slots_per_plan": len(_simulation_slots(m1)),
        "plans": ranked,
        "top": ranked[0] if ranked else None,
    }
    with _lock:
        _last_brief = brief

    if log_fn and ranked:
        top = ranked[0]
        log_fn(
            f"tomorrow ({wd_names[twd]}): {len(ranked)} plan(s) simulated on "
            f"{brief['slots_per_plan']} slots — TOP {top.get('acct_num','?')} "
            f"{top.get('phase_key','?')} score={top['score']} "
            f"TP={top['tp_rate']:.0%} SL={top['sl_rate']:.0%} "
            f"avg {top.get('avg_tp_min')}min best window {top.get('best_slot')} "
            f"{str(top.get('best_direction','')).upper()}"
        )
        for p in ranked[:5]:
            log_fn(
                f"  {p.get('acct_num','?')} {p.get('phase_key','?')} "
                f"TP={p['tp_ticks']}t SL={p['sl_ticks']}t "
                f"score={p['score']} tp={p['tp_rate']:.0%} sl={p['sl_rate']:.0%} "
                f"~{p.get('avg_tp_min')}min window={p.get('best_slot')}"
            )
    return brief


def get_last_brief() -> Dict[str, Any]:
    with _lock:
        return dict(_last_brief)


def get_plan_stats(plan_id: str, window: int = 200) -> Dict[str, Any]:
    """Rolling sim stats for one plan (feeds tomorrow entry decision)."""
    with _lock:
        _load_journal()
        recs = [r for r in _journal if r.get("plan_id") == plan_id]
    recent = recs[-window:]
    if not recent:
        return {"n": 0}
    n = len(recent)
    tp = sum(1 for r in recent if r.get("outcome") == "tp")
    sl = sum(1 for r in recent if r.get("outcome") == "sl")
    return {
        "n": n,
        "tp_rate": round(tp / n, 3),
        "sl_rate": round(sl / n, 3),
    }


def learning_confidence_adjustment(direction: str, plan_id: Optional[str] = None) -> float:
    """Small gate adjustment from simulation history (±0.05 max)."""
    brief = get_last_brief()
    top = brief.get("top")
    if not top:
        return 0.0
    if plan_id and top.get("plan_id") != plan_id:
        for p in brief.get("plans", []):
            if p.get("plan_id") == plan_id:
                top = p
                break
    if top.get("score", 0) >= 0.8 and top.get("best_direction") == direction:
        return -0.03   # relax slightly — sims look good for this direction
    if top.get("sl_rate", 0) > 0.5:
        return +0.05   # tighten — sims mostly stopped out
    return 0.0


def make_plan_id(acct_num: str, phase_key: str, firm_code: str) -> str:
    return f"{firm_code}:{phase_key}:{acct_num}".lower().replace(" ", "_")


# ── Continuous batch simulator (tomorrow plans → open batch → TP/SL → repeat) ──

_batch: Dict[str, Any] = {
    "batch_num": 0,
    "open": [],
    "closed": [],
    "batch_results": [],       # per-batch tp/sl counts for accuracy tracking
    "trade_seq": 0,
    "last_step": 0.0,
}
_history_path = os.path.join(_base_dir(), "sim_batch_history.jsonl")
MAX_CLOSED = 500


def _mt5_wall_dt(epoch: int) -> datetime:
    """Broker server wall time (matches MT5 Market Watch / chart axis)."""
    return datetime.utcfromtimestamp(int(epoch))


def _mt5_now_ts(m1_bars=None) -> int:
    """Current MT5 server unix stamp from live tick or latest M1 bar."""
    if MT5_AVAILABLE:
        for cand in MT5_SYMBOL_CANDIDATES:
            try:
                if mt5.symbol_info(cand) is None:
                    continue
                tick = mt5.symbol_info_tick(cand)
                if tick and int(getattr(tick, "time", 0) or 0) > 0:
                    return int(tick.time)
            except Exception:
                continue
    if m1_bars is not None and len(m1_bars):
        return int(m1_bars[-1][0])
    return int(time.time())


def _fmt_ts(epoch: Optional[int]) -> str:
    if not epoch:
        return "—"
    try:
        return _mt5_wall_dt(epoch).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "—"


def _learning_note(trade: Dict, batch_stats: Dict) -> Optional[Dict[str, str]]:
    if trade.get("outcome") != "sl":
        return None
    b = trade.get("batch", 0)
    acc = batch_stats.get("accuracy")
    return {
        "what_went_wrong": (
            f"Simulated {trade.get('side', '').upper()} on {trade.get('acct_num', '?')} "
            f"({trade.get('phase_key')}) hit SL at {trade.get('exit_price')} "
            f"after {trade.get('duration_min')}min — market moved "
            f"{trade.get('signed_move', 0):+.1f} pts against the position."),
        "what_improved": (
            f"Batch {b} result fed into the ML journal. "
            f"Running accuracy over last {batch_stats.get('n_batches', 0)} batches: "
            f"{acc:.0%} TP-first when available." if acc is not None else
            "Batch result fed into the ML journal for recency-weighted retraining."),
        "did_it_help": (
            f"Next batch #{b + 1} opened with fresh trend + updated gate. "
            f"Cumulative sim TP rate: {batch_stats.get('tp_rate', 0):.0%}."
        ),
    }


def _check_open_trade(trade: Dict, m1_bars, ticks=None,
                      symbol: Optional[str] = None) -> Optional[Dict]:
    """Return close dict if TP/SL (or timeout) hit — ticks preferred, else M1."""
    if m1_bars is None or len(m1_bars) == 0:
        return None
    walk = walk_tp_sl(
        trade["entry_ts"],
        trade["entry_price"],
        trade["direction"],
        trade["tp_points"],
        trade["sl_points"],
        m1_bars,
        ticks=ticks,
        symbol=symbol or trade.get("symbol"),
    )
    trade["mfe"] = walk.get("mfe_points", 0)
    trade["mae"] = walk.get("mae_points", 0)
    trade["walk_mode"] = walk.get("walk_mode", "m1")
    if walk["outcome"] in ("tp", "sl"):
        return {
            "outcome": walk["outcome"],
            "exit_ts": walk["exit_ts"],
            "exit_price": walk["exit_price"],
        }
    cutoff = trade["entry_ts"] + MAX_WALK_MIN * 60
    now_t = _mt5_now_ts(m1_bars)
    if ticks is not None and len(ticks):
        last_t = int(ticks[-1]["time"])
        last_px = _tick_exit_price(ticks[-1], trade["direction"])
    else:
        last_t = int(m1_bars[-1][0])
        last_px = float(m1_bars[-1][4])
    if last_t >= cutoff:
        return {
            "outcome": "timeout",
            "exit_ts": last_t,
            "exit_price": last_px,
        }
    trade["last_checked_ts"] = last_t
    return None


def _close_trade(trade: Dict, close: Dict) -> Dict[str, Any]:
    exit_ts = close["exit_ts"]
    exit_px = close["exit_price"]
    entry_px = trade["entry_price"]
    sign = 1.0 if trade["direction"] == "buy" else -1.0
    move = (exit_px - entry_px) * sign
    oc = close["outcome"]
    tp_pts = trade["tp_points"]
    sl_pts = trade["sl_points"]
    if oc == "tp":
        pnl_pts = tp_pts
    elif oc == "sl":
        pnl_pts = -sl_pts
    else:
        pnl_pts = move
    dur = max(1, int((exit_ts - trade["entry_ts"]) / 60)) if exit_ts else None
    row = {
        "simulated": True,
        "trade_id": trade["trade_id"],
        "batch": trade["batch"],
        "plan_id": trade["plan_id"],
        "acct_num": trade.get("acct_num", "?"),
        "firm_code": trade.get("firm_code", ""),
        "phase_key": trade.get("phase_key", ""),
        "symbol": trade.get("symbol", "ustech"),
        "side": trade["direction"],
        "volume": 1,
        "entry_time": trade["entry_ts"],
        "entry_time_str": _fmt_ts(trade["entry_ts"]),
        "entry_price": round(entry_px, 2),
        "exit_time": exit_ts,
        "exit_time_str": _fmt_ts(exit_ts),
        "exit_price": round(exit_px, 2),
        "duration_min": dur,
        "outcome": oc,
        "net_profit": round(pnl_pts, 2),
        "signed_move": round(move, 2),
        "won": oc == "tp",
        "lost": oc == "sl",
        "closed": True,
        "tp_ticks": trade.get("tp_ticks"),
        "sl_ticks": trade.get("sl_ticks"),
        "mfe_points": round(trade.get("mfe", 0), 2),
        "mae_points": round(trade.get("mae", 0), 2),
        "ai_lean": trade["direction"],
        "walk_mode": trade.get("walk_mode", "m1"),
        "tp_points": tp_pts,
        "sl_points": sl_pts,
        "tp_level": trade.get("tp_level"),
        "sl_level": trade.get("sl_level"),
    }
    return row


def _open_batch(plans: List[Dict], m1, m5, direction_fn=None,
                log_fn: Optional[Callable[[str], None]] = None,
                ticks=None, symbol: Optional[str] = None) -> int:
    """Open one simulated trade per tomorrow plan at the current price."""
    if not plans or m1 is None or len(m1) < 2:
        return 0
    # Enter on a bar with forward history so TP/SL can resolve in the same step
    lookback = min(SIM_INTERVAL_MIN, max(1, len(m1) - 1))
    entry_bar = m1[-(lookback + 1)] if len(m1) > lookback else m1[0]
    bar_ts = int(entry_bar[0])
    bar_px = float(entry_bar[4])
    _batch["batch_num"] += 1
    bnum = _batch["batch_num"]
    opened = 0
    for plan in plans:
        direction = None
        if direction_fn:
            try:
                direction = direction_fn(plan)
            except Exception:
                direction = None
        if direction not in ("buy", "sell"):
            direction = trend_at_time(m5, bar_ts)
        if direction not in ("buy", "sell"):
            continue
        entry_ts, entry_price = entry_fill_from_ticks(
            ticks, bar_ts, direction, bar_px)
        sign = 1.0 if direction == "buy" else -1.0
        tp_pts = plan["tp_points"]
        sl_pts = plan["sl_points"]
        _batch["trade_seq"] += 1
        tid = f"B{bnum}-T{_batch['trade_seq']}"
        _batch["open"].append({
            "trade_id": tid,
            "batch": bnum,
            "plan_id": plan["plan_id"],
            "acct_num": plan.get("acct_num"),
            "firm_code": plan.get("firm_code"),
            "phase_key": plan.get("phase_key"),
            "symbol": plan.get("mt5_symbol", "ustech"),
            "direction": direction,
            "entry_ts": entry_ts,
            "entry_price": entry_price,
            "tp_points": tp_pts,
            "sl_points": sl_pts,
            "tp_ticks": plan.get("tp_ticks"),
            "sl_ticks": plan.get("sl_ticks"),
            "tp_level": round(entry_price + sign * tp_pts, 2),
            "sl_level": round(entry_price - sign * sl_pts, 2),
            "last_checked_ts": entry_ts,
            "mfe": 0.0,
            "mae": 0.0,
        })
        opened += 1
    if log_fn and opened:
        mode = "tick" if ticks is not None and len(ticks) else "M1"
        log_fn(
            f"batch #{bnum} OPEN — {opened} simulated tomorrow trade(s) @ "
            f"{entry_price:.2f} ({mode} walk)")
    return opened


def _batch_accuracy_stats() -> Dict[str, Any]:
    br = _batch["batch_results"]
    if not br:
        return {"n_batches": 0, "tp_rate": 0.0, "accuracy": 0.0}
    tp = sum(x.get("tp", 0) for x in br)
    sl = sum(x.get("sl", 0) for x in br)
    total = tp + sl
    return {
        "n_batches": len(br),
        "tp_rate": tp / total if total else 0.0,
        "accuracy": tp / total if total else 0.0,
        "tp": tp,
        "sl": sl,
    }


def _persist_closed(row: Dict) -> None:
    try:
        with open(_history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass


def _process_trade_close(trade: Dict, hit: Dict, symbol: str,
                         log_fn: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    row = _close_trade(trade, hit)
    stats = _batch_accuracy_stats()
    if row.get("lost"):
        row["learning"] = _learning_note(row, stats)
    _batch["closed"].append(row)
    _persist_closed(row)
    if prediction_tracker and row["outcome"] in ("tp", "sl"):
        try:
            prediction_tracker.ingest_simulation(
                symbol,
                entry_ts=row["entry_time"],
                price=row["entry_price"],
                lean=row["side"],
                tp_points=trade["tp_points"],
                sl_points=trade["sl_points"],
                outcome=row["outcome"],
                outcome_min=row.get("duration_min"),
                mfe_points=row.get("mfe_points", 0),
                mae_points=row.get("mae_points", 0),
            )
        except Exception:
            pass
    if log_fn:
        tag = "TP" if row["won"] else "SL" if row["lost"] else row["outcome"].upper()
        acct = str(row.get("acct_num") or "?")
        log_fn(
            f"batch #{row['batch']} CLOSED {acct[-8:]} "
            f"{row['phase_key']} {row['side'].upper()} -> {tag} "
            f"@ {row['exit_price']} in {row['duration_min']}min "
            f"({row['signed_move']:+.1f}pts)"
        )
    return row


def _flush_open_trades(m1, symbol: str, ticks=None,
                       log_fn: Optional[Callable[[str], None]] = None) -> List[Dict]:
    """Check all open trades; return rows closed this pass."""
    closed = []
    still_open = []
    for trade in _batch["open"]:
        hit = _check_open_trade(trade, m1, ticks=ticks, symbol=symbol)
        if hit:
            closed.append(_process_trade_close(trade, hit, symbol, log_fn))
        else:
            still_open.append(trade)
    _batch["open"] = still_open
    return closed


def step_batch_engine(
    plans: List[Dict[str, Any]],
    symbol: str = "ustech",
    log_fn: Optional[Callable[[str], None]] = None,
    direction_fn: Optional[Callable[[Dict], Optional[str]]] = None,
    max_batch_rounds: int = 15,
) -> Dict[str, Any]:
    """Advance open simulated trades; when all close, open the next batch.

    Call every ~60s (and on Trade History refresh). Requires MT5 M1/tick data.
    """
    global _batch
    with _lock:
        _batch["last_step"] = time.time()
        if plans:
            _batch["plans"] = plans
        use_plans = plans or _batch.get("plans") or []

        m1, m5, sym = fetch_m1_m5(symbol)
        if m1 is None or len(m1) < 10:
            return {
                "error": "connect MT5 for M1 bars",
                "open": len(_batch["open"]),
                "closed": len(_batch["closed"]),
                **_batch_accuracy_stats(),
            }

        now_ts = _mt5_now_ts(m1)
        tick_from = now_ts - MAX_WALK_MIN * 60
        if _batch["open"]:
            tick_from = min(tick_from, min(t["entry_ts"] for t in _batch["open"]))
        session_ticks = None
        walk_mode = "m1"
        if USE_TICK_WALK:
            session_ticks = fetch_ticks(sym or symbol, tick_from, now_ts)
            if session_ticks is not None and len(session_ticks):
                walk_mode = "ticks"

        closed_this_step: List[Dict] = []
        for _round in range(max_batch_rounds):
            batch_closed = _flush_open_trades(
                m1, sym or symbol, ticks=session_ticks, log_fn=log_fn)
            closed_this_step.extend(batch_closed)

            if _batch["open"]:
                break

            if batch_closed and use_plans:
                tp_n = sum(1 for r in batch_closed if r.get("won"))
                sl_n = sum(1 for r in batch_closed if r.get("lost"))
                _batch["batch_results"].append({
                    "batch": _batch["batch_num"],
                    "tp": tp_n,
                    "sl": sl_n,
                    "ts": time.time(),
                })
                acc = _batch_accuracy_stats()
                if log_fn:
                    log_fn(
                        f"batch #{_batch['batch_num']} COMPLETE — {tp_n} TP / {sl_n} SL | "
                        f"running accuracy {acc['accuracy']:.0%} over {acc['n_batches']} batch(es) — "
                        f"opening next batch"
                    )
                if not _open_batch(
                        use_plans, m1, m5, direction_fn, log_fn,
                        ticks=session_ticks, symbol=sym or symbol):
                    break
                continue

            if not batch_closed and use_plans and not _batch["open"]:
                if not _open_batch(
                        use_plans, m1, m5, direction_fn, log_fn,
                        ticks=session_ticks, symbol=sym or symbol):
                    break
                continue

            break

        if len(_batch["closed"]) > MAX_CLOSED:
            _batch["closed"] = _batch["closed"][-MAX_CLOSED:]

        return {
            "symbol": sym,
            "batch_num": _batch["batch_num"],
            "open_count": len(_batch["open"]),
            "closed_count": len(_batch["closed"]),
            "closed_this_step": len(closed_this_step),
            "walk_mode": walk_mode,
            "tick_count": len(session_ticks) if session_ticks is not None else 0,
            **_batch_accuracy_stats(),
        }


def get_simulated_trade_history(include_open: bool = True,
                                m1_bars=None) -> List[Dict[str, Any]]:
    """All closed (+ optionally open) simulated trades for the UI."""
    now_mt5 = _mt5_now_ts(m1_bars)
    cutoff = now_mt5 - SIM_HISTORY_MAX_AGE_SEC
    with _lock:
        rows = []
        for r in _batch["closed"]:
            entry_ts = r.get("entry_time") or 0
            if entry_ts and entry_ts < cutoff:
                continue
            row = dict(r)
            row["entry_time_str"] = _fmt_ts(entry_ts)
            if row.get("exit_time"):
                row["exit_time_str"] = _fmt_ts(row["exit_time"])
            rows.append(row)
        if include_open:
            for t in _batch["open"]:
                entry_ts = t["entry_ts"]
                rows.append({
                    "simulated": True,
                    "trade_id": t["trade_id"],
                    "batch": t["batch"],
                    "acct_num": t.get("acct_num"),
                    "phase_key": t.get("phase_key"),
                    "symbol": t.get("symbol", "ustech"),
                    "side": t["direction"],
                    "volume": 1,
                    "entry_time": entry_ts,
                    "entry_time_str": _fmt_ts(entry_ts),
                    "entry_price": t["entry_price"],
                    "exit_time_str": "OPEN",
                    "exit_price": None,
                    "duration_min": max(1, int((now_mt5 - entry_ts) / 60)),
                    "outcome": "open",
                    "net_profit": None,
                    "won": False,
                    "lost": False,
                    "closed": False,
                    "ai_lean": t["direction"],
                    "tp_points": t.get("tp_points"),
                    "sl_points": t.get("sl_points"),
                    "tp_level": t.get("tp_level"),
                    "sl_level": t.get("sl_level"),
                })
        rows.sort(key=lambda r: r.get("entry_time") or 0, reverse=True)
        return rows


def _rebuild_batch_results_from_closed() -> None:
    """Restore batch accuracy counters after loading persisted history."""
    by_batch: Dict[int, Dict[str, int]] = {}
    for row in _batch["closed"]:
        b = int(row.get("batch") or 0)
        if b <= 0:
            continue
        bucket = by_batch.setdefault(b, {"tp": 0, "sl": 0})
        if row.get("won"):
            bucket["tp"] += 1
        elif row.get("lost"):
            bucket["sl"] += 1
    _batch["batch_results"] = [
        {"batch": b, "tp": v["tp"], "sl": v["sl"], "ts": 0}
        for b, v in sorted(by_batch.items())
    ]


def load_persisted_history() -> None:
    """Restore closed sim history from disk on startup."""
    try:
        if not os.path.exists(_history_path):
            return
        max_batch = 0
        max_seq = 0
        now_mt5 = _mt5_now_ts()
        cutoff = now_mt5 - SIM_HISTORY_MAX_AGE_SEC
        kept: List[Dict] = []
        with open(_history_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                entry_ts = int(row.get("entry_time") or 0)
                if entry_ts and entry_ts < cutoff:
                    continue
                row["entry_time_str"] = _fmt_ts(entry_ts)
                if row.get("exit_time"):
                    row["exit_time_str"] = _fmt_ts(row["exit_time"])
                kept.append(row)
                max_batch = max(max_batch, int(row.get("batch") or 0))
                tid = str(row.get("trade_id") or "")
                if tid.startswith("B") and "-T" in tid:
                    try:
                        max_seq = max(max_seq, int(tid.split("-T")[-1]))
                    except ValueError:
                        pass
        _batch["closed"] = kept[-MAX_CLOSED:]
        _batch["batch_num"] = max_batch
        _batch["trade_seq"] = max_seq
        _rebuild_batch_results_from_closed()
    except Exception:
        pass


load_persisted_history()


# ── Historical Strategy Tester (replay over days/months/year) ─────────────

HISTORICAL_PERIODS: Dict[str, int] = {
    "live": 0,
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "365d": 365,
}

HISTORICAL_PERIOD_LABELS = {
    "live": "Live (today batch)",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
    "90d": "Last 90 days",
    "365d": "Last 1 year",
}

MAX_HISTORICAL_TRADES = 4000
M1_CHUNK_DAYS = 28
M5_WARMUP_DAYS = 12

_last_historical: Dict[str, Any] = {}

_DEFAULT_BACKTEST_PLAN: Dict[str, Any] = {
    "plan_id": "default:ch1:ustech",
    "acct_num": "BACKTEST",
    "firm_code": "FN",
    "phase_key": "CH1",
    "mt5_symbol": "ustech",
    "tp_ticks": 250,
    "sl_ticks": 100,
    "tp_points": DEFAULT_TP_POINTS,
    "sl_points": DEFAULT_SL_POINTS,
    "expected_min": expected_duration_min(DEFAULT_TP_POINTS, DEFAULT_SL_POINTS),
}


def interval_for_days(days: int) -> int:
    """Entry spacing — wider for long lookbacks to keep runtime reasonable."""
    if days <= 7:
        return 15
    if days <= 30:
        return 15
    if days <= 90:
        return 30
    return 60


def fetch_rates_range(symbol: str, timeframe, from_ts: int, to_ts: int):
    """MT5 OHLC range in server-wall time."""
    if not MT5_AVAILABLE or to_ts <= from_ts:
        return None
    sym = _resolve_symbol(symbol)
    if not sym:
        return None
    try:
        dt_from = _mt5_wall_dt(from_ts)
        dt_to = _mt5_wall_dt(to_ts + 60)
        return mt5.copy_rates_range(sym, timeframe, dt_from, dt_to)
    except Exception:
        return None


def _dedupe_rates(rates):
    if rates is None or len(rates) == 0:
        return rates
    by_t: Dict[int, Any] = {}
    for r in rates:
        by_t[int(r[0])] = r
    import numpy as np
    return np.array([by_t[k] for k in sorted(by_t)])


def fetch_rates_range_chunked(symbol: str, timeframe, from_ts: int, to_ts: int,
                              chunk_days: int = M1_CHUNK_DAYS):
    """Fetch long histories in monthly chunks (MT5 bar limits)."""
    if to_ts <= from_ts:
        return None
    chunks = []
    t = from_ts
    step = chunk_days * 86400
    while t < to_ts:
        t_end = min(to_ts, t + step)
        part = fetch_rates_range(symbol, timeframe, t, t_end)
        if part is not None and len(part):
            chunks.append(part)
        t = t_end + 60
    if not chunks:
        return None
    if len(chunks) == 1:
        return chunks[0]
    import numpy as np
    merged = np.concatenate(chunks)
    return _dedupe_rates(merged)


def fetch_m1_m5_historical(symbol: str, from_ts: int, to_ts: int):
    """M1 + M5 for a historical window (M5 includes warmup for EMA trend)."""
    sym = _resolve_symbol(symbol)
    if not sym:
        return None, None, sym
    m1 = fetch_rates_range_chunked(sym, mt5.TIMEFRAME_M1, from_ts, to_ts)
    m5_from = from_ts - M5_WARMUP_DAYS * 86400
    m5 = fetch_rates_range_chunked(sym, mt5.TIMEFRAME_M5, m5_from, to_ts)
    return m1, m5, sym


def historical_entry_slots(m1_bars, from_ts: int, to_ts: int,
                           interval_min: int = SIM_INTERVAL_MIN) -> List[Tuple[int, float]]:
    """(entry_ts, m1_close) on interval boundaries across a date range."""
    if m1_bars is None or len(m1_bars) < interval_min + 2:
        return []
    step = interval_min * 60
    t = from_ts - (from_ts % step) + step
    end_t = to_ts - step
    slots: List[Tuple[int, float]] = []
    bar_i = 0
    n = len(m1_bars)
    while t <= end_t:
        price = None
        while bar_i < n and int(m1_bars[bar_i][0]) <= t:
            price = float(m1_bars[bar_i][4])
            bar_i += 1
        if price is not None and t >= from_ts:
            slots.append((t, price))
        t += step
    return slots


def _historical_trade_row(plan: Dict, entry_ts: int, entry_price: float,
                          direction: str, walk: Dict, seq: int,
                          days_label: str) -> Dict[str, Any]:
    tp_pts = float(plan["tp_points"])
    sl_pts = float(plan["sl_points"])
    pseudo = {
        "trade_id": f"H{days_label}-T{seq}",
        "batch": days_label,
        "plan_id": plan.get("plan_id"),
        "acct_num": plan.get("acct_num", "?"),
        "firm_code": plan.get("firm_code", ""),
        "phase_key": plan.get("phase_key", ""),
        "symbol": plan.get("mt5_symbol", "ustech"),
        "direction": direction,
        "entry_ts": entry_ts,
        "entry_price": entry_price,
        "tp_points": tp_pts,
        "sl_points": sl_pts,
        "tp_ticks": plan.get("tp_ticks"),
        "sl_ticks": plan.get("sl_ticks"),
        "mfe": walk.get("mfe_points", 0),
        "mae": walk.get("mae_points", 0),
        "walk_mode": walk.get("walk_mode", "m1"),
    }
    oc = walk.get("outcome") or "none"
    if oc in ("tp", "sl"):
        close = {
            "outcome": oc,
            "exit_ts": walk["exit_ts"],
            "exit_price": walk["exit_price"],
        }
    else:
        exit_ts = walk.get("exit_ts") or (entry_ts + MAX_WALK_MIN * 60)
        close = {"outcome": "timeout", "exit_ts": exit_ts, "exit_price": entry_price}
    row = _close_trade(pseudo, close)
    row["tp_points"] = tp_pts
    row["sl_points"] = sl_pts
    row["tp_level"] = walk.get("tp_level")
    row["sl_level"] = walk.get("sl_level")
    row["historical"] = True
    row["period"] = days_label
    return row


def run_historical_backtest(
    plans: Optional[List[Dict[str, Any]]] = None,
    symbol: str = "ustech",
    days_back: int = 30,
    interval_min: Optional[int] = None,
    direction_fn: Optional[Callable[[Dict], Optional[str]]] = None,
    max_trades: int = MAX_HISTORICAL_TRADES,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Replay trader blueprints across historical M1 — tick chart on drill-down."""
    global _last_historical
    use_plans = list(plans) if plans else [_DEFAULT_BACKTEST_PLAN]
    if not use_plans:
        use_plans = [_DEFAULT_BACKTEST_PLAN]

    days_back = max(1, int(days_back))
    period_key = f"{days_back}d"
    if interval_min is None:
        interval_min = interval_for_days(days_back)

    to_ts = _mt5_now_ts()
    from_ts = to_ts - days_back * 86400

    if log_fn:
        log_fn(f"historical backtest: loading M1/M5 for last {days_back}d…")

    m1, m5, sym = fetch_m1_m5_historical(symbol, from_ts, to_ts)
    if m1 is None or len(m1) < 60:
        err = {"error": "connect MT5 — need M1 history for the selected period",
               "trades": [], "stats": {}}
        _last_historical = err
        return err

    slots = historical_entry_slots(m1, from_ts, to_ts, interval_min)
    if not slots:
        err = {"error": "no entry slots in range", "trades": [], "stats": {}}
        _last_historical = err
        return err

    est = len(slots) * len(use_plans)
    stride = 1
    if est > max_trades:
        stride = max(1, int(est / max_trades) + 1)
        if log_fn:
            log_fn(f"historical: {est} potential entries — sampling every {stride} slot(s)")

    trades: List[Dict[str, Any]] = []
    seq = 0
    skipped_trend = 0
    for i, (entry_ts, entry_price) in enumerate(slots):
        if i % stride:
            continue
        for plan in use_plans:
            direction = None
            if direction_fn:
                try:
                    direction = direction_fn(plan)
                except Exception:
                    direction = None
            if direction not in ("buy", "sell"):
                direction = trend_at_time(m5, entry_ts) if m5 is not None else None
            if direction not in ("buy", "sell"):
                skipped_trend += 1
                continue

            tp_pts = float(plan["tp_points"])
            sl_pts = float(plan["sl_points"])
            walk = walk_tp_sl(
                entry_ts, entry_price, direction, tp_pts, sl_pts,
                m1, ticks=None, symbol=sym or symbol)
            seq += 1
            trades.append(_historical_trade_row(
                plan, entry_ts, entry_price, direction, walk, seq, period_key))

            if log_fn and seq % 250 == 0:
                log_fn(f"historical backtest: simulated {seq} trades…")

            if len(trades) >= max_trades:
                break
        if len(trades) >= max_trades:
            break

    tp_n = sum(1 for t in trades if t.get("won"))
    sl_n = sum(1 for t in trades if t.get("lost"))
    to_n = sum(1 for t in trades if t.get("outcome") == "timeout")
    closed = tp_n + sl_n
    total_pnl = sum(float(t.get("net_profit") or 0) for t in trades)

    stats = {
        "period_key": period_key,
        "period_label": HISTORICAL_PERIOD_LABELS.get(period_key, f"Last {days_back}d"),
        "days_back": days_back,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "from_str": _fmt_ts(from_ts),
        "to_str": _fmt_ts(to_ts),
        "interval_min": interval_min,
        "n_trades": len(trades),
        "n_plans": len(use_plans),
        "n_slots": len(slots),
        "stride": stride,
        "tp": tp_n,
        "sl": sl_n,
        "timeout": to_n,
        "win_rate": round(tp_n / closed, 3) if closed else 0.0,
        "total_pnl_pts": round(total_pnl, 1),
        "skipped_no_trend": skipped_trend,
        "walk_mode": "m1",
        "symbol": sym,
    }

    trades.sort(key=lambda r: r.get("entry_time") or 0, reverse=True)

    if log_fn:
        log_fn(
            f"historical {stats['period_label']} DONE — {len(trades)} trades "
            f"({tp_n} TP / {sl_n} SL / {to_n} timeout) · "
            f"win {stats['win_rate']:.0%} · Σ {total_pnl:+.0f} sim pts · "
            f"entry every {interval_min}min")

    result = {"trades": trades, "stats": stats, "plans": use_plans}
    _last_historical = result
    return result


def get_last_historical() -> Dict[str, Any]:
    return dict(_last_historical)
