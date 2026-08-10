import unittest
from datetime import datetime

from research.eat_time import has_day_placeholder_for_weekday, next_trading_weekday
from trader_companion.trader_app import TradeOpssAIApp


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


class TraderAppPlaceholderRegressionTests(unittest.TestCase):
    def setUp(self):
        self.app = TradeOpssAIApp.__new__(TradeOpssAIApp)

    def test_rows_without_any_day_placeholder_are_not_active(self):
        ev = {"Account #": "123456", "Prop Day 1": "", "Hedge Result 1": "$100.00"}
        self.assertFalse(self.app._has_placeholder_for_weekday(ev, 1))

    def test_missed_previous_day_placeholder_is_still_tradeable(self):
        ev = {"Account #": "123456", "Hedge Result 1": "MON"}
        self.assertTrue(self.app._has_placeholder_for_weekday(ev, 2))

    def test_future_only_placeholder_is_not_active(self):
        ev = {"Account #": "123456", "Hedge Result 1": "FRI"}
        self.assertFalse(self.app._has_placeholder_for_weekday(ev, 1))

    def test_farming_account_detected_on_monday(self):
        """Farming account with MON placeholder should be active on Monday."""
        ev = {
            "Account #": "123456",
            "Prop Day 1": "$50.00",
            "Hedge Day 1": "MON",
            "Hedge Day 2": "",
        }
        self.assertTrue(self.app._has_placeholder_for_weekday(ev, 0))

    def test_farming_account_detected_on_thursday(self):
        """Farming account with THU placeholder in later cell should be active on Thursday."""
        ev = {
            "Account #": "123456",
            "Prop Day 1": "$50.00",
            "Hedge Day 1": "$100.00",
            "Hedge Day 2": "$75.00",
            "Hedge Day 3": "$80.00",
            "Hedge Day 4": "THU",
            "Hedge Day 5": "",
        }
        self.assertTrue(self.app._has_placeholder_for_weekday(ev, 3))

    def test_farming_account_with_only_filled_days_is_not_active(self):
        """Farming account with no placeholders (all filled) should not be active."""
        ev = {
            "Account #": "123456",
            "Prop Day 1": "$50.00",
            "Hedge Day 1": "$100.00",
            "Hedge Day 2": "$75.00",
            "Hedge Day 3": "$80.00",
            "Hedge Day 4": "",
        }
        self.assertFalse(self.app._has_placeholder_for_weekday(ev, 3))

    def test_farming_account_with_future_placeholder_on_thursday(self):
        """Farming account with only FRI placeholder should not be active on Thursday."""
        ev = {
            "Account #": "123456",
            "Prop Day 1": "$50.00",
            "Hedge Day 1": "$100.00",
            "Hedge Day 2": "$75.00",
            "Hedge Day 3": "FRI",
            "Hedge Day 4": "",
        }
        self.assertFalse(self.app._has_placeholder_for_weekday(ev, 3))

    def test_farming_account_with_funded_acct_detected_on_thursday(self):
        """Farming with Account #.1 and THU placeholder should be active on Thursday."""
        ev = {
            "Account #": "123456",
            "Account #.1": "789012",
            "Prop Day 1": "$50.00",
            "Hedge Day 1": "$100.00",
            "Hedge Day 2": "$75.00",
            "Hedge Day 3": "$80.00",
            "Hedge Day 4": "THU",
            "Hedge Day 5": "",
        }
        self.assertTrue(self.app._has_placeholder_for_weekday(ev, 3))

    def test_farming_account_with_placeholder_in_later_cell(self):
        """Farming account with placeholder in Hedge Day 25 (later cell) should be detected."""
        ev = {
            "Account #": "123456",
            "Prop Day 1": "$50.00",
        }
        # Fill first 24 cells with dollar amounts
        for i in range(1, 25):
            ev[f"Hedge Day {i}"] = f"${100 + i}.00"
        # Put Thursday placeholder in cell 25
        ev["Hedge Day 25"] = "THU"
        ev["Hedge Day 26"] = ""
        self.assertTrue(self.app._has_placeholder_for_weekday(ev, 3))


if __name__ == "__main__":
    unittest.main(verbosity=2)
