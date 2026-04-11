import sqlite3, json

conn = sqlite3.connect('dashboard/dashboard.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# List all tables first
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r['name'] for r in cur.fetchall()]
print("Tables:", tables)

# Check for client-like tables
for t in tables:
    cur.execute(f"PRAGMA table_info({t})")
    cols = [r['name'] for r in cur.fetchall()]
    print(f"\n  {t}: {cols}")
    # Show a sample row
    cur.execute(f"SELECT * FROM {t} LIMIT 1")
    sample = cur.fetchone()
    if sample:
        print(f"    sample: {dict(sample)}")

# Search for chris in any table that has a name or client column
for t in tables:
    cur.execute(f"PRAGMA table_info({t})")
    cols = [r['name'] for r in cur.fetchall()]
    name_cols = [c for c in cols if 'name' in c.lower() or 'client' in c.lower()]
    for nc in name_cols:
        cur.execute(f"SELECT * FROM {t} WHERE {nc} LIKE '%chris%' OR {nc} LIKE '%ream%' LIMIT 5")
        rows = cur.fetchall()
        if rows:
            print(f"\n=== Found in {t}.{nc} ===")
            for r in rows:
                print(json.dumps(dict(r), indent=2, default=str))
rows = cur.fetchall()
if not rows:
    cur.execute("SELECT id, name FROM clients")
    all_clients = cur.fetchall()
    print('No Chris Ream found. All clients:')
    for c in all_clients:
        print(f'  {c["id"]} - {c["name"]}')
else:
    for r in rows:
        client = dict(r)
        cid = client['id']
        print(f"\n=== CLIENT: {client['name']} (id={cid}) ===")
        print(json.dumps(client, indent=2, default=str))

        # Get stored statistics
        cur.execute("SELECT * FROM client_statistics WHERE client_id = ?", (cid,))
        stats = cur.fetchall()
        if stats:
            print(f"\n--- Statistics ({len(stats)} rows) ---")
            for s in stats:
                d = dict(s)
                print(json.dumps(d, indent=2, default=str))

        # Get stored evaluations/deals
        cur.execute("SELECT COUNT(*) as cnt FROM client_data WHERE client_id = ?", (cid,))
        data_count = cur.fetchone()
        print(f"\n--- client_data rows: {data_count['cnt']} ---")

        # Get daily watermarks
        cur.execute("SELECT * FROM daily_watermarks WHERE client_id = ? ORDER BY date DESC LIMIT 10", (cid,))
        wm = cur.fetchall()
        if wm:
            print(f"\n--- Daily Watermarks (last 10) ---")
            for w in wm:
                print(dict(w))

        # Get waterlog periods
        cur.execute("SELECT * FROM waterlog_periods WHERE client_id = ? ORDER BY from_date", (cid,))
        wp = cur.fetchall()
        if wp:
            print(f"\n--- Waterlog Periods ({len(wp)}) ---")
            for p in wp:
                print(dict(p))

conn.close()
