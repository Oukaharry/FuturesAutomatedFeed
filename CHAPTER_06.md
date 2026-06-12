# Chapter 6 — Indicators and strategies

_Exported from CODEBASE_REFERENCE.pdf as plain Markdown. Paste this into another Claude conversation, Notion, or any Markdown viewer._

A strategy is a recipe that decides when to buy or sell. Most strategies are built out of _technical indicators_ — RSI, moving averages, Bollinger Bands. Each indicator is a tiny pure function: it takes a pandas DataFrame of OHLC bars and returns a Series of values. We build the helper module first, then a single indicator template, then the rest, and finally the strategy that combines them.

**Files in this chapter:**

- `trader_companion/utils/__init__.py`
- `trader_companion/utils/config.py`
- `trader_companion/utils/trading_helpers.py`
- `trader_companion/signals/__init__.py`
- `trader_companion/signals/sma.py`
- `trader_companion/signals/ema.py`
- `trader_companion/signals/rsi.py`
- `trader_companion/signals/macd.py`
- `trader_companion/signals/bb.py`
- `trader_companion/signals/atr.py`
- `trader_companion/signals/adx.py`
- `trader_companion/signals/dmi.py`
- `trader_companion/signals/cci.py`
- `trader_companion/signals/momentum.py`
- `trader_companion/signals/roc.py`
- `trader_companion/signals/obv.py`
- `trader_companion/signals/mfi.py`
- `trader_companion/signals/stochastic.py`
- `trader_companion/signals/supertrend.py`
- `trader_companion/signals/sar.py`
- `trader_companion/signals/tsi.py`
- `trader_companion/signals/wr.py`
- `trader_companion/signals/cmo.py`
- `trader_companion/signals/coppock_curve.py`
- `trader_companion/signals/donchian_channel.py`
- `trader_companion/signals/elder_ray.py`
- `trader_companion/signals/fractal.py`
- `trader_companion/signals/gator_oscillator.py`
- `trader_companion/signals/keltner_channel.py`
- `trader_companion/signals/price_channel.py`
- `trader_companion/signals/ultimate_oscillator.py`
- `trader_companion/signals/vortex.py`
- `trader_companion/strategies/__init__.py`
- `trader_companion/strategies/rsi_overbought_oversold.py`

---

### `trader_companion/utils/__init__.py`

> File not present in this checkout — skipped.

### `trader_companion/utils/config.py`

> File not present in this checkout — skipped.

### `trader_companion/utils/trading_helpers.py`

> File not present in this checkout — skipped.

### `trader_companion/signals/__init__.py`

_2 loc · 0 classes · 0 functions · 0 imports_

---

### `trader_companion/signals/sma.py`

_27 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_sma_signal`

```python
def get_sma_signal(symbol, timeframe, period=21, return_value=False)
```
> Get SMA value for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     period: SMA period     return_value: If True, returns the SMA value Returns:     SMA value or None

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_sma_signal(symbol, timeframe, period=21, return_value=False):
    """
    Get SMA value for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: SMA period
        return_value: If True, returns the SMA value
    Returns:
        SMA value or None
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period:
            return None
        closes = np.array([rate[4] for rate in rates])
        sma = pd.Series(closes).rolling(window=period).mean().iloc[-1]
        if return_value:
            return sma
        return sma
    except Exception:
        return None
```

---

### `trader_companion/signals/ema.py`

_27 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_ema_signal`

```python
def get_ema_signal(symbol, timeframe, period=21, return_value=False)
```
> Get EMA value for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     period: EMA period     return_value: If True, returns the EMA value Returns:     EMA value or None

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_ema_signal(symbol, timeframe, period=21, return_value=False):
    """
    Get EMA value for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: EMA period
        return_value: If True, returns the EMA value
    Returns:
        EMA value or None
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period:
            return None
        closes = np.array([rate[4] for rate in rates])
        ema = pd.Series(closes).ewm(span=period, adjust=False).mean().iloc[-1]
        if return_value:
            return ema
        return ema
    except Exception:
        return None
```

---

### `trader_companion/signals/rsi.py`

_150 loc · 0 classes · 4 functions · 4 imports_

**Module docstring**

> RSI Signal Generator Provides RSI-based trading signals for automated trading

**Imports**

```python
import logging
import MetaTrader5 as mt5
import numpy as np
from typing import Union, Tuple, Optional
```

**Functions**

#### `calculate_rsi`

```python
def calculate_rsi(prices: list, period: int=14) -> float
```
> Calculate RSI (Relative Strength Index)  Args:     prices: List of closing prices     period: RSI calculation period      Returns:     RSI value (0-100)

**What it does, step by step:**

1. <b>if</b> <code>len(prices) &lt; period + 1</code>: branches conditionally.
2. Assigns <code>deltas</code> = <code>[prices[i] - prices[i - 1] for i in range(1, len(prices))]</code>.
3. Assigns <code>gains</code> = <code>[max(0, delta) for delta in deltas]</code>.
4. Assigns <code>losses</code> = <code>[max(0, -delta) for delta in deltas]</code>.
5. <b>if</b> <code>len(gains) &gt;= period</code>: branches conditionally (with an <b>else</b>/elif arm).
6. <b>if</b> <code>avg_loss == 0</code>: branches conditionally.
7. Assigns <code>rs</code> = <code>avg_gain / avg_loss</code>.
8. Assigns <code>rsi</code> = <code>100 - 100 / (1 + rs)</code>.
9. <b>return</b> <code>rsi</code>.

```python
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
```

#### `get_price_data`

```python
def get_price_data(symbol: str, timeframe: int, count: int=100) -> Optional[list]
```
> Get price data from MT5  Args:     symbol: Trading symbol     timeframe: MT5 timeframe constant     count: Number of bars to retrieve      Returns:     List of closing prices or None if error

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

#### `get_rsi_signal`

```python
def get_rsi_signal(symbol: str, timeframe: int=mt5.TIMEFRAME_M5, period: int=14, overbought: float=70, oversold: float=30, return_value: bool=False) -> Union[str, Tuple[str, float]]
```
> Get RSI trading signal  Args:     symbol: Trading symbol     timeframe: MT5 timeframe constant     period: RSI calculation period     overbought: Overbought threshold     oversold: Oversold threshold     return_value: Whether to return RSI value along with signal      Returns:     Trading signal ('buy', 'sell', 'hold') or tuple of (signal, rsi_value)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

#### `get_rsi_value`

```python
def get_rsi_value(symbol: str, timeframe: int=mt5.TIMEFRAME_M5, period: int=14) -> float
```
> Get current RSI value for symbol  Args:     symbol: Trading symbol     timeframe: MT5 timeframe constant     period: RSI calculation period      Returns:     Current RSI value

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

---

### `trader_companion/signals/macd.py`

_42 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_macd_signal`

```python
def get_macd_signal(symbol, timeframe, fast_period=12, slow_period=26, signal_period=9, return_value=False)
```
> Get MACD signal for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     fast_period: Fast EMA period     slow_period: Slow EMA period     signal_period: Signal line EMA period     return_value: If True, returns (signal, macd, signal_line) tuple, otherwise just signal Returns:     If return_value=False: signal string ("buy", "sell", or None)     If return_value=True: tuple (signal, macd, signal_line)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_macd_signal(symbol, timeframe, fast_period=12, slow_period=26, signal_period=9, return_value=False):
    """
    Get MACD signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        fast_period: Fast EMA period
        slow_period: Slow EMA period
        signal_period: Signal line EMA period
        return_value: If True, returns (signal, macd, signal_line) tuple, otherwise just signal
    Returns:
        If return_value=False: signal string ("buy", "sell", or None)
        If return_value=True: tuple (signal, macd, signal_line)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, slow_period + signal_period + 10)
        if rates is None or len(rates) < slow_period + signal_period:
            return None
        closes = np.array([rate[4] for rate in rates])
        fast_ema = pd.Series(closes).ewm(span=fast_period, adjust=False).mean()
        slow_ema = pd.Series(closes).ewm(span=slow_period, adjust=False).mean()
        macd = fast_ema - slow_ema
        signal_line = macd.ewm(span=signal_period, adjust=False).mean()
        # Use the last value for signal
        macd_val = macd.iloc[-1]
        signal_val = signal_line.iloc[-1]
        if macd_val > signal_val:
            signal = "buy"
        elif macd_val < signal_val:
            signal = "sell"
        else:
            signal = None
        if return_value:
            return signal, macd_val, signal_val
        return signal
    except Exception:
        return None
```

---

### `trader_companion/signals/bb.py`

_38 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_bb_signal`

```python
def get_bb_signal(symbol, timeframe, period=20, deviation=2.0, return_value=False)
```
> Get Bollinger Bands signal for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     period: BB period     deviation: Standard deviation multiplier     return_value: If True, returns (signal, upper, lower, close), else just signal Returns:     Signal ("upper", "lower", or None) or (signal, upper, lower, close)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_bb_signal(symbol, timeframe, period=20, deviation=2.0, return_value=False):
    """
    Get Bollinger Bands signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: BB period
        deviation: Standard deviation multiplier
        return_value: If True, returns (signal, upper, lower, close), else just signal
    Returns:
        Signal ("upper", "lower", or None) or (signal, upper, lower, close)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period:
            return None
        closes = np.array([rate[4] for rate in rates])
        series = pd.Series(closes)
        sma = series.rolling(window=period).mean().iloc[-1]
        std = series.rolling(window=period).std().iloc[-1]
        upper = sma + deviation * std
        lower = sma - deviation * std
        close = closes[-1]
        signal = None
        if close > upper:
            signal = "upper"
        elif close < lower:
            signal = "lower"
        if return_value:
            return signal, upper, lower, close
        return signal
    except Exception:
        return None
```

---

### `trader_companion/signals/atr.py`

_30 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_atr_signal`

```python
def get_atr_signal(symbol, timeframe, period=14, return_value=False)
```
> Get Average True Range (ATR) value for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     period: ATR period     return_value: If True, returns the ATR value Returns:     ATR value or None

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_atr_signal(symbol, timeframe, period=14, return_value=False):
    """
    Get Average True Range (ATR) value for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: ATR period
        return_value: If True, returns the ATR value
    Returns:
        ATR value or None
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 2)
        if rates is None or len(rates) < period + 1:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        trs = np.maximum(highs[1:] - lows[1:], np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1]))
        atr = pd.Series(trs).rolling(window=period).mean().iloc[-1]
        if return_value:
            return atr
        return atr
    except Exception:
        return None
```

---

### `trader_companion/signals/adx.py`

_40 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_adx_signal`

```python
def get_adx_signal(symbol, timeframe, period=14, threshold=25, return_value=False)
```
> Get ADX value for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     period: ADX period     threshold: ADX threshold for trend strength     return_value: If True, returns (signal, adx_value), else just signal Returns:     Signal ("trend" or None) or (signal, adx_value)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_adx_signal(symbol, timeframe, period=14, threshold=25, return_value=False):
    """
    Get ADX value for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: ADX period
        threshold: ADX threshold for trend strength
        return_value: If True, returns (signal, adx_value), else just signal
    Returns:
        Signal ("trend" or None) or (signal, adx_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 50)
        if rates is None or len(rates) < period + 1:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        plus_dm = highs[1:] - highs[:-1]
        minus_dm = lows[:-1] - lows[1:]
        plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0)
        minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0)
        tr = np.maximum(highs[1:] - lows[1:], np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1]))
        atr = pd.Series(tr).rolling(window=period).mean()
        plus_di = 100 * pd.Series(plus_dm).rolling(window=period).mean() / atr
        minus_di = 100 * pd.Series(minus_dm).rolling(window=period).mean() / atr
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = pd.Series(dx).rolling(window=period).mean().iloc[-1]
        signal = "trend" if adx > threshold else None
        if return_value:
            return signal, adx
        return signal
    except Exception:
        return None
```

---

### `trader_companion/signals/dmi.py`

_42 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_dmi_signal`

```python
def get_dmi_signal(symbol, timeframe, period=14, threshold=25, return_value=False)
```
> Get Directional Movement Index (DMI) signal for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     period: DMI period     threshold: DMI threshold     return_value: If True, returns (signal, plus_di, minus_di), else just signal Returns:     Signal ("bullish", "bearish", or None) or (signal, plus_di, minus_di)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_dmi_signal(symbol, timeframe, period=14, threshold=25, return_value=False):
    """
    Get Directional Movement Index (DMI) signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: DMI period
        threshold: DMI threshold
        return_value: If True, returns (signal, plus_di, minus_di), else just signal
    Returns:
        Signal ("bullish", "bearish", or None) or (signal, plus_di, minus_di)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 50)
        if rates is None or len(rates) < period + 1:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        plus_dm = highs[1:] - highs[:-1]
        minus_dm = lows[:-1] - lows[1:]
        plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0)
        minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0)
        tr = np.maximum(highs[1:] - lows[1:], np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1]))
        atr = pd.Series(tr).rolling(window=period).mean()
        plus_di = 100 * pd.Series(plus_dm).rolling(window=period).mean() / atr
        minus_di = 100 * pd.Series(minus_dm).rolling(window=period).mean() / atr
        signal = None
        if plus_di.iloc[-1] > minus_di.iloc[-1] and plus_di.iloc[-1] > threshold:
            signal = "bullish"
        elif minus_di.iloc[-1] > plus_di.iloc[-1] and minus_di.iloc[-1] > threshold:
            signal = "bearish"
        if return_value:
            return signal, plus_di.iloc[-1], minus_di.iloc[-1]
        return signal
    except Exception:
        return None
```

---

### `trader_companion/signals/cci.py`

_40 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_cci_signal`

```python
def get_cci_signal(symbol, timeframe, period=20, overbought=100, oversold=-100, return_value=False)
```
> Get Commodity Channel Index (CCI) signal for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     period: CCI period     overbought: Overbought threshold     oversold: Oversold threshold     return_value: If True, returns (signal, cci_value), else just signal Returns:     Signal ("buy", "sell", or None) or (signal, cci_value)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_cci_signal(symbol, timeframe, period=20, overbought=100, oversold=-100, return_value=False):
    """
    Get Commodity Channel Index (CCI) signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: CCI period
        overbought: Overbought threshold
        oversold: Oversold threshold
        return_value: If True, returns (signal, cci_value), else just signal
    Returns:
        Signal ("buy", "sell", or None) or (signal, cci_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        typical_price = (highs + lows + closes) / 3
        tp_series = pd.Series(typical_price)
        sma = tp_series.rolling(window=period).mean().iloc[-1]
        mean_dev = np.mean(np.abs(tp_series[-period:] - sma))
        cci = (tp_series.iloc[-1] - sma) / (0.015 * mean_dev) if mean_dev != 0 else 0
        signal = None
        if cci > overbought:
            signal = "sell"
        elif cci < oversold:
            signal = "buy"
        if return_value:
            return signal, cci
        return signal
    except Exception:
        return None
```

---

### `trader_companion/signals/momentum.py`

_33 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_momentum_signal`

```python
def get_momentum_signal(symbol, timeframe, period=10, threshold=0.3, return_value=False)
```
> Get Momentum value for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     period: Momentum period     threshold: Momentum threshold     return_value: If True, returns (signal, momentum_value), else just signal Returns:     Signal ("bullish", "bearish", or None) or (signal, momentum_value)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_momentum_signal(symbol, timeframe, period=10, threshold=0.3, return_value=False):
    """
    Get Momentum value for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: Momentum period
        threshold: Momentum threshold
        return_value: If True, returns (signal, momentum_value), else just signal
    Returns:
        Signal ("bullish", "bearish", or None) or (signal, momentum_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period + 1:
            return None
        closes = np.array([rate[4] for rate in rates])
        momentum = closes[-1] - closes[-period-1]
        signal = None
        if momentum > threshold:
            signal = "bullish"
        elif momentum < -threshold:
            signal = "bearish"
        if return_value:
            return signal, momentum
        return signal
    except Exception:
        return None
```

---

### `trader_companion/signals/roc.py`

_33 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_roc_signal`

```python
def get_roc_signal(symbol, timeframe, period=12, threshold=0, return_value=False)
```
> Get Rate of Change (ROC) signal for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     period: ROC period     threshold: ROC threshold     return_value: If True, returns (signal, roc_value), else just signal Returns:     Signal ("bullish", "bearish", or None) or (signal, roc_value)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_roc_signal(symbol, timeframe, period=12, threshold=0, return_value=False):
    """
    Get Rate of Change (ROC) signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: ROC period
        threshold: ROC threshold
        return_value: If True, returns (signal, roc_value), else just signal
    Returns:
        Signal ("bullish", "bearish", or None) or (signal, roc_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period + 1:
            return None
        closes = np.array([rate[4] for rate in rates])
        roc = ((closes[-1] - closes[-period-1]) / closes[-period-1]) * 100
        signal = None
        if roc > threshold:
            signal = "bullish"
        elif roc < -threshold:
            signal = "bearish"
        if return_value:
            return signal, roc
        return signal
    except Exception:
        return None
```

---

### `trader_companion/signals/obv.py`

_35 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_obv_signal`

```python
def get_obv_signal(symbol, timeframe, return_value=False)
```
> Get On-Balance Volume (OBV) signal for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     return_value: If True, returns the OBV value Returns:     OBV value or None

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

---

### `trader_companion/signals/mfi.py`

_43 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_mfi_signal`

```python
def get_mfi_signal(symbol, timeframe, period=14, overbought=80, oversold=20, return_value=False)
```
> Get Money Flow Index (MFI) signal for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     period: MFI period     overbought: Overbought threshold     oversold: Oversold threshold     return_value: If True, returns (signal, mfi_value), else just signal Returns:     Signal ("buy", "sell", or None) or (signal, mfi_value)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

---

### `trader_companion/signals/stochastic.py`

_42 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_stochastic_signal`

```python
def get_stochastic_signal(symbol, timeframe, k_period=14, d_period=3, overbought=80, oversold=20, return_value=False)
```
> Get Stochastic Oscillator signal for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     k_period: %K period     d_period: %D period     overbought: Overbought threshold     oversold: Oversold threshold     return_value: If True, returns (signal, k_value, d_value), else just signal Returns:     Signal ("buy", "sell", or None) or (signal, k_value, d_value)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_stochastic_signal(symbol, timeframe, k_period=14, d_period=3, overbought=80, oversold=20, return_value=False):
    """
    Get Stochastic Oscillator signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        k_period: %K period
        d_period: %D period
        overbought: Overbought threshold
        oversold: Oversold threshold
        return_value: If True, returns (signal, k_value, d_value), else just signal
    Returns:
        Signal ("buy", "sell", or None) or (signal, k_value, d_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, k_period + d_period + 10)
        if rates is None or len(rates) < k_period + d_period:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        lowest_low = pd.Series(lows).rolling(window=k_period).min()
        highest_high = pd.Series(highs).rolling(window=k_period).max()
        k = 100 * (closes - lowest_low) / (highest_high - lowest_low)
        d = k.rolling(window=d_period).mean()
        k_value = k.iloc[-1]
        d_value = d.iloc[-1]
        signal = None
        if k_value > overbought:
            signal = "sell"
        elif k_value < oversold:
            signal = "buy"
        if return_value:
            return signal, k_value, d_value
        return signal
    except Exception:
        return None
```

---

### `trader_companion/signals/supertrend.py`

_44 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_supertrend_signal`

```python
def get_supertrend_signal(symbol, timeframe, period=10, multiplier=3.0, return_value=False)
```
> Get Supertrend signal for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     period: ATR period for Supertrend     multiplier: Multiplier for ATR     return_value: If True, returns (signal, supertrend), else just signal Returns:     Signal ("bullish", "bearish", or None) or (signal, supertrend)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period + 1:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        atr = pd.Series(np.maximum(highs[1:] - lows[1:], np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1]))).rolling(window=period).mean()
        hl2 = (highs + lows) / 2
        upperband = hl2 - (multiplier * atr)
        lowerband = hl2 + (multiplier * atr)
        supertrend = np.zeros_like(closes)
        direction = np.ones_like(closes)
        for i in range(1, len(closes)):
            if closes[i] > upperband[i]:
                direction[i] = 1
            elif closes[i] < lowerband[i]:
                direction[i] = -1
            else:
                direction[i] = direction[i-1]
            supertrend[i] = lowerband[i] if direction[i] == 1 else upperband[i]
        signal = "bullish" if direction[-1] == 1 else "bearish"
        if return_value:
            return signal, supertrend[-1]
        return signal
    except Exception:
        return None
```

---

### `trader_companion/signals/sar.py`

_56 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_sar_signal`

```python
def get_sar_signal(symbol, timeframe, step=0.02, max_step=0.2, return_value=False)
```
> Get Parabolic SAR signal for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     step: SAR step     max_step: SAR max step     return_value: If True, returns (signal, sar_value), else just signal Returns:     Signal ("buy", "sell", or None) or (signal, sar_value)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
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
```

---

### `trader_companion/signals/tsi.py`

_39 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_tsi_signal`

```python
def get_tsi_signal(symbol, timeframe, r=25, s=13, return_value=False)
```
> Get True Strength Index (TSI) signal for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     r: Long EMA period     s: Short EMA period     return_value: If True, returns (signal, tsi_value), else just signal Returns:     Signal ("bullish", "bearish", or None) or (signal, tsi_value)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_tsi_signal(symbol, timeframe, r=25, s=13, return_value=False):
    """
    Get True Strength Index (TSI) signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        r: Long EMA period
        s: Short EMA period
        return_value: If True, returns (signal, tsi_value), else just signal
    Returns:
        Signal ("bullish", "bearish", or None) or (signal, tsi_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, r + s + 10)
        if rates is None or len(rates) < r + s:
            return None
        closes = np.array([rate[4] for rate in rates])
        diff = np.diff(closes)
        abs_diff = np.abs(diff)
        ema1 = pd.Series(diff).ewm(span=s, adjust=False).mean()
        ema2 = ema1.ewm(span=r, adjust=False).mean()
        abs_ema1 = pd.Series(abs_diff).ewm(span=s, adjust=False).mean()
        abs_ema2 = abs_ema1.ewm(span=r, adjust=False).mean()
        tsi = 100 * (ema2.iloc[-1] / abs_ema2.iloc[-1]) if abs_ema2.iloc[-1] != 0 else 0
        signal = None
        if tsi > 25:
            signal = "bullish"
        elif tsi < -25:
            signal = "bearish"
        if return_value:
            return signal, tsi
        return signal
    except Exception:
        return None
```

---

### `trader_companion/signals/wr.py`

_38 loc · 0 classes · 1 functions · 3 imports_

**Imports**

```python
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
```

**Functions**

#### `get_wr_signal`

```python
def get_wr_signal(symbol, timeframe, period=14, overbought=-20, oversold=-80, return_value=False)
```
> Get Williams %R signal for a given symbol and timeframe. Args:     symbol: Trading symbol     timeframe: MT5 timeframe     period: WR period     overbought: Overbought threshold     oversold: Oversold threshold     return_value: If True, returns (signal, wr_value), else just signal Returns:     Signal ("buy", "sell", or None) or (signal, wr_value)

**What it does, step by step:**

1. <b>try</b> block with 1 <b>except</b> clause.

```python
def get_wr_signal(symbol, timeframe, period=14, overbought=-20, oversold=-80, return_value=False):
    """
    Get Williams %R signal for a given symbol and timeframe.
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe
        period: WR period
        overbought: Overbought threshold
        oversold: Oversold threshold
        return_value: If True, returns (signal, wr_value), else just signal
    Returns:
        Signal ("buy", "sell", or None) or (signal, wr_value)
    """
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period:
            return None
        highs = np.array([rate[2] for rate in rates])
        lows = np.array([rate[3] for rate in rates])
        closes = np.array([rate[4] for rate in rates])
        highest_high = np.max(highs[-period:])
        lowest_low = np.min(lows[-period:])
        wr = -100 * (highest_high - closes[-1]) / (highest_high - lowest_low)
        signal = None
        if wr > overbought:
            signal = "sell"
        elif wr < oversold:
            signal = "buy"
        if return_value:
            return signal, wr
        return signal
    except Exception:
        return None
```

---

### `trader_companion/signals/cmo.py`

_7 loc · 0 classes · 1 functions · 1 imports_

**Imports**

```python
import pandas as pd
```

**Functions**

#### `get_cmo_signal`

```python
def get_cmo_signal(df: pd.DataFrame, period: int=14)
```
**What it does, step by step:**

1. <b>return</b> <code>0</code>.

```python
def get_cmo_signal(df: pd.DataFrame, period: int = 14):
    # Placeholder for Chande Momentum Oscillator (CMO) signal logic
    # Return 1 for buy, -1 for sell, 0 for neutral
    return 0
```

---

### `trader_companion/signals/coppock_curve.py`

_7 loc · 0 classes · 1 functions · 1 imports_

**Imports**

```python
import pandas as pd
```

**Functions**

#### `get_coppock_curve_signal`

```python
def get_coppock_curve_signal(df: pd.DataFrame)
```
**What it does, step by step:**

1. <b>return</b> <code>0</code>.

```python
def get_coppock_curve_signal(df: pd.DataFrame):
    # Placeholder for Coppock Curve signal logic
    # Return 1 for buy, -1 for sell, 0 for neutral
    return 0
```

---

### `trader_companion/signals/donchian_channel.py`

_7 loc · 0 classes · 1 functions · 1 imports_

**Imports**

```python
import pandas as pd
```

**Functions**

#### `get_donchian_channel_signal`

```python
def get_donchian_channel_signal(df: pd.DataFrame, period: int=20)
```
**What it does, step by step:**

1. <b>return</b> <code>0</code>.

```python
def get_donchian_channel_signal(df: pd.DataFrame, period: int = 20):
    # Placeholder for Donchian Channel signal logic
    # Return 1 for buy, -1 for sell, 0 for neutral
    return 0
```

---

### `trader_companion/signals/elder_ray.py`

_7 loc · 0 classes · 1 functions · 1 imports_

**Imports**

```python
import pandas as pd
```

**Functions**

#### `get_elder_ray_signal`

```python
def get_elder_ray_signal(df: pd.DataFrame, period: int=13)
```
**What it does, step by step:**

1. <b>return</b> <code>0</code>.

```python
def get_elder_ray_signal(df: pd.DataFrame, period: int = 13):
    # Placeholder for Elder Ray Index signal logic
    # Return 1 for buy, -1 for sell, 0 for neutral
    return 0
```

---

### `trader_companion/signals/fractal.py`

_7 loc · 0 classes · 1 functions · 1 imports_

**Imports**

```python
import pandas as pd
```

**Functions**

#### `get_fractal_signal`

```python
def get_fractal_signal(df: pd.DataFrame)
```
**What it does, step by step:**

1. <b>return</b> <code>0</code>.

```python
def get_fractal_signal(df: pd.DataFrame):
    # Placeholder for Fractal Indicator signal logic
    # Return 1 for buy, -1 for sell, 0 for neutral
    return 0
```

---

### `trader_companion/signals/gator_oscillator.py`

_7 loc · 0 classes · 1 functions · 1 imports_

**Imports**

```python
import pandas as pd
```

**Functions**

#### `get_gator_oscillator_signal`

```python
def get_gator_oscillator_signal(df: pd.DataFrame)
```
**What it does, step by step:**

1. <b>return</b> <code>0</code>.

```python
def get_gator_oscillator_signal(df: pd.DataFrame):
    # Placeholder for Gator Oscillator signal logic
    # Return 1 for buy, -1 for sell, 0 for neutral
    return 0
```

---

### `trader_companion/signals/keltner_channel.py`

_7 loc · 0 classes · 1 functions · 1 imports_

**Imports**

```python
import pandas as pd
```

**Functions**

#### `get_keltner_channel_signal`

```python
def get_keltner_channel_signal(df: pd.DataFrame, period: int=20, atr_mult: float=2.0)
```
**What it does, step by step:**

1. <b>return</b> <code>0</code>.

```python
def get_keltner_channel_signal(df: pd.DataFrame, period: int = 20, atr_mult: float = 2.0):
    # Placeholder for Keltner Channel signal logic
    # Return 1 for buy, -1 for sell, 0 for neutral
    return 0
```

---

### `trader_companion/signals/price_channel.py`

_7 loc · 0 classes · 1 functions · 1 imports_

**Imports**

```python
import pandas as pd
```

**Functions**

#### `get_price_channel_signal`

```python
def get_price_channel_signal(df: pd.DataFrame, period: int=20)
```
**What it does, step by step:**

1. <b>return</b> <code>0</code>.

```python
def get_price_channel_signal(df: pd.DataFrame, period: int = 20):
    # Placeholder for Price Channel signal logic
    # Return 1 for buy, -1 for sell, 0 for neutral
    return 0
```

---

### `trader_companion/signals/ultimate_oscillator.py`

_7 loc · 0 classes · 1 functions · 1 imports_

**Imports**

```python
import pandas as pd
```

**Functions**

#### `get_ultimate_oscillator_signal`

```python
def get_ultimate_oscillator_signal(df: pd.DataFrame)
```
**What it does, step by step:**

1. <b>return</b> <code>0</code>.

```python
def get_ultimate_oscillator_signal(df: pd.DataFrame):
    # Placeholder for Ultimate Oscillator signal logic
    # Return 1 for buy, -1 for sell, 0 for neutral
    return 0
```

---

### `trader_companion/signals/vortex.py`

_7 loc · 0 classes · 1 functions · 1 imports_

**Imports**

```python
import pandas as pd
```

**Functions**

#### `get_vortex_signal`

```python
def get_vortex_signal(df: pd.DataFrame, period: int=14)
```
**What it does, step by step:**

1. <b>return</b> <code>0</code>.

```python
def get_vortex_signal(df: pd.DataFrame, period: int = 14):
    # Placeholder for Vortex Indicator signal logic
    # Return 1 for buy, -1 for sell, 0 for neutral
    return 0
```

---

### `trader_companion/strategies/__init__.py`

_2 loc · 0 classes · 0 functions · 0 imports_

---

### `trader_companion/strategies/rsi_overbought_oversold.py`

_22 loc · 0 classes · 1 functions · 1 imports_

**Imports**

```python
from signals.rsi import get_rsi_signal
```

**Functions**

#### `rsi_overbought_oversold_strategy`

```python
def rsi_overbought_oversold_strategy(symbol, timeframe, rsi_period=14, rsi_overbought=70, rsi_oversold=30, risk_percent=2.0, return_value=False)
```
> RSI Overbought/Oversold strategy logic. User-editable parameters:     rsi_period: int - RSI calculation period     rsi_overbought: int/float - Overbought threshold     rsi_oversold: int/float - Oversold threshold     risk_percent: float - Risk per trade (not used in signal, but available for position sizing) Returns:     'buy', 'sell', or None (or tuple with RSI value if return_value=True)

**What it does, step by step:**

1. <b>return</b> <code>get_rsi_signal(symbol=symbol, timeframe=timeframe, period=rsi_perio...</code>.

```python
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
```

---
