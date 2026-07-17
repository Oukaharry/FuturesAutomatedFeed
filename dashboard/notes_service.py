from dashboard.database import get_connection
import logging


def _normalize_row_index(rid):
    """Coerce DB/JSON row_index to int for stable dict keys."""
    try:
        return int(rid)
    except (TypeError, ValueError):
        return rid


def notes_for_eval_row(notes, row_index):
    """Look up injected notes for evaluation array index (int or legacy str keys)."""
    if not notes:
        return None
    idx = _normalize_row_index(row_index)
    if idx in notes:
        return notes[idx]
    sidx = str(idx)
    if sidx in notes:
        return notes[sidx]
    return None


def get_client_notes(client_id, _conn=None):
    """
    Returns a dictionary of notes for a client.
    Format: { row_index: { column_key: note_content } }
    """
    try:
        def _run(cursor):
            cursor.execute('''
                SELECT row_index, column_key, note_content 
                FROM cell_notes 
                WHERE client_id = ?
            ''', (client_id,))
            rows = cursor.fetchall()
            notes = {}
            for row in rows:
                try:
                    rid = row['row_index']
                    col = row['column_key']
                    content = row['note_content']
                except (TypeError, IndexError):
                    rid = row[0]
                    col = row[1]
                    content = row[2]
                rid = _normalize_row_index(rid)
                if rid not in notes:
                    notes[rid] = {}
                notes[rid][col] = content
            return notes

        if _conn is not None:
            return _run(_conn.cursor())

        with get_connection() as conn:
            return _run(conn.cursor())
    except Exception as e:
        logging.error(f"Error fetching notes for {client_id}: {e}")
        return {}

def save_client_note(client_id, row_index, column_key, content, user):
    """
    Saves or updates a note.
    """
    try:
        row_index = _normalize_row_index(row_index)
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO cell_notes (client_id, row_index, column_key, note_content, created_by, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (client_id, row_index, column_key) DO UPDATE
                    SET note_content = EXCLUDED.note_content,
                        created_by = EXCLUDED.created_by,
                        updated_at = CURRENT_TIMESTAMP
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
        row_index = _normalize_row_index(row_index)
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
