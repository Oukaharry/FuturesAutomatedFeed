#!/usr/bin/env python3
"""
pg_backup.py — Daily PostgreSQL backup for PythonAnywhere.

Schedule as a daily task on PythonAnywhere:
    python /home/ballerquotes/FuturesAutomatedFeed/scripts/pg_backup.py

What it does:
  1. Calls pg_dump with your PythonAnywhere connection details.
  2. Saves the dump to ~/pg_backups/  (custom format, restorable with pg_restore).
  3. Deletes dumps older than KEEP_DAYS (default: 14) to save disk space.
  4. Logs every run to ~/pg_backups/backup.log.

To restore a dump:
    pg_restore --host=HOSTNAME --port=PORT --username=super \
               --dbname=tradeopss --clean pgbackup-YYYY-MM-DD-HHMM.dump
"""

import os
import subprocess
import sys
import glob
from datetime import datetime, timedelta
from urllib.parse import urlparse

# ─────────────────────────────────────────────────────────────
# CONFIGURATION — edit these or set env vars to override
# ─────────────────────────────────────────────────────────────

# Number of days worth of backups to keep (older files are deleted)
KEEP_DAYS = 14

# Where to store dump files.  On PythonAnywhere this should be under /home/<user>/
BACKUP_DIR = os.path.expanduser("~/pg_backups")

# Connection — read from DATABASE_URL env var first, then fall back to these defaults.
# DATABASE_URL format: postgresql://user:password@host:port/dbname
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://tradeopss_user:CHANGE_ME@ballerquotes-5185.postgres.pythonanywhere-services.com:15185/tradeopss",
)

# Override the pg_dump username here if needed (PythonAnywhere superuser is "super")
# Leave as None to use the username from DATABASE_URL.
PG_DUMP_USER = os.getenv("PG_BACKUP_USER", None)  # e.g. "super"

# ─────────────────────────────────────────────────────────────

def parse_db_url(url):
    """Parse DATABASE_URL into connection components."""
    parsed = urlparse(url)
    return {
        "host":     parsed.hostname,
        "port":     str(parsed.port or 5432),
        "user":     parsed.username,
        "password": parsed.password or "",
        "dbname":   parsed.path.lstrip("/"),
    }


def log(msg, log_path):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def run_backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    log_path = os.path.join(BACKUP_DIR, "backup.log")

    conn = parse_db_url(DATABASE_URL)
    if not conn["host"] or not conn["dbname"]:
        log("ERROR: Could not parse DATABASE_URL — check configuration.", log_path)
        sys.exit(1)

    user = PG_DUMP_USER or conn["user"]
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    dump_file = os.path.join(BACKUP_DIR, f"pgbackup-{timestamp}.dump")

    cmd = [
        "pg_dump",
        f"--host={conn['host']}",
        f"--port={conn['port']}",
        f"--username={user}",
        "--format=c",          # custom format — compressed, selective restore
        "--no-password",       # password is supplied via PGPASSWORD env var
        f"--file={dump_file}",
        conn["dbname"],
    ]

    # Pass password safely via environment variable — never on the command line
    env = os.environ.copy()
    env["PGPASSWORD"] = conn["password"]

    log(f"Starting backup: {conn['dbname']} @ {conn['host']}:{conn['port']}", log_path)
    log(f"Dump file: {dump_file}", log_path)

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,   # 10-minute hard limit
        )
    except FileNotFoundError:
        log("ERROR: pg_dump not found. Make sure PostgreSQL client tools are installed.", log_path)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        log("ERROR: pg_dump timed out after 10 minutes.", log_path)
        sys.exit(1)

    if result.returncode != 0:
        log(f"ERROR: pg_dump failed (exit {result.returncode})", log_path)
        if result.stderr:
            for line in result.stderr.strip().splitlines():
                log(f"  stderr: {line}", log_path)
        # Remove empty/partial dump file
        if os.path.exists(dump_file) and os.path.getsize(dump_file) == 0:
            os.remove(dump_file)
        sys.exit(1)

    size_mb = os.path.getsize(dump_file) / (1024 * 1024)
    log(f"SUCCESS: Backup complete — {size_mb:.2f} MB saved to {os.path.basename(dump_file)}", log_path)

    # ── Rotation: delete dumps older than KEEP_DAYS ───────────
    cutoff = datetime.now() - timedelta(days=KEEP_DAYS)
    removed = 0
    for old_file in glob.glob(os.path.join(BACKUP_DIR, "pgbackup-*.dump")):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(old_file))
            if mtime < cutoff:
                os.remove(old_file)
                removed += 1
                log(f"Rotated old backup: {os.path.basename(old_file)}", log_path)
        except OSError:
            pass
    if removed:
        log(f"Rotation: removed {removed} dump(s) older than {KEEP_DAYS} days.", log_path)

    # ── List current backups ──────────────────────────────────
    dumps = sorted(glob.glob(os.path.join(BACKUP_DIR, "pgbackup-*.dump")))
    log(f"Backups on disk: {len(dumps)}", log_path)


if __name__ == "__main__":
    run_backup()
