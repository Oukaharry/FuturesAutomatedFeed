"""Find Joe Hickens data across the database and hierarchy"""
import sqlite3
import json

conn = sqlite3.connect('dashboard/dashboard.db')
c = conn.cursor()

tables = ['clients_data', 'data_history', 'cell_notes', 'daily_watermarks', 'waterlog_periods']
for t in tables:
    try:
        c.execute(f"SELECT DISTINCT client_id FROM {t} WHERE client_id LIKE ?", ('%ick%',))
        ids = [r[0] for r in c.fetchall()]
        if ids:
            c.execute(f"SELECT COUNT(*) FROM {t} WHERE client_id LIKE ?", ('%ick%',))
            count = c.fetchone()[0]
            print(f"{t}: {count} rows, client_ids: {ids}")
    except Exception as e:
        print(f"{t}: error - {e}")

# Check user_credentials
try:
    c.execute("SELECT username, user_type FROM user_credentials WHERE username LIKE ?", ('%ick%',))
    for row in c.fetchall():
        print(f"user_credentials: {row}")
except Exception as e:
    print(f"user_credentials: {e}")

# Check hierarchy
with open('config/hierarchy.json', 'r') as f:
    h = json.load(f)
for admin, adata in h.get('admins', {}).items():
    for trader, tdata in adata.get('traders', {}).items():
        for client in tdata.get('clients', []):
            name = client.get('name', '') if isinstance(client, dict) else client
            if 'ick' in name.lower():
                print(f"Hierarchy: {admin} > {trader} > {name}")

conn.close()
