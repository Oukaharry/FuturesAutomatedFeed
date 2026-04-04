#!/usr/bin/env python3
"""
TARGETED DATA RESCUE — Scan corrupt 48GB NFS file for data between March 25 and April 2, 2026.

READ-ONLY: Only reads the NFS file as raw bytes. Does NOT touch dashboard.db.
Outputs: _rescue_results.json with all found records.

Run on PythonAnywhere:
    python3 _rescue_missing_data.py 2>&1 | tee _rescue_log.txt

Or background:
    python3 _rescue_missing_data.py > _rescue_log.txt 2>&1 &
    tail -f _rescue_log.txt
"""
import os, sys, json, re, time
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────────────────
NFS_FILE = os.path.expanduser('~/MT5Dashboard/dashboard/.nfs0000000004802cdb0000de98')
OUTPUT_JSON = os.path.expanduser('~/MT5Dashboard/_rescue_results.json')
CHUNK_SIZE = 10 * 1024 * 1024   # 10 MB per read
OVERLAP = 50_000                 # 50 KB overlap between chunks (catch records at boundaries)

# Target dates: March 25 through April 2
TARGET_DATES = [
    '2026-03-25', '2026-03-26', '2026-03-27', '2026-03-28',
    '2026-03-29', '2026-03-30', '2026-03-31',
    '2026-04-01', '2026-04-02',
]

# Build byte patterns to search for
PATTERNS = []
for d in TARGET_DATES:
    PATTERNS.append(d.encode('utf-8'))  # ISO format: 2026-03-26

# Also search for common date formats used in evaluations
for d in TARGET_DATES:
    dt = datetime.strptime(d, '%Y-%m-%d')
    PATTERNS.append(dt.strftime('%m/%d/%y').encode('utf-8'))   # 03/26/26
    PATTERNS.append(dt.strftime('%-m/%-d/%y').encode('utf-8') if os.name != 'nt' else
                    dt.strftime('%m/%d/%y').lstrip('0').replace('/0', '/').encode('utf-8'))  # 3/26/26


def format_time(seconds):
    """Format seconds into human-readable string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds // 60:.0f}m {seconds % 60:.0f}s"
    else:
        return f"{seconds // 3600:.0f}h {(seconds % 3600) // 60:.0f}m"


def extract_json_around(raw_bytes, match_pos, window=20000):
    """Try to extract a complete JSON object around a match position."""
    start = max(0, match_pos - window)
    end = min(len(raw_bytes), match_pos + window)
    region = raw_bytes[start:end]

    try:
        text = region.decode('utf-8', errors='replace')
    except:
        return None

    # Try to find JSON object boundaries around the match
    rel_pos = match_pos - start
    results = []

    # Look backwards for opening brace
    brace_depth = 0
    json_start = None
    for i in range(rel_pos, -1, -1):
        if text[i] == '}':
            brace_depth += 1
        elif text[i] == '{':
            if brace_depth == 0:
                json_start = i
                break
            brace_depth -= 1

    if json_start is not None:
        # Look forwards for matching closing brace
        brace_depth = 0
        for i in range(json_start, len(text)):
            if text[i] == '{':
                brace_depth += 1
            elif text[i] == '}':
                brace_depth -= 1
                if brace_depth == 0:
                    candidate = text[json_start:i + 1]
                    # Clean null bytes
                    candidate = candidate.replace('\x00', '')
                    try:
                        obj = json.loads(candidate)
                        return obj
                    except:
                        # Try a smaller window
                        pass
                    break

    return None


def find_client_context(raw_bytes, match_pos, window=5000):
    """Extract readable text around the match to identify client and data."""
    start = max(0, match_pos - window)
    end = min(len(raw_bytes), match_pos + window)
    region = raw_bytes[start:end]

    try:
        text = region.decode('utf-8', errors='replace').replace('\x00', '')
    except:
        return None, None

    # Find client names (capitalized two-word names)
    names = re.findall(r'\b([A-Z][a-z]{1,15} [A-Z][a-z]{1,15})\b', text)

    # Find all dates in the region
    dates = re.findall(r'2026-(?:03-2[5-9]|03-3[01]|04-0[12])', text)

    # Extract a meaningful snippet around the match
    rel_pos = match_pos - start
    snippet_start = max(0, rel_pos - 200)
    snippet_end = min(len(text), rel_pos + 300)
    snippet = text[snippet_start:snippet_end].strip()

    return {
        'nearby_names': list(dict.fromkeys(names))[:10],  # unique, preserve order
        'dates_found': list(dict.fromkeys(dates)),
        'snippet': snippet,
    }, text


def main():
    print("=" * 90)
    print("  TARGETED DATA RESCUE — March 25 to April 2, 2026")
    print(f"  RUN: {datetime.now()}")
    print("=" * 90)

    if not os.path.exists(NFS_FILE):
        print(f"\n  FATAL: NFS file not found: {NFS_FILE}")
        print("  The file handle may have expired. Data is unrecoverable.")
        sys.exit(1)

    file_size = os.path.getsize(NFS_FILE)
    total_chunks = (file_size // CHUNK_SIZE) + 1

    print(f"\n  File: {os.path.basename(NFS_FILE)}")
    print(f"  Size: {file_size / 1024**3:.1f} GB")
    print(f"  Chunks: ~{total_chunks} × 10 MB")
    print(f"  Searching for dates: {TARGET_DATES[0]} through {TARGET_DATES[-1]}")
    print(f"  Patterns: {len(PATTERNS)} byte patterns")
    print()

    all_finds = []
    found_by_date = {d: 0 for d in TARGET_DATES}
    errors = 0
    start_time = time.time()
    bytes_read = 0

    try:
        with open(NFS_FILE, 'rb') as f:
            chunk_num = 0
            offset = 0

            while offset < file_size:
                chunk_num += 1

                # Read chunk with overlap
                try:
                    f.seek(offset)
                    chunk = f.read(CHUNK_SIZE + OVERLAP)
                    if not chunk:
                        break
                    bytes_read += len(chunk)
                except IOError as e:
                    errors += 1
                    if errors <= 10:
                        print(f"  [I/O ERROR] Offset {offset / 1024**3:.2f} GB: {e}")
                    elif errors == 11:
                        print(f"  (suppressing further I/O errors...)")
                    offset += CHUNK_SIZE
                    continue

                # Search for patterns
                for pattern in PATTERNS:
                    pos = 0
                    while True:
                        idx = chunk.find(pattern, pos)
                        if idx == -1:
                            break
                        pos = idx + 1

                        abs_offset = offset + idx
                        date_str = pattern.decode('utf-8', errors='replace')

                        # Match to ISO date
                        iso_date = None
                        for d in TARGET_DATES:
                            if d in date_str or date_str in d:
                                iso_date = d
                                break

                        # Extract context
                        context, raw_text = find_client_context(chunk, idx)
                        if context is None:
                            continue

                        # Try to extract JSON object
                        json_obj = extract_json_around(chunk, idx)

                        record = {
                            'offset': abs_offset,
                            'offset_gb': round(abs_offset / 1024**3, 3),
                            'date_matched': date_str,
                            'iso_date': iso_date,
                            'names': context['nearby_names'],
                            'dates_in_region': context['dates_found'],
                            'snippet': context['snippet'][:500],
                            'json_extracted': json_obj is not None,
                            'json_data': json_obj,
                        }
                        all_finds.append(record)

                        if iso_date and iso_date in found_by_date:
                            found_by_date[iso_date] += 1

                # Progress report every 50 chunks (~500 MB)
                if chunk_num % 50 == 0:
                    elapsed = time.time() - start_time
                    progress = offset / file_size
                    if progress > 0:
                        eta = elapsed / progress * (1 - progress)
                    else:
                        eta = 0
                    gb_done = offset / 1024**3
                    gb_total = file_size / 1024**3

                    date_summary = ' | '.join(f"{d[-5:]}: {c}" for d, c in found_by_date.items() if c > 0)
                    if not date_summary:
                        date_summary = "none yet"

                    print(
                        f"  [{gb_done:5.1f}/{gb_total:.1f} GB] "
                        f"{progress * 100:5.1f}%  "
                        f"Elapsed: {format_time(elapsed)}  "
                        f"ETA: {format_time(eta)}  "
                        f"Found: {len(all_finds)}  "
                        f"Errors: {errors}  "
                        f"| {date_summary}"
                    )

                offset += CHUNK_SIZE

    except KeyboardInterrupt:
        print(f"\n  [INTERRUPTED] Saving partial results...")
    except Exception as e:
        print(f"\n  [FATAL ERROR] {e}")

    # ── Results ─────────────────────────────────────────────────
    elapsed = time.time() - start_time
    print()
    print("=" * 90)
    print(f"  SCAN COMPLETE — {format_time(elapsed)} elapsed")
    print(f"  Scanned: {bytes_read / 1024**3:.1f} GB of {file_size / 1024**3:.1f} GB")
    print(f"  I/O Errors: {errors}")
    print(f"  Total matches: {len(all_finds)}")
    print()

    print("  MATCHES BY DATE:")
    for d in TARGET_DATES:
        count = found_by_date.get(d, 0)
        bar = "#" * min(count, 50)
        print(f"    {d}: {count:>5} hits  {bar}")

    # Show unique client names found
    all_names = set()
    for rec in all_finds:
        for name in rec.get('names', []):
            all_names.add(name)

    if all_names:
        print(f"\n  UNIQUE CLIENT NAMES FOUND ({len(all_names)}):")
        for name in sorted(all_names):
            print(f"    {name}")

    # Show records with JSON data extracted
    json_records = [r for r in all_finds if r.get('json_extracted')]
    print(f"\n  RECORDS WITH EXTRACTABLE JSON: {len(json_records)}")
    for rec in json_records[:20]:
        names = ', '.join(rec['names'][:3]) if rec['names'] else '?'
        print(f"    {rec['iso_date']} | {names} | offset {rec['offset_gb']:.3f} GB")

    # Save all results to JSON
    try:
        with open(OUTPUT_JSON, 'w') as f:
            json.dump({
                'run_timestamp': datetime.now().isoformat(),
                'file_scanned': NFS_FILE,
                'file_size_gb': round(file_size / 1024**3, 2),
                'elapsed_seconds': round(elapsed, 1),
                'total_matches': len(all_finds),
                'matches_by_date': found_by_date,
                'unique_names': sorted(all_names),
                'json_extractable': len(json_records),
                'records': all_finds,
            }, f, indent=2, default=str)
        print(f"\n  Results saved to: {OUTPUT_JSON}")
    except Exception as e:
        print(f"\n  Error saving results: {e}")

    print()
    print("=" * 90)
    if len(json_records) > 0:
        print("  DATA FOUND! Review _rescue_results.json then run recovery merge.")
    elif len(all_finds) > 0:
        print("  Date patterns found but no clean JSON extracted.")
        print("  Review _rescue_results.json — snippets may still be usable.")
    else:
        print("  NO DATA FOUND for the target date range.")
        print("  The data_history writes may have been to pages that are fully corrupted.")
    print("=" * 90)


if __name__ == '__main__':
    main()
