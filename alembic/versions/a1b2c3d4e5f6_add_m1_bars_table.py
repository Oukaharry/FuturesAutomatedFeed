"""Alembic migration: m1_bars table for companion M1 OHLC sync."""

from alembic import op

revision = "a1b2c3d4e5f6_m1_bars"
down_revision = "5b29b54b57fa"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS m1_bars (
            client_id   TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            bar_time    BIGINT NOT NULL,
            open        DOUBLE PRECISION,
            high        DOUBLE PRECISION,
            low         DOUBLE PRECISION,
            close       DOUBLE PRECISION,
            tick_volume BIGINT,
            PRIMARY KEY (client_id, symbol, bar_time)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_m1_bars_client_symbol_time
        ON m1_bars (client_id, symbol, bar_time DESC)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_m1_bars_client_symbol_time")
    op.execute("DROP TABLE IF EXISTS m1_bars")
