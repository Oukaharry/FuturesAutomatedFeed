# Chapter 4 — Persistence: the database layer

_Exported from CODEBASE_REFERENCE.pdf as plain Markdown. Paste this into another Claude conversation, Notion, or any Markdown viewer._

Trading data has to live somewhere — accounts, payouts, watermarks, deals, notes. We use PostgreSQL in production and SQLite for development, talking to both through SQLAlchemy. Alembic owns the schema: each version file describes a forward step ("add this column") and a rollback step ("drop it"). In this phase we wire the engine, declare the ORM models that mirror the tables, and scaffold the first two Alembic revisions.

**Files in this chapter:**

- `alembic/env.py`
- `alembic/versions/44e368d8bfce_initial_schema.py`
- `alembic/versions/5b29b54b57fa_add_firm_billing_column.py`
- `dashboard/database.py`
- `dashboard/db.py`
- `dashboard/models.py`

---

### `alembic/env.py`

_85 loc · 0 classes · 2 functions · 7 imports_

**Imports**

```python
import os
from logging.config import fileConfig
from dotenv import load_dotenv
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
from dashboard.models import Base
```

**Functions**

#### `run_migrations_offline`

```python
def run_migrations_offline() -> None
```
> Run migrations in 'offline' mode.  This configures the context with just a URL and not an Engine, though an Engine is acceptable here as well.  By skipping the Engine creation we don't even need a DBAPI to be available.  Calls to context.execute() here emit the given string to the script output.

**What it does, step by step:**

1. Assigns <code>url</code> = <code>config.get_main_option('sqlalchemy.url')</code>.
2. Calls <code>context.configure(...)</code> for its side effect.
3. <b>with</b> <code>context.begin_transaction()</code>: enters a context manager.

```python
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()
```

#### `run_migrations_online`

```python
def run_migrations_online() -> None
```
> Run migrations in 'online' mode.  In this scenario we need to create an Engine and associate a connection with the context.

**What it does, step by step:**

1. Assigns <code>connectable</code> = <code>engine_from_config(config.get_section(config.config_ini_s...</code>.
2. <b>with</b> <code>connectable.connect()</code>: enters a context manager.

```python
def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()
```

---

### `alembic/versions/44e368d8bfce_initial_schema.py`

_266 loc · 0 classes · 2 functions · 3 imports_

**Module docstring**

> initial_schema
> Revision ID: 44e368d8bfce Revises:  Create Date: 2026-04-04 11:49:23.036333

**Imports**

```python
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
```

**Functions**

#### `upgrade`

```python
def upgrade() -> None
```
> Upgrade schema.

**What it does, step by step:**

1. Calls <code>op.create_table(...)</code> for its side effect.
2. Calls <code>op.create_table(...)</code> for its side effect.
3. Calls <code>op.create_table(...)</code> for its side effect.
4. Calls <code>op.create_table(...)</code> for its side effect.
5. Calls <code>op.create_table(...)</code> for its side effect.
6. Calls <code>op.create_table(...)</code> for its side effect.
7. Calls <code>op.create_index(...)</code> for its side effect.
8. Calls <code>op.create_index(...)</code> for its side effect.
9. Calls <code>op.create_table(...)</code> for its side effect.
10. Calls <code>op.create_table(...)</code> for its side effect.
11. Calls <code>op.create_index(...)</code> for its side effect.
12. Calls <code>op.create_table(...)</code> for its side effect.
13. Calls <code>op.create_table(...)</code> for its side effect.
14. Calls <code>op.create_index(...)</code> for its side effect.
15. <i>... and 9 more statement(s) in the body.</i>

```python
def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('admin_passwords',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('username', sa.Text(), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('salt', sa.Text(), nullable=False),
    sa.Column('created_at', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_table('api_keys',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('key_hash', sa.Text(), nullable=False),
    sa.Column('key_prefix', sa.Text(), nullable=False),
    sa.Column('admin', sa.Text(), nullable=False),
    sa.Column('trader', sa.Text(), nullable=False),
    sa.Column('client', sa.Text(), server_default=sa.text("''"), nullable=True),
    sa.Column('scope', sa.Text(), server_default=sa.text("'full'"), nullable=True),
    sa.Column('created_at', sa.Text(), nullable=False),
    sa.Column('last_used', sa.Text(), nullable=True),
    sa.Column('is_active', sa.SmallInteger(), server_default=sa.text('1'), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key_hash')
    )
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('timestamp', sa.Text(), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('user_type', sa.Text(), nullable=False),
    sa.Column('user_identifier', sa.Text(), nullable=False),
    sa.Column('ip_address', sa.Text(), nullable=True),
    sa.Column('details', sa.Text(), nullable=True),
    sa.Column('success', sa.SmallInteger(), server_default=sa.text('1'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('cell_notes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('client_id', sa.Text(), nullable=False),
    sa.Column('row_index', sa.Integer(), nullable=False),
    sa.Column('column_key', sa.Text(), nullable=False),
    sa.Column('note_content', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('client_id', 'row_index', 'column_key', name='uq_cell_notes')
    )
    op.create_table('clients_data',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('client_id', sa.Text(), nullable=False),
    sa.Column('deals', sa.Text(), server_default=sa.text("'[]'"), nullable=True),
    sa.Column('positions', sa.Text(), server_default=sa.text("'[]'"), nullable=True),
    sa.Column('account', sa.Text(), server_default=sa.text("'{}'"), nullable=True),
    sa.Column('evaluations', sa.Text(), server_default=sa.text("'[]'"), nullable=True),
    sa.Column('statistics', sa.Text(), server_default=sa.text("'{}'"), nullable=True),
    sa.Column('dropdown_options', sa.Text(), server_default=sa.text("'{}'"), nullable=True),
    sa.Column('identity', sa.Text(), server_default=sa.text("'{}'"), nullable=True),
    sa.Column('last_updated', sa.Text(), nullable=False),
    sa.Column('hedge_accounts', sa.Text(), server_default=sa.text("'[]'"), nullable=True),
    sa.Column('prop_accounts', sa.Text(), server_default=sa.text("'[]'"), nullable=True),
    sa.Column('vps_accounts', sa.Text(), server_default=sa.text("'[]'"), nullable=True),
    sa.Column('payment_info', sa.Text(), server_default=sa.text("'[]'"), nullable=True),
    sa.Column('payment_address', sa.Text(), server_default=sa.text("'{}'"), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('client_id')
    )
    op.create_table('daily_checklists',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('date', sa.Text(), nullable=False),
    sa.Column('user_identifier', sa.Text(), nullable=False),
    sa.Column('user_type', sa.Text(), nullable=False),
    sa.Column('checklist_type', sa.Text(), nullable=False),
    sa.Column('client_id', sa.Text(), server_default=sa.text("''"), nullable=True),
    sa.Column('items', sa.Text(), server_default=sa.text("'[]'"), nullable=True),
    sa.Column('submitted_at', sa.Text(), nullable=False),
    sa.Column('ip_address', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('date', 'user_identifier', 'checklist_type', 'client_id', name='uq_daily_checklists')
    )
    op.create_index('idx_checklist_client', 'daily_checklists', ['date', 'client_id'], unique=False)
    op.create_index('idx_checklist_date', 'daily_checklists', ['date', 'user_identifier'], unique=False)
    op.create_table('daily_watermarks',
    sa.Column('client_id', sa.Text(), nullable=False),
    sa.Column('date', sa.Text(), nullable=False),
    sa.Column('net_profit_complete', sa.Float(), server_default=sa.text('0.0'), nullable=True),
    sa.Column('source', sa.Text(), server_default=sa.text("'auto'"), nullable=True),
    sa.Column('created_at', sa.Text(), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('client_id', 'date')
    )
    op.create_table('data_history',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('client_id', sa.Text(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('changed_by', sa.Text(), nullable=True),
    sa.Column('changed_by_type', sa.Text(), nullable=True),
    sa.Column('ip_address', sa.Text(), nullable=True),
    sa.Column('change_source', sa.Text(), nullable=True),
    sa.Column('change_description', sa.Text(), nullable=True),
    sa.Column('deals', sa.Text(), server_default=sa.text("'[]'"), nullable=True),
    sa.Column('positions', sa.Text(), server_default=sa.text("'[]'"), nullable=True),
    sa.Column('account', sa.Text(), server_default=sa.text("'{}'"), nullable=True),
    sa.Column('evaluations', sa.Text(), server_default=sa.text("'[]'"), nullable=True),
    sa.Column('statistics', sa.Text(), server_default=sa.text("'{}'"), nullable=True),
    sa.Column('dropdown_options', sa.Text(), server_default=sa.text("'{}'"), nullable=True),
    sa.Column('identity', sa.Text(), server_default=sa.text("'{}'"), nullable=True),
    sa.Column('created_at', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('client_id', 'version', name='uq_data_history_client_version')
    )
    op.create_index('idx_data_history_client', 'data_history', ['client_id', 'version'], unique=False)
    op.create_table('evaluations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('account_signature', sa.Text(), nullable=False),
    sa.Column('phase_number', sa.Integer(), nullable=False),
    sa.Column('phase_type', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=True),
    sa.Column('start_date', sa.Text(), nullable=True),
    sa.Column('end_date', sa.Text(), nullable=True),
    sa.Column('reset_id', sa.Text(), nullable=True),
    sa.Column('parent_id', sa.Integer(), nullable=True),
    sa.Column('meta_data', sa.Text(), server_default=sa.text("'{}'"), nullable=True),
    sa.Column('created_at', sa.Text(), server_default=sa.text('now()'), nullable=True),
    sa.ForeignKeyConstraint(['parent_id'], ['evaluations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('kyc_links',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('primary_client', sa.Text(), nullable=False),
    sa.Column('linked_client', sa.Text(), nullable=False),
    sa.Column('linked_by', sa.Text(), server_default=sa.text("'super_admin'"), nullable=True),
    sa.Column('created_at', sa.Text(), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('primary_client', 'linked_client', name='uq_kyc_links')
    )
    op.create_index('idx_kyc_linked', 'kyc_links', ['linked_client'], unique=False)
    op.create_index('idx_kyc_primary', 'kyc_links', ['primary_client'], unique=False)
    op.create_table('login_attempts',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('username', sa.Text(), nullable=False),
    sa.Column('user_type', sa.Text(), nullable=False),
    sa.Column('ip_address', sa.Text(), nullable=True),
    sa.Column('attempt_time', sa.Text(), nullable=False),
    sa.Column('success', sa.SmallInteger(), server_default=sa.text('0'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('phase_definitions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('phase_name', sa.Text(), nullable=False),
    sa.Column('phase_code', sa.Text(), nullable=False),
    sa.Column('sequence_order', sa.Integer(), nullable=False),
    sa.Column('ruleset', sa.Text(), server_default=sa.text("'{}'"), nullable=True),
    sa.Column('next_phase_code', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('phase_code')
    )
    op.create_table('quality_scan_results',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('scan_date', sa.Text(), nullable=False),
    sa.Column('client_id', sa.Text(), nullable=False),
    sa.Column('trader', sa.Text(), nullable=True),
    sa.Column('admin', sa.Text(), nullable=True),
    sa.Column('total_issues', sa.Integer(), server_default=sa.text('0'), nullable=True),
    sa.Column('issues', sa.Text(), server_default=sa.text("'[]'"), nullable=True),
    sa.Column('health_score', sa.Float(), server_default=sa.text('100.0'), nullable=True),
    sa.Column('created_at', sa.Text(), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_quality_scan_date', 'quality_scan_results', ['scan_date', 'client_id'], unique=False)
    op.create_table('sessions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('session_token', sa.Text(), nullable=False),
    sa.Column('user_type', sa.Text(), nullable=False),
    sa.Column('user_identifier', sa.Text(), nullable=False),
    sa.Column('created_at', sa.Text(), nullable=False),
    sa.Column('expires_at', sa.Text(), nullable=False),
    sa.Column('ip_address', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_token')
    )
    op.create_table('system_settings',
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.Text(), nullable=False),
    sa.Column('updated_by', sa.Text(), server_default=sa.text("''"), nullable=True),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('user_credentials',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('username', sa.Text(), nullable=False),
    sa.Column('email', sa.Text(), nullable=True),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('salt', sa.Text(), nullable=False),
    sa.Column('user_type', sa.Text(), nullable=False),
    sa.Column('parent_admin', sa.Text(), nullable=True),
    sa.Column('parent_trader', sa.Text(), nullable=True),
    sa.Column('is_active', sa.SmallInteger(), server_default=sa.text('1'), nullable=True),
    sa.Column('must_change_password', sa.SmallInteger(), server_default=sa.text('1'), nullable=True),
    sa.Column('last_login', sa.Text(), nullable=True),
    sa.Column('created_at', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username', 'user_type', name='uq_user_credentials_username_type')
    )
    op.create_table('waterlog_periods',
    sa.Column('client_id', sa.Text(), nullable=False),
    sa.Column('from_date', sa.Text(), nullable=False),
    sa.Column('to_date', sa.Text(), nullable=False),
    sa.Column('period_low', sa.Float(), nullable=True),
    sa.Column('period_high', sa.Float(), nullable=True),
    sa.Column('split_pct', sa.Integer(), server_default=sa.text('50'), nullable=True),
    sa.PrimaryKeyConstraint('client_id', 'from_date')
    )
```

#### `downgrade`

```python
def downgrade() -> None
```
> Downgrade schema.

**What it does, step by step:**

1. Calls <code>op.drop_table(...)</code> for its side effect.
2. Calls <code>op.drop_table(...)</code> for its side effect.
3. Calls <code>op.drop_table(...)</code> for its side effect.
4. Calls <code>op.drop_table(...)</code> for its side effect.
5. Calls <code>op.drop_index(...)</code> for its side effect.
6. Calls <code>op.drop_table(...)</code> for its side effect.
7. Calls <code>op.drop_table(...)</code> for its side effect.
8. Calls <code>op.drop_table(...)</code> for its side effect.
9. Calls <code>op.drop_index(...)</code> for its side effect.
10. Calls <code>op.drop_index(...)</code> for its side effect.
11. Calls <code>op.drop_table(...)</code> for its side effect.
12. Calls <code>op.drop_table(...)</code> for its side effect.
13. Calls <code>op.drop_index(...)</code> for its side effect.
14. Calls <code>op.drop_table(...)</code> for its side effect.
15. <i>... and 9 more statement(s) in the body.</i>

```python
def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('waterlog_periods')
    op.drop_table('user_credentials')
    op.drop_table('system_settings')
    op.drop_table('sessions')
    op.drop_index('idx_quality_scan_date', table_name='quality_scan_results')
    op.drop_table('quality_scan_results')
    op.drop_table('phase_definitions')
    op.drop_table('login_attempts')
    op.drop_index('idx_kyc_primary', table_name='kyc_links')
    op.drop_index('idx_kyc_linked', table_name='kyc_links')
    op.drop_table('kyc_links')
    op.drop_table('evaluations')
    op.drop_index('idx_data_history_client', table_name='data_history')
    op.drop_table('data_history')
    op.drop_table('daily_watermarks')
    op.drop_index('idx_checklist_date', table_name='daily_checklists')
    op.drop_index('idx_checklist_client', table_name='daily_checklists')
    op.drop_table('daily_checklists')
    op.drop_table('clients_data')
    op.drop_table('cell_notes')
    op.drop_table('audit_log')
    op.drop_table('api_keys')
    op.drop_table('admin_passwords')
```

---

### `alembic/versions/5b29b54b57fa_add_firm_billing_column.py`

_31 loc · 0 classes · 2 functions · 3 imports_

**Module docstring**

> add_firm_billing_column
> Revision ID: 5b29b54b57fa Revises: 44e368d8bfce Create Date: 2026-04-14 17:23:49.376388

**Imports**

```python
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
```

**Functions**

#### `upgrade`

```python
def upgrade() -> None
```
> Upgrade schema.

**What it does, step by step:**

1. Calls <code>op.add_column(...)</code> for its side effect.

```python
def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('clients_data', sa.Column('firm_billing', sa.Text(), server_default='{}'))
```

#### `downgrade`

```python
def downgrade() -> None
```
> Downgrade schema.

**What it does, step by step:**

1. Calls <code>op.drop_column(...)</code> for its side effect.
2. <b>pass</b> (placeholder).

```python
def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('clients_data', 'firm_billing')
    pass
```

---

### `dashboard/database.py`

_2562 loc · 2 classes · 105 functions · 10 imports_

**Module docstring**

> PostgreSQL Database Module for Trading Dashboard Provides secure storage with encrypted data and audit logging.
> Migrated from SQLite — uses psycopg2 with compatibility wrappers so all existing query code (? placeholders, row['col'] access) keeps working.

**Imports**

```python
import json
import os
import hashlib
import secrets
import psycopg2
import psycopg2.extras
import psycopg2.pool
import logging
from datetime import datetime, timedelta
from contextlib import contextmanager
```

**Module constants**

```python
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres123@localhost:5432/tradeopss')
```
_Equivalent to `os.getenv`: reads `DATABASE_URL` from the environment, default `'postgresql://postgres:postgres123@localhost:5432/tradeopss'`._

```python
TRADER_CLEARANCE_NOT_IN_RACE = -1
```
_Numeric literal — a tunable parameter compiled into the source._

**Classes**

#### `class _PgCursorWrapper`

> Wraps psycopg2 RealDictCursor; translates ? → %s.

```python
class _PgCursorWrapper:
    """Wraps psycopg2 RealDictCursor; translates ? → %s."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None):
        sql = sql.replace('?', '%s')
        self._cursor.execute(sql, params)
        return self

    def executemany(self, sql, params_list):
        sql = sql.replace('?', '%s')
        self._cursor.executemany(sql, params_list)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return getattr(self._cursor, 'lastrowid', None)
```

##### `_PgCursorWrapper.__init__`

```python
def __init__(self, cursor)
```
**What it does, step by step:**

1. Assigns <code>self._cursor</code> = <code>cursor</code>.

```python
def __init__(self, cursor):
        self._cursor = cursor
```

##### `_PgCursorWrapper.execute`

```python
def execute(self, sql, params=None)
```
**What it does, step by step:**

1. Assigns <code>sql</code> = <code>sql.replace('?', '%s')</code>.
2. Calls <code>self._cursor.execute(...)</code> for its side effect.
3. <b>return</b> <code>self</code>.

```python
def execute(self, sql, params=None):
        sql = sql.replace('?', '%s')
        self._cursor.execute(sql, params)
        return self
```

##### `_PgCursorWrapper.executemany`

```python
def executemany(self, sql, params_list)
```
**What it does, step by step:**

1. Assigns <code>sql</code> = <code>sql.replace('?', '%s')</code>.
2. Calls <code>self._cursor.executemany(...)</code> for its side effect.
3. <b>return</b> <code>self</code>.

```python
def executemany(self, sql, params_list):
        sql = sql.replace('?', '%s')
        self._cursor.executemany(sql, params_list)
        return self
```

##### `_PgCursorWrapper.fetchone`

```python
def fetchone(self)
```
**What it does, step by step:**

1. <b>return</b> <code>self._cursor.fetchone()</code>.

```python
def fetchone(self):
        return self._cursor.fetchone()
```

##### `_PgCursorWrapper.fetchall`

```python
def fetchall(self)
```
**What it does, step by step:**

1. <b>return</b> <code>self._cursor.fetchall()</code>.

```python
def fetchall(self):
        return self._cursor.fetchall()
```

##### `_PgCursorWrapper.rowcount`

```python
@property
def rowcount(self)
```
**What it does, step by step:**

1. <b>return</b> <code>self._cursor.rowcount</code>.

```python
def rowcount(self):
        return self._cursor.rowcount
```

##### `_PgCursorWrapper.lastrowid`

```python
@property
def lastrowid(self)
```
**What it does, step by step:**

1. <b>return</b> <code>getattr(self._cursor, 'lastrowid', None)</code>.

```python
def lastrowid(self):
        return getattr(self._cursor, 'lastrowid', None)
```

#### `class _PgConnWrapper`

> Wraps a psycopg2 connection to match the sqlite3 interface used throughout.

```python
class _PgConnWrapper:
    """Wraps a psycopg2 connection to match the sqlite3 interface used throughout."""

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def cursor(self):
        return _PgCursorWrapper(
            self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        )

    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()
```

##### `_PgConnWrapper.__init__`

```python
def __init__(self, raw_conn)
```
**What it does, step by step:**

1. Assigns <code>self._conn</code> = <code>raw_conn</code>.

```python
def __init__(self, raw_conn):
        self._conn = raw_conn
```

##### `_PgConnWrapper.cursor`

```python
def cursor(self)
```
**What it does, step by step:**

1. <b>return</b> <code>_PgCursorWrapper(self._conn.cursor(cursor_factory=psycopg2.extras.R...</code>.

```python
def cursor(self):
        return _PgCursorWrapper(
            self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        )
```

##### `_PgConnWrapper.execute`

```python
def execute(self, sql, params=None)
```
**What it does, step by step:**

1. Assigns <code>cur</code> = <code>self.cursor()</code>.
2. Calls <code>cur.execute(...)</code> for its side effect.
3. <b>return</b> <code>cur</code>.

```python
def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur
```

##### `_PgConnWrapper.commit`

```python
def commit(self)
```
**What it does, step by step:**

1. Calls <code>self._conn.commit(...)</code> for its side effect.

```python
def commit(self):
        self._conn.commit()
```

##### `_PgConnWrapper.rollback`

```python
def rollback(self)
```
**What it does, step by step:**

1. Calls <code>self._conn.rollback(...)</code> for its side effect.

```python
def rollback(self):
        self._conn.rollback()
```

##### `_PgConnWrapper.close`

```python
def close(self)
```
**What it does, step by step:**

1. Calls <code>self._conn.close(...)</code> for its side effect.

```python
def close(self):
        self._conn.close()
```

**Functions**

#### `_normalize_identifier`

```python
def _normalize_identifier(value: str) -> str
```
> Normalize user/client identifiers to prevent invisible-mismatch bugs. Handles non‑breaking spaces (common from copy/paste) and zero‑width chars.

**What it does, step by step:**

1. <b>if</b> <code>value is None</code>: branches conditionally.
2. <b>try</b> block with 1 <b>except</b> clause.
3. Assigns <code>s</code> = <code>s.replace('\xa0', ' ').replace('\u200b', '').replace('\u2...</code>.
4. Assigns <code>s</code> = <code>' '.join(s.split())</code>.
5. <b>return</b> <code>s.strip()</code>.

```python
def _normalize_identifier(value: str) -> str:
    """
    Normalize user/client identifiers to prevent invisible-mismatch bugs.
    Handles non‑breaking spaces (common from copy/paste) and zero‑width chars.
    """
    if value is None:
        return ''
    try:
        s = str(value)
    except Exception:
        return ''
    # Replace NBSP with regular space, drop common zero-width chars.
    s = s.replace('\u00A0', ' ').replace('\u200B', '').replace('\u200C', '').replace('\u200D', '')
    # Collapse all whitespace runs to a single space.
    s = ' '.join(s.split())
    return s.strip()
```

#### `_init_pool`

```python
def _init_pool()
```
> Initialize the connection pool on first use.

**What it does, step by step:**

1. Declares globals: _connection_pool.
2. <b>if</b> <code>_connection_pool is None</code>: branches conditionally.

```python
def _init_pool():
    """Initialize the connection pool on first use."""
    global _connection_pool
    if _connection_pool is None:
        try:
            _connection_pool = psycopg2.pool.SimpleConnectionPool(
                _pool_min,
                _pool_max,
                DATABASE_URL,
                connect_timeout=5  # 5-second timeout per connection
            )
            logger.info("[DB] Connection pool initialized (%s-%s connections)", _pool_min, _pool_max)
        except Exception as e:
            logger.error(f"[DB] Failed to initialize connection pool: {e}")
            raise
```

#### `_get_pooled_connection`

```python
def _get_pooled_connection()
```
> Get a connection from the pool (creates pool on first call).

**What it does, step by step:**

1. <b>if</b> <code>_connection_pool is None</code>: branches conditionally.
2. <b>return</b> <code>_connection_pool.getconn()</code>.

```python
def _get_pooled_connection():
    """Get a connection from the pool (creates pool on first call)."""
    if _connection_pool is None:
        _init_pool()
    return _connection_pool.getconn()
```

#### `_return_pooled_connection`

```python
def _return_pooled_connection(conn)
```
> Return a connection to the pool.

**What it does, step by step:**

1. <b>if</b> <code>_connection_pool is not None</code>: branches conditionally (with an <b>else</b>/elif arm).

```python
def _return_pooled_connection(conn):
    """Return a connection to the pool."""
    if _connection_pool is not None:
        _connection_pool.putconn(conn)
    else:
        conn.close()
```

#### `get_connection`

```python
@contextmanager
def get_connection()
```
> Context manager for database connections (PostgreSQL with pooling).

**What it does, step by step:**

1. Assigns <code>raw</code> = <code>None</code>.
2. <b>try</b> block with 2 <b>except</b> clauses, plus a <b>finally</b>.

```python
def get_connection():
    """Context manager for database connections (PostgreSQL with pooling)."""
    raw = None
    try:
        # Get connection from pool (creates pool on first call)
        raw = _get_pooled_connection()
        
        # Reset connection state (auto-commit off, no pending transactions)
        raw.autocommit = False
        raw.rollback()  # Clear any stale state
        
        conn = _PgConnWrapper(raw)
        try:
            yield conn
            # Auto-commit on successful exit (safety net)
            raw.commit()
        except Exception as e:
            # Log and rollback on error
            logger.warning(f"[DB] Transaction error, rolling back: {e}")
            raw.rollback()
            raise
    except psycopg2.OperationalError as e:
        # Connection pool exhausted or DB unreachable
        logger.error(f"[DB] Database connection error (pool issue?): {e}")
        raise
    except Exception as e:
        logger.error(f"[DB] Unexpected error in get_connection: {e}")
        raise
    finally:
        # Always return connection to pool
        if raw is not None:
            _return_pooled_connection(raw)
```

#### `get_direct_connection`

```python
@contextmanager
def get_direct_connection()
```
> One-off PostgreSQL connection (not from the pool). Use for CLI/cron/scripts so pool pre-allocation does not consume slots on small Postgres plans. Always closes the connection when done.

**What it does, step by step:**

1. Assigns <code>raw</code> = <code>psycopg2.connect(DATABASE_URL, connect_timeout=5)</code>.
2. Assigns <code>raw.autocommit</code> = <code>False</code>.
3. <b>try</b> block with 1 <b>except</b> clause, plus a <b>finally</b>.

```python
def get_direct_connection():
    """
    One-off PostgreSQL connection (not from the pool).
    Use for CLI/cron/scripts so pool pre-allocation does not consume slots
    on small Postgres plans. Always closes the connection when done.
    """
    raw = psycopg2.connect(DATABASE_URL, connect_timeout=5)
    raw.autocommit = False
    try:
        raw.rollback()
        conn = _PgConnWrapper(raw)
        yield conn
        raw.commit()
    except Exception as e:
        logger.warning(f"[DB] Transaction error (direct connection), rolling back: {e}")
        raw.rollback()
        raise
    finally:
        try:
            raw.close()
        except Exception:
            pass
```

#### `get_db_path`

```python
def get_db_path()
```
> Legacy helper — returns DATABASE_URL for PostgreSQL.

**What it does, step by step:**

1. <b>return</b> <code>DATABASE_URL</code>.

```python
def get_db_path():
    """Legacy helper — returns DATABASE_URL for PostgreSQL."""
    return DATABASE_URL
```

#### `check_and_repair_database`

```python
def check_and_repair_database()
```
> Connectivity check (PostgreSQL doesn't need SQLite-style repair).

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def check_and_repair_database():
    """Connectivity check (PostgreSQL doesn't need SQLite-style repair)."""
    try:
        with get_connection() as conn:
            conn.execute('SELECT 1')
        return True, 'PostgreSQL connection OK'
    except Exception as e:
        return False, f'PostgreSQL connection failed: {e}'
```

#### `init_database`

```python
def init_database()
```
> Schema is managed by Alembic migrations — verify connectivity and ensure columns exist.

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def init_database():
    """Schema is managed by Alembic migrations — verify connectivity and ensure columns exist."""
    try:
        with get_connection() as conn:
            conn.execute('SELECT 1')
            conn.commit()
        print("Database connection verified (schema managed by Alembic)")
        # Defensive: ensure columns exist even if Alembic migration was stamped on legacy DB
        with get_connection() as conn:
            cursor = conn.cursor()
            for _col, _default in [('prop_accounts', "'[]'"), ('vps_accounts', "'[]'"),
                                    ('hedge_accounts', "'[]'"), ('mt5_credentials', "'{}'"),
                                    ('payment_info', "'[]'"), ('payment_address', "'{}'")]:
                try:
                    cursor.execute(f"ALTER TABLE clients_data ADD COLUMN IF NOT EXISTS {_col} TEXT DEFAULT {_default}")
                except Exception:
                    pass
            conn.commit()
    except Exception as e:
        print(f"Database connection failed: {e}")
```

#### `hash_password`

```python
def hash_password(password: str, salt: str=None) -> tuple
```
> Hash a password with salt using SHA-256 + PBKDF2.

**What it does, step by step:**

1. <b>if</b> <code>salt is None</code>: branches conditionally.
2. Assigns <code>password_hash</code> = <code>hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), s...</code>.
3. <b>return</b> <code>(password_hash, salt)</code>.

```python
def hash_password(password: str, salt: str = None) -> tuple:
    """Hash a password with salt using SHA-256 + PBKDF2."""
    if salt is None:
        salt = secrets.token_hex(32)
    
    # Use PBKDF2 with SHA-256
    password_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000  # 100,000 iterations
    ).hex()
    
    return password_hash, salt
```

#### `verify_password`

```python
def verify_password(password: str, stored_hash: str, salt: str) -> bool
```
> Verify a password against stored hash.

**What it does, step by step:**

1. Assigns <code>(password_hash, _)</code> = <code>hash_password(password, salt)</code>.
2. <b>return</b> <code>secrets.compare_digest(password_hash, stored_hash)</code>.

```python
def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify a password against stored hash."""
    password_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(password_hash, stored_hash)
```

#### `set_admin_password`

```python
def set_admin_password(username: str, password: str) -> bool
```
> Set or update admin password. Ends all sessions for that admin identity.

**What it does, step by step:**

1. Assigns <code>(password_hash, salt)</code> = <code>hash_password(password)</code>.
2. Assigns <code>now</code> = <code>datetime.now().isoformat()</code>.
3. Assigns <code>username</code> = <code>(username or '').strip()</code>.
4. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def set_admin_password(username: str, password: str) -> bool:
    """Set or update admin password. Ends all sessions for that admin identity."""
    password_hash, salt = hash_password(password)
    now = datetime.now().isoformat()
    username = (username or '').strip()

    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO admin_passwords (username, password_hash, salt, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    password_hash = excluded.password_hash,
                    salt = excluded.salt,
                    updated_at = ?
            ''', (username, password_hash, salt, now, now))
            # Sessions use (user_type, user_identifier) = (super_admin, super_admin), etc.
            delete_all_sessions_for_user(username, username, conn=conn, cursor=cursor)
            conn.commit()
            return True
        except Exception as e:
            print(f"Error setting admin password: {e}")
            conn.rollback()
            return False
```

#### `admin_password_exists`

```python
def admin_password_exists(username: str) -> bool
```
> Return True if a password row already exists for the given admin username.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def admin_password_exists(username: str) -> bool:
    """Return True if a password row already exists for the given admin username."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM admin_passwords WHERE username = ?',
            (username,)
        )
        return cursor.fetchone() is not None
```

#### `copy_admin_password_row`

```python
def copy_admin_password_row(from_username: str, to_username: str) -> bool
```
> If to_username has no row, copy password_hash/salt from from_username. Returns True if a row was copied.

**What it does, step by step:**

1. <b>if</b> <code>admin_password_exists(to_username)</code>: branches conditionally.
2. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def copy_admin_password_row(from_username: str, to_username: str) -> bool:
    """
    If to_username has no row, copy password_hash/salt from from_username.
    Returns True if a row was copied.
    """
    if admin_password_exists(to_username):
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT password_hash, salt FROM admin_passwords WHERE username = ?',
            (from_username,)
        )
        row = cursor.fetchone()
        if not row:
            return False
        now = datetime.now().isoformat()
        cursor.execute(
            '''
            INSERT INTO admin_passwords (username, password_hash, salt, created_at)
            VALUES (?, ?, ?, ?)
            ''',
            (to_username, row['password_hash'], row['salt'], now),
        )
        conn.commit()
        return True
```

#### `verify_admin_password`

```python
def verify_admin_password(username: str, password: str) -> bool
```
> Verify admin password.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def verify_admin_password(username: str, password: str) -> bool:
    """Verify admin password."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT password_hash, salt FROM admin_passwords WHERE username = ?',
            (username,)
        )
        row = cursor.fetchone()
        
        if row is None:
            return False
        
        return verify_password(password, row['password_hash'], row['salt'])
```

#### `create_user`

```python
def create_user(username: str, password: str, user_type: str, email: str=None, parent_admin: str=None, parent_trader: str=None) -> bool
```
> Create a new user with hashed password.

**What it does, step by step:**

1. Assigns <code>username</code> = <code>username.strip()</code>.
2. Assigns <code>(password_hash, salt)</code> = <code>hash_password(password)</code>.
3. Assigns <code>now</code> = <code>datetime.now().isoformat()</code>.
4. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def create_user(username: str, password: str, user_type: str, 
                email: str = None, parent_admin: str = None, 
                parent_trader: str = None) -> bool:
    """Create a new user with hashed password."""
    username = username.strip()
    password_hash, salt = hash_password(password)
    now = datetime.now().isoformat()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO user_credentials 
                (username, email, password_hash, salt, user_type, parent_admin, parent_trader, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (username, email, password_hash, salt, user_type, parent_admin, parent_trader, now))
            conn.commit()
            return True
        except psycopg2.IntegrityError:
            # User already exists
            conn.rollback()
            return False
        except Exception as e:
            print(f"Error creating user: {e}")
            return False
```

#### `verify_user_password`

```python
def verify_user_password(username: str, user_type: str, password: str) -> dict
```
> Verify user password and return user info if valid.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def verify_user_password(username: str, user_type: str, password: str) -> dict:
    """Verify user password and return user info if valid."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, username, email, password_hash, salt, user_type, 
                   parent_admin, parent_trader, is_active, must_change_password
            FROM user_credentials 
            WHERE username = ? AND user_type = ? AND is_active = 1
        ''', (username, user_type))
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        if not verify_password(password, row['password_hash'], row['salt']):
            return None
        
        # Update last login
        cursor.execute(
            'UPDATE user_credentials SET last_login = ? WHERE id = ?',
            (datetime.now().isoformat(), row['id'])
        )
        conn.commit()
        
        return {
            'id': row['id'],
            'username': row['username'],
            'email': row['email'],
            'user_type': row['user_type'],
            'parent_admin': row['parent_admin'],
            'parent_trader': row['parent_trader'],
            'must_change_password': bool(row['must_change_password'])
        }
```

#### `verify_client_login`

```python
def verify_client_login(email: str, password: str) -> dict
```
> Verify client login by email and password.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def verify_client_login(email: str, password: str) -> dict:
    """Verify client login by email and password."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, username, email, password_hash, salt, user_type, 
                   parent_admin, parent_trader, is_active, must_change_password
            FROM user_credentials 
            WHERE email = ? AND user_type = 'client' AND is_active = 1
        ''', (email,))
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        if not verify_password(password, row['password_hash'], row['salt']):
            return None
        
        # Update last login
        cursor.execute(
            'UPDATE user_credentials SET last_login = ? WHERE id = ?',
            (datetime.now().isoformat(), row['id'])
        )
        conn.commit()
        
        return {
            'id': row['id'],
            'username': row['username'],
            'email': row['email'],
            'user_type': row['user_type'],
            'parent_admin': row['parent_admin'],
            'parent_trader': row['parent_trader'],
            'must_change_password': bool(row['must_change_password'])
        }
```

#### `update_user_password`

```python
def update_user_password(username: str, user_type: str, new_password: str) -> bool
```
> Update a user's password. Invalidates all active sessions for this account.

**What it does, step by step:**

1. Assigns <code>(password_hash, salt)</code> = <code>hash_password(new_password)</code>.
2. Assigns <code>now</code> = <code>datetime.now().isoformat()</code>.
3. Assigns <code>username</code> = <code>username.strip()</code>.
4. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def update_user_password(username: str, user_type: str, new_password: str) -> bool:
    """Update a user's password. Invalidates all active sessions for this account."""
    password_hash, salt = hash_password(new_password)
    now = datetime.now().isoformat()
    username = username.strip()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE user_credentials 
            SET password_hash = ?, salt = ?, must_change_password = 0, updated_at = ?
            WHERE username = ? AND user_type = ?
        ''', (password_hash, salt, now, username, user_type))
        ok = cursor.rowcount > 0
        if ok:
            delete_all_sessions_for_user(user_type, username, conn=conn, cursor=cursor)
        conn.commit()
        return ok
```

#### `get_user`

```python
def get_user(username: str, user_type: str) -> dict
```
> Get user info without password verification.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_user(username: str, user_type: str) -> dict:
    """Get user info without password verification."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, username, email, user_type, parent_admin, parent_trader, 
                   is_active, must_change_password, last_login, created_at
            FROM user_credentials 
            WHERE username = ? AND user_type = ?
        ''', (username, user_type))
        row = cursor.fetchone()
        return dict(row) if row else None
```

#### `list_users`

```python
def list_users(user_type: str=None) -> list
```
> List all users, optionally filtered by type.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def list_users(user_type: str = None) -> list:
    """List all users, optionally filtered by type."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if user_type:
            cursor.execute('''
                SELECT id, username, email, user_type, parent_admin, parent_trader, 
                       is_active, last_login, created_at
                FROM user_credentials WHERE user_type = ?
                ORDER BY created_at DESC
            ''', (user_type,))
        else:
            cursor.execute('''
                SELECT id, username, email, user_type, parent_admin, parent_trader, 
                       is_active, last_login, created_at
                FROM user_credentials ORDER BY user_type, created_at DESC
            ''')
        return [dict(row) for row in cursor.fetchall()]
```

#### `deactivate_user`

```python
def deactivate_user(username: str, user_type: str) -> bool
```
> Deactivate a user account and end all their sessions.

**What it does, step by step:**

1. Assigns <code>username</code> = <code>username.strip()</code>.
2. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def deactivate_user(username: str, user_type: str) -> bool:
    """Deactivate a user account and end all their sessions."""
    username = username.strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE user_credentials SET is_active = 0, updated_at = ?
            WHERE username = ? AND user_type = ?
        ''', (datetime.now().isoformat(), username, user_type))
        ok = cursor.rowcount > 0
        if ok:
            delete_all_sessions_for_user(user_type, username, conn=conn, cursor=cursor)
        conn.commit()
        return ok
```

#### `activate_user`

```python
def activate_user(username: str, user_type: str) -> bool
```
> Activate a user account.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def activate_user(username: str, user_type: str) -> bool:
    """Activate a user account."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE user_credentials SET is_active = 1, updated_at = ?
            WHERE username = ? AND user_type = ?
        ''', (datetime.now().isoformat(), username, user_type))
        conn.commit()
        return cursor.rowcount > 0
```

#### `reset_user_password`

```python
def reset_user_password(username: str, user_type: str, default_password: str='Test@123') -> str
```
> Reset user password to the default password. Ends all sessions for this account.

**What it does, step by step:**

1. Assigns <code>(password_hash, salt)</code> = <code>hash_password(default_password)</code>.
2. Assigns <code>now</code> = <code>datetime.now().isoformat()</code>.
3. Assigns <code>username</code> = <code>username.strip()</code>.
4. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def reset_user_password(username: str, user_type: str, default_password: str = 'Test@123') -> str:
    """Reset user password to the default password. Ends all sessions for this account."""
    password_hash, salt = hash_password(default_password)
    now = datetime.now().isoformat()
    username = username.strip()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE user_credentials 
            SET password_hash = ?, salt = ?, must_change_password = 1, updated_at = ?
            WHERE username = ? AND user_type = ?
        ''', (password_hash, salt, now, username, user_type))
        if cursor.rowcount > 0:
            delete_all_sessions_for_user(user_type, username, conn=conn, cursor=cursor)
            conn.commit()
            return default_password
        conn.commit()
        return None
```

#### `find_user_by_identifier`

```python
def find_user_by_identifier(identifier: str) -> dict
```
> Find a user by email or username across all user types. Returns user info including user_type if found. Also checks if identifier matches super_admin.

**What it does, step by step:**

1. <b>if</b> <code>identifier.lower() in ['super_admin', 'superadmin', 'admin']</code>: branches conditionally.
2. <b>if</b> <code>identifier.lower() in ['bef_admin', 'befadmin', 'bef']</code>: branches conditionally.
3. <b>if</b> <code>identifier.lower() in ['kwok_admin', 'kwokadmin', 'kwok', 'showcase...</code>: branches conditionally.
4. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def find_user_by_identifier(identifier: str) -> dict:
    """
    Find a user by email or username across all user types.
    Returns user info including user_type if found.
    Also checks if identifier matches super_admin.
    """
    # Check if it's super_admin
    if identifier.lower() in ['super_admin', 'superadmin', 'admin']:
        return {'user_type': 'super_admin', 'username': 'super_admin'}
    
    # Check if it's bef_admin
    if identifier.lower() in ['bef_admin', 'befadmin', 'bef']:
        return {'user_type': 'bef_admin', 'username': 'bef_admin'}

    # Kwok (investor-style) dashboard — full read access, no writes (enforced in app)
    if identifier.lower() in [
        'kwok_admin', 'kwokadmin', 'kwok',
        'showcase_admin', 'showcaseadmin', 'showcase', 'investor_demo',
        'investor', 'demo_investor',
    ]:
        return {'user_type': 'kwok_admin', 'username': 'kwok_admin'}
    
    with get_connection() as conn:
        cursor = conn.cursor()
        # Search by username or email across all user types.
        #
        # IMPORTANT: We must be deterministic here. The schema allows multiple rows to share
        # the same email (unique is (username, user_type)), so a plain fetchone() can return
        # different roles depending on query plan / insertion order. That leads to users
        # sometimes being redirected to the wrong dashboard.
        cursor.execute('''
            SELECT id, username, email, user_type, parent_admin, parent_trader, 
                   is_active, must_change_password, password_hash, salt, last_login
            FROM user_credentials 
            WHERE (username = ? OR email = ?) AND is_active = 1
        ''', (identifier, identifier))
        rows = cursor.fetchall() or []
        if not rows:
            return None

        ident_norm = (identifier or '').strip().lower()
        is_email = '@' in ident_norm

        # Prefer exact email matches when identifier is an email.
        # For email logins, we want client accounts to win over accidentally-created admin/trader rows.
        if is_email:
            email_matches = [r for r in rows if (r.get('email') or '').strip().lower() == ident_norm]
            candidates = email_matches or rows
            role_priority = {'client': 0, 'trader': 1, 'admin': 2}
        else:
            # For username logins, prefer exact username matches first.
            username_matches = [r for r in rows if (r.get('username') or '').strip().lower() == ident_norm]
            candidates = username_matches or rows
            role_priority = {'admin': 0, 'trader': 1, 'client': 2}

        def _score(r):
            ut = (r.get('user_type') or '').strip()
            return (
                role_priority.get(ut, 999),
                0 if (r.get('last_login') or '') else 1,  # prefer accounts that have logged in before
                r.get('id') or 0,
            )

        best = sorted((dict(r) for r in candidates), key=_score)[0]
        return best
```

#### `verify_user_by_identifier`

```python
def verify_user_by_identifier(identifier: str, password: str) -> dict
```
> Verify user credentials by email or username (auto-detect user type). Returns user info with user_type if successful, None otherwise.

**What it does, step by step:**

1. Assigns <code>user</code> = <code>find_user_by_identifier(identifier)</code>.
2. <b>if</b> <code>not user</code>: branches conditionally.
3. <b>if</b> <code>user.get('user_type') in ('super_admin', 'bef_admin', 'kwok_admin')</code>: branches conditionally.
4. Assigns <code>stored_hash</code> = <code>user.get('password_hash')</code>.
5. Assigns <code>salt</code> = <code>user.get('salt')</code>.
6. <b>if</b> <code>not stored_hash or not salt</code>: branches conditionally.
7. Assigns <code>password_hash</code> = <code>hashlib.pbkdf2_hmac('sha256', password.encode(), salt.enc...</code>.
8. <b>if</b> <code>password_hash == stored_hash</code>: branches conditionally.
9. <b>return</b> <code>None</code>.

```python
def verify_user_by_identifier(identifier: str, password: str) -> dict:
    """
    Verify user credentials by email or username (auto-detect user type).
    Returns user info with user_type if successful, None otherwise.
    """
    user = find_user_by_identifier(identifier)
    if not user:
        return None
    
    # Super admin and BEF admin have special handling
    if user.get('user_type') in ('super_admin', 'bef_admin', 'kwok_admin'):
        return user  # Password check happens separately
    
    # Verify password for regular users
    stored_hash = user.get('password_hash')
    salt = user.get('salt')
    
    if not stored_hash or not salt:
        return None
    
    password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
    
    if password_hash == stored_hash:
        # Update last login
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE user_credentials SET last_login = ? WHERE id = ?',
                (datetime.now().isoformat(), user['id'])
            )
            conn.commit()
        
        # Remove sensitive data before returning
        user.pop('password_hash', None)
        user.pop('salt', None)
        return user
    
    return None
```

#### `delete_user_credential`

```python
def delete_user_credential(username: str, user_type: str) -> bool
```
> Permanently delete a user credential and all their sessions.

**What it does, step by step:**

1. Assigns <code>username</code> = <code>username.strip()</code>.
2. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def delete_user_credential(username: str, user_type: str) -> bool:
    """Permanently delete a user credential and all their sessions."""
    username = username.strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        delete_all_sessions_for_user(user_type, username, conn=conn, cursor=cursor)
        cursor.execute('''
            DELETE FROM user_credentials 
            WHERE username = ? AND user_type = ?
        ''', (username, user_type))
        ok = cursor.rowcount > 0
        conn.commit()
        return ok
```

#### `update_user_email`

```python
def update_user_email(username: str, user_type: str, new_email: str) -> bool
```
> Update a user's email address.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def update_user_email(username: str, user_type: str, new_email: str) -> bool:
    """Update a user's email address."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE user_credentials 
            SET email = ?, updated_at = ?
            WHERE username = ? AND user_type = ?
        ''', (new_email, datetime.now().isoformat(), username, user_type))
        conn.commit()
        return cursor.rowcount > 0
```

#### `rename_user_credential`

```python
def rename_user_credential(old_name: str, new_name: str, user_type: str) -> bool
```
> Rename a user in user_credentials table.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def rename_user_credential(old_name: str, new_name: str, user_type: str) -> bool:
    """Rename a user in user_credentials table."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE user_credentials SET username = ?, updated_at = ?
            WHERE username = ? AND user_type = ?
        ''', (new_name, datetime.now().isoformat(), old_name, user_type))
        conn.commit()
        return cursor.rowcount > 0
```

#### `rename_client_in_db`

```python
def rename_client_in_db(old_name: str, new_name: str) -> bool
```
> Rename client_id across all client data tables.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def rename_client_in_db(old_name: str, new_name: str) -> bool:
    """Rename client_id across all client data tables."""
    with get_connection() as conn:
        cursor = conn.cursor()
        for table in ['clients_data', 'data_history', 'cell_notes', 'daily_watermarks', 'waterlog_periods']:
            try:
                cursor.execute(f'UPDATE {table} SET client_id = ? WHERE client_id = ?', (new_name, old_name))
            except Exception:
                pass
        conn.commit()
        return True
```

#### `user_exists`

```python
def user_exists(username: str, user_type: str) -> bool
```
> Check if a user already exists.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def user_exists(username: str, user_type: str) -> bool:
    """Check if a user already exists."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM user_credentials WHERE username = ? AND user_type = ?',
            (username, user_type)
        )
        return cursor.fetchone() is not None
```

#### `record_login_attempt`

```python
def record_login_attempt(username: str, user_type: str, ip_address: str, success: bool)
```
> Record a login attempt.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def record_login_attempt(username: str, user_type: str, ip_address: str, success: bool):
    """Record a login attempt."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO login_attempts (username, user_type, ip_address, attempt_time, success)
            VALUES (?, ?, ?, ?, ?)
        ''', (username, user_type, ip_address, datetime.now().isoformat(), 1 if success else 0))
        conn.commit()
```

#### `get_failed_login_count`

```python
def get_failed_login_count(username: str, user_type: str, minutes: int=15) -> int
```
> Get count of failed login attempts in the last X minutes.

**What it does, step by step:**

1. Lazy import from <code>datetime</code>.
2. Assigns <code>cutoff</code> = <code>(datetime.now() - timedelta(minutes=minutes)).isoformat()</code>.
3. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_failed_login_count(username: str, user_type: str, minutes: int = 15) -> int:
    """Get count of failed login attempts in the last X minutes."""
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as count FROM login_attempts
            WHERE username = ? AND user_type = ? AND success = 0 AND attempt_time > ?
        ''', (username, user_type, cutoff))
        row = cursor.fetchone()
        return row['count'] if row else 0
```

#### `is_account_locked`

```python
def is_account_locked(username: str, user_type: str, max_attempts: int=5) -> bool
```
> Check if account is locked due to too many failed attempts.

**What it does, step by step:**

1. <b>return</b> <code>get_failed_login_count(username, user_type) &gt;= max_attempts</code>.

```python
def is_account_locked(username: str, user_type: str, max_attempts: int = 5) -> bool:
    """Check if account is locked due to too many failed attempts."""
    return get_failed_login_count(username, user_type) >= max_attempts
```

#### `hash_api_key`

```python
def hash_api_key(api_key: str) -> str
```
> Hash an API key using SHA-256.

**What it does, step by step:**

1. <b>return</b> <code>hashlib.sha256(api_key.encode('utf-8')).hexdigest()</code>.

```python
def hash_api_key(api_key: str) -> str:
    """Hash an API key using SHA-256."""
    return hashlib.sha256(api_key.encode('utf-8')).hexdigest()
```

#### `generate_api_key`

```python
def generate_api_key(admin: str, trader: str, client: str='', scope: str='full') -> str
```
> Generate a new API key and store its hash.  scope: 'full' for full access, 'readonly' for read-only endpoints only.

**What it does, step by step:**

1. Assigns <code>api_key</code> = <code>'tk_' + secrets.token_urlsafe(32)</code>.
2. Assigns <code>key_hash</code> = <code>hash_api_key(api_key)</code>.
3. Assigns <code>key_prefix</code> = <code>api_key[:12]</code>.
4. Assigns <code>now</code> = <code>datetime.now().isoformat()</code>.
5. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def generate_api_key(admin: str, trader: str, client: str = '', scope: str = 'full') -> str:
    """Generate a new API key and store its hash.
    
    scope: 'full' for full access, 'readonly' for read-only endpoints only.
    """
    api_key = 'tk_' + secrets.token_urlsafe(32)
    key_hash = hash_api_key(api_key)
    key_prefix = api_key[:12]  # Store prefix for identification
    now = datetime.now().isoformat()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO api_keys (key_hash, key_prefix, admin, trader, client, scope, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (key_hash, key_prefix, admin, trader, client, scope, now))
            conn.commit()
            return api_key  # Return the actual key (only time it's visible)
        except Exception as e:
            print(f"Error generating API key: {e}")
            return None
```

#### `validate_api_key`

```python
def validate_api_key(api_key: str) -> dict
```
> Validate an API key and return user info if valid. Includes 'scope' in the result.

**What it does, step by step:**

1. Assigns <code>key_hash</code> = <code>hash_api_key(api_key)</code>.
2. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def validate_api_key(api_key: str) -> dict:
    """Validate an API key and return user info if valid. Includes 'scope' in the result."""
    key_hash = hash_api_key(api_key)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT admin, trader, client, scope, created_at FROM api_keys 
            WHERE key_hash = ? AND is_active = 1
        ''', (key_hash,))
        row = cursor.fetchone()
        
        if row:
            # Update last_used timestamp
            cursor.execute(
                'UPDATE api_keys SET last_used = ? WHERE key_hash = ?',
                (datetime.now().isoformat(), key_hash)
            )
            conn.commit()
            
            return {
                'admin': row['admin'],
                'trader': row['trader'],
                'client': row['client'],
                'scope': row['scope'] or 'full',
                'created': row['created_at']
            }
        
        return None
```

#### `list_api_keys`

```python
def list_api_keys() -> list
```
> List all API keys (showing only prefix).

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def list_api_keys() -> list:
    """List all API keys (showing only prefix)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT key_prefix, admin, trader, client, scope, created_at, last_used, is_active
            FROM api_keys ORDER BY created_at DESC
        ''')
        return [dict(row) for row in cursor.fetchall()]
```

#### `revoke_api_key`

```python
def revoke_api_key(key_prefix: str) -> bool
```
> Revoke an API key by its prefix.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def revoke_api_key(key_prefix: str) -> bool:
    """Revoke an API key by its prefix."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE api_keys SET is_active = 0 WHERE key_prefix = ?',
            (key_prefix,)
        )
        conn.commit()
        return cursor.rowcount > 0
```

#### `delete_api_key`

```python
def delete_api_key(key_prefix: str) -> bool
```
> Permanently delete an API key by its prefix.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def delete_api_key(key_prefix: str) -> bool:
    """Permanently delete an API key by its prefix."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM api_keys WHERE key_prefix = ?', (key_prefix,))
        conn.commit()
        return cursor.rowcount > 0
```

#### `add_kyc_link`

```python
def add_kyc_link(primary_client: str, linked_client: str, linked_by: str='super_admin') -> bool
```
> Link a secondary client account to a primary client as a KYC.

**What it does, step by step:**

1. <b>if</b> <code>primary_client == linked_client</code>: branches conditionally.
2. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def add_kyc_link(primary_client: str, linked_client: str, linked_by: str = 'super_admin') -> bool:
    """Link a secondary client account to a primary client as a KYC."""
    if primary_client == linked_client:
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO kyc_links (primary_client, linked_client, linked_by, created_at)
                VALUES (?, ?, ?, ?)
            ''', (primary_client, linked_client, linked_by, datetime.now().isoformat()))
            conn.commit()
            return True
        except psycopg2.IntegrityError:
            conn.rollback()
            return False
```

#### `remove_kyc_link`

```python
def remove_kyc_link(primary_client: str, linked_client: str) -> bool
```
> Remove a KYC link between two clients.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def remove_kyc_link(primary_client: str, linked_client: str) -> bool:
    """Remove a KYC link between two clients."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM kyc_links WHERE primary_client = ? AND linked_client = ?',
                       (primary_client, linked_client))
        conn.commit()
        return cursor.rowcount > 0
```

#### `get_kyc_linked_clients`

```python
def get_kyc_linked_clients(primary_client: str) -> list
```
> Get all linked KYC accounts for a primary client.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_kyc_linked_clients(primary_client: str) -> list:
    """Get all linked KYC accounts for a primary client."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT linked_client, linked_by, created_at FROM kyc_links WHERE primary_client = ?',
                       (primary_client,))
        return [{'linked_client': r['linked_client'], 'linked_by': r['linked_by'],
                 'created_at': r['created_at']} for r in cursor.fetchall()]
```

#### `get_kyc_primary_for`

```python
def get_kyc_primary_for(linked_client: str) -> str
```
> If this client is linked to someone, return the primary client name.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_kyc_primary_for(linked_client: str) -> str:
    """If this client is linked to someone, return the primary client name."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT primary_client FROM kyc_links WHERE linked_client = ?',
                       (linked_client,))
        row = cursor.fetchone()
        return row['primary_client'] if row else None
```

#### `is_kyc_primary`

```python
def is_kyc_primary(client_name: str) -> bool
```
> Check if this client is a primary KYC account (has linked accounts under it).

**What it does, step by step:**

1. <b>return</b> <code>len(get_kyc_linked_clients(client_name)) &gt; 0</code>.

```python
def is_kyc_primary(client_name: str) -> bool:
    """Check if this client is a primary KYC account (has linked accounts under it)."""
    return len(get_kyc_linked_clients(client_name)) > 0
```

#### `get_all_kyc_accounts`

```python
def get_all_kyc_accounts(client_name: str) -> list
```
> Get all KYC accounts for a client (including self).  If client_name is primary → returns [self] + linked accounts. If client_name is linked → returns [primary] + all siblings + self.

**What it does, step by step:**

1. Assigns <code>linked</code> = <code>get_kyc_linked_clients(client_name)</code>.
2. <b>if</b> <code>linked</code>: branches conditionally.
3. Assigns <code>primary</code> = <code>get_kyc_primary_for(client_name)</code>.
4. <b>if</b> <code>primary</code>: branches conditionally.
5. <b>return</b> <code>[client_name]</code>.

```python
def get_all_kyc_accounts(client_name: str) -> list:
    """Get all KYC accounts for a client (including self). 
    If client_name is primary → returns [self] + linked accounts.
    If client_name is linked → returns [primary] + all siblings + self.
    """
    # Check if this client is a primary
    linked = get_kyc_linked_clients(client_name)
    if linked:
        return [client_name] + [l['linked_client'] for l in linked]
    # Check if this client is linked to a primary
    primary = get_kyc_primary_for(client_name)
    if primary:
        siblings = get_kyc_linked_clients(primary)
        return [primary] + [l['linked_client'] for l in siblings]
    return [client_name]
```

#### `get_all_kyc_links`

```python
def get_all_kyc_links() -> list
```
> Get all KYC links in the system (for admin view).

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_all_kyc_links() -> list:
    """Get all KYC links in the system (for admin view)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT primary_client, linked_client, linked_by, created_at FROM kyc_links ORDER BY primary_client')
        return [dict(r) for r in cursor.fetchall()]
```

#### `save_client_data`

```python
def save_client_data(client_id: str, data: dict, overwrite: bool=False) -> bool
```
> Save client data to database.  If overwrite=True, replaces all existing data with the provided data (used for sheet imports). If overwrite=False (default), merges: new values take precedence but missing keys fall back to existing.

**What it does, step by step:**

1. Assigns <code>client_id</code> = <code>_normalize_identifier(client_id)</code>.
2. Assigns <code>now</code> = <code>datetime.now().isoformat()</code>.
3. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def save_client_data(client_id: str, data: dict, overwrite: bool = False) -> bool:
    """Save client data to database.
    
    If overwrite=True, replaces all existing data with the provided data (used for sheet imports).
    If overwrite=False (default), merges: new values take precedence but missing keys fall back to existing.
    """
    # Normalize to avoid storing duplicate client_ids that differ only by whitespace
    client_id = _normalize_identifier(client_id)
    now = datetime.now().isoformat()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            if overwrite:
                # Full replacement - use provided data as-is, defaulting missing fields to empty
                merged_deals = data.get('deals', [])
                merged_positions = data.get('positions', [])
                merged_account = data.get('account', {})
                merged_evaluations = data.get('evaluations', [])
                merged_statistics = data.get('statistics', {})
                merged_dropdown_options = data.get('dropdown_options', {})
                merged_identity = data.get('identity', {})
                merged_hedge_accounts = data.get('hedge_accounts', [])
                merged_prop_accounts = data.get('prop_accounts', [])
                merged_vps_accounts = data.get('vps_accounts', [])
                merged_payment_info = data.get('payment_info', [])
                merged_payment_address = data.get('payment_address', {})
                merged_mt5_credentials = data.get('mt5_credentials', {})
                merged_firm_billing = data.get('firm_billing', {})
            else:
                # Merge: get existing data so missing keys fall back gracefully
                cursor.execute('SELECT * FROM clients_data WHERE client_id = ?', (client_id,))
                row = cursor.fetchone()
                
                existing_data = {}
                if row:
                    existing_data = {
                        'deals': json.loads(row['deals']),
                        'positions': json.loads(row['positions']),
                        'account': json.loads(row['account']),
                        'evaluations': json.loads(row['evaluations']),
                        'statistics': json.loads(row['statistics']),
                        'dropdown_options': json.loads(row['dropdown_options']),
                        'identity': json.loads(row['identity']),
                        'hedge_accounts': json.loads(row.get('hedge_accounts') or '[]'),
                        'prop_accounts': json.loads(row.get('prop_accounts') or '[]'),
                        'vps_accounts': json.loads(row.get('vps_accounts') or '[]'),
                        'payment_info': json.loads(row.get('payment_info') or '[]'),
                        'mt5_credentials': json.loads(row.get('mt5_credentials') or '{}'),
                    }
                
                # Merge existing data with new data (new data takes precedence)
                merged_deals = data.get('deals', existing_data.get('deals', []))
                merged_positions = data.get('positions', existing_data.get('positions', []))
                merged_account = data.get('account', existing_data.get('account', {}))
                merged_evaluations = data.get('evaluations', existing_data.get('evaluations', []))
                merged_statistics = data.get('statistics', existing_data.get('statistics', {}))
                merged_dropdown_options = data.get('dropdown_options', existing_data.get('dropdown_options', {}))
                merged_identity = data.get('identity', existing_data.get('identity', {}))
                merged_hedge_accounts = data.get('hedge_accounts', existing_data.get('hedge_accounts', []))
                merged_prop_accounts = data.get('prop_accounts', existing_data.get('prop_accounts', []))
                merged_vps_accounts = data.get('vps_accounts', existing_data.get('vps_accounts', []))
                merged_payment_info = data.get('payment_info', existing_data.get('payment_info', []))
                merged_payment_address = data.get('payment_address', existing_data.get('payment_address', {}))
                merged_mt5_credentials = data.get('mt5_credentials', existing_data.get('mt5_credentials', {}))
                merged_firm_billing = data.get('firm_billing', existing_data.get('firm_billing', {}))

            # Strip _notes from evaluations — notes are stored separately in cell_notes table
            clean_evaluations = [
                {k: v for k, v in ev.items() if k != '_notes'}
                if isinstance(ev, dict) else ev
                for ev in merged_evaluations
            ]

            # Normalize Prop Firm names before storing to prevent duplicates
            FIRM_NORMALIZE = {
                "mffu": "My Funded Futures", "mffuflex": "My Funded Futures",
                "myfundedfutures": "My Funded Futures", "myfundedfx": "My Funded Futures",
                "mff": "My Funded Futures",
                "topstep": "Topstep",
                "topsteprtp": "TopStep RTP",
                "fundingticks": "Funding Ticks", "fundingtick": "Funding Ticks",
                "fundednext": "FundedNext",
                "tradeday": "TradeDay", "tradeify": "Tradeify",
                "alphafutures": "Alpha Futures",
                "toponefutures": "Top One Futures", "topone": "Top One Futures",
            }
            for ev in clean_evaluations:
                if isinstance(ev, dict) and ev.get('Prop Firm'):
                    raw = ev['Prop Firm'].strip().lower().replace(" ", "").replace("_", "")
                    if raw in FIRM_NORMALIZE:
                        ev['Prop Firm'] = FIRM_NORMALIZE[raw]

            cursor.execute('''
                INSERT INTO clients_data (
                    client_id, deals, positions, account, evaluations,
                    statistics, dropdown_options, identity, last_updated,
                    hedge_accounts, prop_accounts, vps_accounts, payment_info, payment_address,
                    mt5_credentials, firm_billing
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    deals = excluded.deals,
                    positions = excluded.positions,
                    account = excluded.account,
                    evaluations = excluded.evaluations,
                    statistics = excluded.statistics,
                    dropdown_options = excluded.dropdown_options,
                    identity = excluded.identity,
                    last_updated = excluded.last_updated,
                    hedge_accounts = excluded.hedge_accounts,
                    prop_accounts = excluded.prop_accounts,
                    vps_accounts = excluded.vps_accounts,
                    payment_info = excluded.payment_info,
                    payment_address = excluded.payment_address,
                    mt5_credentials = excluded.mt5_credentials,
                    firm_billing = excluded.firm_billing
            ''', (
                client_id,
                json.dumps(merged_deals),
                json.dumps(merged_positions),
                json.dumps(merged_account),
                json.dumps(clean_evaluations),
                json.dumps(merged_statistics),
                json.dumps(merged_dropdown_options),
                json.dumps(merged_identity),
                now,
                json.dumps(merged_hedge_accounts),
                json.dumps(merged_prop_accounts),
                json.dumps(merged_vps_accounts),
                json.dumps(merged_payment_info),
                json.dumps(merged_payment_address),
                json.dumps(merged_mt5_credentials),
                json.dumps(merged_firm_billing),
            ))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error saving client data: {e}")
            return False
```

#### `get_client_data`

```python
def get_client_data(client_id: str) -> dict
```
> Get client data from database.

**What it does, step by step:**

1. Assigns <code>norm_id</code> = <code>_normalize_identifier(client_id)</code>.
2. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_client_data(client_id: str) -> dict:
    """Get client data from database."""
    norm_id = _normalize_identifier(client_id)
    with get_connection() as conn:
        cursor = conn.cursor()
        row = None
        # 1) Exact match (as provided)
        if client_id:
            cursor.execute('SELECT * FROM clients_data WHERE client_id = ?', (client_id,))
            row = cursor.fetchone()
        # 2) Exact match (normalized)
        if row is None and norm_id and norm_id != client_id:
            cursor.execute('SELECT * FROM clients_data WHERE client_id = ?', (norm_id,))
            row = cursor.fetchone()
        # 3) Trimmed match (repairs legacy rows with trailing spaces)
        if row is None and norm_id:
            cursor.execute('SELECT * FROM clients_data WHERE btrim(client_id) = ? LIMIT 1', (norm_id,))
            row = cursor.fetchone()
            # If we found a legacy row keyed by a whitespace-variant client_id, attempt a safe rename
            try:
                if row and row.get('client_id') and row.get('client_id') != norm_id:
                    legacy_id = row.get('client_id')
                    # Only rename if the normalized id doesn't already exist
                    cursor.execute('SELECT 1 AS ok FROM clients_data WHERE client_id = ? LIMIT 1', (norm_id,))
                    exists = cursor.fetchone() is not None
                    if not exists:
                        # Commit current read txn before performing rename in a new txn
                        conn.commit()
                        rename_client_in_db(legacy_id, norm_id)
                        # Reload after rename
                        with get_connection() as conn2:
                            cur2 = conn2.cursor()
                            cur2.execute('SELECT * FROM clients_data WHERE client_id = ?', (norm_id,))
                            row = cur2.fetchone()
            except Exception:
                # If repair fails, still return the legacy row we found (read-only)
                pass
        
        if row:
            try:
                identity = json.loads(row['identity'] or '{}') or {}
            except Exception:
                identity = {}
            return {
                'deals': json.loads(row['deals']),
                'positions': json.loads(row['positions']),
                'account': json.loads(row['account']),
                'evaluations': json.loads(row['evaluations']),
                'statistics': json.loads(row['statistics']),
                'dropdown_options': json.loads(row['dropdown_options']),
                'identity': identity,
                'sheet_url': identity.get('sheet_url') if isinstance(identity, dict) else None,
                'last_updated': row['last_updated'],
                'hedge_accounts': json.loads(row.get('hedge_accounts') or '[]'),
                'prop_accounts': json.loads(row.get('prop_accounts') or '[]'),
                'vps_accounts': json.loads(row.get('vps_accounts') or '[]'),
                'payment_info': json.loads(row.get('payment_info') or '[]'),
                'payment_address': json.loads(row.get('payment_address') or '{}'),
                'mt5_credentials': json.loads(row.get('mt5_credentials') or '{}'),
                'firm_billing': json.loads(row.get('firm_billing') or '{}'),
            }
        
        return None
```

#### `get_all_clients`

```python
def get_all_clients() -> dict
```
> Get all client data in a single query (avoids N+1 pattern).

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_all_clients() -> dict:
    """Get all client data in a single query (avoids N+1 pattern)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM clients_data')
        clients = {}
        for row in cursor.fetchall():
            client_id = row['client_id']
            try:
                identity = json.loads(row['identity'] or '{}') or {}
            except Exception:
                identity = {}
            clients[client_id] = {
                'deals': json.loads(row['deals']),
                'positions': json.loads(row['positions']),
                'account': json.loads(row['account']),
                'evaluations': json.loads(row['evaluations']),
                'statistics': json.loads(row['statistics']),
                'dropdown_options': json.loads(row['dropdown_options']),
                'identity': identity,
                'sheet_url': identity.get('sheet_url') if isinstance(identity, dict) else None,
                'last_updated': row['last_updated'],
                'hedge_accounts': json.loads(row.get('hedge_accounts') or '[]'),
                'prop_accounts': json.loads(row.get('prop_accounts') or '[]'),
                'vps_accounts': json.loads(row.get('vps_accounts') or '[]'),
                'payment_info': json.loads(row.get('payment_info') or '[]'),
                'payment_address': json.loads(row.get('payment_address') or '{}'),
                'mt5_credentials': json.loads(row.get('mt5_credentials') or '{}'),
                'firm_billing': json.loads(row.get('firm_billing') or '{}'),
            }
        return clients
```

#### `get_all_client_identities`

```python
def get_all_client_identities() -> dict
```
> Fetch only client_id + identity for all clients in one query. Used to avoid N+1 queries when only identity fields are needed.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_all_client_identities() -> dict:
    """Fetch only client_id + identity for all clients in one query.
    Used to avoid N+1 queries when only identity fields are needed."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT client_id, identity FROM clients_data')
        result = {}
        for row in cursor.fetchall():
            try:
                identity = json.loads(row['identity'] or '{}') or {}
            except Exception:
                identity = {}
            result[row['client_id']] = identity
        return result
```

#### `delete_client_data`

```python
def delete_client_data(client_id: str) -> bool
```
> Permanently delete all data for a client from the database.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def delete_client_data(client_id: str) -> bool:
    """Permanently delete all data for a client from the database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM clients_data WHERE client_id = ?', (client_id,))
        cursor.execute('DELETE FROM data_history WHERE client_id = ?', (client_id,))
        cursor.execute('DELETE FROM cell_notes WHERE client_id = ?', (client_id,))
        cursor.execute('DELETE FROM daily_watermarks WHERE client_id = ?', (client_id,))
        cursor.execute('DELETE FROM waterlog_periods WHERE client_id = ?', (client_id,))
        conn.commit()
        return cursor.rowcount >= 0
```

#### `get_clients_count`

```python
def get_clients_count() -> int
```
> Get count of clients in database.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_clients_count() -> int:
    """Get count of clients in database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM clients_data')
        row = cursor.fetchone()
        return row['count'] if row else 0
```

#### `update_client_field`

```python
def update_client_field(client_id: str, field: str, value) -> bool
```
> Update a specific field for a client.

**What it does, step by step:**

1. Assigns <code>valid_fields</code> = <code>['deals', 'positions', 'account', 'evaluations', 'statist...</code>.
2. <b>if</b> <code>field not in valid_fields</code>: branches conditionally.
3. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def update_client_field(client_id: str, field: str, value) -> bool:
    """Update a specific field for a client."""
    valid_fields = ['deals', 'positions', 'account', 'evaluations', 'statistics', 'identity', 'dropdown_options',
                    'hedge_accounts', 'prop_accounts', 'vps_accounts', 'payment_info', 'payment_address']
    if field not in valid_fields:
        return False
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # First ensure client exists
        cursor.execute('SELECT client_id FROM clients_data WHERE client_id = ?', (client_id,))
        if cursor.fetchone() is None:
            # Create new client record
            save_client_data(client_id, {field: value})
            return True
        
        # Update specific field
        cursor.execute(f'''
            UPDATE clients_data 
            SET {field} = ?, last_updated = ?
            WHERE client_id = ?
        ''', (json.dumps(value), datetime.now().isoformat(), client_id))
        conn.commit()
        return True
```

#### `_repair_quality_table`

```python
def _repair_quality_table()
```
> No-op — schema is managed by Alembic. PostgreSQL handles table integrity.

**What it does, step by step:**

1. Calls <code>print(...)</code> for its side effect.

```python
def _repair_quality_table():
    """No-op — schema is managed by Alembic. PostgreSQL handles table integrity."""
    print("[DB] quality_scan_results table integrity is managed by PostgreSQL")
```

#### `_ensure_quality_bot_tables`

```python
def _ensure_quality_bot_tables()
```
> Small operational tables used by the Slack quality bot: - quality_slack_posts: when the bot posted for a date - quality_issue_baseline: which clients had issues at post time - quality_issue_resolution: when a client first reached 0 issues after baseline

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def _ensure_quality_bot_tables():
    """
    Small operational tables used by the Slack quality bot:
    - quality_slack_posts: when the bot posted for a date
    - quality_issue_baseline: which clients had issues at post time
    - quality_issue_resolution: when a client first reached 0 issues after baseline
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS quality_slack_posts (
                scan_date  TEXT PRIMARY KEY,
                posted_at  TEXT NOT NULL
            )
            '''
        )
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS quality_issue_baseline (
                scan_date  TEXT NOT NULL,
                client_id  TEXT NOT NULL,
                trader     TEXT NOT NULL DEFAULT '',
                had_issues INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (scan_date, client_id)
            )
            '''
        )
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS quality_issue_resolution (
                scan_date   TEXT NOT NULL,
                client_id   TEXT NOT NULL,
                resolved_at TEXT NOT NULL,
                PRIMARY KEY (scan_date, client_id)
            )
            '''
        )
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS quality_team_leaderboard_daily (
                scan_date          TEXT NOT NULL,
                admin_name         TEXT NOT NULL,
                team_name          TEXT NOT NULL,
                rank               INTEGER NOT NULL,
                points             INTEGER NOT NULL DEFAULT 0,
                composite_minutes  INTEGER,
                signoff_minutes    INTEGER,
                clearance_minutes  INTEGER,
                summary_minutes  INTEGER,
                health_score       REAL,
                clients            INTEGER NOT NULL DEFAULT 0,
                created_at         TEXT NOT NULL,
                PRIMARY KEY (scan_date, admin_name)
            )
            '''
        )
        conn.commit()
```

#### `record_quality_slack_post`

```python
def record_quality_slack_post(scan_date: str, posted_at: str)
```
> Record when the Slack quality bot posted for a scan_date (idempotent).  The first timestamp for a scan_date is kept (morning scan or Slack post) so issue-clearance speed rankings are not reset by later posts or rescans.

**What it does, step by step:**

1. <b>if</b> <code>not scan_date or not posted_at</code>: branches conditionally.
2. <b>try</b> block with 1 <b>except</b> clause.

```python
def record_quality_slack_post(scan_date: str, posted_at: str):
    """Record when the Slack quality bot posted for a scan_date (idempotent).

    The first timestamp for a scan_date is kept (morning scan or Slack post) so
    issue-clearance speed rankings are not reset by later posts or rescans.
    """
    if not scan_date or not posted_at:
        return
    try:
        _ensure_quality_bot_tables()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO quality_slack_posts (scan_date, posted_at)
                VALUES (?, ?)
                ON CONFLICT(scan_date) DO NOTHING
                ''',
                (scan_date, posted_at),
            )
            conn.commit()
    except Exception:
        # Non-critical: bot still works without the tie-breaker tables.
        return
```

#### `record_quality_scan_anchor`

```python
def record_quality_scan_anchor(scan_date: str, anchored_at: str)
```
> Alias for the scan-day clock used by issue-clearance rankings (first write wins).

**What it does, step by step:**

1. Calls <code>record_quality_slack_post(...)</code> for its side effect.

```python
def record_quality_scan_anchor(scan_date: str, anchored_at: str):
    """Alias for the scan-day clock used by issue-clearance rankings (first write wins)."""
    record_quality_slack_post(scan_date, anchored_at)
```

#### `upsert_quality_issue_baseline`

```python
def upsert_quality_issue_baseline(scan_date: str, client_id: str, trader: str, had_issues: bool)
```
> Upsert baseline issue state for a client at bot-post time.

**What it does, step by step:**

1. <b>if</b> <code>not scan_date or not client_id</code>: branches conditionally.
2. <b>try</b> block with 1 <b>except</b> clause.

```python
def upsert_quality_issue_baseline(scan_date: str, client_id: str, trader: str, had_issues: bool):
    """Upsert baseline issue state for a client at bot-post time."""
    if not scan_date or not client_id:
        return
    try:
        _ensure_quality_bot_tables()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO quality_issue_baseline (scan_date, client_id, trader, had_issues)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scan_date, client_id) DO UPDATE SET
                    trader = excluded.trader,
                    had_issues = CASE
                        WHEN quality_issue_baseline.had_issues = 1 OR excluded.had_issues = 1 THEN 1
                        ELSE 0
                    END
                ''',
                (scan_date, client_id, trader or '', 1 if had_issues else 0),
            )
            conn.commit()
    except Exception:
        return
```

#### `mark_quality_issue_resolved`

```python
def mark_quality_issue_resolved(scan_date: str, client_id: str, resolved_at: str)
```
> If the client had issues at baseline time and now has 0 issues, record the FIRST time it was observed resolved.

**What it does, step by step:**

1. <b>if</b> <code>not scan_date or not client_id or (not resolved_at)</code>: branches conditionally.
2. <b>try</b> block with 1 <b>except</b> clause.

```python
def mark_quality_issue_resolved(scan_date: str, client_id: str, resolved_at: str):
    """
    If the client had issues at baseline time and now has 0 issues,
    record the FIRST time it was observed resolved.
    """
    if not scan_date or not client_id or not resolved_at:
        return
    try:
        _ensure_quality_bot_tables()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT had_issues FROM quality_issue_baseline WHERE scan_date = ? AND client_id = ?',
                (scan_date, client_id),
            )
            base = cursor.fetchone()
            if not base or int(base.get('had_issues') or 0) != 1:
                return
            cursor.execute(
                '''
                INSERT INTO quality_issue_resolution (scan_date, client_id, resolved_at)
                VALUES (?, ?, ?)
                ON CONFLICT(scan_date, client_id) DO NOTHING
                ''',
                (scan_date, client_id, resolved_at),
            )
            conn.commit()
    except Exception:
        return
```

#### `save_quality_team_leaderboard_day`

```python
def save_quality_team_leaderboard_day(scan_date: str, rows: list) -> None
```
> Persist daily admin-team ranks and points (one row per admin per scan_date).

**What it does, step by step:**

1. <b>if</b> <code>not scan_date</code>: branches conditionally.
2. <b>try</b> block with 1 <b>except</b> clause.

```python
def save_quality_team_leaderboard_day(scan_date: str, rows: list) -> None:
    """Persist daily admin-team ranks and points (one row per admin per scan_date)."""
    if not scan_date:
        return
    try:
        _ensure_quality_bot_tables()
        from datetime import datetime as _dt
        now = _dt.utcnow().isoformat()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM quality_team_leaderboard_daily WHERE scan_date = ?',
                (scan_date,),
            )
            for row in rows or []:
                admin = str(row.get('admin_name') or '').strip()
                if not admin:
                    continue
                cursor.execute(
                    '''
                    INSERT INTO quality_team_leaderboard_daily (
                        scan_date, admin_name, team_name, rank, points,
                        composite_minutes, signoff_minutes, clearance_minutes, summary_minutes,
                        health_score, clients, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        scan_date,
                        admin,
                        str(row.get('team_name') or admin),
                        int(row.get('rank') or 0),
                        int(row.get('points') or 0),
                        row.get('composite_minutes'),
                        row.get('signoff_minutes') if row.get('signoff_minutes') is not None else row.get('avg_signoff_minutes'),
                        row.get('clearance_minutes'),
                        row.get('summary_minutes'),
                        row.get('health_score') if row.get('health_score') is not None else row.get('score'),
                        int(row.get('clients') or 0),
                        now,
                    ),
                )
            conn.commit()
    except Exception as e:
        print(f"Error saving team leaderboard for {scan_date}: {e}")
```

#### `get_quality_team_leaderboard_day`

```python
def get_quality_team_leaderboard_day(scan_date: str) -> list
```
> Rows for one UTC scan_date, ordered by rank.

**What it does, step by step:**

1. <b>if</b> <code>not scan_date</code>: branches conditionally.
2. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_quality_team_leaderboard_day(scan_date: str) -> list:
    """Rows for one UTC scan_date, ordered by rank."""
    if not scan_date:
        return []
    try:
        _ensure_quality_bot_tables()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT * FROM quality_team_leaderboard_daily
                WHERE scan_date = ?
                ORDER BY rank ASC, team_name ASC
                ''',
                (scan_date,),
            )
            return [dict(r) for r in (cursor.fetchall() or [])]
    except Exception as e:
        print(f"Error loading team leaderboard for {scan_date}: {e}")
        return []
```

#### `get_quality_team_leaderboard_month`

```python
def get_quality_team_leaderboard_month(month_prefix: str) -> list
```
> Aggregate points per team for scan_dates starting with YYYY-MM.

**What it does, step by step:**

1. <b>if</b> <code>not month_prefix</code>: branches conditionally.
2. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_quality_team_leaderboard_month(month_prefix: str) -> list:
    """Aggregate points per team for scan_dates starting with YYYY-MM."""
    if not month_prefix:
        return []
    try:
        _ensure_quality_bot_tables()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT admin_name, team_name,
                       SUM(points) AS month_points,
                       COUNT(*) AS days_ranked,
                       MIN(rank) AS best_rank,
                       ROUND(AVG(composite_minutes)) AS avg_composite
                FROM quality_team_leaderboard_daily
                WHERE scan_date LIKE ?
                GROUP BY admin_name, team_name
                ORDER BY month_points DESC, best_rank ASC, team_name ASC
                ''',
                (f'{month_prefix}%',),
            )
            return [dict(r) for r in (cursor.fetchall() or [])]
    except Exception as e:
        print(f"Error loading team leaderboard month {month_prefix}: {e}")
        return []
```

#### `get_trader_issue_resolution_minutes`

```python
def get_trader_issue_resolution_minutes(scan_date: str, trader: str, *, unresolved_minutes: int=99999) -> int
```
> Minutes from scan anchor to when ALL baseline-issue clients for this trader reached 0 issues.  Returns:   - TRADER_CLEARANCE_NOT_IN_RACE (-1): no baseline issues (clean at scan; not ranked as "fastest").   - 0..N: all baseline clients resolved; value is minutes for the slowest client to clear.   - unresolved_minutes (default 99999): still has unresolved baseline clients, or no anchor yet.

**What it does, step by step:**

1. <b>if</b> <code>not scan_date or not trader</code>: branches conditionally.
2. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_trader_issue_resolution_minutes(scan_date: str, trader: str, *, unresolved_minutes: int = 99999) -> int:
    """
    Minutes from scan anchor to when ALL baseline-issue clients for this trader reached 0 issues.

    Returns:
      - TRADER_CLEARANCE_NOT_IN_RACE (-1): no baseline issues (clean at scan; not ranked as "fastest").
      - 0..N: all baseline clients resolved; value is minutes for the slowest client to clear.
      - unresolved_minutes (default 99999): still has unresolved baseline clients, or no anchor yet.
    """
    if not scan_date or not trader:
        return unresolved_minutes
    try:
        _ensure_quality_bot_tables()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT posted_at FROM quality_slack_posts WHERE scan_date = ?', (scan_date,))
            row = cursor.fetchone()
            posted_at = (row.get('posted_at') if row else '') or ''
            if not posted_at:
                return unresolved_minutes

            cursor.execute(
                '''
                SELECT client_id
                FROM quality_issue_baseline
                WHERE scan_date = ? AND lower(trader) = lower(?) AND had_issues = 1
                ''',
                (scan_date, trader),
            )
            clients = [r.get('client_id') for r in (cursor.fetchall() or []) if r.get('client_id')]
            if not clients:
                return TRADER_CLEARANCE_NOT_IN_RACE

            # Fetch resolution rows for those clients
            placeholders = ','.join(['?'] * len(clients))
            cursor.execute(
                f'''
                SELECT client_id, resolved_at
                FROM quality_issue_resolution
                WHERE scan_date = ? AND client_id IN ({placeholders})
                ''',
                (scan_date, *clients),
            )
            res_map = {r.get('client_id'): (r.get('resolved_at') or '') for r in (cursor.fetchall() or [])}
            if any(not res_map.get(cid) for cid in clients):
                return unresolved_minutes

            try:
                from datetime import datetime as _dt
                posted = _dt.fromisoformat(posted_at.replace('Z', '+00:00'))
                mins = []
                for cid in clients:
                    dt = _dt.fromisoformat(res_map[cid].replace('Z', '+00:00'))
                    delta = dt - posted
                    mins.append(max(0, round(delta.total_seconds() / 60)))
                return int(max(mins) if mins else 0)
            except Exception:
                return unresolved_minutes
    except Exception:
        return unresolved_minutes
```

#### `save_quality_scan_results`

```python
def save_quality_scan_results(scan_date: str, results: list)
```
> Save quality scan results for all clients.

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def save_quality_scan_results(scan_date: str, results: list):
    """Save quality scan results for all clients."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM quality_scan_results WHERE scan_date = ?', (scan_date,))
            for r in results:
                cursor.execute('''
                    INSERT INTO quality_scan_results (scan_date, client_id, trader, admin, total_issues, issues, health_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (scan_date, r['client_id'], r.get('trader'), r.get('admin'),
                      r['total_issues'], json.dumps(r['issues']), r['health_score']))
            conn.commit()
    except Exception as e:
        print(f"Error saving quality scan results: {e}")
        raise
```

#### `get_quality_scan_results`

```python
def get_quality_scan_results(scan_date: str=None) -> list
```
> Get quality scan results. If no date, returns latest scan.

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_quality_scan_results(scan_date: str = None) -> list:
    """Get quality scan results. If no date, returns latest scan."""
    try:
        return _get_quality_scan_results_inner(scan_date)
    except Exception as e:
        print(f"Error getting quality scan results: {e}")
        return []
```

#### `_get_quality_scan_results_inner`

```python
def _get_quality_scan_results_inner(scan_date: str=None) -> list
```
**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def _get_quality_scan_results_inner(scan_date: str = None) -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        if not scan_date:
            cursor.execute('SELECT MAX(scan_date) as d FROM quality_scan_results')
            row = cursor.fetchone()
            scan_date = row['d'] if row and row['d'] else None
        if not scan_date:
            return []
        cursor.execute('''
            SELECT * FROM quality_scan_results WHERE scan_date = ? ORDER BY health_score ASC
        ''', (scan_date,))
        results = []
        for row in cursor.fetchall():
            results.append({
                'client_id': row['client_id'],
                'trader': row['trader'],
                'admin': row['admin'],
                'total_issues': row['total_issues'],
                'issues': json.loads(row['issues']),
                'health_score': row['health_score'],
                'scan_date': row['scan_date'],
            })
        return results
```

#### `save_daily_checklist`

```python
def save_daily_checklist(date: str, user_identifier: str, user_type: str, checklist_type: str, items: list, ip_address: str=None, client_id: str='')
```
> Save a daily checklist submission (per client).

**What it does, step by step:**

1. Assigns <code>date</code> = <code>_normalize_identifier(date)</code>.
2. Assigns <code>user_identifier</code> = <code>_normalize_identifier(user_identifier)</code>.
3. Assigns <code>user_type</code> = <code>_normalize_identifier(user_type)</code>.
4. Assigns <code>checklist_type</code> = <code>_normalize_identifier(checklist_type)</code>.
5. Assigns <code>client_id</code> = <code>_normalize_identifier(client_id)</code>.
6. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def save_daily_checklist(date: str, user_identifier: str, user_type: str,
                         checklist_type: str, items: list, ip_address: str = None,
                         client_id: str = ''):
    """Save a daily checklist submission (per client)."""
    # Normalize identifiers to avoid subtle mismatches (e.g. trailing spaces)
    # which can cause the UI to show "pending" even after a successful save.
    date = _normalize_identifier(date)
    user_identifier = _normalize_identifier(user_identifier)
    user_type = _normalize_identifier(user_type)
    checklist_type = _normalize_identifier(checklist_type)
    client_id = _normalize_identifier(client_id)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO daily_checklists (date, user_identifier, user_type, checklist_type, client_id, items, submitted_at, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, user_identifier, checklist_type, client_id) DO UPDATE SET
                user_type = excluded.user_type,
                items = excluded.items,
                submitted_at = excluded.submitted_at,
                ip_address = excluded.ip_address
        ''', (date, user_identifier, user_type, checklist_type, client_id, json.dumps(items),
              datetime.now().isoformat(), ip_address))
        conn.commit()
```

#### `_ensure_checklist_client_column`

```python
def _ensure_checklist_client_column()
```
> No-op — schema is managed by Alembic.

**What it does, step by step:**

1. <b>pass</b> (placeholder).

```python
def _ensure_checklist_client_column():
    """No-op — schema is managed by Alembic."""
    pass
```

#### `_ensure_settings_table`

```python
def _ensure_settings_table()
```
> No-op — schema is managed by Alembic.

**What it does, step by step:**

1. <b>pass</b> (placeholder).

```python
def _ensure_settings_table():
    """No-op — schema is managed by Alembic."""
    pass
```

#### `get_setting`

```python
def get_setting(key: str) -> str
```
> Get a system setting by key. Returns empty string if not found.

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_setting(key: str) -> str:
    """Get a system setting by key. Returns empty string if not found."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM system_settings WHERE key = ?', (key,))
            row = cursor.fetchone()
            return row['value'] if row else ''
    except Exception:
        _ensure_settings_table()
        return ''
```

#### `set_setting`

```python
def set_setting(key: str, value: str, updated_by: str='')
```
> Set a system setting.

**What it does, step by step:**

1. Calls <code>_ensure_settings_table(...)</code> for its side effect.
2. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def set_setting(key: str, value: str, updated_by: str = ''):
    """Set a system setting."""
    _ensure_settings_table()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO system_settings (key, value, updated_at, updated_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, updated_by=excluded.updated_by
        ''', (key, value, datetime.now().isoformat(), updated_by))
        conn.commit()
```

#### `get_daily_checklists`

```python
def get_daily_checklists(date: str, user_identifier: str=None) -> list
```
> Get checklists for a date, optionally filtered by user.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_daily_checklists(date: str, user_identifier: str = None) -> list:
    """Get checklists for a date, optionally filtered by user."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if user_identifier:
            cursor.execute('SELECT * FROM daily_checklists WHERE date = ? AND user_identifier = ?',
                           (date, user_identifier))
        else:
            cursor.execute('SELECT * FROM daily_checklists WHERE date = ?', (date,))
        return [{
            'user_identifier': row['user_identifier'],
            'user_type': row['user_type'],
            'checklist_type': row['checklist_type'],
            'client_id': row['client_id'] if 'client_id' in row.keys() else '',
            'items': json.loads(row['items']),
            'submitted_at': row['submitted_at'],
        } for row in cursor.fetchall()]
```

#### `get_latest_daily_summary_checklist_for_client`

```python
def get_latest_daily_summary_checklist_for_client(scan_date: str, client_id: str) -> dict
```
> Most recent trader daily_summary row for this client on scan_date (by submitted_at).

**What it does, step by step:**

1. <b>if</b> <code>not scan_date or not client_id</code>: branches conditionally.
2. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_latest_daily_summary_checklist_for_client(scan_date: str, client_id: str) -> dict:
    """Most recent trader daily_summary row for this client on scan_date (by submitted_at)."""
    if not scan_date or not client_id:
        return None
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT items, submitted_at, user_identifier FROM daily_checklists
                   WHERE date = ? AND client_id = ? AND checklist_type = ?
                   ORDER BY submitted_at DESC LIMIT 1''',
                (scan_date, client_id, 'daily_summary'),
            )
            row = cursor.fetchone()
            if not row:
                return None
            raw_items = row['items']
            items = json.loads(raw_items) if isinstance(raw_items, str) else (raw_items or [])
            return {
                'items': items,
                'submitted_at': row.get('submitted_at'),
                'user_identifier': row.get('user_identifier') or '',
            }
    except Exception:
        return None
```

#### `get_checklist_clients_for_date`

```python
def get_checklist_clients_for_date(date: str) -> set
```
> Return set of client_ids that have a daily_summary checklist submitted for the given date.

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_checklist_clients_for_date(date: str) -> set:
    """Return set of client_ids that have a daily_summary checklist submitted for the given date."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT client_id FROM daily_checklists WHERE date = ? AND checklist_type = 'daily_summary' AND client_id != ''",
                (date,)
            )
            return {row['client_id'] for row in cursor.fetchall()}
    except Exception:
        return set()
```

#### `get_summary_status_for_date`

```python
def get_summary_status_for_date(date: str) -> list
```
> Return all daily_summary checklist submissions for the given date. Merges data from daily_checklists table AND audit_log.  The 24-hour window runs from 23:05 UTC day-1 to 23:05 UTC day (= 2:05 AM Kenyan → 2:05 AM Kenyan).  The `date` parameter is the UTC date (server runs UTC).

**What it does, step by step:**

1. Assigns <code>results</code> = <code>{}</code>.
2. Defines a nested function <code>_row_value(...)</code>.
3. Lazy import from <code>datetime</code>.
4. <b>try</b> block with 1 <b>except</b> clause.
5. Assigns <code>utc_start</code> = <code>(utc_date - _td(days=1)).strftime('%Y-%m-%d') + 'T23:05'</code>.
6. Assigns <code>utc_end</code> = <code>utc_date.strftime('%Y-%m-%d') + 'T23:05'</code>.
7. <b>try</b> block with 1 <b>except</b> clause.
8. <b>return</b> <code>list(results.values())</code>.

```python
def get_summary_status_for_date(date: str) -> list:
    """Return all daily_summary checklist submissions for the given date.
    Merges data from daily_checklists table AND audit_log.

    The 24-hour window runs from 23:05 UTC day-1 to 23:05 UTC day
    (= 2:05 AM Kenyan → 2:05 AM Kenyan).  The `date` parameter is the
    UTC date (server runs UTC).
    """
    results = {}  # normalized client_id -> {client_id, submitted_by, submitted_at}

    def _row_value(row, key, default=None):
        """Support both dict rows and sqlite3.Row-like rows."""
        try:
            return row[key]
        except Exception:
            try:
                return row.get(key, default)  # type: ignore[attr-defined]
            except Exception:
                return default

    from datetime import timedelta as _td
    try:
        utc_date = datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        return []

    # Window: 23:05 UTC previous day → 23:05 UTC this day
    # = 2:05 AM Kenyan day → 2:05 AM Kenyan day+1
    utc_start = (utc_date - _td(days=1)).strftime('%Y-%m-%d') + 'T23:05'
    utc_end = utc_date.strftime('%Y-%m-%d') + 'T23:05'

    try:
        # Build a set of valid client names to avoid mis-parsing audit_log details.
        # (Some logs contain " for <client> : replaced ..." which is NOT a client id.)
        try:
            from config.hierarchy import get_all_clients as _hier_clients
            _valid_clients = { _normalize_identifier(x) for x in (_hier_clients() or []) if _normalize_identifier(x) }
        except Exception:
            _valid_clients = set()

        with get_connection() as conn:
            cursor = conn.cursor()
            # Source 1: daily_checklists — ONLY count as "sent" if the checklist
            # includes the explicit slack marker item (id == "slack_sent").
            # Traders can Save & Preview without actually sending; that should NOT
            # mark the client as done in the submission tracker.
            cursor.execute(
                "SELECT client_id, user_identifier, submitted_at, items FROM daily_checklists "
                "WHERE checklist_type = 'daily_summary' AND client_id != '' "
                "AND submitted_at >= ? AND submitted_at < ? "
                "ORDER BY submitted_at DESC",
                (utc_start, utc_end)
            )
            for row in cursor.fetchall():
                cid = _normalize_identifier(_row_value(row, 'client_id') or '')
                if not cid:
                    continue
                # Only count if slack_sent exists in the saved items payload.
                try:
                    raw_items = _row_value(row, 'items')
                    items = json.loads(raw_items) if isinstance(raw_items, str) else (raw_items or [])
                    has_slack_marker = any(
                        isinstance(it, dict) and (it.get('id') == 'slack_sent')
                        for it in (items or [])
                    )
                except Exception:
                    has_slack_marker = False
                if not has_slack_marker:
                    continue
                if cid not in results:
                    results[cid] = {
                        'client_id': cid,
                        'submitted_by': _row_value(row, 'user_identifier') or '',
                        'submitted_at': _row_value(row, 'submitted_at'),
                    }

            # Source 2: audit_log — same 23:05→23:05 UTC window
            cursor.execute(
                "SELECT user_identifier, details, timestamp FROM audit_log "
                "WHERE action IN ('SLACK_DAILY_SUMMARY') "
                "AND timestamp >= ? AND timestamp < ? AND success = 1 "
                "ORDER BY timestamp DESC",
                (utc_start, utc_end)
            )
            for row in cursor.fetchall():
                details = _row_value(row, 'details') or ''
                client_id = ''
                if ' for ' in details:
                    part = details.split(' for ', 1)[1]
                    import re
                    part = re.sub(r':\s*\d+\s+sections?\s*$', '', part).strip()
                    # If the message includes extra suffixes (e.g. ": replaced ..."),
                    # try to recover just the client name.
                    candidate = _normalize_identifier(part or '')
                    if candidate and _valid_clients:
                        if candidate not in _valid_clients:
                            # Common pattern: "<client> : <extra info>"
                            head = _normalize_identifier(candidate.split(':', 1)[0])
                            if head in _valid_clients:
                                candidate = head
                    client_id = candidate

                client_id = _normalize_identifier(client_id or '')
                if client_id and (_valid_clients and client_id not in _valid_clients):
                    # Don't allow audit_log inference to create phantom client ids.
                    continue
                if client_id and client_id not in results:
                    results[client_id] = {
                        'client_id': client_id,
                        'submitted_by': _row_value(row, 'user_identifier') or '',
                        'submitted_at': _row_value(row, 'timestamp'),
                    }
    except Exception:
        pass
    return list(results.values())
```

#### `get_weekly_scan_results`

```python
def get_weekly_scan_results(end_date: str=None, days: int=7) -> list
```
> Get quality scan results for a date range (default: last 7 days).

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_weekly_scan_results(end_date: str = None, days: int = 7) -> list:
    """Get quality scan results for a date range (default: last 7 days)."""
    try:
        return _get_weekly_scan_results_inner(end_date, days)
    except Exception as e:
        print(f"Error getting weekly scan results: {e}")
        return []
```

#### `_get_weekly_scan_results_inner`

```python
def _get_weekly_scan_results_inner(end_date: str=None, days: int=7) -> list
```
**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def _get_weekly_scan_results_inner(end_date: str = None, days: int = 7) -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=days - 1)).strftime('%Y-%m-%d')
        cursor.execute('''
            SELECT * FROM quality_scan_results
            WHERE scan_date BETWEEN ? AND ?
            ORDER BY scan_date ASC, health_score ASC
        ''', (start_date, end_date))
        results = []
        for row in cursor.fetchall():
            results.append({
                'client_id': row['client_id'],
                'trader': row['trader'],
                'admin': row['admin'],
                'total_issues': row['total_issues'],
                'issues': json.loads(row['issues']),
                'health_score': row['health_score'],
                'scan_date': row['scan_date'],
            })
        return results
```

#### `_ensure_qa_resolutions_table`

```python
def _ensure_qa_resolutions_table()
```
> Ensure QA resolution table exists (small operational table).

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def _ensure_qa_resolutions_table():
    """Ensure QA resolution table exists (small operational table)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS qa_resolutions (
                check_name TEXT NOT NULL,
                client_id TEXT NOT NULL,
                row_index INTEGER NOT NULL,
                resolved BOOLEAN NOT NULL DEFAULT TRUE,
                resolved_by TEXT NOT NULL DEFAULT '',
                resolved_at TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (check_name, client_id, row_index)
            )
        ''')
        conn.commit()
```

#### `get_qa_resolved_set`

```python
def get_qa_resolved_set(check_name: str) -> set
```
> Return a set of (client_id, row_index) resolved for a given QA check.

**What it does, step by step:**

1. <b>if</b> <code>not check_name</code>: branches conditionally.
2. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_qa_resolved_set(check_name: str) -> set:
    """Return a set of (client_id, row_index) resolved for a given QA check."""
    if not check_name:
        return set()
    try:
        _ensure_qa_resolutions_table()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT client_id, row_index FROM qa_resolutions WHERE check_name = ? AND resolved = TRUE',
                (check_name,)
            )
            rows = cursor.fetchall() or []
            out = set()
            for r in rows:
                try:
                    out.add((r['client_id'], int(r['row_index'])))
                except Exception:
                    continue
            return out
    except Exception:
        return set()
```

#### `is_qa_resolved`

```python
def is_qa_resolved(check_name: str, client_id: str, row_index: int) -> bool
```
> Check whether a specific QA issue has been resolved.

**What it does, step by step:**

1. <b>if</b> <code>not check_name or not client_id</code>: branches conditionally.
2. <b>try</b> block with 1 <b>except</b> clause.

```python
def is_qa_resolved(check_name: str, client_id: str, row_index: int) -> bool:
    """Check whether a specific QA issue has been resolved."""
    if not check_name or not client_id:
        return False
    try:
        _ensure_qa_resolutions_table()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT resolved FROM qa_resolutions WHERE check_name = ? AND client_id = ? AND row_index = ?',
                (check_name, client_id, int(row_index))
            )
            row = cursor.fetchone()
            return bool(row and row.get('resolved'))
    except Exception:
        return False
```

#### `mark_qa_resolved`

```python
def mark_qa_resolved(check_name: str, client_id: str, row_index: int, resolved_by: str, notes: str='')
```
> Mark a QA issue resolved (idempotent).

**What it does, step by step:**

1. <b>if</b> <code>not check_name or not client_id</code>: branches conditionally.
2. Calls <code>_ensure_qa_resolutions_table(...)</code> for its side effect.
3. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def mark_qa_resolved(check_name: str, client_id: str, row_index: int, resolved_by: str, notes: str = ''):
    """Mark a QA issue resolved (idempotent)."""
    if not check_name or not client_id:
        return
    _ensure_qa_resolutions_table()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO qa_resolutions (check_name, client_id, row_index, resolved, resolved_by, resolved_at, notes)
            VALUES (?, ?, ?, TRUE, ?, ?, ?)
            ON CONFLICT(check_name, client_id, row_index) DO UPDATE SET
                resolved = TRUE,
                resolved_by = excluded.resolved_by,
                resolved_at = excluded.resolved_at,
                notes = excluded.notes
        ''', (check_name, client_id, int(row_index), resolved_by or '', datetime.now().isoformat(), notes or ''))
        conn.commit()
```

#### `get_client_activity`

```python
def get_client_activity(client_id: str) -> dict
```
> Get last push time and last edit info for a client from data_history.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_client_activity(client_id: str) -> dict:
    """Get last push time and last edit info for a client from data_history."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Last push (from companion app / MT5)
        cursor.execute('''
            SELECT created_at, changed_by FROM data_history
            WHERE client_id = ? AND change_source = 'push'
            ORDER BY version DESC LIMIT 1
        ''', (client_id,))
        push_row = cursor.fetchone()

        # Last manual edit (from dashboard)
        cursor.execute('''
            SELECT created_at, changed_by, changed_by_type FROM data_history
            WHERE client_id = ? AND change_source IN ('dashboard_edit', 'dashboard_delete')
            ORDER BY version DESC LIMIT 1
        ''', (client_id,))
        edit_row = cursor.fetchone()

        return {
            'last_push_at': push_row['created_at'] if push_row else None,
            'last_push_by': push_row['changed_by'] if push_row else None,
            'last_edit_at': edit_row['created_at'] if edit_row else None,
            'last_edit_by': edit_row['changed_by'] if edit_row else None,
            'last_edit_by_type': edit_row['changed_by_type'] if edit_row else None,
        }
```

#### `get_next_version`

```python
def get_next_version(client_id: str) -> int
```
> Get the next version number for a client's data history.

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_next_version(client_id: str) -> int:
    """Get the next version number for a client's data history."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT MAX(version) as max_version FROM data_history WHERE client_id = ?
            ''', (client_id,))
            row = cursor.fetchone()
            return (row['max_version'] or 0) + 1
    except Exception as e:
        print(f"Error getting next version: {e}")
        # Fallback to local timestamp-based ID or just start at 1 if DB read fails?
        # If DB read fails, snapshot will likely fail too, but at least we don't crash the app.
        return 1
```

#### `verify_data_saved`

```python
def verify_data_saved(client_id: str, expected_evals_count: int=None, expected_stat_key: str=None) -> bool
```
> Verify that data was actually saved and committed to the database.  This is a critical check to detect silent commit failures or connection issues. Pass expected_evals_count or expected_stat_key to verify specific fields were persisted.  Returns: True if data is present and matches expected values, False otherwise.

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def verify_data_saved(client_id: str, expected_evals_count: int = None, expected_stat_key: str = None) -> bool:
    """
    Verify that data was actually saved and committed to the database.
    
    This is a critical check to detect silent commit failures or connection issues.
    Pass expected_evals_count or expected_stat_key to verify specific fields were persisted.
    
    Returns: True if data is present and matches expected values, False otherwise.
    """
    try:
        saved_data = get_client_data(client_id)
        if not saved_data:
            logger.warning(f"[DB VERIFY FAILED] No data found for {client_id} after save")
            return False
        
        if expected_evals_count is not None:
            actual_count = len(saved_data.get('evaluations', []))
            if actual_count != expected_evals_count:
                logger.warning(
                    f"[DB VERIFY FAILED] {client_id} evals count mismatch: "
                    f"expected {expected_evals_count}, got {actual_count}"
                )
                return False
        
        if expected_stat_key is not None:
            stats = saved_data.get('statistics', {})
            if expected_stat_key not in stats:
                logger.warning(
                    f"[DB VERIFY FAILED] {client_id} stats missing key: {expected_stat_key}"
                )
                return False
        
        logger.debug(f"[DB VERIFY OK] {client_id} data verified successfully")
        return True
    except Exception as e:
        logger.error(f"[DB VERIFY ERROR] Failed to verify {client_id}: {e}")
        return False
```

#### `save_data_snapshot`

```python
def save_data_snapshot(client_id: str, data: dict, action: str, changed_by: str=None, changed_by_type: str=None, ip_address: str=None, change_source: str=None, change_description: str=None) -> int
```
> Save a snapshot of client data to history for versioning/rollback. Version number is assigned atomically inside the transaction using an advisory lock to prevent duplicate-key races under concurrent writes.  Returns:     The version number of the saved snapshot, or -1 on failure.

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def save_data_snapshot(client_id: str, data: dict, action: str,
                       changed_by: str = None, changed_by_type: str = None,
                       ip_address: str = None, change_source: str = None, 
                       change_description: str = None) -> int:
    """
    Save a snapshot of client data to history for versioning/rollback.
    Version number is assigned atomically inside the transaction using
    an advisory lock to prevent duplicate-key races under concurrent writes.

    Returns:
        The version number of the saved snapshot, or -1 on failure.
    """
    try:
        now = datetime.now().isoformat()

        deals_json           = json.dumps(data.get('deals', []))
        positions_json       = json.dumps(data.get('positions', []))
        account_json         = json.dumps(data.get('account', {}))
        evaluations_json     = json.dumps(data.get('evaluations', []))
        statistics_json      = json.dumps(data.get('statistics', {}))
        dropdown_options_json = json.dumps(data.get('dropdown_options', {}))
        identity_json        = json.dumps(data.get('identity', {}))

        with get_connection() as conn:
            cursor = conn.cursor()

            # Advisory lock keyed on client_id hash — prevents concurrent
            # workers from reading the same MAX(version). Released on commit.
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (client_id,)
            )
            cursor.execute(
                'SELECT COALESCE(MAX(version), 0) AS max_ver FROM data_history '
                'WHERE client_id = %s',
                (client_id,)
            )
            row = cursor.fetchone()
            version = (row['max_ver'] if row else 0) + 1

            cursor.execute('''
                INSERT INTO data_history (
                    client_id, version, action, changed_by, changed_by_type,
                    ip_address, change_source, change_description,
                    deals, positions, account, evaluations, statistics,
                    dropdown_options, identity, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                client_id, version, action, changed_by, changed_by_type,
                ip_address, change_source, change_description,
                deals_json, positions_json, account_json, evaluations_json, statistics_json,
                dropdown_options_json, identity_json, now
            ))
            conn.commit()
            return version
    except Exception as e:
        print(f"Error saving data snapshot: {e}")
        return -1
```

#### `save_client_data_with_history`

```python
def save_client_data_with_history(client_id: str, data: dict, action: str='UPDATE', changed_by: str=None, changed_by_type: str=None, ip_address: str=None, change_source: str=None, change_description: str=None, overwrite: bool=False) -> tuple
```
> Save client data AND create a history snapshot for versioning.  Includes verification that data was actually committed to the database.  Returns:     Tuple of (success: bool, version: int)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def save_client_data_with_history(client_id: str, data: dict, 
                                 action: str = 'UPDATE',
                                 changed_by: str = None,
                                 changed_by_type: str = None,
                                 ip_address: str = None,
                                 change_source: str = None,
                                 change_description: str = None,
                                 overwrite: bool = False) -> tuple:
    """
    Save client data AND create a history snapshot for versioning.
    
    Includes verification that data was actually committed to the database.
    
    Returns:
        Tuple of (success: bool, version: int)
    """
    try:
        # First, save a snapshot to history
        version = save_data_snapshot(
            client_id, data, action, changed_by, changed_by_type,
            ip_address, change_source, change_description
        )
        
        if version <= 0:
            logger.error(f"[DB SAVE FAILED] Failed to create history snapshot for {client_id}")
            return (False, -1)
        
        # Then save the current data
        success = save_client_data(client_id, data, overwrite=overwrite)
        
        if not success:
            logger.error(f"[DB SAVE FAILED] Failed to save current data for {client_id} (v{version})")
            return (False, version)
        
        # CRITICAL: Verify data was actually committed (catch silent commit failures)
        evals_count = len(data.get('evaluations', []))
        if not verify_data_saved(client_id, expected_evals_count=evals_count):
            logger.error(
                f"[DB COMMIT VERIFICATION FAILED] {client_id} data not verified after save (v{version}). "
                f"This indicates a potential database connection or commit issue."
            )
            # Don't fail here — data may be committed but verification query hit stale connection
            # Just log it so admin can investigate
        
        logger.info(f"[DB SAVE OK] {client_id} saved successfully (v{version}, {evals_count} evals)")
        return (success, version)
        
    except Exception as e:
        logger.error(f"[DB SAVE ERROR] Failed to save {client_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return (False, -1)
```

#### `get_data_history`

```python
def get_data_history(client_id: str, limit: int=50) -> list
```
> Get the history of all data changes for a client.  Returns list of history entries (newest first) with metadata.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_data_history(client_id: str, limit: int = 50) -> list:
    """
    Get the history of all data changes for a client.
    
    Returns list of history entries (newest first) with metadata.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, client_id, version, action, changed_by, changed_by_type,
                   ip_address, change_source, change_description, created_at
            FROM data_history 
            WHERE client_id = ?
            ORDER BY version DESC
            LIMIT ?
        ''', (client_id, limit))
        
        return [dict(row) for row in cursor.fetchall()]
```

#### `get_data_version`

```python
def get_data_version(client_id: str, version: int) -> dict
```
> Get a specific version of client data from history.  Returns the full data dict for that version, or None if not found.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_data_version(client_id: str, version: int) -> dict:
    """
    Get a specific version of client data from history.
    
    Returns the full data dict for that version, or None if not found.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM data_history WHERE client_id = ? AND version = ?
        ''', (client_id, version))
        row = cursor.fetchone()
        
        if row:
            return {
                'version': row['version'],
                'action': row['action'],
                'changed_by': row['changed_by'],
                'changed_by_type': row['changed_by_type'],
                'change_source': row['change_source'],
                'change_description': row['change_description'],
                'created_at': row['created_at'],
                'data': {
                    'deals': json.loads(row['deals']),
                    'positions': json.loads(row['positions']),
                    'account': json.loads(row['account']),
                    'evaluations': json.loads(row['evaluations']),
                    'statistics': json.loads(row['statistics']),
                    'dropdown_options': json.loads(row['dropdown_options']),
                    'identity': json.loads(row['identity'])
                }
            }
        return None
```

#### `rollback_to_version`

```python
def rollback_to_version(client_id: str, version: int, rolled_back_by: str=None, rolled_back_by_type: str=None, ip_address: str=None) -> tuple
```
> Rollback client data to a specific historical version.  Creates a new version entry marking this as a rollback.  Returns:     Tuple of (success: bool, new_version: int)

**What it does, step by step:**

1. Assigns <code>historical</code> = <code>get_data_version(client_id, version)</code>.
2. <b>if</b> <code>not historical</code>: branches conditionally.
3. <b>return</b> <code>save_client_data_with_history(client_id, historical['data'], action...</code>.

```python
def rollback_to_version(client_id: str, version: int, 
                        rolled_back_by: str = None,
                        rolled_back_by_type: str = None,
                        ip_address: str = None) -> tuple:
    """
    Rollback client data to a specific historical version.
    
    Creates a new version entry marking this as a rollback.
    
    Returns:
        Tuple of (success: bool, new_version: int)
    """
    # Get the historical version data
    historical = get_data_version(client_id, version)
    if not historical:
        return (False, -1)
    
    # Save as new current data with rollback action
    return save_client_data_with_history(
        client_id,
        historical['data'],
        action='ROLLBACK',
        changed_by=rolled_back_by,
        changed_by_type=rolled_back_by_type,
        ip_address=ip_address,
        change_source='rollback',
        change_description=f'Rolled back to version {version} from {historical["created_at"]}'
    )
```

#### `compare_versions`

```python
def compare_versions(client_id: str, version1: int, version2: int) -> dict
```
> Compare two versions of client data and return differences.  Returns dict with changed fields and their old/new values.

**What it does, step by step:**

1. Assigns <code>v1_data</code> = <code>get_data_version(client_id, version1)</code>.
2. Assigns <code>v2_data</code> = <code>get_data_version(client_id, version2)</code>.
3. <b>if</b> <code>not v1_data or not v2_data</code>: branches conditionally.
4. Assigns <code>differences</code> = <code>{'version1': version1, 'version2': version2, 'version1_da...</code>.
5. <b>for</b> <code>field</code> in <code>['deals', 'positions', 'account', 'evaluations', 'statist...</code>: iterates.
6. <b>return</b> <code>differences</code>.

```python
def compare_versions(client_id: str, version1: int, version2: int) -> dict:
    """
    Compare two versions of client data and return differences.
    
    Returns dict with changed fields and their old/new values.
    """
    v1_data = get_data_version(client_id, version1)
    v2_data = get_data_version(client_id, version2)
    
    if not v1_data or not v2_data:
        return None
    
    differences = {
        'version1': version1,
        'version2': version2,
        'version1_date': v1_data['created_at'],
        'version2_date': v2_data['created_at'],
        'changes': {}
    }
    
    # Compare each major field
    for field in ['deals', 'positions', 'account', 'evaluations', 'statistics']:
        d1 = v1_data['data'].get(field)
        d2 = v2_data['data'].get(field)
        
        if d1 != d2:
            if isinstance(d1, list) and isinstance(d2, list):
                differences['changes'][field] = {
                    'type': 'list',
                    'v1_count': len(d1),
                    'v2_count': len(d2),
                    'changed': True
                }
            elif isinstance(d1, dict) and isinstance(d2, dict):
                # For dicts, find specific key changes
                changed_keys = []
                all_keys = set(d1.keys()) | set(d2.keys())
                for key in all_keys:
                    if d1.get(key) != d2.get(key):
                        changed_keys.append(key)
                differences['changes'][field] = {
                    'type': 'dict',
                    'changed_keys': changed_keys
                }
            else:
                differences['changes'][field] = {
                    'type': 'other',
                    'changed': True
                }
    
    return differences
```

#### `get_latest_version`

```python
def get_latest_version(client_id: str) -> int
```
> Get the latest version number for a client.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_latest_version(client_id: str) -> int:
    """Get the latest version number for a client."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT MAX(version) as max_version FROM data_history WHERE client_id = ?
        ''', (client_id,))
        row = cursor.fetchone()
        return row['max_version'] or 0
```

#### `cleanup_old_history`

```python
def cleanup_old_history(client_id: str=None, keep_versions: int=10) -> int
```
> Clean up old history entries, keeping only the latest N versions per client. Also deletes any history entries older than 30 days regardless of version count.  Returns the number of deleted entries.

**What it does, step by step:**

1. Assigns <code>cutoff</code> = <code>(datetime.now() - timedelta(days=30)).isoformat()</code>.
2. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def cleanup_old_history(client_id: str = None, keep_versions: int = 10) -> int:
    """
    Clean up old history entries, keeping only the latest N versions per client.
    Also deletes any history entries older than 30 days regardless of version count.
    
    Returns the number of deleted entries.
    """
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        total_deleted = 0
        
        if client_id:
            clients = [client_id]
        else:
            cursor.execute('SELECT DISTINCT client_id FROM data_history')
            clients = [row['client_id'] for row in cursor.fetchall()]
        
        for cid in clients:
            # Delete versions beyond keep_versions limit
            cursor.execute('''
                DELETE FROM data_history 
                WHERE client_id = ? AND version NOT IN (
                    SELECT version FROM data_history 
                    WHERE client_id = ? 
                    ORDER BY version DESC 
                    LIMIT ?
                )
            ''', (cid, cid, keep_versions))
            total_deleted += cursor.rowcount
            
            # Also delete anything older than 30 days
            cursor.execute('''
                DELETE FROM data_history 
                WHERE client_id = ? AND created_at < ?
            ''', (cid, cutoff))
            total_deleted += cursor.rowcount
        
        conn.commit()
        return total_deleted
```

#### `cleanup_audit_log`

```python
def cleanup_audit_log(keep_days: int=30) -> int
```
> Delete audit log entries older than keep_days. Returns count deleted.

**What it does, step by step:**

1. Assigns <code>cutoff</code> = <code>(datetime.now() - timedelta(days=keep_days)).isoformat()</code>.
2. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def cleanup_audit_log(keep_days: int = 30) -> int:
    """Delete audit log entries older than keep_days. Returns count deleted."""
    cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM audit_log WHERE timestamp < ?', (cutoff,))
        deleted = cursor.rowcount
        conn.commit()
        return deleted
```

#### `cleanup_database`

```python
def cleanup_database() -> dict
```
> Master cleanup: prune data_history, audit_log, and expired sessions. Returns a summary dict of rows deleted per table.

**What it does, step by step:**

1. Imports <code>logging</code> (lazy import inside the function).
2. Assigns <code>results</code> = <code>{}</code>.
3. Assigns <code>results['data_history']</code> = <code>cleanup_old_history(keep_versions=10)</code>.
4. Assigns <code>results['audit_log']</code> = <code>cleanup_audit_log(keep_days=30)</code>.
5. Calls <code>cleanup_expired_sessions(...)</code> for its side effect.
6. Assigns <code>results['sessions']</code> = <code>'cleaned'</code>.
7. Assigns <code>total</code> = <code>sum((v for v in results.values() if isinstance(v, int)))</code>.
8. Calls <code>logging.info(...)</code> for its side effect.
9. <b>return</b> <code>results</code>.

```python
def cleanup_database() -> dict:
    """
    Master cleanup: prune data_history, audit_log, and expired sessions.
    Returns a summary dict of rows deleted per table.
    """
    import logging
    results = {}
    
    results['data_history'] = cleanup_old_history(keep_versions=10)
    results['audit_log'] = cleanup_audit_log(keep_days=30)
    cleanup_expired_sessions()
    results['sessions'] = 'cleaned'
    
    total = sum(v for v in results.values() if isinstance(v, int))
    logging.info(f"Database cleanup complete: {results} ({total} rows deleted)")
    return results
```

#### `log_action`

```python
def log_action(action: str, user_type: str, user_identifier: str, ip_address: str=None, details: str=None, success: bool=True)
```
> Log an action to the audit log.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def log_action(action: str, user_type: str, user_identifier: str, 
               ip_address: str = None, details: str = None, success: bool = True):
    """Log an action to the audit log."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO audit_log (timestamp, action, user_type, user_identifier, ip_address, details, success)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            action,
            user_type,
            user_identifier,
            ip_address,
            details,
            1 if success else 0
        ))
        conn.commit()
```

#### `get_audit_log`

```python
def get_audit_log(limit: int=100, action_filter: str=None) -> list
```
> Get recent audit log entries.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def get_audit_log(limit: int = 100, action_filter: str = None) -> list:
    """Get recent audit log entries."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        if action_filter:
            cursor.execute('''
                SELECT * FROM audit_log 
                WHERE action LIKE ? 
                ORDER BY timestamp DESC LIMIT ?
            ''', (f'%{action_filter}%', limit))
        else:
            cursor.execute(
                'SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?',
                (limit,)
            )
        
        return [dict(row) for row in cursor.fetchall()]
```

#### `create_session`

```python
def create_session(user_type: str, user_identifier: str, ip_address: str=None, hours_valid: int=24) -> str
```
> Create a new session token.

**What it does, step by step:**

1. Assigns <code>user_identifier</code> = <code>user_identifier.strip()</code>.
2. Assigns <code>session_token</code> = <code>secrets.token_urlsafe(32)</code>.
3. Assigns <code>now</code> = <code>datetime.now()</code>.
4. Assigns <code>expires</code> = <code>now + timedelta(hours=hours_valid)</code>.
5. <b>with</b> <code>get_connection()</code>: enters a context manager.
6. <b>return</b> <code>session_token</code>.

```python
def create_session(user_type: str, user_identifier: str, ip_address: str = None, 
                   hours_valid: int = 24) -> str:
    """Create a new session token."""
    user_identifier = user_identifier.strip()
    session_token = secrets.token_urlsafe(32)
    now = datetime.now()
    expires = now + timedelta(hours=hours_valid)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO sessions (session_token, user_type, user_identifier, created_at, expires_at, ip_address)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session_token, user_type, user_identifier, now.isoformat(), expires.isoformat(), ip_address))
        conn.commit()
    
    return session_token
```

#### `validate_session`

```python
def validate_session(session_token: str) -> dict
```
> Validate a session token and return user info if valid.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def validate_session(session_token: str) -> dict:
    """Validate a session token and return user info if valid."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_type, user_identifier, expires_at FROM sessions
            WHERE session_token = ?
        ''', (session_token,))
        row = cursor.fetchone()
        
        if row:
            expires = datetime.fromisoformat(row['expires_at'])
            if datetime.now() < expires:
                return {
                    'user_type': row['user_type'],
                    'user_identifier': row['user_identifier']
                }
            else:
                # Session expired, delete it
                cursor.execute('DELETE FROM sessions WHERE session_token = ?', (session_token,))
                conn.commit()
        
        return None
```

#### `delete_session`

```python
def delete_session(session_token: str)
```
> Delete a session (logout).

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def delete_session(session_token: str):
    """Delete a session (logout)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM sessions WHERE session_token = ?', (session_token,))
        conn.commit()
```

#### `delete_all_sessions_for_user`

```python
def delete_all_sessions_for_user(user_type: str, user_identifier: str, *, conn=None, cursor=None) -> int
```
> Remove every session for this principal (all browsers / devices). When conn/cursor are passed, uses that transaction (caller commits).

**What it does, step by step:**

1. Assigns <code>user_type</code> = <code>(user_type or '').strip()</code>.
2. Assigns <code>user_identifier</code> = <code>(user_identifier or '').strip()</code>.
3. <b>if</b> <code>not user_type or not user_identifier</code>: branches conditionally.
4. <b>if</b> <code>cursor is not None</code>: branches conditionally.
5. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def delete_all_sessions_for_user(
    user_type: str,
    user_identifier: str,
    *,
    conn=None,
    cursor=None,
) -> int:
    """
    Remove every session for this principal (all browsers / devices).
    When conn/cursor are passed, uses that transaction (caller commits).
    """
    user_type = (user_type or '').strip()
    user_identifier = (user_identifier or '').strip()
    if not user_type or not user_identifier:
        return 0
    if cursor is not None:
        cursor.execute(
            'DELETE FROM sessions WHERE user_type = ? AND user_identifier = ?',
            (user_type, user_identifier),
        )
        return int(cursor.rowcount or 0)
    with get_connection() as c:
        cur = c.cursor()
        cur.execute(
            'DELETE FROM sessions WHERE user_type = ? AND user_identifier = ?',
            (user_type, user_identifier),
        )
        c.commit()
        return int(cur.rowcount or 0)
```

#### `delete_other_sessions_for_user`

```python
def delete_other_sessions_for_user(user_type: str, user_identifier: str, except_session_token: str) -> int
```
> Remove sessions for this user except the given token (sign out other devices).

**What it does, step by step:**

1. Assigns <code>user_type</code> = <code>(user_type or '').strip()</code>.
2. Assigns <code>user_identifier</code> = <code>(user_identifier or '').strip()</code>.
3. Assigns <code>tok</code> = <code>(except_session_token or '').strip()</code>.
4. <b>if</b> <code>not user_type or not user_identifier or (not tok)</code>: branches conditionally.
5. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def delete_other_sessions_for_user(
    user_type: str,
    user_identifier: str,
    except_session_token: str,
) -> int:
    """Remove sessions for this user except the given token (sign out other devices)."""
    user_type = (user_type or '').strip()
    user_identifier = (user_identifier or '').strip()
    tok = (except_session_token or '').strip()
    if not user_type or not user_identifier or not tok:
        return 0
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''DELETE FROM sessions
               WHERE user_type = ? AND user_identifier = ? AND session_token <> ?''',
            (user_type, user_identifier, tok),
        )
        n = int(cursor.rowcount or 0)
        conn.commit()
        return n
```

#### `list_sessions_public_for_user`

```python
def list_sessions_public_for_user(user_type: str, user_identifier: str, current_session_token: str) -> list
```
> Active sessions for API: tokens are never returned; is_current marks this browser.

**What it does, step by step:**

1. Assigns <code>user_type</code> = <code>(user_type or '').strip()</code>.
2. Assigns <code>user_identifier</code> = <code>(user_identifier or '').strip()</code>.
3. Assigns <code>cur_tok</code> = <code>(current_session_token or '').strip()</code>.
4. <b>if</b> <code>not user_type or not user_identifier</code>: branches conditionally.
5. Assigns <code>now</code> = <code>datetime.now().isoformat()</code>.
6. <b>with</b> <code>get_connection()</code>: enters a context manager.
7. Assigns <code>out</code> = <code>[]</code>.
8. <b>for</b> <code>row</code> in <code>rows</code>: iterates.
9. <b>return</b> <code>out</code>.

```python
def list_sessions_public_for_user(
    user_type: str, user_identifier: str, current_session_token: str
) -> list:
    """Active sessions for API: tokens are never returned; is_current marks this browser."""
    user_type = (user_type or '').strip()
    user_identifier = (user_identifier or '').strip()
    cur_tok = (current_session_token or '').strip()
    if not user_type or not user_identifier:
        return []
    now = datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT session_token, created_at, expires_at, ip_address
               FROM sessions
               WHERE user_type = ? AND user_identifier = ? AND expires_at > ?
               ORDER BY created_at ASC''',
            (user_type, user_identifier, now),
        )
        rows = cursor.fetchall() or []
    out = []
    for row in rows:
        tok = (row['session_token'] or '').strip()
        is_cur = bool(
            cur_tok and tok and len(cur_tok) == len(tok) and secrets.compare_digest(tok, cur_tok)
        )
        out.append({
            'created_at': row['created_at'],
            'expires_at': row['expires_at'],
            'ip_address': row['ip_address'],
            'is_current': is_cur,
        })
    return out
```

#### `cleanup_expired_sessions`

```python
def cleanup_expired_sessions()
```
> Delete all expired sessions.

**What it does, step by step:**

1. <b>with</b> <code>get_connection()</code>: enters a context manager.

```python
def cleanup_expired_sessions():
    """Delete all expired sessions."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'DELETE FROM sessions WHERE expires_at < ?',
            (datetime.now().isoformat(),)
        )
        conn.commit()
```

#### `migrate_from_json`

```python
def migrate_from_json(api_keys_file: str=None, data_file: str=None)
```
> Migrate data from JSON files to SQLite database.

**What it does, step by step:**

1. Assigns <code>base_dir</code> = <code>os.path.dirname(os.path.abspath(__file__))</code>.
2. <b>if</b> <code>api_keys_file is None</code>: branches conditionally.
3. <b>if</b> <code>data_file is None</code>: branches conditionally.
4. Assigns <code>migrated</code> = <code>{'api_keys': 0, 'clients': 0}</code>.
5. <b>if</b> <code>os.path.exists(api_keys_file)</code>: branches conditionally.
6. <b>if</b> <code>os.path.exists(data_file)</code>: branches conditionally.
7. <b>return</b> <code>migrated</code>.

```python
def migrate_from_json(api_keys_file: str = None, data_file: str = None):
    """Migrate data from JSON files to SQLite database."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    if api_keys_file is None:
        api_keys_file = os.path.join(base_dir, 'api_keys.json')
    if data_file is None:
        data_file = os.path.join(base_dir, 'dashboard_data.json')
    
    migrated = {'api_keys': 0, 'clients': 0}
    
    # Migrate API keys (note: we can't migrate the actual keys, only the metadata)
    if os.path.exists(api_keys_file):
        try:
            with open(api_keys_file, 'r') as f:
                old_keys = json.load(f)
            
            print(f"Found {len(old_keys)} API keys to migrate")
            print("NOTE: Existing API keys cannot be migrated (they were stored in plain text)")
            print("You will need to generate new API keys for each trader")
            migrated['api_keys'] = len(old_keys)
        except Exception as e:
            print(f"Error reading API keys file: {e}")
    
    # Migrate client data
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r') as f:
                data = json.load(f)
            
            clients_db = data.get('clients_db', {})
            for client_id, client_data in clients_db.items():
                save_client_data(client_id, client_data)
                migrated['clients'] += 1
            
            print(f"Migrated {migrated['clients']} clients")
        except Exception as e:
            print(f"Error migrating client data: {e}")
    
    return migrated
```

---

### `dashboard/db.py`

_44 loc · 0 classes · 1 functions · 4 imports_

**Module docstring**

> SQLAlchemy engine + session factory.
> Reads DATABASE_URL from environment (or .env file). Falls back to SQLite for legacy compatibility.
> Set in .env:     DATABASE_URL=postgresql://postgres:password@localhost:5432/tradeopss

**Imports**

```python
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
```

**Module constants**

```python
DATABASE_URL = os.environ.get('DATABASE_URL', f"sqlite:///{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.db')}")
```
_Equivalent to `os.getenv`: reads `DATABASE_URL` from the environment, default `f"sqlite:///{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.db')}"`._

**Functions**

#### `get_session`

```python
def get_session()
```
> Dependency-style session: use as context manager.

**What it does, step by step:**

1. Assigns <code>session</code> = <code>SessionLocal()</code>.
2. <b>try</b> block with 1 <b>except</b> clause, plus a <b>finally</b>.

```python
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
```

---

### `dashboard/models.py`

_330 loc · 18 classes · 0 functions · 3 imports_

**Module docstring**

> SQLAlchemy ORM Models — mirrors the existing SQLite schema exactly. Target: PostgreSQL (local dev first, then production).
> Usage:     from dashboard.models import Base, ClientsData, UserCredentials, ...     from dashboard.db import engine, SessionLocal
> Note: server_default is used everywhere so that raw SQL INSERTs       (which bypass the ORM) still get correct column defaults.

**Imports**

```python
from datetime import datetime
from sqlalchemy import BigInteger, Column, Float, ForeignKey, Index, Integer, SmallInteger, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import DeclarativeBase, relationship
```

**Classes**

#### `class Base(DeclarativeBase)`

```python
class Base(DeclarativeBase):
    pass
```

#### `class ApiKey(Base)`

```python
__tablename__ = 'api_keys'
id = Column(Integer, primary_key=True, autoincrement=True)
key_hash = Column(Text, unique=True, nullable=False)
key_prefix = Column(Text, nullable=False)
admin = Column(Text, nullable=False)
trader = Column(Text, nullable=False)
client = Column(Text, server_default=text("''"))
scope = Column(Text, server_default=text("'full'"))
created_at = Column(Text, nullable=False)
last_used = Column(Text)
is_active = Column(SmallInteger, server_default=text('1'))
```

```python
class ApiKey(Base):
    __tablename__ = 'api_keys'

    id         = Column(Integer, primary_key=True, autoincrement=True)
    key_hash   = Column(Text, unique=True, nullable=False)
    key_prefix = Column(Text, nullable=False)
    admin      = Column(Text, nullable=False)
    trader     = Column(Text, nullable=False)
    client     = Column(Text, server_default=text("''"))
    scope      = Column(Text, server_default=text("'full'"))
    created_at = Column(Text, nullable=False)
    last_used  = Column(Text)
    is_active  = Column(SmallInteger, server_default=text("1"))
```

#### `class AdminPassword(Base)`

```python
__tablename__ = 'admin_passwords'
id = Column(Integer, primary_key=True, autoincrement=True)
username = Column(Text, unique=True, nullable=False)
password_hash = Column(Text, nullable=False)
salt = Column(Text, nullable=False)
created_at = Column(Text, nullable=False)
updated_at = Column(Text)
```

```python
class AdminPassword(Base):
    __tablename__ = 'admin_passwords'

    id            = Column(Integer, primary_key=True, autoincrement=True)
    username      = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    salt          = Column(Text, nullable=False)
    created_at    = Column(Text, nullable=False)
    updated_at    = Column(Text)
```

#### `class UserCredential(Base)`

```python
__tablename__ = 'user_credentials'
__table_args__ = (UniqueConstraint('username', 'user_type', name='uq_user_credentials_username_type'),)
id = Column(Integer, primary_key=True, autoincrement=True)
username = Column(Text, nullable=False)
email = Column(Text)
password_hash = Column(Text, nullable=False)
salt = Column(Text, nullable=False)
user_type = Column(Text, nullable=False)
parent_admin = Column(Text)
parent_trader = Column(Text)
is_active = Column(SmallInteger, server_default=text('1'))
must_change_password = Column(SmallInteger, server_default=text('1'))
last_login = Column(Text)
created_at = Column(Text, nullable=False)
updated_at = Column(Text)
```

```python
class UserCredential(Base):
    __tablename__ = 'user_credentials'
    __table_args__ = (
        UniqueConstraint('username', 'user_type', name='uq_user_credentials_username_type'),
    )

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    username             = Column(Text, nullable=False)
    email                = Column(Text)
    password_hash        = Column(Text, nullable=False)
    salt                 = Column(Text, nullable=False)
    user_type            = Column(Text, nullable=False)
    parent_admin         = Column(Text)
    parent_trader        = Column(Text)
    is_active            = Column(SmallInteger, server_default=text("1"))
    must_change_password = Column(SmallInteger, server_default=text("1"))
    last_login           = Column(Text)
    created_at           = Column(Text, nullable=False)
    updated_at           = Column(Text)
```

#### `class ClientsData(Base)`

```python
__tablename__ = 'clients_data'
id = Column(Integer, primary_key=True, autoincrement=True)
client_id = Column(Text, unique=True, nullable=False)
deals = Column(Text, server_default=text("'[]'"))
positions = Column(Text, server_default=text("'[]'"))
account = Column(Text, server_default=text("'{}'"))
evaluations = Column(Text, server_default=text("'[]'"))
statistics = Column(Text, server_default=text("'{}'"))
dropdown_options = Column(Text, server_default=text("'{}'"))
identity = Column(Text, server_default=text("'{}'"))
last_updated = Column(Text, nullable=False)
hedge_accounts = Column(Text, server_default=text("'[]'"))
prop_accounts = Column(Text, server_default=text("'[]'"))
vps_accounts = Column(Text, server_default=text("'[]'"))
payment_info = Column(Text, server_default=text("'[]'"))
payment_address = Column(Text, server_default=text("'{}'"))
```

```python
class ClientsData(Base):
    __tablename__ = 'clients_data'

    id               = Column(Integer, primary_key=True, autoincrement=True)
    client_id        = Column(Text, unique=True, nullable=False)
    deals            = Column(Text, server_default=text("'[]'"))
    positions        = Column(Text, server_default=text("'[]'"))
    account          = Column(Text, server_default=text("'{}'"))
    evaluations      = Column(Text, server_default=text("'[]'"))
    statistics       = Column(Text, server_default=text("'{}'"))
    dropdown_options = Column(Text, server_default=text("'{}'"))
    identity         = Column(Text, server_default=text("'{}'"))
    last_updated     = Column(Text, nullable=False)
    hedge_accounts   = Column(Text, server_default=text("'[]'"))
    prop_accounts    = Column(Text, server_default=text("'[]'"))
    vps_accounts     = Column(Text, server_default=text("'[]'"))
    payment_info     = Column(Text, server_default=text("'[]'"))
    payment_address  = Column(Text, server_default=text("'{}'"))
```

#### `class AuditLog(Base)`

```python
__tablename__ = 'audit_log'
id = Column(Integer, primary_key=True, autoincrement=True)
timestamp = Column(Text, nullable=False)
action = Column(Text, nullable=False)
user_type = Column(Text, nullable=False)
user_identifier = Column(Text, nullable=False)
ip_address = Column(Text)
details = Column(Text)
success = Column(SmallInteger, server_default=text('1'))
```

```python
class AuditLog(Base):
    __tablename__ = 'audit_log'

    id              = Column(Integer, primary_key=True, autoincrement=True)
    timestamp       = Column(Text, nullable=False)
    action          = Column(Text, nullable=False)
    user_type       = Column(Text, nullable=False)
    user_identifier = Column(Text, nullable=False)
    ip_address      = Column(Text)
    details         = Column(Text)
    success         = Column(SmallInteger, server_default=text("1"))
```

#### `class DataHistory(Base)`

```python
__tablename__ = 'data_history'
__table_args__ = (UniqueConstraint('client_id', 'version', name='uq_data_history_client_version'), Index('idx_data...
id = Column(Integer, primary_key=True, autoincrement=True)
client_id = Column(Text, nullable=False)
version = Column(Integer, nullable=False)
action = Column(Text, nullable=False)
changed_by = Column(Text)
changed_by_type = Column(Text)
ip_address = Column(Text)
change_source = Column(Text)
change_description = Column(Text)
deals = Column(Text, server_default=text("'[]'"))
positions = Column(Text, server_default=text("'[]'"))
account = Column(Text, server_default=text("'{}'"))
evaluations = Column(Text, server_default=text("'[]'"))
statistics = Column(Text, server_default=text("'{}'"))
dropdown_options = Column(Text, server_default=text("'{}'"))
identity = Column(Text, server_default=text("'{}'"))
created_at = Column(Text, nullable=False)
```

```python
class DataHistory(Base):
    __tablename__ = 'data_history'
    __table_args__ = (
        UniqueConstraint('client_id', 'version', name='uq_data_history_client_version'),
        Index('idx_data_history_client', 'client_id', 'version'),
    )

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    client_id          = Column(Text, nullable=False)
    version            = Column(Integer, nullable=False)
    action             = Column(Text, nullable=False)
    changed_by         = Column(Text)
    changed_by_type    = Column(Text)
    ip_address         = Column(Text)
    change_source      = Column(Text)
    change_description = Column(Text)
    deals              = Column(Text, server_default=text("'[]'"))
    positions          = Column(Text, server_default=text("'[]'"))
    account            = Column(Text, server_default=text("'{}'"))
    evaluations        = Column(Text, server_default=text("'[]'"))
    statistics         = Column(Text, server_default=text("'{}'"))
    dropdown_options   = Column(Text, server_default=text("'{}'"))
    identity           = Column(Text, server_default=text("'{}'"))
    created_at         = Column(Text, nullable=False)
```

#### `class Session(Base)`

```python
__tablename__ = 'sessions'
id = Column(Integer, primary_key=True, autoincrement=True)
session_token = Column(Text, unique=True, nullable=False)
user_type = Column(Text, nullable=False)
user_identifier = Column(Text, nullable=False)
created_at = Column(Text, nullable=False)
expires_at = Column(Text, nullable=False)
ip_address = Column(Text)
```

```python
class Session(Base):
    __tablename__ = 'sessions'

    id              = Column(Integer, primary_key=True, autoincrement=True)
    session_token   = Column(Text, unique=True, nullable=False)
    user_type       = Column(Text, nullable=False)
    user_identifier = Column(Text, nullable=False)
    created_at      = Column(Text, nullable=False)
    expires_at      = Column(Text, nullable=False)
    ip_address      = Column(Text)
```

#### `class CellNote(Base)`

```python
__tablename__ = 'cell_notes'
__table_args__ = (UniqueConstraint('client_id', 'row_index', 'column_key', name='uq_cell_notes'),)
id = Column(Integer, primary_key=True, autoincrement=True)
client_id = Column(Text, nullable=False)
row_index = Column(Integer, nullable=False)
column_key = Column(Text, nullable=False)
note_content = Column(Text)
created_by = Column(Text)
updated_at = Column(Text)
```

```python
class CellNote(Base):
    __tablename__ = 'cell_notes'
    __table_args__ = (
        UniqueConstraint('client_id', 'row_index', 'column_key', name='uq_cell_notes'),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    client_id    = Column(Text, nullable=False)
    row_index    = Column(Integer, nullable=False)
    column_key   = Column(Text, nullable=False)
    note_content = Column(Text)
    created_by   = Column(Text)
    updated_at   = Column(Text)
```

#### `class DailyWatermark(Base)`

```python
__tablename__ = 'daily_watermarks'
client_id = Column(Text, primary_key=True, nullable=False)
date = Column(Text, primary_key=True, nullable=False)
net_profit_complete = Column(Float, server_default=text('0.0'))
source = Column(Text, server_default=text("'auto'"))
created_at = Column(Text, server_default=func.now())
```

```python
class DailyWatermark(Base):
    __tablename__ = 'daily_watermarks'

    client_id           = Column(Text, primary_key=True, nullable=False)
    date                = Column(Text, primary_key=True, nullable=False)
    net_profit_complete = Column(Float, server_default=text("0.0"))
    source              = Column(Text, server_default=text("'auto'"))
    created_at          = Column(Text, server_default=func.now())
```

#### `class WaterlogPeriod(Base)`

```python
__tablename__ = 'waterlog_periods'
client_id = Column(Text, primary_key=True, nullable=False)
from_date = Column(Text, primary_key=True, nullable=False)
to_date = Column(Text, nullable=False)
period_low = Column(Float)
period_high = Column(Float)
split_pct = Column(Integer, server_default=text('50'))
```

```python
class WaterlogPeriod(Base):
    __tablename__ = 'waterlog_periods'

    client_id   = Column(Text, primary_key=True, nullable=False)
    from_date   = Column(Text, primary_key=True, nullable=False)
    to_date     = Column(Text, nullable=False)
    period_low  = Column(Float)
    period_high = Column(Float)
    split_pct   = Column(Integer, server_default=text("50"))
```

#### `class LoginAttempt(Base)`

```python
__tablename__ = 'login_attempts'
id = Column(Integer, primary_key=True, autoincrement=True)
username = Column(Text, nullable=False)
user_type = Column(Text, nullable=False)
ip_address = Column(Text)
attempt_time = Column(Text, nullable=False)
success = Column(SmallInteger, server_default=text('0'))
```

```python
class LoginAttempt(Base):
    __tablename__ = 'login_attempts'

    id           = Column(Integer, primary_key=True, autoincrement=True)
    username     = Column(Text, nullable=False)
    user_type    = Column(Text, nullable=False)
    ip_address   = Column(Text)
    attempt_time = Column(Text, nullable=False)
    success      = Column(SmallInteger, server_default=text("0"))
```

#### `class Evaluation(Base)`

```python
__tablename__ = 'evaluations'
id = Column(Integer, primary_key=True, autoincrement=True)
account_signature = Column(Text, nullable=False)
phase_number = Column(Integer, nullable=False)
phase_type = Column(Text, nullable=False)
status = Column(Text, server_default=text("'pending'"))
start_date = Column(Text)
end_date = Column(Text)
reset_id = Column(Text)
parent_id = Column(Integer, ForeignKey('evaluations.id'))
meta_data = Column(Text, server_default=text("'{}'"))
created_at = Column(Text, server_default=func.now())
children = relationship('Evaluation', backref='parent', remote_side=[id])
```

```python
class Evaluation(Base):
    __tablename__ = 'evaluations'

    id                = Column(Integer, primary_key=True, autoincrement=True)
    account_signature = Column(Text, nullable=False)
    phase_number      = Column(Integer, nullable=False)
    phase_type        = Column(Text, nullable=False)
    status            = Column(Text, server_default=text("'pending'"))
    start_date        = Column(Text)
    end_date          = Column(Text)
    reset_id          = Column(Text)
    parent_id         = Column(Integer, ForeignKey('evaluations.id'))
    meta_data         = Column(Text, server_default=text("'{}'"))
    created_at        = Column(Text, server_default=func.now())

    children = relationship('Evaluation', backref='parent', remote_side=[id])
```

#### `class PhaseDefinition(Base)`

```python
__tablename__ = 'phase_definitions'
id = Column(Integer, primary_key=True, autoincrement=True)
phase_name = Column(Text, nullable=False)
phase_code = Column(Text, unique=True, nullable=False)
sequence_order = Column(Integer, nullable=False)
ruleset = Column(Text, server_default=text("'{}'"))
next_phase_code = Column(Text)
```

```python
class PhaseDefinition(Base):
    __tablename__ = 'phase_definitions'

    id             = Column(Integer, primary_key=True, autoincrement=True)
    phase_name     = Column(Text, nullable=False)
    phase_code     = Column(Text, unique=True, nullable=False)
    sequence_order = Column(Integer, nullable=False)
    ruleset        = Column(Text, server_default=text("'{}'"))
    next_phase_code = Column(Text)
```

#### `class KycLink(Base)`

```python
__tablename__ = 'kyc_links'
__table_args__ = (UniqueConstraint('primary_client', 'linked_client', name='uq_kyc_links'), Index('idx_kyc_primary...
id = Column(Integer, primary_key=True, autoincrement=True)
primary_client = Column(Text, nullable=False)
linked_client = Column(Text, nullable=False)
linked_by = Column(Text, server_default=text("'super_admin'"))
created_at = Column(Text, server_default=func.now())
```

```python
class KycLink(Base):
    __tablename__ = 'kyc_links'
    __table_args__ = (
        UniqueConstraint('primary_client', 'linked_client', name='uq_kyc_links'),
        Index('idx_kyc_primary', 'primary_client'),
        Index('idx_kyc_linked', 'linked_client'),
    )

    id             = Column(Integer, primary_key=True, autoincrement=True)
    primary_client = Column(Text, nullable=False)
    linked_client  = Column(Text, nullable=False)
    linked_by      = Column(Text, server_default=text("'super_admin'"))
    created_at     = Column(Text, server_default=func.now())
```

#### `class QualityScanResult(Base)`

```python
__tablename__ = 'quality_scan_results'
__table_args__ = (Index('idx_quality_scan_date', 'scan_date', 'client_id'),)
id = Column(Integer, primary_key=True, autoincrement=True)
scan_date = Column(Text, nullable=False)
client_id = Column(Text, nullable=False)
trader = Column(Text)
admin = Column(Text)
total_issues = Column(Integer, server_default=text('0'))
issues = Column(Text, server_default=text("'[]'"))
health_score = Column(Float, server_default=text('100.0'))
created_at = Column(Text, server_default=func.now())
```

```python
class QualityScanResult(Base):
    __tablename__ = 'quality_scan_results'
    __table_args__ = (
        Index('idx_quality_scan_date', 'scan_date', 'client_id'),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    scan_date    = Column(Text, nullable=False)
    client_id    = Column(Text, nullable=False)
    trader       = Column(Text)
    admin        = Column(Text)
    total_issues = Column(Integer, server_default=text("0"))
    issues       = Column(Text, server_default=text("'[]'"))
    health_score = Column(Float, server_default=text("100.0"))
    created_at   = Column(Text, server_default=func.now())
```

#### `class DailyChecklist(Base)`

```python
__tablename__ = 'daily_checklists'
__table_args__ = (UniqueConstraint('date', 'user_identifier', 'checklist_type', 'client_id', name='uq_daily_checkl...
id = Column(Integer, primary_key=True, autoincrement=True)
date = Column(Text, nullable=False)
user_identifier = Column(Text, nullable=False)
user_type = Column(Text, nullable=False)
checklist_type = Column(Text, nullable=False)
client_id = Column(Text, server_default=text("''"))
items = Column(Text, server_default=text("'[]'"))
submitted_at = Column(Text, nullable=False)
ip_address = Column(Text)
```

```python
class DailyChecklist(Base):
    __tablename__ = 'daily_checklists'
    __table_args__ = (
        UniqueConstraint('date', 'user_identifier', 'checklist_type', 'client_id',
                         name='uq_daily_checklists'),
        Index('idx_checklist_date', 'date', 'user_identifier'),
        Index('idx_checklist_client', 'date', 'client_id'),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    date            = Column(Text, nullable=False)
    user_identifier = Column(Text, nullable=False)
    user_type       = Column(Text, nullable=False)
    checklist_type  = Column(Text, nullable=False)
    client_id       = Column(Text, server_default=text("''"))
    items           = Column(Text, server_default=text("'[]'"))
    submitted_at    = Column(Text, nullable=False)
    ip_address      = Column(Text)
```

#### `class SystemSetting(Base)`

```python
__tablename__ = 'system_settings'
key = Column(Text, primary_key=True)
value = Column(Text, nullable=False)
updated_at = Column(Text, nullable=False)
updated_by = Column(Text, server_default=text("''"))
```

```python
class SystemSetting(Base):
    __tablename__ = 'system_settings'

    key        = Column(Text, primary_key=True)
    value      = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)
    updated_by = Column(Text, server_default=text("''"))
```

---
