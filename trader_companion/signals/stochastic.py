import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_stochastic_signal(symbol, timeframe, k_period=14, d_period=3, overbought=80, oversold=20, return_value=False):
    """
    Get Stochastic Oscillator signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        k_period: %K period
        d_period: %D period
        overbought: Overbought threshold
        oversold: Oversold threshold
        return_value: If True, returns (signal, k_value, d_value), else just signal
    Returns:
        Signal ("buy", "sell", or None) or (signal, k_value, d_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, k_period + d_period + 10)
        if rates is None or len(rates) < k_period + d_period:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        lowest_low = pd.Series(lows).rolling(window=k_period).min()
        highest_high = pd.Series(highs).rolling(window=k_period).max()
        k = 100 * (closes - lowest_low) / (highest_high - lowest_low)
        d = k.rolling(window=d_period).mean()
        k_value = k.iloc[-1]
        d_value = d.iloc[-1]
        signal = None
        if k_value > overbought:
            signal = "sell"
        elif k_value < oversold:
            signal = "buy"
        if return_value:
            return signal, k_value, d_value
        return signal
    except Exception:
        return None
