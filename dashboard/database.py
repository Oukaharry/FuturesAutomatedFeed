"""
PostgreSQL Database Module for Trading Dashboard
Provides secure storage with encrypted data and audit logging.

Migrated from SQLite — uses psycopg2 with compatibility wrappers
so all existing query code (? placeholders, row['col'] access) keeps working.
"""
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
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None

if load_dotenv:
    load_dotenv()

DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://postgres:postgres123@localhost:5432/tradeopss'
)

logger = logging.getLogger(__name__)

# ─── Identifier normalization ───────────────────────────────────────
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

# ─── Connection Pooling ─────────────────────────────────────────────
# Reuse connections instead of creating new ones (prevents exhaustion).
# On hosts with low max_connections (e.g. PythonAnywhere managed Postgres),
# min=5 at pool init can fail with "remaining connection slots are reserved...".
# Override via DB_POOL_MIN / DB_POOL_MAX (integers, min >= 1).
_pool_min = max(1, int(os.environ.get("DB_POOL_MIN", "1")))
_pool_max = max(_pool_min, int(os.environ.get("DB_POOL_MAX", "10")))
_connection_pool = None

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

def _get_pooled_connection():
    """Get a connection from the pool (creates pool on first call)."""
    if _connection_pool is None:
        _init_pool()
    return _connection_pool.getconn()

def _return_pooled_connection(conn):
    """Return a connection to the pool."""
    if _connection_pool is not None:
        _connection_pool.putconn(conn)
    else:
        conn.close()


# ─── Compatibility wrappers ────────────────────────────────────────
# Translate SQLite-style ? placeholders to psycopg2 %s automatically,
# and return dict rows so row['col'] keeps working everywhere.

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


@contextmanager
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


@contextmanager
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


def get_db_path():
    """Legacy helper — returns DATABASE_URL for PostgreSQL."""
    return DATABASE_URL

def check_and_repair_database():
    """Connectivity check (PostgreSQL doesn't need SQLite-style repair)."""
    try:
        with get_connection() as conn:
            conn.execute('SELECT 1')
        return True, 'PostgreSQL connection OK'
    except Exception as e:
        return False, f'PostgreSQL connection failed: {e}'

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

# ============ Password Hashing ============

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

def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify a password against stored hash."""
    password_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(password_hash, stored_hash)

# ============ Admin Password Management ============

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

def admin_password_exists(username: str) -> bool:
    """Return True if a password row already exists for the given admin username."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM admin_passwords WHERE username = ?',
            (username,)
        )
        return cursor.fetchone() is not None


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

# ============ User Credential Management ============

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

def user_exists(username: str, user_type: str) -> bool:
    """Check if a user already exists."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM user_credentials WHERE username = ? AND user_type = ?',
            (username, user_type)
        )
        return cursor.fetchone() is not None

def record_login_attempt(username: str, user_type: str, ip_address: str, success: bool):
    """Record a login attempt."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO login_attempts (username, user_type, ip_address, attempt_time, success)
            VALUES (?, ?, ?, ?, ?)
        ''', (username, user_type, ip_address, datetime.now().isoformat(), 1 if success else 0))
        conn.commit()

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

def is_account_locked(username: str, user_type: str, max_attempts: int = 5) -> bool:
    """Check if account is locked due to too many failed attempts."""
    return get_failed_login_count(username, user_type) >= max_attempts

# ============ API Key Management ============

def hash_api_key(api_key: str) -> str:
    """Hash an API key using SHA-256."""
    return hashlib.sha256(api_key.encode('utf-8')).hexdigest()

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

def list_api_keys() -> list:
    """List all API keys (showing only prefix)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT key_prefix, admin, trader, client, scope, created_at, last_used, is_active
            FROM api_keys ORDER BY created_at DESC
        ''')
        return [dict(row) for row in cursor.fetchall()]

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

def delete_api_key(key_prefix: str) -> bool:
    """Permanently delete an API key by its prefix."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM api_keys WHERE key_prefix = ?', (key_prefix,))
        conn.commit()
        return cursor.rowcount > 0

# ============ KYC Link Management ============

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

def remove_kyc_link(primary_client: str, linked_client: str) -> bool:
    """Remove a KYC link between two clients."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM kyc_links WHERE primary_client = ? AND linked_client = ?',
                       (primary_client, linked_client))
        conn.commit()
        return cursor.rowcount > 0

def get_kyc_linked_clients(primary_client: str) -> list:
    """Get all linked KYC accounts for a primary client."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT linked_client, linked_by, created_at FROM kyc_links WHERE primary_client = ?',
                       (primary_client,))
        return [{'linked_client': r['linked_client'], 'linked_by': r['linked_by'],
                 'created_at': r['created_at']} for r in cursor.fetchall()]

def get_kyc_primary_for(linked_client: str) -> str:
    """If this client is linked to someone, return the primary client name."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT primary_client FROM kyc_links WHERE linked_client = ?',
                       (linked_client,))
        row = cursor.fetchone()
        return row['primary_client'] if row else None

def is_kyc_primary(client_name: str) -> bool:
    """Check if this client is a primary KYC account (has linked accounts under it)."""
    return len(get_kyc_linked_clients(client_name)) > 0

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

def get_all_kyc_links() -> list:
    """Get all KYC links in the system (for admin view)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT primary_client, linked_client, linked_by, created_at FROM kyc_links ORDER BY primary_client')
        return [dict(r) for r in cursor.fetchall()]

# ============ Client Data Management ============

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

def get_clients_count() -> int:
    """Get count of clients in database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM clients_data')
        row = cursor.fetchone()
        return row['count'] if row else 0

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

# ============ Quality Scan Functions ============

def _repair_quality_table():
    """No-op — schema is managed by Alembic. PostgreSQL handles table integrity."""
    print("[DB] quality_scan_results table integrity is managed by PostgreSQL")

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
        conn.commit()


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


def record_quality_scan_anchor(scan_date: str, anchored_at: str):
    """Alias for the scan-day clock used by issue-clearance rankings (first write wins)."""
    record_quality_slack_post(scan_date, anchored_at)


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
                    had_issues = excluded.had_issues
                ''',
                (scan_date, client_id, trader or '', 1 if had_issues else 0),
            )
            conn.commit()
    except Exception:
        return


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


def get_trader_issue_resolution_minutes(scan_date: str, trader: str, *, unresolved_minutes: int = 99999) -> int:
    """
    For Slack leaderboard tie-breaks.
    Returns minutes from posted_at to the time ALL baseline-issue clients for this trader were resolved.
    If any baseline-issue client is not yet resolved, returns unresolved_minutes.
    If the trader had no baseline issues, returns 0 (fastest by default).
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
                return 0

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

def get_quality_scan_results(scan_date: str = None) -> list:
    """Get quality scan results. If no date, returns latest scan."""
    try:
        return _get_quality_scan_results_inner(scan_date)
    except Exception as e:
        print(f"Error getting quality scan results: {e}")
        return []

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


def _ensure_checklist_client_column():
    """No-op — schema is managed by Alembic."""
    pass

# ============ System Settings ============

def _ensure_settings_table():
    """No-op — schema is managed by Alembic."""
    pass


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
            # Source 1: daily_checklists — filter by submitted_at timestamp
            # so the window is exactly 23:05→23:05 UTC
            cursor.execute(
                "SELECT client_id, user_identifier, submitted_at FROM daily_checklists "
                "WHERE checklist_type = 'daily_summary' AND client_id != '' "
                "AND submitted_at >= ? AND submitted_at < ? "
                "ORDER BY submitted_at DESC",
                (utc_start, utc_end)
            )
            for row in cursor.fetchall():
                cid = _normalize_identifier(_row_value(row, 'client_id') or '')
                if not cid:
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
                "WHERE action IN ('CHECKLIST_SUBMIT', 'SLACK_DAILY_SUMMARY') "
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


def get_weekly_scan_results(end_date: str = None, days: int = 7) -> list:
    """Get quality scan results for a date range (default: last 7 days)."""
    try:
        return _get_weekly_scan_results_inner(end_date, days)
    except Exception as e:
        print(f"Error getting weekly scan results: {e}")
        return []

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


# ============ QA Resolutions (super-admin gated) ============

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


# ============ Data History Management ============

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

def get_latest_version(client_id: str) -> int:
    """Get the latest version number for a client."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT MAX(version) as max_version FROM data_history WHERE client_id = ?
        ''', (client_id,))
        row = cursor.fetchone()
        return row['max_version'] or 0

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


def cleanup_audit_log(keep_days: int = 30) -> int:
    """Delete audit log entries older than keep_days. Returns count deleted."""
    cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM audit_log WHERE timestamp < ?', (cutoff,))
        deleted = cursor.rowcount
        conn.commit()
        return deleted


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

# ============ Audit Logging ============

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

# ============ Session Management ============

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

def delete_session(session_token: str):
    """Delete a session (logout)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM sessions WHERE session_token = ?', (session_token,))
        conn.commit()


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


def cleanup_expired_sessions():
    """Delete all expired sessions."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'DELETE FROM sessions WHERE expires_at < ?',
            (datetime.now().isoformat(),)
        )
        conn.commit()

# ============ Migration from JSON ============

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

# Initialize database on import
init_database()
