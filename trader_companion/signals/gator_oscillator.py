import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_gator_oscillator_signal(symbol, timeframe, return_value=False):
    """
    Gator/Alligator alignment signal:
      buy  — lips > teeth > jaw (alligator eating upward)
      sell — lips < teeth < jaw (alligator eating downward)

    Returns:
        Signal ("buy", "sell", or None) or (signal, jaw, teeth, lips)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 60)
        if rates is None or len(rates) < 30:
            return None
        highs = pd.Series([rate[2] for rate in rates])
        lows = pd.Series([rate[3] for rate in rates])
        median = (highs + lows) / 2.0

        def _smma(s, period):
            return s.ewm(alpha=1.0 / period, adjust=False).mean()

        jaw = _smma(median, 13).shift(8).iloc[-1]
        teeth = _smma(median, 8).shift(5).iloc[-1]
        lips = _smma(median, 5).shift(3).iloc[-1]
        if pd.isna(jaw) or pd.isna(teeth) or pd.isna(lips):
            return None
        signal = None
        if lips > teeth > jaw:
            signal = "buy"
        elif lips < teeth < jaw:
            signal = "sell"
        if return_value:
            return signal, jaw, teeth, lips
        return signal
    except Exception:
        return None
