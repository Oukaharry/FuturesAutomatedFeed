#!/usr/bin/env python3
"""
Server-side unblock for MFFU Builder sharing the MFFU Tradovate login.

The companion (pre-fix) treats "MFFU Builder" as its own broker connection.
Until a new exe ships with Builder mapped into the MFFU login family, clone
My Funded Futures / MFFU Tradovate credentials onto a prop_accounts row labeled
"MFFU Builder" so the Builder broker row auto-fills and can be Connected.

Usage (production):
  python3 scripts/apply_mffu_builder_broker_share.py
  python3 scripts/apply_mffu_builder_broker_share.py --client "Angel Islas"
  python3 scripts/apply_mffu_builder_broker_share.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MFFU_SOURCE_LABELS = {
    "mffu",
    "my funded futures",
    "myfundedfutures",
}
BUILDER_LABEL = "MFFU Builder"
BUILDER_MATCH = ("mffu builder", "mffu_builder", "builder 50k")


def _load_dotenv():
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _db_url() -> str:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if url:
        return url
    raise SystemExit("DATABASE_URL is required")


def _norm(s: str) -> str:
    return " ".join(str(s or "").lower().replace("_", " ").split())


def _is_mffu_source(label: str) -> bool:
    n = _norm(label)
    compact = n.replace(" ", "")
    if "builder" in compact:
        return False
    return n in MFFU_SOURCE_LABELS or compact in {"mffu", "myfundedfutures"}


def _is_builder_label(label: str) -> bool:
    n = _norm(label)
    return any(tok in n for tok in BUILDER_MATCH)


def _has_tv_creds(pa: dict) -> bool:
    return bool(
        str(pa.get("tradovate_username") or "").strip()
        and str(pa.get("tradovate_password") or "").strip()
    )


def _client_needs_builder_row(evals: list, prop_accounts: list) -> tuple[bool, dict | None]:
    has_builder_eval = any(
        _is_builder_label(ev.get("Prop Firm"))
        for ev in (evals or [])
        if isinstance(ev, dict) and not ev.get("_deleted")
    )
    if not has_builder_eval:
        return False, None

    for pa in prop_accounts or []:
        if isinstance(pa, dict) and _is_builder_label(pa.get("prop_firm")) and _has_tv_creds(pa):
            return False, None  # already present

    source = None
    for pa in prop_accounts or []:
        if not isinstance(pa, dict):
            continue
        if _is_mffu_source(pa.get("prop_firm")) and _has_tv_creds(pa):
            source = pa
            break
    return True, source


def _clone_builder_row(source: dict) -> dict:
    row = deepcopy(source)
    row["prop_firm"] = BUILDER_LABEL
    # Keep login/password/tradovate_* ; clear notes noise
    if not str(row.get("notes") or "").strip():
        row["notes"] = "Auto-cloned from MFFU — same Tradovate login as My Funded Futures"
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", help="Only this client_id")
    ap.add_argument("--apply", action="store_true", help="Write changes")
    args = ap.parse_args()

    _load_dotenv()
    import psycopg2

    conn = psycopg2.connect(_db_url())
    conn.autocommit = False
    cur = conn.cursor()
    if args.client:
        cur.execute(
            "SELECT client_id, evaluations, prop_accounts FROM clients_data WHERE client_id=%s",
            (args.client,),
        )
    else:
        cur.execute("SELECT client_id, evaluations, prop_accounts FROM clients_data")

    planned = []
    for client_id, ev_raw, pa_raw in cur.fetchall():
        try:
            evals = json.loads(ev_raw) if ev_raw else []
        except Exception:
            evals = []
        try:
            prop_accounts = json.loads(pa_raw) if pa_raw else []
        except Exception:
            prop_accounts = []
        if not isinstance(prop_accounts, list):
            prop_accounts = []

        needs, source = _client_needs_builder_row(evals, prop_accounts)
        if not needs:
            continue
        if not source:
            planned.append((client_id, None, "HAS Builder evals but no MFFU Tradovate creds to clone"))
            continue
        planned.append((client_id, _clone_builder_row(source), None))

    if not planned:
        print("No clients need an MFFU Builder prop_accounts clone.")
        return 0

    for client_id, row, err in planned:
        if err:
            print(f"SKIP {client_id}: {err}")
            continue
        user = row.get("tradovate_username")
        print(f"{'APPLY' if args.apply else 'DRY'} {client_id}: add prop_firm={BUILDER_LABEL!r} "
              f"tradovate_username={user!r}")

    if not args.apply:
        print("\nDry run only. Re-run with --apply to write.")
        return 0

    for client_id, row, err in planned:
        if err or not row:
            continue
        cur.execute(
            "SELECT prop_accounts FROM clients_data WHERE client_id=%s FOR UPDATE",
            (client_id,),
        )
        raw = cur.fetchone()[0]
        prop_accounts = json.loads(raw) if raw else []
        if not isinstance(prop_accounts, list):
            prop_accounts = []
        # Drop empty/incomplete Builder stubs before appending
        prop_accounts = [
            pa for pa in prop_accounts
            if not (isinstance(pa, dict) and _is_builder_label(pa.get("prop_firm")) and not _has_tv_creds(pa))
        ]
        if any(isinstance(pa, dict) and _is_builder_label(pa.get("prop_firm")) and _has_tv_creds(pa)
               for pa in prop_accounts):
            print(f"  {client_id}: already has Builder creds after re-read — skipped")
            continue
        prop_accounts.append(row)
        cur.execute(
            "UPDATE clients_data SET prop_accounts=%s WHERE client_id=%s",
            (json.dumps(prop_accounts), client_id),
        )
        print(f"  {client_id}: wrote Builder prop_accounts row")

    conn.commit()
    cur.close()
    conn.close()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
