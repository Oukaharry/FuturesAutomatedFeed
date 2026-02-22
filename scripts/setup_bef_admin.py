import os
import sys

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.database import set_admin_password, init_database

print("Setting up bef_admin...")
# Ensure table exists
init_database()

if set_admin_password('bef_admin', 'BEFAdmin@123'):
    print("Successfully created 'bef_admin' user.")
else:
    print("Failed to create 'bef_admin' user.")
