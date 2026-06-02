#!/usr/bin/env python3
"""
Analyse Stats-tab trade history for a dashboard client and write an HTML insights report.

Loads deals from PostgreSQL (clients_data.deals), groups into round-trip trades,
and surfaces win-rate / P&L patterns by day-of-week, hour, and direction (BUY vs SELL).

Usage (from project root, same venv as the dashboard):
    python scripts/trade_history_analysis.py Aaron
    python scripts/trade_history_analysis.py "Brian Shore" --output reports/brian.html
    python scripts/trade_history_analysis.py Aaron --open

Requires DATABASE_URL (or default local postgres) and psycopg2.
"""
from __future__ import annotations

import argparse
import html
import os
import sys
import webbrowser
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("FLASK_ENV", "development")

DOW_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DOW_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

_INTERNAL_TYPES = frozenset({
    "BALANCE", "CREDIT", "2", "2.0", "3", "3.0",
    "CHARGE", "CORRECTION", "BONUS",
    "DEAL_TYPE_BALANCE", "DEAL_TYPE_CREDIT",
})


@dataclass
class Trade:
    position_id: Any
    symbol: str
    direction: str  # BUY or SELL
    volume: float
    entry_dt: datetime
    exit_dt: datetime
    net_pnl: float
    deal_count: int = 1


@dataclass
class BucketStats:
    label: str
    count: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    net_pnl: float = 0.0
    gross_wins: float = 0.0
    gross_losses: float = 0.0

    @property
    def win_rate(self) -> float:
        return (self.wins / self.count * 100.0) if self.count else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.net_pnl / self.count if self.count else 0.0

    @property
    def avg_win(self) -> float:
        return self.gross_wins / self.wins if self.wins else 0.0

    @property
    def avg_loss(self) -> float:
        return self.gross_losses / self.losses if self.losses else 0.0

    @property
    def profit_factor(self) -> Optional[float]:
        if self.gross_losses == 0:
            return None if self.gross_wins == 0 else float("inf")
        return self.gross_wins / abs(self.gross_losses)

    def add(self, pnl: float) -> None:
        self.count += 1
        self.net_pnl += pnl
        if pnl > 0:
            self.wins += 1
            self.gross_wins += pnl
        elif pnl < 0:
            self.losses += 1
            self.gross_losses += pnl
        else:
            self.breakeven += 1


def _resolve_client_id(query: str) -> str:
    from dashboard.database import get_all_clients

    q = (query or "").strip()
    if not q:
        sys.exit("Pass a client name as the first argument.")

    clients = get_all_clients() or []
    if not clients:
        from dashboard.database import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT client_id FROM clients_data ORDER BY client_id")
            clients = [r["client_id"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]

    for c in clients:
        if c == q:
            return c
    lower = q.lower()
    for c in clients:
        if c.lower() == lower:
            return c
    matches = [c for c in clients if lower in c.lower()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        sys.exit(f"Ambiguous client {q!r}. Matches: {', '.join(matches[:15])}")
    sys.exit(f"Client {q!r} not found. Try: python scripts/_list_all_clients.py")


def _parse_deal_dt(deal: dict) -> Optional[datetime]:
    raw = deal.get("time_raw")
    if raw is None or raw == "":
        raw = deal.get("time") or deal.get("open_time")
    if raw is None or raw == "":
        return None
    try:
        n = float(raw)
        if n > 10_000_000_000:
            n = n / 1000.0
        if n > 1_000_000_000:
            return datetime.fromtimestamp(n)
    except (TypeError, ValueError):
        pass
    try:
        s = str(raw).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _deal_pnl(deal: dict) -> float:
    return (
        float(deal.get("profit") or 0)
        + float(deal.get("swap") or 0)
        + float(deal.get("commission") or 0)
        + float(deal.get("fee") or 0)
    )


def _is_internal_deal(deal: dict) -> bool:
    if not isinstance(deal, dict):
        return True
    raw_type = str(deal.get("type", "")).strip().upper()
    raw_entry = str(deal.get("entry", "")).strip().upper()
    try:
        if int(float(raw_type)) in (2, 3):
            return True
    except (TypeError, ValueError):
        pass
    if raw_type in _INTERNAL_TYPES or raw_entry in _INTERNAL_TYPES:
        return True
    if "BALANCE" in raw_type or "CREDIT" in raw_type:
        return True
    return False


def _normalize_direction(raw: Any) -> str:
    s = str(raw or "").strip().upper()
    if s in ("BUY", "0", "0.0"):
        return "BUY"
    if s in ("SELL", "1", "1.0"):
        return "SELL"
    if "BUY" in s:
        return "BUY"
    if "SELL" in s:
        return "SELL"
    return s or "?"


def _filter_trade_deals(deals: List[dict]) -> List[dict]:
    out = []
    for d in deals or []:
        if not isinstance(d, dict) or _is_internal_deal(d):
            continue
        dt = _parse_deal_dt(d)
        if not dt:
            continue
        out.append(d)
    return out


def _build_trades(deals: List[dict]) -> List[Trade]:
    """Group deals by position_id into round-trip trades."""
    by_pos: Dict[Any, List[dict]] = defaultdict(list)
    orphans: List[dict] = []

    for d in deals:
        pos_id = d.get("position_id")
        if pos_id in (None, "", 0, "0"):
            orphans.append(d)
            continue
        by_pos[pos_id].append(d)

    trades: List[Trade] = []

    for pos_id, pos_deals in by_pos.items():
        pos_deals.sort(key=lambda x: _parse_deal_dt(x) or datetime.min)
        first, last = pos_deals[0], pos_deals[-1]
        entry_dt = _parse_deal_dt(first)
        exit_dt = _parse_deal_dt(last)
        if not entry_dt or not exit_dt:
            continue
        direction = _normalize_direction(first.get("type"))
        net = sum(_deal_pnl(d) for d in pos_deals)
        trades.append(Trade(
            position_id=pos_id,
            symbol=str(first.get("symbol") or ""),
            direction=direction,
            volume=float(first.get("volume") or 0),
            entry_dt=entry_dt,
            exit_dt=exit_dt,
            net_pnl=round(net, 2),
            deal_count=len(pos_deals),
        ))

    # Fallback: treat OUT deals as closed legs when position_id grouping is thin
    if len(trades) < max(3, len(deals) * 0.15):
        out_deals = [
            d for d in orphans
            if str(d.get("entry", "")).upper() in ("OUT", "1", "1.0", "OUT_BY", "3")
        ]
        if not out_deals:
            out_deals = [d for d in orphans if abs(_deal_pnl(d)) > 0.001]
        seen_tickets = {t.position_id for t in trades}
        for d in out_deals:
            ticket = d.get("ticket") or d.get("order")
            if ticket in seen_tickets:
                continue
            dt = _parse_deal_dt(d)
            if not dt:
                continue
            trades.append(Trade(
                position_id=ticket,
                symbol=str(d.get("symbol") or ""),
                direction=_normalize_direction(d.get("type")),
                volume=float(d.get("volume") or 0),
                entry_dt=dt,
                exit_dt=dt,
                net_pnl=round(_deal_pnl(d), 2),
                deal_count=1,
            ))

    trades.sort(key=lambda t: t.exit_dt)
    return trades


def _stats_from_trades(trades: List[Trade]) -> BucketStats:
    b = BucketStats(label="Overall")
    for t in trades:
        b.add(t.net_pnl)
    return b


def _bucket_trades(
    trades: List[Trade],
    key_fn: Callable[[Trade], str],
) -> Dict[str, BucketStats]:
    buckets: Dict[str, BucketStats] = {}
    for t in trades:
        key = key_fn(t)
        if key not in buckets:
            buckets[key] = BucketStats(label=key)
        buckets[key].add(t.net_pnl)
    return buckets


def _rank_buckets(
    buckets: Dict[str, BucketStats],
    min_trades: int = 3,
    sort_key: str = "net_pnl",
) -> List[BucketStats]:
    items = [b for b in buckets.values() if b.count >= min_trades]
    if sort_key == "win_rate":
        items.sort(key=lambda b: (b.win_rate, b.net_pnl), reverse=True)
    else:
        items.sort(key=lambda b: b.net_pnl, reverse=True)
    return items


def _build_recommendations(
    overall: BucketStats,
    by_dow: Dict[str, BucketStats],
    by_hour: Dict[str, BucketStats],
    by_dir: Dict[str, BucketStats],
    by_dir_hour: Dict[Tuple[str, str], BucketStats],
    min_trades: int,
) -> List[str]:
    tips: List[str] = []

    if overall.count == 0:
        return ["No completed trades found in stored history. Push from TradeOpss v1.6.5+ to backfill Stats trade history."]

    if overall.win_rate < 50:
        tips.append(
            f"Overall win rate is {overall.win_rate:.1f}% — focus on cutting low-edge sessions before sizing up."
        )
    pf = overall.profit_factor
    if pf is not None and pf < 1.0:
        tips.append(
            f"Profit factor {pf:.2f} is below 1.0 — average losses exceed average wins; tighten stops or reduce size on weak setups."
        )
    elif pf is not None and pf >= 1.5:
        tips.append(f"Profit factor {pf:.2f} is healthy — prioritize repeating your best time windows.")

    best_days = _rank_buckets(by_dow, min_trades, "net_pnl")[:2]
    worst_days = sorted(
        [b for b in by_dow.values() if b.count >= min_trades],
        key=lambda b: b.net_pnl,
    )[:2]
    if best_days:
        tips.append(
            "Best days: "
            + ", ".join(f"{b.label} ({b.win_rate:.0f}% WR, ${b.net_pnl:,.0f})" for b in best_days)
            + " — lean into these sessions."
        )
    if worst_days and worst_days[0].net_pnl < 0:
        tips.append(
            "Weakest days: "
            + ", ".join(f"{b.label} ({b.win_rate:.0f}% WR, ${b.net_pnl:,.0f})" for b in worst_days)
            + " — consider standing down or halving size."
        )

    best_hours = _rank_buckets(by_hour, min_trades, "net_pnl")[:3]
    worst_hours = sorted(
        [b for b in by_hour.values() if b.count >= min_trades],
        key=lambda b: b.net_pnl,
    )[:3]
    if best_hours:
        tips.append(
            "Best hours (entry): "
            + ", ".join(f"{b.label} ({b.win_rate:.0f}% WR)" for b in best_hours)
        )
    if worst_hours and worst_hours[0].net_pnl < 0:
        tips.append(
            "Avoid / reduce size: "
            + ", ".join(f"{b.label} ({b.win_rate:.0f}% WR, ${b.net_pnl:,.0f})" for b in worst_hours)
        )

    buy = by_dir.get("BUY")
    sell = by_dir.get("SELL")
    if buy and sell and buy.count >= min_trades and sell.count >= min_trades:
        if buy.win_rate > sell.win_rate + 8:
            tips.append(f"BUY side outperforms ({buy.win_rate:.0f}% vs {sell.win_rate:.0f}% WR) — bias long setups unless SELL windows below are strong.")
        elif sell.win_rate > buy.win_rate + 8:
            tips.append(f"SELL side outperforms ({sell.win_rate:.0f}% vs {buy.win_rate:.0f}% WR) — bias short setups unless BUY windows below are strong.")

    dir_hour_ranked = sorted(
        [b for b in by_dir_hour.values() if b.count >= max(2, min_trades - 1)],
        key=lambda b: b.net_pnl,
        reverse=True,
    )
    if dir_hour_ranked:
        top = dir_hour_ranked[:3]
        tips.append(
            "Highest-edge direction × hour: "
            + ", ".join(f"{b.label} ({b.win_rate:.0f}% WR, ${b.net_pnl:,.0f}, n={b.count})" for b in top)
        )
        bottom = sorted(dir_hour_ranked, key=lambda b: b.net_pnl)[:3]
        if bottom and bottom[0].net_pnl < 0:
            tips.append(
                "Lowest-edge direction × hour: "
                + ", ".join(f"{b.label} ({b.win_rate:.0f}% WR, ${b.net_pnl:,.0f})" for b in bottom)
            )

    if overall.avg_win and overall.avg_loss:
        rr = abs(overall.avg_win / overall.avg_loss) if overall.avg_loss else 0
        if rr < 1.0 and overall.win_rate < 55:
            tips.append(
                f"Average win ${overall.avg_win:.2f} vs average loss ${overall.avg_loss:.2f} — reward/risk {rr:.2f}; need higher win rate or wider targets."
            )

    return tips


def _money(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}${v:,.2f}"


def _pct(v: float) -> str:
    return f"{v:.1f}%"


def _pf_str(b: BucketStats) -> str:
    pf = b.profit_factor
    if pf is None:
        return "—"
    if pf == float("inf"):
        return "∞"
    return f"{pf:.2f}"


def _pnl_class(v: float) -> str:
    if v > 0:
        return "pos"
    if v < 0:
        return "neg"
    return "zero"


def _bar(value: float, max_abs: float, positive: bool = True) -> str:
    if max_abs <= 0:
        pct = 0
    else:
        pct = min(100, abs(value) / max_abs * 100)
    cls = "bar-pos" if value >= 0 else "bar-neg"
    return f'<div class="bar-track"><div class="bar-fill {cls}" style="width:{pct:.1f}%"></div></div>'


def _render_bucket_table(rows: List[BucketStats], value_col: str = "net") -> str:
    if not rows:
        return "<p class='muted'>Not enough data (need at least 3 trades per bucket).</p>"
    max_abs = max(abs(r.net_pnl) for r in rows) or 1
    out = [
        "<table><thead><tr>",
        "<th>Bucket</th><th>Trades</th><th>Win rate</th><th>Net P/L</th>",
        "<th>Avg/trade</th><th>Avg win</th><th>Avg loss</th><th>PF</th><th></th>",
        "</tr></thead><tbody>",
    ]
    for b in rows:
        out.append("<tr>")
        out.append(f"<td><strong>{html.escape(b.label)}</strong></td>")
        out.append(f"<td class='num'>{b.count}</td>")
        wr_cls = "pos" if b.win_rate >= 50 else "neg" if b.win_rate < 45 else ""
        out.append(f"<td class='num {wr_cls}'>{_pct(b.win_rate)}</td>")
        out.append(f"<td class='num {_pnl_class(b.net_pnl)}'>{_money(b.net_pnl)}</td>")
        out.append(f"<td class='num {_pnl_class(b.avg_pnl)}'>{_money(b.avg_pnl)}</td>")
        out.append(f"<td class='num pos'>{_money(b.avg_win)}</td>")
        out.append(f"<td class='num neg'>{_money(b.avg_loss)}</td>")
        out.append(f"<td class='num'>{_pf_str(b)}</td>")
        out.append(f"<td class='bar-cell'>{_bar(b.net_pnl, max_abs)}</td>")
        out.append("</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def _render_insights(tips: List[str]) -> str:
    if not tips:
        return ""
    items = "".join(f"<li>{html.escape(t)}</li>" for t in tips)
    return f"<section class='insights'><h2>Actionable insights</h2><ul>{items}</ul></section>"


def _render_summary_cards(overall: BucketStats, trade_count: int, deal_count: int, span: str) -> str:
    pf = _pf_str(overall)
    return f"""
    <section class="cards">
      <div class="card"><div class="label">Round-trip trades</div><div class="value">{trade_count}</div><div class="sub">{deal_count} deal legs in DB</div></div>
      <div class="card"><div class="label">Win rate</div><div class="value {'pos' if overall.win_rate >= 50 else 'neg'}">{_pct(overall.win_rate)}</div><div class="sub">{overall.wins}W / {overall.losses}L / {overall.breakeven}BE</div></div>
      <div class="card"><div class="label">Net P/L</div><div class="value {_pnl_class(overall.net_pnl)}">{_money(overall.net_pnl)}</div><div class="sub">{span}</div></div>
      <div class="card"><div class="label">Profit factor</div><div class="value">{pf}</div><div class="sub">Avg win {_money(overall.avg_win)} · Avg loss {_money(overall.avg_loss)}</div></div>
    </section>
    """


def render_html_report(
    client_id: str,
    trades: List[Trade],
    deals_raw: int,
    overall: BucketStats,
    by_dow: Dict[str, BucketStats],
    by_hour: Dict[str, BucketStats],
    by_dir: Dict[str, BucketStats],
    by_symbol: Dict[str, BucketStats],
    by_dir_dow: Dict[Tuple[str, str], BucketStats],
    by_dir_hour: Dict[Tuple[str, str], BucketStats],
    tips: List[str],
) -> str:
    if trades:
        span = f"{trades[0].entry_dt.strftime('%Y-%m-%d')} → {trades[-1].exit_dt.strftime('%Y-%m-%d')}"
    else:
        span = "no trades"

    dow_rows = [_rank_buckets({k: v for k, v in by_dow.items()}, 1, "net_pnl")]
    # Keep Mon–Sun order
    dow_ordered = []
    for name in DOW_NAMES:
        if name in by_dow:
            dow_ordered.append(by_dow[name])
    dow_ordered = [b for b in dow_ordered if b.count > 0]

    hour_ordered = []
    for h in range(24):
        label = f"{h:02d}:00"
        if label in by_hour:
            hour_ordered.append(by_hour[label])

    dir_rows = sorted(by_dir.values(), key=lambda b: b.count, reverse=True)
    sym_rows = _rank_buckets(by_symbol, 2, "net_pnl")

    dir_dow_rows = sorted(by_dir_dow.values(), key=lambda b: b.net_pnl, reverse=True)
    dir_hour_rows = sorted(by_dir_hour.values(), key=lambda b: b.net_pnl, reverse=True)

    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Trade analysis — {html.escape(client_id)}</title>
  <style>
    :root {{
      --bg: #0b1020; --panel: #121a2e; --border: #1e2a44; --text: #e8eef8;
      --muted: #8fa3c0; --pos: #34d399; --neg: #f87171; --accent: #60a5fa;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 24px 20px 48px; }}
    h1 {{ margin: 0 0 6px; font-size: 1.75rem; }}
    .meta {{ color: var(--muted); margin-bottom: 24px; font-size: 0.92rem; }}
    section {{ background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; margin-bottom: 20px; }}
    h2 {{ margin: 0 0 14px; font-size: 1.1rem; color: var(--accent); }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 20px; }}
    .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }}
    .card .label {{ color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; }}
    .card .value {{ font-size: 1.6rem; font-weight: 700; margin: 6px 0; }}
    .card .sub {{ color: var(--muted); font-size: 0.82rem; }}
    .pos {{ color: var(--pos); }} .neg {{ color: var(--neg); }} .zero {{ color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th, td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); text-align: left; }}
    th {{ color: var(--muted); font-weight: 600; font-size: 0.75rem; text-transform: uppercase; }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .bar-cell {{ width: 120px; }}
    .bar-track {{ height: 8px; background: #0a1020; border-radius: 4px; overflow: hidden; }}
    .bar-fill {{ height: 100%; border-radius: 4px; }}
    .bar-pos {{ background: linear-gradient(90deg, #059669, #34d399); }}
    .bar-neg {{ background: linear-gradient(90deg, #dc2626, #f87171); }}
    .insights ul {{ margin: 0; padding-left: 1.2rem; }}
    .insights li {{ margin-bottom: 10px; }}
    .muted {{ color: var(--muted); }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    @media (max-width: 900px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Trade history analysis</h1>
    <p class="meta">Client: <strong>{html.escape(client_id)}</strong> · Generated {generated} · Entry-time buckets · Data: dashboard Stats trade history</p>

    {_render_summary_cards(overall, len(trades), deals_raw, span)}
    {_render_insights(tips)}

    <div class="grid-2">
      <section>
        <h2>By day of week (entry time)</h2>
        {_render_bucket_table(dow_ordered)}
      </section>
      <section>
        <h2>By hour (entry time, 24h)</h2>
        {_render_bucket_table(hour_ordered)}
      </section>
    </div>

    <section>
      <h2>BUY vs SELL</h2>
      {_render_bucket_table(dir_rows)}
    </section>

    <div class="grid-2">
      <section>
        <h2>Direction × day of week</h2>
        {_render_bucket_table(dir_dow_rows[:14])}
      </section>
      <section>
        <h2>Direction × hour (best / worst edges)</h2>
        {_render_bucket_table(dir_hour_rows[:18])}
      </section>
    </div>

    <section>
      <h2>By symbol</h2>
      {_render_bucket_table(sym_rows)}
    </section>

    <section>
      <h2>Best sessions (net P/L, min 3 trades)</h2>
      {_render_bucket_table(_rank_buckets(by_hour, 3, "net_pnl")[:5])}
    </section>

    <section>
      <h2>Worst sessions (net P/L, min 3 trades)</h2>
      {_render_bucket_table(sorted([b for b in by_hour.values() if b.count >= 3], key=lambda b: b.net_pnl)[:5])}
    </section>
  </div>
</body>
</html>
"""


def analyse_client(client_id: str, min_trades: int = 3) -> Tuple[str, dict]:
    from dashboard.database import get_client_data

    data = get_client_data(client_id) or {}
    raw_deals = data.get("deals") or []
    filtered = _filter_trade_deals(raw_deals)
    trades = _build_trades(filtered)
    overall = _stats_from_trades(trades)

    by_dow = _bucket_trades(trades, lambda t: DOW_NAMES[t.entry_dt.weekday()])
    by_hour = _bucket_trades(trades, lambda t: f"{t.entry_dt.hour:02d}:00")
    by_dir = _bucket_trades(trades, lambda t: t.direction)
    by_symbol = _bucket_trades(trades, lambda t: t.symbol or "?")

    by_dir_dow: Dict[Tuple[str, str], BucketStats] = {}
    by_dir_hour: Dict[Tuple[str, str], BucketStats] = {}
    for t in trades:
        k1 = (t.direction, DOW_NAMES[t.entry_dt.weekday()])
        if k1 not in by_dir_dow:
            by_dir_dow[k1] = BucketStats(label=f"{k1[0]} · {k1[1]}")
        by_dir_dow[k1].add(t.net_pnl)
        k2 = (t.direction, f"{t.entry_dt.hour:02d}:00")
        if k2 not in by_dir_hour:
            by_dir_hour[k2] = BucketStats(label=f"{k2[0]} @ {k2[1]}")
        by_dir_hour[k2].add(t.net_pnl)

    tips = _build_recommendations(overall, by_dow, by_hour, by_dir, by_dir_hour, min_trades)

    html_out = render_html_report(
        client_id, trades, len(raw_deals), overall,
        by_dow, by_hour, by_dir, by_symbol, by_dir_dow, by_dir_hour, tips,
    )
    meta = {
        "trades": len(trades),
        "deals": len(raw_deals),
        "filtered_deals": len(filtered),
        "net_pnl": overall.net_pnl,
        "win_rate": overall.win_rate,
    }
    return html_out, meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse dashboard trade history and write HTML report")
    parser.add_argument("client", help='Client name (e.g. Aaron or "Brian Shore")')
    parser.add_argument("--output", "-o", help="Output HTML path (default: reports/trade_analysis_<client>.html)")
    parser.add_argument("--min-trades", type=int, default=3, help="Minimum trades per bucket for ranked insights (default: 3)")
    parser.add_argument("--open", action="store_true", help="Open the report in the default browser")
    args = parser.parse_args()

    client_id = _resolve_client_id(args.client)
    html_report, meta = analyse_client(client_id, min_trades=args.min_trades)

    reports_dir = os.path.join(_ROOT, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in client_id)
    out_path = args.output or os.path.join(reports_dir, f"trade_analysis_{safe}.html")
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_report)

    print(f"Client:     {client_id}")
    print(f"Deals:      {meta['deals']} raw, {meta['filtered_deals']} trade legs, {meta['trades']} round-trips")
    print(f"Win rate:   {meta['win_rate']:.1f}%")
    print(f"Net P/L:    ${meta['net_pnl']:,.2f}")
    print(f"Report:     {out_path}")

    if args.open:
        webbrowser.open(f"file:///{out_path.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
