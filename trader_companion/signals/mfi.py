import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_mfi_signal(symbol, timeframe, period=14, overbought=80, oversold=20, return_value=False):
    """
    Get Money Flow Index (MFI) signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: MFI period
        overbought: Overbought threshold
        oversold: Oversold threshold
        return_value: If True, returns (signal, mfi_value), else just signal
    Returns:
        Signal ("buy", "sell", or None) or (signal, mfi_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period + 1:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        volumes = np.array([rate[5] for rate in rates])
        typical_price = (highs + lows + closes) / 3
        money_flow = typical_price * volumes
        positive_flow = np.where(typical_price[1:] > typical_price[:-1], money_flow[1:], 0)
        negative_flow = np.where(typical_price[1:] < typical_price[:-1], money_flow[1:], 0)
        pos_mf = pd.Series(positive_flow).rolling(window=period).sum().iloc[-1]
        neg_mf = pd.Series(negative_flow).rolling(window=period).sum().iloc[-1]
        mfi = 100 * pos_mf / (pos_mf + neg_mf) if (pos_mf + neg_mf) != 0 else 50
        signal = None
        if mfi > overbought:
            signal = "sell"
        elif mfi < oversold:
            signal = "buy"
        if return_value:
            return signal, mfi
        return signal
    except Exception:
        return None
