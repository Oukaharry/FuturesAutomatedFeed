# 🔐 Security Enhancement Deployment Steps

## Files to Upload to PythonAnywhere

Upload these files to `/home/ballerquotes/TrackingDashboard/dashboard/`:

### 1. Core Files
| Local File | Upload To |
|------------|-----------|
| `deployment_package/dashboard/app.py` | `/home/ballerquotes/TrackingDashboard/dashboard/app.py` |
| `deployment_package/dashboard/database.py` | `/home/ballerquotes/TrackingDashboard/dashboard/database.py` |

### 2. Templates
Upload to `/home/ballerquotes/TrackingDashboard/dashboard/templates/`:

| Local File | Upload To |
|------------|-----------|
| `deployment_package/dashboard/templates/login.html` | `templates/login.html` |
| `deployment_package/dashboard/templates/change_password.html` | `templates/change_password.html` |

---

## Step-by-Step Instructions

### Step 1: Install Flask-Limiter
1. Go to **Consoles** tab in PythonAnywhere
2. Open a **Bash console**
3. Run:
```bash
pip3.10 install --user flask-limiter
```

### Step 2: Upload Files
1. Go to **Files** tab
2. Navigate to `/home/ballerquotes/TrackingDashboard/dashboard/`
3. Upload `app.py` and `database.py`
4. Navigate to `/home/ballerquotes/TrackingDashboard/dashboard/templates/`
5. Upload `login.html` and `change_password.html`

### Step 3: Create Initial Users
After uploading, run this in a **Bash console**:

```bash
cd /home/ballerquotes/TrackingDashboard
python3.10 -c "
from dashboard.database import init_database, create_user

# Initialize database (creates new tables)
init_database()

# Create users (you can customize these)
# create_user(username, email, password, user_type, parent_admin=None, parent_trader=None)

# Example: Create an admin user
create_user('admin1', 'admin1@example.com', 'SecurePass123!', 'admin')

# Example: Create a trader under admin1
create_user('trader1', 'trader1@example.com', 'TraderPass123!', 'trader', parent_admin='admin1')

# Example: Create a client under trader1
create_user('client1@email.com', 'client1@email.com', 'ClientPass123!', 'client', parent_admin='admin1', parent_trader='trader1')

print('Users created successfully!')
"
```

### Step 4: Reload Web App
1. Go to **Web** tab
2. Click the green **Reload** button

---

## 🔑 Default Credentials After Deployment

| User Type | Username/Email | Password |
|-----------|---------------|----------|
| Super Admin | super_admin | BallerAdmin@123 |
| Admin | admin1 (create via script above) | SecurePass123! |
| Trader | trader1 (create via script above) | TraderPass123! |
| Client | client1@email.com (create via script above) | ClientPass123! |

⚠️ **IMPORTANT**: Change these passwords immediately after first login!

---

## Security Features Now Active

✅ **Password Authentication** - All users must login with password  
✅ **Password Hashing** - PBKDF2-SHA256 with 100,000 iterations  
✅ **Rate Limiting** - 10 login attempts per minute  
✅ **Account Lockout** - 15 minute lockout after 5 failed attempts  
✅ **Session Management** - Secure HTTP-only cookies, 24-hour expiry  
✅ **Audit Logging** - All actions logged with timestamp and IP  
✅ **SQL Injection Protection** - Parameterized queries  

---

## Test the Login

1. Visit: https://ballerquotes.pythonanywhere.com
2. You should see the new tabbed login page
3. Login as Super Admin with password: `BallerAdmin@123`
4. You'll be prompted to change your password (recommended)
