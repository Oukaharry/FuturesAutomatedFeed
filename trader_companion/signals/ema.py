import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_ema_signal(symbol, timeframe, period=21, return_value=False):
    """
    Get EMA value for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: EMA period
        return_value: If True, returns the EMA value
    Returns:
        EMA value or None
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period:
            return None
        closes = np.array([rate[4] for rate in rates])
        ema = pd.Series(closes).ewm(span=period, adjust=False).mean().iloc[-1]
        if return_value:
            return ema
        return ema
    except Exception:
        return None
