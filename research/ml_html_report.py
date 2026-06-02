"""Presentable HTML report for ML + active-trade portfolio analysis."""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from research.eat_time import format_dt_eat, format_hour_eat

DOW_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Blueprint-aligned column colors (dashboard evaluations table)
PHASE_BADGE_CLASS = {
    "CH": "badge-ch",
    "FD": "badge-fd",
    "DD": "badge-dd",
    "FA": "badge-fa",
    "UNK": "badge-unk",
}


def _money(v: float) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    sign = "+" if v > 0 else ""
    return f"{sign}${float(v):,.2f}"


def _pct(v: float) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v) * 100:.1f}%"


def _pnl_class(v: float) -> str:
    try:
        if hasattr(v, "item"):
            v = float(v.item())
        else:
            v = float(v)
    except (TypeError, ValueError):
        return "zero"
    if v > 0:
        return "pos"
    if v < 0:
        return "neg"
    return "zero"


def _bar(value: float, max_abs: float) -> str:
    if max_abs <= 0:
        pct = 0
    else:
        pct = min(100, abs(value) / max_abs * 100)
    cls = "bar-pos" if value >= 0 else "bar-neg"
    return f'<div class="bar-track"><div class="bar-fill {cls}" style="width:{pct:.1f}%"></div></div>'


def _badge_class(phase_badge: str) -> str:
    b = str(phase_badge or "UNK").upper()
    for prefix, cls in PHASE_BADGE_CLASS.items():
        if b.startswith(prefix):
            return cls
    return "badge-unk"


def _phase_badge_html(badge: str, stage: str = "") -> str:
    b = html.escape(str(badge or "UNK"))
    s = html.escape(str(stage or ""))
    cls = _badge_class(badge)
    title = f' title="{s}"' if s else ""
    return f'<span class="badge-phase {cls}"{title}>{b}</span>'


def _fmt_hour(h: Any) -> str:
    try:
        hi = int(h)
        if 0 <= hi <= 23:
            return f"{hi:02d}:00"
    except (TypeError, ValueError):
        pass
    return "—"


def _fmt_dt(val: Any) -> str:
    return format_dt_eat(val)


def _table_from_records(
    records: List[dict],
    columns: List[tuple],
    *,
    max_rows: int = 40,
    bar_col: Optional[str] = None,
) -> str:
    if not records:
        return "<p class='muted'>No data.</p>"
    rows = records[:max_rows]
    max_abs = 1.0
    if bar_col:
        vals = [abs(float(r.get(bar_col, 0) or 0)) for r in rows]
        max_abs = max(vals) if vals else 1.0

    thead = "".join(f"<th>{html.escape(lbl)}</th>" for _, lbl in columns)
    body_parts = []
    for r in rows:
        tds = []
        for key, lbl in columns:
            val = r.get(key, "")
            if key == "phase_badge":
                tds.append(f"<td>{_phase_badge_html(str(val), str(r.get('phase_stage', '')))}</td>")
            elif key in ("avg_pnl", "net_pnl", "total_pnl", "total", "profit") and val != "":
                try:
                    fv = float(val)
                    tds.append(f"<td class='num {_pnl_class(fv)}'>{_money(fv)}</td>")
                except (TypeError, ValueError):
                    tds.append(f"<td>{html.escape(str(val))}</td>")
            elif key == "win_rate" and val != "":
                try:
                    tds.append(f"<td class='num'>{_pct(float(val))}</td>")
                except (TypeError, ValueError):
                    tds.append(f"<td>{html.escape(str(val))}</td>")
            elif key == "entry_hour":
                tds.append(f"<td>{format_hour_eat(val)}</td>")
            elif key in ("entry_time", "close_time"):
                tds.append(f"<td class='num'>{_fmt_dt(val)}</td>")
            elif key == "ml_confidence" and val != "":
                try:
                    tds.append(f"<td class='num'>{float(val) * 100:.0f}%</td>")
                except (TypeError, ValueError):
                    tds.append(f"<td>—</td>")
            elif key == "rule_status":
                st = str(val)
                cls = "status-ok" if st == "OK" else "status-warn" if "align" in st.lower() else "status-bad"
                tds.append(f"<td><span class='status-pill {cls}'>{html.escape(st)}</span></td>")
            elif key == "market_status":
                st = str(val)
                if "against rec" in st or "misaligned + losing" in st:
                    cls = "status-bad"
                elif "misaligned" in st:
                    cls = "status-warn"
                else:
                    cls = "status-ok"
                tds.append(f"<td><span class='status-pill {cls}'>{html.escape(st)}</span></td>")
            else:
                tds.append(f"<td>{html.escape(str(val))}</td>")
            _ = lbl
        bar_cell = ""
        if bar_col and bar_col in r:
            try:
                bar_cell = f"<td class='bar-cell'>{_bar(float(r[bar_col]), max_abs)}</td>"
            except (TypeError, ValueError):
                bar_cell = "<td></td>"
        body_parts.append("<tr>" + "".join(tds) + bar_cell + "</tr>")

    bar_th = "<th></th>" if bar_col else ""
    return f"<table class='data-table'><thead><tr>{thead}{bar_th}</tr></thead><tbody>{''.join(body_parts)}</tbody></table>"


def _df_records(df: pd.DataFrame, max_rows: Optional[int] = None) -> List[dict]:
    if df is None or df.empty:
        return []
    d = df if max_rows is None else df.head(max_rows)
    recs = d.to_dict("records")
    for r in recs:
        for k, v in list(r.items()):
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat() if pd.notna(v) else ""
    return recs


def _firm_summary_row(grp: pd.DataFrame) -> str:
    n = len(grp)
    pnl = float(grp["net_pnl"].sum()) if "net_pnl" in grp.columns else 0.0
    wr = float(grp["won"].mean()) if "won" in grp.columns and n else 0.0
    phases = grp["phase_badge"].value_counts().head(6) if "phase_badge" in grp.columns else pd.Series()
    chips = "".join(
        f'<span class="mini-chip">{html.escape(str(ph))} ×{int(c)}</span>'
        for ph, c in phases.items()
    )
    return (
        f'<span class="firm-stats">{n:,} trades · WR {_pct(wr)} · '
        f'<span class="{_pnl_class(pnl)}">{_money(pnl)}</span></span>'
        f'<span class="firm-chips">{chips}</span>'
    )


def _render_trades_by_firm(
    df: pd.DataFrame,
    *,
    section_id: str,
    title: str,
    subtitle: str,
    columns: List[Tuple[str, str]],
    bar_col: Optional[str] = None,
    max_rows_per_firm: Optional[int] = None,
    section_class: str = "",
) -> str:
    if df is None or df.empty:
        return f"""
        <section id="{section_id}" class="panel section-major">
          <h2>{html.escape(title)}</h2>
          <p class="muted">{html.escape(subtitle)}</p>
          <p class="muted">No rows.</p>
        </section>
        """

    firm_col = "_sort_firm" if "_sort_firm" in df.columns else "prop_firm"
    firms = sorted(df[firm_col].fillna("Unknown").unique())

    blocks: List[str] = []
    total = len(df)
    for firm in firms:
        grp = df[df[firm_col] == firm]
        if max_rows_per_firm:
            display = grp.head(max_rows_per_firm)
            trunc_note = f" (showing {len(display):,} of {len(grp):,})" if len(display) < len(grp) else ""
        else:
            display = grp
            trunc_note = ""

        records = _df_records(display)
        table = _table_from_records(records, columns, max_rows=len(records) + 1, bar_col=bar_col)
        blocks.append(f"""
        <details class="firm-block" open>
          <summary class="firm-summary">
            <span class="firm-name">{html.escape(str(firm))}</span>
            {_firm_summary_row(grp)}
            {f'<span class="trunc-note">{html.escape(trunc_note.strip())}</span>' if trunc_note else ''}
          </summary>
          <div class="firm-table-wrap">{table}</div>
        </details>
        """)

    extra = f" {section_class}" if section_class else ""
    return f"""
    <section id="{section_id}" class="panel section-major{extra}">
      <h2>{html.escape(title)}</h2>
      <p class="muted">{html.escape(subtitle)} · <strong>{total:,}</strong> rows · sorted by prop firm → phase (CH1, FD2, …) → client</p>
      <div class="firm-groups">{''.join(blocks)}</div>
    </section>
    """


LIVE_COLUMNS = [
    ("client_id", "Client"),
    ("account_short", "Prop account"),
    ("phase_badge", "Phase"),
    ("phase_stage", "Stage"),
    ("symbol", "Symbol"),
    ("side", "Dir"),
    ("recommended_side", "Recommend"),
    ("entry_dow_name", "Entry day"),
    ("entry_hour", "Hour"),
    ("sl_dist", "SL"),
    ("tp_dist", "TP"),
    ("profit", "Float P/L"),
    ("rule_status", "Side rule"),
    ("market_status", "Market vs rec"),
]

CLOSED_COLUMNS = [
    ("client_id", "Client"),
    ("account_short", "Prop account"),
    ("phase_badge", "Phase"),
    ("phase_stage", "Stage"),
    ("symbol", "Symbol"),
    ("side", "Dir"),
    ("entry_time", "Entry"),
    ("close_time", "Close"),
    ("volume", "Vol"),
    ("net_pnl", "Net P/L"),
]


def _render_kpi_cards(analysis: Dict[str, Any]) -> str:
    br = analysis.get("business_rules") or {}
    active_n = br.get("active_count", 0)
    clients_n = br.get("active_clients", 0)
    accounts_n = br.get("active_accounts", 0)
    violations = len(br.get("direction_violations") or [])
    day_ok = br.get("same_day_ok", True)
    rec_day = br.get("recommended_dow", "—")
    today_dow = br.get("today_dow_name", "—")
    hist_dow = br.get("best_historical_dow") or "—"
    ml = analysis.get("ml") or {}
    acc = ml.get("accuracy_test")
    acc_s = f"{float(acc) * 100:.1f}%" if acc is not None else "—"
    n_closed = analysis.get("n_trades", 0)
    kpi_sub_day = (
        f"Today (EAT): {html.escape(str(today_dow))}"
        if day_ok
        else f"Today {html.escape(str(today_dow))} · hist. best {html.escape(str(hist_dow))}"
    )

    return f"""
    <section class="kpi-grid">
      <div class="kpi"><span class="kpi-label">All clients (closed)</span><span class="kpi-value">{n_closed:,}</span><span class="kpi-sub">Round-trip history</span></div>
      <div class="kpi"><span class="kpi-label">Live trades</span><span class="kpi-value accent">{active_n}</span><span class="kpi-sub">{clients_n} clients · {accounts_n} accounts</span></div>
      <div class="kpi"><span class="kpi-label">Phase model accuracy</span><span class="kpi-value">{acc_s}</span><span class="kpi-sub">Time-ordered holdout</span></div>
      <div class="kpi"><span class="kpi-label">Same entry day</span><span class="kpi-value {'pos' if day_ok else 'warn'}">{'Yes' if day_ok else 'Split'}</span><span class="kpi-sub">{kpi_sub_day}</span></div>
      <div class="kpi"><span class="kpi-label">Direction conflicts</span><span class="kpi-value {'pos' if violations == 0 else 'neg'}">{violations}</span><span class="kpi-sub">Per prop account</span></div>
    </section>
    """


def _render_nav() -> str:
    return """
    <nav class="report-nav">
      <a href="#analytics">Analytics</a>
      <a href="#coordinated-plan">Plan</a>
      <a href="#live-trades">Live trades</a>
      <a href="#all-clients-data">All clients data</a>
    </nav>
    """


def _render_alerts(analysis: Dict[str, Any]) -> str:
    br = analysis.get("business_rules") or {}
    alerts: List[str] = []

    if not br.get("same_day_ok"):
        dates = ", ".join(br.get("active_dates") or [])
        alerts.append(
            f"<div class='alert alert-warn'><strong>Split entry days</strong> — live trades span {html.escape(dates)}. "
            f"All accounts should share one calendar day. Target: <strong>{html.escape(str(br.get('recommended_dow')))}</strong>.</div>"
        )
    else:
        udate = br.get("unified_entry_date") or br.get("today_eat", "")
        udow = br.get("today_dow_name", br.get("recommended_dow", ""))
        alerts.append(
            f"<div class='alert alert-ok'><strong>Same-day aligned (EAT)</strong> — "
            f"<strong>{html.escape(str(udow))}</strong> "
            f"<code>{html.escape(str(udate))}</code>.</div>"
        )

    for v in br.get("direction_violations") or []:
        alerts.append(
            f"<div class='alert alert-danger'><strong>Mixed direction</strong> — "
            f"{html.escape(str(v.get('client_id')))} · account {html.escape(str(v.get('account_number')))} · "
            f"BUY {v.get('buy_count', 0)} / SELL {v.get('sell_count', 0)} → "
            f"<strong>{html.escape(str(v.get('recommended_side')))}</strong></div>"
        )

    if not alerts:
        return ""
    return "<section class='alerts'>" + "".join(alerts) + "</section>"


def _render_timing_heatmap(block: Dict[str, Any], phase: str) -> str:
    by_hour = block.get("by_hour")
    if by_hour is None or (isinstance(by_hour, pd.DataFrame) and by_hour.empty):
        return ""
    if isinstance(by_hour, pd.DataFrame):
        hour_map = {int(r["entry_hour"]): float(r.get("avg_pnl", 0)) for _, r in by_hour.iterrows() if "entry_hour" in r}
    else:
        hour_map = {}
    max_abs = max((abs(v) for v in hour_map.values()), default=1) or 1
    cells = []
    for h in range(24):
        v = hour_map.get(h, 0)
        if h not in hour_map:
            cls = "heat-empty"
            title = f"{format_hour_eat(h)} — no data"
            cells.append(f'<div class="heat-cell {cls}" title="{html.escape(title)}">{h:02d}</div>')
        else:
            intensity = min(1.0, abs(v) / max_abs)
            cls = "heat-pos" if v >= 0 else "heat-neg"
            title = f"{format_hour_eat(h)} avg {_money(v)}"
            cells.append(
                f'<div class="heat-cell {cls}" style="opacity:{0.35 + intensity * 0.65:.2f}" title="{html.escape(title)}">{h:02d}</div>'
            )

    badge = phase
    return f"""
    <div class="phase-card">
      <div class="phase-head">
        {_phase_badge_html(badge, phase)}
        <span class="phase-meta">{block.get('n', 0):,} closed · prefer <strong>{html.escape(str(block.get('prefer_side', '?')))}</strong></span>
      </div>
      <div class="heat-row">{''.join(cells)}</div>
      <div class="phase-tables grid-2">
        <div>
          <h4>Best days</h4>
          {_table_from_records(block.get('best_dow') or [], [('bucket','Day'),('n','N'),('win_rate','WR'),('avg_pnl','Avg')], bar_col='avg_pnl')}
        </div>
        <div>
          <h4>Best hours</h4>
          {_table_from_records(block.get('best_hours') or [], [('bucket','Hour'),('n','N'),('win_rate','WR'),('avg_pnl','Avg')], bar_col='avg_pnl')}
        </div>
      </div>
    </div>
    """


def _render_insights(tips: List[str]) -> str:
    if not tips:
        return ""
    items = "".join(f"<li>{t}</li>" for t in tips)
    return f"<section class='panel insights'><h2>Key findings</h2><ul class='insight-list'>{items}</ul></section>"


def _report_styles() -> str:
    return """
    :root {
      --bg: #070b14;
      --panel: #0f1628;
      --panel2: #141e34;
      --border: #243049;
      --text: #eef4fc;
      --muted: #8b9cb8;
      --accent: #5b9cf5;
      --pos: #34d399;
      --neg: #f87171;
      --warn: #fbbf24;
      --ch: #22c55e;
      --fd: #f97316;
      --dd: #a855f7;
      --fa: #8b5cf6;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.45; }
    .hero { background: linear-gradient(135deg, #0f1a33 0%, #1a1040 50%, #0b1020 100%); border-bottom: 1px solid var(--border); padding: 32px 24px 28px; }
    .hero h1 { margin: 0 0 6px; font-size: 1.75rem; font-weight: 600; }
    .hero .meta { color: var(--muted); font-size: 0.9rem; max-width: 800px; }
    .wrap { max-width: 1400px; margin: 0 auto; padding: 24px 20px 56px; }
    .report-nav { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }
    .report-nav a { color: var(--accent); text-decoration: none; font-size: 0.85rem; padding: 6px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--panel); }
    .report-nav a:hover { background: var(--panel2); }
    .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }
    .kpi { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
    .kpi-label { display: block; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
    .kpi-value { display: block; font-size: 1.5rem; font-weight: 600; margin-top: 4px; }
    .kpi-value.accent { color: var(--accent); }
    .kpi-value.pos { color: var(--pos); }
    .kpi-value.neg { color: var(--neg); }
    .kpi-value.warn { color: var(--warn); }
    .kpi-sub { display: block; font-size: 0.78rem; color: var(--muted); margin-top: 4px; }
    .panel, section.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 20px 22px; margin-bottom: 18px; }
    .section-major h2 { margin: 0 0 8px; font-size: 1.25rem; color: var(--text); border-left: 4px solid var(--accent); padding-left: 12px; }
    .section-major.live h2 { border-left-color: var(--pos); }
    .section-major.closed h2 { border-left-color: var(--accent); }
    .panel h2 { margin: 0 0 12px; font-size: 1.1rem; color: var(--accent); }
    .panel.highlight { border-color: #3d5a80; background: linear-gradient(180deg, var(--panel2), var(--panel)); }
    .alerts { margin-bottom: 18px; }
    .alert { padding: 12px 16px; border-radius: 10px; margin-bottom: 10px; font-size: 0.9rem; border: 1px solid; }
    .alert-ok { background: rgba(52,211,153,0.08); border-color: rgba(52,211,153,0.35); }
    .alert-warn { background: rgba(251,191,36,0.08); border-color: rgba(251,191,36,0.35); }
    .alert-danger { background: rgba(248,113,113,0.1); border-color: rgba(248,113,113,0.4); }
    .firm-block { border: 1px solid var(--border); border-radius: 10px; margin-bottom: 12px; background: var(--panel2); }
    .firm-block summary { cursor: pointer; padding: 12px 16px; list-style: none; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; }
    .firm-block summary::-webkit-details-marker { display: none; }
    .firm-name { font-weight: 700; font-size: 1rem; color: #fbbf24; min-width: 140px; }
    .firm-stats { color: var(--muted); font-size: 0.85rem; }
    .firm-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-left: auto; }
    .mini-chip { font-size: 0.72rem; padding: 2px 8px; border-radius: 4px; background: rgba(91,156,245,0.15); color: var(--accent); }
    .trunc-note { font-size: 0.75rem; color: var(--warn); }
    .firm-table-wrap { padding: 0 12px 12px; overflow-x: auto; }
    .badge-phase { display: inline-block; font-weight: 700; font-size: 0.78rem; padding: 3px 8px; border-radius: 5px; letter-spacing: 0.02em; }
    .badge-ch { background: rgba(34,197,94,0.2); color: #4ade80; border: 1px solid rgba(34,197,94,0.45); }
    .badge-fd { background: rgba(249,115,22,0.2); color: #fb923c; border: 1px solid rgba(249,115,22,0.45); }
    .badge-dd { background: rgba(168,85,247,0.2); color: #c084fc; border: 1px solid rgba(168,85,247,0.45); }
    .badge-fa { background: rgba(139,92,246,0.2); color: #a78bfa; border: 1px solid rgba(139,92,246,0.45); }
    .badge-unk { background: rgba(148,163,184,0.15); color: #94a3b8; border: 1px solid var(--border); }
    .status-pill { font-size: 0.75rem; padding: 2px 8px; border-radius: 4px; }
    .status-ok { background: rgba(52,211,153,0.15); color: var(--pos); }
    .status-warn { background: rgba(251,191,36,0.15); color: var(--warn); }
    .status-bad { background: rgba(248,113,113,0.15); color: var(--neg); }
    .legend-phases { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; font-size: 0.8rem; }
    table.data-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
    th, td { padding: 7px 9px; border-bottom: 1px solid var(--border); text-align: left; }
    th { color: var(--muted); font-size: 0.68rem; text-transform: uppercase; }
    td.num { font-variant-numeric: tabular-nums; }
    td.pos { color: var(--pos); }
    td.neg { color: var(--neg); }
    .bar-track { height: 6px; background: var(--border); border-radius: 3px; min-width: 60px; }
    .bar-fill.bar-pos { background: var(--pos); }
    .bar-fill.bar-neg { background: var(--neg); }
    .muted { color: var(--muted); font-size: 0.86rem; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .phase-card { background: var(--panel2); border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 14px; }
    .heat-row { display: grid; grid-template-columns: repeat(24, 1fr); gap: 3px; margin-bottom: 14px; }
    .heat-cell { font-size: 0.55rem; text-align: center; padding: 6px 0; border-radius: 4px; background: var(--border); }
    .heat-cell.heat-pos { background: var(--pos); color: #042f1a; }
    .heat-cell.heat-neg { background: var(--neg); color: #3f0a0a; }
    .rec-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
    .rec-item { background: rgba(91,156,245,0.06); border-radius: 10px; padding: 14px; }
    pre.report { background: #0a0e18; padding: 12px; border-radius: 8px; font-size: 0.75rem; color: var(--muted); overflow-x: auto; }
    footer { margin-top: 24px; color: var(--muted); font-size: 0.8rem; }
    @media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } }
    """


def render_ml_html_report(
    analysis: Dict[str, Any],
    *,
    data_source_line: str = "",
    title: str = "ML Trade Timing Analysis",
) -> str:
    ml = analysis.get("ml") or {}
    timing = analysis.get("timing") or {}
    bs = analysis.get("buy_sell") or {}
    tips: List[str] = list(analysis.get("insight_tips") or [])

    active_df = analysis.get("active_predictions")
    closed_df = analysis.get("closed_trades")
    if closed_df is None:
        closed_df = analysis.get("df")

    live_cols = [c for c in LIVE_COLUMNS if active_df is None or c[0] in getattr(active_df, "columns", [])]
    closed_cols = [c for c in CLOSED_COLUMNS if closed_df is None or c[0] in getattr(closed_df, "columns", [])]

    live_section = _render_trades_by_firm(
        active_df if isinstance(active_df, pd.DataFrame) else pd.DataFrame(),
        section_id="live-trades",
        title="Live trades",
        subtitle="Open positions from clients_data.positions — grouped by blueprint prop firm",
        columns=live_cols or LIVE_COLUMNS,
        section_class="live",
    )

    closed_section = _render_trades_by_firm(
        closed_df if isinstance(closed_df, pd.DataFrame) else pd.DataFrame(),
        section_id="all-clients-data",
        title="All clients — full closed trade history",
        subtitle="Every stored round-trip — CH1 / FD2 / FA badges match blueprint comments",
        columns=closed_cols or CLOSED_COLUMNS,
        bar_col="net_pnl",
        section_class="closed",
    )

    phase_legend = """
    <div class="legend-phases">
      <span><span class="badge-phase badge-ch">CH1</span> Challenge</span>
      <span><span class="badge-phase badge-fd">FD2</span> Funded</span>
      <span><span class="badge-phase badge-dd">DD1</span> Double Dip</span>
      <span><span class="badge-phase badge-fa">FA</span> Farming</span>
      <span><span class="badge-phase badge-unk">UNK</span> Unknown</span>
    </div>
    """

    recs = analysis.get("portfolio_recommendations") or {}
    uw = int(recs.get("underwater_on_recommendation", 0) or 0)
    uw_alert = ""
    if uw > 0:
        uw_alert = (
            f"<div class='alert alert-danger'><strong>Market vs recommendation</strong> — "
            f"{uw} open leg(s) are on the recommended side but show negative float P/L "
            f"(price has moved against that direction on the hedge book). Re-run the report after "
            f"clients push fresh positions.</div>"
        )

    rec_html = ""
    if recs or uw_alert:
        rec_html = f"""
        {uw_alert}
        <section id="coordinated-plan" class="panel highlight">
          <h2>Coordinated plan (from live book)</h2>
          <div class="rec-grid">
            <div class="rec-item"><span class="rec-label">Trading day (EAT)</span><span class="rec-value">{html.escape(str(recs.get('trading_day', '—')))}</span></div>
            <div class="rec-item"><span class="rec-label">Today (EAT)</span><span class="rec-value">{html.escape(str(recs.get('today_dow_name', '—')))} · {html.escape(str(recs.get('today_eat', '—')))}</span></div>
            <div class="rec-item"><span class="rec-label">Hist. best day</span><span class="rec-value">{html.escape(str(recs.get('best_historical_dow', '—')))}</span></div>
            <div class="rec-item"><span class="rec-label">Entry window</span><span class="rec-value">{html.escape(str(recs.get('best_hour_window', '—')))}</span></div>
            <div class="rec-item"><span class="rec-label">Direction bias</span><span class="rec-value">{html.escape(str(recs.get('portfolio_side', '—')))}</span></div>
            <div class="rec-item"><span class="rec-label">Underwater on rec</span><span class="rec-value {'neg' if uw else ''}">{uw}</span></div>
            <div class="rec-item"><span class="rec-label">Fix accounts</span><span class="rec-value">{recs.get('accounts_needing_fix', 0)}</span></div>
          </div>
          <p class="muted">{html.escape(str(recs.get('summary', '')))}</p>
        </section>
        """

    phase_cards = "".join(
        _render_timing_heatmap(timing[p], p)
        for p in ["CH", "FD", "FA", "DD", "UNK"]
        if p in timing
    )

    analytics = f"""
    <section id="analytics" class="panel">
      <h2>Analytics — timing & ML</h2>
      {_render_insights(tips) if tips else ''}
      <h3 style="color:var(--muted);font-size:0.9rem;margin-top:16px">Overall BUY vs SELL</h3>
      {_table_from_records(_df_records(bs.get('overall')), [('side','Side'),('n','N'),('win_rate','WR'),('avg_pnl','Avg'),('total','Total')], bar_col='avg_pnl')}
      <h3 style="color:var(--muted);font-size:0.9rem">By phase badge group</h3>
      {_table_from_records(_df_records(bs.get('by_phase_side')), [('phase_group','Group'),('side','Side'),('n','N'),('win_rate','WR'),('avg_pnl','Avg')], bar_col='avg_pnl')}
      <h3 style="color:var(--muted);font-size:0.9rem;margin-top:20px">Hour heatmaps (closed)</h3>
      {phase_cards}
      <h3 style="color:var(--muted);font-size:0.9rem;margin-top:16px">Classifier holdout</h3>
      <pre class="report">{html.escape(str(ml.get('report', '')))}</pre>
    </section>
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(title)}</title>
  <style>{_report_styles()}</style>
</head>
<body>
  <header class="hero">
    <div class="wrap" style="padding-top:0;padding-bottom:0">
      <h1>{html.escape(title)}</h1>
      <p class="meta">{html.escape(data_source_line)}<br/>
        Generated {html.escape(str(analysis.get('generated_at', '')))} ·
        All entry times in <strong>EAT (Africa/Nairobi)</strong> ·
        Phase labels <strong>CH1 / FD2 / FA</strong> match blueprint · sorted by <strong>prop firm</strong>.
      </p>
    </div>
  </header>
  <div class="wrap">
    {_render_nav()}
    {phase_legend}
    {_render_kpi_cards(analysis)}
    {_render_alerts(analysis)}
    {analytics}
    {rec_html}
    {live_section}
    {closed_section}
    <footer>Not trading advice. One direction per prop account; same entry day across clients.</footer>
  </div>
</body>
</html>"""
