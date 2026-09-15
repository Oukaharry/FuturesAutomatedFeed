"""Generate a JSON-only TopStep 50K XFA DLL-off simulation."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trader_companion.prop_firm_manager import PropFirmManager


STARTING_BALANCE = 0.0
PAYOUT_CAP = 2000.0
TICK_DOLLARS_NQ = 10.0
TICK_DOLLARS_MNQ = 2.0


def _config():
    return {
        "topstepx_symbol": "NQU26",
        "topstepx_qty": 2,
        "topstepx_tp_ticks": 400,
        "topstepx_sl_ticks": 200,
    }


def _farm_config():
    return {
        "topstepx_symbol": "MNQU26",
        "topstepx_qty": 2,
        "topstepx_tp_ticks": 154,
        "topstepx_sl_ticks": 520,
    }


def _payout(balance, payout_number):
    payout = min(PAYOUT_CAP, int(0.5 * balance))
    return payout, balance - payout


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
        "Evaluation days": 2,
        "Evaluations passed": 0,
        "Funded wins": 0,
        "Funded losses": 0,
        "Farm wins": 0,
        "Farm losses": 0,
        "Payouts": 0,
        "Completed accounts": 0,
        "Failed accounts": 0,
        "Seed": seed,
    }

    for account_number in range(1, account_count + 1):
        account_id = f"TOPSTEP-XFA-{account_number:03d}"
        balance = STARTING_BALANCE
        account_events = []
        funded_trades = 0
        payouts = 0
        status = "complete"
        reason = "completed four payouts"

        for day in range(1, 3):
            result = manager.randomize_trade_config(
                "TopStep 50K XFA", f"challenge_trade{day}", _config(),
                account_key=account_id, balance=balance)
            tp_ticks = int(result["topstepx_tp_ticks"])
            sl_ticks = int(result["topstepx_sl_ticks"])
            next_balance = balance + tp_ticks * TICK_DOLLARS_NQ
            event = {
                "account": account_id,
                "trade": f"challenge_trade{day}",
                "event": f"EVAL {day}",
                "balance": balance,
                "tp_ticks": tp_ticks,
                "sl_ticks": sl_ticks,
                "qty": int(result["topstepx_qty"]),
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
            "detail": "XFA funded balance starts at $0",
        }
        events.append(reset)
        account_events.append(reset)
        balance = STARTING_BALANCE

        for payout_number in range(1, 5):
            funded_phase = f"funded_trade{payout_number}"
            result = manager.randomize_trade_config(
                "TopStep 50K XFA", funded_phase, _config(),
                account_key=account_id, balance=balance)
            randomization = result.get("_randomization") or {}
            tp_ticks = int(result["topstepx_tp_ticks"])
            sl_ticks = int(result["topstepx_sl_ticks"])
            won = outcome_rng.random() < 0.70
            next_balance = balance + (tp_ticks * TICK_DOLLARS_NQ if won
                                      else -sl_ticks * TICK_DOLLARS_NQ)
            event = {
                "account": account_id,
                "trade": funded_phase,
                "event": f"FD{payout_number}",
                "balance": balance,
                "t1_ticks": randomization.get("target_ticks") if payout_number == 1 else None,
                "t2_ticks": randomization.get("target_ticks") if payout_number > 1 else None,
                "tp_ticks": tp_ticks,
                "sl_ticks": sl_ticks,
                "qty": int(result["topstepx_qty"]),
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
                reason = f"FD{payout_number} loss/restart"
                stop = {
                    "account": account_id,
                    "event": f"STOP FD{payout_number}",
                    "balance": balance,
                    "next_balance": balance,
                    "outcome": "STOP",
                    "detail": "XFA MLL stop/restart",
                }
                events.append(stop)
                account_events.append(stop)
                break

            for farm_day in range(1, 5):
                farm = manager.randomize_trade_config(
                    "TopStep 50K XFA", "farming", _farm_config(),
                    account_key=account_id, balance=balance)
                farm_tp = int(farm["topstepx_tp_ticks"])
                farm_sl = int(farm["topstepx_sl_ticks"])
                farm_won = outcome_rng.random() < 0.80
                farm_next = balance + (farm_tp * TICK_DOLLARS_MNQ if farm_won
                                       else -farm_sl * TICK_DOLLARS_MNQ)
                farm_event = {
                    "account": account_id,
                    "trade": f"farming_day{farm_day}",
                    "event": f"FARM {farm_day}",
                    "balance": balance,
                    "tp_ticks": farm_tp,
                    "sl_ticks": farm_sl,
                    "qty": int(farm["topstepx_qty"]),
                    "outcome": "WIN" if farm_won else "LOSS",
                    "next_balance": farm_next,
                }
                events.append(farm_event)
                account_events.append(farm_event)
                summary["Farm wins" if farm_won else "Farm losses"] += 1
                balance = farm_next
            else:
                payout, retained = _payout(balance, payout_number)
                if payout < 500:
                    status = "failed"
                    reason = f"P{payout_number} payout minimum not met"
                    break
                payout_event = {
                    "account": account_id,
                    "event": f"PAYOUT {payout_number}",
                    "balance": balance,
                    "payout_amount": payout,
                    "retained_balance": retained,
                    "outcome": "PAYOUT",
                }
                events.append(payout_event)
                account_events.append(payout_event)
                summary["Payouts"] += 1
                payouts += 1
                balance = retained
                continue
            break

        if payouts == 4:
            summary["Completed accounts"] += 1
        else:
            status = "failed"
            summary["Failed accounts"] += 1
        accounts.append({
            "account": account_id,
            "status": status,
            "funded_trades": funded_trades,
            "payouts": payouts,
            "final_balance": balance,
            "reason": reason if payouts < 4 else "completed four payouts",
        })

    payload = {
        "seed": seed,
        "firm": "TopStep 50K XFA",
        "account_size": "$50,000",
        "dll": "off",
        "summary": summary,
        "accounts": accounts,
        "events": events,
    }
    if json_path:
        Path(json_path).write_text(json.dumps(payload, indent=2) + "\n",
                                   encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Simulate TopStep 50K XFA")
    parser.add_argument("--accounts", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--json", default="tests/topstep_xfa_50k.json")
    args = parser.parse_args()
    run_simulation(args.accounts, args.seed, args.json)
    print(f"JSON_OUTPUT {args.json}")


if __name__ == "__main__":
    main()
