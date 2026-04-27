"""
List clients where clients_data.identity JSON has no non-blank "email" field
(the Version History panel needs this).

Run from repo root with the same Python/env as the dashboard (DATABASE_URL or dashboard/.env):

  python scripts/audit_client_identity_email.py

On PythonAnywhere (bash), from the app root:

  cd /home/ballerquotes/MT5Dashboard && python scripts/audit_client_identity_email.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(ROOT, "dashboard")
if DASH not in sys.path:
    sys.path.insert(0, DASH)
os.chdir(DASH)

from database import get_all_client_identities  # noqa: E402


def main() -> None:
    m = get_all_client_identities()
    missing: list[str] = []
    for client_id, identity in m.items():
        if not identity or not str(identity.get("email") or "").strip():
            missing.append(str(client_id))
    missing.sort()
    print(f"Total clients: {len(m)}")
    print(f"Missing or blank identity.email: {len(missing)}")
    for cid in missing:
        print(f"  {cid}")
    if not missing:
        print("OK — all clients have a non-blank email in identity.")


if __name__ == "__main__":
    main()
