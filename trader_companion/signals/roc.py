import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_roc_signal(symbol, timeframe, period=12, threshold=0, return_value=False):
    """
    Get Rate of Change (ROC) signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: ROC period
        threshold: ROC threshold
        return_value: If True, returns (signal, roc_value), else just signal
    Returns:
        Signal ("bullish", "bearish", or None) or (signal, roc_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period + 1:
            return None
        closes = np.array([rate[4] for rate in rates])
        roc = ((closes[-1] - closes[-period-1]) / closes[-period-1]) * 100
        signal = None
        if roc > threshold:
            signal = "bullish"
        elif roc < -threshold:
            signal = "bearish"
        if return_value:
            return signal, roc
        return signal
    except Exception:
        return None
