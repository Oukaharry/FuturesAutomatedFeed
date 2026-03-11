import json
import os

# Load hierarchy from JSON file
HIERARCHY_FILE = os.path.join(os.path.dirname(__file__), "hierarchy.json")

def load_hierarchy():
    if os.path.exists(HIERARCHY_FILE):
        with open(HIERARCHY_FILE, "r") as f:
            return json.load(f)
    return {"admins": {}}

SYSTEM_HIERARCHY = load_hierarchy()

def reload_hierarchy():
    """Reloads the hierarchy from disk to ensure freshness."""
    global SYSTEM_HIERARCHY
    new_data = load_hierarchy()
    SYSTEM_HIERARCHY.clear()
    SYSTEM_HIERARCHY.update(new_data)
    return SYSTEM_HIERARCHY

def save_hierarchy(hierarchy_data):
    # Ensure directory exists
    os.makedirs(os.path.dirname(HIERARCHY_FILE), exist_ok=True)
    with open(HIERARCHY_FILE, "w") as f:
        json.dump(hierarchy_data, f, indent=4)
        
    # Also update in-memory reference immediately
    if hierarchy_data is not SYSTEM_HIERARCHY:
        SYSTEM_HIERARCHY.clear()
        SYSTEM_HIERARCHY.update(hierarchy_data)

def add_admin(admin_name, email=""):
    reload_hierarchy() # Ensure we have latest data
    if admin_name not in SYSTEM_HIERARCHY["admins"]:
        SYSTEM_HIERARCHY["admins"][admin_name] = {
            "email": email,
            "traders": {}
        }
        save_hierarchy(SYSTEM_HIERARCHY)
        return True
    return False

def update_admin_details(admin_name, email):
    reload_hierarchy()
    if admin_name in SYSTEM_HIERARCHY["admins"]:
        SYSTEM_HIERARCHY["admins"][admin_name]["email"] = email
        save_hierarchy(SYSTEM_HIERARCHY)
        return True
    return False

def update_trader_details(admin_name, trader_name, email):
    reload_hierarchy()
    if admin_name in SYSTEM_HIERARCHY["admins"]:
        traders = SYSTEM_HIERARCHY["admins"][admin_name]["traders"]
        if trader_name in traders:
            traders[trader_name]["email"] = email
            save_hierarchy(SYSTEM_HIERARCHY)
            return True
    return False

def update_client_details(admin_name, trader_name, client_name, email):
    reload_hierarchy()
    if admin_name in SYSTEM_HIERARCHY["admins"]:
        traders = SYSTEM_HIERARCHY["admins"][admin_name]["traders"]
        if trader_name in traders:
            clients = traders[trader_name]["clients"]
            for client in clients:
                if client["name"] == client_name:
                    client["email"] = email
                    save_hierarchy(SYSTEM_HIERARCHY)
                    return True
    return False

def update_client_category(admin_name, trader_name, client_name, category):
    reload_hierarchy()
    if admin_name in SYSTEM_HIERARCHY["admins"]:
        traders = SYSTEM_HIERARCHY["admins"][admin_name]["traders"]
        if trader_name in traders:
            clients = traders[trader_name]["clients"]
            for client in clients:
                if client["name"] == client_name:
                    client["category"] = category
                    save_hierarchy(SYSTEM_HIERARCHY)
                    return True
    return False


def add_trader(admin_name, trader_name, email=""):
    if admin_name in SYSTEM_HIERARCHY["admins"]:
        if trader_name not in SYSTEM_HIERARCHY["admins"][admin_name]["traders"]:
            SYSTEM_HIERARCHY["admins"][admin_name]["traders"][trader_name] = {
                "email": email,
                "clients": []
            }
            save_hierarchy(SYSTEM_HIERARCHY)
            return True
    return False

def add_client(admin_name, trader_name, client_name, email="", category=""):
    if admin_name in SYSTEM_HIERARCHY["admins"]:
        traders = SYSTEM_HIERARCHY["admins"][admin_name]["traders"]
        if trader_name in traders:
            # Check if client exists
            existing_clients = [c["name"] for c in traders[trader_name]["clients"]]
            if client_name not in existing_clients:
                traders[trader_name]["clients"].append({
                    "name": client_name,
                    "email": email,
                    "category": category
                })
                save_hierarchy(SYSTEM_HIERARCHY)
                return True
    return False

def remove_admin(admin_name):
    if admin_name in SYSTEM_HIERARCHY["admins"]:
        del SYSTEM_HIERARCHY["admins"][admin_name]
        save_hierarchy(SYSTEM_HIERARCHY)
        return True
    return False

def remove_trader(admin_name, trader_name):
    if admin_name in SYSTEM_HIERARCHY["admins"]:
        traders = SYSTEM_HIERARCHY["admins"][admin_name]["traders"]
        if trader_name in traders:
            del traders[trader_name]
            save_hierarchy(SYSTEM_HIERARCHY)
            return True
    return False

def remove_client(admin_name, trader_name, client_name):
    if admin_name in SYSTEM_HIERARCHY["admins"]:
        traders = SYSTEM_HIERARCHY["admins"][admin_name]["traders"]
        if trader_name in traders:
            clients = traders[trader_name]["clients"]
            for i, client in enumerate(clients):
                if client["name"] == client_name:
                    del clients[i]
                    save_hierarchy(SYSTEM_HIERARCHY)
                    return True
    return False

def rename_admin(old_name, new_name, new_email=None):
    """Rename an admin. Preserves all traders/clients underneath."""
    reload_hierarchy()
    if old_name not in SYSTEM_HIERARCHY["admins"]:
        return False
    if new_name != old_name and new_name in SYSTEM_HIERARCHY["admins"]:
        return False  # new name already taken
    admin_data = SYSTEM_HIERARCHY["admins"].pop(old_name)
    if new_email is not None:
        admin_data["email"] = new_email
    SYSTEM_HIERARCHY["admins"][new_name] = admin_data
    save_hierarchy(SYSTEM_HIERARCHY)
    return True

def rename_trader(admin_name, old_name, new_name, new_email=None):
    """Rename a trader under a given admin."""
    reload_hierarchy()
    if admin_name not in SYSTEM_HIERARCHY["admins"]:
        return False
    traders = SYSTEM_HIERARCHY["admins"][admin_name]["traders"]
    if old_name not in traders:
        return False
    if new_name != old_name and new_name in traders:
        return False  # new name already taken under this admin
    trader_data = traders.pop(old_name)
    if new_email is not None:
        trader_data["email"] = new_email
    traders[new_name] = trader_data
    save_hierarchy(SYSTEM_HIERARCHY)
    return True

def rename_client(admin_name, trader_name, old_name, new_name, new_email=None, new_category=None):
    """Rename a client under a given admin/trader."""
    reload_hierarchy()
    if admin_name not in SYSTEM_HIERARCHY["admins"]:
        return False
    traders = SYSTEM_HIERARCHY["admins"][admin_name]["traders"]
    if trader_name not in traders:
        return False
    clients = traders[trader_name]["clients"]
    for client in clients:
        if client["name"] == old_name:
            client["name"] = new_name
            if new_email is not None:
                client["email"] = new_email
            if new_category is not None:
                client["category"] = new_category
            save_hierarchy(SYSTEM_HIERARCHY)
            return True
    return False

def move_client(client_name, old_admin, old_trader, new_admin, new_trader):
    # Verify existence of old location
    if old_admin not in SYSTEM_HIERARCHY["admins"]: return False
    if old_trader not in SYSTEM_HIERARCHY["admins"][old_admin]["traders"]: return False
    
    # Verify existence of new location
    if new_admin not in SYSTEM_HIERARCHY["admins"]: return False
    if new_trader not in SYSTEM_HIERARCHY["admins"][new_admin]["traders"]: return False
    
    # Find client
    old_clients = SYSTEM_HIERARCHY["admins"][old_admin]["traders"][old_trader]["clients"]
    client_data = None
    client_index = -1
    
    for i, c in enumerate(old_clients):
        if c["name"] == client_name:
            client_data = c
            client_index = i
            break
            
    if client_data is None: return False
    
    # Check if client already exists in new location (prevent duplicates)
    new_clients = SYSTEM_HIERARCHY["admins"][new_admin]["traders"][new_trader]["clients"]
    if any(c["name"] == client_name for c in new_clients):
        return False # Already exists there
        
    # Move
    del old_clients[client_index]
    new_clients.append(client_data)
    save_hierarchy(SYSTEM_HIERARCHY)
    return True

def move_trader(trader_name, old_admin, new_admin):
    # Verify existence
    if old_admin not in SYSTEM_HIERARCHY["admins"]: return False
    if new_admin not in SYSTEM_HIERARCHY["admins"]: return False
    
    old_traders = SYSTEM_HIERARCHY["admins"][old_admin]["traders"]
    if trader_name not in old_traders: return False
    
    new_traders = SYSTEM_HIERARCHY["admins"][new_admin]["traders"]
    if trader_name in new_traders: return False # Already exists
    
    # Move
    trader_data = old_traders[trader_name]
    del old_traders[trader_name]
    new_traders[trader_name] = trader_data
    save_hierarchy(SYSTEM_HIERARCHY)
    return True

def get_client_profile(client_name):
    """Finds the admin and trader for a given client name."""
    for admin, admin_data in SYSTEM_HIERARCHY["admins"].items():
        for trader, trader_data in admin_data["traders"].items():
            for client in trader_data["clients"]:
                if client["name"] == client_name:
                    return {"admin": admin, "trader": trader, "client": client_name, "email": client.get("email", "")}
    return None

def get_client_by_email(email):
    """Finds the client profile by email."""
    if not email: return None
    email = email.lower().strip()
    for admin, admin_data in SYSTEM_HIERARCHY["admins"].items():
        for trader, trader_data in admin_data["traders"].items():
            for client in trader_data["clients"]:
                client_email = client.get("email", "").lower().strip()
                if client_email == email:
                    return {"admin": admin, "trader": trader, "client": client["name"], "email": client.get("email", "")}
    return None

def get_all_clients():
    """Returns a list of all client names."""
    clients_list = []
    for admin_data in SYSTEM_HIERARCHY["admins"].values():
        for trader_data in admin_data["traders"].values():
            for client in trader_data["clients"]:
                clients_list.append(client["name"])
    return clients_list

def get_user_by_email(email):
    """
    Find specific user (Admin, Trader, or Client) by email.
    Returns: {'username': name, 'user_type': type, 'email': email, ...defaults}
    """
    if not email: return None
    email = email.lower().strip()
    
    for admin_name, admin_data in SYSTEM_HIERARCHY["admins"].items():
        # Check Admin
        if admin_data.get("email", "").lower().strip() == email:
            return {
                "username": admin_name,
                "user_type": "admin", 
                "email": email,
                "parent_admin": None,
                "parent_trader": None,
                "must_change_password": 0,
                "is_active": 1
            }
            
        for trader_name, trader_data in admin_data["traders"].items():
            # Check Trader
            if trader_data.get("email", "").lower().strip() == email:
                return {
                    "username": trader_name,
                    "user_type": "trader",
                    "email": email,
                    "parent_admin": admin_name,
                    "parent_trader": None,
                    "must_change_password": 0,
                    "is_active": 1
                }
                
            # Check Clients
            for client in trader_data["clients"]:
                client_email = client.get("email", "").lower().strip()
                if client_email == email:
                    return {
                        "username": client["name"],
                        "user_type": "client",
                        "email": email,
                        "parent_admin": admin_name,
                        "parent_trader": trader_name,
                        "must_change_password": 0,
                        "is_active": 1
                    }
    return None

