import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_elder_ray_signal(symbol, timeframe, period=13, return_value=False):
    """
    Elder Ray signal (trend EMA + bull/bear power):
      buy  — EMA rising and bear power negative but strengthening
      sell — EMA falling and bull power positive but weakening

    Returns:
        Signal ("buy", "sell", or None) or (signal, bull_power, bear_power)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 30)
        if rates is None or len(rates) < period + 2:
            return None
        highs = pd.Series([rate[2] for rate in rates])
        lows = pd.Series([rate[3] for rate in rates])
        closes = pd.Series([rate[4] for rate in rates])
        ema = closes.ewm(span=period, adjust=False).mean()
        bull = highs - ema
        bear = lows - ema
        if pd.isna(ema.iloc[-1]) or pd.isna(ema.iloc[-2]):
            return None
        signal = None
        if ema.iloc[-1] > ema.iloc[-2] and bear.iloc[-1] < 0 and bear.iloc[-1] > bear.iloc[-2]:
            signal = "buy"
        elif ema.iloc[-1] < ema.iloc[-2] and bull.iloc[-1] > 0 and bull.iloc[-1] < bull.iloc[-2]:
            signal = "sell"
        if return_value:
            return signal, bull.iloc[-1], bear.iloc[-1]
        return signal
    except Exception:
        return None
