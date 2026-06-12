import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_keltner_channel_signal(symbol, timeframe, period=20, atr_mult=2.0, return_value=False):
    """
    Keltner Channel breakout signal (EMA center ± ATR * multiplier).

    Close above the upper band = buy, below the lower band = sell.

    Returns:
        Signal ("buy", "sell", or None) or (signal, upper, lower)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 50)
        if rates is None or len(rates) < period + 1:
            return None
        highs = pd.Series([rate[2] for rate in rates])
        lows = pd.Series([rate[3] for rate in rates])
        closes = pd.Series([rate[4] for rate in rates])
        center = closes.ewm(span=period, adjust=False).mean()
        prev_close = closes.shift(1)
        tr = pd.concat([(highs - lows),
                        (highs - prev_close).abs(),
                        (lows - prev_close).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
        upper = center.iloc[-1] + atr_mult * atr.iloc[-1]
        lower = center.iloc[-1] - atr_mult * atr.iloc[-1]
        close = closes.iloc[-1]
        signal = None
        if close > upper:
            signal = "buy"
        elif close < lower:
            signal = "sell"
        if return_value:
            return signal, upper, lower
        return signal
    except Exception:
        return None
