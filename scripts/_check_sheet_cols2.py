"""Parse Ed's sheet with header=0 and show all columns"""
import requests
import pandas as pd
from io import StringIO

url = "https://docs.google.com/spreadsheets/d/1ivVtySJKJveJHNg9Hs4kH8fTqWDgMQMOxkYCPxIMtQM/export?format=csv"
resp = requests.get(url, timeout=30)
content = resp.text

# The first row IS the header
df = pd.read_csv(StringIO(content), header=0)
cols = list(df.columns)
print(f"Total columns: {len(cols)}")

# Show all columns with index
for i, c in enumerate(cols):
    marker = ""
    if 'rogress' in str(c).lower():
        marker = " *** PROGRESS ***"
    elif 'Prop Day' in str(c) or 'Hedge Day' in str(c):
        marker = " [farming]"
    elif 'Farm' in str(c):
        marker = " [farming]"
    print(f"  [{i:3d}] {c}{marker}")
