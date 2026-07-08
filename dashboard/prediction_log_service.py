"""Live prediction verification stats for companion ML insights."""

from __future__ import annotations


def prediction_stats() -> dict:
    """Return aggregate counts for logged ML predictions (best-effort)."""
    try:
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE verified_at IS NOT NULL) AS verified,
                    COUNT(*) FILTER (WHERE overall_correct IS TRUE) AS wins,
                    COUNT(*) FILTER (WHERE overall_correct IS FALSE) AS losses
                FROM momentum_predictions
                """
            )
            row = cur.fetchone()
            if not row:
                return {}
            return {
                "total": int(row["total"] or 0),
                "verified": int(row["verified"] or 0),
                "wins": int(row["wins"] or 0),
                "losses": int(row["losses"] or 0),
            }
    except Exception:
        return {"total": 0, "verified": 0, "wins": 0, "losses": 0}
