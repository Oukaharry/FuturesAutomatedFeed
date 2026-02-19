import re

def extract_account_from_comment(c):
    if not c: return None
    
    # Look for digits before the phase
    m = re.search(r'(\d+)_(CH|FD|DD|FA)', c, re.IGNORECASE)
    if m:
        return m.group(1)
    
    # Fallback: Look for alphanumeric string of length 4+
    m = re.search(r'([A-Za-z0-9]{4,})_(CH|FD|DD|FA)', c, re.IGNORECASE)
    if m:
        return m.group(1)
        
    return None

test_cases = [
    "50KTC-V2-...4610_CH2",
    "MFFU...60016_FD1",
    "V2-...3586_CH1",
    "Normal12345_CH1"
]

print("Testing extract_account_from_comment:")
for c in test_cases:
    res = extract_account_from_comment(c)
    print(f"Comment: '{c}' -> Extracted: '{res}'")
