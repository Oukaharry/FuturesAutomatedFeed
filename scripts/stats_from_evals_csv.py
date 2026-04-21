#!/usr/bin/env python3
"""
Compute Stats-tab card numbers from an evaluations export CSV.

Matches the intended semantics:
  - In Progress = whole client view (all non-deleted rows): payouts + hedge + farming - fees
  - Completed = inactive/ended slice: payouts only when funded Status is Completed; fees/hedge/farm only when ended/p1-fail

Excludes "Discrepancy from Google Sheets" on purpose for comparison.

Usage:
  python scripts/stats_from_evals_csv.py "C:\\path\\to\\client_evaluations.csv"
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from typing import Dict, List


def parse_currency(val) -> float:
    if val is None:
        return 0.0
    s = str(val)
    s = (
        s.replace("$", "")
        .replace("€", "")
        .replace("£", "")
        .replace("\u00a0", "")  # NBSP
        .replace("\u202f", "")  # NNBSP
        .strip()
    )
    if not s or s == "-" or s.lower() == "nan":
        return 0.0
    if len(s) >= 2 and s[0] == "(" and s[-1] == ")":
        s = "-" + s[1:-1].strip()
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return 0.0


def money(x: float) -> str:
    return f"${x:,.2f}"


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _write_html_report(
    out_path: str,
    *,
    title: str,
    rows: int,
    pc: Dict[str, float],
    cf: Dict[str, float],
    pc_hedging_results: float,
    cf_hedging_results: float,
    pc_net: float,
    cf_net: float,
) -> None:
    def amt_color(v: float) -> str:
        return "#34d399" if v >= 0 else "#f87171"

    def line(label: str, value: str, color: str) -> str:
        return f"""
          <div class="row">
            <div class="label">{_html_escape(label)}</div>
            <div class="value" style="color:{color};">{_html_escape(value)}</div>
          </div>
        """

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_html_escape(title)}</title>
  <style>
    :root {{
      --bg: #070a12;
      --card: #0b1220;
      --border: rgba(255,255,255,0.08);
      --muted: #94a3b8;
      --text: #e2e8f0;
      --green: #34d399;
      --red: #f87171;
      --amber: #fbbf24;
    }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, "Noto Sans", "Liberation Sans", sans-serif;
      background: radial-gradient(1200px 700px at 40% -10%, rgba(124,58,237,0.20), transparent 60%),
                  radial-gradient(900px 600px at 80% 10%, rgba(34,211,238,0.10), transparent 55%),
                  var(--bg);
      color: var(--text);
      padding: 28px;
    }}
    .meta {{
      color: var(--muted);
      font-size: 12px;
      margin: 0 0 14px 2px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(320px, 1fr));
      gap: 16px;
      align-items: start;
    }}
    .card {{
      background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.015));
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px 16px 12px 16px;
      box-shadow: 0 8px 30px rgba(0,0,0,0.35);
    }}
    .card h2 {{
      margin: 0 0 10px 0;
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 0.2px;
      color: #cbd5e1;
    }}
    .row {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      padding: 10px 0;
      border-top: 1px solid rgba(255,255,255,0.06);
    }}
    .row:first-of-type {{ border-top: 0; }}
    .label {{
      color: #cbd5e1;
      font-size: 13px;
      font-weight: 650;
    }}
    .sub .label {{
      color: var(--muted);
      font-weight: 600;
      padding-left: 16px;
    }}
    .value {{
      font-variant-numeric: tabular-nums;
      font-weight: 800;
      letter-spacing: 0.2px;
    }}
    .net {{
      border-top: 2px solid rgba(255,255,255,0.18);
      margin-top: 2px;
    }}
    @media (max-width: 900px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="meta">{_html_escape(title)} • Rows: {rows} • Discrepancy excluded</div>
  <div class="grid">
    <div class="card">
      <h2>Profitability - Completed</h2>
      {line("Payouts", money(pc["payouts"]), "var(--green)")}
      {line("Hedging Results", money(pc_hedging_results), amt_color(pc_hedging_results))}
      <div class="sub">{line("Hedging", money(pc["hedge"]), amt_color(pc["hedge"]))}</div>
      <div class="sub">{line("Farming", money(pc["farm"]), amt_color(pc["farm"]))}</div>
      {line("Challenge Fees", money(-pc["fees"]), "var(--red)")}
      <div class="net">{line("Net Profit", money(pc_net), amt_color(pc_net))}</div>
    </div>

    <div class="card">
      <h2>Net Profit In Progress</h2>
      {line("Payouts", money(cf["payouts"]), "var(--green)")}
      {line("Hedging Results", money(cf_hedging_results), amt_color(cf_hedging_results))}
      <div class="sub">{line("Hedging", money(cf["hedge"]), amt_color(cf["hedge"]))}</div>
      <div class="sub">{line("Farming", money(cf["farm"]), amt_color(cf["farm"]))}</div>
      {line("Challenge Fees", money(-cf["fees"]), "var(--red)")}
      <div class="net">{line("Net Profit", money(cf_net), amt_color(cf_net))}</div>
    </div>
  </div>
</body>
</html>
"""

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as wf:
        wf.write(html)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--html", dest="html_path", default="", help="Write an HTML report to this path")
    args = ap.parse_args()

    path = args.csv_path
    if not os.path.exists(path):
        raise SystemExit(f"File not found: {path}")

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        fieldnames = r.fieldnames or []

        p1_cols = [f"Hedge Result {i}" for i in range(1, 6)]
        fd_cols = [f"Hedge Result {i}.1" for i in range(1, 6)]
        farm_hr_cols = ["Hedge Result 6", "Hedge Result 7"]

        hedge_day_cols: List[str] = []
        for i in range(1, 51):
            c = f"Hedge Day {i}"
            if c in fieldnames:
                hedge_day_cols.append(c)
        if not hedge_day_cols:
            for c in fieldnames:
                if re.match(r"^Hedge Day \d+$", c):
                    hedge_day_cols.append(c)

        def status_has(low: str, keys: List[str]) -> bool:
            return any(k in low for k in keys)

        # Totals
        cf = {"payouts": 0.0, "fees": 0.0, "hedge": 0.0, "farm": 0.0}  # all non-deleted
        pc = {"payouts": 0.0, "fees": 0.0, "hedge": 0.0, "farm": 0.0}  # inactive slice (ended/p1-fail)
        active = {"payouts": 0.0, "fees": 0.0, "hedge": 0.0, "farm": 0.0}  # remainder = cf - pc (computed directly)

        rows = 0
        for row in r:
            rows += 1
            status_p1 = str(row.get("Status P1", "") or "").strip()
            status_fd = str(row.get("Status", "") or row.get("Status Funded", "") or "").strip()
            sp1 = status_p1.lower()
            sfd = status_fd.lower()

            is_deleted = ("deleted" in sp1) or ("deleted" in sfd)
            is_p1_fail = status_has(sp1, ["fail", "breach", "sl", "closed"])
            is_fd_fail = status_has(sfd, ["fail", "breach", "sl", "closed"])
            is_fd_completed = "complete" in sfd
            is_fd_ended = is_fd_fail or is_fd_completed

            p1_hedges = round(sum(parse_currency(row.get(c)) for c in p1_cols), 2)
            funded_core = round(sum(parse_currency(row.get(c)) for c in fd_cols), 2)
            farming_hr = round(sum(parse_currency(row.get(c)) for c in farm_hr_cols), 2)
            hedge_days = round(sum(parse_currency(row.get(c)) for c in hedge_day_cols), 2)

            fee = parse_currency(row.get("Fee"))
            activation_fee = parse_currency(row.get("Activation Fee"))
            payouts = round(sum(parse_currency(row.get(f"Payout {i}")) for i in range(1, 7)), 2)

            farming_net_raw = row.get("Farming Net")
            farming_net_set = farming_net_raw is not None and str(farming_net_raw).strip() not in ("", "-")
            farm_val = round(parse_currency(farming_net_raw), 2) if farming_net_set else round(farming_hr + hedge_days, 2)

            # --- Cashflow / In Progress: all non-deleted rows ---
            if not is_deleted:
                cf["fees"] += fee + activation_fee
                cf["payouts"] += payouts
                # Hedging = P1 + funded core; Farming = farming net or (HR6-7 + hedge days)
                cf["hedge"] += (p1_hedges + funded_core)
                cf["farm"] += farm_val

            if is_deleted:
                continue

            # --- Completed: inactive/ended slice ---
            if is_p1_fail or is_fd_ended:
                pc["fees"] += fee + activation_fee

            if is_fd_ended:
                pc["hedge"] += (p1_hedges + funded_core)
                pc["farm"] += farm_val
            elif is_p1_fail:
                pc["hedge"] += p1_hedges

            if is_fd_completed:
                pc["payouts"] += payouts

            # Track active slice directly: non-deleted but NOT in inactive slice
            if not (is_p1_fail or is_fd_ended):
                active["fees"] += fee + activation_fee
                active["payouts"] += payouts
                active["hedge"] += (p1_hedges + funded_core)
                active["farm"] += farm_val

        # Round to 2 dp like UI
        def r2(x: float) -> float:
            return round(x + 1e-9, 2)

        for obj in (cf, pc):
            for k in obj:
                obj[k] = r2(obj[k])

        for k in active:
            active[k] = r2(active[k])

        cf_hedging_results = r2(cf["hedge"] + cf["farm"])
        pc_hedging_results = r2(pc["hedge"] + pc["farm"])
        active_hedging_results = r2(active["hedge"] + active["farm"])
        cf_net = r2(cf["payouts"] + cf_hedging_results - cf["fees"])
        pc_net = r2(pc["payouts"] + pc_hedging_results - pc["fees"])
        active_net = r2(active["payouts"] + active_hedging_results - active["fees"])

    if args.html_path:
        out_path = os.path.abspath(args.html_path)
        title = os.path.basename(path)
        _write_html_report(
            out_path,
            title=title,
            rows=rows,
            pc=pc,
            cf=cf,
            pc_hedging_results=pc_hedging_results,
            cf_hedging_results=cf_hedging_results,
            pc_net=pc_net,
            cf_net=cf_net,
        )
        print(f"Wrote HTML report: {out_path}")
        return

    # Print UI-like cards (no discrepancy line)
    print(f"Rows: {rows}")
    print("")
    print("Profitability - Completed")
    print(f"  Payouts:          {money(pc['payouts'])}")
    print(f"  Hedging Results:  {money(pc_hedging_results)}")
    print(f"    Hedging:        {money(pc['hedge'])}")
    print(f"    Farming:        {money(pc['farm'])}")
    print(f"  Challenge Fees:   {money(-pc['fees'])}")
    print(f"  Net Profit:       {money(pc_net)}")
    print("")
    print("Net Profit In Progress")
    print(f"  Payouts:          {money(cf['payouts'])}")
    print(f"  Hedging Results:  {money(cf_hedging_results)}")
    print(f"    Hedging:        {money(cf['hedge'])}")
    print(f"    Farming:        {money(cf['farm'])}")
    print(f"  Challenge Fees:   {money(-cf['fees'])}")
    print(f"  Net Profit:       {money(cf_net)}")

    print("")
    print("Active slice only (All - Completed)")
    print(f"  Payouts:          {money(active['payouts'])}")
    print(f"  Hedging Results:  {money(active_hedging_results)}")
    print(f"    Hedging:        {money(active['hedge'])}")
    print(f"    Farming:        {money(active['farm'])}")
    print(f"  Challenge Fees:   {money(-active['fees'])}")
    print(f"  Net Profit:       {money(active_net)}")


if __name__ == "__main__":
    main()

