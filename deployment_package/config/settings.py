import os
from config.hierarchy import get_client_profile

# Identity Configuration
# Default to "Chris" (under Philip) if not specified
CLIENT_NAME = os.getenv("CLIENT_NAME", "Chris")

# Auto-detect Admin and Trader based on Client Name
profile = get_client_profile(CLIENT_NAME)
if profile:
    ADMIN_NAME = profile["admin"]
    TRADER_NAME = profile["trader"]
else:
    # Fallback for unknown clients
    ADMIN_NAME = os.getenv("ADMIN_NAME", "UnknownAdmin")
    TRADER_NAME = os.getenv("TRADER_NAME", "UnknownTrader")

# MT5 Configuration
MT5_LOGIN = int(os.getenv("MT5_LOGIN", 3053752))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "Blueedge1!")
MT5_SERVER = os.getenv("MT5_SERVER", "PlexyTrade-Server01")
MT5_TERMINAL = os.getenv("MT5_TERMINAL", "MetaTrader 5 (MetaTrader 5)")
MT5_SYMBOL = os.getenv("MT5_SYMBOL", "USTECH")

# Google Sheets Configuration
SHEET_URL = "https://docs.google.com/spreadsheets/d/1vtuGcTe8ys44wHCJGJr6VoImeh8q0beaKkZMt0hd3VU/edit?usp=sharing"

