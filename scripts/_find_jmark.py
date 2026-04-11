import requests

r = requests.get('https://www.tradeopss.com/api/kyc/list')
print(f"Status: {r.status_code}")
if r.status_code != 200:
    print(r.text[:500])
else:
    clients = r.json()
    print(f"Total clients: {len(clients)}")
    for c in clients:
        name = c.get('name', '')
        email = c.get('email', '')
        if 'jmark' in name.lower() or 'jmark' in email.lower():
            print(f"Email: {email}, Name: {name}")
    # Also try partial match
    if not any('jmark' in c.get('name','').lower() or 'jmark' in c.get('email','').lower() for c in clients):
        # Show all names for manual lookup
        for c in clients:
            name = c.get('name', '')
            if name and name[0].upper() == 'J':
                print(f"  J-name: {name} -> {c.get('email','')}")
