#!/usr/bin/env python3
"""
STEP 1: Analyze what data the server logs actually contain.
Sample error.log and server.log from the missing week to understand
what can be reconstructed.

Run: python3 _analyze_logs.py
"""
import os, sys, gzip, re, json
from datetime import datetime
from collections import defaultdict, Counter

print("=" * 100)
print("LOG CONTENT ANALYSIS — What data is in the missing week logs?")
print(f"Time: {datetime.now()}")
print("=" * 100)

# The key log files covering the missing week
LOG_FILES = {
    'error.log.8': ('/var/log/www.tradeopss.com.error.log.8.gz', 'Mar 25-26'),
    'error.log.7': ('/var/log/www.tradeopss.com.error.log.7.gz', 'Mar 26-27'),
    'error.log.6': ('/var/log/www.tradeopss.com.error.log.6.gz', 'Mar 27-28'),
    'error.log.5': ('/var/log/www.tradeopss.com.error.log.5.gz', 'Mar 28-29'),
    'error.log.4': ('/var/log/www.tradeopss.com.error.log.4.gz', 'Mar 29-30'),
    'error.log.3': ('/var/log/www.tradeopss.com.error.log.3.gz', 'Mar 30-31'),
    'error.log.1': ('/var/log/www.tradeopss.com.error.log.1', 'Mar 31-Apr 2'),
    'server.log.7': ('/var/log/www.tradeopss.com.server.log.7.gz', 'Mar 26-27'),
    'server.log.1': ('/var/log/www.tradeopss.com.server.log.1', 'Mar 31-Apr 2'),
    # Also check the dashboard's own logs
    'dashboard.server.log.3': (os.path.expanduser('~/MT5Dashboard/dashboard/server.log.3'), 'Apr 2'),
}


# ═══════════════════════════════════════════════════════════════
# PART 1: Sample each log file to understand content patterns
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*80}")
print("PART 1: LOG CONTENT PATTERNS")
print(f"{'='*80}")

# For each log, categorize lines by type
for label, (path, dates) in LOG_FILES.items():
    if not os.path.exists(path):
        print(f"\n  [{label}] NOT FOUND: {path}")
        continue
    
    size = os.path.getsize(path)
    sz = f"{size/1024/1024:.1f}MB"
    print(f"\n  [{label}] ({dates}) — {sz}")
    
    categories = Counter()
    sample_lines = defaultdict(list)
    total = 0
    
    try:
        if path.endswith('.gz'):
            f = gzip.open(path, 'rt', errors='replace')
        else:
            f = open(path, 'r', errors='replace')
        
        for line in f:
            total += 1
            line = line.strip()
            
            # Categorize
            if 'FINAL DATA TO SAVE' in line:
                categories['FINAL_DATA_TO_SAVE'] += 1
                if len(sample_lines['FINAL_DATA_TO_SAVE']) < 3:
                    sample_lines['FINAL_DATA_TO_SAVE'].append(line[:300])
            elif 'Push for' in line and 'deals' in line:
                categories['PUSH_SUMMARY'] += 1
                if len(sample_lines['PUSH_SUMMARY']) < 3:
                    sample_lines['PUSH_SUMMARY'].append(line[:300])
            elif 'CLIENT_DATA_PUSH' in line or 'Data pushed for' in line:
                categories['DATA_PUSH_EVENT'] += 1
                if len(sample_lines['DATA_PUSH_EVENT']) < 3:
                    sample_lines['DATA_PUSH_EVENT'].append(line[:300])
            elif 'save_client_data' in line.lower() or 'SAVING' in line:
                categories['SAVE_EVENT'] += 1
                if len(sample_lines['SAVE_EVENT']) < 3:
                    sample_lines['SAVE_EVENT'].append(line[:300])
            elif 'evaluations' in line.lower() and ('NEW' in line or 'EXISTING' in line or 'Preserving' in line):
                categories['EVAL_INFO'] += 1
                if len(sample_lines['EVAL_INFO']) < 3:
                    sample_lines['EVAL_INFO'].append(line[:300])
            elif 'calculate_statistics' in line or 'Stats calculated' in line:
                categories['STATS_CALC'] += 1
                if len(sample_lines['STATS_CALC']) < 3:
                    sample_lines['STATS_CALC'].append(line[:300])
            elif 'hedging_review' in line.lower() or 'total_deposits' in line or 'total_withdrawals' in line:
                categories['HEDGING_VALUES'] += 1
                if len(sample_lines['HEDGING_VALUES']) < 3:
                    sample_lines['HEDGING_VALUES'].append(line[:300])
            elif '/api/update_data' in line and 'POST' in line:
                categories['UPDATE_DATA_POST'] += 1
                if len(sample_lines['UPDATE_DATA_POST']) < 3:
                    sample_lines['UPDATE_DATA_POST'].append(line[:300])
            elif '/api/client/push' in line and 'POST' in line:
                categories['CLIENT_PUSH_POST'] += 1
                if len(sample_lines['CLIENT_PUSH_POST']) < 3:
                    sample_lines['CLIENT_PUSH_POST'].append(line[:300])
            elif '/api/data' in line and 'GET' in line and '200' in line:
                categories['DATA_GET_200'] += 1
                if len(sample_lines['DATA_GET_200']) < 3:
                    sample_lines['DATA_GET_200'].append(line[:300])
            elif 'DATA_PROCESSOR' in line or 'DEBUG' in line.upper():
                categories['DEBUG_OUTPUT'] += 1
                if len(sample_lines['DEBUG_OUTPUT']) < 5:
                    sample_lines['DEBUG_OUTPUT'].append(line[:300])
            elif '/api/notes' in line or 'UPDATE_NOTE' in line or 'Note on' in line:
                categories['NOTES'] += 1
                if len(sample_lines['NOTES']) < 3:
                    sample_lines['NOTES'].append(line[:300])
            elif 'FA PRE-COMPUTE' in line or 'FA SKIP' in line or 'FARMING' in line.upper():
                categories['FARMING'] += 1
                if len(sample_lines['FARMING']) < 3:
                    sample_lines['FARMING'].append(line[:300])
            elif 'SESSION' in line and 'account_guess' in line:
                categories['SESSION_MATCH'] += 1
                if len(sample_lines['SESSION_MATCH']) < 3:
                    sample_lines['SESSION_MATCH'].append(line[:300])
            elif 'MATCHED EVAL' in line:
                categories['MATCHED_EVAL'] += 1
                if len(sample_lines['MATCHED_EVAL']) < 3:
                    sample_lines['MATCHED_EVAL'].append(line[:300])
            elif 'watermark' in line.lower():
                categories['WATERMARK'] += 1
                if len(sample_lines['WATERMARK']) < 3:
                    sample_lines['WATERMARK'].append(line[:300])
            elif '"deals"' in line or '"positions"' in line or '"evaluations"' in line:
                categories['JSON_DATA'] += 1
                if len(sample_lines['JSON_DATA']) < 5:
                    sample_lines['JSON_DATA'].append(line[:500])
            elif line.startswith('{') or line.startswith('['):
                categories['RAW_JSON'] += 1
                if len(sample_lines['RAW_JSON']) < 5:
                    sample_lines['RAW_JSON'].append(line[:500])
            elif 'Sheet import' in line or 'migrate_sheet' in line or 'SHEET_IMPORT' in line:
                categories['SHEET_IMPORT'] += 1
                if len(sample_lines['SHEET_IMPORT']) < 3:
                    sample_lines['SHEET_IMPORT'].append(line[:300])
            elif 'import_csv' in line or 'CSV' in line:
                categories['CSV_IMPORT'] += 1
                if len(sample_lines['CSV_IMPORT']) < 3:
                    sample_lines['CSV_IMPORT'].append(line[:300])
            elif 'Stats tab override' in line:
                categories['STATS_TAB'] += 1
            elif '[REQUEST]' in line:
                categories['REQUEST_LOG'] += 1
            else:
                categories['OTHER'] += 1
                if len(sample_lines['OTHER']) < 5:
                    sample_lines['OTHER'].append(line[:300])
            
            if total > 2000000:  # Cap at 2M lines
                break
        
        f.close()
    except Exception as e:
        print(f"    Error: {e}")
        continue
    
    print(f"    Total lines: {total}")
    print(f"\n    Category breakdown:")
    for cat, cnt in categories.most_common(30):
        pct = cnt / total * 100
        print(f"      {cat:<25} {cnt:>8} ({pct:>5.1f}%)")
        if cat in sample_lines:
            for s in sample_lines[cat][:2]:
                print(f"        → {s}")


# ═══════════════════════════════════════════════════════════════
# PART 2: Deep dive into a single error log to find full data
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*80}")
print("PART 2: DEEP DIVE — searching for reconstructable data in error.log.7 (Mar 26-27)")
print(f"{'='*80}")

target_log = '/var/log/www.tradeopss.com.error.log.7.gz'
if os.path.exists(target_log):
    try:
        # Look for multi-line JSON blocks, full data dumps, etc.
        full_blocks = []
        current_block = []
        in_json_block = False
        json_depth = 0
        
        push_data_sections = []  # Lines around push events
        
        f = gzip.open(target_log, 'rt', errors='replace')
        line_num = 0
        context_buffer = []
        
        for line in f:
            line_num += 1
            context_buffer.append(line.rstrip())
            if len(context_buffer) > 30:
                context_buffer.pop(0)
            
            # When we see a push event, capture surrounding context
            if 'Push for' in line and 'deals' in line and len(push_data_sections) < 5:
                # Get the next 50 lines too
                push_context = list(context_buffer)
                try:
                    for _ in range(50):
                        next_line = next(f)
                        line_num += 1
                        push_context.append(next_line.rstrip())
                except StopIteration:
                    pass
                push_data_sections.append((line_num, push_context))
            
            # Look for lines that contain substantial JSON
            if ('{' in line and '"' in line and len(line) > 500) and len(full_blocks) < 10:
                full_blocks.append((line_num, line.rstrip()[:1000]))
            
            if line_num > 500000:  # Sample first 500K lines
                break
        
        f.close()
        
        if push_data_sections:
            print(f"\n  Found {len(push_data_sections)} push events. Sample context:")
            for i, (lnum, ctx) in enumerate(push_data_sections[:3]):
                print(f"\n  --- Push event #{i+1} around line {lnum} ---")
                for cl in ctx:
                    print(f"    {cl[:200]}")
        
        if full_blocks:
            print(f"\n  Found {len(full_blocks)} lines with substantial JSON:")
            for lnum, block in full_blocks[:5]:
                print(f"    Line {lnum}: {block[:500]}")
    
    except Exception as e:
        print(f"  Error: {e}")
        import traceback; traceback.print_exc()
else:
    print(f"  {target_log} not found")


# ═══════════════════════════════════════════════════════════════
# PART 3: Check what /api/update_data and /api/client/push log
# Look for the full request/response data
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*80}")
print("PART 3: CHECK FOR FULL DATA IN PUSH REQUESTS")
print(f"{'='*80}")

# Check error.log.3 (Mar 30-31) — known to have 67,224 push/API lines
log3 = '/var/log/www.tradeopss.com.error.log.3.gz'
if os.path.exists(log3):
    print(f"\n  Scanning error.log.3 for full data blocks...")
    
    push_blocks = []
    current_push = None
    lines_after_push = 0
    
    try:
        f = gzip.open(log3, 'rt', errors='replace')
        for i, line in enumerate(f):
            ls = line.strip()
            
            # Start capturing when we see a push
            if '📥 Push for' in ls:
                if current_push and current_push['lines']:
                    push_blocks.append(current_push)
                # Extract client_id
                m = re.search(r'Push for (.+?):', ls)
                cid = m.group(1) if m else '?'
                current_push = {'client_id': cid, 'start_line': i, 'header': ls[:200], 'lines': []}
                lines_after_push = 0
            elif current_push and lines_after_push < 100:
                current_push['lines'].append(ls)
                lines_after_push += 1
                
                # Stop if we hit the next timestamp entry that's not indented
                if ls and not ls.startswith(' ') and not ls.startswith('\t') and re.match(r'^\d{4}-\d{2}-\d{2}', ls) and lines_after_push > 5:
                    push_blocks.append(current_push)
                    current_push = None
            
            if len(push_blocks) >= 10:
                break
            
            if i > 2000000:
                break
        
        if current_push:
            push_blocks.append(current_push)
        f.close()
        
        print(f"\n  Captured {len(push_blocks)} complete push blocks:")
        for pb in push_blocks[:3]:
            print(f"\n  === {pb['client_id']} (line {pb['start_line']}) ===")
            print(f"  {pb['header']}")
            for pl in pb['lines'][:30]:
                print(f"    {pl[:200]}")
    
    except Exception as e:
        print(f"  Error: {e}")


# ═══════════════════════════════════════════════════════════════
# PART 4: Check the full DATA_PROCESSOR DEBUG blocks
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*80}")
print("PART 4: DATA_PROCESSOR DEBUG OUTPUT")
print(f"{'='*80}")

# The server.log.1 has #012 separated multi-line debug blocks
slog1 = '/var/log/www.tradeopss.com.server.log.1'
if os.path.exists(slog1):
    print(f"\n  Scanning server.log.1 for DATA_PROCESSOR DEBUG...")
    
    debug_blocks = []
    try:
        with open(slog1, 'r', errors='replace') as f:
            for i, line in enumerate(f):
                if 'DATA_PROCESSOR' in line or 'DEBUG' in line.upper():
                    debug_blocks.append((i, line.strip()[:500]))
                    if len(debug_blocks) >= 10:
                        break
                if i > 500000:
                    break
        
        if debug_blocks:
            print(f"  Found {len(debug_blocks)} debug lines:")
            for lnum, bl in debug_blocks[:5]:
                # #012 is newline in uwsgi logs
                expanded = bl.replace('#012', '\n    ')
                print(f"    Line {lnum}: {expanded[:500]}")
    except Exception as e:
        print(f"  Error: {e}")


print(f"\n\n{'='*100}")
print("ANALYSIS COMPLETE")
print(f"{'='*100}")
