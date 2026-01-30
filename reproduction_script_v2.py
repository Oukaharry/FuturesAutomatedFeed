
import sys
import os

# Add workspace to path
sys.path.append(os.getcwd())

from config.hierarchy import get_user_by_email
from dashboard.database import find_user_by_identifier

print("Imported successfully.")

identifier = "chris@blueedgefinancial.com"

print(f"Testing DB lookup for: {identifier}")
user_db = find_user_by_identifier(identifier)
print(f"DB Result: {user_db}")

print(f"Testing Hierarchy lookup for: {identifier}")
user_hierarchy = get_user_by_email(identifier)
print(f"Hierarchy Result: {user_hierarchy}")

if not user_db and '@' in identifier:
    print("User not in DB, falling back to hierarchy...")
    if user_hierarchy:
        print("User found in hierarchy!")
    else:
        print("User NOT found in hierarchy either.")
