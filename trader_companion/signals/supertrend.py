import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_supertrend_signal(symbol, timeframe, period=10, multiplier=3.0, return_value=False):
    """
    Get Supertrend signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: ATR period for Supertrend
        multiplier: Multiplier for ATR
        return_value: If True, returns (signal, supertrend), else just signal
    Returns:
        Signal ("bullish", "bearish", or None) or (signal, supertrend)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period + 1:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        atr = pd.Series(np.maximum(highs[1:] - lows[1:], np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1]))).rolling(window=period).mean()
        hl2 = (highs + lows) / 2
        upperband = hl2 - (multiplier * atr)
        lowerband = hl2 + (multiplier * atr)
        supertrend = np.zeros_like(closes)
        direction = np.ones_like(closes)
        for i in range(1, len(closes)):
            if closes[i] > upperband[i]:
                direction[i] = 1
            elif closes[i] < lowerband[i]:
                direction[i] = -1
            else:
                direction[i] = direction[i-1]
            supertrend[i] = lowerband[i] if direction[i] == 1 else upperband[i]
        signal = "bullish" if direction[-1] == 1 else "bearish"
        if return_value:
            return signal, supertrend[-1]
        return signal
    except Exception:
        return None
