import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_cci_signal(symbol, timeframe, period=20, overbought=100, oversold=-100, return_value=False):
    """
    Get Commodity Channel Index (CCI) signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: CCI period
        overbought: Overbought threshold
        oversold: Oversold threshold
        return_value: If True, returns (signal, cci_value), else just signal
    Returns:
        Signal ("buy", "sell", or None) or (signal, cci_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        typical_price = (highs + lows + closes) / 3
        tp_series = pd.Series(typical_price)
        sma = tp_series.rolling(window=period).mean().iloc[-1]
        mean_dev = np.mean(np.abs(tp_series[-period:] - sma))
        cci = (tp_series.iloc[-1] - sma) / (0.015 * mean_dev) if mean_dev != 0 else 0
        signal = None
        if cci > overbought:
            signal = "sell"
        elif cci < oversold:
            signal = "buy"
        if return_value:
            return signal, cci
        return signal
    except Exception:
        return None
