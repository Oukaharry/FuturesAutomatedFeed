"""
Set Aymeric's 7/21–8/15/2026 profit split to $6,324 (50% of $12,648.55 net).

Uses admin override tables (same as dashboard Profit Split tab edits).
Run from repo root with DATABASE_URL in .env:

    python scripts/fix_aymeric_profit_split.py
    python scripts/fix_aymeric_profit_split.py --dry-run

Production (after git pull + web reload for watermark/UI fixes):

    bash scripts/run_aymeric_profit_split_production.sh
    # or: .\\scripts\\run_aymeric_profit_split_production.ps1
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# Period ending 8/15/2026 (legacy window truncated at cutover)
PERIOD_721 = "7/21/2026"
NET_721 = 12648.55
SPLIT_721 = 6324.0

# Period 8/16→8/30/2026 — remove ghost $12,027 split (wrong baseline before 7/21 override)
PERIOD_816 = "8/16/2026"
NET_816 = 12648.55
SPLIT_816 = 0.0

SPIKE_WATERMARK_MIN = 80_000.0
SPIKE_WATERMARK_SINCE = "2026-08-16"
SPIKE_WATERMARK_REPLACE = NET_721


def _find_aymeric_client_id():
    from dashboard.database import get_all_clients

    matches = []
    for cid, meta in (get_all_clients() or {}).items():
        name = (meta.get("name") or cid or "").strip()
        if "aymeric" in name.lower() or "aymeric" in cid.lower():
            matches.append((cid, name))
    return matches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-scrub-watermarks",
        action="store_true",
        help="Skip fixing inflated daily_watermarks rows (>= $80k since 2026-08-16)",
    )
    args = parser.parse_args()

    matches = _find_aymeric_client_id()
    if not matches:
        print("No client matching 'Aymeric' found.")
        sys.exit(1)
    if len(matches) > 1:
        exact = [m for m in matches if m[0].strip().lower() == "aymeric"]
        if exact:
            matches = exact
        else:
            print("Multiple matches — pick one:")
            for cid, name in matches:
                print(f"  {cid!r} ({name})")
            sys.exit(1)

    client_id, display = matches[0]
    print(f"Client: {display} ({client_id})")
    for label, fd, net, ps in (
        ("7/21→8/15", PERIOD_721, NET_721, SPLIT_721),
        ("8/16→8/30", PERIOD_816, NET_816, SPLIT_816),
    ):
        print(f"  {label} from_date={fd} net=${net:,.2f} split=${ps:,.0f}")

    from dashboard.watermark_service import (
        compute_waterlog_from_db,
        save_net_profit_override,
        save_profit_split_override,
    )
    from dashboard.database import get_client_data, get_connection

    before = compute_waterlog_from_db(client_id)
    if before and before.get("periods"):
        for fd in (PERIOD_721, PERIOD_816):
            for p in before["periods"]:
                if (p.get("from_date") or "").strip() == fd:
                    print(
                        f"Before {fd}:",
                        f"to={p.get('to_date')}",
                        f"low={p.get('low')}",
                        f"profit_split={p.get('profit_split')}",
                    )
                    break

    data = get_client_data(client_id) or {}
    stats_net = None
    try:
        from dashboard.watermark_service import canonical_client_stats_net

        stats_net = canonical_client_stats_net(data)
        if stats_net is not None:
            print(f"Current dashboard stats net (live): ${stats_net:,.2f}")
    except Exception:
        pass

    if args.dry_run:
        print("Dry run — no DB writes.")
        return

    ok = True
    for fd, net, ps in ((PERIOD_721, NET_721, SPLIT_721), (PERIOD_816, NET_816, SPLIT_816)):
        ok = save_net_profit_override(client_id, fd, net) and ok
        ok = save_profit_split_override(client_id, fd, ps) and ok
    if not ok:
        print("Failed to save overrides.")
        sys.exit(1)

    if not args.no_scrub_watermarks:
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE daily_watermarks
                       SET net_profit_complete = ?
                     WHERE client_id = ?
                       AND date >= ?
                       AND net_profit_complete >= ?
                    """,
                    (
                        SPIKE_WATERMARK_REPLACE,
                        client_id,
                        SPIKE_WATERMARK_SINCE,
                        SPIKE_WATERMARK_MIN,
                    ),
                )
                n = cur.rowcount
                conn.commit()
            print(f"Scrubbed {n} inflated daily_watermark row(s) (>={SPIKE_WATERMARK_MIN:,.0f}).")
        except Exception as e:
            print(f"Warning: daily_watermarks scrub failed: {e}")

    after = compute_waterlog_from_db(client_id)
    if after and after.get("periods"):
        for fd in (PERIOD_721, PERIOD_816):
            for p in after["periods"]:
                if (p.get("from_date") or "").strip() == fd:
                    print(
                        f"After {fd}:",
                        f"low={p.get('low')}",
                        f"profit_split={p.get('profit_split')}",
                        f"override={p.get('profit_split_override')}",
                    )
                    break
    print("last_split_net_profit:", after.get("last_split_net_profit") if after else None)
    print("Done. Reload web app + hard-refresh Aymeric Profit Split tab.")


if __name__ == "__main__":
    main()
