import MetaTrader5 as mt5
import pandas as pd

class MT5Connector:
    def __init__(self, login, password, server, terminal_path=None):
        self.login = login
        self.password = password
        self.server = server
        self.terminal_path = terminal_path
        self.connected = False

    def connect(self):
        init_params = {}
        if self.terminal_path and "exe" in self.terminal_path:
             init_params["path"] = self.terminal_path

        if not mt5.initialize(**init_params):
            print("initialize() failed, error code =", mt5.last_error())
            return False
        
        if not self.login or not self.password or not self.server:
             print("MT5 Credentials missing. Skipping login.")
             return False

        authorized = mt5.login(self.login, password=self.password, server=self.server)
        if authorized:
            self.connected = True
            print(f"Connected to MT5 account #{self.login}")
        else:
            print("failed to connect at account #{}, error code: {}".format(self.login, mt5.last_error()))
        
        return self.connected

    def shutdown(self):
        mt5.shutdown()
        self.connected = False

    def get_deals(self, days=30, from_date=None):
        # Ensure MT5 is initialized and logged in for the current thread
        init_params = {}
        if self.terminal_path and "exe" in self.terminal_path:
             init_params["path"] = self.terminal_path

        if not mt5.initialize(**init_params):
            print(f"get_deals: mt5.initialize() failed with path: {self.terminal_path}")
            print("Error code:", mt5.last_error())
            return []
            
        if self.login and self.password and self.server:
            # Ensure login is int
            try:
                login_int = int(self.login)
            except:
                print(f"Invalid login format: {self.login}")
                return []

            if not mt5.login(login_int, password=self.password, server=self.server):
                print(f"get_deals: mt5.login failed for {self.login}")
                print("Error code:", mt5.last_error())
                return []

        import time
        to_timestamp = time.time() + 86400 # Add buffer (1 day)
        
        if from_date:
            from_timestamp = from_date.timestamp()
        elif days is None:
            from_timestamp = 0.0
        else:
            # Calculate from_timestamp relative to NOW, not the buffered to_timestamp
            from_timestamp = time.time() - (days * 24 * 3600)
        
        try:
            # Use timestamps to avoid datetime issues
            deals = mt5.history_deals_get(from_timestamp, to_timestamp)
        except Exception as e:
            print(f"get_deals: Exception calling history_deals_get: {e}")
            return []
        
        if deals is None:
            print("No deals found. Error code={}".format(mt5.last_error()))
            return []
            
        return deals

    def get_deals_by_position(self, position_id):
        if not self.connected: return []
        try:
            deals = mt5.history_deals_get(position=position_id)
            if deals is None:
                return []
            return deals
        except Exception as e:
            print(f"get_deals_by_position error: {e}")
            return []

    def get_account_info(self):
        if not self.connected: return None
        try:
            return mt5.account_info()
        except Exception as e:
            print(f"get_account_info error: {e}")
            return None

    def get_positions(self):
        if not self.connected: return []
        try:
            positions = mt5.positions_get()
            if positions is None:
                return []
            return positions
        except Exception as e:
            print(f"get_positions error: {e}")
            return []
        except Exception as e:
            print(f"get_account_info error: {e}")
            return None

    def get_positions(self):
        if not self.connected: return []
        try:
            positions = mt5.positions_get()
            if positions is None:
                return []
            return positions
        except Exception as e:
            print(f"get_positions error: {e}")
            return []

    def place_order(self, symbol, order_type, volume, sl_points=None, tp_points=None, comment=""):
        """
        Places a market order.
        order_type: 'BUY' or 'SELL'
        sl_points: Stop Loss in points (optional)
        tp_points: Take Profit in points (optional)
        """
        if not self.connected:
            if not self.connect():
                return False

        # Ensure symbol is selected
        if not mt5.symbol_select(symbol, True):
            print(f"Failed to select symbol {symbol}")
            return False

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            print(f"{symbol} not found")
            return False

        # Determine order type and price
        if order_type.upper() == 'BUY':
            mt5_type = mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(symbol).ask
        elif order_type.upper() == 'SELL':
            mt5_type = mt5.ORDER_TYPE_SELL
            price = mt5.symbol_info_tick(symbol).bid
        else:
            print(f"Invalid order type: {order_type}")
            return False

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": mt5_type,
            "price": price,
            "deviation": 20,
            "magic": 234000,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # Calculate SL/TP prices if points provided
        point = symbol_info.point
        if sl_points:
            if mt5_type == mt5.ORDER_TYPE_BUY:
                request["sl"] = price - (sl_points * point)
            else:
                request["sl"] = price + (sl_points * point)
        
        if tp_points:
            if mt5_type == mt5.ORDER_TYPE_BUY:
                request["tp"] = price + (tp_points * point)
            else:
                request["tp"] = price - (tp_points * point)

        # Send order
        result = mt5.order_send(request)
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"Order failed: {result.comment} ({result.retcode})")
            return False
        
        print(f"Order placed successfully: {result.order}")
        return True
