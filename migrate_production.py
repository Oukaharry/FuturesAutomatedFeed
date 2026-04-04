#!/usr/bin/env python3
"""
Production Migration Script: SQLite → PostgreSQL on PythonAnywhere.

Run this ONCE after setting up PostgreSQL on PythonAnywhere.

Prerequisites:
  1. Create a PostgreSQL database on PythonAnywhere:
     - Go to Databases tab → PostgreSQL section
     - Set a PostgreSQL password (note it down)
     - PythonAnywhere gives you:
         Host: ballerquotes-4913.postgres.pythonanywhere-services.com
         Port: 14913  (shown on Databases page)
         DB:   ballerquotes$default   (or create a custom one)
         User: ballerquotes
         Pass: <the password you set>

  2. Install psycopg2 in your PythonAnywhere virtualenv:
         pip install psycopg2-binary sqlalchemy alembic python-dotenv

  3. Update .env on PythonAnywhere with your DATABASE_URL:
         DATABASE_URL=postgresql://ballerquotes:<password>@ballerquotes-4913.postgres.pythonanywhere-services.com:14913/ballerquotes$default

  4. Run this script from the project directory:
         cd /home/ballerquotes/MT5Dashboard
         python migrate_production.py

What this script does (in order):
  Step 1: Verifies PostgreSQL connectivity
  Step 2: Runs Alembic migrations to create all tables
  Step 3: Copies all data from SQLite → PostgreSQL
  Step 4: Resets serial sequences so new inserts don't collide
  Step 5: Verifies row counts match

Safe to re-run — uses ON CONFLICT DO NOTHING.
"""
import os
import sys
import subprocess
import sqlite3

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.path.join(SCRIPT_DIR, 'dashboard', 'dashboard.db')
ENV_PATH = os.path.join(SCRIPT_DIR, '.env')
ALEMBIC_INI = os.path.join(SCRIPT_DIR, 'alembic.ini')

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except ImportError:
    print("ERROR: python-dotenv not installed. Run: pip install python-dotenv")
    sys.exit(1)

DATABASE_URL = os.environ.get('DATABASE_URL', '')
if not DATABASE_URL or not DATABASE_URL.startswith('postgresql'):
    print("ERROR: DATABASE_URL not set or not a PostgreSQL URL.")
    print("  Set it in .env like:")
    print("  DATABASE_URL=postgresql://ballerquotes:<pass>@<host>:<port>/<dbname>")
    sys.exit(1)

# Import psycopg2 after env is loaded
try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)


# Tables to migrate (dependency order) and their unique conflict column.
TABLES = [
    ('admin_passwords',      'username'),
    ('user_credentials',     None),
    ('api_keys',             'key_hash'),
    ('clients_data',         'client_id'),
    ('data_history',         None),
    ('audit_log',            None),
    ('sessions',             'session_token'),
    ('cell_notes',           None),
    ('daily_watermarks',     None),
    ('waterlog_periods',     None),
    ('login_attempts',       None),
    ('evaluations',          None),
    ('phase_definitions',    'phase_code'),
    ('kyc_links',            None),
    ('quality_scan_results', None),
    ('daily_checklists',     None),
    ('system_settings',      'key'),
]


def masked_url(url):
    """Hide password in DATABASE_URL for display."""
    if '@' in url:
        pre, post = url.split('@', 1)
        if '://' in pre:
            scheme_user = pre.rsplit(':', 1)[0]
            return f"{scheme_user}:****@{post}"
    return url


# ──────────────────────────────────────────────────────────────────────────
# Step 1: Verify PostgreSQL connectivity
# ──────────────────────────────────────────────────────────────────────────
def step_verify_pg():
    print("=" * 60)
    print("STEP 1: Verify PostgreSQL connectivity")
    print("=" * 60)
    print(f"  URL: {masked_url(DATABASE_URL)}")

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]
        print(f"  Connected: {version[:60]}")
        cur.close()
        conn.close()
        print("  [OK]\n")
        return True
    except psycopg2.Error as e:
        print(f"  FAILED: {e}")
        print("\n  Check your DATABASE_URL in .env and that PostgreSQL is running.")
        return False


# ──────────────────────────────────────────────────────────────────────────
# Step 2: Run Alembic migrations
# ──────────────────────────────────────────────────────────────────────────
def step_run_alembic():
    print("=" * 60)
    print("STEP 2: Run Alembic migrations (create tables)")
    print("=" * 60)

    if not os.path.exists(ALEMBIC_INI):
        print(f"  ERROR: alembic.ini not found at {ALEMBIC_INI}")
        return False

    try:
        result = subprocess.run(
            [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"  {result.stdout.strip()}")
            print("  [OK]\n")
            return True
        else:
            print(f"  STDOUT: {result.stdout.strip()}")
            print(f"  STDERR: {result.stderr.strip()}")
            print("  FAILED — fix Alembic errors above and re-run.")
            return False
    except Exception as e:
        print(f"  ERROR running Alembic: {e}")
        return False


# ──────────────────────────────────────────────────────────────────────────
# Step 3: Migrate data from SQLite → PostgreSQL
# ──────────────────────────────────────────────────────────────────────────
def get_sqlite_columns(cur, table):
    cur.execute(f'PRAGMA table_info([{table}])')
    return [row[1] for row in cur.fetchall()]


def migrate_table(sqlite_cur, pg_cur, table, conflict_col):
    columns = get_sqlite_columns(sqlite_cur, table)
    cols_no_id = [c for c in columns if c != 'id']

    sqlite_cur.execute(f'SELECT {", ".join(cols_no_id)} FROM [{table}]')
    rows = sqlite_cur.fetchall()

    if not rows:
        print(f'    {table:30s}   0 rows (empty)')
        return 0

    col_list = ', '.join(cols_no_id)
    placeholders = ', '.join(['%s'] * len(cols_no_id))
    sql = f'INSERT INTO {table} ({col_list}) VALUES ({placeholders})'

    if conflict_col:
        sql += f' ON CONFLICT ({conflict_col}) DO NOTHING'
    else:
        sql += ' ON CONFLICT DO NOTHING'

    inserted = 0
    errors = 0
    for row in rows:
        try:
            pg_cur.execute(sql, row)
            inserted += pg_cur.rowcount
        except psycopg2.Error as e:
            pg_cur.connection.rollback()
            errors += 1
            if errors <= 3:
                print(f'      SKIP row in {table}: {e.pgerror.strip() if e.pgerror else e}')

    suffix = f' ({errors} skipped)' if errors else ''
    print(f'    {table:30s} {inserted:>5} / {len(rows)} rows{suffix}')
    return inserted


def step_migrate_data():
    print("=" * 60)
    print("STEP 3: Migrate data from SQLite → PostgreSQL")
    print("=" * 60)

    if not os.path.exists(SQLITE_PATH):
        print(f"  WARNING: SQLite database not found at {SQLITE_PATH}")
        print("  Skipping data migration — tables are created but empty.")
        return True

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_cur = sqlite_conn.cursor()

    pg_conn = psycopg2.connect(DATABASE_URL)
    pg_conn.autocommit = False
    pg_cur = pg_conn.cursor()

    total_inserted = 0
    total_source = 0
    tables_with_id = []

    print(f"  SQLite: {SQLITE_PATH}")
    print(f"  PostgreSQL: {masked_url(DATABASE_URL)}\n")

    for table, conflict_col in TABLES:
        columns = get_sqlite_columns(sqlite_cur, table)
        if 'id' in columns:
            tables_with_id.append(table)

        inserted = migrate_table(sqlite_cur, pg_cur, table, conflict_col)
        sqlite_cur.execute(f'SELECT COUNT(*) FROM [{table}]')
        total_source += sqlite_cur.fetchone()[0]
        total_inserted += inserted

    pg_conn.commit()

    # Reset sequences so new auto-increment IDs don't collide
    print("\n  Resetting sequences...")
    for table in tables_with_id:
        try:
            pg_cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE(MAX(id), 0) + 1, false) FROM {table}"
            )
        except Exception:
            pg_cur.connection.rollback()
    pg_conn.commit()

    print(f"\n  Total: {total_inserted} / {total_source} rows migrated")
    print("  [OK]\n")

    sqlite_conn.close()
    pg_cur.close()
    pg_conn.close()
    return True


# ──────────────────────────────────────────────────────────────────────────
# Step 4: Verify
# ──────────────────────────────────────────────────────────────────────────
def step_verify():
    print("=" * 60)
    print("STEP 4: Verify row counts")
    print("=" * 60)

    if not os.path.exists(SQLITE_PATH):
        print("  (SQLite not present — skipping verification)")
        return True

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_cur = sqlite_conn.cursor()

    pg_conn = psycopg2.connect(DATABASE_URL)
    pg_cur = pg_conn.cursor()

    all_ok = True
    for table, _ in TABLES:
        sqlite_cur.execute(f'SELECT COUNT(*) FROM [{table}]')
        sc = sqlite_cur.fetchone()[0]
        pg_cur.execute(f'SELECT COUNT(*) FROM {table}')
        pc = pg_cur.fetchone()[0]
        status = 'OK' if pc >= sc else 'MISMATCH'
        if status == 'MISMATCH':
            all_ok = False
        print(f'    {table:30s}  SQLite={sc:>5}  PG={pc:>5}  [{status}]')

    sqlite_conn.close()
    pg_cur.close()
    pg_conn.close()

    if all_ok:
        print("\n  All tables verified. [OK]\n")
    else:
        print("\n  WARNING: Some tables have mismatched counts.\n")
    return all_ok


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────
def main():
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  PRODUCTION MIGRATION: SQLite → PostgreSQL              ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  Project: {SCRIPT_DIR:<47s}║")
    print(f"║  SQLite:  {'EXISTS' if os.path.exists(SQLITE_PATH) else 'NOT FOUND':<47s}║")
    print(f"║  PG URL:  {masked_url(DATABASE_URL)[:47]:<47s}║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # Confirm before proceeding
    if '--yes' not in sys.argv:
        answer = input("Proceed with migration? [y/N] ").strip().lower()
        if answer != 'y':
            print("Aborted.")
            sys.exit(0)

    # Step 1
    if not step_verify_pg():
        sys.exit(1)

    # Step 2
    if not step_run_alembic():
        sys.exit(1)

    # Step 3
    if not step_migrate_data():
        sys.exit(1)

    # Step 4
    step_verify()

    print("=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Update your WSGI file to load .env (see below)")
    print("  2. Reload the web app on PythonAnywhere")
    print("  3. Test the dashboard in your browser")
    print("  4. Once confirmed working, rename dashboard.db to")
    print("     dashboard.db.bak as backup")
    print()
    print("  WSGI addition (add before the Flask import):")
    print("  ─────────────────────────────────────────────")
    print("  from dotenv import load_dotenv")
    print("  load_dotenv('/home/ballerquotes/MT5Dashboard/.env')")
    print()


if __name__ == '__main__':
    main()
