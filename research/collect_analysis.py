"""Gather structured metrics from stored MT5 deals (for HTML/text reports)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd

from research.backtest_metrics import (
    daily_equity_from_trades,
    max_drawdown,
    sharpe_daily,
    trade_level_metrics,
    walk_forward_summary,
)
from research.trade_dataset import deals_to_round_trips, load_clients_deals


def collect_analysis(client_filter: Optional[str] = None) -> Dict[str, Any]:
    """Run all analytics; caller must configure DB source first."""
    generated = datetime.now().isoformat(timespec="seconds")
    all_clients = load_clients_deals(client_filter)
    parts = []
    cov_rows = []
    for cid, deals in all_clients.items():
        if isinstance(deals, str):
            import json
            deals = json.loads(deals)
        n_deals = len(deals or [])
        if not n_deals:
            cov_rows.append(
                {
                    "client_id": cid,
                    "raw_deals": 0,
                    "round_trips": 0,
                    "parsed_comments": 0,
                    "parse_rate_pct": 0,
                    "total_net_pnl": 0,
                    "first_close": None,
                    "last_close": None,
                    "last_updated": None,
                }
            )
            continue
        rt = deals_to_round_trips(deals, client_id=cid)
        if not rt.empty:
            parts.append(rt)
        n_rt = len(rt)
        valid = int(rt["parse_valid"].sum()) if n_rt and "parse_valid" in rt.columns else 0
        pnl = float(rt["net_pnl"].sum()) if n_rt else 0.0
        cov_rows.append(
            {
                "client_id": cid,
                "raw_deals": n_deals,
                "round_trips": n_rt,
                "parsed_comments": valid,
                "parse_rate_pct": round(100 * valid / n_rt, 1) if n_rt else 0,
                "total_net_pnl": round(pnl, 2),
                "first_close": rt["close_time"].min() if n_rt and rt["close_time"].notna().any() else None,
                "last_close": rt["close_time"].max() if n_rt and rt["close_time"].notna().any() else None,
                "last_updated": None,
            }
        )
    cov = pd.DataFrame(cov_rows).sort_values("round_trips", ascending=False)
    with_rt = cov[cov["round_trips"] > 0]
    trades = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    coverage = {
        "total_clients": len(cov),
        "clients_with_trades": len(with_rt),
        "total_raw_deals": int(cov["raw_deals"].sum()),
        "total_round_trips": int(cov["round_trips"].sum()),
        "avg_parse_rate_pct": round(float(with_rt["parse_rate_pct"].mean()), 1) if len(with_rt) else None,
    }
    if trades.empty:
        return {
            "generated_at": generated,
            "client_filter": client_filter,
            "coverage": coverage,
            "empty": True,
            "portfolio": {},
            "risk": {},
            "walk_forward": {},
            "by_phase": pd.DataFrame(),
            "by_symbol": pd.DataFrame(),
            "by_hour": pd.DataFrame(),
            "clients_top": pd.DataFrame(),
            "clients_bottom": pd.DataFrame(),
            "insights": ["No round-trip trades found."],
            "coverage_table": cov,
        }

    parsed = trades[trades["parse_valid"] == True]  # noqa: E712
    portfolio = trade_level_metrics(trades)

    daily = trades.dropna(subset=["close_time"]).copy()
    daily["date"] = pd.to_datetime(daily["close_time"]).dt.date
    daily_pnl = daily.groupby("date")["net_pnl"].sum()
    eq = daily_equity_from_trades(trades)
    mdd_abs, mdd_pct = max_drawdown(eq)

    risk = {
        "trading_days": len(daily_pnl),
        "sharpe_daily": sharpe_daily(daily_pnl),
        "max_drawdown": mdd_abs,
        "max_drawdown_pct": mdd_pct,
    }

    wf = walk_forward_summary(trades)

    by_phase = pd.DataFrame()
    if "phase_code" in parsed.columns and len(parsed) > 0:
        by_phase = (
            parsed.groupby("phase_code", dropna=False)
            .agg(
                n=("net_pnl", "count"),
                total_pnl=("net_pnl", "sum"),
                win_rate=("net_pnl", lambda s: 100 * (s > 0).mean()),
                avg_pnl=("net_pnl", "mean"),
            )
            .round(2)
            .sort_values("n", ascending=False)
            .reset_index()
        )

    by_symbol = pd.DataFrame()
    if "symbol" in trades.columns:
        by_symbol = (
            trades.groupby("symbol")
            .agg(n=("net_pnl", "count"), total_pnl=("net_pnl", "sum"), avg=("net_pnl", "mean"))
            .round(2)
            .sort_values("n", ascending=False)
            .head(10)
            .reset_index()
        )

    by_hour = pd.DataFrame()
    hour_note = ""
    if "close_time" in parsed.columns and len(parsed) > 50:
        t = parsed.dropna(subset=["close_time"]).copy()
        t["hour"] = pd.to_datetime(t["close_time"]).dt.hour
        by_hour = (
            t.groupby("hour")
            .agg(n=("net_pnl", "count"), avg_pnl=("net_pnl", "mean"))
            .round(2)
            .reset_index()
        )
        if len(by_hour):
            best = by_hour.loc[by_hour["avg_pnl"].idxmax()]
            worst = by_hour.loc[by_hour["avg_pnl"].idxmin()]
            hour_note = (
                f"Best hour {int(best['hour'])} (avg ${best['avg_pnl']:,.2f}); "
                f"worst hour {int(worst['hour'])} (avg ${worst['avg_pnl']:,.2f})"
            )

    by_client = (
        trades.groupby("client_id")
        .agg(n=("net_pnl", "count"), total=("net_pnl", "sum"), wr=("net_pnl", lambda s: 100 * (s > 0).mean()))
        .round(2)
    )
    qualified = by_client[by_client["n"] >= 20].sort_values("total", ascending=False)
    clients_top = qualified.head(12).reset_index()
    clients_bottom = qualified.tail(8).sort_values("total").reset_index()

    insights = []
    if len(parsed) > 100 and "phase_code" in parsed.columns:
        for phase, row in parsed.groupby("phase_code")["net_pnl"].agg(["mean", "count"]).iterrows():
            if row["count"] >= 30:
                insights.append(
                    f"Phase <strong>{phase}</strong>: {int(row['count']):,} trades, "
                    f"avg P&amp;L <span class='{'pos' if row['mean'] >= 0 else 'neg'}'>${row['mean']:,.2f}</span>"
                )
    ch = parsed[parsed["phase_code"].astype(str).str.startswith("CH", na=False)]
    fd = parsed[parsed["phase_code"].astype(str).str.startswith("FD", na=False)]
    fa = parsed[parsed["phase_code"] == "FA"]
    if len(ch) >= 20 and len(fd) >= 20:
        insights.append(
            f"Challenge (CH) avg ${ch['net_pnl'].mean():,.2f} vs Funded (FD) avg ${fd['net_pnl'].mean():,.2f} on MT5 hedge legs"
        )
    if len(fa) >= 20:
        insights.append(f"Farming (FA): avg ${fa['net_pnl'].mean():,.2f} over {len(fa):,} trades")

    cov_display = (
        cov[cov["round_trips"] > 0]
        .sort_values("round_trips", ascending=False)
        .head(30)
        .reset_index(drop=True)
    )

    return {
        "generated_at": generated,
        "client_filter": client_filter,
        "empty": False,
        "coverage": coverage,
        "portfolio": portfolio,
        "risk": risk,
        "walk_forward": wf,
        "by_phase": by_phase,
        "by_symbol": by_symbol,
        "by_hour": by_hour,
        "hour_note": hour_note,
        "clients_top": clients_top,
        "clients_bottom": clients_bottom,
        "insights": insights or ["Insufficient data for insights."],
        "coverage_table": cov_display,
    }
