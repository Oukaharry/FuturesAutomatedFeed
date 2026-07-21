#!/usr/bin/env python3
"""Diagnose daily summary tracker false 0/N counts (production-safe, read-only).

Usage (from repo root on production):
    python3 scripts/probe_summary_tracker.py

Or paste the bash block from scripts/probe_summary_tracker.sh
Or paste the python3 -c block documented at the bottom of probe_summary_tracker.sh
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass


def _eat_now():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3)))


def _kenya_today_str(eat_dt=None):
    return (eat_dt or _eat_now()).strftime("%Y-%m-%d")


def _summary_tracker_date_str(eat_dt=None):
    eat_dt = eat_dt or _eat_now()
    d = eat_dt.date()
    if eat_dt.hour * 60 + eat_dt.minute < 2 * 60 + 5:
        d = d - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _window_bounds(date_str):
    try:
        day = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None, None
    start = day.strftime("%Y-%m-%d") + "T02:05"
    end = (day + timedelta(days=1)).strftime("%Y-%m-%d") + "T02:05"
    return start, end


def _window(date_str):
    return _window_bounds(date_str)


def _parse_items(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return []


def _has_slack_sent(items):
    return any(isinstance(it, dict) and it.get("id") == "slack_sent" for it in (items or []))


def main():
    from dashboard.database import get_connection, get_summary_status_for_date

    eat = _eat_now()
    utc = datetime.now(timezone.utc)
    server_local = datetime.now()

    kenya_cal = _kenya_today_str(eat)
    tracker = _summary_tracker_date_str(eat)
    utc_cal = utc.strftime("%Y-%m-%d")

    print("=" * 72)
    print("DAILY SUMMARY TRACKER DIAGNOSTIC")
    print("=" * 72)
    print(f"Kenya now (EAT):     {eat.isoformat()}")
    print(f"UTC now:             {utc.isoformat()}")
    print(f"Server local now:    {server_local.isoformat()} (naive — submitted_at uses this)")
    print()
    print(f"Kenya calendar date: {kenya_cal}")
    print(f"Tracker date (fix):  {tracker}  <- dashboard should use this")
    print(f"UTC calendar date:   {utc_cal}  <- old Slack bot used this")
    print()

    if kenya_cal != tracker:
        print("WARNING  DATE MISMATCH (root cause of 0/N before ~02:05 EAT):")
        print(f"   UI was querying tracker window for {kenya_cal}, but sends for this")
        print(f"   operational cycle live under tracker date {tracker}.")
        print()

    for label, d in (
        ("Kenya calendar (OLD default)", kenya_cal),
        ("Tracker date (CORRECT)", tracker),
        ("UTC calendar (Slack bot OLD)", utc_cal),
    ):
        start, end = _window_bounds(d)
        subs = get_summary_status_for_date(d) or []
        print(f"--- {label}: {d} ---")
        print(f"    window UTC: [{start} , {end})")
        print(f"    counted sends: {len(subs)}")
        if subs[:3]:
            for s in subs[:3]:
                print(f"      * {s.get('client_id')} @ {s.get('submitted_at')} by {s.get('submitted_by')}")
            if len(subs) > 3:
                print(f"      ... +{len(subs) - 3} more")
        print()

    # Raw DB: recent checklist rows + audit log
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT current_database(), now() AS db_now")
            row = cur.fetchone()
            if row:
                keys = row.keys() if hasattr(row, "keys") else range(len(row))
                db_info = {k: row[k] for k in keys}
                print(f"Database: {db_info.get('current_database', '?')}  db_now={db_info.get('db_now')}")
            print()

            cur.execute(
                """
                SELECT date, client_id, user_identifier, checklist_type, submitted_at, items
                FROM daily_checklists
                WHERE checklist_type = 'daily_summary' AND client_id != ''
                ORDER BY submitted_at DESC
                LIMIT 15
                """
            )
            rows = cur.fetchall()
            print(f"Recent daily_summary checklist rows (last {len(rows)}):")
            in_tracker_window = 0
            has_marker = 0
            t_start, t_end = _window(tracker)
            for r in rows:
                cid = r["client_id"] if "client_id" in r.keys() else r[3]
                sub_at = r["submitted_at"] if "submitted_at" in r.keys() else r[4]
                items = _parse_items(r["items"] if "items" in r.keys() else r[5])
                slack = _has_slack_sent(items)
                in_win = bool(t_start and t_end and sub_at and t_start <= sub_at < t_end)
                if in_win:
                    in_tracker_window += 1
                if slack:
                    has_marker += 1
                flag = []
                if not slack:
                    flag.append("NO slack_sent marker")
                if not in_win:
                    flag.append("outside current tracker window")
                extra = f"  [{', '.join(flag)}]" if flag else "  [OK for tracker]"
                print(f"  {sub_at}  date={r['date']}  {cid}  slack_sent={slack}{extra}")
            print()
            print(
                f"  Of recent rows: {has_marker} with slack_sent, "
                f"{in_tracker_window} in tracker window [{t_start}, {t_end})"
            )
            print()

            cur.execute(
                """
                SELECT timestamp, user_identifier, action, success, details
                FROM audit_log
                WHERE action = 'SLACK_DAILY_SUMMARY'
                ORDER BY timestamp DESC
                LIMIT 10
                """
            )
            audits = cur.fetchall()
            print(f"Recent SLACK_DAILY_SUMMARY audit_log rows (last {len(audits)}):")
            for a in audits:
                ts = a["timestamp"]
                ok = a["success"]
                det = (a["details"] or "")[:80]
                in_win = bool(t_start and t_end and ts and t_start <= ts < t_end)
                print(f"  {ts}  success={ok}  in_window={in_win}  {det}")
            print()

    except Exception as e:
        print(f"(Skipping detailed SQL — {e})")
        import traceback
        traceback.print_exc()

    # Compare old vs new API logic
    old_count = len(get_summary_status_for_date(kenya_cal) or [])
    new_count = len(get_summary_status_for_date(tracker) or [])
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  Old logic (Kenya calendar {kenya_cal}): {old_count} sends counted")
    print(f"  Fixed logic (tracker date {tracker}):   {new_count} sends counted")
    if old_count == 0 and new_count > 0:
        print()
        print("  CONFIRMED: deploy the tracker-date fix to restore correct counts.")
    elif old_count == 0 and new_count == 0:
        print()
        print("  Still 0 on tracker date — check:")
        print("    • Were summaries sent via Slack (not Save-only)?")
        print("    • Do checklist rows include items[].id == 'slack_sent'?")
        print("    • Is submitted_at within the window shown above?")
    print()


if __name__ == "__main__":
    main()
