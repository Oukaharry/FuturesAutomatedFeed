import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_macd_signal(symbol, timeframe, fast_period=12, slow_period=26, signal_period=9, return_value=False):
    """
    Get MACD signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        fast_period: Fast EMA period
        slow_period: Slow EMA period
        signal_period: Signal line EMA period
        return_value: If True, returns (signal, macd, signal_line) tuple, otherwise just signal
    Returns:
        If return_value=False: signal string ("buy", "sell", or None)
        If return_value=True: tuple (signal, macd, signal_line)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, slow_period + signal_period + 10)
        if rates is None or len(rates) < slow_period + signal_period:
            return None
        closes = np.array([rate[4] for rate in rates])
        fast_ema = pd.Series(closes).ewm(span=fast_period, adjust=False).mean()
        slow_ema = pd.Series(closes).ewm(span=slow_period, adjust=False).mean()
        macd = fast_ema - slow_ema
        signal_line = macd.ewm(span=signal_period, adjust=False).mean()
        # Use the last value for signal
        macd_val = macd.iloc[-1]
        signal_val = signal_line.iloc[-1]
        if macd_val > signal_val:
            signal = "buy"
        elif macd_val < signal_val:
            signal = "sell"
        else:
            signal = None
        if return_value:
            return signal, macd_val, signal_val
        return signal
    except Exception:
        return None
