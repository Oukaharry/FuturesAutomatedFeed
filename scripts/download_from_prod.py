"""
scripts/download_from_prod.py
------------------------------
Download files from PythonAnywhere production.

Usage — named shortcuts:
    python scripts/download_from_prod.py             # download all shortcuts
    python scripts/download_from_prod.py db          # recovered db
    python scripts/download_from_prod.py hierarchy   # hierarchy.json
    python scripts/download_from_prod.py backup      # latest pg_dump for today
                                                       (pg_backups/pgbackup-YYYY-MM-DD-HHMM.dump)

Usage — specific backup date:
    python scripts/download_from_prod.py --date 2026-04-23 backup

Usage — custom file:
    python scripts/download_from_prod.py --src /home/ballerquotes/MT5Dashboard/config/settings.py --dest config/settings.py
"""
import json
import os
import sys
import ssl
import urllib.request
import argparse
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


def _list_remote_backups():
    url = f"https://www.pythonanywhere.com/api/v0/user/ballerquotes/files/tree/?path={PG_BACKUPS_REMOTE}"
    req = urllib.request.Request(url, headers={"Authorization": f"Token {TOKEN}"})
    with _urlopen(req) as resp:
        paths = json.loads(resp.read().decode())
    return sorted(os.path.basename(p) for p in paths if p.endswith(".dump"))


def _resolve_backup_name(for_date=None):
    """Pick the latest pgbackup-YYYY-MM-DD-HHMM.dump for the given date."""
    target_date = for_date or _backup_date
    prefix = f"pgbackup-{target_date}-"
    matches = [name for name in _list_remote_backups() if name.startswith(prefix)]
    if not matches:
        available = _list_remote_backups()
        hint = ", ".join(available[-5:]) if available else "(none on server)"
        raise SystemExit(
            f"No backup found for {target_date}. "
            f"Expected {prefix}HHMM.dump. Recent on server: {hint}"
        )
    return max(matches)


def _backup_paths():
    name = _resolve_backup_name()
    return (
        f"{PG_BACKUPS_REMOTE}/{name}",
        os.path.join(LOCAL, "pg_backups", name),
    )


FILES = {
    "db":        (f"{REMOTE}/dashboard/dashboard.db_recovered", os.path.join(LOCAL, "dashboard.db_recovered")),
    "hierarchy": (f"{REMOTE}/config/hierarchy.json",            os.path.join(LOCAL, "config", "hierarchy.json")),
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
    targets = [a for a in sys.argv[1:] if not a.startswith("-")] or list(FILES.keys()) + ["backup"]
    for t in targets:
        if t == "backup":
            download(*_backup_paths())
            continue
        if t not in FILES:
            print(f"Unknown target '{t}'. Choose from: {', '.join([*FILES, 'backup'])}")
            print("Or use: --src /remote/path --dest local/path")
            sys.exit(1)
        download(*FILES[t])

    print("Done.")


if __name__ == "__main__":
    main()
