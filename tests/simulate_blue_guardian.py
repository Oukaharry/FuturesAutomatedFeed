"""Print a deterministic Blue Guardian Reserve funded-trade simulation.

Run from the repository root:
    .venv/bin/python tests/simulate_blue_guardian.py

The simulator uses PropFirmManager.randomize_trade_config() for every trade,
then applies a simple synthetic win/loss result to produce the next live
balance. It is a configuration simulation, not a market-performance model.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

# Allow direct execution from the repository root or the tests directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trader_companion.prop_firm_manager import PropFirmManager


TICK_DOLLARS = 10.0
FARM_TICK_DOLLARS = 5.0
STARTING_BALANCE = 50000.0
LOCKED_FLOOR = 50100.0
TARGET_BALANCE = 54000.0
TP_FLOOR_DOLLARS = 800.0
MAX_TP_TICKS = 600
MIN_TP_TICKS = 80
SL_MIN_TICKS = 10
MIN_FT2_BALANCE = 50100.0


def _config():
    return {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 201,
        "tradovate_sl_ticks": 190,
    }


def _farm_config():
    return {
        "tradovate_symbol": "NQU6",
        "tradovate_qty": 1,
        "tradovate_tp_ticks": 31,
        "tradovate_sl_ticks": 200,
    }


def _money(value):
    return f"${float(value):,.2f}"


def run_simulation(account_count: int = 50, seed: int = 20260915,
                   json_path=None):
    """Return simulated trade records and print each trade to stdout."""
    if account_count < 1:
        raise ValueError("account_count must be positive")

    random.seed(seed)
    outcome_rng = random.Random(seed + 1)
    manager = PropFirmManager()
    records = []
    funded_wins = funded_losses = farm_wins = farm_losses = gated = 0
    payouts = 0
    account_summaries = []

    for account_number in range(1, account_count + 1):
        account_id = f"BGR-SIM-{account_number:03d}"
        balance = STARTING_BALANCE
        account_records = []
        account_payouts = 0
        account_reason = "completed funded chain"
        account_status = "ok"
        account_farm_days = 0
        account_funded_trades = 0
        for funded_number in range(1, 5):
            if funded_number == 1:
                assert balance == STARTING_BALANCE, (account_id, balance)
            elif balance < MIN_FT2_BALANCE:
                gated += 1
                print(
                    f"GATE {account_id} FD{funded_number} "
                    f"balance=${balance:,.2f} < minimum=${MIN_FT2_BALANCE:,.2f}"
                )
                gate_record = {"account": account_id, "event": f"GATE FD{funded_number}",
                               "balance": balance, "outcome": "GATE",
                               "detail": f"balance below ${MIN_FT2_BALANCE:,.2f}"}
                records.append(gate_record)
                account_records.append(gate_record)
                account_status = "gated"
                account_reason = f"FD{funded_number} balance below ${MIN_FT2_BALANCE:,.2f}"
                break

            phase = f"funded_trade{funded_number}"
            result = manager.randomize_trade_config(
                "Blue Guardian Reserve", phase, _config(),
                account_key=account_id, balance=balance)
            tp_ticks = int(result["tradovate_tp_ticks"])
            sl_ticks = int(result["tradovate_sl_ticks"])
            randomization = result.get("_randomization") or {}
            target = float(randomization.get(
                "target_dollars", STARTING_BALANCE + tp_ticks * TICK_DOLLARS))
            expected_tp = max(MIN_TP_TICKS, min(
                MAX_TP_TICKS, int((target - balance) // TICK_DOLLARS)))
            expected_sl = 200 if funded_number == 1 else max(
                SL_MIN_TICKS, min(MAX_TP_TICKS,
                                  int((balance - LOCKED_FLOOR) // TICK_DOLLARS)))
            assert tp_ticks == expected_tp, (phase, balance, target, result)
            assert sl_ticks == expected_sl, (phase, balance, target, result)

            won = outcome_rng.random() < 0.70
            next_balance = balance + (tp_ticks * TICK_DOLLARS if won else -sl_ticks * TICK_DOLLARS)
            outcome = "WIN" if won else "LOSS"
            funded_wins += int(won)
            funded_losses += int(not won)
            records.append({"account": account_id, "trade": phase,
                            "event": f"FD{funded_number}",
                            "balance": balance, "target": target,
                            "tp_ticks": tp_ticks, "sl_ticks": sl_ticks,
                            "outcome": outcome, "next_balance": next_balance})
            records[-1]["number"] = len(records)
            account_records.append(records[-1])
            account_funded_trades += 1
            print(f"{len(records):03d} {account_id} FD{funded_number} "
                  f"balance=${balance:,.2f} target=${target:,.2f} "
                  f"TP={tp_ticks}t SL={sl_ticks}t {outcome} "
                  f"next=${next_balance:,.2f}")
            balance = next_balance

            if not won:
                print(f"STOP {account_id} FD{funded_number} loss; no farming/payout")
                stop_record = {"account": account_id, "event": f"STOP FD{funded_number}",
                               "balance": balance, "next_balance": balance,
                               "outcome": "STOP", "detail": "funded trade loss"}
                records.append(stop_record)
                account_records.append(stop_record)
                account_status = "failed"
                account_reason = f"FD{funded_number} loss"
                break

            # A funded win is followed by five farming days before the next
            # payout reset. Farming uses the actual MNQ TP/SL randomizer.
            for farm_day in range(1, 5):
                farm = manager.randomize_trade_config(
                    "Blue Guardian Reserve", "farming", _farm_config(),
                    account_key=account_id, balance=balance)
                farm_tp = int(farm["tradovate_tp_ticks"])
                farm_sl = int(farm["tradovate_sl_ticks"])
                assert farm_tp == 31
                assert 100 <= farm_sl <= 390
                farm_won = outcome_rng.random() < 0.80
                farm_next = balance + (farm_tp * FARM_TICK_DOLLARS
                                       if farm_won else -farm_sl * FARM_TICK_DOLLARS)
                farm_outcome = "WIN" if farm_won else "LOSS"
                farm_wins += int(farm_won)
                farm_losses += int(not farm_won)
                farm_phase = f"farming_day{farm_day}"
                records.append({"account": account_id, "trade": farm_phase,
                                "event": f"FARM {farm_day}",
                                "balance": balance, "target": None,
                                "tp_ticks": farm_tp, "sl_ticks": farm_sl,
                                "outcome": farm_outcome, "next_balance": farm_next})
                records[-1]["number"] = len(records)
                account_records.append(records[-1])
                account_farm_days += 1
                print(f"{len(records):03d} {account_id} {farm_phase} "
                      f"balance=${balance:,.2f} TP={farm_tp}t SL={farm_sl}t "
                      f"{farm_outcome} next=${farm_next:,.2f}")
                balance = farm_next
                if not farm_won:
                    if balance < LOCKED_FLOOR:
                        print(f"BREACH {account_id} farming day {farm_day} "
                              f"balance=${balance:,.2f} < floor=${LOCKED_FLOOR:,.2f}")
                        stop_record = {"account": account_id, "event": "BREACH FARMING",
                                       "balance": balance, "next_balance": balance,
                                       "outcome": "BREACH",
                                       "detail": f"balance below ${LOCKED_FLOOR:,.2f}"}
                        records.append(stop_record)
                        account_records.append(stop_record)
                        account_status = "failed"
                        account_reason = f"farming day {farm_day} breached below ${LOCKED_FLOOR:,.2f}"
                        break
                    print(f"CONTINUE {account_id} farming loss; "
                          f"balance=${balance:,.2f} remains above floor")
            else:
                # The payout retains half of the profit above $50,000.
                profit_above_start = max(0.0, balance - STARTING_BALANCE)
                payout = profit_above_start / 2.0
                payout_balance = STARTING_BALANCE + profit_above_start / 2.0
                payouts += 1
                account_payouts += 1
                print(f"PAYOUT {account_id} FD{funded_number} "
                      f"pre=${balance:,.2f} payout=${payout:,.2f} "
                      f"next_balance=${payout_balance:,.2f}")
                payout_record = {
                    "account": account_id,
                    "event": f"PAYOUT FD{funded_number}",
                    "balance": balance,
                    "next_balance": payout_balance,
                    "outcome": "PAYOUT",
                    "detail": f"payout ${payout:,.2f}",
                }
                records.append(payout_record)
                account_records.append(payout_record)
                balance = payout_balance
                continue

        account_summaries.append({"account": account_id, "status": account_status,
                      "funded_trades": account_funded_trades,
                      "farm_days": account_farm_days,
                      "payouts": account_payouts,
                      "reason": account_reason})

    summary = {
        "Accounts": account_count,
        "Events": len(records),
        "Funded wins": funded_wins,
        "Funded losses": funded_losses,
        "Farm wins": farm_wins,
        "Farm losses": farm_losses,
        "Payouts": payouts,
        "Gated accounts": gated,
        "Minimum FD2 balance": _money(MIN_FT2_BALANCE),
        "Seed": seed,
    }
    print(
        f"SUMMARY events={len(records)} accounts={account_count} "
        f"funded_wins={funded_wins} funded_losses={funded_losses} "
        f"farm_wins={farm_wins} farm_losses={farm_losses} payouts={payouts} "
        f"gated={gated} min_ft2_balance=${MIN_FT2_BALANCE:,.2f} seed={seed}"
    )
    if json_path:
        payload = {
            "seed": seed,
            "firm": "Blue Guardian Reserve",
            "account_size": "$50,000",
            "summary": summary,
            "accounts": account_summaries,
            "events": records,
        }
        Path(json_path).write_text(json.dumps(payload, indent=2) + "\n",
                                   encoding="utf-8")
        print(f"JSON_OUTPUT {json_path}")
    return records


def main():
    parser = argparse.ArgumentParser(description="Simulate Blue Guardian Reserve funded trades")
    parser.add_argument("--accounts", type=int, default=50,
                        help="accounts to simulate; default: 50 (200 trades)")
    parser.add_argument("--seed", type=int, default=20260915,
                        help="deterministic simulation seed")
    parser.add_argument("--json", default=None,
                        help="JSON output path; omit to disable")
    args = parser.parse_args()
    run_simulation(account_count=args.accounts, seed=args.seed,
                   json_path=args.json)


if __name__ == "__main__":
    main()
