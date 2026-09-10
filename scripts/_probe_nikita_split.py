"""One-off probe: Nikita profit split for 8/30 period."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("DATABASE_TYPE", "postgresql")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_DB", "tradeopss")

from datetime import date, datetime

from dashboard.database import get_client_data, get_connection
from dashboard.watermark_service import (
    canonical_client_stats_net,
    compute_waterlog_from_db,
    get_net_profit_overrides,
    get_profit_split_overrides,
    get_split_pct_overrides,
    _iter_profit_split_periods,
    _monthly_profit_split_amount,
    _period_end_net_from_dailies,
)

CLIENT_ID = "Nikita"


def _money(s):
    return float(str(s).replace("$", "").replace(",", "").strip())


def main():
    data = get_client_data(CLIENT_ID) or {}
    live = canonical_client_stats_net(data)
    cf = (data.get("statistics") or {}).get("cashflow_inprogress") or {}
    hr = (data.get("statistics") or {}).get("hedging_review") or {}

    print("=== Nikita profit split probe ===")
    print(f"LIVE NET: {live}")
    print(
        "CASHFLOW:",
        {k: cf.get(k) for k in ("payouts", "hedging_results", "farming_results", "challenge_fees", "net_profit")},
    )
    print("DISCREPANCY:", hr.get("discrepancy"))
    print("NP overrides:", get_net_profit_overrides(CLIENT_ID))
    print("Split pct overrides:", get_split_pct_overrides(CLIENT_ID))
    print("PS overrides:", get_profit_split_overrides(CLIENT_ID))

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT date, net_profit_complete FROM daily_watermarks
            WHERE client_id = %s AND date >= %s AND date <= %s
            ORDER BY date
            """,
            (CLIENT_ID, "2026-07-15", "2026-09-10"),
        )
        rows = cur.fetchall()
    print("\nDAILY WATERMARKS (Jul 15 – Sep 10):")
    for r in rows:
        print(f"  {r['date']}  {r['net_profit_complete']}")

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT date, net_profit_complete FROM daily_watermarks
            WHERE client_id = %s ORDER BY date
            """,
            (CLIENT_ID,),
        )
        daily = [
            (datetime.strptime(str(r["date"]), "%Y-%m-%d").date(), float(r["net_profit_complete"]))
            for r in cur.fetchall()
        ]

    wl = compute_waterlog_from_db(CLIENT_ID, _live_net=live)
    print("\nCOMPUTED PERIODS (Jul–Sep):")
    for p in wl["periods"]:
        td = p.get("to_date", "")
        fd = p.get("from_date", "")
        if "2026" in td and any(x in td for x in ("7/", "8/", "9/")):
            print(f"  {fd} → {td}: low={p['low']} split={p['profit_split']} pct={p.get('split_pct')}")

    p830 = next(p for p in wl["periods"] if p.get("to_date") == "8/30/2026")
    p715 = next(p for p in wl["periods"] if p.get("from_date") == "7/21/2026")
    low = _money(p830["low"])
    base = _money(p715["low"])
    print("\n8/30 PERIOD DETAIL:")
    print(f"  Period: 8/16/2026 → 8/30/2026")
    print(f"  Period-end net (low): ${low:,.2f}")
    print(f"  Baseline (7/21→8/15 end net): ${base:,.2f}")
    print(f"  Split @ 50%: ${(low - base) * 0.5:,.2f}  (shown: {p830['profit_split']})")

    # Recompute 8/16-8/30 from dailies ONLY (no live net injection)
    start, end = date(2026, 8, 16), date(2026, 8, 30)
    in_range = [(d, v) for d, v in daily if start <= d <= end]
    daily_only_net = _period_end_net_from_dailies(
        in_range, base, period_complete=True, live_net=None
    )
    print(f"\n  Daily-only end net on 8/30 (no live stats): ${daily_only_net:,.2f}")
    print(f"  Split from dailies only: ${_monthly_profit_split_amount(daily_only_net, base, 50):,.2f}")

    # Show net movement within Aug 16-30 window
    if in_range:
        print(f"  Daily range in window: min={min(v for _, v in in_range):,.2f} max={max(v for _, v in in_range):,.2f}")
        print(f"  First day ({in_range[0][0]}): {in_range[0][1]:,.2f}")
        print(f"  Last day ({in_range[-1][0]}): {in_range[-1][1]:,.2f}")

    # Check if 7/21 override drives baseline
    ov = get_net_profit_overrides(CLIENT_ID).get("7/21/2026")
    if ov is not None:
        print(f"\n  NOTE: net_profit override on 7/21/2026 = {ov}")
        daily_815 = [v for d, v in daily if d == date(2026, 8, 15)]
        if daily_815:
            print(f"  Daily watermark on 8/15/2026 = {daily_815[0]:,.2f}")


if __name__ == "__main__":
    main()
