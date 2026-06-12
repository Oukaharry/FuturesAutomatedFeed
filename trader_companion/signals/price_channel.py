import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_price_channel_signal(symbol, timeframe, period=20, return_value=False):
    """
    Price Channel (close-based) breakout signal.

    Channel uses the PRIOR `period` closes (shifted one bar). Close above
    the upper channel = buy, below the lower channel = sell.

    Returns:
        Signal ("buy", "sell", or None) or (signal, upper, lower)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period + 1:
            return None
        closes = np.array([rate[4] for rate in rates])
        upper = np.max(closes[-period - 1:-1])
        lower = np.min(closes[-period - 1:-1])
        close = closes[-1]
        signal = None
        if close > upper:
            signal = "buy"
        elif close < lower:
            signal = "sell"
        if return_value:
            return signal, upper, lower
        return signal
    except Exception:
        return None
