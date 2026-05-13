#!/bin/bash
# ============================================================
# PythonAnywhere PostgreSQL Setup & Migration
# ============================================================
# Run this ONCE after enabling PostgreSQL on PythonAnywhere:
#
#   cd /home/ballerquotes/MT5Dashboard
#   bash setup_postgres.sh
#
# Prerequisites:
#   - PostgreSQL enabled on PythonAnywhere Databases tab
#   - PostgreSQL password set on that same page
# ============================================================

set -e  # Exit on any error

PROJECT_DIR="/home/ballerquotes/MT5Dashboard"
VENV_DIR="/home/ballerquotes/.virtualenvs/myvenv"
ENV_FILE="$PROJECT_DIR/.env"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  PythonAnywhere: PostgreSQL Setup & Migration            ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ------------------------------------------------------------------
# Step 1: Collect PostgreSQL credentials
# ------------------------------------------------------------------
echo "== STEP 1: PostgreSQL credentials =="
echo ""
echo "Find these on your PythonAnywhere Databases tab:"
echo ""

read -p "  PostgreSQL host (e.g. ballerquotes-4913.postgres.pythonanywhere-services.com): " PG_HOST
read -p "  PostgreSQL port (e.g. 14913): " PG_PORT
read -p "  Database name (e.g. ballerquotes\$default): " PG_DB
read -p "  Username (e.g. ballerquotes): " PG_USER
read -s -p "  Password: " PG_PASS
echo ""

DATABASE_URL="postgresql://${PG_USER}:${PG_PASS}@${PG_HOST}:${PG_PORT}/${PG_DB}"

echo ""
echo "  URL: postgresql://${PG_USER}:****@${PG_HOST}:${PG_PORT}/${PG_DB}"
echo ""

# ------------------------------------------------------------------
# Step 2: Install Python dependencies
# ------------------------------------------------------------------
echo "== STEP 2: Install dependencies =="

if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
    echo "  Activated virtualenv: $VENV_DIR"
else
    echo "  WARNING: virtualenv not found at $VENV_DIR"
    echo "  Using system Python. You may need to adjust VENV_DIR in this script."
fi

pip install --quiet psycopg2-binary sqlalchemy alembic python-dotenv
echo "  Installed: psycopg2-binary sqlalchemy alembic python-dotenv"
echo ""

# ------------------------------------------------------------------
# Step 3: Test PostgreSQL connection
# ------------------------------------------------------------------
echo "== STEP 3: Test PostgreSQL connection =="

python3 -c "
import psycopg2
conn = psycopg2.connect('${DATABASE_URL}')
cur = conn.cursor()
cur.execute('SELECT version()')
print('  Connected:', cur.fetchone()[0][:60])
conn.close()
"

if [ $? -ne 0 ]; then
    echo "  FAILED — check your credentials and try again."
    exit 1
fi
echo "  [OK]"
echo ""

# ------------------------------------------------------------------
# Step 4: Add DATABASE_URL to .env
# ------------------------------------------------------------------
echo "== STEP 4: Update .env file =="

cd "$PROJECT_DIR"

if [ -f "$ENV_FILE" ]; then
    # Remove any existing DATABASE_URL line and append new one
    grep -v "^DATABASE_URL=" "$ENV_FILE" > "$ENV_FILE.tmp" || true
    mv "$ENV_FILE.tmp" "$ENV_FILE"
fi

echo "DATABASE_URL=${DATABASE_URL}" >> "$ENV_FILE"
echo "  DATABASE_URL added to $ENV_FILE"
echo ""

# ------------------------------------------------------------------
# Step 5: Run Alembic migrations (create tables)
# ------------------------------------------------------------------
echo "== STEP 5: Run Alembic migrations =="

cd "$PROJECT_DIR"
python3 -m alembic upgrade head
echo "  [OK]"
echo ""

# ------------------------------------------------------------------
# Step 6: Migrate data from SQLite → PostgreSQL
# ------------------------------------------------------------------
echo "== STEP 6: Migrate data from SQLite =="

if [ -f "$PROJECT_DIR/dashboard/dashboard.db" ]; then
    python3 migrate_production.py --yes
else
    echo "  No SQLite database found — skipping data migration."
    echo "  Tables are created but empty (fresh start)."
fi
echo ""

# ------------------------------------------------------------------
# Step 7: Update WSGI file reminder
# ------------------------------------------------------------------
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  SETUP COMPLETE                                          ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║                                                          ║"
echo "║  Now update your WSGI config file:                       ║"
echo "║                                                          ║"
echo "║  Add BEFORE the Flask import:                            ║"
echo "║                                                          ║"
echo "║    from dotenv import load_dotenv                        ║"
echo "║    load_dotenv('/home/ballerquotes/MT5Dashboard/.env')   ║"
echo "║                                                          ║"
echo "║  Then:                                                   ║"
echo "║    1. Go to Web tab on PythonAnywhere                    ║"
echo "║    2. Click 'Reload' to restart the web app              ║"
echo "║    3. Visit https://www.tradeopss.com to verify          ║"
echo "║                                                          ║"
echo "║  Backup: rename dashboard.db → dashboard.db.bak          ║"
echo "║    mv dashboard/dashboard.db dashboard/dashboard.db.bak  ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
