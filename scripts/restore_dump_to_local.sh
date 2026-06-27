#!/usr/bin/env bash
# restore_dump_to_local.sh — macOS / Linux
# Restore a pg_dump custom-format (.dump) file into local PostgreSQL.
# Same flow as restore_dump_to_local.ps1 (Windows).
#
# Prerequisites:
#   - Local PostgreSQL running (e.g. brew services start postgresql@16)
#   - psql and pg_restore on PATH (script prepends common Homebrew paths)
#   - A dump file in pg_backups/ (e.g. from: python scripts/download_from_prod.py backup)
#
# Usage:
#   chmod +x scripts/restore_dump_to_local.sh
#   ./scripts/restore_dump_to_local.sh
#   ./scripts/restore_dump_to_local.sh /path/to/pgbackup-2026-05-22-1200.dump
#
# Optional env (or .env in repo root):
#   LOCAL_PGPASSWORD, LOCAL_PGPASSWORD_DEFAULT, POSTGRES_PASSWORD
#   POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DUMP_PATH="${1:-}"
LOCAL_HOST="${POSTGRES_HOST:-localhost}"
LOCAL_PORT="${POSTGRES_PORT:-5432}"
LOCAL_DB="${POSTGRES_DB:-tradeopss}"
LOCAL_USER="${POSTGRES_USER:-postgres}"

import_dotenv() {
  local env_file="$1"
  [[ -f "$env_file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" != *"="* ]] && continue
    local key="${line%%=*}"
    local val="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    val="${val#"${val%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    if [[ "$val" == \"*\" && "$val" == *\" ]]; then val="${val:1:${#val}-2}"; fi
    if [[ "$val" == \'*\' && "$val" == *\' ]]; then val="${val:1:${#val}-2}"; fi
    if [[ -z "${!key:-}" ]]; then
      export "$key=$val"
    fi
  done < "$env_file"
}

import_dotenv "$REPO_ROOT/.env"

LOCAL_HOST="${POSTGRES_HOST:-$LOCAL_HOST}"
LOCAL_PORT="${POSTGRES_PORT:-$LOCAL_PORT}"
LOCAL_DB="${POSTGRES_DB:-$LOCAL_DB}"
LOCAL_USER="${POSTGRES_USER:-$LOCAL_USER}"

if [[ -z "$DUMP_PATH" ]]; then
  shopt -s nullglob
  dumps=( "$REPO_ROOT"/pg_backups/pgbackup-*.dump )
  shopt -u nullglob
  if [[ ${#dumps[@]} -eq 0 ]]; then
    echo "ERROR: No dump found in pg_backups/pgbackup-*.dump" >&2
    echo "Download one with:  python scripts/download_from_prod.py backup" >&2
    exit 1
  fi
  DUMP_PATH="$(ls -t "${dumps[@]}" | head -1)"
fi

if [[ ! -f "$DUMP_PATH" ]]; then
  echo "ERROR: Dump file not found: $DUMP_PATH" >&2
  exit 1
fi

for _pg in /usr/local/opt/postgresql@18/bin /opt/homebrew/opt/postgresql@18/bin \
           /usr/local/opt/postgresql@17/bin /opt/homebrew/opt/postgresql@17/bin \
           /usr/local/opt/postgresql@16/bin /opt/homebrew/opt/postgresql@16/bin \
           /usr/local/opt/postgresql@15/bin /opt/homebrew/opt/postgresql@15/bin; do
  if [[ -d "$_pg" ]]; then
    export PATH="$_pg:$PATH"
    break
  fi
done

if ! command -v psql >/dev/null 2>&1; then
  echo "ERROR: psql not found. Install PostgreSQL (e.g. brew install postgresql@16) and ensure bin is on PATH." >&2
  exit 1
fi
if ! command -v pg_restore >/dev/null 2>&1; then
  echo "ERROR: pg_restore not found. Install PostgreSQL client tools." >&2
  exit 1
fi

local_pass="${LOCAL_PGPASSWORD:-${LOCAL_PGPASSWORD_DEFAULT:-${POSTGRES_PASSWORD:-}}}"
local_pass="${local_pass#"${local_pass%%[![:space:]]*}"}"
local_pass="${local_pass%"${local_pass##*[![:space:]]}"}"
if [[ -z "$local_pass" ]]; then
  read -r -s -p "Enter LOCAL Postgres password: " local_pass
  echo ""
fi

cleanup() {
  export PGPASSWORD=
}
trap cleanup EXIT

export PGPASSWORD="$local_pass"

stamp="$(date '+%Y%m%d_%H%M%S')"
backup_db="${LOCAL_DB}__backup_${stamp}"

echo ""
echo "Restoring dump: $DUMP_PATH"
echo "Target local DB: ${LOCAL_USER}@${LOCAL_HOST}:${LOCAL_PORT}/${LOCAL_DB}"
echo ""

psql -U "$LOCAL_USER" -h "$LOCAL_HOST" -p "$LOCAL_PORT" -d postgres -v ON_ERROR_STOP=1 \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${LOCAL_DB}' AND pid <> pg_backend_pid();" \
  || true

exists="$(psql -U "$LOCAL_USER" -h "$LOCAL_HOST" -p "$LOCAL_PORT" -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname = '${LOCAL_DB}';" | tr -d '[:space:]')"

if [[ "$exists" == "1" ]]; then
  echo "Renaming current '${LOCAL_DB}' to '${backup_db}'..."
  psql -U "$LOCAL_USER" -h "$LOCAL_HOST" -p "$LOCAL_PORT" -d postgres -v ON_ERROR_STOP=1 \
    -c "ALTER DATABASE \"${LOCAL_DB}\" RENAME TO \"${backup_db}\";"
fi

echo "Creating fresh '${LOCAL_DB}'..."
psql -U "$LOCAL_USER" -h "$LOCAL_HOST" -p "$LOCAL_PORT" -d postgres -v ON_ERROR_STOP=1 \
  -c "CREATE DATABASE \"${LOCAL_DB}\";"

echo "Running pg_restore..."
set +e
pg_restore -U "$LOCAL_USER" -h "$LOCAL_HOST" -p "$LOCAL_PORT" \
  --dbname="$LOCAL_DB" --no-owner --no-acl --clean --if-exists "$DUMP_PATH"
restore_rc=$?
set -e

if [[ $restore_rc -ne 0 ]]; then
  echo ""
  echo "ERROR: pg_restore failed with exit code $restore_rc" >&2
  echo "Your previous DB is still available as: ${backup_db}" >&2
  exit 1
fi

psql -U "$LOCAL_USER" -h "$LOCAL_HOST" -p "$LOCAL_PORT" -d "$LOCAL_DB" \
  -c "SELECT COUNT(*) AS table_count FROM information_schema.tables WHERE table_schema = 'public';"

echo ""
echo "Restore complete. Backup DB: ${backup_db}"
echo "Completed at: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
