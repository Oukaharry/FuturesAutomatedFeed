"""
SQLite Database Module for Trading Dashboard
Provides secure storage with encrypted data and audit logging
"""
import sqlite3
import json
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from contextlib import contextmanager

# Database file path
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.db')

def get_db_path():
    return DB_PATH

@contextmanager
def get_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_database():
    """Initialize the database with required tables."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # API Keys table - stores hashed keys
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT UNIQUE NOT NULL,
                key_prefix TEXT NOT NULL,
                admin TEXT NOT NULL,
                trader TEXT NOT NULL,
                client TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                last_used TEXT,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        # Admin passwords table - stores hashed passwords (for super_admin)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_passwords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        ''')
        
        # User credentials table - for admins, traders, and clients
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                email TEXT,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                user_type TEXT NOT NULL,
                parent_admin TEXT,
                parent_trader TEXT,
                is_active INTEGER DEFAULT 1,
                must_change_password INTEGER DEFAULT 1,
                last_login TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                UNIQUE(username, user_type)
            )
        ''')
        
        # Clients data table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS clients_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT UNIQUE NOT NULL,
                deals TEXT DEFAULT '[]',
                positions TEXT DEFAULT '[]',
                account TEXT DEFAULT '{}',
                evaluations TEXT DEFAULT '[]',
                statistics TEXT DEFAULT '{}',
                dropdown_options TEXT DEFAULT '{}',
                identity TEXT DEFAULT '{}',
                last_updated TEXT NOT NULL
            )
        ''')
        
        # Audit log table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                user_type TEXT NOT NULL,
                user_identifier TEXT NOT NULL,
                ip_address TEXT,
                details TEXT,
                success INTEGER DEFAULT 1
            )
        ''')
        
        # Data history table - stores all versions of client data for rollback
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS data_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                action TEXT NOT NULL,
                changed_by TEXT,
                changed_by_type TEXT,
                ip_address TEXT,
                change_source TEXT,
                change_description TEXT,
                deals TEXT DEFAULT '[]',
                positions TEXT DEFAULT '[]',
                account TEXT DEFAULT '{}',
                evaluations TEXT DEFAULT '[]',
                statistics TEXT DEFAULT '{}',
                dropdown_options TEXT DEFAULT '{}',
                identity TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(client_id, version)
            )
        ''')
        
        # Create index for faster history lookups
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_data_history_client 
            ON data_history(client_id, version DESC)
        ''')
        
        # Sessions table for web login
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_token TEXT UNIQUE NOT NULL,
                user_type TEXT NOT NULL,
                user_identifier TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                ip_address TEXT
            )
        ''')
        
        # Cell Notes table (For client evaluations)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cell_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL,
                row_index INTEGER NOT NULL,
                column_key TEXT NOT NULL,
                note_content TEXT,
                created_by TEXT,
                updated_at TEXT,
                UNIQUE(client_id, row_index, column_key)
            )
        ''')
        
        # Daily Watermarks table - stores daily snapshots of Net Profit Complete
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_watermarks (
                client_id TEXT NOT NULL,
                date TEXT NOT NULL,
                net_profit_complete REAL DEFAULT 0.0,
                source TEXT DEFAULT 'auto',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (client_id, date)
            )
        ''')

        # Failed login attempts table (for lockout)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                user_type TEXT NOT NULL,
                ip_address TEXT,
                attempt_time TEXT NOT NULL,
                success INTEGER DEFAULT 0
            )
        ''')

        # Seeding Default Admins if missing
        # Check Super Admin
        cursor.execute("SELECT 1 FROM admin_passwords WHERE username = 'super_admin'")
        if not cursor.fetchone():
            # Default password 'ballerquotes' (should represent secure config)
            # In production this should be changed immediately
            pw_hash, salt = hash_password('ballerquotes') 
            now = datetime.now().isoformat()
            cursor.execute("INSERT INTO admin_passwords (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)", 
                          ('super_admin', pw_hash, salt, now))
            print("✅ Created default super_admin account")
            
        # Check BEF Admin
        cursor.execute("SELECT 1 FROM admin_passwords WHERE username = 'bef_admin'")
        if not cursor.fetchone():
            pw_hash, salt = hash_password('bef_admin_123') 
            now = datetime.now().isoformat()
            cursor.execute("INSERT INTO admin_passwords (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)", 
                          ('bef_admin', pw_hash, salt, now))
            print("✅ Created default bef_admin account")
            
        conn.commit()

        # Evaluations table (New Dynamic Phase Architecture)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_signature TEXT NOT NULL,
                phase_number INTEGER NOT NULL,
                phase_type TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                start_date TEXT,
                end_date TEXT,
                reset_id TEXT,
                parent_id INTEGER,
                meta_data TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(parent_id) REFERENCES evaluations(id)
            )
        ''')

        # Phase Definitions table (Dynamic Rules)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS phase_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phase_name TEXT NOT NULL,
                phase_code TEXT NOT NULL UNIQUE,
                sequence_order INTEGER NOT NULL,
                ruleset TEXT DEFAULT '{}',
                next_phase_code TEXT
            )
        ''')
        
        # Seeding Default Admins if missing (MUST BE AFTER hash_password is defined, but init_database calls run later)
        # Actually this works because init_database() is called at end of file.
        
        # Check Super Admin
        cursor.execute("SELECT 1 FROM admin_passwords WHERE username = 'super_admin'")
        if not cursor.fetchone():
            # Default password 'ballerquotes' (should represent secure config)
            # In production this should be changed immediately
            # Use local import or definition if not available
            try:
                pw_hash, salt = hash_password('ballerquotes') 
                now = datetime.now().isoformat()
                cursor.execute("INSERT INTO admin_passwords (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)", 
                              ('super_admin', pw_hash, salt, now))
                print("✅ Created default super_admin account")
            except NameError:
                # If hash_password not defined yet (circular/scope), skip
                print("⚠️ Skipping default admin creation (hash_password not ready)")
                
        # Check BEF Admin
        cursor.execute("SELECT 1 FROM admin_passwords WHERE username = 'bef_admin'")
        if not cursor.fetchone():
            try:
                pw_hash, salt = hash_password('bef_admin_123') 
                now = datetime.now().isoformat()
                cursor.execute("INSERT INTO admin_passwords (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)", 
                              ('bef_admin', pw_hash, salt, now))
                print("✅ Created default bef_admin account")
            except NameError:
                pass
            
        conn.commit()
        print("Database initialized successfully")

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
    """Set or update admin password."""
    password_hash, salt = hash_password(password)
    now = datetime.now().isoformat()
    
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
            conn.commit()
            return True
        except Exception as e:
            print(f"Error setting admin password: {e}")
            return False

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
        except sqlite3.IntegrityError:
            # User already exists
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
    """Update a user's password."""
    password_hash, salt = hash_password(new_password)
    now = datetime.now().isoformat()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE user_credentials 
            SET password_hash = ?, salt = ?, must_change_password = 0, updated_at = ?
            WHERE username = ? AND user_type = ?
        ''', (password_hash, salt, now, username, user_type))
        conn.commit()
        return cursor.rowcount > 0

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
    """Deactivate a user account."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE user_credentials SET is_active = 0, updated_at = ?
            WHERE username = ? AND user_type = ?
        ''', (datetime.now().isoformat(), username, user_type))
        conn.commit()
        return cursor.rowcount > 0

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

def reset_user_password(username: str, user_type: str) -> str:
    """Reset user password to a random temporary password."""
    temp_password = secrets.token_urlsafe(12)
    password_hash, salt = hash_password(temp_password)
    now = datetime.now().isoformat()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE user_credentials 
            SET password_hash = ?, salt = ?, must_change_password = 1, updated_at = ?
            WHERE username = ? AND user_type = ?
        ''', (password_hash, salt, now, username, user_type))
        conn.commit()
        
        if cursor.rowcount > 0:
            return temp_password
        return None

def find_user_by_identifier(identifier: str) -> dict:
    """
    Find a user by email or username across all user types.
    Returns user info including user_type if found.
    Also checks if identifier matches super_admin.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Check if it's super_admin or special admin in admin_passwords
        cursor.execute('SELECT username FROM admin_passwords WHERE username = ?', (identifier,))
        admin_row = cursor.fetchone()
        if admin_row:
            return {'user_type': 'super_admin', 'username': admin_row['username']}
    
    # Check if it's super_admin hardcoded aliases
    if identifier.lower() in ['super_admin', 'superadmin', 'admin']:
        return {'user_type': 'super_admin', 'username': 'super_admin'}
    
    with get_connection() as conn:
        cursor = conn.cursor()
        # Search by username or email across all user types
        cursor.execute('''
            SELECT id, username, email, user_type, parent_admin, parent_trader, 
                   is_active, must_change_password, password_hash, salt, last_login
            FROM user_credentials 
            WHERE (username = ? OR email = ?) AND is_active = 1
        ''', (identifier, identifier))
        row = cursor.fetchone()
        return dict(row) if row else None

def verify_user_by_identifier(identifier: str, password: str) -> dict:
    """
    Verify user credentials by email or username (auto-detect user type).
    Returns user info with user_type if successful, None otherwise.
    """
    user = find_user_by_identifier(identifier)
    if not user:
        return None
    
    # Super admin has special handling
    if user.get('user_type') == 'super_admin':
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
    """Permanently delete a user credential."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM user_credentials 
            WHERE username = ? AND user_type = ?
        ''', (username, user_type))
        conn.commit()
        return cursor.rowcount > 0

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

def generate_api_key(admin: str, trader: str, client: str = '') -> str:
    """Generate a new API key and store its hash."""
    api_key = 'tk_' + secrets.token_urlsafe(32)
    key_hash = hash_api_key(api_key)
    key_prefix = api_key[:12]  # Store prefix for identification
    now = datetime.now().isoformat()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO api_keys (key_hash, key_prefix, admin, trader, client, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (key_hash, key_prefix, admin, trader, client, now))
            conn.commit()
            return api_key  # Return the actual key (only time it's visible)
        except Exception as e:
            print(f"Error generating API key: {e}")
            return None

def validate_api_key(api_key: str) -> dict:
    """Validate an API key and return user info if valid."""
    key_hash = hash_api_key(api_key)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT admin, trader, client, created_at FROM api_keys 
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
                'created': row['created_at']
            }
        
        return None

def list_api_keys() -> list:
    """List all API keys (showing only prefix)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT key_prefix, admin, trader, client, created_at, last_used, is_active
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

# ============ Client Data Management ============

def save_client_data(client_id: str, data: dict) -> bool:
    """Save client data to database - Merges updates instead of overwriting."""
    now = datetime.now().isoformat()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            # First, get existing data to merge with
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
                    'identity': json.loads(row['identity'])
                }
            
            # Merge existing data with new data (new data takes precedence)
            # This ensures that if we only update one field (e.g. account), we don't wipe out others (e.g. deals)
            # if the caller didn't provide them.
            
            merged_deals = data.get('deals', existing_data.get('deals', []))
            merged_positions = data.get('positions', existing_data.get('positions', []))
            merged_account = data.get('account', existing_data.get('account', {}))
            merged_evaluations = data.get('evaluations', existing_data.get('evaluations', []))
            merged_statistics = data.get('statistics', existing_data.get('statistics', {}))
            merged_dropdown_options = data.get('dropdown_options', existing_data.get('dropdown_options', {}))
            merged_identity = data.get('identity', existing_data.get('identity', {}))

            cursor.execute('''
                INSERT INTO clients_data (
                    client_id, deals, positions, account, evaluations,
                    statistics, dropdown_options, identity, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    deals = excluded.deals,
                    positions = excluded.positions,
                    account = excluded.account,
                    evaluations = excluded.evaluations,
                    statistics = excluded.statistics,
                    dropdown_options = excluded.dropdown_options,
                    identity = excluded.identity,
                    last_updated = excluded.last_updated
            ''', (
                client_id,
                json.dumps(merged_deals),
                json.dumps(merged_positions),
                json.dumps(merged_account),
                json.dumps(merged_evaluations),
                json.dumps(merged_statistics),
                json.dumps(merged_dropdown_options),
                json.dumps(merged_identity),
                now
            ))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error saving client data: {e}")
            return False

def delete_client_data(client_id: str) -> bool:
    """
    Deletes all data associated with a client.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Delete from main data store
            cursor .execute("DELETE FROM clients_data WHERE client_id = ?", (client_id,))
            
            # Delete from history
            cursor.execute("DELETE FROM data_history WHERE client_id = ?", (client_id,))
            
            # Delete notes
            cursor.execute("DELETE FROM cell_notes WHERE client_id = ?", (client_id,))
            
            # Delete watermarks
            cursor.execute("DELETE FROM daily_watermarks WHERE client_id = ?", (client_id,))
            
            conn.commit()
            return True
            
    except Exception as e:
        print(f"Error deleting client data for {client_id}: {e}")
        return False

def get_client_data(client_id: str) -> dict:
    """Get client data from database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM clients_data WHERE client_id = ?', (client_id,))
        row = cursor.fetchone()
        
        if row:
            return {
                'deals': json.loads(row['deals']),
                'positions': json.loads(row['positions']),
                'account': json.loads(row['account']),
                'evaluations': json.loads(row['evaluations']),
                'statistics': json.loads(row['statistics']),
                'dropdown_options': json.loads(row['dropdown_options']),
                'identity': json.loads(row['identity']),
                'last_updated': row['last_updated']
            }
        
        return None

def get_all_clients() -> dict:
    """Get all client data."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT client_id FROM clients_data')
        clients = {}
        for row in cursor.fetchall():
            client_id = row['client_id']
            clients[client_id] = get_client_data(client_id)
        return clients

def get_clients_count() -> int:
    """Get count of clients in database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM clients_data')
        row = cursor.fetchone()
        return row['count'] if row else 0

def update_client_field(client_id: str, field: str, value) -> bool:
    """Update a specific field for a client."""
    valid_fields = ['deals', 'positions', 'account', 'evaluations', 'statistics', 'identity', 'dropdown_options']
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

# ============ Data History Management ============

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

def save_data_snapshot(client_id: str, data: dict, action: str, 
                       changed_by: str = None, changed_by_type: str = None,
                       ip_address: str = None, change_source: str = None, 
                       change_description: str = None) -> int:
    """
    Save a snapshot of client data to history for versioning/rollback.
    
    Args:
        client_id: The client identifier
        data: The client data dict to snapshot
        action: Type of action (INITIAL, UPDATE, SHEET_IMPORT, MT5_PUSH, ROLLBACK, etc.)
        changed_by: Username/email of who made the change
        changed_by_type: Type of user (client, trader, admin, system)
        ip_address: IP address of the request
        change_source: Source of change (trader_app, dashboard_api, sheet_migration, etc.)
        change_description: Human-readable description of what changed
    
    Returns:
        The version number of the saved snapshot
    """
    try:
        version = get_next_version(client_id)
        now = datetime.now().isoformat()
        
        # Serialize fields safely
        deals_json = json.dumps(data.get('deals', []))
        positions_json = json.dumps(data.get('positions', []))
        account_json = json.dumps(data.get('account', {}))
        evaluations_json = json.dumps(data.get('evaluations', []))
        statistics_json = json.dumps(data.get('statistics', {}))
        dropdown_options_json = json.dumps(data.get('dropdown_options', {}))
        identity_json = json.dumps(data.get('identity', {}))

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO data_history (
                    client_id, version, action, changed_by, changed_by_type,
                    ip_address, change_source, change_description,
                    deals, positions, account, evaluations, statistics,
                    dropdown_options, identity, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                                 change_description: str = None) -> tuple:
    """
    Save client data AND create a history snapshot for versioning.
    
    Returns:
        Tuple of (success: bool, version: int)
    """
    # First, save a snapshot to history
    version = save_data_snapshot(
        client_id, data, action, changed_by, changed_by_type,
        ip_address, change_source, change_description
    )
    
    # Then save the current data
    success = save_client_data(client_id, data)
    
    return (success, version)

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

def cleanup_old_history(client_id: str = None, keep_versions: int = 100) -> int:
    """
    Clean up old history entries, keeping only the latest N versions per client.
    
    Returns the number of deleted entries.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        if client_id:
            # Delete for specific client
            cursor.execute('''
                DELETE FROM data_history 
                WHERE client_id = ? AND version NOT IN (
                    SELECT version FROM data_history 
                    WHERE client_id = ? 
                    ORDER BY version DESC 
                    LIMIT ?
                )
            ''', (client_id, client_id, keep_versions))
        else:
            # Get all client IDs
            cursor.execute('SELECT DISTINCT client_id FROM data_history')
            clients = [row['client_id'] for row in cursor.fetchall()]
            
            total_deleted = 0
            for cid in clients:
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
            
            conn.commit()
            return total_deleted
        
        deleted = cursor.rowcount
        conn.commit()
        return deleted

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
