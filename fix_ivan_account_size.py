"""
One-time fix: Set Account Size to $50,000 for all evaluations
belonging to Ivan Kolyabin where Account Size is blank.
"""

import json
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard", "dashboard.db")
CLIENT_ID = "Ivan Kolyabin"
NEW_SIZE = "$50,000"

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT evaluations FROM clients_data WHERE client_id = ?", (CLIENT_ID,))
    row = cur.fetchone()
    if not row:
        print(f"Client '{CLIENT_ID}' not found in database.")
        conn.close()
        return

    evaluations = json.loads(row[0]) if row[0] else []
    updated = 0

    for i, ev in enumerate(evaluations):
        current = (ev.get("Account Size") or "").strip()
        if not current:
            ev["Account Size"] = NEW_SIZE
            updated += 1
            print(f"  Row {i + 1}: set Account Size → {NEW_SIZE}")
        else:
            print(f"  Row {i + 1}: already has Account Size = {current}, skipped")

    if updated:
        cur.execute(
            "UPDATE clients_data SET evaluations = ? WHERE client_id = ?",
            (json.dumps(evaluations), CLIENT_ID),
        )
        conn.commit()
        print(f"\nDone. Updated {updated} evaluation(s) for {CLIENT_ID}.")
    else:
        print("\nNo blank Account Size fields found. Nothing to update.")

    conn.close()


if __name__ == "__main__":
    main()
