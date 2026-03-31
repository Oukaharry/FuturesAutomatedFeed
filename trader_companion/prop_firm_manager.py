# prop_firm_manager.py - Prop Firm Blueprint Management System
# Handles different prop firm configurations for manual trading

import logging
import datetime
from typing import Dict, Optional, Tuple

class PropFirmManager:
    """
    Manages prop firm-specific configurations and blueprints.
    
    Supported Prop Firms:
    - MFFU: My Funded Futures
    - Funded Next: Funded Next
    - FundingTicks: Funding Ticks
    - TopStep: TopStep
    - Trade Day: Trade Day (EOD Account Type)
    - Tradeify: Tradeify (Growth Account)
    - Top One Futures: Top One Futures
    
    All configurations are for $50,000 accounts and manual trading only.
    """
    
    # Mapping from detected firm code -> UI dropdown blueprint name
    DETECTED_TO_BLUEPRINT = {
        "MFFU": "MFFU_Flex",
        "MFFU_Flex": "MFFU_Flex",
        "Funded Next": "Funded Next",
        "FundedNext": "Funded Next",
        "FundingTicks": "FundingTicks",
        "Trade Day": "TradeDay",
        "TopStep": "TopStep",
        "Apex": "Apex",
        "Tradeify": "Tradeify",
        "Lucid": "Lucid",
        "AlphaFutures": "Alpha Futures",
        "AlphaFutures GC": "AlphaFutures GC",
        "Top One Futures": "Top One Futures",
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.current_firm_code = "MFFU"  # Default prop firm

        # Per-account daily direction locks: {account_number: {"date": date, "direction": "BUY"/"SELL"}}
        self._account_direction_locks: Dict[str, Dict] = {}
        
        # Prop firm blueprints - $50k account configurations only core challange with the flex addon
        self.firm_blueprints = {
            "MFFU": {
                "name": "MFFU",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Funded Phase", "Farming Phase"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 151,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 2.8,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 42
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 151,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 5.2,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 42
                        }
                    },
                    "funded": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 1,
                            "tradovate_tp_ticks": 204,
                            "tradovate_sl_ticks": 400,
                            "mt5_volume": 4.8,
                            "mt5_tp_points": 96,
                            "mt5_sl_points": 55
                        }
                    },
                    "funded_1": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 500,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 15.8,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 129
                        }
                    },
                    "funded_2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 290,
                            "mt5_volume": 18,
                            "mt5_tp_points": 68,
                            "mt5_sl_points": 79
                        }
                    },
                    "funded_3": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 190,
                            "mt5_volume": 18,
                            "mt5_tp_points": 43,
                            "mt5_sl_points": 29
                        }
                    },
                    "funded_4": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 150,
                            "tradovate_sl_ticks": 165,
                            "mt5_volume": 13.6,
                            "mt5_tp_points": 37,
                            "mt5_sl_points": 42
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQM6",
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
            "MFFU_Flex": {
                "name": "MFFU_Flex",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Funded Phase", "Double Dip Phase", "Farming Phase"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 151,
                            "tradovate_sl_ticks": 201,
                            "mt5_volume": 4.6,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 42
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 151,
                            "tradovate_sl_ticks": 201,
                            "mt5_volume": 8.4,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 42
                        }
                    },
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 540,
                            "tradovate_sl_ticks": 201,
                            "mt5_volume": 16,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 139
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 261,
                            "mt5_volume": 20,
                            "mt5_tp_points": 61,
                            "mt5_sl_points": 79
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 276,
                            "mt5_volume": 18.0,
                            "mt5_tp_points": 65,
                            "mt5_sl_points": 79
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 284,
                            "mt5_volume": 13.6,
                            "mt5_tp_points": 66,
                            "mt5_sl_points": 79
                        }
                    },"funded_trade_doubledip_1": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 540,
                            "tradovate_sl_ticks": 201,
                            "mt5_volume": 13,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 139
                        }
                    },"funded_trade_doubledip_2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 261,
                            "mt5_volume": 14,
                            "mt5_tp_points": 61,
                            "mt5_sl_points": 79
                        }
                    },"funded_trade_doubledip_3": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 276,
                            "mt5_volume": 9,
                            "mt5_tp_points": 65,
                            "mt5_sl_points": 79
                        }
                    },"funded_trade_doubledip_4": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 284,
                            "mt5_volume": 20,
                            "mt5_tp_points": 66,
                            "mt5_sl_points": 79
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 260,
                            "mt5_volume": 17,
                            "mt5_tp_points": 61,
                            "mt5_sl_points": 79
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 285,
                            "mt5_volume": 7,
                            "mt5_tp_points": 67,
                            "mt5_sl_points": 79
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 298,
                            "mt5_volume": 0,
                            "mt5_tp_points": 70,
                            "mt5_sl_points": 79
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "MNQM6",
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
                "trading_phases": ["Challenge Phase", "Funded Phase", "Double Dip Phase", "Farming Phase"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "topstepx_symbol": "NQM26",
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
                            "topstepx_symbol": "NQM26",
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
                            "topstepx_symbol": "NQM26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 540,
                            "topstepx_sl_ticks": 201,
                            "mt5_volume": 16,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 139
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "topstepx_symbol": "NQM26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 300,
                            "topstepx_sl_ticks": 261,
                            "mt5_volume": 20,
                            "mt5_tp_points": 61,
                            "mt5_sl_points": 79
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "topstepx_symbol": "NQM26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 300,
                            "topstepx_sl_ticks": 276,
                            "mt5_volume": 18.0,
                            "mt5_tp_points": 65,
                            "mt5_sl_points": 79
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "topstepx_symbol": "NQM26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 300,
                            "topstepx_sl_ticks": 284,
                            "mt5_volume": 13.6,
                            "mt5_tp_points": 66,
                            "mt5_sl_points": 79
                        }
                    },"funded_trade_doubledip_1": {
                        "50k": {
                            "topstepx_symbol": "NQM26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 540,
                            "topstepx_sl_ticks": 201,
                            "mt5_volume": 15,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 139
                        }
                    },"funded_trade_doubledip_2": {
                        "50k": {
                            "topstepx_symbol": "NQM26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 300,
                            "topstepx_sl_ticks": 261,
                            "mt5_volume": 14,
                            "mt5_tp_points": 61,
                            "mt5_sl_points": 79
                        }
                    },"funded_trade_doubledip_3": {
                        "50k": {
                            "topstepx_symbol": "NQM26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 300,
                            "topstepx_sl_ticks": 276,
                            "mt5_volume": 9,
                            "mt5_tp_points": 65,
                            "mt5_sl_points": 79
                        }
                    },"funded_trade_doubledip_4": {
                        "50k": {
                            "topstepx_symbol": "NQM26",
                            "topstepx_qty": 2,
                            "topstepx_tp_ticks": 300,
                            "topstepx_sl_ticks": 284,
                            "mt5_volume": 20,
                            "mt5_tp_points": 66,
                            "mt5_sl_points": 79
                        }
                    },
                    "farming": {
                        "50k": {
                            "topstepx_symbol": "MNQM26",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 170,
                            "mt5_volume": 18,
                            "mt5_tp_points": 38,
                            "mt5_sl_points": 54
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 190,
                            "mt5_volume": 18.0,
                            "mt5_tp_points": 43,
                            "mt5_sl_points": 54
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 54
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 500,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 20,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 129
                        }
                    }
                }
            },
            "AlphaFutures": {
                "name": "AlphaFutures",
                "account_sizes": ["$50,000", "$100,000", "$150,000"],
                "trading_phases": ["Challenge Phase", "Funded Phase", "Farming Phase"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 202,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume":3,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        },
                        "100k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 4,
                            "tradovate_tp_ticks": 202,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 6,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        },
                        "150k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 6,
                            "tradovate_tp_ticks": 202,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 9,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 202,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 7.4,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        },
                        "100k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 4,
                            "tradovate_tp_ticks": 202,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 14.8,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        },
                        "150k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 6,
                            "tradovate_tp_ticks": 202,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 22.2,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 55
                        },
                    },
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 600,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 22,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 154
                        },
                        "100k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 4,
                            "tradovate_tp_ticks": 600,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 44,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 154
                        },
                        "150k": {
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 40,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 29
                        },
                        "100k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 4,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 80,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 29
                        },
                        "150k": {
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 25,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 54
                        },
                        "100k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 4,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 50,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 54
                        },
                        "150k": {
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 15,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 54
                        },
                        "100k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 4,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 175,
                            "mt5_volume": 30,
                            "mt5_tp_points": 39,
                            "mt5_sl_points": 54
                        },
                        "150k": {
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "MNQM6",
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
            "AlphaFutures GC": {
                "name": "AlphaFutures GC",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Funded Phase", "Farming Phase"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": { 
                            "tradovate_symbol": "GCM6", 
                            "tradovate_qty": 1, 
                            "tradovate_tp_ticks": 201, 
                            "tradovate_sl_ticks": 175, 
                            "mt5_symbol": "XAUUSD",
                            "mt5_volume": 0.09, 
                            "mt5_tp_points": 1710, 
                            "mt5_sl_points": 2050 
                        }
                    },
                    "challenge_trade2": {
                        "50k": { 
                            "tradovate_symbol": "GCM6", 
                            "tradovate_qty": 1, 
                            "tradovate_tp_ticks": 201, 
                            "tradovate_sl_ticks": 175, 
                            "mt5_symbol": "XAUUSD",
                            "mt5_volume": 0.2, 
                            "mt5_tp_points": 1710, 
                            "mt5_sl_points": 2050 
                        }
                    },
                    "funded_trade1": {
                        "50k": { 
                            "tradovate_symbol": "GCM6", 
                            "tradovate_qty": 2, 
                            "tradovate_tp_ticks": 300, 
                            "tradovate_sl_ticks": 88, 
                            "mt5_symbol": "XAUUSD",
                            "mt5_volume": 0.49, 
                            "mt5_tp_points": 1710, 
                            "mt5_sl_points": 6040 
                        }
                    },
                    "funded_trade2": {
                        "50k": { 
                            "tradovate_symbol": "GCM6", 
                            "tradovate_qty": 1, 
                            "tradovate_tp_ticks": 100, 
                            "tradovate_sl_ticks": 175, 
                            "mt5_symbol": "XAUUSD",
                            "mt5_volume": 0.75, 
                            "mt5_tp_points": 1710, 
                            "mt5_sl_points": 1040 
                        }
                    },
                    "funded_trade3": {
                        "50k": { 
                            "tradovate_symbol": "GCM6", 
                            "tradovate_qty": 1, 
                            "tradovate_tp_ticks": 200, 
                            "tradovate_sl_ticks": 175, 
                            "mt5_symbol": "XAUUSD",
                            "mt5_volume": 0.24, 
                            "mt5_tp_points": 1710, 
                            "mt5_sl_points": 2040 
                        }
                    },
                    "funded_trade4": {
                        "50k": { 
                            "tradovate_symbol": "GCM6", 
                            "tradovate_qty": 1, 
                            "tradovate_tp_ticks": 200, 
                            "tradovate_sl_ticks": 175, 
                            "mt5_symbol": "XAUUSD",
                            "mt5_volume": 0, 
                            "mt5_tp_points": 1710, 
                            "mt5_sl_points": 2040 
                        }
                    },
                    "farming": {
                        "50k": {
                             "tradovate_symbol": "MGCM6", 
                             "tradovate_qty": 1, 
                             "tradovate_tp_ticks": 204, 
                             "tradovate_sl_ticks": 600, 
                             "mt5_symbol": "XAUUSD",
                             "mt5_volume": 0.9, 
                             "mt5_tp_points": 596, 
                             "mt5_sl_points": 208 
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
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 85,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 3.6,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 26
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 85,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 5.6,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 26
                        }
                    },"challenge_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 85,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 8.8,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 26
                        }
                    },
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 540,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 13.8,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 139
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 260,
                            "mt5_volume": 18,
                            "mt5_tp_points": 61,
                            "mt5_sl_points": 79
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 275,
                            "mt5_volume": 3,
                            "mt5_tp_points": 64,
                            "mt5_sl_points": 79
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 283,
                            "mt5_volume": 0,
                            "mt5_tp_points": 28,
                            "mt5_sl_points": 29
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQM6",
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
                            "tradovate_symbol": "NQM6",
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
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 410,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 107
                        }
                    },
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 54
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 29
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 150,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 42
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 150,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 21,
                            "mt5_sl_points": 42
                        }
                    },
                    "farming": {
                        "50k": {
                            "tradovate_symbol": "MNQM6",
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
                "name": "Top One Futures",
                "account_sizes": ["$50,000"],
                "trading_phases": ["Challenge Phase", "Funded Phase", "Double Dip Phase"],
                "strategy_configs": {
                    "challenge_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 101,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 2.6,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 30
                        }
                    },
                    "challenge_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 101,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 4.8,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 30
                        }
                    },
                    "challenge_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 101,
                            "tradovate_sl_ticks": 200,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 30
                        }
                    },
                    "funded_trade1": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 79
                        }
                    },
                    "funded_trade1_2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 400,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 79
                        }
                    },
                    "funded_trade2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 29
                        }
                    },
                    "funded_trade2_2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 29
                        }
                    },
                    "funded_trade3": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 29
                        }
                    },
                    "funded_trade3_2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 29
                        }
                    },
                    "funded_trade4": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 29
                        }
                    },
                    "funded_trade4_2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 29
                        }
                    },
                    "funded_trade_doubledip_1": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 300,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 79
                        }
                    },
                    "funded_trade_doubledip_1_2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 400,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 79
                        }
                    },
                    "funded_trade_doubledip_2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 29
                        }
                    },
                    "funded_trade_doubledip_2_2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 29
                        }
                    },
                    "funded_trade_doubledip_3": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 29
                        }
                    },
                    "funded_trade_doubledip_3_2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 29
                        }
                    },
                    "funded_trade_doubledip_4": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 100,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 29
                        }
                    },
                    "funded_trade_doubledip_4_2": {
                        "50k": {
                            "tradovate_symbol": "NQM6",
                            "tradovate_qty": 2,
                            "tradovate_tp_ticks": 200,
                            "tradovate_sl_ticks": 100,
                            "mt5_volume": 0,
                            "mt5_tp_points": 46,
                            "mt5_sl_points": 29
                        }
                    }
                }
            }
        }
    
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
        
        self.logger.warning(f"Unknown prefix '{prefix}' from account '{username}' — prop firm not recognized")
        return None
    
    def get_firm_info(self, firm_code: str) -> Dict:
        """Get complete prop firm information."""
        # Normalize firm_code to handle variations
        normalized_code = firm_code
        if firm_code == "Alpha Futures":
            normalized_code = "AlphaFutures"
        elif firm_code == "FundedNext":
            normalized_code = "Funded Next"
        elif firm_code == "TopOneFutures":
            normalized_code = "Top One Futures"
        
        return self.firm_blueprints.get(normalized_code, self.firm_blueprints["MFFU"])
    
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
            self.logger.warning(f"Phase '{phase_key}' not found for '{firm_code}', using MFFU default")
            mffu_configs = self.firm_blueprints["MFFU"]["strategy_configs"]
            phase_config = mffu_configs.get(phase_key, {})
        
        self.logger.info(f"[DEBUG get_strategy_config] phase_config keys: {list(phase_config.keys()) if phase_config else 'None'}")
        
        config = phase_config.get(size_key)
        if not config:
            # For farming phase, try to fallback to 50k first before using MFFU fallback
            if phase_key == "farming" and size_key != "50k" and "50k" in phase_config:
                self.logger.info(f"Farming config not found for '{size_key}', using 50k farming config instead")
                config = phase_config["50k"]
            else:
                self.logger.warning(f"Config not found for '{firm_code}/{phase_key}/{size_key}', using MFFU fallback")
                config = self.firm_blueprints["MFFU"]["strategy_configs"]["challenge_trade1"]["50k"]
        else:
            self.logger.info(f"[DEBUG get_strategy_config] Found config: qty={config.get('tradovate_qty', 'N/A')}, volume={config.get('mt5_volume', 'N/A')}")
        
        if config:
            config = config.copy()
            if 'mt5_volume' in config:
                config['mt5_volume'] = round(config['mt5_volume'], 2)
        
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
            "MFFU": "MFFU",
            "MFFU_Flex": "MFFU_Flex",
            "Funded Next": "Funded Next",
            "FundedNext": "Funded Next",
            "FundingTicks": "FundingTicks",
            "TopStep": "TopStep",
            "Tradeify": "Tradeify",
            "Apex": "Apex",
            "Alpha Futures": "AlphaFutures",
            "AlphaFutures": "AlphaFutures",
            "AlphaFutures GC": "AlphaFutures GC",
            "Top One Futures": "Top One Futures",
            "Other": "MFFU"  # Default fallback
        }
        
        # For "Other" prop firm, we prefer the specific blueprint if provided
        if firm_name == "Other":
            if blueprint_firm and blueprint_firm in self.firm_blueprints:
                self.current_firm_code = blueprint_firm
                self.logger.info(f"Other mode: Using specific blueprint {self.current_firm_code}")
            elif broker and broker == "TopStep":
                self.current_firm_code = "TopStep"
            else:  # Tradovate or any other
                self.current_firm_code = "MFFU"
            
            if not blueprint_firm:
                self.logger.info(f"Other mode: Mapped to {self.current_firm_code} based on broker '{broker}'")
        else:
            self.current_firm_code = firm_mapping.get(firm_name, firm_name)
        
        self.logger.info(f"Set prop firm to: {self.current_firm_code}")
    
    def get_prop_firm_strategy_config(self, trading_phase, account_size="$50,000", balance_performance=0.0):
        """Get strategy config for current prop firm (manual trading only)"""
        self.logger.info(f"Looking up: '{self.current_firm_code}', phase='{trading_phase}', size='{account_size}'")
        
        firm_info = self.firm_blueprints.get(self.current_firm_code, self.firm_blueprints["MFFU"])
        
        if self.current_firm_code not in self.firm_blueprints:
            self.logger.warning(f"Blueprint '{self.current_firm_code}' not found! Using MFFU fallback")
        
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
                if balance_performance >= 5.0:
                    phase_key = "challenge_trade3"
                elif balance_performance >= 2.5:
                    phase_key = "challenge_trade2"
                else:
                    phase_key = "challenge_trade1"
            else:
                phase_key = "challenge_trade2" if balance_performance >= 2.5 else "challenge_trade1"
        
        self.logger.info(f"[DEBUG] Using phase_key '{phase_key}' for phase '{trading_phase}'")
        
        if trading_phase == "Funded Phase":
            if self.current_firm_code == "MFFU":
                phase_key = "funded"
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
            elif self.current_firm_code == "Top One Futures":
                if balance_performance < 2.0:
                    phase_key = "funded_trade1"
                elif balance_performance < 4.0:
                    phase_key = "funded_trade2"
                elif balance_performance < 6.0:
                    phase_key = "funded_trade3"
                else:
                    phase_key = "funded_trade4"
            elif self.current_firm_code == "FundingTicks":
                phase_key = "funded_trade1" # Default to trade 1
            elif self.current_firm_code == "Tradeify":
                phase_key = "funded_trade1"
            else:
                # Default for others
                phase_key = "funded_trade1"

        if trading_phase == "Double Dip Phase":
            if self.current_firm_code == "TopStep":
                # TopStep Double Dip Phase Logic
                if balance_performance < 2.0:
                    phase_key = "funded_trade_doubledip_1"
                elif balance_performance < 4.0:
                    phase_key = "funded_trade_doubledip_2"
                elif balance_performance < 6.0:
                    phase_key = "funded_trade_doubledip_3"
                else:
                    phase_key = "funded_trade_doubledip_4"
            elif self.current_firm_code == "Top One Futures":
                # Top One Futures Double Dip Phase Logic
                if balance_performance < 2.0:
                    phase_key = "funded_trade_doubledip_1"
                elif balance_performance < 4.0:
                    phase_key = "funded_trade_doubledip_2"
                elif balance_performance < 6.0:
                    phase_key = "funded_trade_doubledip_3"
                else:
                    phase_key = "funded_trade_doubledip_4"
            else:
                phase_key = "funded" # Fallback

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
        
        if phase_key == "farming" and self.current_firm_code == "Funded Next":
            # Strict logic: Funded Next farming MUST use 50k blueprint regardless of size
            if "50k" in phase_configs:
                self.logger.info(f"Enforcing Funded Next 50k farming blueprint for '{size_key}'")
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
                mffu_configs = self.firm_blueprints["MFFU"]["strategy_configs"]
                # Map current phase_key to MFFU equivalent if possible
                mffu_phase_key = phase_key
                if "funded" in phase_key: mffu_phase_key = "funded"
                elif "farming" in phase_key: mffu_phase_key = "farming"
                else: mffu_phase_key = "challenge_trade1"
                
                fallback = mffu_configs.get(mffu_phase_key, {}).get(size_key, {})
                
                if fallback:
                    self.logger.warning(f"No config for {self.current_firm_code}/{phase_key}, using MFFU {mffu_phase_key}")
                    return fallback
                else:
                    ultimate_fallback = {
                        "tradovate_symbol": "MNQM6",
                        "tradovate_qty": 2,
                        "tradovate_tp_ticks": 154,
                        "tradovate_sl_ticks": 400,
                        "mt5_volume": 4.0,
                        "mt5_tp_points": 98,
                        "mt5_sl_points": 41
                    }
                    self.logger.error(f"No valid config, using ultimate fallback")
                    return ultimate_fallback
        
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
        "MFFU": {
            "Challenge": ["challenge_trade1", "challenge_trade2"],
            "Funded":    ["funded", "funded_1", "funded_2", "funded_3", "funded_4"],
            "Farming":   ["farming"],
        },
        "MFFU_Flex": {
            "Challenge":  ["challenge_trade1", "challenge_trade2"],
            "Funded":     ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Double Dip": ["funded_trade_doubledip_1", "funded_trade_doubledip_2",
                           "funded_trade_doubledip_3", "funded_trade_doubledip_4"],
            "Farming":    ["farming"],
        },
        "Funded Next": {
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
        "Lucid": {
            "Challenge": ["challenge_trade1", "challenge_trade2"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Farming":   ["farming"],
        },
        "TradeDay": {
            "Challenge": ["challenge_trade1", "challenge_trade2", "challenge_trade3",
                          "challenge_trade4", "challenge_trade5"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3"],
        },
        "AlphaFutures": {
            "Challenge": ["challenge_trade1", "challenge_trade2"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Farming":   ["farming"],
        },
        "AlphaFutures GC": {
            "Challenge": ["challenge_trade1", "challenge_trade2"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Farming":   ["farming"],
        },
        "Tradeify": {
            "Challenge": ["challenge_trade1", "challenge_trade2", "challenge_trade3"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Farming":   ["farming"],
        },
        "Apex": {
            "Challenge": ["challenge_trade1", "challenge_trade2"],
            "Funded":    ["funded_trade1", "funded_trade2", "funded_trade3", "funded_trade4"],
            "Farming":   ["farming"],
        },
        "Top One Futures": {
            "Challenge":  ["challenge_trade1", "challenge_trade2", "challenge_trade3"],
            "Funded":     ["funded_trade1", "funded_trade1_2", "funded_trade2", "funded_trade2_2",
                           "funded_trade3", "funded_trade3_2", "funded_trade4", "funded_trade4_2"],
            "Double Dip": ["funded_trade_doubledip_1", "funded_trade_doubledip_1_2",
                           "funded_trade_doubledip_2", "funded_trade_doubledip_2_2",
                           "funded_trade_doubledip_3", "funded_trade_doubledip_3_2",
                           "funded_trade_doubledip_4", "funded_trade_doubledip_4_2"],
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
        phase_key_group = phase_map.get(current_phase, current_phase)

        firm_orders = self._PHASE_TRADE_ORDER.get(firm_code, {})
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
        # If in loss, tighten SL to limit further damage.
        # New SL target in dollars = original SL risk + any existing profit
        # (existing profit acts as a buffer we can afford to lose)
        adjusted_sl_dollars = target_loss + current_profit
        # Floor: at least 30% of original SL to avoid being stopped out instantly
        adjusted_sl_dollars = max(adjusted_sl_dollars, target_loss * 0.30)
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
        "Funded Next":      50000.0,
        "FundingTicks":     50000.0,
        "TradeDay":         50000.0,
        "Tradeify":         50000.0,
        "AlphaFutures":     50000.0,
        "Apex":             50000.0,
        "Lucid":            50000.0,
        "Top One Futures":  50000.0,
    }

    # NQ tick-to-MT5-point conversion ratio (1 MT5 point = 4 Tradovate ticks)
    _NQ_TICK_TO_POINT_RATIO = 4
    # Safety buffer subtracted from safe distance (MT5 points)
    _FARMING_BUFFER_POINTS = 4

    def adjust_farming_tp_sl(self, config: Dict, current_balance: float,
                             firm_code: str) -> Dict:
        """Adjust MT5 TP for farming trades based on hard-stop proximity.

        Farming trades use micro contracts (MNQM6).  If the MT5 TP is so
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

    def get_default_config(self) -> Dict:
        """Get the default strategy config (MFFU challenge_trade1 50k).
        
        Used as the ultimate fallback when no specific config is available.
        Always pulls from the actual MFFU blueprint, never hardcoded values.
        """
        return self.get_strategy_config("MFFU", "challenge_trade1", "50k")

    def get_default_symbol(self, broker: str = "tradovate") -> str:
        """Get the default trading symbol for a broker platform.
        
        Pulls from the MFFU challenge_trade1 blueprint.
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

        today = datetime.date.today()
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
        today = datetime.date.today()
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
            {"Alpha Futures", "AlphaFutures GC"},
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
