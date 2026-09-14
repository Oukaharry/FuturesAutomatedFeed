"""Standalone diagnostic: capture Tradovate's live websocket traffic.

Run this directly (not through the main app) against a real Tradovate
account to see what messages the web app's own websocket(s) carry. The
goal is to find the quote/chart message format so it can eventually
replace the MT5 price feed used for AI signal decisions.

Usage:
    python trader_companion/sniff_tradovate_ws.py --seconds 120

You will be prompted for your Tradovate username and password directly in
the terminal (password input is hidden) — never pass them as CLI flags.

Leave the Chrome window open on a live chart/DOM for the full duration so
the market-data socket has time to stream ticks/bars. Afterwards, inspect
the output .jsonl file (one JSON object per line: ts, direction, socket_url,
payload) to identify the market-data socket among auth/heartbeat traffic.
"""
import argparse
import getpass
import os

# Must be set before TradovateAccount launches Chrome — logging prefs are a
# launch-time capability and cannot be enabled after the fact.
os.environ.setdefault("TRADOVATE_WS_SNIFF", "1")

from trader_companion.tradovate import TradovateAccount


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=120,
                         help="Capture duration in seconds (default 120)")
    parser.add_argument("--filter", default=None,
                         help="Only capture frames containing this substring")
    parser.add_argument("--out", default=None,
                         help="Output .jsonl path (default: auto-named)")
    args = parser.parse_args()

    username = input("Tradovate username: ").strip()
    password = getpass.getpass("Tradovate password (hidden): ")

    acct = TradovateAccount(username, password)
    print(f"Logging into Tradovate as {username}...")
    acct.login()

    print(f"Capturing websocket frames for {args.seconds}s — "
          f"leave the chart open and let it run...")
    out_path, count, urls = acct.sniff_websocket_frames(
        duration_sec=args.seconds, out_path=args.out, text_filter=args.filter)

    print(f"\nCaptured {count} frame(s) -> {out_path}")
    print("Distinct websocket URLs seen:")
    for u in sorted(urls):
        print(f"  {u}")


if __name__ == "__main__":
    main()
