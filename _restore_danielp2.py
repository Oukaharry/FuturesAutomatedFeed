import requests

email = "dpedtrading@yahoo.com"
base = "https://www.tradeopss.com"

# Fetch history list only (no individual version fetches)
r = requests.post(f"{base}/api/client/history", json={"email": email, "limit": 200}, timeout=30)
data = r.json()
client_id = data.get("client_id", "?")
history = data.get("history", [])
total = data.get("total_versions", "?")
print(f"Client: {client_id} | Total versions: {total}\n")

for v in history:
    ver = v["version"]
    by = v.get("changed_by", "?")
    action = v.get("action", "?")
    desc = (v.get("change_description", "") or "")[:80]
    date = v.get("created_at", "")[:19]
    print(f"v{ver} | {date} | by: {by} | {action} | {desc}")
