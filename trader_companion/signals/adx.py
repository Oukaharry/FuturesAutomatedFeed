import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_adx_signal(symbol, timeframe, period=14, threshold=25, return_value=False):
    """
    Get ADX value for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: ADX period
        threshold: ADX threshold for trend strength
        return_value: If True, returns (signal, adx_value), else just signal
    Returns:
        Signal ("trend" or None) or (signal, adx_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 50)
        if rates is None or len(rates) < period + 1:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        plus_dm = highs[1:] - highs[:-1]
        minus_dm = lows[:-1] - lows[1:]
        plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0)
        minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0)
        tr = np.maximum(highs[1:] - lows[1:], np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1]))
        atr = pd.Series(tr).rolling(window=period).mean()
        plus_di = 100 * pd.Series(plus_dm).rolling(window=period).mean() / atr
        minus_di = 100 * pd.Series(minus_dm).rolling(window=period).mean() / atr
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = pd.Series(dx).rolling(window=period).mean().iloc[-1]
        signal = "trend" if adx > threshold else None
        if return_value:
            return signal, adx
        return signal
    except Exception:
        return None
