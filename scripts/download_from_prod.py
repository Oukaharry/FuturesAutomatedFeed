"""
scripts/download_from_prod.py
------------------------------
Download files from PythonAnywhere production.

Usage — named shortcuts:
    python scripts/download_from_prod.py             # download all shortcuts
    python scripts/download_from_prod.py db          # recovered db
    python scripts/download_from_prod.py hierarchy   # hierarchy.json

Usage — custom file:
    python scripts/download_from_prod.py --src /home/ballerquotes/MT5Dashboard/config/settings.py --dest config/settings.py
"""
import os, sys, urllib.request, argparse

TOKEN   = "b0074de864d103e9a7f52574ba59e6c9a53950ae"
BASE    = "https://www.pythonanywhere.com/api/v0/user/ballerquotes/files/path"
REMOTE  = "/home/ballerquotes/MT5Dashboard"
LOCAL   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = {
    "db":        (f"{REMOTE}/dashboard/dashboard.db_recovered", os.path.join(LOCAL, "dashboard.db_recovered")),
    "hierarchy": (f"{REMOTE}/config/hierarchy.json",            os.path.join(LOCAL, "config", "hierarchy.json")),
}

def download(remote, local):
    print(f"Downloading {remote} ...")
    req  = urllib.request.Request(f"{BASE}{remote}", headers={"Authorization": f"Token {TOKEN}"})
    data = urllib.request.urlopen(req).read()
    os.makedirs(os.path.dirname(os.path.abspath(local)), exist_ok=True)
    with open(local, "wb") as f:
        f.write(data)
    print(f"  Saved {len(data):,} bytes -> {os.path.abspath(local)}")

# -- custom --src / --dest mode
if "--src" in sys.argv:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src",  required=True, help="Remote absolute path on PythonAnywhere")
    parser.add_argument("--dest", required=True, help="Local destination path")
    args = parser.parse_args()
    download(args.src, args.dest)
    sys.exit(0)

# -- shortcut mode
targets = [a for a in sys.argv[1:] if not a.startswith("-")] or list(FILES.keys())
for t in targets:
    if t not in FILES:
        print(f"Unknown target '{t}'. Choose from: {', '.join(FILES)}")
        print("Or use: --src /remote/path --dest local/path")
        sys.exit(1)
    download(*FILES[t])

print("Done.")
