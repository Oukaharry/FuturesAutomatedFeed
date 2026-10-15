"""
Re-queue and flush same-day Fail purchase Slack alerts for one client.

Also supports restoring missing Fail challenge rows (Pilar Cortez case:
companion logged Fail for accounts that later vanished from the sheet).

Usage:
    python scripts/repair_client_purchase_alerts.py "Pilar Cortez" --dry-run
    python scripts/repair_client_purchase_alerts.py "Pilar Cortez" --add-fails
    python scripts/repair_client_purchase_alerts.py "Pilar Cortez" --add-fails --force-slack
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

# Accounts companion logged as Challenge Fail for Pilar on 2026-10-15.
PILAR_TODAY_TRADEIFY_FAILS = (
    "TDFYSL50993059889",
    "TDFYSL50386007145",
    "TDFYSL50531077663",
    "TDFYSL50969792459",
    "TDFYSL50957256773",
)


def _ensure_fail_rows(client_id, account_numbers, prop_firm, evaluations, today):
    """Append missing challenge Fail rows; return (evaluations, added_accounts)."""
    existing = {
        str(ev.get("Account #") or "").strip().upper()
        for ev in evaluations
        if isinstance(ev, dict) and not ev.get("_deleted")
    }
    added = []
    for acct in account_numbers:
        key = str(acct or "").strip().upper()
        if not key or key in existing:
            continue
        evaluations.append({
            "Prop Firm": prop_firm,
            "Account #": acct,
            "Account Size": "$50,000",
            "Status P1": "Fail",
            "Date Ended": today,
            "Status": "-",
            "Account #.1": "",
            "_derived_Status P1": (
                f"repair: companion challenge breach on {today}"
            ),
        })
        existing.add(key)
        added.append(acct)
    return evaluations, added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client_id", help='Client name, e.g. "Pilar Cortez"')
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--add-fails",
        action="store_true",
        help="Restore known missing Tradeify Fail rows for this client",
    )
    parser.add_argument(
        "--force-slack",
        action="store_true",
        help="Send purchase Slack even when firm max-out would drop it",
    )
    args = parser.parse_args()
    client_id = args.client_id.strip()
    if not client_id:
        print("client_id required", file=sys.stderr)
        return 2

    from dashboard.database import (
        get_breach_alert_pending,
        get_breach_alert_sent_accounts,
        get_client_data,
        save_client_data_with_history,
    )
    from dashboard.app import (
        BREACH_SLACK_NOTIFICATIONS_PAUSED,
        _breaches_within_firm_max_out,
        _breach_firm_family,
        _count_firm_max_out_slots,
        _firm_eval_marked_live_account,
        _firm_max_out,
        _flush_batched_breach_alerts,
        _kenya_today_str,
        _queue_breach_alerts,
        _send_admin_breach_alert,
        _unsent_today_fail_purchase_breaches,
        app,
    )

    data = get_client_data(client_id) or {}
    evaluations = list(data.get("evaluations") or [])
    if not evaluations and not args.add_fails:
        print(f"{client_id}: no evaluations found")
        return 1

    today = _kenya_today_str()
    added = []
    if args.add_fails and client_id.lower() in ("pilar cortez", "pillar cortez"):
        evaluations, added = _ensure_fail_rows(
            client_id,
            PILAR_TODAY_TRADEIFY_FAILS,
            "Tradeify (50% Add-On)",
            evaluations,
            today,
        )

    pending_before = get_breach_alert_pending(client_id)
    sent = get_breach_alert_sent_accounts(client_id)
    candidates = _unsent_today_fail_purchase_breaches(client_id, evaluations)
    fam = _breach_firm_family("Tradeify (50% Add-On)")
    occupied = _count_firm_max_out_slots(fam, evaluations)
    cap = _firm_max_out(fam)
    live_blocks = _firm_eval_marked_live_account(fam, evaluations)
    room = _breaches_within_firm_max_out(fam, candidates, evaluations)

    print(f"client={client_id}")
    print(f"kenya_today={today}")
    print(f"slack_paused={BREACH_SLACK_NOTIFICATIONS_PAUSED}")
    print(f"eval_rows={len(evaluations)}")
    print(f"fail_rows_added={added}")
    print(f"pending_before={len(pending_before)}")
    print(f"sent_accounts={len(sent)}")
    print(f"unsent_today_fails={len(candidates)}")
    for b in candidates:
        print(
            f"  - {b.get('phase')} {b.get('account')} "
            f"firm={b.get('prop_firm')!r}"
        )
    print(f"tradeify_max_out={occupied}/{cap} live_account_blocks={live_blocks}")
    print(f"tradeify_room_for_purchase={len(room)}")

    if args.dry_run:
        print("dry-run: no save/queue/flush")
        return 0

    with app.app_context():
        if added:
            data = dict(data)
            data["evaluations"] = evaluations
            save_client_data_with_history(
                client_id,
                data,
                change_source="repair_client_purchase_alerts",
                change_description=(
                    f"Restored {len(added)} Tradeify challenge Fail row(s) "
                    f"for {today}"
                ),
            )
            print(f"saved_fail_rows={len(added)}")

        queued = 0
        if candidates:
            queued = _queue_breach_alerts(
                client_id, candidates, evaluations=evaluations)
            print(f"queued={queued}")

        announced = _flush_batched_breach_alerts(client_id, evaluations)
        print(f"announced={announced}")

        if args.force_slack and candidates and announced <= 0:
            forced = _send_admin_breach_alert(client_id, candidates)
            print(f"force_slack_sent={forced}")
            if forced > 0:
                from dashboard.database import mark_breach_alert_accounts_sent
                keys = [
                    f"{_breach_firm_family(b.get('prop_firm'))}|"
                    f"{str(b.get('account') or '').strip().lower()}"
                    for b in candidates
                ]
                mark_breach_alert_accounts_sent(client_id, keys)

        pending_after = get_breach_alert_pending(client_id)
        print(f"pending_after={len(pending_after)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
