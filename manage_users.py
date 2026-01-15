import os
import sys
from config.hierarchy import SYSTEM_HIERARCHY, add_admin, add_trader, add_client

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    print("="*50)
    print("      MT5 Hedging Engine - User Management")
    print("="*50)

def list_hierarchy():
    print("\n--- Current Hierarchy ---")
    if not SYSTEM_HIERARCHY["admins"]:
        print("No admins found.")
        return

    for admin, admin_data in SYSTEM_HIERARCHY["admins"].items():
        print(f"\n[Admin] {admin}")
        traders = admin_data.get("traders", {})
        if not traders:
            print("  No traders assigned.")
        for trader, clients in traders.items():
            print(f"  └── [Trader] {trader}")
            if not clients:
                print("      No clients assigned.")
            for client in clients:
                print(f"      └── [Client] {client}")

def add_new_admin():
    print("\n--- Add New Admin ---")
    name = input("Enter Admin Name: ").strip()
    if not name:
        print("Name cannot be empty.")
        return
    
    if add_admin(name):
        print(f"Success: Admin '{name}' added.")
    else:
        print(f"Error: Admin '{name}' already exists.")

def add_new_trader():
    print("\n--- Add New Trader ---")
    admins = list(SYSTEM_HIERARCHY["admins"].keys())
    if not admins:
        print("No admins available. Create an admin first.")
        return

    print("Select Admin:")
    for i, admin in enumerate(admins):
        print(f"{i+1}. {admin}")
    
    try:
        choice = int(input("Choice (Number): ")) - 1
        if 0 <= choice < len(admins):
            admin_name = admins[choice]
            trader_name = input("Enter Trader Name: ").strip()
            if not trader_name:
                print("Name cannot be empty.")
                return
            
            if add_trader(admin_name, trader_name):
                print(f"Success: Trader '{trader_name}' added to Admin '{admin_name}'.")
            else:
                print(f"Error: Trader '{trader_name}' already exists under this admin.")
        else:
            print("Invalid choice.")
    except ValueError:
        print("Invalid input.")

def add_new_client():
    print("\n--- Add New Client ---")
    admins = list(SYSTEM_HIERARCHY["admins"].keys())
    if not admins:
        print("No admins available.")
        return

    # Flatten list of (Admin, Trader) tuples
    trader_options = []
    for admin in admins:
        traders = SYSTEM_HIERARCHY["admins"][admin]["traders"]
        for trader in traders:
            trader_options.append((admin, trader))
    
    if not trader_options:
        print("No traders available. Create a trader first.")
        return

    print("Select Trader:")
    for i, (admin, trader) in enumerate(trader_options):
        print(f"{i+1}. {trader} (Admin: {admin})")
    
    try:
        choice = int(input("Choice (Number): ")) - 1
        if 0 <= choice < len(trader_options):
            admin_name, trader_name = trader_options[choice]
            client_name = input("Enter Client Name: ").strip()
            if not client_name:
                print("Name cannot be empty.")
                return
            
            if add_client(admin_name, trader_name, client_name):
                print(f"Success: Client '{client_name}' added to Trader '{trader_name}'.")
            else:
                print(f"Error: Client '{client_name}' already exists under this trader.")
        else:
            print("Invalid choice.")
    except ValueError:
        print("Invalid input.")

def main_menu():
    while True:
        # clear_screen() # Optional: keep history visible
        print_header()
        print("1. List Hierarchy")
        print("2. Add Admin")
        print("3. Add Trader")
        print("4. Add Client")
        print("5. Exit")
        
        choice = input("\nEnter choice (1-5): ").strip()
        
        if choice == '1':
            list_hierarchy()
        elif choice == '2':
            add_new_admin()
        elif choice == '3':
            add_new_trader()
        elif choice == '4':
            add_new_client()
        elif choice == '5':
            print("Exiting...")
            break
        else:
            print("Invalid choice. Please try again.")
        
        input("\nPress Enter to continue...")

if __name__ == "__main__":
    main_menu()
