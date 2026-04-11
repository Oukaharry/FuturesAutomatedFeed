"""Quick test to verify hierarchy structure without resetting anything."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Read and exec just the data + functions from reset_database.py
with open('reset_database.py', 'r') as f:
    code = f.read()
# Execute only up to "# ── Main ──" 
main_marker = code.index("\nif not os.path.exists(DB_PATH)")
exec(code[:main_marker])

all_clients = collect_all_clients()
hierarchy = build_hierarchy_json()
admin_count = len(hierarchy["admins"])
trader_count = sum(len(a["traders"]) for a in hierarchy["admins"].values())
print(f"Admins: {admin_count}, Traders: {trader_count}, Clients: {len(all_clients)}")
print()

for admin_name, admin_data in hierarchy["admins"].items():
    print(f"ADMIN: {admin_name} ({admin_data['email']})")
    for trader_name, trader_data in admin_data["traders"].items():
        clients = [c["name"] for c in trader_data["clients"]]
        print(f"  TRADER: {trader_name} ({trader_data['email']}) -> {len(clients)} clients: {clients}")
    print()

# Verify Samuel Tangara specifically (from user's screenshot)
print("=== Samuel Tangara detail ===")
print(json.dumps(hierarchy["admins"]["Samuel Tangara"], indent=2))
