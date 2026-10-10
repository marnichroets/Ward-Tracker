import unittest
from datetime import date, datetime, timezone

from week_dates import (
    SAST,
    activity_date_for_day,
    candidate_week_keys,
    current_month_key,
    current_week_key,
    format_week_label,
    format_week_range_with_year,
    is_saturday,
    month_bounds,
    month_label,
    next_month_key,
    normalise_new_activity_date,
    previous_month_key,
    sast_today,
    validate_campaign_activity_date,
    validate_campaign_date_range,
    validate_candidate_week_key,
    validate_month_key,
    week_key_and_day_for_date,
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
    end_date are counted, i.e. duration_days = (end - start).days + 1."""

    def test_same_start_and_end_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least 7 days"):
            validate_campaign_date_range("2026-09-01", "2026-09-01")

    def test_seven_inclusive_days_is_accepted(self):
        start, end = validate_campaign_date_range("2026-09-01", "2026-09-07")
        self.assertEqual(start, date(2026, 9, 1))
        self.assertEqual(end, date(2026, 9, 7))
        self.assertEqual((end - start).days + 1, 7)

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


class WeekKeyAndDayForDateTests(unittest.TestCase):
    def test_matches_forward_derivation_for_every_day_of_a_week(self):
        # activity_date_for_day is the tested forward direction; round-trip
        # every day of an arbitrary week through it and back.
        week_key = "2026-09-13"  # Sunday anchor -> Mon 2026-09-14 .. Sun 2026-09-20
        for day in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]:
            d = date.fromisoformat(activity_date_for_day(week_key, day))
            derived_week_key, derived_day = week_key_and_day_for_date(d)
            self.assertEqual(derived_week_key, week_key)
            self.assertEqual(derived_day, day)

    def test_known_date(self):
        # 2026-09-14 is a Monday; its week's Sunday anchor is 2026-09-13.
        self.assertEqual(week_key_and_day_for_date(date(2026, 9, 14)), ("2026-09-13", "mon"))
        self.assertEqual(week_key_and_day_for_date(date(2026, 9, 20)), ("2026-09-13", "sun"))

    def test_month_boundary(self):
        # 2026-09-30 is a Wednesday.
        week_key, day = week_key_and_day_for_date(date(2026, 9, 30))
        self.assertEqual(day, "wed")
        self.assertEqual(activity_date_for_day(week_key, "wed"), "2026-09-30")


class ValidateCampaignActivityDateTests(unittest.TestCase):
    def test_date_within_range_accepted(self):
        d = validate_campaign_activity_date("2026-09-14", "2026-10-04", "2026-09-20")
        self.assertEqual(d, date(2026, 9, 20))

    def test_date_equal_to_start_or_end_accepted(self):
        self.assertEqual(
            validate_campaign_activity_date("2026-09-14", "2026-10-04", "2026-09-14"),
            date(2026, 9, 14),
        )
        self.assertEqual(
            validate_campaign_activity_date("2026-09-14", "2026-10-04", "2026-10-04"),
            date(2026, 10, 4),
        )

    def test_date_before_campaign_start_rejected(self):
        with self.assertRaises(ValueError):
            validate_campaign_activity_date("2026-09-14", "2026-10-04", "2026-09-13")

    def test_date_after_campaign_end_rejected(self):
        with self.assertRaises(ValueError):
            validate_campaign_activity_date("2026-09-14", "2026-10-04", "2026-10-05")

    def test_malformed_date_rejected(self):
        with self.assertRaises(ValueError):
            validate_campaign_activity_date("2026-09-14", "2026-10-04", "not-a-date")

    def test_independent_of_candidate_week_window(self):
        # A date far outside "this week or next week" must still be accepted
        # here, because this validator has nothing to do with
        # validate_candidate_week_key.
        d = validate_campaign_activity_date("2020-01-01", "2020-02-11", "2020-01-15")
        self.assertEqual(d, date(2020, 1, 15))


class MonthKeyTests(unittest.TestCase):
    def test_current_month_key_uses_sast_date(self):
        self.assertEqual(current_month_key(datetime(2026, 9, 1, 0, 30, tzinfo=SAST)), "2026-09")

    def test_month_bounds_ordinary_month(self):
        self.assertEqual(month_bounds("2026-09"), (date(2026, 9, 1), date(2026, 9, 30)))

    def test_month_bounds_february_non_leap_year(self):
        self.assertEqual(month_bounds("2026-02"), (date(2026, 2, 1), date(2026, 2, 28)))

    def test_month_bounds_february_leap_year(self):
        self.assertEqual(month_bounds("2028-02"), (date(2028, 2, 1), date(2028, 2, 29)))

    def test_previous_and_next_month_key_within_year(self):
        self.assertEqual(previous_month_key("2026-09"), "2026-08")
        self.assertEqual(next_month_key("2026-09"), "2026-10")

    def test_previous_and_next_month_key_across_year_boundary(self):
        self.assertEqual(previous_month_key("2026-01"), "2025-12")
        self.assertEqual(next_month_key("2026-12"), "2027-01")

    def test_month_label(self):
        self.assertEqual(month_label("2026-09"), "September 2026")

    def test_validate_month_key_accepts_well_formed_key(self):
        self.assertEqual(validate_month_key("2026-09"), "2026-09")

    def test_validate_month_key_rejects_malformed_input(self):
        for bad in ("2026-9", "2026-13", "2026-00", "09-2026", "not-a-month", ""):
            with self.assertRaises(ValueError):
                validate_month_key(bad)

    def test_month_bounds_rejects_invalid_key(self):
        with self.assertRaises(ValueError):
            month_bounds("2026-13")


class CandidateDashboardReminderTests(unittest.TestCase):
    """Covers the week-range label / Saturday-detection helpers backing the
    candidate-dashboard reminder cards. Mirrors the user-facing example in
    the feature spec: mocked "now" of 2026-10-10 (a Saturday) SAST must show
    Current 5-11 October 2026 and Upcoming 12-18 October 2026."""

    def test_mocked_2026_10_10_saturday_matches_spec_example(self):
        now = datetime(2026, 10, 10, 12, 0, tzinfo=SAST)
        current, upcoming = candidate_week_keys(now)
        self.assertEqual(current, "2026-10-04")
        self.assertEqual(upcoming, "2026-10-11")
        self.assertEqual(format_week_range_with_year(current), "5–11 October 2026")
        self.assertEqual(format_week_range_with_year(upcoming), "12–18 October 2026")
        self.assertTrue(is_saturday(now))

    def test_normal_mid_month_week(self):
        # Wednesday 16 Sep 2026 -> week is 14-20 Sep 2026.
        now = datetime(2026, 9, 16, 9, 0, tzinfo=SAST)
        current, _ = candidate_week_keys(now)
        self.assertEqual(format_week_range_with_year(current), "14–20 September 2026")
        self.assertFalse(is_saturday(now))

    def test_saturday(self):
        now = datetime(2026, 9, 19, 23, 0, tzinfo=SAST)  # Saturday
        self.assertTrue(is_saturday(now))

    def test_sunday(self):
        now = datetime(2026, 9, 20, 0, 1, tzinfo=SAST)  # Sunday
        self.assertFalse(is_saturday(now))
        current, _ = candidate_week_keys(now)
        # Sunday 20 Sep still belongs to the 14-20 Sep reporting week.
        self.assertEqual(format_week_range_with_year(current), "14–20 September 2026")

    def test_monday(self):
        now = datetime(2026, 9, 21, 0, 1, tzinfo=SAST)  # Monday, new week starts
        self.assertFalse(is_saturday(now))
        current, _ = candidate_week_keys(now)
        self.assertEqual(format_week_range_with_year(current), "21–27 September 2026")

    def test_month_boundary_within_same_year(self):
        # Monday 28 Sep 2026 -> week is 28 Sep - 4 Oct 2026.
        now = datetime(2026, 9, 29, 10, 0, tzinfo=SAST)
        current, _ = candidate_week_keys(now)
        self.assertEqual(
            format_week_range_with_year(current), "28 September – 4 October 2026"
        )

    def test_december_to_january_year_boundary(self):
        # Monday 28 Dec 2026 -> week is 28 Dec 2026 - 3 Jan 2027.
        now = datetime(2026, 12, 30, 10, 0, tzinfo=SAST)
        current, upcoming = candidate_week_keys(now)
        self.assertEqual(
            format_week_range_with_year(current),
            "28 December 2026 – 3 January 2027",
        )
        self.assertEqual(
            format_week_range_with_year(upcoming),
            "4–10 January 2027",
        )

    def test_leap_year_february_week(self):
        # 2028 is a leap year; Monday 28 Feb 2028 -> week is 28 Feb - 5 Mar.
        now = datetime(2028, 2, 29, 10, 0, tzinfo=SAST)  # leap day, Tuesday
        current, _ = candidate_week_keys(now)
        self.assertEqual(
            format_week_range_with_year(current), "28 February – 5 March 2028"
        )

    def test_no_utc_off_by_one_near_sast_midnight(self):
        # 2026-09-20 23:30 SAST is 21:30 UTC the same calendar day — must
        # never be mistaken for the next UTC calendar day's week.
        now_sast = datetime(2026, 9, 20, 23, 30, tzinfo=SAST)
        now_utc = now_sast.astimezone(timezone.utc)
        self.assertEqual(now_utc.date().isoformat(), "2026-09-20")
        current, _ = candidate_week_keys(now_sast)
        self.assertEqual(format_week_range_with_year(current), "14–20 September 2026")


if __name__ == "__main__":
    unittest.main()
