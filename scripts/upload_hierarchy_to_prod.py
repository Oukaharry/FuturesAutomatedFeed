"""
Upload local config/hierarchy.json to PythonAnywhere production.

Use this after local hierarchy-only fixes when your normal deploy does not ship
the JSON file:

    python scripts/upload_hierarchy_to_prod.py

Safety:
  - downloads the current production hierarchy into config/prod_hierarchy_backups/
  - uploads the local config/hierarchy.json to the production path
  - re-downloads the production file and verifies it matches local bytes

Set PYTHONANYWHERE_TOKEN to override the token from scripts/download_from_prod.py.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
import urllib.request
from datetime import datetime
from pathlib import Path

from download_from_prod import BASE, LOCAL, REMOTE, TOKEN, _ssl_ctx


REMOTE_HIERARCHY = f"{REMOTE}/config/hierarchy.json"
LOCAL_HIERARCHY = Path(LOCAL) / "config" / "hierarchy.json"
BACKUP_DIR = Path(LOCAL) / "config" / "prod_hierarchy_backups"


def _token() -> str:
    return os.environ.get("PYTHONANYWHERE_TOKEN", TOKEN).strip()


def _request(remote_path: str, method: str = "GET", data: bytes | None = None, headers: dict | None = None):
    req_headers = {"Authorization": f"Token {_token()}"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(
        f"{BASE}{remote_path}",
        data=data,
        headers=req_headers,
        method=method,
    )
    return urllib.request.urlopen(req, context=_ssl_ctx)


def download_remote(remote_path: str) -> bytes:
    with _request(remote_path) as response:
        return response.read()


def _multipart_content(file_bytes: bytes, filename: str) -> tuple[bytes, str]:
    boundary = f"----CursorHierarchyUpload{uuid.uuid4().hex}"
    body = b"".join([
        f"--{boundary}\r\n".encode("ascii"),
        (
            'Content-Disposition: form-data; name="content"; '
            f'filename="{filename}"\r\n'
        ).encode("utf-8"),
        b"Content-Type: application/json\r\n\r\n",
        file_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode("ascii"),
    ])
    return body, f"multipart/form-data; boundary={boundary}"


def upload_remote(remote_path: str, local_path: Path) -> int:
    file_bytes = local_path.read_bytes()
    body, content_type = _multipart_content(file_bytes, local_path.name)
    with _request(
        remote_path,
        method="POST",
        data=body,
        headers={"Content-Type": content_type, "Content-Length": str(len(body))},
    ) as response:
        return response.status


def backup_remote_hierarchy() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"hierarchy.prod.{stamp}.json"
    backup_path.write_bytes(download_remote(REMOTE_HIERARCHY))
    return backup_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload local config/hierarchy.json to production.")
    parser.add_argument("--local", default=str(LOCAL_HIERARCHY), help="Local hierarchy JSON path")
    parser.add_argument("--remote", default=REMOTE_HIERARCHY, help="Remote PythonAnywhere hierarchy path")
    parser.add_argument("--no-backup", action="store_true", help="Skip downloading a production backup first")
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen without uploading")
    args = parser.parse_args()

    local_path = Path(args.local).resolve()
    remote_path = args.remote

    if not local_path.exists():
        print(f"ERROR: local hierarchy not found: {local_path}", file=sys.stderr)
        return 1

    local_bytes = local_path.read_bytes()
    print(f"Local:  {local_path} ({len(local_bytes):,} bytes)")
    print(f"Remote: {remote_path}")

    if args.dry_run:
        print("Dry run only. No production files changed.")
        return 0

    if not args.no_backup:
        backup_path = backup_remote_hierarchy()
        print(f"Backed up production hierarchy -> {backup_path}")

    status = upload_remote(remote_path, local_path)
    if status not in (200, 201):
        print(f"ERROR: upload returned unexpected HTTP status {status}", file=sys.stderr)
        return 2
    print(f"Uploaded hierarchy to production (HTTP {status}).")

    remote_bytes = download_remote(remote_path)
    if remote_bytes != local_bytes:
        print("ERROR: verification failed; remote file does not match local file.", file=sys.stderr)
        return 3

    print("Verified: production hierarchy now matches local config/hierarchy.json.")
    print("The app reloads hierarchy on /api/hierarchy, so a webapp restart is usually not required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
