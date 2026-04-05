"""Quick smoke test: exercise core database functions against PostgreSQL."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.database import (
    check_and_repair_database,
    create_user, verify_user_password, list_users,
    save_client_data, get_client_data, get_all_clients,
    log_action, get_audit_log,
    set_setting, get_setting,
    create_session, validate_session, delete_session,
    generate_api_key, validate_api_key,
)

passed = 0
failed = 0

def test(name, condition):
    global passed, failed
    if condition:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}")
        failed += 1

# 1
ok, msg = check_and_repair_database()
test("Connectivity", ok)

# 2
result = create_user("test_admin", "TestP@ss123", "admin", email="test@test.com")
test("Create user", result)

# 3
user = verify_user_password("test_admin", "admin", "TestP@ss123")
test("Verify user password", user is not None and user["username"] == "test_admin")

# 4
users = list_users("admin")
test("List users", len(users) >= 1)

# 5
saved = save_client_data("test_client_001", {
    "deals": [{"id": 1, "symbol": "NQ"}],
    "positions": [],
    "account": {"balance": 100000},
    "evaluations": [],
    "statistics": {},
    "identity": {"name": "Test Client"},
})
test("Save client data", saved)

# 6
data = get_client_data("test_client_001")
test("Get client data", data is not None and data["account"]["balance"] == 100000)

# 7
all_c = get_all_clients()
test("Get all clients", len(all_c) >= 1)

# 8
log_action("TEST", "admin", "test_admin", "127.0.0.1", "Phase 3 test")
logs = get_audit_log(limit=5)
test("Audit log", len(logs) >= 1)

# 9
set_setting("test_key", "test_value", "test")
val = get_setting("test_key")
test("System settings", val == "test_value")

# 10
token = create_session("admin", "test_admin", "127.0.0.1")
session = validate_session(token)
test("Session create/validate", session is not None)
delete_session(token)
test("Session delete", validate_session(token) is None)

# 11
key = generate_api_key("admin1", "trader1")
info = validate_api_key(key)
test("API key generate/validate", info is not None and info["scope"] == "full")

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
if failed == 0:
    print("ALL TESTS PASSED!")
else:
    print("SOME TESTS FAILED")
    sys.exit(1)
