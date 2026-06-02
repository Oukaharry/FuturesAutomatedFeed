#!/usr/bin/env python3
"""
Run research/learn_from_db.py against production PostgreSQL.

Requires PRODUCTION_DATABASE_URL in .env (from PythonAnywhere → Databases).

Usage:
    python scripts/run_research_production.py
    python scripts/run_research_production.py --client "Chris Ream"

Optional — refresh from prod backup file first (offline copy):
    python scripts/download_from_prod.py backup
    pg_restore ...  # into a local DB, then:
    python scripts/run_research_production.py --database-url postgresql://...
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default="")
    ap.add_argument("--out", default=os.path.join(_ROOT, "research", "reports", "production_analysis.html"))
    ap.add_argument("--database-url", default="", help="Use restored backup DB instead of live prod URL")
    args = ap.parse_args()

    cmd = [sys.executable, os.path.join(_ROOT, "research", "learn_from_db.py")]
    if args.client:
        cmd.extend(["--client", args.client])
    if args.out:
        cmd.extend(["--out", args.out])
    if args.database_url:
        cmd.extend(["--database-url", args.database_url])
    else:
        cmd.append("--production")

    print("Running research against PRODUCTION data source...")
    print("Command:", " ".join(cmd))
    raise SystemExit(subprocess.call(cmd, cwd=_ROOT))


if __name__ == "__main__":
    main()
