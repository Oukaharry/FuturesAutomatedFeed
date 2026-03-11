"""
Reset database: Delete ALL client data and insert fresh clients with zero data.
Run server-side: python reset_database.py
"""
import os, sys, json, sqlite3
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, 'dashboard', 'dashboard.db')

# ── Client list with categories ──
CLIENTS = [
    # Group 1
    ("Marion Nyika", ""),
    ("Fabian Omondi", ""),
    ("Joe Hicken", "PRIVATE"),
    ("Adrian Vazquez", "PRIVATE"),
    ("Soklay Tuy", "PRIVATE"),
    ("Isaac Woolsey", "PRIVATE"),
    ("Changlim Eang", "PRIVATE"),
    ("Leanghour", "PRIVATE"),
    ("Justin Reed", "PRIVATE"),
    ("Samuel Pew", "PRIVATE"),
    ("Paul Ayieko", ""),
    ("Sariah Martinez", "PRIVATE"),
    ("Davy Hicken", "PRIVATE"),
    ("Emilio Martinez", "PRIVATE"),
    ("Abish Del Toro", "PRIVATE"),
    ("Silin Sorn", "PRIVATE"),
    ("Skyler Colvin", "PRIVATE"),
    ("Poyi Woolsey", "PRIVATE"),
    ("Varith Eng", "PRIVATE"),
    ("Joy Ndua", ""),
    ("Julieth Munialo", ""),
    ("Tyler Turner", "PRIVATE"),
    ("Stephen Ngatuvai", "PRIVATE"),
    ("Justin Wood", "PRIVATE"),
    ("Ashlee Williams", "PRIVATE"),
    ("Linet Lom", "PRIVATE"),
    ("Makara Sorn", "PRIVATE"),
    ("Chad Gines", "PRIVATE"),
    ("Alexis Williams", "PRIVATE"),
    ("Wayne Ogolla", ""),
    ("Kresha Turner", "PRIVATE"),
    ("Zak Wood", "PRIVATE"),
    ("Kimlong Lom", "PRIVATE"),
    ("Josue Leon", "PRIVATE"),
    ("Alexander Estrada", "PRIVATE"),
    ("Lea Galan", "PRIVATE"),
    ("Francisco Morales", "PRIVATE"),
    ("Yuri Wong", "PRIVATE"),
    ("Hailee Wood", "PRIVATE"),

    # Group 2
    ("Dennis Muthee", ""),
    ("Rodney Otieno", ""),
    ("Jian Sheng Zhou", "BEF"),
    ("Joe Mittlestaedt", "PRIVATE"),
    ("Mohit", "BEF"),
    ("Nitin", "BEF"),
    ("Brian Shore", "BEF"),
    ("Jason Tracy", "BEF"),
    ("Bec Tracy", "BEF"),
    ("Steve Okok", ""),
    ("Sagen", "PRIVATE"),
    ("Jono", "PRIVATE"),
    ("Kevin Williams", "PRIVATE"),
    ("Watkins", "PRIVATE"),
    ("Rob Madsen", "PRIVATE"),
    ("Conner", "PRIVATE"),
    ("Aaron", "PRIVATE"),

    # Group 3
    ("Kellen Njeri", ""),
    ("Gideon Oruma", ""),
    ("Andrew Mackay", "PRIVATE"),
    ("Kaden Johnson", "PRIVATE"),
    ("Chris Ream", "BEF"),
    ("Sean Ream", "BEF"),
    ("Kelly Ream", "BEF"),
    ("Halli Hicken", "PRIVATE"),
    ("Rod Halford", "PRIVATE"),
    ("Jon Rylat", "BEF"),

    # Group 4
    ("Hillary Litali", ""),
    ("Albert Andati", ""),
    ("Ian", "PRIVATE"),
    ("Oliver Den", "BEF"),
    ("Eduardo Cruz", "BEF"),
    ("Ellie Loyd", "PRIVATE"),
    ("Ferdinand Stolk", "BEF"),
    ("Daniel P", "BEF"),
    ("Timothy Olwande", ""),
    ("Nikita", "BEF"),
    ("Gregoz Krepa", "BEF"),
    ("Riaz", "BEF"),
    ("Seong Jing Park", "BEF"),
    ("Anthony Arnold", "BEF"),
    ("Steven", "BEF"),
    ("Cassey Lloyd", "PRIVATE"),

    # Group 5
    ("Samuel Tangara", ""),
    ("Hesbon Okumu", ""),
    ("Mark Sullivan", "BEF"),
    ("Reece", "BEF"),
    ("Taras", "BEF"),
    ("Nate", "PRIVATE"),
    ("David S", "BEF"),
    ("Jmark", "BEF"),
    ("Amber Wood", "PRIVATE"),
    ("John Njihia", ""),
    ("Cole Goodwin", "BEF"),
    ("Ed Schreiner", "BEF"),
    ("Guarav Kumar", "BEF"),
    ("Jeffrey Hinds", "BEF"),
    ("Pierre Alexandre", "BEF"),
    ("William Lockridge", "BEF"),
    ("Erik Johnson", "BEF"),

    # Group 6
    ("Vincent Odhiambo", ""),
    ("Hezil Hill", ""),
    ("Tyler Dubroc", "BEF"),
    ("Gregory Falk", "BEF"),
    ("Glen Quebec", "BEF"),
    ("Ryan Burbidge", "BEF"),
    ("Jiangquan Zhang", "BEF"),
    ("Josh Blackman", "BEF"),
    ("Merrinson", "BEF"),

    # Group 7
    ("Shaban Imran", ""),
    ("Aymeric", "BEF"),
    ("Alex Mosart", "BEF"),
    ("Ariel", "BEF"),
    ("Jake Lloyd", ""),
    ("Thak Mano", "BEF"),
    ("Armin Mansory", "BEF"),
    ("Ivan Kolyabin", "BEF"),

    # Group 8
    ("Philip Tangara", ""),
    ("Tangara", ""),
    ("Adam Wenig", "BEF"),
    ("Fallback", "PRIVATE"),
]

# ── Main ──
if not os.path.exists(DB_PATH):
    print(f"ERROR: Database not found at {DB_PATH}")
    sys.exit(1)

# Deduplicate by name (keep first occurrence)
seen = set()
unique_clients = []
for name, cat in CLIENTS:
    if name not in seen:
        seen.add(name)
        unique_clients.append((name, cat))
    else:
        print(f"  Skipping duplicate: {name}")

print(f"Total unique clients to insert: {len(unique_clients)}")
print(f"\nTables to be WIPED:")
print(f"  - clients_data")
print(f"  - data_history")
print(f"  - cell_notes")
print(f"  - daily_watermarks")
print(f"  - waterlog_periods")
print(f"\nThis will DELETE ALL existing data and replace with {len(unique_clients)} fresh clients.")

confirm = input("\nType RESET to confirm: ").strip()
if confirm != "RESET":
    print("Aborted.")
    sys.exit(0)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Step 1: Delete all data
print("\nDeleting all existing data...")
for table in ['clients_data', 'data_history', 'cell_notes', 'daily_watermarks', 'waterlog_periods']:
    try:
        cursor.execute(f'DELETE FROM {table}')
        print(f"  Cleared {table} ({cursor.rowcount} rows)")
    except Exception as e:
        print(f"  Warning: {table}: {e}")

# Step 2: Insert fresh clients
now = datetime.utcnow().isoformat()
empty_stats = json.dumps({})
empty_list = json.dumps([])
empty_dict = json.dumps({})

print(f"\nInserting {len(unique_clients)} clients...")
for name, category in unique_clients:
    identity = {"name": name}
    if category:
        identity["profile"] = category
        identity["category"] = category
    
    try:
        cursor.execute('''
            INSERT INTO clients_data (
                client_id, deals, positions, account, evaluations,
                statistics, dropdown_options, identity, last_updated,
                hedge_accounts, prop_accounts, vps_accounts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            name, empty_list, empty_list, empty_dict, empty_list,
            empty_stats, empty_dict, json.dumps(identity), now,
            empty_list, empty_list, empty_list
        ))
        print(f"  + {name} ({category or 'default'})")
    except Exception as e:
        print(f"  ERROR inserting {name}: {e}")

conn.commit()
conn.close()

print(f"\nDone. Inserted {len(unique_clients)} clients with clean/zero data.")
