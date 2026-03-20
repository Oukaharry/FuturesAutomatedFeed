import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_sma_signal(symbol, timeframe, period=21, return_value=False):
    """
    Get SMA value for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: SMA period
        return_value: If True, returns the SMA value
    Returns:
        SMA value or None
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period:
            return None
        closes = np.array([rate[4] for rate in rates])
        sma = pd.Series(closes).rolling(window=period).mean().iloc[-1]
        if return_value:
            return sma
        return sma
    except Exception:
        return None
