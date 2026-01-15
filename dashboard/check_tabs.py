"""Check for multiple tabs in the Google Sheet"""
import requests

# The default export gets the first sheet. Let's try to get sheet list
sheet_id = '1rXdWErZD5C0pTWcAu8jCQSFBv2Mm1O88cPoJHFaUH2E'

# Try different sheet IDs (gid parameter)
# gid=0 is usually first sheet, gid=123456 etc for others
gids_to_try = [0, 1, 2]

for gid in gids_to_try:
    url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}'
    response = requests.get(url)
    
    if response.status_code == 200:
        lines = response.text.split('\n')
        first_lines = lines[:5]
        print(f"\n=== GID {gid} ===")
        for line in first_lines:
            print(f"  {line[:100]}...")
    else:
        print(f"\nGID {gid}: Status {response.status_code}")
