
import requests
import json

url = "http://localhost:5001/api/client/migrate_sheet"
payload = {
    "email": "riverflow2ocean@gmail.com",
    "sheet_url": "https://docs.google.com/spreadsheets/d/10eGsivGm5GOaH0orB2AAbjpXzDwDkYY1gIZgux9nIjI/edit?usp=sharing"
}

try:
    print(f"Migrating sheet for {payload['email']}...")
    response = requests.post(url, json=payload)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")
