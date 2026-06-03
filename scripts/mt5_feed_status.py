#!/usr/bin/env python3
"""
Print MT5 M1 feed cache status (poll-only, no WebSocket).

Requires MT5 connected. Start feed first via companion or:
  python scripts/mt5_feed_status.py --start --symbols ustech
"""

from __future__ import annotations

import argparse
import json
import sys
import time

ROOT = __file__.replace("\\", "/").rsplit("/", 2)[0]
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    p = argparse.ArgumentParser(description="MT5 M1 feed cache status")
    p.add_argument("--start", action="store_true", help="Start feed if not running")
    p.add_argument("--symbols", default="ustech", help="Comma-separated symbols")
    p.add_argument("--wait", type=float, default=3.0, help="Seconds to wait after start")
    args = p.parse_args()

    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("Install MetaTrader5: pip install MetaTrader5", file=sys.stderr)
        return 1

    if not mt5.initialize():
        print("MT5 not connected — open terminal and log in first.", file=sys.stderr)
        return 1

    from trader_companion.mt5_market_feed import (
        format_market_feed_status_for_user,
        get_market_feed_status,
        start_mt5_market_feed,
    )

    if args.start:
        syms = [s.strip() for s in args.symbols.split(",") if s.strip()]
        start_mt5_market_feed(syms)
        time.sleep(max(0.5, args.wait))

    print(format_market_feed_status_for_user())
    snap = get_market_feed_status()
    print(json.dumps(snap, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
