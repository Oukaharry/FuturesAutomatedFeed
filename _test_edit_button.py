"""Quick test to check if edit button works correctly"""
import sys, os
sys.path.insert(0, '.')
os.environ['FLASK_ENV'] = 'development'

from dashboard.app import app
print('Flask app imported successfully')

with app.test_client() as client:
    resp = client.get('/super-admin')
    print(f'super-admin status: {resp.status_code}')
    if resp.status_code == 200:
        html = resp.data.decode('utf-8')
        checks = [
            ('editUserModal div', 'id="editUserModal"' in html),
            ('openEditUserModal function', 'function openEditUserModal' in html),
            ('closeEditUserModal function', 'function closeEditUserModal' in html),
            ('submitEditUser function', 'async function submitEditUser' in html),
            ('editUserOriginalName hidden', 'editUserOriginalName' in html),
        ]
        for name, result in checks:
            status = "OK" if result else "MISSING"
            print(f'  {name}: {status}')
    
    # Test the update endpoints exist
    for endpoint in ['/api/update_admin', '/api/update_trader', '/api/update_client']:
        resp = client.post(endpoint, json={'name': 'test', 'email': 'test@test.com'})
        print(f'{endpoint}: status={resp.status_code}')
        if resp.status_code != 200:
            print(f'  Response: {resp.data.decode("utf-8")[:200]}')
