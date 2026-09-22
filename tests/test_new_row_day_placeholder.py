from datetime import datetime, timedelta, timezone

from dashboard.app import _new_row_day_placeholder, _seed_new_row_day_placeholder


EAT = timezone(timedelta(hours=3))


def _eat(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=EAT)


# 2026-09-22 is a Tuesday.
def test_morning_row_trades_the_same_day():
    assert _new_row_day_placeholder(_eat(2026, 9, 22, 9)) == "TUESDAY"


def test_one_am_is_still_the_same_day():
    assert _new_row_day_placeholder(_eat(2026, 9, 22, 1)) == "TUESDAY"


def test_just_before_the_cutoff_is_still_the_same_day():
    assert _new_row_day_placeholder(_eat(2026, 9, 22, 16, 59)) == "TUESDAY"


def test_the_cutoff_itself_queues_the_next_day():
    assert _new_row_day_placeholder(_eat(2026, 9, 22, 17)) == "WEDNESDAY"


def test_late_evening_queues_the_next_day():
    assert _new_row_day_placeholder(_eat(2026, 9, 22, 23, 30)) == "WEDNESDAY"


def test_after_midnight_belongs_to_the_day_it_rolled_into():
    # 00:30 Wednesday is the tail of Tuesday's 17:00-01:00 block, so the next
    # tradeable session is Wednesday itself — not Thursday.
    assert _new_row_day_placeholder(_eat(2026, 9, 23, 0, 30)) == "WEDNESDAY"


def test_friday_evening_rolls_over_the_weekend():
    assert _new_row_day_placeholder(_eat(2026, 9, 25, 18)) == "MONDAY"


def test_saturday_rolls_to_monday():
    assert _new_row_day_placeholder(_eat(2026, 9, 26, 10)) == "MONDAY"


def test_sunday_evening_rolls_to_monday():
    assert _new_row_day_placeholder(_eat(2026, 9, 27, 20)) == "MONDAY"


def test_new_not_started_row_is_seeded():
    row = {"Status P1": "Not Started"}

    _seed_new_row_day_placeholder(row, _eat(2026, 9, 22, 9))

    assert row["Hedge Result 1"] == "TUESDAY"


def test_dash_placeholder_counts_as_empty():
    row = {"Status P1": "Not Started", "Hedge Result 1": "—"}

    _seed_new_row_day_placeholder(row, _eat(2026, 9, 22, 9))

    assert row["Hedge Result 1"] == "TUESDAY"


def test_row_that_already_traded_is_left_alone():
    row = {"Status P1": "Not Started", "Hedge Result 1": "$0.00"}

    _seed_new_row_day_placeholder(row, _eat(2026, 9, 22, 9))

    assert row["Hedge Result 1"] == "$0.00"


def test_row_that_is_not_started_by_status_is_left_alone():
    row = {"Status P1": "In Progress"}

    _seed_new_row_day_placeholder(row, _eat(2026, 9, 22, 9))

    assert "Hedge Result 1" not in row


def test_status_casing_does_not_matter():
    row = {"Status P1": "not started"}

    _seed_new_row_day_placeholder(row, _eat(2026, 9, 22, 9))

    assert row["Hedge Result 1"] == "TUESDAY"
