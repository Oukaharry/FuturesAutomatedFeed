import unittest
from datetime import datetime

from research.eat_time import has_day_placeholder_for_weekday, next_trading_weekday


class NextTradingWeekdayTests(unittest.TestCase):
    def test_placeholder_matches_current_weekday(self):
        ev = {"Hedge Result 1": "FRI"}
        self.assertTrue(has_day_placeholder_for_weekday(ev, 4))

    def test_placeholder_rejects_other_weekday(self):
        ev = {"Hedge Result 1": "MON"}
        self.assertFalse(has_day_placeholder_for_weekday(ev, 4))

    def test_placeholder_filter_leaves_non_placeholder_rows_alone(self):
        ev = {"Hedge Result 1": "$0.00"}
        self.assertTrue(has_day_placeholder_for_weekday(ev, 4))

    def test_friday_rolls_to_monday(self):
        self.assertEqual(next_trading_weekday(datetime(2026, 6, 12)), 0)

    def test_weekend_rolls_to_monday(self):
        self.assertEqual(next_trading_weekday(datetime(2026, 6, 13)), 0)
        self.assertEqual(next_trading_weekday(datetime(2026, 6, 14)), 0)

    def test_weekday_rolls_to_next_day(self):
        self.assertEqual(next_trading_weekday(datetime(2026, 6, 8)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
