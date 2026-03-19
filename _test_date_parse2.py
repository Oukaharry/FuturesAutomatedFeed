"""Test the updated _parse_date_str against all real formats."""
import sys
sys.path.insert(0, '.')
from dashboard.app import _parse_date_str

tests = [
    # M/D (no year)
    ('10/20', '2025-10-20'),
    ('7/8', '2025-07-08'),
    ('8/1', '2025-08-01'),
    ('10/1', '2025-10-01'),
    ('11/2', '2025-11-02'),
    ('11/13', '2025-11-13'),
    # M/D/YY
    ('1/1/26', '2026-01-01'),
    ('10/1/25', '2025-10-01'),
    ('12/2/25', '2025-12-02'),
    ('11/24/25', '2025-11-24'),
    # M/D/YYYY
    ('8/29/2025', '2025-08-29'),
    ('1/5/2026', '2026-01-05'),
    # MM/DD/YY
    ('02/03/26', '2026-02-03'),
    ('10-22-25', '2025-10-22'),
    # MM/DD/YYYY
    ('01/21/2026', '2026-01-21'),
    ('10/01/2025', '2025-10-01'),
    # Trailing period
    ('2/2/26.', '2026-02-02'),
    ('1/24/26.', '2026-01-24'),
    ('2/3/2026.', '2026-02-03'),
    ('2/10/2026.', '2026-02-10'),
    # Dot-separated: 8.19.20
    ('8.19.20', '2020-08-19'),
    # Leading junk
    ('V10/17/25', '2025-10-17'),
    # Double-slash
    ('12//25', None),  # ambiguous, should fail
    # Garbage
    ('$45,938.00', None),
    ('EVALUATION PHASE', None),
    ('CLOSE', None),
    ('Topt', None),
    ('re', None),
    ('33/26', None),
    ('3/626', None),
]

print(f"Testing {len(tests)} cases:\n")
passed = 0
failed = 0
for val, expected in tests:
    result = _parse_date_str(val)
    ok = result == expected
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: '{val}' -> got '{result}', expected '{expected}'")

print(f"\n{passed}/{len(tests)} passed, {failed} failed")
