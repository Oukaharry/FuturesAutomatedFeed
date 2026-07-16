#!/usr/bin/env python3
"""Compare classic vs split funded SL on historical MT5 hedge round-trips.

MT5 legs are hedges (inverted vs Tradovate prop). Prop direction / TP / SL
are derived from the hedge entry (opposite side; hedge TP = prop SL distance).

Usage (from repo root):
    python scripts/analyze_funded_sl_modes.py
    python scripts/analyze_funded_sl_modes.py --html research/reports/funded_sl_mode_analysis.html
"""
from __future__ import annotations

import argparse
import html
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))
load_dotenv()

try:
    import MetaTrader5 as mt5
except ImportError:
    print("pip install MetaTrader5", file=sys.stderr)
    sys.exit(1)

from config.settings import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER
from trader_companion.mt5_comment_parser import MT5CommentParser, Phase
from trader_companion.signals.trade_simulator import walk_tp_sl

FUNDED_TRADE1_SL = 2000.0
LOCK_LEVEL = 50000.0
START_BALANCE = 50000.0
TICK_VALUE = 5.0  # $ per 0.25pt tick per NQ contract
DEFAULT_QTY = 2
POINTS_PER_DOLLAR_PER_CONTRACT = 20.0  # NQ: $20 per index point per lot
MAX_WALK_DAYS = 365

MT5_TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
SYMBOL_ALIASES = ("ustech", "USTECH", "US100", "NAS100")


def connect_mt5() -> bool:
    init = (
        mt5.initialize(path=MT5_TERMINAL)
        if os.path.isfile(MT5_TERMINAL)
        else mt5.initialize()
    )
    if not init:
        print("MT5 initialize failed:", mt5.last_error())
        return False
    if not mt5.login(int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER):
        print("MT5 login failed:", mt5.last_error())
        return False
    ai = mt5.account_info()
    print(f"Connected MT5 #{ai.login if ai else MT5_LOGIN} @ {MT5_SERVER}")
    return True


def resolve_symbol() -> str:
    for sym in SYMBOL_ALIASES:
        if mt5.symbol_info(sym) is not None:
            return sym
    return "ustech"


def deal_rows(days: int = MAX_WALK_DAYS) -> List[dict]:
    frm = time.time() - days * 86400
    raw = mt5.history_deals_get(frm, time.time() + 86400)
    if not raw:
        return []
    order_cache: Dict[int, dict] = {}

    def order_sl_tp(order_id: int) -> Tuple[float, float]:
        if not order_id:
            return 0.0, 0.0
        if order_id not in order_cache:
            sl = tp = 0.0
            try:
                ords = mt5.history_orders_get(ticket=order_id)
                if ords:
                    sl = float(ords[0].sl or 0)
                    tp = float(ords[0].tp or 0)
            except Exception:
                pass
            order_cache[order_id] = {"sl": sl, "tp": tp}
        o = order_cache[order_id]
        return float(o["sl"]), float(o["tp"])

    out = []
    for d in raw:
        sl, tp = order_sl_tp(int(d.order or 0))
        out.append({
            "ticket": d.ticket,
            "position_id": d.position_id,
            "order": d.order,
            "symbol": d.symbol,
            "type": int(d.type),
            "entry": int(d.entry),
            "time": int(d.time),
            "price": float(d.price),
            "volume": float(d.volume),
            "profit": float(d.profit),
            "commission": float(d.commission),
            "swap": float(d.swap),
            "fee": float(d.fee),
            "sl": sl,
            "tp": tp,
            "comment": d.comment or "",
        })
    return out


def round_trips(deals: List[dict]) -> List[dict]:
    parser = MT5CommentParser()
    by_pos: Dict[int, List[dict]] = defaultdict(list)
    for d in deals:
        if d["type"] in (2, 3, 4, 5, 6):
            continue
        pid = int(d.get("position_id") or 0)
        if pid:
            by_pos[pid].append(d)

    rows = []
    for pid, dl in by_pos.items():
        entry = None
        exit_d = None
        has_exit = False
        net = 0.0
        for d in dl:
            e = d["entry"]
            if e == 0 and entry is None:
                entry = d
            if e in (1, 2, 3):
                has_exit = True
                if exit_d is None or d["time"] >= exit_d["time"]:
                    exit_d = d
            net += d["profit"] + d["commission"] + d["swap"] + d["fee"]
        if not has_exit or not entry:
            continue
        parsed = parser.parse(entry["comment"])
        if not parsed.is_valid or parsed.phase != Phase.FUNDED:
            continue
        hedge_side = "BUY" if entry["type"] == 0 else "SELL"
        prop_side = "sell" if hedge_side == "BUY" else "buy"
        ep = float(entry["price"])
        h_tp = float(entry["tp"] or exit_d.get("tp") or 0)
        h_sl = float(entry["sl"] or exit_d.get("sl") or 0)
        if h_tp and h_sl and ep:
            prop_sl_pts = abs(ep - h_tp)
            prop_tp_pts = abs(h_sl - ep)
        else:
            prop_sl_pts = prop_tp_pts = 0.0
        tn = parsed.trade_number if parsed.trade_number is not None else 1
        if tn <= 0:
            tn = 1
        rows.append({
            "position_id": pid,
            "account": parsed.account_number,
            "trade_num": tn,
            "comment": entry["comment"],
            "entry_ts": entry["time"],
            "entry_time": datetime.fromtimestamp(entry["time"], tz=timezone.utc),
            "entry_price": ep,
            "close_price": float(exit_d["price"]),
            "hedge_side": hedge_side,
            "prop_side": prop_side,
            "prop_tp_pts": round(prop_tp_pts, 2),
            "prop_sl_pts": round(prop_sl_pts, 2),
            "mt5_net": round(net, 2),
            "prop_pnl_est": round(-net, 2),
            "symbol": entry.get("symbol") or "",
        })
    rows.sort(key=lambda r: (r["account"] or "", r["entry_ts"]))
    return rows


def sl_dollars_to_pts(dollars: float, qty: int = DEFAULT_QTY) -> float:
    if dollars <= 0 or qty <= 0:
        return 0.0
    return dollars / (qty * POINTS_PER_DOLLAR_PER_CONTRACT)


def assign_cycle_balance(trades: List[dict]) -> None:
    """Attach cycle balance / profit cushion before each trade (same account)."""
    by_acct: Dict[str, List[dict]] = defaultdict(list)
    for t in trades:
        by_acct[t["account"] or "?"].append(t)
    for acct, seq in by_acct.items():
        balance = START_BALANCE
        for t in seq:
            tn = int(t["trade_num"] or 1)
            if tn <= 1:
                balance = START_BALANCE
            t["balance_before"] = balance
            t["cycle_profit_before"] = max(0.0, balance - LOCK_LEVEL)
            if tn <= 1:
                classic_sl = FUNDED_TRADE1_SL
                split_sl = FUNDED_TRADE1_SL
            else:
                classic_sl = max(FUNDED_TRADE1_SL, balance - LOCK_LEVEL)
                split_sl = FUNDED_TRADE1_SL + max(0.0, balance - LOCK_LEVEL)
            t["classic_sl_dollars"] = round(classic_sl, 2)
            t["split_sl_dollars"] = round(split_sl, 2)
            t["classic_sl_pts"] = round(sl_dollars_to_pts(classic_sl), 2)
            t["split_sl_pts"] = round(sl_dollars_to_pts(split_sl), 2)
            balance += float(t.get("prop_pnl_est") or 0)


def outcome_from_close(t: dict, sl_pts: float) -> str:
    """First-touch proxy using exit price (when M1 history is unavailable)."""
    tp_pts = float(t["prop_tp_pts"] or 0)
    if tp_pts <= 0 or sl_pts <= 0:
        return "unknown"
    ep = float(t["entry_price"])
    cp = float(t["close_price"])
    side = t["prop_side"]
    if side == "buy":
        if cp >= ep + tp_pts:
            return "tp"
        if cp <= ep - sl_pts:
            return "sl"
    else:
        if cp <= ep - tp_pts:
            return "tp"
        if cp >= ep + sl_pts:
            return "sl"
    return "none"


def walk_outcome(t: dict, sym: str, sl_pts: float) -> str:
    tp_pts = float(t["prop_tp_pts"] or 0)
    if tp_pts <= 0 or sl_pts <= 0:
        return "unknown"
    entry_ts = int(t["entry_ts"])
    m1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 50000)
    if m1 is not None and len(m1) > 10:
        earliest = int(m1[0][0])
        if earliest <= entry_ts:
            bars = [r for r in m1 if int(r[0]) >= entry_ts - 60]
            if len(bars) >= 2:
                w = walk_tp_sl(
                    entry_ts, t["entry_price"], t["prop_side"],
                    tp_pts, sl_pts, bars, symbol=sym,
                )
                out = w.get("outcome") or "none"
                if out in ("tp", "sl"):
                    return out
                mfe = float(w.get("mfe_points") or 0)
                mae = float(w.get("mae_points") or 0)
                if mfe >= tp_pts:
                    return "tp"
                if mae >= sl_pts:
                    return "sl"
                return out
    return outcome_from_close(t, sl_pts)


def analyze(trades: List[dict], sym: str) -> Dict[str, Any]:
    assign_cycle_balance(trades)
    results = []
    for i, t in enumerate(trades):
        if i and i % 20 == 0:
            print(f"  walking M1 {i}/{len(trades)}...")
        actual_sl = float(t["prop_sl_pts"] or 0)
        classic_sl = float(t["classic_sl_pts"] or 0)
        split_sl = float(t["split_sl_pts"] or 0)
        actual_out = walk_outcome(t, sym, actual_sl) if actual_sl > 0 else "unknown"
        classic_out = walk_outcome(t, sym, classic_sl) if classic_sl > 0 else "unknown"
        split_out = walk_outcome(t, sym, split_sl) if split_sl > 0 else "unknown"
        results.append({**t, "actual_outcome": actual_out,
                        "classic_outcome": classic_out, "split_outcome": split_out})

    def agg(rows, key):
        tp = sum(1 for r in rows if r[key] == "tp")
        sl = sum(1 for r in rows if r[key] == "sl")
        unk = sum(1 for r in rows if r[key] not in ("tp", "sl"))
        return {"tp": tp, "sl": sl, "unknown": unk, "n": len(rows)}

    all_t = results
    t2p = [r for r in results if int(r["trade_num"] or 1) >= 2]
    flipped = [
        r for r in t2p
        if r["classic_outcome"] == "sl" and r["split_outcome"] == "tp"
    ]
    hurt = [
        r for r in t2p
        if r["classic_outcome"] == "tp" and r["split_outcome"] == "sl"
    ]

    return {
        "results": results,
        "summary": {
            "total_funded": len(all_t),
            "trade2_plus": len(t2p),
            "actual": agg(all_t, "actual_outcome"),
            "classic": agg(all_t, "classic_outcome"),
            "split": agg(all_t, "split_outcome"),
            "classic_t2": agg(t2p, "classic_outcome"),
            "split_t2": agg(t2p, "split_outcome"),
            "split_saves": len(flipped),
            "split_hurts": len(hurt),
            "flipped_rows": flipped,
            "hurt_rows": hurt,
        },
    }


def render_html(data: Dict[str, Any], sym: str) -> str:
    s = data["summary"]
    rows = data["results"]
    gen = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    def tbl(title, items):
        if not items:
            return f"<h3>{html.escape(title)}</h3><p>None</p>"
        keys = list(items[0].keys())
        hdr = "".join(f"<th>{html.escape(k)}</th>" for k in keys)
        body = ""
        for it in items[:50]:
            body += "<tr>" + "".join(
                f"<td>{html.escape(str(it.get(k, '')))}</td>" for k in keys) + "</tr>"
        return f"<h3>{html.escape(title)}</h3><table><tr>{hdr}</tr>{body}</table>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Funded SL mode analysis</title>
<style>
body{{font-family:Segoe UI,sans-serif;background:#0f172a;color:#e2e8f0;padding:24px}}
table{{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}}
th,td{{border:1px solid #334155;padding:6px 8px;text-align:left}}
th{{background:#1e293b}} .win{{color:#4ade80}} .loss{{color:#f87171}}
.card{{background:#1e293b;border-radius:8px;padding:16px;margin:12px 0}}
</style></head><body>
<h1>Classic vs Split Funded SL — MT5 hedge history</h1>
<p>Account #{MT5_LOGIN} · symbol {html.escape(sym)} · {gen}</p>
<p>Prop leg inferred by inverting MT5 hedge (hedge TP distance = prop SL, hedge SL = prop TP).</p>
<div class="card">
<h2>Summary</h2>
<ul>
<li>Funded round-trips: <b>{s['total_funded']}</b> (trade 2+: <b>{s['trade2_plus']}</b>)</li>
<li>Actual walk: TP {s['actual']['tp']} / SL {s['actual']['sl']} / unknown {s['actual']['unknown']}</li>
<li>Classic SL sim: TP {s['classic']['tp']} / SL {s['classic']['sl']}</li>
<li>Split SL sim: TP {s['split']['tp']} / SL {s['split']['sl']}</li>
<li class="win">Trade 2+ split would have saved (classic SL → split TP): <b>{s['split_saves']}</b></li>
<li class="loss">Trade 2+ split would have hurt (classic TP → split SL): <b>{s['split_hurts']}</b></li>
</ul>
<p><b>Verdict:</b> {"Split mode likely better on trade 2+" if s['split_saves'] > s['split_hurts'] else "Classic mode safer or equivalent" if s['split_saves'] == s['split_hurts'] else "Classic mode better on historical paths"}</p>
</div>
{tbl("Trade 2+ — split would have reached TP (classic stopped out)", s['flipped_rows'])}
{tbl("Trade 2+ — split would have stopped out (classic reached TP)", s['hurt_rows'])}
{tbl("All funded trades (sample)", rows[:80])}
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default=os.path.join(ROOT, "research", "reports", "funded_sl_mode_analysis.html"))
    ap.add_argument("--days", type=int, default=MAX_WALK_DAYS)
    args = ap.parse_args()

    if not connect_mt5():
        sys.exit(1)
    try:
        sym = resolve_symbol()
        deals = deal_rows(args.days)
        trips = round_trips(deals)
        print(f"Deals: {len(deals)} | Funded round-trips: {len(trips)}")
        if not trips:
            print("No funded round-trips found in history.")
            return
        data = analyze(trips, sym)
        s = data["summary"]
        print(f"Actual: TP={s['actual']['tp']} SL={s['actual']['sl']}")
        print(f"Classic sim: TP={s['classic']['tp']} SL={s['classic']['sl']}")
        print(f"Split sim: TP={s['split']['tp']} SL={s['split']['sl']}")
        print(f"Trade2+ split saves={s['split_saves']} hurts={s['split_hurts']}")

        os.makedirs(os.path.dirname(args.html) or ".", exist_ok=True)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(render_html(data, sym))
        print(f"Report: {args.html}")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
