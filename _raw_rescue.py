#!/usr/bin/env python3
"""
RAW BINARY RESCUE — bypasses SQLite entirely.
Reads corrupt files as raw bytes and extracts client data by scanning for JSON patterns.

For .nfs file with "disk I/O error": tries raw read at various offsets
For .nfs file with "not a database": fixes SQLite header and retries, or scans raw

Run on PythonAnywhere: python3 _raw_rescue.py
"""
import os, sys, json, struct, re, sqlite3
from datetime import datetime

DASH_DIR = os.path.expanduser('~/MT5Dashboard/dashboard')
CUR_DB   = os.path.join(DASH_DIR, 'dashboard.db')

BIG_NFS   = os.path.join(DASH_DIR, '.nfs0000000004802cdb0000de98')   # 48.1 GB, disk I/O
SMALL_NFS = os.path.join(DASH_DIR, '.nfs00000000048053f600025d72')    # 19.7 GB, not a db
BACKUP    = os.path.join(DASH_DIR, 'dashboard.db.backup_20260311_103843')  # 9.7 GB

# SQLite header magic
SQLITE_MAGIC = b'SQLite format 3\x00'

# ──────────────────────────────────────────────────────────────────
# APPROACH 1: Try to fix the "not a database" file by writing correct header
# ──────────────────────────────────────────────────────────────────
def try_fix_header(filepath):
    """Check if the file has a corrupted header. If so, create a fixed copy header."""
    print(f"\n  Checking header of {os.path.basename(filepath)}...")
    try:
        with open(filepath, 'rb') as f:
            header = f.read(100)
        
        print(f"  First 16 bytes: {header[:16]}")
        print(f"  First 16 hex:   {header[:16].hex()}")
        
        if header[:16] == SQLITE_MAGIC:
            print("  Header looks valid — corruption is in data pages")
            return False
        
        # Check if it might be a WAL file
        WAL_MAGIC = b'\x37\x7f\x06\x82'  # Big-endian
        WAL_MAGIC2 = b'\x37\x7f\x06\x83'
        if header[:4] in (WAL_MAGIC, WAL_MAGIC2):
            print("  THIS IS A WAL (Write-Ahead Log) FILE — contains the freshest data!")
            return 'WAL'
        
        # Try to detect page size from later in the file
        # Standard SQLite header at bytes 16-17 is page size
        page_size_raw = struct.unpack('>H', header[16:18])[0]
        print(f"  Detected page size field: {page_size_raw}")
        
        # Check if it's just the first few bytes that are bad
        # Look for SQLite-like data structure deeper in the file
        with open(filepath, 'rb') as f:
            # Try reading at page boundaries (4096, 8192, etc)
            for offset in [4096, 8192, 16384, 32768, 65536]:
                f.seek(offset)
                page = f.read(4096)
                # B-tree leaf page starts with 0x0D, interior with 0x05
                if page and page[0] in (0x05, 0x0D, 0x02, 0x0A):
                    print(f"  Found valid B-tree page at offset {offset} (type={hex(page[0])})")
        
        return True  # Header is bad but file may have data
    except Exception as e:
        print(f"  Error reading header: {e}")
        return False

# ──────────────────────────────────────────────────────────────────
# APPROACH 2: Try to read file raw and check if it's accessible
# ──────────────────────────────────────────────────────────────────
def check_raw_readable(filepath):
    """Check if we can read the file at all, at various offsets."""
    fn = os.path.basename(filepath)
    print(f"\n  Testing raw read access to {fn}...")
    
    try:
        fsize = os.path.getsize(filepath)
        print(f"  File size: {fsize/1024/1024/1024:.2f} GB")
    except Exception as e:
        print(f"  Cannot stat file: {e}")
        return False
    
    readable_ranges = []
    unreadable_ranges = []
    
    # Test reads at various offsets
    test_offsets = [0, 4096, 1024*1024, 10*1024*1024, 100*1024*1024, 
                    500*1024*1024, 1024*1024*1024, 5*1024*1024*1024,
                    10*1024*1024*1024, 20*1024*1024*1024, 40*1024*1024*1024]
    
    with open(filepath, 'rb') as f:
        for offset in test_offsets:
            if offset >= fsize:
                continue
            try:
                f.seek(offset)
                data = f.read(4096)
                if data:
                    readable_ranges.append(offset)
                    if offset == 0:
                        print(f"    Offset {offset:>15,}: READABLE — first bytes: {data[:20].hex()}")
                    else:
                        print(f"    Offset {offset:>15,}: READABLE ({len(data)} bytes)")
                else:
                    unreadable_ranges.append(offset)
                    print(f"    Offset {offset:>15,}: EMPTY")
            except Exception as e:
                unreadable_ranges.append(offset)
                print(f"    Offset {offset:>15,}: FAILED — {e}")
    
    if readable_ranges:
        print(f"  FILE IS PARTIALLY READABLE — {len(readable_ranges)} of {len(readable_ranges)+len(unreadable_ranges)} test offsets")
        return True
    else:
        print(f"  FILE IS COMPLETELY UNREADABLE")
        return False

# ──────────────────────────────────────────────────────────────────
# APPROACH 3: Scan raw bytes for JSON client data
# ──────────────────────────────────────────────────────────────────
def scan_for_client_data(filepath, max_gb=None):
    """Scan raw file bytes for JSON blobs containing client data."""
    fn = os.path.basename(filepath)
    fsize = os.path.getsize(filepath)
    
    if max_gb:
        scan_limit = min(fsize, int(max_gb * 1024*1024*1024))
    else:
        scan_limit = fsize
    
    print(f"\n  Scanning {fn} for client data patterns ({scan_limit/1024/1024/1024:.1f} GB)...")
    
    # Patterns to search for — unique strings that only appear in client data
    # We look for evaluation date patterns from Apr 2 (today)
    patterns = [
        b'"Date Purchased": "2026-04-02',
        b'"Date Purchased":"2026-04-02',
        b'"Date Started": "2026-04-02',
        b'"Date Started":"2026-04-02',
        b'"Date Purchased": "04/02/26',
        b'"Date Purchased": "4/2/26',
        b'"Date Started": "04/02/',
        b'"Date Started": "4/2/',
        # Also April 1 and March 31 (recent)
        b'"Date Purchased": "2026-04-01',
        b'"Date Purchased": "2026-03-31',
        b'"Date Purchased": "2026-03-30',
        b'"Date Purchased": "2026-03-29',
        b'"Date Purchased": "2026-03-28',
        b'"Date Purchased": "2026-03-27',
        b'"Date Purchased": "2026-03-26',
        b'"Date Purchased": "2026-03-25',
    ]
    
    CHUNK_SIZE = 10 * 1024 * 1024  # 10MB chunks
    OVERLAP = 1024  # overlap between chunks to catch data at boundaries
    
    found_records = {}
    errors = 0
    chunks_read = 0
    offset = 0
    
    try:
        with open(filepath, 'rb') as f:
            while offset < scan_limit:
                try:
                    f.seek(offset)
                    chunk = f.read(CHUNK_SIZE + OVERLAP)
                    if not chunk:
                        break
                    chunks_read += 1
                    
                    for pattern in patterns:
                        pos = 0
                        while True:
                            idx = chunk.find(pattern, pos)
                            if idx == -1:
                                break
                            pos = idx + 1
                            
                            # Try to extract the full JSON record around this match
                            # Go back to find the start of the JSON object
                            start = max(0, idx - 5000)
                            end = min(len(chunk), idx + 50000)
                            context = chunk[start:end]
                            
                            # Try to find client_id nearby
                            try:
                                text = context.decode('utf-8', errors='replace')
                                # Look for the date value
                                date_match = pattern.decode('utf-8')
                                abs_offset = offset + idx
                                
                                # Extract the date
                                date_key = date_match.split('"')[1]  # e.g. "Date Purchased"
                                
                                # Try to find a client identifier nearby
                                # Client IDs are usually stored as the key in a row
                                # Look for common name patterns
                                name_patterns = re.findall(r'[A-Z][a-z]+ [A-Z][a-z]+', text[:500])
                                
                                record_key = f"offset_{abs_offset}"
                                if name_patterns:
                                    record_key = name_patterns[0]
                                
                                if record_key not in found_records:
                                    found_records[record_key] = {
                                        'offset': abs_offset,
                                        'date_key': date_key,
                                        'date_found': date_match,
                                        'nearby_names': name_patterns[:5] if name_patterns else [],
                                        'context_snippet': text[idx-start:idx-start+200].replace('\x00', '').strip()
                                    }
                            except:
                                pass
                    
                    # Progress
                    if chunks_read % 100 == 0:
                        pct = offset / scan_limit * 100
                        print(f"    Progress: {pct:.1f}% ({offset/1024/1024/1024:.1f} GB) — found {len(found_records)} records so far, {errors} read errors")
                    
                    offset += CHUNK_SIZE
                    
                except IOError as e:
                    errors += 1
                    if errors <= 5:
                        print(f"    I/O error at offset {offset/1024/1024:.1f} MB: {e}")
                    elif errors == 6:
                        print(f"    (suppressing further I/O errors...)")
                    offset += CHUNK_SIZE  # Skip this chunk
                    continue
                    
    except Exception as e:
        print(f"  Fatal error: {e}")
    
    print(f"\n  Scan complete: read {chunks_read} chunks, {errors} errors, found {len(found_records)} records with recent dates")
    
    return found_records

# ──────────────────────────────────────────────────────────────────
# APPROACH 4: Try connecting with various PRAGMA options
# ──────────────────────────────────────────────────────────────────
def try_sqlite_recovery(filepath):
    """Try various SQLite recovery techniques."""
    fn = os.path.basename(filepath)
    print(f"\n  Trying SQLite recovery on {fn}...")
    
    methods = [
        # Method 1: Read-only with journal_mode OFF
        lambda: sqlite3.connect(f'file:{filepath}?mode=ro&nolock=1', uri=True),
        # Method 2: immutable mode
        lambda: sqlite3.connect(f'file:{filepath}?immutable=1', uri=True),
        # Method 3: regular with timeout
        lambda: sqlite3.connect(filepath, timeout=30),
    ]
    
    for i, method in enumerate(methods):
        try:
            conn = method()
            conn.execute("PRAGMA journal_mode=OFF")
            conn.execute("PRAGMA locking_mode=NORMAL")
            
            # Try to read tables
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = [t[0] for t in tables]
            print(f"  Method {i+1}: SUCCESS — tables: {table_names}")
            
            # Try clients_data
            if 'clients_data' in table_names:
                try:
                    count = conn.execute("SELECT COUNT(*) FROM clients_data").fetchone()[0]
                    print(f"  clients_data has {count} rows")
                    
                    # Try to read each row individually
                    for rid in range(1, count + 5):
                        try:
                            row = conn.execute("SELECT client_id FROM clients_data WHERE rowid=?", (rid,)).fetchone()
                            if row:
                                print(f"    rowid {rid}: {row[0]}")
                        except Exception as e:
                            print(f"    rowid {rid}: Error - {e}")
                            if 'malformed' in str(e) or 'corrupt' in str(e):
                                break
                except Exception as e:
                    print(f"  Error reading clients_data: {e}")
            
            # Try audit_log for today
            if 'audit_log' in table_names:
                try:
                    rows = conn.execute("""
                        SELECT timestamp, action, details FROM audit_log 
                        WHERE timestamp LIKE '2026-04-02%'
                        ORDER BY timestamp DESC LIMIT 10
                    """).fetchall()
                    print(f"  Today's audit entries: {len(rows)}")
                    for r in rows:
                        print(f"    {r[0]} | {r[1]} | {str(r[2])[:60]}")
                except Exception as e:
                    print(f"  Error reading audit_log: {e}")
            
            conn.close()
            return True
            
        except Exception as e:
            print(f"  Method {i+1}: {e}")
    
    return False

# ──────────────────────────────────────────────────────────────────
# APPROACH 5: For "not a database" — check if it's a WAL file
# ──────────────────────────────────────────────────────────────────
def try_wal_extraction(filepath):
    """Check if file is a WAL and extract data from it."""
    fn = os.path.basename(filepath)
    print(f"\n  Checking if {fn} is a WAL file...")
    
    try:
        with open(filepath, 'rb') as f:
            header = f.read(32)
        
        magic = struct.unpack('>I', header[0:4])[0]
        if magic in (0x377f0682, 0x377f0683):
            print("  ** THIS IS A WAL FILE! **")
            file_format = struct.unpack('>I', header[4:8])[0]
            page_size = struct.unpack('>I', header[8:12])[0]
            checkpoint_seq = struct.unpack('>I', header[12:16])[0]
            salt1 = struct.unpack('>I', header[16:20])[0]
            salt2 = struct.unpack('>I', header[20:24])[0]
            checksum1 = struct.unpack('>I', header[24:28])[0]
            checksum2 = struct.unpack('>I', header[28:32])[0]
            
            print(f"  Page size: {page_size}")
            print(f"  Checkpoint sequence: {checkpoint_seq}")
            print(f"  This WAL contains uncommitted/recent writes — the freshest data!")
            
            # WAL frame format: 24 bytes header + page_size bytes of data
            # Frame header: page number (4), commit size (4), salt1 (4), salt2 (4), checksum1 (4), checksum2 (4)
            frame_size = 24 + page_size
            fsize = os.path.getsize(filepath)
            num_frames = (fsize - 32) // frame_size
            print(f"  Estimated frames: {num_frames}")
            
            # Read frames and look for client data
            found_data = []
            with open(filepath, 'rb') as f:
                f.seek(32)  # Skip WAL header
                for frame_idx in range(min(num_frames, 100000)):  # Cap at 100k frames
                    try:
                        frame_header = f.read(24)
                        if len(frame_header) < 24:
                            break
                        page_num = struct.unpack('>I', frame_header[0:4])[0]
                        page_data = f.read(page_size)
                        if len(page_data) < page_size:
                            break
                        
                        # Check if page contains client data (JSON patterns)
                        if b'"evaluations"' in page_data or b'"identity"' in page_data or b'"Date Purchased"' in page_data:
                            text = page_data.decode('utf-8', errors='replace')
                            # Check for today's date
                            if '2026-04-02' in text or '2026-04-01' in text or '04/02' in text:
                                found_data.append({
                                    'frame': frame_idx,
                                    'page_num': page_num,
                                    'snippet': text[:500].replace('\x00', '')
                                })
                                if len(found_data) <= 10:
                                    print(f"    Frame {frame_idx}, page {page_num}: FOUND today's data!")
                                    print(f"      {text[:200].replace(chr(0), '')}")
                    except Exception as e:
                        if frame_idx < 5:
                            print(f"    Frame {frame_idx}: Error - {e}")
                        continue
            
            print(f"\n  Total frames with today's data: {len(found_data)}")
            return found_data
        else:
            print(f"  Not a WAL file (magic: {hex(magic)})")
            # Check what the file actually is
            with open(filepath, 'rb') as f:
                first_bytes = f.read(100)
            print(f"  First 32 bytes hex: {first_bytes[:32].hex()}")
            print(f"  First 16 bytes raw: {first_bytes[:16]}")
            
            # Could be a journal file
            JOURNAL_MAGIC = b'\xd9\xd5\x05\xf9\x20\xa1\x63\xd7'
            if first_bytes[:8] == JOURNAL_MAGIC:
                print("  ** THIS IS A ROLLBACK JOURNAL FILE! **")
                return 'JOURNAL'
            
            return None
    except Exception as e:
        print(f"  Error: {e}")
        return None


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════
print("=" * 90)
print("RAW BINARY DATA RESCUE")
print(f"Time: {datetime.now()}")
print("=" * 90)

files_to_check = [
    (BIG_NFS, "48GB corrupt (was main DB)"),
    (SMALL_NFS, "19.7GB (unknown type)"),
]

for filepath, desc in files_to_check:
    fn = os.path.basename(filepath)
    if not os.path.exists(filepath):
        print(f"\n{'='*90}")
        print(f"SKIP: {fn} — file does not exist")
        continue
    
    print(f"\n{'='*90}")
    print(f"FILE: {fn}  —  {desc}")
    print(f"Size: {os.path.getsize(filepath)/1024/1024/1024:.2f} GB")
    print(f"{'='*90}")
    
    # Step 1: Check if file is readable at all
    readable = check_raw_readable(filepath)
    
    if not readable:
        print(f"\n  FILE IS DEAD — cannot read any bytes. NFS handle has expired.")
        continue
    
    # Step 2: Check header / file type
    header_result = try_fix_header(filepath)
    
    # Step 3: Check if it's a WAL file
    if header_result == 'WAL' or header_result is True:
        wal_data = try_wal_extraction(filepath)
        if wal_data and isinstance(wal_data, list) and len(wal_data) > 0:
            print(f"\n  ** WAL CONTAINS {len(wal_data)} FRAMES WITH TODAY'S DATA **")
            print(f"  This is recoverable! Running detailed extraction...")
    
    # Step 4: Try SQLite with various methods
    try_sqlite_recovery(filepath)
    
    # Step 5: Raw byte scan for JSON data (scan first 5GB to save time)
    print(f"\n  Starting raw byte scan (first 5 GB)...")
    records = scan_for_client_data(filepath, max_gb=5)
    
    if records:
        print(f"\n  *** FOUND {len(records)} RECORDS WITH RECENT DATES ***")
        for key, rec in sorted(records.items())[:20]:
            print(f"    {key}: {rec['date_found']} at offset {rec['offset']}")
            if rec['nearby_names']:
                print(f"      Nearby names: {rec['nearby_names']}")
            print(f"      Context: {rec['context_snippet'][:150]}")
    else:
        print(f"\n  No recent data found in first 5 GB. Try scanning more? (rerun with larger limit)")

# Also check the backup
print(f"\n{'='*90}")
print(f"BACKUP: {os.path.basename(BACKUP)}")
print(f"{'='*90}")
if os.path.exists(BACKUP):
    try_sqlite_recovery(BACKUP)
else:
    print("  File not found")

print(f"\n{'='*90}")
print("RESCUE COMPLETE")
print(f"{'='*90}")
