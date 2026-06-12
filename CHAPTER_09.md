# Chapter 9 — Pushing data to the dashboard

_Exported from CODEBASE_REFERENCE.pdf as plain Markdown. Paste this into another Claude conversation, Notion, or any Markdown viewer._

The desktop companion runs on the trader's machine. The web dashboard runs on a server. They communicate through an HTTP ingestion API. In this phase we build the outbound HTTP client and the periodic sync that pushes MT5 deal history to the server.

**Files in this chapter:**

- `trader_companion/push_data.py`
- `trader_companion/mt5_dashboard_sync.py`

---

### `trader_companion/push_data.py`

_199 loc · 0 classes · 4 functions · 7 imports_

**Module docstring**

> MT5 Data Pusher - Command Line Interface Simple script for traders to push data to the dashboard from command line. NO API KEY REQUIRED - just your email address!

**Imports**

```python
import sys
import os
import json
import gzip as _gzip
import argparse
import requests
from trader_companion.trader_app import MT5DataPusher, APP_VERSION
```

**Functions**

#### `lookup_client`

```python
def lookup_client(url, email)
```
> Lookup client hierarchy from email - NO API KEY.

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def lookup_client(url, email):
    """Lookup client hierarchy from email - NO API KEY."""
    try:
        response = requests.post(
            f"{url.rstrip('/')}/api/client/auth",
            json={"email": email},
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                return data.get("identity", {}), None
            else:
                return None, data.get("message", "Client not found")
        else:
            return None, f"API Error: {response.status_code}"
    except Exception as e:
        return None, str(e)
```

#### `push_data`

```python
def push_data(url, email, account, positions, deals, statistics)
```
> Push data to dashboard - NO API KEY. Sends gzip-compressed JSON.

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def push_data(url, email, account, positions, deals, statistics):
    """Push data to dashboard - NO API KEY. Sends gzip-compressed JSON."""
    try:
        payload = {
            "email": email,
            "account": account,
            "positions": positions,
            "deals": deals,
            "statistics": statistics,
            "evaluations": [],
            "dropdown_options": {},
            "companion_version": APP_VERSION,
        }
        raw = json.dumps(payload).encode('utf-8')
        compressed = _gzip.compress(raw, compresslevel=6)
        response = requests.post(
            f"{url.rstrip('/')}/api/client/push",
            data=compressed,
            headers={
                "Content-Type": "application/json",
                "Content-Encoding": "gzip",
                "X-Companion-Version": APP_VERSION,
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                return True, data.get("message", "Data pushed successfully")
            else:
                return False, data.get("message", "Push failed")
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, str(e)
```

#### `migrate_sheet`

```python
def migrate_sheet(url, email, sheet_url)
```
> Migrate data from Google Sheets.

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def migrate_sheet(url, email, sheet_url):
    """Migrate data from Google Sheets."""
    try:
        response = requests.post(
            f"{url.rstrip('/')}/api/client/migrate_sheet",
            json={"email": email, "sheet_url": sheet_url},
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                return True, f"Imported {data.get('records_imported', 0)} records"
            else:
                return False, data.get("message", "Migration failed")
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, str(e)
```

#### `main`

```python
def main()
```
**What it does, step by step:**

1. Assigns <code>parser</code> = <code>argparse.ArgumentParser(description='Push MT5 data to Tra...</code>.
2. Calls <code>parser.add_argument(...)</code> for its side effect.
3. Calls <code>parser.add_argument(...)</code> for its side effect.
4. Calls <code>parser.add_argument(...)</code> for its side effect.
5. Calls <code>parser.add_argument(...)</code> for its side effect.
6. Calls <code>parser.add_argument(...)</code> for its side effect.
7. Calls <code>parser.add_argument(...)</code> for its side effect.
8. Calls <code>parser.add_argument(...)</code> for its side effect.
9. Assigns <code>args</code> = <code>parser.parse_args()</code>.
10. Calls <code>print(...)</code> for its side effect.
11. Calls <code>print(...)</code> for its side effect.
12. Calls <code>print(...)</code> for its side effect.
13. Calls <code>print(...)</code> for its side effect.
14. Assigns <code>(client_info, error)</code> = <code>lookup_client(args.url, args.email)</code>.
15. <i>... and 22 more statement(s) in the body.</i>

```python
def main():
    parser = argparse.ArgumentParser(description='Push MT5 data to Trading Dashboard (No API Key Required!)')
    parser.add_argument('--url', default='https://www.tradeopss.com', help='Dashboard URL')
    parser.add_argument('--email', required=True, help='Your registered client email')
    parser.add_argument('--sheet', help='Google Sheet URL to migrate data from')
    parser.add_argument('--mt5-login', help='MT5 account login')
    parser.add_argument('--mt5-password', help='MT5 account password')
    parser.add_argument('--mt5-server', help='MT5 server name')
    parser.add_argument('--days', type=int, default=30, help='Days of history to fetch')
    
    args = parser.parse_args()
    
    print("=" * 50)
    print("MT5 Data Pusher (No API Key Required!)")
    print("=" * 50)
    
    # Lookup client by email first
    print(f"\n[*] Looking up client: {args.email}")
    client_info, error = lookup_client(args.url, args.email)
    
    if error:
        print(f"\n[✗] Lookup failed: {error}")
        print("    Make sure your email is registered in the system.")
        sys.exit(1)
    
    client_name = client_info.get('client', '')
    trader_name = client_info.get('trader', '')
    admin_name = client_info.get('admin', '')
    category = client_info.get('category', '')
    
    print(f"    ✓ Client: {client_name}")
    print(f"    ✓ Trader: {trader_name}")
    print(f"    ✓ Admin: {admin_name}")
    print(f"    ✓ Category: {category}")
    
    # If sheet URL provided, migrate from sheets
    if args.sheet:
        print(f"\n[*] Migrating data from Google Sheets...")
        success, msg = migrate_sheet(args.url, args.email, args.sheet)
        if success:
            print(f"\n[✓] {msg}")
        else:
            print(f"\n[✗] {msg}")
            sys.exit(1)
        print("\n[*] Done!")
        return
    
    # Otherwise, push MT5 data
    pusher = MT5DataPusher(args.url)
    
    # Connect to MT5 if credentials provided
    if args.mt5_login and args.mt5_password and args.mt5_server:
        print(f"\n[*] Connecting to MT5 account {args.mt5_login}...")
        success, msg = pusher.connect_mt5(args.mt5_login, args.mt5_password, args.mt5_server)
        print(f"    {msg}")
        
        if not success:
            print("\n[!] Failed to connect to MT5. Exiting.")
            sys.exit(1)
    else:
        # Try to connect to already running MT5
        print("\n[*] Connecting to running MT5 terminal...")
        success, msg = pusher.connect_mt5()
        print(f"    {msg}")
        
        if not success:
            print("\n[!] No MT5 connection. Provide --mt5-login, --mt5-password, --mt5-server")
            print("    Or use --sheet to migrate from Google Sheets instead.")
            sys.exit(1)
    
    # Get data
    account = pusher.get_account_info() or {}
    if account:
        print(f"\n[+] Account: #{account.get('login', 'N/A')} @ {account.get('server', 'N/A')}")
        print(f"    Balance: {account.get('balance', 0)} {account.get('currency', '')}")
        print(f"    Equity: {account.get('equity', 0)} {account.get('currency', '')}")
    
    positions = pusher.get_positions()
    deals = pusher.get_deals(days=args.days)
    statistics = pusher.calculate_statistics(deals)
    
    # Push data
    print(f"\n[*] Pushing data for client: {client_name}")
    success, msg = push_data(args.url, args.email, account, positions, deals, statistics)
    
    if success:
        print(f"\n[✓] {msg}")
    else:
        print(f"\n[✗] {msg}")
        sys.exit(1)
    
    # Disconnect
    pusher.disconnect_mt5()
    print("\n[*] Done!")
```

---

### `trader_companion/mt5_dashboard_sync.py`

_840 loc · 1 classes · 1 functions · 5 imports_

**Module docstring**

> MT5 Dashboard Sync Service Syncs MT5 trading history to the TradeConnector Dashboard

**Imports**

```python
import MetaTrader5 as mt5
import requests
import logging
from datetime import datetime, timedelta
import json
```

**Classes**

#### `class MT5DashboardSync`

```python
class MT5DashboardSync:
    def __init__(self, dashboard_url="http://localhost:5000/api", user_email=None):
        """
        Initialize MT5 Dashboard Sync
        
        Args:
            dashboard_url: Base URL for dashboard API
            user_email: User email for authentication
        """
        self.dashboard_url = dashboard_url.rstrip('/')
        self.user_email = user_email
        self.auth_token = None
        self._is_connected = False
        logging.info(f"[MT5 SYNC] Initialized for email: {user_email}")
    
    def set_auth_token(self, token):
        """Set authentication token from dashboard login"""
        self.auth_token = token
        logging.info("[MT5 SYNC] Authentication token set")
    
    def check_dashboard_health(self):
        """
        Check if dashboard backend is running and healthy
        
        Returns:
            dict: {'connected': bool, 'status': str, 'message': str}
        """
        try:
            # Check backend health endpoint
            backend_url = self.dashboard_url.replace('/api', '')
            health_url = f"{backend_url}/health"
            
            response = requests.get(health_url, timeout=3)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'healthy':
                    self._is_connected = True
                    return {
                        'connected': True,
                        'status': 'healthy',
                        'message': 'Dashboard connected',
                        'version': data.get('version', 'unknown')
                    }
            
            self._is_connected = False
            return {
                'connected': False,
                'status': 'unhealthy',
                'message': f'Dashboard responded with status {response.status_code}'
            }
            
        except requests.exceptions.Timeout:
            self._is_connected = False
            return {
                'connected': False,
                'status': 'timeout',
                'message': 'Dashboard connection timeout (3s)'
            }
        except requests.exceptions.ConnectionError:
            self._is_connected = False
            return {
                'connected': False,
                'status': 'error',
                'message': 'Cannot connect to dashboard. Is it running?'
            }
        except Exception as e:
            self._is_connected = False
            return {
                'connected': False,
                'status': 'error',
                'message': f'Health check failed: {str(e)}'
            }
    
    def is_connected(self):
        """Check if dashboard is connected"""
        return self._is_connected
    
    def register_mt5_account(self, mt5_login, mt5_name, mt5_server, broker=None):
        """
        Log MT5 connection - MT5 is only used to extract Tradovate/TopStep data
        
        MT5 account is NOT registered in dashboard. MT5 is simply a data source
        for extracting prop firm account numbers and hedge amounts.
        
        Args:
            mt5_login: MT5 account login number
            mt5_name: MT5 account name
            mt5_server: MT5 server name
            broker: Broker name (optional)
            
        Returns:
            dict: Always returns success
        """
        client_name = f"{mt5_login}: {mt5_name}"
        logging.info(f"[MT5 DATA SOURCE] MT5 connected: {client_name}")
        logging.info(f"[MT5 DATA SOURCE] MT5 will be used to extract Tradovate/TopStep account data")
        return {'success': True, 'message': 'MT5 connected as data source'}
    
    def login(self, email, password):
        """
        Login to dashboard and get authentication token
        
        Args:
            email: User email
            password: User password
            
        Returns:
            dict: {'success': bool, 'token': str, 'error': str}
        """
        try:
            # Demo mode credentials (matches dashboard frontend)
            demo_credentials = {
                'harryodhiambo17@gmail.com': 'demo123',
                'admin@tradeconnector.com': 'admin123',
                'test@example.com': 'test123'
            }
            
            # Check if using demo credentials
            if email in demo_credentials and demo_credentials[email] == password:
                # Generate demo token
                demo_token = f'demo-token-{int(datetime.now().timestamp())}'
                self.auth_token = demo_token
                self.user_email = email
                
                logging.info(f"[MT5 SYNC] Demo login successful for {email}")
                return {
                    'success': True,
                    'token': demo_token,
                    'user': {
                        'email': email,
                        'firstName': 'Harry' if email == 'harryodhiambo17@gmail.com' else 'Demo',
                        'lastName': 'Odhiambo' if email == 'harryodhiambo17@gmail.com' else 'User'
                    }
                }
            
            # Try real API call if not demo credentials
            url = f"{self.dashboard_url}/auth/login"
            payload = {
                'email': email,
                'password': password
            }
            
            logging.info(f"[MT5 SYNC] Attempting login to {url}...")
            response = requests.post(url, json=payload, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                token = data.get('token')
                
                if token:
                    self.auth_token = token
                    self.user_email = email
                    logging.info(f"[MT5 SYNC] Login successful for {email}")
                    return {
                        'success': True,
                        'token': token,
                        'user': data.get('user', {})
                    }
                else:
                    return {
                        'success': False,
                        'error': 'No token received from server'
                    }
            else:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get('error', f'Login failed with status {response.status_code}')
                
                # Add helpful message about demo credentials
                if response.status_code == 401:
                    error_msg += '\\n\\nTry demo credentials:\\nEmail: harryodhiambo17@gmail.com\\nPassword: demo123'
                
                logging.error(f"[MT5 SYNC] Login failed: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }
                
        except requests.exceptions.Timeout:
            logging.error("[MT5 SYNC] Login request timeout")
            return {
                'success': False,
                'error': 'Login request timeout (30s). Dashboard may be slow or not responding.'
            }
        except requests.exceptions.ConnectionError as e:
            logging.error(f"[MT5 SYNC] Connection error: {e}")
            # If connection fails, suggest demo credentials as fallback
            return {
                'success': False,
                'error': f'Cannot connect to dashboard. Try demo credentials instead:\\nEmail: harryodhiambo17@gmail.com\\nPassword: demo123'
            }
        except Exception as e:
            logging.error(f"[MT5 SYNC] Login error: {e}")
            return {
                'success': False,
                'error': f'Login error: {str(e)}'
            }
    
    def get_mt5_history_by_account(self, account_number=None, days_back=7):
        """
        Fetch MT5 trading history filtered by account number (from comment)
        
        Args:
            account_number: Prop firm account number to filter by (optional)
            days_back: Number of days to look back for history (default: 7)
            
        Returns:
            List of trade dictionaries filtered by account number
        """
        try:
            logging.info(f"[MT5 SYNC] Fetching history for last {days_back} days...")
            
            # Check MT5 initialization status FIRST
            terminal_info = mt5.terminal_info()
            if terminal_info is None:
                logging.error("[MT5 SYNC] MT5 terminal_info() returned None - MT5 not initialized")
                if not mt5.initialize():
                    logging.error("[MT5 SYNC] Failed to initialize MT5")
                    return []
                else:
                    logging.info("[MT5 SYNC] MT5 initialized successfully")
            else:
                logging.info(f"[MT5 SYNC] MT5 is initialized: {terminal_info.connected}")
            
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            # Get deals (closed trades)
            logging.info(f"[MT5 SYNC] Requesting deals from {start_date.strftime('%Y-%m-%d %H:%M:%S')} to {end_date.strftime('%Y-%m-%d %H:%M:%S')}...")
            deals = mt5.history_deals_get(start_date, end_date)
            
            if deals is None:
                logging.warning("[MT5 SYNC] MT5 returned None for deals - check MT5 connection")
                logging.warning(f"[MT5 SYNC] MT5 last error: {mt5.last_error()}")
                return []
            
            if len(deals) == 0:
                logging.warning("[MT5 SYNC] No deals found in specified period")
                logging.warning(f"[MT5 SYNC] Checked period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
                logging.warning(f"[MT5 SYNC] Try checking MT5 'Account History' tab to verify trades exist")
                return []
            
            logging.info(f"[MT5 SYNC] Found {len(deals)} deals, processing into trades...")
            logging.info(f"[MT5 SYNC] First deal sample: ticket={deals[0].ticket if deals else 'N/A'}, time={deals[0].time if deals else 'N/A'}, comment='{deals[0].comment if deals else 'N/A'}'")
            
            
            # Process deals into trade format
            trades = []
            deal_pairs = {}  # Group entry and exit deals
            
            for deal in deals:
                # Skip balance operations
                if deal.type not in [mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL]:
                    continue
                
                # Filter by account number if specified (comment contains account number)
                if account_number:
                    comment = deal.comment or ''
                    if account_number not in comment:
                        continue
                
                position_id = deal.position_id
                
                if position_id not in deal_pairs:
                    deal_pairs[position_id] = {'entry': None, 'exit': None}
                
                # Determine if this is entry or exit
                if deal.entry == mt5.DEAL_ENTRY_IN:
                    deal_pairs[position_id]['entry'] = deal
                elif deal.entry == mt5.DEAL_ENTRY_OUT:
                    deal_pairs[position_id]['exit'] = deal
            
            # Combine entry/exit pairs into complete trades
            for position_id, pair in deal_pairs.items():
                if pair['entry'] and pair['exit']:
                    entry = pair['entry']
                    exit_deal = pair['exit']
                    
                    # Extract account info from comment
                    comment = entry.comment or ''
                    account_info = self._extract_account_from_comment(comment)
                    
                    # Debug log first few comments to understand format
                    if len(trades) < 5:
                        logging.info(f"[MT5 SYNC DEBUG] Trade {position_id} comment: '{comment}' -> Account: '{account_info['accountNumber']}', Firm: '{account_info['propFirm']}'")
                    
                    trade = {
                        'ticket': position_id,
                        'symbol': entry.symbol,
                        'type': 'buy' if entry.type == mt5.DEAL_TYPE_BUY else 'sell',
                        'volume': entry.volume,
                        'openPrice': entry.price,
                        'closePrice': exit_deal.price,
                        'openTime': datetime.fromtimestamp(entry.time).isoformat(),
                        'closeTime': datetime.fromtimestamp(exit_deal.time).isoformat(),
                        'profit': exit_deal.profit,
                        'commission': entry.commission + exit_deal.commission,
                        'swap': entry.swap + exit_deal.swap,
                        'comment': comment,
                        'accountNumber': account_info['accountNumber'],
                        'propFirm': account_info['propFirm']
                    }
                    
                    trades.append(trade)
            
            logging.info(f"[MT5 SYNC] Fetched {len(trades)} completed trades")
            if account_number:
                logging.info(f"[MT5 SYNC] Filtered for account: {account_number}")
            return trades
            
        except Exception as e:
            logging.error(f"[MT5 SYNC] Error fetching MT5 history: {e}")
            return []
    
    def _extract_account_from_comment(self, comment):
        """
        Extract account number and prop firm from MT5 comment
        
        Supported formats:
        - TopStep: 'PA-TS123456', 'TS123456', 'PA123456', or variations
        - Tradovate: 'TRDV123456', 'TV123456', or variations  
        - Generic: Treats any alphanumeric string as account number
        - Empty: Returns empty account number (trade will be skipped)
        - With Phase: 'ACCOUNT_CH1', 'ACCOUNT_FD1', etc. (phase suffix is stripped)
        
        Returns:
            dict: {'accountNumber': str, 'propFirm': str}
        """
        if not comment or not comment.strip():
            return {'accountNumber': '', 'propFirm': 'Unknown'}
        
        comment = comment.strip()
        
        # Strip phase abbreviation suffix if present (e.g., _CH1, _FD2, _DD3, _FA)
        # This must be done BEFORE other processing
        import re
        if '_' in comment:
            # Check for numbered formats (_CH1-4, _FD1-4, _DD1-4)
            if re.search(r'_(CH|FD|DD)\d+$', comment):
                comment = re.sub(r'_(CH|FD|DD)\d+$', '', comment)
            # Check for simple farming format: _FA
            elif comment.endswith('_FA'):
                comment = comment[:-3]
            # Check for unknown phase marker
            elif comment.endswith('_UNK'):
                comment = comment[:-4]
        
        # Remove common noise characters
        clean_comment = comment.replace('#', '').replace('/', '').strip()

        # Quick heuristic: detect Other-mode combined comments that start
        # with an account identifier then an underscore and a prop-firm token
        # Example: '123456_PropFirm_Challenge_T1' -> account=123456, propFirm=PropFirm
        try:
            parts = clean_comment.split('_')
            if len(parts) >= 2:
                first = parts[0].strip()
                second = parts[1].strip()
                # First part looks like a numeric account or contains known prefixes
                if re.match(r'^[0-9]{3,}$', first) or any(k in first.upper() for k in ['TRDV', 'TV', 'TS', 'PA']):
                    return {'accountNumber': first, 'propFirm': second}
        except Exception:
            # If anything goes wrong with this heuristic, continue with normal parsing
            pass

        # Check for TopStep patterns (PA-, TS, TopStep keywords)
        if any(keyword in clean_comment.upper() for keyword in ['TS', 'TOPSTEP', 'PA-', 'PA ']):
            # Extract just the numeric part or full account number
            import re
            # Try to find PA-XXXXX or TS-XXXXX pattern
            match = re.search(r'(?:PA-?|TS-?)([A-Z0-9]+)', clean_comment.upper())
            if match:
                account_num = match.group(1)
            else:
                # Remove all prefix keywords and get what's left
                account_num = clean_comment.upper()
                for prefix in ['PA-', 'PA ', 'TS-', 'TS ', 'TOPSTEP-', 'TOPSTEP ']:
                    account_num = account_num.replace(prefix, '')
                account_num = account_num.strip()
            
            return {'accountNumber': account_num, 'propFirm': 'TopStep'}
        
        # Check for Tradovate patterns (TRDV, TV, Tradovate keywords)
        if any(keyword in clean_comment.upper() for keyword in ['TRDV', 'TV', 'TRADOVATE']):
            import re
            # Try to find TRDV-XXXXX or TV-XXXXX pattern
            match = re.search(r'(?:TRDV-?|TV-?)([A-Z0-9]+)', clean_comment.upper())
            if match:
                account_num = match.group(1)
            else:
                # Remove all prefix keywords
                account_num = clean_comment.upper()
                for prefix in ['TRDV-', 'TRDV ', 'TV-', 'TV ', 'TRADOVATE-', 'TRADOVATE ']:
                    account_num = account_num.replace(prefix, '')
                account_num = account_num.strip()
            
            return {'accountNumber': account_num, 'propFirm': 'Tradovate'}
        
        # If no specific pattern but comment exists, use it as account number
        # This handles cases where account number is just digits or simple format
        if clean_comment and len(clean_comment) >= 3:  # Minimum reasonable account number length
            return {'accountNumber': clean_comment, 'propFirm': 'Auto-detected'}
        
        # Comment too short or invalid
        return {'accountNumber': '', 'propFirm': 'Unknown'}
    
    def get_mt5_client_info(self):
        """
        Get MT5 account info including client name
        
        Returns:
            dict: {'login': int, 'name': str, 'clientName': str}
                  clientName format: "login: name" (e.g., "3053752: Tyler Turner")
        """
        try:
            if not mt5.initialize():
                logging.error("[MT5 SYNC] Failed to initialize MT5")
                return None
            
            account_info = mt5.account_info()
            if not account_info:
                logging.error("[MT5 SYNC] Failed to get account info")
                return None
            
            client_info = {
                'login': account_info.login,
                'name': account_info.name,
                'clientName': f"{account_info.login}: {account_info.name}"
            }
            
            logging.info(f"[MT5 SYNC] Client: {client_info['clientName']}")
            return client_info
            
        except Exception as e:
            logging.error(f"[MT5 SYNC] Error getting client info: {e}")
            return None
    
    def _determine_phase_from_lotsize(self, lot_size):
        """
        Determine trading phase based on lot size
        
        Different phases use different lot sizes:
        - Evaluation: Smaller lots (e.g., 1.0, 2.0)
        - Funded: Medium lots (e.g., 3.0, 4.0, 5.0)
        - Farming: Larger lots (e.g., 6.0+)
        
        Args:
            lot_size: MT5 lot size
            
        Returns:
            Tuple of (phase, hedge_column_number)
        """
        # These thresholds can be customized based on your strategy
        if lot_size <= 2.0:
            # Evaluation phase - lot sizes 1.0, 2.0
            hedge_num = int(lot_size)  # 1.0 -> hedge 1, 2.0 -> hedge 2, etc.
            return 'evaluation', hedge_num
        elif lot_size <= 5.0:
            # Funded phase - lot sizes 3.0, 4.0, 5.0
            hedge_num = int(lot_size - 2.0)  # 3.0 -> hedge 1, 4.0 -> hedge 2, 5.0 -> hedge 3
            return 'funded', hedge_num
        else:
            # Farming phase - lot sizes 6.0+
            hedge_num = int(lot_size - 5.0)  # 6.0 -> hedge 1, 7.0 -> hedge 2, etc.
            return 'farming', hedge_num
    
    def get_mt5_history(self, days_back=30):
        """
        Fetch all MT5 trading history (backward compatibility)
        
        Args:
            days_back: Number of days to look back for history
            
        Returns:
            List of trade dictionaries
        """
        return self.get_mt5_history_by_account(account_number=None, days_back=days_back)
    
    # MT5 account matching removed - MT5 is only used to extract Tradovate/TopStep account numbers from trade comments
    
    # Account lookup removed - MT5 only extracts trade data, dashboard auto-creates accounts
    
    def auto_discover_and_sync(self):
        """
        Automatically discover all prop firm accounts from MT5 and sync to dashboard.
        
        Process:
        1. Fetch all MT5 trades
        2. Extract unique account numbers from comments
        3. Group trades by account and lot size to determine phase
        4. Auto-create/update accounts in dashboard
        5. Sync all hedge results
        
        Returns:
            dict: Summary of discovery and sync results
        """
        try:
            if not self.user_email or not self.auth_token:
                return {
                    'success': False,
                    'error': 'Not authenticated. Please login first.'
                }
            
            logging.info("[MT5 AUTO-DISCOVER] Starting automatic account discovery...")
            
            # Get MT5 account info
            client_info = self.get_mt5_client_info()
            if not client_info:
                return {
                    'success': False,
                    'error': 'Failed to get MT5 account info'
                }
            
            mt5_account = f"{client_info['login']}: {client_info['name']}"
            logging.info(f"[MT5 AUTO-DISCOVER] MT5 Hedge Account: {mt5_account}")
            
            # Fetch all MT5 trades (last 7 days for faster processing)
            logging.info("[MT5 AUTO-DISCOVER] Fetching MT5 trade history...")
            logging.info(f"[MT5 AUTO-DISCOVER] Calling get_mt5_history_by_account(account_number=None, days_back=7)...")
            all_trades = self.get_mt5_history_by_account(account_number=None, days_back=7)
            logging.info(f"[MT5 AUTO-DISCOVER] get_mt5_history_by_account() returned {len(all_trades) if all_trades else 0} trades")
            
            if not all_trades:
                logging.warning("[MT5 AUTO-DISCOVER] No trades found in MT5 history - check MT5 connection and trade history")
                return {
                    'success': False,
                    'error': 'No trades found in MT5 history (last 7 days)'
                }
            
            logging.info(f"[MT5 AUTO-DISCOVER] Found {len(all_trades)} total trades")
            
            # Group trades by account number and analyze lot sizes
            logging.info("[MT5 AUTO-DISCOVER] Grouping trades by account...")
            accounts_data = {}
            skipped_trades = 0
            
            for trade in all_trades:
                account_num = trade.get('accountNumber', '').strip()
                if not account_num:
                    skipped_trades += 1
                    if skipped_trades <= 3:  # Log first 3 skipped trades
                        logging.warning(f"[MT5 AUTO-DISCOVER] Skipping trade {trade.get('ticket')} - no account number. Comment: '{trade.get('comment', '')}'")
                    continue
                
                if account_num not in accounts_data:
                    accounts_data[account_num] = {
                        'trades': [],
                        'lot_sizes': set(),
                        'propFirm': trade.get('propFirm', 'Auto-detected'),
                        'phases': {}  # phase -> {trades, total_pnl, hedge_columns}
                    }
                
                accounts_data[account_num]['trades'].append(trade)
                accounts_data[account_num]['lot_sizes'].add(trade['volume'])
                
                # Update prop firm if we detect a more specific one
                if trade.get('propFirm') and trade['propFirm'] != 'Unknown' and trade['propFirm'] != 'Auto-detected':
                    accounts_data[account_num]['propFirm'] = trade['propFirm']
            
            # Log summary of skipped trades
            if skipped_trades > 0:
                logging.warning(f"[MT5 AUTO-DISCOVER] ⚠️  Skipped {skipped_trades} of {len(all_trades)} trades (no account number in comment)")
                logging.warning(f"[MT5 AUTO-DISCOVER] Successfully extracted {len(accounts_data)} unique accounts from {len(all_trades) - skipped_trades} trades")
            else:
                logging.info(f"[MT5 AUTO-DISCOVER] ✓ Successfully extracted all {len(all_trades)} trades into {len(accounts_data)} accounts")
                
                # Determine phase from lot size
                phase, hedge_num = self._determine_phase_from_lotsize(trade['volume'])
                
                if phase not in accounts_data[account_num]['phases']:
                    accounts_data[account_num]['phases'][phase] = {
                        'trades': [],
                        'hedge_columns': {},
                        'total_pnl': 0
                    }
                
                # Add to hedge column
                if hedge_num not in accounts_data[account_num]['phases'][phase]['hedge_columns']:
                    accounts_data[account_num]['phases'][phase]['hedge_columns'][hedge_num] = {
                        'trades': [],
                        'pnl': 0
                    }
                
                accounts_data[account_num]['phases'][phase]['hedge_columns'][hedge_num]['trades'].append(trade)
                accounts_data[account_num]['phases'][phase]['hedge_columns'][hedge_num]['pnl'] += trade['profit']
                accounts_data[account_num]['phases'][phase]['total_pnl'] += trade['profit']
            
            if skipped_trades > 0:
                logging.warning(f"[MT5 AUTO-DISCOVER] Skipped {skipped_trades} trades with no account number")
            
            logging.info(f"[MT5 AUTO-DISCOVER] Discovered {len(accounts_data)} unique accounts:")
            
            # Count TopStep vs Tradovate
            topstep_count = sum(1 for d in accounts_data.values() if d['propFirm'] == 'TopStep')
            tradovate_count = sum(1 for d in accounts_data.values() if d['propFirm'] == 'Tradovate')
            
            logging.info(f"  TopStep Accounts: {topstep_count}")
            logging.info(f"  Tradovate Accounts: {tradovate_count}")
            logging.info(f"  Other Accounts: {len(accounts_data) - topstep_count - tradovate_count}")
            
            results = {
                'success': True,
                'mt5Account': mt5_account,
                'totalTrades': len(all_trades),
                'accountsDiscovered': len(accounts_data),
                'topStepCount': topstep_count,
                'tradovateCount': tradovate_count,
                'accounts': []
            }
            
            # Process each account
            for account_num, data in accounts_data.items():
                prop_firm = data['propFirm']
                logging.info(f"\n[MT5 AUTO-DISCOVER] Account: {account_num} ({prop_firm})")
                logging.info(f"  Total Trades: {len(data['trades'])}")
                logging.info(f"  Lot Sizes: {sorted(data['lot_sizes'])}")
                logging.info(f"  Phases Detected: {list(data['phases'].keys())}")
                
                account_result = {
                    'accountNumber': account_num,
                    'propFirm': prop_firm,
                    'totalTrades': len(data['trades']),
                    'phases': {}
                }
                
                # Sync each phase for this account
                for phase, phase_data in data['phases'].items():
                    logging.info(f"\n  Phase: {phase}")
                    logging.info(f"    Trades: {len(phase_data['trades'])}")
                    logging.info(f"    Hedge Columns: {sorted(phase_data['hedge_columns'].keys())}")
                    logging.info(f"    Total P&L: ${phase_data['total_pnl']:.2f}")
                    
                    # Prepare hedge results for this phase
                    hedge_results = {}
                    for hedge_num, hedge_data in phase_data['hedge_columns'].items():
                        hedge_amount = hedge_data['pnl']
                        logging.info(f"      Hedge {hedge_num}: {len(hedge_data['trades'])} trades, ${hedge_amount:.2f}")
                        
                        if phase == 'farming':
                            # Farming uses propDay and hedgeDay — store clean numeric, no $ prefix
                            hedge_results[f'hedgeDay{hedge_num}'] = f"{hedge_amount:.2f}"
                            logging.info(f"        → Dashboard field: hedgeDay{hedge_num} = ${hedge_amount:.2f}")
                        else:
                            # Evaluation and Funded use hedgeResult — store clean numeric, no $ prefix
                            hedge_results[f'hedgeResult{hedge_num}'] = f"{hedge_amount:.2f}"
                            logging.info(f"        → Dashboard field: hedgeResult{hedge_num} = ${hedge_amount:.2f}")
                    
                    # Add net total — store clean numeric, no $ prefix
                    if phase == 'farming':
                        hedge_results['farmingNet'] = f"{phase_data['total_pnl']:.2f}"
                    else:
                        hedge_results['hedgeNet'] = f"{phase_data['total_pnl']:.2f}"
                    
                    account_result['phases'][phase] = {
                        'trades': len(phase_data['trades']),
                        'hedgeColumns': sorted(phase_data['hedge_columns'].keys()),
                        'totalPnL': phase_data['total_pnl'],
                        'hedgeResults': hedge_results
                    }
                
                results['accounts'].append(account_result)
            
            # Send all data to dashboard for auto-creation/update
            logging.info(f"\n[MT5 AUTO-DISCOVER] Sending discovery data to dashboard...")
            
            headers = {
                'Authorization': f'Bearer {self.auth_token}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'email': self.user_email,
                'mt5Account': mt5_account,
                'accountsData': results['accounts'],
                'allTrades': all_trades
            }
            
            url = f"{self.dashboard_url}/mt5-sync/auto-discover"
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                api_result = response.json()
                results['syncResult'] = api_result
                logging.info(f"[MT5 AUTO-DISCOVER] Success! {api_result.get('message', 'Accounts synced')}")
                return results
            else:
                error_msg = f"Auto-discover sync failed: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', error_msg)
                except:
                    pass
                
                logging.error(f"[MT5 AUTO-DISCOVER] {error_msg}")
                results['success'] = False
                results['error'] = error_msg
                return results
                
        except Exception as e:
            logging.error(f"[MT5 AUTO-DISCOVER] Error: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e)
            }
    
    def sync_to_dashboard(self, account_number=None, phase=None, prop_firm=None):
        """
        Extract Tradovate/TopStep account numbers and hedge amounts from MT5 trades
        
        MT5 is ONLY used to extract:
        1. Prop firm account numbers from trade comments (Tradovate, TopStep)
        2. Hedge amounts based on lot sizes
        3. Trade P&L per hedge column
        
        MT5 account is NOT matched - just extract data and send to auto-discover.
        Use auto_discover_and_sync() instead for full automation.
        
        Args:
            account_number: Prop firm account number (optional)
            phase: Trading phase (optional)
            prop_firm: Prop firm name (optional)
            
        Returns:
            dict: Sync result (redirects to auto-discover)
        """
        logging.info("[MT5 SYNC] Redirecting to auto-discover for full account extraction...")
        return self.auto_discover_and_sync()
    
    def get_sync_status(self, account_number):
        """
        Get sync status for an account
        
        Args:
            account_number: Prop firm account number
            
        Returns:
            dict: Sync status
        """
        try:
            if not self.auth_token:
                return {
                    'success': False,
                    'error': 'Not authenticated'
                }
            
            headers = {
                'Authorization': f'Bearer {self.auth_token}'
            }
            
            url = f"{self.dashboard_url}/mt5-sync/account/{account_number}"
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    'success': False,
                    'error': f'Status check failed: {response.status_code}'
                }
                
        except Exception as e:
            logging.error(f"[MT5 SYNC] Error checking sync status: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def auto_sync_all_accounts(self, accounts_config):
        """
        Automatically sync all configured accounts
        
        Args:
            accounts_config: List of account dictionaries with:
                - accountNumber
                - phase
                - propFirm
                
        Returns:
            dict: Summary of sync results
        """
        results = {
            'total': len(accounts_config),
            'success': 0,
            'failed': 0,
            'details': []
        }
        
        for account in accounts_config:
            account_number = account.get('accountNumber')
            phase = account.get('phase')
            prop_firm = account.get('propFirm')
            
            logging.info(f"[MT5 SYNC] Auto-syncing account {account_number} ({phase})")
            
            result = self.sync_to_dashboard(account_number, phase, prop_firm)
            
            if result.get('success'):
                results['success'] += 1
            else:
                results['failed'] += 1
            
            results['details'].append({
                'accountNumber': account_number,
                'phase': phase,
                'result': result
            })
        
        logging.info(f"[MT5 SYNC] Auto-sync complete: {results['success']}/{results['total']} successful")
        
        return results
```

##### `MT5DashboardSync.__init__`

```python
def __init__(self, dashboard_url='http://localhost:5000/api', user_email=None)
```
> Initialize MT5 Dashboard Sync  Args:     dashboard_url: Base URL for dashboard API     user_email: User email for authentication

**What it does, step by step:**

1. Assigns <code>self.dashboard_url</code> = <code>dashboard_url.rstrip('/')</code>.
2. Assigns <code>self.user_email</code> = <code>user_email</code>.
3. Assigns <code>self.auth_token</code> = <code>None</code>.
4. Assigns <code>self._is_connected</code> = <code>False</code>.
5. Calls <code>logging.info(...)</code> for its side effect.

```python
def __init__(self, dashboard_url="http://localhost:5000/api", user_email=None):
        """
        Initialize MT5 Dashboard Sync
        
        Args:
            dashboard_url: Base URL for dashboard API
            user_email: User email for authentication
        """
        self.dashboard_url = dashboard_url.rstrip('/')
        self.user_email = user_email
        self.auth_token = None
        self._is_connected = False
        logging.info(f"[MT5 SYNC] Initialized for email: {user_email}")
```

##### `MT5DashboardSync.set_auth_token`

```python
def set_auth_token(self, token)
```
> Set authentication token from dashboard login

**What it does, step by step:**

1. Assigns <code>self.auth_token</code> = <code>token</code>.
2. Calls <code>logging.info(...)</code> for its side effect.

```python
def set_auth_token(self, token):
        """Set authentication token from dashboard login"""
        self.auth_token = token
        logging.info("[MT5 SYNC] Authentication token set")
```

##### `MT5DashboardSync.check_dashboard_health`

```python
def check_dashboard_health(self)
```
> Check if dashboard backend is running and healthy  Returns:     dict: {'connected': bool, 'status': str, 'message': str}

**What it does, step by step:**

1. <b>try</b> block with 3 <b>except</b> clauses.

```python
def check_dashboard_health(self):
        """
        Check if dashboard backend is running and healthy
        
        Returns:
            dict: {'connected': bool, 'status': str, 'message': str}
        """
        try:
            # Check backend health endpoint
            backend_url = self.dashboard_url.replace('/api', '')
            health_url = f"{backend_url}/health"
            
            response = requests.get(health_url, timeout=3)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'healthy':
                    self._is_connected = True
                    return {
                        'connected': True,
                        'status': 'healthy',
                        'message': 'Dashboard connected',
                        'version': data.get('version', 'unknown')
                    }
            
            self._is_connected = False
            return {
                'connected': False,
                'status': 'unhealthy',
                'message': f'Dashboard responded with status {response.status_code}'
            }
            
        except requests.exceptions.Timeout:
            self._is_connected = False
            return {
                'connected': False,
                'status': 'timeout',
                'message': 'Dashboard connection timeout (3s)'
            }
        except requests.exceptions.ConnectionError:
            self._is_connected = False
            return {
                'connected': False,
                'status': 'error',
                'message': 'Cannot connect to dashboard. Is it running?'
            }
        except Exception as e:
            self._is_connected = False
            return {
                'connected': False,
                'status': 'error',
                'message': f'Health check failed: {str(e)}'
            }
```

##### `MT5DashboardSync.is_connected`

```python
def is_connected(self)
```
> Check if dashboard is connected

**What it does, step by step:**

1. <b>return</b> <code>self._is_connected</code>.

```python
def is_connected(self):
        """Check if dashboard is connected"""
        return self._is_connected
```

##### `MT5DashboardSync.register_mt5_account`

```python
def register_mt5_account(self, mt5_login, mt5_name, mt5_server, broker=None)
```
> Log MT5 connection - MT5 is only used to extract Tradovate/TopStep data  MT5 account is NOT registered in dashboard. MT5 is simply a data source for extracting prop firm account numbers and hedge amounts.  Args:     mt5_login: MT5 account login number     mt5_name: MT5 account name     mt5_server: MT5 server name     broker: Broker name (optional)      Returns:     dict: Always returns success

**What it does, step by step:**

1. Assigns <code>client_name</code> = <code>f'{mt5_login}: {mt5_name}'</code>.
2. Calls <code>logging.info(...)</code> for its side effect.
3. Calls <code>logging.info(...)</code> for its side effect.
4. <b>return</b> <code>{'success': True, 'message': 'MT5 connected as data source'}</code>.

```python
def register_mt5_account(self, mt5_login, mt5_name, mt5_server, broker=None):
        """
        Log MT5 connection - MT5 is only used to extract Tradovate/TopStep data
        
        MT5 account is NOT registered in dashboard. MT5 is simply a data source
        for extracting prop firm account numbers and hedge amounts.
        
        Args:
            mt5_login: MT5 account login number
            mt5_name: MT5 account name
            mt5_server: MT5 server name
            broker: Broker name (optional)
            
        Returns:
            dict: Always returns success
        """
        client_name = f"{mt5_login}: {mt5_name}"
        logging.info(f"[MT5 DATA SOURCE] MT5 connected: {client_name}")
        logging.info(f"[MT5 DATA SOURCE] MT5 will be used to extract Tradovate/TopStep account data")
        return {'success': True, 'message': 'MT5 connected as data source'}
```

##### `MT5DashboardSync.login`

```python
def login(self, email, password)
```
> Login to dashboard and get authentication token  Args:     email: User email     password: User password      Returns:     dict: {'success': bool, 'token': str, 'error': str}

**What it does, step by step:**

1. <b>try</b> block with 3 <b>except</b> clauses.

```python
def login(self, email, password):
        """
        Login to dashboard and get authentication token
        
        Args:
            email: User email
            password: User password
            
        Returns:
            dict: {'success': bool, 'token': str, 'error': str}
        """
        try:
            # Demo mode credentials (matches dashboard frontend)
            demo_credentials = {
                'harryodhiambo17@gmail.com': 'demo123',
                'admin@tradeconnector.com': 'admin123',
                'test@example.com': 'test123'
            }
            
            # Check if using demo credentials
            if email in demo_credentials and demo_credentials[email] == password:
                # Generate demo token
                demo_token = f'demo-token-{int(datetime.now().timestamp())}'
                self.auth_token = demo_token
                self.user_email = email
                
                logging.info(f"[MT5 SYNC] Demo login successful for {email}")
                return {
                    'success': True,
                    'token': demo_token,
                    'user': {
                        'email': email,
                        'firstName': 'Harry' if email == 'harryodhiambo17@gmail.com' else 'Demo',
                        'lastName': 'Odhiambo' if email == 'harryodhiambo17@gmail.com' else 'User'
                    }
                }
            
            # Try real API call if not demo credentials
            url = f"{self.dashboard_url}/auth/login"
            payload = {
                'email': email,
                'password': password
            }
            
            logging.info(f"[MT5 SYNC] Attempting login to {url}...")
            response = requests.post(url, json=payload, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                token = data.get('token')
                
                if token:
                    self.auth_token = token
                    self.user_email = email
                    logging.info(f"[MT5 SYNC] Login successful for {email}")
                    return {
                        'success': True,
                        'token': token,
                        'user': data.get('user', {})
                    }
                else:
                    return {
                        'success': False,
                        'error': 'No token received from server'
                    }
            else:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get('error', f'Login failed with status {response.status_code}')
                
                # Add helpful message about demo credentials
                if response.status_code == 401:
                    error_msg += '\\n\\nTry demo credentials:\\nEmail: harryodhiambo17@gmail.com\\nPassword: demo123'
                
                logging.error(f"[MT5 SYNC] Login failed: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }
                
        except requests.exceptions.Timeout:
            logging.error("[MT5 SYNC] Login request timeout")
            return {
                'success': False,
                'error': 'Login request timeout (30s). Dashboard may be slow or not responding.'
            }
        except requests.exceptions.ConnectionError as e:
            logging.error(f"[MT5 SYNC] Connection error: {e}")
            # If connection fails, suggest demo credentials as fallback
            return {
                'success': False,
                'error': f'Cannot connect to dashboard. Try demo credentials instead:\\nEmail: harryodhiambo17@gmail.com\\nPassword: demo123'
            }
        except Exception as e:
            logging.error(f"[MT5 SYNC] Login error: {e}")
            return {
                'success': False,
                'error': f'Login error: {str(e)}'
            }
```

##### `MT5DashboardSync.get_mt5_history_by_account`

```python
def get_mt5_history_by_account(self, account_number=None, days_back=7)
```
> Fetch MT5 trading history filtered by account number (from comment)  Args:     account_number: Prop firm account number to filter by (optional)     days_back: Number of days to look back for history (default: 7)      Returns:     List of trade dictionaries filtered by account number

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_mt5_history_by_account(self, account_number=None, days_back=7):
        """
        Fetch MT5 trading history filtered by account number (from comment)
        
        Args:
            account_number: Prop firm account number to filter by (optional)
            days_back: Number of days to look back for history (default: 7)
            
        Returns:
            List of trade dictionaries filtered by account number
        """
        try:
            logging.info(f"[MT5 SYNC] Fetching history for last {days_back} days...")
            
            # Check MT5 initialization status FIRST
            terminal_info = mt5.terminal_info()
            if terminal_info is None:
                logging.error("[MT5 SYNC] MT5 terminal_info() returned None - MT5 not initialized")
                if not mt5.initialize():
                    logging.error("[MT5 SYNC] Failed to initialize MT5")
                    return []
                else:
                    logging.info("[MT5 SYNC] MT5 initialized successfully")
            else:
                logging.info(f"[MT5 SYNC] MT5 is initialized: {terminal_info.connected}")
            
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            # Get deals (closed trades)
            logging.info(f"[MT5 SYNC] Requesting deals from {start_date.strftime('%Y-%m-%d %H:%M:%S')} to {end_date.strftime('%Y-%m-%d %H:%M:%S')}...")
            deals = mt5.history_deals_get(start_date, end_date)
            
            if deals is None:
                logging.warning("[MT5 SYNC] MT5 returned None for deals - check MT5 connection")
                logging.warning(f"[MT5 SYNC] MT5 last error: {mt5.last_error()}")
                return []
            
            if len(deals) == 0:
                logging.warning("[MT5 SYNC] No deals found in specified period")
                logging.warning(f"[MT5 SYNC] Checked period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
                logging.warning(f"[MT5 SYNC] Try checking MT5 'Account History' tab to verify trades exist")
                return []
            
            logging.info(f"[MT5 SYNC] Found {len(deals)} deals, processing into trades...")
            logging.info(f"[MT5 SYNC] First deal sample: ticket={deals[0].ticket if deals else 'N/A'}, time={deals[0].time if deals else 'N/A'}, comment='{deals[0].comment if deals else 'N/A'}'")
            
            
            # Process deals into trade format
            trades = []
            deal_pairs = {}  # Group entry and exit deals
            
            for deal in deals:
                # Skip balance operations
                if deal.type not in [mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL]:
                    continue
                
                # Filter by account number if specified (comment contains account number)
                if account_number:
                    comment = deal.comment or ''
                    if account_number not in comment:
                        continue
                
                position_id = deal.position_id
                
                if position_id not in deal_pairs:
                    deal_pairs[position_id] = {'entry': None, 'exit': None}
                
                # Determine if this is entry or exit
                if deal.entry == mt5.DEAL_ENTRY_IN:
                    deal_pairs[position_id]['entry'] = deal
                elif deal.entry == mt5.DEAL_ENTRY_OUT:
                    deal_pairs[position_id]['exit'] = deal
            
            # Combine entry/exit pairs into complete trades
            for position_id, pair in deal_pairs.items():
                if pair['entry'] and pair['exit']:
                    entry = pair['entry']
                    exit_deal = pair['exit']
                    
                    # Extract account info from comment
                    comment = entry.comment or ''
                    account_info = self._extract_account_from_comment(comment)
                    
                    # Debug log first few comments to understand format
                    if len(trades) < 5:
                        logging.info(f"[MT5 SYNC DEBUG] Trade {position_id} comment: '{comment}' -> Account: '{account_info['accountNumber']}', Firm: '{account_info['propFirm']}'")
                    
                    trade = {
                        'ticket': position_id,
                        'symbol': entry.symbol,
                        'type': 'buy' if entry.type == mt5.DEAL_TYPE_BUY else 'sell',
                        'volume': entry.volume,
                        'openPrice': entry.price,
                        'closePrice': exit_deal.price,
                        'openTime': datetime.fromtimestamp(entry.time).isoformat(),
                        'closeTime': datetime.fromtimestamp(exit_deal.time).isoformat(),
                        'profit': exit_deal.profit,
                        'commission': entry.commission + exit_deal.commission,
                        'swap': entry.swap + exit_deal.swap,
                        'comment': comment,
                        'accountNumber': account_info['accountNumber'],
                        'propFirm': account_info['propFirm']
                    }
                    
                    trades.append(trade)
            
            logging.info(f"[MT5 SYNC] Fetched {len(trades)} completed trades")
            if account_number:
                logging.info(f"[MT5 SYNC] Filtered for account: {account_number}")
            return trades
            
        except Exception as e:
            logging.error(f"[MT5 SYNC] Error fetching MT5 history: {e}")
            return []
```

##### `MT5DashboardSync._extract_account_from_comment`

```python
def _extract_account_from_comment(self, comment)
```
> Extract account number and prop firm from MT5 comment  Supported formats: - TopStep: 'PA-TS123456', 'TS123456', 'PA123456', or variations - Tradovate: 'TRDV123456', 'TV123456', or variations   - Generic: Treats any alphanumeric string as account number - Empty: Returns empty account number (trade will be skipped) - With Phase: 'ACCOUNT_CH1', 'ACCOUNT_FD1', etc. (phase suffix is stripped)  Returns:     dict: {'accountNumber': str, 'propFirm': str}

**What it does, step by step:**

1. <b>if</b> <code>not comment or not comment.strip()</code>: branches conditionally.
2. Assigns <code>comment</code> = <code>comment.strip()</code>.
3. Imports <code>re</code> (lazy import inside the function).
4. <b>if</b> <code>'_' in comment</code>: branches conditionally.
5. Assigns <code>clean_comment</code> = <code>comment.replace('#', '').replace('/', '').strip()</code>.
6. <b>try</b> block with 1 <b>except</b> clause.
7. <b>if</b> <code>any((keyword in clean_comment.upper() for keyword in ['TS', 'TOPSTE...</code>: branches conditionally.
8. <b>if</b> <code>any((keyword in clean_comment.upper() for keyword in ['TRDV', 'TV',...</code>: branches conditionally.
9. <b>if</b> <code>clean_comment and len(clean_comment) &gt;= 3</code>: branches conditionally.
10. <b>return</b> <code>{'accountNumber': '', 'propFirm': 'Unknown'}</code>.

```python
def _extract_account_from_comment(self, comment):
        """
        Extract account number and prop firm from MT5 comment
        
        Supported formats:
        - TopStep: 'PA-TS123456', 'TS123456', 'PA123456', or variations
        - Tradovate: 'TRDV123456', 'TV123456', or variations  
        - Generic: Treats any alphanumeric string as account number
        - Empty: Returns empty account number (trade will be skipped)
        - With Phase: 'ACCOUNT_CH1', 'ACCOUNT_FD1', etc. (phase suffix is stripped)
        
        Returns:
            dict: {'accountNumber': str, 'propFirm': str}
        """
        if not comment or not comment.strip():
            return {'accountNumber': '', 'propFirm': 'Unknown'}
        
        comment = comment.strip()
        
        # Strip phase abbreviation suffix if present (e.g., _CH1, _FD2, _DD3, _FA)
        # This must be done BEFORE other processing
        import re
        if '_' in comment:
            # Check for numbered formats (_CH1-4, _FD1-4, _DD1-4)
            if re.search(r'_(CH|FD|DD)\d+$', comment):
                comment = re.sub(r'_(CH|FD|DD)\d+$', '', comment)
            # Check for simple farming format: _FA
            elif comment.endswith('_FA'):
                comment = comment[:-3]
            # Check for unknown phase marker
            elif comment.endswith('_UNK'):
                comment = comment[:-4]
        
        # Remove common noise characters
        clean_comment = comment.replace('#', '').replace('/', '').strip()

        # Quick heuristic: detect Other-mode combined comments that start
        # with an account identifier then an underscore and a prop-firm token
        # Example: '123456_PropFirm_Challenge_T1' -> account=123456, propFirm=PropFirm
        try:
            parts = clean_comment.split('_')
            if len(parts) >= 2:
                first = parts[0].strip()
                second = parts[1].strip()
                # First part looks like a numeric account or contains known prefixes
                if re.match(r'^[0-9]{3,}$', first) or any(k in first.upper() for k in ['TRDV', 'TV', 'TS', 'PA']):
                    return {'accountNumber': first, 'propFirm': second}
        except Exception:
            # If anything goes wrong with this heuristic, continue with normal parsing
            pass

        # Check for TopStep patterns (PA-, TS, TopStep keywords)
        if any(keyword in clean_comment.upper() for keyword in ['TS', 'TOPSTEP', 'PA-', 'PA ']):
            # Extract just the numeric part or full account number
            import re
            # Try to find PA-XXXXX or TS-XXXXX pattern
            match = re.search(r'(?:PA-?|TS-?)([A-Z0-9]+)', clean_comment.upper())
            if match:
                account_num = match.group(1)
            else:
                # Remove all prefix keywords and get what's left
                account_num = clean_comment.upper()
                for prefix in ['PA-', 'PA ', 'TS-', 'TS ', 'TOPSTEP-', 'TOPSTEP ']:
                    account_num = account_num.replace(prefix, '')
                account_num = account_num.strip()
            
            return {'accountNumber': account_num, 'propFirm': 'TopStep'}
        
        # Check for Tradovate patterns (TRDV, TV, Tradovate keywords)
        if any(keyword in clean_comment.upper() for keyword in ['TRDV', 'TV', 'TRADOVATE']):
            import re
            # Try to find TRDV-XXXXX or TV-XXXXX pattern
            match = re.search(r'(?:TRDV-?|TV-?)([A-Z0-9]+)', clean_comment.upper())
            if match:
                account_num = match.group(1)
            else:
                # Remove all prefix keywords
                account_num = clean_comment.upper()
                for prefix in ['TRDV-', 'TRDV ', 'TV-', 'TV ', 'TRADOVATE-', 'TRADOVATE ']:
                    account_num = account_num.replace(prefix, '')
                account_num = account_num.strip()
            
            return {'accountNumber': account_num, 'propFirm': 'Tradovate'}
        
        # If no specific pattern but comment exists, use it as account number
        # This handles cases where account number is just digits or simple format
        if clean_comment and len(clean_comment) >= 3:  # Minimum reasonable account number length
            return {'accountNumber': clean_comment, 'propFirm': 'Auto-detected'}
        
        # Comment too short or invalid
        return {'accountNumber': '', 'propFirm': 'Unknown'}
```

##### `MT5DashboardSync.get_mt5_client_info`

```python
def get_mt5_client_info(self)
```
> Get MT5 account info including client name  Returns:     dict: {'login': int, 'name': str, 'clientName': str}           clientName format: "login: name" (e.g., "3053752: Tyler Turner")

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_mt5_client_info(self):
        """
        Get MT5 account info including client name
        
        Returns:
            dict: {'login': int, 'name': str, 'clientName': str}
                  clientName format: "login: name" (e.g., "3053752: Tyler Turner")
        """
        try:
            if not mt5.initialize():
                logging.error("[MT5 SYNC] Failed to initialize MT5")
                return None
            
            account_info = mt5.account_info()
            if not account_info:
                logging.error("[MT5 SYNC] Failed to get account info")
                return None
            
            client_info = {
                'login': account_info.login,
                'name': account_info.name,
                'clientName': f"{account_info.login}: {account_info.name}"
            }
            
            logging.info(f"[MT5 SYNC] Client: {client_info['clientName']}")
            return client_info
            
        except Exception as e:
            logging.error(f"[MT5 SYNC] Error getting client info: {e}")
            return None
```

##### `MT5DashboardSync._determine_phase_from_lotsize`

```python
def _determine_phase_from_lotsize(self, lot_size)
```
> Determine trading phase based on lot size  Different phases use different lot sizes: - Evaluation: Smaller lots (e.g., 1.0, 2.0) - Funded: Medium lots (e.g., 3.0, 4.0, 5.0) - Farming: Larger lots (e.g., 6.0+)  Args:     lot_size: MT5 lot size      Returns:     Tuple of (phase, hedge_column_number)

**What it does, step by step:**

1. <b>if</b> <code>lot_size &lt;= 2.0</code>: branches conditionally (with an <b>else</b>/elif arm).

```python
def _determine_phase_from_lotsize(self, lot_size):
        """
        Determine trading phase based on lot size
        
        Different phases use different lot sizes:
        - Evaluation: Smaller lots (e.g., 1.0, 2.0)
        - Funded: Medium lots (e.g., 3.0, 4.0, 5.0)
        - Farming: Larger lots (e.g., 6.0+)
        
        Args:
            lot_size: MT5 lot size
            
        Returns:
            Tuple of (phase, hedge_column_number)
        """
        # These thresholds can be customized based on your strategy
        if lot_size <= 2.0:
            # Evaluation phase - lot sizes 1.0, 2.0
            hedge_num = int(lot_size)  # 1.0 -> hedge 1, 2.0 -> hedge 2, etc.
            return 'evaluation', hedge_num
        elif lot_size <= 5.0:
            # Funded phase - lot sizes 3.0, 4.0, 5.0
            hedge_num = int(lot_size - 2.0)  # 3.0 -> hedge 1, 4.0 -> hedge 2, 5.0 -> hedge 3
            return 'funded', hedge_num
        else:
            # Farming phase - lot sizes 6.0+
            hedge_num = int(lot_size - 5.0)  # 6.0 -> hedge 1, 7.0 -> hedge 2, etc.
            return 'farming', hedge_num
```

##### `MT5DashboardSync.get_mt5_history`

```python
def get_mt5_history(self, days_back=30)
```
> Fetch all MT5 trading history (backward compatibility)  Args:     days_back: Number of days to look back for history      Returns:     List of trade dictionaries

**What it does, step by step:**

1. <b>return</b> <code>self.get_mt5_history_by_account(account_number=None, days_back=days...</code>.

```python
def get_mt5_history(self, days_back=30):
        """
        Fetch all MT5 trading history (backward compatibility)
        
        Args:
            days_back: Number of days to look back for history
            
        Returns:
            List of trade dictionaries
        """
        return self.get_mt5_history_by_account(account_number=None, days_back=days_back)
```

##### `MT5DashboardSync.auto_discover_and_sync`

```python
def auto_discover_and_sync(self)
```
> Automatically discover all prop firm accounts from MT5 and sync to dashboard.  Process: 1. Fetch all MT5 trades 2. Extract unique account numbers from comments 3. Group trades by account and lot size to determine phase 4. Auto-create/update accounts in dashboard 5. Sync all hedge results  Returns:     dict: Summary of discovery and sync results

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def auto_discover_and_sync(self):
        """
        Automatically discover all prop firm accounts from MT5 and sync to dashboard.
        
        Process:
        1. Fetch all MT5 trades
        2. Extract unique account numbers from comments
        3. Group trades by account and lot size to determine phase
        4. Auto-create/update accounts in dashboard
        5. Sync all hedge results
        
        Returns:
            dict: Summary of discovery and sync results
        """
        try:
            if not self.user_email or not self.auth_token:
                return {
                    'success': False,
                    'error': 'Not authenticated. Please login first.'
                }
            
            logging.info("[MT5 AUTO-DISCOVER] Starting automatic account discovery...")
            
            # Get MT5 account info
            client_info = self.get_mt5_client_info()
            if not client_info:
                return {
                    'success': False,
                    'error': 'Failed to get MT5 account info'
                }
            
            mt5_account = f"{client_info['login']}: {client_info['name']}"
            logging.info(f"[MT5 AUTO-DISCOVER] MT5 Hedge Account: {mt5_account}")
            
            # Fetch all MT5 trades (last 7 days for faster processing)
            logging.info("[MT5 AUTO-DISCOVER] Fetching MT5 trade history...")
            logging.info(f"[MT5 AUTO-DISCOVER] Calling get_mt5_history_by_account(account_number=None, days_back=7)...")
            all_trades = self.get_mt5_history_by_account(account_number=None, days_back=7)
            logging.info(f"[MT5 AUTO-DISCOVER] get_mt5_history_by_account() returned {len(all_trades) if all_trades else 0} trades")
            
            if not all_trades:
                logging.warning("[MT5 AUTO-DISCOVER] No trades found in MT5 history - check MT5 connection and trade history")
                return {
                    'success': False,
                    'error': 'No trades found in MT5 history (last 7 days)'
                }
            
            logging.info(f"[MT5 AUTO-DISCOVER] Found {len(all_trades)} total trades")
            
            # Group trades by account number and analyze lot sizes
            logging.info("[MT5 AUTO-DISCOVER] Grouping trades by account...")
            accounts_data = {}
            skipped_trades = 0
            
            for trade in all_trades:
                account_num = trade.get('accountNumber', '').strip()
                if not account_num:
                    skipped_trades += 1
                    if skipped_trades <= 3:  # Log first 3 skipped trades
                        logging.warning(f"[MT5 AUTO-DISCOVER] Skipping trade {trade.get('ticket')} - no account number. Comment: '{trade.get('comment', '')}'")
                    continue
                
                if account_num not in accounts_data:
                    accounts_data[account_num] = {
                        'trades': [],
                        'lot_sizes': set(),
                        'propFirm': trade.get('propFirm', 'Auto-detected'),
                        'phases': {}  # phase -> {trades, total_pnl, hedge_columns}
                    }
                
                accounts_data[account_num]['trades'].append(trade)
                accounts_data[account_num]['lot_sizes'].add(trade['volume'])
                
                # Update prop firm if we detect a more specific one
                if trade.get('propFirm') and trade['propFirm'] != 'Unknown' and trade['propFirm'] != 'Auto-detected':
                    accounts_data[account_num]['propFirm'] = trade['propFirm']
            
            # Log summary of skipped trades
            if skipped_trades > 0:
                logging.warning(f"[MT5 AUTO-DISCOVER] ⚠️  Skipped {skipped_trades} of {len(all_trades)} trades (no account number in comment)")
                logging.warning(f"[MT5 AUTO-DISCOVER] Successfully extracted {len(accounts_data)} unique accounts from {len(all_trades) - skipped_trades} trades")
            else:
                logging.info(f"[MT5 AUTO-DISCOVER] ✓ Successfully extracted all {len(all_trades)} trades into {len(accounts_data)} accounts")
                
                # Determine phase from lot size
                phase, hedge_num = self._determine_phase_from_lotsize(trade['volume'])
                
                if phase not in accounts_data[account_num]['phases']:
                    accounts_data[account_num]['phases'][phase] = {
                        'trades': [],
                        'hedge_columns': {},
                        'total_pnl': 0
                    }
                
                # Add to hedge column
                if hedge_num not in accounts_data[account_num]['phases'][phase]['hedge_columns']:
                    accounts_data[account_num]['phases'][phase]['hedge_columns'][hedge_num] = {
                        'trades': [],
                        'pnl': 0
                    }
                
                accounts_data[account_num]['phases'][phase]['hedge_columns'][hedge_num]['trades'].append(trade)
                accounts_data[account_num]['phases'][phase]['hedge_columns'][hedge_num]['pnl'] += trade['profit']
                accounts_data[account_num]['phases'][phase]['total_pnl'] += trade['profit']
            
            if skipped_trades > 0:
                logging.warning(f"[MT5 AUTO-DISCOVER] Skipped {skipped_trades} trades with no account number")
            
            logging.info(f"[MT5 AUTO-DISCOVER] Discovered {len(accounts_data)} unique accounts:")
            
            # Count TopStep vs Tradovate
            topstep_count = sum(1 for d in accounts_data.values() if d['propFirm'] == 'TopStep')
            tradovate_count = sum(1 for d in accounts_data.values() if d['propFirm'] == 'Tradovate')
            
            logging.info(f"  TopStep Accounts: {topstep_count}")
            logging.info(f"  Tradovate Accounts: {tradovate_count}")
            logging.info(f"  Other Accounts: {len(accounts_data) - topstep_count - tradovate_count}")
            
            results = {
                'success': True,
                'mt5Account': mt5_account,
                'totalTrades': len(all_trades),
                'accountsDiscovered': len(accounts_data),
                'topStepCount': topstep_count,
                'tradovateCount': tradovate_count,
                'accounts': []
            }
            
            # Process each account
            for account_num, data in accounts_data.items():
                prop_firm = data['propFirm']
                logging.info(f"\n[MT5 AUTO-DISCOVER] Account: {account_num} ({prop_firm})")
                logging.info(f"  Total Trades: {len(data['trades'])}")
                logging.info(f"  Lot Sizes: {sorted(data['lot_sizes'])}")
                logging.info(f"  Phases Detected: {list(data['phases'].keys())}")
                
                account_result = {
                    'accountNumber': account_num,
                    'propFirm': prop_firm,
                    'totalTrades': len(data['trades']),
                    'phases': {}
                }
                
                # Sync each phase for this account
                for phase, phase_data in data['phases'].items():
                    logging.info(f"\n  Phase: {phase}")
                    logging.info(f"    Trades: {len(phase_data['trades'])}")
                    logging.info(f"    Hedge Columns: {sorted(phase_data['hedge_columns'].keys())}")
                    logging.info(f"    Total P&L: ${phase_data['total_pnl']:.2f}")
                    
                    # Prepare hedge results for this phase
                    hedge_results = {}
                    for hedge_num, hedge_data in phase_data['hedge_columns'].items():
                        hedge_amount = hedge_data['pnl']
                        logging.info(f"      Hedge {hedge_num}: {len(hedge_data['trades'])} trades, ${hedge_amount:.2f}")
                        
                        if phase == 'farming':
                            # Farming uses propDay and hedgeDay — store clean numeric, no $ prefix
                            hedge_results[f'hedgeDay{hedge_num}'] = f"{hedge_amount:.2f}"
                            logging.info(f"        → Dashboard field: hedgeDay{hedge_num} = ${hedge_amount:.2f}")
                        else:
                            # Evaluation and Funded use hedgeResult — store clean numeric, no $ prefix
                            hedge_results[f'hedgeResult{hedge_num}'] = f"{hedge_amount:.2f}"
                            logging.info(f"        → Dashboard field: hedgeResult{hedge_num} = ${hedge_amount:.2f}")
                    
                    # Add net total — store clean numeric, no $ prefix
                    if phase == 'farming':
                        hedge_results['farmingNet'] = f"{phase_data['total_pnl']:.2f}"
                    else:
                        hedge_results['hedgeNet'] = f"{phase_data['total_pnl']:.2f}"
                    
                    account_result['phases'][phase] = {
                        'trades': len(phase_data['trades']),
                        'hedgeColumns': sorted(phase_data['hedge_columns'].keys()),
                        'totalPnL': phase_data['total_pnl'],
                        'hedgeResults': hedge_results
                    }
                
                results['accounts'].append(account_result)
            
            # Send all data to dashboard for auto-creation/update
            logging.info(f"\n[MT5 AUTO-DISCOVER] Sending discovery data to dashboard...")
            
            headers = {
                'Authorization': f'Bearer {self.auth_token}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'email': self.user_email,
                'mt5Account': mt5_account,
                'accountsData': results['accounts'],
                'allTrades': all_trades
            }
            
            url = f"{self.dashboard_url}/mt5-sync/auto-discover"
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                api_result = response.json()
                results['syncResult'] = api_result
                logging.info(f"[MT5 AUTO-DISCOVER] Success! {api_result.get('message', 'Accounts synced')}")
                return results
            else:
                error_msg = f"Auto-discover sync failed: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', error_msg)
                except:
                    pass
                
                logging.error(f"[MT5 AUTO-DISCOVER] {error_msg}")
                results['success'] = False
                results['error'] = error_msg
                return results
                
        except Exception as e:
            logging.error(f"[MT5 AUTO-DISCOVER] Error: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e)
            }
```

##### `MT5DashboardSync.sync_to_dashboard`

```python
def sync_to_dashboard(self, account_number=None, phase=None, prop_firm=None)
```
> Extract Tradovate/TopStep account numbers and hedge amounts from MT5 trades  MT5 is ONLY used to extract: 1. Prop firm account numbers from trade comments (Tradovate, TopStep) 2. Hedge amounts based on lot sizes 3. Trade P&L per hedge column  MT5 account is NOT matched - just extract data and send to auto-discover. Use auto_discover_and_sync() instead for full automation.  Args:     account_number: Prop firm account number (optional)     phase: Trading phase (optional)     prop_firm: Prop firm name (optional)      Returns:     dict: Sync result (redirects to auto-discover)

**What it does, step by step:**

1. Calls <code>logging.info(...)</code> for its side effect.
2. <b>return</b> <code>self.auto_discover_and_sync()</code>.

```python
def sync_to_dashboard(self, account_number=None, phase=None, prop_firm=None):
        """
        Extract Tradovate/TopStep account numbers and hedge amounts from MT5 trades
        
        MT5 is ONLY used to extract:
        1. Prop firm account numbers from trade comments (Tradovate, TopStep)
        2. Hedge amounts based on lot sizes
        3. Trade P&L per hedge column
        
        MT5 account is NOT matched - just extract data and send to auto-discover.
        Use auto_discover_and_sync() instead for full automation.
        
        Args:
            account_number: Prop firm account number (optional)
            phase: Trading phase (optional)
            prop_firm: Prop firm name (optional)
            
        Returns:
            dict: Sync result (redirects to auto-discover)
        """
        logging.info("[MT5 SYNC] Redirecting to auto-discover for full account extraction...")
        return self.auto_discover_and_sync()
```

##### `MT5DashboardSync.get_sync_status`

```python
def get_sync_status(self, account_number)
```
> Get sync status for an account  Args:     account_number: Prop firm account number      Returns:     dict: Sync status

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_sync_status(self, account_number):
        """
        Get sync status for an account
        
        Args:
            account_number: Prop firm account number
            
        Returns:
            dict: Sync status
        """
        try:
            if not self.auth_token:
                return {
                    'success': False,
                    'error': 'Not authenticated'
                }
            
            headers = {
                'Authorization': f'Bearer {self.auth_token}'
            }
            
            url = f"{self.dashboard_url}/mt5-sync/account/{account_number}"
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    'success': False,
                    'error': f'Status check failed: {response.status_code}'
                }
                
        except Exception as e:
            logging.error(f"[MT5 SYNC] Error checking sync status: {e}")
            return {
                'success': False,
                'error': str(e)
            }
```

##### `MT5DashboardSync.auto_sync_all_accounts`

```python
def auto_sync_all_accounts(self, accounts_config)
```
> Automatically sync all configured accounts  Args:     accounts_config: List of account dictionaries with:         - accountNumber         - phase         - propFirm          Returns:     dict: Summary of sync results

**What it does, step by step:**

1. Assigns <code>results</code> = <code>{'total': len(accounts_config), 'success': 0, 'failed': 0...</code>.
2. <b>for</b> <code>account</code> in <code>accounts_config</code>: iterates.
3. Calls <code>logging.info(...)</code> for its side effect.
4. <b>return</b> <code>results</code>.

```python
def auto_sync_all_accounts(self, accounts_config):
        """
        Automatically sync all configured accounts
        
        Args:
            accounts_config: List of account dictionaries with:
                - accountNumber
                - phase
                - propFirm
                
        Returns:
            dict: Summary of sync results
        """
        results = {
            'total': len(accounts_config),
            'success': 0,
            'failed': 0,
            'details': []
        }
        
        for account in accounts_config:
            account_number = account.get('accountNumber')
            phase = account.get('phase')
            prop_firm = account.get('propFirm')
            
            logging.info(f"[MT5 SYNC] Auto-syncing account {account_number} ({phase})")
            
            result = self.sync_to_dashboard(account_number, phase, prop_firm)
            
            if result.get('success'):
                results['success'] += 1
            else:
                results['failed'] += 1
            
            results['details'].append({
                'accountNumber': account_number,
                'phase': phase,
                'result': result
            })
        
        logging.info(f"[MT5 SYNC] Auto-sync complete: {results['success']}/{results['total']} successful")
        
        return results
```

**Functions**

#### `get_mt5_sync`

```python
def get_mt5_sync(dashboard_url='http://localhost:5000/api', user_email=None)
```
> Get or create global MT5 sync instance

**What it does, step by step:**

1. Declares globals: _mt5_sync_instance.
2. <b>if</b> <code>_mt5_sync_instance is None or _mt5_sync_instance.user_email != user...</code>: branches conditionally.
3. <b>return</b> <code>_mt5_sync_instance</code>.

```python
def get_mt5_sync(dashboard_url="http://localhost:5000/api", user_email=None):
    """Get or create global MT5 sync instance"""
    global _mt5_sync_instance
    
    if _mt5_sync_instance is None or _mt5_sync_instance.user_email != user_email:
        _mt5_sync_instance = MT5DashboardSync(dashboard_url, user_email)
    
    return _mt5_sync_instance
```

---
