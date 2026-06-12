import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_vortex_signal(symbol, timeframe, period=14, return_value=False):
    """
    Vortex Indicator signal: VI+ above VI- = buy, VI- above VI+ = sell.

    Returns:
        Signal ("buy", "sell", or None) or (signal, vi_plus, vi_minus)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 30)
        if rates is None or len(rates) < period + 2:
            return None
        highs = pd.Series([rate[2] for rate in rates])
        lows = pd.Series([rate[3] for rate in rates])
        closes = pd.Series([rate[4] for rate in rates])
        prev_close = closes.shift(1)
        tr = pd.concat([(highs - lows),
                        (highs - prev_close).abs(),
                        (lows - prev_close).abs()], axis=1).max(axis=1)
        vm_plus = (highs - lows.shift(1)).abs()
        vm_minus = (lows - highs.shift(1)).abs()
        tr_sum = tr.rolling(window=period).sum()
        vi_plus = (vm_plus.rolling(window=period).sum() / tr_sum).iloc[-1]
        vi_minus = (vm_minus.rolling(window=period).sum() / tr_sum).iloc[-1]
        if pd.isna(vi_plus) or pd.isna(vi_minus):
            return None
        signal = None
        if vi_plus > vi_minus:
            signal = "buy"
        elif vi_minus > vi_plus:
            signal = "sell"
        if return_value:
            return signal, vi_plus, vi_minus
        return signal
    except Exception:
        return None
