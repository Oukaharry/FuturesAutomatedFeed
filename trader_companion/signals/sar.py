import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_sar_signal(symbol, timeframe, step=0.02, max_step=0.2, return_value=False):
    """
    Get Parabolic SAR signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        step: SAR step
        max_step: SAR max step
        return_value: If True, returns (signal, sar_value), else just signal
    Returns:
        Signal ("buy", "sell", or None) or (signal, sar_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 100)
        if rates is None or len(rates) < 2:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        sar = np.zeros_like(closes)
        trend = 1  # 1 for up, -1 for down
        af = step
        ep = highs[0] if trend == 1 else lows[0]
        sar[0] = lows[0] if trend == 1 else highs[0]
        for i in range(1, len(closes)):
            sar[i] = sar[i-1] + af * (ep - sar[i-1])
            if trend == 1:
                if highs[i] > ep:
                    ep = highs[i]
                    af = min(af + step, max_step)
                if lows[i] < sar[i]:
                    trend = -1
                    sar[i] = ep
                    ep = lows[i]
                    af = step
            else:
                if lows[i] < ep:
                    ep = lows[i]
                    af = min(af + step, max_step)
                if highs[i] > sar[i]:
                    trend = 1
                    sar[i] = ep
                    ep = highs[i]
                    af = step
        sar_value = sar[-1]
        signal = "buy" if closes[-1] > sar_value else "sell"
        if return_value:
            return signal, sar_value
        return signal
    except Exception:
        return None
