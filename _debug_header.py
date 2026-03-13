"""Debug: Check header detection in reimport script"""
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
print(f'Fetching XLSX...')
resp = requests.get(url, timeout=60)
wb = openpyxl.load_workbook(filename=io.BytesIO(resp.content), data_only=True)
ws = wb[wb.sheetnames[0]]

# Show first 10 rows to find header
for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=10, values_only=False)):
    row_vals = [str(c.value).strip() if c.value else '' for c in row[:10]]
    has_pf = any('Prop Firm' in str(v) for v in row_vals)
    has_as = any('Account Size' in str(v) for v in row_vals)
    print(f'Row {r_idx}: {row_vals[:5]} ... PF={has_pf} AS={has_as}')

# Now try the exact header detection from reimport_sheet_notes.py
header_idx = -1
col_map = {}
for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=False)):
    row_vals = [str(c.value).strip() if c.value else '' for c in row]
    if any('Prop Firm' in str(v) for v in row_vals):
        header_idx = r_idx
        col_map = {idx: str(h).strip() for idx, h in enumerate(row_vals) if h}
        print(f'\nHeader found via Prop Firm at r_idx={r_idx}')
        break
    elif any('Account Size' in str(v) for v in row_vals):
        header_idx = r_idx
        col_map = {idx: str(h).strip() for idx, h in enumerate(row_vals) if h}
        if 0 in col_map and not col_map[0]:
            col_map[0] = 'Prop Firm'
        elif 0 not in col_map:
            col_map[0] = 'Prop Firm'
        print(f'\nHeader found via Account Size at r_idx={r_idx}')
        print(f'col_map size: {len(col_map)}')
        # Show farming columns
        farming = {k: v for k, v in col_map.items() if 'Day' in v or 'Progress' in v}
        print(f'Farming cols: {farming}')
        break

if header_idx != -1:
    # Count valid rows and comments
    data_row_counter = 0
    note_count = 0
    for row_cells in ws.iter_rows(min_row=header_idx + 2, values_only=False):
        is_valid = False
        for c_idx, cell in enumerate(row_cells):
            if c_idx in col_map and col_map[c_idx] == 'Prop Firm':
                if cell.value and str(cell.value).strip():
                    is_valid = True
                break
        if is_valid:
            for c_idx, cell in enumerate(row_cells):
                if c_idx in col_map and cell.comment:
                    note_count += 1
            data_row_counter += 1
    print(f'\nValid data rows: {data_row_counter}')
    print(f'Total comments in data rows: {note_count}')
else:
    print('Header NOT found!')
