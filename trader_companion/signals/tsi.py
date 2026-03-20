import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_tsi_signal(symbol, timeframe, r=25, s=13, return_value=False):
    """
    Get True Strength Index (TSI) signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        r: Long EMA period
        s: Short EMA period
        return_value: If True, returns (signal, tsi_value), else just signal
    Returns:
        Signal ("bullish", "bearish", or None) or (signal, tsi_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, r + s + 10)
        if rates is None or len(rates) < r + s:
            return None
        closes = np.array([rate[4] for rate in rates])
        diff = np.diff(closes)
        abs_diff = np.abs(diff)
        ema1 = pd.Series(diff).ewm(span=s, adjust=False).mean()
        ema2 = ema1.ewm(span=r, adjust=False).mean()
        abs_ema1 = pd.Series(abs_diff).ewm(span=s, adjust=False).mean()
        abs_ema2 = abs_ema1.ewm(span=r, adjust=False).mean()
        tsi = 100 * (ema2.iloc[-1] / abs_ema2.iloc[-1]) if abs_ema2.iloc[-1] != 0 else 0
        signal = None
        if tsi > 25:
            signal = "bullish"
        elif tsi < -25:
            signal = "bearish"
        if return_value:
            return signal, tsi
        return signal
    except Exception:
        return None
