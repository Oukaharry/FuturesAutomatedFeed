from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Trade:
    client_id: str
    position_id: object
    symbol: str
    direction: str
    volume: float
    entry_dt: datetime
    exit_dt: datetime
    net_pnl: float
    deal_count: int = 1
