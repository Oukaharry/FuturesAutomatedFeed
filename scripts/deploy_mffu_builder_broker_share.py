#!/usr/bin/env python3
"""
Deploy MFFU Builder ↔ MFFU Tradovate share workaround to production.

1. Upload apply script (+ trader_app.py fix for next companion rebuild)
2. Clone MFFU Tradovate creds onto "MFFU Builder" prop_accounts rows
3. Reload www.tradeopss.com

Usage:
  python3 scripts/deploy_mffu_builder_broker_share.py
  python3 scripts/deploy_mffu_builder_broker_share.py --client "Angel Islas"
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from download_from_prod import BASE, REMOTE, TOKEN, _ssl_ctx  # noqa: E402

USERNAME = "ballerquotes"
HOST = "www.pythonanywhere.com"
API = f"https://{HOST}/api/v0/user/{USERNAME}"
DOMAIN = "www.tradeopss.com"
REMOTE_ROOT = REMOTE
VENV_PYTHON = "/home/ballerquotes/.virtualenvs/tradeopss/bin/python"

UPLOADS = [
    ("scripts/apply_mffu_builder_broker_share.py",
     f"{REMOTE_ROOT}/scripts/apply_mffu_builder_broker_share.py"),
    ("trader_companion/trader_app.py",
     f"{REMOTE_ROOT}/trader_companion/trader_app.py"),
]


def _token() -> str:
    return os.environ.get("PYTHONANYWHERE_TOKEN", TOKEN).strip()


def _request(url: str, method: str = "GET", data: bytes | None = None, headers: dict | None = None):
    hdrs = {"Authorization": f"Token {_token()}"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    return urllib.request.urlopen(req, context=_ssl_ctx)


def _multipart_body(file_bytes: bytes, filename: str) -> tuple[bytes, str]:
    boundary = f"----DeployBuilder{uuid.uuid4().hex}"
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="content"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: application/octet-stream\r\n\r\n",
        file_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return body, f"multipart/form-data; boundary={boundary}"


def upload_file(local_rel: str, remote_path: str) -> None:
    local_path = ROOT / local_rel
    if not local_path.is_file():
        raise SystemExit(f"Missing local file: {local_path}")
    body, ctype = _multipart_body(local_path.read_bytes(), local_path.name)
    url = f"{BASE}{remote_path}"
    print(f"Uploading {local_rel} -> {remote_path} ...")
    with _request(
        url,
        method="POST",
        data=body,
        headers={"Content-Type": ctype, "Content-Length": str(len(body))},
    ) as resp:
        print(f"  HTTP {resp.status}")


def reload_webapp() -> None:
    url = f"{API}/webapps/{DOMAIN}/reload/"
    print(f"Reloading {DOMAIN} ...")
    with _request(url, method="POST", data=b"") as resp:
        print(f"  HTTP {resp.status}")


def _create_bash_console() -> int:
    payload = json.dumps({
        "executable": "bash",
        "arguments": "",
        "working_directory": REMOTE_ROOT,
    }).encode()
    url = f"{API}/consoles/"
    with _request(
        url,
        method="POST",
        data=payload,
        headers={"Content-Type": "application/json"},
    ) as resp:
        data = json.loads(resp.read().decode())
    console_id = int(data["id"])
    print(f"Opened bash console id={console_id}")
    return console_id


def _console_send(console_id: int, text: str) -> None:
    url = f"{API}/consoles/{console_id}/send_input/"
    body = f"input={urllib.parse.quote_plus(text)}".encode()
    with _request(
        url,
        method="POST",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as resp:
        resp.read()


def _console_latest(console_id: int) -> str:
    url = f"{API}/consoles/{console_id}/get_latest_output/"
    with _request(url) as resp:
        data = json.loads(resp.read().decode())
    return data.get("output") or ""


def run_apply_on_prod(client: str | None) -> None:
    console_id = _create_bash_console()
    time.sleep(3)
    client_arg = f' --client "{client}"' if client else ""
    cmd = (
        f"cd {REMOTE_ROOT} && "
        f"export FLASK_ENV=production && "
        f"set -a && source .env && set +a && "
        f"{VENV_PYTHON} scripts/apply_mffu_builder_broker_share.py{client_arg} && "
        f"{VENV_PYTHON} scripts/apply_mffu_builder_broker_share.py{client_arg} --apply\n"
    )
    print("Running apply_mffu_builder_broker_share.py on production ...")
    _console_send(console_id, cmd)

    output = ""
    for _ in range(40):
        time.sleep(2)
        output = _console_latest(console_id)
        if "Done." in output or "No clients need" in output or "Traceback" in output:
            break
    print("--- console output (tail) ---")
    print(output[-5000:] if output else "(no output yet)")
    if "Traceback" in output:
        raise SystemExit("Apply failed — see console output above")
    if "Done." not in output and "No clients need" not in output:
        raise SystemExit(
            "DB apply may not have completed — check PythonAnywhere Bash console manually"
        )


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default=None, help="Limit DB clone to one client_id")
    ap.add_argument("--skip-db", action="store_true")
    args = ap.parse_args()

    for local_rel, remote in UPLOADS:
        upload_file(local_rel, remote)

    if not args.skip_db:
        run_apply_on_prod(args.client)

    reload_webapp()
    print(
        "\nDone.\n"
        "No exe rebuild: on Tradeopss AI, reload Angel Islas, then Connect the "
        "'MFFU Builder' broker row (same Tradovate login as MFFU) — auto-trade "
        "will stop skipping Builder.\n"
        "Permanent fix is already on the server in trader_app.py for the next build."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
