"""
RSI Signal Generator
Provides RSI-based trading signals for automated trading
"""

import logging
import MetaTrader5 as mt5
import numpy as np
from typing import Union, Tuple, Optional

def calculate_rsi(prices: list, period: int = 14) -> float:
    """
    Calculate RSI (Relative Strength Index)
    
    Args:
        prices: List of closing prices
        period: RSI calculation period
        
    Returns:
        RSI value (0-100)
    """
    if len(prices) < period + 1:
        return 50.0  # Neutral RSI if not enough data
    
    # Calculate price changes
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    
    # Separate gains and losses
    gains = [max(0, delta) for delta in deltas]
    losses = [max(0, -delta) for delta in deltas]
    
    # Calculate average gains and losses
    if len(gains) >= period:
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
    else:
        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
    
    # Calculate RSI
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi

def get_price_data(symbol: str, timeframe: int, count: int = 100) -> Optional[list]:
    """
    Get price data from MT5
    
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe constant
        count: Number of bars to retrieve
        
    Returns:
        List of closing prices or None if error
    """
    try:
        # Get rates from MT5
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        
        if rates is None or len(rates) == 0:
            logging.warning(f"No price data available for {symbol}")
            return None
        
        # Extract closing prices
        closes = [rate[4] for rate in rates]  # rate[4] is close price
        
        return closes
        
    except Exception as e:
        logging.error(f"Error getting price data for {symbol}: {e}")
        return None

def get_rsi_signal(symbol: str, timeframe: int = mt5.TIMEFRAME_M5, 
                  period: int = 14, overbought: float = 70, oversold: float = 30,
                  return_value: bool = False) -> Union[str, Tuple[str, float]]:
    """
    Get RSI trading signal
    
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe constant
        period: RSI calculation period
        overbought: Overbought threshold
        oversold: Oversold threshold
        return_value: Whether to return RSI value along with signal
        
    Returns:
        Trading signal ('buy', 'sell', 'hold') or tuple of (signal, rsi_value)
    """
    try:
        # Get price data
        prices = get_price_data(symbol, timeframe, period + 50)  # Get extra data for accuracy
        
        if prices is None or len(prices) < period + 1:
            logging.warning(f"Insufficient price data for RSI calculation on {symbol}")
            if return_value:
                return 'hold', 50.0
            return 'hold'
        
        # Calculate RSI
        rsi_value = calculate_rsi(prices, period)
        
        # Generate signal
        if rsi_value <= oversold:
            signal = 'buy'
        elif rsi_value >= overbought:
            signal = 'sell'
        else:
            signal = 'hold'
        
        logging.debug(f"RSI Signal for {symbol}: RSI={rsi_value:.2f}, Signal={signal}")
        
        if return_value:
            return signal, rsi_value
        return signal
        
    except Exception as e:
        logging.error(f"Error calculating RSI signal for {symbol}: {e}")
        if return_value:
            return 'hold', 50.0
        return 'hold'

def get_rsi_value(symbol: str, timeframe: int = mt5.TIMEFRAME_M5, period: int = 14) -> float:
    """
    Get current RSI value for symbol
    
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe constant
        period: RSI calculation period
        
    Returns:
        Current RSI value
    """
    try:
        prices = get_price_data(symbol, timeframe, period + 50)
        
        if prices is None or len(prices) < period + 1:
            return 50.0
        
        return calculate_rsi(prices, period)
        
    except Exception as e:
        logging.error(f"Error getting RSI value for {symbol}: {e}")
        return 50.0