import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_cmo_signal(symbol, timeframe, period=14, overbought=50, oversold=-50, return_value=False):
    """
    Chande Momentum Oscillator signal: oversold (<= -50) = buy,
    overbought (>= +50) = sell.

    Returns:
        Signal ("buy", "sell", or None) or (signal, cmo_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period + 1:
            return None
        closes = pd.Series([rate[4] for rate in rates])
        delta = closes.diff()
        up = delta.clip(lower=0).rolling(window=period).sum().iloc[-1]
        down = (-delta.clip(upper=0)).rolling(window=period).sum().iloc[-1]
        denom = up + down
        if denom == 0 or pd.isna(denom):
            return None
        cmo = 100 * (up - down) / denom
        signal = None
        if cmo <= oversold:
            signal = "buy"
        elif cmo >= overbought:
            signal = "sell"
        if return_value:
            return signal, cmo
        return signal
    except Exception:
        return None
