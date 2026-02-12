import re

def get_last_n_digits(account: str, n: int = 5) -> str:
    """
    Extract last N digits from account number.
    Prioritizes digits at the end of the string to avoid prefix contamination.
    """
    if not account:
        return ""
    
    # Try to extract the final sequence of digits
    match = re.search(r'(\d+)$', str(account).strip())
    if match:
        digits = match.group(1)
        # For Topstep (V2-) or short accounts, ensure we don't demand more digits than exist
        if len(digits) < n:
            return digits
        return digits[-n:]
    
    # Fallback: extract all digits
    digits = re.sub(r'\D', '', str(account))
    if len(digits) < n:
        return digits
    return digits[-n:]

target = "FTDF...23575"
db_val = "FTDFYSLX50129523575"

t_last5 = get_last_n_digits(target, 5)
d_last5 = get_last_n_digits(db_val, 5)

print(f"Target: '{target}' -> Last5: '{t_last5}'")
print(f"DB Val: '{db_val}' -> Last5: '{d_last5}'")
print(f"Match? {t_last5 == d_last5}")

# Test the function logic with the loop
matches = []
target_last5 = t_last5
eval_last5 = d_last5

if target_last5 and len(target_last5) >= 4:
    if eval_last5 == target_last5:
        print("MATCHED via exact last 5")
    elif len(eval_last5) != len(target_last5):
        if eval_last5.endswith(target_last5) or target_last5.endswith(eval_last5):
             print("MATCHED via suffix")
    elif len(target_last5) >= 4 and len(eval_last5) >= 4:
        if target_last5[-4:] == eval_last5[-4:]:
             print("MATCHED via last 4")
        else:
            print("FAILED last 4 check")
else:
    print("Skipped logic")
