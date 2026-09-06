import asyncio
import copy
import os
import unittest
from datetime import datetime
from types import SimpleNamespace

try:
    import fastapi  # noqa: F401
    from bson import ObjectId
    from fastapi import HTTPException
    from pymongo.errors import DuplicateKeyError

    HAS_API_DEPS = True
except ModuleNotFoundError:
    ObjectId = None
    HTTPException = Exception
    DuplicateKeyError = Exception
    HAS_API_DEPS = False

try:
    from fastapi.testclient import TestClient  # requires httpx

    HAS_TESTCLIENT = True
except ImportError:
    TestClient = None
    HAS_TESTCLIENT = False


@unittest.skipUnless(HAS_API_DEPS, "FastAPI dependencies are not installed")
class CampaignCrudTests(unittest.TestCase):
    """Phase 1 backend foundation: campaign create/read/update/archive/delete,
    duration validation, and roster-only identity enforcement — mirroring the
    conventions in tests/test_api_smartsheet.py (FakeCollection, direct
    async-function calls against the real handlers)."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
        os.environ.setdefault("ADMIN_PIN", "1234")
        os.environ.setdefault("JWT_SECRET", "local-test-secret")
        global appmod
        import main as appmod

    def setUp(self):
        self.original_entries_col = appmod.entries_col
        self.original_roster_col = appmod.roster_col
        self.original_campaigns_col = appmod.campaigns_col
        self.entries = FakeCollection()
        self.roster = FakeCollection()
        self.campaigns = FakeCollection()
        self.roster.docs = [
            {"_id": ObjectId(), "name": "Test Candidate", "ward": "Ward 1", "name_slug": "test-candidate"},
        ]
        appmod.entries_col = self.entries
        appmod.roster_col = self.roster
        appmod.campaigns_col = self.campaigns

    def tearDown(self):
        appmod.entries_col = self.original_entries_col
        appmod.roster_col = self.original_roster_col
        appmod.campaigns_col = self.original_campaigns_col

    def _body(self, **overrides):
        kwargs = dict(
            person_id="test-candidate",
            name="Ward 13 Canvassing Drive",
            start_date="2026-09-14",
            end_date="2026-10-04",
        )
        kwargs.update(overrides)
        return appmod.CampaignIn(**kwargs)

    # ---- identity ----

    def test_create_campaign_stores_canonical_roster_person_id(self):
        result = asyncio.run(appmod.create_campaign(self._body(person_id="Test Candidate")))
        self.assertEqual(result["person_id"], "test-candidate")
        self.assertEqual(self.campaigns.docs[0]["person_id"], "test-candidate")

    def test_create_campaign_rejects_unknown_roster_identity(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign(self._body(person_id="nobody-on-the-roster")))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.campaigns.docs), 0)

    def test_update_campaign_still_enforces_roster(self):
        created = asyncio.run(appmod.create_campaign(self._body()))
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.update_campaign(created["id"], self._body(person_id="nobody-on-the-roster")))
        self.assertEqual(exc.exception.status_code, 400)

    # ---- duration validation ----

    def test_same_day_campaign_accepted(self):
        result = asyncio.run(appmod.create_campaign(self._body(start_date="2026-09-14", end_date="2026-09-14")))
        self.assertEqual(result["start_date"], "2026-09-14")
        self.assertEqual(result["end_date"], "2026-09-14")

    def test_42_inclusive_calendar_days_accepted(self):
        # 2026-09-01 .. 2026-10-12 inclusive is exactly 42 calendar dates.
        result = asyncio.run(appmod.create_campaign(self._body(start_date="2026-09-01", end_date="2026-10-12")))
        self.assertEqual(result["start_date"], "2026-09-01")
        self.assertEqual(result["end_date"], "2026-10-12")

    def test_43_inclusive_calendar_days_rejected(self):
        # One calendar day past the 42-day maximum.
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign(self._body(start_date="2026-09-01", end_date="2026-10-13")))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.campaigns.docs), 0)

    def test_end_before_start_rejected(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign(self._body(start_date="2026-09-14", end_date="2026-09-13")))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.campaigns.docs), 0)

    def test_blank_start_date_rejected(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign(self._body(start_date="")))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.campaigns.docs), 0)

    def test_blank_end_date_rejected(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign(self._body(end_date="")))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.campaigns.docs), 0)

    def test_blank_name_rejected(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign(self._body(name="   ")))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.campaigns.docs), 0)

    # ---- read / update ----

    def test_get_campaign_round_trip(self):
        created = asyncio.run(appmod.create_campaign(self._body()))
        fetched = asyncio.run(appmod.get_campaign(created["id"]))
        self.assertEqual(fetched["name"], "Ward 13 Canvassing Drive")
        self.assertEqual(fetched["start_date"], "2026-09-14")

    def test_get_missing_campaign_404s(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.get_campaign(str(ObjectId())))
        self.assertEqual(exc.exception.status_code, 404)

    def test_list_campaigns_scoped_by_person(self):
        asyncio.run(appmod.create_campaign(self._body()))
        self.roster.docs.append(
            {"_id": ObjectId(), "name": "Second Candidate", "ward": "Ward 2", "name_slug": "second-candidate"}
        )
        asyncio.run(appmod.create_campaign(self._body(person_id="second-candidate", name="Area Outreach")))
        mine = asyncio.run(appmod.list_campaigns("test-candidate"))
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["name"], "Ward 13 Canvassing Drive")

    def test_update_campaign_changes_fields(self):
        created = asyncio.run(appmod.create_campaign(self._body()))
        updated = asyncio.run(appmod.update_campaign(created["id"], self._body(name="Renamed Drive")))
        self.assertEqual(updated["name"], "Renamed Drive")
        self.assertEqual(len(self.campaigns.docs), 1)

    def test_update_missing_campaign_404s(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.update_campaign(str(ObjectId()), self._body()))
        self.assertEqual(exc.exception.status_code, 404)

    # ---- derived status ----

    def test_derived_status_planned_active_completed(self):
        created = asyncio.run(appmod.create_campaign(self._body(start_date="2026-09-14", end_date="2026-10-04")))
        doc = dict(self.campaigns.docs[0])
        utc = appmod.timezone.utc
        self.assertEqual(appmod.derive_campaign_status(doc, datetime(2026, 9, 1, tzinfo=utc)), "planned")
        self.assertEqual(appmod.derive_campaign_status(doc, datetime(2026, 9, 20, tzinfo=utc)), "active")
        self.assertEqual(appmod.derive_campaign_status(doc, datetime(2026, 9, 14, tzinfo=utc)), "active")
        self.assertEqual(appmod.derive_campaign_status(doc, datetime(2026, 10, 4, tzinfo=utc)), "active")
        self.assertEqual(appmod.derive_campaign_status(doc, datetime(2026, 10, 10, tzinfo=utc)), "completed")
        self.assertEqual(created["status"], "planned")

    def test_archived_status_overrides_dates(self):
        created = asyncio.run(appmod.create_campaign(self._body(start_date="2026-09-01", end_date="2026-09-10")))
        archived = asyncio.run(appmod.archive_campaign(created["id"], "test-candidate"))
        utc = appmod.timezone.utc
        # Even "checking" mid-campaign dates, an archived campaign reports archived.
        self.assertEqual(appmod.derive_campaign_status(dict(self.campaigns.docs[0]), datetime(2026, 9, 5, tzinfo=utc)), "archived")
        self.assertEqual(archived["status"], "archived")

    # ---- archive: the normal terminal action ----

    def test_archive_sets_archived_at_and_status(self):
        created = asyncio.run(appmod.create_campaign(self._body()))
        self.assertIsNone(self.campaigns.docs[0]["archived_at"])
        archived = asyncio.run(appmod.archive_campaign(created["id"], "test-candidate"))
        self.assertEqual(archived["status"], "archived")
        self.assertIsNotNone(self.campaigns.docs[0]["archived_at"])

    def test_archive_missing_campaign_404s(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.archive_campaign(str(ObjectId()), "test-candidate"))
        self.assertEqual(exc.exception.status_code, 404)

    def test_archive_rejects_unknown_roster_identity(self):
        created = asyncio.run(appmod.create_campaign(self._body()))
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.archive_campaign(created["id"], "nobody-on-the-roster"))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertIsNone(self.campaigns.docs[0]["archived_at"])

    def test_archive_only_changes_archived_at_nothing_else(self):
        created = asyncio.run(appmod.create_campaign(self._body()))
        archived = asyncio.run(appmod.archive_campaign(created["id"], "test-candidate"))
        self.assertEqual(archived["name"], "Ward 13 Canvassing Drive")
        self.assertEqual(archived["start_date"], "2026-09-14")
        self.assertEqual(archived["end_date"], "2026-10-04")
        self.assertEqual(archived["person_id"], "test-candidate")

    def test_archive_does_not_touch_entries_collection(self):
        self.entries.docs = [entry_doc(type_display="Door to Door", week_key="2026-09-13", day="mon")]
        before = copy.deepcopy(self.entries.docs)
        created = asyncio.run(appmod.create_campaign(self._body()))
        asyncio.run(appmod.archive_campaign(created["id"], "test-candidate"))
        self.assertEqual(self.entries.docs, before)

    # ---- delete: narrow escape hatch only, never a cascade ----

    def test_delete_campaign_with_zero_linked_activities_succeeds(self):
        created = asyncio.run(appmod.create_campaign(self._body()))
        result = asyncio.run(appmod.delete_campaign(created["id"], "test-candidate"))
        self.assertEqual(result, {"deleted": True})
        self.assertEqual(len(self.campaigns.docs), 0)

    def test_delete_missing_campaign_404s(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.delete_campaign(str(ObjectId()), "test-candidate"))
        self.assertEqual(exc.exception.status_code, 404)

    def test_delete_rejects_unknown_roster_identity(self):
        created = asyncio.run(appmod.create_campaign(self._body()))
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.delete_campaign(created["id"], "nobody-on-the-roster"))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.campaigns.docs), 1)

    def test_delete_campaign_with_linked_activity_returns_409(self):
        created = asyncio.run(appmod.create_campaign(self._body()))
        self.entries.docs = [entry_doc(type_display="Door to Door", week_key="2026-09-13", day="mon")]
        self.entries.docs[0]["campaign_id"] = created["id"]
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.delete_campaign(created["id"], "test-candidate"))
        self.assertEqual(exc.exception.status_code, 409)
        self.assertEqual(len(self.campaigns.docs), 1, "the campaign itself must survive a rejected delete")

    def test_delete_campaign_never_deletes_or_modifies_the_linked_activity(self):
        created = asyncio.run(appmod.create_campaign(self._body()))
        self.entries.docs = [entry_doc(type_display="Door to Door", week_key="2026-09-13", day="mon")]
        self.entries.docs[0]["campaign_id"] = created["id"]
        before = copy.deepcopy(self.entries.docs)
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.delete_campaign(created["id"], "test-candidate"))
        self.assertEqual(self.entries.docs, before, "no cascade-delete path from campaign to entries")

    # ---- ownership: a second roster person must never mutate this campaign ----

    def test_different_roster_person_cannot_update_campaign(self):
        created = asyncio.run(appmod.create_campaign(self._body()))
        self.roster.docs.append(
            {"_id": ObjectId(), "name": "Second Candidate", "ward": "Ward 2", "name_slug": "second-candidate"}
        )
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.update_campaign(created["id"], self._body(
                person_id="second-candidate", name="Hijacked Name",
            )))
        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(self.campaigns.docs[0]["name"], "Ward 13 Canvassing Drive")
        self.assertEqual(self.campaigns.docs[0]["person_id"], "test-candidate")

    def test_different_roster_person_cannot_archive_campaign(self):
        created = asyncio.run(appmod.create_campaign(self._body()))
        self.roster.docs.append(
            {"_id": ObjectId(), "name": "Second Candidate", "ward": "Ward 2", "name_slug": "second-candidate"}
        )
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.archive_campaign(created["id"], "second-candidate"))
        self.assertEqual(exc.exception.status_code, 404)
        self.assertIsNone(self.campaigns.docs[0]["archived_at"])

    def test_different_roster_person_cannot_delete_campaign(self):
        created = asyncio.run(appmod.create_campaign(self._body()))
        self.roster.docs.append(
            {"_id": ObjectId(), "name": "Second Candidate", "ward": "Ward 2", "name_slug": "second-candidate"}
        )
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.delete_campaign(created["id"], "second-candidate"))
        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(len(self.campaigns.docs), 1)

    def test_put_cannot_change_campaign_ownership_even_with_correct_original_owner(self):
        # There is no field a legitimate owner can send to reassign their own
        # campaign to someone else — CampaignIn's person_id is only ever used
        # to prove the caller's own identity, never to name a new owner.
        created = asyncio.run(appmod.create_campaign(self._body()))
        self.roster.docs.append(
            {"_id": ObjectId(), "name": "Second Candidate", "ward": "Ward 2", "name_slug": "second-candidate"}
        )
        # Owner calls update but is (deliberately, per the API contract) unable
        # to name a different resulting owner: the request must be made AS the
        # existing owner, so attempting it as "second-candidate" is rejected
        # as a different-person mutation attempt, not honored as a transfer.
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.update_campaign(created["id"], self._body(person_id="second-candidate")))
        self.assertEqual(self.campaigns.docs[0]["person_id"], "test-candidate")


@unittest.skipUnless(HAS_API_DEPS, "FastAPI dependencies are not installed")
class CampaignActivityTests(unittest.TestCase):
    """Phase 2: campaign-linked activity creation (single + recurring),
    materialized as real entries documents, campaign-bounded date
    validation, and the (recurrence_id, activity_date) idempotency design."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
        os.environ.setdefault("ADMIN_PIN", "1234")
        os.environ.setdefault("JWT_SECRET", "local-test-secret")
        global appmod
        import main as appmod

    def setUp(self):
        self.original_entries_col = appmod.entries_col
        self.original_roster_col = appmod.roster_col
        self.original_campaigns_col = appmod.campaigns_col
        self.entries = FakeCollection()
        self.roster = FakeCollection()
        self.campaigns = FakeCollection()
        self.roster.docs = [
            {"_id": ObjectId(), "name": "Test Candidate", "ward": "Ward 1", "name_slug": "test-candidate"},
            {"_id": ObjectId(), "name": "Second Candidate", "ward": "Ward 2", "name_slug": "second-candidate"},
        ]
        appmod.entries_col = self.entries
        appmod.roster_col = self.roster
        appmod.campaigns_col = self.campaigns
        self.campaign = asyncio.run(appmod.create_campaign(appmod.CampaignIn(
            person_id="test-candidate", name="Ward 13 Canvassing Drive",
            start_date="2026-09-14", end_date="2026-10-04",
        )))

    def tearDown(self):
        appmod.entries_col = self.original_entries_col
        appmod.roster_col = self.original_roster_col
        appmod.campaigns_col = self.original_campaigns_col

    def _single_body(self, **overrides):
        kwargs = dict(
            person_id="test-candidate",
            activity_date="2026-09-19",
            type="Door to Door",
            type_display="Door to Door",
            start_time="09:00",
            end_time="12:00",
            venue="Ward 7 Main Road",
        )
        kwargs.update(overrides)
        return appmod.CampaignActivityIn(**kwargs)

    def _repeat_body(self, **overrides):
        kwargs = dict(
            person_id="test-candidate",
            weekday="sat",
            first_occurrence_date="2026-09-19",  # a Saturday
            until="2026-10-03",
            type="Door to Door",
            type_display="Door to Door",
            start_time="09:00",
            end_time="12:00",
            venue="Ward 7 Main Road",
        )
        kwargs.update(overrides)
        return appmod.CampaignActivityRepeatIn(**kwargs)

    # ---- single occurrence ----

    def test_single_activity_created_as_real_entry_with_campaign_id(self):
        result = asyncio.run(appmod.create_campaign_activity(self.campaign["id"], self._single_body()))
        self.assertEqual(len(self.entries.docs), 1)
        stored = self.entries.docs[0]
        self.assertEqual(stored["campaign_id"], self.campaign["id"])
        self.assertEqual(stored["person_id"], "test-candidate")
        self.assertEqual(stored["name"], "Test Candidate")
        self.assertEqual(stored["ward"], "Ward 1")
        self.assertEqual(stored["activity_date"], "2026-09-19")
        self.assertEqual(stored["day"], "sat")
        self.assertEqual(stored["week_key"], "2026-09-13")
        self.assertEqual(result["type_display"], "Door to Door")

    def test_single_activity_gets_smartsheet_classification_like_any_other_entry(self):
        asyncio.run(appmod.create_campaign_activity(self.campaign["id"], self._single_body()))
        self.assertEqual(self.entries.docs[0]["smartsheet_category"], "CANVASSING")
        self.assertEqual(self.entries.docs[0]["canonical_activity"], "Door to Door")

    def test_single_activity_rejects_date_outside_campaign_range(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign_activity(
                self.campaign["id"], self._single_body(activity_date="2026-10-05"),
            ))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.entries.docs), 0)

    def test_single_activity_rejects_non_owner(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign_activity(
                self.campaign["id"], self._single_body(person_id="second-candidate"),
            ))
        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(len(self.entries.docs), 0)

    def test_single_activity_other_text_required(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign_activity(
                self.campaign["id"], self._single_body(type="Other", type_display=""),
            ))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.entries.docs), 0)

    # ---- Phase 5.1: Location/Venue required + must not just restate the ward ----

    def test_single_activity_requires_a_location(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign_activity(self.campaign["id"], self._single_body(venue=None)))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.entries.docs), 0)

    def test_single_activity_rejects_exact_ward_as_location(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign_activity(self.campaign["id"], self._single_body(venue="Ward 1")))
        self.assertIn("specific location", exc.exception.detail)
        self.assertEqual(len(self.entries.docs), 0)

    def test_single_activity_rejects_case_insensitive_ward_as_location(self):
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.create_campaign_activity(self.campaign["id"], self._single_body(venue="ward 1")))
        self.assertEqual(len(self.entries.docs), 0)

    def test_single_activity_allows_location_containing_ward_text(self):
        result = asyncio.run(appmod.create_campaign_activity(
            self.campaign["id"], self._single_body(venue="Mlungisi Community Hall, Ward 1"),
        ))
        self.assertEqual(result["venue"], "Mlungisi Community Hall, Ward 1")

    def test_repeat_activity_rejects_ward_only_venue(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign_activity_repeat(
                self.campaign["id"], self._repeat_body(venue="Ward 1"),
            ))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.entries.docs), 0)

    def test_repeat_activity_uses_canonical_roster_ward(self):
        asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], self._repeat_body()))
        self.assertTrue(all(d["ward"] == "Ward 1" for d in self.entries.docs))

    # ---- "Municipality" UI-label correction: same rules for a full municipality-style value ----

    def test_single_activity_uses_canonical_roster_municipality_value(self):
        self.roster.docs[0]["ward"] = "Amathole District Municipality"
        result = asyncio.run(appmod.create_campaign_activity(self.campaign["id"], self._single_body()))
        self.assertEqual(result["ward"], "Amathole District Municipality")

    def test_single_activity_rejects_full_municipality_name_as_location(self):
        self.roster.docs[0]["ward"] = "Amathole District Municipality"
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.create_campaign_activity(
                self.campaign["id"], self._single_body(venue="Amathole District Municipality"),
            ))
        self.assertEqual(len(self.entries.docs), 0)

    def test_repeat_activity_uses_canonical_roster_municipality_value(self):
        self.roster.docs[0]["ward"] = "Amathole District Municipality"
        asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], self._repeat_body()))
        self.assertTrue(all(d["ward"] == "Amathole District Municipality" for d in self.entries.docs))

    def test_single_activity_independent_of_candidate_week_window(self):
        # 2026-09-19 is neither "this week" nor "next week" relative to a
        # 2020 clock, but campaign-bounded validation doesn't care — it only
        # checks the campaign's own dates. Use a campaign whose dates are
        # nowhere near "today" at all — inserted directly rather than via
        # create_campaign, since Phase 5 blocks CREATING a brand-new campaign
        # that has already ended; it must never block using/editing
        # activities on an existing historical one (see CampaignPastEndDate
        # ...Tests below for the creation-time guard itself).
        far_campaign_id = ObjectId()
        self.campaigns.docs = [{
            "_id": far_campaign_id, "person_id": "test-candidate", "name": "Old Drive",
            "start_date": "2020-01-01", "end_date": "2020-01-10",
            "created_at": "2020-01-01T00:00:00+00:00", "archived_at": None,
        }]
        result = asyncio.run(appmod.create_campaign_activity(str(far_campaign_id), self._single_body(
            activity_date="2020-01-05",
        )))
        self.assertEqual(result["activity_date"], "2020-01-05")

    # ---- recurring ----

    def test_repeat_creates_one_entry_per_saturday(self):
        result = asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], self._repeat_body()))
        # 19 Sep, 26 Sep, 3 Oct
        self.assertEqual(len(result["created"]), 3)
        self.assertEqual(result["skipped_duplicate_dates"], [])
        self.assertEqual(len(self.entries.docs), 3)
        dates = sorted(d["activity_date"] for d in self.entries.docs)
        self.assertEqual(dates, ["2026-09-19", "2026-09-26", "2026-10-03"])
        for d in self.entries.docs:
            self.assertEqual(d["campaign_id"], self.campaign["id"])
            self.assertEqual(d["recurrence_id"], result["recurrence_id"])
            self.assertEqual(d["day"], "sat")

    def test_repeat_clamps_until_to_campaign_end_date(self):
        # Campaign ends 2026-10-04; ask for occurrences through 2026-11-01.
        result = asyncio.run(appmod.create_campaign_activity_repeat(
            self.campaign["id"], self._repeat_body(until="2026-11-01"),
        ))
        dates = sorted(d["activity_date"] for d in self.entries.docs)
        self.assertEqual(dates, ["2026-09-19", "2026-09-26", "2026-10-03"])
        self.assertNotIn("2026-11-07", dates)

    def test_repeat_retry_with_identical_request_does_not_duplicate(self):
        first = asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], self._repeat_body()))
        self.assertEqual(len(self.entries.docs), 3)
        second = asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], self._repeat_body()))
        self.assertEqual(second["recurrence_id"], first["recurrence_id"])
        self.assertEqual(second["created"], [])
        self.assertEqual(len(second["skipped_duplicate_dates"]), 3)
        # Still exactly 3 entries total — the retry created nothing new.
        self.assertEqual(len(self.entries.docs), 3)

    def test_two_independently_created_activities_same_type_and_date_both_allowed(self):
        # A manually-added single activity and a recurring occurrence that
        # happen to share a type and date are NOT the same thing and must
        # both exist.
        asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], self._repeat_body()))
        self.assertEqual(len(self.entries.docs), 3)
        single_result = asyncio.run(appmod.create_campaign_activity(
            self.campaign["id"], self._single_body(activity_date="2026-09-19"),
        ))
        self.assertEqual(len(self.entries.docs), 4)
        self.assertNotIn("recurrence_id", self.entries.docs[-1])

    def test_two_different_recurring_series_same_type_are_independent(self):
        # Different venue -> different recurrence_id -> both series coexist,
        # even though they share type/date on their first occurrence.
        first = asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], self._repeat_body()))
        second = asyncio.run(appmod.create_campaign_activity_repeat(
            self.campaign["id"], self._repeat_body(venue="A Different Venue Entirely"),
        ))
        self.assertNotEqual(first["recurrence_id"], second["recurrence_id"])
        self.assertEqual(len(second["created"]), 3)
        self.assertEqual(len(self.entries.docs), 6)

    def test_repeat_rejects_first_occurrence_not_matching_weekday(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign_activity_repeat(
                self.campaign["id"], self._repeat_body(first_occurrence_date="2026-09-18"),  # a Friday
            ))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.entries.docs), 0)

    def test_repeat_rejects_first_occurrence_outside_campaign_range(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign_activity_repeat(
                self.campaign["id"], self._repeat_body(first_occurrence_date="2026-09-12"),  # before campaign start
            ))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.entries.docs), 0)

    def test_repeat_rejects_until_before_first_occurrence(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign_activity_repeat(
                self.campaign["id"], self._repeat_body(until="2026-09-12"),
            ))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.entries.docs), 0)

    def test_repeat_rejects_non_owner(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign_activity_repeat(
                self.campaign["id"], self._repeat_body(person_id="second-candidate"),
            ))
        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(len(self.entries.docs), 0)

    def test_generated_occurrence_independently_editable(self):
        asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], self._repeat_body()))
        occurrence = self.entries.docs[0]
        updated = asyncio.run(appmod.update_entry(str(occurrence["_id"]), appmod.EntryIn(
            person_id="test-candidate", name="Test Candidate", ward="Ward 1",
            day=occurrence["day"], type="Door to Door", type_display="Door to Door",
            week_key=occurrence["week_key"], week_label=occurrence["week_label"],
            activity_date=occurrence["activity_date"],
            start_time="10:00", end_time="13:00", venue="Changed Venue",
        )))
        self.assertEqual(updated["start_time"], "10:00")
        self.assertEqual(updated["venue"], "Changed Venue")
        # The other two occurrences are untouched.
        others = [d for d in self.entries.docs if str(d["_id"]) != str(occurrence["_id"])]
        self.assertEqual(len(others), 2)
        for o in others:
            self.assertEqual(o["venue"], "Ward 7 Main Road")

    def test_editing_campaign_occurrence_to_a_date_outside_the_campaign_is_rejected(self):
        asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], self._repeat_body()))
        occurrence = self.entries.docs[0]
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.update_entry(str(occurrence["_id"]), appmod.EntryIn(
                person_id="test-candidate", name="Test Candidate", ward="Ward 1",
                day=occurrence["day"], type="Door to Door", type_display="Door to Door",
                week_key=occurrence["week_key"], week_label=occurrence["week_label"],
                activity_date="2026-10-05",  # one day past the campaign's end_date
                start_time="10:00", end_time="13:00", venue="Changed Venue",
            )))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(self.entries.docs[0]["activity_date"], occurrence["activity_date"])

    def test_editing_a_plain_non_campaign_entry_still_enforces_the_week_window(self):
        # Regression: the campaign branch in entry_doc_from_body must never
        # leak into ordinary entries — this must still fail exactly as it
        # did before Phase 2 existed.
        entry_id = ObjectId()
        self.entries.docs = [{
            "_id": entry_id, "person_id": "test-candidate", "name": "Test Candidate",
            "ward": "Ward 1", "day": "mon", "type": "Door to Door", "type_display": "Door to Door",
            "notes": None, "week_key": "2020-01-05", "week_label": "irrelevant",
            "submitted_at": "2020-01-01T00:00:00+00:00",
        }]
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.update_entry(str(entry_id), appmod.EntryIn(
                person_id="test-candidate", name="Test Candidate", ward="Ward 1",
                day="mon", type="Door to Door", type_display="Door to Door",
                week_key="2020-01-05", week_label="irrelevant",
                activity_date="2020-01-06", start_time="10:00", end_time="13:00", venue="X",
            )))
        self.assertEqual(exc.exception.status_code, 400)

    def test_generated_occurrence_independently_deletable(self):
        asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], self._repeat_body()))
        self.assertEqual(len(self.entries.docs), 3)
        occurrence_id = str(self.entries.docs[0]["_id"])
        result = asyncio.run(appmod.delete_entry(occurrence_id, "test-candidate"))
        self.assertEqual(result, {"deleted": True})
        self.assertEqual(len(self.entries.docs), 2)

    # ---- list ----

    def test_list_campaign_activities_returns_them_chronologically(self):
        asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], self._repeat_body()))
        listed = asyncio.run(appmod.list_campaign_activities(self.campaign["id"]))
        self.assertEqual(len(listed), 3)
        dates = [e["activity_date"] for e in listed]
        self.assertEqual(dates, sorted(dates))

    def test_list_campaign_activities_empty_for_unused_campaign(self):
        other = asyncio.run(appmod.create_campaign(appmod.CampaignIn(
            person_id="second-candidate", name="Untouched Campaign",
            start_date="2026-09-14", end_date="2026-10-04",
        )))
        listed = asyncio.run(appmod.list_campaign_activities(other["id"]))
        self.assertEqual(listed, [])

    # ---- archived campaign guard ----

    def test_single_activity_creation_rejected_for_archived_campaign(self):
        asyncio.run(appmod.archive_campaign(self.campaign["id"], "test-candidate"))
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign_activity(self.campaign["id"], self._single_body()))
        self.assertEqual(exc.exception.status_code, 409)
        self.assertEqual(len(self.entries.docs), 0)

    def test_recurring_creation_rejected_for_archived_campaign(self):
        asyncio.run(appmod.archive_campaign(self.campaign["id"], "test-candidate"))
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], self._repeat_body()))
        self.assertEqual(exc.exception.status_code, 409)
        self.assertEqual(len(self.entries.docs), 0)

    def test_existing_campaign_activities_remain_readable_after_archive(self):
        asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], self._repeat_body()))
        self.assertEqual(len(self.entries.docs), 3)
        asyncio.run(appmod.archive_campaign(self.campaign["id"], "test-candidate"))
        listed = asyncio.run(appmod.list_campaign_activities(self.campaign["id"]))
        self.assertEqual(len(listed), 3)
        dates = sorted(e["activity_date"] for e in listed)
        self.assertEqual(dates, ["2026-09-19", "2026-09-26", "2026-10-03"])

    def test_archiving_does_not_delete_existing_activities(self):
        asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], self._repeat_body()))
        before = copy.deepcopy(self.entries.docs)
        asyncio.run(appmod.archive_campaign(self.campaign["id"], "test-candidate"))
        self.assertEqual(self.entries.docs, before)
        self.assertEqual(len(self.entries.docs), 3)


@unittest.skipUnless(HAS_API_DEPS, "FastAPI dependencies are not installed")
class ExistingActivitiesUnaffectedByCampaignsTests(unittest.TestCase):
    """Historical activities predate campaign_id entirely — they must remain
    valid, unmodified, and correctly served without ever being rewritten."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
        os.environ.setdefault("ADMIN_PIN", "1234")
        os.environ.setdefault("JWT_SECRET", "local-test-secret")
        global appmod
        import main as appmod

    def setUp(self):
        self.original_entries_col = appmod.entries_col
        self.original_roster_col = appmod.roster_col
        self.original_campaigns_col = appmod.campaigns_col
        self.entries = FakeCollection()
        self.roster = FakeCollection()
        self.campaigns = FakeCollection()
        appmod.entries_col = self.entries
        appmod.roster_col = self.roster
        appmod.campaigns_col = self.campaigns

    def tearDown(self):
        appmod.entries_col = self.original_entries_col
        appmod.roster_col = self.original_roster_col
        appmod.campaigns_col = self.original_campaigns_col

    def test_historical_entry_with_no_campaign_id_key_reads_back_unmodified(self):
        entry_id = ObjectId()
        self.entries.docs = [entry_doc(_id=entry_id, type_display="Door to Door", week_key="2026-08-30", day="mon")]
        self.assertNotIn("campaign_id", self.entries.docs[0])
        report = asyncio.run(appmod.admin_all(True))
        self.assertEqual(len(report["entries"]), 1)
        self.assertEqual(report["entries"][0]["type_display"], "Door to Door")
        self.assertNotIn("campaign_id", self.entries.docs[0], "reading must never write campaign_id onto the stored document")

    def test_admin_reassign_person_still_works_unrelated_to_campaigns(self):
        entry_id = ObjectId()
        self.roster.docs = [{"_id": ObjectId(), "name": "Cecilia Anne Auld (CLLR)", "ward": "Ward 4", "name_slug": "cecilia-anne-auld-cllr"}]
        self.entries.docs = [entry_doc(_id=entry_id, type_display="Door to Door", week_key="2026-08-30", day="mon")]
        result = asyncio.run(appmod.admin_reassign_entry_person(
            str(entry_id), appmod.ReassignPersonIn(name="Cecilia Anne Auld (CLLR)"), True,
        ))
        self.assertEqual(result["person_id"], "cecilia-anne-auld-cllr")

    def test_creating_a_campaign_does_not_change_any_existing_entry_document(self):
        self.entries.docs = [entry_doc(type_display="Door to Door", week_key="2026-08-30", day="mon")]
        before = copy.deepcopy(self.entries.docs)
        self.roster.docs = [{"_id": ObjectId(), "name": "Test Candidate", "ward": "Ward 1", "name_slug": "test-candidate"}]
        asyncio.run(appmod.create_campaign(appmod.CampaignIn(
            person_id="test-candidate", name="Ward 13 Canvassing Drive",
            start_date="2026-09-14", end_date="2026-10-04",
        )))
        self.assertEqual(self.entries.docs, before)


@unittest.skipUnless(HAS_API_DEPS, "FastAPI dependencies are not installed")
class CampaignPastEndDateTests(unittest.TestCase):
    """Phase 5: a brand-new campaign whose end date has already completely
    passed is rejected; editing an existing historical campaign never is."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
        os.environ.setdefault("ADMIN_PIN", "1234")
        os.environ.setdefault("JWT_SECRET", "local-test-secret")
        global appmod
        import main as appmod

    def setUp(self):
        self.original_entries_col = appmod.entries_col
        self.original_roster_col = appmod.roster_col
        self.original_campaigns_col = appmod.campaigns_col
        self.entries = FakeCollection()
        self.roster = FakeCollection()
        self.campaigns = FakeCollection()
        self.roster.docs = [
            {"_id": ObjectId(), "name": "Test Candidate", "ward": "Ward 1", "name_slug": "test-candidate"},
        ]
        appmod.entries_col = self.entries
        appmod.roster_col = self.roster
        appmod.campaigns_col = self.campaigns
        self.today = appmod.sast_today()

    def tearDown(self):
        appmod.entries_col = self.original_entries_col
        appmod.roster_col = self.original_roster_col
        appmod.campaigns_col = self.original_campaigns_col

    def _body(self, **overrides):
        kwargs = dict(person_id="test-candidate", name="Drive")
        kwargs.update(overrides)
        return appmod.CampaignIn(**kwargs)

    def test_end_yesterday_rejected(self):
        yesterday = (self.today - appmod.timedelta(days=1)).isoformat()
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_campaign(self._body(start_date=yesterday, end_date=yesterday)))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.campaigns.docs), 0)

    def test_end_today_allowed(self):
        today = self.today.isoformat()
        result = asyncio.run(appmod.create_campaign(self._body(start_date=today, end_date=today)))
        self.assertEqual(result["end_date"], today)

    def test_start_in_past_end_in_future_allowed(self):
        start = (self.today - appmod.timedelta(days=5)).isoformat()
        end = (self.today + appmod.timedelta(days=5)).isoformat()
        result = asyncio.run(appmod.create_campaign(self._body(start_date=start, end_date=end)))
        self.assertEqual(result["start_date"], start)
        self.assertEqual(result["status"], "active")

    def test_future_campaign_allowed(self):
        start = (self.today + appmod.timedelta(days=10)).isoformat()
        end = (self.today + appmod.timedelta(days=20)).isoformat()
        result = asyncio.run(appmod.create_campaign(self._body(start_date=start, end_date=end)))
        self.assertEqual(result["status"], "planned")

    def test_historical_existing_campaign_remains_readable(self):
        old_end = (self.today - appmod.timedelta(days=100)).isoformat()
        old_start = (self.today - appmod.timedelta(days=110)).isoformat()
        campaign_id = ObjectId()
        self.campaigns.docs = [{
            "_id": campaign_id, "person_id": "test-candidate", "name": "Old Drive",
            "start_date": old_start, "end_date": old_end,
            "created_at": "2020-01-01T00:00:00+00:00", "archived_at": None,
        }]
        fetched = asyncio.run(appmod.get_campaign(str(campaign_id)))
        self.assertEqual(fetched["name"], "Old Drive")
        self.assertEqual(fetched["status"], "completed")

    def test_editing_existing_historical_campaign_not_blocked_by_past_end_date(self):
        # The past-end-date guard is create-only — renaming (or otherwise
        # editing, within its own existing dates) an existing historical
        # campaign must never be blocked merely because today has since
        # moved past its end date.
        old_end = (self.today - appmod.timedelta(days=100)).isoformat()
        old_start = (self.today - appmod.timedelta(days=110)).isoformat()
        campaign_id = ObjectId()
        self.campaigns.docs = [{
            "_id": campaign_id, "person_id": "test-candidate", "name": "Old Drive",
            "start_date": old_start, "end_date": old_end,
            "created_at": "2020-01-01T00:00:00+00:00", "archived_at": None,
        }]
        updated = asyncio.run(appmod.update_campaign(str(campaign_id), self._body(
            name="Renamed Old Drive", start_date=old_start, end_date=old_end,
        )))
        self.assertEqual(updated["name"], "Renamed Old Drive")


@unittest.skipUnless(HAS_API_DEPS, "FastAPI dependencies are not installed")
class CampaignDateEditSafetyTests(unittest.TestCase):
    """Phase 5: editing a campaign's dates must never silently exclude an
    activity that already exists inside it; archiving freezes the campaign
    itself (not just new activities) from further candidate edits."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
        os.environ.setdefault("ADMIN_PIN", "1234")
        os.environ.setdefault("JWT_SECRET", "local-test-secret")
        global appmod
        import main as appmod

    def setUp(self):
        self.original_entries_col = appmod.entries_col
        self.original_roster_col = appmod.roster_col
        self.original_campaigns_col = appmod.campaigns_col
        self.entries = FakeCollection()
        self.roster = FakeCollection()
        self.campaigns = FakeCollection()
        self.roster.docs = [
            {"_id": ObjectId(), "name": "Test Candidate", "ward": "Ward 1", "name_slug": "test-candidate"},
        ]
        appmod.entries_col = self.entries
        appmod.roster_col = self.roster
        appmod.campaigns_col = self.campaigns
        self.campaign = asyncio.run(appmod.create_campaign(appmod.CampaignIn(
            person_id="test-candidate", name="Ward 13 Canvassing Drive",
            start_date="2026-09-01", end_date="2026-09-21",
        )))
        asyncio.run(appmod.create_campaign_activity(self.campaign["id"], appmod.CampaignActivityIn(
            person_id="test-candidate", activity_date="2026-09-18",
            type="Door to Door", type_display="Door to Door",
            start_time="09:00", end_time="12:00", venue="Hall",
        )))

    def tearDown(self):
        appmod.entries_col = self.original_entries_col
        appmod.roster_col = self.original_roster_col
        appmod.campaigns_col = self.original_campaigns_col

    def _campaign_body(self, **overrides):
        kwargs = dict(
            person_id="test-candidate", name="Ward 13 Canvassing Drive",
            start_date="2026-09-01", end_date="2026-09-21",
        )
        kwargs.update(overrides)
        return appmod.CampaignIn(**kwargs)

    def test_valid_date_edit_works(self):
        updated = asyncio.run(appmod.update_campaign(self.campaign["id"], self._campaign_body(end_date="2026-09-25")))
        self.assertEqual(updated["end_date"], "2026-09-25")

    def test_rename_works(self):
        updated = asyncio.run(appmod.update_campaign(self.campaign["id"], self._campaign_body(name="Renamed Drive")))
        self.assertEqual(updated["name"], "Renamed Drive")

    def test_42_day_maximum_still_enforced_on_edit(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.update_campaign(self.campaign["id"], self._campaign_body(
                start_date="2026-09-01", end_date="2026-10-13",  # 43 inclusive days
            )))
        self.assertEqual(exc.exception.status_code, 400)

    def test_end_before_start_rejected_on_edit(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.update_campaign(self.campaign["id"], self._campaign_body(
                start_date="2026-09-20", end_date="2026-09-10",
            )))
        self.assertEqual(exc.exception.status_code, 400)

    def test_date_edit_excluding_existing_activity_rejected(self):
        # The linked activity is on 2026-09-18; shrinking the range to end
        # 2026-09-15 would exclude it.
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.update_campaign(self.campaign["id"], self._campaign_body(end_date="2026-09-15")))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(self.campaigns.docs[0]["end_date"], "2026-09-21", "a rejected edit must not partially apply")

    def test_rejected_date_edit_does_not_alter_linked_activity(self):
        before = copy.deepcopy(self.entries.docs)
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.update_campaign(self.campaign["id"], self._campaign_body(end_date="2026-09-15")))
        self.assertEqual(self.entries.docs, before)

    def test_archived_campaign_cannot_be_edited(self):
        asyncio.run(appmod.archive_campaign(self.campaign["id"], "test-candidate"))
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.update_campaign(self.campaign["id"], self._campaign_body(name="Renamed")))
        self.assertEqual(exc.exception.status_code, 409)
        self.assertEqual(self.campaigns.docs[0]["name"], "Ward 13 Canvassing Drive")

    def test_archived_campaign_rejects_candidate_activity_edit(self):
        occurrence = self.entries.docs[0]
        asyncio.run(appmod.archive_campaign(self.campaign["id"], "test-candidate"))
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.update_entry(str(occurrence["_id"]), appmod.EntryIn(
                person_id="test-candidate", name="Test Candidate", ward="Ward 1",
                day=occurrence["day"], type="Door to Door", type_display="Door to Door",
                week_key=occurrence["week_key"], week_label=occurrence["week_label"],
                activity_date=occurrence["activity_date"],
                start_time="10:00", end_time="13:00", venue="Changed Venue",
            )))
        self.assertEqual(exc.exception.status_code, 409)
        self.assertEqual(self.entries.docs[0]["venue"], "Hall", "the rejected edit must not partially apply")

    def test_archived_campaign_still_readable(self):
        asyncio.run(appmod.archive_campaign(self.campaign["id"], "test-candidate"))
        listed = asyncio.run(appmod.list_campaign_activities(self.campaign["id"]))
        self.assertEqual(len(listed), 1)


@unittest.skipUnless(HAS_API_DEPS, "FastAPI dependencies are not installed")
class RecurringOccurrenceCollisionTests(unittest.TestCase):
    """Phase 5: editing one occurrence in a recurring series onto a
    sibling occurrence's date must fail cleanly (never a raw 500 or a
    leaked Mongo/database detail), with no partial/corrupt write."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
        os.environ.setdefault("ADMIN_PIN", "1234")
        os.environ.setdefault("JWT_SECRET", "local-test-secret")
        global appmod
        import main as appmod

    def setUp(self):
        self.original_entries_col = appmod.entries_col
        self.original_roster_col = appmod.roster_col
        self.original_campaigns_col = appmod.campaigns_col
        self.entries = FakeCollection()
        self.roster = FakeCollection()
        self.campaigns = FakeCollection()
        self.roster.docs = [
            {"_id": ObjectId(), "name": "Test Candidate", "ward": "Ward 1", "name_slug": "test-candidate"},
        ]
        appmod.entries_col = self.entries
        appmod.roster_col = self.roster
        appmod.campaigns_col = self.campaigns
        self.campaign = asyncio.run(appmod.create_campaign(appmod.CampaignIn(
            person_id="test-candidate", name="Ward 13 Canvassing Drive",
            start_date="2026-09-14", end_date="2026-10-04",
        )))
        asyncio.run(appmod.create_campaign_activity_repeat(self.campaign["id"], appmod.CampaignActivityRepeatIn(
            person_id="test-candidate", weekday="sat",
            first_occurrence_date="2026-09-19", until="2026-10-03",
            type="Door to Door", type_display="Door to Door",
            start_time="09:00", end_time="12:00", venue="Ward 7 Main Road",
        )))

    def tearDown(self):
        appmod.entries_col = self.original_entries_col
        appmod.roster_col = self.original_roster_col
        appmod.campaigns_col = self.original_campaigns_col

    def _edit_body(self, occurrence, **overrides):
        kwargs = dict(
            person_id="test-candidate", name="Test Candidate", ward="Ward 1",
            day=occurrence["day"], type="Door to Door", type_display="Door to Door",
            week_key=occurrence["week_key"], week_label=occurrence["week_label"],
            activity_date=occurrence["activity_date"],
            start_time="09:00", end_time="12:00", venue="Ward 7 Main Road",
        )
        kwargs.update(overrides)
        return appmod.EntryIn(**kwargs)

    def test_editing_occurrence_onto_sibling_date_rejected_cleanly(self):
        occurrences = sorted(self.entries.docs, key=lambda d: d["activity_date"])
        first, second = occurrences[0], occurrences[1]
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.update_entry(
                str(first["_id"]), self._edit_body(first, activity_date=second["activity_date"])
            ))
        self.assertEqual(exc.exception.status_code, 409)
        detail = str(exc.exception.detail).lower()
        self.assertNotIn("mongo", detail)
        self.assertNotIn("e11000", detail)
        self.assertNotIn("duplicate key", detail)

    def test_no_partial_write_occurs_on_rejected_collision(self):
        occurrences = sorted(self.entries.docs, key=lambda d: d["activity_date"])
        first, second = occurrences[0], occurrences[1]
        before = copy.deepcopy(self.entries.docs)
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.update_entry(
                str(first["_id"]), self._edit_body(first, activity_date=second["activity_date"])
            ))
        self.assertEqual(self.entries.docs, before)

    def test_editing_occurrence_to_a_free_date_still_works(self):
        occurrence = sorted(self.entries.docs, key=lambda d: d["activity_date"])[0]
        updated = asyncio.run(appmod.update_entry(
            str(occurrence["_id"]), self._edit_body(occurrence, activity_date="2026-09-21")
        ))
        self.assertEqual(updated["activity_date"], "2026-09-21")

    def test_duplicate_key_error_backstop_converted_to_clean_409(self):
        # Race-condition backstop: even if the pre-check somehow missed a
        # concurrent collision, the unique-index error itself must never
        # leak as a raw 500 or expose Mongo/database details.
        occurrence = self.entries.docs[0]
        original_update = self.entries.find_one_and_update

        async def raising_update(*args, **kwargs):
            raise DuplicateKeyError(
                "E11000 duplicate key error collection: ward_tracker.entries "
                "index: recurrence_id_1_activity_date_1"
            )

        self.entries.find_one_and_update = raising_update
        try:
            with self.assertRaises(HTTPException) as exc:
                asyncio.run(appmod.update_entry(
                    str(occurrence["_id"]), self._edit_body(occurrence, activity_date="2026-09-21")
                ))
        finally:
            self.entries.find_one_and_update = original_update
        self.assertEqual(exc.exception.status_code, 409)
        detail = str(exc.exception.detail).lower()
        self.assertNotIn("e11000", detail)
        self.assertNotIn("mongo", detail)
        self.assertEqual(len(self.entries.docs), 3, "the backstop must not corrupt/lose any existing document")


@unittest.skipUnless(HAS_API_DEPS and HAS_TESTCLIENT, "FastAPI TestClient (httpx) is not installed")
class CampaignApiTests(unittest.TestCase):
    """Real HTTP round-trip through the actual ASGI app — a direct request
    that never touched a UI must still be rejected/accepted exactly like the
    entries endpoints, and existing entries endpoints must be provably
    unaffected by anything added in this phase."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
        os.environ.setdefault("ADMIN_PIN", "1234")
        os.environ.setdefault("JWT_SECRET", "local-test-secret")
        global appmod
        import main as appmod

    def setUp(self):
        self.original_entries_col = appmod.entries_col
        self.original_roster_col = appmod.roster_col
        self.original_campaigns_col = appmod.campaigns_col
        appmod.entries_col = FakeCollection()
        appmod.roster_col = FakeCollection()
        appmod.campaigns_col = FakeCollection()
        appmod.roster_col.docs = [
            {"_id": ObjectId(), "name": "Marnich Roets", "ward": "Ward 1", "name_slug": "marnich-roets"},
            {"_id": ObjectId(), "name": "Second Candidate", "ward": "Ward 2", "name_slug": "second-candidate"},
        ]
        self.client = TestClient(appmod.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        appmod.entries_col = self.original_entries_col
        appmod.roster_col = self.original_roster_col
        appmod.campaigns_col = self.original_campaigns_col

    def _create(self, **overrides):
        body = dict(
            person_id="marnich roets", name="Ward 13 Canvassing Drive",
            start_date="2026-09-14", end_date="2026-10-04",
        )
        body.update(overrides)
        return self.client.post("/api/campaigns", json=body)

    def test_direct_api_post_with_unregistered_identity_is_rejected(self):
        response = self._create(person_id="attacker-chosen-id")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(appmod.campaigns_col.docs), 0)

    def test_direct_api_post_with_registered_identity_succeeds_and_canonicalizes(self):
        response = self._create()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["person_id"], "marnich-roets")
        self.assertIn(body["status"], {"planned", "active", "completed"})

    def test_42_inclusive_calendar_days_accepted_over_http(self):
        response = self._create(start_date="2026-09-01", end_date="2026-10-12")
        self.assertEqual(response.status_code, 200)

    def test_43_inclusive_calendar_days_rejected_over_http(self):
        response = self._create(start_date="2026-09-01", end_date="2026-10-13")
        self.assertEqual(response.status_code, 400)

    def test_missing_dates_rejected_over_http(self):
        response = self.client.post("/api/campaigns", json=dict(
            person_id="marnich roets", name="Missing Dates",
        ))
        self.assertNotEqual(response.status_code, 200)

    def test_get_and_list_round_trip_over_http(self):
        created = self._create().json()
        fetched = self.client.get(f"/api/campaigns/{created['id']}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["name"], "Ward 13 Canvassing Drive")

        listed = self.client.get("/api/campaigns", params={"person_id": "marnich-roets"})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)

    def test_update_over_http(self):
        created = self._create().json()
        response = self.client.put(f"/api/campaigns/{created['id']}", json=dict(
            person_id="marnich roets", name="Renamed Drive",
            start_date="2026-09-14", end_date="2026-10-04",
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Renamed Drive")

    def test_archive_over_http(self):
        created = self._create().json()
        archived = self.client.patch(
            f"/api/campaigns/{created['id']}/archive", params={"person_id": "marnich-roets"}
        )
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(archived.json()["status"], "archived")

    def test_delete_with_linked_activity_returns_409_over_http(self):
        created = self._create().json()
        appmod.entries_col.docs.append(entry_doc(type_display="Door to Door", week_key="2026-09-13", day="mon"))
        appmod.entries_col.docs[0]["campaign_id"] = created["id"]
        response = self.client.request(
            "DELETE", f"/api/campaigns/{created['id']}", params={"person_id": "marnich-roets"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(appmod.campaigns_col.docs), 1)

    def test_delete_with_no_linked_activity_succeeds_over_http(self):
        created = self._create().json()
        response = self.client.request(
            "DELETE", f"/api/campaigns/{created['id']}", params={"person_id": "marnich-roets"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(appmod.campaigns_col.docs), 0)

    # ---- ownership (A-G): a second roster person must never mutate this
    # campaign merely by knowing its id, over real HTTP requests ----

    def test_A_owner_can_update_their_own_campaign_over_http(self):
        created = self._create().json()
        response = self.client.put(f"/api/campaigns/{created['id']}", json=dict(
            person_id="marnich roets", name="Renamed by Owner",
            start_date="2026-09-14", end_date="2026-10-04",
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Renamed by Owner")

    def test_B_different_roster_person_cannot_update_it_over_http(self):
        created = self._create().json()
        before = copy.deepcopy(appmod.campaigns_col.docs[0])
        response = self.client.put(f"/api/campaigns/{created['id']}", json=dict(
            person_id="second candidate", name="Hijacked",
            start_date="2026-09-14", end_date="2026-10-04",
        ))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(appmod.campaigns_col.docs[0], before)

    def test_C_different_roster_person_cannot_archive_it_over_http(self):
        created = self._create().json()
        before = copy.deepcopy(appmod.campaigns_col.docs[0])
        response = self.client.patch(
            f"/api/campaigns/{created['id']}/archive", params={"person_id": "second-candidate"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(appmod.campaigns_col.docs[0], before)
        self.assertIsNone(appmod.campaigns_col.docs[0]["archived_at"])

    def test_D_different_roster_person_cannot_delete_it_over_http(self):
        created = self._create().json()
        response = self.client.request(
            "DELETE", f"/api/campaigns/{created['id']}", params={"person_id": "second-candidate"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(appmod.campaigns_col.docs), 1)

    def test_E_put_cannot_change_campaign_ownership_over_http(self):
        created = self._create().json()
        # Even the real owner cannot use PUT to hand the campaign to someone
        # else: person_id in the body only ever proves who is asking, it is
        # never accepted as "the new owner" — attempting it as a different
        # identity is rejected as a mutation by a non-owner (see test B),
        # and there is no field/flow that reassigns person_id at all.
        response = self.client.put(f"/api/campaigns/{created['id']}", json=dict(
            person_id="marnich roets", name="Still Owned By Marnich",
            start_date="2026-09-14", end_date="2026-10-04",
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["person_id"], "marnich-roets")
        self.assertEqual(appmod.campaigns_col.docs[0]["person_id"], "marnich-roets")

    def test_F_failed_ownership_attempts_leave_the_campaign_document_unchanged(self):
        created = self._create().json()
        before = copy.deepcopy(appmod.campaigns_col.docs[0])
        self.client.put(f"/api/campaigns/{created['id']}", json=dict(
            person_id="second candidate", name="Hijacked",
            start_date="2026-09-14", end_date="2026-10-04",
        ))
        self.client.patch(f"/api/campaigns/{created['id']}/archive", params={"person_id": "second-candidate"})
        self.client.request("DELETE", f"/api/campaigns/{created['id']}", params={"person_id": "second-candidate"})
        self.assertEqual(appmod.campaigns_col.docs[0], before)

    def test_G_failed_ownership_attempts_leave_all_entry_documents_unchanged(self):
        created = self._create().json()
        appmod.entries_col.docs.append(entry_doc(type_display="Door to Door", week_key="2026-09-13", day="mon"))
        appmod.entries_col.docs[0]["campaign_id"] = created["id"]
        before = copy.deepcopy(appmod.entries_col.docs)
        self.client.put(f"/api/campaigns/{created['id']}", json=dict(
            person_id="second candidate", name="Hijacked",
            start_date="2026-09-14", end_date="2026-10-04",
        ))
        self.client.patch(f"/api/campaigns/{created['id']}/archive", params={"person_id": "second-candidate"})
        self.client.request("DELETE", f"/api/campaigns/{created['id']}", params={"person_id": "second-candidate"})
        self.assertEqual(appmod.entries_col.docs, before)

    def test_existing_entries_write_window_rule_is_untouched_by_this_phase(self):
        # A plain /api/entries create still goes through the unmodified
        # current/next-week-only rule — campaigns introduce no shared code
        # path that could have loosened it.
        response = self.client.post("/api/entries", json=dict(
            person_id="x", name="marnich roets", ward="Ward 1", day="mon",
            type="Door to Door", type_display="Door to Door", notes=None,
            week_key="2020-01-01", week_label="irrelevant", activity_date="2020-01-02",
            start_time="09:00", end_time="10:00", venue="Ward office",
        ))
        self.assertEqual(response.status_code, 400)

    def test_single_campaign_activity_over_http(self):
        created = self._create().json()
        response = self.client.post(f"/api/campaigns/{created['id']}/activities", json=dict(
            person_id="marnich roets", activity_date="2026-09-19",
            type="Door to Door", type_display="Door to Door",
            start_time="09:00", end_time="12:00", venue="Ward office",
        ))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["activity_date"], "2026-09-19")
        listed = self.client.get(f"/api/campaigns/{created['id']}/activities")
        self.assertEqual(len(listed.json()), 1)

    def test_single_campaign_activity_rejects_non_owner_over_http(self):
        created = self._create().json()
        response = self.client.post(f"/api/campaigns/{created['id']}/activities", json=dict(
            person_id="second candidate", activity_date="2026-09-19",
            type="Door to Door", type_display="Door to Door",
        ))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(appmod.entries_col.docs), 0)

    def test_repeat_campaign_activity_over_http(self):
        created = self._create().json()  # 2026-09-14 .. 2026-10-04
        response = self.client.post(f"/api/campaigns/{created['id']}/activities/repeat", json=dict(
            person_id="marnich roets", weekday="sat",
            first_occurrence_date="2026-09-19", until="2026-10-03",
            type="Door to Door", type_display="Door to Door",
            start_time="09:00", end_time="12:00", venue="Ward office",
        ))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["created"]), 3)
        listed = self.client.get(f"/api/campaigns/{created['id']}/activities")
        self.assertEqual(len(listed.json()), 3)

    def test_repeat_campaign_activity_retry_is_idempotent_over_http(self):
        created = self._create().json()
        payload = dict(
            person_id="marnich roets", weekday="sat",
            first_occurrence_date="2026-09-19", until="2026-10-03",
            type="Door to Door", type_display="Door to Door",
            start_time="09:00", end_time="12:00", venue="Ward office",
        )
        first = self.client.post(f"/api/campaigns/{created['id']}/activities/repeat", json=payload)
        second = self.client.post(f"/api/campaigns/{created['id']}/activities/repeat", json=payload)
        self.assertEqual(first.json()["recurrence_id"], second.json()["recurrence_id"])
        self.assertEqual(second.json()["created"], [])
        listed = self.client.get(f"/api/campaigns/{created['id']}/activities")
        self.assertEqual(len(listed.json()), 3)

    def test_existing_entry_gains_a_null_campaign_id_through_the_entryout_model(self):
        # admin_all/admin_report return raw dicts with no response_model, so a
        # historical document with no campaign_id key stays exactly as-is
        # there (see the next test). EntryOut is the schema declared as
        # "future compatible" in this phase — exercise it via an endpoint
        # that actually applies it (reassign-person), not admin_all.
        created = self.client.post("/api/entries", json=dict(
            person_id="x", name="marnich roets", ward="Ward 1", day="mon",
            type="Door to Door", type_display="Door to Door", notes=None,
            week_key="2026-08-30", week_label="31 Aug - 6 Sep", activity_date="2026-08-31",
            start_time="09:00", end_time="10:00", venue="Ward office",
        )).json()
        self.assertNotIn("campaign_id", appmod.entries_col.docs[0])
        token = appmod.make_admin_token()
        response = self.client.patch(
            f"/api/admin/entries/{created['id']}/reassign-person",
            json={"name": "Marnich Roets"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("campaign_id", response.json())
        self.assertIsNone(response.json()["campaign_id"])

    def test_admin_all_leaves_historical_document_without_a_campaign_id_key_untouched(self):
        self.client.post("/api/entries", json=dict(
            person_id="x", name="marnich roets", ward="Ward 1", day="mon",
            type="Door to Door", type_display="Door to Door", notes=None,
            week_key="2026-08-30", week_label="31 Aug - 6 Sep", activity_date="2026-08-31",
            start_time="09:00", end_time="10:00", venue="Ward office",
        ))
        self.assertNotIn("campaign_id", appmod.entries_col.docs[0])
        token = appmod.make_admin_token()
        response = self.client.get("/api/admin/all", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 200)
        entries = response.json()["entries"]
        self.assertEqual(len(entries), 1)
        self.assertNotIn("campaign_id", entries[0])


class AsyncCursor:
    def __init__(self, docs):
        self.docs = [copy.deepcopy(doc) for doc in docs]

    def __aiter__(self):
        self._iter = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def create_index(self, *args, **kwargs):
        return "idx"

    def find(self, query=None, projection=None):
        query = query or {}
        docs = [doc for doc in self.docs if matches(doc, query)]
        return AsyncCursor(docs)

    async def find_one(self, query):
        for doc in self.docs:
            if matches(doc, query):
                return copy.deepcopy(doc)
        return None

    async def insert_one(self, doc):
        stored = copy.deepcopy(doc)
        stored["_id"] = ObjectId()
        self.docs.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def find_one_and_update(self, query, update, return_document=True):
        for doc in self.docs:
            if matches(doc, query):
                doc.update(copy.deepcopy(update.get("$set", {})))
                return copy.deepcopy(doc)
        return None

    async def delete_one(self, query):
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not matches(doc, query)]
        return SimpleNamespace(deleted_count=before - len(self.docs))


def matches(doc, query):
    return all(doc.get(key) == value for key, value in query.items())


def entry_doc(
    _id=None,
    type_display="Door to Door",
    type=None,
    week_key="2026-08-30",
    day="mon",
    start_time=None,
    end_time=None,
    venue=None,
    is_custom_activity=None,
):
    doc = {
        "_id": _id or ObjectId(),
        "person_id": "test-candidate",
        "name": "Test Candidate",
        "ward": "Ward 1",
        "day": day,
        "type": type or type_display,
        "type_display": type_display,
        "notes": None,
        "week_key": week_key,
        "week_label": "31 Aug - 6 Sep",
        "submitted_at": "2026-09-01T10:00:00+00:00",
    }
    if start_time is not None:
        doc["start_time"] = start_time
    if end_time is not None:
        doc["end_time"] = end_time
    if venue is not None:
        doc["venue"] = venue
    if is_custom_activity is not None:
        doc["is_custom_activity"] = is_custom_activity
    return doc


if __name__ == "__main__":
    unittest.main()
