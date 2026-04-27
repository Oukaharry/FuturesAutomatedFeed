"""
Export clients_data identity emails to JSON for use with backfill_identity_email.py on production.

Run on your *local* machine (where identity emails are correct), from app root, with venv:

  python scripts/export_identity_emails_json.py
  python scripts/export_identity_emails_json.py --out /tmp/client_emails.json

Copy the file to the server, then on production:
  python scripts/backfill_identity_email.py --json client_emails.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(ROOT, "dashboard")
if DASH not in sys.path:
    sys.path.insert(0, DASH)
os.chdir(DASH)

from database import get_all_client_identities  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default=os.path.join(ROOT, "client_emails_from_local_identity.json"),
        help="Output path (default: <repo>/client_emails_from_local_identity.json)",
    )
    args = ap.parse_args()

    m = get_all_client_identities()
    out: dict[str, str] = {}
    for client_id, identity in m.items():
        em = str((identity or {}).get("email") or "").strip()
        if em:
            out[str(client_id)] = em
    out_path = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
    print(f"Wrote {len(out)} emails -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
