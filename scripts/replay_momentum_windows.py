"""
Print today's 15m momentum regimes from M1 USTECH data.

Usage:
  python scripts/replay_momentum_windows.py
  python scripts/replay_momentum_windows.py --limit 120000
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_env = os.path.join(ROOT, ".env")
if os.path.isfile(_env):
    with open(_env, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=120000)
    parser.add_argument("--symbol", default="USTECH")
    args = parser.parse_args()

    from dashboard.ml_predictions_service import fetch_m1_bars_for_ml
    from research.momentum_forecast import detect_momentum_windows_m15, run_momentum_forecast
    from research.market_signals import bars_list_to_m1_df

    bars = fetch_m1_bars_for_ml(symbol=args.symbol, limit=args.limit)
    if not bars:
        print("No M1 bars in database.")
        return 1

    fc = run_momentum_forecast(bars)
    pred = fc.get("prediction") or {}
    regimes = fc.get("m15_regimes") or detect_momentum_windows_m15(bars_list_to_m1_df(bars))

    print("=" * 60)
    print(f"USTECH momentum replay ({len(bars):,} M1 bars)")
    print("=" * 60)
    print(f"Bias:        {pred.get('bias')}")
    print(f"Window:      {pred.get('momentum_window') or pred.get('best_entry_window')}")
    print(f"Entry note:  {pred.get('entry_note', '')[:120]}")
    print()
    print("Today's 15m regimes (EAT / UTC+3):")
    for w in regimes.get("windows") or []:
        tag = " [ACTIVE]" if w.get("active") else ""
        print(
            f"  {w.get('range_display')}{tag}  "
            f"bars={w.get('bars')} move={w.get('move_pct'):+.2f}%"
        )
    if not regimes.get("windows"):
        print("  (none)")
    print()
    print("Full prediction JSON (truncated):")
    print(json.dumps({k: pred.get(k) for k in (
        "bias", "momentum_window", "windows_today", "confidence", "entry_note"
    )}, indent=2, default=str)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
