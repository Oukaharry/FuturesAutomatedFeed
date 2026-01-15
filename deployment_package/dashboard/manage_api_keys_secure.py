#!/usr/bin/env python3
"""
Secure API Key Management Tool
Manages API keys stored with SHA-256 hashing in SQLite database
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.database import (
    generate_api_key, list_api_keys, revoke_api_key, delete_api_key,
    verify_admin_password, set_admin_password, get_audit_log
)

def print_header():
    print("\n" + "=" * 60)
    print("   SECURE API KEY MANAGEMENT")
    print("   (Keys are hashed - never stored in plain text)")
    print("=" * 60)

def authenticate():
    """Require admin password to access management functions."""
    print("\nAdmin authentication required.")
    password = input("Enter admin password: ").strip()
    
    if not verify_admin_password('super_admin', password):
        print("❌ Invalid password!")
        return False
    
    print("✓ Authentication successful\n")
    return True

def list_keys():
    """Display all API keys (showing prefix only)."""
    keys = list_api_keys()
    
    print("\n" + "=" * 60)
    print("API KEYS (Prefix Only - Full keys are never stored)")
    print("=" * 60)
    
    if not keys:
        print("No API keys found.")
        return
    
    print(f"{'Prefix':<15} {'Trader':<15} {'Admin':<15} {'Active':<8} {'Last Used'}")
    print("-" * 75)
    
    for key in keys:
        active = "✓" if key['is_active'] else "✗"
        last_used = key['last_used'] or "Never"
        if len(last_used) > 19:
            last_used = last_used[:19]
        print(f"{key['key_prefix']:<15} {key['trader']:<15} {key['admin']:<15} {active:<8} {last_used}")
    
    print("-" * 75)
    print(f"Total: {len(keys)} keys")

def generate_new_key():
    """Generate a new API key for a trader."""
    print("\n--- Generate New API Key ---")
    
    trader = input("Trader name: ").strip()
    if not trader:
        print("❌ Trader name required!")
        return
    
    admin = input("Admin name (default: same as trader): ").strip() or trader
    client = input("Client name (optional): ").strip()
    
    print("\nGenerating API key...")
    api_key = generate_api_key(admin, trader, client)
    
    if api_key:
        print("\n" + "=" * 60)
        print("✓ API KEY GENERATED SUCCESSFULLY")
        print("=" * 60)
        print(f"\nTrader: {trader}")
        print(f"Admin: {admin}")
        if client:
            print(f"Client: {client}")
        print(f"\n🔑 API KEY: {api_key}")
        print("\n⚠️  IMPORTANT: Save this key now!")
        print("   It will NEVER be shown again.")
        print("   The key is stored as a hash and cannot be recovered.")
        print("=" * 60)
    else:
        print("❌ Failed to generate API key!")

def revoke_key():
    """Revoke an existing API key."""
    print("\n--- Revoke API Key ---")
    
    # Show current keys first
    list_keys()
    
    key_prefix = input("\nEnter key prefix to revoke (e.g., tk_abc123...): ").strip()
    if not key_prefix:
        print("❌ Key prefix required!")
        return
    
    confirm = input(f"Are you sure you want to revoke key '{key_prefix}'? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("Cancelled.")
        return
    
    if revoke_api_key(key_prefix):
        print(f"✓ API key '{key_prefix}' has been revoked!")
    else:
        print(f"❌ API key '{key_prefix}' not found!")

def permanently_delete_key():
    """Permanently delete an API key."""
    print("\n--- Permanently Delete API Key ---")
    
    # Show current keys first
    list_keys()
    
    key_prefix = input("\nEnter key prefix to DELETE (e.g., tk_abc123...): ").strip()
    if not key_prefix:
        print("❌ Key prefix required!")
        return
    
    print("\n⚠️  WARNING: This action cannot be undone!")
    confirm = input(f"Type 'DELETE' to permanently remove key '{key_prefix}': ").strip()
    if confirm != 'DELETE':
        print("Cancelled.")
        return
    
    if delete_api_key(key_prefix):
        print(f"✓ API key '{key_prefix}' has been permanently deleted!")
    else:
        print(f"❌ API key '{key_prefix}' not found!")

def view_audit_log():
    """View recent audit log entries."""
    print("\n--- Audit Log ---")
    
    limit = input("Number of entries to show (default: 20): ").strip()
    limit = int(limit) if limit.isdigit() else 20
    
    action_filter = input("Filter by action (leave empty for all): ").strip() or None
    
    logs = get_audit_log(limit, action_filter)
    
    print("\n" + "=" * 80)
    print("AUDIT LOG")
    print("=" * 80)
    
    if not logs:
        print("No log entries found.")
        return
    
    for log in logs:
        timestamp = log['timestamp'][:19] if len(log['timestamp']) > 19 else log['timestamp']
        success = "✓" if log['success'] else "✗"
        print(f"[{timestamp}] {success} {log['action']:<25} | {log['user_type']}: {log['user_identifier']}")
        if log['details']:
            print(f"    └── {log['details']}")
    
    print("-" * 80)
    print(f"Showing {len(logs)} entries")

def change_admin_password():
    """Change the admin password."""
    print("\n--- Change Admin Password ---")
    
    current = input("Enter current password: ").strip()
    if not verify_admin_password('super_admin', current):
        print("❌ Invalid current password!")
        return
    
    new_password = input("Enter new password (min 8 characters): ").strip()
    if len(new_password) < 8:
        print("❌ Password must be at least 8 characters!")
        return
    
    confirm = input("Confirm new password: ").strip()
    if new_password != confirm:
        print("❌ Passwords don't match!")
        return
    
    if set_admin_password('super_admin', new_password):
        print("✓ Password changed successfully!")
    else:
        print("❌ Failed to change password!")

def main():
    print_header()
    
    # Authenticate first
    if not authenticate():
        return
    
    while True:
        print("\n" + "-" * 40)
        print("OPTIONS:")
        print("1. Generate new API key")
        print("2. List all API keys")
        print("3. Revoke API key")
        print("4. Permanently delete API key")
        print("5. View audit log")
        print("6. Change admin password")
        print("7. Exit")
        print("-" * 40)
        
        choice = input("\nSelect option (1-7): ").strip()
        
        if choice == '1':
            generate_new_key()
        elif choice == '2':
            list_keys()
        elif choice == '3':
            revoke_key()
        elif choice == '4':
            permanently_delete_key()
        elif choice == '5':
            view_audit_log()
        elif choice == '6':
            change_admin_password()
        elif choice == '7':
            print("\nGoodbye!")
            break
        else:
            print("Invalid option. Please select 1-7.")

if __name__ == '__main__':
    main()
