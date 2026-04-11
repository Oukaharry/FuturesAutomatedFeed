"""
Phase 4: Migrate all data from SQLite → PostgreSQL.

Reads every row from the local dashboard.db and inserts into the
PostgreSQL tradeopss database.  Uses ON CONFLICT DO NOTHING so the
script is safe to re-run.

Usage:
    python _migrate_sqlite_to_pg.py
"""
import sqlite3
import os
import sys
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard', 'dashboard.db')
PG_URL = os.environ['DATABASE_URL']

# Tables to migrate (in dependency order) and their unique conflict targets
# for ON CONFLICT DO NOTHING.
TABLES = [
    # table_name,        conflict_target (for ON CONFLICT)
    ('admin_passwords',   'username'),
    ('user_credentials',  None),        # composite unique handled by DO NOTHING
    ('api_keys',          'key_hash'),
    ('clients_data',      'client_id'),
    ('data_history',      None),
    ('audit_log',         None),
    ('sessions',          'session_token'),
    ('cell_notes',        None),
    ('daily_watermarks',  None),        # composite PK
    ('waterlog_periods',  None),        # composite PK
    ('login_attempts',    None),
    ('evaluations',       None),
    ('phase_definitions', 'phase_code'),
    ('kyc_links',         None),
    ('quality_scan_results', None),
    ('daily_checklists',  None),
    ('system_settings',   'key'),
]

# Skip these SQLite-internal tables
SKIP = {'sqlite_sequence'}


def get_sqlite_columns(sqlite_cur, table):
    """Get column names for a SQLite table."""
    sqlite_cur.execute(f'PRAGMA table_info([{table}])')
    return [row[1] for row in sqlite_cur.fetchall()]


def migrate_table(sqlite_cur, pg_cur, table, conflict_col=None):
    """Migrate all rows from one SQLite table to PostgreSQL."""
    columns = get_sqlite_columns(sqlite_cur, table)

    # Skip 'id' column — let PostgreSQL auto-generate serial IDs
    cols_no_id = [c for c in columns if c != 'id']

    sqlite_cur.execute(f'SELECT {", ".join(cols_no_id)} FROM [{table}]')
    rows = sqlite_cur.fetchall()

    if not rows:
        print(f'  {table:30s}   0 rows (empty)')
        return 0

    # Build INSERT statement
    col_list = ', '.join(cols_no_id)
    placeholders = ', '.join(['%s'] * len(cols_no_id))
    sql = f'INSERT INTO {table} ({col_list}) VALUES ({placeholders})'

    if conflict_col:
        sql += f' ON CONFLICT ({conflict_col}) DO NOTHING'
    else:
        sql += ' ON CONFLICT DO NOTHING'

    inserted = 0
    for row in rows:
        try:
            pg_cur.execute(sql, row)
            inserted += pg_cur.rowcount
        except psycopg2.Error as e:
            # Skip individual row errors (e.g. constraint violations)
            pg_cur.connection.rollback()
            print(f'    SKIP row in {table}: {e.pgerror.strip() if e.pgerror else e}')
            continue

    print(f'  {table:30s} {inserted:>5} / {len(rows)} rows inserted')
    return inserted


def reset_sequences(pg_cur, tables_with_id):
    """Reset PostgreSQL serial sequences to max(id)+1 so new inserts don't collide."""
    for table in tables_with_id:
        try:
            pg_cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 0) + 1, false) FROM {table}")
        except Exception as e:
            # Some tables (composite PK, no 'id') won't have a sequence — skip
            pg_cur.connection.rollback()


def main():
    if not os.path.exists(SQLITE_PATH):
        print(f'ERROR: SQLite database not found at {SQLITE_PATH}')
        sys.exit(1)

    print(f'SQLite: {SQLITE_PATH}')
    print(f'PostgreSQL: {PG_URL.split("@")[1] if "@" in PG_URL else PG_URL}')
    print()

    # Connect to both databases
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_cur = sqlite_conn.cursor()

    pg_conn = psycopg2.connect(PG_URL)
    pg_conn.autocommit = False
    pg_cur = pg_conn.cursor()

    total_inserted = 0
    total_rows = 0
    tables_with_id = []

    print('Migrating tables:')
    for table, conflict_col in TABLES:
        columns = get_sqlite_columns(sqlite_cur, table)
        if 'id' in columns:
            tables_with_id.append(table)

        inserted = migrate_table(sqlite_cur, pg_cur, table, conflict_col)
        sqlite_cur.execute(f'SELECT COUNT(*) FROM [{table}]')
        count = sqlite_cur.fetchone()[0]
        total_inserted += inserted
        total_rows += count

    # Commit all inserts
    pg_conn.commit()

    # Reset auto-increment sequences
    print('\nResetting sequences...')
    reset_sequences(pg_cur, tables_with_id)
    pg_conn.commit()

    # Verify counts
    print('\nVerification:')
    for table, _ in TABLES:
        sqlite_cur.execute(f'SELECT COUNT(*) FROM [{table}]')
        sqlite_count = sqlite_cur.fetchone()[0]
        pg_cur.execute(f'SELECT COUNT(*) FROM {table}')
        pg_count = pg_cur.fetchone()[0]
        status = 'OK' if pg_count >= sqlite_count else 'MISMATCH'
        print(f'  {table:30s}  SQLite={sqlite_count:>5}  PG={pg_count:>5}  [{status}]')

    print(f'\nTotal: {total_inserted} / {total_rows} rows migrated')
    print('Done!')

    sqlite_conn.close()
    pg_cur.close()
    pg_conn.close()


if __name__ == '__main__':
    main()
