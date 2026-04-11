"""Summarize the deep log extraction results."""
import json

with open('_deep_log_results.json', 'r') as f:
    data = json.load(f)

print(f'Rows with [MATCHED EVAL]: {len(data["row_to_matched"])}')
print(f'Rows with FINAL DATA accounts: {len(data["row_to_final_data"])}')
print(f'Session accounts: {len(data["session_accounts"])}')
print(f'Rows with firm-matching candidates: {len(data["results"])}')

# Show rows with candidates - count how many per row
total_candidates = 0
for idx, cands in data['results'].items():
    total_candidates += len(cands)
print(f'Total firm-matching candidate accounts: {total_candidates}')

# Show a sample
for idx in sorted(data['results'].keys(), key=int)[:5]:
    cands = data['results'][idx]
    print(f'  Row {idx}: {cands[:5]}...' if len(cands) > 5 else f'  Row {idx}: {cands}')
