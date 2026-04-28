import argparse
import json
from datetime import datetime
import sys
from pathlib import Path
import html

# Ensure project root is importable when running from /scripts
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


_INTERNAL_DEAL_TYPES_INT = {2, 3}  # BALANCE=2, CREDIT=3
_INTERNAL_DEAL_TYPES_STR = {
    'BALANCE', '2', '2.0',
    'CREDIT', '3', '3.0',
    'DEAL_TYPE_BALANCE', 'DEAL_TYPE_CREDIT',
}

_BALANCE_DEAL_TYPES_INT = {2}
_BALANCE_DEAL_TYPES_STR = {
    'BALANCE', '2', '2.0',
    'DEAL_TYPE_BALANCE',
}


def _is_internal_transfer_deal(d) -> bool:
    if not isinstance(d, dict):
        return False

    raw_type = d.get("type", "")
    raw_entry = d.get("entry", "")

    # Numeric check (raw MT5 / DataFrame): catches 2, 2.0, 3, 3.0, etc.
    try:
        if int(float(raw_type)) in _INTERNAL_DEAL_TYPES_INT:
            return True
    except (ValueError, TypeError):
        pass

    # String check (JSON payloads / serialized exports)
    str_type = str(raw_type).strip().upper()
    str_entry = str(raw_entry).strip().upper()

    return (
        str_type in _INTERNAL_DEAL_TYPES_STR
        or str_entry in _INTERNAL_DEAL_TYPES_STR
        or ("BALANCE" in str_type)
        or ("CREDIT" in str_type)
    )


def _is_balance_transfer_deal(d) -> bool:
    """BALANCE-only internal transfers."""
    if not isinstance(d, dict):
        return False

    raw_type = d.get("type", "")
    raw_entry = d.get("entry", "")

    try:
        if int(float(raw_type)) in _BALANCE_DEAL_TYPES_INT:
            return True
    except (ValueError, TypeError):
        pass

    str_type = str(raw_type).strip().upper()
    str_entry = str(raw_entry).strip().upper()

    return (
        str_type in _BALANCE_DEAL_TYPES_STR
        or str_entry in _BALANCE_DEAL_TYPES_STR
        or ("BALANCE" in str_type)
    )


def _summarize_deal(d: dict) -> dict:
    if not isinstance(d, dict):
        return {"raw": str(d)}
    return {
        "ticket": d.get("ticket") or d.get("position_id") or d.get("deal") or None,
        "type": d.get("type"),
        "entry": d.get("entry"),
        "profit": d.get("profit") if "profit" in d else d.get("net_profit"),
        "time": d.get("time") or d.get("open_time"),
        "comment": d.get("comment"),
    }


def _render_html_report(records: list, meta: dict) -> str:
    def esc(s) -> str:
        return html.escape("" if s is None else str(s))

    def link(url: str) -> str:
        if not url:
            return "—"
        u = esc(url)
        return f'<a href="{u}" target="_blank" rel="noreferrer">{u}</a>'

    rows = []
    for r in records:
        samples_pre = esc(json.dumps(r.get("samples", []), ensure_ascii=False, indent=2))
        purged = r.get("purged_count")
        purged_cell = f"<td class='num strong'>{esc(purged)}</td>" if purged is not None else ""
        rows.append(
            "<tr>"
            f"<td class='mono'>{esc(r.get('client_id'))}</td>"
            f"<td>{esc(r.get('email') or '—')}</td>"
            f"<td class='mono'>{esc(r.get('last_updated') or '—')}</td>"
            f"<td class='num'>{esc(r.get('deals_total'))}</td>"
            f"<td class='num strong'>{esc(r.get('internal_transfers'))}</td>"
            f"{purged_cell}"
            f"<td class='samples'><pre>{samples_pre}</pre></td>"
            f"<td class='sheet'>{link(r.get('sheet_url'))}</td>"
            "</tr>"
        )

    started = esc(meta.get("started"))
    finished = esc(meta.get("finished"))
    total_clients = esc(meta.get("total_clients"))
    scanned = esc(meta.get("scanned"))
    flagged = esc(meta.get("flagged"))
    mode = esc(meta.get("mode") or "internal")
    applied = "yes" if meta.get("applied") else "no"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Internal Transfers Audit</title>
  <style>
    :root {{
      --bg: #0b1220;
      --card: rgba(255,255,255,0.06);
      --text: #e6edf3;
      --muted: rgba(230,237,243,0.7);
      --border: rgba(255,255,255,0.12);
      --accent: #60a5fa;
      --danger: #f87171;
    }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, "Noto Sans", "Liberation Sans", sans-serif;
      background: radial-gradient(1200px 800px at 15% 10%, rgba(96,165,250,0.18), transparent 55%),
                  radial-gradient(900px 700px at 80% 25%, rgba(248,113,113,0.12), transparent 60%),
                  var(--bg);
      color: var(--text);
    }}
    .wrap {{ max-width: 1200px; margin: 28px auto; padding: 0 18px 60px; }}
    h1 {{ font-size: 22px; margin: 0 0 10px; }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
      margin: 14px 0 18px;
    }}
    .pill {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      line-height: 1.25;
    }}
    .pill .k {{ color: var(--muted); font-size: 12px; }}
    .pill .v {{ font-size: 14px; margin-top: 4px; }}
    .pill .v strong {{ color: var(--danger); }}
    .note {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 14px;
    }}
    table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow: hidden;
    }}
    thead th {{
      text-align: left;
      font-size: 12px;
      letter-spacing: 0.03em;
      text-transform: uppercase;
      color: var(--muted);
      background: rgba(255,255,255,0.05);
      border-bottom: 1px solid var(--border);
      padding: 10px 10px;
      position: sticky;
      top: 0;
      backdrop-filter: blur(10px);
    }}
    tbody td {{
      border-bottom: 1px solid rgba(255,255,255,0.08);
      padding: 10px 10px;
      vertical-align: top;
      font-size: 13px;
    }}
    tbody tr:hover td {{
      background: rgba(255,255,255,0.04);
    }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .strong {{ color: var(--danger); font-weight: 700; }}
    .samples pre {{
      margin: 0;
      max-height: 160px;
      overflow: auto;
      padding: 10px;
      border: 1px solid rgba(255,255,255,0.10);
      border-radius: 10px;
      background: rgba(0,0,0,0.20);
      color: rgba(230,237,243,0.9);
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .footer {{
      margin-top: 14px;
      color: var(--muted);
      font-size: 12px;
    }}
    @media (max-width: 980px) {{
      .meta {{ grid-template-columns: 1fr 1fr; }}
      thead {{ display: none; }}
      table, tbody, tr, td {{ display: block; width: 100%; }}
      tbody td {{ border-bottom: none; }}
      tbody tr {{
        border-bottom: 1px solid rgba(255,255,255,0.12);
        padding: 10px 0;
      }}
      tbody td::before {{
        content: attr(data-label);
        display: block;
        color: var(--muted);
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        margin-bottom: 4px;
      }}
      .num {{ text-align: left; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Internal Transfers Audit (Persisted Deals)</h1>
    <div class="note">
      Mode: <span class="mono">{mode}</span>. Applied purge: <span class="mono">{applied}</span>.
      <br/>
      Flags clients whose stored <span class="mono">deals</span> include internal transfer entries (BALANCE/CREDIT).
      These rows should not be stored or displayed after the server-side filter fix.
    </div>
    <div class="meta">
      <div class="pill"><div class="k">Started</div><div class="v mono">{started}</div></div>
      <div class="pill"><div class="k">Finished</div><div class="v mono">{finished}</div></div>
      <div class="pill"><div class="k">Clients in DB</div><div class="v">{total_clients}</div></div>
      <div class="pill"><div class="k">Scanned</div><div class="v">{scanned}</div></div>
      <div class="pill"><div class="k">Flagged</div><div class="v"><strong>{flagged}</strong></div></div>
    </div>

    <table>
      <thead>
        <tr>
          <th>Client</th>
          <th>Email</th>
          <th>Last Updated</th>
          <th class="num">Deals</th>
          <th class="num">Internal</th>
          {("<th class='num'>Purged</th>" if any(r.get("purged_count") is not None for r in records) else "")}
          <th>Samples</th>
          <th>Sheet URL</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows) if rows else '<tr><td colspan="8">No internal transfers found.</td></tr>'}
      </tbody>
    </table>

    <div class="footer mono">
      Generated by scripts/check_existing_internal_transfers.py
    </div>
  </div>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan persisted client records for internal transfer deals (BALANCE/CREDIT) already stored in DB."
    )
    parser.add_argument("--limit", type=int, default=0, help="Stop after reporting N clients (0 = no limit).")
    parser.add_argument("--samples", type=int, default=3, help="Number of sample internal deals to print per client.")
    parser.add_argument(
        "--mode",
        choices=["internal", "balance"],
        default="internal",
        help="Detection mode: 'internal' = BALANCE+CREDIT, 'balance' = BALANCE only.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Permanently purge matching deals from the DB (writes cleaned deals back).",
    )
    parser.add_argument(
        "--html",
        default=str(PROJECT_ROOT / "reports" / "internal-transfer-audit.html"),
        help="Write a formatted HTML report to this path.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON lines (one per client) instead of human-readable text.",
    )
    args = parser.parse_args()

    from dashboard.database import get_all_clients, update_client_field

    clients = get_all_clients() or {}
    total_clients = len(clients)

    flagged = 0
    scanned = 0
    started = datetime.now().isoformat(timespec="seconds")

    if not args.json:
        print(f"[scan] started={started} clients={total_clients}")

    matcher = _is_internal_transfer_deal if args.mode == "internal" else _is_balance_transfer_deal

    records = []
    total_purged = 0
    for client_id, client_data in clients.items():
        scanned += 1
        deals = (client_data or {}).get("deals") or []
        internal = [d for d in deals if matcher(d)]
        if not internal:
            continue

        flagged += 1
        identity = (client_data or {}).get("identity") or {}
        email = identity.get("email") if isinstance(identity, dict) else None
        sheet_url = identity.get("sheet_url") if isinstance(identity, dict) else None

        record = {
            "client_id": client_id,
            "email": email,
            "last_updated": (client_data or {}).get("last_updated"),
            "deals_total": len(deals),
            "internal_transfers": len(internal),
            "samples": [_summarize_deal(d) for d in internal[: max(0, args.samples)]],
            "sheet_url": sheet_url,
        }

        if args.apply:
            cleaned = [d for d in deals if not matcher(d)]
            purged_count = len(deals) - len(cleaned)
            ok = update_client_field(client_id, "deals", cleaned)
            record["purged_count"] = purged_count if ok else None
            record["purge_ok"] = bool(ok)
            if ok:
                total_purged += purged_count
        records.append(record)

        if args.json:
            print(json.dumps(record, ensure_ascii=False))
        else:
            print(
                f"\n[client] {client_id}"
                + (f" email={email}" if email else "")
                + (f" last_updated={record['last_updated']}" if record.get("last_updated") else "")
            )
            print(f"  deals_total={record['deals_total']} internal_transfers={record['internal_transfers']}")
            for i, s in enumerate(record["samples"], start=1):
                print(f"  sample_{i}={json.dumps(s, ensure_ascii=False)}")
            if sheet_url:
                print(f"  sheet_url={sheet_url}")
            if args.apply:
                print(f"  purged={record.get('purged_count')} ok={record.get('purge_ok')}")

        if args.limit and flagged >= args.limit:
            break

    finished = datetime.now().isoformat(timespec="seconds")
    if not args.json:
        print(f"\n[scan] finished={finished} scanned={scanned} flagged={flagged}")
        if args.apply:
            print(f"[purge] mode={args.mode} total_purged={total_purged}")

    # Always write HTML report (unless explicitly disabled)
    if args.html:
        out_path = Path(args.html)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        html_doc = _render_html_report(
            records=records,
            meta={
                "started": started,
                "finished": finished,
                "total_clients": total_clients,
                "scanned": scanned,
                "flagged": flagged,
                "mode": args.mode,
                "applied": bool(args.apply),
            },
        )
        out_path.write_text(html_doc, encoding="utf-8")
        if not args.json:
            print(f"[report] wrote_html={out_path}")

    # exit code 2 if any flagged (useful for CI / quick checks)
    return 2 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())

