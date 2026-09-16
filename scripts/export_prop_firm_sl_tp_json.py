"""
Export nested JSON of prop-firm SL/TP: eval / funded / farming columns,
static ticks vs randomized ranges (from prop_firm_manager blueprints + rules).

Usage (repo root):
    python scripts/export_prop_firm_sl_tp_json.py
    python scripts/export_prop_firm_sl_tp_json.py -o path/to/out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from trader_companion.prop_firm_manager import PropFirmManager  # noqa: E402

DEFAULT_SIZE = "50k"


def _phase_column(phase_key: str) -> str | None:
    k = (phase_key or "").lower()
    if k == "farming" or "qualifying" in k:
        return "farming"
    if k.startswith("challenge") or k.startswith("evaluation"):
        return "eval"
    if k.startswith((
        "funded", "payout", "doubledip", "live_trade", "sim",
        "finishing", "rebuild", "cycle_trade", "cycle_recovery",
    )):
        return "funded"
    return None


def _pick_ticks(cfg: dict) -> dict:
    out = {}
    for prefix in ("tradovate", "topstepx"):
        tp = cfg.get(f"{prefix}_tp_ticks")
        sl = cfg.get(f"{prefix}_sl_ticks")
        if tp is not None:
            out[f"{prefix}_tp_ticks"] = tp
        if sl is not None:
            out[f"{prefix}_sl_ticks"] = sl
    for k in ("mt5_tp_points", "mt5_sl_points", "mt5_volume"):
        if cfg.get(k) is not None:
            out[k] = cfg[k]
    if cfg.get("tradovate_symbol"):
        out["symbol"] = cfg["tradovate_symbol"]
    elif cfg.get("topstepx_symbol"):
        out["symbol"] = cfg["topstepx_symbol"]
    if cfg.get("tradovate_qty") is not None:
        out["qty"] = cfg["tradovate_qty"]
    elif cfg.get("topstepx_qty") is not None:
        out["qty"] = cfg["topstepx_qty"]
    if cfg.get("disable_tp_adjustment"):
        out["disable_tp_adjustment"] = True
    return out


def _fixed(tp, sl):
    return {
        "tp": {"mode": "fixed", "ticks": int(tp) if tp else None},
        "sl": {"mode": "fixed", "ticks": int(sl) if sl else None},
    }


def _randomization_meta(firm_code: str, phase_key: str, blueprint_tp: float, blueprint_sl: float) -> dict:
    """Policy mirror of PropFirmManager.randomize_trade_config (no random draws)."""
    firm = (firm_code or "").strip()
    phase = (phase_key or "").lower()
    is_farming = phase == "farming" or "qualifying" in phase

    # ── MFFU Builder ──
    if firm in ("MFFU Builder 50K", "MFFU Builder", "MFFU_Builder"):
        return {
            "tp": {"mode": "fixed", "ticks": int(blueprint_tp) if blueprint_tp else None,
                   "note": "Blueprint TP; disable_tp_adjustment at order time"},
            "sl": {"mode": "fixed", "ticks": 100, "note": "Forced to 100t in randomize_trade_config"},
        }

    # ── FundedNext Rapid Daily ──
    if firm in ("FundedNext Rapid Daily", "FundedNext Rapid Daily 50K"):
        if not phase.startswith("funded_trade"):
            return _fixed(blueprint_tp, blueprint_sl)
        t1 = phase.startswith("funded_trade1")
        return {
            "tp": {
                "mode": "randomized",
                "method": "legal_tick_candidates_from_balance_target",
                "target_balance_dollars_range": [54900, 56650] if t1 else [53150, 53450],
                "exclude_tick_multiples_of_100": True,
                "max_ticks": 600,
                "friction_dollars": 8.80,
                "ft1_persisted_per_account": t1,
            },
            "sl": {"mode": "fixed", "ticks": int(blueprint_sl) if blueprint_sl else None,
                   "note": "Blueprint SL; not overwritten by randomizer"},
        }

    # ── MFFU Rapid EOD ──
    if firm == "MFFU Rapid EOD":
        if phase.startswith("challenge_trade"):
            return _fixed(51, 133)
        if phase.startswith("funded_trade1"):
            return {
                "tp": {"mode": "randomized", "method": "unique_tick_pick", "ticks_range": [305, 335],
                       "exclude_multiples_of_100": True, "persisted_per_account": True},
                "sl": {"mode": "fixed", "ticks": 133},
            }
        if phase.startswith("funded_trade"):
            return {
                "tp": {"mode": "randomized", "method": "unique_tick_pick", "ticks_range": [267, 450],
                       "exclude_multiples_of_100": True, "capped_at": 599},
                "sl": {"mode": "fixed", "ticks": 133},
            }
        if is_farming:
            return {
                "tp": {"mode": "fixed", "ticks": int(blueprint_tp)},
                "sl": {"mode": "randomized", "method": "farming_sl_factor",
                       "factor_range": [0.90, 1.10], "blueprint_ticks": int(blueprint_sl)},
            }
        return _fixed(blueprint_tp, blueprint_sl)

    # ── TopStep 50K XFA ──
    if firm in ("TopStep 50K XFA", "TopStep XFA", "TopStep_XFA"):
        if phase.startswith("challenge_trade"):
            return _fixed(152, 200)
        if phase.startswith("funded_trade1"):
            return {
                "tp": {"mode": "randomized", "method": "target_dollars_4000_5000",
                       "formula_ticks": "floor((target + 18) / 10)", "persisted_per_account": True},
                "sl": {"mode": "fixed", "ticks": 200},
            }
        if phase.startswith("funded_trade"):
            return {
                "tp": {"mode": "randomized", "method": "target_dollars_balance_aware",
                       "target_dollars_range": [4000, 5000],
                       "formula_ticks": "floor((target - balance + 18) / 10)"},
                "sl": {"mode": "randomized", "method": "floor_balance_over_10",
                       "formula_ticks": "min(600, floor(balance / 10))"},
            }
        if is_farming:
            return {
                "tp": {"mode": "fixed", "ticks": 154},
                "sl": {"mode": "randomized", "method": "base_plus_daily_jitter",
                       "base_range": [520, 580], "jitter": [-20, 20], "clamped_range": [450, 600]},
            }
        return _fixed(blueprint_tp, blueprint_sl)

    # ── Tradeify Select ──
    if firm in ("Tradeify Select", "Tradeify Select 50K"):
        if phase.startswith("funded_trade1"):
            return {
                "tp": {"mode": "randomized", "method": "target_balance_dollars",
                       "target_balance_range": [54500, 56000],
                       "pre_sept_2026_purchase_offset": 1000,
                       "formula_ticks": "floor((target - balance) / 10)", "clamped_ticks": [15, 600]},
                "sl": {"mode": "fixed", "ticks": 200},
            }
        if phase.startswith("funded_trade") and not phase.startswith("funded_trade1"):
            return {
                "tp": {"mode": "randomized", "method": "target_balance_dollars",
                       "target_balance_range": [54500, 57500],
                       "pre_sept_2026_purchase_offset": 1000,
                       "formula_ticks": "floor((target - balance) / 10)", "clamped_ticks": [150, 600]},
                "sl": {"mode": "randomized", "method": "floor_room_above_50100",
                       "formula_ticks": "min(600, floor((balance - 50100) / 10))"},
            }
        if is_farming:
            return {
                "tp": {"mode": "fixed", "ticks": 154},
                "sl": {"mode": "randomized", "method": "base_plus_daily_jitter_with_cap",
                       "base_range": [470, 580], "jitter": [-20, 20],
                       "clamped_range": [450, 600],
                       "cap_formula": "floor((balance - 50100) / 4)"},
            }
        return _fixed(blueprint_tp, blueprint_sl)

    # ── FTMO Futures Pro ──
    if firm in ("FTMO Futures Pro", "FTMO Pro"):
        if phase.startswith("funded_trade1"):
            return {
                "tp": {"mode": "randomized", "method": "profit_dollars_above_50k",
                       "target_profit_range": [5000, 6000], "persisted_per_user": True,
                       "formula_ticks": "floor(profit / 10)", "clamped_ticks": [80, 600]},
                "sl": {"mode": "fixed", "ticks": 95},
            }
        if phase.startswith("funded_trade") and not phase.startswith("funded_trade1"):
            return {
                "tp": {"mode": "randomized", "method": "target_balance_dollars",
                       "target_balance_range": [54500, 57000],
                       "formula_ticks": "floor((target - balance) / 10)", "clamped_ticks": [0, 600]},
                "sl": {"mode": "randomized", "method": "dll_room",
                       "formula_ticks": "min(95, floor((balance - 50050) / 10))", "min_ticks": 20},
            }
        if is_farming:
            return {
                "tp": {"mode": "fixed", "ticks": 138, "qty": 3},
                "sl": {"mode": "randomized", "method": "base_plus_daily_jitter",
                       "base_range": [500, 580], "jitter": [-20, 20], "clamped_range": [480, 600]},
            }
        return _fixed(blueprint_tp, blueprint_sl)

    # ── Lucid ──
    if firm == "Lucid":
        if phase.startswith("challenge_trade"):
            return {
                "tp": {"mode": "randomized", "method": "qty_choice_1_or_2",
                       "ticks_if_qty_1": 304, "ticks_if_qty_2": 152},
                "sl": {"mode": "randomized", "method": "qty_choice_1_or_2",
                       "ticks_if_qty_1": 400, "ticks_if_qty_2": 200},
            }
        if phase.startswith("funded_trade1"):
            return {
                "tp": {"mode": "randomized", "method": "target_balance_unique_tp",
                       "target_balance_range": [53000, 54000], "friction_dollars": 17.0},
                "sl": {"mode": "fixed", "ticks": 200},
            }
        if phase.startswith("funded_trade"):
            return {
                "tp": {"mode": "randomized", "method": "cycle_start_plus_offset",
                       "offset_range": [1300, 1700], "friction_dollars": 17.0},
                "sl": {"mode": "randomized", "method": "floor_room_above_50100",
                       "formula_ticks": "min(600, floor((balance - 50100) / 10))"},
            }
        if is_farming:
            return {
                "tp": {"mode": "fixed", "ticks": 156},
                "sl": {"mode": "randomized", "method": "farming_sl_factor",
                       "factor_range": [0.90, 1.10], "blueprint_ticks": int(blueprint_sl)},
            }
        return _fixed(blueprint_tp, blueprint_sl)

    # ── Blue Guardian Reserve ──
    if firm in ("Blue Guardian Reserve", "Blue Guardian"):
        if phase.startswith("challenge_trade"):
            return {
                "tp": {"mode": "randomized", "method": "eval_contract_setup_draw",
                       "tp_draw_range": [300, 304], "divisor_by_setup": "1 or 2"},
                "sl": {"mode": "randomized", "method": "eval_contract_setup_draw", "base_sl_ticks": 400},
            }
        if phase.startswith("funded_trade1"):
            return {
                "tp": {"mode": "randomized", "method": "persisted_target_balance",
                       "target_balance_range": [54250, 56000],
                       "formula_ticks": "floor((target - 50000) / 10)", "clamped_ticks": [80, 600]},
                "sl": {"mode": "fixed", "ticks": 200},
            }
        if phase.startswith("funded_trade") and not phase.startswith("funded_trade1"):
            return {
                "tp": {"mode": "randomized", "method": "target_balance_dollars",
                       "target_balance_range": [53500, 55000],
                       "formula_ticks": "floor((target - balance) / 10)", "clamped_ticks": [80, 600]},
                "sl": {"mode": "randomized", "method": "floor_room_above_50100",
                       "formula_ticks": "min(600, floor((balance - 50100) / 10))"},
            }
        if is_farming:
            return {
                "tp": {"mode": "fixed", "ticks": 31, "qty": 1},
                "sl": {"mode": "randomized", "method": "base_plus_daily_jitter",
                       "base_range": [160, 320], "jitter": [-15, 15], "clamped_range": [100, 390]},
            }
        if phase.startswith("live_trade"):
            return {
                "tp": {"mode": "fixed", "ticks": 100},
                "sl": {"mode": "randomized", "method": "floor_room_above_50100",
                       "formula_ticks": "min(600, floor((balance - 50100) / 10))"},
            }
        return _fixed(blueprint_tp, blueprint_sl)

    # ── Generic (legacy blueprints) ──
    if phase.startswith("challenge"):
        return _fixed(blueprint_tp, blueprint_sl)
    if phase.startswith(("payout", "doubledip")):
        return _fixed(blueprint_tp, blueprint_sl)

    if blueprint_tp <= 0 and blueprint_sl <= 0:
        return _fixed(None, None)

    is_farming_phase = is_farming or "qualifying" in phase or phase.startswith("live_trade")
    use_flex_room = (
        firm == "Funded Next Flex"
        and phase.startswith("funded_trade")
        and not phase.startswith("funded_trade1")
    )

    meta = {"policy": "funded_next_flex_room_sl" if use_flex_room else "generic_per_account"}

    if is_farming_phase:
        meta["tp"] = {"mode": "fixed", "ticks": int(blueprint_tp) if blueprint_tp else None,
                      "note": "Farming TP stays at blueprint"}
        if blueprint_sl > 0:
            meta["sl"] = {
                "mode": "randomized",
                "method": "blueprint_sl_factor_per_account",
                "factor_range": [0.90, 1.10],
                "blueprint_ticks": int(blueprint_sl),
                "effective_ticks_range": [
                    max(10, int(round(blueprint_sl * 0.90))),
                    max(10, int(round(blueprint_sl * 1.10))),
                ],
            }
        else:
            meta["sl"] = {"mode": "fixed", "ticks": None}
    else:
        if blueprint_tp > 0:
            meta["tp"] = {
                "mode": "randomized",
                "method": "blueprint_tp_factor_per_account",
                "factor_range": [0.92, 1.08],
                "blueprint_ticks": int(blueprint_tp),
                "effective_ticks_range": [
                    max(5, int(round(blueprint_tp * 0.92))),
                    max(5, int(round(blueprint_tp * 1.08))),
                ],
                "unique_tp_per_firm": phase.startswith("funded_trade"),
            }
        else:
            meta["tp"] = {"mode": "fixed", "ticks": None}
        meta["sl"] = {
            "mode": "fixed",
            "ticks": int(blueprint_sl) if blueprint_sl else None,
            "note": "Blueprint SL; may be adjusted at order time by calculate_funded_sl / midnight / TMDL",
        }

    return meta


def _column_summary(legs: list) -> dict:
    if not legs:
        return {"mode": "none", "trade_count": 0, "trades": []}

    modes = set()
    for leg in legs:
        for side in ("tp", "sl"):
            m = leg["randomization"].get(side, {}).get("mode")
            if m:
                modes.add(m)
        if leg["randomization"].get("policy"):
            pass

    if modes <= {"fixed"}:
        col_mode = "static"
    elif modes <= {"randomized"}:
        col_mode = "randomized"
    elif modes & {"fixed", "randomized"}:
        col_mode = "mixed"
    else:
        col_mode = "unknown"

    return {"mode": col_mode, "trade_count": len(legs), "trades": legs}


def build_export() -> dict:
    mgr = PropFirmManager()
    firms_out = {}

    for firm_code in sorted(mgr.firm_blueprints.keys()):
        info = mgr.firm_blueprints[firm_code]
        strategies = info.get("strategy_configs") or {}
        columns = {"eval": [], "funded": [], "farming": []}

        for phase_key in sorted(strategies.keys()):
            col = _phase_column(phase_key)
            if not col:
                continue
            size_map = strategies[phase_key]
            cfg = size_map.get(DEFAULT_SIZE) or size_map.get("50k") or {}
            if not cfg:
                for v in size_map.values():
                    if isinstance(v, dict) and v:
                        cfg = v
                        break
            ticks = _pick_ticks(cfg)
            bp_tp = float(cfg.get("tradovate_tp_ticks") or cfg.get("topstepx_tp_ticks") or 0)
            bp_sl = float(cfg.get("tradovate_sl_ticks") or cfg.get("topstepx_sl_ticks") or 0)
            rand = _randomization_meta(firm_code, phase_key, bp_tp, bp_sl)
            if isinstance(rand, dict) and "tp" not in rand and "sl" not in rand:
                rand = {**rand, **_fixed(bp_tp, bp_sl)}
            elif isinstance(rand, dict) and "tp" in rand:
                pass
            columns[col].append({
                "phase_key": phase_key,
                "blueprint": ticks,
                "randomization": rand,
            })

        firms_out[firm_code] = {
            "display_name": info.get("name", firm_code),
            "account_sizes": info.get("account_sizes", []),
            "trading_phases": info.get("trading_phases", []),
            "broker_platform": info.get("broker_platform"),
            "eval": _column_summary(columns["eval"]),
            "funded": _column_summary(columns["funded"]),
            "farming": _column_summary(columns["farming"]),
        }

    return {
        "meta": {
            "source_module": "trader_companion/prop_firm_manager.py",
            "default_account_size_key": DEFAULT_SIZE,
            "columns": ["eval", "funded", "farming"],
            "legend": {
                "blueprint": "Static values in firm_blueprints before randomize_trade_config runs.",
                "randomization": "What randomize_trade_config may change at order time.",
                "runtime_note": "Many firms also adjust SL via calculate_funded_sl, calculate_adjusted_sl_midnight, or TMDL cap after randomization.",
            },
            "runtime_sl_adjustments": {
                "calculate_funded_sl": "Funded trade 2+: SL$ = balance - lock_level; trade 1 often fixed $2k risk (see app path).",
                "calculate_adjusted_sl_midnight": "Challenge/intraday: widen/tighten SL from SOD balance vs blueprint SL dollars.",
                "calculate_adjusted_sl_tmdl_cap": "Cap SL to remaining trailing drawdown before lock.",
            },
        },
        "prop_firms": firms_out,
    }


def main():
    parser = argparse.ArgumentParser(description="Export prop firm SL/TP JSON")
    parser.add_argument(
        "-o", "--output",
        default=os.path.join(ROOT, "trader_companion", "prop_firm_sl_tp.json"),
        help="Output JSON path",
    )
    args = parser.parse_args()
    data = build_export()
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {len(data['prop_firms'])} firms -> {args.output}")


if __name__ == "__main__":
    main()
