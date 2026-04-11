"""Direct XLSX SUMIF replication to match Sheet formula exactly."""
import sys, os, io
import requests, openpyxl
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.data_processor import fetch_evaluations

sheet_key = '1q4atojmjW03XLU6bRfubZ3WZiK071x3eQttt5kdKVYs'

print("Fetching XLSX...")
resp = requests.get(f"https://docs.google.com/spreadsheets/d/{sheet_key}/export?format=xlsx", timeout=60)
wb = openpyxl.load_workbook(filename=io.BytesIO(resp.content), data_only=True)
ws = wb[wb.sheetnames[0]]

HEADER_ROW = 2
# Column indices (0-based): H=7(Status P1), T=19(Status Funded)
# J-N = 9-13 (P1 hedge), U-AA = 20-26 (Funded hedge)
P1_STATUS_CI = 7
FD_STATUS_CI = 19
P1_HEDGE_CIS = [9, 10, 11, 12, 13]  # J-N
FD_HEDGE_CIS = [20, 21, 22, 23, 24, 25, 26]  # U-AA

def num(cell_val):
    if cell_val is None: return 0.0
    if isinstance(cell_val, (int, float)): return float(cell_val)
    s = str(cell_val).strip().replace('$', '').replace(',', '')
    if not s or s == '-': return 0.0
    try: return float(s)
    except: return 0.0

# Replicate the exact Sheet formula
part1 = 0.0  # SUMIFS(J:N, H=Fail)
part2 = 0.0  # SUMIFS(U:AA, T=Fail) + SUMIFS(U:AA, T=Completed)
part3 = 0.0  # SUMIFS(J:N, T=Fail) + SUMIFS(J:N, T=Completed)

diff_rows = []

print("Fetching CSV for comparison...")
csv_evals, _ = fetch_evaluations(f"https://docs.google.com/spreadsheets/d/{sheet_key}/edit")

csv_idx = 0
for row_cells in ws.iter_rows(min_row=HEADER_ROW + 1, values_only=True):
    pf = row_cells[0]
    if not pf or not str(pf).strip():
        continue
    
    rn = csv_idx + 3  # sheet row (header=2, data starts row 3)
    p1_status = str(row_cells[P1_STATUS_CI] or '').strip()
    fd_status = str(row_cells[FD_STATUS_CI] or '').strip()
    
    p1_sum = sum(num(row_cells[ci]) for ci in P1_HEDGE_CIS)
    fd_sum = sum(num(row_cells[ci]) for ci in FD_HEDGE_CIS)
    
    # Part 1: P1 hedge where P1 Status = Fail
    if p1_status == 'Fail':
        part1 += p1_sum
    
    # Part 2: Funded hedge where Status = Fail or Completed
    if fd_status in ('Fail', 'Completed'):
        part2 += fd_sum
    
    # Part 3: P1 hedge where Status = Fail or Completed
    if fd_status in ('Fail', 'Completed'):
        part3 += p1_sum
    
    # Compare XLSX vs CSV for this row
    if csv_idx < len(csv_evals):
        csv_ev = csv_evals[csv_idx]
        csv_p1_cols = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
        csv_fd_cols = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']
        
        for ci, cname in zip(P1_HEDGE_CIS, csv_p1_cols):
            xv = num(row_cells[ci])
            cv = num(csv_ev.get(cname))
            if abs(xv - cv) > 0.005:
                # Check if it contributes
                if p1_status == 'Fail' or fd_status in ('Fail', 'Completed'):
                    diff_rows.append(f"  Row {rn} {pf} | {cname}: XLSX={row_cells[ci]}({xv:.2f}) CSV={csv_ev.get(cname)}({cv:.2f}) diff={xv-cv:.2f} P1={p1_status} F={fd_status}")
        
        for ci, cname in zip(FD_HEDGE_CIS, csv_fd_cols):
            xv = num(row_cells[ci])
            cv = num(csv_ev.get(cname))
            if abs(xv - cv) > 0.005:
                if fd_status in ('Fail', 'Completed'):
                    diff_rows.append(f"  Row {rn} {pf} | {cname}: XLSX={row_cells[ci]}({xv:.2f}) CSV={csv_ev.get(cname)}({cv:.2f}) diff={xv-cv:.2f} P1={p1_status} F={fd_status}")
    
    csv_idx += 1

xlsx_total = part1 + part2 + part3
print(f"\n=== XLSX SUMIF Results ===")
print(f"Part 1 (P1 hedge, P1=Fail):           {part1:.2f}")
print(f"Part 2 (FD hedge, FD=Fail/Completed): {part2:.2f}")
print(f"Part 3 (P1 hedge, FD=Fail/Completed): {part3:.2f}")
print(f"XLSX Total:                            {xlsx_total:.2f}")
print(f"Sheet Stats tab says:                  -439.52")
print(f"Dashboard computes (from CSV):         -431.67")
print(f"XLSX vs Stats tab diff:                {xlsx_total - (-439.52):.2f}")
print(f"XLSX vs Dashboard diff:                {xlsx_total - (-431.67):.2f}")

if diff_rows:
    print(f"\n=== XLSX vs CSV Cell Differences (completed rows) ===")
    for r in diff_rows:
        print(r)
else:
    print(f"\n(No XLSX vs CSV cell differences found)")
