import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_atr_signal(symbol, timeframe, period=14, return_value=False):
    """
    Get Average True Range (ATR) value for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: ATR period
        return_value: If True, returns the ATR value
    Returns:
        ATR value or None
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 2)
        if rates is None or len(rates) < period + 1:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        trs = np.maximum(highs[1:] - lows[1:], np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1]))
        atr = pd.Series(trs).rolling(window=period).mean().iloc[-1]
        if return_value:
            return atr
        return atr
    except Exception:
        return None
