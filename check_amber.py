import sqlite3
import os

db_path = r"c:\\Users\\harry\\Music\\MT5HedgingEngine\\dashboard\\dashboard.db"

if os.path.exists(db_path):
    print(f"Database found at {db_path}")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # 1. List Tables
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cur.fetchall()
    print("Tables:", [t[0] for t in tables])
    
    print("-" * 30)

    # 2. Check for Amber in relevant tables
    for t_info in tables:
        t_name = t_info[0]
        # Only check likely tables
        if 'key' not in t_name and 'sqlite' not in t_name: # skip system/keys
            try:
                # Get column names
                cur.execute(f"PRAGMA table_info({t_name})")
                cols = [info[1] for info in cur.fetchall()]
                
                # Search cols that might contain client name
                search_cols = [c for c in cols if any(x in c.lower() for x in ['client', 'name', 'user', 'id', 'email'])]
                
                for sc in search_cols:
                    try:
                        cur.execute(f"SELECT {sc} FROM {t_name} WHERE {sc} LIKE '%Amber%'")
                        matches = cur.fetchall()
                        if matches:
                            print(f"MATCH in {t_name}.{sc}:")
                            for m in matches:
                                val = m[0]
                                # Highlight trailing spaces
                                if isinstance(val, str):
                                    print(f"  '{val}' (Length: {len(val)})")
                                else:
                                    print(f"  {val}")
                    except Exception as e: 
                        # print(e)
                        pass
            except Exception as e:
                print(f"Error scanning {t_name}: {e}")
    conn.close()
else:
    print(f"Database not found at {db_path}")
