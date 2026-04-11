import json
import os
import sys

LOW, HIGH = 2000, 2999

# ---------------------------------------------------------------------------
# Load DATABASE_URL from .env if present
# ---------------------------------------------------------------------------
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path, encoding="utf-8", errors="replace") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL or DATABASE_URL.startswith("sqlite"):
    print("ERROR: Set DATABASE_URL to your PostgreSQL connection string in .env", file=sys.stderr)
    print("  Example: DATABASE_URL=postgresql://user:pass@localhost:5432/mt5_dashboard", file=sys.stderr)
    sys.exit(1)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)

def parse_num(val):
    """Return float if val is numeric-ish, else None."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = val.replace(",", "").replace("$", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

cur.execute("SELECT client_id, identity, evaluations FROM clients_data")
rows = cur.fetchall()
cur.close()
conn.close()

results = []

for row in rows:
    client_id = row["client_id"]

    # Resolve display name from identity JSON
    try:
        identity = json.loads(row["identity"] or "{}")
        client_name = (
            identity.get("name")
            or identity.get("client")
            or identity.get("display_name")
            or client_id
        )
    except (json.JSONDecodeError, TypeError):
        client_name = client_id

    # Parse evaluations list
    try:
        evaluations = json.loads(row["evaluations"] or "[]")
    except (json.JSONDecodeError, TypeError):
        evaluations = []

    for row_idx, ev in enumerate(evaluations):
        if not isinstance(ev, dict):
            continue
        for col, raw_val in ev.items():
            # Skip payout-related columns
            col_lower = col.lower()
            if any(k in col_lower for k in ("payout", "payment", "withdraw", "disburs", "hedge net")):
                continue
            num = parse_num(raw_val)
            if num is not None and LOW <= num <= HIGH:
                results.append({
                    "client_name": client_name,
                    "client_id": client_id,
                    "row": row_idx,
                    "column": col,
                    "value": num,
                    "raw_value": raw_val,
                })

# ---------------------------------------------------------------------------
# Group results by client
# ---------------------------------------------------------------------------
from collections import defaultdict
grouped = defaultdict(list)
for r in results:
    grouped[(r["client_name"], r["client_id"])].append(r)

total = len(results)
client_count = len(grouped)

# ---------------------------------------------------------------------------
# Build HTML
# ---------------------------------------------------------------------------
rows_html = ""
for (client_name, client_id), matches in sorted(grouped.items(), key=lambda x: x[0][0].lower()):
    row_count = len(matches)
    rows_html += f"""
      <tr class="client-header">
        <td colspan="3" class="client-name">{client_name} <span class="badge">{row_count} match{'es' if row_count != 1 else ''}</span></td>
      </tr>"""
    for m in matches:
        rows_html += f"""
      <tr>
        <td class="col-row">Row {m['row']}</td>
        <td class="col-col">{m['column']}</td>
        <td class="col-val">{m['raw_value']}</td>
      </tr>"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Values between {LOW} and {HIGH}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0a0f1e; color: #e2e8f0; font-family: 'Segoe UI', sans-serif; padding: 32px; }}
    h1 {{ font-size: 1.4rem; font-weight: 600; color: #60a5fa; margin-bottom: 6px; }}
    .subtitle {{ font-size: 0.85rem; color: #64748b; margin-bottom: 28px; }}
    .subtitle span {{ color: #94a3b8; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th {{ background: #0d1628; color: #94a3b8; text-transform: uppercase;
          font-size: 0.72rem; letter-spacing: 0.08em; padding: 10px 14px;
          border-bottom: 1px solid rgba(255,255,255,0.06); text-align: left; }}
    tr.client-header td {{ background: #111827; padding: 10px 14px;
          border-top: 2px solid rgba(96,165,250,0.2);
          border-bottom: 1px solid rgba(255,255,255,0.04); }}
    .client-name {{ font-weight: 600; color: #93c5fd; font-size: 0.92rem; }}
    .badge {{ display: inline-block; background: rgba(96,165,250,0.15);
              color: #60a5fa; border-radius: 99px; padding: 1px 8px;
              font-size: 0.72rem; font-weight: 500; margin-left: 8px; vertical-align: middle; }}
    tr:not(.client-header):hover {{ background: rgba(255,255,255,0.03); }}
    td {{ padding: 8px 14px; border-bottom: 1px solid rgba(255,255,255,0.04); color: #cbd5e1; }}
    .col-row {{ color: #64748b; font-size: 0.8rem; width: 80px; }}
    .col-col {{ color: #a5b4fc; }}
    .col-val {{ font-weight: 600; color: #fbbf24; text-align: right; width: 120px; }}
  </style>
</head>
<body>
  <h1>Values between {LOW:,} and {HIGH:,}</h1>
  <p class="subtitle">
    <span>{total}</span> match{'es' if total != 1 else ''} across
    <span>{client_count}</span> client{'s' if client_count != 1 else ''}
  </p>
  <table>
    <thead>
      <tr>
        <th>Row</th>
        <th>Column</th>
        <th style="text-align:right">Value</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</body>
</html>"""

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_find_values_2000_3000.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Report saved: {out_path}")
print(f"Total matches: {total} across {client_count} clients")

import webbrowser
webbrowser.open(out_path)
