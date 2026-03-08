"""Fetch Nikki's Stats tab (gid=839895136) and show raw content."""
import sys, requests
sys.path.insert(0, '.')

KEY = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'
GID = '839895136'

csv_url = f'https://docs.google.com/spreadsheets/d/{KEY}/export?format=csv&gid={GID}'
r = requests.get(csv_url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
print(f'Status: {r.status_code}')
if r.ok:
    for line in r.text.strip().splitlines()[:60]:
        print(line)
