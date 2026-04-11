"""Investigate abnormally high farming results in the sheet."""
import csv, io, re
import requests

SHEET_ID = '1Oh9EuozLXIsfxTvbvMIJKhzvOgmEOvt9NP-0HJJAEmA'

def fetch_csv(gid=0):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return list(csv.reader(io.StringIO(resp.text)))

def parse_currency(val):
    if not val or not val.strip():
        return None
    s = val.strip()
    if s.lower() in ('pass', 'farming', 'n/a', '-', ''):
        return None
    neg = '(' in s or s.startswith('-')
    s = re.sub(r'[^0-9.]', '', s)
    if not s:
        return None
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None

def main():
    print("Fetching sheet...")
    rows = fetch_csv()
    print(f"Rows: {len(rows)}, Cols: {max(len(r) for r in rows)}")

    # Find header
    header_idx = None
    for i, row in enumerate(rows):
        for cell in row:
            if 'prop firm' in str(cell).lower():
                header_idx = i
                break
        if header_idx is not None:
            break

    if header_idx is None:
        print("No header found!")
        return

    headers = [str(h).strip().lower() for h in rows[header_idx]]

    # Find all farming-related columns
    farming_cols = []
    for i, h in enumerate(headers):
        if 'farming' in h:
            farming_cols.append((i, h))

    print(f"\nFarming columns found:")
    for idx, name in farming_cols:
        print(f"  Col {idx}: '{name}'")

    # Also find hedge net and hedge result cols for context
    hedge_net_cols = [(i, h) for i, h in enumerate(headers) if h == 'hedge net']
    print(f"\nHedge net columns: {hedge_net_cols}")

    # Scan all data rows for farming values
    print(f"\n{'='*100}")
    print(f"  ALL NON-EMPTY FARMING VALUES")
    print(f"{'='*100}")

    big_values = []
    all_farming = []

    for row_idx in range(header_idx + 1, len(rows)):
        row = rows[row_idx]
        if len(row) <= 1:
            continue

        # Get prop firm name
        prop_col = next((i for i, h in enumerate(headers) if h == 'prop firm'), 0)
        prop = row[prop_col].strip() if prop_col < len(row) else ''
        
        # Get status
        status_col = next((i for i, h in enumerate(headers) if h == 'status'), None)
        status = row[status_col].strip() if status_col is not None and status_col < len(row) else ''

        for col_idx, col_name in farming_cols:
            if col_idx >= len(row):
                continue
            raw = row[col_idx].strip()
            if not raw or raw == '$0.00' or raw == '0':
                continue

            num = parse_currency(raw)
            sheet_row = row_idx + 1  # 1-based

            all_farming.append({
                'sheet_row': sheet_row,
                'prop': prop,
                'status': status,
                'col': col_name,
                'raw': raw,
                'numeric': num,
            })

            if num is not None and abs(num) > 10000:
                big_values.append({
                    'sheet_row': sheet_row,
                    'prop': prop,
                    'status': status,
                    'col': col_name,
                    'raw': raw,
                    'numeric': num,
                })

    # Print ALL farming values
    print(f"\n  Total non-empty farming values: {len(all_farming)}")
    print(f"\n  {'Row':>4} {'Prop Firm':<30} {'Status':<12} {'Column':<20} {'Raw Value':<25} {'Parsed':>15}")
    print("  " + "-" * 110)

    total = 0.0
    for f in sorted(all_farming, key=lambda x: x['sheet_row']):
        num_str = f"${f['numeric']:,.2f}" if f['numeric'] is not None else "PARSE_FAIL"
        print(f"  {f['sheet_row']:>4} {f['prop'][:30]:<30} {f['status'][:12]:<12} {f['col']:<20} {f['raw'][:25]:<25} {num_str:>15}")
        if f['numeric'] is not None:
            total += f['numeric']

    print("  " + "-" * 110)
    print(f"  {'TOTAL':>70} {f'${total:,.2f}':>15}")

    # Highlight suspicious values
    if big_values:
        print(f"\n{'='*100}")
        print(f"  SUSPICIOUS VALUES (> $10,000)")
        print(f"{'='*100}")
        for f in big_values:
            print(f"  Row {f['sheet_row']}: {f['prop']} - {f['col']} = '{f['raw']}' -> ${f['numeric']:,.2f}")
            # Print full row context
            row = rows[f['sheet_row'] - 1]
            print(f"    Full row first 10 cells: {row[:10]}")

    # Also check: what formulas could be summing these?
    # Look at the "Totals" column area or summary rows
    print(f"\n{'='*100}")
    print(f"  CHECKING FOR SUMMARY/TOTALS ROWS")
    print(f"{'='*100}")
    for row_idx in range(len(rows)):
        row = rows[row_idx]
        for cell in row:
            if 'farming' in str(cell).lower() and ('result' in str(cell).lower() or 'total' in str(cell).lower() or 'profit' in str(cell).lower()):
                print(f"  Row {row_idx+1}: {row[:8]}")
                break

    # Check the profitability section (rows 11-17 based on screenshot)
    print(f"\n{'='*100}")
    print(f"  PROFITABILITY SECTION (rows 10-20)")
    print(f"{'='*100}")
    for row_idx in range(9, min(20, len(rows))):
        row = rows[row_idx]
        non_empty = [(i, c) for i, c in enumerate(row) if c.strip()]
        if non_empty:
            print(f"  Row {row_idx+1}: {non_empty}")


if __name__ == '__main__':
    main()
