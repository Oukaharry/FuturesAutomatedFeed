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
