def usd_to_points_mt5(symbol_info, usd, lot_size):
    """
    Convert a dollar TP/SL to MT5 points for the given symbol.
    symbol_info: dict from MT5 API with 'trade_tick_value', 'trade_tick_size', 'point'
    usd: TP or SL value in dollars
    lot_size: trade size in lots
    Returns: int (points)
    """
    pip_value = symbol_info['trade_tick_value'] * lot_size
    if pip_value == 0 or symbol_info['point'] == 0:
        return 0
    points = int(abs(usd) / pip_value * (symbol_info['trade_tick_size'] / symbol_info['point']))
    return points