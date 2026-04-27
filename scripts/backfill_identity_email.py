"""
Set clients_data.identity["email"] from (1) hierarchy.json and/or (2) a JSON file.

Version History reads identity.email, not hierarchy. Emails in hierarchy (from the team tree UI)
or in your local DB can be missing from identity if rows were created by import/sync that did
not merge email into the identity blob.

Usage (app root, same env as the app — DATABASE_URL / dashboard/.env loaded via database.py):

  # Preview only
  python scripts/backfill_identity_email.py --dry-run

  # Apply: fill from config/hierarchy.json (reloads file from disk)
  python scripts/backfill_identity_email.py

  # After exporting emails from your local DB (see export_identity_emails_json.py), merge gaps
  python scripts/backfill_identity_email.py --json path/to/client_emails.json

  python scripts/backfill_identity_email.py --dry-run --json client_emails.json  # preview merge

On PythonAnywhere:
  export PYTHONPATH=~/MT5Dashboard/dashboard:~/MT5Dashboard
  cd ~/MT5Dashboard
  # Or: PYTHONPATH=~/MT5Dashboard python scripts/backfill_identity_email.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(ROOT, "dashboard")
for p in (DASH, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
os.chdir(DASH)

from config.hierarchy import get_client_profile, reload_hierarchy  # noqa: E402
from database import (  # noqa: E402
    get_all_client_identities,
    get_client_data,
    update_client_field,
    update_user_email,
)


def _build_email_map_from_json(path: str) -> dict[str, str]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("JSON root must be an object: {\"Client Name\": \"email@...\"}")
    return {str(k).strip(): str(v).strip() for k, v in raw.items() if str(v or "").strip()}


def _resolve_email(client_id: str, json_map: dict[str, str]) -> tuple[str, str]:
    """
    Return (email, source) or ("", "") if unknown.
    """
    prof = get_client_profile(client_id)
    h_email = (prof or {}).get("email") or ""
    h_email = h_email.strip()
    if h_email:
        return h_email, "hierarchy"
    j_email = json_map.get(client_id, "") or json_map.get(client_id.strip(), "")
    if j_email.strip():
        return j_email.strip(), "json"
    return "", ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill clients_data.identity email from hierarchy and/or JSON.")
    ap.add_argument("--json", dest="json_path", default=None, help="Optional {client_id: email} from local export")
    ap.add_argument("--dry-run", action="store_true", help="Print actions only, do not write DB")
    args = ap.parse_args()

    json_map: dict[str, str] = {}
    if args.json_path:
        json_map = _build_email_map_from_json(args.json_path)
        print(f"Loaded {len(json_map)} client emails from {args.json_path}")

    reload_hierarchy()

    identities = get_all_client_identities()
    missing: list[str] = []
    for client_id, identity in identities.items():
        if not str((identity or {}).get("email") or "").strip():
            missing.append(str(client_id))
    missing.sort()

    print(f"Clients missing identity.email: {len(missing)}")
    if not missing:
        print("Nothing to do.")
        return 0

    done = 0
    still = []
    for client_id in missing:
        email, source = _resolve_email(client_id, json_map)
        if not email:
            still.append(client_id)
            print(f"  [skip] {client_id!r} — no email in hierarchy or JSON")
            continue
        if args.dry_run:
            print(f"  [dry-run] {client_id!r} <= {email!r} ({source})")
            done += 1
            continue
        data = get_client_data(client_id)
        if not data:
            print(f"  [skip] {client_id!r} — no clients_data row")
            still.append(client_id)
            continue
        ident = dict(data.get("identity") or {})
        ident["email"] = email
        if "client" not in ident:
            ident["client"] = client_id
        update_client_field(client_id, "identity", ident)
        update_user_email(client_id, "client", email)
        print(f"  [ok] {client_id!r} <= {email!r} ({source})")
        done += 1

    if args.dry_run:
        print(f"\nDry run: would update {done} client(s); skipped (no source): {len(still)}")
    else:
        print(f"\nUpdated identity.email for {done} client(s). Unresolved: {len(still)}")
        if still:
            for c in still:
                print(f"  {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
