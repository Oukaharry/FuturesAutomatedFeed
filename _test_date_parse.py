from datetime import datetime

test_vals = ['11/24/25', '12/2/25', '8/20/25', '8/29/2025', '2025-03-19']

for v in test_vals:
    parsed = None
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%d/%m/%Y', '%d/%m/%y',
                '%m-%d-%Y', '%m-%d-%y', '%d-%m-%Y', '%d-%m-%y',
                '%b %d, %Y', '%B %d, %Y', '%Y/%m/%d'):
        try:
            parsed = datetime.strptime(v, fmt).strftime('%Y-%m-%d')
            print(f'  {v} -> {parsed}  (fmt={fmt})')
            break
        except ValueError:
            continue
    if not parsed:
        print(f'  {v} -> FAILED TO PARSE')
