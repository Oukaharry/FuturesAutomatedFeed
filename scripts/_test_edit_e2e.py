"""End-to-end test for edit button functionality"""
import sys, os, re
sys.path.insert(0, '.')
os.environ['FLASK_ENV'] = 'development'

from dashboard.app import app

with app.test_client() as client:
    # Login first
    resp = client.post('/api/login', json={
        'username': 'super_admin',
        'password': 'admin123'
    })
    login_result = resp.get_json()
    print(f'Login: {login_result}')
    
    if login_result and login_result.get('status') == 'success':
        resp = client.get('/super_admin')
        print(f'super_admin page: {resp.status_code}')
        
        if resp.status_code == 200:
            html = resp.data.decode('utf-8')
            
            # Check critical functions
            funcs = re.findall(r'(?:async\s+)?function\s+(\w+)', html)
            print(f'JS functions defined: {len(funcs)}')
            
            critical = ['openEditUserModal', 'closeEditUserModal', 'submitEditUser', 'deleteUser', 'renderTree', 'loadData']
            for fn in critical:
                found = fn in funcs
                print(f'  {fn}: {"FOUND" if found else "MISSING"}')
            
            # Check modal HTML
            print(f'editUserModal HTML: {"FOUND" if "editUserModal" in html else "MISSING"}')
            
            # Check the hierarchy endpoint
            resp2 = client.get('/api/hierarchy')
            print(f'Hierarchy API: {resp2.status_code}')
            if resp2.status_code == 200:
                hdata = resp2.get_json()
                print(f'  Admins: {list(hdata.get("admins", {}).keys())[:5]}')
    else:
        print('Login failed - trying to check the page template directly')
        from flask import render_template_string
        with app.app_context():
            html = open('dashboard/templates/super_admin.html', 'r').read()
            funcs = re.findall(r'(?:async\s+)?function\s+(\w+)', html)
            print(f'JS functions in template: {len(funcs)}')
            critical = ['openEditUserModal', 'closeEditUserModal', 'submitEditUser']
            for fn in critical:
                print(f'  {fn}: {"FOUND" if fn in funcs else "MISSING"}')
