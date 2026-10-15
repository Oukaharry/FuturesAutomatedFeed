"""TopStep RTP switches to 47-tick *_p2 keys after funded payout 1."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "trader_companion"))

from prop_firm_manager import PropFirmManager  # noqa: E402


def test_no_remap_before_first_payout():
    m = PropFirmManager()
    assert m.remap_phase_key_for_funded_payout("TopStep RTP", "funded_trade2", 0) == "funded_trade2"


def test_remap_after_payout_to_p2_keys():
    m = PropFirmManager()
    assert m.remap_phase_key_for_funded_payout(
        "TopStep RTP", "funded_trade1", 1) == "funded_trade1_p2"
    assert m.remap_phase_key_for_funded_payout(
        "TopStep RTP", "funded_trade2", 2) == "funded_trade2_p2"


def test_get_strategy_config_tp_ticks_after_payout():
    m = PropFirmManager()
    pre = m.get_strategy_config("TopStep RTP", "funded_trade2", "50k", funded_payout_count=0)
    post = m.get_strategy_config("TopStep RTP", "funded_trade2", "50k", funded_payout_count=1)
    assert int(pre.get("topstepx_tp_ticks")) == 114
    assert int(post.get("topstepx_tp_ticks")) == 47
    assert float(post.get("mt5_volume") or 0) > 0


def _as_tradovate_keys(cfg):
    """_apply_tp_sl_adjustments mirrors topstepx_* onto tradovate_* before adjusting."""
    cfg = dict(cfg)
    cfg["tradovate_tp_ticks"] = cfg["topstepx_tp_ticks"]
    cfg["tradovate_sl_ticks"] = cfg["topstepx_sl_ticks"]
    cfg["tradovate_qty"] = cfg["topstepx_qty"]
    return cfg


def test_cycle_goal_adjuster_keeps_the_470_payout2_tp():
    """Regression: post-payout RTP trade was re-aimed to $1,500 instead of $470.

    With the payout uncounted the 114-tick first-cycle config was used and the
    funded cycle-goal adjuster aimed at the $5,400 target: 5400 - 3900 banked
    = $1,500 → 150 ticks. The 47-tick payout-2+ blueprint is now pinned.
    """
    m = PropFirmManager()
    first_cycle = _as_tradovate_keys(
        m.get_strategy_config("TopStep RTP", "funded_trade2", "50k", funded_payout_count=0))
    buggy = m.calculate_adjusted_tp(first_cycle, 3900.0, 5.0, target_profit_dollars=5400.0)
    assert buggy["tradovate_tp_ticks"] * 2 * 5.0 == 1500.0

    payout2 = _as_tradovate_keys(
        m.get_strategy_config("TopStep RTP", "funded_trade2", "50k", funded_payout_count=1))
    fixed = m.calculate_adjusted_tp(payout2, 3900.0, 5.0, target_profit_dollars=5400.0)
    assert fixed["tradovate_tp_ticks"] == 47
    assert fixed["tradovate_tp_ticks"] * 2 * 5.0 == 470.0


def test_p2_keys_keep_their_own_trade_index():
    from trader_companion.trader_app import TradeOpssAIApp

    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    assert app._phase_trade_index("funded_trade1_p2") == 1
    assert app._phase_trade_index("funded_trade3_p2") == 3
    assert app._phase_trade_index("funded_trade2") == 2


def test_cleared_payout_marker_still_counts_as_a_payout():
    """TopStepX has no Tradovate balance history, so the marker is the evidence."""
    from trader_companion.trader_app import TradeOpssAIApp

    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    app._trade_outcome_history = lambda force=False: {}
    app._save_breach_state = lambda: None
    row = {
        "Prop Firm": "TopStep RTP",
        "Account #": "RTP-CH-1",
        "Account #.1": "RTP-FD-50000123",
        "Hedge Result 1.1": "1140.00",
        "Hedge Result 2.1": "PAYOUT",
    }
    assert app._funded_payout_count(row) == 1

    row["Hedge Result 2.1"] = "WEDNESDAY"
    assert app._funded_payout_count(row) == 1
    assert app._effective_phase_key(row, "TopStep RTP", "funded_trade2") == "funded_trade2_p2"
