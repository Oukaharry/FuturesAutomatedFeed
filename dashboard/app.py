from flask import Flask, render_template, jsonify, request, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import threading
import json
import os
import sys
from functools import wraps
import secrets
import hashlib
from datetime import datetime

# Add project root to sys.path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.hierarchy import (
    SYSTEM_HIERARCHY, add_admin, add_trader, add_client, 
    update_admin_details, get_client_by_email,
    remove_admin, remove_trader, remove_client,
    move_client, move_trader
)

# Import database module for secure storage
from dashboard.database import (
    init_database, 
    validate_api_key, generate_api_key, list_api_keys, revoke_api_key,
    verify_admin_password, set_admin_password,
    save_client_data, get_client_data, get_all_clients, get_clients_count, update_client_field,
    log_action, get_audit_log,
    create_session, validate_session, delete_session,
    create_user, verify_user_password, verify_client_login, update_user_password,
    get_user, list_users, deactivate_user, reset_user_password, user_exists,
    record_login_attempt, is_account_locked,
    find_user_by_identifier, verify_user_by_identifier
)

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))

# ============ Rate Limiting ============
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Initialize Hierarchy from Config
hierarchy = SYSTEM_HIERARCHY

# Initialize admin password if not exists
def init_admin_password():
    """Initialize default admin password if not set."""
    admin_password = os.getenv('ADMIN_PASSWORD', 'BallerAdmin@123')
    set_admin_password('super_admin', admin_password)
    print("Admin password initialized")

# Run initialization
init_database()
init_admin_password()

# ============ Authentication Decorators ============

def require_api_key(f):
    """Decorator to require valid API key for endpoint access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        client_ip = get_remote_address()
        
        if not api_key:
            log_action('API_ACCESS_DENIED', 'unknown', 'no_key', client_ip, 'Missing API key', False)
            return jsonify({"status": "error", "message": "API key required"}), 401
        
        user_info = validate_api_key(api_key)
        if not user_info:
            log_action('API_ACCESS_DENIED', 'unknown', api_key[:12], client_ip, 'Invalid API key', False)
            return jsonify({"status": "error", "message": "Invalid API key"}), 403
        
        # Add user info to request context
        request.api_user = user_info
        log_action('API_ACCESS', 'trader', user_info.get('trader', 'unknown'), client_ip, f"Endpoint: {request.endpoint}")
        return f(*args, **kwargs)
    return decorated_function

def require_admin_password(f):
    """Decorator to require admin password for endpoint access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_ip = get_remote_address()
        
        # Check for password in request body or headers
        admin_password = None
        if request.is_json:
            admin_password = request.json.get('admin_password')
        if not admin_password:
            admin_password = request.headers.get('X-Admin-Password')
        
        if not admin_password:
            log_action('ADMIN_ACCESS_DENIED', 'admin', 'unknown', client_ip, 'Missing password', False)
            return jsonify({"status": "error", "message": "Admin password required"}), 401
        
        if not verify_admin_password('super_admin', admin_password):
            log_action('ADMIN_ACCESS_DENIED', 'admin', 'super_admin', client_ip, 'Invalid password', False)
            return jsonify({"status": "error", "message": "Invalid admin password"}), 403
        
        log_action('ADMIN_ACCESS', 'admin', 'super_admin', client_ip, f"Endpoint: {request.endpoint}")
        return f(*args, **kwargs)
    return decorated_function

def require_role(*allowed_roles):
    """Decorator to require specific roles via session authentication."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            session_token = request.cookies.get('session_token')
            
            if not session_token:
                return jsonify({"status": "error", "message": "Authentication required"}), 401
            
            session_info = validate_session(session_token)
            if not session_info:
                return jsonify({"status": "error", "message": "Invalid or expired session"}), 401
            
            user_type = session_info.get('user_type')
            if user_type not in allowed_roles:
                log_action('ACCESS_DENIED', user_type, session_info.get('user_identifier'), 
                          get_remote_address(), f"Required roles: {allowed_roles}", False)
                return jsonify({"status": "error", "message": "Access denied. Insufficient permissions."}), 403
            
            request.session_user = session_info
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_session(f):
    """Decorator to require valid session for web access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = request.cookies.get('session_token')
        
        if not session_token:
            return redirect(url_for('index'))
        
        session_info = validate_session(session_token)
        if not session_info:
            return redirect(url_for('index'))
        
        request.session_user = session_info
        return f(*args, **kwargs)
    return decorated_function

# ============ Web Routes ============

@app.route('/')
def index():
    # Check if already logged in
    session_token = request.cookies.get('session_token')
    if session_token:
        session_info = validate_session(session_token)
        if session_info:
            # Redirect to appropriate dashboard
            user_type = session_info.get('user_type')
            user_id = session_info.get('user_identifier')
            if user_type == 'super_admin':
                return redirect('/super_admin')
            elif user_type == 'admin':
                return redirect(f'/admin/{user_id}')
            elif user_type == 'trader':
                return redirect(f'/trader/{user_id}')
            elif user_type == 'client':
                return redirect(f'/dashboard/{user_id}')
    return render_template('login.html')

@app.route('/super_admin')
@require_session
def super_admin():
    if request.session_user.get('user_type') != 'super_admin':
        return redirect('/')
    return render_template('super_admin.html')

@app.route('/admin/<admin_name>')
@require_session
def admin_dashboard(admin_name):
    session_user = request.session_user
    # Allow super_admin to access any admin dashboard
    if session_user.get('user_type') == 'super_admin':
        return render_template('admin_dashboard.html', admin_name=admin_name)
    # Check if user is the correct admin
    if session_user.get('user_type') != 'admin' or session_user.get('user_identifier') != admin_name:
        return redirect('/')
    return render_template('admin_dashboard.html', admin_name=admin_name)

@app.route('/trader/<trader_name>')
@require_session
def trader_dashboard(trader_name):
    session_user = request.session_user
    # Allow super_admin to access any trader dashboard
    if session_user.get('user_type') == 'super_admin':
        return render_template('trader_dashboard.html', trader_name=trader_name)
    # Allow admin to access traders under them
    if session_user.get('user_type') == 'admin':
        return render_template('trader_dashboard.html', trader_name=trader_name)
    # Check if user is the correct trader
    if session_user.get('user_type') != 'trader' or session_user.get('user_identifier') != trader_name:
        return redirect('/')
    return render_template('trader_dashboard.html', trader_name=trader_name)

@app.route('/dashboard/<client_id>')
@require_session
def client_dashboard(client_id):
    session_user = request.session_user
    # Allow super_admin, admin, and trader to access any client dashboard
    if session_user.get('user_type') in ['super_admin', 'admin', 'trader']:
        return render_template('index.html', client_id=client_id)
    # Check if user is the correct client
    if session_user.get('user_type') != 'client' or session_user.get('user_identifier') != client_id:
        return redirect('/')
    return render_template('index.html', client_id=client_id)

# ============ Hierarchy API with Role-Based Access Control ============

def get_filtered_hierarchy(user_type, user_identifier):
    """
    Returns hierarchy filtered based on user role:
    - super_admin: sees everything
    - admin: sees only their traders and clients
    - trader: sees only their clients
    - client: sees only themselves
    """
    full_hierarchy = hierarchy
    
    if user_type == 'super_admin':
        return full_hierarchy
    
    if user_type == 'admin':
        # Admin sees only their own data
        admin_name = user_identifier
        if admin_name in full_hierarchy.get('admins', {}):
            return {
                'admins': {
                    admin_name: full_hierarchy['admins'][admin_name]
                }
            }
        return {'admins': {}}
    
    if user_type == 'trader':
        # Trader sees only their clients - need to find which admin they belong to
        trader_name = user_identifier
        for admin_name, admin_data in full_hierarchy.get('admins', {}).items():
            traders = admin_data.get('traders', {})
            if trader_name in traders:
                return {
                    'admins': {
                        admin_name: {
                            'email': '',  # Hide admin email from trader
                            'traders': {
                                trader_name: traders[trader_name]
                            }
                        }
                    }
                }
        return {'admins': {}}
    
    if user_type == 'client':
        # Client sees only themselves
        client_name = user_identifier
        for admin_name, admin_data in full_hierarchy.get('admins', {}).items():
            for trader_name, trader_data in admin_data.get('traders', {}).items():
                for client in trader_data.get('clients', []):
                    if client.get('name') == client_name or client.get('email') == client_name:
                        return {
                            'admins': {
                                admin_name: {
                                    'email': '',
                                    'traders': {
                                        trader_name: {
                                            'email': '',
                                            'clients': [client]
                                        }
                                    }
                                }
                            }
                        }
        return {'admins': {}}
    
    return {'admins': {}}

@app.route('/api/hierarchy')
def get_hierarchy():
    """Returns hierarchy filtered by user's role."""
    session_token = request.cookies.get('session_token')
    
    if not session_token:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    
    session_info = validate_session(session_token)
    if not session_info:
        return jsonify({"status": "error", "message": "Invalid session"}), 401
    
    user_type = session_info.get('user_type')
    user_identifier = session_info.get('user_identifier')
    
    filtered = get_filtered_hierarchy(user_type, user_identifier)
    return jsonify(filtered)

@app.route('/api/client/lookup', methods=['POST'])
@require_api_key
def api_client_lookup():
    """Look up client hierarchy info by email."""
    email = request.json.get('email', '').strip()
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    client = get_client_by_email(email)
    if client:
        return jsonify({
            "status": "success",
            "client": client['client'],
            "trader": client['trader'],
            "admin": client['admin'],
            "email": client['email']
        })
    
    return jsonify({"status": "error", "message": "Email not found in system"}), 404

# ============ PUBLIC CLIENT API (No API Key Required) ============

@app.route('/api/client/auth', methods=['POST'])
@limiter.limit("30 per minute")
def api_client_auth():
    """
    Public endpoint - authenticate client by email only.
    Returns client hierarchy info if email exists in system.
    No API key required - just the client email.
    """
    email = request.json.get('email', '').strip().lower()
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    client = get_client_by_email(email)
    if client:
        log_action('CLIENT_AUTH', 'client', email, get_remote_address(), 'Email verified')
        return jsonify({
            "status": "success",
            "identity": {
                "admin": client['admin'],
                "trader": client['trader'],
                "client": client['client'],
                "email": client['email'],
                "category": client.get('category', '')
            }
        })
    
    log_action('CLIENT_AUTH_FAILED', 'client', email, get_remote_address(), 'Email not found', False)
    return jsonify({"status": "error", "message": "Email not registered in the system"}), 404


@app.route('/api/client/push', methods=['POST'])
@limiter.limit("60 per minute")
def api_client_push():
    """
    Public endpoint - push data using client email only (no API key).
    Automatically looks up hierarchy from email.
    Recalculates statistics using MT5 deals/account data if provided.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    # Look up client by email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered in the system"}), 404
    
    admin_id = client_info['admin']
    trader_id = client_info['trader']
    client_id = client_info['client']
    
    # Get MT5 data from push
    mt5_deals = data.get("deals", [])
    mt5_account = data.get("account", {})
    new_evaluations = data.get("evaluations", [])
    
    # Get existing data to merge evaluations if needed
    existing_data = get_client_data(client_id) or {}
    evaluations = new_evaluations if new_evaluations else existing_data.get("evaluations", [])
    
    # Debug logging
    acct_balance = mt5_account.get('balance', 0) if mt5_account else 0
    app.logger.info(f"Push for {client_id}: {len(mt5_deals)} deals, balance={acct_balance}, {len(evaluations)} evaluations")
    
    # ALWAYS recalculate statistics when we have evaluations or MT5 data
    # This ensures discrepancy is only calculated when we have actual MT5 data
    statistics = data.get("statistics", {})
    if evaluations or mt5_deals or mt5_account:
        try:
            from utils.data_processor import calculate_statistics
            # Pass MT5 data - if empty, discrepancy will be 0
            mt5_acc_param = mt5_account if mt5_account else None
            mt5_deals_param = mt5_deals if mt5_deals else None
            statistics = calculate_statistics(evaluations, mt5_acc_param, mt5_deals_param)
            
            # Log the hedging review results
            hr = statistics.get('hedging_review', {})
            app.logger.info(f"Stats calculated: balance={hr.get('current_balance')}, deposits={hr.get('total_deposits')}, withdrawals={hr.get('total_withdrawals')}, actual_hedging={hr.get('actual_hedging_results')}")
        except Exception as e:
            app.logger.error(f"Error recalculating stats: {e}")
            import traceback
            app.logger.error(traceback.format_exc())
            # Keep the provided statistics if recalc fails
    
    # Prepare client data
    client_data = {
        "deals": mt5_deals,
        "positions": data.get("positions", []),
        "account": mt5_account,
        "evaluations": evaluations,
        "statistics": statistics,
        "dropdown_options": data.get("dropdown_options", {}),
        "identity": {
            "admin": admin_id,
            "trader": trader_id,
            "client": client_id,
            "email": email
        }
    }
    
    # Save to database
    save_client_data(client_id, client_data)
    
    # Update Hierarchy (in case new)
    add_admin(admin_id)
    add_trader(admin_id, trader_id)
    add_client(admin_id, trader_id, client_id)
    
    log_action('CLIENT_DATA_PUSH', 'client', email, get_remote_address(), f"Data pushed for {client_id}")
    return jsonify({
        "status": "success", 
        "message": f"Data updated for {client_id}",
        "identity": {
            "admin": admin_id,
            "trader": trader_id,
            "client": client_id
        }
    })


@app.route('/api/client/migrate_sheet', methods=['POST'])
@limiter.limit("10 per minute")
def api_migrate_sheet():
    """
    Public endpoint - migrate data from Google Sheets using client email.
    Fetches data from Google Sheet and pushes it to the dashboard.
    """
    data = request.json
    email = data.get('email', '').strip().lower()
    sheet_url = data.get('sheet_url', '').strip()
    
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    if not sheet_url:
        return jsonify({"status": "error", "message": "Google Sheet URL required"}), 400
    
    # Look up client by email
    client_info = get_client_by_email(email)
    if not client_info:
        return jsonify({"status": "error", "message": "Email not registered in the system"}), 404
    
    admin_id = client_info['admin']
    trader_id = client_info['trader']
    client_id = client_info['client']
    
    # Fetch data from Google Sheets
    try:
        # Import the data processor
        from utils.data_processor import fetch_evaluations, calculate_statistics
        
        evaluations = fetch_evaluations(sheet_url)
        if not evaluations:
            return jsonify({"status": "error", "message": "Could not fetch data from sheet. Make sure it's public."}), 400
        
        # Calculate statistics without MT5 data (discrepancy will be 0)
        statistics = calculate_statistics(evaluations, None, None)
        
        # Prepare client data
        client_data = {
            "deals": [],
            "positions": [],
            "account": {},
            "evaluations": evaluations,
            "statistics": statistics,
            "dropdown_options": {},
            "identity": {
                "admin": admin_id,
                "trader": trader_id,
                "client": client_id,
                "email": email
            },
            "sheet_url": sheet_url,
            "migrated_at": datetime.now().isoformat()
        }
        
        # Save to database
        save_client_data(client_id, client_data)
        
        # Update Hierarchy
        add_admin(admin_id)
        add_trader(admin_id, trader_id)
        add_client(admin_id, trader_id, client_id)
        
        log_action('SHEET_MIGRATION', 'client', email, get_remote_address(), 
                   f"Migrated {len(evaluations)} records from Google Sheets for {client_id}")
        
        # Return statistics for verification
        return jsonify({
            "status": "success", 
            "message": f"Successfully migrated {len(evaluations)} evaluation records",
            "records_imported": len(evaluations),
            "statistics": statistics,  # Include stats for client-side verification
            "identity": {
                "admin": admin_id,
                "trader": trader_id,
                "client": client_id
            }
        })
        
    except Exception as e:
        log_action('SHEET_MIGRATION_FAILED', 'client', email, get_remote_address(), str(e), False)
        return jsonify({"status": "error", "message": f"Migration failed: {str(e)}"}), 500


@app.route('/api/login', methods=['POST'])
@limiter.limit("10 per minute")
def api_login():
    email = request.json.get('email')
    client_ip = get_remote_address()
    
    if not email: 
        return jsonify({"status": "error", "message": "Email required"}), 400
    
    client = get_client_by_email(email)
    if client:
        log_action('CLIENT_LOGIN', 'client', email, client_ip, 'Successful login')
        return jsonify({"status": "success", "redirect": f"/dashboard/{client['client']}"})
    
    log_action('CLIENT_LOGIN_FAILED', 'client', email, client_ip, 'Email not found', False)
    return jsonify({"status": "error", "message": "Email not found"}), 404

@app.route('/api/admin_login', methods=['POST'])
@limiter.limit("5 per minute")
def api_admin_login():
    """Secure admin login with session creation."""
    password = request.json.get('password')
    client_ip = get_remote_address()
    
    if not password:
        return jsonify({"status": "error", "message": "Password required"}), 400
    
    if verify_admin_password('super_admin', password):
        session_token = create_session('admin', 'super_admin', client_ip)
        log_action('ADMIN_LOGIN', 'admin', 'super_admin', client_ip, 'Successful login')
        
        response = jsonify({"status": "success", "redirect": "/super_admin"})
        response.set_cookie('session_token', session_token, httponly=True, secure=True, samesite='Strict')
        return response
    
    log_action('ADMIN_LOGIN_FAILED', 'admin', 'super_admin', client_ip, 'Invalid password', False)
    return jsonify({"status": "error", "message": "Invalid password"}), 403

@app.route('/logout')
def logout():
    """Logout via GET request - clears session and redirects to login."""
    session_token = request.cookies.get('session_token')
    if session_token:
        delete_session(session_token)
        log_action('LOGOUT', 'user', 'session', get_remote_address())
    
    response = redirect('/')
    response.delete_cookie('session_token')
    return response

@app.route('/api/logout', methods=['POST'])
def api_logout():
    """Logout and invalidate session (API endpoint)."""
    session_token = request.cookies.get('session_token')
    if session_token:
        delete_session(session_token)
    
    response = jsonify({"status": "success"})
    response.delete_cookie('session_token')
    return response

# ============ Unified Authentication Endpoint ============

@app.route('/api/auth/login', methods=['POST'])
@limiter.limit("10 per minute")
def unified_login():
    """
    Unified login endpoint - auto-detects user type from email/username.
    - Super Admin: requires email + password
    - Admin/Trader/Client: only requires email (no password)
    """
    data = request.json
    identifier = data.get('identifier', '').strip()
    password = data.get('password', '')
    remember = data.get('remember', False)
    client_ip = get_remote_address()
    
    if not identifier:
        return jsonify({"status": "error", "message": "Email is required"}), 400
    
    # Find user by identifier (email or username)
    user = find_user_by_identifier(identifier)
    
    if not user:
        log_action('LOGIN_FAILED', 'unknown', identifier, client_ip, 'User not found', False)
        return jsonify({"status": "error", "message": "Email not found in system"}), 403
    
    user_type = user.get('user_type')
    username = user.get('username', identifier)
    
    # Check account lockout
    if is_account_locked(username, user_type):
        log_action('LOGIN_LOCKED', user_type, username, client_ip, 'Account locked', False)
        return jsonify({"status": "error", "message": "Account locked. Too many failed attempts. Try again in 15 minutes."}), 429
    
    # Handle Super Admin login - REQUIRES PASSWORD
    if user_type == 'super_admin':
        if not password:
            return jsonify({"status": "error", "message": "Password is required for Super Admin"}), 400
        
        if verify_admin_password('super_admin', password):
            session_token = create_session('super_admin', 'super_admin', client_ip)
            record_login_attempt('super_admin', 'super_admin', client_ip, True)
            log_action('LOGIN_SUCCESS', 'super_admin', 'super_admin', client_ip)
            
            max_age = 30 * 24 * 60 * 60 if remember else 86400  # 30 days or 24 hours
            response = jsonify({
                "status": "success",
                "user_type": "super_admin",
                "redirect": "/super_admin",
                "must_change_password": False
            })
            response.set_cookie('session_token', session_token, httponly=True, secure=True, samesite='Lax', max_age=max_age)
            return response
        
        record_login_attempt('super_admin', 'super_admin', client_ip, False)
        log_action('LOGIN_FAILED', 'super_admin', 'super_admin', client_ip, 'Invalid password', False)
        return jsonify({"status": "error", "message": "Invalid password"}), 403
    
    # Handle Admin/Trader/Client login - NO PASSWORD REQUIRED (email only)
    # Just verify the email exists in hierarchy
    session_token = create_session(user_type, username, client_ip)
    record_login_attempt(username, user_type, client_ip, True)
    log_action('LOGIN_SUCCESS', user_type, username, client_ip, 'Email-only login')
    
    # Determine redirect URL based on user type
    redirect_map = {
        'admin': f'/admin/{username}',
        'trader': f'/trader/{username}',
        'client': f'/dashboard/{username}'
    }
    redirect_url = redirect_map.get(user_type, '/')
    
    max_age = 30 * 24 * 60 * 60 if remember else 86400
    response = jsonify({
        "status": "success",
        "user_type": user_type,
        "redirect": redirect_url,
        "must_change_password": False
    })
    response.set_cookie('session_token', session_token, httponly=True, secure=True, samesite='Lax', max_age=max_age)
    return response

# ============ User Management Endpoints (Admin only) ============

@app.route('/api/admin/create_user', methods=['POST'])
@require_admin_password
@limiter.limit("20 per hour")
def api_create_user():
    """Create a new user account."""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    user_type = data.get('user_type')  # admin, trader, or client
    email = data.get('email')
    parent_admin = data.get('parent_admin')
    parent_trader = data.get('parent_trader')
    
    if not username or not password or not user_type:
        return jsonify({"status": "error", "message": "Username, password, and user_type required"}), 400
    
    if user_type not in ['admin', 'trader', 'client']:
        return jsonify({"status": "error", "message": "Invalid user type"}), 400
    
    if user_exists(username, user_type):
        return jsonify({"status": "error", "message": f"{user_type.title()} '{username}' already exists"}), 400
    
    if create_user(username, password, user_type, email, parent_admin, parent_trader):
        log_action('CREATE_USER', 'admin', username, get_remote_address(), f"Type: {user_type}")
        return jsonify({"status": "success", "message": f"{user_type.title()} '{username}' created successfully"})
    
    return jsonify({"status": "error", "message": "Failed to create user"}), 500

def can_manage_user(manager_type, manager_identifier, target_username, target_user_type):
    """Check if a user can manage (reset password, deactivate) another user."""
    if manager_type == 'super_admin':
        return True  # Super admin can manage everyone
    
    if manager_type == 'admin':
        # Admin can manage traders and clients under them
        admin_data = hierarchy.get('admins', {}).get(manager_identifier, {})
        
        if target_user_type == 'trader':
            # Check if trader is under this admin
            return target_username in admin_data.get('traders', {})
        
        if target_user_type == 'client':
            # Check if client is under any of this admin's traders
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    if client.get('name') == target_username or client.get('email') == target_username:
                        return True
            return False
        
        return False  # Admin cannot manage other admins
    
    if manager_type == 'trader':
        # Trader can only manage their clients
        if target_user_type != 'client':
            return False
        
        for admin_data in hierarchy.get('admins', {}).values():
            trader_data = admin_data.get('traders', {}).get(manager_identifier, {})
            for client in trader_data.get('clients', []):
                if client.get('name') == target_username or client.get('email') == target_username:
                    return True
        return False
    
    return False

@app.route('/api/admin/list_users', methods=['GET'])
@require_admin_password
def api_list_users():
    """List all users."""
    user_type = request.args.get('type')
    users = list_users(user_type)
    return jsonify({"status": "success", "users": users})

@app.route('/api/user/reset_password', methods=['POST'])
@require_role('super_admin', 'admin', 'trader')
def api_reset_password_rbac():
    """Reset a user's password with role-based access control."""
    from dashboard.email_service import send_password_reset_with_temp
    
    session_user = request.session_user
    manager_type = session_user.get('user_type')
    manager_id = session_user.get('user_identifier')
    
    data = request.json
    username = data.get('username')
    user_type = data.get('user_type')
    email = data.get('email')
    
    if not username or not user_type:
        return jsonify({"status": "error", "message": "Username and user_type required"}), 400
    
    # Check if user has permission to reset this user's password
    if not can_manage_user(manager_type, manager_id, username, user_type):
        log_action('RESET_PASSWORD_DENIED', manager_type, manager_id, get_remote_address(), 
                   f"Attempted to reset: {username} ({user_type})", False)
        return jsonify({"status": "error", "message": "Access denied. You can only manage users under your hierarchy."}), 403
    
    temp_password = reset_user_password(username, user_type)
    if temp_password:
        log_action('RESET_PASSWORD', manager_type, username, get_remote_address(), f"By: {manager_id}")
        
        email_sent = False
        if email:
            email_sent = send_password_reset_with_temp(email, username, temp_password)
        
        return jsonify({
            "status": "success", 
            "message": f"Password reset for {username}",
            "temporary_password": temp_password,
            "email_sent": email_sent
        })
    
    return jsonify({"status": "error", "message": "User not found"}), 404

@app.route('/api/admin/reset_password', methods=['POST'])
@require_admin_password
def api_reset_password():
    """Reset a user's password (legacy - uses password header)."""
    from dashboard.email_service import send_password_reset_with_temp
    
    data = request.json
    username = data.get('username')
    user_type = data.get('user_type')
    email = data.get('email')  # Optional - for email notification
    
    if not username or not user_type:
        return jsonify({"status": "error", "message": "Username and user_type required"}), 400
    
    temp_password = reset_user_password(username, user_type)
    if temp_password:
        log_action('RESET_PASSWORD', 'admin', username, get_remote_address(), f"Type: {user_type}")
        
        # Send email notification if email provided
        email_sent = False
        if email:
            email_sent = send_password_reset_with_temp(email, username, temp_password)
        
        return jsonify({
            "status": "success", 
            "message": f"Password reset for {username}",
            "temporary_password": temp_password,
            "email_sent": email_sent
        })
    
    return jsonify({"status": "error", "message": "User not found"}), 404

@app.route('/api/admin/deactivate_user', methods=['POST'])
@require_admin_password
def api_deactivate_user():
    """Deactivate a user account."""
    data = request.json
    username = data.get('username')
    user_type = data.get('user_type')
    
    if not username or not user_type:
        return jsonify({"status": "error", "message": "Username and user_type required"}), 400
    
    if deactivate_user(username, user_type):
        log_action('DEACTIVATE_USER', 'admin', username, get_remote_address(), f"Type: {user_type}")
        return jsonify({"status": "success", "message": f"User '{username}' deactivated"})
    
    return jsonify({"status": "error", "message": "User not found"}), 404

# ============ Change Password Endpoint ============

@app.route('/change-password')
@require_session
def change_password_page():
    """Page to change password."""
    return render_template('change_password.html')

@app.route('/api/auth/change_password', methods=['POST'])
@require_session
@limiter.limit("5 per hour")
def api_change_password():
    """Change user's own password."""
    from dashboard.email_service import send_password_changed_notification
    
    data = request.json
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    
    if not current_password or not new_password:
        return jsonify({"status": "error", "message": "Current and new password required"}), 400
    
    if len(new_password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters"}), 400
    
    session_user = request.session_user
    user_type = session_user.get('user_type')
    username = session_user.get('user_identifier')
    user_email = session_user.get('email', username)  # Use email if available
    
    # Verify current password
    if user_type == 'super_admin':
        if not verify_admin_password('super_admin', current_password):
            return jsonify({"status": "error", "message": "Current password is incorrect"}), 403
        if set_admin_password('super_admin', new_password):
            log_action('CHANGE_PASSWORD', 'super_admin', 'super_admin', get_remote_address())
            # Send email notification
            if user_email:
                send_password_changed_notification(user_email, 'Super Admin', 'self')
            return jsonify({"status": "success", "message": "Password changed successfully"})
    else:
        user_info = verify_user_password(username, user_type, current_password)
        if not user_info:
            return jsonify({"status": "error", "message": "Current password is incorrect"}), 403
        if update_user_password(username, user_type, new_password):
            log_action('CHANGE_PASSWORD', user_type, username, get_remote_address())
            # Send email notification
            if user_email and '@' in user_email:
                send_password_changed_notification(user_email, username, 'self')
            return jsonify({"status": "success", "message": "Password changed successfully"})
    
    return jsonify({"status": "error", "message": "Failed to change password"}), 500

# ============ Admin/Trader/Client Management ============

@app.route('/api/add_admin', methods=['POST'])
def api_add_admin():
    name = request.json.get('name')
    if not name: return jsonify({"status": "error", "message": "Name required"}), 400
    
    if add_admin(name):
        log_action('ADD_ADMIN', 'system', name, get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Admin exists"}), 400

@app.route('/api/update_admin', methods=['POST'])
def api_update_admin():
    name = request.json.get('name')
    email = request.json.get('email')
    if not name: return jsonify({"status": "error", "message": "Name required"}), 400
    
    if update_admin_details(name, email):
        log_action('UPDATE_ADMIN', 'admin', name, get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Admin not found"}), 400

@app.route('/api/add_trader', methods=['POST'])
def api_add_trader():
    admin = request.json.get('admin')
    name = request.json.get('name')
    if not admin or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    if add_trader(admin, name):
        log_action('ADD_TRADER', 'admin', name, get_remote_address(), f"Admin: {admin}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Invalid request or Trader exists"}), 400

@app.route('/api/add_client', methods=['POST'])
def api_add_client():
    admin = request.json.get('admin')
    trader = request.json.get('trader')
    name = request.json.get('name')
    email = request.json.get('email', '')
    category = request.json.get('category', '')
    
    if not admin or not trader or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    if add_client(admin, trader, name, email, category):
        log_action('ADD_CLIENT', 'trader', name, get_remote_address(), f"Trader: {trader}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Invalid request or Client exists"}), 400

@app.route('/api/remove_admin', methods=['POST'])
def api_remove_admin():
    name = request.json.get('name')
    if not name: return jsonify({"status": "error", "message": "Name required"}), 400
    
    if remove_admin(name):
        log_action('REMOVE_ADMIN', 'system', name, get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Admin not found"}), 400

@app.route('/api/remove_trader', methods=['POST'])
def api_remove_trader():
    admin = request.json.get('admin')
    name = request.json.get('name')
    if not admin or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    if remove_trader(admin, name):
        log_action('REMOVE_TRADER', 'admin', name, get_remote_address(), f"Admin: {admin}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Trader not found"}), 400

@app.route('/api/remove_client', methods=['POST'])
def api_remove_client():
    admin = request.json.get('admin')
    trader = request.json.get('trader')
    name = request.json.get('name')
    if not admin or not trader or not name: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    if remove_client(admin, trader, name):
        log_action('REMOVE_CLIENT', 'trader', name, get_remote_address(), f"Trader: {trader}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Client not found"}), 400

@app.route('/api/move_client', methods=['POST'])
def api_move_client():
    data = request.json
    if move_client(data['client_name'], data['old_admin'], data['old_trader'], data['new_admin'], data['new_trader']):
        log_action('MOVE_CLIENT', 'admin', data['client_name'], get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Move failed"}), 400

@app.route('/api/move_trader', methods=['POST'])
def api_move_trader():
    data = request.json
    if move_trader(data['trader_name'], data['old_admin'], data['new_admin']):
        log_action('MOVE_TRADER', 'admin', data['trader_name'], get_remote_address())
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Move failed"}), 400

@app.route('/super_admin/clients')
@require_session
def client_management():
    if request.session_user.get('user_type') != 'super_admin':
        return redirect('/')
    return render_template('client_management.html')

# ============ Data API with Role-Based Access Control ============

def can_access_client(user_type, user_identifier, target_client):
    """Check if user has permission to access a client's data."""
    if user_type == 'super_admin':
        return True
    
    if user_type == 'client':
        # Client can only access their own data
        return user_identifier == target_client
    
    # For admins and traders, check hierarchy
    for admin_name, admin_data in hierarchy.get('admins', {}).items():
        for trader_name, trader_data in admin_data.get('traders', {}).items():
            for client in trader_data.get('clients', []):
                client_name = client.get('name', '')
                client_email = client.get('email', '')
                
                if client_name == target_client or client_email == target_client:
                    if user_type == 'admin' and user_identifier == admin_name:
                        return True
                    if user_type == 'trader' and user_identifier == trader_name:
                        return True
    
    return False

def get_accessible_clients(user_type, user_identifier):
    """Get list of client names this user can access."""
    clients = []
    
    if user_type == 'super_admin':
        # Super admin can access all clients
        for admin_data in hierarchy.get('admins', {}).values():
            for trader_data in admin_data.get('traders', {}).values():
                for client in trader_data.get('clients', []):
                    clients.append(client.get('name'))
        return clients
    
    if user_type == 'admin':
        # Admin can access all clients under their traders
        admin_data = hierarchy.get('admins', {}).get(user_identifier, {})
        for trader_data in admin_data.get('traders', {}).values():
            for client in trader_data.get('clients', []):
                clients.append(client.get('name'))
        return clients
    
    if user_type == 'trader':
        # Trader can access only their clients
        for admin_data in hierarchy.get('admins', {}).values():
            trader_data = admin_data.get('traders', {}).get(user_identifier, {})
            for client in trader_data.get('clients', []):
                clients.append(client.get('name'))
        return clients
    
    if user_type == 'client':
        # Client can only access themselves
        return [user_identifier]
    
    return []

@app.route('/api/data')
def get_data():
    """Get client data - requires authentication and role-based access."""
    client_id = request.args.get('client_id')
    
    # Check authentication
    session_token = request.cookies.get('session_token')
    if not session_token:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    
    session_info = validate_session(session_token)
    if not session_info:
        return jsonify({"status": "error", "message": "Invalid session"}), 401
    
    user_type = session_info.get('user_type')
    user_identifier = session_info.get('user_identifier')
    
    if client_id:
        # Check if user can access this client's data
        if not can_access_client(user_type, user_identifier, client_id):
            log_action('ACCESS_DENIED', user_type, user_identifier, get_remote_address(), f"Tried to access: {client_id}", False)
            return jsonify({"status": "error", "message": "Access denied"}), 403
        
        data = get_client_data(client_id)
        if data:
            return jsonify(data)
    
    # If no client specified, return empty
    return jsonify({
        "deals": [], "positions": [], "account": {}, 
        "evaluations": [], "statistics": {}, "dropdown_options": {}, 
        "last_updated": "Never"
    })

@app.route('/api/update_data', methods=['POST'])
@require_api_key
@limiter.limit("60 per minute")
def update_data():
    data = request.json
    identity = data.get('identity', {})
    
    # Use authenticated user info if no identity provided
    if not identity and hasattr(request, 'api_user'):
        identity = {
            'admin': request.api_user.get('admin'),
            'trader': request.api_user.get('trader'),
            'client': request.api_user.get('client')
        }
    
    admin_id = identity.get('admin', 'Admin1')
    trader_id = identity.get('trader', 'Trader1')
    client_id = identity.get('client', 'Client1')
    
    # Prepare client data
    client_data = {
        "deals": data.get("deals", []),
        "positions": data.get("positions", []),
        "account": data.get("account", {}),
        "evaluations": data.get("evaluations", []),
        "statistics": data.get("statistics", {}),
        "dropdown_options": data.get("dropdown_options", {}),
        "identity": identity
    }
    
    # Save to database
    save_client_data(client_id, client_data)
    
    # Update Hierarchy
    add_admin(admin_id)
    add_trader(admin_id, trader_id)
    add_client(admin_id, trader_id, client_id)
    
    log_action('DATA_UPDATE', 'trader', trader_id, get_remote_address(), f"Client: {client_id}")
    return jsonify({"status": "success", "message": "Data updated"})

# ============ API Key Management (Admin only) ============

@app.route('/api/admin/generate_key', methods=['POST'])
@require_admin_password
@limiter.limit("10 per hour")
def api_generate_key():
    """Generate a new API key for a trader."""
    trader_info = request.json.get('trader_info', {})
    admin = trader_info.get('admin')
    trader = trader_info.get('trader')
    client = trader_info.get('client', '')
    
    if not admin or not trader:
        return jsonify({"status": "error", "message": "Admin and trader required"}), 400
    
    # Generate hashed API key
    api_key = generate_api_key(admin, trader, client)
    
    if api_key:
        log_action('GENERATE_API_KEY', 'admin', trader, get_remote_address())
        return jsonify({
            "status": "success",
            "api_key": api_key,  # Only time the full key is visible
            "trader_info": {"admin": admin, "trader": trader, "client": client}
        })
    
    return jsonify({"status": "error", "message": "Failed to generate key"}), 500

@app.route('/api/admin/list_keys', methods=['GET'])
@require_admin_password
def api_list_keys():
    """List all API keys (showing only prefix)."""
    keys = list_api_keys()
    log_action('LIST_API_KEYS', 'admin', 'super_admin', get_remote_address())
    return jsonify({"status": "success", "keys": keys})

@app.route('/api/admin/revoke_key', methods=['POST'])
@require_admin_password
def api_revoke_key():
    """Revoke an API key."""
    key_prefix = request.json.get('key_prefix')
    
    if not key_prefix:
        return jsonify({"status": "error", "message": "Key prefix required"}), 400
    
    if revoke_api_key(key_prefix):
        log_action('REVOKE_API_KEY', 'admin', key_prefix, get_remote_address())
        return jsonify({"status": "success", "message": "API key revoked"})
    
    return jsonify({"status": "error", "message": "API key not found"}), 404

# ============ Audit Log (Admin only) ============

@app.route('/api/admin/audit_log', methods=['GET'])
@require_admin_password
def api_audit_log():
    """Get audit log entries."""
    limit = request.args.get('limit', 100, type=int)
    action_filter = request.args.get('action', None)
    
    logs = get_audit_log(limit, action_filter)
    return jsonify({"status": "success", "logs": logs})

# ============ Trader Push Endpoints ============

@app.route('/api/trader/push_account', methods=['POST'])
@require_api_key
@limiter.limit("30 per minute")
def push_account_data():
    """Endpoint for traders to push account information."""
    data = request.json
    client_id = data.get('client_id') or request.api_user.get('client', 'Client1')
    
    update_client_field(client_id, 'account', data.get('account', {}))
    log_action('PUSH_ACCOUNT', 'trader', request.api_user.get('trader'), get_remote_address(), f"Client: {client_id}")
    
    return jsonify({"status": "success", "message": "Account data updated"})

@app.route('/api/trader/push_positions', methods=['POST'])
@require_api_key
@limiter.limit("30 per minute")
def push_positions():
    """Endpoint for traders to push current positions."""
    data = request.json
    client_id = data.get('client_id') or request.api_user.get('client', 'Client1')
    
    update_client_field(client_id, 'positions', data.get('positions', []))
    log_action('PUSH_POSITIONS', 'trader', request.api_user.get('trader'), get_remote_address(), f"Client: {client_id}")
    
    return jsonify({"status": "success", "message": "Positions updated"})

@app.route('/api/trader/push_deals', methods=['POST'])
@require_api_key
@limiter.limit("30 per minute")
def push_deals():
    """Endpoint for traders to push deal history."""
    data = request.json
    client_id = data.get('client_id') or request.api_user.get('client', 'Client1')
    
    update_client_field(client_id, 'deals', data.get('deals', []))
    log_action('PUSH_DEALS', 'trader', request.api_user.get('trader'), get_remote_address(), f"Client: {client_id}")
    
    return jsonify({"status": "success", "message": "Deals updated"})

@app.route('/api/trader/push_evaluations', methods=['POST'])
@require_api_key
@limiter.limit("30 per minute")
def push_evaluations():
    """Endpoint for traders to push evaluation data."""
    data = request.json
    client_id = data.get('client_id') or request.api_user.get('client', 'Client1')
    
    update_client_field(client_id, 'evaluations', data.get('evaluations', []))
    log_action('PUSH_EVALUATIONS', 'trader', request.api_user.get('trader'), get_remote_address(), f"Client: {client_id}")
    
    return jsonify({"status": "success", "message": "Evaluations updated"})

# ============ Health Check ============

@app.route('/health', methods=['GET'])
@app.route('/api/health', methods=['GET'])
def health_check():
    """Simple health check endpoint."""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "clients_count": get_clients_count()
    })

# ============ Change Password Endpoint ============

@app.route('/api/admin/change_password', methods=['POST'])
@require_admin_password
@limiter.limit("3 per hour")
def change_admin_password():
    """Change admin password."""
    new_password = request.json.get('new_password')
    
    if not new_password or len(new_password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters"}), 400
    
    if set_admin_password('super_admin', new_password):
        log_action('CHANGE_PASSWORD', 'admin', 'super_admin', get_remote_address())
        return jsonify({"status": "success", "message": "Password changed successfully"})
    
    return jsonify({"status": "error", "message": "Failed to change password"}), 500

# ============ Main Entry Point ============

def run_dashboard():
    print(f"\n{'='*60}")
    print("SECURE DASHBOARD API SERVER STARTING")
    print(f"{'='*60}")
    print(f"Database: SQLite with encrypted storage")
    print(f"Rate Limiting: Enabled")
    print(f"Password Hashing: PBKDF2-SHA256 (100,000 iterations)")
    print(f"API Keys: Hashed with SHA-256")
    print(f"Audit Logging: Enabled")
    print(f"\nClients in database: {get_clients_count()}")
    print(f"{'='*60}\n")
    app.run(host='0.0.0.0', port=5001, debug=True)

if __name__ == '__main__':
    run_dashboard()
