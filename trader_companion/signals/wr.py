import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_wr_signal(symbol, timeframe, period=14, overbought=-20, oversold=-80, return_value=False):
    """
    Get Williams %R signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: WR period
        overbought: Overbought threshold
        oversold: Oversold threshold
        return_value: If True, returns (signal, wr_value), else just signal
    Returns:
        Signal ("buy", "sell", or None) or (signal, wr_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        highest_high = np.max(highs[-period:])
        lowest_low = np.min(lows[-period:])
        wr = -100 * (highest_high - closes[-1]) / (highest_high - lowest_low)
        signal = None
        if wr > overbought:
            signal = "sell"
        elif wr < oversold:
            signal = "buy"
        if return_value:
            return signal, wr
        return signal
    except Exception:
        return None
