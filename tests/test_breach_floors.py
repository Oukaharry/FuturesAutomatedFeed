from trader_companion.prop_firm_manager import PropFirmManager


def test_funded_floors_come_from_the_hard_stop_table():
    mgr = PropFirmManager()

    assert mgr.get_breach_floor("Funded Next", "Funded") == 50000.0
    assert mgr.get_breach_floor("Funded Next Flex", "Funded") == 48500.0
    assert mgr.get_breach_floor("TradeDay", "Funded") == 50000.0
    assert mgr.get_breach_floor("Tradeify", "Funded") == 50000.0
    assert mgr.get_breach_floor("Tradeify Select", "Funded") == 50100.0
    assert mgr.get_breach_floor("Blue Guardian Reserve", "Funded") == 50100.0
    assert mgr.get_breach_floor("FTMO Futures Pro", "Funded") == 50000.0
    assert mgr.get_breach_floor("FundedNext Rapid Daily", "Funded") == 50100.0
    assert mgr.get_breach_floor("AlphaFutures", "Funded") == 50000.0
    assert mgr.get_breach_floor("Apex", "Funded") == 50000.0
    assert mgr.get_breach_floor("Lucid", "Funded") == 50000.0
    assert mgr.get_breach_floor("Top One Futures", "Funded") == 50000.0
    assert mgr.get_breach_floor("Funded Futures Family", "Funded") == 48000.0


def test_a_zero_hard_stop_is_a_real_floor_not_a_missing_one():
    # TopStep funded starts at $0, so it can never breach on balance alone.
    # Treating 0.0 as absent would default it to 50,100 and fail every account.
    mgr = PropFirmManager()

    assert mgr.get_breach_floor("TopStep", "Funded") == 0.0
    assert mgr.get_breach_floor("TopStep RTP", "Funded") == 0.0


def test_firms_absent_from_the_table_fall_back_to_their_blueprint_rule():
    mgr = PropFirmManager()

    assert mgr.get_breach_floor("MFFU Builder 50K", "Funded") == 50100.0


def test_challenge_floor_is_the_house_value():
    mgr = PropFirmManager()

    for firm in ("Tradeify", "TopStep", "Apex", "FundedNext Rapid Daily"):
        assert mgr.get_breach_floor(firm, "Challenge") == 48000.0


def test_unknown_firm_falls_back_to_the_house_floors():
    mgr = PropFirmManager()

    assert mgr.get_breach_floor("Not A Firm", "Challenge") == 48000.0
    assert mgr.get_breach_floor("Not A Firm", "Funded") == 50100.0


def test_phase_defaults_to_funded():
    mgr = PropFirmManager()

    assert mgr.get_breach_floor("Tradeify") == 50000.0


def test_breach_floor_is_independent_of_the_sl_sizing_lock_level():
    # get_lock_level is hardcoded (TopStep 0, MFFU 100, else 50,000) and sizes
    # funded stops; the breach floor is the hard stop. They deliberately differ.
    mgr = PropFirmManager()

    assert mgr.get_breach_floor("Funded Next Flex", "Funded") == 48500.0
    assert mgr.get_lock_level("Funded Next Flex") == 50000.0
