#!/usr/bin/env python3
"""Production worker / overload probe (read-only, safe to run on PythonAnywhere).

Usage (from repo root on production bash console):

    cd ~/MT5Dashboard
    set -a && source .env && set +a
    python3 scripts/probe_worker_health.py

Paste one-liner (after cd + source .env):

    python3 -c "import os,sys; sys.path.insert(0,os.getcwd()); exec(open('scripts/probe_worker_health.py').read())"

Or compact import (if this file is deployed):

    python3 -c "import os,sys; sys.path.insert(0,os.getcwd()); from scripts.probe_worker_health import main; main()"
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

LOG_PATH = os.path.join(ROOT, "dashboard", "server_recent.log")
WARN_PG_BACKENDS = 14
CRIT_PG_BACKENDS = 18


def _hr(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def _status(level: str, msg: str) -> None:
    print(f"  [{level}] {msg}")


def _row_val(row, key, idx=0):
    """RealDictCursor rows are dicts; never use row[0] on production."""
    if row is None:
        return None
    if hasattr(row, "keys"):
        if key in row:
            return row[key]
        # SHOW max_connections etc. — single anonymous column
        vals = list(row.values())
        return vals[idx] if vals else None
    return row[idx]


def _probe_postgres() -> dict:
    from dashboard.database import get_direct_connection

    out = {"backends": 0, "by_state": {}, "max_connections": None, "claims": [], "caches": []}
    with get_direct_connection() as conn:
        cur = conn.cursor()
        cur.execute("SHOW max_connections")
        row = cur.fetchone()
        out["max_connections"] = int(_row_val(row, "max_connections"))

        cur.execute(
            """
            SELECT state, count(*) AS n
            FROM pg_stat_activity
            WHERE datname = current_database()
            GROUP BY state
            ORDER BY n DESC
            """
        )
        for r in cur.fetchall():
            state = _row_val(r, "state")
            n = _row_val(r, "n")
            out["by_state"][state or "?"] = n
            out["backends"] += n

        cur.execute(
            """
            SELECT application_name, state, count(*) AS n
            FROM pg_stat_activity
            WHERE datname = current_database()
            GROUP BY application_name, state
            ORDER BY n DESC
            LIMIT 12
            """
        )
        out["by_app"] = [
            {
                "app": _row_val(r, "application_name") or "(none)",
                "state": _row_val(r, "state") or "?",
                "n": _row_val(r, "n"),
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT cache_key, expires_at > NOW() AS fresh, updated_at,
                   length(payload) AS bytes
            FROM api_response_cache
            WHERE cache_key LIKE '%::computing'
               OR cache_key LIKE 'heavy_compute::%'
               OR cache_key LIKE 'cache-warm::%'
               OR cache_key LIKE 'super_admin_%'
            ORDER BY updated_at DESC
            LIMIT 20
            """
        )
        for r in cur.fetchall():
            out["claims"].append(
                {
                    "key": _row_val(r, "cache_key"),
                    "fresh": _row_val(r, "fresh"),
                    "updated_at": _row_val(r, "updated_at"),
                    "bytes": _row_val(r, "bytes"),
                }
            )

        cur.execute(
            """
            SELECT cache_key, expires_at > NOW() AS fresh, updated_at
            FROM api_response_cache
            WHERE cache_key IN (
                'super_admin_totals_bundle:v3:ALL',
                'super_admin_splits_bundle:v1:ALL',
                'hierarchy:enriched:full'
            )
            """
        )
        for r in cur.fetchall():
            out["caches"].append(
                {
                    "key": _row_val(r, "cache_key"),
                    "fresh": _row_val(r, "fresh"),
                    "updated_at": _row_val(r, "updated_at"),
                }
            )
    return out


def _probe_recent_log(tail_lines: int = 800) -> dict:
    out = {
        "path": LOG_PATH,
        "exists": os.path.isfile(LOG_PATH),
        "counts": Counter(),
        "slow_super_admin": [],
        "recent_errors": [],
    }
    if not out["exists"]:
        return out

    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-tail_lines:]
    except OSError as e:
        out["read_error"] = str(e)
        return out

    pat_502 = re.compile(r"\b502\b|502-backend", re.I)
    pat_503 = re.compile(r"-> 503\b|status.?503", re.I)
    pat_slots = re.compile(r"connection slots|slots exhausted|cooling down", re.I)
    pat_compute = re.compile(r"\[shared_cache\] computing ", re.I)
    pat_computed = re.compile(r"\[shared_cache\] computed ", re.I)
    pat_sa = re.compile(r"GET /api/super_admin/\S+ -> (\d+) \(([0-9.]+)ms\)", re.I)

    for line in lines:
        if pat_502.search(line):
            out["counts"]["502"] += 1
        if pat_503.search(line):
            out["counts"]["503"] += 1
        if pat_slots.search(line):
            out["counts"]["pg_slots"] += 1
        if pat_compute.search(line):
            out["counts"]["cache_computing"] += 1
        if pat_computed.search(line):
            out["counts"]["cache_computed"] += 1
        if "ERROR" in line or "Traceback" in line:
            out["recent_errors"].append(line.rstrip()[-160:])

        m = pat_sa.search(line)
        if m:
            status, ms = m.group(1), float(m.group(2))
            if ms >= 5000 or status == "503":
                out["slow_super_admin"].append(line.rstrip()[-120:])

    out["recent_errors"] = out["recent_errors"][-8:]
    out["slow_super_admin"] = out["slow_super_admin"][-8:]
    return out


def main() -> int:
    now = datetime.now(timezone.utc).astimezone()
    print(f"Worker health probe @ {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"cwd={os.getcwd()}  PYTHONANYWHERE_SITE={os.environ.get('PYTHONANYWHERE_SITE', '(not set)')}")

    issues: list[str] = []
    ok_notes: list[str] = []

    _hr("Postgres connections")
    try:
        pg = _probe_postgres()
        mx = pg["max_connections"] or "?"
        print(f"  Backends on this DB: {pg['backends']} / max_connections={mx}")
        for state, n in sorted(pg["by_state"].items(), key=lambda x: -x[1]):
            print(f"    {state}: {n}")
        print("  Top application_name × state:")
        for row in pg.get("by_app") or []:
            print(f"    {row['n']:>3}  {row['app']!r}  {row['state']}")

        if pg["backends"] >= CRIT_PG_BACKENDS:
            issues.append(f"Postgres backends CRITICAL ({pg['backends']}/{mx}) — workers likely starved")
        elif pg["backends"] >= WARN_PG_BACKENDS:
            issues.append(f"Postgres backends HIGH ({pg['backends']}/{mx}) — watch for slot exhaustion")
        else:
            ok_notes.append(f"Postgres backends OK ({pg['backends']}/{mx})")

        _hr("Shared cache / heavy compute locks")
        active_claims = [c for c in pg["claims"] if c["key"].endswith("::computing") and c["fresh"]]
        if active_claims:
            print("  Active compute claims (another worker may be scanning now):")
            for c in active_claims:
                print(f"    {c['key']}  updated={c['updated_at']}")
            if len(active_claims) > 1:
                issues.append(f"{len(active_claims)} parallel compute claims — check heavy_compute lock")
        else:
            ok_notes.append("No active ::computing claims")

        heavy = [c for c in pg["claims"] if c["key"].startswith("heavy_compute::")]
        if heavy:
            for c in heavy:
                tag = "HELD" if c["fresh"] else "free"
                print(f"  heavy_compute global: {tag}  updated={c['updated_at']}")

        print("  Super-admin cache rows:")
        if pg["caches"]:
            for c in pg["caches"]:
                tag = "FRESH" if c["fresh"] else "STALE"
                print(f"    [{tag}] {c['key']}  updated={c['updated_at']}")
        else:
            print("    (none — cold cache; first Super Admin load will compute in background)")

        if pg["claims"]:
            print("  Recent cache/lock rows:")
            for c in pg["claims"][:10]:
                tag = "fresh" if c["fresh"] else "expired"
                print(f"    [{tag}] {c['key']}  updated={c['updated_at']}  {c['bytes']}B")

    except Exception as e:
        issues.append(f"Postgres probe failed: {e}")
        import traceback

        traceback.print_exc()

    _hr(f"Recent app log (tail {LOG_PATH})")
    log = _probe_recent_log()
    if not log["exists"]:
        print(f"  Log not found: {LOG_PATH}")
    else:
        c = log["counts"]
        print(
            f"  Last ~800 lines: 502={c.get('502', 0)}  "
            f"503={c.get('503', 0)}  pg_slot_errors={c.get('pg_slots', 0)}  "
            f"cache_computing={c.get('cache_computing', 0)}  "
            f"cache_computed={c.get('cache_computed', 0)}"
        )
        if c.get("502", 0) > 0:
            issues.append(f"{c['502']} x 502 in recent log")
        if c.get("503", 0) >= 10:
            issues.append(f"{c['503']} x 503 in recent log (clients retrying cold cache)")
        if c.get("pg_slots", 0) > 0:
            issues.append(f"{c['pg_slots']} pg slot exhaustion messages in recent log")
        if log["slow_super_admin"]:
            print("  Slow / 503 super_admin API (recent):")
            for ln in log["slow_super_admin"]:
                print(f"    {ln}")
        if log["recent_errors"]:
            print("  Recent ERROR lines:")
            for ln in log["recent_errors"]:
                print(f"    {ln}")

    _hr("VERDICT")
    if issues:
        for msg in issues:
            _status("WARN", msg)
    if ok_notes:
        for msg in ok_notes:
            _status("OK", msg)
    if not issues:
        print("  Overall: OK — no overload signals in DB or recent log.")
        print("  Tip: reload Super Admin once; if stats appear in <1s, L2 cache is warm.")
    else:
        print()
        print("  If pg slots CRITICAL: python3 scripts/pa_free_pg_slots.py")
        print("  If many 503s on super_admin: wait for cache warm or reload after ~2 min.")
    print()
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
