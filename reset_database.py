"""
Reset database AND hierarchy: Delete ALL data, insert fresh clients,
and rebuild hierarchy.json with proper Admin → Trader → Client structure.
Run server-side: python reset_database.py
"""
import os, sys, json, sqlite3, shutil
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, 'dashboard', 'dashboard.db')
HIERARCHY_PATH = os.path.join(SCRIPT_DIR, 'config', 'hierarchy.json')
DEPLOY_HIERARCHY_PATH = os.path.join(SCRIPT_DIR, 'deployment_package', 'config', 'hierarchy.json')

# ── Known emails (from existing hierarchy & screenshots) ──
KNOWN_EMAILS = {
    # Admins
    "Marion Nyika": "marionnyika00@gmail.com",
    "Dennis Muthee": "dennismuthee.dm@gmail.com",
    "Kellen Njeri": "",
    "Hillary Litali": "litalihillary@gmail.com",
    "Samuel Tangara": "tangarasamuel18@gmail.com",
    "Vincent Odhiambo": "odhiambovincentmax@gmail.com",
    "Shaban Imran": "",
    "Philip Tangara": "tangsphilip@gmail.com",
    # Traders
    "Rodney Otieno": "rodneygenga1@gmail.com",
    "Steve Okok": "otienookok19@gmail.com",
    "Albert Andati": "albertandati2@gmail.com",
    "Timothy Olwande": "timothywando456@gmail.com",
    "Hesbon Okumu": "hezimstingofficial@gmail.com",
    "Tangara": "tangsphilip@gmail.com",
    # Clients
    "Joe Hicken": "joehickenfpf@gmail.com",
    "Davy Hicken": "davyhickenfpf@gmail.com",
    "Tyler Turner": "tyler.arthur.turner@gmail.com",
    "Watkins": "jpw.northstar77@gmail.com",
    "Rob Madsen": "berobsfundsok@gmail.com",
    "Ariel": "ariel@blueedgefinancial.com",
    "Josh Blackman": "josh.blackman.investing@gmail.com",
    "Nitin": "Nitinmalhotra20@gmail.com",
    "Brian Shore": "bshore17@gmail.com",
    "Jason Tracy": "jasontracy724@gmail.com",
    "Ian": "vpfianh@gmail.com",
    "Andrew Mackay": "mackayfutures@gmail.com",
    "Cole Goodwin": "goodwin.icon@gmail.com",
    "Ed Schreiner": "302shmed@gmail.com",
    "Thak Mano": "thakmano2@gmail.com",
    "Steven": "stevefishbach@gmail.com",
    "Aaron": "millearron1231@icloud.com",
    "Alex Mosart": "mostertalex8@gmail.com",
    "Jmark": "traderjmark@gmail.com",
    "Amber Wood": "ambrwood23@gmail.com",
    "Taras": "taras@anatsko.com",
    "Nate": "natetrade123456@gmail.com",
    "Reece": "reecewebb758@outlook.com",
    "Jake Lloyd": "jacoblloyd1214@gmail.com",
}

def email(name):
    return KNOWN_EMAILS.get(name, "")

# ── Complete hierarchy: Admin → Trader → Clients ──
# Each group: { admin: (name,), traders: [ { trader: (name,), clients: [(name, category), ...] } ] }
# Only entries with BEF/PRIVATE are actual clients; "" entries are admins/traders.
HIERARCHY_DATA = [
    # ── Marion Nyika ──
    {
        "admin": "Marion Nyika",
        "traders": [
            {"trader": "Fabian Omondi", "clients": [
                ("Joe Hicken", "PRIVATE"), ("Adrian Vazquez", "PRIVATE"),
                ("Soklay Tuy", "PRIVATE"), ("Isaac Woolsey", "PRIVATE"),
                ("Changlim Eang", "PRIVATE"), ("Leanghour", "PRIVATE"),
                ("Justin Reed", "PRIVATE"), ("Samuel Pew", "PRIVATE"),
            ]},
            {"trader": "Paul Ayieko", "clients": [
                ("Sariah Martinez", "PRIVATE"), ("Davy Hicken", "PRIVATE"),
                ("Emilio Martinez", "PRIVATE"), ("Abish Del Toro", "PRIVATE"),
                ("Silin Sorn", "PRIVATE"), ("Skyler Colvin", "PRIVATE"),
                ("Poyi Woolsey", "PRIVATE"), ("Varith Eng", "PRIVATE"),
            ]},
            {"trader": "Joy Ndua", "clients": []},
            {"trader": "Julieth Munialo", "clients": [
                ("Tyler Turner", "PRIVATE"), ("Stephen Ngatuvai", "PRIVATE"),
                ("Justin Wood", "PRIVATE"), ("Ashlee Williams", "PRIVATE"),
                ("Linet Lom", "PRIVATE"), ("Makara Sorn", "PRIVATE"),
                ("Chad Gines", "PRIVATE"), ("Alexis Williams", "PRIVATE"),
            ]},
            {"trader": "Wayne Ogolla", "clients": [
                ("Kresha Turner", "PRIVATE"), ("Zak Wood", "PRIVATE"),
                ("Kimlong Lom", "PRIVATE"), ("Josue Leon", "PRIVATE"),
                ("Alexander Estrada", "PRIVATE"), ("Lea Galan", "PRIVATE"),
                ("Francisco Morales", "PRIVATE"), ("Yuri Wong", "PRIVATE"),
                ("Hailee Wood", "PRIVATE"),
            ]},
        ]
    },
    # ── Dennis Muthee ──
    {
        "admin": "Dennis Muthee",
        "traders": [
            {"trader": "Rodney Otieno", "clients": [
                ("Jian Sheng Zhou", "BEF"), ("Joe Mittlestaedt", "PRIVATE"),
                ("Mohit", "BEF"), ("Nitin", "BEF"),
                ("Brian Shore", "BEF"), ("Jason Tracy", "BEF"),
                ("Bec Tracy", "BEF"),
            ]},
            {"trader": "Steve Okok", "clients": [
                ("Sagen", "PRIVATE"), ("Jono", "PRIVATE"),
                ("Kevin Williams", "PRIVATE"), ("Watkins", "PRIVATE"),
                ("Rob Madsen", "PRIVATE"), ("Conner", "PRIVATE"),
                ("Aaron", "PRIVATE"),
            ]},
        ]
    },
    # ── Kellen Njeri ──
    {
        "admin": "Kellen Njeri",
        "traders": [
            {"trader": "Gideon Oruma", "clients": [
                ("Andrew Mackay", "PRIVATE"), ("Kaden Johnson", "PRIVATE"),
                ("Chris Ream", "BEF"), ("Sean Ream", "BEF"),
                ("Kelly Ream", "BEF"), ("Halli Hicken", "PRIVATE"),
                ("Rod Halford", "PRIVATE"), ("Jon Rylat", "BEF"),
            ]},
        ]
    },
    # ── Hillary Litali ──
    {
        "admin": "Hillary Litali",
        "traders": [
            {"trader": "Albert Andati", "clients": [
                ("Ian", "PRIVATE"), ("Oliver Den", "BEF"),
                ("Eduardo Cruz", "BEF"), ("Ellie Loyd", "PRIVATE"),
                ("Ferdinand Stolk", "BEF"), ("Daniel P", "BEF"),
            ]},
            {"trader": "Timothy Olwande", "clients": [
                ("Nikita", "BEF"), ("Gregoz Krepa", "BEF"),
                ("Riaz", "BEF"), ("Seong Jing Park", "BEF"),
                ("Anthony Arnold", "BEF"), ("Steven", "BEF"),
                ("Cassey Lloyd", "PRIVATE"),
            ]},
        ]
    },
    # ── Samuel Tangara ──
    {
        "admin": "Samuel Tangara",
        "traders": [
            {"trader": "Hesbon Okumu", "clients": [
                ("Mark Sullivan", "BEF"), ("Reece", "BEF"),
                ("Taras", "BEF"), ("Nate", "PRIVATE"),
                ("David S", "BEF"), ("Jmark", "BEF"),
                ("Amber Wood", "PRIVATE"),
            ]},
            {"trader": "John Njihia", "clients": [
                ("Cole Goodwin", "BEF"), ("Ed Schreiner", "BEF"),
                ("Guarav Kumar", "BEF"), ("Jeffrey Hinds", "BEF"),
                ("Pierre Alexandre", "BEF"), ("William Lockridge", "BEF"),
                ("Erik Johnson", "BEF"),
            ]},
        ]
    },
    # ── Vincent Odhiambo ──
    {
        "admin": "Vincent Odhiambo",
        "traders": [
            {"trader": "Hezil Hill", "clients": [
                ("Tyler Dubroc", "BEF"), ("Gregory Falk", "BEF"),
                ("Glen Quebec", "BEF"), ("Ryan Burbidge", "BEF"),
                ("Jiangquan Zhang", "BEF"), ("Josh Blackman", "BEF"),
                ("Merrinson", "BEF"),
            ]},
        ]
    },
    # ── Shaban Imran ── (self-trader for first clients, then Jake Lloyd as 2nd trader)
    {
        "admin": "Shaban Imran",
        "traders": [
            {"trader": "Shaban Imran", "clients": [
                ("Aymeric", "BEF"), ("Alex Mosart", "BEF"),
                ("Ariel", "BEF"),
            ]},
            {"trader": "Jake Lloyd", "clients": [
                ("Thak Mano", "BEF"), ("Armin Mansory", "BEF"),
                ("Ivan Kolyabin", "BEF"),
            ]},
        ]
    },
    # ── Philip Tangara ──
    {
        "admin": "Philip Tangara",
        "traders": [
            {"trader": "Tangara", "clients": [
                ("Adam Wenig", "BEF"), ("Fallback", "PRIVATE"),
            ]},
        ]
    },
]


def build_hierarchy_json():
    """Build hierarchy.json structure from HIERARCHY_DATA."""
    admins = {}
    for group in HIERARCHY_DATA:
        admin_name = group["admin"]
        traders_dict = {}
        for t in group["traders"]:
            trader_name = t["trader"]
            clients_list = []
            for client_name, category in t["clients"]:
                cat = "BEF" if category.upper() == "BEF" else "Private"
                clients_list.append({
                    "name": client_name,
                    "email": email(client_name),
                    "category": cat,
                })
            traders_dict[trader_name] = {
                "email": email(trader_name),
                "clients": clients_list,
            }
        admins[admin_name] = {
            "email": email(admin_name),
            "traders": traders_dict,
        }

    return {
        "super_admin": {
            "name": "baller",
            "email": "ballerquotesvpf@gmail.com"
        },
        "admins": admins,
    }


def collect_all_clients():
    """Collect all actual clients (BEF/PRIVATE) from hierarchy data."""
    clients = []
    seen = set()
    for group in HIERARCHY_DATA:
        for t in group["traders"]:
            for client_name, category in t["clients"]:
                if client_name not in seen:
                    seen.add(client_name)
                    clients.append((client_name, category))
    return clients


# ── Main ──
if not os.path.exists(DB_PATH):
    print(f"ERROR: Database not found at {DB_PATH}")
    sys.exit(1)

all_clients = collect_all_clients()
hierarchy = build_hierarchy_json()
admin_count = len(hierarchy["admins"])
trader_count = sum(len(a["traders"]) for a in hierarchy["admins"].values())

print(f"=== RESET DATABASE & HIERARCHY ===")
print(f"\nHierarchy: {admin_count} admins, {trader_count} traders, {len(all_clients)} clients")
print(f"\nAdmins:")
for admin_name, admin_data in hierarchy["admins"].items():
    traders = list(admin_data["traders"].keys())
    client_count = sum(len(t["clients"]) for t in admin_data["traders"].values())
    print(f"  {admin_name} → traders: {', '.join(traders)} → {client_count} clients")

print(f"\nDatabase tables to be WIPED:")
print(f"  - clients_data, data_history, cell_notes, daily_watermarks, waterlog_periods")
print(f"\nHierarchy files to be OVERWRITTEN:")
print(f"  - {HIERARCHY_PATH}")
if os.path.exists(DEPLOY_HIERARCHY_PATH):
    print(f"  - {DEPLOY_HIERARCHY_PATH}")

print(f"\nThis will DELETE ALL existing data and rebuild with {len(all_clients)} clients.")

confirm = input("\nType RESET to confirm: ").strip()
if confirm != "RESET":
    print("Aborted.")
    sys.exit(0)

# Step 1: Backup old hierarchy
if os.path.exists(HIERARCHY_PATH):
    backup = HIERARCHY_PATH + '.bak'
    shutil.copy2(HIERARCHY_PATH, backup)
    print(f"\nBacked up old hierarchy to {backup}")

# Step 2: Write new hierarchy.json
os.makedirs(os.path.dirname(HIERARCHY_PATH), exist_ok=True)
with open(HIERARCHY_PATH, 'w', encoding='utf-8') as f:
    json.dump(hierarchy, f, indent=4, ensure_ascii=False)
print(f"Wrote new hierarchy: {HIERARCHY_PATH}")

# Also update deployment copy if it exists
if os.path.exists(os.path.dirname(DEPLOY_HIERARCHY_PATH)):
    with open(DEPLOY_HIERARCHY_PATH, 'w', encoding='utf-8') as f:
        json.dump(hierarchy, f, indent=4, ensure_ascii=False)
    print(f"Wrote deployment hierarchy: {DEPLOY_HIERARCHY_PATH}")

# Step 3: Reset database
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print("\nDeleting all existing data...")
for table in ['clients_data', 'data_history', 'cell_notes', 'daily_watermarks', 'waterlog_periods']:
    try:
        cursor.execute(f'DELETE FROM {table}')
        print(f"  Cleared {table} ({cursor.rowcount} rows)")
    except Exception as e:
        print(f"  Warning: {table}: {e}")

# Step 4: Insert fresh clients (only actual clients, not admins/traders)
now = datetime.utcnow().isoformat()
empty_stats = json.dumps({})
empty_list = json.dumps([])
empty_dict = json.dumps({})

print(f"\nInserting {len(all_clients)} clients...")
for name, category in all_clients:
    cat = "BEF" if category.upper() == "BEF" else "Private"
    identity = {"name": name, "profile": cat, "category": cat}
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
        print(f"  + {name} ({cat})")
    except Exception as e:
        print(f"  ERROR inserting {name}: {e}")

conn.commit()
conn.close()

print(f"\n=== DONE ===")
print(f"Hierarchy: {admin_count} admins, {trader_count} traders")
print(f"Database: {len(all_clients)} clients inserted with clean/zero data")
print(f"\nReload your web app for changes to take effect.")
