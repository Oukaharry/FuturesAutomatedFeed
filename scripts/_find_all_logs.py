#!/usr/bin/env python3
"""
Find ALL log files on PythonAnywhere — server logs, access logs, error logs.
PA stores logs at specific locations. Also run the fast data_history scan.

Run: python3 _find_all_logs.py
"""
import os, sys, glob, subprocess
from datetime import datetime

print("=" * 100)
print("FINDING ALL LOGS ON PYTHONANYWHERE")
print(f"Time: {datetime.now()}")
print("=" * 100)

home = os.path.expanduser('~')
username = os.path.basename(home)

# ═══════════════════════════════════════════════════════════════
# 1. PythonAnywhere standard log locations
# ═══════════════════════════════════════════════════════════════
print(f"\n--- PythonAnywhere Standard Log Locations ---")

pa_log_patterns = [
    # PA web app logs
    f'/var/log/{username}.pythonanywhere.com.access.log',
    f'/var/log/{username}.pythonanywhere.com.error.log',
    f'/var/log/{username}.pythonanywhere.com.server.log',
    # Custom domain logs
    '/var/log/tradeopss.com.access.log',
    '/var/log/tradeopss.com.error.log',
    '/var/log/tradeopss.com.server.log',
    # PA user logs  
    f'{home}/logs/*.log',
    f'{home}/var/log/*',
    # Generic patterns
    '/var/log/*.log',
    f'/var/log/*{username}*',
    f'/tmp/*{username}*log*',
]

found_logs = []
for pattern in pa_log_patterns:
    matches = glob.glob(pattern)
    for f in matches:
        try:
            size = os.path.getsize(f)
            mtime = datetime.fromtimestamp(os.path.getmtime(f))
            found_logs.append((f, size, mtime))
            sz = f"{size/1024:.1f}K" if size < 1024*1024 else f"{size/1024/1024:.1f}M"
            print(f"  {sz:>10}  {mtime.strftime('%Y-%m-%d %H:%M')}  {f}")
        except (PermissionError, OSError):
            pass

# Also check for rotated/archived logs
print(f"\n--- Rotated / Archived Logs ---")
rotate_patterns = [
    f'/var/log/{username}*.log.*',
    f'/var/log/{username}*.log-*',
    '/var/log/tradeopss.com*.log.*',
    '/var/log/tradeopss.com*.log-*',
    '/var/log/tradeopss.com*.gz',
    f'/var/log/{username}*.gz',
    f'{home}/logs/*.log.*',
    f'{home}/logs/*.gz',
]

for pattern in rotate_patterns:
    matches = glob.glob(pattern)
    for f in sorted(matches):
        try:
            size = os.path.getsize(f)
            mtime = datetime.fromtimestamp(os.path.getmtime(f))
            found_logs.append((f, size, mtime))
            sz = f"{size/1024:.1f}K" if size < 1024*1024 else f"{size/1024/1024:.1f}M"
            print(f"  {sz:>10}  {mtime.strftime('%Y-%m-%d %H:%M')}  {f}")
        except (PermissionError, OSError):
            pass


# ═══════════════════════════════════════════════════════════════
# 2. Brute force search for any log files
# ═══════════════════════════════════════════════════════════════
print(f"\n--- Searching /var/log/ for accessible files ---")
try:
    for f in sorted(os.listdir('/var/log/')):
        path = os.path.join('/var/log', f)
        try:
            if os.path.isfile(path):
                size = os.path.getsize(path)
                mtime = datetime.fromtimestamp(os.path.getmtime(path))
                # Check if we can read it
                readable = os.access(path, os.R_OK)
                if readable and (username in f or 'tradeopss' in f):
                    sz = f"{size/1024:.1f}K" if size < 1024*1024 else f"{size/1024/1024:.1f}M"
                    print(f"  {sz:>10}  {mtime.strftime('%Y-%m-%d %H:%M')}  {path}  {'✓' if readable else '✗'}")
                    if (path, size, mtime) not in found_logs:
                        found_logs.append((path, size, mtime))
        except:
            pass
except PermissionError:
    print("  /var/log/ not accessible")

# Search home directory tree
print(f"\n--- Searching ~/MT5Dashboard/ for log files ---")
for root, dirs, files in os.walk(os.path.expanduser('~/MT5Dashboard')):
    # Skip .git and .nfs files
    dirs[:] = [d for d in dirs if d != '.git']
    for f in files:
        if 'log' in f.lower() or f.endswith('.log') or f.endswith('.gz'):
            path = os.path.join(root, f)
            try:
                size = os.path.getsize(path)
                if size > 0:
                    mtime = datetime.fromtimestamp(os.path.getmtime(path))
                    sz = f"{size/1024:.1f}K" if size < 1024*1024 else f"{size/1024/1024:.1f}M"
                    rel = path.replace(home, '~')
                    print(f"  {sz:>10}  {mtime.strftime('%Y-%m-%d %H:%M')}  {rel}")
                    found_logs.append((path, size, mtime))
            except:
                pass


# ═══════════════════════════════════════════════════════════════
# 3. For each log file, check date range and look for push data
# ═══════════════════════════════════════════════════════════════
MISSING_DATES = ['2026-03-26', '2026-03-27', '2026-03-28', '2026-03-29', 
                 '2026-03-30', '2026-03-31', '2026-04-01',
                 'Mar/26/2026', 'Mar/27/2026', 'Mar/28/2026', 'Mar/29/2026',
                 'Mar/30/2026', 'Mar/31/2026', 'Apr/01/2026',
                 '26/Mar/2026', '27/Mar/2026', '28/Mar/2026', '29/Mar/2026',
                 '30/Mar/2026', '31/Mar/2026', '01/Apr/2026']

print(f"\n\n{'='*80}")
print("SCANNING LOGS FOR MISSING WEEK DATA (March 26 - April 1)")
print(f"{'='*80}")

# Deduplicate
seen = set()
unique_logs = []
for path, size, mtime in found_logs:
    if path not in seen:
        seen.add(path)
        unique_logs.append((path, size, mtime))

for path, size, mtime in sorted(unique_logs):
    if size > 500 * 1024 * 1024:
        print(f"\n  Skipping {path} (too large: {size/1024/1024:.0f}M)")
        continue
    if size == 0:
        continue
    
    rel = path.replace(home, '~')
    print(f"\n  Scanning: {rel} ({size/1024:.0f}K)")
    
    try:
        # Handle gzipped files
        if path.endswith('.gz'):
            import gzip
            opener = lambda: gzip.open(path, 'rt', errors='replace')
        else:
            opener = lambda: open(path, 'r', errors='replace')
        
        first_line = None
        last_line = None
        missing_week_lines = []
        push_lines = []
        total_lines = 0
        
        with opener() as f:
            for line in f:
                total_lines += 1
                if not first_line:
                    first_line = line.strip()
                last_line = line.strip()
                
                # Check for missing week dates
                for d in MISSING_DATES:
                    if d in line:
                        missing_week_lines.append(line.strip())
                        # Check if it's a push/update
                        if any(kw in line.lower() for kw in ['update_data', 'push', 'post', 'api']):
                            push_lines.append(line.strip())
                        break
                
                if total_lines > 5000000:
                    break
        
        print(f"    Lines: {total_lines}")
        if first_line:
            print(f"    First: {first_line[:150]}")
        if last_line:
            print(f"    Last:  {last_line[:150]}")
        
        if missing_week_lines:
            print(f"    *** {len(missing_week_lines)} lines from missing week! ***")
            if push_lines:
                print(f"    *** {len(push_lines)} push/API lines! ***")
                for line in push_lines[:10]:
                    print(f"      {line[:200]}")
            else:
                for line in missing_week_lines[:5]:
                    print(f"      {line[:200]}")
    except Exception as e:
        print(f"    Error: {e}")


# ═══════════════════════════════════════════════════════════════
# 4. Check if PA stores archived logs elsewhere
# ═══════════════════════════════════════════════════════════════
print(f"\n\n{'='*80}")
print("PA LOG RETENTION INFO")
print(f"{'='*80}")
print(f"""
  PythonAnywhere log retention policy:
  - Server log:  Today only (overwritten on each reload)  
  - Access log:  Today only (rotated daily, kept ~30 days as .gz)
  - Error log:   Today only (rotated daily, kept ~30 days as .gz)
  
  HOWEVER: Rotated logs may exist as:
    /var/log/tradeopss.com.access.log.1
    /var/log/tradeopss.com.access.log.2.gz
    etc.
  
  Check the 'Rotated / Archived Logs' section above for these files.
""")

# Try to list all our log variants
print("  All /var/log/ files matching our domains:")
try:
    for f in sorted(os.listdir('/var/log/')):
        if username in f or 'tradeopss' in f:
            path = os.path.join('/var/log', f)
            try:
                size = os.path.getsize(path)
                mtime = datetime.fromtimestamp(os.path.getmtime(path))
                readable = os.access(path, os.R_OK)
                sz = f"{size/1024:.1f}K" if size < 1024*1024 else f"{size/1024/1024:.1f}M"
                print(f"    {sz:>10}  {mtime.strftime('%Y-%m-%d %H:%M')}  {f}  {'✓readable' if readable else '✗locked'}")
            except:
                print(f"    {'?':>10}  {'?':>16}  {f}")
except:
    pass


print(f"\n{'='*100}")
print("DONE")
print(f"{'='*100}")
