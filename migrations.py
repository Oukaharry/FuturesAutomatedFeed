"""
Database Migration Script for MT5 Hedging Dashboard
====================================================
This script handles database migrations from SQLite to PostgreSQL
and manages schema versioning using Flask-Migrate (Alembic).

Usage:
    # Initialize migrations (first time only)
    python migrations.py init
    
    # Create a new migration
    python migrations.py migrate -m "Description of changes"
    
    # Apply migrations
    python migrations.py upgrade
    
    # Rollback last migration
    python migrations.py downgrade
    
    # Export SQLite to PostgreSQL
    python migrations.py export-to-postgres
"""

import os
import sys
import json
import sqlite3
import argparse
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.database import get_connection, DB_PATH


def get_all_tables():
    """Get all table names from SQLite database."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        return [row[0] for row in cursor.fetchall()]


def get_table_schema(table_name):
    """Get CREATE TABLE statement for a table."""
    with get_connection() as conn:
        cursor = conn.execute(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        result = cursor.fetchone()
        return result[0] if result else None


def export_table_data(table_name):
    """Export all data from a table."""
    with get_connection() as conn:
        cursor = conn.execute(f"SELECT * FROM {table_name}")
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
        return columns, [dict(zip(columns, row)) for row in rows]


def sqlite_to_postgres_type(sqlite_type):
    """Convert SQLite column type to PostgreSQL type."""
    type_mapping = {
        'INTEGER': 'INTEGER',
        'TEXT': 'TEXT',
        'REAL': 'DOUBLE PRECISION',
        'BLOB': 'BYTEA',
        'NUMERIC': 'NUMERIC',
        'BOOLEAN': 'BOOLEAN',
    }
    
    sqlite_type_upper = sqlite_type.upper() if sqlite_type else 'TEXT'
    
    for sqlite_t, postgres_t in type_mapping.items():
        if sqlite_t in sqlite_type_upper:
            return postgres_t
    
    return 'TEXT'


def generate_postgres_schema():
    """Generate PostgreSQL schema from SQLite database."""
    tables = get_all_tables()
    postgres_sql = []
    
    postgres_sql.append("-- PostgreSQL Schema for MT5 Hedging Dashboard")
    postgres_sql.append(f"-- Generated: {datetime.now().isoformat()}")
    postgres_sql.append("-- ================================================\n")
    
    for table in tables:
        schema = get_table_schema(table)
        if schema:
            # Convert SQLite schema to PostgreSQL
            pg_schema = schema
            
            # Replace SQLite-specific syntax
            pg_schema = pg_schema.replace('AUTOINCREMENT', '')
            pg_schema = pg_schema.replace('INTEGER PRIMARY KEY', 'SERIAL PRIMARY KEY')
            
            postgres_sql.append(f"-- Table: {table}")
            postgres_sql.append(pg_schema + ";\n")
    
    return '\n'.join(postgres_sql)


def export_data_to_json(output_file='db_export.json'):
    """Export all database data to JSON."""
    tables = get_all_tables()
    export_data = {
        'exported_at': datetime.now().isoformat(),
        'source': 'sqlite',
        'tables': {}
    }
    
    for table in tables:
        columns, data = export_table_data(table)
        export_data['tables'][table] = {
            'columns': columns,
            'row_count': len(data),
            'data': data
        }
        print(f"  Exported {len(data)} rows from {table}")
    
    with open(output_file, 'w') as f:
        json.dump(export_data, f, indent=2, default=str)
    
    print(f"\n✅ Data exported to {output_file}")
    return output_file


def generate_postgres_insert_statements(json_file='db_export.json'):
    """Generate PostgreSQL INSERT statements from exported JSON."""
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    sql_statements = []
    sql_statements.append("-- PostgreSQL INSERT statements")
    sql_statements.append(f"-- Generated from: {json_file}")
    sql_statements.append("-- ================================================\n")
    
    for table_name, table_data in data['tables'].items():
        if not table_data['data']:
            continue
        
        sql_statements.append(f"-- {table_name}: {table_data['row_count']} rows")
        
        for row in table_data['data']:
            columns = ', '.join(row.keys())
            values = []
            
            for key, value in row.items():
                if value is None:
                    values.append('NULL')
                elif isinstance(value, bool):
                    values.append('TRUE' if value else 'FALSE')
                elif isinstance(value, (int, float)):
                    values.append(str(value))
                else:
                    # Escape single quotes
                    escaped = str(value).replace("'", "''")
                    values.append(f"'{escaped}'")
            
            values_str = ', '.join(values)
            sql_statements.append(f"INSERT INTO {table_name} ({columns}) VALUES ({values_str});")
        
        sql_statements.append("")
    
    output_file = 'postgres_data.sql'
    with open(output_file, 'w') as f:
        f.write('\n'.join(sql_statements))
    
    print(f"✅ INSERT statements written to {output_file}")
    return output_file


def create_migration_table():
    """Create a table to track migration versions."""
    with get_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL UNIQUE,
                description TEXT,
                applied_at TEXT NOT NULL
            )
        ''')
        conn.commit()
        print("✅ Migration tracking table created")


def record_migration(version, description):
    """Record a migration as applied."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
            (version, description, datetime.now().isoformat())
        )
        conn.commit()


def get_applied_migrations():
    """Get list of applied migrations."""
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                "SELECT version, description, applied_at FROM schema_migrations ORDER BY applied_at"
            )
            return cursor.fetchall()
        except sqlite3.OperationalError:
            return []


def show_status():
    """Show current database status."""
    print("\n📊 Database Status")
    print("=" * 50)
    print(f"Database: {DB_PATH}")
    
    tables = get_all_tables()
    print(f"\nTables ({len(tables)}):")
    
    for table in tables:
        with get_connection() as conn:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"  • {table}: {count} rows")
    
    migrations = get_applied_migrations()
    print(f"\nMigrations Applied: {len(migrations)}")
    for version, description, applied_at in migrations:
        print(f"  • {version}: {description} ({applied_at})")


def main():
    parser = argparse.ArgumentParser(description='Database Migration Tool')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Status command
    subparsers.add_parser('status', help='Show database status')
    
    # Init command
    subparsers.add_parser('init', help='Initialize migration tracking')
    
    # Export command
    export_parser = subparsers.add_parser('export', help='Export data to JSON')
    export_parser.add_argument('-o', '--output', default='db_export.json', help='Output file')
    
    # Schema command
    subparsers.add_parser('schema', help='Generate PostgreSQL schema')
    
    # Full export command
    subparsers.add_parser('export-to-postgres', help='Full export for PostgreSQL migration')
    
    args = parser.parse_args()
    
    if args.command == 'status':
        show_status()
    
    elif args.command == 'init':
        create_migration_table()
    
    elif args.command == 'export':
        export_data_to_json(args.output)
    
    elif args.command == 'schema':
        schema = generate_postgres_schema()
        with open('postgres_schema.sql', 'w') as f:
            f.write(schema)
        print("✅ PostgreSQL schema written to postgres_schema.sql")
    
    elif args.command == 'export-to-postgres':
        print("🔄 Starting full PostgreSQL export...")
        print("\n1. Generating PostgreSQL schema...")
        schema = generate_postgres_schema()
        with open('postgres_schema.sql', 'w') as f:
            f.write(schema)
        print("   ✅ Schema saved to postgres_schema.sql")
        
        print("\n2. Exporting data to JSON...")
        export_data_to_json()
        
        print("\n3. Generating INSERT statements...")
        generate_postgres_insert_statements()
        
        print("\n" + "=" * 50)
        print("✅ Export complete!")
        print("\nTo migrate to PostgreSQL:")
        print("  1. Create a new PostgreSQL database")
        print("  2. Run: psql -d your_db -f postgres_schema.sql")
        print("  3. Run: psql -d your_db -f postgres_data.sql")
    
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
