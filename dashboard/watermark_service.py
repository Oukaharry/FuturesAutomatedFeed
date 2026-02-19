from dashboard.database import get_connection
from datetime import datetime, timedelta
import logging

def save_daily_profit(client_id, net_profit, date_str=None, source='auto'):
    """
    Saves or updates the daily net profit for a client.
    date_str: 'YYYY-MM-DD', defaults to today.
    """
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')
        
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            # Use SQLite's upsert capability (INSERT OR REPLACE)
            # Since we defined PRIMARY KEY (client_id, date)
            cursor.execute('''
                INSERT OR REPLACE INTO daily_watermarks (client_id, date, net_profit_complete, source, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (client_id, date_str, float(net_profit), source))
            conn.commit()
            logging.info(f"Saved daily watermark for {client_id} on {date_str}: ${net_profit} ({source})")
            return True
    except Exception as e:
        logging.error(f"Error saving daily profit: {e}")
        return False

def get_watermark_history(client_id, days=30):
    """
    Returns list of dicts: [{'date': 'YYYY-MM-DD', 'profit': 123.45}, ...]
    Sorted by date.
    """
    try:
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT date, net_profit_complete 
                FROM daily_watermarks 
                WHERE client_id = ? AND date >= ? 
                ORDER BY date ASC
            ''', (client_id, cutoff_date))
            rows = cursor.fetchall()
            return [{'date': row['date'], 'profit': row['net_profit_complete']} for row in rows]
    except Exception as e:
        logging.error(f"Error getting watermark history: {e}")
        return []

def get_lower_watermark(client_id, days=14):
    """
    Returns the minimum profit recorded in the last X days.
    Returns: {'date': 'YYYY-MM-DD', 'profit': 123.45} or None
    """
    history = get_watermark_history(client_id, days)
    if not history:
        return None
    
    # Calculate min
    min_record = min(history, key=lambda x: x['profit'])
    return min_record

def get_high_watermark(client_id, days=14):
    """
    Returns the maximum profit recorded in the last X days.
    Returns: {'date': 'YYYY-MM-DD', 'profit': 123.45} or None
    """
    history = get_watermark_history(client_id, days)
    if not history:
        return None
    
    # Calculate max
    max_record = max(history, key=lambda x: x['profit'])
    return max_record

def get_bulk_watermarks(days=14):
    """
    Returns a dictionary of watermarks for all clients over the last X days.
    Returns: {client_id: {'high': float, 'low': float}}
    """
    try:
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT client_id, MAX(net_profit_complete) as high, MIN(net_profit_complete) as low
                FROM daily_watermarks
                WHERE date >= ?
                GROUP BY client_id
            ''', (cutoff_date,))
            rows = cursor.fetchall()
            # rows are usually tuples or dict-like depending on row_factory.
            # Assuming sqlite3.Row or tuple.
            result = {}
            for row in rows:
                # row accessible by index if tuple, or key if Row.
                # standard sqlite3 without row_factory returns tuples.
                # But dashboard/database.py might set row_factory.
                # Let's assume keys work if Row, or index if tuple?
                # Safer: check type or try/except.
                # Actually, check get_connection implementation.
                try: # dict-like
                    c_id = row['client_id']
                    high = row['high']
                    low = row['low']
                except: # tuple
                    c_id = row[0]
                    high = row[1]
                    low = row[2]
                
                result[c_id] = {'high': high, 'low': low}
            return result
    except Exception as e:
        logging.error(f"Error getting bulk watermarks: {e}")
        return {}

def get_aggregate_watermarks(days=14):
    """
    Returns the High and Low Watermarks for the aggregated portfolio (sum of all clients)
    over the last X days.
    Returns: {'hwm': float, 'lwm': float}
    """
    try:
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        with get_connection() as conn:
            cursor = conn.cursor()
            # Sum profit for each day
            cursor.execute('''
                SELECT date, SUM(net_profit_complete) as total_profit
                FROM daily_watermarks
                WHERE date >= ?
                GROUP BY date
                ORDER BY date ASC
            ''', (cutoff_date,))
            rows = cursor.fetchall()
            
            if not rows:
                return {'hwm': 0.0, 'lwm': 0.0}

            # rows is list of tuples/Rows
            # Extract daily totals
            daily_totals = []
            for row in rows:
                try:
                    daily_totals.append(row['total_profit'])
                except:
                    daily_totals.append(row[1])
            
            if not daily_totals:
                return {'hwm': 0.0, 'lwm': 0.0}

            return {
                'hwm': max(daily_totals),
                'lwm': min(daily_totals)
            }
    except Exception as e:
        logging.error(f"Error getting aggregate watermarks: {e}")
        return {'hwm': 0.0, 'lwm': 0.0}

def bulk_save_history(client_id, history_data):
    """
    Bulk saves history from external source (e.g., sheet).
    history_data: list of {'date': 'YYYY-MM-DD', 'profit': 123.45}
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            for record in history_data:
                cursor.execute('''
                    INSERT OR IGNORE INTO daily_watermarks (client_id, date, net_profit_complete, source, created_at)
                    VALUES (?, ?, ?, 'sheet_import', CURRENT_TIMESTAMP)
                ''', (client_id, record['date'], float(record['profit'])))
            conn.commit()
            return True
    except Exception as e:
        logging.error(f"Error bulk saving history: {e}")
        return False
