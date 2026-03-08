import sys
sys.path.insert(0, '.')
sys.path.insert(0, './dashboard')
from dashboard.database import get_all_clients

all_clients = get_all_clients()
for cid, data in all_clients.items():
    if not data:
        continue
    identity = data.get('identity', {}) or {}
    url = identity.get('sheet_url', '')
    print(f"Client: {cid} | Sheet: {url[:80]}")
