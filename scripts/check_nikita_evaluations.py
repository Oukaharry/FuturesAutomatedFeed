"""
scripts/check_nikita_evaluations.py
-----------------------------------
Run the same "how many evaluations does Nikita have?" query against local
PostgreSQL and/or production PostgreSQL (PythonAnywhere via SSH tunnel), and
print a side-by-side comparison so you can see *why* Nikita looks empty in
the production dashboard.

Both targets execute the exact same SQL — the counterpart file
``scripts/prod_check_nikita_evaluations.sql`` has the raw version.

Usage
-----
  # both (default)
  python scripts/check_nikita_evaluations.py

  # just local
  python scripts/check_nikita_evaluations.py --target local

  # just prod (requires the SSH tunnel open on 127.0.0.1:5433)
  python scripts/check_nikita_evaluations.py --target prod

  # different client name (defaults to 'Nikita')
  python scripts/check_nikita_evaluations.py --client Tsubasa

Environment variables (loaded from .env if present)
---------------------------------------------------
Local  : POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
Prod   : SYNC_PROD_HOST (127.0.0.1), SYNC_PROD_PORT (5433),
         SYNC_PROD_DB  (tradeopss),  SYNC_PROD_USER (tradeopss_admin),
         SYNC_PROD_PGPASSWORD (required for prod)

Prod prerequisite (same as sync_prod_to_local.sh):
  ssh -L 5433:ballerquotes-5185.postgres.pythonanywhere-services.com:15185 \\
      ballerquotes@ssh.pythonanywhere.com -N
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 is not installed. Run: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass


@dataclass
class Target:
    label: str
    host: str
    port: int
    dbname: str
    user: str
    password: str

    def connect(self):
        return psycopg2.connect(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            password=self.password,
            connect_timeout=10,
        )


def _local_target() -> Target:
    return Target(
        label="LOCAL",
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "tradeopss"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres123"),
    )


def _prod_target() -> Target:
    pw = os.getenv("SYNC_PROD_PGPASSWORD", "")
    if not pw:
        print(
            "ERROR: SYNC_PROD_PGPASSWORD is not set. Export the production DB\n"
            "       password for tradeopss_admin before running --target prod.",
            file=sys.stderr,
        )
        sys.exit(2)
    return Target(
        label="PROD",
        host=os.getenv("SYNC_PROD_HOST", "127.0.0.1"),
        port=int(os.getenv("SYNC_PROD_PORT", "5433")),
        dbname=os.getenv("SYNC_PROD_DB", "tradeopss"),
        user=os.getenv("SYNC_PROD_USER", "tradeopss_admin"),
        password=pw,
    )


COUNT_SQL = """
SELECT
    client_id,
    COALESCE(json_array_length(evaluations::json), 0) AS evaluation_count,
    length(evaluations)                               AS evaluations_text_bytes,
    last_updated
FROM clients_data
WHERE client_id ILIKE %s
ORDER BY client_id
"""

RECENT_SQL = """
WITH match AS (
    SELECT evaluations::json AS evals
    FROM clients_data
    WHERE client_id ILIKE %s
    LIMIT 1
)
SELECT
    ordinality - 1                           AS idx,
    elem ->> 'Account #'                     AS challenge_account,
    elem ->> 'Account #.1'                   AS funded_account,
    elem ->> 'Prop Firm'                     AS prop_firm,
    elem ->> 'Date Purchased'                AS date_purchased,
    elem ->> 'Date Started'                  AS date_started,
    elem ->> 'Status'                        AS status
FROM match,
     json_array_elements(match.evals) WITH ORDINALITY AS t(elem, ordinality)
ORDER BY ordinality DESC
LIMIT %s
"""

EVAL_TABLE_SQL = """
SELECT
    account_signature,
    phase_number,
    phase_type,
    status,
    start_date,
    end_date
FROM evaluations
WHERE account_signature ILIKE %s
ORDER BY id DESC
LIMIT %s
"""


def run_target(target: Target, client: str, limit: int) -> dict:
    pattern = f"{client}%"
    out: dict = {"label": target.label, "error": None, "rows": [], "recent": [], "eval_table": []}
    try:
        with target.connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(COUNT_SQL, (pattern,))
                out["rows"] = [dict(r) for r in cur.fetchall()]

                cur.execute(RECENT_SQL, (pattern, limit))
                out["recent"] = [dict(r) for r in cur.fetchall()]

                cur.execute(EVAL_TABLE_SQL, (f"%{client}%", limit))
                out["eval_table"] = [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _print_result(result: dict, target: Target) -> None:
    label = result["label"]
    header = f" {label}  ({target.user}@{target.host}:{target.port}/{target.dbname}) "
    print("\n" + header.center(78, "="))

    if result["error"]:
        print(f"  ERROR: {result['error']}")
        return

    rows = result["rows"]
    if not rows:
        print("  (no clients_data row matched)")
    else:
        print(f"  clients_data matches: {len(rows)}")
        for r in rows:
            print(
                f"    - client_id={r['client_id']!r:20s} "
                f"evaluation_count={r['evaluation_count']:>4}  "
                f"bytes={r['evaluations_text_bytes']:>8}  "
                f"last_updated={r['last_updated']}"
            )

    recent = result["recent"]
    if recent:
        print(f"\n  Last {len(recent)} evaluations (newest first):")
        for r in recent:
            print(
                f"    idx={r['idx']:>3}  "
                f"chal={(r['challenge_account'] or '')[:12]:12s}  "
                f"fund={(r['funded_account']  or '')[:12]:12s}  "
                f"firm={(r['prop_firm']       or '')[:14]:14s}  "
                f"purchased={r['date_purchased']}  started={r['date_started']}  "
                f"status={r['status']}"
            )

    evt = result["eval_table"]
    if evt:
        print(f"\n  evaluations table rows with signature LIKE %{target.label.lower()}%:")
        for r in evt:
            print(
                f"    sig={r['account_signature']:40s} "
                f"phase={r['phase_number']} {r['phase_type']} "
                f"status={r['status']} "
                f"{r['start_date']} -> {r['end_date']}"
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", choices=("local", "prod", "both"), default="both",
                    help="Which DB to query (default: both)")
    ap.add_argument("--client", default="Nikita",
                    help="Client name prefix to search for (default: Nikita)")
    ap.add_argument("--limit", type=int, default=10,
                    help="How many recent evaluations to show per target (default: 10)")
    ap.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON instead of a formatted report")
    args = ap.parse_args()

    targets: list[Target] = []
    if args.target in ("local", "both"):
        targets.append(_local_target())
    if args.target in ("prod", "both"):
        targets.append(_prod_target())

    results = [(t, run_target(t, args.client, args.limit)) for t in targets]

    if args.json:
        print(json.dumps(
            [{"target": t.label, **r} for t, r in results],
            default=str,
            indent=2,
        ))
        return 0 if all(r["error"] is None for _, r in results) else 1

    print(f"\nLooking for client_id ILIKE '{args.client}%' across {len(results)} target(s)...")
    for t, r in results:
        _print_result(r, t)

    if len(results) == 2 and all(r["error"] is None for _, r in results):
        local_count = sum(row["evaluation_count"] for row in results[0][1]["rows"]) or 0
        prod_count  = sum(row["evaluation_count"] for row in results[1][1]["rows"]) or 0
        delta = prod_count - local_count
        print("\n" + " SUMMARY ".center(78, "="))
        print(f"  local evaluations: {local_count}")
        print(f"  prod  evaluations: {prod_count}")
        print(f"  prod - local     : {delta:+d}")
        if local_count > 0 and prod_count == 0:
            print("  >> Nikita has evaluations locally but NONE in prod — "
                  "that's almost certainly why the prod dashboard looks empty.")

    return 0 if all(r["error"] is None for _, r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
