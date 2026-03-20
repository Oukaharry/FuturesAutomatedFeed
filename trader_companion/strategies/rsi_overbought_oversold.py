from signals.rsi import get_rsi_signal

def rsi_overbought_oversold_strategy(symbol, timeframe, rsi_period=14, rsi_overbought=70, rsi_oversold=30, risk_percent=2.0, return_value=False):
    """
    RSI Overbought/Oversold strategy logic.
    User-editable parameters:
        rsi_period: int - RSI calculation period
        rsi_overbought: int/float - Overbought threshold
        rsi_oversold: int/float - Oversold threshold
        risk_percent: float - Risk per trade (not used in signal, but available for position sizing)
    Returns:
        'buy', 'sell', or None (or tuple with RSI value if return_value=True)
    """
    return get_rsi_signal(
        symbol=symbol,
        timeframe=timeframe,
        period=rsi_period,
        overbought=rsi_overbought,
        oversold=rsi_oversold,
        return_value=return_value
    )
