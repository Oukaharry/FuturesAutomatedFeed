import os
from dotenv import load_dotenv

class Config:
    def __init__(self):
        load_dotenv()
        self.tradovate_user = os.getenv("TRADOVATE_USER")
        self.tradovate_pass = os.getenv("TRADOVATE_PASS")
        self.mt5_login = os.getenv("MT5_LOGIN")
        self.mt5_password = os.getenv("MT5_PASSWORD")
        self.mt5_server = os.getenv("MT5_SERVER")
        self.moving_average_short = int(os.getenv("MOVING_AVERAGE_SHORT", 10))
        self.moving_average_long = int(os.getenv("MOVING_AVERAGE_LONG", 50))
        self.account_pairs = self.load_account_pairs()

    def load_account_pairs(self):
        pairs = []
        for i in range(1, 4):  # Allow up to 3 pairs
            user = os.getenv(f"ACCOUNT_PAIR_{i}_USER")
            password = os.getenv(f"ACCOUNT_PAIR_{i}_PASS")
            if user and password:
                pairs.append((user, password))
        return pairs

    def get_tradovate_credentials(self):
        return self.tradovate_user, self.tradovate_pass

    def get_mt5_credentials(self):
        return self.mt5_login, self.mt5_password, self.mt5_server

    def get_moving_average_settings(self):
        return self.moving_average_short, self.moving_average_long

    def get_account_pairs(self):
        return self.account_pairs

def load_config():
    load_dotenv()
    config = {
        "TRADOVATE_USER": os.getenv("TRADOVATE_USER"),
        "TRADOVATE_PASS": os.getenv("TRADOVATE_PASS"),
        "MT5_LOGIN": os.getenv("MT5_LOGIN"),
        "MT5_PASSWORD": os.getenv("MT5_PASSWORD"),
        "MT5_SERVER": os.getenv("MT5_SERVER"),
        # Add more config variables as needed
    }
    return config