"""Post funded-trade-1 breach floors (prop_firm_manager.get_breach_floor)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "trader_companion"))

from prop_firm_manager import PropFirmManager  # noqa: E402


def _mgr():
    return PropFirmManager()


def test_funded_pre_ft1_no_floor_except_topstep():
    m = _mgr()
    assert m.get_breach_floor("Funded Next", "Funded", after_funded_trade1=False) is None
    assert m.get_breach_floor("Tradeify", "Funded", after_funded_trade1=False) is None
    assert m.get_breach_floor("MFFU_Flex", "Funded", after_funded_trade1=False) is None
    assert m.get_breach_floor("TopStep", "Funded", after_funded_trade1=False) is None
    assert m.get_breach_floor("TopStep 50K XFA", "Funded", after_funded_trade1=False) is None


def test_funded_post_ft1_floors():
    m = _mgr()
    cases = {
        "MFFU_Flex": -2000.0,
        "MFFU Builder 50K": -2000.0,
        "MFFU Rapid EOD": -2000.0,
        "MFFU": -2000.0,
        "Funded Next Flex": 48500.0,
        "Funded Next": 48000.0,
        "TradeDay": 48000.0,
        "Tradeify": 48000.0,
        "Tradeify Select": 48000.0,
        "Lucid": 48000.0,
        "LucidMaxx": 48000.0,
        "AlphaFutures": 48000.0,
        "Apex": 48000.0,
        "FTMO Futures Pro": 48000.0,
        "Top One Futures": 48000.0,
        "Blue Guardian Reserve": 48000.0,
        "FundedNext Rapid Daily": 48000.0,
        "TopStep": -2000.0,
    }
    for firm, expected in cases.items():
        got = m.get_breach_floor(firm, "Funded", after_funded_trade1=True)
        assert got == expected, f"{firm}: {got} != {expected}"


def test_challenge_unchanged_default():
    m = _mgr()
    assert m.get_breach_floor("Funded Next", "Challenge") == 48000.0


def test_funded_post_ft2_ceilings():
    m = _mgr()
    assert m.get_breach_floor(
        "MFFU_Flex", "Funded", after_funded_trade1=True, after_funded_trade2=True
    ) == 100.0
    assert m.get_breach_floor(
        "TopStep", "Funded", after_funded_trade1=True, after_funded_trade2=True
    ) == 0.0
    assert m.get_breach_floor(
        "Tradeify", "Funded", after_funded_trade1=True, after_funded_trade2=True
    ) == 50100.0
    assert m.get_ft2_breach_ceiling("AlphaFutures") == 50000.0
    assert m.get_ft2_breach_ceiling("TradeDay") == 50100.0
    assert m.get_breach_floor(
        "Funded Next Flex", "Funded", after_funded_trade1=True, after_funded_trade2=True
    ) == 50100.0
    assert m.breach_uses_at_or_below("Funded", after_funded_trade2=True) is True
    assert m.breach_uses_at_or_below("Funded", after_funded_trade2=False) is False
