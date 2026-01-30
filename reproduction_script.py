
import sys
import os

# Add workspace to path
sys.path.append(os.getcwd())

from config.hierarchy import get_user_by_email, SYSTEM_HIERARCHY

print("Loading SYSTEM_HIERARCHY...")
# print(SYSTEM_HIERARCHY)

email_to_test = "chris@blueedgefinancial.com"
print(f"Testing lookup for: {email_to_test}")

user = get_user_by_email(email_to_test)
print(f"Result: {user}")

if user:
    print("SUCCESS: User found.")
else:
    print("FAILURE: User not found.")
