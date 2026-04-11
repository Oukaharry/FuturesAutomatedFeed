import requests

email = "dpedtrading@yahoo.com"
base = "https://www.tradeopss.com"

# Fetch history
r = requests.post(f"{base}/api/client/history", json={"email": email, "limit": 200}, timeout=30)
data = r.json()
client_id = data.get("client_id", "?")
print(f"Client: {client_id}\n")

for v in data.get("history", []):
    ver = v["version"]
    vr = requests.post(f"{base}/api/client/version", json={"email": email, "version": ver}, timeout=15)
    if vr.status_code == 200:
        evals = len(vr.json().get("data", {}).get("evaluations", []))
    else:
        evals = "?"
    by = v.get("changed_by", "?")
    action = v.get("action", "?")
    desc = (v.get("change_description", "") or "")[:60]
    date = v.get("created_at", "")[:19]
    print(f"v{ver} | {date} | evals: {evals} | by: {by} | {action} | {desc}")
