import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_dmi_signal(symbol, timeframe, period=14, threshold=25, return_value=False):
    """
    Get Directional Movement Index (DMI) signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: DMI period
        threshold: DMI threshold
        return_value: If True, returns (signal, plus_di, minus_di), else just signal
    Returns:
        Signal ("bullish", "bearish", or None) or (signal, plus_di, minus_di)
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
        signal = None
        if plus_di.iloc[-1] > minus_di.iloc[-1] and plus_di.iloc[-1] > threshold:
            signal = "bullish"
        elif minus_di.iloc[-1] > plus_di.iloc[-1] and minus_di.iloc[-1] > threshold:
            signal = "bearish"
        if return_value:
            return signal, plus_di.iloc[-1], minus_di.iloc[-1]
        return signal
    except Exception:
        return None
