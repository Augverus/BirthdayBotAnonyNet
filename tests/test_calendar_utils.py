"""Tests for Jalali calendar helpers, including the Esfand 30 rule."""
import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import jdatetime

import calendar_utils as cal


class CalendarTestCase(unittest.TestCase):
    def test_jalali_anchor_is_sane(self):
        # Guards the assumption that the installed jdatetime maps Nowruz 1403
        # to 20 March 2024; every other expectation below depends on it.
        self.assertEqual(
            jdatetime.date.fromgregorian(date=date(2024, 3, 20)),
            jdatetime.date(1403, 1, 1),
        )

    def test_valid_birthday_bounds(self):
        self.assertTrue(cal.valid_birthday(1, 31))
        self.assertTrue(cal.valid_birthday(6, 31))
        self.assertFalse(cal.valid_birthday(7, 31))
        self.assertTrue(cal.valid_birthday(7, 30))
        self.assertTrue(cal.valid_birthday(11, 30))
        self.assertTrue(cal.valid_birthday(12, 30))
        self.assertFalse(cal.valid_birthday(12, 31))
        self.assertFalse(cal.valid_birthday(0, 1))
        self.assertFalse(cal.valid_birthday(1, 0))

    def test_days_in_month_fixed_months(self):
        self.assertEqual(cal.days_in_month(1), 31)
        self.assertEqual(cal.days_in_month(6), 31)
        self.assertEqual(cal.days_in_month(7), 30)
        self.assertEqual(cal.days_in_month(11), 30)

    def test_days_in_month_rejects_invalid_month(self):
        with self.assertRaises(ValueError):
            cal.days_in_month(13)
        with self.assertRaises(ValueError):
            cal.days_in_month(0)

    def test_days_in_month_esfand_follows_current_year(self):
        with patch.object(cal, 'local_now', return_value=datetime(2024, 6, 1)):
            self.assertEqual(cal.days_in_month(12), 30)  # 1403 is a leap year
        with patch.object(cal, 'local_now', return_value=datetime(2023, 6, 1)):
            self.assertEqual(cal.days_in_month(12), 29)  # 1402 is not

    def test_occurrence_moves_esfand_30_to_29_when_target_year_is_not_leap(self):
        self.assertEqual(
            jdatetime.date.fromgregorian(date=cal.occurrence(1402, 12, 30)),
            jdatetime.date(1402, 12, 29),
        )
        self.assertEqual(
            jdatetime.date.fromgregorian(date=cal.occurrence(1403, 12, 30)),
            jdatetime.date(1403, 12, 30),
        )

    def test_today_and_remaining_on_the_birthday(self):
        # 1 June 2024 is Jalali 1403-03-12.
        with patch.object(cal, 'local_now', return_value=datetime(2024, 6, 1, 12, 0)):
            self.assertEqual(cal.today(), jdatetime.date(1403, 3, 12))
            self.assertEqual(cal.remaining(3, 12), 0)
            self.assertEqual(cal.remaining(3, 13), 1)
            self.assertEqual(cal.elapsed(3, 12), 0)
            self.assertEqual(cal.elapsed(3, 11), 1)

    def test_remaining_rolls_over_to_next_year(self):
        with patch.object(cal, 'local_now', return_value=datetime(2024, 6, 1, 12, 0)):
            self.assertGreater(cal.remaining(3, 11), 300)

    def test_birthday_text(self):
        self.assertEqual(cal.birthday_text(1, 5), '5 فروردین')
        self.assertEqual(cal.birthday_text(12, 29), '29 اسفند')

    def test_stat_boundaries_use_local_midnight_and_rolling_week(self):
        # local_now() is timezone-aware in production; keep that contract here.
        now = datetime(2024, 6, 1, 15, 30, tzinfo=ZoneInfo('Asia/Tehran'))
        with patch.object(cal, 'local_now', return_value=now):
            today, week = cal.stat_boundaries()
        self.assertEqual(today, '2024-05-31T20:30:00+00:00')  # local midnight in UTC
        self.assertEqual(week, '2024-05-25T12:00:00+00:00')  # now minus 7 days, same clock time
        self.assertLess(
            (datetime.fromisoformat(today) - datetime.fromisoformat(week)).total_seconds(),
            7 * 86400,
        )


if __name__ == '__main__':
    unittest.main()
