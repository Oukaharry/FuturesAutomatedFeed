"""List Prop Day / Hedge Day values for all farming rows from the dashboard."""
import json
import requests

EMAIL = "harryodhiambo16@gmail.com"
URL = "https://www.tradeopss.com/api/client/data"

r = requests.post(URL, json={"email": EMAIL},
                  headers={"Content-Type": "application/json"}, timeout=30)
r.raise_for_status()
data = r.json()
evals = data.get("evaluations", []) or []
print(f"Total eval rows: {len(evals)}\n")

found_any = False
for idx, ev in enumerate(evals):
    if ev.get("_deleted"):
        continue
    prop_days = {}
    hedge_days = {}
    for i in range(1, 61):
        pv = str(ev.get(f"Prop Day {i}", "") or "").strip()
        hv = str(ev.get(f"Hedge Day {i}", "") or "").strip()
        if pv:
            prop_days[i] = pv
        if hv:
            hedge_days[i] = hv
    if not prop_days and not hedge_days:
        continue
    found_any = True
    firm = ev.get("Prop Firm", "?")
    acct = ev.get("Account #.1") or ev.get("Account #") or "?"
    size = ev.get("Account Size", "?")
    status = ev.get("Status") or ev.get("Status P1") or ""
    print(f"Row {idx + 1}: {firm} | {acct} | {size} | status={status}")
    all_slots = sorted(set(prop_days) | set(hedge_days))
    for s in all_slots:
        print(f"   Day {s:>2}:  Prop = {prop_days.get(s, '—'):>12}   Hedge = {hedge_days.get(s, '—'):>12}")
    print()

if not found_any:
    print("No rows with Prop Day or Hedge Day values found.")
