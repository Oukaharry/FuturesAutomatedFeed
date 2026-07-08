#!/usr/bin/env python3
"""Emergency: free Postgres connection slots on PythonAnywhere.

Run from a PA Bash console (with DATABASE_URL in the environment, or as argv):

  cd ~/MT5Dashboard
  python3 scripts/pa_free_pg_slots.py

Or:

  python3 scripts/pa_free_pg_slots.py "$DATABASE_URL"

Terminates idle/idle-in-transaction backends for this database (not your own
session). Use when the web app logs:

  FATAL: remaining connection slots are reserved for non-replication superuser
"""
from __future__ import annotations

import os
import sys

import psycopg2


def main() -> int:
    url = (sys.argv[1] if len(sys.argv) > 1 else None) or os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: set DATABASE_URL or pass it as the first argument", file=sys.stderr)
        return 1

    conn = psycopg2.connect(url, connect_timeout=10)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pid, usename, application_name, state, state_change,
                       left(coalesce(query, ''), 80) AS query
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                ORDER BY state_change NULLS LAST
                """
            )
            rows = cur.fetchall()
            print(f"Backends for this DB (excluding self): {len(rows)}")
            for r in rows:
                print(f"  pid={r[0]} user={r[1]} app={r[2]!r} state={r[3]} since={r[4]} q={r[5]!r}")

            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                  AND state IN ('idle', 'idle in transaction', 'idle in transaction (aborted)')
                """
            )
            killed = sum(1 for row in cur.fetchall() if row[0])
            print(f"Terminated idle backends: {killed}")

            cur.execute(
                """
                SELECT count(*)
                FROM pg_stat_activity
                WHERE datname = current_database()
                """
            )
            print(f"Remaining backends on this DB: {cur.fetchone()[0]}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
