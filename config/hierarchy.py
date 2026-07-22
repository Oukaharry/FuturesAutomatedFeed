import json
import os

# Load hierarchy from JSON file
# Prefer the restructured hierarchy if it exists so the app can switch immediately
BASE_DIR = os.path.dirname(__file__)
RESTRUCTURED_FILE = os.path.join(BASE_DIR, "hierarchy_restructured.json")
LEGACY_FILE = os.path.join(BASE_DIR, "hierarchy.json")
# Use the restructured file when present, otherwise fall back to the legacy file
HIERARCHY_FILE = RESTRUCTURED_FILE if os.path.exists(RESTRUCTURED_FILE) else LEGACY_FILE

def load_hierarchy():
    if os.path.exists(HIERARCHY_FILE):
        with open(HIERARCHY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Compatibility: if the file is the "restructured" shape (admins -> clients + top-level traders)
        # convert it in-memory to the legacy nested shape {admins: {admin: {traders: {trader: {clients: []}}}}}
        try:
            if isinstance(data, dict) and 'admins' in data:
                sample_admin = next(iter(data['admins'].values())) if data['admins'] else None
                # Restructured format: admin entries contain 'clients' (list) and there is a top-level 'traders' registry
                if sample_admin is not None and 'clients' in sample_admin and 'traders' not in sample_admin:
                    trader_registry = data.get('traders', {}) if isinstance(data.get('traders', {}), dict) else {}
                    new_admins = {}
                    for admin_name, admin_data in data.get('admins', {}).items():
                        traders_map = {}
                        for client in admin_data.get('clients', []):
                            assigned = (client.get('assigned_trader') or '').strip()
                            # Use assigned trader as key; if missing, group under empty-string key
                            key = assigned
                            if key not in traders_map:
                                tr_email = trader_registry.get(key, {}).get('email', '') if key else ''
                                tr_active = trader_registry.get(key, {}).get('active_status', 'active') if key else 'active'
                                traders_map[key] = {'email': tr_email, 'clients': [], 'active_status': tr_active}
                            # Keep assigned_trader on the client object for frontend/UI use
                            client_copy = dict(client)
                            traders_map[key]['clients'].append(client_copy)
                        # Traders with no clients yet (assigned_traders on disk)
                        for trader_name in admin_data.get('assigned_traders', []):
                            key = (trader_name or '').strip()
                            if key and key not in traders_map:
                                tr_email = trader_registry.get(key, {}).get('email', '')
                                tr_active = trader_registry.get(key, {}).get('active_status', 'active')
                                traders_map[key] = {'email': tr_email, 'clients': [], 'active_status': tr_active}
                        # Preserve all original admin fields (email, slack_user_id, etc.)
                        preserved = {
                            k: v for k, v in admin_data.items()
                            if k not in ('clients', 'assigned_traders')
                        }
                        preserved['traders'] = traders_map
                        new_admins[admin_name] = preserved
                    data['admins'] = new_admins
        except Exception:
            # If conversion fails for any reason, fall back to raw data
            pass

        return data

    return {"admins": {}}

SYSTEM_HIERARCHY = load_hierarchy()

def reload_hierarchy():
    """Reloads the hierarchy from disk to ensure freshness."""
    global SYSTEM_HIERARCHY
    new_data = load_hierarchy()
    SYSTEM_HIERARCHY.clear()
    SYSTEM_HIERARCHY.update(new_data)
    return SYSTEM_HIERARCHY

def _to_flat_format(hierarchy_data):
    """Convert in-memory nested format back to flat format for disk persistence."""
    import copy
    out = copy.deepcopy(hierarchy_data)
    trader_registry = out.get('traders')
    if not isinstance(trader_registry, dict):
        trader_registry = {}
    out['traders'] = trader_registry

    for admin_name, admin_data in out.get('admins', {}).items():
        if 'traders' in admin_data and 'clients' not in admin_data:
            flat_clients = []
            assigned_traders = []
            for trader_name, trader_data in admin_data['traders'].items():
                tname = (trader_name or '').strip()
                if tname:
                    assigned_traders.append(tname)
                    em = (trader_data or {}).get('email', '') or ''
                    entry = trader_registry.setdefault(tname, {})
                    if em:
                        entry['email'] = em
                    elif 'email' not in entry:
                        entry['email'] = ''
                    active = (trader_data or {}).get('active_status')
                    if active:
                        entry['active_status'] = active
                for client in (trader_data or {}).get('clients', []):
                    c = dict(client)
                    # Normalize client name to prevent invisible mismatch bugs (trailing spaces/NBSP).
                    nm = str(c.get('name', '') or '')
                    nm = nm.replace('\u00A0', ' ').replace('\u200B', '').replace('\u200C', '').replace('\u200D', '')
                    nm = ' '.join(nm.split()).strip()
                    c['name'] = nm
                    c['assigned_trader'] = trader_name
                    flat_clients.append(c)
            preserved = {
                k: v for k, v in admin_data.items()
                if k not in ('traders', 'assigned_traders')
            }
            preserved['assigned_traders'] = sorted(set(assigned_traders), key=lambda s: s.lower())
            preserved['clients'] = flat_clients
            out['admins'][admin_name] = preserved
    return out


def save_hierarchy(hierarchy_data):
    # Ensure directory exists
    os.makedirs(os.path.dirname(HIERARCHY_FILE), exist_ok=True)
    # Always persist in flat format so the JSON structure stays consistent
    flat = _to_flat_format(hierarchy_data)
    with open(HIERARCHY_FILE, "w") as f:
        json.dump(flat, f, indent=4)
        
    # Also update in-memory reference immediately
    if hierarchy_data is not SYSTEM_HIERARCHY:
        SYSTEM_HIERARCHY.clear()
        SYSTEM_HIERARCHY.update(hierarchy_data)

    try:
        from dashboard.shared_cache import invalidate_prefix
        invalidate_prefix('hierarchy:')
    except Exception:
        pass

def reassign_client_trader(client_name, admin_name, new_trader):
    """
    Reassign a client to a trader under target admin (may differ from current admin).
    Auto-creates the new trader lane under the target admin if it doesn't exist,
    pulling the email from the top-level traders registry.
    Returns True on success, False if the client or target admin cannot be found.
    """
    reload_hierarchy()

    admins = SYSTEM_HIERARCHY.get('admins', {})
    if admin_name not in admins:
        return False

    # Find current trader lane for this client — search specified admin first,
    # then fall back to all admins (client may have been moved across admins)
    found_admin = None
    old_trader = None
    for search_admin in ([admin_name] + [a for a in admins if a != admin_name]):
        traders = admins[search_admin].get('traders', {})
        for t_name, t_data in traders.items():
            for client in t_data.get('clients', []):
                if client.get('name') == client_name:
                    found_admin = search_admin
                    old_trader = t_name
                    break
            if old_trader:
                break
        if old_trader:
            break

    if old_trader is None or found_admin is None:
        return False

    if old_trader == new_trader and found_admin == admin_name:
        return True  # nothing to do

    source_traders = admins[found_admin].get('traders', {})
    target_traders = admins[admin_name].get('traders', {})

    # Auto-create the new trader lane if missing under the target admin
    if new_trader not in target_traders:
        trader_email = SYSTEM_HIERARCHY.get('traders', {}).get(new_trader, {}).get('email', '')
        target_traders[new_trader] = {'email': trader_email, 'clients': []}

    # Remove client from old location
    old_clients = source_traders[old_trader]['clients']
    client_obj = None
    for i, c in enumerate(old_clients):
        if c.get('name') == client_name:
            client_obj = old_clients.pop(i)
            break

    if client_obj is None:
        return False

    client_obj['assigned_trader'] = new_trader
    target_traders[new_trader]['clients'].append(client_obj)

    # Clean up empty trader lane
    if not source_traders[old_trader]['clients']:
        del source_traders[old_trader]

    save_hierarchy(SYSTEM_HIERARCHY)
    return True


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

def update_admin_details(admin_name, email, slack_user_id=None):
    reload_hierarchy()
    if admin_name in SYSTEM_HIERARCHY["admins"]:
        SYSTEM_HIERARCHY["admins"][admin_name]["email"] = email
        if slack_user_id is not None:  # allow clearing by passing ''
            SYSTEM_HIERARCHY["admins"][admin_name]["slack_user_id"] = slack_user_id.strip()
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


def find_trader_admin(trader_name):
    """Return admin name if *trader_name* is assigned under any admin (including empty lanes)."""
    reload_hierarchy()
    name = (trader_name or '').strip()
    if not name:
        return None
    for admin_name, admin_data in SYSTEM_HIERARCHY.get('admins', {}).items():
        if name in admin_data.get('traders', {}):
            return admin_name
    return None


def set_trader_active_status(admin_name, trader_name, active_status):
    """Mark a trader lane active/inactive without removing clients."""
    reload_hierarchy()
    admin_name = (admin_name or '').strip()
    trader_name = (trader_name or '').strip()
    status = 'inactive' if str(active_status or '').lower() == 'inactive' else 'active'
    admin = SYSTEM_HIERARCHY.get('admins', {}).get(admin_name)
    if not admin:
        return False
    traders = admin.get('traders', {})
    if trader_name not in traders:
        return False
    traders[trader_name]['active_status'] = status
    registry = SYSTEM_HIERARCHY.setdefault('traders', {})
    if not isinstance(registry, dict):
        registry = {}
        SYSTEM_HIERARCHY['traders'] = registry
    registry.setdefault(trader_name, {})['active_status'] = status
    save_hierarchy(SYSTEM_HIERARCHY)
    return True


def trader_is_active(trader_name):
    """False when trader is deactivated in hierarchy and/or user_credentials."""
    name = (trader_name or '').strip()
    if not name:
        return False
    reload_hierarchy()
    registry = SYSTEM_HIERARCHY.get('traders', {}) or {}
    found_lane = False
    for admin_data in SYSTEM_HIERARCHY.get('admins', {}).values():
        td = (admin_data.get('traders') or {}).get(name)
        if td is None:
            continue
        found_lane = True
        lane_status = (td.get('active_status') or registry.get(name, {}).get('active_status') or 'active')
        if str(lane_status).lower() == 'inactive':
            return False
        break
    if not found_lane:
        reg_status = registry.get(name, {}).get('active_status')
        if reg_status and str(reg_status).lower() == 'inactive':
            return False
    try:
        from dashboard.database import get_user
        row = get_user(name, 'trader')
        if row is not None and not row.get('is_active', 1):
            return False
    except Exception:
        pass
    return True


def add_trader(admin_name, trader_name, email=""):
    reload_hierarchy()
    if admin_name in SYSTEM_HIERARCHY["admins"]:
        traders = SYSTEM_HIERARCHY["admins"][admin_name].setdefault("traders", {})
        if trader_name not in traders:
            traders[trader_name] = {
                "email": email,
                "clients": [],
                "active_status": "active",
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
                active_status = (
                    trader_data.get('active_status')
                    or SYSTEM_HIERARCHY.get('traders', {}).get(trader_name, {}).get('active_status')
                    or 'active'
                )
                is_active = 0 if str(active_status).lower() == 'inactive' else 1
                return {
                    "username": trader_name,
                    "user_type": "trader",
                    "email": email,
                    "parent_admin": admin_name,
                    "parent_trader": None,
                    "must_change_password": 0,
                    "is_active": is_active
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

