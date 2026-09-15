"""Generate a JSON-only MFFU Rapid EOD 50K lifecycle simulation."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trader_companion.prop_firm_manager import PropFirmManager


STARTING_BALANCE = 50000.0
RETAINED_BALANCE = 52100.0
LOCKED_FLOOR = 50100.0
TICK_DOLLARS = 15.0


def _calculate_payout(balance, cycle_start, funded_number):
    if funded_number == 4:
        payout = balance - LOCKED_FLOOR
        retained_balance = LOCKED_FLOOR
    else:
        cycle_profit = balance - cycle_start
        payout = math.floor(0.5 * cycle_profit)
        retained_balance = balance - payout
        if retained_balance < RETAINED_BALANCE:
            raise AssertionError(
                f"retained balance ${retained_balance:,.2f} below "
                f"minimum ${RETAINED_BALANCE:,.2f}")
    return payout, retained_balance


def _config():
    return {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 3,
        "tradovate_tp_ticks": 320,
        "tradovate_sl_ticks": 133,
    }


def run_simulation(account_count: int = 20, seed: int = 20260915, json_path=None):
    if account_count < 1:
        raise ValueError("account_count must be positive")

    random.seed(seed)
    outcome_rng = random.Random(seed + 1)
    manager = PropFirmManager()
    events = []
    accounts = []
    summary = {
        "Accounts": account_count,
        "Evaluation days": 4,
        "Evaluations passed": 0,
        "Funded wins": 0,
        "Funded losses": 0,
        "Payouts": 0,
        "Completed accounts": 0,
        "Failed accounts": 0,
        "Seed": seed,
    }

    for account_number in range(1, account_count + 1):
        account_id = f"MFFU-EOD-{account_number:03d}"
        balance = STARTING_BALANCE
        account_events = []
        status = "ok"
        reason = "completed four payouts"
        funded_trades = 0
        payouts = 0

        for day in range(1, 5):
            result = manager.randomize_trade_config(
                "MFFU Rapid EOD", f"challenge_trade{day}", _config(),
                account_key=account_id, balance=balance)
            next_balance = balance + result["tradovate_tp_ticks"] * TICK_DOLLARS
            event = {
                "account": account_id,
                "trade": f"challenge_trade{day}",
                "event": f"EVAL {day}",
                "balance": balance,
                "tp_ticks": int(result["tradovate_tp_ticks"]),
                "sl_ticks": int(result["tradovate_sl_ticks"]),
                "qty": int(result["tradovate_qty"]),
                "outcome": "WIN",
                "next_balance": next_balance,
            }
            events.append(event)
            account_events.append(event)
            balance = next_balance

        summary["Evaluations passed"] += 1
        reset = {
            "account": account_id,
            "event": "FUNDING RESET",
            "balance": balance,
            "next_balance": STARTING_BALANCE,
            "outcome": "RESET",
            "detail": "evaluation balance is not carried into the funded account",
        }
        events.append(reset)
        account_events.append(reset)
        balance = STARTING_BALANCE
        cycle_start = STARTING_BALANCE

        for funded_number in range(1, 5):
            result = manager.randomize_trade_config(
                "MFFU Rapid EOD", f"funded_trade{funded_number}", _config(),
                account_key=account_id, balance=balance)
            randomization = result.get("_randomization") or {}
            tp_ticks = int(result["tradovate_tp_ticks"])
            sl_ticks = int(result["tradovate_sl_ticks"])
            won = outcome_rng.random() < 0.70
            next_balance = balance + (tp_ticks * TICK_DOLLARS if won
                                      else -sl_ticks * TICK_DOLLARS)
            event = {
                "account": account_id,
                "trade": f"funded_trade{funded_number}",
                "event": f"FD{funded_number}",
                "balance": balance,
                "t1_ticks": randomization.get("target_ticks") if funded_number == 1 else None,
                "t2_ticks": randomization.get("target_ticks") if funded_number > 1 else None,
                "tp_ticks": tp_ticks,
                "sl_ticks": sl_ticks,
                "qty": int(result["tradovate_qty"]),
                "outcome": "WIN" if won else "LOSS",
                "next_balance": next_balance,
            }
            events.append(event)
            account_events.append(event)
            funded_trades += 1
            summary["Funded wins" if won else "Funded losses"] += 1
            balance = next_balance

            if not won:
                status = "failed"
                reason = f"FD{funded_number} loss/restart"
                stop = {
                    "account": account_id,
                    "event": f"STOP FD{funded_number}",
                    "balance": balance,
                    "next_balance": balance,
                    "outcome": "STOP",
                    "detail": "133-tick stop hit; restart node",
                }
                events.append(stop)
                account_events.append(stop)
                break

            payout, retained_balance = _calculate_payout(
                balance, cycle_start, funded_number)
            if payout < 500:
                status = "failed"
                reason = f"FD{funded_number} payout minimum not met"
                no_payout = {
                    "account": account_id,
                    "event": f"NO PAYOUT FD{funded_number}",
                    "balance": balance,
                    "outcome": "NO_PAYOUT",
                    "detail": f"requested payout ${payout:,.2f} below $500 minimum",
                }
                events.append(no_payout)
                account_events.append(no_payout)
                break

            payout_event = {
                "account": account_id,
                "event": f"PAYOUT FD{funded_number}",
                "balance": balance,
                    "cycle_start": cycle_start,
                    "cycle_profit": balance - cycle_start,
                "payout_amount": payout,
                    "retained_balance": retained_balance,
                "outcome": "PAYOUT",
            }
            events.append(payout_event)
            account_events.append(payout_event)
            summary["Payouts"] += 1
            payouts += 1
            balance = retained_balance
            cycle_start = balance

        if payouts == 4:
            summary["Completed accounts"] += 1
        elif status == "failed":
            summary["Failed accounts"] += 1

        accounts.append({
            "account": account_id,
            "status": "complete" if payouts == 4 else status,
            "funded_trades": funded_trades,
            "payouts": payouts,
            "final_balance": balance,
            "reason": reason if payouts < 4 else "completed four payouts",
        })

    payload = {
        "seed": seed,
        "firm": "MFFU Rapid EOD 50K",
        "account_size": "$50,000",
        "summary": summary,
        "accounts": accounts,
        "events": events,
    }
    if json_path:
        Path(json_path).write_text(json.dumps(payload, indent=2) + "\n",
                                   encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Simulate MFFU Rapid EOD 50K")
    parser.add_argument("--accounts", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--json", default="tests/mffu_rapid_eod_50k.json")
    args = parser.parse_args()
    run_simulation(args.accounts, args.seed, args.json)
    print(f"JSON_OUTPUT {args.json}")


if __name__ == "__main__":
    main()
