from trader_companion.trader_app import TradeOpssAIApp, kenya_today
from trader_companion.prop_firm_manager import PropFirmManager

FIRM = "MFFU Builder 50K"
ACCOUNT = "MFFU-BUILDER-1"


class _FakeAccount:
    def __init__(self, history):
        self._history = history

    def get_trade_history(self):
        return self._history


def _app(daily_pnl=None):
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    app.log = lambda *a, **k: None
    app._ai_trace = lambda *a, **k: None
    if daily_pnl is not None:
        app._broker_connections = {
            "Fake": {"account": _FakeAccount(
                [{"account_name": ACCOUNT, "daily_pnl": daily_pnl}]
            )}
        }
    return app


def _today():
    return kenya_today().strftime("%Y-%m-%d")


def _evaluation():
    return {"Account #": ACCOUNT, "Account #.1": ACCOUNT}


def _day(net_pnl, trades=1, date=None):
    return [{"date": date or _today(), "trades": trades, "net_pnl": net_pnl}]


# --- state machine data -------------------------------------------------


def test_state_machine_branches_win_and_loss_to_different_phases():
    mgr = PropFirmManager()
    assert mgr.resolve_next_phase_key(FIRM, "funded_trade1", "win") == "funded_trade2"
    assert mgr.resolve_next_phase_key(FIRM, "funded_trade1", "loss") == "funded_recovery1"


def test_mffu_transitions_match_the_blueprint():
    # Transcribed from the MFFU Builder 50K blueprint, not inferred.
    mgr = PropFirmManager()
    expected = {
        ("funded_trade2", "win"): "cycle_trade_a",
        ("funded_trade2", "loss"): "funded_trade3",
        ("funded_trade3", "win"): "finishing_trade",
        ("funded_trade3", "loss"): "account_blown",
        ("funded_recovery1", "win"): "funded_recovery2",
        ("funded_recovery1", "loss"): "account_blown",
        ("funded_recovery2", "win"): "finishing_trade",
        ("funded_recovery2", "loss"): "funded_recovery3",
        ("funded_recovery3", "win"): "rebuild_trade",
        ("funded_recovery3", "loss"): "account_blown",
        ("finishing_trade", "win"): "cycle_trade_a",
        ("finishing_trade", "loss"): "rebuild_trade",
        ("rebuild_trade", "win"): "cycle_trade_a",
        ("rebuild_trade", "loss"): "rebuild_trade2",
        ("rebuild_trade2", "win"): "finishing_trade",
        ("rebuild_trade2", "loss"): "account_blown",
        ("cycle_trade_a", "win"): "cycle_trade_b",
        ("cycle_trade_a", "loss"): "cycle_recovery",
        ("cycle_trade_b", "win"): "cycle_trade_a",
        ("cycle_trade_b", "loss"): "cycle_trade_a",
        ("cycle_recovery", "win"): "cycle_trade_a",
        ("cycle_recovery", "loss"): "account_blown",
    }
    for (key, outcome), nxt in expected.items():
        assert mgr.resolve_next_phase_key(FIRM, key, outcome) == nxt, key


def test_ftmo_recovery_leads_to_cleanup_and_both_legs_repeat():
    mgr = PropFirmManager()
    f = "FTMO Futures Pro"
    assert mgr.resolve_next_phase_key(f, "funded_trade1_recovery", "win") == "funded_trade1_cleanup"
    assert mgr.resolve_next_phase_key(f, "funded_trade1_recovery", "loss") == "funded_trade1_recovery"
    assert mgr.resolve_next_phase_key(f, "funded_trade1_cleanup", "loss") == "funded_trade1_cleanup"


def test_failed_recovery_is_terminal():
    mgr = PropFirmManager()
    assert mgr.resolve_next_phase_key(FIRM, "challenge_recovery", "loss") == "evaluation_failed"
    assert mgr.is_terminal_phase_key("evaluation_failed")
    assert mgr.is_terminal_phase_key("account_blown")
    assert not mgr.is_terminal_phase_key("funded_trade2")


def test_firms_without_a_state_machine_return_none():
    mgr = PropFirmManager()
    assert mgr.resolve_next_phase_key("Lucid", "funded_trade1", "win") is None


def test_unknown_outcome_never_resolves_a_branch():
    mgr = PropFirmManager()
    assert mgr.resolve_next_phase_key(FIRM, "funded_trade1", "pending") is None
    assert mgr.resolve_next_phase_key(FIRM, "funded_trade1", "") is None


# --- outcome detection --------------------------------------------------


def test_profitable_day_is_a_win_and_losing_day_is_a_loss():
    assert _app(_day(412.50))._resolve_trade_outcome(ACCOUNT) == "win"
    assert _app(_day(-1000.0))._resolve_trade_outcome(ACCOUNT) == "loss"


def test_day_with_no_closed_trade_is_unresolved():
    # Order filled but brackets not hit yet — must not guess a branch.
    assert _app(_day(0.0, trades=0))._resolve_trade_outcome(ACCOUNT) is None


def test_payout_withdrawal_day_is_not_reported_as_a_loss():
    # A withdrawal carries a non-trade cashChangeType, so it never reaches
    # net_pnl and leaves the day with zero closed trades.
    assert _app(_day(0.0, trades=0))._resolve_trade_outcome(ACCOUNT) is None


def test_missing_history_is_unresolved():
    assert _app([])._resolve_trade_outcome(ACCOUNT) is None
    assert _app(_day(100.0))._resolve_trade_outcome("unknown-account") is None


def test_outcome_lookup_without_broker_connections_is_safe():
    assert _app()._resolve_trade_outcome(ACCOUNT) is None


# --- wiring into next-trade selection -----------------------------------


def test_winning_funded_trade_advances_to_the_next_build_trade():
    app = _app(_day(412.50))
    assert app._resolve_next_hedge_field(
        _evaluation(), FIRM, "Funded", "Hedge Result 1.1"
    ) == "Hedge Result 2.1"


def test_losing_funded_trade_diverts_to_recovery_instead_of_the_next_build():
    # funded_recovery1 sits at index 3 of the funded order → Hedge Result 4.1.
    # Positional ordering would have returned Hedge Result 2.1 here.
    app = _app(_day(-1000.0))
    assert app._resolve_next_hedge_field(
        _evaluation(), FIRM, "Funded", "Hedge Result 1.1"
    ) == "Hedge Result 4.1"


def test_unresolved_trade_falls_back_to_positional_order():
    app = _app(_day(0.0, trades=0))
    assert app._resolve_next_hedge_field(
        _evaluation(), FIRM, "Funded", "Hedge Result 1.1"
    ) == "Hedge Result 2.1"


def test_winning_recovery_advances_down_the_recovery_chain():
    # Blueprint: Funded Recovery 1 TP → Funded Recovery 2 (index 4).
    app = _app(_day(412.50))
    assert app._resolve_next_hedge_field(
        _evaluation(), FIRM, "Funded", "Hedge Result 4.1"
    ) == "Hedge Result 5.1"


def test_terminal_outcome_queues_no_further_trade():
    app = _app(_day(-1000.0))
    assert app._resolve_next_hedge_field(
        _evaluation(), FIRM, "Funded", "Hedge Result 4.1"
    ) is None


def test_standard_firms_keep_positional_behaviour_on_a_loss():
    app = _app(_day(-500.0))
    assert app._resolve_next_hedge_field(
        {"Account #": ACCOUNT}, "MFFU Rapid EOD", "Challenge", "Hedge Result 4"
    ) == "Hedge Result 1.1"


# --- FTMO Futures Pro ---------------------------------------------------


def test_ftmo_losing_build_routes_to_recovery_not_a_qualifying_day():
    # Regression: the farming branch used to queue Hedge Day 1 on any funded
    # entry, so a losing build trade skipped its recovery leg entirely.
    app = _app(_day(-475.0))
    assert app._resolve_next_hedge_field(
        _evaluation(), "FTMO Futures Pro", "Funded", "Hedge Result 1.1"
    ) == "Hedge Result 2.1"


def test_ftmo_winning_build_still_earns_a_qualifying_day():
    app = _app(_day(3005.0))
    assert app._resolve_next_hedge_field(
        _evaluation(), "FTMO Futures Pro", "Funded", "Hedge Result 1.1"
    ) == "Hedge Day 1"


def test_ftmo_losing_recovery_repeats_the_same_leg():
    # Blueprint: 1R repeats once before the account dies.
    app = _app(_day(-475.0))
    assert app._resolve_next_hedge_field(
        _evaluation(), "FTMO Futures Pro", "Funded", "Hedge Result 2.1"
    ) == "Hedge Result 2.1"


def test_ftmo_winning_recovery_moves_to_cleanup():
    app = _app(_day(3005.0))
    assert app._resolve_next_hedge_field(
        _evaluation(), "FTMO Futures Pro", "Funded", "Hedge Result 2.1"
    ) == "Hedge Result 3.1"


def test_ftmo_losing_cleanup_recomputes_and_repeats():
    app = _app(_day(-475.0))
    assert app._resolve_next_hedge_field(
        _evaluation(), "FTMO Futures Pro", "Funded", "Hedge Result 3.1"
    ) == "Hedge Result 3.1"


# --- FundedNext Rapid Daily ---------------------------------------------


def test_rapid_daily_win_skips_the_recovery_leg():
    app = _app(_day(600.0))
    assert app._resolve_next_hedge_field(
        _evaluation(), "FundedNext Rapid Daily", "Funded", "Hedge Result 1.1"
    ) == "Hedge Result 3.1"


def test_rapid_daily_loss_takes_the_recovery_leg():
    app = _app(_day(-1000.0))
    assert app._resolve_next_hedge_field(
        _evaluation(), "FundedNext Rapid Daily", "Funded", "Hedge Result 1.1"
    ) == "Hedge Result 2.1"


def test_rapid_daily_cycle_two_has_two_recovery_legs_before_the_floor():
    app = _app(_day(-1000.0))
    # funded_trade2 → recovery1
    assert app._resolve_next_hedge_field(
        _evaluation(), "FundedNext Rapid Daily", "Funded", "Hedge Result 3.1"
    ) == "Hedge Result 4.1"
    # recovery1 → recovery2
    assert app._resolve_next_hedge_field(
        _evaluation(), "FundedNext Rapid Daily", "Funded", "Hedge Result 4.1"
    ) == "Hedge Result 5.1"
    # recovery2 → floor, nothing queued
    assert app._resolve_next_hedge_field(
        _evaluation(), "FundedNext Rapid Daily", "Funded", "Hedge Result 5.1"
    ) is None


# --- correction pass ----------------------------------------------------


def _traded_row(placeholder_field, firm=FIRM):
    return {
        "Account #": ACCOUNT,
        "Account #.1": ACCOUNT,
        "Prop Firm": firm,
        "Hedge Result 1.1": "$0.00",
        placeholder_field: "WED",
    }


def test_locate_cells_finds_the_trade_that_queued_the_placeholder():
    app = _app()
    traded, phase, placeholder = app._locate_progression_cells(
        _traded_row("Hedge Result 2.1")
    )
    assert (traded, phase, placeholder) == ("Hedge Result 1.1", "Funded", "Hedge Result 2.1")


def test_latest_resolved_outcome_ignores_days_without_a_closed_trade():
    app = _app([
        {"date": "2026-09-14", "trades": 1, "net_pnl": -1000.0},
        {"date": "2026-09-15", "trades": 0, "net_pnl": 0.0},
    ])
    assert app._latest_resolved_outcome(ACCOUNT) == ("2026-09-14", "loss")


def test_loss_moves_the_placeholder_from_the_build_slot_to_recovery():
    # Queued positionally at fill time, then the trade hit its stop.
    app = _app(_day(-1000.0))
    current, corrected = app._reconcile_outcome_placeholder(_traded_row("Hedge Result 2.1"))
    assert (current, corrected) == ("Hedge Result 2.1", "Hedge Result 4.1")


def test_correct_placeholder_is_left_alone():
    app = _app(_day(412.50))
    assert app._reconcile_outcome_placeholder(
        _traded_row("Hedge Result 2.1")
    ) == (None, None)


def test_correction_is_idempotent():
    app = _app(_day(-1000.0))
    row = _traded_row("Hedge Result 4.1")
    assert app._reconcile_outcome_placeholder(row) == (None, None)


def test_unresolved_trade_is_never_corrected():
    app = _app(_day(0.0, trades=0))
    assert app._reconcile_outcome_placeholder(
        _traded_row("Hedge Result 2.1")
    ) == (None, None)


def test_row_without_a_pending_placeholder_is_skipped():
    app = _app(_day(-1000.0))
    row = {"Account #": ACCOUNT, "Prop Firm": FIRM, "Hedge Result 1.1": "$0.00"}
    assert app._reconcile_outcome_placeholder(row) == (None, None)


def test_standard_firm_placeholders_are_never_moved():
    app = _app(_day(-500.0))
    row = _traded_row("Hedge Result 2.1", firm="Lucid")
    assert app._reconcile_outcome_placeholder(row) == (None, None)


# --- payout detection ---------------------------------------------------

# Real Tradovate Account Balance History (account FTDFYSLX50467846972).
# 2026-08-28 is a payout: balance falls 55,383.48 → 52,691.74 with zero P&L.
BALANCE_HISTORY = [
    ("2026-08-19", 55388.48, 5388.48, 1),
    ("2026-08-20", 54782.68, -605.80, 1),
    ("2026-08-21", 54932.88, 150.20, 1),
    ("2026-08-22", 54932.88, 0.00, 0),
    ("2026-08-24", 55083.08, 150.20, 1),
    ("2026-08-25", 55233.28, 150.20, 1),
    ("2026-08-26", 55383.48, 150.20, 1),
    ("2026-08-27", 55383.48, 0.00, 0),
    ("2026-08-28", 52691.74, 0.00, 0),
    ("2026-08-29", 52691.74, 0.00, 0),
    ("2026-08-31", 55080.22, 2388.48, 1),
    ("2026-09-01", 54426.42, -653.80, 1),
]


def _history(rows=None):
    return [
        {"date": d, "balance_eod": bal, "net_pnl": pnl, "trades": t}
        for d, bal, pnl, t in (rows if rows is not None else BALANCE_HISTORY)
    ]


def test_payout_is_detected_from_an_unexplained_balance_drop():
    app = _app(_history())
    assert app._detect_payouts(ACCOUNT) == [("2026-08-28", 2691.74)]


def test_losing_days_are_not_mistaken_for_payouts():
    # 08-20 (-605.80) and 09-01 (-653.80) both drop the balance, but the loss
    # fully explains the move.
    app = _app(_history())
    flagged = {d for d, _ in app._detect_payouts(ACCOUNT)}
    assert "2026-08-20" not in flagged
    assert "2026-09-01" not in flagged


def test_flat_and_winning_days_are_not_payouts():
    app = _app(_history())
    flagged = {d for d, _ in app._detect_payouts(ACCOUNT)}
    assert flagged.isdisjoint({"2026-08-22", "2026-08-27", "2026-08-31"})


def test_payouts_are_counted():
    app = _app(_history())
    assert app._payout_count(ACCOUNT) == 1


def test_a_payout_day_never_resolves_as_a_losing_trade():
    # The 08-28 withdrawal must not push the state machine down a loss branch.
    app = _app(_history())
    assert app._resolve_trade_outcome(ACCOUNT, on_date="2026-08-28") is None
    assert app._latest_resolved_outcome(ACCOUNT) == ("2026-09-01", "loss")


def test_deposits_are_not_reported_as_payouts():
    app = _app(_history([
        ("2026-09-01", 50000.00, 0.00, 0),
        ("2026-09-02", 60000.00, 0.00, 0),
    ]))
    assert app._detect_payouts(ACCOUNT) == []


def test_sub_dollar_drift_is_ignored():
    app = _app(_history([
        ("2026-09-01", 50000.00, 0.00, 0),
        ("2026-09-02", 49999.60, 0.00, 0),
    ]))
    assert app._detect_payouts(ACCOUNT) == []


def test_payout_on_a_day_that_also_traded_is_still_detected():
    app = _app(_history([
        ("2026-09-01", 54000.00, 0.00, 0),
        # +150 traded, but 2,000 withdrawn the same day.
        ("2026-09-02", 52150.00, 150.00, 1),
    ]))
    assert app._detect_payouts(ACCOUNT) == [("2026-09-02", 2000.0)]


def test_payout_target_gates_on_the_firm_rule():
    app = _app(_history())
    # MFFU Builder banks five payouts; one is not enough.
    assert app._payout_target_reached(ACCOUNT, FIRM) is False


def test_payout_target_is_false_for_firms_without_a_payout_rule():
    app = _app(_history())
    assert app._payout_target_reached(ACCOUNT, "Lucid") is False


# --- recovery preconditions ---------------------------------------------


def test_recovery_legs_declare_the_outcome_they_require():
    mgr = PropFirmManager()
    assert mgr.required_outcome_for_phase(FIRM, "funded_recovery1") == "loss"
    assert mgr.required_outcome_for_phase(FIRM, "cycle_recovery") == "loss"
    assert mgr.required_outcome_for_phase(
        "FundedNext Rapid Daily", "funded_trade2_recovery2") == "loss"
    # A build trade carries no precondition.
    assert mgr.required_outcome_for_phase(FIRM, "funded_trade1") is None


def test_recovery_is_blocked_when_the_prior_trade_won():
    # The user's rule: recovery 1 is only valid after SL1.
    app = _app(_day(412.50))
    assert app._outcome_gate_blocks(_evaluation(), FIRM, "funded_recovery1") is True


def test_recovery_is_allowed_after_a_stop_out():
    app = _app(_day(-1000.0))
    assert app._outcome_gate_blocks(_evaluation(), FIRM, "funded_recovery1") is False


def test_unverifiable_outcome_warns_but_does_not_stall_trading():
    app = _app(_day(0.0, trades=0))
    assert app._outcome_gate_blocks(_evaluation(), FIRM, "funded_recovery1") is False


def test_firms_without_gating_are_unaffected():
    app = _app(_day(412.50))
    assert app._outcome_gate_blocks(_evaluation(), "Lucid", "funded_trade2") is False


# --- derived statuses ---------------------------------------------------


def _account(balance, daily_pnl):
    app = TradeOpssAIApp.__new__(TradeOpssAIApp)
    app.prop_firm_mgr = PropFirmManager()
    app.log = lambda *a, **k: None
    app._ai_trace = lambda *a, **k: None
    app._broker_connections = {
        "Fake": {"account": _FakeAccount(
            [{"account_name": ACCOUNT, "balance": balance, "daily_pnl": daily_pnl}]
        )}
    }
    return app


def test_balance_at_the_floor_marks_the_account_failed():
    app = _account(50100.0, _day(-1000.0))
    status, reason = app._derive_account_status(_evaluation(), FIRM)
    assert status == "Fail"
    assert "floor" in reason


def test_healthy_balance_is_left_alone():
    app = _account(53000.0, _day(412.50))
    assert app._derive_account_status(_evaluation(), FIRM) == (None, None)


def test_completed_needs_every_payout_and_a_blown_account():
    # SOP 7c: not Completed until payouts are processed AND the account blows.
    rows = [
        ("2026-09-01", 54100.0, 0.0, 0), ("2026-09-02", 52100.0, 0.0, 0),
        ("2026-09-03", 54100.0, 2000.0, 1), ("2026-09-04", 52100.0, 0.0, 0),
        ("2026-09-05", 54100.0, 2000.0, 1), ("2026-09-06", 52100.0, 0.0, 0),
        ("2026-09-07", 54100.0, 2000.0, 1), ("2026-09-08", 52100.0, 0.0, 0),
        ("2026-09-09", 54100.0, 2000.0, 1), ("2026-09-10", 52100.0, 0.0, 0),
        ("2026-09-11", 50100.0, -2000.0, 1),
    ]
    history = [{"date": d, "balance_eod": b, "net_pnl": p, "trades": t}
               for d, b, p, t in rows]
    app = _account(50100.0, history)
    assert app._payout_count(ACCOUNT) == 5
    status, _ = app._derive_account_status(_evaluation(), FIRM)
    assert status == "Completed"


def test_status_is_unknown_without_broker_data():
    app = _app()
    assert app._derive_account_status(_evaluation(), FIRM) == (None, None)


# --- funded column names ------------------------------------------------

# The dashboard's funded columns: 1.1–5.1, then 6 and 7 with no ".1" suffix,
# then overflow columns 8+ rendered after the farming block.
FIXED_FUNDED_COLUMNS = [
    "Hedge Result 1.1", "Hedge Result 2.1", "Hedge Result 3.1",
    "Hedge Result 4.1", "Hedge Result 5.1", "Hedge Result 6", "Hedge Result 7",
]


def test_companion_and_server_agree_on_funded_columns():
    from dashboard.eval_status import FUNDED_HEDGE_COLS

    app = _app()
    assert app._get_phase_fields("Funded") == list(FUNDED_HEDGE_COLS)
    assert app._get_phase_fields("Double Dip") == list(FUNDED_HEDGE_COLS)


def test_fixed_funded_columns_keep_their_positions():
    # Overflow must append, never renumber the existing seven.
    app = _app()
    assert app._get_phase_fields("Funded")[:7] == FIXED_FUNDED_COLUMNS


def test_phase_scan_set_matches_the_funded_columns():
    app = _app()
    funded = dict(TradeOpssAIApp._ALL_PHASE_FIELD_SETS)["Funded"]
    assert funded == app._get_phase_fields("Funded")


def test_no_phantom_suffixed_columns_are_ever_emitted():
    app = _app()
    for phase in ("Challenge", "Funded", "Double Dip", "Farming"):
        fields = app._get_phase_fields(phase)
        assert "Hedge Result 6.1" not in fields
        assert "Hedge Result 7.1" not in fields


def test_overflow_covers_the_largest_firm():
    mgr = PropFirmManager()
    app = _app()
    widest = max(len(o.get("Funded", [])) for o in mgr._PHASE_TRADE_ORDER.values())
    assert len(app._get_phase_fields("Funded")) >= widest


def test_challenge_columns_do_not_collide_with_funded_overflow():
    app = _app()
    challenge = set(app._get_phase_fields("Challenge"))
    funded = set(app._get_phase_fields("Funded"))
    assert not (challenge & funded)


def test_late_funded_slots_route_to_real_columns():
    # Funded Recovery 2 SL → Funded Recovery 3 (index 5 → the unsuffixed
    # "Hedge Result 6", which used to be emitted as a phantom "6.1").
    app = _app(_day(-1000.0))
    assert app._resolve_next_hedge_field(
        _evaluation(), FIRM, "Funded", "Hedge Result 5.1"
    ) == "Hedge Result 6"

    # Funded Recovery 3 TP → Rebuild Trade (index 7).
    app = _app(_day(412.50))
    assert app._resolve_next_hedge_field(
        _evaluation(), FIRM, "Funded", "Hedge Result 6"
    ) == "Hedge Result 8"


def test_trades_past_the_seventh_reach_overflow_columns():
    # Finishing Trade sits at index 6 ("Hedge Result 7"); both branches land
    # in overflow columns that were unreachable before.
    app = _app(_day(412.50))
    assert app._resolve_next_hedge_field(
        _evaluation(), FIRM, "Funded", "Hedge Result 7"
    ) == "Hedge Result 10"  # payout banked → Cycle Trade A

    app = _app(_day(-1000.0))
    assert app._resolve_next_hedge_field(
        _evaluation(), FIRM, "Funded", "Hedge Result 7"
    ) == "Hedge Result 8"  # → Rebuild Trade
