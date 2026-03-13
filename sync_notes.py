#!/usr/bin/env python3
"""
Notes Sync Script
=================
Run on the production server to EXPORT all cell_notes to a JSON file,
then run locally to IMPORT those notes into the local database.

Usage:
  ON SERVER:   python sync_notes.py export
  LOCALLY:     python sync_notes.py import notes_export.json
"""
import sys
import json
import os
import sqlite3
from datetime import datetime

# Auto-detect environment
# On PythonAnywhere: /home/ballerquotes/MT5Dashboard/dashboard/dashboard.db
# Locally: ./dashboard/dashboard.db
SERVER_DB = '/home/ballerquotes/MT5Dashboard/dashboard/dashboard.db'
LOCAL_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard', 'dashboard.db')

def get_db_path():
    if os.path.exists(SERVER_DB):
        return SERVER_DB
    elif os.path.exists(LOCAL_DB):
        return LOCAL_DB
    else:
        print(f"ERROR: Cannot find database at {SERVER_DB} or {LOCAL_DB}")
        sys.exit(1)

def export_notes(output_file='notes_export.json'):
    """Export all cell_notes from the database to a JSON file."""
    db_path = get_db_path()
    print(f"Database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all notes
    cursor.execute('''
        SELECT client_id, row_index, column_key, note_content, created_by, updated_at
        FROM cell_notes
        ORDER BY client_id, row_index, column_key
    ''')
    rows = cursor.fetchall()
    
    notes = []
    for row in rows:
        notes.append({
            'client_id': row['client_id'],
            'row_index': row['row_index'],
            'column_key': row['column_key'],
            'note_content': row['note_content'],
            'created_by': row['created_by'],
            'updated_at': row['updated_at']
        })
    
    conn.close()
    
    # Summary
    clients = set(n['client_id'] for n in notes)
    prop_day_notes = [n for n in notes if n['column_key'].startswith('Prop Day')]
    
    print(f"\n=== Export Summary ===")
    print(f"Total notes: {len(notes)}")
    print(f"Prop Day notes: {len(prop_day_notes)}")
    print(f"Clients: {sorted(clients)}")
    
    for client in sorted(clients):
        client_notes = [n for n in notes if n['client_id'] == client]
        client_prop = [n for n in client_notes if n['column_key'].startswith('Prop Day')]
        rows_with_prop = len(set(n['row_index'] for n in client_prop))
        print(f"  {client}: {len(client_notes)} total notes, {len(client_prop)} Prop Day notes across {rows_with_prop} rows")
    
    # Write to file
    export_data = {
        'exported_at': datetime.now().isoformat(),
        'source_db': db_path,
        'total_notes': len(notes),
        'notes': notes
    }
    
    with open(output_file, 'w') as f:
        json.dump(export_data, f, indent=2)
    
    print(f"\nExported to: {output_file}")
    print(f"File size: {os.path.getsize(output_file):,} bytes")

def import_notes(input_file):
    """Import notes from a JSON file into the local database."""
    if not os.path.exists(input_file):
        print(f"ERROR: File not found: {input_file}")
        sys.exit(1)
    
    db_path = get_db_path()
    print(f"Database: {db_path}")
    print(f"Import file: {input_file}")
    
    with open(input_file, 'r') as f:
        export_data = json.load(f)
    
    notes = export_data['notes']
    print(f"Source: {export_data.get('source_db', 'unknown')}")
    print(f"Exported at: {export_data.get('exported_at', 'unknown')}")
    print(f"Notes to import: {len(notes)}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Ensure table exists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cell_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT NOT NULL,
            row_index INTEGER NOT NULL,
            column_key TEXT NOT NULL,
            note_content TEXT,
            created_by TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(client_id, row_index, column_key)
        )
    ''')
    
    imported = 0
    updated = 0
    skipped = 0
    
    for note in notes:
        # Check if note already exists
        cursor.execute('''
            SELECT note_content FROM cell_notes 
            WHERE client_id = ? AND row_index = ? AND column_key = ?
        ''', (note['client_id'], note['row_index'], note['column_key']))
        
        existing = cursor.fetchone()
        
        if existing is None:
            # Insert new note
            cursor.execute('''
                INSERT INTO cell_notes (client_id, row_index, column_key, note_content, created_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (note['client_id'], note['row_index'], note['column_key'],
                  note['note_content'], note['created_by'], note['updated_at']))
            imported += 1
        elif existing[0] != note['note_content']:
            # Update with newer content (server wins)
            cursor.execute('''
                UPDATE cell_notes 
                SET note_content = ?, created_by = ?, updated_at = ?
                WHERE client_id = ? AND row_index = ? AND column_key = ?
            ''', (note['note_content'], note['created_by'], note['updated_at'],
                  note['client_id'], note['row_index'], note['column_key']))
            updated += 1
        else:
            skipped += 1
    
    conn.commit()
    conn.close()
    
    print(f"\n=== Import Summary ===")
    print(f"New notes imported: {imported}")
    print(f"Existing notes updated: {updated}")
    print(f"Unchanged (skipped): {skipped}")
    print(f"Total processed: {imported + updated + skipped}")

def show_status():
    """Show current notes status in the database."""
    db_path = get_db_path()
    print(f"Database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM cell_notes")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM cell_notes WHERE column_key LIKE 'Prop Day%'")
    prop_day = cursor.fetchone()[0]
    
    cursor.execute("SELECT DISTINCT client_id FROM cell_notes ORDER BY client_id")
    clients = [r[0] for r in cursor.fetchall()]
    
    print(f"\n=== Notes Status ===")
    print(f"Total notes: {total}")
    print(f"Prop Day notes (displayed as Prop Progress): {prop_day}")
    print(f"Clients with notes: {clients}")
    
    for client in clients:
        cursor.execute("""
            SELECT COUNT(*), COUNT(DISTINCT row_index) 
            FROM cell_notes 
            WHERE client_id = ? AND column_key LIKE 'Prop Day%'
        """, (client,))
        count, rows = cursor.fetchone()
        print(f"  {client}: {count} Prop Day notes across {rows} rows")
    
    conn.close()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        print("Commands:")
        print("  export [output.json]  - Export all notes to JSON")
        print("  import <input.json>   - Import notes from JSON")
        print("  status                - Show notes status")
        sys.exit(0)
    
    command = sys.argv[1].lower()
    
    if command == 'export':
        output = sys.argv[2] if len(sys.argv) > 2 else 'notes_export.json'
        export_notes(output)
    elif command == 'import':
        if len(sys.argv) < 3:
            print("ERROR: Please specify input file: python sync_notes.py import notes_export.json")
            sys.exit(1)
        import_notes(sys.argv[2])
    elif command == 'status':
        show_status()
    else:
        print(f"Unknown command: {command}")
        print("Use: export, import, or status")
        sys.exit(1)
