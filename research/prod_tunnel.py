"""SSH tunnel to PythonAnywhere production PostgreSQL."""

from __future__ import annotations

import os
import socket
import time
from contextlib import contextmanager
from typing import Iterator, Optional
from urllib.parse import quote_plus

_tunnel = None


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def build_production_database_url(local_port: int) -> str:
    user = _env("PRODUCTION_DB_USER", "tradeopss_admin")
    password = _env("PRODUCTION_DB_PASSWORD")
    dbname = _env("PRODUCTION_DB_NAME", "tradeopss")
    if not password:
        raise RuntimeError("PRODUCTION_DB_PASSWORD is not set in .env")
    return (
        f"postgresql://{quote_plus(user)}:{quote_plus(password)}"
        f"@127.0.0.1:{local_port}/{dbname}"
    )


def _pick_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_local_port(host: str, port: int, timeout: float = 60.0) -> None:
    """Tunnel may bind before remote Postgres accepts connections."""
    deadline = time.time() + timeout
    last_err: Optional[Exception] = None
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=3):
                return
        except OSError as e:
            last_err = e
            time.sleep(0.75)
    raise RuntimeError(
        f"Forwarded Postgres not reachable at {host}:{port} after {timeout:.0f}s: {last_err}"
    )


@contextmanager
def production_ssh_tunnel() -> Iterator[str]:
    """
    Open SSH tunnel and yield a DATABASE_URL pointing at 127.0.0.1:<local_port>.

    Requires: pip install sshtunnel
    Env: PRODUCTION_DB_HOST, PRODUCTION_DB_PORT, SSH_TUNNEL_* , PRODUCTION_DB_* creds
    """
    global _tunnel

    use_tunnel = _env("PRODUCTION_USE_SSH_TUNNEL", "true").lower() in ("1", "true", "yes")
    if not use_tunnel:
        url = _env("PRODUCTION_DATABASE_URL")
        if not url:
            raise RuntimeError("Set PRODUCTION_DATABASE_URL or PRODUCTION_USE_SSH_TUNNEL=true")
        yield url
        return

    try:
        from sshtunnel import SSHTunnelForwarder
    except ImportError as e:
        raise RuntimeError(
            "Install sshtunnel: pip install sshtunnel"
        ) from e

    remote_host = _env("PRODUCTION_DB_HOST")
    remote_port = int(_env("PRODUCTION_DB_PORT", "15185"))
    ssh_host = _env("SSH_TUNNEL_HOST", "ssh.pythonanywhere.com")
    ssh_port = int(_env("SSH_TUNNEL_PORT", "22"))
    ssh_user = _env("SSH_TUNNEL_USER", "ballerquotes")
    ssh_password = _env("SSH_TUNNEL_PASSWORD")

    if not remote_host or not ssh_password:
        raise RuntimeError(
            "Missing PRODUCTION_DB_HOST or SSH_TUNNEL_PASSWORD in .env"
        )

    local_port = _pick_free_local_port()
    _tunnel = SSHTunnelForwarder(
        (ssh_host, ssh_port),
        ssh_username=ssh_user,
        ssh_password=ssh_password,
        remote_bind_address=(remote_host, remote_port),
        local_bind_address=("127.0.0.1", local_port),
        set_keepalive=30.0,
    )
    _tunnel.start()
    if not _tunnel.is_active:
        raise RuntimeError("SSH tunnel failed to start")
    _wait_for_local_port("127.0.0.1", local_port, timeout=float(_env("SSH_TUNNEL_READY_TIMEOUT", "60")))
    try:
        yield build_production_database_url(local_port)
    finally:
        _tunnel.stop()
        _tunnel = None
