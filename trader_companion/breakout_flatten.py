"""Re-authenticate the open Breakout tab (enchanted link) and flatten a position.

    python -m trader_companion.breakout_flatten [--trade-id XTNS...] [--email ...]
"""

import argparse
import json
import os
import time

from trader_companion import breakout_probe as bp
from trader_companion.breakout_api import BreakoutBrowserAPI
from trader_companion.cdp_capture import CDPCapture


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--email", default=os.environ.get("BREAKOUT_EMAIL", "joehickenfpf@gmail.com"))
    p.add_argument("--trade-id", default=None, help="position trade id; default = close every open position")
    a = p.parse_args()

    bp.launch_chrome()
    api = BreakoutBrowserAPI()
    st, _, d = api.get("/session/expiration")
    if st != 200:
        api.close()
        cap = CDPCapture(bp.PORT, bp.HOSTS, "/tmp/breakout_capture/relogin", url_hint="breakoutprop.com").start()
        ok = bp.email_login(cap, a.email)
        cap.stop()
        if not ok:
            return 1
        time.sleep(6)
        api = BreakoutBrowserAPI()
    api.accounts()
    aid = api.account_id
    print("account:", aid)
    s = api.overview().get("summary", {})
    print(f"before: balance {s['balance']['amount']}  equity {s['equity']['amount']}  "
          f"upnl {s['upnl']['amount']}  used_margin {s['used_margin']['amount']}")
    if float(s["used_margin"]["amount"]) <= 0:
        print("no margin in use — nothing open (TP/SL already closed it)")
    else:
        ids = [a.trade_id] if a.trade_id else []
        if not ids:
            st, _, d = api.get(f"/positions?account_id={aid}")
            ids = [x.get("trade_id") or x.get("id") for x in ((d or {}).get("result") or []) if isinstance(x, dict)]
        for tid in ids:
            st, d = api.close_position(tid)
            print(f"CLOSE {tid} -> {st} {json.dumps(d)[:300]}")
        time.sleep(3)
        s = api.overview().get("summary", {})
        print(f"after : balance {s['balance']['amount']}  equity {s['equity']['amount']}  "
              f"upnl {s['upnl']['amount']}  used_margin {s['used_margin']['amount']}")
    st, _, d = api.get(f"/breakout/v1/accounts/trading-summary?account_id={aid}")
    print("summary:", json.dumps({k: (v.get("amount") if isinstance(v, dict) else v)
                                  for k, v in (d.get("result") or {}).items()})[:500])
    api.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
