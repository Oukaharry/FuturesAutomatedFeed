"""
scripts/migrate_hierarchy.py
-----------------------------
Transform hierarchy.json from the nested production format to the flat format
our current system expects.

Production format (nested):
  admins -> { admin -> { traders -> { trader -> { clients: [...] } } } }

Our format (flat):
  traders -> { trader -> { email } }              (top-level registry)
  admins  -> { admin  -> { clients: [ { ..., assigned_trader } ] } }

Run:
    python scripts/migrate_hierarchy.py                     # default: config/hierarchy.json
    python scripts/migrate_hierarchy.py --file path/to/hierarchy.json
"""

import json
import os
import sys
import shutil
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FILE = os.path.join(BASE_DIR, "config", "hierarchy.json")


def migrate(data):
    """Convert nested hierarchy to flat format. Returns new dict."""

    # Already in flat format? (has top-level traders AND admins have clients lists)
    if "traders" in data and isinstance(data.get("traders"), dict):
        sample = next(iter(data.get("admins", {}).values()), None)
        if sample and "clients" in sample and "traders" not in sample:
            print("  Already in flat format — nothing to do.")
            return data

    traders_registry = {}
    new_admins = {}

    for admin_name, admin_data in data.get("admins", {}).items():
        flat_clients = []

        for trader_name, trader_data in admin_data.get("traders", {}).items():
            # Collect trader into global registry
            if trader_name not in traders_registry:
                traders_registry[trader_name] = {
                    "email": trader_data.get("email", "")
                }

            # Flatten clients with assigned_trader
            for client in trader_data.get("clients", []):
                c = dict(client)
                c["assigned_trader"] = trader_name
                flat_clients.append(c)

        # Build admin entry — carry over all non-traders fields
        admin_entry = {}
        for key, val in admin_data.items():
            if key != "traders":
                admin_entry[key] = val
        admin_entry["clients"] = flat_clients

        new_admins[admin_name] = admin_entry

    result = {}
    # Preserve super_admin
    if "super_admin" in data:
        result["super_admin"] = data["super_admin"]

    result["traders"] = dict(sorted(traders_registry.items()))
    result["admins"] = new_admins

    return result


def main():
    parser = argparse.ArgumentParser(description="Migrate hierarchy.json to flat format")
    parser.add_argument("--file", default=DEFAULT_FILE, help="Path to hierarchy.json")
    parser.add_argument("--dry-run", action="store_true", help="Print result without writing")
    args = parser.parse_args()

    filepath = os.path.abspath(args.file)
    if not os.path.exists(filepath):
        print(f"Error: {filepath} not found")
        sys.exit(1)

    print(f"Reading {filepath} ...")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = migrate(data)

    # Stats
    traders_count = len(result.get("traders", {}))
    admins_count = len(result.get("admins", {}))
    clients_count = sum(len(a.get("clients", [])) for a in result.get("admins", {}).values())
    print(f"  {traders_count} traders, {admins_count} admins, {clients_count} clients")

    if args.dry_run:
        print("\n--- DRY RUN (no file written) ---")
        print(json.dumps(result, indent=4))
        return

    # Backup original
    backup = filepath + ".bak"
    shutil.copy2(filepath, backup)
    print(f"  Backup saved -> {backup}")

    # Write migrated file
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4)

    print(f"  Written {filepath}")
    print("Done.")


if __name__ == "__main__":
    main()
