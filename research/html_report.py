"""Render MT5 research analysis as a standalone HTML report."""

from __future__ import annotations

import html
from typing import Any, Dict

import pandas as pd


def _esc(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""


def _df_table(df: pd.DataFrame, money_cols: tuple[str, ...] = ()) -> str:
    if df is None or df.empty:
        return "<p class='muted'>No data.</p>"
    headers = "".join(f"<th>{_esc(c)}</th>" for c in df.columns)
    rows = []
    for _, row in df.iterrows():
        cells = []
        for c in df.columns:
            v = row[c]
            cls = ""
            if c in money_cols or c in ("total_pnl", "total", "avg_pnl", "avg", "net_pnl"):
                try:
                    fv = float(v)
                    cls = ' class="pos"' if fv > 0 else (' class="neg"' if fv < 0 else "")
                    v = f"${fv:,.2f}"
                except (TypeError, ValueError):
                    pass
            elif c == "win_rate" or c == "wr":
                try:
                    v = f"{float(v):.1f}%"
                except (TypeError, ValueError):
                    pass
            elif c == "n":
                try:
                    v = f"{int(v):,}"
                except (TypeError, ValueError):
                    pass
            cells.append(f"<td{cls}>{_esc(v)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _metric_card(label: str, value: str, sub: str = "") -> str:
    sub_html = f"<div class='sub'>{_esc(sub)}</div>" if sub else ""
    return f"<div class='card'><div class='label'>{_esc(label)}</div><div class='value'>{value}</div>{sub_html}</div>"


def render_html(data: Dict[str, Any], *, data_source_line: str = "") -> str:
    cov = data.get("coverage") or {}
    port = data.get("portfolio") or {}
    risk = data.get("risk") or {}
    wf = data.get("walk_forward") or {}

    cards = [
        _metric_card("Clients", f"{cov.get('total_clients', 0):,}", f"{cov.get('clients_with_trades', 0):,} with trades"),
        _metric_card("Round trips", f"{cov.get('total_round_trips', 0):,}", f"{cov.get('total_raw_deals', 0):,} raw deals"),
        _metric_card("Win rate", f"{port.get('win_rate_pct', 0):.1f}%", f"{port.get('n_trades', 0):,} closed positions"),
        _metric_card("Profit factor", f"{port.get('profit_factor', 0):.2f}", f"Expectancy ${port.get('expectancy', 0):,.2f}"),
        _metric_card("Total P/L", f"${port.get('total_pnl', 0):,.2f}", "MT5 hedge legs (not prop payout)"),
        _metric_card("Sharpe (daily)", f"{risk.get('sharpe_daily', 0):.2f}", f"{risk.get('trading_days', 0)} trading days"),
    ]

    wf_html = ""
    if wf and "note" not in wf:
        wf_html = f"""
        <section>
          <h2>Walk-forward (70% train / 30% test)</h2>
          <table>
            <thead><tr><th>Split</th><th>Trades</th><th>Win rate</th><th>Expectancy</th><th>Profit factor</th></tr></thead>
            <tbody>
              <tr><td>Train</td><td>{wf.get('train_trades', 0):,}</td><td>{wf.get('train_win_rate_pct', 0):.1f}%</td>
                  <td>${wf.get('train_expectancy', 0):,.2f}</td><td>{wf.get('train_profit_factor', 0):.2f}</td></tr>
              <tr><td>Test</td><td>{wf.get('test_trades', 0):,}</td><td>{wf.get('test_win_rate_pct', 0):.1f}%</td>
                  <td>${wf.get('test_expectancy', 0):,.2f}</td><td>{wf.get('test_profit_factor', 0):.2f}</td></tr>
            </tbody>
          </table>
          <p class="muted">Time-ordered split — tests whether recent hedge performance matches history.</p>
        </section>
        """

    insights_li = "".join(f"<li>{x}</li>" for x in data.get("insights", []))
    filter_note = ""
    if data.get("client_filter"):
        filter_note = f"<p class='tag'>Filtered: {_esc(data['client_filter'])}</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>MT5 Hedge Research — {_esc(data.get('generated_at', ''))}</title>
  <style>
    :root {{
      --bg: #0f1419;
      --panel: #1a2332;
      --text: #e7ecf3;
      --muted: #8b9cb3;
      --accent: #3b82f6;
      --pos: #22c55e;
      --neg: #ef4444;
      --border: #2d3a4f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 2rem 1.5rem 3rem;
      line-height: 1.5;
    }}
    .wrap {{ max-width: 1100px; margin: 0 auto; }}
    h1 {{ font-size: 1.75rem; margin: 0 0 0.25rem; }}
    h2 {{ font-size: 1.15rem; margin: 2rem 0 0.75rem; color: var(--accent); }}
    .meta {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 1.5rem; }}
    .tag {{ display: inline-block; background: var(--panel); padding: 0.25rem 0.6rem; border-radius: 4px; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: 0.75rem;
      margin: 1.25rem 0;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1rem;
    }}
    .card .label {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
    .card .value {{ font-size: 1.35rem; font-weight: 600; margin-top: 0.25rem; }}
    .card .sub {{ font-size: 0.8rem; color: var(--muted); margin-top: 0.35rem; }}
    section {{ margin-top: 1rem; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
      background: var(--panel);
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid var(--border);
    }}
    th, td {{ padding: 0.55rem 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }}
    th {{ background: #243044; color: var(--muted); font-weight: 600; }}
    tr:last-child td {{ border-bottom: none; }}
    .pos {{ color: var(--pos); }}
    .neg {{ color: var(--neg); }}
    .muted {{ color: var(--muted); font-size: 0.85rem; }}
    ul.insights {{ padding-left: 1.25rem; }}
    ul.insights li {{ margin: 0.4rem 0; }}
    .disclaimer {{
      margin-top: 2.5rem;
      padding: 1rem;
      border-left: 3px solid var(--accent);
      background: var(--panel);
      font-size: 0.85rem;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>MT5 Hedge Research Report</h1>
    <p class="meta">Generated {_esc(data.get('generated_at', ''))}<br/>
    {_esc(data_source_line)}{filter_note}</p>
    <div class="cards">{''.join(cards)}</div>

    <section>
      <h2>Insights</h2>
      <ul class="insights">{insights_li}</ul>
    </section>

    {wf_html}

    <section>
      <h2>Performance by phase</h2>
      {_df_table(data.get('by_phase', pd.DataFrame()))}
    </section>

    <section>
      <h2>Top symbols</h2>
      {_df_table(data.get('by_symbol', pd.DataFrame()))}
    </section>

    <section>
      <h2>Close hour (time pattern)</h2>
      <p class="muted">{_esc(data.get('hour_note', ''))}</p>
      {_df_table(data.get('by_hour', pd.DataFrame()))}
    </section>

    <section>
      <h2>Best clients (min 20 trades)</h2>
      {_df_table(data.get('clients_top', pd.DataFrame()))}
    </section>

    <section>
      <h2>Weakest clients (min 20 trades)</h2>
      {_df_table(data.get('clients_bottom', pd.DataFrame()))}
    </section>

    <section>
      <h2>Top clients by volume (coverage)</h2>
      {_df_table(data.get('coverage_table', pd.DataFrame()))}
    </section>

    <div class="disclaimer">
      Descriptive analysis of MT5 deal history stored in the dashboard database.
      Negative P/L on hedge accounts is often expected when prop accounts are profitable.
      Not trading advice. Parse rate: {cov.get('avg_parse_rate_pct', 'N/A')}% avg comment match.
      Max drawdown: ${risk.get('max_drawdown', 0):,.2f} ({risk.get('max_drawdown_pct', 0):.1f}% of peak).
    </div>
  </div>
</body>
</html>
"""
