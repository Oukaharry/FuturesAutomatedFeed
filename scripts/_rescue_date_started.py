#!/usr/bin/env python3
"""
TARGETED RESCUE — Scan 48GB NFS for "Date Started" values in March 26 → April 2, 2026.

Searches for the actual JSON key "Date Started" paired with each date format.
Also checks "Date Started.1" (Phase 2) and "Date Purchased".

READ-ONLY on the NFS file.  Outputs _rescue_date_started.json.

Run on PythonAnywhere:
    python3 _rescue_date_started.py 2>&1 | tee _rescue_ds_log.txt
"""
import os, sys, json, re, time
from datetime import datetime, timedelta

# ── CONFIG ──────────────────────────────────────────────────────
NFS_FILE = os.path.expanduser('~/MT5Dashboard/dashboard/.nfs0000000004802cdb0000de98')
OUTPUT_JSON = os.path.expanduser('~/MT5Dashboard/_rescue_date_started.json')
CHUNK_SIZE = 10 * 1024 * 1024   # 10 MB
OVERLAP = 50_000                 # 50 KB overlap

# Date range: March 26 → April 2 inclusive
START = datetime(2026, 3, 26)
END   = datetime(2026, 4, 2)

# Keys to match
DATE_KEYS = ['Date Started', 'Date Started.1', 'Date Purchased']

# Build byte patterns:  "Date Started": "3/26/26"  etc.
PATTERNS = []   # list of (bytes_pattern, key_name, iso_date)
d = START
while d <= END:
    iso = d.strftime('%Y-%m-%d')       # 2026-03-26
    mdy_short = f"{d.month}/{d.day}/{d.strftime('%y')}"    # 3/26/26
    mdy_pad   = d.strftime('%m/%d/%y')                      # 03/26/26

    date_variants = [iso, mdy_short, mdy_pad]
    # Avoid duplicates (e.g. 03/26/26 == 3/26/26 when month<10 pad is same)
    date_variants = list(dict.fromkeys(date_variants))

    for key in DATE_KEYS:
        for dv in date_variants:
            # Two common JSON spacings:  "key": "val"  and  "key":"val"
            for sep in ['": "', '":"']:
                pat = f'{key}{sep}{dv}'
                PATTERNS.append((pat.encode('utf-8'), key, iso, dv))
    d += timedelta(days=1)


def format_time(seconds):
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds // 60:.0f}m {seconds % 60:.0f}s"
    else:
        return f"{seconds // 3600:.0f}h {(seconds % 3600) // 60:.0f}m"


def extract_json_around(raw_bytes, match_pos, window=20000):
    """Try to extract a complete JSON object around the match."""
    start = max(0, match_pos - window)
    end = min(len(raw_bytes), match_pos + window)
    region = raw_bytes[start:end]
    try:
        text = region.decode('utf-8', errors='replace').replace('\x00', '')
    except:
        return None

    rel_pos = match_pos - start
    # Walk backwards for opening brace
    depth = 0
    json_start = None
    for i in range(rel_pos, -1, -1):
        if text[i] == '}':
            depth += 1
        elif text[i] == '{':
            if depth == 0:
                json_start = i
                break
            depth -= 1
    if json_start is None:
        return None

    # Walk forwards for matching close
    depth = 0
    for i in range(json_start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                candidate = text[json_start:i + 1]
                try:
                    return json.loads(candidate)
                except:
                    pass
                break
    return None


def extract_context(raw_bytes, match_pos, window=3000):
    """Get readable text snippet around match."""
    start = max(0, match_pos - window)
    end = min(len(raw_bytes), match_pos + window)
    try:
        text = raw_bytes[start:end].decode('utf-8', errors='replace').replace('\x00', '')
    except:
        return {}

    names = re.findall(r'\b([A-Z][a-z]{1,15} [A-Z][a-z]{1,15})\b', text)
    # Grab a tight snippet around the match
    rel = match_pos - start
    snip_start = max(0, rel - 200)
    snip_end = min(len(text), rel + 300)
    return {
        'names': list(dict.fromkeys(names))[:10],
        'snippet': text[snip_start:snip_end].strip()[:500],
    }


def main():
    print("=" * 90)
    print("  DATE-STARTED RESCUE SCAN — March 26 → April 2, 2026")
    print(f"  RUN: {datetime.now()}")
    print("=" * 90)

    if not os.path.exists(NFS_FILE):
        print(f"\n  FATAL: NFS file gone: {NFS_FILE}")
        sys.exit(1)

    file_size = os.path.getsize(NFS_FILE)
    total_chunks = (file_size // CHUNK_SIZE) + 1

    print(f"\n  File: {os.path.basename(NFS_FILE)}  ({file_size / 1024**3:.1f} GB)")
    print(f"  Patterns: {len(PATTERNS)}  ({len(DATE_KEYS)} keys × date variants × 2 spacings)")
    print(f"  Chunks: ~{total_chunks} × 10 MB")
    print()

    all_finds = []
    seen_offsets = set()          # deduplicate overlapping-chunk hits
    by_date = {}                  # iso_date -> count
    by_key  = {}                  # key_name -> count
    errors  = 0
    start_time = time.time()
    bytes_read = 0

    try:
        with open(NFS_FILE, 'rb') as f:
            chunk_num = 0
            offset = 0

            while offset < file_size:
                chunk_num += 1
                try:
                    f.seek(offset)
                    chunk = f.read(CHUNK_SIZE + OVERLAP)
                    if not chunk:
                        break
                    bytes_read += len(chunk)
                except IOError as e:
                    errors += 1
                    if errors <= 10:
                        print(f"  [I/O] {offset / 1024**3:.2f} GB: {e}")
                    offset += CHUNK_SIZE
                    continue

                for pat_bytes, key_name, iso_date, date_val in PATTERNS:
                    pos = 0
                    while True:
                        idx = chunk.find(pat_bytes, pos)
                        if idx == -1:
                            break
                        pos = idx + 1

                        abs_off = offset + idx
                        # Deduplicate (overlap region can re-find same hit)
                        bucket = abs_off // 100
                        if bucket in seen_offsets:
                            continue
                        seen_offsets.add(bucket)

                        ctx = extract_context(chunk, idx)
                        json_obj = extract_json_around(chunk, idx)

                        record = {
                            'offset': abs_off,
                            'offset_gb': round(abs_off / 1024**3, 3),
                            'key': key_name,
                            'date_value': date_val,
                            'iso_date': iso_date,
                            'names': ctx.get('names', []),
                            'snippet': ctx.get('snippet', ''),
                            'json_extracted': json_obj is not None,
                            'json_data': json_obj,
                        }
                        all_finds.append(record)
                        by_date[iso_date] = by_date.get(iso_date, 0) + 1
                        by_key[key_name]  = by_key.get(key_name, 0) + 1

                # Progress every 50 chunks
                if chunk_num % 50 == 0:
                    elapsed = time.time() - start_time
                    prog = offset / file_size
                    eta = elapsed / prog * (1 - prog) if prog > 0 else 0
                    date_summary = ' | '.join(f"{d}: {by_date[d]}" for d in sorted(by_date))
                    if not date_summary:
                        date_summary = "none yet"
                    print(
                        f"  [{offset / 1024**3:5.1f}/{file_size / 1024**3:.1f} GB] "
                        f"{prog * 100:5.1f}%  "
                        f"Elapsed: {format_time(elapsed)}  "
                        f"ETA: {format_time(eta)}  "
                        f"Hits: {len(all_finds)}  "
                        f"| {date_summary}"
                    )

                offset += CHUNK_SIZE

    except KeyboardInterrupt:
        print("\n  [INTERRUPTED] Saving partial results...")
    except Exception as e:
        print(f"\n  [FATAL] {e}")

    elapsed = time.time() - start_time
    print()
    print("=" * 90)
    print(f"  COMPLETE — {format_time(elapsed)}")
    print(f"  Scanned: {bytes_read / 1024**3:.1f} GB  |  I/O errors: {errors}")
    print(f"  Total hits: {len(all_finds)}")
    print()

    print("  HITS BY DATE:")
    d = START
    while d <= END:
        iso = d.strftime('%Y-%m-%d')
        c = by_date.get(iso, 0)
        bar = "#" * min(c, 60)
        print(f"    {iso}: {c:>5}  {bar}")
        d += timedelta(days=1)

    print(f"\n  HITS BY KEY:")
    for k, c in sorted(by_key.items(), key=lambda x: -x[1]):
        print(f"    {k}: {c}")

    # Unique client names
    all_names = set()
    for rec in all_finds:
        for n in rec.get('names', []):
            all_names.add(n)
    if all_names:
        print(f"\n  CLIENT NAMES ({len(all_names)}):")
        for n in sorted(all_names):
            print(f"    {n}")

    # JSON-extractable records
    json_recs = [r for r in all_finds if r.get('json_extracted')]
    print(f"\n  RECORDS WITH JSON: {len(json_recs)}")
    for rec in json_recs[:30]:
        names = ', '.join(rec['names'][:3]) if rec['names'] else '?'
        print(f"    {rec['iso_date']} | {rec['key']} = {rec['date_value']} | {names} | {rec['offset_gb']:.3f} GB")

    # Save
    try:
        with open(OUTPUT_JSON, 'w') as out:
            json.dump({
                'run_timestamp': datetime.now().isoformat(),
                'file_scanned': NFS_FILE,
                'file_size_gb': round(file_size / 1024**3, 2),
                'elapsed_seconds': round(elapsed, 1),
                'total_hits': len(all_finds),
                'by_date': by_date,
                'by_key': by_key,
                'unique_names': sorted(all_names),
                'json_extractable': len(json_recs),
                'records': all_finds,
            }, out, indent=2, default=str)
        print(f"\n  Saved: {OUTPUT_JSON}")
    except Exception as e:
        print(f"\n  Save error: {e}")

    print("=" * 90)


if __name__ == '__main__':
    main()
