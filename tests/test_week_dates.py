import unittest
from datetime import date, datetime

from week_dates import (
    SAST,
    activity_date_for_day,
    candidate_week_keys,
    current_week_key,
    format_week_label,
    normalise_new_activity_date,
    sast_today,
    validate_campaign_date_range,
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


class CampaignDateRangeTests(unittest.TestCase):
    """Duration is an INCLUSIVE calendar-date count: both start_date and
    end_date are counted, i.e. duration_days = (end - start).days + 1. A
    same-day campaign is 1 day, not 0."""

    def test_same_start_and_end_date_is_1_day_and_accepted(self):
        start, end = validate_campaign_date_range("2026-09-01", "2026-09-01")
        self.assertEqual(start, date(2026, 9, 1))
        self.assertEqual(end, date(2026, 9, 1))
        self.assertEqual((end - start).days + 1, 1)

    def test_2026_09_01_to_2026_10_12_is_exactly_42_inclusive_days_and_accepted(self):
        start, end = validate_campaign_date_range("2026-09-01", "2026-10-12")
        self.assertEqual((end - start).days + 1, 42)

    def test_2026_09_01_to_2026_10_13_is_43_inclusive_days_and_rejected(self):
        # One calendar day more than the 42-day maximum.
        with self.assertRaises(ValueError):
            validate_campaign_date_range("2026-09-01", "2026-10-13")

    def test_end_before_start_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_campaign_date_range("2026-09-14", "2026-09-13")

    def test_missing_start_date_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_campaign_date_range("", "2026-09-14")
        with self.assertRaises(ValueError):
            validate_campaign_date_range(None, "2026-09-14")

    def test_missing_end_date_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_campaign_date_range("2026-09-14", "")
        with self.assertRaises(ValueError):
            validate_campaign_date_range("2026-09-14", None)

    def test_malformed_date_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_campaign_date_range("2026-13-01", "2026-09-14")
        with self.assertRaises(ValueError):
            validate_campaign_date_range("2026-09-14", "not-a-date")

    def test_sast_today_matches_existing_sast_anchor_logic(self):
        # Sunday 30 Aug 2026 23:59 SAST is still 30 Aug in SAST, same anchor
        # date test_week_dates already relies on for current_week_key.
        now = datetime(2026, 8, 30, 23, 59, tzinfo=SAST)
        self.assertEqual(sast_today(now), date(2026, 8, 30))


if __name__ == "__main__":
    unittest.main()
