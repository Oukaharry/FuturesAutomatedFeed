"""Debug which clients get flagged for downtime and why."""
import sys, os
sys.path.insert(0, '.')
os.environ.setdefault('FLASK_ENV', 'development')

from config.hierarchy import get_all_clients, get_client_profile
from dashboard.database import get_client_data
from datetime import datetime

now = datetime.now()
today_wd = now.weekday()

day_names = {0:'Monday',1:'Tuesday',2:'Wednesday',3:'Thursday',4:'Friday'}
if today_wd <= 3:
    next_td = today_wd + 1
else:
    next_td = 0
allowed = {today_wd, next_td}
print(f'Today: {day_names.get(today_wd, "Weekend")} (wd={today_wd})')
print(f'Allowed days: {[day_names[d] for d in sorted(allowed)]}')
print()

wd_to_num = {
    'monday':0,'mon':0,
    'tuesday':1,'tue':1,'tues':1,
    'wednesday':2,'wed':2,'weds':2,
    'thursday':3,'thu':3,'thurs':3,
    'friday':4,'fri':4,
}

flagged = []
not_flagged = []
skipped = []

for client_name in sorted(get_all_clients()):
    data = get_client_data(client_name)
    if not data:
        skipped.append(f'  {client_name}: no data')
        continue
    identity = data.get('identity', {})
    if isinstance(identity, dict) and identity.get('active_status') == 'inactive':
        skipped.append(f'  {client_name}: inactive')
        continue
    evaluations = data.get('evaluations', [])
    for idx, ev in enumerate(evaluations):
        if ev.get('_deleted'):
            continue
        status_p1 = str(ev.get('Status P1', '') or '').strip().lower()
        status_p2 = str(ev.get('Status', '') or '').strip().lower()
        
        prop_firm = str(ev.get('Prop Firm', '') or '').strip()
        acct_size = str(ev.get('Account Size', '') or '').strip()
        has_data = bool(prop_firm or acct_size)
        
        if not has_data:
            continue
            
        inactive_p1 = any(k in status_p1 for k in ('fail','breach','delete','closed','sl'))
        inactive_p2 = any(k in status_p2 for k in ('fail','breach','delete','closed','sl','complete'))
        
        acct = str(ev.get('Account #', '') or '').strip() or str(ev.get('Account #.1', '') or '').strip() or '?'
        
        # Why would row be skipped?
        skip_reasons = []
        if inactive_p1:
            skip_reasons.append(f'inactive_p1({status_p1})')
        if inactive_p2:
            skip_reasons.append(f'inactive_p2({status_p2})')
        if not status_p1:
            skip_reasons.append('empty_status_p1')
        
        if skip_reasons:
            not_flagged.append(f'  SKIP: {client_name} Row{idx+1} [{acct}] - {", ".join(skip_reasons)}')
            continue
        
        # Find all weekday mentions
        found_days = set()
        day_sources = {}
        for key, val in ev.items():
            if str(key).startswith('_'):
                continue
            s = str(val or '').strip().lower()
            for token, day_num in wd_to_num.items():
                if token in s:
                    found_days.add(day_num)
                    if day_num not in day_sources:
                        day_sources[day_num] = []
                    day_sources[day_num].append(f'{key}="{str(val)[:40]}"')
        
        stale = found_days - allowed
        
        if stale:
            stale_names = [day_names[d] for d in sorted(stale)]
            flagged.append(f'  FLAGGED: {client_name} Row{idx+1} [{acct}] p1="{status_p1}" p2="{status_p2}" stale={stale_names}')
            for d in sorted(stale):
                if d in day_sources:
                    for src in day_sources[d][:3]:
                        flagged.append(f'    {day_names[d]} found in: {src}')
        elif found_days:
            found_names = [day_names[d] for d in sorted(found_days) if d in day_names]
            not_flagged.append(f'  OK: {client_name} Row{idx+1} [{acct}] p1="{status_p1}" p2="{status_p2}" days={found_names}')
        else:
            not_flagged.append(f'  NO_DAYS: {client_name} Row{idx+1} [{acct}] p1="{status_p1}" p2="{status_p2}"')

print(f'=== FLAGGED ({len(flagged)} lines) ===')
for line in flagged:
    print(line)
print()
print(f'=== NOT FLAGGED / SKIPPED ({len(not_flagged)} lines) ===')
for line in not_flagged:
    print(line)
print()
print(f'=== INACTIVE/NO DATA ({len(skipped)}) ===')
for line in skipped[:20]:
    print(line)
if len(skipped) > 20:
    print(f'  ... and {len(skipped)-20} more')
