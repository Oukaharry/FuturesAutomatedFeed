#!/usr/bin/env python3
"""
Simulate traders clearing quality-scan issues at different speeds (local DB test).

Uses real scan rows from quality_scan_results, seeds the issue-tracking tables,
clears clients on a timeline, then prints the clearance leaderboard the dashboard uses.

Examples:
  # Full simulation on today's scan (3 fast / medium / slow + 1 partial trader)
  python scripts/simulate_trader_issue_clearance.py --run

  # Reset tracking for a date and re-seed only (no clearance)
  python scripts/simulate_trader_issue_clearance.py --date 2026-05-25 --reset --seed-only

  # Show current ranking without changing data
  python scripts/simulate_trader_issue_clearance.py --show-ranking

  # After simulation, mimic "Run Quality Scan" sync on final DB state
  python scripts/simulate_trader_issue_clearance.py --final-rescan
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("FLASK_ENV", "development")


def _parse_anchor(scan_date: str, anchor_arg: Optional[str]) -> datetime:
    if anchor_arg:
        dt = datetime.fromisoformat(anchor_arg.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    # Default: same calendar day, 06:00 UTC (morning scan clock)
    return datetime.strptime(scan_date + "T06:00:00", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _reset_tracking(scan_date: str) -> None:
    from dashboard.database import get_connection

    with get_connection() as conn:
        cur = conn.cursor()
        for table, col in (
            ("quality_issue_resolution", "scan_date"),
            ("quality_issue_baseline", "scan_date"),
            ("quality_slack_posts", "scan_date"),
        ):
            cur.execute(f"DELETE FROM {table} WHERE {col} = ?", (scan_date,))
        conn.commit()
    print(f"[reset] Cleared tracking tables for {scan_date}")


def _load_rows(scan_date: str) -> List[dict]:
    from dashboard.database import get_quality_scan_results

    rows = get_quality_scan_results(scan_date) or []
    if not rows:
        raise SystemExit(f"No quality_scan_results for {scan_date}. Run a quality scan first.")
    return rows


def _traders_with_issues(rows: List[dict]) -> Dict[str, List[dict]]:
    from dashboard.app import _trader_ranking_health_metrics

    out: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        n, _ = _trader_ranking_health_metrics(r.get("issues"))
        if n > 0:
            t = (r.get("trader") or "").strip() or "Unassigned"
            out[t].append(r)
    return dict(out)


def _seed_baseline(scan_date: str, anchor: datetime, by_trader: Dict[str, List[dict]]) -> int:
    from dashboard.database import record_quality_scan_anchor, upsert_quality_issue_baseline

    record_quality_scan_anchor(scan_date, _iso(anchor))
    count = 0
    for _trader, clients in by_trader.items():
        for r in clients:
            upsert_quality_issue_baseline(
                scan_date, r["client_id"], str(r.get("trader") or ""), True
            )
            count += 1
    print(f"[seed] Anchor {_iso(anchor)} · baseline clients with issues: {count}")
    return count


def _clear_client_in_scan(scan_date: str, client_id: str) -> None:
    from dashboard.database import get_connection

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE quality_scan_results
            SET issues = ?, total_issues = 0, health_score = 100.0
            WHERE scan_date = ? AND client_id = ?
            """,
            (json.dumps([]), scan_date, client_id),
        )
        conn.commit()


def _mark_cleared(scan_date: str, client_id: str, when: datetime) -> None:
    from dashboard.database import mark_quality_issue_resolved

    mark_quality_issue_resolved(scan_date, client_id, _iso(when))


def _pick_traders(
    by_trader: Dict[str, List[dict]],
    names: Optional[List[str]],
    max_traders: int,
) -> List[str]:
    if names:
        missing = [n for n in names if n not in by_trader]
        if missing:
            raise SystemExit(f"Traders not in scan with issues: {missing}")
        return names[:max_traders]
    ranked = sorted(by_trader.items(), key=lambda x: len(x[1]), reverse=True)
    return [t for t, _ in ranked[:max_traders]]


def _spread_offsets(count: int, start: int, end: int) -> List[int]:
    if count <= 0:
        return []
    if count == 1:
        return [start]
    step = (end - start) / max(count - 1, 1)
    return [int(round(start + step * i)) for i in range(count)]


def _build_schedule(
    traders: List[str],
    by_trader: Dict[str, List[dict]],
    clients_per_trader: int,
) -> List[Tuple[str, str, int]]:
    """
    Return (trader, client_id, minutes_from_anchor) clearance events.

    Profiles:
      - fast / medium / slow: ALL clients with issues cleared (staggered); trader fully ranks when last clears.
      - partial (4th trader): half of clients cleared; rest stay open → pending in leaderboard.
    """
    profiles = [
        ("fast", 12, 38),
        ("medium", 45, 85),
        ("slow", 100, 150),
        ("partial", 55, 90),
    ]
    events: List[Tuple[str, str, int]] = []
    for i, trader in enumerate(traders):
        start_m, end_m = profiles[min(i, len(profiles) - 1)][1:]
        all_clients = by_trader[trader]
        if i < 3:
            # Full clearance — every client with issues must hit 0 for ranking time.
            targets = all_clients if clients_per_trader <= 0 else all_clients[:clients_per_trader]
        else:
            # Partial: clear ~half, leave the rest open.
            n = max(1, len(all_clients) // 2)
            targets = all_clients[:n]

        offsets = _spread_offsets(len(targets), start_m, end_m)
        for r, mins in zip(targets, offsets):
            events.append((trader, r["client_id"], mins))
    return sorted(events, key=lambda e: e[2])


def _run_clearance(
    scan_date: str,
    anchor: datetime,
    events: List[Tuple[str, str, int]],
    pause_sec: float,
) -> None:
    import time

    for trader, client_id, mins in events:
        when = anchor + timedelta(minutes=mins)
        _mark_cleared(scan_date, client_id, when)
        _clear_client_in_scan(scan_date, client_id)
        print(f"  [{mins:3d}m] {trader} cleared {client_id} @ {_iso(when)}")
        if pause_sec > 0:
            time.sleep(pause_sec)


def _final_rescan_sync(scan_date: str) -> None:
    from dashboard.app import _sync_quality_issue_tracking

    rows = _load_rows(scan_date)
    _sync_quality_issue_tracking(scan_date, rows)
    print(f"[final-rescan] Synced tracking from {len(rows)} scan rows")


def _show_ranking(scan_date: str) -> None:
    from dashboard.app import (
        _format_clearance_minutes,
        _trader_clearance_sort_key,
        _trader_ranking_health_metrics,
    )
    from dashboard.database import get_trader_issue_resolution_minutes

    rows = _load_rows(scan_date)
    by_trader = _traders_with_issues(rows)

    # Include traders who had baseline but may now be fully clear
    all_traders = set(by_trader.keys())
    for r in rows:
        t = (r.get("trader") or "").strip() or "Unassigned"
        all_traders.add(t)

    entries = []
    for trader in all_traders:
        raw = get_trader_issue_resolution_minutes(scan_date, trader)
        unresolved = raw >= 99999
        not_in_race = raw < 0
        open_issues = 0
        clients_with_issues = 0
        for r in rows:
            if ((r.get("trader") or "").strip() or "Unassigned") != trader:
                continue
            ti, _ = _trader_ranking_health_metrics(r.get("issues"))
            if ti > 0:
                open_issues += ti
                clients_with_issues += 1
        from dashboard.app import _trader_tracker_subtitle

        lb = {"issues": open_issues, "health_sum": 0.0, "clients": 0}
        for r in rows:
            if ((r.get("trader") or "").strip() or "Unassigned") != trader:
                continue
            _, hs = _trader_ranking_health_metrics(r.get("issues"))
            lb["health_sum"] += hs
            lb["clients"] += 1
        if lb["clients"] == 0:
            lb["clients"] = 1
        entries.append({
            "trader": trader,
            "clearance_minutes": None if unresolved or not_in_race else raw,
            "clearance_unresolved": unresolved,
            "clearance_not_in_race": not_in_race,
            "clearance_label": _trader_tracker_subtitle(raw, lb),
            "open_issues": open_issues,
            "clients_with_issues": clients_with_issues,
        })

    entries.sort(key=_trader_clearance_sort_key)
    print(f"\n{'Rank':<5} {'Trader':<22} {'Status':<28} {'Open':<6} {'Min':<6}")
    print("-" * 72)
    shown = 0
    for e in entries:
        # Skip traders with no baseline involvement and no open issues
        if (
            e["open_issues"] == 0
            and e["clearance_unresolved"]
            and e["clearance_label"].startswith("No issues")
        ):
            continue
        shown += 1
        mins = e["clearance_minutes"]
        print(
            f"{shown:<5} {e['trader']:<22} {e['clearance_label']:<28} {e['open_issues']:<6} "
            f"{'' if mins is None else mins:<6}"
        )
        if shown >= 25:
            break
    print("\nRefresh Quality Dashboard → Daily Summary Tracker to see card order.\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="Scan date YYYY-MM-DD (default: latest in DB)")
    ap.add_argument("--anchor", help="Anchor ISO time UTC (default: date 06:00 UTC)")
    ap.add_argument("--traders", nargs="+", help="Trader names to simulate (default: top 4 by issue count)")
    ap.add_argument(
        "--clients-per-trader",
        type=int,
        default=0,
        help="Cap clients cleared for fast/medium/slow (0 = all clients with issues)",
    )
    ap.add_argument("--reset", action="store_true", help="Clear tracking tables for this date first")
    ap.add_argument("--seed-only", action="store_true", help="Only reset+seed baseline, no clearance")
    ap.add_argument("--run", action="store_true", help="Reset, seed, simulate clearance timeline")
    ap.add_argument("--show-ranking", action="store_true", help="Print leaderboard from current DB state")
    ap.add_argument("--final-rescan", action="store_true", help="Run _sync_quality_issue_tracking on scan rows")
    ap.add_argument(
        "--pause-sec",
        type=float,
        default=0.0,
        help="Seconds to sleep between clearance steps (watch UI live)",
    )
    args = ap.parse_args()

    if not any((args.run, args.show_ranking, args.final_rescan, args.seed_only)):
        ap.print_help()
        sys.exit(0)

    from dashboard.database import get_quality_scan_results

    if args.date:
        scan_date = args.date
    else:
        latest = get_quality_scan_results() or []
        if not latest:
            raise SystemExit("No scan results in DB. Run a quality scan first.")
        scan_date = latest[0]["scan_date"]
    rows = _load_rows(scan_date)

    anchor = _parse_anchor(scan_date, args.anchor)
    by_trader = _traders_with_issues(rows)
    if not by_trader:
        raise SystemExit("No traders with ranking-visible issues on this scan date.")

    if args.reset or args.run or args.seed_only:
        _reset_tracking(scan_date)

    if args.run or args.seed_only:
        _seed_baseline(scan_date, anchor, by_trader)

    if args.seed_only:
        _show_ranking(scan_date)
        return

    if args.run:
        traders = _pick_traders(by_trader, args.traders, max_traders=4)
        events = _build_schedule(traders, by_trader, args.clients_per_trader)
        print(f"[simulate] Traders: {', '.join(traders)}")
        print(f"[simulate] {len(events)} clearance events from anchor {_iso(anchor)}")
        _run_clearance(scan_date, anchor, events, args.pause_sec)
        print("[simulate] Done. Partial traders still have open issues until you clear them.")

    if args.final_rescan:
        _final_rescan_sync(scan_date)

    if args.run or args.show_ranking or args.final_rescan:
        _show_ranking(scan_date)


if __name__ == "__main__":
    main()
