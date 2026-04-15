"""
Extract all emails from the dashboard database (user_credentials table)
and from the hierarchy config file.
"""
import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard', 'dashboard.db')
# Respect config.hierarchy selection for which JSON file to read (restructured vs legacy)
HIERARCHY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'hierarchy.json')
try:
    from config import hierarchy as _hier
    HIERARCHY_PATH = getattr(_hier, 'HIERARCHY_FILE', HIERARCHY_PATH)
except Exception:
    pass

def extract_from_db():
    """Extract emails from user_credentials table."""
    results = {'super_admin': [], 'admin': [], 'trader': [], 'client': []}
    
    if not os.path.exists(DB_PATH):
        print(f"[!] Database not found: {DB_PATH}")
        return results
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT username, email, user_type, is_active, last_login 
        FROM user_credentials 
        ORDER BY user_type, username
    """)
    
    for row in cursor.fetchall():
        user_type = row['user_type']
        if user_type not in results:
            results[user_type] = []
        results[user_type].append({
            'name': row['username'],
            'email': row['email'] or '',
            'active': bool(row['is_active']),
            'last_login': row['last_login'] or 'Never',
        })
    
    conn.close()
    return results

def extract_from_hierarchy():
    """Extract emails from hierarchy.json."""
    results = {'super_admin': [], 'admin': [], 'trader': [], 'client': []}
    
    if not os.path.exists(HIERARCHY_PATH):
        print(f"[!] Hierarchy file not found: {HIERARCHY_PATH}")
        return results
    
    with open(HIERARCHY_PATH, 'r') as f:
        hierarchy = json.load(f)
    
    # Super admin
    sa = hierarchy.get('super_admin', {})
    if sa.get('email'):
        results['super_admin'].append({'name': sa.get('name', 'super_admin'), 'email': sa['email']})
    
    # Admins -> Traders -> Clients
    for admin_name, admin_data in hierarchy.get('admins', {}).items():
        if admin_data.get('email'):
            results['admin'].append({'name': admin_name, 'email': admin_data['email']})
        
        for trader_name, trader_data in admin_data.get('traders', {}).items():
            if trader_data.get('email'):
                results['trader'].append({'name': trader_name, 'email': trader_data['email']})
            
            for client in trader_data.get('clients', []):
                if client.get('email'):
                    results['client'].append({
                        'name': client['name'],
                        'email': client['email'],
                        'category': client.get('category', ''),
                        'trader': trader_name,
                        'admin': admin_name,
                    })
    
    return results

def main():
    print("=" * 70)
    print("  EMAIL EXTRACTION REPORT")
    print("=" * 70)
    
    # --- Database ---
    print("\n📦 DATABASE (user_credentials)")
    print("-" * 50)
    db_data = extract_from_db()
    db_total = 0
    for role in ['super_admin', 'admin', 'trader', 'client']:
        users = db_data.get(role, [])
        if users:
            print(f"\n  [{role.upper()}] ({len(users)})")
            for u in users:
                status = "✅" if u.get('active', True) else "❌"
                email = u['email'] or '(no email)'
                print(f"    {status} {u['name']:20s}  {email}")
                db_total += 1
    print(f"\n  DB Total: {db_total} users")
    
    # --- Hierarchy ---
    print("\n\n📂 HIERARCHY (config/hierarchy.json)")
    print("-" * 50)
    h_data = extract_from_hierarchy()
    h_total = 0
    for role in ['super_admin', 'admin', 'trader', 'client']:
        users = h_data.get(role, [])
        if users:
            print(f"\n  [{role.upper()}] ({len(users)})")
            for u in users:
                extra = ""
                if u.get('trader'):
                    extra = f"  (trader: {u['trader']})"
                if u.get('category'):
                    extra += f"  [{u['category']}]"
                print(f"    {u['name']:20s}  {u['email']}{extra}")
                h_total += 1
    print(f"\n  Hierarchy Total: {h_total} entries")
    
    # --- Combined unique emails ---
    print("\n\n📧 ALL UNIQUE EMAILS")
    print("-" * 50)
    all_emails = set()
    for source in [db_data, h_data]:
        for role_users in source.values():
            for u in role_users:
                if u.get('email'):
                    all_emails.add(u['email'].lower())
    
    for email in sorted(all_emails):
        print(f"  {email}")
    print(f"\n  Total unique emails: {len(all_emails)}")

if __name__ == '__main__':
    main()
