"""Probe team leaderboard from local DB (no Flask import)."""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("psycopg2 required")
    sys.exit(1)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres123@localhost:5432/tradeopss"
)

ADMIN_TEAMS = {
    "marion nyika": ("JoeOppss", "marion nyika"),
    "joy ndua": ("Turnups", "joy ndua"),
    "dennis muthee": ("Hypernikao", "dennis muthee"),
    "shila orori": ("Locked In", "shila orori"),
    "kellen njeri": ("Young Bosses", "kellen njeri"),
    "shalline mukholi": ("Team Aurora", "shalline mukholi"),
    "vivian miano": ("Team Comet", "vivian miano"),
}


def q(conn, sql, params=None):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return [dict(r) for r in cur.fetchall()]


def main():
    conn = psycopg2.connect(DATABASE_URL)
    data = {
        "database": DATABASE_URL.split("@")[-1],
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

    data["table_exists"] = bool(
        q(
            conn,
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'quality_team_leaderboard_daily'",
        )
    )
    data["stored_leaderboard"] = q(
        conn,
        """
        SELECT scan_date, admin_name, team_name, rank, points,
               composite_minutes, signoff_minutes, clearance_minutes, summary_minutes,
               health_score, clients, created_at
        FROM quality_team_leaderboard_daily
        ORDER BY scan_date, rank
        """,
    )
    data["slack_posts"] = q(
        conn, "SELECT scan_date, posted_at FROM quality_slack_posts ORDER BY scan_date"
    )
    data["scan_dates"] = [
        r["scan_date"]
        for r in q(
            conn,
            "SELECT DISTINCT scan_date FROM quality_scan_results ORDER BY scan_date DESC LIMIT 30",
        )
    ]

    # Monthly rollup from stored
    monthly = defaultdict(lambda: defaultdict(lambda: {"month_points": 0, "days": []}))
    for r in data["stored_leaderboard"]:
        m = str(r["scan_date"])[:7]
        tn = r["team_name"]
        monthly[m][tn]["admin_name"] = r["admin_name"]
        monthly[m][tn]["month_points"] += int(r["points"] or 0)
        monthly[m][tn]["days"].append(r)
    data["monthly_stored"] = {
        m: {k: dict(v) for k, v in teams.items()} for m, teams in monthly.items()
    }

    # Checklist / sign-off hints per admin per day
    data["admin_signoff_samples"] = q(
        conn,
        """
        SELECT date, user_identifier AS admin, client_id, checklist_type, submitted_at, items
        FROM daily_checklists
        WHERE checklist_type = 'admin_daily_summary'
        ORDER BY date DESC, user_identifier
        LIMIT 200
        """,
    )

    data["trader_summary_slack_sent"] = q(
        conn,
        """
        SELECT date, user_identifier AS trader, client_id, submitted_at
        FROM daily_checklists
        WHERE checklist_type = 'daily_summary'
          AND items::text LIKE '%%slack_sent%%'
        ORDER BY date DESC, submitted_at
        LIMIT 100
        """,
    )

    conn.close()
    print(json.dumps(data, indent=2, default=str))


if __name__ == "__main__":
    main()
