import unittest
from datetime import datetime

from week_dates import (
    SAST,
    activity_date_for_day,
    candidate_week_keys,
    current_week_key,
    format_week_label,
    normalise_new_activity_date,
    validate_candidate_week_key,
)


class WeekDateTests(unittest.TestCase):
    def test_sunday_30_aug_2359_sast_is_24_to_30_aug_reporting_week(self):
        now = datetime(2026, 8, 30, 23, 59, tzinfo=SAST)
        self.assertEqual(current_week_key(now), "2026-08-23")
        self.assertEqual(format_week_label(current_week_key(now)), "24 Aug - 30 Aug")

    def test_monday_31_aug_0001_sast_is_31_aug_to_6_sep_reporting_week(self):
        now = datetime(2026, 8, 31, 0, 1, tzinfo=SAST)
        self.assertEqual(current_week_key(now), "2026-08-30")
        self.assertEqual(format_week_label(current_week_key(now)), "31 Aug - 6 Sep")

    def test_sunday_anchor_day_offsets(self):
        self.assertEqual(activity_date_for_day("2026-08-23", "sun"), "2026-08-30")
        self.assertEqual(activity_date_for_day("2026-08-30", "mon"), "2026-08-31")
        self.assertEqual(activity_date_for_day("2026-08-30", "sun"), "2026-09-06")

    def test_new_activity_date_is_derived_or_strictly_validated(self):
        self.assertEqual(
            normalise_new_activity_date("2026-08-30", "mon"), "2026-08-31"
        )
        self.assertEqual(
            normalise_new_activity_date("2026-08-30", "mon", "2026-08-31"),
            "2026-08-31",
        )
        with self.assertRaises(ValueError):
            normalise_new_activity_date("2026-08-30", "mon", "2026-08-30")
        with self.assertRaises(ValueError):
            normalise_new_activity_date("2026-08-30", "monday")
        with self.assertRaises(ValueError):
            normalise_new_activity_date("2026-02-30", "mon")

    def test_candidate_writes_allow_only_current_and_next_week(self):
        now = datetime(2026, 8, 30, 23, 59, tzinfo=SAST)
        current, next_week = candidate_week_keys(now)
        self.assertEqual(validate_candidate_week_key(current, now), current)
        self.assertEqual(validate_candidate_week_key(next_week, now), next_week)
        with self.assertRaises(ValueError):
            validate_candidate_week_key("2026-08-16", now)

    def test_historical_week_remains_readable(self):
        self.assertEqual(format_week_label("2026-08-23"), "24 Aug - 30 Aug")

    def test_legacy_records_without_activity_date_remain_supported(self):
        entries = [
            {"week_key": "2026-08-23", "day": "sun"},
            {"week_key": "2026-08-30", "day": "mon"},
            {"week_key": "2026-08-30", "day": "sun"},
        ]

        self.assertEqual(activity_date_for_day(entries[0]["week_key"], entries[0]["day"]), "2026-08-30")
        self.assertEqual(activity_date_for_day(entries[1]["week_key"], entries[1]["day"]), "2026-08-31")
        self.assertEqual(activity_date_for_day(entries[2]["week_key"], entries[2]["day"]), "2026-09-06")
        self.assertTrue(all("activity_date" not in entry for entry in entries))


if __name__ == "__main__":
    unittest.main()
