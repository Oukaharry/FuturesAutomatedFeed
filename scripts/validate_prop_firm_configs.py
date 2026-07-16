"""Validate all prop firm blueprints resolve with complete MT5 hedge fields."""
import importlib.util
import sys

path = "trader_companion/prop_firm_manager.py"
spec = importlib.util.spec_from_file_location("pfm", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
pm = mod.PropFirmManager()

issues = []
ok = 0
for firm in pm.firm_blueprints:
    for pk in pm.firm_blueprints[firm].get("strategy_configs", {}):
        cfg = pm.get_strategy_config(firm, pk, "50k")
        sym = (cfg.get("tradovate_symbol") or cfg.get("topstepx_symbol") or "").upper()
        if "GC" in sym and "NQ" not in sym and "MNQ" not in sym:
            ok += 1
            continue
        if "NQ" not in sym and "MNQ" not in sym:
            continue
        vol = float(cfg.get("mt5_volume") or 0)
        mtp = int(cfg.get("mt5_tp_points") or 0)
        msl = int(cfg.get("mt5_sl_points") or 0)
        if vol <= 0 or mtp <= 0 or msl <= 0:
            issues.append(f"{firm}/{pk}: vol={vol} mtp={mtp} msl={msl}")
        else:
            ok += 1

# Phase order keys must exist
for firm, phases in pm._PHASE_TRADE_ORDER.items():
    configs = pm.firm_blueprints.get(firm, {}).get("strategy_configs", {})
    for phase, keys in phases.items():
        for k in keys:
            if k not in configs:
                issues.append(f"ORDER {firm}/{phase}: missing key '{k}'")

print(f"OK: {ok} NQ configs with full MT5")
if issues:
    print(f"ISSUES ({len(issues)}):")
    for i in issues:
        print(f"  - {i}")
    sys.exit(1)
print("All checks passed.")
