import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_supertrend_signal(symbol, timeframe, period=10, multiplier=3.0, return_value=False):
    """
    Get Supertrend signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: ATR period for Supertrend
        multiplier: Multiplier for ATR
        return_value: If True, returns (signal, supertrend), else just signal
    Returns:
        Signal ("bullish", "bearish", or None) or (signal, supertrend)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 50)
        if rates is None or len(rates) < period + 2:
            return None
        highs = np.array([rate[2] for rate in rates], dtype=float)
        lows = np.array([rate[3] for rate in rates], dtype=float)
        closes = np.array([rate[4] for rate in rates], dtype=float)
        n = len(closes)

        # True range: max of (H-L, |H-prevC|, |L-prevC|)
        prev_close = np.roll(closes, 1)
        tr = np.maximum.reduce([
            highs - lows,
            np.abs(highs - prev_close),
            np.abs(lows - prev_close),
        ])
        tr[0] = highs[0] - lows[0]
        atr = pd.Series(tr).rolling(window=period).mean().to_numpy()

        hl2 = (highs + lows) / 2.0
        upper = hl2 + multiplier * atr
        lower = hl2 - multiplier * atr

        start = period  # first index with a valid ATR
        if n <= start + 1:
            return None

        f_upper = upper.copy()
        f_lower = lower.copy()
        direction = np.ones(n)
        for i in range(start + 1, n):
            # Band carry-over (classic Supertrend rules)
            if upper[i] < f_upper[i - 1] or closes[i - 1] > f_upper[i - 1]:
                f_upper[i] = upper[i]
            else:
                f_upper[i] = f_upper[i - 1]
            if lower[i] > f_lower[i - 1] or closes[i - 1] < f_lower[i - 1]:
                f_lower[i] = lower[i]
            else:
                f_lower[i] = f_lower[i - 1]

            if closes[i] > f_upper[i - 1]:
                direction[i] = 1
            elif closes[i] < f_lower[i - 1]:
                direction[i] = -1
            else:
                direction[i] = direction[i - 1]

        supertrend = float(f_lower[-1] if direction[-1] == 1 else f_upper[-1])
        signal = "bullish" if direction[-1] == 1 else "bearish"
        if return_value:
            return signal, supertrend
        return signal
    except Exception:
        return None
