"""Look at what the server logs contain after FINAL DATA TO SAVE blocks, 
and check the actual push data format to find row-level account mappings."""
import os, glob, re

LOG_DIR = 'logs'
log_files = sorted(glob.glob(os.path.join(LOG_DIR, '*.log.*')))

# Find FINAL DATA TO SAVE blocks for Chris
with open('_chris_log_final_data.txt', 'w', encoding='utf-8') as out:
    for log_file in log_files:
        fname = os.path.basename(log_file)
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        
        for i, line in enumerate(lines):
            if 'FINAL DATA TO SAVE for Chris' in line:
                out.write(f'\n{"="*80}\n')
                out.write(f'[{fname}:{i}] {line.rstrip()}\n')
                # Show the next 30 lines
                for j in range(i+1, min(i+31, len(lines))):
                    out.write(f'  [{j}] {lines[j].rstrip()}\n')
                out.write(f'--- END BLOCK ---\n')
            
            # Also capture any line with evaluations data near Chris pushes
            if 'Push for Chris' in line:
                out.write(f'\n[PUSH {fname}:{i}] {line.rstrip()}\n')
                # Check 10 lines before and 20 after
                for j in range(max(0, i-5), min(i+20, len(lines))):
                    if 'evaluations' in lines[j].lower() or 'Account' in lines[j] or 'row' in lines[j].lower():
                        out.write(f'  [{j}] {lines[j].rstrip()}\n')

print('Written to _chris_log_final_data.txt')

# Also check: does the extraction JSON already have what we need?
import json
with open('_chris_ream_extracted.json', 'r') as f:
    jdata = json.load(f)

am = jdata['account_maps']
print(f'\naccount_maps entries: {len(am)}')
print(f'Covers rows: {sorted(int(k) for k in am.keys())[:30]}...')
print(f'Max row in account_maps: {max(int(k) for k in am.keys())}')
print(f'Min row in account_maps: {min(int(k) for k in am.keys())}')

# Check what the actual push data on the server endpoint looks like
# by looking at the app.py push endpoint
print('\nChecking data_push endpoint format...')
