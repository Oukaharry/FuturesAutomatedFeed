# prop_firm_manager.py - Prop Firm Blueprint Management System
# Handles different prop firm configurations for manual trading

import logging
import datetime
import copy

# ── Kenya / East Africa Time (UTC+3) ──────────────────────────────────
# Daily-rollover decisions (the per-account direction lock below) need to
# track the Kenya trading day, not the host machine's local clock.
# Without this, a Windows host whose timezone is not Kenya would leave
# yesterday's direction lock active past Kenya midnight, blocking the
# first trade of the new Kenya trading day.  Kenya does not observe DST,
# so a fixed UTC+3 offset is correct year-round.
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    _KENYA_TZ = ZoneInfo("Africa/Nairobi")
except Exception:  # pragma: no cover
    _KENYA_TZ = datetime.timezone(datetime.timedelta(hours=3), name="EAT")


def _kenya_today() -> datetime.date:
    """Today's calendar date in Kenya / EAT (UTC+3)."""
    return datetime.datetime.now(_KENYA_TZ).date()
from typing import Dict, Optional, Tuple

class PropFirmManager:
    """
    Manages prop firm-specific configurations and blueprints.
    
    Supported Prop Firms:
    - MFFU: My Funded Futures
    - Funded Next: Funded Next
    - Funded Next Flex: Funded Next Flex
    - FundingTicks: Funding Ticks
    - TopStep: TopStep
    - Trade Day: Trade Day (EOD Account Type)
    - Tradeify: Tradeify (Growth Account)
    - Top One Futures: Top One Futures
    - Funded Futures Family: Funded Futures Family ($50k EOD drawdown)
    
    All configurations are for $50,000 accounts and manual trading only.
    """
    
    # Mapping from detected firm code -> UI dropdown blueprint name
    DETECTED_TO_BLUEPRINT = {
        "MFFU": "MFFU_Flex",
        "MFFU_Flex": "MFFU_Flex",
        "Funded Next": "Funded Next",
        "FundedNext": "Funded Next",
        "Funded Next Flex": "Funded Next Flex",
        "FundedNextFlex": "Funded Next Flex",
        "FundingTicks": "FundingTicks",
        "Trade Day": "TradeDay",
        "TopStep": "TopStep",
        "TopStep RTP": "TopStep RTP",
        "TopStep_RTP": "TopStep RTP",
        "Apex": "Apex",
        "Tradeify": "Tradeify",
        "Lucid": "Lucid",
        "AlphaFutures": "Alpha Futures",
        "AlphaFutures GC": "Alpha Futures",
        "Top One Futures": "Top One Futures",
        "Funded Futures Family": "Funded Futures Family",
        "FFF": "Funded Futures Family",
        "The5ers": "The5ers",
        "5ers": "The5ers",
        "Goat Funded Futures": "GoatFunded",
        "GoatFunded": "GoatFunded",
        "GFF": "GoatFunded",
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.current_firm_code = "MFFU_Flex"  # Default prop firm

        # Per-account daily direction locks: {account_number: {"date": date, "direction": "BUY"/"SELL"}}
        self._account_direction_locks: Dict[str, Dict] = {}

        # Prop firm blueprints - $50k account configurations only core challange with the flex addon
        self.firm_blueprints = {
            "MFFU_Flex": {
                "name": "MFFU",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Funded Phase", "Farming Phase"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 52,
                            "tradovate_sl_ticks": 133,
                            "mt5_volume": 4,
                            "mt5_tp_points": 15,
                            "mt5_sl_points": 18
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 52,
                            "tradovate_sl_ticks": 133,
                            "mt5_volume": 7,
                            "mt5_tp_points": 15,
                            "mt5_sl_points": 18
                        }
                    },
                    "challenge_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 52,
                            "tradovate_sl_ticks": 133,
                            "mt5_volume": 10,
                            "mt5_tp_points": 15,
                            "mt5_sl_points": 18
                        }
                    },
                    "challenge_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 52,
                            "tradovate_sl_ticks": 133,
                            "mt5_volume": 13,
                            "mt5_tp_points": 15,
                            "mt5_sl_points": 18
                        }
                    },
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 133,
                            "mt5_volume": 16,
                            "mt5_tp_points": 88,
                            "mt5_sl_points": 18
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 267,
                            "tradovate_sl_ticks": 133,
                            "mt5_volume": 19,
                            "mt5_tp_points": 78,
                            "mt5_sl_points": 18
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 267,
                            "tradovate_sl_ticks": 133,
                            "mt5_volume": 3,
                            "mt5_tp_points": 78,
                            "mt5_sl_points": 18
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 267,
                            "tradovate_sl_ticks": 133,
                            "mt5_volume": 6,
                            "mt5_tp_points": 78,
                            "mt5_sl_points": 18
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 154,
                            "tradovate_sl_ticks": 600,
                            "mt5_volume": 3.2,
                            "mt5_tp_points": 146,
                            "mt5_sl_points": 43
                        }
                    }
                }
            },
            "Funded Next": {
                "name": "Funded Next",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Payout 1", "Payout 2", "Payout 3", "Payout 4", "Farming Phase"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 102,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 3.6,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 30
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 102,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 6.2,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 30
                        }
                    },
                    "challenge_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 101,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 10.4,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 30
                        }
                    },
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 520,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 18.4,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 134
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 220,
                            "tradovate_sl_ticks": 260,
                            "mt5_volume": 17,
                            "mt5_tp_points": 61,
                            "mt5_sl_points": 59
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 220,
                            "tradovate_sl_ticks": 245,
                            "mt5_volume": 3,
                            "mt5_tp_points": 57,
                            "mt5_sl_points": 59
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 220,
                            "tradovate_sl_ticks": 238,
                            "mt5_volume": 0,
                            "mt5_tp_points": 55,
                            "mt5_sl_points": 59
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 204,
                            "tradovate_sl_ticks": 600,
                            "mt5_volume": 3.2,
                            "mt5_tp_points": 146,
                            "mt5_sl_points": 55
                        }
                    }
                }
            },
            "FundingTicks": {
                "name": "FundingTicks",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Funded Phase", "Farming Phase"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 127,
                            "tradovate_sl_ticks": 250,
                            "mt5_volume": 5.2,
                            "mt5_tp_points": 58,
                            "mt5_sl_points": 36
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 127,
                            "tradovate_sl_ticks": 250,
                            "mt5_volume": 7.8,
                            "mt5_tp_points": 58,
                            "mt5_sl_points": 36
                        }
                    },
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 500,
                            "tradovate_sl_ticks": 250,
                            "mt5_volume": 13.8,
                            "mt5_tp_points": 58,
                            "mt5_sl_points": 129
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 150,
                            "tradovate_sl_ticks": 250,
                            "mt5_volume": 18,
                            "mt5_tp_points": 58,
                            "mt5_sl_points": 42
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 150,
                            "tradovate_sl_ticks": 250,
                            "mt5_volume": 8.6,
                            "mt5_tp_points": 58,
                            "mt5_sl_points": 42
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 150,
                            "tradovate_sl_ticks": 250,
                            "mt5_volume": 0,
                            "mt5_tp_points": 58,
                            "mt5_sl_points": 42
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 204,
                            "tradovate_sl_ticks": 600,
                            "mt5_volume": 1.6,
                            "mt5_tp_points": 146,
                            "mt5_sl_points": 55
                        }
                    }
                }
            },
            "TopStep": {
                "name": "TopStep",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Funded Phase", "Farming Phase"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 151,
                            "topstepx_sl_ticks": 201,
                            "mt5_volume": 4.6,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 42
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 151,
                            "topstepx_sl_ticks": 201,
                            "mt5_volume": 8.4,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 42
                        }
                    },
                    "funded_trade1": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 340,
                            "topstepx_sl_ticks": 201,
                            "mt5_volume": 16,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 89
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 140,
                            "topstepx_sl_ticks": 161,
                            "mt5_volume": 20,
                            "mt5_tp_points": 36,
                            "mt5_sl_points": 39
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 140,
                            "topstepx_sl_ticks": 146,
                            "mt5_volume": 18.0,
                            "mt5_tp_points": 32,
                            "mt5_sl_points": 39
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 140,
                            "topstepx_sl_ticks": 139,
                            "mt5_volume": 13.6,
                            "mt5_tp_points": 30,
                            "mt5_sl_points": 39
                        }
                    },"funded_trade_doubledip_1": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 340,
                            "topstepx_sl_ticks": 201,
                            "mt5_volume": 16,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 89
                        }
                    },"funded_trade_doubledip_2": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 140,
                            "topstepx_sl_ticks": 161,
                            "mt5_volume": 20,
                            "mt5_tp_points": 36,
                            "mt5_sl_points": 39
                        }
                    },"funded_trade_doubledip_3": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 140,
                            "topstepx_sl_ticks": 146,
                            "mt5_volume": 9,
                            "mt5_tp_points": 32,
                            "mt5_sl_points": 39
                        }
                    },"funded_trade_doubledip_4": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 140,
                            "topstepx_sl_ticks": 139,
                            "mt5_volume": 20,
                            "mt5_tp_points": 30,
                            "mt5_sl_points": 39
                        }
                    },
                    "farming": {
                        "50k": {
                            "topstepx_symbol": "MNQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 154,
                            "topstepx_sl_ticks": 600,
                            "mt5_volume": 3.6,
                            "mt5_tp_points": 146,
                            "mt5_sl_points": 43
                        }
                    }
                }
            },
            # ─── TopStep RTP (Rapid Trade Path / Combine variant) ────────────
            # Differs from the standard TopStep blueprint in that the funded
            # phase uses smaller, more granular trades (TP=114 ticks for the
            # first payout, TP=47 for subsequent payouts) instead of one big
            # trade per payout.  Each entry below mirrors the standard
            # TopStep keys (funded_trade1..4, doubledip_1..4, farming) so
            # the rest of the trader_app code works unchanged.
            "TopStep RTP": {
                "name": "TopStep RTP",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Funded Phase", "Farming Phase"],
                "strategy_configs": {
                    # ── Evaluation / Challenge ──
                    # Goal: +$3,000 profit before two losses in a row, while
                    # respecting the 50% consistency rule and $1,000 daily-loss
                    # limit.  Two winning trades of ~$1,510 each clear the
                    # target.  SL is tightened to -100 ticks (-$1,000) so a
                    # single loss does not breach the daily limit.
                    "challenge_trade1": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 151,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 4.6,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 42
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 151,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 8.4,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 42
                        }
                    },
                    # ── Funded ──
                    # funded_trade1 holds the Payout-1 flavor (TP=114 ticks /
                    # $1,140).  Three of these in the first payout cycle bring
                    # the account to ~$3,400.  funded_trade2-4 hold the
                    # recurring Payout-2+ flavor (TP=47 / $470); three of those
                    # per cycle clears the ~$1,400 subsequent-payout target.
                    # MT5 hedge values mirror the standard TopStep blueprint
                    # (same $50k account, same hedge math) — verify they still
                    # net out at the new TP/SL ratios before live use.
                    "funded_trade1": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 114,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 16,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 89
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 47,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 20,
                            "mt5_tp_points": 36,
                            "mt5_sl_points": 39
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 47,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 18.0,
                            "mt5_tp_points": 32,
                            "mt5_sl_points": 39
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 47,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 13.6,
                            "mt5_tp_points": 30,
                            "mt5_sl_points": 39
                        }
                    },
                    # ── Funded Payout 2+ (target ~$1,400) ───────────────
                    # New blueprints synced from the connector reference.
                    # Dormant until _PHASE_TRADE_ORDER routes "Payout 2+"
                    # to these keys; MT5 hedge values left at 0 — fill
                    # before enabling Payout-2+ hedged trading.
                    "funded_trade1_p2": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 47,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0
                        }
                    },
                    "funded_trade2_p2": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 47,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0
                        }
                    },
                    "funded_trade3_p2": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 47,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0
                        }
                    },
                    # ── Funded Double Dip ──
                    # User spec: "Same as funded trades sequence above."
                    # Doubledip_1 holds the Payout-1 flavor, doubledip_2-4
                    # hold the recurring Payout-2+ flavor.
                    "funded_trade_doubledip_1": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 114,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 16,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 89
                        }
                    },
                    "funded_trade_doubledip_2": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 47,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 20,
                            "mt5_tp_points": 36,
                            "mt5_sl_points": 39
                        }
                    },
                    "funded_trade_doubledip_3": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 47,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 9,
                            "mt5_tp_points": 32,
                            "mt5_sl_points": 39
                        }
                    },
                    "funded_trade_doubledip_4": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 47,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 20,
                            "mt5_tp_points": 30,
                            "mt5_sl_points": 39
                        }
                    },
                    # ── Double Dip Payout 2+ (mirrors Funded Payout 2+) ─
                    # New blueprints synced from the connector reference.
                    # Dormant until _PHASE_TRADE_ORDER routes
                    # "Double Dip Payout 2+" to these keys; MT5 hedge
                    # values left at 0 — fill before enabling.
                    "funded_trade_doubledip_1_p2": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 47,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0
                        }
                    },
                    "funded_trade_doubledip_2_p2": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 47,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0
                        }
                    },
                    "funded_trade_doubledip_3_p2": {
                        "50k": {
                            "topstepx_symbol": "NQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 47,
                            "topstepx_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0
                        }
                    },
                    # ── Farming (MNQ vs USTEC) ──
                    # Used only to complete the 5-min trading-day requirement
                    # once the profit target has been reached.  Same setup as
                    # the standard TopStep blueprint.
                    "farming": {
                        "50k": {
                            "topstepx_symbol": "MNQU26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 154,
                            "topstepx_sl_ticks": 600,
                            "mt5_volume": 3.6,
                            "mt5_tp_points": 146,
                            "mt5_sl_points": 43
                        }
                    }
                }
            },
            "Lucid": {
                "name": "Lucid",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Funded Phase", "Double Dip Phase", "Farming Phase"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 151,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 5,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 42
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 151,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 8,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 42
                        }
                    },
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 340,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 15,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 89
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 140,
                            "tradovate_sl_ticks": 170,
                            "mt5_volume": 18,
                            "mt5_tp_points": 38,
                            "mt5_sl_points": 39
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 140,
                            "tradovate_sl_ticks": 160,
                            "mt5_volume": 18.0,
                            "mt5_tp_points": 36,
                            "mt5_sl_points": 39
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 140,
                            "tradovate_sl_ticks": 155,
                            "mt5_volume": 0,
                            "mt5_tp_points": 34,
                            "mt5_sl_points": 39
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 154,
                            "tradovate_sl_ticks": 600,
                            "mt5_volume": 3.6,
                            "mt5_tp_points": 146,
                            "mt5_sl_points": 43
                        }
                    }
                }
            },
            "TradeDay": {
                "name": "TradeDay",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Funded Phase", "Double Dip Phase", "Farming Phase"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 62,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume":3.6,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 20
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 62,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 5.2,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 20
                        }
                    },
                    "challenge_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 62,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 7.4,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 20
                        }
                    },
                    "challenge_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 62,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 10.2,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 20
                        }
                    },
                    "challenge_trade5": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 62,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 14.2,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 20
                        }
                    },
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 500,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 20,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 129
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 500,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 28,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 129
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 500,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 20,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 129
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 204,
                            "tradovate_sl_ticks": 600,
                            "mt5_volume": 3.2,
                            "mt5_tp_points": 146,
                            "mt5_sl_points": 55
                        }
                    }
                }
            },
            "AlphaFutures": {
                "name": "AlphaFutures",
                # Platform: Alpha Trader (futures.alphatrader.com) — migrated from Tradovate 2026.
                # Connector: connectors/alphatrader_connector.py
                # tradovate_symbol field is still used for symbol lookup; connector maps it to
                # Alpha Trader contract_id (e.g. "NQU6" → "NQ", "MNQU6" → "MNQ").
                "account_sizes": ["$50,000", "$100,000", "$150,000"],
                "trading_phases": ["Challenge Phase", "Funded Phase", "Farming Phase"],
                "compliance_rules": {
                    "consistency_pct": 0.40,
                },
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 135,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume":3,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        },
                        "100k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 4,
                            "tradovate_tp_ticks": 135,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 6,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        },
                        "150k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 6,
                            "tradovate_tp_ticks": 135,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 9,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 135,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 7.4,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        },
                        "100k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 4,
                            "tradovate_tp_ticks": 135,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 14.8,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        },
                        "150k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 6,
                            "tradovate_tp_ticks": 135,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 22.2,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        },
                    },
                    "challenge_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 135,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 11.1,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        },
                        "100k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 4,
                            "tradovate_tp_ticks": 135,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 22.2,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        },
                        "150k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 6,
                            "tradovate_tp_ticks": 135,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 33.3,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        }
                    },
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 600,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 22,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 154
                        },
                        "100k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 4,
                            "tradovate_tp_ticks": 600,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 44,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 154
                        },
                        "150k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 6,
                            "tradovate_tp_ticks": 600,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 66,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 154
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 40,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 29
                        },
                        "100k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 4,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 80,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 29
                        },
                        "150k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 6,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 120,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 29
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 25,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 54
                        },
                        "100k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 4,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 50,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 54
                        },
                        "150k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 6,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 75,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 54
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 15,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 54
                        },
                        "100k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 4,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 30,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 54
                        },
                        "150k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 6,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 45,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 54
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 204,
                            "tradovate_sl_ticks": 600,
                            "mt5_volume": 3.6,
                            "mt5_tp_points": 146,
                            "mt5_sl_points": 55
                        }
                    }
                }
            },
            "Tradeify": {
                "name": "Tradeify",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Payout 1", "Payout 2", "Payout 3", "Payout 4", "Farming (Consistency)"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 102,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 3,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 30
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 102,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 5.2,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 30
                        }
                    },"challenge_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 102,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 8.8,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 30
                        }
                    },
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 540,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 15,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 139
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 240,
                            "tradovate_sl_ticks": 260,
                            "mt5_volume": 18,
                            "mt5_tp_points": 61,
                            "mt5_sl_points": 64
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 240,
                            "tradovate_sl_ticks": 245,
                            "mt5_volume": 3,
                            "mt5_tp_points": 57,
                            "mt5_sl_points": 64
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 240,
                            "tradovate_sl_ticks": 238,
                            "mt5_volume": 0,
                            "mt5_tp_points": 55,
                            "mt5_sl_points": 64
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 154,
                            "tradovate_sl_ticks": 600,
                            "mt5_volume": 3.6,
                            "mt5_tp_points": 146,
                            "mt5_sl_points": 43
                        }
                    }
                }
            },
            "Apex": {
                "name": "Apex",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Payout 1", "Payout 2", "Payout 3", "Payout 4", "Farming (Consistency)"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 310,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 82
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 410,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 107
                        }
                    },
                    "payout1_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 250,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 54
                        }
                    },
                    "payout1_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 250,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 54
                        }
                    },
                    "payout2_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 54
                        }
                    },
                    "payout2_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 54
                        }
                    },
                    "payout3_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 150,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 54
                        }
                    },
                    "payout3_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 150,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 54
                        }
                    },
                    "payout4_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 150,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 54
                        }
                    },
                    "payout4_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 150,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 54
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 173,
                            "tradovate_sl_ticks": 500,
                            "mt5_volume": 0,
                            "mt5_tp_points": 121,
                            "mt5_sl_points": 48
                        }
                    }
                }
            },
            "Top One Futures": {
                "name": "Top One Futures Elite Daily",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Payout 1", "Payout 2", "Double Dip Payout 1", "Double Dip Payout 2", "Farming Phase"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 202,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0
                        }
                    },
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 600,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 3500
                        }
                    },
                    "funded_trade1a": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 3500
                        }
                    },
                    "funded_trade1b": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 3500
                        }
                    },
                    "funded_trade1c": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 500,
                            "tradovate_sl_ticks": 180,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 3500
                        }
                    },
                    "funded_trade1d": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 600,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 3500
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 1000
                        }
                    },
                    "funded_trade2a": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 400,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 1000
                        }
                    },
                    "funded_trade2b": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 600,
                            "tradovate_sl_ticks": 80,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 1000
                        }
                    },
                    "funded_trade_doubledip_1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 600,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 3500
                        }
                    },
                    "funded_trade_doubledip_1a": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 3500
                        }
                    },
                    "funded_trade_doubledip_1b": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 3500
                        }
                    },
                    "funded_trade_doubledip_1c": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 500,
                            "tradovate_sl_ticks": 180,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 3500
                        }
                    },
                    "funded_trade_doubledip_1d": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 600,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 3500
                        }
                    },
                    "funded_trade_doubledip_2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 1000
                        }
                    },
                    "funded_trade_doubledip_2a": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 400,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 1000
                        }
                    },
                    "funded_trade_doubledip_2b": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 600,
                            "tradovate_sl_ticks": 80,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 1000
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 204,
                            "tradovate_sl_ticks": 600,
                            "mt5_volume": 0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 204
                        }
                    }
                }
            },
            "The5ers": {
                "name": "The5ers",
                # Platform: BlackArrow only. No MT5/Tradovate connector exists.
                # tradovate_symbol/qty used as canonical NQ placeholders.
                # mt5_volume is 0 — no hedge leg on this firm.
                "account_sizes": ["$50,000"],
                "trading_phases": [
                    "Challenge Phase",
                    "Payout 1",
                    "Payout 2",
                    "Payout 3",
                    "Payout 4",
                    "Farming Phase",
                ],
                "compliance_rules": {
                    # EOD trailing drawdown — anchors to all-time-high midnight balance.
                    # 4% of that high-water mark = hard floor. Never resets downward.
                    "drawdown_type":        "eod_trailing",
                    "drawdown_pct":         0.04,
                    # 40% consistency: no single trade > 40% of TOTAL profits earned (soft breach).
                    # Soft = account stays live; keep trading until ratio drops to ≤40%.
                    # Formula: if breach → new target = biggest_trade / 0.40.
                    # Example: $1,600 trade → new target = $4,000.
                    "consistency_pct":      0.40,
                    "consistency_mode":     "soft",
                    # Day Trade track: all positions MUST close ≥10 min before market close.
                    # Cutoff = 4:50 PM CET (platform enforces 5:00 PM CET as EOD).
                    "overnight_allowed":    False,
                    "eod_cutoff_cet":       "16:50",  # "4:50 PM CET" per official FAQ
                    "weekend_allowed":      False,     # both Day Trade and Swing
                    # Inactivity: ≥1 trade per 14 calendar days or account is terminated.
                    "inactivity_days":      14,
                    # Copy trading: own accounts only; 25K/50K accounts; max combined $75K.
                    # Cannot copy other traders or let others copy you.
                    "copy_trading_allowed": True,
                    "copy_trading_own_only": True,
                    "copy_trading_max_combined": 75000,
                    # News: trading during economic releases IS allowed (no restriction).
                    "news_trading_allowed": True,
                    # Evaluation profits do NOT carry over — funded account starts at $50K clean.
                    "eval_profits_carry_over": False,
                    # Max contract size per $50K account: 2 NQ minis OR 20 MNQ micros.
                    "max_contracts_mini":   2,
                    "max_contracts_micro":  20,
                    "max_accounts":         5,
                    # Scaling (funded only): every 10% profit milestone →
                    #   +5% balance, +1 mini / +10 micros added to max. Cap: $500K.
                    "scaling_profit_pct":   0.10,
                    "scaling_balance_inc_pct": 0.05,
                    "scaling_mini_inc":     1,
                    "scaling_micro_inc":    10,
                    "scaling_max_balance":  500000,
                },
                "strategy_configs": {
                    # ── Challenge Phase ────────────────────────────────────────────
                    # Target: $3,000 (+6% of $50K). Official max: 2 NQ minis.
                    # 3 trades × 2 minis × 100 ticks × $5 = $1,000/trade → $3,000.
                    # Each trade = 33.3% of $3K total — within the 40% consistency rule.
                    # Can pass in 1 day (allowed per FAQ) if all 3 trades fit in a session.
                    #
                    # SL MODE: "full_cushion" — SL is set dynamically at trade time to
                    # consume the ENTIRE remaining drawdown cushion:
                    #   SL_ticks = (current_balance - drawdown_floor) / (qty × tick_value)
                    #   drawdown_floor = MLL shown on platform  (or SOD_balance × 0.96)
                    #   tick_value (NQ) = $5
                    # Example progression:
                    #   Start of day  → cushion=$2,000 → SL=200 ticks
                    #   After +$1,000 → cushion=$3,000 → SL=300 ticks
                    #   After +$2,000 → cushion=$4,000 → SL=400 ticks
                    # tradovate_sl_ticks=200 is the fallback if balance can't be read.
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty":    2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 200,
                            "sl_mode":          "full_cushion",
                            # NEVER raise TP via calculate_adjusted_tp.
                            # 100t × 2 NQ × $5 = $1,000 = 33.3% of $3k target -> within 40% rule.
                            # Raising TP (e.g. to 150t = $1,500) would breach the 40% consistency limit.
                            "disable_tp_adjustment": True,
                            "mt5_volume":  0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 1000,
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty":    2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 200,
                            "sl_mode":          "full_cushion",
                            "disable_tp_adjustment": True,
                            "mt5_volume":  0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 1000,
                        }
                    },
                    "challenge_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty":    2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 200,
                            "sl_mode":          "full_cushion",
                            "disable_tp_adjustment": True,
                            "mt5_volume":  0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 1000,
                        }
                    },
                    # ── Payout 1 ───────────────────────────────────────────────────
                    # Funded target = 4% of $50K = $2,000.
                    # 4 trades for consistency: biggest single trade must be ≤40% of total.
                    # 4 × 2 minis × 94 ticks × $5 = $940/trade → $3,760 total.
                    # Biggest trade = $940 / $3,760 = 25% — compliant at trade 4.
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty":    2,
                            "tradovate_tp_ticks": 94,
                            "tradovate_sl_ticks": 100,
                            "disable_tp_adjustment": True,
                            "mt5_volume":  0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 940,
                        }
                    },
                    # ── Payout 2 ───────────────────────────────────────────────────
                    # 2 minis × 120 ticks × $5 = $1,200/trade.
                    # Keep each trade ≤ 40% of running cumulative profits.
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty":    2,
                            "tradovate_tp_ticks": 120,
                            "tradovate_sl_ticks": 100,
                            "disable_tp_adjustment": True,
                            "mt5_volume":  0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 1200,
                        }
                    },
                    # ── Payout 3 ───────────────────────────────────────────────────
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty":    2,
                            "tradovate_tp_ticks": 120,
                            "tradovate_sl_ticks": 100,
                            "disable_tp_adjustment": True,
                            "mt5_volume":  0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 1200,
                        }
                    },
                    # ── Payout 4+ ──────────────────────────────────────────────────
                    "funded_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty":    2,
                            "tradovate_tp_ticks": 120,
                            "tradovate_sl_ticks": 100,
                            "disable_tp_adjustment": True,
                            "mt5_volume":  0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 1200,
                        }
                    },
                    # ── Farming (inactivity guard) ─────────────────────────────────
                    # MNQ micros to keep the 14-day inactivity clock alive cheaply.
                    # Max 20 MNQ — using only 2 keeps risk minimal.
                    # 2 MNQ × 154 ticks × $0.50 = $154.
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQU6",
                            "tradovate_qty":    2,
                    "compliance_rules": {
                        "consistency_pct": 0.40,
                    },
                            "tradovate_tp_ticks": 154,
                            "tradovate_sl_ticks": 600,
                            "mt5_volume":  0,
                            "mt5_tp_points": 0,
                            "mt5_sl_points": 0,
                            "profit_target": 154,
                        }
                    },
                },
            },
            "Funded Futures Family": {
                "name": "Funded Futures Family",
                "account_sizes": ["$50,000"],
                "trading_phases": [
                    "Challenge Phase",
                    "Payout 1",
                    "Payout 2",
                    "Payout 3",
                    "Farming (Consistency)",
                ],
                "strategy_configs": {
                    # Challenge: 2 trades at 50% consistency · $1,510 each (2 NQ × 151 ticks × $5)
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 151,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 10.4,
                            "mt5_tp_points": 23,
                            "mt5_sl_points": 30,
                            "profit_target": 1510,
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 151,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 10.4,
                            "mt5_tp_points": 23,
                            "mt5_sl_points": 30,
                            "profit_target": 1510,
                        }
                    },
                    # Funded: each trade ~$1,680 (2 NQ × 168 ticks × $5; target $1,675)
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 168,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 16,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 46,
                            "profit_target": 1675,
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 168,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 18,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 46,
                            "profit_target": 1675,
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 168,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 18,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 46,
                            "profit_target": 1675,
                        }
                    },
                    # Farming: $204 (2 MNQ × 204 ticks × $0.50)
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQU6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 204,
                            "tradovate_sl_ticks": 600,
                            "mt5_volume": 3.2,
                            "mt5_tp_points": 146,
                            "mt5_sl_points": 55,
                            "profit_target": 204,
                        }
                    },
                },
            },
            # Goat Funded Futures — $50k EOD, 4% max drawdown ($2,000), 3 minis max, 50% consistency
            # Phase 1 (Challenge) → Live Account; no daily drawdown
            # Site: app.goatfundedfutures.com
            "GoatFunded": {
                "name": "Goat Funded Futures",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Funded Phase", "Farming Phase"],
                "compliance_rules": {
                    "consistency_pct": 0.50,
                    "drawdown_type": "EOD",
                    "no_daily_drawdown": True,
                    "max_drawdown_dollars": 2000,
                    "min_trading_days_challenge": 2,
                    "min_trading_days_funded": 5,
                },
                "strategy_configs": {
                    # Challenge: 3 NQ minis, 101t TP × $5 × 3 = $1,515/trade (49.97% of $3,030 → under 50% consistency)
                    # SL=133t × 3 minis × $5 = $1,995 (within $2k max drawdown)
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 101,
                            "tradovate_sl_ticks": 133,
                            "mt5_volume": 7,
                            "mt5_tp_points": 23,
                            "mt5_sl_points": 18,
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 101,
                            "tradovate_sl_ticks": 133,
                            "mt5_volume": 12,
                            "mt5_tp_points": 23,
                            "mt5_sl_points": 18,
                        }
                    },
                    # Funded (Live Account): SL fixed to protect $2k max drawdown
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 500,
                            "tradovate_sl_ticks": 133,
                            "mt5_volume": 18,
                            "mt5_tp_points": 15,
                            "mt5_sl_points": 129,
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 133,
                            "tradovate_sl_ticks": 133,
                            "mt5_volume": 22,
                            "mt5_tp_points": 15,
                            "mt5_sl_points": 40,
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 133,
                            "tradovate_sl_ticks": 133,
                            "mt5_volume": 26,
                            "mt5_tp_points": 15,
                            "mt5_sl_points": 40,
                        }
                    },
                    # Farming: micro contracts (30 micros max)
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQU6",
                            "tradovate_qty": 3,
                            "tradovate_tp_ticks": 204,
                            "tradovate_sl_ticks": 600,
                            "mt5_volume": 3.2,
                            "mt5_tp_points": 146,
                            "mt5_sl_points": 55,
                        }
                    },
                },
            },
        }

        # Funded Next has two selectable blueprints in the UI. Flex starts as
        # an independent clone so values can diverge safely later.
        self.firm_blueprints["Funded Next Flex"] = copy.deepcopy(self.firm_blueprints["Funded Next"])
        self.firm_blueprints["Funded Next Flex"]["name"] = "Funded Next Flex"

        # Funded Next Flex tuning (50k account):
        # - Challenge tuned to ~2.5k cumulative target with 40% consistency-friendly sizing.
        # - Funded tuned to $1.5k payout-style TP/risk per trade.
        fn_flex_cfg = self.firm_blueprints["Funded Next Flex"]["strategy_configs"]

        fn_flex_cfg["challenge_trade1"]["50k"].update({
            "tradovate_tp_ticks": 84,
            "tradovate_sl_ticks": 150,
            "mt5_volume": 3.2,
            "mt5_tp_points": 35,
            "mt5_sl_points": 24,
        })
        fn_flex_cfg["challenge_trade2"]["50k"].update({
            "tradovate_tp_ticks": 84,
            "tradovate_sl_ticks": 150,
            "mt5_volume": 6.4,
            "mt5_tp_points": 35,
            "mt5_sl_points": 24,
        })
        fn_flex_cfg["challenge_trade3"]["50k"].update({
            "tradovate_tp_ticks": 84,
            "tradovate_sl_ticks": 150,
            "mt5_volume": 9.6,
            "mt5_tp_points": 35,
            "mt5_sl_points": 24,
        })

        fn_flex_cfg["funded_trade1"]["50k"].update({
            "tradovate_tp_ticks": 310,
            "tradovate_sl_ticks": 150,
            "mt5_volume": 12,
            "mt5_tp_points": 35,
            "mt5_sl_points": 80,
        })
        fn_flex_cfg["funded_trade2"]["50k"].update({
            "tradovate_tp_ticks": 150,
            "tradovate_sl_ticks": 150,
            "mt5_volume": 14,
            "mt5_tp_points": 35,
            "mt5_sl_points": 35,
        })
        fn_flex_cfg["funded_trade3"]["50k"].update({
            "tradovate_tp_ticks": 150,
            "tradovate_sl_ticks": 150,
            "mt5_volume": 16,
            "mt5_tp_points": 35,
            "mt5_sl_points": 35,
        })
        fn_flex_cfg["funded_trade4"]["50k"].update({
            "tradovate_tp_ticks": 150,
            "tradovate_sl_ticks": 150,
            "mt5_volume": 0,
            "mt5_tp_points": 35,
            "mt5_sl_points": 35,
        })

        # Flex uses the same farming setup as standard Funded Next.
        fn_flex_cfg["farming"]["50k"] = copy.deepcopy(
            self.firm_blueprints["Funded Next"]["strategy_configs"]["farming"]["50k"]
        )

    def detect_prop_firm(self, username: str) -> Optional[str]:
        """Detect prop firm based on username prefix. Returns None if unrecognized."""
        if not username or (isinstance(username, str) and len(username) < 4):
            self.logger.warning(f"Username too short: '{username}', cannot detect prop firm")
            return None
        
        prefix = username[:4].upper()
        
        if prefix in self.firm_blueprints:
            self.logger.info(f"Detected prop firm '{prefix}' from username: '{username}'")
            return prefix
        
        if any(prefix.startswith(var) for var in ["APEX"]):
            return "Apex"
        elif any(prefix.startswith(var) for var in ["FTPR"]):
            return "FundingTicks"
        elif any(prefix.startswith(var) for var in ["ELTD", "TDFU"]):
            return "Trade Day"
        elif any(prefix.startswith(var) for var in ["FNFT", "FTFN"]):
            return "Funded Next"
        elif any(prefix.startswith(var) for var in ["MFFU"]):
            return "MFFU"
        elif any(prefix.startswith(var) for var in ["V2-"]):
            return "TopStep"
        elif any(prefix.startswith(var) for var in ["TDFY", "FTDF"]):
            return "Tradeify"
        elif any(prefix.startswith(var) for var in ["LFE0", "LFF0"]):
            return "Lucid"
        elif any(prefix.startswith(var) for var in ["AFAD"]):
            return "AlphaFutures"
        elif any(prefix.startswith(var) for var in ["FFFF", "FFFU", "FDFM", "FFFA"]):
            return "Funded Futures Family"
        elif any(prefix.startswith(var) for var in ["GFFU", "GFFF"]):
            return "GoatFunded"
        
        self.logger.warning(f"Unknown prefix '{prefix}' from account '{username}' — prop firm not recognized")
        return None
    
    def get_firm_info(self, firm_code: str) -> Dict:
        """Get complete prop firm information.

        This is the single convergence point for blueprint access
        (get_strategy_config / get_account_sizes / etc. all route here), so
        normalization is robust: an unrecognised-but-resolvable label must
        NEVER silently fall back to the MFFU_Flex blueprint. In particular a
        TopStep-family label always resolves to the correct TopStep vs
        TopStep RTP blueprint regardless of casing/spacing.
        """
        normalized_code = firm_code

        # Legacy / explicit aliases.
        if firm_code in ("Alpha Futures", "AlphaFutures GC"):
            normalized_code = "AlphaFutures"
        elif firm_code == "FundedNext":
            normalized_code = "Funded Next"
        elif firm_code in ("FundedNextFlex", "Funded Next Flex"):
            normalized_code = "Funded Next Flex"
        elif firm_code in ("FFF", "Funded Futures Family", "FundedFuturesFamily"):
            normalized_code = "Funded Futures Family"
        elif firm_code in ("5ers", "The5ers", "the5ers", "The 5ers"):
            normalized_code = "The5ers"
        elif firm_code in ("Goat Funded Futures", "Goat Funded", "GFF"):
            normalized_code = "GoatFunded"
        elif firm_code == "TopOneFutures":
            normalized_code = "Top One Futures"
        elif firm_code in ("MFFU", "My Funded Futures"):
            # Legacy alias — MFFU is no longer a separate blueprint
            normalized_code = "MFFU_Flex"
        elif firm_code in ("Trade Day", "Trade day"):
            normalized_code = "TradeDay"

        # Exact blueprint key — fast path.
        if normalized_code in self.firm_blueprints:
            return self.firm_blueprints[normalized_code]

        raw = str(firm_code or "").strip()
        if raw:
            # Case-insensitive exact key match.
            for bk in self.firm_blueprints:
                if bk.lower() == raw.lower():
                    return self.firm_blueprints[bk]

            # TopStep family: distinguish RTP by substring so a label like
            # 'Topstep' / 'topstep rtp' / 'TopstepRTP' can never collapse to
            # the generic MFFU_Flex fallback. 'topsteprtp' (compacted)
            # contains both tokens, so RTP is detected before plain TopStep.
            compact = raw.lower().replace("_", "").replace("-", "").replace(" ", "")
            if "topstep" in compact:
                key = "TopStep RTP" if "rtp" in compact else "TopStep"
                if key in self.firm_blueprints:
                    return self.firm_blueprints[key]
            elif "rtp" in compact and "TopStep RTP" in self.firm_blueprints:
                return self.firm_blueprints["TopStep RTP"]
            if "fundedfuturesfamily" in compact or "fundedfutures" in compact:
                return self.firm_blueprints["Funded Futures Family"]
            if "goatfunded" in compact or "goatfund" in compact:
                return self.firm_blueprints["GoatFunded"]

        self.logger.warning(
            f"get_firm_info: unrecognised firm_code '{firm_code}' — "
            f"falling back to MFFU_Flex blueprint"
        )
        return self.firm_blueprints["MFFU_Flex"]
    
    def get_account_sizes(self, firm_code: str) -> list:
        """Get account sizes for specific prop firm."""
        firm_info = self.get_firm_info(firm_code)
        return firm_info.get("account_sizes", ["$50,000"])
    
    def get_trading_phases(self, firm_code: str) -> list:
        """Get trading phases for specific prop firm."""
        firm_info = self.get_firm_info(firm_code)
        return firm_info.get("trading_phases", ["Challenge Phase", "Funded Phase", "Farming Phase"])
    
    def convert_account_size_to_key(self, account_size: str, firm_code: str = None) -> str:
        """Convert account size string to size key (e.g., '$50,000' -> '50k')"""
        if not account_size:
            return "50k"
        s = account_size.lower().replace(",", "").replace("$", "").strip()
        if "150" in s or s == "150k":
            return "150k"
        if "100" in s or s == "100k":
            return "100k"
        return "50k"
    
    def get_strategy_config(self, firm_code: str, phase_key: str, size_key: str = "50k") -> Dict:
        """Get strategy configuration for specific prop firm and phase."""
        # Normalize size_key: "$50,000" -> "50k", "$100,000" -> "100k", etc.
        size_key = self.convert_account_size_to_key(size_key, firm_code)
        self.logger.info(f"[DEBUG get_strategy_config] firm_code='{firm_code}', phase_key='{phase_key}', size_key='{size_key}'")
        
        firm_info = self.get_firm_info(firm_code)
        strategy_configs = firm_info.get("strategy_configs", {})
        
        phase_config = strategy_configs.get(phase_key, {})
        if not phase_config:
            self.logger.warning(f"Phase '{phase_key}' not found for '{firm_code}', using MFFU_Flex default")
            mffu_configs = self.firm_blueprints["MFFU_Flex"]["strategy_configs"]
            phase_config = mffu_configs.get(phase_key, {})

        self.logger.info(f"[DEBUG get_strategy_config] phase_config keys: {list(phase_config.keys()) if phase_config else 'None'}")

        config = phase_config.get(size_key)
        if not config:
            # For farming phase, try to fallback to 50k first before using MFFU_Flex fallback
            if phase_key == "farming" and size_key != "50k" and "50k" in phase_config:
                self.logger.info(f"Farming config not found for '{size_key}', using 50k farming config instead")
                config = phase_config["50k"]
            else:
                self.logger.warning(f"Config not found for '{firm_code}/{phase_key}/{size_key}', using MFFU_Flex fallback")
                config = self.firm_blueprints["MFFU_Flex"]["strategy_configs"]["challenge_trade1"]["50k"]
        else:
            self.logger.info(f"[DEBUG get_strategy_config] Found config: qty={config.get('tradovate_qty', 'N/A')}, volume={config.get('mt5_volume', 'N/A')}")
        
        if config:
            config = self._ensure_mt5_hedge_config(
                config.copy(), phase_key=phase_key,
                firm_code=firm_info.get("name", firm_code))
            if 'mt5_volume' in config:
                config['mt5_volume'] = round(float(config['mt5_volume'] or 0), 2)
        
        return config
    
    def validate_firm_setup(self, username: str) -> Tuple[Optional[str], Dict]:
        """Validate and get complete prop firm setup for a username."""
        firm_code = self.detect_prop_firm(username)
        if firm_code is None:
            self.logger.warning(f"Could not detect prop firm for '{username}'")
            return None, {}
        firm_info = self.get_firm_info(firm_code)
        
        self.logger.info(f"Prop firm setup for '{username}': {firm_info['name']} ({firm_code})")
        return firm_code, firm_info
    
    def set_prop_firm(self, firm_name, broker=None, blueprint_firm=None):
        """Set the current prop firm
        
        Args:
            firm_name: The prop firm name (MFFU, TopStep, Other, etc.)
            broker: The broker platform for 'Other' mode (TopStep or Tradovate)
            blueprint_firm: The specific blueprint to use when in Other mode (e.g. MFFU_Flex)
        """
        self.logger.info(f"Setting prop firm: '{firm_name}', broker: '{broker}', blueprint: '{blueprint_firm}'")
        
        firm_mapping = {
            "MFFU": "MFFU_Flex",  # Legacy alias
            "My Funded Futures": "MFFU_Flex",  # Legacy alias
            "MFFU_Flex": "MFFU_Flex",
            "Funded Next": "Funded Next",
            "FundedNext": "Funded Next",
            "Funded Next Flex": "Funded Next Flex",
            "FundedNextFlex": "Funded Next Flex",
            "FundingTicks": "FundingTicks",
            "TopStep": "TopStep",
            "TopStep RTP": "TopStep RTP",
            "TopStep_RTP": "TopStep RTP",
            "Tradeify": "Tradeify",
            "Apex": "Apex",
            "Alpha Futures": "AlphaFutures",
            "AlphaFutures": "AlphaFutures",
            "AlphaFutures GC": "AlphaFutures",
            "Top One Futures": "Top One Futures",
            "Funded Futures Family": "Funded Futures Family",
            "FFF": "Funded Futures Family",
            "The5ers": "The5ers",
            "5ers": "The5ers",
            "Goat Funded Futures": "GoatFunded",
            "GoatFunded": "GoatFunded",
            "GFF": "GoatFunded",
            "Other": "MFFU_Flex"  # Default fallback
        }

        # For "Other" prop firm, we prefer the specific blueprint if provided
        if firm_name == "Other":
            if blueprint_firm and blueprint_firm in self.firm_blueprints:
                self.current_firm_code = blueprint_firm
                self.logger.info(f"Other mode: Using specific blueprint {self.current_firm_code}")
            elif broker and broker == "TopStep":
                self.current_firm_code = "TopStep"
            else:  # Tradovate or any other
                self.current_firm_code = "MFFU_Flex"
            
            if not blueprint_firm:
                self.logger.info(f"Other mode: Mapped to {self.current_firm_code} based on broker '{broker}'")
        else:
            self.current_firm_code = firm_mapping.get(firm_name, firm_name)
        
        self.logger.info(f"Set prop firm to: {self.current_firm_code}")
    
    def get_prop_firm_strategy_config(self, trading_phase, account_size="$50,000", balance_performance=0.0):
        """Get strategy config for current prop firm (manual trading only)"""
        self.logger.info(f"Looking up: '{self.current_firm_code}', phase='{trading_phase}', size='{account_size}'")
        
        # Route through get_firm_info so the same robust normalization
        # (case-insensitive + TopStep-vs-RTP) applies here too — never a
        # silent direct-dict miss to MFFU_Flex.
        firm_info = self.get_firm_info(self.current_firm_code)
        
        # Convert account size to size key (e.g., "$50,000" -> "50k", "$100,000" -> "100k", "$150,000" -> "150k")
        size_key = "50k"  # Default
        if "$100,000" in account_size or "100k" in account_size.lower():
            size_key = "100k"
        elif "$150,000" in account_size or "150k" in account_size.lower():
            size_key = "150k"
        elif "$50,000" in account_size or "50k" in account_size.lower():
            size_key = "50k"
        
        self.logger.info(f"[DEBUG] Converted account_size '{account_size}' to size_key '{size_key}'")
        
        # Default phase key
        phase_key = "challenge_trade1"
        
        if trading_phase == "Challenge Phase":
            if self.current_firm_code == "Top One Futures":
                phase_key = "challenge_trade1"
            elif self.current_firm_code == "AlphaFutures":
                if balance_performance < 3.2:
                    phase_key = "challenge_trade1"
                elif balance_performance < 6.4:
                    phase_key = "challenge_trade2"
                else:
                    phase_key = "challenge_trade3"
            else:
                phase_key = "challenge_trade2" if balance_performance >= 2.5 else "challenge_trade1"
        
        self.logger.info(f"[DEBUG] Using phase_key '{phase_key}' for phase '{trading_phase}'")
        
        if trading_phase == "Funded Phase":
            if self.current_firm_code in ("MFFU", "MFFU_Flex"):
                # MFFU / MFFU_Flex Funded Phase Logic (Condensed Payouts)
                if balance_performance < 2.0:
                    phase_key = "funded_trade1"
                elif balance_performance < 4.0:
                    phase_key = "funded_trade2"
                elif balance_performance < 6.0:
                    phase_key = "funded_trade3"
                else:
                    phase_key = "funded_trade4"
            elif self.current_firm_code == "Trade Day":
                phase_key = "funded"
            elif self.current_firm_code == "TopStep":
                # TopStep Funded Phase Logic (Condensed Payouts)
                if balance_performance < 2.0:
                    phase_key = "funded_trade1"
                elif balance_performance < 4.0:
                    phase_key = "funded_trade2"
                elif balance_performance < 6.0:
                    phase_key = "funded_trade3"
                else:
                    phase_key = "funded_trade4"
            elif self.current_firm_code == "TopStep RTP":
                # TopStep RTP Funded Phase Logic — same balance bands as
                # standard TopStep but pointing at the RTP trade flavors
                # (funded_trade1 = Payout-1 TP=114, funded_trade2-4 =
                # Payout-2+ TP=47).
                if balance_performance < 2.0:
                    phase_key = "funded_trade1"
                elif balance_performance < 4.0:
                    phase_key = "funded_trade2"
                elif balance_performance < 6.0:
                    phase_key = "funded_trade3"
                else:
                    phase_key = "funded_trade4"
            elif self.current_firm_code == "Top One Futures":
                # Top One Futures uses Payout 1 / Payout 2 selection instead of
                # a single "Funded Phase". This branch only runs as a safety
                # fallback if "Funded Phase" is somehow still selected; default
                # to funded_trade1 so behavior matches Payout 1.
                phase_key = "funded_trade1"
            elif self.current_firm_code == "FundingTicks":
                phase_key = "funded_trade1" # Default to trade 1
            elif self.current_firm_code == "Tradeify":
                phase_key = "funded_trade1"
            else:
                # Default for others
                phase_key = "funded_trade1"

        if trading_phase == "Double Dip Phase":
            if self.current_firm_code in ("TopStep", "TopStep RTP", "MFFU", "MFFU_Flex"):
                # Double Dip Phase Logic (shared by TopStep / MFFU / MFFU_Flex)
                if balance_performance < 2.0:
                    phase_key = "funded_trade_doubledip_1"
                elif balance_performance < 4.0:
                    phase_key = "funded_trade_doubledip_2"
                elif balance_performance < 6.0:
                    phase_key = "funded_trade_doubledip_3"
                else:
                    phase_key = "funded_trade_doubledip_4"
            elif self.current_firm_code == "Top One Futures":
                if balance_performance < 2.0:
                    phase_key = "funded_trade_doubledip_1"
                else:
                    phase_key = "funded_trade_doubledip_2"
            else:
                phase_key = "funded" # Fallback

        elif trading_phase == "Double Dip Payout 1":
            # Top One Futures Double Dip uses the same structure as Payout 1
            phase_key = "funded_trade_doubledip_1"

        elif trading_phase == "Double Dip Payout 2":
            # Top One Futures Double Dip uses the same structure as Payout 2
            phase_key = "funded_trade_doubledip_2"

        elif trading_phase == "Payout 1":
            phase_key = "funded_trade1"
            
        elif trading_phase == "Payout 2":
            phase_key = "funded_trade2"
            
        elif trading_phase == "Payout 3":
            phase_key = "funded_trade3"
            
        elif trading_phase == "Payout 4":
            phase_key = "funded_trade4"
            
        elif trading_phase == "Farming Phase":
            phase_key = "farming"
            
        elif trading_phase == "Farming (Consistency)":
            phase_key = "farming"
        
        strategy_configs = firm_info.get("strategy_configs", {})
        phase_configs = strategy_configs.get(phase_key, {})
        config = phase_configs.get(size_key, {})
        
        self.logger.info(f"[DEBUG] Retrieved config for {self.current_firm_code}/{phase_key}/{size_key}: {bool(config)}")
        if config:
            self.logger.info(f"[DEBUG] Config qty={config.get('tradovate_qty', 'N/A')}, volume={config.get('mt5_volume', 'N/A')}")
        
        if phase_key == "farming" and self.current_firm_code in ("Funded Next", "Funded Next Flex"):
            # Strict logic: Funded Next farming blueprints MUST use 50k regardless of size
            if "50k" in phase_configs:
                self.logger.info(f"Enforcing {self.current_firm_code} 50k farming blueprint for '{size_key}'")
                config = phase_configs["50k"]

        if not config:
            # For farming phase, try to fallback to 50k first before using MFFU fallback
            if phase_key == "farming" and size_key != "50k" and "50k" in phase_configs:
                self.logger.info(f"Farming config not found for '{size_key}', using 50k farming config instead")
                config = phase_configs["50k"]

            # Try to find a fallback within the same firm if possible
            if trading_phase == "Funded Phase" and not config:
                 # Try alternative funded keys
                 for alt_key in ["funded", "funded_trade1"]:
                     if alt_key in strategy_configs:
                         config = strategy_configs[alt_key].get(size_key, {})
                         if config:
                             phase_key = alt_key
                             break
            
            if not config:
                mffu_configs = self.firm_blueprints["MFFU_Flex"]["strategy_configs"]
                # Map current phase_key to MFFU_Flex equivalent if possible
                mffu_phase_key = phase_key
                if "funded" in phase_key: mffu_phase_key = "funded_trade1"
                elif "farming" in phase_key: mffu_phase_key = "farming"
                else: mffu_phase_key = "challenge_trade1"

                fallback = mffu_configs.get(mffu_phase_key, {}).get(size_key, {})

                if fallback:
                    self.logger.warning(f"No config for {self.current_firm_code}/{phase_key}, using MFFU_Flex {mffu_phase_key}")
                    return self._ensure_mt5_hedge_config(
                        dict(fallback), phase_key=phase_key,
                        firm_code=self.current_firm_code or "")
                else:
                    ultimate_fallback = {
                        "tradovate_symbol": "MNQU6",
                        "tradovate_qty": 2,
                        "tradovate_tp_ticks": 154,
                        "tradovate_sl_ticks": 400,
                        "mt5_volume": 4.0,
                        "mt5_tp_points": 98,
                        "mt5_sl_points": 41
                    }
                    self.logger.error(f"No valid config, using ultimate fallback")
                    return self._ensure_mt5_hedge_config(
                        ultimate_fallback, phase_key=phase_key,
                        firm_code=self.current_firm_code or "")

        if config:
            config = self._ensure_mt5_hedge_config(
                dict(config), phase_key=phase_key,
                firm_code=self.current_firm_code or "")
            if 'mt5_volume' in config:
                config['mt5_volume'] = round(float(config['mt5_volume'] or 0), 2)
        return config
    
    def get_prop_firm_account_sizes(self, firm_code=None):
        """Get account sizes for detected or specified prop firm"""
        if firm_code is None:
            firm_code = self.current_firm_code
        return self.get_account_sizes(firm_code)
    
    def get_prop_firm_trading_phases(self, firm_code=None):
        """Get trading phases for detected or specified prop firm"""
        if firm_code is None:
            firm_code = self.current_firm_code
        return self.get_trading_phases(firm_code)
    
    def format_volume_for_display(self, volume):
        """Format MT5 volume for display (used by GUI)"""
        if volume == 0:
            return "0.0"
        return f"{volume:.1f}"

    def get_tick_value(self, symbol: str) -> float:
        """Get tick value for a given trading symbol.
        
        Returns the dollar value per tick for the given contract symbol.
        This is the single source of truth for tick values across the app.
        """
        symbol_upper = symbol.upper() if symbol else ""
        # Micro Gold contracts
        if "MGC" in symbol_upper:
            return 1.0
        # Standard Gold contracts
        if "GC" in symbol_upper:
            return 10.0
        # Micro NASDAQ contracts (check before standard NQ)
        if "MNQ" in symbol_upper:
            return 0.5
        # Standard NASDAQ contracts
        if "NQ" in symbol_upper:
            return 5.0
        # Default to micro contract value
        return 0.5

    # ── Ordered trade progressions per phase ──────────────────────────
    # Maps (phase_display) → ordered list of blueprint keys within that phase.
    # The balance-based stage detection walks through these in order.
    _PHASE_TRADE_ORDER = {
        "MFFU_Flex": {
            "Challenge":  ["challenge_trade1", "challenge_trade2", "challenge_trade3", "challenge_trade4"],
            "Funded":     ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Farming":    ["farming"],
        },
        "Funded Next": {
            "Challenge": ["challenge_trade1", "challenge_trade2", "challenge_trade3"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Farming":   ["farming"],
        },
        "Funded Next Flex": {
            "Challenge": ["challenge_trade1", "challenge_trade2", "challenge_trade3"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Farming":   ["farming"],
        },
        "FundingTicks": {
            "Challenge": ["challenge_trade1", "challenge_trade2"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Farming":   ["farming"],
        },
        "TopStep": {
            "Challenge":  ["challenge_trade1", "challenge_trade2"],
            "Funded":     ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Double Dip": ["funded_trade_doubledip_1", "funded_trade_doubledip_2",
                           "funded_trade_doubledip_3", "funded_trade_doubledip_4"],
            "Farming":    ["farming"],
        },
        "TopStep RTP": {
            "Challenge":  ["challenge_trade1", "challenge_trade2"],
            "Funded":     ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Farming":    ["farming"],
        },
        "Lucid": {
            "Challenge": ["challenge_trade1", "challenge_trade2"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Farming":   ["farming"],
        },
        "TradeDay": {
            "Challenge": ["challenge_trade1", "challenge_trade2", "challenge_trade3",
                          "challenge_trade4", "challenge_trade5"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3"],
            "Farming":   ["farming"],
        },
        "AlphaFutures": {
            "Challenge": ["challenge_trade1", "challenge_trade2", "challenge_trade3"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Farming":   ["farming"],
        },
        "Tradeify": {
            "Challenge": ["challenge_trade1", "challenge_trade2", "challenge_trade3"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Farming":   ["farming"],
        },
        "Funded Futures Family": {
            "Challenge": ["challenge_trade1", "challenge_trade2"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3"],
            "Farming":   ["farming"],
        },
        "Apex": {
            "Challenge": ["challenge_trade1", "challenge_trade2"],
            # Each payout is its own race to its profit target. "Funded" is an
            # alias for Payout 1 (the entry point right after the challenge) so
            # live phase detection — which only reports "Funded" — defaults to it.
            "Funded":    ["payout1_trade1", "payout1_trade2"],
            "Payout 1":  ["payout1_trade1", "payout1_trade2"],
            "Payout 2":  ["payout2_trade1", "payout2_trade2"],
            "Payout 3":  ["payout3_trade1", "payout3_trade2"],
            "Payout 4":  ["payout4_trade1", "payout4_trade2"],
            "Farming":   ["farming"],
        },
        "The5ers": {
            "Challenge": ["challenge_trade1", "challenge_trade2", "challenge_trade3"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Payout 1":  ["funded_trade1"],
            "Payout 2":  ["funded_trade2"],
            "Payout 3":  ["funded_trade3"],
            "Payout 4":  ["funded_trade4"],
            "Farming":   ["farming"],
        },
        "GoatFunded": {
            "Challenge": ["challenge_trade1", "challenge_trade2"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3"],
            "Farming":   ["farming"],
        },
        "Top One Futures": {
            "Challenge": ["challenge_trade1"],
            "Payout 1":  ["funded_trade1", "funded_trade1a", "funded_trade1b",
                          "funded_trade1c", "funded_trade1d"],
            "Payout 2":  ["funded_trade2", "funded_trade2a", "funded_trade2b"],
            "Funded":    ["funded_trade1", "funded_trade1a", "funded_trade1b",
                          "funded_trade1c", "funded_trade1d",
                          "funded_trade2", "funded_trade2a", "funded_trade2b"],
            "Double Dip Payout 1": [
                "funded_trade_doubledip_1", "funded_trade_doubledip_1a",
                "funded_trade_doubledip_1b", "funded_trade_doubledip_1c",
                "funded_trade_doubledip_1d"],
            "Double Dip Payout 2": [
                "funded_trade_doubledip_2", "funded_trade_doubledip_2a",
                "funded_trade_doubledip_2b"],
            "Double Dip": [
                "funded_trade_doubledip_1", "funded_trade_doubledip_1a",
                "funded_trade_doubledip_1b", "funded_trade_doubledip_1c",
                "funded_trade_doubledip_1d",
                "funded_trade_doubledip_2", "funded_trade_doubledip_2a",
                "funded_trade_doubledip_2b"],
            "Farming": ["farming"],
        },
    }

    def predict_next_trade(self, firm_code: str, current_phase: str,
                           current_profit: float, size_key: str = "50k") -> Dict:
        """Predict current stage and next trade based on balance.

        Walks the ordered trade progression for the firm/phase, computing
        cumulative profit at each stage boundary.  Returns a dict with:
          current_stage  - human label like "Challenge Trade 2"
          next_stage     - human label for next trade, or "Phase Complete"
          next_config    - the blueprint config dict for the next trade (or None)
          next_phase_key - the blueprint key for the next trade
          balance_target - the cumulative $ target at end of current stage
          stages         - list of (label, phase_key, cumul_target) for all stages
        """
        # Normalize phase display to match _PHASE_TRADE_ORDER keys
        phase_map = {"Challenge": "Challenge", "Funded": "Funded",
                     "Farming": "Farming", "Double Dip": "Double Dip",
                     "Payout 1": "Funded", "Payout 2": "Funded",
                     "Payout 3": "Funded", "Payout 4": "Funded"}
        firm_orders = self._PHASE_TRADE_ORDER.get(firm_code, {})
        # Prefer the firm's own phase key (e.g. Apex's per-payout groups); only
        # collapse Payout→Funded for firms that don't define per-payout orders.
        if current_phase in firm_orders:
            phase_key_group = current_phase
        else:
            phase_key_group = phase_map.get(current_phase, current_phase)
        trade_keys = firm_orders.get(phase_key_group, [])

        if not trade_keys:
            return {"current_stage": current_phase, "next_stage": "—",
                    "next_config": None, "next_phase_key": None,
                    "balance_target": 0, "stages": []}

        # Build cumulative profit milestones for each stage
        stages = []
        cumulative = 0.0
        for key in trade_keys:
            cfg = self.get_strategy_config(firm_code, key, size_key)
            if not cfg:
                continue
            sym = cfg.get("tradovate_symbol", "") or cfg.get("topstepx_symbol", "")
            qty = int(cfg.get("tradovate_qty", 0) or cfg.get("topstepx_qty", 0))
            tp = int(cfg.get("tradovate_tp_ticks", 0) or cfg.get("topstepx_tp_ticks", 0))
            tick_val = self.get_tick_value(sym)
            stage_profit = qty * tp * tick_val
            cumulative += stage_profit
            label = key.replace("_", " ").replace("trade", "Trade ").title()
            # Clean up label
            label = label.replace("Challenge Trade ", "Challenge #") \
                         .replace("Funded Trade ", "Funded #") \
                         .replace("Funded ", "Funded #") if "trade" in key.lower() else label
            label = key.replace("_", " ").title()
            stages.append((label, key, round(cumulative, 2), round(stage_profit, 2)))

        # Find which stage we're currently in based on profit
        current_idx = 0
        for i, (_, _, cumul_target, _) in enumerate(stages):
            if current_profit < cumul_target - 0.01:
                current_idx = i
                break
        else:
            # Profit exceeds all stages — we're past the last one
            current_idx = len(stages) - 1

        current_label, current_key, current_target, current_stage_profit = stages[current_idx]

        # Next trade
        if current_idx + 1 < len(stages):
            next_label, next_key, next_target, next_profit = stages[current_idx + 1]
            next_cfg = self.get_strategy_config(firm_code, next_key, size_key)
        else:
            next_label = "Phase Complete"
            next_key = None
            next_cfg = None
            next_target = current_target

        return {
            "current_stage": current_label,
            "current_phase_key": current_key,
            "current_target": current_target,
            "current_stage_profit": current_stage_profit,
            "next_stage": next_label,
            "next_config": next_cfg,
            "next_phase_key": next_key,
            "next_target": next_target,
            "balance_target": current_target,
            "stages": stages,
        }

    def get_stage_start_target(self, firm_code: str, current_phase: str,
                               phase_key: str, size_key: str = "50k") -> float:
        """Return the cumulative $ profit expected BEFORE this stage begins.

        E.g. if the phase order is [trade1, trade2, trade3] and each has a
        $1000 TP target, then:
          trade1 start = $0
          trade2 start = $1000
          trade3 start = $2000

        This is the profit the account should already have when entering
        this stage.  Used to adjust TP so the trade doesn't overshoot or
        undershoot the stage target.
        """
        phase_map = {"Challenge": "Challenge", "Funded": "Funded",
                     "Farming": "Farming", "Double Dip": "Double Dip",
                     "Payout 1": "Funded", "Payout 2": "Funded",
                     "Payout 3": "Funded", "Payout 4": "Funded"}
        firm_orders = self._PHASE_TRADE_ORDER.get(firm_code, {})
        if current_phase in firm_orders:
            phase_group = current_phase
        else:
            phase_group = phase_map.get(current_phase, current_phase)
        trade_keys = firm_orders.get(phase_group, [])

        cumulative = 0.0
        for key in trade_keys:
            if key == phase_key:
                return round(cumulative, 2)
            cfg = self.get_strategy_config(firm_code, key, size_key)
            if not cfg:
                continue
            sym = cfg.get("tradovate_symbol", "") or cfg.get("topstepx_symbol", "")
            qty = int(cfg.get("tradovate_qty", 0) or cfg.get("topstepx_qty", 0))
            tp = int(cfg.get("tradovate_tp_ticks", 0) or cfg.get("topstepx_tp_ticks", 0))
            tick_val = self.get_tick_value(sym)
            cumulative += qty * tp * tick_val
        return round(cumulative, 2)

    def adjust_tp_sl_for_balance(self, config: Dict, current_profit: float) -> Dict:
        """Adjust TP and SL ticks/points based on current account profit.

        If the account already has profit, TP is reduced so the trade doesn't
        overshoot the blueprint target.  If the account has a loss, TP is
        increased to recover back to the target.  SL is adjusted inversely.

        Returns a NEW config dict with adjusted values (original is not mutated).
        """
        config = config.copy()
        symbol = config.get("tradovate_symbol", "") or config.get("topstepx_symbol", "")
        qty = int(config.get("tradovate_qty", 0) or config.get("topstepx_qty", 0))
        orig_tp = int(config.get("tradovate_tp_ticks", 0) or config.get("topstepx_tp_ticks", 0))
        orig_sl = int(config.get("tradovate_sl_ticks", 0) or config.get("topstepx_sl_ticks", 0))
        mt5_tp = int(config.get("mt5_tp_points", 0))
        mt5_sl = int(config.get("mt5_sl_points", 0))

        if qty <= 0 or orig_tp <= 0:
            return config

        tick_val = self.get_tick_value(symbol)
        # Blueprint dollar target for the Tradovate trade
        target_profit = qty * orig_tp * tick_val
        # Blueprint dollar risk for the Tradovate trade
        target_loss = qty * orig_sl * tick_val

        if target_profit == 0:
            return config

        remaining_profit = target_profit - current_profit
        # Floor: at least 10% of original TP to avoid zero/negative TP
        min_tp_dollars = target_profit * 0.10
        remaining_profit = max(remaining_profit, min_tp_dollars)

        # Adjustment ratio
        tp_ratio = remaining_profit / target_profit

        # Adjusted Tradovate TP ticks (round to nearest int, minimum 5 ticks)
        adjusted_tp = max(5, round(orig_tp * tp_ratio))

        # SL adjustment: if in profit, we can afford a wider SL (profit cushion).
        # If in loss, keep blueprint SL — don't tighten, let the prop account
        # reach its actual drawdown limit before the hedge closes.
        if current_profit > 0:
            # Profit acts as a buffer we can afford to lose → widen SL
            adjusted_sl_dollars = target_loss + current_profit
        else:
            # In loss — keep blueprint SL so hedge stays open until drawdown limit
            adjusted_sl_dollars = target_loss
        sl_ratio = adjusted_sl_dollars / target_loss if target_loss > 0 else 1.0
        adjusted_sl = max(10, round(orig_sl * sl_ratio))

        # Apply Tradovate adjustments
        tp_key = "tradovate_tp_ticks" if "tradovate_tp_ticks" in config else "topstepx_tp_ticks"
        sl_key = "tradovate_sl_ticks" if "tradovate_sl_ticks" in config else "topstepx_sl_ticks"
        config[tp_key] = adjusted_tp
        config[sl_key] = adjusted_sl

        # Apply SWAPPED ratios to MT5 TP/SL points — hedging means
        # Tradovate TP ↔ MT5 SL (hedge loses when main wins)
        # Tradovate SL ↔ MT5 TP (hedge wins when main loses)
        if mt5_tp > 0:
            config["mt5_tp_points"] = max(5, round(mt5_tp * sl_ratio))
        if mt5_sl > 0:
            config["mt5_sl_points"] = max(5, round(mt5_sl * tp_ratio))

        self.logger.info(
            f"[TP/SL Adjust] profit=${current_profit:.2f}, "
            f"target=${target_profit:.2f}, remaining=${remaining_profit:.2f}, "
            f"TP: {orig_tp}→{adjusted_tp} ticks, SL: {orig_sl}→{adjusted_sl} ticks, "
            f"MT5 TP(sl_ratio): {mt5_tp}→{config.get('mt5_tp_points')}, "
            f"MT5 SL(tp_ratio): {mt5_sl}→{config.get('mt5_sl_points')}")

        return config

    # ── Farming Hard-Stop Thresholds ──────────────────────────────
    # Minimum balance before the prop firm closes the account.
    # Farming trades use MNQ (micro) contracts; the adjustment logic
    # caps MT5 TP so the prop account can't breach the hard-stop
    # while the MT5 hedge stays open.

    _HARD_STOP_THRESHOLDS: Dict[str, float] = {
        # MFFU / MFFU_Flex: detected dynamically (see adjust_farming_tp_sl)
        "TopStep":          0.0,     # Funded starts at $0; account blows at $0
        "TopStep RTP":      0.0,
        "Funded Next":      50000.0,
        "Funded Next Flex": 48500.0,
        "FundingTicks":     50000.0,
        "TradeDay":         50000.0,
        "Tradeify":         50000.0,
        "AlphaFutures":     50000.0,
        "Apex":             50000.0,
        "Lucid":            50000.0,
        "Top One Futures":  50000.0,
        "Funded Futures Family": 48000.0,  # $50k − $2k EOD max drawdown
        "GoatFunded":       48000.0,  # $50k − $2k EOD max drawdown
    }

    # ── Profit targets for auto-status computation ────────────────────
    # Maps firm_code → phase → cumulative profit needed to pass.
    # "Challenge" target = total $ profit above starting balance to pass the challenge.
    # "Funded" target per payout = profit needed before next payout request.
    # These are used by compute_account_status() to auto-set Pass/Fail/In Progress.
    _PROFIT_TARGETS: Dict[str, Dict[str, float]] = {
        "MFFU":             {"Challenge": 3020, "Funded": 1020},
        "MFFU_Flex":        {"Challenge": 3020, "Funded": 4500},
        "Funded Next":      {"Challenge": 3050, "Funded": 5200},
        "Funded Next Flex": {"Challenge": 2500, "Funded": 3050},
        "FundingTicks":     {"Challenge": 2540, "Funded": 5000},
        "TopStep":          {"Challenge": 3020, "Funded": 5400},
        "TopStep RTP":      {"Challenge": 3020, "Funded": 5400},
        "Lucid":            {"Challenge": 3020, "Funded": 3400},
        "TradeDay":         {"Challenge": 3100, "Funded": 5000},
        "AlphaFutures":     {"Challenge": 4040, "Funded": 6000},
        "Tradeify":         {"Challenge": 3060, "Funded": 5400},
        "Apex":             {"Challenge": 7200, "Funded": 2000},
        "Top One Futures":  {"Challenge": 3030, "Funded": 3000},
        "Funded Futures Family": {"Challenge": 3020, "Funded": 5025},
        "GoatFunded":             {"Challenge": 3000, "Funded": 4050},
    }

    def compute_account_status(self, firm_code: str, phase: str,
                               current_balance: float,
                               starting_balance: float = 50000.0,
                               breached: bool = False) -> str:
        """Compute the account status based on balance vs profit targets.

        Returns one of: 'Pass', 'Fail', 'In Progress', or None if unable to determine.

        Parameters:
            firm_code:        Canonical firm identifier (e.g. 'MFFU', 'TopStep')
            phase:            Current phase display name ('Challenge' or 'Funded')
            current_balance:  Live broker balance
            starting_balance: Account starting balance (default $50,000)
            breached:         Whether the prop firm reports the account as breached
        """
        if breached:
            return "Fail"

        targets = self._PROFIT_TARGETS.get(firm_code, {})
        phase_key = "Challenge" if phase == "Challenge" else "Funded"
        target = targets.get(phase_key)
        if target is None:
            return None  # unknown firm/phase, can't determine

        profit = current_balance - starting_balance

        if profit >= target:
            return "Pass"

        # Check if balance is at or below breach threshold
        if firm_code in ("MFFU", "MFFU_Flex", "My Funded Futures"):
            if current_balance < 50100.0:
                hard_stop = 0.0
            else:
                hard_stop = 50100.0
        else:
            hard_stop = self._HARD_STOP_THRESHOLDS.get(firm_code, 50000.0)

        if current_balance <= hard_stop:
            return "Fail"

        return "In Progress"

    # NQ tick-to-MT5-point conversion ratio (1 MT5 point = 4 Tradovate ticks)
    _NQ_TICK_TO_POINT_RATIO = 4
    # Safety buffer subtracted from safe distance (MT5 points)
    _FARMING_BUFFER_POINTS = 4

    def adjust_farming_tp_sl(self, config: Dict, current_balance: float,
                             firm_code: str) -> Dict:
        """Adjust MT5 TP for farming trades based on hard-stop proximity.

        Farming trades use micro contracts (MNQU6).  If the MT5 TP is so
        large that the prop account would breach the hard-stop threshold
        before MT5 closes, we cap MT5 TP to a safe distance.

        Only MT5 TP is adjusted — Tradovate TP/SL and MT5 SL stay unchanged.

        Returns a NEW config dict (original is not mutated).
        """
        config = config.copy()
        symbol = config.get("tradovate_symbol", "") or config.get("topstepx_symbol", "")

        # Only applies to micro contracts (farming)
        if "MNQ" not in symbol.upper():
            return config

        mt5_tp = float(config.get("mt5_tp_points", 0))
        if mt5_tp <= 0:
            return config

        # Determine hard-stop threshold
        if firm_code in ("MFFU", "MFFU_Flex", "My Funded Futures"):
            # MFFU zero-start vs traditional detection:
            # If balance < $50,100 it can't be a traditional $50k account
            # (would already be breached), so it must be zero-start.
            if current_balance < 50100.0:
                hard_stop = 0.0
            else:
                hard_stop = 50100.0
        else:
            hard_stop = self._HARD_STOP_THRESHOLDS.get(firm_code, 50000.0)

        distance_to_max_loss = current_balance - hard_stop
        if distance_to_max_loss <= 0:
            self.logger.warning(
                f"[Farming TP] Balance ${current_balance:,.2f} already at/below "
                f"hard stop ${hard_stop:,.2f} for {firm_code}")
            return config

        tick_val = self.get_tick_value(symbol)
        trado_qty = int(config.get("tradovate_qty", 1) or config.get("topstepx_qty", 1))
        if tick_val <= 0 or trado_qty <= 0:
            return config

        # Distance in Tradovate ticks, then convert to MT5 points
        distance_ticks = distance_to_max_loss / (tick_val * trado_qty)
        distance_mt5_pts = distance_ticks / self._NQ_TICK_TO_POINT_RATIO
        safe_distance = distance_mt5_pts - self._FARMING_BUFFER_POINTS

        # Only cap if MT5 TP exceeds safe distance AND balance is close
        max_loss_dollars = mt5_tp * tick_val * trado_qty
        needs_adjustment = (mt5_tp > safe_distance
                            and distance_to_max_loss < max_loss_dollars)

        if needs_adjustment and safe_distance > 0:
            recommended = int(safe_distance)
            self.logger.info(
                f"[Farming TP Cap] {firm_code}: balance=${current_balance:,.2f}, "
                f"hard_stop=${hard_stop:,.2f}, distance=${distance_to_max_loss:,.2f}, "
                f"safe={safe_distance:.1f}pts → MT5 TP {mt5_tp}→{recommended}")
            config["mt5_tp_points"] = max(5, recommended)
        else:
            self.logger.info(
                f"[Farming TP OK] {firm_code}: MT5 TP {mt5_tp} pts <= "
                f"safe distance {safe_distance:.1f} pts — no change needed")

        return config

    # ── Reference-ported TP→SL adjustment pipeline ───────────────────────
    #
    # Carried verbatim from TradeAccountConnector src/prop_firm_manager.py.
    # Pre-trade adjustment runs in this order:
    #   1) calculate_adjusted_tp  — reduce TP by stage profit already earned;
    #                                scale MT5 SL proportionally.
    #   2) calculate_adjusted_sl_midnight_floor — scale SL by today's daily P/L,
    #                                using the SOD (midnight) balance as anchor.
    #   3) calculate_adjusted_sl_tmdl_cap — final cap by remaining drawdown when
    #                                live balance is below the TMDL lock level.
    #
    # All three are pure functions: they take a config dict and return a copy
    # with adjusted fields plus metadata (`_original_*`, `_tp_was_adjusted`,
    # `_sl_was_adjusted`, `_sl_adjustment_reason`, `_adj_reasons` list).

    _SL_MIN_TICKS = 10
    _TP_MIN_TICKS = 5
    _MT5_MIN_POINTS = 5
    # The MT5 hedge TP is set this many points SHORT of the SL-equivalent so
    # the MT5 hedge closes before the prop SL triggers. Matches the 4-point
    # buffer used in the farming-stage hard-stop check.
    _MT5_TP_BUFFER_POINTS = 4
    # Funded-account SL rule: trade 1 always risks exactly this many dollars.
    FUNDED_TRADE1_SL_DOLLARS = 2000.0
    FUNDED_SL_MODE_CLASSIC = "classic"
    FUNDED_SL_MODE_SPLIT = "split"

    def _ensure_mt5_hedge_config(self, config: Dict, phase_key: str = "",
                                 firm_code: str = "") -> Dict:
        """Fill missing MT5 hedge fields from Tradovate / TopStepX legs."""
        if not config:
            return config

        sym = (config.get("tradovate_symbol") or config.get("topstepx_symbol") or "")
        sym_u = sym.upper()
        if not sym_u or ("GC" in sym_u and "NQ" not in sym_u and "MNQ" not in sym_u):
            return config

        qty = float(config.get("tradovate_qty") or config.get("topstepx_qty") or 0)
        tp = int(config.get("tradovate_tp_ticks") or config.get("topstepx_tp_ticks") or 0)
        sl = int(config.get("tradovate_sl_ticks") or config.get("topstepx_sl_ticks") or 0)
        if qty <= 0 or sl <= 0:
            return config

        tick = self.get_tick_value(sym)
        prop_tp = qty * tp * tick
        pk = (phase_key or "").lower()
        is_farming = pk == "farming" or "MNQ" in sym_u
        is_funded = ("funded" in pk or "payout" in pk or "doubledip" in pk)
        is_challenge = "challenge" in pk
        is_trade1 = any(x in pk for x in ("trade1", "payout1", "doubledip_1"))
        is_trade4 = pk.endswith("trade4") or pk.endswith("_4")
        is_last_funded = is_trade4 or (
            pk.endswith("trade3") and firm_code in (
                "Funded Next", "Funded Next Flex", "FundingTicks", "Tradeify", "Lucid"))

        mtp = int(config.get("mt5_tp_points") or 0)
        msl = int(config.get("mt5_sl_points") or 0)
        vol = float(config.get("mt5_volume") or 0)

        if mtp <= 0:
            config["mt5_tp_points"] = self._sl_to_mt5_tp(sl)
            mtp = int(config["mt5_tp_points"])

        if msl <= 0:
            if is_farming:
                config["mt5_sl_points"] = 55
            elif is_funded and is_trade1:
                config["mt5_sl_points"] = 139 if sl >= 175 else 89
            elif is_funded and is_trade4:
                config["mt5_sl_points"] = 64 if sl >= 200 else 39
            elif is_funded:
                config["mt5_sl_points"] = 64 if sl >= 200 else max(39, mtp)
            elif is_challenge:
                config["mt5_sl_points"] = 30 if sl >= 200 else max(20, mtp - 10)
            elif mtp <= 25:
                config["mt5_sl_points"] = 54
            else:
                config["mt5_sl_points"] = max(self._MT5_MIN_POINTS, mtp)
            msl = int(config["mt5_sl_points"])

        if vol <= 0 and msl > 0:
            if is_farming:
                config["mt5_volume"] = 3.2
            elif is_funded and is_trade1:
                config["mt5_volume"] = round(self.FUNDED_TRADE1_SL_DOLLARS / msl, 1)
            elif is_funded and is_last_funded:
                config["mt5_volume"] = max(1.5, round(3.0 * prop_tp / 2400.0, 1))
            elif is_funded:
                config["mt5_volume"] = round(max(9.0, 18.0 * prop_tp / 2400.0), 1)
            elif mtp <= 25 and msl >= 50:
                config["mt5_volume"] = round(prop_tp / (2.0 * msl), 1)
            elif qty <= 1:
                config["mt5_volume"] = round(prop_tp / 290.0, 1)
            else:
                config["mt5_volume"] = round(prop_tp / 290.0, 1)

        return config

    @staticmethod
    def _sl_to_mt5_tp(trado_sl_ticks: int) -> int:
        """Convert Tradovate SL ticks → MT5 TP points.

        int(sl / 4) − 4-point hedge buffer, floored at _MT5_MIN_POINTS.
        """
        return max(PropFirmManager._MT5_MIN_POINTS,
                   int(trado_sl_ticks / PropFirmManager._NQ_TICK_TO_POINT_RATIO)
                   - PropFirmManager._MT5_TP_BUFFER_POINTS)

    def calculate_adjusted_tp(self, config: Dict, stage_profit_so_far: float,
                              tick_value: float = 5.0,
                              target_profit_dollars: Optional[float] = None) -> Dict:
        """Adjust TP by stage profit/shortfall; scale MT5 SL proportionally.

        When `target_profit_dollars` is supplied, TP is recalculated from the
        remaining dollars needed to reach that target. This is used for the
        Funded Next Flex funded-2 path, where the trade should always land on
        the remaining ticks needed to return the account to the target profit.

        Returns:
            Adjusted config copy. No-op if qty/tp/tick invalid, or if the
            computed TP equals the blueprint TP.
        """
        adjusted = config.copy()
        orig_tp = float(config.get('tradovate_tp_ticks', 0) or 0)
        orig_mt5_sl = float(config.get('mt5_sl_points', 0) or 0)
        qty = float(config.get('tradovate_qty', 0) or config.get('topstepx_qty', 0) or 0)

        if orig_tp <= 0 or qty <= 0 or tick_value <= 0:
            return adjusted

        if target_profit_dollars is not None:
            remaining_profit = float(target_profit_dollars) - float(stage_profit_so_far)
            remaining_ticks = remaining_profit / (tick_value * qty)
            adjusted_tp = max(self._TP_MIN_TICKS, round(remaining_ticks))
            if adjusted_tp == int(orig_tp):
                return adjusted

            tp_ratio = adjusted_tp / orig_tp if orig_tp > 0 else 1.0
            adjusted_mt5_sl = max(self._MT5_MIN_POINTS, round(orig_mt5_sl * tp_ratio)) if orig_mt5_sl > 0 else int(orig_mt5_sl)

            adjusted['_original_tradovate_tp_ticks'] = int(orig_tp)
            adjusted['_original_mt5_sl_points'] = int(orig_mt5_sl)
            adjusted['tradovate_tp_ticks'] = int(adjusted_tp)
            adjusted['mt5_sl_points'] = int(adjusted_mt5_sl)
            adjusted['_tp_was_adjusted'] = True
            adjusted.setdefault('_adj_reasons', []).append(
                f"TP {int(orig_tp)}→{int(adjusted_tp)}t: remaining ${remaining_profit:+,.0f} to target"
            )
            self.logger.info(
                f"🎯 TP-target: target=${float(target_profit_dollars):,.0f}, "
                f"current_profit=${stage_profit_so_far:,.0f}, "
                f"remaining=${remaining_profit:,.0f}, TP {int(orig_tp)}→{int(adjusted_tp)}t"
            )
            return adjusted

        profit_ticks = stage_profit_so_far / (tick_value * qty)

        # Safety net: you cannot have already earned more than the entire stage
        # TP target before this trade's stage even begins. profit_ticks >
        # orig_tp means stage_profit_so_far was over-stated upstream (e.g. a
        # hardcoded starting_balance causing the whole account balance to be
        # treated as stage profit, or stage_start falling back to 0). Trust
        # nothing here — keep the blueprint TP/SL instead of flooring TP to
        # _TP_MIN_TICKS and dragging the MT5 SL down with it.
        if profit_ticks > orig_tp:
            self.logger.warning(
                f"⚠ TP adjust SKIPPED (implausible input): profit_ticks="
                f"{profit_ticks:,.0f} > orig_tp={int(orig_tp)}t "
                f"(stage P/L=${stage_profit_so_far:,.0f}, tick_value=${tick_value}, "
                f"qty={qty:g}) — keeping blueprint TP/SL"
            )
            adjusted.setdefault('_adj_reasons', []).append(
                f"TP adjust skipped: stage P/L ${stage_profit_so_far:,.0f} "
                f"implausible (> full {int(orig_tp)}t target)"
            )
            return adjusted

        # Ahead (profit_ticks > 0) shrinks TP toward _TP_MIN_TICKS.
        # Behind (profit_ticks < 0) grows TP to make up the shortfall, capped
        # at 2× the blueprint so a bad/over-negative stage P/L can't balloon it.
        raw_tp = round(orig_tp - profit_ticks)
        tp_ceiling = 2.0 * orig_tp
        adjusted_tp = min(tp_ceiling, max(self._TP_MIN_TICKS, raw_tp))
        was_capped = raw_tp > tp_ceiling
        if adjusted_tp == orig_tp:
            return adjusted

        tp_ratio = adjusted_tp / orig_tp if orig_tp > 0 else 1.0
        adjusted_mt5_sl = max(self._MT5_MIN_POINTS, round(orig_mt5_sl * tp_ratio)) if orig_mt5_sl > 0 else int(orig_mt5_sl)

        adjusted['_original_tradovate_tp_ticks'] = int(orig_tp)
        adjusted['_original_mt5_sl_points'] = int(orig_mt5_sl)
        adjusted['tradovate_tp_ticks'] = int(adjusted_tp)
        adjusted['mt5_sl_points'] = int(adjusted_mt5_sl)
        adjusted['_tp_was_adjusted'] = True

        if profit_ticks >= 0:
            detail = "already earned in this stage"
        else:
            detail = "behind stage target — TP raised to catch up"
            if was_capped:
                detail += f", capped at 2× ({int(tp_ceiling)}t)"
        reason = (f"TP {int(orig_tp)}→{int(adjusted_tp)}t: stage P/L "
                  f"${stage_profit_so_far:+,.0f} ({detail})")
        adjusted.setdefault('_adj_reasons', []).append(reason)
        self.logger.info(
            f"📊 TP adjust: stage P/L=${stage_profit_so_far:+,.2f} → "
            f"TP {int(orig_tp)}→{int(adjusted_tp)}t, "
            f"MT5 SL {int(orig_mt5_sl)}→{int(adjusted_mt5_sl)}pts"
        )
        return adjusted

    def calculate_adjusted_sl_midnight_floor(self, config: Dict, live_net_liq: float,
                                             net_liq_sod: float, tick_value: float = 5.0) -> Dict:
        """Step 1 of SL adjustment: scale by today's daily P/L.

        Anchors at the SOD (midnight) balance so a winning intraday session
        lets the SL widen, while a losing day tightens it.

        Math:
            blueprint_sl_dollars = trado_sl * tick_value * qty
            sl_floor             = net_liq_sod - blueprint_sl_dollars
            available            = live_net_liq - sl_floor       (= daily_pnl + blueprint_sl_dollars)
            new_sl_ticks         = max(10, int(available / (tick_value * qty)))

        If `available <= 0` the SL is forced to the 10-tick minimum.
        """
        adjusted = config.copy()
        orig_sl = float(config.get('tradovate_sl_ticks', 0) or 0)
        orig_mt5_tp = float(config.get('mt5_tp_points', 0) or 0)
        qty = float(config.get('tradovate_qty', 0) or config.get('topstepx_qty', 0) or 0)

        if orig_sl <= 0 or qty <= 0 or tick_value <= 0 or net_liq_sod <= 0:
            return adjusted

        blueprint_sl_dollars = orig_sl * tick_value * qty
        sl_floor = net_liq_sod - blueprint_sl_dollars
        available = live_net_liq - sl_floor
        daily_pnl = live_net_liq - net_liq_sod

        adjusted.setdefault('_original_tradovate_sl_ticks', int(orig_sl))
        adjusted.setdefault('_original_mt5_tp_points', int(orig_mt5_tp))

        if available > 0:
            new_sl = max(self._SL_MIN_TICKS, int(available / (tick_value * qty)))
            if new_sl == int(orig_sl):
                return adjusted
            new_mt5_tp = self._sl_to_mt5_tp(new_sl)
            adjusted['tradovate_sl_ticks'] = new_sl
            adjusted['mt5_tp_points'] = new_mt5_tp
            adjusted['_sl_was_adjusted'] = True
            reason = (f"SL {int(orig_sl)}→{new_sl}t: midnight bal "
                      f"${net_liq_sod:,.0f}, daily P/L ${daily_pnl:+,.0f}")
            adjusted.setdefault('_adj_reasons', []).append(reason)
            adjusted['_sl_adjustment_reason'] = reason
            self.logger.info(
                f"🌙 Midnight SL: SOD=${net_liq_sod:,.2f}, live=${live_net_liq:,.2f}, "
                f"daily P/L=${daily_pnl:+,.2f} → SL {int(orig_sl)}→{new_sl}t, "
                f"MT5 TP {int(orig_mt5_tp)}→{new_mt5_tp}pts"
            )
        else:
            new_sl = self._SL_MIN_TICKS
            new_mt5_tp = self._sl_to_mt5_tp(new_sl)
            adjusted['tradovate_sl_ticks'] = new_sl
            adjusted['mt5_tp_points'] = new_mt5_tp
            adjusted['_sl_was_adjusted'] = True
            reason = f"SL → {new_sl}t: balance below midnight SL floor ${sl_floor:,.0f}"
            adjusted.setdefault('_adj_reasons', []).append(reason)
            adjusted['_sl_adjustment_reason'] = reason
            self.logger.warning(
                f"🚨 Midnight SL FLOOR BREACHED: live=${live_net_liq:,.2f} "
                f"below floor=${sl_floor:,.2f} → SL forced to {new_sl}t"
            )
        return adjusted

    def calculate_adjusted_sl_tmdl_cap(self, config: Dict, live_net_liq: float,
                                       live_min_equity: float, tmdl: float,
                                       tick_value: float = 5.0) -> Dict:
        """Step 2 of SL adjustment: cap by remaining drawdown.

        Only applies when the account has not yet reached the
        trailing-drawdown lock (`live_net_liq < tmdl`). Caps the (possibly
        already step-1-adjusted) SL to remaining drawdown.
        """
        adjusted = config.copy()
        orig_sl = float(config.get('tradovate_sl_ticks', 0) or 0)
        orig_mt5_tp = float(config.get('mt5_tp_points', 0) or 0)
        qty = float(config.get('tradovate_qty', 0) or config.get('topstepx_qty', 0) or 0)

        if orig_sl <= 0 or qty <= 0 or tick_value <= 0:
            return adjusted
        if live_min_equity <= 0 or live_net_liq >= tmdl:
            return adjusted  # Already at the lock — no cap needed

        drawdown_remaining = live_net_liq - live_min_equity
        if drawdown_remaining <= 0:
            self.logger.warning(
                f"⚠ TMDL cap: drawdown_remaining=${drawdown_remaining:,.2f} "
                f"(live=${live_net_liq:,.2f}, min_eq=${live_min_equity:,.2f}) — cannot tighten further"
            )
            return adjusted

        current_sl_risk = orig_sl * tick_value * qty
        if current_sl_risk <= drawdown_remaining:
            return adjusted

        capped_sl = max(self._SL_MIN_TICKS, int(drawdown_remaining / (tick_value * qty)))
        if capped_sl == int(orig_sl):
            return adjusted
        capped_mt5_tp = self._sl_to_mt5_tp(capped_sl)

        # Preserve original if midnight floor already recorded it
        adjusted.setdefault('_original_tradovate_sl_ticks', int(orig_sl))
        adjusted.setdefault('_original_mt5_tp_points', int(orig_mt5_tp))
        adjusted['tradovate_sl_ticks'] = capped_sl
        adjusted['mt5_tp_points'] = capped_mt5_tp
        adjusted['_sl_was_adjusted'] = True
        reason = (f"SL →{capped_sl}t: near drawdown limit, only "
                  f"${drawdown_remaining:,.0f} remaining")
        adjusted.setdefault('_adj_reasons', []).append(reason)
        adjusted['_sl_adjustment_reason'] = reason
        self.logger.warning(
            f"🎯 TMDL SL cap: remaining=${drawdown_remaining:,.2f} → "
            f"SL {int(orig_sl)}→{capped_sl}t, MT5 TP {int(orig_mt5_tp)}→{capped_mt5_tp}pts"
        )
        return adjusted

    def calculate_funded_sl(self, config: Dict, current_balance: float,
                            threshold: float, trade_index: int,
                            tick_value: float = 5.0) -> Dict:
        """Funded-account SL rule (REPLACES midnight-floor + TMDL for funded).

        Applies to every firm's Funded and Double Dip phases:

          • Trade 1 (funded_trade1 / doubledip_1): SL risk is fixed at
            exactly $2,000 (FUNDED_TRADE1_SL_DOLLARS).
          • Trade 2+:  SL risk dollars = current_balance - threshold, where
            `threshold` is the FLAT lock level (TopStep $0, MFFU $100,
            others $50,000) — i.e. the literal distance from the firm's
            hard drawdown floor. NOT the trailing min(lock, balance−$2,000):
            the SL must match exactly how much room is left to the floor.

        SL is converted to ticks (sl_dollars / (tick × qty)), floored at
        _SL_MIN_TICKS. The MT5 hedge TP is re-derived from the new SL via
        _sl_to_mt5_tp so the prop SL and MT5 TP close together.

        Args:
            config: Blueprint (tradovate_sl_ticks, mt5_tp_points, qty).
            current_balance: Live account balance in dollars.
            threshold: Static drawdown threshold in dollars.
            trade_index: 1-based trade number within the phase.
            tick_value: $/tick.

        Returns:
            Adjusted config copy. No-op if qty/tick invalid.
        """
        adjusted = config.copy()
        orig_sl = float(config.get('tradovate_sl_ticks', 0) or 0)
        orig_mt5_tp = float(config.get('mt5_tp_points', 0) or 0)
        qty = float(config.get('tradovate_qty', 0) or config.get('topstepx_qty', 0) or 0)

        if qty <= 0 or tick_value <= 0:
            return adjusted

        if trade_index <= 1:
            sl_dollars = self.FUNDED_TRADE1_SL_DOLLARS
            basis = f"funded trade 1 — fixed ${sl_dollars:,.0f} SL"
        else:
            sl_dollars = current_balance - threshold
            basis = (f"funded trade {trade_index} — balance "
                     f"${current_balance:,.0f} − threshold ${threshold:,.0f}")

        new_sl = max(self._SL_MIN_TICKS,
                     int(round(sl_dollars / (tick_value * qty))))
        new_mt5_tp = self._sl_to_mt5_tp(new_sl)

        adjusted.setdefault('_original_tradovate_sl_ticks', int(orig_sl))
        adjusted.setdefault('_original_mt5_tp_points', int(orig_mt5_tp))
        adjusted['tradovate_sl_ticks'] = new_sl
        adjusted['mt5_tp_points'] = new_mt5_tp
        adjusted['_sl_was_adjusted'] = True
        reason = (f"SL {int(orig_sl)}→{new_sl}t (${sl_dollars:,.0f}): {basis}")
        adjusted.setdefault('_adj_reasons', []).append(reason)
        adjusted['_sl_adjustment_reason'] = reason
        self.logger.info(
            f"💵 Funded SL rule: {reason}, "
            f"MT5 TP {int(orig_mt5_tp)}→{new_mt5_tp}pts"
        )
        return adjusted

    def get_lock_level(self, prop_firm: str, other_broker: Optional[str] = None) -> float:
        """Public: the flat lock-level floor for a firm.

        TopStep $0, MFFU $100, all others $50,000. This is the threshold the
        funded SL rule measures distance from (SL$ = balance − lock_level for
        funded trade 2+), NOT the trailing min(lock, balance−$2,000).
        """
        return self._get_lock_level(prop_firm, other_broker)

    def _get_lock_level(self, prop_firm: str, other_broker: Optional[str] = None) -> float:
        """Return the absolute floor the trailing threshold locks at."""
        if prop_firm in ("TopStep", "TopStep RTP") or (prop_firm == "Other" and other_broker == "TopStep"):
            return 0.0
        if prop_firm in ("MFFU_Flex", "MFFU", "My Funded Futures"):
            return 100.0
        return 50000.0  # Standard $50k-start firms (and challenge phase)

    def get_default_config(self) -> Dict:
        """Get the default strategy config (MFFU_Flex challenge_trade1 50k).

        Used as the ultimate fallback when no specific config is available.
        Always pulls from the actual MFFU_Flex blueprint, never hardcoded values.
        """
        return self.get_strategy_config("MFFU_Flex", "challenge_trade1", "50k")

    def get_default_symbol(self, broker: str = "tradovate") -> str:
        """Get the default trading symbol for a broker platform.

        Pulls from the MFFU_Flex challenge_trade1 blueprint.
        """
        config = self.get_default_config()
        if broker.lower() == "topstepx" or broker.lower() == "topstep":
            return config.get("topstepx_symbol", config.get("tradovate_symbol", ""))
        return config.get("tradovate_symbol", "")

    # ── Per-Account Daily Direction Lock ──────────────────────────────

    def check_and_lock_direction(self, account_number: str, side: str) -> bool:
        """Enforce one-direction-per-day rule *per account*.

        Args:
            account_number: The Tradovate/TopStep account identifier.
            side: 'BUY' or 'SELL'.

        Returns:
            True if the trade is allowed, False if blocked.
        """
        if not account_number or account_number in ("Unknown", "Not Connected"):
            # Can't enforce without a valid account — allow but warn
            self.logger.warning("Direction lock skipped: no valid account number")
            return True

        # Kenya time, not host local time — see _KENYA_TZ note at the top.
        today = _kenya_today()
        side_upper = side.upper()
        lock = self._account_direction_locks.get(account_number)

        # New day → reset
        if lock is None or lock["date"] != today:
            self._account_direction_locks[account_number] = {"date": today, "direction": side_upper}
            self.logger.info(f"[RULE] Daily direction LOCKED to {side_upper} for account {account_number} ({today})")
            return True

        # Same day — check direction
        if lock["direction"] == side_upper:
            return True

        self.logger.warning(
            f"[BLOCK] Direction violation for {account_number}: "
            f"locked={lock['direction']}, attempted={side_upper}"
        )
        return False

    def get_locked_direction(self, account_number: str) -> Optional[str]:
        """Return the locked direction for an account today, or None."""
        if not account_number:
            return None
        today = _kenya_today()
        lock = self._account_direction_locks.get(account_number)
        if lock and lock["date"] == today:
            return lock["direction"]
        return None

    def reset_direction_lock(self, account_number: str) -> None:
        """Manually reset the direction lock for a specific account."""
        self._account_direction_locks.pop(account_number, None)
        self.logger.info(f"[RULE] Direction lock reset for account {account_number}")

    # ── Blueprint ↔ Account Validation ───────────────────────────────

    def detect_firm_from_account(self, account_number: str) -> Optional[str]:
        """Detect the prop firm from a Tradovate/TopStep account number.

        Returns the UI-facing blueprint name (e.g. 'MFFU_Flex', 'Funded Next')
        or None if detection fails.
        """
        detected_code = self.detect_prop_firm(account_number)
        if detected_code is None:
            self.logger.warning(f"Account '{account_number}' — prop firm could not be identified")
            return None
        blueprint = self.DETECTED_TO_BLUEPRINT.get(detected_code)
        if blueprint:
            self.logger.info(f"Account '{account_number}' detected as '{detected_code}' → blueprint '{blueprint}'")
        else:
            self.logger.warning(f"Account '{account_number}' detected as '{detected_code}' but no blueprint mapping exists")
        return blueprint

    def validate_blueprint_match(self, account_number: str, selected_blueprint: str) -> Tuple[bool, Optional[str]]:
        """Check whether the selected blueprint matches the connected account.

        Args:
            account_number: Account identifier from Tradovate/TopStep.
            selected_blueprint: The blueprint currently selected in the UI.

        Returns:
            (is_match, detected_blueprint)
            - is_match is True when they are compatible.
            - detected_blueprint is the blueprint we think the account belongs to.
        """
        detected = self.detect_firm_from_account(account_number)
        if detected is None:
            # Detection inconclusive — allow but warn
            return True, None

        # Treat MFFU and MFFU_Flex as compatible
        compatible_groups = [
            {"MFFU", "MFFU_Flex"},
            {"Alpha Futures", "AlphaFutures"},
        ]
        for group in compatible_groups:
            if detected in group and selected_blueprint in group:
                return True, detected

        is_match = (detected == selected_blueprint)
        if not is_match:
            self.logger.warning(
                f"Blueprint MISMATCH: account '{account_number}' belongs to '{detected}' "
                f"but '{selected_blueprint}' is selected"
            )
        return is_match, detected
