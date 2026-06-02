"""Trading metrics on round-trip / daily P&L series (Inglese-style backtest stats)."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd


def daily_equity_from_trades(trades: pd.DataFrame, pnl_col: str = "net_pnl") -> pd.Series:
    """Cumulative P&L by calendar close date."""
    if trades.empty or "close_time" not in trades.columns:
        return pd.Series(dtype=float)
    t = trades.dropna(subset=["close_time"]).copy()
    t["date"] = pd.to_datetime(t["close_time"]).dt.date
    daily = t.groupby("date")[pnl_col].sum().sort_index()
    return daily.cumsum()


def trade_level_metrics(trades: pd.DataFrame, pnl_col: str = "net_pnl") -> Dict[str, float]:
    """Classic metrics from a list of closed trades."""
    if trades.empty:
        return {"n_trades": 0}

    pnl = trades[pnl_col].astype(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    n = len(pnl)

    gross_win = wins.sum() if len(wins) else 0.0
    gross_loss = abs(losses.sum()) if len(losses) else 0.0

    return {
        "n_trades": n,
        "win_rate_pct": round(100 * len(wins) / n, 2) if n else 0.0,
        "total_pnl": round(float(pnl.sum()), 2),
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "profit_factor": float(round(gross_win / gross_loss, 2)) if gross_loss > 0 else 0.0,
        "expectancy": round(float(pnl.mean()), 2) if n else 0.0,
        "largest_win": round(float(wins.max()), 2) if len(wins) else 0.0,
        "largest_loss": round(float(losses.min()), 2) if len(losses) else 0.0,
    }


def max_drawdown(equity: pd.Series) -> Tuple[float, float]:
    """Return (max_drawdown_abs, max_drawdown_pct_of_peak)."""
    if equity.empty or len(equity) < 2:
        return 0.0, 0.0
    peak = equity.cummax()
    dd = equity - peak
    max_dd = float(dd.min())
    peak_at = float(peak.max()) if float(peak.max()) != 0 else 1.0
    return round(max_dd, 2), round(100 * max_dd / abs(peak_at), 2) if peak_at else 0.0


def sharpe_daily(daily_pnl: pd.Series, periods_per_year: int = 252) -> float:
    """Annualized Sharpe from daily P&L (not log returns)."""
    if daily_pnl.empty or len(daily_pnl) < 2 or daily_pnl.std() == 0:
        return 0.0
    return round(float(daily_pnl.mean() / daily_pnl.std() * np.sqrt(periods_per_year)), 2)


def walk_forward_summary(
    trades: pd.DataFrame,
    train_frac: float = 0.7,
    pnl_col: str = "net_pnl",
) -> Dict[str, object]:
    """
    Simple time-ordered train/test split (book-style out-of-sample check).
    """
    if trades.empty or "close_time" not in trades.columns:
        return {}
    t = trades.dropna(subset=["close_time"]).sort_values("close_time")
    split = int(len(t) * train_frac)
    if split < 10 or len(t) - split < 5:
        return {"note": "insufficient trades for walk-forward"}

    train, test = t.iloc[:split], t.iloc[split:]
    m_train = trade_level_metrics(train, pnl_col)
    m_test = trade_level_metrics(test, pnl_col)
    return {
        "train_trades": m_train["n_trades"],
        "test_trades": m_test["n_trades"],
        "train_win_rate_pct": m_train["win_rate_pct"],
        "test_win_rate_pct": m_test["win_rate_pct"],
        "train_expectancy": m_train["expectancy"],
        "test_expectancy": m_test["expectancy"],
        "train_profit_factor": m_train["profit_factor"],
        "test_profit_factor": m_test["profit_factor"],
    }
