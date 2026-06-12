import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_coppock_curve_signal(symbol, timeframe, wma_period=10, roc1=14, roc2=11, return_value=False):
    """
    Coppock Curve signal: curve rising = buy, falling = sell.

    Returns:
        Signal ("buy", "sell", or None) or (signal, current, previous)
    """
    try:
        need = max(roc1, roc2) + wma_period + 10
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, need)
        if rates is None or len(rates) < max(roc1, roc2) + wma_period + 2:
            return None
        closes = pd.Series([rate[4] for rate in rates])
        roc_sum = ((closes / closes.shift(roc1) - 1.0) * 100.0
                   + (closes / closes.shift(roc2) - 1.0) * 100.0)
        weights = np.arange(1, wma_period + 1, dtype=float)
        wsum = weights.sum()
        cc = roc_sum.rolling(window=wma_period).apply(
            lambda x: float((x * weights).sum() / wsum), raw=True)
        cur, prev = cc.iloc[-1], cc.iloc[-2]
        if pd.isna(cur) or pd.isna(prev):
            return None
        signal = None
        if cur > prev:
            signal = "buy"
        elif cur < prev:
            signal = "sell"
        if return_value:
            return signal, cur, prev
        return signal
    except Exception:
        return None
