import asyncio
import copy
import os
import unittest

os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
os.environ.setdefault("ADMIN_PIN", "1234")
os.environ.setdefault("JWT_SECRET", "local-test-secret")

from bson import ObjectId
from fastapi import HTTPException

import activity_records
import activity_config
import leadership_reporting
import main as appmod
import official_capture
from test_campaigns import FakeCollection
from week_dates import current_week_key, activity_date_for_day, recommended_campaign_activities


class OperationalUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.original = appmod.entries_col, appmod.roster_col, appmod.campaigns_col
        appmod.entries_col = FakeCollection()
        appmod.roster_col = FakeCollection()
        appmod.campaigns_col = FakeCollection()
        appmod.roster_col.docs = [
            {"_id": ObjectId(), "name": "Test Candidate", "name_slug": "test-candidate",
             "ward": "Amahlathi", "municipality": "Amahlathi", "actual_ward": "Ward 7"},
            {"_id": ObjectId(), "name": "Other Candidate", "name_slug": "other-candidate",
             "ward": "Amahlathi", "municipality": "Amahlathi", "actual_ward": "Ward 7"},
        ]

    def tearDown(self):
        appmod.entries_col, appmod.roster_col, appmod.campaigns_col = self.original

    def campaign_body(self, **overrides):
        values = dict(
            person_id="test-candidate", name="Safer Streets", objective="Reduce unsafe areas",
            problem_description="Residents do not feel safe", solution="Visible patrols and reporting",
            wards=["Ward 7"], area="Bedford", start_date="2026-09-15", end_date="2026-09-21",
            campaign_theme="Crime", purpose="tackling_problem", includes_criticism=False,
            campaign_message="We will work with residents to make every street safer.",
            planned_activity_types=["Community Crime Patrol"],
            planned_activities=[{"id": "p1", "date": "2026-09-16", "time": "10:00",
                                 "activity_type": "Community Crime Patrol", "area": "Bedford"},
                                {"id": "p2", "date": "2026-09-18", "time": "10:00",
                                 "activity_type": "Community Crime Patrol", "area": "Bedford"}],
            submission_status="submitted",
        )
        values.update(overrides)
        return appmod.CampaignIn(**values)

    def entry_body(self, person="test-candidate", name="Test Candidate", **overrides):
        week = current_week_key()
        values = dict(
            person_id=person, name=name, ward="Ward 7", day="mon", type="Door to Door",
            type_display="Door to Door", week_key=week, week_label="",
            activity_date=activity_date_for_day(week, "mon"), start_time="10:00", end_time="11:00",
            venue="Bedford Hall",
        )
        values.update(overrides)
        return appmod.EntryIn(**values)

    def complete_campaign_doc(self, **overrides):
        values = {
            "person_id": "test-candidate", "name": "Safer Streets",
            "objective": "Reduce unsafe areas", "problem_description": "Residents do not feel safe",
            "solution": "Visible patrols and reporting", "municipality": "Amahlathi",
            "wards": ["Ward 7"], "start_date": "2026-09-15", "end_date": "2026-09-21",
            "campaign_theme": "Crime", "purpose": "tackling_problem",
            "includes_criticism": False, "campaign_message": "Make every street safer.",
            "area": "", "support_people": [],
            "planned_activities": [
                {"id": "p1", "date": "2026-09-16", "time": "10:00",
                 "activity_type": "Community Crime Patrol", "area": ""},
                {"id": "p2", "date": "2026-09-18", "time": "14:00",
                 "activity_type": "Community Crime Patrol", "area": ""},
            ],
        }
        values.update(overrides)
        return values

    def test_full_campaign_stores_owner_message_people_types_and_plan_time(self):
        result = asyncio.run(appmod.create_campaign(self.campaign_body(support_people=["Helper One"])))
        self.assertEqual(result["person_id"], "test-candidate")
        self.assertEqual(result["municipality"], "Amahlathi")
        self.assertEqual(result["wards"], ["Ward 7"])
        self.assertEqual(result["support_people"], ["Helper One"])
        self.assertEqual(result["planned_activities"][0]["time"], "10:00")
        self.assertEqual(result["recommended_activity_minimum"], 2)

    def test_word_count_is_guidance_not_submission_validation(self):
        result = asyncio.run(appmod.create_campaign(self.campaign_body(campaign_message="Vote local.")))
        self.assertEqual(result["submission_status"], "submitted")

    def test_completeness_requires_all_official_fields_but_not_optional_fields(self):
        complete = self.complete_campaign_doc()
        self.assertEqual(appmod._campaign_missing_fields(complete), [])
        required_cases = {
            "name": "Campaign name", "objective": "Objective",
            "problem_description": "Problem / issue", "solution": "Solution",
            "municipality": "Municipality", "wards": "Ward / wards",
            "start_date": "Start date", "end_date": "End date",
            "campaign_theme": "Campaign theme", "purpose": "Campaign type",
            "includes_criticism": "Criticism: Yes or No", "campaign_message": "Campaign message",
        }
        for field, label in required_cases.items():
            value = [] if field == "wards" else None if field == "includes_criticism" else "   "
            with self.subTest(field=field):
                self.assertIn(label, appmod._campaign_missing_fields(self.complete_campaign_doc(**{field: value})))

    def test_placeholders_and_partial_plan_rows_do_not_satisfy_completeness(self):
        invalid_selections = self.complete_campaign_doc(
            campaign_theme="Select theme", purpose="Select one",
            planned_activities=[
                {"id": "p1", "date": "2026-09-16", "time": "10:00",
                 "activity_type": "Community Crime Patrol", "area": ""},
                {"id": "p2", "date": "2026-09-18", "time": "",
                 "activity_type": "Select activity", "area": "Optional venue"},
            ],
        )
        missing = appmod._campaign_missing_fields(invalid_selections)
        self.assertIn("Campaign theme", missing)
        self.assertIn("Campaign type", missing)
        self.assertIn("planned activity 2: Time, Activity Type", missing)
        self.assertIn("planned activities (1 of 2)", missing)

    def test_legacy_activity_types_without_required_plan_remain_intact_but_incomplete(self):
        campaign_id = ObjectId()
        historical = self.complete_campaign_doc(
            _id=campaign_id, planned_activity_types=["Community Crime Patrol"],
            planned_activities=[], submission_status="submitted",
            created_at="2026-08-01T00:00:00+00:00",
        )
        original = copy.deepcopy(historical)
        result = appmod.campaign_for_response(historical)
        self.assertFalse(result["completeness"]["ready"])
        self.assertIn("planned activities (0 of 2)", result["completeness"]["missing_fields"])
        self.assertEqual(result["planned_activity_types"], ["Community Crime Patrol"])
        self.assertEqual(historical, original)

    def test_one_central_planning_config_exposes_every_official_activity_type_once(self):
        config = activity_config.activity_config_response()
        flattened = [value for group in config["planned_activity_groups"] for value in group["values"]]
        self.assertEqual(set(flattened), set(activity_config.OFFICIAL_ACTIVITY_TYPES))
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_campaign_theme_config_matches_confirmed_official_values_verbatim(self):
        expected = [
            "Corruption", "Cost of living", "Councillor", "Crime", "Culture",
            "Documentation", "Education", "Electricity", "Environment", "Farming",
            "Grants", "Healthcare", "Housing", "Illegal immigration", "Jobs",
            "Municipal management", "Not a Campaign", "Protests", "Roads",
            "Service delivery", "Social ills", "Taxation", "Taxis, public transport",
            "Traffic and traffic policing", "Water",
        ]
        self.assertEqual(activity_config.campaign_themes()[:len(expected)], expected)

    def test_draft_may_be_incomplete_and_is_not_active(self):
        result = asyncio.run(appmod.create_campaign(appmod.CampaignIn(
            person_id="test-candidate", name="Partial", submission_status="draft"
        )))
        self.assertEqual(result["status"], "draft")
        self.assertFalse(result["completeness"]["ready"])
        dashboard = leadership_reporting.build_dashboard([], appmod.roster_col.docs, appmod.campaigns_col.docs)
        self.assertEqual(dashboard["kpis"]["active_campaigns"], 0)

    def test_incomplete_draft_cannot_submit(self):
        draft = asyncio.run(appmod.create_campaign(appmod.CampaignIn(
            person_id="test-candidate", name="Partial", submission_status="draft"
        )))
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(appmod.submit_campaign(draft["id"], appmod.CampaignSubmitIn(person_id="test-candidate")))
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("missing_fields", caught.exception.detail)

    def test_legacy_activity_types_alone_cannot_mark_a_campaign_complete(self):
        draft = asyncio.run(appmod.create_campaign(self.campaign_body(
            submission_status="draft", planned_activities=[],
            planned_activity_types=["Community Crime Patrol"],
        )))
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(appmod.submit_campaign(
                draft["id"], appmod.CampaignSubmitIn(person_id="test-candidate")
            ))
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("planned activities (0 of 2)", caught.exception.detail["missing_fields"])

    def test_legacy_submitted_campaign_can_save_partial_completion(self):
        campaign_id = ObjectId()
        appmod.campaigns_col.docs = [{
            "_id": campaign_id, "person_id": "test-candidate", "name": "Legacy Drive",
            "municipality": "Amahlathi", "wards": ["Ward 7"],
            "start_date": "2026-09-15", "end_date": "2026-09-21",
            "submission_status": "submitted", "created_at": "2026-08-01T00:00:00+00:00",
        }]
        body = appmod.CampaignIn(
            person_id="test-candidate", name="Legacy Drive", wards=["Ward 7"],
            start_date="2026-09-15", end_date="2026-09-21", campaign_theme="Crime",
            submission_status="submitted",
        )
        result = asyncio.run(appmod.update_campaign(str(campaign_id), body))
        self.assertEqual(result["id"], str(campaign_id))
        self.assertEqual(result["submission_status"], "submitted")
        self.assertEqual(result["campaign_theme"], "Crime")
        self.assertFalse(result["completeness"]["ready"])

    def test_recommended_minimum_uses_proportional_partial_week_rule(self):
        self.assertEqual(recommended_campaign_activities("2026-09-01", "2026-09-07"), 2)
        self.assertEqual(recommended_campaign_activities("2026-09-01", "2026-09-08"), 3)
        self.assertEqual(recommended_campaign_activities("2026-09-01", "2026-09-21"), 6)

    def test_campaign_duplicate_warns_then_create_anyway_succeeds(self):
        asyncio.run(appmod.create_campaign(self.campaign_body()))
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(appmod.create_campaign(self.campaign_body()))
        self.assertEqual(caught.exception.status_code, 409)
        result = asyncio.run(appmod.create_campaign(self.campaign_body(create_anyway=True)))
        self.assertEqual(result["duplicate_review_status"], activity_records.POSSIBLE_DUPLICATE)

    def test_activity_duplicate_warns_submit_anyway_and_different_candidate_is_safe(self):
        first = asyncio.run(appmod.create_entry(self.entry_body()))
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(appmod.create_entry(self.entry_body()))
        self.assertEqual(caught.exception.detail["duplicate_kind"], "exact")
        second = asyncio.run(appmod.create_entry(self.entry_body(duplicate_override=True)))
        self.assertNotEqual(first["id"], second["id"])
        other = asyncio.run(appmod.create_entry(self.entry_body(person="other-candidate", name="Other Candidate")))
        self.assertTrue(other["id"])

    def test_possible_duplicate_is_non_blocking_after_override_and_different_work_is_safe(self):
        asyncio.run(appmod.create_entry(self.entry_body()))
        possible = self.entry_body(venue="Bedford Library", start_time="11:30", end_time="12:30")
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(appmod.create_entry(possible))
        self.assertEqual(caught.exception.detail["duplicate_kind"], "possible")
        possible.duplicate_override = True
        result = asyncio.run(appmod.create_entry(possible))
        self.assertEqual(result["duplicate_review_status"], activity_records.POSSIBLE_DUPLICATE)
        clearly_different = self.entry_body(type="Public meeting", type_display="Public meeting")
        self.assertTrue(asyncio.run(appmod.create_entry(clearly_different))["id"])

    def test_planned_and_completed_matching_are_not_duplicate_compared(self):
        campaign = asyncio.run(appmod.create_campaign(self.campaign_body()))
        # Campaign creation stores a plan but creates no completed entry.
        self.assertEqual(len(appmod.entries_col.docs), 0)
        body = appmod.CampaignActivityIn(
            person_id="test-candidate", activity_date="2026-09-16", type="Community Crime Patrol",
            type_display="Community Crime Patrol", start_time="10:00", end_time="11:00",
            venue="Bedford", ward="Ward 7",
        )
        result = asyncio.run(appmod.create_campaign_activity(campaign["id"], body))
        self.assertTrue(result["id"])

    def test_captured_campaign_edit_flags_review_and_preserves_history(self):
        campaign = asyncio.run(appmod.create_campaign(self.campaign_body()))
        asyncio.run(appmod.update_campaign_capture(
            campaign["id"], appmod.CampaignCaptureUpdateIn(campaign_manager_capture_status="captured"), True
        ))
        updated = asyncio.run(appmod.update_campaign(
            campaign["id"], self.campaign_body(solution="More patrols and a public feedback line")
        ))
        stored = appmod.campaigns_col.docs[0]
        self.assertTrue(stored["official_review_required"])
        self.assertEqual(stored["change_history"][-1]["field"], "solution")
        self.assertEqual(stored["change_history"][-1]["previous_value"], "Visible patrols and reporting")
        cleared = asyncio.run(appmod.campaign_official_record_updated(campaign["id"], True))
        self.assertFalse(cleared["official_review_required"])

    def test_confirmed_duplicate_is_preserved_but_shared_reporting_excludes_it(self):
        asyncio.run(appmod.create_entry(self.entry_body()))
        asyncio.run(appmod.create_entry(self.entry_body(duplicate_override=True)))
        duplicate_id = str(appmod.entries_col.docs[1]["_id"])
        evidence = [{"id": "kept-photo"}]
        appmod.entries_col.docs[1]["evidence_photos"] = copy.deepcopy(evidence)
        asyncio.run(appmod.update_entry_duplicate_review(
            duplicate_id, appmod.DuplicateReviewIn(status="confirmed_duplicate"), True
        ))
        self.assertEqual(len(appmod.entries_col.docs), 2)
        self.assertEqual(appmod.entries_col.docs[1]["evidence_photos"], evidence)
        dataset = leadership_reporting.weekly_grid_dataset(appmod.entries_col.docs, lambda d: d.get("ward", ""))
        self.assertEqual(dataset["total_activities"], 1)

    def test_possible_and_not_duplicate_records_keep_counting(self):
        possible = self.entry_body().model_dump()
        possible["duplicate_review_status"] = activity_records.POSSIBLE_DUPLICATE
        reviewed = self.entry_body(venue="Another venue").model_dump()
        reviewed["duplicate_review_status"] = activity_records.NOT_DUPLICATE
        self.assertEqual(len(activity_records.reportable_activities([possible, reviewed])), 2)

    def test_historical_duplicate_analysis_is_read_only(self):
        asyncio.run(appmod.create_entry(self.entry_body()))
        asyncio.run(appmod.create_entry(self.entry_body(duplicate_override=True)))
        before = copy.deepcopy(appmod.entries_col.docs)
        result = asyncio.run(appmod.admin_possible_duplicates(True))
        self.assertEqual(result["count"], 1)
        self.assertEqual(appmod.entries_col.docs, before)

    def test_coordinator_time_uses_canonical_fields_and_missing_is_safe(self):
        row = official_capture.augment_entry({"id": "1", "start_time": "10:00", "end_time": "11:00"}, None)
        self.assertEqual(row["time_label"], "10:00 - 11:00")
        self.assertEqual(activity_records.activity_time_label("10:00", "11:00"), row["time_label"])
        historical = official_capture.augment_entry({"id": "2"}, None)
        self.assertEqual(historical["time_label"], "Time not recorded")
        self.assertNotIn("activity_time", row)

    def test_historical_campaign_loads_without_fabricated_new_values(self):
        legacy = {"_id": ObjectId(), "person_id": "test-candidate", "name": "Legacy",
                  "purpose": "Legacy free-text goal", "start_date": "2026-09-01", "end_date": "2026-09-07"}
        result = appmod.campaign_for_response(legacy)
        self.assertEqual(result["objective"], "Legacy free-text goal")
        self.assertIsNone(result["purpose"])
        self.assertIsNone(result["campaign_message"])
        self.assertEqual(result["planned_activities"], [])


if __name__ == "__main__":
    unittest.main()
