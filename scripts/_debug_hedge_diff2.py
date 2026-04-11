"""Find the $7.85 hedging difference by replicating exact Sheet SUMIF logic."""
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.data_processor import fetch_evaluations, parse_currency

SHEET_URL = "https://docs.google.com/spreadsheets/d/1q4atojmjW03XLU6bRfubZ3WZiK071x3eQttt5kdKVYs/edit"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard', 'dashboard.db')

def pc(val):
    if val is None: return 0.0
    s = str(val).strip()
    if not s or s == '-' or s.lower() == 'none': return 0.0
    s = s.replace('$', '').replace(',', '').strip()
    try: return float(s)
    except: return 0.0

# Fetch sheet data
print("Fetching sheet...")
sh_evals, sh_notes = fetch_evaluations(SHEET_URL)
print(f"Rows: {len(sh_evals)}")

# Column mapping from the formula:
# J-N = Hedge Result 1-5 (P1)
# H = Status P1
# T = Status (Funded)
# U-AA = Hedge Result 1.1 - Hedge Result 7 (Funded)

# Replicate exact SUMIF from formula
part1 = 0.0  # P1 hedge (J-N) where P1 Status (H) = "Fail"
part2 = 0.0  # Funded hedge (U-AA) where Funded Status (T) = "Fail" or "Completed"
part3 = 0.0  # P1 hedge (J-N) where Funded Status (T) = "Fail" or "Completed"

P1_COLS = ['Hedge Result 1', 'Hedge Result 2', 'Hedge Result 3', 'Hedge Result 4', 'Hedge Result 5']
FD_COLS = ['Hedge Result 1.1', 'Hedge Result 2.1', 'Hedge Result 3.1', 'Hedge Result 4.1', 'Hedge Result 5.1', 'Hedge Result 6', 'Hedge Result 7']

# Also track what parse_currency (dashboard version) gives vs pc (simple)
part1_pc = 0.0
part2_pc = 0.0
part3_pc = 0.0

for idx, ev in enumerate(sh_evals):
    rn = idx + 2
    p1_status = str(ev.get('Status P1', '') or '').strip()
    f_status = str(ev.get('Status', '') or '').strip()
    
    p1_vals = [pc(ev.get(c)) for c in P1_COLS]
    fd_vals = [pc(ev.get(c)) for c in FD_COLS]
    p1_sum = sum(p1_vals)
    fd_sum = sum(fd_vals)
    
    p1_vals_parse = [parse_currency(ev.get(c)) for c in P1_COLS]
    fd_vals_parse = [parse_currency(ev.get(c)) for c in FD_COLS]
    p1_sum_parse = sum(p1_vals_parse)
    fd_sum_parse = sum(fd_vals_parse)
    
    # Part 1: P1 hedge where P1 Status = "Fail"
    if p1_status == 'Fail':
        part1 += p1_sum
        part1_pc += p1_sum_parse
    
    # Part 2: Funded hedge where Funded Status = "Fail" or "Completed"
    if f_status in ('Fail', 'Completed'):
        part2 += fd_sum
        part2_pc += fd_sum_parse
    
    # Part 3: P1 hedge where Funded Status = "Fail" or "Completed"
    if f_status in ('Fail', 'Completed'):
        part3 += p1_sum
        part3_pc += p1_sum_parse
    
    # Check for rows where Part 1 AND Part 3 both fire (double-count P1)
    if p1_status == 'Fail' and f_status in ('Fail', 'Completed') and abs(p1_sum) > 0.005:
        print(f"  ** DOUBLE-COUNT Row {rn}: {ev.get('Prop Firm')} P1={p1_status} F={f_status} P1_hedge={p1_sum:.2f}")
    
    # Check for rows where pc != parse_currency (parsing difference)
    if abs(p1_sum - p1_sum_parse) > 0.005 or abs(fd_sum - fd_sum_parse) > 0.005:
        print(f"  ** PARSE DIFF Row {rn}: {ev.get('Prop Firm')} P1: simple={p1_sum:.2f} parse={p1_sum_parse:.2f} FD: simple={fd_sum:.2f} parse={fd_sum_parse:.2f}")
        for c in P1_COLS + FD_COLS:
            raw = ev.get(c)
            s = pc(raw)
            p = parse_currency(raw)
            if abs(s - p) > 0.005:
                print(f"    {c}: raw='{raw}' simple={s:.2f} parse_currency={p:.2f}")

total_simple = part1 + part2 + part3
total_parse = part1_pc + part2_pc + part3_pc

print(f"\n=== Simple parse ===")
print(f"Part 1 (P1 where P1=Fail):           {part1:.2f}")
print(f"Part 2 (FD where FD=Fail/Completed): {part2:.2f}")
print(f"Part 3 (P1 where FD=Fail/Completed): {part3:.2f}")
print(f"Total:                                {total_simple:.2f}")

print(f"\n=== parse_currency (dashboard version) ===")
print(f"Part 1 (P1 where P1=Fail):           {part1_pc:.2f}")
print(f"Part 2 (FD where FD=Fail/Completed): {part2_pc:.2f}")
print(f"Part 3 (P1 where FD=Fail/Completed): {part3_pc:.2f}")
print(f"Total:                                {total_parse:.2f}")

print(f"\nSheet Stats tab says:                 -439.52")
print(f"Dashboard computes:                   -431.67")
print(f"Difference:                           {-439.52 - (-431.67):.2f}")
