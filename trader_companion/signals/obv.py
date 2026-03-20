import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_obv_signal(symbol, timeframe, return_value=False):
    """
    Get On-Balance Volume (OBV) signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        return_value: If True, returns the OBV value
    Returns:
        OBV value or None
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 100)
        if rates is None or len(rates) < 2:
            return None
        closes = np.array([rate[4] for rate in rates])
        volumes = np.array([rate[5] for rate in rates])
        obv = [volumes[0]]
        for i in range(1, len(closes)):
            if closes[i] > closes[i-1]:
                obv.append(obv[-1] + volumes[i])
            elif closes[i] < closes[i-1]:
                obv.append(obv[-1] - volumes[i])
            else:
                obv.append(obv[-1])
        obv_value = obv[-1]
        if return_value:
            return obv_value
        return obv_value
    except Exception:
        return None
