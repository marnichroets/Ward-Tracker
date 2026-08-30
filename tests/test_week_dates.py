import hashlib
import json
import unittest
from collections import Counter
from datetime import datetime
from pathlib import Path

from week_dates import (
    SAST,
    activity_date_for_day,
    current_week_key,
    format_week_label,
    normalise_new_activity_date,
)


ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "backups" / "ward-tracker-admin-all-20260830-120603Z.json"
BACKUP_SHA256 = "F9FBFE85074168D8415BC9170285C2F443B12906AB724D29EB335369DC83DE06"


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

    def test_existing_53_backup_records_remain_untouched(self):
        raw = BACKUP.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest().upper(), BACKUP_SHA256)

        entries = json.loads(raw.decode("utf-8"))["entries"]
        self.assertEqual(len(entries), 53)
        self.assertEqual(Counter(e["week_key"] for e in entries), Counter({
            "2026-08-23": 23,
            "2026-08-30": 30,
        }))
        self.assertTrue(all("activity_date" not in e for e in entries))


if __name__ == "__main__":
    unittest.main()
