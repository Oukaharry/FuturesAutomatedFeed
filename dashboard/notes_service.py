from dashboard.database import get_connection
import logging

def get_client_notes(client_id):
    """
    Returns a dictionary of notes for a client.
    Format: { row_index: { column_key: note_content } }
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT row_index, column_key, note_content 
                FROM cell_notes 
                WHERE client_id = ?
            ''', (client_id,))
            rows = cursor.fetchall()
            
            notes = {}
            for row in rows:
                # Handle both dict-like (Row) and tuple results
                try:
                    rid = row['row_index']
                    col = row['column_key']
                    content = row['note_content']
                except (TypeError, IndexError):
                    rid = row[0]
                    col = row[1]
                    content = row[2]
                
                if rid not in notes:
                    notes[rid] = {}
                notes[rid][col] = content
            return notes
    except Exception as e:
        logging.error(f"Error fetching notes for {client_id}: {e}")
        return {}

def save_client_note(client_id, row_index, column_key, content, user):
    """
    Saves or updates a note.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO cell_notes (client_id, row_index, column_key, note_content, created_by, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (client_id, row_index, column_key, content, user))
            conn.commit()
            return True
    except Exception as e:
        logging.error(f"Error saving note for {client_id}: {e}")
        return False

def delete_client_note(client_id, row_index, column_key):
    """
    Deletes a specific note.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM cell_notes 
                WHERE client_id = ? AND row_index = ? AND column_key = ?
            ''', (client_id, row_index, column_key))
            conn.commit()
            return True
    except Exception as e:
        logging.error(f"Error deleting note for {client_id}: {e}")
        return False
