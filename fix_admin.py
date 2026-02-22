import sys
import os
import sqlite3

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dashboard.database import init_database, set_admin_password, verify_admin_password, get_connection

print("=== DIAGNOSIS START ===")

# 1. Initialize DB to ensure tables exist
print("Ensuring database tables exist...")
try:
    init_database()
except Exception as e:
    print(f"CRITICAL ERROR initializing database: {e}")

# 2. Check if user exists
print("\nChecking 'bef_admin' status...")
with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM admin_passwords WHERE username='bef_admin'")
    row = cursor.fetchone()
    
    if row:
        updated_at = "Unknown"
        if row and 'updated_at' in row.keys():
            updated_at = row['updated_at'] if row['updated_at'] else "Never"
            
        print(f"User 'bef_admin' FOUND in database. Last updated: {updated_at}")
    else:
        print("User 'bef_admin' NOT FOUND in database.")

# 3. Test current password
TARGET_PASSWORD = 'BEFAdmin@123'
print(f"\nTesting login with password: '{TARGET_PASSWORD}'")
if verify_admin_password('bef_admin', TARGET_PASSWORD):
    print(f"SUCCESS: The password is currently VALID. You can log in with '{TARGET_PASSWORD}'.")
else:
    print(f"FAILURE: The password '{TARGET_PASSWORD}' is currently INVALID.")
    
    # 4. Force Reset
    print("\nAttempting to FORCE RESET password...")
    try:
        success = set_admin_password('bef_admin', TARGET_PASSWORD)
        if success:
            print("Password reset command EXECUTED successfully.")
            
            # 5. Re-test
            if verify_admin_password('bef_admin', TARGET_PASSWORD):
                print(f"SUCCESS: Verification AFTER reset passed. You can now log in with '{TARGET_PASSWORD}'.")
            else:
                print("CRITICAL FAILURE: Verification failed even after reset. Check database permissions or file paths!")
        else:
            print("Failed to execute password reset.")
    except Exception as e:
        print(f"Exception during reset: {e}")

print("=== DIAGNOSIS END ===")
