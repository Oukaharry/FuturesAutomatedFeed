"""Alembic migration: api_response_cache for shared endpoint caching."""

from alembic import op

revision = "b2c3d4e5f6a7_api_cache"
down_revision = "a1b2c3d4e5f6_m1_bars"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS api_response_cache (
            cache_key   TEXT PRIMARY KEY,
            payload     TEXT NOT NULL,
            expires_at  TIMESTAMPTZ NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_api_response_cache_expires
        ON api_response_cache (expires_at)
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_api_response_cache_expires")
    op.execute("DROP TABLE IF EXISTS api_response_cache")
