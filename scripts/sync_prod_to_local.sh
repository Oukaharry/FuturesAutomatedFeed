#!/usr/bin/env bash
# sync_prod_to_local.sh — macOS / Linux
# Same flow as sync_prod_to_local.ps1: dump prod (via SSH tunnel) → restore local.
#
# Prerequisites:
#   1. SSH tunnel (separate terminal, keep open):
#        ssh -L 5433:ballerquotes-5185.postgres.pythonanywhere-services.com:15185 \
#            ballerquotes@ssh.pythonanywhere.com -N
#   2. Local PostgreSQL running (e.g. brew services start postgresql@16)
#   3. pg_dump / psql on PATH, or Homebrew PostgreSQL @16 installed (script prepends common paths).
#
# Usage (three separate commands; do not paste "chmod" help text as extra words):
#   chmod +x sync_prod_to_local.sh
#   export SYNC_PROD_PGPASSWORD='actual-DB-password-for-user-tradeopss_admin'
#   ./sync_prod_to_local.sh
#
# SYNC_PROD_PGPASSWORD is the PostgreSQL password for SYNC_PROD_USER (not the username string).
#
# Local DB user/password default from .env in this repo (POSTGRES_*), else postgres / postgres123.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/.env"
  set +a
fi

PROD_HOST="${SYNC_PROD_HOST:-127.0.0.1}"
PROD_PORT="${SYNC_PROD_PORT:-5433}"
PROD_DB="${SYNC_PROD_DB:-tradeopss}"
PROD_USER="${SYNC_PROD_USER:-tradeopss_admin}"

LOCAL_HOST="${POSTGRES_HOST:-localhost}"
LOCAL_PORT="${POSTGRES_PORT:-5432}"
LOCAL_DB="${POSTGRES_DB:-tradeopss}"
LOCAL_USER="${POSTGRES_USER:-postgres}"
LOCAL_PASS="${POSTGRES_PASSWORD:-postgres123}"

PROD_PASS="${SYNC_PROD_PGPASSWORD:-}"
if [[ -z "$PROD_PASS" ]]; then
  echo "ERROR: Set SYNC_PROD_PGPASSWORD to the production PostgreSQL password for user '${PROD_USER}'." >&2
  echo "Example:  export SYNC_PROD_PGPASSWORD='...' && ./sync_prod_to_local.sh" >&2
  exit 1
fi

for _pg in /usr/local/opt/postgresql@16/bin /opt/homebrew/opt/postgresql@16/bin \
           /usr/local/opt/postgresql@15/bin /opt/homebrew/opt/postgresql@15/bin; do
  if [[ -d "$_pg" ]]; then
    export PATH="$_pg:$PATH"
    break
  fi
done

if ! command -v psql >/dev/null 2>&1 || ! command -v pg_dump >/dev/null 2>&1; then
  echo "ERROR: psql and pg_dump must be on PATH (install PostgreSQL client/server, e.g. brew install postgresql@16)." >&2
  exit 1
fi

temp=""
cleanup() {
  export PGPASSWORD=
  rm -f "$temp"
}
trap cleanup EXIT
temp="$(mktemp "${TMPDIR:-/tmp}/prod_dump.XXXXXX")"

echo ""
echo "[1/3] Dropping and recreating local database '${LOCAL_DB}'..."
export PGPASSWORD="$LOCAL_PASS"
psql -U "$LOCAL_USER" -h "$LOCAL_HOST" -p "$LOCAL_PORT" -d postgres -v ON_ERROR_STOP=1 \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${LOCAL_DB}' AND pid <> pg_backend_pid();" \
  || true
psql -U "$LOCAL_USER" -h "$LOCAL_HOST" -p "$LOCAL_PORT" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"${LOCAL_DB}\";"
psql -U "$LOCAL_USER" -h "$LOCAL_HOST" -p "$LOCAL_PORT" -d postgres -v ON_ERROR_STOP=1 \
  -c "CREATE DATABASE \"${LOCAL_DB}\";"

echo "[2/3] Dumping production to temp file..."
# Do not reuse PGPASSWORD from local psql above — libpq would send the local password
# to the tunneled production server and pg_isready can exit non-zero (false "down").
if ! env -u PGPASSWORD pg_isready -h "$PROD_HOST" -p "$PROD_PORT" >/dev/null 2>&1; then
  echo "" >&2
  echo "ERROR: Nothing is accepting PostgreSQL connections at ${PROD_HOST}:${PROD_PORT}." >&2
  echo "Start the SSH tunnel first and leave it running, for example:" >&2
  echo "" >&2
  echo "  ssh -L 5433:ballerquotes-5185.postgres.pythonanywhere-services.com:15185 \\" >&2
  echo "      ballerquotes@ssh.pythonanywhere.com -N" >&2
  echo "" >&2
  echo "Then verify (no PGPASSWORD in the environment):  env -u PGPASSWORD pg_isready -h 127.0.0.1 -p 5433" >&2
  echo "If pg_dump still fails, double-check SYNC_PROD_PGPASSWORD is the DB password for user '${PROD_USER}' (not the username)." >&2
  env -u PGPASSWORD pg_isready -h "$PROD_HOST" -p "$PROD_PORT" >&2 || true
  exit 1
fi
export PGPASSWORD="$PROD_PASS"
# Omit owner/grants so local DB need not have production roles (e.g. tradeopss_admin).
pg_dump -h "$PROD_HOST" -p "$PROD_PORT" -U "$PROD_USER" -d "$PROD_DB" \
  --no-owner --no-acl -f "$temp"

echo "    Restoring to local database..."
export PGPASSWORD="$LOCAL_PASS"
psql -U "$LOCAL_USER" -h "$LOCAL_HOST" -p "$LOCAL_PORT" -d "$LOCAL_DB" -v ON_ERROR_STOP=1 -f "$temp"

echo "[3/3] Sync complete. Local '${LOCAL_DB}' now matches production."
echo "Completed at: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
