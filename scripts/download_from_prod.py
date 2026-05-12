"""
scripts/download_from_prod.py
------------------------------
Download files from PythonAnywhere production.

Usage — named shortcuts:
    python scripts/download_from_prod.py             # download all shortcuts
    python scripts/download_from_prod.py db          # recovered db
    python scripts/download_from_prod.py hierarchy   # hierarchy.json
    python scripts/download_from_prod.py backup      # today's pg_dump backup
                                                       (pg_backups/pgbackup-YYYY-MM-DD-0001.dump)

Usage — specific backup date:
    python scripts/download_from_prod.py --date 2026-04-23 backup

Usage — custom file:
    python scripts/download_from_prod.py --src /home/ballerquotes/MT5Dashboard/config/settings.py --dest config/settings.py
"""
import os, sys, ssl, urllib.request, argparse
from datetime import date

def _make_ssl_context():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for cafile in (
        "/etc/ssl/cert.pem",
        "/usr/local/etc/openssl@3/cert.pem",
        "/opt/homebrew/etc/ca-certificates/cert.pem",
    ):
        if os.path.isfile(cafile):
            return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


_ssl_ctx = _make_ssl_context()


def _urlopen(req):
    return urllib.request.urlopen(req, context=_ssl_ctx)


TOKEN   = "b0074de864d103e9a7f52574ba59e6c9a53950ae"
BASE    = "https://www.pythonanywhere.com/api/v0/user/ballerquotes/files/path"
REMOTE  = "/home/ballerquotes/MT5Dashboard"
PG_BACKUPS_REMOTE = "/home/ballerquotes/pg_backups"
LOCAL   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Allow callers to override the date via `--date YYYY-MM-DD`; default is today.
_backup_date = date.today().strftime("%Y-%m-%d")
if "--date" in sys.argv:
    _i = sys.argv.index("--date")
    if _i + 1 < len(sys.argv):
        _backup_date = sys.argv[_i + 1]
        del sys.argv[_i:_i + 2]
_backup_name = f"pgbackup-{_backup_date}-0001.dump"

FILES = {
    "db":        (f"{REMOTE}/dashboard/dashboard.db_recovered", os.path.join(LOCAL, "dashboard.db_recovered")),
    "hierarchy": (f"{REMOTE}/config/hierarchy.json",            os.path.join(LOCAL, "config", "hierarchy.json")),
    "backup":    (f"{PG_BACKUPS_REMOTE}/{_backup_name}",        os.path.join(LOCAL, "pg_backups", _backup_name)),
}

def download(remote, local):
    print(f"Downloading {remote} ...")
    req  = urllib.request.Request(f"{BASE}{remote}", headers={"Authorization": f"Token {TOKEN}"})
    data = _urlopen(req).read()
    os.makedirs(os.path.dirname(os.path.abspath(local)), exist_ok=True)
    with open(local, "wb") as f:
        f.write(data)
    print(f"  Saved {len(data):,} bytes -> {os.path.abspath(local)}")

def main():
    # -- custom --src / --dest mode
    if "--src" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--src",  required=True, help="Remote absolute path on PythonAnywhere")
        parser.add_argument("--dest", required=True, help="Local destination path")
        args = parser.parse_args()
        download(args.src, args.dest)
        return

    # -- shortcut mode
    targets = [a for a in sys.argv[1:] if not a.startswith("-")] or list(FILES.keys())
    for t in targets:
        if t not in FILES:
            print(f"Unknown target '{t}'. Choose from: {', '.join(FILES)}")
            print("Or use: --src /remote/path --dest local/path")
            sys.exit(1)
        download(*FILES[t])

    print("Done.")


if __name__ == "__main__":
    main()
