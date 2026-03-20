import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_momentum_signal(symbol, timeframe, period=10, threshold=0.3, return_value=False):
    """
    Get Momentum value for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: Momentum period
        threshold: Momentum threshold
        return_value: If True, returns (signal, momentum_value), else just signal
    Returns:
        Signal ("bullish", "bearish", or None) or (signal, momentum_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period + 1:
            return None
        closes = np.array([rate[4] for rate in rates])
        momentum = closes[-1] - closes[-period-1]
        signal = None
        if momentum > threshold:
            signal = "bullish"
        elif momentum < -threshold:
            signal = "bearish"
        if return_value:
            return signal, momentum
        return signal
    except Exception:
        return None
