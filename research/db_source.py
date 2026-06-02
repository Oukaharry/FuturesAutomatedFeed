"""Select local vs production PostgreSQL for research scripts."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Callable, Iterator, Literal, Optional, TypeVar
from urllib.parse import urlparse

SourceKind = Literal["local", "production", "prod_backup"]

T = TypeVar("T")


def _mask_url(url: str) -> str:
    """Host/db only — never log passwords."""
    try:
        p = urlparse(url)
        host = p.hostname or "?"
        port = p.port or 5432
        db = (p.path or "").lstrip("/") or "?"
        user = p.username or "?"
        return f"{user}@{host}:{port}/{db}"
    except Exception:
        return "(unparseable url)"


def _env_bool(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes")


def resolve_production_url() -> str:
    """Direct production URL (no SSH tunnel)."""
    prod = (os.environ.get("PRODUCTION_DATABASE_URL") or "").strip()
    if prod:
        return prod
    local_default = "postgresql://postgres:postgres123@localhost:5432/tradeopss"
    current = (os.environ.get("DATABASE_URL") or local_default).strip()
    host = urlparse(current).hostname or ""
    if host not in ("localhost", "127.0.0.1", ""):
        return current
    raise RuntimeError(
        "Set PRODUCTION_DATABASE_URL or enable PRODUCTION_USE_SSH_TUNNEL in .env"
    )


def _apply_database_url(url: str) -> None:
    os.environ["DATABASE_URL"] = url
    # SSH tunnel to PythonAnywhere can be slow on first connect
    os.environ.setdefault("DB_CONNECT_TIMEOUT", "45")
    os.environ.setdefault("DB_POOL_MIN", "1")
    os.environ.setdefault("DB_POOL_MAX", "3")
    from dashboard import database as db

    db.DATABASE_URL = url
    db.reset_connection_pool()
    # Re-read timeout after env change
    db._db_connect_timeout = max(5, int(os.environ.get("DB_CONNECT_TIMEOUT", "45")))
    ok, msg = db.check_and_repair_database()
    if not ok:
        raise RuntimeError(f"Database connection failed: {msg}")


def configure_source(
    *,
    production: bool = False,
    database_url: Optional[str] = None,
) -> SourceKind:
    """
    Point dashboard.database at the requested server (no SSH tunnel).

    For production over SSH, use run_with_production() instead.
    """
    from dotenv import load_dotenv

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(root, ".env"))

    kind: SourceKind = "local"
    if database_url:
        url = database_url.strip()
        kind = "prod_backup" if "localhost" in _mask_url(url) else "production"
    elif production:
        if _env_bool("PRODUCTION_USE_SSH_TUNNEL"):
            raise RuntimeError("Use run_with_production() when PRODUCTION_USE_SSH_TUNNEL=true")
        url = resolve_production_url()
        kind = "production"
    else:
        url = (os.environ.get("DATABASE_URL") or "").strip()
        if not url or url.startswith("sqlite"):
            raise RuntimeError(
                "DATABASE_URL must be PostgreSQL for research, or pass --production."
            )

    _apply_database_url(url)
    return kind


@contextmanager
def run_with_production() -> Iterator[SourceKind]:
    """
    Open SSH tunnel (if configured), connect to production, yield, then close tunnel.
    """
    from dotenv import load_dotenv

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(root, ".env"))

    if _env_bool("PRODUCTION_USE_SSH_TUNNEL"):
        from research.prod_tunnel import production_ssh_tunnel

        with production_ssh_tunnel() as url:
            _apply_database_url(url)
            yield "production"
    else:
        _apply_database_url(resolve_production_url())
        yield "production"


def run_learning_with_source(
    fn: Callable[[], T],
    *,
    production: bool = False,
    database_url: Optional[str] = None,
) -> tuple[T, SourceKind, str]:
    """Run fn() after DB is configured; returns (result, kind, source_description)."""
    if production and _env_bool("PRODUCTION_USE_SSH_TUNNEL"):
        with run_with_production() as kind:
            from dashboard.database import DATABASE_URL

            desc = describe_active_source(kind)
            return fn(), kind, desc
    kind = configure_source(production=production, database_url=database_url)
    return fn(), kind, describe_active_source(kind)


def describe_active_source(kind: SourceKind) -> str:
    from dashboard.database import DATABASE_URL

    return f"data_source={kind} target={_mask_url(DATABASE_URL)}"
