"""Generate a JSON-only FundedNext Rapid Daily 50K simulation."""

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
PAYOUT_REQUEST = 1200.0
RETAINED_BALANCE = 52800.0
LATER_CYCLE_RETAINED_BALANCE = 52100.0


def _config():
    return {
        "tradovate_symbol": "NQZ6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 400,
        "tradovate_sl_ticks": 100,
    }


def run_simulation(account_count=20, seed=20260915, json_path=None):
    random.seed(seed)
    outcomes = random.Random(seed + 1)
    manager = PropFirmManager()
    accounts = []
    events = []

    for number in range(1, account_count + 1):
        account = f"FN-RAPID-{number:03d}"
        balance = STARTING_BALANCE
        status = "complete"
        reason = "completed funded cycle"

        result = manager.randomize_trade_config(
            "FundedNext Rapid Daily", "challenge_trade1", _config(),
            account_key=account, balance=balance)
        eval_won = outcomes.random() < 0.70
        if number == 1:
            eval_won = False
        tp = 300
        sl = 100
        next_balance = balance + (tp * NQ_TICK_DOLLARS if eval_won
                                  else -sl * NQ_TICK_DOLLARS)
        events.append({
            "account": account,
            "trade": "challenge_trade1",
            "event": "EVAL 1",
            "balance": balance,
            "tp_ticks": tp,
            "sl_ticks": sl,
            "qty": 2,
            "outcome": "WIN" if eval_won else "LOSS",
            "next_balance": next_balance,
        })
        balance = next_balance

        if not eval_won:
            recovery = manager.randomize_trade_config(
                "FundedNext Rapid Daily", "challenge_trade1_recovery",
                _config(), account_key=account, balance=balance)
            recovery_won = outcomes.random() < 0.70
            if number == 1:
                recovery_won = True
            tp = 400
            next_balance = balance + (tp * NQ_TICK_DOLLARS if recovery_won
                                      else -sl * NQ_TICK_DOLLARS)
            events.append({
                "account": account,
                "trade": "challenge_trade1_recovery",
                "event": "EVAL RECOVERY",
                "balance": balance,
                "tp_ticks": tp,
                "sl_ticks": sl,
                "qty": 2,
                "outcome": "WIN" if recovery_won else "LOSS",
                "next_balance": next_balance,
            })
            balance = next_balance
            if not recovery_won:
                status = "failed"
                reason = "evaluation recovery loss; $48,000 floor"

        if status == "complete":
            events.append({
                "account": account,
                "event": "FUNDING RESET",
                "balance": balance,
                "next_balance": STARTING_BALANCE,
                "outcome": "RESET",
            })
            balance = STARTING_BALANCE

        if status == "complete":
            for cycle in range(1, 6):
                main_phase = f"funded_trade{cycle}"
                recovery_phases = (
                    [f"funded_trade{cycle}_recovery1", f"funded_trade{cycle}_recovery2"]
                    if cycle == 2 else [f"funded_trade{cycle}_recovery"]
                )
                attempts = [main_phase] + recovery_phases
                cycle_won = False
                for attempt_number, phase in enumerate(attempts):
                    result = manager.randomize_trade_config(
                        "FundedNext Rapid Daily", phase, _config(),
                        account_key=account, balance=balance)
                    tp = int(result["tradovate_tp_ticks"])
                    sl = int(result["tradovate_sl_ticks"])
                    won = outcomes.random() < 0.70
                    if number == 1:
                        forced_outcomes = {
                            1: (False, True),
                            2: (True,),
                            3: (False, True),
                            4: (False, False),
                        }
                        cycle_outcomes = forced_outcomes[cycle]
                        won = cycle_outcomes[attempt_number]
                    next_balance = balance + (tp * NQ_TICK_DOLLARS if won
                                              else -sl * NQ_TICK_DOLLARS)
                    events.append({
                        "account": account,
                        "trade": phase,
                        "event": f"FD{cycle}" if attempt_number == 0 else f"FD{cycle} RECOVERY {attempt_number}",
                        "balance": balance,
                        "target_profit_ticks": tp,
                        "tp_ticks": tp,
                        "sl_ticks": sl,
                        "qty": int(result["tradovate_qty"]),
                        "outcome": "WIN" if won else "LOSS",
                        "next_balance": next_balance,
                    })
                    balance = next_balance
                    if won:
                        cycle_won = True
                        break

                if not cycle_won:
                    status = "failed"
                    reason = f"funded cycle {cycle} recovery exhausted; breach"
                    events.append({
                        "account": account,
                        "event": f"BREACH FD{cycle}",
                        "balance": balance,
                        "outcome": "BREACH",
                        "detail": "primary and recovery funded trades failed",
                    })
                    break

                retained = RETAINED_BALANCE if cycle == 1 else LATER_CYCLE_RETAINED_BALANCE
                payout_amount = max(0.0, balance - retained)
                events.append({
                    "account": account,
                    "event": f"PAYOUT {cycle}",
                    "balance": balance,
                    "payout_request_gross": min(PAYOUT_REQUEST, payout_amount),
                    "payout_before_provider_fees": min(1080.0, payout_amount),
                    "retained_balance": retained,
                    "outcome": "PAYOUT",
                })
                balance = retained

        accounts.append({
            "account": account,
            "status": status,
            "final_balance": balance,
            "reason": reason,
        })

    payload = {
        "seed": seed,
        "firm": "FundedNext Rapid Daily 50K",
        "account_size": "$50,000",
        "position": "2 NQ minis",
        "summary": {"Accounts": account_count, "Events": len(events), "Seed": seed},
        "accounts": accounts,
        "events": events,
    }
    if json_path:
        Path(json_path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--accounts", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--json", default="tests/fundednext_rapid_daily_50k.json")
    args = parser.parse_args()
    run_simulation(args.accounts, args.seed, args.json)
    print(f"JSON_OUTPUT {args.json}")


if __name__ == "__main__":
    main()
