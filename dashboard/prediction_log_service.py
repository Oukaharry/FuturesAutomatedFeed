"""Record momentum forecasts and verify outcomes against M1 price."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from research.eat_time import EAT, format_dt_eat, now_eat

logger = logging.getLogger(__name__)

MIN_MOVE_BPS = 3.0


def _ensure_table() -> None:
    from dashboard.database import get_connection

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS momentum_predictions (
                id              SERIAL PRIMARY KEY,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                symbol          TEXT NOT NULL DEFAULT 'USTECH',
                bias            TEXT NOT NULL,
                strength        DOUBLE PRECISION,
                entry_price     DOUBLE PRECISION,
                window_start    TIMESTAMPTZ,
                window_end      TIMESTAMPTZ,
                window_label    TEXT,
                horizons_json   TEXT,
                votes_json      TEXT,
                verified_json   TEXT,
                verified_at     TIMESTAMPTZ,
                overall_correct BOOLEAN
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_momentum_pred_created
            ON momentum_predictions (created_at DESC)
        """)
        conn.commit()


def record_prediction(
    prediction: Dict[str, Any],
    *,
    symbol: str = "USTECH",
) -> Optional[int]:
    """Persist a momentum forecast when ready. Returns row id."""
    if not prediction.get("ready") or prediction.get("bias") not in ("BUY", "SELL"):
        return None
    try:
        _ensure_table()
        from dashboard.database import get_connection

        win = prediction.get("window") or {}
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO momentum_predictions (
                    created_at, symbol, bias, strength, entry_price,
                    window_start, window_end, window_label,
                    horizons_json, votes_json
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s
                )
                RETURNING id
                """,
                (
                    now_eat().isoformat(),
                    symbol,
                    prediction.get("bias"),
                    prediction.get("strength"),
                    prediction.get("entry_price"),
                    win.get("start_eat"),
                    win.get("valid_through_eat") or win.get("end_eat"),
                    prediction.get("momentum_window")
                    or prediction.get("expected_hold")
                    or prediction.get("best_entry_window"),
                    json.dumps(prediction.get("horizons") or []),
                    json.dumps(prediction.get("votes") or {}),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            pid = row["id"] if isinstance(row, dict) else row[0]
            logger.info("[PredictionLog] recorded id=%s bias=%s", pid, prediction.get("bias"))
            return int(pid)
    except Exception as e:
        logger.warning("[PredictionLog] record failed: %s", e)
        return None


def _price_at_offset(m1_bars: List[dict], created_ts: float, offset_min: int) -> Optional[float]:
    """Close price at created + offset minutes using M1 bar_time convention."""
    target = int(created_ts) + offset_min * 60
    best = None
    best_diff = 999999
    for b in m1_bars:
        t = int(b.get("bar_time") or b.get("time") or 0)
        if t <= 0:
            continue
        diff = abs(t - target)
        if diff < best_diff:
            best_diff = diff
            best = float(b.get("close", 0))
    if best is None or best_diff > 180:
        return None
    return best


def verify_pending_predictions(m1_bars: List[dict]) -> int:
    """Fill verified_json for predictions old enough to score. Returns count updated."""
    if not m1_bars:
        return 0
    try:
        _ensure_table()
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, created_at, bias, entry_price, horizons_json, verified_at
                FROM momentum_predictions
                WHERE verified_at IS NULL
                ORDER BY created_at ASC
                LIMIT 200
            """)
            rows = cur.fetchall()

        updated = 0
        min_move = MIN_MOVE_BPS / 10000.0
        now_ts = now_eat().timestamp()

        for row in rows:
            rid = row["id"] if isinstance(row, dict) else row[0]
            created = row["created_at"] if isinstance(row, dict) else row[1]
            bias = str(row["bias"] if isinstance(row, dict) else row[2])
            entry = row["entry_price"] if isinstance(row, dict) else row[3]
            horizons_raw = row["horizons_json"] if isinstance(row, dict) else row[4]

            if hasattr(created, "timestamp"):
                created_ts = created.timestamp()
            else:
                from datetime import datetime
                created_ts = datetime.fromisoformat(str(created)).timestamp()

            try:
                horizons = json.loads(horizons_raw or "[]")
            except json.JSONDecodeError:
                horizons = []

            max_h = max((int(h.get("minutes", 0)) for h in horizons), default=240)
            if now_ts < created_ts + max_h * 60 + 120:
                continue

            if not entry or float(entry) <= 0:
                entry_px = _price_at_offset(m1_bars, created_ts, 0)
            else:
                entry_px = float(entry)

            if not entry_px:
                continue

            checks: List[Dict[str, Any]] = []
            correct_n = 0
            scored_n = 0
            for h in horizons:
                mins = int(h.get("minutes") or 0)
                if mins <= 0:
                    continue
                exit_px = _price_at_offset(m1_bars, created_ts, mins)
                if exit_px is None:
                    checks.append({"minutes": mins, "label": h.get("label"), "scored": False})
                    continue
                ret = exit_px / entry_px - 1.0
                if bias == "BUY":
                    ok = ret > min_move
                else:
                    ok = ret < -min_move
                scored_n += 1
                if ok:
                    correct_n += 1
                checks.append({
                    "minutes": mins,
                    "label": h.get("label"),
                    "scored": True,
                    "exit_price": round(exit_px, 2),
                    "return_pct": round(ret * 100, 4),
                    "correct": ok,
                })

            overall = (correct_n / scored_n >= 0.5) if scored_n else None
            verified = {
                "checks": checks,
                "scored_horizons": scored_n,
                "correct_horizons": correct_n,
                "entry_price_used": entry_px,
            }

            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE momentum_predictions
                    SET verified_json = %s, verified_at = %s, overall_correct = %s
                    WHERE id = %s
                    """,
                    (json.dumps(verified), now_eat().isoformat(), overall, rid),
                )
                conn.commit()
            updated += 1

        if updated:
            logger.info("[PredictionLog] verified %s predictions", updated)
        return updated
    except Exception as e:
        logger.warning("[PredictionLog] verify failed: %s", e)
        return 0


def list_predictions(*, limit: int = 50) -> List[Dict[str, Any]]:
    try:
        _ensure_table()
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, created_at, symbol, bias, strength, entry_price,
                       window_label, horizons_json, verified_json, verified_at, overall_correct
                FROM momentum_predictions
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

        out: List[Dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                r = row
            else:
                r = {
                    "id": row[0], "created_at": row[1], "symbol": row[2], "bias": row[3],
                    "strength": row[4], "entry_price": row[5], "window_label": row[6],
                    "horizons_json": row[7], "verified_json": row[8],
                    "verified_at": row[9], "overall_correct": row[10],
                }
            try:
                horizons = json.loads(r.get("horizons_json") or "[]")
            except json.JSONDecodeError:
                horizons = []
            try:
                verified = json.loads(r.get("verified_json") or "null")
            except json.JSONDecodeError:
                verified = None
            created = r.get("created_at")
            out.append({
                "id": r.get("id"),
                "created_at": format_dt_eat(created),
                "symbol": r.get("symbol"),
                "bias": r.get("bias"),
                "strength": r.get("strength"),
                "entry_price": r.get("entry_price"),
                "window_label": r.get("window_label"),
                "horizons": horizons,
                "verified": verified,
                "verified_at": format_dt_eat(r.get("verified_at")) if r.get("verified_at") else None,
                "overall_correct": r.get("overall_correct"),
            })
        return out
    except Exception as e:
        logger.warning("[PredictionLog] list failed: %s", e)
        return []


def prediction_stats() -> Dict[str, Any]:
    try:
        _ensure_table()
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE verified_at IS NOT NULL) AS verified,
                       COUNT(*) FILTER (WHERE overall_correct = TRUE) AS wins,
                       COUNT(*) FILTER (WHERE overall_correct = FALSE) AS losses
                FROM momentum_predictions
            """)
            row = cur.fetchone()
        if not row:
            return {}
        if isinstance(row, dict):
            return dict(row)
        return {"total": row[0], "verified": row[1], "wins": row[2], "losses": row[3]}
    except Exception:
        return {}
