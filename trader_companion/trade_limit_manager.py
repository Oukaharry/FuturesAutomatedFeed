"""
Trade Limit Manager for Combine-Based Trading
Manages trade limits based on the number of combines purchased and active MT5 trades
"""

import sys
import os
import logging
import time
from typing import Dict, List, Optional, Tuple

# Add src to path for imports
sys.path.append(os.path.dirname(__file__))

# MT5 functionality is available through mt5.py module
# The TradeLimitManager will receive MT5 API instance from the main application
get_mt5 = lambda: None

# Import for popup alerts
try:
    import tkinter as tk
    from tkinter import messagebox
    POPUP_AVAILABLE = True
except ImportError:
    POPUP_AVAILABLE = False
    print("Warning: tkinter not available, popup alerts disabled")

def show_trade_limit_alert(message: str, title: str = "Trade Limit Exceeded"):
    """
    Show a popup alert when trade limits are exceeded
    """
    if POPUP_AVAILABLE:
        try:
            # Create a temporary root window (hidden)
            root = tk.Tk()
            root.withdraw()  # Hide the main window
            
            # Show the error message
            messagebox.showerror(title, message)
            
            # Destroy the root window
            root.destroy()
            
        except Exception as e:
            logging.error(f"Failed to show popup alert: {e}")
            print(f"⚠️ Popup alert failed: {message}")
    else:
        # Fallback to console output
        print(f"🚨 {title}: {message}")

class TradeLimit:
    """Represents trade limit information for a combine"""
    def __init__(self, combine_id: str, max_trades: int, account_name: str = ""):
        self.combine_id = combine_id
        self.max_trades = max_trades
        self.account_name = account_name
        self.active_trades = 0
        self.last_check = 0
        
    def can_place_trade(self) -> bool:
        """Check if a new trade can be placed"""
        return self.active_trades < self.max_trades
    
    def remaining_trades(self) -> int:
        """Get number of remaining trade slots"""
        return max(0, self.max_trades - self.active_trades)

class TradeLimitManager:
    """Manages trade limits across multiple combines"""
    
    def __init__(self, max_trades: int = 5):
        self.combines: Dict[str, TradeLimit] = {}
        self.mt5 = None
        self.last_mt5_check = 0
        self.check_interval = 5  # Check MT5 every 5 seconds
        self.max_trades = max_trades  # Store the max trades limit
        
        # Default combine configurations
        self.default_combines = {
            "5_combine": 5,
            "10_combine": 10,
            "15_combine": 15,
            "20_combine": 20
        }
        
        # Add a default combine with the specified max trades
        self.add_combine("default", max_trades, "Default Account")
        
        self._initialize_mt5()
        
    def _initialize_mt5(self):
        """Initialize MT5 connection - MT5 API will be set by the main application"""
        # MT5 API instance will be set by the application through set_mt5_api() method
        self.mt5 = None
    
    def add_combine(self, combine_id: str, max_trades: int, account_name: str = "") -> bool:
        """Add a new combine with specified trade limit"""
        try:
            self.combines[combine_id] = TradeLimit(combine_id, max_trades, account_name)
            logging.info(f"✅ Added combine {combine_id} with {max_trades} trade limit")
            return True
        except Exception as e:
            logging.error(f"❌ Failed to add combine {combine_id}: {e}")
            return False
    
    def remove_combine(self, combine_id: str) -> bool:
        """Remove a combine"""
        try:
            if combine_id in self.combines:
                del self.combines[combine_id]
                logging.info(f"✅ Removed combine {combine_id}")
                return True
            else:
                logging.warning(f"⚠️ Combine {combine_id} not found")
                return False
        except Exception as e:
            logging.error(f"❌ Failed to remove combine {combine_id}: {e}")
            return False
    
    def set_mt5_api(self, mt5_api):
        """Set the MT5 API instance from the main application"""
        self.mt5 = mt5_api
        if mt5_api:
            logging.info("✅ MT5 API set for trade limit checking")
        
    def get_active_trades_from_mt5(self) -> int:
        """Get number of active trades from MT5 terminal"""
        if not self.mt5:
            return 0
        
        try:
            # Initialize MT5 if not already done
            if not self.mt5.initialize():
                logging.error("❌ Failed to initialize MT5 for trade checking")
                return 0
            
            # Get all open positions
            positions = self.mt5.positions_get()
            if positions is None:
                positions = []
            
            active_count = len(positions)
            logging.info(f"📊 MT5 active trades: {active_count}")
            
            # Get detailed position info
            if active_count > 0:
                logging.info("📋 Active positions:")
                for i, pos in enumerate(positions):
                    symbol = pos.symbol
                    volume = pos.volume
                    position_type = "BUY" if pos.type == 0 else "SELL"
                    profit = pos.profit
                    logging.info(f"   {i+1}. {symbol} {position_type} {volume} lots (P&L: {profit:.2f})")
            
            # Shutdown MT5 connection
            self.mt5.shutdown()
            
            return active_count
            
        except Exception as e:
            logging.error(f"❌ Error checking MT5 active trades: {e}")
            try:
                self.mt5.shutdown()
            except:
                pass
            return 0
    
    def update_active_trades_all_combines(self) -> bool:
        """Update active trade counts for all combines from MT5"""
        current_time = time.time()
        
        # Only check if enough time has passed
        if current_time - self.last_mt5_check < self.check_interval:
            return True
        
        try:
            total_active = self.get_active_trades_from_mt5()
            
            # Update all combines with current active trade count
            for combine_id, combine in self.combines.items():
                combine.active_trades = total_active
                combine.last_check = current_time
                logging.info(f"📊 {combine_id}: {combine.active_trades}/{combine.max_trades} trades active")
            
            self.last_mt5_check = current_time
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to update active trades: {e}")
            return False
    
    def can_place_trade(self, combine_id: str = None) -> Tuple[bool, str]:
        """
        Check if a new trade can be placed
        Returns: (can_place, reason)
        """
        # Update active trades from MT5
        self.update_active_trades_all_combines()
        
        # Use default combine if none specified
        if not combine_id:
            combine_id = "default"
        
        if combine_id in self.combines:
            # Check specific combine
            combine = self.combines[combine_id]
            if combine.can_place_trade():
                remaining = combine.remaining_trades()
                return True, f"✅ Can place trade. {remaining} slots remaining for {combine_id}"
            else:
                error_message = f"❌ Trade limit reached for {combine_id} ({combine.active_trades}/{combine.max_trades})"
                
                # Show popup alert for trade limit exceeded
                popup_message = (f"🚨 TRADE LIMIT EXCEEDED 🚨\n\n"
                               f"Account: {combine_id}\n"
                               f"Active Trades: {combine.active_trades}\n"
                               f"Maximum Allowed: {combine.max_trades}\n\n"
                               f"You have reached your combine purchase limit!\n"
                               f"Close existing trades or purchase more combines to continue trading.")
                
                show_trade_limit_alert(popup_message, "Trade Limit Exceeded")
                
                return False, error_message
        
        elif self.combines:
            # Check if any combine allows trading
            available_combines = []
            for cid, combine in self.combines.items():
                if combine.can_place_trade():
                    available_combines.append((cid, combine.remaining_trades()))
            
            if available_combines:
                total_remaining = sum(remaining for _, remaining in available_combines)
                combine_names = ", ".join(f"{cid}({remaining})" for cid, remaining in available_combines)
                return True, f"✅ Can place trade. Available combines: {combine_names}"
            else:
                active_info = ", ".join(f"{cid}({c.active_trades}/{c.max_trades})" 
                                      for cid, c in self.combines.items())
                error_message = f"❌ All trade limits reached. Active: {active_info}"
                
                # Show popup alert for all limits exceeded
                popup_message = (f"🚨 ALL TRADE LIMITS EXCEEDED 🚨\n\n"
                               f"All your combines have reached their maximum trades:\n"
                               f"{active_info}\n\n"
                               f"Please close existing trades or purchase more combines to continue trading.")
                
                show_trade_limit_alert(popup_message, "All Trade Limits Exceeded")
                
                return False, error_message
        
        else:
            error_message = "❌ No combines configured"
            show_trade_limit_alert("No trading combines configured! Please set up your combine limits.", "Configuration Error")
            return False, error_message
    
    def get_current_trade_count(self) -> int:
        """Get the current number of active trades from MT5"""
        try:
            return self.get_active_trades_from_mt5()
        except Exception as e:
            logging.error(f"Failed to get current trade count: {e}")
            return 0
    
    def get_trade_summary(self) -> Dict:
        """Get comprehensive trade limit summary"""
        self.update_active_trades_all_combines()
        
        summary = {
            "total_combines": len(self.combines),
            "total_max_trades": sum(c.max_trades for c in self.combines.values()),
            "total_active_trades": sum(c.active_trades for c in self.combines.values()),
            "total_remaining": sum(c.remaining_trades() for c in self.combines.values()),
            "mt5_active_trades": self.get_active_trades_from_mt5() if self.mt5 else 0,
            "combines": {}
        }
        
        for combine_id, combine in self.combines.items():
            summary["combines"][combine_id] = {
                "max_trades": combine.max_trades,
                "active_trades": combine.active_trades,
                "remaining": combine.remaining_trades(),
                "can_trade": combine.can_place_trade(),
                "account_name": combine.account_name
            }
        
        return summary
    
    def print_trade_status(self):
        """Print detailed trade status"""
        summary = self.get_trade_summary()
        
        print("\n" + "="*60)
        print("📊 TRADE LIMIT STATUS")
        print("="*60)
        
        print(f"🎯 Total Combines: {summary['total_combines']}")
        print(f"📈 Total Trade Capacity: {summary['total_max_trades']}")
        print(f"⚡ Active Trades (MT5): {summary['mt5_active_trades']}")
        print(f"🟢 Available Slots: {summary['total_remaining']}")
        
        if summary['combines']:
            print(f"\n📋 COMBINE DETAILS:")
            for combine_id, info in summary['combines'].items():
                status = "🟢 Available" if info['can_trade'] else "🔴 Full"
                account_info = f" ({info['account_name']})" if info['account_name'] else ""
                print(f"   {combine_id}{account_info}: {info['active_trades']}/{info['max_trades']} {status}")
        
        can_trade, reason = self.can_place_trade()
        print(f"\n🎯 TRADE STATUS: {reason}")
        print("="*60)
    
    def load_combines_from_config(self, config_file: str = "combine_config.txt") -> bool:
        """Load combine configuration from file"""
        try:
            if not os.path.exists(config_file):
                # Create default config file
                self.create_default_config(config_file)
            
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split(',')
                        if len(parts) >= 2:
                            combine_id = parts[0].strip()
                            max_trades = int(parts[1].strip())
                            account_name = parts[2].strip() if len(parts) > 2 else ""
                            self.add_combine(combine_id, max_trades, account_name)
            
            logging.info(f"✅ Loaded combines from {config_file}")
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to load combines from {config_file}: {e}")
            return False
    
    def create_default_config(self, config_file: str = "combine_config.txt"):
        """Create default combine configuration file"""
        try:
            with open(config_file, 'w') as f:
                f.write("# Combine Configuration File\n")
                f.write("# Format: combine_id, max_trades, account_name (optional)\n")
                f.write("# Example: 5_combine, 5, Main Account\n\n")
                
                f.write("# Default configurations (modify as needed)\n")
                f.write("5_combine, 5, Primary\n")
                f.write("# 10_combine, 10, Secondary\n")
                f.write("# 15_combine, 15, Advanced\n")
                f.write("# 20_combine, 20, Professional\n")
            
            logging.info(f"✅ Created default config file: {config_file}")
            
        except Exception as e:
            logging.error(f"❌ Failed to create default config: {e}")

# Global trade limit manager instance
trade_limit_manager = TradeLimitManager()

def check_trade_limit(combine_id: str = None) -> Tuple[bool, str]:
    """
    Quick function to check if a trade can be placed
    Returns: (can_place, reason)
    """
    return trade_limit_manager.can_place_trade(combine_id)

def get_trade_summary() -> Dict:
    """Get current trade limit summary"""
    return trade_limit_manager.get_trade_summary()

def initialize_trade_limits(config_file: str = "combine_config.txt") -> bool:
    """Initialize trade limits from configuration"""
    return trade_limit_manager.load_combines_from_config(config_file)

if __name__ == "__main__":
    # Test the trade limit manager
    print("🔍 Testing Trade Limit Manager...")
    
    # Initialize with test combines
    trade_limit_manager.add_combine("test_5", 5, "Test Account 5")
    trade_limit_manager.add_combine("test_10", 10, "Test Account 10")
    
    # Print status
    trade_limit_manager.print_trade_status()
    
    # Test trade placement
    can_trade, reason = trade_limit_manager.can_place_trade()
    print(f"\n🎯 Trade test: {reason}")
