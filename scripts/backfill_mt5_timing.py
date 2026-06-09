"""One-off: persist identity.mt5_timing for all clients with deal history."""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_env = os.path.join(_ROOT, ".env")
if os.path.isfile(_env):
    for line in open(_env, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    from research.trade_dataset import backfill_mt5_timing_for_all_clients

    stats = backfill_mt5_timing_for_all_clients()
    total = stats.get("clients_with_deals", 0)
    calibrated = stats.get("already_calibrated", 0) + stats.get("backfilled", 0)
    print("mt5_timing backfill:", stats)
    print(f"calibrated coverage: {calibrated}/{total}")
    return 0 if stats.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
