"""Generate configuration-focused JSON simulations for remaining blueprints."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trader_companion.prop_firm_manager import PropFirmManager


REMAINING_FIRMS = (
    "MFFU_Flex",
    "Funded Next",
    "TopStep",
    "TopStep RTP",
    "TradeDay",
    "AlphaFutures",
    "Tradeify",
    "Apex",
    "Top One Futures",
    "Funded Futures Family",
    "Funded Next Flex",
    "FTMO Futures Pro",
    "Tradeify Select",
)


def _config(manager, firm, phase):
    config = manager.get_strategy_config(firm, phase, "50k")
    if config:
        return config
    return {
        "tradovate_symbol": "NQZ6",
        "tradovate_qty": 2,
        "tradovate_tp_ticks": 200,
        "tradovate_sl_ticks": 200,
    }


def _tick_value(manager, config):
    symbol = config.get("tradovate_symbol") or config.get("topstepx_symbol") or "NQZ6"
    return manager.get_tick_value(symbol)


def simulate_firm(firm, account_count, seed):
    random.seed(seed)
    outcomes = random.Random(seed + 1)
    manager = PropFirmManager()
    accounts = []
    events = []

    for number in range(1, account_count + 1):
        account = f"{firm.upper().replace(' ', '-').replace('_', '-')}-{number:03d}"
        balance = 50000.0
        account_status = "ok"
        reason = "completed configuration chain"

        for day in range(1, 3):
            base = _config(manager, firm, f"challenge_trade{day}")
            result = manager.randomize_trade_config(
                firm, f"challenge_trade{day}", base,
                account_key=account, balance=balance)
            tp_key = "tradovate_tp_ticks" if "tradovate_tp_ticks" in result else "topstepx_tp_ticks"
            sl_key = "tradovate_sl_ticks" if "tradovate_sl_ticks" in result else "topstepx_sl_ticks"
            qty_key = "tradovate_qty" if "tradovate_qty" in result else "topstepx_qty"
            tp = int(result.get(tp_key, 0))
            sl = int(result.get(sl_key, 0))
            qty = int(result.get(qty_key, 0))
            next_balance = balance + tp * qty * _tick_value(manager, result)
            event = {
                "account": account,
                "trade": f"challenge_trade{day}",
                "event": f"EVAL {day}",
                "balance": balance,
                "tp_ticks": tp,
                "sl_ticks": sl,
                "qty": qty,
                "outcome": "WIN",
                "next_balance": next_balance,
            }
            events.append(event)
            balance = next_balance

        reset = {
            "account": account,
            "event": "FUNDING RESET",
            "balance": balance,
            "next_balance": 50000.0,
            "outcome": "RESET",
            "detail": "evaluation balance is not carried into funded phase",
        }
        events.append(reset)
        balance = 50000.0

        for funded_number in range(1, 5):
            phase = f"funded_trade{funded_number}"
            base = _config(manager, firm, phase)
            result = manager.randomize_trade_config(
                firm, phase, base, account_key=account, balance=balance)
            tp_key = "tradovate_tp_ticks" if "tradovate_tp_ticks" in result else "topstepx_tp_ticks"
            sl_key = "tradovate_sl_ticks" if "tradovate_sl_ticks" in result else "topstepx_sl_ticks"
            qty_key = "tradovate_qty" if "tradovate_qty" in result else "topstepx_qty"
            tp = int(result.get(tp_key, 0))
            sl = int(result.get(sl_key, 0))
            qty = int(result.get(qty_key, 0))
            tick_value = _tick_value(manager, result)
            won = outcomes.random() < 0.70
            next_balance = balance + (tp * qty * tick_value if won
                                      else -sl * qty * tick_value)
            event = {
                "account": account,
                "trade": phase,
                "event": f"FD{funded_number}",
                "balance": balance,
                "tp_ticks": tp,
                "sl_ticks": sl,
                "qty": qty,
                "outcome": "WIN" if won else "LOSS",
                "next_balance": next_balance,
            }
            events.append(event)
            balance = next_balance
            if not won:
                account_status = "failed"
                reason = f"FD{funded_number} loss"
                break

            for farm_day in range(1, 5):
                farm_base = _config(manager, firm, "farming")
                farm = manager.randomize_trade_config(
                    firm, "farming", farm_base,
                    account_key=account, balance=balance)
                farm_tp_key = "tradovate_tp_ticks" if "tradovate_tp_ticks" in farm else "topstepx_tp_ticks"
                farm_sl_key = "tradovate_sl_ticks" if "tradovate_sl_ticks" in farm else "topstepx_sl_ticks"
                farm_qty_key = "tradovate_qty" if "tradovate_qty" in farm else "topstepx_qty"
                farm_tp = int(farm.get(farm_tp_key, 0))
                farm_sl = int(farm.get(farm_sl_key, 0))
                farm_qty = int(farm.get(farm_qty_key, 0))
                farm_tick = _tick_value(manager, farm)
                farm_win = outcomes.random() < 0.80
                farm_next = balance + (farm_tp * farm_qty * farm_tick if farm_win
                                       else -farm_sl * farm_qty * farm_tick)
                events.append({
                    "account": account,
                    "trade": f"farming_day{farm_day}",
                    "event": f"FARM {farm_day}",
                    "balance": balance,
                    "tp_ticks": farm_tp,
                    "sl_ticks": farm_sl,
                    "qty": farm_qty,
                    "outcome": "WIN" if farm_win else "LOSS",
                    "next_balance": farm_next,
                })
                balance = farm_next
            else:
                payout = max(0.0, balance - 50000.0) / 2.0
                events.append({
                    "account": account,
                    "event": f"PAYOUT FD{funded_number}",
                    "balance": balance,
                    "payout_amount": payout,
                    "retained_balance": balance - payout,
                    "outcome": "PAYOUT",
                })
                balance -= payout
                continue
            break

        accounts.append({
            "account": account,
            "status": account_status,
            "final_balance": balance,
            "reason": reason,
        })

    return {
        "seed": seed,
        "firm": firm,
        "account_size": "$50,000",
        "simulation_type": "configuration-focused lifecycle",
        "summary": {
            "Accounts": account_count,
            "Events": len([event for event in events]),
            "Seed": seed,
        },
        "accounts": accounts,
        "events": events,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--accounts", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--output-dir", default="tests")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, firm in enumerate(REMAINING_FIRMS):
        payload = simulate_firm(firm, args.accounts, args.seed + index)
        filename = firm.lower().replace(" ", "_").replace("-", "_") + ".json"
        path = output_dir / filename
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"JSON_OUTPUT {path}")


if __name__ == "__main__":
    main()
