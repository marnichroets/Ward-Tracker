import copy
import csv
import io
import unittest

from smartsheet_reporting import (
    CANONICAL_ACTIVITY_CATEGORY,
    CANVASSING,
    CUSTOM_OTHER_TYPE,
    NEEDS_REVIEW,
    PRESENCE,
    PUBLIC_STREET_MEETING,
    SMARTSHEET_HEADERS,
    classification_for_entry,
    classify_activity_text,
    is_custom_other_entry,
    review_entries,
    reporting_metadata_for_submission,
    smartsheet_csv_bytes,
    smartsheet_rows,
    summarize_smartsheet_entries,
    validate_time_range,
)


def csv_rows(payload: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))


class SmartSheetReportingTests(unittest.TestCase):
    def test_each_approved_activity_maps_to_one_destination(self):
        for label, expected_category in CANONICAL_ACTIVITY_CATEGORY.items():
            with self.subTest(label=label):
                classification = classify_activity_text(label)
                self.assertEqual(classification.category, expected_category)
                self.assertEqual(classification.canonical_activity, label)
                self.assertFalse(classification.needs_review)

    def test_required_specific_mappings(self):
        self.assertEqual(classify_activity_text("House Meeting").category, CANVASSING)
        self.assertEqual(classify_activity_text("Street Meeting").category, PUBLIC_STREET_MEETING)
        self.assertEqual(classify_activity_text("Blue Wave").category, PRESENCE)

    def test_case_insensitive_historical_matching(self):
        self.assertEqual(classify_activity_text("door to door canvassing Ward 5").category, CANVASSING)
        self.assertEqual(classify_activity_text("PUBLIC MEETING").category, PUBLIC_STREET_MEETING)
        self.assertEqual(classify_activity_text("cleaning up dump site").category, PRESENCE)
        self.assertEqual(classify_activity_text("SOUP kitchen").category, PRESENCE)

    def test_unclear_historical_text_needs_review(self):
        classification = classify_activity_text("candidate follow up")
        self.assertEqual(classification.category, NEEDS_REVIEW)
        self.assertTrue(classification.needs_review)

    def test_generic_canvassing_is_suggested_but_still_needs_review_for_exact_activity(self):
        classification = classify_activity_text("Canvassing")
        self.assertEqual(classification.category, CANVASSING)
        self.assertEqual(classification.suggested_category, CANVASSING)
        self.assertTrue(classification.needs_review)

    def test_poster_preparation_is_suggested_presence_but_still_needs_review(self):
        classification = classify_activity_text("Preparing posters with cable ties")
        self.assertEqual(classification.category, PRESENCE)
        self.assertEqual(classification.suggested_category, PRESENCE)
        self.assertIsNone(classification.canonical_activity)
        self.assertTrue(classification.needs_review)

    def test_time_validation_accepts_valid_times_and_rejects_obvious_invalid_ranges(self):
        self.assertEqual(validate_time_range("09:00", "10:30"), ("09:00", "10:30"))
        self.assertEqual(validate_time_range(None, None), (None, None))
        with self.assertRaises(ValueError):
            validate_time_range("10:00", "09:30")
        with self.assertRaises(ValueError):
            validate_time_range("9am", "10:00")

    def test_new_submission_derives_category_and_canonical_activity(self):
        metadata = reporting_metadata_for_submission({
            "type": "Door to Door",
            "type_display": "Door to Door",
        })
        self.assertEqual(metadata["smartsheet_category"], CANVASSING)
        self.assertEqual(metadata["canonical_activity"], "Door to Door")
        self.assertEqual(metadata["category_source"], "automatic")

    def test_admin_review_category_is_preserved_when_activity_text_is_unchanged(self):
        existing = {
            "type": "Other",
            "type_display": "Legacy activity",
            "smartsheet_category": PRESENCE,
            "category_source": "admin_review",
            "category_reviewed_at": "2026-09-01T10:00:00+00:00",
        }
        metadata = reporting_metadata_for_submission({
            "type": "Other",
            "type_display": "Legacy activity",
        }, existing)
        self.assertEqual(metadata["smartsheet_category"], PRESENCE)
        self.assertEqual(metadata["category_source"], "admin_review")

    def test_legacy_records_remain_readable_and_unchanged_by_classification(self):
        entries = [
            {
                "id": "1",
                "week_key": "2026-08-30",
                "day": "mon",
                "type": "Door to Door",
                "type_display": "Door to Door",
                "ward": "Ward 1",
            },
            {
                "id": "2",
                "week_key": "2026-08-30",
                "day": "tue",
                "type": "Other",
                "type_display": "Legacy unclear activity",
                "ward": "Ward 2",
            },
            {
                "id": "3",
                "week_key": "2026-08-23",
                "day": "sun",
                "type": "Blue Wave",
                "type_display": "Blue Wave",
                "ward": "Ward 3",
            },
        ]
        before = copy.deepcopy(entries)

        summary = summarize_smartsheet_entries(entries, "2026-08-30")
        review_rows = review_entries(entries)

        self.assertEqual(len(entries), 3)
        self.assertEqual(len(before), len(entries))
        self.assertEqual(before, entries)
        self.assertEqual(summary["total_historical_activities"], 3)
        self.assertEqual(summary["weekly"]["total"], 2)
        self.assertEqual(summary["needs_review"], len(review_rows))
        self.assertEqual(summary["needs_review"], 1)
        self.assertTrue(all("start_time" not in entry for entry in entries))
        self.assertTrue(all("end_time" not in entry for entry in entries))
        self.assertTrue(all("venue" not in entry for entry in entries))

    def test_smartsheet_export_columns_week_filtering_and_blank_historical_times(self):
        docs = [
            {
                "id": "1",
                "week_key": "2026-08-30",
                "day": "mon",
                "activity_date": "2026-08-31",
                "ward": "Ward 1",
                "venue": "Hall",
                "type": "Door to Door",
                "type_display": "Door to Door",
                "start_time": "09:00",
                "end_time": "10:00",
            },
            {
                "id": "2",
                "week_key": "2026-08-30",
                "day": "tue",
                "activity_date": "2026-09-01",
                "ward": "Ward 2",
                "type": "Street Meeting",
                "type_display": "Street Meeting",
            },
            {
                "id": "3",
                "week_key": "2026-08-23",
                "day": "mon",
                "activity_date": "2026-08-24",
                "ward": "Ward 3",
                "type": "Blue Wave",
                "type_display": "Blue Wave",
            },
        ]

        rows = csv_rows(smartsheet_csv_bytes(docs, "2026-08-30", CANVASSING))
        self.assertEqual(rows[0], SMARTSHEET_HEADERS)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][:7], ["2026-08-31", "09:00", "10:00", "Ntsikana Constituency", "Ward 1", "Hall", "Door to Door"])

        public_rows = csv_rows(smartsheet_csv_bytes(docs, "2026-08-30", PUBLIC_STREET_MEETING))
        self.assertEqual(public_rows[1][1], "")
        self.assertEqual(public_rows[1][2], "")
        self.assertEqual(public_rows[1][6], "Street Meeting")

    def test_no_duplicate_rows_between_category_exports(self):
        docs = [
            {"id": "1", "week_key": "2026-08-30", "day": "mon", "type_display": "Door to Door", "ward": "1"},
            {"id": "2", "week_key": "2026-08-30", "day": "tue", "type_display": "Street Meeting", "ward": "2"},
            {"id": "3", "week_key": "2026-08-30", "day": "wed", "type_display": "Blue Wave", "ward": "3"},
            {"id": "4", "week_key": "2026-08-30", "day": "thu", "type_display": "Unclear work", "ward": "4"},
        ]
        category_rows = []
        for category in (CANVASSING, PUBLIC_STREET_MEETING, PRESENCE):
            category_rows.extend(tuple(row) for row in smartsheet_rows(docs, "2026-08-30", category))

        self.assertEqual(len(category_rows), 3)
        self.assertEqual(len(set(category_rows)), 3)

        all_rows = csv_rows(smartsheet_csv_bytes(docs, "2026-08-30", "ALL"))
        self.assertIn("SMARTSHEET DESTINATION", all_rows[0])
        self.assertIn("REVIEW STATUS", all_rows[0])
        self.assertTrue(any(row[-2:] == ["Needs Review", "Needs review"] for row in all_rows[1:]))


class OtherActivityClassificationTests(unittest.TestCase):
    """Item 13: a candidate-typed "Other" activity must never be auto-guessed
    into a fixed SmartSheet category, even when the wording happens to match
    an official activity label exactly."""

    def test_is_custom_other_entry_matches_only_the_type_marker(self):
        self.assertTrue(is_custom_other_entry({"type": CUSTOM_OTHER_TYPE, "type_display": "Community prayer event"}))
        self.assertFalse(is_custom_other_entry({"type": "Door to Door", "type_display": "Door to Door"}))
        self.assertFalse(is_custom_other_entry({}))
        self.assertFalse(is_custom_other_entry({"type": " other "}))  # marker must match exactly, not fuzzily

    def test_other_submission_with_custom_wording_needs_review(self):
        metadata = reporting_metadata_for_submission({
            "type": CUSTOM_OTHER_TYPE,
            "type_display": "Community prayer event",
        })
        self.assertEqual(metadata["smartsheet_category"], NEEDS_REVIEW)
        self.assertIsNone(metadata["canonical_activity"])
        self.assertEqual(metadata["category_source"], "automatic")
        self.assertFalse(metadata["category_reviewed"])

    def test_other_wording_matching_an_official_label_is_not_auto_classified(self):
        # The candidate deliberately used Other instead of the matching dropdown
        # entry — submission-time metadata must not silently reclassify it.
        metadata = reporting_metadata_for_submission({
            "type": CUSTOM_OTHER_TYPE,
            "type_display": "Door to Door",
        })
        self.assertEqual(metadata["smartsheet_category"], NEEDS_REVIEW)
        self.assertIsNone(metadata["canonical_activity"])

        # And re-deriving classification straight from the stored doc (as the
        # admin review list, summary, and exports all do) must agree.
        classification = classification_for_entry({
            "type": CUSTOM_OTHER_TYPE,
            "type_display": "Door to Door",
            **metadata,
        })
        self.assertEqual(classification.category, NEEDS_REVIEW)
        self.assertIsNone(classification.canonical_activity)

    def test_other_entry_without_stored_metadata_still_needs_review(self):
        # Defends against re-deriving classification from a raw doc (e.g. a
        # historical/legacy record) instead of trusting stored fields.
        classification = classification_for_entry({
            "type": CUSTOM_OTHER_TYPE,
            "type_display": "Public Meeting",
        })
        self.assertEqual(classification.category, NEEDS_REVIEW)
        self.assertIsNone(classification.canonical_activity)
        self.assertTrue(classification.needs_review)

    def test_other_entry_appears_in_admin_review_with_exact_wording(self):
        entries = [{
            "id": "42",
            "week_key": "2026-08-30",
            "day": "wed",
            "type": CUSTOM_OTHER_TYPE,
            "type_display": "Community prayer event",
            "name": "Nomsa Dlamini",
            "ward": "Ward 4",
            "smartsheet_category": NEEDS_REVIEW,
            "canonical_activity": None,
            "category_source": "automatic",
        }]
        rows = review_entries(entries)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["original_activity"], "Community prayer event")
        self.assertIsNone(rows[0]["suggested_category"])

    def test_other_entry_excluded_from_category_exports_until_reviewed(self):
        docs = [
            {"id": "1", "week_key": "2026-08-30", "day": "mon", "type": "Door to Door", "type_display": "Door to Door", "ward": "1"},
            {
                "id": "2", "week_key": "2026-08-30", "day": "tue",
                "type": CUSTOM_OTHER_TYPE, "type_display": "Door to Door",
                "ward": "2", "smartsheet_category": NEEDS_REVIEW, "canonical_activity": None,
                "category_source": "automatic",
            },
        ]
        canvassing_rows = smartsheet_rows(docs, "2026-08-30", CANVASSING)
        self.assertEqual(len(canvassing_rows), 1)
        self.assertEqual(canvassing_rows[0][6], "Door to Door")

        all_rows = csv_rows(smartsheet_csv_bytes(docs, "2026-08-30", "ALL"))
        needs_review_rows = [r for r in all_rows[1:] if r[-2:] == ["Needs Review", "Needs review"]]
        self.assertEqual(len(needs_review_rows), 1)
        self.assertEqual(needs_review_rows[0][6], "Door to Door")

    def test_other_entry_admin_review_override_is_preserved_when_wording_unchanged(self):
        existing = {
            "type": CUSTOM_OTHER_TYPE,
            "type_display": "Community prayer event",
            "smartsheet_category": PRESENCE,
            "category_source": "admin_review",
            "category_reviewed_at": "2026-09-01T10:00:00+00:00",
        }
        metadata = reporting_metadata_for_submission({
            "type": CUSTOM_OTHER_TYPE,
            "type_display": "Community prayer event",
        }, existing)
        self.assertEqual(metadata["smartsheet_category"], PRESENCE)
        self.assertEqual(metadata["category_source"], "admin_review")

    def test_other_entry_edit_with_changed_wording_resets_to_needs_review(self):
        existing = {
            "type": CUSTOM_OTHER_TYPE,
            "type_display": "Community prayer event",
            "smartsheet_category": PRESENCE,
            "category_source": "admin_review",
            "category_reviewed_at": "2026-09-01T10:00:00+00:00",
        }
        metadata = reporting_metadata_for_submission({
            "type": CUSTOM_OTHER_TYPE,
            "type_display": "Different wording entirely",
        }, existing)
        self.assertEqual(metadata["smartsheet_category"], NEEDS_REVIEW)
        self.assertEqual(metadata["category_source"], "automatic")
        self.assertFalse(metadata["category_reviewed"])

    def test_normal_activities_unaffected_by_other_handling(self):
        # House Meeting -> Canvassing and Street Meeting -> Public/Street must
        # remain exactly as before; only the Other marker forces NEEDS_REVIEW.
        house = reporting_metadata_for_submission({"type": "House Meeting", "type_display": "House Meeting"})
        self.assertEqual(house["smartsheet_category"], CANVASSING)
        self.assertEqual(house["canonical_activity"], "House Meeting")

        street = reporting_metadata_for_submission({"type": "Street Meeting", "type_display": "Street Meeting"})
        self.assertEqual(street["smartsheet_category"], PUBLIC_STREET_MEETING)
        self.assertEqual(street["canonical_activity"], "Street Meeting")


if __name__ == "__main__":
    unittest.main()
