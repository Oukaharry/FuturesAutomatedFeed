# Security Implementation Guide

## Overview
This document describes the security features implemented in the Trading Dashboard.

---

## 🔐 Security Features Implemented

### 1. Password Hashing (PBKDF2-SHA256)
- **Algorithm**: PBKDF2 with SHA-256
- **Iterations**: 100,000 (industry standard)
- **Salt**: 32-byte random salt per password
- **Storage**: Only hash + salt stored, never plain text

### 2. API Key Hashing (SHA-256)
- API keys are hashed before storage
- Only the key prefix (first 12 chars) is stored for identification
- Full key is shown only once at generation time
- Cannot be recovered - must generate new key if lost

### 3. Rate Limiting
| Endpoint Type | Limit |
|--------------|-------|
| Default | 200/day, 50/hour |
| Login | 10/minute |
| Admin Login | 5/minute |
| Data Push | 30/minute |
| API Key Generation | 10/hour |
| Password Change | 3/hour |

### 4. SQLite Database
- Replaces JSON file storage
- Proper relational data storage
- File: `dashboard.db`
- Automatic initialization on first run

### 5. Audit Logging
All actions are logged with:
- Timestamp
- Action type
- User type (admin/trader/client)
- User identifier
- IP address
- Success/failure status
- Additional details

**Logged actions include:**
- Login attempts (success/failure)
- API key generation/revocation
- Data updates
- Admin actions
- Client/trader management

### 6. Session Management
- Secure session tokens for web logins
- HTTP-only cookies
- Automatic expiration (24 hours)
- Secure + SameSite cookie flags

---

## 📁 Database Schema

### api_keys
```sql
- id: INTEGER PRIMARY KEY
- key_hash: TEXT (SHA-256 hash)
- key_prefix: TEXT (first 12 chars for ID)
- admin: TEXT
- trader: TEXT
- client: TEXT
- created_at: TEXT
- last_used: TEXT
- is_active: INTEGER (1=active, 0=revoked)
```

### admin_passwords
```sql
- id: INTEGER PRIMARY KEY
- username: TEXT UNIQUE
- password_hash: TEXT (PBKDF2 hash)
- salt: TEXT
- created_at: TEXT
- updated_at: TEXT
```

### clients_data
```sql
- id: INTEGER PRIMARY KEY
- client_id: TEXT UNIQUE
- deals: TEXT (JSON)
- positions: TEXT (JSON)
- account: TEXT (JSON)
- evaluations: TEXT (JSON)
- statistics: TEXT (JSON)
- dropdown_options: TEXT (JSON)
- identity: TEXT (JSON)
- last_updated: TEXT
```

### audit_log
```sql
- id: INTEGER PRIMARY KEY
- timestamp: TEXT
- action: TEXT
- user_type: TEXT
- user_identifier: TEXT
- ip_address: TEXT
- details: TEXT
- success: INTEGER
```

### sessions
```sql
- id: INTEGER PRIMARY KEY
- session_token: TEXT UNIQUE
- user_type: TEXT
- user_identifier: TEXT
- created_at: TEXT
- expires_at: TEXT
- ip_address: TEXT
```

---

## 🚀 Deployment Instructions

### 1. Install new dependencies
On PythonAnywhere Bash console:
```bash
pip3.10 install --user flask-limiter
```

### 2. Upload new files
Upload these files to `/home/ballerquotes/TrackingDashboard/dashboard/`:
- `app.py` (updated)
- `database.py` (new)
- `manage_api_keys.py` (updated)

### 3. Reload the web app
Go to PythonAnywhere Web tab → Click Reload

### 4. Generate new API keys
Old API keys won't work (they were plain text).
Run the key management tool to create new keys:
```bash
cd /home/ballerquotes/TrackingDashboard/dashboard
python3.10 manage_api_keys.py
```

---

## 🔧 Admin Operations

### View Audit Log
```bash
cd /home/ballerquotes/TrackingDashboard/dashboard
python3.10 manage_api_keys.py
# Select option 5
```

### Change Admin Password
```bash
cd /home/ballerquotes/TrackingDashboard/dashboard
python3.10 manage_api_keys.py
# Select option 6
```

### API Endpoints for Admin

**List API Keys:**
```bash
curl -X GET "https://ballerquotes.pythonanywhere.com/api/admin/list_keys" \
  -H "X-Admin-Password: YOUR_PASSWORD"
```

**Generate New Key:**
```bash
curl -X POST "https://ballerquotes.pythonanywhere.com/api/admin/generate_key" \
  -H "Content-Type: application/json" \
  -d '{"admin_password": "YOUR_PASSWORD", "trader_info": {"admin": "Philip", "trader": "Philip"}}'
```

**View Audit Log:**
```bash
curl -X GET "https://ballerquotes.pythonanywhere.com/api/admin/audit_log?limit=50" \
  -H "X-Admin-Password: YOUR_PASSWORD"
```

---

## ⚠️ Important Notes

1. **API Keys are one-time visible**: Save them immediately after generation
2. **Old JSON-based API keys won't work**: Generate new keys for all traders
3. **Database backup**: Periodically backup `dashboard.db`
4. **Rate limits**: Traders may see 429 errors if pushing too frequently
5. **Session expiry**: Admin sessions expire after 24 hours

---

## 🛡️ Security Best Practices

1. **Change the default admin password** immediately after deployment
2. **Use HTTPS only** (PythonAnywhere provides this by default)
3. **Revoke API keys** when traders leave
4. **Monitor audit logs** regularly for suspicious activity
5. **Keep backups** of the database file
