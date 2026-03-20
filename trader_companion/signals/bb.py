import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_bb_signal(symbol, timeframe, period=20, deviation=2.0, return_value=False):
    """
    Get Bollinger Bands signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: BB period
        deviation: Standard deviation multiplier
        return_value: If True, returns (signal, upper, lower, close), else just signal
    Returns:
        Signal ("upper", "lower", or None) or (signal, upper, lower, close)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period:
            return None
        closes = np.array([rate[4] for rate in rates])
        series = pd.Series(closes)
        sma = series.rolling(window=period).mean().iloc[-1]
        std = series.rolling(window=period).std().iloc[-1]
        upper = sma + deviation * std
        lower = sma - deviation * std
        close = closes[-1]
        signal = None
        if close > upper:
            signal = "upper"
        elif close < lower:
            signal = "lower"
        if return_value:
            return signal, upper, lower, close
        return signal
    except Exception:
        return None
