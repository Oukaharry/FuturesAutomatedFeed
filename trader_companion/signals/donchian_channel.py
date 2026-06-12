import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_donchian_channel_signal(symbol, timeframe, period=20, return_value=False):
    """
    Donchian Channel breakout signal.

    Bands use the PRIOR `period` bars (shifted one bar) so the current bar
    cannot leak into its own channel. Close above the upper band = buy,
    below the lower band = sell.

    Returns:
        Signal ("buy", "sell", or None) or (signal, upper, lower)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period + 1:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        upper = np.max(highs[-period - 1:-1])
        lower = np.min(lows[-period - 1:-1])
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
