"""
SQLAlchemy engine + session factory.

Reads DATABASE_URL from environment (or .env file).
Falls back to SQLite for legacy compatibility.

Set in .env:
    DATABASE_URL=postgresql://postgres:password@localhost:5432/tradeopss
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    # fallback: existing SQLite db
    f"sqlite:///{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.db')}"
)

# PostgreSQL: use pool_pre_ping to recover from dropped connections
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,  # set True to log all SQL during dev
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_session():
    """Dependency-style session: use as context manager."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
