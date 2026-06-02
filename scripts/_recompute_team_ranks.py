"""Recompute admin team ranks for probe report (requires venv with Flask)."""
import json
import sys
sys.path.insert(0, ".")

from config.hierarchy import get_all_clients, get_client_profile
from dashboard.database import get_setting
from dashboard.app import compute_admin_teams_ranked

def main():
    dates = sys.argv[1:] or ["2026-05-29", "2026-05-28", "2026-05-27"]
    try:
        excluded_traders = set(json.loads(get_setting("summary_tracker_excluded_traders") or "[]"))
        excluded_clients = set(json.loads(get_setting("summary_tracker_excluded_clients") or "[]"))
    except Exception:
        excluded_traders, excluded_clients = set(), set()

    all_clients = get_all_clients()
    filtered = []
    for cid in all_clients:
        if cid in excluded_clients:
            continue
        prof = get_client_profile(cid) or {}
        if (prof.get("trader") or "Unassigned") in excluded_traders:
            continue
        filtered.append(cid)

    out = {}
    for d in dates:
        ranked = compute_admin_teams_ranked(d, filtered, excluded_clients, excluded_traders)
        out[d] = ranked
    print(json.dumps(out, indent=2, default=str))

if __name__ == "__main__":
    main()
