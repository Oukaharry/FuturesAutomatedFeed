"""Quick database diagnostic"""
from database import get_connection, init_database

# Initialize DB if needed
init_database()

with get_connection() as conn:
    cursor = conn.cursor()

    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    print(f"Tables: {tables}")

    # Check clients_data
    if 'clients_data' in tables:
        cursor.execute("SELECT client_id, last_updated FROM clients_data")
        rows = cursor.fetchall()
        print(f"\nClients in database: {len(rows)}")
        for row in rows:
            print(f"  - {row[0]} (updated: {row[1]})")
    else:
        print("\nNo clients_data table!")

    # Check hierarchy
    if 'hierarchy' in tables:
        cursor.execute("SELECT admin_id, trader_id, client_id FROM hierarchy")
        rows = cursor.fetchall()
        print(f"\nHierarchy entries: {len(rows)}")
        for row in rows[:5]:
            print(f"  - Admin: {row[0]}, Trader: {row[1]}, Client: {row[2]}")
        if len(rows) > 5:
            print(f"  ... and {len(rows) - 5} more")
