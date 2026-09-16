"""Generate a JSON-only FTMO Futures Pro first-cycle simulation."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trader_companion.prop_firm_manager import PropFirmManager


STARTING_BALANCE = 50000.0
NQ_TICK_DOLLARS = 10.0
MNQ_TICK_DOLLARS = 1.5


def _nq_config():
    return {
        "tradovate_symbol": "NQZ6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 200,
        "tradovate_sl_ticks": 95,
    }


def _mnq_config():
    return {
        "tradovate_symbol": "MNQZ6",
        "tradovate_qty": 3,
        "tradovate_tp_ticks": 138,
        "tradovate_sl_ticks": 500,
    }


def run_simulation(account_count=20, seed=20260915, json_path=None):
    random.seed(seed)
    outcomes = random.Random(seed + 1)
    manager = PropFirmManager()
    accounts = []
    events = []

    for number in range(1, account_count + 1):
        account = f"FTMO-PRO-{number:03d}"
        balance = STARTING_BALANCE
        account_events = []
        status = "complete"
        reason = "completed FT1 and FT2+ cycle"

        ft1 = manager.randomize_trade_config(
            "FTMO Futures Pro", "funded_trade1", _nq_config(),
            account_key=account, balance=balance)
        ft1_tp = int(ft1["tradovate_tp_ticks"])
        ft1_sl = int(ft1["tradovate_sl_ticks"])
        ft1_win = outcomes.random() < 0.70
        ft1_next = balance + (ft1_tp * NQ_TICK_DOLLARS if ft1_win
                              else -ft1_sl * NQ_TICK_DOLLARS)
        event = {
            "account": account,
            "trade": "funded_trade1",
            "event": "FD1",
            "balance": balance,
            "target_profit_dollars": ft1["_randomization"]["target_profit_dollars"],
            "tp_ticks": ft1_tp,
            "sl_ticks": ft1_sl,
            "outcome": "WIN" if ft1_win else "LOSS",
            "next_balance": ft1_next,
        }
        events.append(event)
        account_events.append(event)
        balance = ft1_next

        if not ft1_win:
            status = "failed"
            reason = "FD1 loss"
        else:
            for day in range(1, 5):
                farm = manager.randomize_trade_config(
                    "FTMO Futures Pro", "farming", _mnq_config(),
                    account_key=account, balance=balance)
                farm_tp = int(farm["tradovate_tp_ticks"])
                farm_sl = int(farm["tradovate_sl_ticks"])
                farm_win = outcomes.random() < 0.80
                farm_next = balance + (farm_tp * MNQ_TICK_DOLLARS if farm_win
                                       else -farm_sl * MNQ_TICK_DOLLARS)
                event = {
                    "account": account,
                    "trade": f"farming_day{day}",
                    "event": f"FARM {day}",
                    "balance": balance,
                    "tp_ticks": farm_tp,
                    "sl_ticks": farm_sl,
                    "farm_sl_base": farm["_randomization"]["farm_sl_base"],
                    "farm_sl_jitter": farm["_randomization"]["farm_sl_jitter"],
                    "outcome": "WIN" if farm_win else "LOSS",
                    "next_balance": farm_next,
                }
                events.append(event)
                account_events.append(event)
                balance = farm_next

            payout = max(0.0, balance - 51000.0)
            payout_event = {
                "account": account,
                "event": "PAYOUT 1",
                "balance": balance,
                "payout_amount": payout,
                "retained_balance": balance - payout,
                "outcome": "PAYOUT",
            }
            events.append(payout_event)
            account_events.append(payout_event)
            balance -= payout

            ft2 = manager.randomize_trade_config(
                "FTMO Futures Pro", "funded_trade2", _nq_config(),
                account_key=account, balance=balance)
            ft2_tp = int(ft2["tradovate_tp_ticks"])
            ft2_sl = int(ft2["tradovate_sl_ticks"])
            ft2_win = outcomes.random() < 0.70
            ft2_next = balance + (ft2_tp * NQ_TICK_DOLLARS if ft2_win
                                  else -ft2_sl * NQ_TICK_DOLLARS)
            event = {
                "account": account,
                "trade": "funded_trade2",
                "event": "FD2",
                "balance": balance,
                "target_dollars": ft2["_randomization"]["target_dollars"],
                "tp_ticks": ft2_tp,
                "sl_ticks": ft2_sl,
                "outcome": "WIN" if ft2_win else "LOSS",
                "next_balance": ft2_next,
            }
            events.append(event)
            account_events.append(event)
            balance = ft2_next
            if not ft2_win:
                status = "failed"
                reason = "FD2 loss"

        accounts.append({
            "account": account,
            "status": status,
            "final_balance": balance,
            "reason": reason,
        })

    payload = {
        "seed": seed,
        "firm": "FTMO Futures Pro 50K",
        "account_size": "$50,000",
        "accounts": accounts,
        "events": events,
    }
    if json_path:
        Path(json_path).write_text(json.dumps(payload, indent=2) + "\n",
                                   encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--accounts", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--json", default="tests/ftmo_futures_pro_cycle.json")
    args = parser.parse_args()
    run_simulation(args.accounts, args.seed, args.json)
    print(f"JSON_OUTPUT {args.json}")


if __name__ == "__main__":
    main()
