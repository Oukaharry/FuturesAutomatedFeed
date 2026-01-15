"""
MT5 Trader Companion App
A desktop application for traders to push their MT5 data to the Trading Dashboard.
"""
import sys
import os
import json
import requests
import time
from datetime import datetime
import threading

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False
    print("Tkinter not available - running in console mode")

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    print("MetaTrader5 module not found. Install with: pip install MetaTrader5")


class MT5DataPusher:
    """Handles MT5 data extraction and API pushing."""
    
    def __init__(self, dashboard_url="http://127.0.0.1:5001", api_key=None):
        self.dashboard_url = dashboard_url.rstrip('/')
        self.api_key = api_key
        self.connected = False
        self.login = None
        self.server = None
        
    def connect_mt5(self, login=None, password=None, server=None, terminal_path=None):
        """Connect to MT5 terminal."""
        if not MT5_AVAILABLE:
            return False, "MetaTrader5 module not installed"
        
        init_params = {}
        if terminal_path:
            init_params['path'] = terminal_path
            
        if not mt5.initialize(**init_params):
            error = mt5.last_error()
            return False, f"MT5 initialization failed: {error}"
        
        if login and password and server:
            try:
                login_int = int(login)
            except ValueError:
                return False, "Login must be a number"
                
            if not mt5.login(login_int, password=password, server=server):
                error = mt5.last_error()
                return False, f"MT5 login failed: {error}"
            
            self.login = login_int
            self.server = server
        
        self.connected = True
        account = mt5.account_info()
        if account:
            return True, f"Connected to account #{account.login} ({account.server})"
        return True, "Connected to MT5 (no account logged in)"
    
    def disconnect_mt5(self):
        """Disconnect from MT5."""
        if MT5_AVAILABLE:
            mt5.shutdown()
        self.connected = False
        return True, "Disconnected from MT5"
    
    def get_account_info(self):
        """Get account information."""
        if not self.connected:
            return None
        
        account = mt5.account_info()
        if not account:
            return None
            
        return {
            "login": account.login,
            "server": account.server,
            "balance": account.balance,
            "equity": account.equity,
            "profit": account.profit,
            "margin": account.margin,
            "margin_free": account.margin_free,
            "margin_level": account.margin_level if account.margin > 0 else 0,
            "leverage": account.leverage,
            "currency": account.currency,
            "name": account.name,
            "company": account.company
        }
    
    def get_positions(self):
        """Get open positions."""
        if not self.connected:
            return []
        
        positions = mt5.positions_get()
        if positions is None:
            return []
        
        result = []
        for pos in positions:
            result.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "type": "BUY" if pos.type == 0 else "SELL",
                "volume": pos.volume,
                "price_open": pos.price_open,
                "price_current": pos.price_current,
                "sl": pos.sl,
                "tp": pos.tp,
                "profit": pos.profit,
                "swap": pos.swap,
                "time": datetime.fromtimestamp(pos.time).isoformat(),
                "magic": pos.magic,
                "comment": pos.comment
            })
        return result
    
    def get_deals(self, days=30):
        """Get deal history."""
        if not self.connected:
            return []
        
        from_timestamp = time.time() - (days * 24 * 3600)
        to_timestamp = time.time() + 86400
        
        deals = mt5.history_deals_get(from_timestamp, to_timestamp)
        if deals is None:
            return []
        
        result = []
        for deal in deals:
            result.append({
                "ticket": deal.ticket,
                "order": deal.order,
                "position_id": deal.position_id,
                "symbol": deal.symbol,
                "type": self._deal_type_to_string(deal.type),
                "entry": self._entry_to_string(deal.entry),
                "volume": deal.volume,
                "price": deal.price,
                "profit": deal.profit,
                "commission": deal.commission,
                "swap": deal.swap,
                "fee": deal.fee,
                "time": datetime.fromtimestamp(deal.time).isoformat(),
                "magic": deal.magic,
                "comment": deal.comment
            })
        return result
    
    def _deal_type_to_string(self, deal_type):
        types = {0: "BUY", 1: "SELL", 2: "BALANCE", 3: "CREDIT", 
                 4: "CHARGE", 5: "CORRECTION", 6: "BONUS"}
        return types.get(deal_type, str(deal_type))
    
    def _entry_to_string(self, entry):
        entries = {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}
        return entries.get(entry, str(entry))
    
    def calculate_statistics(self, deals):
        """Calculate trading statistics from deals."""
        if not deals:
            return {}
        
        # Filter actual trades (not balance operations)
        trades = [d for d in deals if d.get('type') in ['BUY', 'SELL'] and d.get('entry') == 'OUT']
        
        if not trades:
            return {"total_trades": 0}
        
        profits = [t['profit'] for t in trades]
        winning = [p for p in profits if p > 0]
        losing = [p for p in profits if p < 0]
        
        return {
            "total_trades": len(trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": round(len(winning) / len(trades) * 100, 2) if trades else 0,
            "total_profit": round(sum(profits), 2),
            "average_win": round(sum(winning) / len(winning), 2) if winning else 0,
            "average_loss": round(sum(losing) / len(losing), 2) if losing else 0,
            "profit_factor": round(abs(sum(winning) / sum(losing)), 2) if losing and sum(losing) != 0 else 0,
            "largest_win": round(max(winning), 2) if winning else 0,
            "largest_loss": round(min(losing), 2) if losing else 0
        }
    
    def push_to_dashboard(self, client_name, admin_name="", trader_name=""):
        """Push all data to the dashboard."""
        if not self.api_key:
            return False, "API key not set"
        
        account = self.get_account_info()
        positions = self.get_positions()
        deals = self.get_deals(days=30)
        statistics = self.calculate_statistics(deals)
        
        payload = {
            "identity": {
                "admin": admin_name or "Admin",
                "trader": trader_name or "Trader",
                "client": client_name
            },
            "account": account or {},
            "positions": positions,
            "deals": deals,
            "statistics": statistics,
            "evaluations": [],
            "dropdown_options": {}
        }
        
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key
        }
        
        try:
            response = requests.post(
                f"{self.dashboard_url}/api/update_data",
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    return True, f"Data pushed successfully for {client_name}"
                return False, data.get('message', 'Unknown error')
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
                
        except requests.exceptions.ConnectionError:
            return False, f"Cannot connect to dashboard at {self.dashboard_url}"
        except requests.exceptions.Timeout:
            return False, "Request timed out"
        except Exception as e:
            return False, str(e)


class TraderCompanionApp:
    """GUI Application for the Trader Companion."""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("MT5 Trader Companion - No API Key Required")
        self.root.geometry("750x800")
        self.root.configure(bg='#1a1a2e')
        
        self.pusher = MT5DataPusher()
        self.auto_push_enabled = False
        self.auto_push_thread = None
        self.client_info = None  # Stores looked-up hierarchy info
        
        self.setup_ui()
        self.load_config()
        
    def setup_ui(self):
        """Setup the user interface."""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configure styles
        style.configure('TFrame', background='#1a1a2e')
        style.configure('TLabel', background='#1a1a2e', foreground='white', font=('Segoe UI', 10))
        style.configure('TButton', font=('Segoe UI', 10, 'bold'))
        style.configure('Header.TLabel', font=('Segoe UI', 16, 'bold'), foreground='#667eea')
        style.configure('Status.TLabel', font=('Segoe UI', 10), foreground='#16a34a')
        style.configure('Error.TLabel', font=('Segoe UI', 10), foreground='#dc2626')
        
        # Main container
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header = ttk.Label(main_frame, text="📊 MT5 Trader Companion", style='Header.TLabel')
        header.pack(pady=(0, 20))
        
        # Connection Frame
        conn_frame = ttk.LabelFrame(main_frame, text="Dashboard Connection", padding=15)
        conn_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Dashboard URL
        url_frame = ttk.Frame(conn_frame)
        url_frame.pack(fill=tk.X, pady=5)
        ttk.Label(url_frame, text="Dashboard URL:", width=15).pack(side=tk.LEFT)
        self.url_entry = ttk.Entry(url_frame, width=40)
        self.url_entry.insert(0, "https://ballerquotes.pythonanywhere.com")
        self.url_entry.pack(side=tk.LEFT, padx=5)
        
        # Identity Frame - SIMPLIFIED: Just client email (NO API KEY NEEDED)
        id_frame = ttk.LabelFrame(main_frame, text="Client Identification (Email Only - No API Key Required)", padding=15)
        id_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Client Email
        email_frame = ttk.Frame(id_frame)
        email_frame.pack(fill=tk.X, pady=5)
        ttk.Label(email_frame, text="Client Email:", width=15).pack(side=tk.LEFT)
        self.client_email_entry = ttk.Entry(email_frame, width=35)
        self.client_email_entry.pack(side=tk.LEFT, padx=5)
        self.lookup_btn = ttk.Button(email_frame, text="🔍 Lookup", command=self.lookup_client)
        self.lookup_btn.pack(side=tk.LEFT, padx=5)
        
        # Hierarchy Info Display (read-only, populated after lookup)
        self.hierarchy_var = tk.StringVar(value="Enter client email and click 'Lookup' to identify hierarchy")
        self.hierarchy_label = ttk.Label(id_frame, textvariable=self.hierarchy_var, 
                                         font=('Segoe UI', 9, 'italic'), foreground='#888888')
        self.hierarchy_label.pack(fill=tk.X, pady=(10, 5))
        
        # MT5 Frame
        mt5_frame = ttk.LabelFrame(main_frame, text="MT5 Connection (Optional)", padding=15)
        mt5_frame.pack(fill=tk.X, pady=(0, 15))
        
        # MT5 Login
        login_frame = ttk.Frame(mt5_frame)
        login_frame.pack(fill=tk.X, pady=5)
        ttk.Label(login_frame, text="Login:", width=15).pack(side=tk.LEFT)
        self.mt5_login = ttk.Entry(login_frame, width=20)
        self.mt5_login.pack(side=tk.LEFT, padx=5)
        ttk.Label(login_frame, text="Password:").pack(side=tk.LEFT, padx=(20, 0))
        self.mt5_password = ttk.Entry(login_frame, width=20, show="*")
        self.mt5_password.pack(side=tk.LEFT, padx=5)
        
        # MT5 Server
        server_frame = ttk.Frame(mt5_frame)
        server_frame.pack(fill=tk.X, pady=5)
        ttk.Label(server_frame, text="Server:", width=15).pack(side=tk.LEFT)
        self.mt5_server = ttk.Entry(server_frame, width=40)
        self.mt5_server.pack(side=tk.LEFT, padx=5)
        
        # MT5 Connect Button
        self.mt5_btn = ttk.Button(mt5_frame, text="Connect to MT5", command=self.toggle_mt5_connection)
        self.mt5_btn.pack(pady=10)
        
        # Buttons Frame
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=15)
        
        self.push_btn = ttk.Button(btn_frame, text="📤 Push Data Now", command=self.push_data)
        self.push_btn.pack(side=tk.LEFT, padx=5)
        
        self.auto_btn = ttk.Button(btn_frame, text="🔄 Start Auto-Push (5min)", command=self.toggle_auto_push)
        self.auto_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="💾 Save Config", command=self.save_config).pack(side=tk.RIGHT, padx=5)
        
        # Google Sheets Migration Frame
        sheet_frame = ttk.LabelFrame(main_frame, text="📋 Import from Google Sheets", padding=15)
        sheet_frame.pack(fill=tk.X, pady=(0, 15))
        
        sheet_url_frame = ttk.Frame(sheet_frame)
        sheet_url_frame.pack(fill=tk.X, pady=5)
        ttk.Label(sheet_url_frame, text="Sheet URL:", width=12).pack(side=tk.LEFT)
        self.sheet_url_entry = ttk.Entry(sheet_url_frame, width=40)
        self.sheet_url_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        self.migrate_btn = ttk.Button(sheet_frame, text="📥 Import Sheet Data", command=self.migrate_from_sheet)
        self.migrate_btn.pack(pady=10)
        
        ttk.Label(sheet_frame, text="Paste your Google Sheet URL to import existing data (sheet must be public)", 
                  font=('Segoe UI', 8, 'italic'), foreground='#888888').pack()
        
        # Status Frame
        status_frame = ttk.LabelFrame(main_frame, text="Status Log", padding=10)
        status_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.log_text = scrolledtext.ScrolledText(status_frame, height=6, bg='#0f0f1a', fg='#00ff00',
                                                   font=('Consolas', 9), insertbackground='white')
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready - No API key required, just your email!")
        self.status_label = ttk.Label(main_frame, textvariable=self.status_var, style='Status.TLabel')
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)
        
    def log(self, message, level="INFO"):
        """Add a message to the log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = "#00ff00" if level == "INFO" else "#ff6b6b" if level == "ERROR" else "#ffcc00"
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def lookup_client(self):
        """Lookup client hierarchy from email - NO API KEY REQUIRED."""
        email = self.client_email_entry.get().strip()
        dashboard_url = self.url_entry.get().strip().rstrip('/')
        
        if not email:
            messagebox.showerror("Error", "Please enter the client email")
            return
        
        self.log(f"Looking up client: {email}")
        self.hierarchy_var.set("Looking up...")
        self.root.update_idletasks()
        
        try:
            # Use public endpoint - no API key needed
            response = requests.post(
                f"{dashboard_url}/api/client/auth",
                json={"email": email},
                headers={"Content-Type": "application/json"},
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    self.client_info = data.get("identity", {})
                    client = self.client_info.get("client", "Unknown")
                    trader = self.client_info.get("trader", "Unknown")
                    admin = self.client_info.get("admin", "Unknown")
                    category = self.client_info.get("category", "Unknown")
                    
                    self.hierarchy_var.set(f"✅ {client} → Trader: {trader} → Admin: {admin} | Category: {category}")
                    self.hierarchy_label.configure(foreground='#16a34a')
                    self.log(f"✅ Client found: {client} → {trader} → {admin}")
                else:
                    error_msg = data.get("message", "Client not found")
                    self.hierarchy_var.set(f"❌ {error_msg}")
                    self.hierarchy_label.configure(foreground='#dc2626')
                    self.client_info = None
                    self.log(f"❌ Lookup failed: {error_msg}", "ERROR")
            else:
                error_msg = f"API Error: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message", error_msg)
                except:
                    pass
                self.hierarchy_var.set(f"❌ {error_msg}")
                self.hierarchy_label.configure(foreground='#dc2626')
                self.client_info = None
                self.log(f"❌ Lookup failed: {error_msg}", "ERROR")
                
        except requests.exceptions.Timeout:
            self.hierarchy_var.set("❌ Connection timeout")
            self.hierarchy_label.configure(foreground='#dc2626')
            self.log("❌ Connection timeout", "ERROR")
        except requests.exceptions.ConnectionError:
            self.hierarchy_var.set("❌ Cannot connect to server")
            self.hierarchy_label.configure(foreground='#dc2626')
            self.log("❌ Cannot connect to server", "ERROR")
        except Exception as e:
            self.hierarchy_var.set(f"❌ Error: {str(e)}")
            self.hierarchy_label.configure(foreground='#dc2626')
            self.log(f"❌ Error: {e}", "ERROR")
        
    def toggle_mt5_connection(self):
        """Connect or disconnect from MT5."""
        if self.pusher.connected:
            success, msg = self.pusher.disconnect_mt5()
            self.mt5_btn.configure(text="Connect to MT5")
            self.log(msg)
        else:
            login = self.mt5_login.get().strip()
            password = self.mt5_password.get()
            server = self.mt5_server.get().strip()
            
            success, msg = self.pusher.connect_mt5(login, password, server)
            if success:
                self.mt5_btn.configure(text="Disconnect MT5")
            self.log(msg, "INFO" if success else "ERROR")
            
    def push_data(self):
        """Push data to dashboard - NO API KEY REQUIRED."""
        dashboard_url = self.url_entry.get().strip().rstrip('/')
        email = self.client_email_entry.get().strip()
        
        # Use looked-up hierarchy info
        if not self.client_info:
            messagebox.showerror("Error", "Please lookup the client first by entering email and clicking 'Lookup'")
            return
        
        client_name = self.client_info.get('client', '')
        
        if not client_name:
            messagebox.showerror("Error", "Client lookup failed - no client name found")
            return
        
        self.log(f"Pushing data for {client_name}...")
        self.status_var.set("Pushing data...")
        
        # Get MT5 data
        account = self.pusher.get_account_info() or {}
        positions = self.pusher.get_positions()
        deals = self.pusher.get_deals()
        statistics = self.pusher.calculate_statistics(deals)
        
        payload = {
            "email": email,
            "account": account,
            "positions": positions,
            "deals": deals,
            "statistics": statistics,
            "evaluations": [],
            "dropdown_options": {}
        }
        
        try:
            # Use public endpoint - no API key needed
            response = requests.post(
                f"{dashboard_url}/api/client/push",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    self.log(f"✅ {data.get('message', 'Data pushed successfully')}")
                    self.status_var.set("Ready - Data pushed!")
                else:
                    self.log(f"❌ {data.get('message', 'Push failed')}", "ERROR")
                    self.status_var.set("Push failed")
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_msg = response.json().get("message", error_msg)
                except:
                    pass
                self.log(f"❌ Push failed: {error_msg}", "ERROR")
                self.status_var.set("Push failed")
                
        except Exception as e:
            self.log(f"❌ Push error: {e}", "ERROR")
            self.status_var.set("Push failed")
    
    def migrate_from_sheet(self):
        """Migrate data from Google Sheets to the dashboard with verification."""
        email = self.client_email_entry.get().strip()
        sheet_url = self.sheet_url_entry.get().strip()
        dashboard_url = self.url_entry.get().strip().rstrip('/')
        
        if not email:
            messagebox.showerror("Error", "Please enter your client email first")
            return
        
        if not sheet_url:
            messagebox.showerror("Error", "Please enter the Google Sheet URL")
            return
        
        if 'docs.google.com/spreadsheets' not in sheet_url:
            messagebox.showerror("Error", "Please enter a valid Google Sheets URL")
            return
        
        self.log(f"Step 1: Fetching data from Google Sheets...")
        self.status_var.set("Fetching sheet data...")
        self.root.update_idletasks()
        
        try:
            # Step 1: Fetch and calculate locally first
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from utils.data_processor import fetch_evaluations, calculate_statistics
            
            evaluations = fetch_evaluations(sheet_url)
            if not evaluations:
                self.log("❌ Could not fetch data from sheet. Make sure it's public.", "ERROR")
                messagebox.showerror("Error", "Could not fetch data from sheet. Make sure it's public.")
                return
            
            self.log(f"   Fetched {len(evaluations)} evaluation records")
            
            # Calculate local stats
            local_stats = calculate_statistics(evaluations)
            self.log(f"Step 2: Calculated local statistics")
            
            # Step 2: Push to dashboard
            self.log(f"Step 3: Pushing data to dashboard...")
            self.status_var.set("Pushing to dashboard...")
            self.root.update_idletasks()
            
            response = requests.post(
                f"{dashboard_url}/api/client/migrate_sheet",
                json={"email": email, "sheet_url": sheet_url},
                headers={"Content-Type": "application/json"},
                timeout=60
            )
            
            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_msg = response.json().get("message", error_msg)
                except:
                    pass
                self.log(f"❌ Migration failed: {error_msg}", "ERROR")
                self.status_var.set("Migration failed")
                messagebox.showerror("Error", error_msg)
                return
            
            data = response.json()
            if data.get("status") != "success":
                error_msg = data.get("message", "Migration failed")
                self.log(f"❌ {error_msg}", "ERROR")
                self.status_var.set("Migration failed")
                messagebox.showerror("Error", error_msg)
                return
            
            records = data.get("records_imported", 0)
            dashboard_stats = data.get("statistics", {})
            
            self.log(f"   ✅ Dashboard imported {records} records")
            
            # Step 3: Verify stats match
            self.log(f"Step 4: Verifying statistics match...")
            self.status_var.set("Verifying stats...")
            self.root.update_idletasks()
            
            discrepancies = self.verify_stats(local_stats, dashboard_stats)
            
            if discrepancies:
                self.log("=" * 50, "ERROR")
                self.log("⚠️ STATS DISCREPANCIES FOUND:", "ERROR")
                for disc in discrepancies:
                    self.log(f"   {disc}", "ERROR")
                self.log("=" * 50, "ERROR")
                messagebox.showwarning("Stats Mismatch", 
                    f"Data imported but {len(discrepancies)} stat discrepancies found. Check log for details.")
            else:
                self.log("✅ All statistics verified - MATCH!")
                messagebox.showinfo("Success", 
                    f"Successfully imported {records} records.\nAll statistics verified and match!")
            
            self.status_var.set(f"Imported {records} records")
            self.lookup_client()
                
        except requests.exceptions.Timeout:
            self.log("❌ Connection timeout - sheet may be too large", "ERROR")
            self.status_var.set("Timeout")
            messagebox.showerror("Timeout", "Connection timed out. Make sure your sheet is public and try again.")
        except Exception as e:
            self.log(f"❌ Migration error: {e}", "ERROR")
            self.status_var.set("Migration failed")
            messagebox.showerror("Error", str(e))
    
    def verify_stats(self, local_stats, dashboard_stats):
        """Compare local stats with dashboard stats and return list of discrepancies."""
        discrepancies = []
        tolerance = 0.01  # Allow $0.01 difference for rounding
        
        # Helper to compare values
        def compare(name, local_val, dash_val):
            if isinstance(local_val, (int, float)) and isinstance(dash_val, (int, float)):
                if abs(local_val - dash_val) > tolerance:
                    discrepancies.append(f"{name}: Local=${local_val:,.2f} vs Dashboard=${dash_val:,.2f}")
            elif local_val != dash_val:
                discrepancies.append(f"{name}: Local={local_val} vs Dashboard={dash_val}")
        
        # Compare profitability_completed
        local_prof = local_stats.get('profitability_completed', {})
        dash_prof = dashboard_stats.get('profitability_completed', {})
        compare("Prof.Challenge Fees", local_prof.get('challenge_fees', 0), dash_prof.get('challenge_fees', 0))
        compare("Prof.Hedging Results", local_prof.get('hedging_results', 0), dash_prof.get('hedging_results', 0))
        compare("Prof.Farming Results", local_prof.get('farming_results', 0), dash_prof.get('farming_results', 0))
        compare("Prof.Payouts", local_prof.get('payouts', 0), dash_prof.get('payouts', 0))
        compare("Prof.Net Profit", local_prof.get('net_profit', 0), dash_prof.get('net_profit', 0))
        
        # Compare cashflow_inprogress
        local_cash = local_stats.get('cashflow_inprogress', {})
        dash_cash = dashboard_stats.get('cashflow_inprogress', {})
        compare("Cash.Challenge Fees", local_cash.get('challenge_fees', 0), dash_cash.get('challenge_fees', 0))
        compare("Cash.Hedging Results", local_cash.get('hedging_results', 0), dash_cash.get('hedging_results', 0))
        compare("Cash.Farming Results", local_cash.get('farming_results', 0), dash_cash.get('farming_results', 0))
        compare("Cash.Payouts", local_cash.get('payouts', 0), dash_cash.get('payouts', 0))
        compare("Cash.Net Profit", local_cash.get('net_profit', 0), dash_cash.get('net_profit', 0))
        
        # Compare eval_totals
        local_et = local_stats.get('eval_totals', {})
        dash_et = dashboard_stats.get('eval_totals', {})
        compare("Eval.Total Running", local_et.get('total_running', 0), dash_et.get('total_running', 0))
        compare("Eval.Total Passed", local_et.get('total_passed', 0), dash_et.get('total_passed', 0))
        compare("Eval.Total Failed", local_et.get('total_failed', 0), dash_et.get('total_failed', 0))
        
        # Compare funded_totals
        local_ft = local_stats.get('funded_totals', {})
        dash_ft = dashboard_stats.get('funded_totals', {})
        compare("Funded.Not Started", local_ft.get('not_started', 0), dash_ft.get('not_started', 0))
        compare("Funded.Ongoing", local_ft.get('ongoing', 0), dash_ft.get('ongoing', 0))
        compare("Funded.Failed", local_ft.get('failed', 0), dash_ft.get('failed', 0))
        compare("Funded.Completed", local_ft.get('completed', 0), dash_ft.get('completed', 0))
        
        return discrepancies
        
    def toggle_auto_push(self):
        """Toggle automatic data pushing."""
        if self.auto_push_enabled:
            self.auto_push_enabled = False
            self.auto_btn.configure(text="🔄 Start Auto-Push (5min)")
            self.log("Auto-push stopped")
        else:
            if not self.client_info:
                messagebox.showerror("Error", "Please lookup the client first")
                return
            self.auto_push_enabled = True
            self.auto_btn.configure(text="⏹ Stop Auto-Push")
            self.log("Auto-push started (every 5 minutes)")
            self.auto_push_thread = threading.Thread(target=self.auto_push_loop, daemon=True)
            self.auto_push_thread.start()
            
    def auto_push_loop(self):
        """Background loop for auto-pushing."""
        while self.auto_push_enabled:
            self.root.after(0, self.push_data)
            for _ in range(300):  # 5 minutes in seconds
                if not self.auto_push_enabled:
                    break
                time.sleep(1)
                
    def save_config(self):
        """Save configuration to file."""
        config = {
            "dashboard_url": self.url_entry.get(),
            "client_email": self.client_email_entry.get(),
            "sheet_url": self.sheet_url_entry.get(),
            "mt5_login": self.mt5_login.get(),
            "mt5_server": self.mt5_server.get()
        }
        
        config_path = os.path.join(os.path.dirname(__file__), "trader_config.json")
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        self.log("Configuration saved")
        messagebox.showinfo("Saved", "Configuration saved successfully")
        
    def load_config(self):
        """Load configuration from file."""
        config_path = os.path.join(os.path.dirname(__file__), "trader_config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                
                self.url_entry.delete(0, tk.END)
                self.url_entry.insert(0, config.get('dashboard_url', 'https://ballerquotes.pythonanywhere.com'))
                
                self.client_email_entry.delete(0, tk.END)
                self.client_email_entry.insert(0, config.get('client_email', ''))
                
                self.sheet_url_entry.delete(0, tk.END)
                self.sheet_url_entry.insert(0, config.get('sheet_url', ''))
                
                self.mt5_login.delete(0, tk.END)
                self.mt5_login.insert(0, config.get('mt5_login', ''))
                
                self.mt5_server.delete(0, tk.END)
                self.mt5_server.insert(0, config.get('mt5_server', ''))
                
                self.log("Configuration loaded")
            except Exception as e:
                self.log(f"Failed to load config: {e}", "ERROR")
                
    def run(self):
        """Run the application."""
        self.root.mainloop()


def main():
    """Main entry point."""
    if GUI_AVAILABLE:
        app = TraderCompanionApp()
        app.run()
    else:
        print("=" * 50)
        print("MT5 Trader Companion - Console Mode")
        print("=" * 50)
        print("\nGUI not available. Install tkinter to use the graphical interface.")
        print("\nUsage:")
        print("  1. Set your API key in the dashboard")
        print("  2. Use the MT5DataPusher class programmatically")
        print("\nExample:")
        print("  pusher = MT5DataPusher('http://localhost:5001', 'your-api-key')")
        print("  pusher.connect_mt5(login, password, server)")
        print("  pusher.push_to_dashboard('ClientName', 'AdminName', 'TraderName')")


if __name__ == "__main__":
    main()
