"""Generate a JSON-only Lucid Flex 50K lifecycle simulation."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trader_companion.prop_firm_manager import PropFirmManager


STARTING_BALANCE = 50000.0
LOCKED_FLOOR = 50100.0
NQ_TICK_DOLLARS = 10.0
MNQ_TICK_DOLLARS = 1.0


def _eval_config():
    return {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 1,
        "tradovate_tp_ticks": 304,
        "tradovate_sl_ticks": 400,
    }


def _funded_config(cycle_start):
    return {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 140,
        "tradovate_sl_ticks": 200,
        "cycle_start": cycle_start,
    }


def _farm_config():
    return {
        "tradovate_symbol": "MNQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 156,
        "tradovate_sl_ticks": 500,
    }


def run_simulation(account_count: int = 20, seed: int = 20260915, json_path=None):
    if account_count < 1:
        raise ValueError("account_count must be positive")

    random.seed(seed)
    outcome_rng = random.Random(seed + 1)
    manager = PropFirmManager()
    events = []
    accounts = []
    counters = {
        "Accounts": account_count,
        "Evaluations passed": 0,
        "Funded wins": 0,
        "Funded losses": 0,
        "Farm wins": 0,
        "Farm losses": 0,
        "Payouts": 0,
        "Gated accounts": 0,
        "Seed": seed,
    }

    for account_number in range(1, account_count + 1):
        account_id = f"LUCID-SIM-{account_number:03d}"
        balance = STARTING_BALANCE
        cycle_start = STARTING_BALANCE
        account_events = []
        account_status = "ok"
        account_reason = "completed funded chain"
        funded_trades = 0
        payouts = 0
        eval_qty = None

        for eval_day in range(1, 3):
            result = manager.randomize_trade_config(
                "Lucid", f"challenge_trade{eval_day}", _eval_config(),
                account_key=account_id, balance=balance)
            eval_qty = int(result["tradovate_qty"])
            eval_tp = int(result["tradovate_tp_ticks"])
            eval_sl = int(result["tradovate_sl_ticks"])
            won = True
            next_balance = balance + eval_tp * NQ_TICK_DOLLARS
            event = {
                "account": account_id,
                "trade": f"challenge_trade{eval_day}",
                "event": f"EVAL {eval_day}",
                "balance": balance,
                "tp_ticks": eval_tp,
                "sl_ticks": eval_sl,
                "qty": eval_qty,
                "outcome": "WIN" if won else "LOSS",
                "next_balance": next_balance,
            }
            events.append(event)
            account_events.append(event)
            balance = next_balance

        counters["Evaluations passed"] += 1
        funding_reset = {
            "account": account_id,
            "event": "FUNDING RESET",
            "balance": balance,
            "next_balance": STARTING_BALANCE,
            "outcome": "RESET",
            "detail": "evaluation balance is not carried into the funded account",
        }
        events.append(funding_reset)
        account_events.append(funding_reset)
        balance = STARTING_BALANCE
        cycle_start = STARTING_BALANCE

        for funded_number in range(1, 6):
            if funded_number > 1 and balance < LOCKED_FLOOR:
                counters["Gated accounts"] += 1
                account_status = "gated"
                account_reason = f"FD{funded_number} balance below ${LOCKED_FLOOR:,.2f}"
                event = {
                    "account": account_id,
                    "event": f"GATE FD{funded_number}",
                    "balance": balance,
                    "outcome": "GATE",
                    "detail": account_reason,
                }
                events.append(event)
                account_events.append(event)
                break

            result = manager.randomize_trade_config(
                "Lucid", f"funded_trade{funded_number}",
                _funded_config(cycle_start), account_key=account_id,
                balance=balance)
            tp_ticks = int(result["tradovate_tp_ticks"])
            sl_ticks = int(result["tradovate_sl_ticks"])
            randomization = result.get("_randomization") or {}
            won = outcome_rng.random() < 0.70
            next_balance = balance + (tp_ticks * NQ_TICK_DOLLARS if won
                                      else -sl_ticks * NQ_TICK_DOLLARS)
            event = {
                "account": account_id,
                "trade": f"funded_trade{funded_number}",
                "event": f"FD{funded_number}",
                "balance": balance,
                "cycle_start": cycle_start,
                "offset_dollars": randomization.get("offset_dollars"),
                "target": randomization.get("target_dollars"),
                "tp_ticks": tp_ticks,
                "sl_ticks": sl_ticks,
                "outcome": "WIN" if won else "LOSS",
                "next_balance": next_balance,
            }
            events.append(event)
            account_events.append(event)
            funded_trades += 1
            counters["Funded wins" if won else "Funded losses"] += 1
            balance = next_balance

            if not won:
                account_status = "failed"
                account_reason = f"FD{funded_number} loss"
                stop = {
                    "account": account_id,
                    "event": f"STOP FD{funded_number}",
                    "balance": balance,
                    "next_balance": balance,
                    "outcome": "STOP",
                    "detail": "funded trade loss",
                }
                events.append(stop)
                account_events.append(stop)
                break

            for farm_day in range(1, 5):
                farm = manager.randomize_trade_config(
                    "Lucid", "farming", _farm_config(),
                    account_key=account_id, balance=balance)
                farm_tp = int(farm["tradovate_tp_ticks"])
                farm_sl = int(farm["tradovate_sl_ticks"])
                farm_won = outcome_rng.random() < 0.80
                farm_next = balance + (farm_tp * MNQ_TICK_DOLLARS if farm_won
                                       else -farm_sl * MNQ_TICK_DOLLARS)
                farm_event = {
                    "account": account_id,
                    "trade": f"farming_day{farm_day}",
                    "event": f"FARM {farm_day}",
                    "balance": balance,
                    "tp_ticks": farm_tp,
                    "sl_ticks": farm_sl,
                    "outcome": "WIN" if farm_won else "LOSS",
                    "next_balance": farm_next,
                }
                events.append(farm_event)
                account_events.append(farm_event)
                counters["Farm wins" if farm_won else "Farm losses"] += 1
                balance = farm_next
                if balance < LOCKED_FLOOR:
                    counters["Gated accounts"] += 1
                    account_status = "gated"
                    account_reason = f"farming breach before FD{funded_number + 1}"
                    breach = {
                        "account": account_id,
                        "event": "BREACH FARMING",
                        "balance": balance,
                        "outcome": "BREACH",
                        "detail": f"balance below ${LOCKED_FLOOR:,.2f}",
                    }
                    events.append(breach)
                    account_events.append(breach)
                    break
            else:
                cycle_profit = balance - cycle_start
                if cycle_profit < 1000:
                    account_status = "failed"
                    account_reason = f"FD{funded_number} payout minimum not met"
                    no_payout = {
                        "account": account_id,
                        "event": f"NO PAYOUT FD{funded_number}",
                        "balance": balance,
                        "outcome": "NO_PAYOUT",
                        "detail": f"cycle profit ${cycle_profit:,.2f} below $1,000",
                    }
                    events.append(no_payout)
                    account_events.append(no_payout)
                    break
                payout = min(2000.0, float(int(0.5 * cycle_profit)))
                balance -= payout
                payouts += 1
                counters["Payouts"] += 1
                payout_event = {
                    "account": account_id,
                    "event": f"PAYOUT FD{funded_number}",
                    "balance": balance + payout,
                    "cycle_start": cycle_start,
                    "cycle_profit": cycle_profit,
                    "payout_request": payout,
                    "next_balance": balance,
                    "outcome": "PAYOUT",
                }
                events.append(payout_event)
                account_events.append(payout_event)
                cycle_start = balance
                if payouts >= 5:
                    account_status = "complete"
                    account_reason = "completed five payouts"
                    break
                continue
            break

        accounts.append({
            "account": account_id,
            "status": account_status,
            "evaluation_qty": eval_qty,
            "funded_trades": funded_trades,
            "payouts": payouts,
            "final_balance": balance,
            "reason": account_reason,
        })

    payload = {
        "seed": seed,
        "firm": "Lucid Flex 50K",
        "account_size": "$50,000",
        "summary": counters,
        "accounts": accounts,
        "events": events,
    }
    if json_path:
        Path(json_path).write_text(json.dumps(payload, indent=2) + "\n",
                                   encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Simulate Lucid Flex 50K")
    parser.add_argument("--accounts", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--json", default="tests/lucid_flex_50k.json")
    args = parser.parse_args()
    run_simulation(args.accounts, args.seed, args.json)
    print(f"JSON_OUTPUT {args.json}")


if __name__ == "__main__":
    main()
