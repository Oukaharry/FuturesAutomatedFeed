"""
Restore Nikita profit-share rows after stale override / watermark regression.

Morning fix: delete net_profit_override on 7/21/2026 (was $116,428.88).
Also refresh today's daily watermark using canonical stats net (incl. discrepancy).

Requires deployed watermark_service fix (no blind $15k period cap).

    python scripts/fix_nikita_profit_split.py
    python scripts/fix_nikita_profit_split.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

CLIENT_ID = "Nikita"
STALE_NP_OVERRIDE = "7/21/2026"
# Cashflow-only plateau seen when discrepancy was omitted from daily snapshots
PLATEAU_LO, PLATEAU_HI = 99_200.0, 99_500.0


def _period_row(wl, to_date):
    for p in wl.get("periods") or []:
        if p.get("to_date") == to_date:
            return p
    return None


def _show(label, wl):
    for end in ("7/20/2026", "8/15/2026", "8/30/2026"):
        p = _period_row(wl, end)
        if p:
            print(
                f"  {end}: low={p.get('low')} split={p.get('profit_split')}"
            )
    print(f"  last_split_net_profit={wl.get('last_split_net_profit')}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from dashboard.database import get_client_data, get_connection
    from dashboard.watermark_service import (
        canonical_client_stats_net,
        compute_waterlog_from_db,
        save_daily_profit,
    )

    data = get_client_data(CLIENT_ID) or {}
    live = canonical_client_stats_net(data)
    print(f"Client: {CLIENT_ID}")
    print(f"Canonical stats net (live): {live}")

    wl_before = compute_waterlog_from_db(CLIENT_ID, _live_net=live)
    print("\nBEFORE:")
    _show("", wl_before)

    if args.dry_run:
        print("\nDry run — no DB writes.")
        return

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM net_profit_overrides WHERE client_id = %s AND from_date = %s",
            (CLIENT_ID, STALE_NP_OVERRIDE),
        )
        deleted = cur.rowcount
        conn.commit()
    print(f"\nDeleted net_profit_override rows: {deleted} ({STALE_NP_OVERRIDE})")

    if live is not None:
        today = datetime.now().strftime("%Y-%m-%d")
        save_daily_profit(CLIENT_ID, live, today, source="repair")
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE daily_watermarks
                   SET net_profit_complete = %s, source = 'repair'
                 WHERE client_id = %s
                   AND date >= %s
                   AND net_profit_complete >= %s
                   AND net_profit_complete <= %s
                   AND source IN ('live', 'auto')
                """,
                (float(live), CLIENT_ID, "2026-08-01", PLATEAU_LO, PLATEAU_HI),
            )
            repaired = cur.rowcount
            conn.commit()
        print(f"Today's watermark set to ${live:,.2f}; repaired {repaired} plateau row(s).")

    wl_after = compute_waterlog_from_db(CLIENT_ID, _live_net=live)
    print("\nAFTER (reload dashboard after deploying watermark_service.py):")
    _show("", wl_after)


if __name__ == "__main__":
    main()
