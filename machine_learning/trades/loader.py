"""Load MT5 deals from TradeOpss Postgres (clients_data.deals)."""
from __future__ import annotations

import sys
from typing import List, Optional

import pandas as pd

from machine_learning.trades.builder import build_trades, filter_trade_deals
from machine_learning.trades.models import Trade


def _all_client_id_list() -> List[str]:
    from dashboard.database import get_all_clients

    data = get_all_clients()
    if isinstance(data, dict) and data:
        return sorted(data.keys())
    from dashboard.database import get_connection

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT client_id FROM clients_data ORDER BY client_id")
        return [r["client_id"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]


def resolve_client_id(query: str) -> str:
    q = (query or "").strip()
    if not q:
        raise ValueError("Client name is required.")

    clients = _all_client_id_list()

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
        raise ValueError(f"Ambiguous client {q!r}. Matches: {', '.join(matches[:15])}")
    raise ValueError(f"Client {q!r} not found.")


def list_client_ids() -> List[str]:
    return _all_client_id_list()


def load_client_deals(client_id: str) -> List[dict]:
    from dashboard.database import get_client_data

    data = get_client_data(client_id) or {}
    return data.get("deals") or []


def trades_to_records(trades: List[Trade]) -> List[dict]:
    rows = []
    for t in trades:
        hold = (t.exit_dt - t.entry_dt).total_seconds() / 60.0
        rows.append(
            {
                "client_id": t.client_id,
                "position_id": str(t.position_id),
                "symbol": t.symbol,
                "direction": t.direction,
                "volume": t.volume,
                "entry_time": t.entry_dt,
                "exit_time": t.exit_dt,
                "hold_minutes": round(hold, 2),
                "net_pnl": t.net_pnl,
                "deal_count": t.deal_count,
            }
        )
    return rows


def load_client_trades_df(client_id: str) -> pd.DataFrame:
    raw = load_client_deals(client_id)
    filtered = filter_trade_deals(raw)
    trades = build_trades(client_id, filtered)
    if not trades:
        return pd.DataFrame()
    return pd.DataFrame(trades_to_records(trades))


def load_all_trades_df(client_ids: Optional[List[str]] = None) -> pd.DataFrame:
    ids = client_ids or list_client_ids()
    frames = []
    for cid in ids:
        try:
            df = load_client_trades_df(cid)
            if not df.empty:
                frames.append(df)
        except Exception as exc:
            print(f"[ml] skip {cid}: {exc}", file=sys.stderr)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
