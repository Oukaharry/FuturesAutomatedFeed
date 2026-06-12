import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_ultimate_oscillator_signal(symbol, timeframe, short=7, medium=14, long=28,
                                   overbought=70, oversold=30, return_value=False):
    """
    Ultimate Oscillator signal: oversold (<= 30) = buy, overbought (>= 70) = sell.

    Returns:
        Signal ("buy", "sell", or None) or (signal, uo_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, long + 10)
        if rates is None or len(rates) < long + 2:
            return None
        highs = pd.Series([rate[2] for rate in rates])
        lows = pd.Series([rate[3] for rate in rates])
        closes = pd.Series([rate[4] for rate in rates])
        prev_close = closes.shift(1)
        true_low = pd.concat([lows, prev_close], axis=1).min(axis=1)
        true_high = pd.concat([highs, prev_close], axis=1).max(axis=1)
        bp = closes - true_low
        tr = true_high - true_low

        def _avg(n):
            tr_sum = tr.rolling(window=n).sum()
            return bp.rolling(window=n).sum() / tr_sum.replace(0, np.nan)

        uo = (100 * (4 * _avg(short) + 2 * _avg(medium) + _avg(long)) / 7).iloc[-1]
        if pd.isna(uo):
            return None
        signal = None
        if uo <= oversold:
            signal = "buy"
        elif uo >= overbought:
            signal = "sell"
        if return_value:
            return signal, uo
        return signal
    except Exception:
        return None
