"""Debug FundedNext billing DOM to see account numbers per row."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'trader_companion'))
from prop_firm_scrapers import FundedNextCDPAccount

acct = FundedNextCDPAccount(debug_port=9222)
acct.login()

# Navigate to billing page
acct._js("window.location.href = 'https://app.fundednext.com/billing/billing-history'")
time.sleep(5)

# Dump raw DOM table data with ALL cells
raw = acct._js("""
(function() {
    var rows = document.querySelectorAll('.ant-table-wrapper table tbody tr.ant-table-row');
    if (rows.length === 0) rows = document.querySelectorAll('table tbody tr');
    var results = [];
    for (var i = 0; i < rows.length; i++) {
        var cells = rows[i].querySelectorAll('td');
        var cellTexts = [];
        for (var j = 0; j < cells.length; j++) {
            cellTexts.push('cell[' + j + ']: ' + cells[j].innerText.trim());
        }
        results.push(cellTexts);
    }
    return JSON.stringify(results, null, 2);
})()
""")

print("=== RAW DOM TABLE ===")
data = json.loads(raw)
for i, row in enumerate(data):
    print(f"\n--- Row {i} ---")
    for cell in row:
        print(f"  {cell}")

# Also check the mapping - navigate to accounts
acct._js("window.location.href = 'https://app.fundednext.com/accounts'")
time.sleep(5)
acct._switch_type_tab("Futures")
time.sleep(3)

mapping = acct.get_account_mapping()
print(f"\n=== ACCOUNT MAPPING ({len(mapping)}) ===")
for key, info in mapping.items():
    print(f"  {key} -> {json.dumps(info, indent=4)}")

acct.disconnect()
