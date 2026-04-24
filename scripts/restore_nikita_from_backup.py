"""
scripts/restore_nikita_from_backup.py
-------------------------------------
Safely restore a single client's `clients_data` row (e.g. Nikita) from one of
the daily PythonAnywhere pg_dump backups without disturbing any other client.

Works against two targets:
  --target local   local PostgreSQL (default) — good for dry-running the
                   restore against a backup you've downloaded.
  --target prod    production PostgreSQL at PythonAnywhere (no SSH tunnel
                   needed when run *inside* a PythonAnywhere bash console;
                   on your laptop you need the SSH tunnel on port 5433).

It never touches the live table until you explicitly run the `restore` mode,
and `restore` always writes a JSON snapshot of the current live row first.

Subcommands
-----------
  scan
      Restore the ``clients_data`` table from every backup in --backup-dir into
      a scratch database and print the evaluation count for the target client.
      Use this to find the newest backup that still has the real data.

  show <backup.dump>
      Restore ``clients_data`` from that one file into the scratch DB and print
      a few recent evaluations so you can eyeball them.

  snapshot
      Dump the current live row for the target client to a local JSON file.
      Automatic inside `restore`, but available standalone.

  restore <backup.dump>
      Snapshot live -> restore ``clients_data`` from that backup to scratch ->
      UPSERT just the target client's row from scratch into live.

Environment variables (loaded from .env if present)
---------------------------------------------------
  local target :
      POSTGRES_HOST (localhost), POSTGRES_PORT (5432), POSTGRES_DB (tradeopss),
      POSTGRES_USER (postgres),  POSTGRES_PASSWORD (postgres123)
  prod target :
      PROD_DB_HOST (ballerquotes-5185.postgres.pythonanywhere-services.com),
      PROD_DB_PORT (15185),      PROD_DB_NAME (tradeopss),
      PROD_DB_USER (tradeopss_admin),
      PROD_DB_PASSWORD / SYNC_PROD_PGPASSWORD (REQUIRED)
  both targets :
      SCAN_DB_NAME (tradeopss_scan)   — scratch DB, dropped/recreated per run

Typical flow
------------
  # 1. dry run locally against today's downloaded dump
  python scripts/download_from_prod.py backup
  python scripts/restore_nikita_from_backup.py --target local scan \\
         --backup-dir pg_backups
  python scripts/restore_nikita_from_backup.py --target local show \\
         pg_backups/pgbackup-2026-04-24-0001.dump
  python scripts/restore_nikita_from_backup.py --target local restore \\
         pg_backups/pgbackup-2026-04-24-0001.dump

  # 2. once local looks right, do the real thing on prod
  #    (inside a PythonAnywhere bash console, in ~/MT5Dashboard)
  export PROD_DB_PASSWORD='...'
  python3 scripts/restore_nikita_from_backup.py --target prod scan \\
         --backup-dir ~/pg_backups
  python3 scripts/restore_nikita_from_backup.py --target prod restore \\
         ~/pg_backups/pgbackup-2026-04-22-0001.dump
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 is not installed. Run: pip install --user psycopg2-binary", file=sys.stderr)
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass


# ─── target-aware config (populated by main() before any helper runs) ──────
HOST: str = ""
PORT: int = 0
DB:   str = ""
USER: str = ""
PASS: str = ""
SCAN: str = os.getenv("SCAN_DB_NAME", "tradeopss_scan")
TARGET: str = "local"


def _configure_target(target: str) -> None:
    global HOST, PORT, DB, USER, PASS, TARGET
    TARGET = target
    if target == "local":
        HOST = os.getenv("POSTGRES_HOST", "localhost")
        PORT = int(os.getenv("POSTGRES_PORT", "5432"))
        DB   = os.getenv("POSTGRES_DB", "tradeopss")
        USER = os.getenv("POSTGRES_USER", "postgres")
        PASS = os.getenv("POSTGRES_PASSWORD", "postgres123")
    elif target == "prod":
        HOST = os.getenv("PROD_DB_HOST", "ballerquotes-5185.postgres.pythonanywhere-services.com")
        PORT = int(os.getenv("PROD_DB_PORT", "15185"))
        DB   = os.getenv("PROD_DB_NAME", "tradeopss")
        USER = os.getenv("PROD_DB_USER", "tradeopss_admin")
        PASS = os.getenv("PROD_DB_PASSWORD") or os.getenv("SYNC_PROD_PGPASSWORD", "")
    else:
        raise ValueError(f"unknown target {target!r}")


def _require_password() -> None:
    if not PASS:
        var = "PROD_DB_PASSWORD" if TARGET == "prod" else "POSTGRES_PASSWORD"
        print(f"ERROR: {var} is not set for --target {TARGET}. Export it first.",
              file=sys.stderr)
        sys.exit(2)


def _connect(database: str):
    return psycopg2.connect(
        host=HOST, port=PORT, dbname=database, user=USER, password=PASS,
        connect_timeout=15,
    )


def _run(cmd: list[str], *, check: bool = True, quiet: bool = False) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PGPASSWORD"] = PASS
    if not quiet:
        print("  $", " ".join(cmd))
    return subprocess.run(
        cmd, env=env, check=check,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


# ─── scratch DB helpers ────────────────────────────────────────────────────
def _pg_admin_conn():
    """
    Connect to the maintenance DB with autocommit *before* any statement runs.
    CREATE/DROP DATABASE must not run inside a transaction; using `with conn`
    as a context manager can still leave the first query in a transaction in
    some driver/version combos unless autocommit is set immediately.
    """
    conn = _connect("postgres")
    conn.autocommit = True
    return conn


def _ensure_scan_db() -> None:
    """(Re)create an empty scratch database."""
    print(f"[scratch] Dropping + creating {SCAN}...")
    conn = _pg_admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()", (SCAN,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{SCAN}"')
            cur.execute(f'CREATE DATABASE "{SCAN}"')
    finally:
        conn.close()


def _drop_scan_db() -> None:
    try:
        conn = _pg_admin_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=%s AND pid<>pg_backend_pid()", (SCAN,),
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{SCAN}"')
        finally:
            conn.close()
    except Exception as exc:
        print(f"[scratch] Warning: failed to drop {SCAN}: {exc}", file=sys.stderr)


def _restore_clients_data(backup_path: Path) -> None:
    """Drop + recreate SCAN, then pg_restore only the clients_data table into it."""
    _ensure_scan_db()
    cmd = [
        "pg_restore",
        "-h", HOST, "-p", str(PORT), "-U", USER,
        "-d", SCAN,
        "--table=clients_data",
        "--no-owner", "--no-acl",
        "--clean", "--if-exists",
        str(backup_path),
    ]
    res = _run(cmd, check=False)
    # pg_restore returns non-zero on harmless "does not exist" warnings; only
    # bail if the table itself didn't materialize in scratch.
    with _connect(SCAN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='clients_data'"
        )
        if cur.fetchone() is None:
            print(res.stderr, file=sys.stderr)
            raise RuntimeError(f"pg_restore did not produce clients_data from {backup_path.name}")


def _count_eval(database: str, client: str) -> tuple[int, str | None, int | None]:
    """Return (eval_count, last_updated, byte_length) for a client."""
    with _connect(database) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(json_array_length(evaluations::json),0), "
            "       last_updated, length(evaluations) "
            "FROM clients_data WHERE client_id=%s",
            (client,),
        )
        row = cur.fetchone()
    if row is None:
        return (0, None, None)
    return row  # type: ignore[return-value]


# ─── subcommands ───────────────────────────────────────────────────────────
def cmd_scan(args: argparse.Namespace) -> int:
    _require_password()
    backup_dir = Path(args.backup_dir).expanduser()
    dumps = sorted(p for p in backup_dir.glob("*.dump") if p.is_file())
    if not dumps:
        print(f"No .dump files in {backup_dir}", file=sys.stderr)
        return 1

    print(f"Scanning {len(dumps)} backups in {backup_dir} for client {args.client!r}...")
    results: list[tuple[str, int, str | None, int | None]] = []
    try:
        for dump in dumps:
            print(f"\n[{dump.name}]")
            try:
                _restore_clients_data(dump)
                count, last_updated, nbytes = _count_eval(SCAN, args.client)
                print(f"  -> {count} evaluations  (bytes={nbytes}  last_updated={last_updated})")
                results.append((dump.name, count, last_updated, nbytes))
            except Exception as exc:
                print(f"  -> FAILED: {exc}")
                results.append((dump.name, -1, None, None))
    finally:
        _drop_scan_db()

    print("\n" + "=" * 78)
    print(f"{'backup':32s}  {'evals':>6s}  {'bytes':>8s}  last_updated")
    print("-" * 78)
    for name, count, lu, nb in results:
        ev = "ERR" if count < 0 else str(count)
        nbs = "" if nb is None else str(nb)
        print(f"{name:32s}  {ev:>6s}  {nbs:>8s}  {lu or ''}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    _require_password()
    dump = Path(args.backup).expanduser()
    try:
        _restore_clients_data(dump)
        with _connect(SCAN) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT client_id, last_updated, "
                "       COALESCE(json_array_length(evaluations::json),0) AS n, "
                "       length(evaluations) AS nbytes "
                "FROM clients_data WHERE client_id=%s", (args.client,),
            )
            meta = cur.fetchone()
            if not meta:
                print(f"Client {args.client!r} NOT found in {dump.name}")
                return 1
            print(f"{meta['client_id']}: {meta['n']} evaluations  "
                  f"(bytes={meta['nbytes']}  last_updated={meta['last_updated']})")

            cur.execute(
                """
                WITH m AS (
                  SELECT evaluations::json AS evals FROM clients_data
                  WHERE client_id=%s LIMIT 1
                )
                SELECT ordinality-1 AS idx,
                       elem->>'Account #'     AS chal,
                       elem->>'Account #.1'   AS fund,
                       elem->>'Prop Firm'     AS firm,
                       elem->>'Date Purchased' AS purchased,
                       elem->>'Date Started'  AS started,
                       elem->>'Status'        AS status
                FROM m, json_array_elements(m.evals) WITH ORDINALITY AS t(elem, ordinality)
                ORDER BY ordinality DESC LIMIT %s
                """,
                (args.client, args.limit),
            )
            for r in cur.fetchall():
                print(
                    f"  idx={r['idx']:>3}  "
                    f"chal={(r['chal'] or '')[:12]:12s}  "
                    f"fund={(r['fund'] or '')[:12]:12s}  "
                    f"firm={(r['firm'] or '')[:14]:14s}  "
                    f"purchased={r['purchased']}  started={r['started']}  status={r['status']}"
                )
        return 0
    finally:
        _drop_scan_db()


def _snapshot_live(client: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"live_{client}_{ts}.json"
    with _connect(DB) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM clients_data WHERE client_id=%s", (client,))
        row = cur.fetchone()
    out.write_text(json.dumps(row, default=str, indent=2))
    print(f"[snapshot] live row for {client!r} saved to {out}")
    return out


def cmd_snapshot(args: argparse.Namespace) -> int:
    _require_password()
    _snapshot_live(args.client, Path(args.out_dir).expanduser())
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    _require_password()
    dump = Path(args.backup).expanduser()

    _snapshot_live(args.client, Path(args.out_dir).expanduser())

    try:
        _restore_clients_data(dump)

        with _connect(SCAN) as scan_conn, scan_conn.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as scan_cur:
            scan_cur.execute(
                "SELECT * FROM clients_data WHERE client_id=%s", (args.client,)
            )
            src = scan_cur.fetchone()
            if not src:
                print(f"ERROR: {args.client!r} not found in {dump.name}; nothing to restore.",
                      file=sys.stderr)
                return 1
            try:
                n = len(json.loads(src["evaluations"] or "[]"))
            except Exception:
                n = -1
            print(f"[restore] source has {n} evaluations "
                  f"(last_updated={src['last_updated']}) — about to UPSERT into {DB}.")

        if not args.yes:
            resp = input("Proceed with UPSERT into live DB? [y/N] ").strip().lower()
            if resp != "y":
                print("Aborted.")
                return 1

        cols = [c for c in src.keys() if c != "id"]
        placeholders = ", ".join(["%s"] * len(cols))
        updates = ", ".join(f'"{c}"=EXCLUDED."{c}"' for c in cols if c != "client_id")
        sql = (
            f'INSERT INTO clients_data ({", ".join(f"""\"{c}\"""" for c in cols)}) '
            f"VALUES ({placeholders}) "
            f"ON CONFLICT (client_id) DO UPDATE SET {updates}"
        )
        values = [src[c] for c in cols]
        with _connect(DB) as conn, conn.cursor() as cur:
            cur.execute(sql, values)
            conn.commit()

        count, lu, _ = _count_eval(DB, args.client)
        print(f"[restore] DONE. Live {args.client!r} now has {count} evaluations "
              f"(last_updated={lu}).")
        return 0
    finally:
        _drop_scan_db()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--target", choices=("local", "prod"), default="local",
                    help="Which DB to operate on (default: local)")
    ap.add_argument("--client", default="Nikita", help="client_id to operate on (default Nikita)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="Count client's evaluations in every backup")
    p.add_argument("--backup-dir", default="~/pg_backups")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("show", help="Show recent evaluations for the client in one backup")
    p.add_argument("backup", help="Path to a .dump file")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("snapshot", help="Save the live row for the client to JSON")
    p.add_argument("--out-dir", default="~/restore_snapshots")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("restore", help="Restore the client's row from a backup")
    p.add_argument("backup", help="Path to a .dump file")
    p.add_argument("--out-dir", default="~/restore_snapshots")
    p.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    p.set_defaults(func=cmd_restore)

    args = ap.parse_args()
    _configure_target(args.target)
    print(f"[target] {TARGET}: {USER}@{HOST}:{PORT}/{DB}  (scratch DB: {SCAN})")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
