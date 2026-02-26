import pandas as pd
import requests
import io
import logging

SHEET_ID = "10eGsivGm5GOaH0orB2AAbjpXzDwDkYY1gIZgux9nIjI"
STATS_GID = "839895136"
WATERLOG_GID = "520289647"

def get_sheet_csv(gid):
    try:
        url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.content.decode('utf-8')
    except Exception as e:
        logging.error(f"Error fetching sheet CSV (gid={gid}): {e}")
        return None

def fetch_waterlog_data():
    """Fetches and parses the Profitability Waterlog tab."""
    csv_content = get_sheet_csv(WATERLOG_GID)
    if not csv_content:
        return None

    try:
        # Read the CSV into a pandas DataFrame
        df = pd.read_csv(io.StringIO(csv_content))
        
        data = []
        for index, row in df.iterrows():
            # Handle potential column name mismatches or extra spaces
            timestamp = row.get('Timestamp', '')
            value = row.get('Value', '')
            
            # 'From ' often has a trailing space in CSV exports
            from_date = row.get('From ', row.get('From', ''))
            
            to_date = row.get('To', '')
            low = row.get('Low', '')
            high = row.get('High', '')
            profit_split = row.get('Profit Split', '')
            
            entry = {
                'timestamp': str(timestamp) if pd.notna(timestamp) else '',
                'value': str(value) if pd.notna(value) else '',
                'from_date': str(from_date) if pd.notna(from_date) else '',
                'to_date': str(to_date) if pd.notna(to_date) else '',
                'low': str(low) if pd.notna(low) else '',
                'high': str(high) if pd.notna(high) else '',
                'profit_split': str(profit_split) if pd.notna(profit_split) else ''
            }
            data.append(entry)
            
        return data
    except Exception as e:
        logging.error(f"Error parsing Waterlog data: {e}")
        return None

def fetch_stats_data():
    """Fetches and parses the Stats tab."""
    csv_content = get_sheet_csv(STATS_GID)
    if not csv_content:
        return None

    try:
        # Return raw rows for flexible rendering
        df = pd.read_csv(io.StringIO(csv_content), header=None)
        df = df.fillna('')
        return df.values.tolist()
    except Exception as e:
        logging.error(f"Error parsing Stats data: {e}")
        return None
