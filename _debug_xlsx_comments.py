"""Debug: Check if XLSX export contains cell comments"""
import sqlite3, json, requests, io, openpyxl, re

conn = sqlite3.connect('dashboard/dashboard.db')
cur = conn.cursor()
cur.execute("SELECT identity FROM clients_data WHERE client_id='Ed'")
row = cur.fetchone()
identity = json.loads(row[0])
sheet_url = identity['sheet_url']
conn.close()

match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', sheet_url)
key = match.group(1)
url = f'https://docs.google.com/spreadsheets/d/{key}/export?format=xlsx'
print(f'Fetching {url[:80]}...')
resp = requests.get(url, timeout=60)
print(f'Status: {resp.status_code}, Size: {len(resp.content)} bytes')

wb = openpyxl.load_workbook(filename=io.BytesIO(resp.content), data_only=True)
print(f'Sheets: {wb.sheetnames}')
ws = wb[wb.sheetnames[0]]

# Scan ALL cells for comments
total_comments = 0
for row in ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=False):
    for cell in row:
        if cell.comment:
            total_comments += 1
            if total_comments <= 15:
                text = cell.comment.text.replace('\n', ' | ')[:60]
                print(f'  Comment at {cell.coordinate}: "{text}"')

print(f'\nTotal comments in XLSX: {total_comments}')
print(f'Max row in sheet: {ws.max_row}')

# Also check: does Google Sheets "Notes" feature export differently?
# Google Sheets has both "Notes" (simple text on cell) and "Comments" (threaded discussion)
# openpyxl only sees Excel-style comments. Let's check if notes are stored differently.

# Try checking if there are any note-like attributes
print('\n--- Checking a known cell with a note (if row data visible) ---')
# Ed row 536 had Prop Day 1 = "2/5 | 1/13/26" as a note
# Let's find which sheet column is Prop Day 1
header_idx = -1
col_map = {}
for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=False)):
    row_vals = [str(c.value).strip() if c.value else '' for c in row]
    if any('Prop Firm' in str(v) for v in row_vals):
        header_idx = r_idx
        col_map = {}
        for idx, h in enumerate(row_vals):
            if h:
                col_map[h] = idx
        print(f'Header at xlsx row {r_idx + 1}')
        break

if 'Prop Day 1' in col_map:
    pd1_col = col_map['Prop Day 1']
    print(f'Prop Day 1 is at column index {pd1_col}')
    # Check a few data rows for that column
    data_row = 0
    for row in ws.iter_rows(min_row=header_idx + 2, values_only=False):
        pf_cell = row[0] if row else None
        if pf_cell and pf_cell.value and str(pf_cell.value).strip():
            if pd1_col < len(row):
                cell = row[pd1_col]
                val = cell.value
                has_comment = cell.comment is not None
                if val or has_comment:
                    comment_text = cell.comment.text[:40] if cell.comment else 'None'
                    print(f'  Data row {data_row}: value="{val}", comment={comment_text}')
            data_row += 1
            if data_row > 600:
                break

print(f'\nDone. Scanned {data_row} data rows.')
