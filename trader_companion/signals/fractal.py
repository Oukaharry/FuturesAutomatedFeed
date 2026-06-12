import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_fractal_signal(symbol, timeframe, return_value=False):
    """
    Williams Fractal breakout signal: close above the last confirmed up
    fractal = buy, below the last confirmed down fractal = sell. The last
    two bars are excluded (fractals there are unconfirmed).

    Returns:
        Signal ("buy", "sell", or None) or (signal, last_up, last_down)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 100)
        if rates is None or len(rates) < 6:
            return None
        highs = pd.Series([rate[2] for rate in rates])
        lows = pd.Series([rate[3] for rate in rates])
        closes = pd.Series([rate[4] for rate in rates])
        up = ((highs > highs.shift(1)) & (highs > highs.shift(2))
              & (highs > highs.shift(-1)) & (highs > highs.shift(-2))).fillna(False)
        down = ((lows < lows.shift(1)) & (lows < lows.shift(2))
                & (lows < lows.shift(-1)) & (lows < lows.shift(-2))).fillna(False)
        # last 2 bars cannot host a confirmed fractal
        up_levels = highs[:-2][up[:-2].values]
        down_levels = lows[:-2][down[:-2].values]
        last_up = float(up_levels.iloc[-1]) if len(up_levels) else None
        last_down = float(down_levels.iloc[-1]) if len(down_levels) else None
        close = float(closes.iloc[-1])
        signal = None
        if last_up is not None and close > last_up:
            signal = "buy"
        elif last_down is not None and close < last_down:
            signal = "sell"
        if return_value:
            return signal, last_up, last_down
        return signal
    except Exception:
        return None
